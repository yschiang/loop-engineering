"""Evidence commands (design §2, §7; T3.1): `evidence red` (worker), `evidence green`
(coordinator) and the diagnostic replay G1 runs on contradictory evidence.

Only policy commands run (`workflow.yaml` `evidence.commands`); `{junit_out}` is the only
placeholder and loopctl fills it. Every run is bounded by
`min(limits.evidence_call_s, budget.remaining)` in its own process group, and is an
`activities` record of kind `evidence` from start to end (design §10).

State (top-level field owned here):
  evidence[<kind>-<n>] = {id, n, kind: red|green|replay, command_id, command, producer,
      status: running|passed|test_failed|not_behavior_failure|collection_error|no_junit|
              inconsistent|evidence_timeout,
      exit, timed_out, cause: call_limit|active_budget, limit_s, elapsed_s, started_at,
      ended_at, failing, passing, raw {stdout, stderr: {$object}}, raw_digest {stdout, stderr},
      junit {$object}|None, junit_digest,
      red:    attempt, task_id, batch_id, finding_ids, worktree, snapshot {commit, tree, parent, ref}
      green:  head, checkout, checkout_head, removed, results_seen
      replay: of, head (the Red's snapshot), checkout, checkout_head, removed, reproduced}
A call-limit timeout blocks the feature (`evidence_timeout:<id>`); a timeout caused by the
active budget does not (the expiry path is T7.1's). A checkout that cannot be removed is
listed as `checkout_not_removed:<path>`. Tools are imported inside the effectful functions,
so the state core (`loopctl.next` → `loopctl.gates`) never loads subprocess.
"""

import difflib
import secrets
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from loopctl import assignments, budget, clock, store
from loopctl.observe import Rejected, block, commit, limit, now_iso, owned, policy

State = dict[str, Any]
TOOL = "loopctl"
GREEN_COMMAND = "suite"  # Red and Green share it (workflow.yaml)
# A failure of one of these types is an environment or typo failure, not missing behaviour.
NOT_BEHAVIOUR = ("ImportError", "ModuleNotFoundError", "SyntaxError", "IndentationError", "TabError")


def producer(command: str) -> dict[str, str]:
    return {"tool": TOOL, "command": command}


# --- pure: classification of a run (G1 re-derives it from the stored raw junit) -------------


def _exception_type(element: ET.Element) -> str:
    head = (element.get("message") or "").split(":", 1)[0].strip()
    if head in NOT_BEHAVIOUR:
        return head
    last = (element.text or "").rstrip().rsplit("\n", 1)[-1]  # "tests/x.py:3: AssertionError"
    return last.rsplit(": ", 1)[-1].strip() if ": " in last else ""


def _cases(junit: str) -> dict[str, str] | None:
    try:
        root = ET.fromstring(junit)
    except ET.ParseError:
        return None
    cases: dict[str, str] = {}
    for case in root.iter("testcase"):
        cid = f"{case.get('classname', '')}::{case.get('name', '')}"
        failure, error = case.find("failure"), case.find("error")
        if failure is not None:
            cases[cid] = "not_behaviour" if _exception_type(failure) in NOT_BEHAVIOUR else "failure"
        elif error is not None:
            cases[cid] = "error"
        elif case.find("skipped") is not None:
            cases[cid] = "skipped"
        else:
            cases[cid] = "passed"
    return cases


def classify(exit_code: int | None, junit: str | None) -> dict[str, Any]:
    """A Red is `test_failed`: pytest exit 1 with at least one behaviour failure. A syntax,
    import or collection error is not a Red (tasks.md: ImportError 不算)."""
    if exit_code is None:
        return {"status": "evidence_timeout", "failing": [], "passing": []}
    cases = _cases(junit) if junit is not None else None
    if cases is None:
        status = "passed" if exit_code == 0 else "no_junit" if exit_code == 1 else "collection_error"
        return {"status": status, "failing": [], "passing": []}
    failing = sorted(c for c, kind in cases.items() if kind == "failure")
    broken = [c for c, kind in cases.items() if kind in ("not_behaviour", "error")]
    passing = sorted(c for c, kind in cases.items() if kind == "passed")
    if exit_code == 0:
        status = "inconsistent" if failing or broken else "passed"
    elif exit_code == 1:
        status = "test_failed" if failing else "not_behavior_failure" if broken else "inconsistent"
    else:
        status = "collection_error"
    return {"status": status, "failing": failing, "passing": passing}


def added_lines(old: str, new: str) -> set[str]:
    """Non-blank lines `new` adds to `old` (a test delta)."""
    a, b = old.splitlines(), new.splitlines()
    out: set[str] = set()
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out |= {line.rstrip() for line in b[j1:j2] if line.strip()}
    return out


def completed(state: State) -> list[tuple[int, str, dict[str, Any]]]:
    """Attempts with an imported, completed result, in dispatch order."""
    found = [(a["n"], k, a) for k, a in (state.get("attempts") or {}).items()
             if (a.get("result") or {}).get("status") == "completed"]
    return sorted(found)


def records(state: State, kind: str) -> list[dict[str, Any]]:
    return sorted((e for e in (state.get("evidence") or {}).values() if e.get("kind") == kind), key=lambda e: e["n"])


# --- policy command and time bound --------------------------------------------------------


def bound_policy(state: State) -> dict[str, Any]:
    """The registered policy only: a `workflow.yaml` in the cwd may be the worker's own copy."""
    if not ((state.get("versions") or {}).get("policy") or {}).get("content"):
        raise Rejected("policy_not_registered", 3)
    return policy(state)


def command(pol: dict[str, Any], command_id: str) -> list[str]:
    commands = (pol.get("evidence") or {}).get("commands") or {}
    spec = commands.get(command_id) if isinstance(commands, dict) else None
    argv = spec.get("argv") if isinstance(spec, dict) else None
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
        raise Rejected("unknown_command_id", 1, command_id=command_id, allowed=sorted(commands))
    return list(argv)


def time_limit(state: State, pol: dict[str, Any]) -> tuple[float, str]:
    """min(limits.evidence_call_s, budget.remaining) and which of the two it is."""
    call = limit(pol, "evidence_call_s", 900)
    left = budget.remaining(state, clock.now()).total_seconds()
    if left < call:
        if left <= 0:
            raise Rejected("active_budget_exhausted", 3, remaining_s=left)
        return round(left, 3), "active_budget"
    return call, "call_limit"


def _run(feature: str, record: dict[str, Any], argv: list[str], cwd: str, bound: tuple[float, str]) -> dict[str, Any]:
    """Allocate the evidence id and the activity start, run once, record the end."""
    from loopctl.tools import evidence as tools

    limit_s, cause = bound
    at, box = now_iso(), {}

    def start(s: State) -> State:
        evidence = s.setdefault("evidence", {})
        n = len(evidence) + 1
        eid = f"{record['kind']}-{n}"
        box["id"] = eid
        evidence[eid] = {**record, "id": eid, "n": n, "status": "running", "started_at": at, "limit_s": limit_s,
                         "cause": cause}
        s.setdefault("activities", []).append(
            {"kind": "evidence", "attempt": record.get("attempt"), "evidence": eid, "start": at, "end": None}
        )
        return s

    commit(feature, f"evidence:{record['kind']}:start@{at}:{secrets.token_hex(6)}", start)
    eid = box["id"]
    with tempfile.TemporaryDirectory(prefix="loopctl-junit-") as tmp:
        junit_path = Path(tmp) / "junit.xml"
        run = tools.run_command([a.replace("{junit_out}", str(junit_path)) for a in argv], cwd, limit_s)
        junit = junit_path.read_bytes() if junit_path.is_file() else None
    ended = now_iso()
    outcome = classify(None if run["timed_out"] else run["exit"], junit.decode(errors="replace") if junit else None)
    stdout, stderr = store.put_object(run["stdout"]), store.put_object(run["stderr"])
    fields = {
        **outcome, "exit": run["exit"], "timed_out": run["timed_out"], "elapsed_s": run["elapsed_s"],
        "ended_at": ended, "raw": {"stdout": store.object_ref(stdout), "stderr": store.object_ref(stderr)},
        "raw_digest": {"stdout": stdout, "stderr": stderr},
        "junit": store.object_ref(store.put_object(junit)) if junit is not None else None,
        "junit_digest": store.digest(junit) if junit is not None else None,
    }

    def finish(s: State) -> State:
        s["evidence"][eid].update(fields)
        for activity in s.get("activities", []):
            if activity.get("evidence") == eid and not activity["end"]:
                activity["end"] = ended
        if run["timed_out"] and cause == "call_limit":
            block(s, f"evidence_timeout:{eid}")  # an active-budget timeout goes the expiry path (T7.1)
        return s

    commit(feature, f"evidence:{eid}:end", finish)
    return dict(store.load(feature)[1]["evidence"][eid])


# --- evidence red (worker) ------------------------------------------------------------------


def red(feature: str, attempt: str, command_id: str, findings: list[str], cwd: Path) -> dict[str, Any]:
    """Capture a Red in the active attempt's own worktree. No owner token: this is the one
    loopctl command the implementer profile allows; the attempt and its worktree bind it."""
    from loopctl.tools import evidence as tools

    _, st = store.load(feature)
    a = (st.get("attempts") or {}).get(attempt)
    if a is None:
        raise Rejected("unknown_attempt", attempt=attempt)
    if a.get("end"):
        raise Rejected("attempt_ended", attempt=attempt)
    if a.get("result"):
        raise Rejected("result_already_imported", attempt=attempt)
    asg = st["assignments"][attempt]
    findings = list(dict.fromkeys(findings))
    if asg.get("batch_id") is None and findings:
        raise Rejected("findings_outside_a_correction", attempt=attempt)
    if asg.get("batch_id") is not None and not findings:
        raise Rejected("findings_required", attempt=attempt, finding_ids=asg["finding_ids"])
    if unknown := [f for f in findings if f not in asg["finding_ids"]]:
        raise Rejected("finding_not_in_assignment", findings=unknown, finding_ids=asg["finding_ids"])
    pol = bound_policy(st)
    argv = command(pol, command_id)
    read_s = limit(pol, "read_call_s", 30)
    top = tools.toplevel(cwd, read_s)
    if top is None or Path(top).resolve() != Path(asg["worktree"]).resolve():
        raise Rejected("not_in_attempt_worktree", cwd=str(cwd), worktree=asg["worktree"])
    bound = time_limit(st, pol)
    try:
        snap = tools.snapshot(asg["worktree"], f"refs/loopctl/snapshots/{feature}/{secrets.token_hex(8)}",
                              f"loopctl red snapshot of {attempt}", read_s)
    except tools.GitError as e:
        raise Rejected("snapshot_failed", detail=str(e)) from e
    record = {
        "kind": "red", "command_id": command_id, "command": argv, "producer": producer("evidence red"),
        "attempt": attempt, "task_id": asg["task_id"], "batch_id": asg["batch_id"], "finding_ids": findings,
        "worktree": str(Path(top).resolve()), "snapshot": snap,
    }
    done = _run(feature, record, argv, asg["worktree"], bound)
    if done["status"] == "evidence_timeout":
        raise Rejected("evidence_timeout", 3, evidence=done)
    return {"evidence": done}


# --- clean checkouts: evidence green and replay (coordinator) -------------------------------


def workspace(state: State) -> dict[str, Any]:
    doc = assignments.plan_doc(state)
    if doc is None:
        raise Rejected("plan_tasks_unusable")
    return dict(doc["workspace"])


def feature_head(state: State, pol: dict[str, Any]) -> str:
    """H: the feature branch as the source repository has it now."""
    from loopctl.tools import evidence as tools

    ws = workspace(state)
    head = tools.rev_parse(ws["source"], f"refs/heads/{ws['branch']}", limit(pol, "read_call_s", 30))
    if head is None:
        raise Rejected("head_unreadable", 3, branch=ws["branch"])
    return head


def _in_checkout(feature: str, state: State, pol: dict[str, Any], rev: str, record: dict[str, Any],
                 extra: Any = None) -> dict[str, Any]:
    """Run the policy command in a fresh `worktree add --detach` checkout of `rev` under
    $LOOPCTL_HOME, never in the Implementer worktree; remove it in `finally` (design §7)."""
    from loopctl.tools import evidence as tools

    repo = workspace(state)["source"]
    read_s = limit(pol, "read_call_s", 30)
    argv = command(pol, record["command_id"])
    bound = time_limit(state, pol)
    checkout = store.home() / "checkouts" / feature / secrets.token_hex(8)
    try:
        tools.add_checkout(repo, checkout, rev, read_s)
    except tools.GitError as e:
        raise Rejected("checkout_failed", detail=str(e)) from e
    done: dict[str, Any] | None = None
    try:
        at = tools.rev_parse(str(checkout), "HEAD", read_s)
        done = _run(feature, {**record, "command": argv, "checkout": str(checkout), "checkout_head": at},
                    argv, str(checkout), bound)
    finally:
        removed = tools.remove_checkout(repo, checkout, read_s)
        eid = done["id"] if done else None
        more = extra(done) if (extra and done) else {}

        def cleanup(s: State) -> State:
            if eid:
                s["evidence"][eid].update({"removed": removed, **more})
            if not removed:
                block(s, f"checkout_not_removed:{checkout}")
            return s

        commit(feature, f"evidence:{eid or checkout.name}:cleanup", cleanup)
    return dict(store.load(feature)[1]["evidence"][done["id"]])


def green(feature: str, token: str | None) -> dict[str, Any]:
    _, st = owned(feature, token)
    pol = bound_policy(st)
    head = feature_head(st, pol)
    record = {"kind": "green", "command_id": GREEN_COMMAND, "producer": producer("evidence green"), "head": head,
              "results_seen": len(completed(st))}
    done = _in_checkout(feature, st, pol, head, record)
    if done["status"] == "evidence_timeout":
        raise Rejected("evidence_timeout", 3, evidence=done)
    return {"evidence": done}


def replay(feature: str, red_id: str) -> dict[str, Any]:
    """Diagnostic only (design §7): re-run a Red's own command on its snapshot. It never
    becomes a Red; G1 reads `reproduced` to continue or block."""
    _, st = store.load(feature)
    pol = bound_policy(st)
    original = st["evidence"][red_id]
    snap = original["snapshot"]["commit"]
    record = {"kind": "replay", "of": red_id, "command_id": original["command_id"], "producer": producer("replay"),
              "head": snap}

    def reproduced(done: dict[str, Any]) -> dict[str, Any]:
        same = done["status"] == "test_failed" and set(original["failing"]) <= set(done["failing"])
        return {"reproduced": same}

    return _in_checkout(feature, st, pol, snap, record, reproduced)
