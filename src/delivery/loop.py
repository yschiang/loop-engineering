"""Controller main loop: one persisted transition per step (design §3, §9.2, §11)."""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delivery.budget import ACTIVE_LIMIT_SECONDS, active_seconds, close_activity, open_activity
from delivery.controller import authorize_dispatch, dependency_ready, reassess
from delivery.correction import check_result, dispatch_batch, ready_for_batch, record_recheck
from delivery.decisions import may_dispatch_implementation
from delivery.events import EventLog, flush_pending
from delivery.findings import close, import_review, open_blocking, submit_fix
from delivery.gates import decide_pass, evaluate_g1, evaluate_g2, evaluate_g3, observe_new_version
from delivery.integration import integrate
from delivery.outbox import advance, new_dispatch_op, new_pr_op
from delivery.publication import register_publication
from delivery.results import import_result
from delivery.runner import evidence_record, run_evidence
from delivery.store import Store
from delivery.versions import version_key

# Step outcomes after which nothing more can happen without an external event or a person.
RESTING = frozenset({"awaiting_approval", "blocked", "pass", "waiting_result", "waiting_ci", "idle",
                     "waiting_dependency"})


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
    authority: Any = None  # delivery.authority.Authority owning this feature
    implementer_isolation: dict[str, Any] | None = None
    installed_skills: dict[str, str] | None = None
    clock: Any = None  # () -> seconds; wall clock when None


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
              bindings: dict[str, str], approval: dict[str, Any] | None, ticket: str | None = None,
              dependencies: list[dict[str, Any]] | None = None, skills: dict[str, str] | None = None,
              carried_active_seconds: float = 0) -> dict[str, Any]:
    tip = _git(ctx.ctl_repo, "rev-parse", f"refs/heads/{ctx.branch}")
    base = _git(ctx.ctl_repo, "rev-parse", "refs/heads/main")
    versions = {"repo_id": str(ctx.ctl_repo), "pr_number": None, "head_sha": tip, "base_ref": "main",
                "base_tip": base, "merge_base": _git(ctx.ctl_repo, "merge-base", base, tip), "bindings": bindings,
                "skills": dict(skills or {}), "controller_version": "0.1.0"}
    k = version_key(versions)
    state: dict[str, Any] = {
        "schema_version": 1, "run_id": run_id, "feature_key": feature_key, "plan_version": plan_version,
        "approval": approval, "phase": "implementing" if approval else "awaiting_approval",
        "next_action": {"kind": "step", "detail": ""}, "versions": versions,
        "tasks": [{**t, "status": "pending", "lease": None, "attempts": [],
                   "change_class": t.get("change_class", "behavior"), "red": []} for t in tasks],
        "gates": {g: {"gate": g, "status": "missing", "version_key": k, "evidence": []} for g in ("g1", "g2", "g3")},
        "ticket": ticket, "dependencies": list(dependencies or []), "waits": [],
        "registry": {"seq": 0, "findings": {}},
        "budget": {"correction_rounds_used": 0, "carried_seconds": carried_active_seconds, "activities": {},
                   "extensions": []}, "batches": [],
        "disputes": {}, "operations": {}, "imported_results": {}, "blockers": [], "pass_history": [],
        "current_pass": None, "acceptance": {"history": []}, "decisions": [], "pending_history": [],
        "reviews": [], "integration": {"branch": ctx.branch, "tip": tip, "log": []}}
    if approval is not None:
        state["approval"] = {**approval, "plan_producer": "implementer"}
    store = Store(ctx.run_dir)
    store.commit(state)
    return state


def _now_s(ctx: Context) -> float:
    return float(ctx.clock()) if ctx.clock is not None else time.time()


def _is_ancestor(ctx: Context) -> Any:
    return lambda a, b: subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=ctx.ctl_repo,
                                       capture_output=True, check=False).returncode == 0


def _dispatch_guard(ctx: Context, store: Store, state: dict[str, Any], unit: dict[str, Any], role: str) -> str | None:
    """Every dispatch passes the approved-contract checks first; None means dispatch may proceed."""
    if ctx.authority is None or ctx.authority.active_run_id() != state["run_id"]:
        return _block(store, state, "authority_not_held", run_id=state["run_id"])
    if not state.get("ticket"):
        return _block(store, state, "no_ticket")
    if state["versions"]["bindings"].get("plan") != state["plan_version"]:
        state["phase"] = "awaiting_approval"
        store.commit(state)
        return "awaiting_approval"
    installed = ctx.installed_skills or {}
    drift = sorted(n for n, d in state["versions"]["skills"].items() if installed.get(n) != d)
    if drift:
        return _block(store, state, "skill_pin_mismatch", skills=drift)
    if role == "implementer" and (ctx.implementer_isolation or {}).get("status") != "verified":
        return _block(store, state, "implementer_isolation_unverified")
    b = state["budget"]
    limit = ACTIVE_LIMIT_SECONDS + sum(e["seconds"] for e in b.get("extensions", []))
    budget_ok = b.get("carried_seconds", 0) + active_seconds(b, _now_s(ctx)) < limit
    if not budget_ok:
        return _block(store, state, "active_budget_exhausted", limit=limit)
    waits = []
    for dep in state["dependencies"]:
        ready = dependency_ready({**dep, **ctx.github.read_dependency(dep["feature"])}, _is_ancestor(ctx),
                                 state["versions"]["base_tip"])
        if not ready["ready"]:
            waits.append({"kind": "dependency", "feature": dep["feature"], "wait": ready["wait"]})
    if waits:
        state["waits"] = waits
        store.commit(state)
        return "waiting_dependency"
    state["waits"] = []
    if role == "implementer":
        verdict = authorize_dispatch(state, {"task_id": unit["task_id"], "via": "controller",
                                             "requested_by": "implementer"}, budget_ok, not waits)
        if not verdict["accepted"]:
            return _block(store, state, "dispatch_refused", reason=verdict["reason"])
    return None


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
    open_activity(state["budget"], attempt_id, role, _now_s(ctx))
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
        return _block(store, state, "dispatch_failed", op_id=op["op_id"], op_state=op["state"])
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
    if att["attempt_id"] in state["budget"].get("activities", {}):
        close_activity(state["budget"], att["attempt_id"], _now_s(ctx))
    if out.status != "imported":
        return _block(store, state, f"result_{out.status}", attempt_id=att["attempt_id"], reasons=out.reasons)
    store.commit(state)
    return "result_imported"


def _verify_red(ctx: Context, store: Store, att: dict[str, Any], rec: dict[str, Any], scope: list[str]) -> dict[str, Any]:
    """Controller-side checks: raw-output digest, red ref fetched from the attempt, replay at the snapshot."""
    inbox = ctx.run_dir / "inbox" / att["attempt_id"]
    raw = inbox / "red.stdout"
    digest_ok = raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest() == rec["digests"].get("stdout")
    # Copy the worker's raw output into controller-owned durable blobs before anything references it.
    raw_refs = {name: store.put_blob((inbox / f"red.{name}").read_bytes()).ref
                for name in ("stdout", "stderr") if (inbox / f"red.{name}").exists()}
    snap = rec.get("snapshot") or {}
    replay: dict[str, Any] = {"status": "not_run", "failing_ids": []}
    if snap.get("ref"):
        _git(ctx.ctl_repo, "fetch", "-q", att["clone"], f"+{snap['ref']}:{snap['ref']}")
        wt = ctx.run_dir / "verify" / f"replay-{snap['commit'][:12]}"
        _git(ctx.ctl_repo, "worktree", "add", "-q", "--detach", str(wt), snap["commit"])
        try:
            again = run_evidence("replay_check", rec["task_id"], rec["attempt_id"], list(rec["argv"]), str(wt),
                                 snap["commit"], scope, ctx.policy["excludes"])
            replay = {"status": again.status, "failing_ids": list(again.failing_ids),
                      "raw": {"stdout": store.put_blob(again.stdout).ref, "stderr": store.put_blob(again.stderr).ref}}
        finally:
            _git(ctx.ctl_repo, "worktree", "remove", "--force", str(wt), check=False)
    ref = store.put_blob(json.dumps(rec, sort_keys=True).encode()).ref
    return {"kind": rec["kind"], "status": rec["status"], "producer": rec["producer"], "digest_ok": digest_ok,
            "failing_ids": rec["failing_ids"], "snapshot": {"commit": snap.get("commit"), "parent": snap.get("parent")},
            "replay": replay, "record": ref, "raw": raw_refs}


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
        refused = _dispatch_guard(ctx, store, state, task, "implementer")
        if refused is not None:
            return refused
        batch = next((b for b in state["batches"] if b["batch_id"] == task.get("batch_id")), None)
        return _new_attempt(ctx, store, state, task, "implementer",
                            {"batch": batch["items"] if batch else {}, "g1_return": task.get("g1_return")})
    att = task["attempts"][-1]
    waiting = _drive_attempt(ctx, store, state, att)
    if waiting is not None:
        return waiting
    task = next(t for t in state["tasks"] if t["task_id"] == task["task_id"])
    result = _load_blob(store, state["imported_results"][att["attempt_id"]])
    if result["execution_status"] != "succeeded":
        return _block(store, state, "task_failed", task_id=task["task_id"])
    if task.get("batch_id") and not task.get("responses_applied"):
        batch = next(b for b in state["batches"] if b["batch_id"] == task["batch_id"])
        missing = check_result(batch, result)
        if missing:
            return _block(store, state, "incomplete_correction_result", missing=missing)
        for fid, resp in result["responses"].items():
            if resp["kind"] == "fix_submitted":
                submit_fix(state["registry"], fid, resp["commit"], [state["imported_results"][att["attempt_id"]]])
        task["responses_applied"] = True
    op_id = f"op-integrate-{att['attempt_id']}"
    if op_id not in state["operations"]:
        # Persist the intended effect first (design §11); the ref move happens in the next step.
        state["operations"][op_id] = {"op_id": op_id, "kind": "integrate", "state": "pending",
                                      "task_id": task["task_id"], "attempt_id": att["attempt_id"],
                                      "clone": att["clone"], "t0": att["t0"], "scope": task["scope"]}
        store.commit(state)
        return "integrate_registered"
    op = state["operations"][op_id]
    if op["state"] in ("pending", "in_flight"):
        op["state"] = "in_flight"
        store.commit(state)
        out = integrate(str(ctx.ctl_repo), state, task["task_id"], att["attempt_id"], att["clone"], att["t0"],
                        task["scope"], ctx.branch)  # idempotent: re-run after a crash converges on the ref
        op.update(state="succeeded" if out["status"] == "succeeded" else "blocked", result=out)
        if out["status"] != "succeeded":
            return _block(store, state, "integration_" + out["status"], reason=out.get("reason"))
        store.commit(state)
        return "integrate_applied"
    task["red"] = task["red"] + [_verify_red(ctx, store, att, rec, task["scope"])
                                 for rec in result.get("evidence", []) if rec["kind"] == "red"]
    task["status"] = "succeeded"
    state["integration"]["tip"] = op["result"]["head"]
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
    rec: dict[str, Any] = {**evidence_record(ev),
                           "raw": {"stdout": store.put_blob(ev.stdout).ref, "stderr": store.put_blob(ev.stderr).ref}}
    ref = store.put_blob(json.dumps(rec, sort_keys=True).encode()).ref
    status = "passed" if ev.status == "passed" else "failed"
    return {"head": head, "status": status, "producer": {"tool": "controller-runner"},
            "passing_ids": list(ev.passing_ids), "failing_ids": list(ev.failing_ids)}, ref


NOT_AT_HEAD = "red tests not passing at head"


def _g1_fixable(a: dict[str, Any], green: dict[str, Any]) -> bool:
    """Fixable: the integrated code is wrong (regression, red tests still failing at head).
    Missing, invalid or unreproducible historical Red cannot be repaired afterwards and blocks (D26)."""
    bad = [r for r in a["tasks"].values() if r["status"] != "passed"]
    if any(r["status"] != "failed" or any(NOT_AT_HEAD not in x for x in r["reasons"]) for r in bad):
        return False
    return green["status"] == "failed" or bool(bad)


def _return_to_producer(store: Store, state: dict[str, Any], a: dict[str, Any]) -> str:
    """Design §3: a fixable G1 gap goes back to the work unit that produced this head; no correction round."""
    producer_id = state["integration"]["log"][-1]["task_id"]
    task = next(t for t in state["tasks"] if t["task_id"] == producer_id)
    task.update(status="pending", lease=None, g1_return={"reasons": a["reasons"], "version_key": _key(state)})
    state["phase"] = "correcting" if task.get("batch_id") else "implementing"
    store.commit(state)
    return "g1_returned"


def _na_eligibility(ctx: Context, store: Store, state: dict[str, Any]) -> str | None:
    """N/A is never self-granted: controller pre-filter, then an independent reviewer bound to the diff (D26)."""
    for task in state["tasks"]:
        if task["change_class"] != "na_requested" or task.get("na"):
            continue
        entry = next(e for e in reversed(state["integration"]["log"]) if e["task_id"] == task["task_id"])
        diff = _git(ctx.ctl_repo, "diff", entry["from"], entry["to"])
        paths = _git(ctx.ctl_repo, "diff", "--name-only", entry["from"], entry["to"]).split()
        digest = "diff:" + hashlib.sha256(diff.encode()).hexdigest()
        task["diff_digest"] = digest
        nondoc = [p for p in paths if not any(fnmatch.fnmatch(p, g) for g in ctx.policy.get("na_doc_globs", []))]
        if nondoc:
            task["na"] = {"status": "rejected", "reason": f"prefilter: non-doc paths {nondoc}", "diff_digest": digest}
            store.commit(state)
            return "na_prefilter_rejected"
        unit = task.setdefault("na_review", {"task_id": f"na-{task['task_id']}", "scope": [], "attempts": [],
                                             "lease": None})
        if unit["lease"] is None:
            refused = _dispatch_guard(ctx, store, state, unit, "na_reviewer")
            if refused is not None:
                return refused
            return _new_attempt(ctx, store, state, unit, "na_reviewer",
                                {"diff_digest": digest, "diff_paths": paths, "na_task": task["task_id"],
                                 "na_reason": task.get("na_reason", "")})
        waiting = _drive_attempt(ctx, store, state, unit["attempts"][-1])
        if waiting is not None:
            return waiting
        task = next(t for t in state["tasks"] if t["task_id"] == task["task_id"])
        ref = state["imported_results"][task["na_review"]["attempts"][-1]["attempt_id"]]
        result = _load_blob(store, ref)
        status = result["eligibility"] if result.get("diff_digest") == digest else "rejected"
        task["na"] = {"status": status, "diff_digest": result.get("diff_digest"), "result": ref}
        store.commit(state)
        return "na_decided"
    return None


def _step_validate(ctx: Context, store: Store, state: dict[str, Any]) -> str:
    na_step = _na_eligibility(ctx, store, state)
    if na_step is not None and na_step != "na_prefilter_rejected":
        return na_step
    head = _git(ctx.ctl_repo, "rev-parse", f"refs/heads/{ctx.branch}")
    if state["versions"]["head_sha"] != head:
        reassess(state, {**state["versions"], "head_sha": head})
    green, ref = _green(ctx, store, state, head)
    tasks = [{"task_id": t["task_id"], "change_class": t["change_class"], "red": t["red"], "na": t.get("na"),
              "diff_digest": t.get("diff_digest")} for t in state["tasks"]]
    a = evaluate_g1(tasks, green, head, _is_ancestor(ctx))
    state["gates"]["g1"] = {**a, "gate": "g1", "version_key": _key(state), "evidence": [ref]}
    if a["status"] != "passed":
        if _g1_fixable(a, green):
            return _return_to_producer(store, state, a)
        return _block(store, state, "g1_not_passed", status=a["status"], reasons=a["reasons"])
    op_id = f"op-pr-{head[:12]}"
    if op_id not in state["operations"]:
        new_pr_op(state, op_id, ctx.branch, f"S1 delivery run {state['run_id']} head {head}", state["run_id"])
        store.commit(state)
    advance(store, state, op_id, github=ctx.github)
    op = state["operations"][op_id]
    if op["state"] != "succeeded":
        return _block(store, state, "pr_publication", op_id=op_id, op_state=op["state"])
    if state["versions"]["pr_number"] != op["result"]["number"]:
        reassess(state, {**state["versions"], "pr_number": op["result"]["number"]})
    state["phase"] = "checking"
    store.commit(state)
    return "g1_passed"


def _base_recheck(ctx: Context, store: Store, state: dict[str, Any], new_vs: dict[str, Any]) -> dict[str, Any]:
    """R-base: merge the unchanged head onto the new base and rerun the G1 commands on the merge result."""
    head, base = new_vs["head_sha"], new_vs["base_tip"]
    merged = subprocess.run(["git", "merge-tree", "--write-tree", base, head], cwd=ctx.ctl_repo,
                            capture_output=True, text=True, check=False)
    if merged.returncode != 0:
        return {"status": "failed", "reason": "base_conflict"}
    tree = merged.stdout.split()[0]
    merge = _git(ctx.ctl_repo, "commit-tree", tree, "-p", head, "-p", base, "-m", "delivery base recheck")
    green, ref = _green(ctx, store, state, merge)
    return {"status": green["status"], "evidence": [ref]}


def _reread(ctx: Context, store: Store, state: dict[str, Any]) -> str | None:
    """Re-read head/base/merge-base and every binding; any difference is handled before gates are trusted."""
    ext = ctx.github.read_versions(ctx.branch)
    vs = state["versions"]
    changed = {r: d for r, d in ext["bindings"].items() if vs["bindings"].get(r) != d}
    if changed:
        state["candidates"] = {r: {"content_digest": d, "observed_at": _now()} for r, d in changed.items()}
        observe_new_version(state, "contract-candidate", _now())
        state["phase"] = "awaiting_approval"
        store.commit(state)
        return "awaiting_approval"
    new_vs = {**vs, "head_sha": ext["head_sha"], "base_tip": ext["base_tip"], "merge_base": ext["merge_base"]}
    if version_key(new_vs) == version_key(vs):
        return None
    recheck = _base_recheck(ctx, store, state, new_vs) if new_vs["head_sha"] == vs["head_sha"] else None
    reassess(state, new_vs, base_recheck=recheck)
    if state["phase"] == "correcting":
        out = dispatch_batch(state, version_key(new_vs), open_blocking(state["registry"]), [], base_conflict=True)
        if not out["dispatched"]:
            state["phase"] = "blocked"
        else:
            add_fix_task(state, out["batch"])
    store.commit(state)
    return "versions_changed"


def add_fix_task(state: dict[str, Any], batch: dict[str, Any]) -> None:
    state["tasks"].append({"task_id": f"fix-{batch['batch_id']}", "batch_id": batch["batch_id"],
                           "scope": _scope(state), "ac_ids": [], "spec": None, "status": "pending", "lease": None,
                           "attempts": [], "change_class": "behavior", "red": []})


def _step_check(ctx: Context, store: Store, state: dict[str, Any]) -> str:
    moved = _reread(ctx, store, state)
    if moved is not None:
        return moved
    k, vs = _key(state), state["versions"]
    review = next((r for r in state["reviews"] if r["version_key"] == k), None)
    if review is None:
        refused = _dispatch_guard(ctx, store, state, {"task_id": "review"}, "reviewer")
        if refused is not None:
            return refused
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
        reported = import_review(state["registry"], {"result_id": ref, "findings": result.get("findings", [])}, k)
        if state["batches"]:
            last = state["batches"][-1]
            for fid in last["items"]["findings"]:  # each fixed finding was re-checked by this review
                record_recheck(state, fid, still_open=fid in reported, batch_id=last["batch_id"], result_id=ref)
        for c in result.get("closures", []):
            close(state["registry"], c["finding_id"], {"actor_kind": "reviewer", "result_id": ref, "version_key": k,
                                                       "reason": c["reason"], "evidence": [ref]}, k)
        review["findings_imported"] = True
        review["publication"] = register_publication(
            state, state["run_id"], {"result_id": ref, "review_id": review["task_id"], "verdict": result.get("verdict"),
                                     "version_key": k, "head": vs["head_sha"], "base": vs["base_tip"],
                                     "spec": vs["bindings"].get("plan", ""),
                                     "findings": [{**state["registry"]["findings"][fid], "id": fid}
                                                  for fid in state["registry"]["findings"]
                                                  if any(h["result_id"] == ref for h in
                                                         state["registry"]["findings"][fid].get("history", []))]})
        store.commit(state)
    for pub in review.get("publication", []):
        if state["operations"][pub]["state"] not in ("succeeded", "blocked"):
            advance(store, state, pub, github=ctx.github)  # publication state never changes the verdict
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
        def reread() -> str:
            ext = ctx.github.read_versions(ctx.branch)
            return version_key({**vs, "head_sha": ext["head_sha"], "base_tip": ext["base_tip"],
                                "merge_base": ext["merge_base"], "bindings": ext["bindings"]})

        decide_pass(state, k, blocking, reread=reread, now=_now())
        store.commit(state)
        return "pass" if state["current_pass"] else "reconcile"
    ci = g3["reasons"] if g3["status"] != "passed" else []
    out = dispatch_batch(state, k, blocking, ci)
    if not out["dispatched"]:
        state["phase"] = "blocked"
        store.commit(state)
        return "blocked"
    add_fix_task(state, out["batch"])
    state["phase"] = "correcting"
    store.commit(state)
    return "correction_dispatched"


def step(ctx: Context) -> str:
    """One transition, then its audit event (pending history → events.jsonl, deduplicated by ID)."""
    store = Store(ctx.run_dir)
    before = store.load().state.get("revision")
    result = _transition(ctx)
    after = store.load()
    if after.blocked or after.state.get("revision") == before:
        return result  # nothing changed: resting steps leave no history
    state = after.state
    state["pending_history"] = [*state.get("pending_history", []),
                                {"id": f"ev-{state['revision']}-{result}", "step": result, "phase": state["phase"],
                                 "at": _now()}]
    store.commit(state)
    flush_pending(store, EventLog(ctx.run_dir / "events.jsonl"))
    return result


def _transition(ctx: Context) -> str:
    """Load the persisted run, perform at most one transition, persist it; safe to call after any crash."""
    store = Store(ctx.run_dir)
    loaded = store.load()
    if loaded.blocked:
        return "blocked"
    state = loaded.state
    phase = state["phase"]
    if phase == "awaiting_approval":
        if state.get("contract_adopted"):
            state.pop("contract_adopted")
            state["phase"] = "validating"  # G1 is re-evaluated under the new contract, then a new review
            store.commit(state)
            return "contract_adopted"
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
    if phase == "ready_for_acceptance":
        return _reread(ctx, store, state) or "pass"  # a later change invalidates the Pass (AC-G18)
    return "idle"


def run_until_idle(ctx: Context, max_steps: int = 200) -> list[str]:
    trail: list[str] = []
    for _ in range(max_steps):
        trail.append(step(ctx))
        if trail[-1] in RESTING:
            return trail
    raise RuntimeError(f"no resting state after {max_steps} steps: {trail[-10:]}")
