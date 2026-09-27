"""`delivery` command line entry point (design §1). Commands call the core and persist real state."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

EXIT_UNAVAILABLE = 3  # an S2 adapter (runtime/GitHub) is required but not in this build

WORKFLOW_TEMPLATE = """schema_version: 1
repo: {github: yschiang/orca-delivery, base: main}
g1:
  commands: [{id: unit, run: [uv, run, pytest, -q, "--junitxml={junit}"]}]
snapshot: {exclude: [".env*", "*.pem", "*.key"]}
na: {doc_globs: ["docs/**", "**/*.md"]}
ci:
  required: [{name: test, app: github-actions, source: head}]
  allow_non_success: []
timeouts_min: {worker: 45, review: 30, ci: 30}
recurrence: {max_failed_rechecks: 2, block_on_reopen: true}
profiles:
  implementer: {runtime: opencode, provider: anthropic, model: claude-opus-5-5, sandbox: worker}
  reviewer: {runtime: opencode, provider: openai, model: null, sandbox: reviewer}
"""
AVAILABLE_RUNTIMES: frozenset[str] = frozenset()  # OpenCode/GitHub adapters are S2 (tasks 3.x/4.x)


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _unavailable(what: str) -> int:
    print(f"{what} adapter is not available in this build (S2); nothing external was attempted", file=sys.stderr)
    return EXIT_UNAVAILABLE


def _ctx(repo: Path, run_dir: Path, branch: str, attempts: Path) -> Any:
    from delivery.loop import Context

    return Context(run_dir=run_dir, ctl_repo=repo, attempts_root=attempts, branch=branch, runtime=None, github=None,
                   policy={}, isolation=None, sandbox_profile_digest=None)


def cmd_init(a: argparse.Namespace) -> int:
    path = Path(a.repo) / "workflow.yaml"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        print(f"{path} exists; not overwritten", file=sys.stderr)
        return 1
    with os.fdopen(fd, "w") as f:
        f.write(WORKFLOW_TEMPLATE)
    (Path(a.repo) / ".delivery" / "runs").mkdir(parents=True, exist_ok=True)
    print(json.dumps({"workflow": str(path)}))
    return 0


def _claim(a: argparse.Namespace, run_dir: Path) -> tuple[int | None, str]:
    """(exit code or None, authority status). An existing active run is resumed, never recreated."""
    from delivery.authority import Authority

    repo_id = a.repo_id or os.path.realpath(a.repo)
    out = Authority(Path(a.state_home), repo_id, a.feature).start(str(Path(a.repo).resolve()), str(run_dir),
                                                                  a.run_id)
    if out.status not in ("created", "resume"):
        print(json.dumps(out.__dict__), file=sys.stdout)
        print(f"start refused: {out.status}", file=sys.stderr)
        return 1, out.status
    if out.status == "resume":
        print(json.dumps({"status": "resume", "run_id": out.run_id, "run_dir": out.state_dir}))
        return 0, out.status
    return None, out.status


def cmd_start(a: argparse.Namespace) -> int:
    from delivery.loop import start_run

    repo = Path(a.repo).resolve()
    run_dir = repo / ".delivery" / "runs" / a.run_id
    code, _ = _claim(a, run_dir)
    if code is not None:
        return code
    if subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/heads/{a.branch}"], cwd=repo,
                      capture_output=True, check=False).returncode != 0:
        _git(repo, "branch", a.branch, "main")
    tasks = json.loads(Path(a.tasks).read_text())
    start_run(_ctx(repo, run_dir, a.branch, Path(a.state_home) / "attempts" / a.run_id), a.run_id, a.feature, tasks,
              a.plan_version, {"plan": a.plan_version}, None, ticket=a.feature)
    print(json.dumps({"status": "created", "run_dir": str(run_dir), "phase": "awaiting_approval"}))
    return 0


def cmd_adopt(a: argparse.Namespace) -> int:
    """Adopt imports the handed-over plan, tasks and versions, then routes by the facts (AC-O08/O09)."""
    from delivery.controller import route_intake
    from delivery.loop import start_run
    from delivery.store import Store

    repo = Path(a.repo).resolve()
    run_dir = repo / ".delivery" / "runs" / a.run_id
    code, _ = _claim(a, run_dir)
    if code is not None:
        return code
    facts = json.loads(Path(a.facts).read_text())
    routed = route_intake(facts)
    branch = facts.get("branch") or _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    plan = facts.get("plan_version", "")
    approval = facts.get("approval") if facts.get("d11") else None
    state = start_run(_ctx(repo, run_dir, branch, Path(a.state_home) / "attempts" / a.run_id), a.run_id,
                      a.feature, facts.get("tasks", []), plan, {"plan": plan, **facts.get("bindings", {})},
                      approval, ticket=a.feature)
    store = Store(run_dir)
    store.load()
    state.update(phase=routed["phase"], blockers=routed["blockers"],
                 adopted_from={"owner_handoff": facts["owner_handoff"], "facts_file": str(a.facts)})
    store.commit(state)
    print(json.dumps({"run_dir": str(run_dir), "phase": routed["phase"], "blockers": routed["blockers"]}))
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    from delivery.publication import render_status
    from delivery.store import Store

    loaded = Store(a.run_dir).load()
    print(render_status(loaded.state))
    if loaded.blocked:
        print("state not trusted: " + "; ".join(loaded.reasons))
        return 1
    return 0


def cmd_decide(a: argparse.Namespace) -> int:
    from delivery.decisions import DecisionInvalid, apply_decision
    from delivery.store import Store

    store = Store(a.run_dir)
    loaded = store.load()
    if loaded.blocked:
        print("state not trusted; decision not recorded", file=sys.stderr)
        return 1
    decision = {"decision_id": f"DEC-{uuid.uuid4().hex[:8]}", "kind": a.kind, "actor": a.actor,
                "actor_kind": a.actor_kind, "source": a.source, "reason": a.reason,
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(), "subject": json.loads(a.subject)}
    try:
        state = apply_decision(loaded.state, decision)
    except DecisionInvalid as e:
        print(f"decision rejected: {e}", file=sys.stderr)
        return 1
    store.commit(state)
    print(json.dumps({"decision_id": decision["decision_id"], "phase": state["phase"]}))
    return 0


def cmd_evidence(a: argparse.Namespace) -> int:
    from delivery.runner import evidence_record, run_evidence

    argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
    out = Path(a.out)
    names = [out / f"{a.kind}.{ext}" for ext in ("json", "stdout", "stderr")]
    existing = [str(n) for n in names if n.exists()]
    if existing:
        print(f"evidence exists; history is never overwritten: {existing}", file=sys.stderr)
        return 1
    ev = run_evidence(a.kind, a.task, a.attempt, argv, str(a.cwd), a.t0, a.scope.split(","), a.exclude)
    out.mkdir(parents=True, exist_ok=True)
    for path, data in zip(names, (json.dumps(evidence_record(ev), indent=2).encode(), ev.stdout, ev.stderr),
                          strict=True):
        with open(path, "xb") as f:  # exclusive create: a concurrent writer cannot replace it either
            f.write(data)
    print(json.dumps({"status": ev.status, "record": str(out / f"{a.kind}.json")}))
    return 1 if ev.status == "snapshot_refused" else 0


def cmd_submit(a: argparse.Namespace) -> int:
    from delivery.store import BlobConflict, Store

    raw = Path(a.file).read_bytes()
    if not isinstance(json.loads(raw), dict):
        print("result must be a JSON object", file=sys.stderr)
        return 1
    try:
        Store(Path(a.inbox)).put_blob(raw, name="result.json")
    except BlobConflict as e:
        print(f"result already submitted with different bytes: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"inbox": str(Path(a.inbox) / "result.json")}))
    return 0


def _reconcile_local(run_dir: Path) -> tuple[int, dict[str, Any]]:
    from delivery.events import EventLog, flush_pending
    from delivery.store import Store

    store = Store(run_dir)
    if store.load().blocked:
        print("state not trusted; nothing done", file=sys.stderr)
        return 1, {}
    if flush_pending(store, EventLog(run_dir / "events.jsonl")).blocked:
        print("history corrupt; blocked", file=sys.stderr)
        return 1, {}
    return 0, store.load().state


def cmd_reconcile(a: argparse.Namespace) -> int:
    code, _ = _reconcile_local(Path(a.run_dir))
    return code if code else _unavailable("GitHub (external version re-read)")


def cmd_resume(a: argparse.Namespace) -> int:
    code, state = _reconcile_local(Path(a.run_dir))
    if code:
        return code
    if state["phase"] in ("awaiting_approval", "blocked", "ready_for_acceptance"):
        print(json.dumps({"phase": state["phase"], "note": "resting; nothing to dispatch"}))
        return 0
    return _unavailable("runtime (dispatch)")


def cmd_preflight(a: argparse.Namespace) -> int:
    import yaml

    from delivery.sandbox import Boundary, Probe, run_suite

    policy = yaml.safe_load((Path(a.repo) / "workflow.yaml").read_text())
    profile = policy["profiles"][a.profile]
    runtime = {"name": profile["runtime"],
               "status": "available" if profile["runtime"] in AVAILABLE_RUNTIMES else "unavailable",
               "reason": "" if profile["runtime"] in AVAILABLE_RUNTIMES else "runtime adapters land in S2"}
    with tempfile.TemporaryDirectory() as t:
        root = Path(t).resolve()
        (root / "denied").mkdir()
        (root / "allowed").mkdir()
        b = Boundary(allow_write=(root / "allowed",), deny_write=(root / "denied",), deny_read=())
        probes = [Probe("write_denied", ("/bin/sh", "-c", f"echo x > {root}/denied/f"), "denied"),
                  Probe("write_allowed", ("/bin/sh", "-c", f"echo x > {root}/allowed/f"), "allowed")]
        rep = run_suite(b, probes, [p.name for p in probes])
    report = {"profile": a.profile, "runtime": runtime,
              "isolation": {"status": rep.status, "launcher": rep.launcher,
                            "note": "basic launcher probe only; full design 10.4 suite: tests/os"}}
    print(json.dumps(report))
    return 0 if runtime["status"] == "available" and rep.status == "verified" else EXIT_UNAVAILABLE


COMMANDS = {
    "init": ("write workflow.yaml and .delivery/ for a repo", cmd_init),
    "start": ("start a feature run under the feature authority", cmd_start),
    "adopt": ("adopt an existing feature after owner handoff", cmd_adopt),
    "status": ("show phase, gates, blockers and next action", cmd_status),
    "resume": ("reconcile, then continue dispatch (needs a runtime adapter)", cmd_resume),
    "decide": ("record a human decision (run outside worker sandboxes)", cmd_decide),
    "reconcile": ("recover history/results and re-read external versions", cmd_reconcile),
    "preflight": ("check the selected runtime/sandbox profile", cmd_preflight),
    "evidence": ("run a command and capture evidence", cmd_evidence),
    "submit-result": ("submit a worker result into its inbox (write-once)", cmd_submit),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delivery", description="Orca delivery controller")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    p = {name: sub.add_parser(name, help=help_text) for name, (help_text, _) in COMMANDS.items()}
    p["init"].add_argument("--repo", required=True)
    for name in ("start", "adopt"):
        for flag in ("--repo", "--feature", "--run-id", "--state-home"):
            p[name].add_argument(flag, required=True)
        p[name].add_argument("--repo-id")
    for flag in ("--branch", "--tasks", "--plan-version"):
        p["start"].add_argument(flag, required=True)
    p["adopt"].add_argument("--facts", required=True)
    for name in ("status", "resume", "decide", "reconcile"):
        p[name].add_argument("--run-dir", required=True, type=Path)
    for flag in ("--kind", "--actor", "--source", "--reason", "--subject"):
        p["decide"].add_argument(flag, required=True)
    p["decide"].add_argument("--actor-kind", default="human")
    p["preflight"].add_argument("--repo", required=True)
    p["preflight"].add_argument("--profile", required=True)
    ev = p["evidence"].add_subparsers(dest="evidence_cmd", required=True).add_parser("run")
    for flag in ("--kind", "--task", "--attempt", "--cwd", "--t0", "--scope", "--out"):
        ev.add_argument(flag, required=True)
    ev.add_argument("--exclude", action="append", default=[".env*", "*.pem", "*.key"])
    ev.add_argument("argv", nargs=argparse.REMAINDER)
    p["submit-result"].add_argument("--inbox", required=True)
    p["submit-result"].add_argument("--file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help()
        return 2
    handler: Any = COMMANDS[args.command][1]
    result: int = handler(args)
    return result
