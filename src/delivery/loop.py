"""Controller main loop: one persisted transition per step (design §3, §9.2, §11)."""

from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delivery.controller import reassess
from delivery.correction import check_result, dispatch_batch, ready_for_batch
from delivery.decisions import may_dispatch_implementation
from delivery.findings import close, import_review, open_blocking, submit_fix
from delivery.gates import decide_pass, evaluate_g1, evaluate_g2, evaluate_g3
from delivery.integration import integrate
from delivery.outbox import advance, new_dispatch_op, new_pr_op
from delivery.results import import_result
from delivery.runner import evidence_record, run_evidence
from delivery.store import Store
from delivery.versions import version_key

# Step outcomes after which nothing more can happen without an external event or a person.
RESTING = frozenset({"awaiting_approval", "blocked", "pass", "waiting_result", "waiting_ci", "idle"})


@dataclass
class Context:
    run_dir: Path
    ctl_repo: Path
    attempts_root: Path
    branch: str
    runtime: Any
    github: Any
    policy: dict[str, Any]
    isolation: dict[str, Any] | None
    sandbox_profile_digest: str | None


def _git(cwd: Path | str, *a: str, check: bool = True) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=check).stdout.strip()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _key(state: dict[str, Any]) -> str:
    return version_key(state["versions"])


def _block(store: Store, state: dict[str, Any], kind: str, **detail: Any) -> str:
    state["phase"] = "blocked"
    state["blockers"].append({"kind": kind, **detail})
    store.commit(state)
    return "blocked"


def _scope(state: dict[str, Any]) -> list[str]:
    return sorted({p for t in state["tasks"] for p in t["scope"]})


def start_run(ctx: Context, run_id: str, feature_key: str, tasks: list[dict[str, Any]], plan_version: str,
              bindings: dict[str, str], approval: dict[str, Any] | None) -> dict[str, Any]:
    tip = _git(ctx.ctl_repo, "rev-parse", f"refs/heads/{ctx.branch}")
    base = _git(ctx.ctl_repo, "rev-parse", "refs/heads/main")
    versions = {"repo_id": str(ctx.ctl_repo), "pr_number": None, "head_sha": tip, "base_ref": "main",
                "base_tip": base, "merge_base": _git(ctx.ctl_repo, "merge-base", base, tip), "bindings": bindings,
                "skills": {}, "controller_version": "0.1.0"}
    k = version_key(versions)
    state: dict[str, Any] = {
        "schema_version": 1, "run_id": run_id, "feature_key": feature_key, "plan_version": plan_version,
        "approval": approval, "phase": "implementing" if approval else "awaiting_approval",
        "next_action": {"kind": "step", "detail": ""}, "versions": versions,
        "tasks": [{**t, "status": "pending", "lease": None, "attempts": [], "change_class": "behavior", "red": []}
                  for t in tasks],
        "gates": {g: {"gate": g, "status": "missing", "version_key": k, "evidence": []} for g in ("g1", "g2", "g3")},
        "registry": {"seq": 0, "findings": {}}, "budget": {"correction_rounds_used": 0}, "batches": [],
        "disputes": {}, "operations": {}, "imported_results": {}, "blockers": [], "pass_history": [],
        "current_pass": None, "acceptance": {"history": []}, "decisions": [], "pending_history": [],
        "reviews": [], "integration": {"branch": ctx.branch, "tip": tip, "log": []}}
    if approval is not None:
        state["approval"] = {**approval, "plan_producer": "implementer"}
    store = Store(ctx.run_dir)
    store.commit(state)
    return state


def _new_attempt(ctx: Context, store: Store, state: dict[str, Any], unit: dict[str, Any], role: str,
                 extra: dict[str, Any]) -> str:
    attempt_id = f"{unit['task_id']}-a{len(unit['attempts']) + 1}"
    clone = ctx.attempts_root / attempt_id
    _git(ctx.attempts_root.parent, "clone", "-q", "--no-hardlinks", "--branch", ctx.branch, str(ctx.ctl_repo),
         str(clone))
    t0 = _git(clone, "rev-parse", "HEAD")
    inbox = ctx.run_dir / "inbox" / attempt_id
    inbox.mkdir(parents=True, exist_ok=True)
    assignment = {"run_id": state["run_id"], "task_id": unit["task_id"], "attempt_id": attempt_id, "role": role,
                  "clone_path": str(clone), "base_sha": t0, "scope": {"paths": unit["scope"]}, "inbox": str(inbox),
                  "g1_argv": ctx.policy["g1_argv"], "excludes": ctx.policy["excludes"],
                  "task": {"spec": unit.get("spec"), "ac_ids": unit.get("ac_ids", [])}, **extra}
    ref = store.put_blob(json.dumps(assignment, sort_keys=True).encode()).ref
    op_id = f"op-dispatch-{attempt_id}"
    new_dispatch_op(state, op_id, attempt_id, json.dumps(assignment))
    state["operations"][op_id]["role"] = role
    state["operations"][op_id]["sandbox_profile_digest"] = ctx.sandbox_profile_digest
    unit["lease"] = attempt_id
    unit["attempts"].append({"attempt_id": attempt_id, "clone": str(clone), "t0": t0, "assignment_ref": ref,
                             "op_id": op_id})
    store.commit(state)
    return "dispatch_registered"


def _load_blob(store: Store, ref: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(store.blob_path(ref).read_bytes())
    return body


def _drive_attempt(ctx: Context, store: Store, state: dict[str, Any], att: dict[str, Any]) -> str | None:
    """Advance dispatch and import the result; None once the result is imported."""
    op = state["operations"][att["op_id"]]
    if op["state"] in ("blocked", "fenced"):
        return _block(store, state, "dispatch_failed", op_id=op["op_id"], state=op["state"])
    if op["stage"] != "prompt_accepted":
        advance(store, state, op["op_id"], runtime=ctx.runtime)
        return "dispatch_advanced"
    if att["attempt_id"] in state["imported_results"]:
        return None
    inbox = ctx.run_dir / "inbox" / att["attempt_id"] / "result.json"
    if not inbox.exists():
        return "waiting_result"
    assignment = _load_blob(store, att["assignment_ref"])
    out = import_result(store, state, assignment, inbox)
    state.clear()
    state.update(out.state)
    if out.status != "imported":
        return _block(store, state, f"result_{out.status}", attempt_id=att["attempt_id"], reasons=out.reasons)
    store.commit(state)
    return "result_imported"


def _verify_red(ctx: Context, store: Store, att: dict[str, Any], rec: dict[str, Any], scope: list[str]) -> dict[str, Any]:
    """Controller-side checks: raw-output digest, red ref fetched from the attempt, replay at the snapshot."""
    inbox = ctx.run_dir / "inbox" / att["attempt_id"]
    raw = inbox / "red.stdout"
    digest_ok = raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest() == rec["digests"].get("stdout")
    snap = rec.get("snapshot") or {}
    replay: dict[str, Any] = {"status": "not_run", "failing_ids": []}
    if snap.get("ref"):
        _git(ctx.ctl_repo, "fetch", "-q", att["clone"], f"+{snap['ref']}:{snap['ref']}")
        wt = ctx.run_dir / "verify" / f"replay-{snap['commit'][:12]}"
        _git(ctx.ctl_repo, "worktree", "add", "-q", "--detach", str(wt), snap["commit"])
        try:
            again = run_evidence("replay_check", rec["task_id"], rec["attempt_id"], list(rec["argv"]), str(wt),
                                 snap["commit"], scope, ctx.policy["excludes"])
            replay = {"status": again.status, "failing_ids": list(again.failing_ids)}
        finally:
            _git(ctx.ctl_repo, "worktree", "remove", "--force", str(wt), check=False)
    ref = store.put_blob(json.dumps(rec, sort_keys=True).encode()).ref
    return {"kind": rec["kind"], "status": rec["status"], "producer": rec["producer"], "digest_ok": digest_ok,
            "failing_ids": rec["failing_ids"], "snapshot": {"commit": snap.get("commit"), "parent": snap.get("parent")},
            "replay": replay, "record": ref}


def _step_implement(ctx: Context, store: Store, state: dict[str, Any]) -> str:
    if not may_dispatch_implementation(state):
        state["phase"] = "awaiting_approval"
        store.commit(state)
        return "awaiting_approval"
    task = next((t for t in state["tasks"] if t["status"] != "succeeded"), None)
    if task is None:
        state["phase"] = "validating"
        store.commit(state)
        return "all_tasks_integrated"
    if task["lease"] is None:
        batch = next((b for b in state["batches"] if b["batch_id"] == task.get("batch_id")), None)
        return _new_attempt(ctx, store, state, task, "implementer",
                            {"batch": batch["items"] if batch else {}})
    att = task["attempts"][-1]
    waiting = _drive_attempt(ctx, store, state, att)
    if waiting is not None:
        return waiting
    task = next(t for t in state["tasks"] if t["task_id"] == task["task_id"])
    result = _load_blob(store, state["imported_results"][att["attempt_id"]])
    if result["execution_status"] != "succeeded":
        return _block(store, state, "task_failed", task_id=task["task_id"])
    if task.get("batch_id"):
        batch = next(b for b in state["batches"] if b["batch_id"] == task["batch_id"])
        missing = check_result(batch, result)
        if missing:
            return _block(store, state, "incomplete_correction_result", missing=missing)
        for fid, resp in result["responses"].items():
            if resp["kind"] == "fix_submitted":
                submit_fix(state["registry"], fid, resp["commit"], [state["imported_results"][att["attempt_id"]]])
    out = integrate(str(ctx.ctl_repo), state, task["task_id"], att["attempt_id"], att["clone"], att["t0"],
                    task["scope"], ctx.branch)
    if out["status"] != "succeeded":
        return _block(store, state, "integration_" + out["status"], reason=out.get("reason"))
    task["red"] = [_verify_red(ctx, store, att, rec, task["scope"]) for rec in result.get("evidence", [])
                   if rec["kind"] == "red"]
    task["status"] = "succeeded"
    state["integration"]["tip"] = out["head"]
    store.commit(state)
    return "integrated"


def _green(ctx: Context, store: Store, state: dict[str, Any], head: str) -> tuple[dict[str, Any], str]:
    wt = ctx.run_dir / "verify" / f"green-{head[:12]}"
    _git(ctx.ctl_repo, "worktree", "add", "-q", "--detach", str(wt), head)
    try:
        ev = run_evidence("green", "g1", "controller", list(ctx.policy["g1_argv"]), str(wt), head, _scope(state),
                          ctx.policy["excludes"])
    finally:
        _git(ctx.ctl_repo, "worktree", "remove", "--force", str(wt), check=False)
    rec = evidence_record(ev)
    ref = store.put_blob(json.dumps(rec, sort_keys=True).encode()).ref
    status = "passed" if ev.status == "passed" else "failed"
    return {"head": head, "status": status, "producer": {"tool": "controller-runner"},
            "passing_ids": list(ev.passing_ids), "failing_ids": list(ev.failing_ids)}, ref


def _step_validate(ctx: Context, store: Store, state: dict[str, Any]) -> str:
    head = _git(ctx.ctl_repo, "rev-parse", f"refs/heads/{ctx.branch}")
    if state["versions"]["head_sha"] != head:
        reassess(state, {**state["versions"], "head_sha": head})
    green, ref = _green(ctx, store, state, head)
    tasks = [{"task_id": t["task_id"], "change_class": t["change_class"], "red": t["red"]} for t in state["tasks"]]
    a = evaluate_g1(tasks, green, head,
                    lambda x, y: subprocess.run(["git", "merge-base", "--is-ancestor", x, y], cwd=ctx.ctl_repo,
                                                capture_output=True, check=False).returncode == 0)
    state["gates"]["g1"] = {**a, "gate": "g1", "version_key": _key(state), "evidence": [ref]}
    if a["status"] != "passed":
        return _block(store, state, "g1_not_passed", status=a["status"], reasons=a["reasons"])
    op_id = f"op-pr-{head[:12]}"
    if op_id not in state["operations"]:
        new_pr_op(state, op_id, ctx.branch, f"S1 delivery run {state['run_id']} head {head}", state["run_id"])
        store.commit(state)
    advance(store, state, op_id, github=ctx.github)
    op = state["operations"][op_id]
    if op["state"] != "succeeded":
        return _block(store, state, "pr_publication", op_id=op_id, state=op["state"])
    if state["versions"]["pr_number"] != op["result"]["number"]:
        reassess(state, {**state["versions"], "pr_number": op["result"]["number"]})
    state["phase"] = "checking"
    store.commit(state)
    return "g1_passed"


def _step_check(ctx: Context, store: Store, state: dict[str, Any]) -> str:
    k, vs = _key(state), state["versions"]
    review = next((r for r in state["reviews"] if r["version_key"] == k), None)
    if review is None:
        review = {"task_id": f"review-{len(state['reviews']) + 1}", "version_key": k, "scope": [], "attempts": [],
                  "lease": None}
        state["reviews"].append(review)
        contract = {x: vs[x] for x in ("head_sha", "base_tip", "bindings", "skills")}
        return _new_attempt(ctx, store, state, review, "reviewer", {"version_key": k, "contract": contract})
    att = review["attempts"][-1]
    waiting = _drive_attempt(ctx, store, state, att)
    if waiting is not None:
        return waiting
    review = next(r for r in state["reviews"] if r["version_key"] == k)
    ref = state["imported_results"][att["attempt_id"]]
    result = _load_blob(store, ref)
    if not review.get("findings_imported"):
        import_review(state["registry"], {"result_id": ref, "findings": result.get("findings", [])}, k)
        for c in result.get("closures", []):
            close(state["registry"], c["finding_id"], {"actor_kind": "reviewer", "result_id": ref, "version_key": k,
                                                       "reason": c["reason"], "evidence": [ref]}, k)
        review["findings_imported"] = True
    op = state["operations"][att["op_id"]]
    implementer_sessions = {o["session_id"] for o in state["operations"].values()
                            if o["kind"] == "dispatch" and o.get("role") == "implementer" and o["session_id"]}
    g2_in = {"dispatched_by": "controller", "role": "reviewer", "version_key": result.get("version_key"),
             "verdict": result.get("verdict"), "session_id": op["session_id"], "parent_session_id": None,
             "requested_model": ctx.policy["reviewer"]["model"], "actual_model": result["producer"]["actual_model"],
             "receipt_profile_digest": op.get("sandbox_profile_digest"), "read_contract": result.get("read_contract")}
    blocking = open_blocking(state["registry"])
    g2 = evaluate_g2(g2_in, vs, k, ctx.policy["reviewer"], ctx.isolation, implementer_sessions, blocking)
    g3 = evaluate_g3(ctx.policy["ci"], ctx.github.required_checks(), vs["head_sha"], vs["base_tip"], None,
                     ctx.github.list_checks(vs["head_sha"]))
    state["gates"]["g2"] = {**g2, "evidence": [ref]}
    state["gates"]["g3"] = {**g3, "version_key": k, "evidence": []}
    if g2["status"] == "unknown":
        return _block(store, state, "g2_unknown", reasons=g2["reasons"])
    if not ready_for_batch(g2, g3):
        store.commit(state)
        return "waiting_ci"
    if g2["status"] == g3["status"] == "passed":
        pr = vs["pr_number"]
        decide_pass(state, k, blocking,
                    reread=lambda: version_key({**vs, "head_sha": ctx.github.pr_head(pr)}), now=_now())
        store.commit(state)
        return "pass" if state["current_pass"] else "reconcile"
    ci = g3["reasons"] if g3["status"] != "passed" else []
    out = dispatch_batch(state, k, blocking, ci)
    if not out["dispatched"]:
        state["phase"] = "blocked"
        store.commit(state)
        return "blocked"
    batch = out["batch"]
    state["tasks"].append({"task_id": f"fix-{batch['batch_id']}", "batch_id": batch["batch_id"],
                           "scope": _scope(state), "ac_ids": [], "spec": None, "status": "pending", "lease": None,
                           "attempts": [], "change_class": "behavior", "red": []})
    state["phase"] = "correcting"
    store.commit(state)
    return "correction_dispatched"


def step(ctx: Context) -> str:
    """Load the persisted run, perform at most one transition, persist it; safe to call after any crash."""
    store = Store(ctx.run_dir)
    loaded = store.load()
    if loaded.blocked:
        return "blocked"
    state = loaded.state
    phase = state["phase"]
    if phase == "awaiting_approval":
        if may_dispatch_implementation(state):
            state["phase"] = "implementing"
            store.commit(state)
            return "approved"
        return "awaiting_approval"
    if phase in ("implementing", "correcting"):
        return _step_implement(ctx, store, state)
    if phase == "validating":
        return _step_validate(ctx, store, state)
    if phase == "checking":
        return _step_check(ctx, store, state)
    if phase == "blocked":
        return "blocked"
    return "pass" if phase == "ready_for_acceptance" else "idle"


def run_until_idle(ctx: Context, max_steps: int = 200) -> list[str]:
    trail: list[str] = []
    for _ in range(max_steps):
        trail.append(step(ctx))
        if trail[-1] in RESTING:
            return trail
    raise RuntimeError(f"no resting state after {max_steps} steps: {trail[-10:]}")
