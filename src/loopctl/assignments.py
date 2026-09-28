"""Assignments, worker dispatch routing, the common result envelope and `result import`
(design §4, §6, §8; T2.3). T5.1 only adds `review` / `correction` to BODY_VALIDATORS.

The approved plan is a native document; its machine-readable part is one fenced block:

    ```loopctl-plan
    workspace: {source: <abs path of the repo main checkout>, worktree: <abs path>, branch: <b>,
                base: <b>, herdr_session: <optional>}
    tasks:
      - {id: T1, acs: [{id: AC-1, verify: <method>}], scope: [<path or glob>, …]}
    ```

State (top-level fields owned here):
  assignments[attempt] = {attempt_id, task_id, batch_id, finding_ids, role, profile, worktree,
                          branch, base, head, pr, plan, digests, acs, scope, result_path, …}
  attempts[attempt]    = {n, task_id, role, handle: {herdr_session, pane, agent_name,
                          native_session_id, runtime}, poll_s, started_at, result, rejected,
                          conflicts, end}
Routing and validation here are pure; git and Herdr are reached only inside `op_spec` and
`import_result` (imported there), so `loopctl.next` stays free of subprocess.
"""

import fnmatch
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from loopctl import clock, observe, store, writes
from loopctl.observe import (
    Rejected,
    block,
    commit,
    limit,
    now_iso,
    owned,
    policy,
    settle,
    unblock,
)

State = dict[str, Any]
SCHEMA_VERSION = 1
ROLE = "implementer"
PLAN_BLOCK = re.compile(r"```loopctl-plan\n(.*?)```", re.DOTALL)
TASK_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
WORKSPACE_KEYS = ("source", "worktree", "branch", "base")


def human(blockers: list[str], kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": kinds or []}


def _write(kind: str, op_id: str) -> dict[str, Any]:
    return {"action": "write", "op": kind, "id": op_id}


def _observe(source: str, attempt: str) -> dict[str, Any]:
    return {"action": "observe", "source": source, "purpose": source, "read_key": f"{source}:{attempt}",
            "attempt": attempt}


# --- the approved plan's task list ---------------------------------------------------------


def _strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


def plan_doc(state: State) -> dict[str, Any] | None:
    """The workspace and task list of the registered plan, or None if unusable (no block, no
    tasks, a task without AC/verification or scope)."""
    plan = state.get("plan") or {}
    if not plan.get("content"):
        return None
    match = PLAN_BLOCK.search(store.get_object(plan["content"][store.OBJECT_KEY]).decode(errors="replace"))
    try:
        doc = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("workspace"), dict):
        return None
    ws, tasks = doc["workspace"], doc.get("tasks")
    if not all(isinstance(ws.get(k), str) and ws[k] for k in WORKSPACE_KEYS) or not isinstance(tasks, list) or not tasks:
        return None
    if not (Path(ws["source"]).is_absolute() and Path(ws["worktree"]).is_absolute()):
        return None  # machine paths: never resolved against whatever cwd `next` runs in
    if ws.get("herdr_session") is not None and not isinstance(ws["herdr_session"], str):
        return None
    ids = []
    for task in tasks:
        acs = task.get("acs") if isinstance(task, dict) else None
        if not (
            isinstance(task, dict) and isinstance(task.get("id"), str) and TASK_ID.fullmatch(task["id"])
            and isinstance(acs, list) and acs and _strings(task.get("scope"))
            and all(isinstance(ac, dict) and isinstance(ac.get("id"), str) and isinstance(ac.get("verify"), str)
                    and ac["id"] and ac["verify"] for ac in acs)
        ):
            return None
        ids.append(task["id"])
    if len(set(ids)) != len(ids):
        return None
    workspace = {k: ws[k] for k in WORKSPACE_KEYS}
    workspace["herdr_session"] = ws.get("herdr_session")
    return {"workspace": workspace, "tasks": [
        {"id": t["id"], "acs": [{"id": a["id"], "verify": a["verify"]} for a in t["acs"]], "scope": list(t["scope"])}
        for t in tasks
    ]}


# --- routing (pure; `next` calls it for approved / implementing) ---------------------------


def attempts_of(state: State, task_id: str) -> list[tuple[str, dict[str, Any]]]:
    found = [(k, a) for k, a in (state.get("attempts") or {}).items() if a["task_id"] == task_id]
    return sorted(found, key=lambda item: item[1]["n"])


def _active(state: State) -> str | None:
    open_ = [(a["n"], k) for k, a in (state.get("attempts") or {}).items() if not a.get("end")]
    return max(open_)[1] if open_ else None


def _op_step(state: State, kind: str, op_id: str, now: datetime) -> dict[str, Any] | None:
    op = (state.get("writes") or {}).get(op_id)
    if op is not None and op["status"] in ("prepared", "failed") and kind != "stop" and (
        "approval" in op and op["approval"] != writes.approval_of(state)
    ):
        return human([f"approval_changed:{op_id}"])  # prepared under an earlier approval: never sent
    if op is None or op["status"] in ("prepared", "failed"):
        return _write(kind, op_id)
    if op["status"] == "succeeded":
        return None
    if op["status"] == "in_flight":
        wait = max(1.0, (writes.stale_at(op) - now).total_seconds())
        return {"action": "wait", "poll_after_s": wait, "reason": f"write_in_flight:{op_id}"}
    return human([f"write_unknown:{op_id}"], ["resolve_operation"])  # safety normally reads it back


def _seen(attempt: dict[str, Any]) -> set[str]:
    seen = {r["digest"] for r in attempt.get("rejected", [])} | {c["digest"] for c in attempt.get("conflicts", [])}
    if attempt.get("result"):
        seen.add(attempt["result"]["digest"])
    return seen


def _file_result(state: State, attempt: str) -> bytes | None:
    path = Path(state["assignments"][attempt]["result_path"])
    return path.read_bytes() if path.is_file() else None


def tool_result(state: State, attempt: str) -> bytes | None:
    """The tool-produced envelope from the native final message (design §6, D06), if any."""
    found = observe.parsed_native_result(state, attempt)
    if found is None:
        return None
    doc, fact = found
    env = {
        **doc,
        "producer": "tool",
        "native": {"runtime": state["attempts"][attempt]["handle"]["runtime"], "session_id": fact["session_id"],
                   "message_id": fact["result"]["message_id"]},
        "raw_digest": fact["result"]["raw_digest"],
    }
    return (json.dumps(env, sort_keys=True, indent=2) + "\n").encode()


def _due(state: State, read_key: str, poll_s: float, now: datetime) -> float:
    """Seconds until the next poll of `read_key` (0 = due now)."""
    last = ((state.get("read_budget") or {}).get(read_key) or {}).get("last_at")
    if last is None:
        return 0.0
    return max(0.0, (datetime.fromisoformat(last) + timedelta(seconds=poll_s) - now).total_seconds())


def _running(state: State, attempt: str, now: datetime) -> dict[str, Any]:
    a = state["attempts"][attempt]
    if f"{attempt}.stop" in state["writes"] and (step := _op_step(state, "stop", f"{attempt}.stop", now)):
        return step
    seen = _seen(a)
    # A result can only be checked against a known native ID (OpenCode reports its own):
    # until native observation learns it, the file waits instead of being judged.
    known = a["handle"]["native_session_id"] is not None
    for data in (_file_result(state, attempt) if known else None, None if a["result"] else tool_result(state, attempt)):
        if data is not None and store.digest(data) not in seen:
            return {"action": "import", "attempt": attempt}
    poll = float(a["poll_s"])
    sources = ["native"] if a["result"] else ["worker", "native"]
    waits = {s: _due(state, f"{s}:{attempt}", poll, now) for s in sources}
    for source in sources:
        if waits[source] == 0:
            return _observe(source, attempt)
    if a["result"] is None and observe.native_turn_complete(state, attempt):
        return human([f"result_rejected:{attempt}" if a["rejected"] else f"result_missing:{attempt}"])
    return {"action": "wait", "poll_after_s": min(waits.values()), "reason": f"attempt_running:{attempt}"}


def _free_pane(state: State, now: datetime) -> dict[str, Any] | None:
    """An ended writer's idle agent still holds the worktree pane: stop it (and confirm the
    stop) before another agent is started there."""
    ended = [(a["n"], k) for k, a in (state.get("attempts") or {}).items() if a.get("end")]
    if not ended:
        return None
    last = max(ended)[1]
    started = (state.get("writes") or {}).get(f"{last}.agent_start") or {}
    if started.get("status") != "succeeded":
        return None
    return _op_step(state, "stop", f"{last}.stop", now)


def _next_task(state: State, doc: dict[str, Any]) -> tuple[str | None, bool]:
    for task in doc["tasks"]:
        runs = [a for _, a in attempts_of(state, task["id"]) if a.get("end") and a.get("result")]
        if any(a["result"]["status"] == "completed" for a in runs):
            continue
        return task["id"], any(a["result"]["status"] == "blocked" for a in runs)
    return None, False


def route(state: State, now: datetime) -> dict[str, Any]:
    """The next worker-dispatch action after approval, in the design §2 vocabulary."""
    doc = plan_doc(state)
    if doc is None:
        return human(["plan_tasks_unusable"])
    if step := _op_step(state, "worktree_create", "worktree", now):
        return step
    if not state["writes"]["worktree"]["facts"].get("pane"):
        return human(["worktree_pane_unknown"])
    if active := _active(state):
        for kind in ("agent_start", "prompt"):
            if step := _op_step(state, kind, f"{active}.{kind}", now):
                return step
        return _running(state, active, now)
    if step := _free_pane(state, now):
        return step
    task_id, blocked = _next_task(state, doc)
    if task_id is None:
        return human(["tasks_complete"])  # G1 (T3.1) takes over from here
    if blocked:
        return human([f"task_blocked:{task_id}"])
    return _write("agent_start", f"{task_id}-a{len(attempts_of(state, task_id)) + 1}.agent_start")


# --- op specs (effectful: git, Herdr argv) -------------------------------------------------


def _git(worktree: str, timeout_s: float, *args: str) -> str | None:
    from loopctl import tools

    try:
        return tools.run(["git", "-C", worktree, *args], timeout_s).strip()
    except tools.ToolError:
        return None


def prompt_text(marker: str, asg: dict[str, Any], handle: dict[str, Any]) -> str:
    acs = "\n".join(f"- {ac['id']}: {ac['verify']}" for ac in asg["acs"])
    native = {"runtime": handle["runtime"], "session_id": handle["native_session_id"] or "<your session id>"}
    return (
        f"loopctl assignment {marker}\n"
        f"Implement task {asg['task_id']} (attempt {asg['attempt_id']}) test-first in {asg['worktree']} on "
        f"branch {asg['branch']}. Change only these paths: {', '.join(asg['scope'])}. Commit your work.\n"
        f"Acceptance criteria and how each is verified:\n{acs}\n"
        "When done, write the result envelope (schema_version 1, attempt_id, role, producer \"worker\", "
        f"native {json.dumps(native)}, cwd, versions {{head, base, digests}}, body_kind \"implementation\", "
        f"body {{task_id, status completed|blocked, summary}}) to {asg['result_path']}, and end your final "
        "message with the same envelope as a JSON block.\n"
        f"Assignment:\n```json\n{json.dumps(asg, indent=2, sort_keys=True)}\n```\n{marker}\n"
    )


def op_spec(state: State, kind: str, op_id: str, pol: dict[str, Any], feature: str) -> dict[str, Any]:
    """The fixed argv, marker and expected identity of a new op; only what routing allows."""
    from loopctl.preflight import RUNTIMES
    from loopctl.tools import herdr

    attempts = state.get("attempts") or {}
    if kind == "stop":  # stopping a started agent is always allowed, even while Blocked (D47)
        attempt = op_id.removesuffix(".stop")
        started = (state.get("writes") or {}).get(f"{attempt}.agent_start") or {}
        if op_id == attempt or attempt not in attempts or started.get("status") != "succeeded":
            raise Rejected("not_routable", op=op_id)
    elif state.get("blockers"):
        raise Rejected("feature_blocked", 3, blockers=state["blockers"])
    elif state.get("phase") not in ("approved", "implementing"):
        raise Rejected("not_routable", op=op_id, phase=state.get("phase"))
    else:
        allowed = route(state, clock.now())
        if allowed != _write(kind, op_id):
            raise Rejected("not_routable", op=op_id, next=allowed)
    doc = plan_doc(state)
    assert doc is not None  # route() said this op is next
    ws = doc["workspace"]
    session = ws["herdr_session"]
    if kind == "worktree_create":
        args = ["worktree", "create", "--cwd", ws["source"], "--branch", ws["branch"], "--base", ws["base"],
                "--path", ws["worktree"], "--label", f"loopctl-{feature}", "--no-focus"]
        expected = {"source": ws["source"], "path": ws["worktree"], "branch": ws["branch"], "bind": ws["worktree"]}
        return {"argv": herdr.argv(session, args), "expected": expected, "session": session}
    pane_facts = state["writes"]["worktree"]["facts"]
    if kind == "agent_start":
        return _agent_start(state, op_id, pol, feature, ws, pane_facts, RUNTIMES, herdr)
    attempt = op_id.rsplit(".", 1)[0]
    handle = attempts[attempt]["handle"]
    if kind == "prompt":
        marker = f"loopctl-op:{feature}/{op_id}"
        text = prompt_text(marker, state["assignments"][attempt], handle)
        expected = {"pane": handle["pane"], "workspace": pane_facts.get("workspace"), "marker": marker, "bind": handle["pane"]}
        return {"argv": herdr.argv(session, ["agent", "prompt", handle["agent_name"], text]), "expected": expected,
                "marker": marker, "session": session}
    keys = RUNTIMES[handle["runtime"]][1]
    return {"argv": herdr.argv(session, ["agent", "send-keys", handle["agent_name"], *keys]),
            "expected": {"pane": handle["pane"], "bind": handle["pane"]}, "session": session}


def _agent_start(
    state: State, op_id: str, pol: dict[str, Any], feature: str, ws: dict[str, Any], pane_facts: dict[str, Any],
    runtimes: dict[str, tuple[str, list[str]]], herdr: Any,
) -> dict[str, Any]:
    attempt = op_id.removesuffix(".agent_start")
    task_id = attempt.rsplit("-a", 1)[0]
    task = next(t for t in plan_doc(state)["tasks"] if t["id"] == task_id)  # type: ignore[index]
    profile = (pol.get("profiles") or {}).get(ROLE)
    if not isinstance(profile, dict) or profile.get("runtime") not in runtimes:
        raise Rejected("profile_unusable", 3, role=ROLE)
    head = _git(ws["worktree"], limit(pol, "read_call_s", 30), "rev-parse", "HEAD")
    if not head:
        raise Rejected("worktree_unreadable", 3, worktree=ws["worktree"])
    runtime = profile["runtime"]
    native_id = str(uuid.uuid4()) if runtime == "claude-code" else None  # OpenCode reports its own
    name = f"lc-{feature}-{attempt}"
    settings = str(Path(profile["settings"]).resolve())
    if runtime == "claude-code":
        args = ["--model", profile["model"], "--effort", profile["effort"], "--settings", settings, "--session-id", str(native_id)]
    else:
        args = ["--agent", f"loopctl-{ROLE}", "-m", f"{profile['provider']}/{profile['model']}"]
    ready_ms = str(int(limit(pol, "write_call_s", 60) * 1000 / 2))
    argv = herdr.argv(ws["herdr_session"], ["agent", "start", name, "--kind", runtimes[runtime][0], "--pane",
                                            pane_facts["pane"], "--timeout", ready_ms, "--", *args])
    plan = state["plan"]
    assignment = {
        "attempt_id": attempt, "task_id": task_id, "batch_id": None, "finding_ids": [], "role": ROLE,
        "profile": {k: profile.get(k) for k in ("transport", "runtime", "provider", "model", "effort", "settings")},
        "worktree": ws["worktree"], "branch": ws["branch"], "base": ws["base"], "head": head, "pr": None,
        "plan": {k: plan[k] for k in ("locator", "version", "digest")},
        "digests": dict(state["approval"]["digests"]),
        "acs": task["acs"], "scope": task["scope"],
        "result_path": str(Path(ws["worktree"]) / ".loopctl" / "results" / f"{attempt}.json"),
        "result_schema": SCHEMA_VERSION,
    }
    handle = {"herdr_session": ws["herdr_session"], "pane": pane_facts["pane"], "agent_name": name,
              "native_session_id": native_id, "runtime": runtime}
    poll = limit(pol, "poll_worker_s", 30)

    def on_prepare(st: State, at: str) -> None:
        st.setdefault("assignments", {})[attempt] = assignment
        st["attempts"][attempt] = {
            "n": len(st["attempts"]) + 1, "task_id": task_id, "role": ROLE, "handle": handle, "poll_s": poll,
            "started_at": at, "result": None, "rejected": [], "conflicts": [], "end": None,
        }
        st.setdefault("activities", []).append({"kind": "worker", "attempt": attempt, "start": at, "end": None})

    expected = {"agent": name, "pane": pane_facts["pane"], "cwd": ws["worktree"], "bind": name}
    return {"argv": argv, "expected": expected, "session": ws["herdr_session"], "on_prepare": on_prepare}


# --- the common result envelope (design §8) ------------------------------------------------


def _implementation(body: Any, asg: dict[str, Any]) -> list[str]:
    if not isinstance(body, dict):
        return ["not_an_object"]
    errors = [] if body.get("task_id") == asg["task_id"] else ["task_id"]
    errors += [] if body.get("status") in ("completed", "blocked") else ["status"]
    return errors + ([] if isinstance(body.get("summary"), str) else ["summary"])


# body_kind -> validator(body, assignment) -> errors. T5.1 adds `review` and `correction`.
BODY_VALIDATORS = {"implementation": _implementation}


def _has_argv(value: Any) -> bool:
    if isinstance(value, dict):
        return "argv" in value or any(_has_argv(v) for v in value.values())
    return isinstance(value, list) and any(_has_argv(v) for v in value)


def _git_facts(asg: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    head = _git(asg["worktree"], timeout_s, "rev-parse", "HEAD")
    if head is None:
        return {"head": None, "ancestor": False, "changed": []}
    ancestor = _git(asg["worktree"], timeout_s, "merge-base", "--is-ancestor", asg["head"], head) is not None
    changed = (_git(asg["worktree"], timeout_s, "diff", "--name-only", asg["head"], head) or "").splitlines()
    return {"head": head, "ancestor": ancestor, "changed": [p for p in changed if p]}


def diffs(env: Any, asg: dict[str, Any], handle: dict[str, Any], producer: str, git: dict[str, Any]) -> list[str]:
    """Every identity, version and scope difference between a result and its assignment."""
    if not isinstance(env, dict):
        return ["not_an_object"]
    found = [] if env.get("schema_version") == SCHEMA_VERSION else ["schema_version"]
    found += [f for f in ("attempt_id", "role") if env.get(f) != asg[f]]
    found += [] if env.get("producer") == producer else ["producer"]
    native: dict[str, Any] = env["native"] if isinstance(env.get("native"), dict) else {}
    if native.get("runtime") != handle["runtime"]:
        found.append("native_runtime")
    if handle["native_session_id"] is None or native.get("session_id") != handle["native_session_id"]:
        found.append("native_session_id")  # unknown handle ids are never filled in from a result
    cwd = env.get("cwd")
    if not isinstance(cwd, str) or Path(cwd).resolve() != Path(asg["worktree"]).resolve():
        found.append("cwd")
    versions: dict[str, Any] = env["versions"] if isinstance(env.get("versions"), dict) else {}
    found += [f for f in ("base", "digests") if versions.get(f) != asg[f]]
    if git["head"] is None or versions.get("head") != git["head"]:
        found.append("head")
    if git["head"] is not None and not git["ancestor"]:
        found.append("head_lineage")
    found += [f"scope:{p}" for p in git["changed"] if not any(fnmatch.fnmatchcase(p, s) for s in asg["scope"])]
    if _has_argv(env):
        found.append("worker_argv")
    validator = BODY_VALIDATORS.get(str(env.get("body_kind")))
    found += ["body_kind"] if validator is None else [f"body:{e}" for e in validator(env.get("body"), asg)]
    return found


class _Duplicate(Exception):
    pass


def import_result(feature: str, token: str | None, attempt: str, file: str | None) -> dict[str, Any]:
    """Import one attempt's result: the file (default: the assignment's result location) or,
    without a file, the tool-extracted native result. The original bytes are always kept."""
    _, st = owned(feature, token)
    a = (st.get("attempts") or {}).get(attempt)
    if a is None:
        raise Rejected("unknown_attempt", attempt=attempt)
    asg, handle = st["assignments"][attempt], a["handle"]
    data = Path(file).read_bytes() if file and Path(file).is_file() else None if file else _file_result(st, attempt)
    producer = "worker"
    if data is None and not file:
        data, producer = tool_result(st, attempt), "tool"
    if data is None:
        raise Rejected("result_missing", attempt=attempt, path=file or asg["result_path"])
    if handle["native_session_id"] is None:  # nothing to compare yet: not a rejection
        raise Rejected("native_session_unknown", attempt=attempt, runtime=handle["runtime"])
    digest = store.digest(data)
    if a.get("result") and a["result"]["digest"] == digest:
        return {"attempt": attempt, "duplicate": True, "result": a["result"]}
    for kept in a.get("rejected", []):
        if kept["digest"] == digest:
            raise Rejected("result_rejected", 1, attempt=attempt, diffs=kept["diffs"], duplicate=True)
    if digest in {c["digest"] for c in a.get("conflicts", [])}:
        raise Rejected("result_conflict", 3, attempt=attempt, duplicate=True)
    ref = store.object_ref(store.put_object(data))
    at = now_iso()
    if a.get("result"):  # same attempt, different bytes: keep both, stop for a human
        def conflict(s: State) -> State:
            s["attempts"][attempt]["conflicts"].append({"object": ref, "digest": digest, "at": at})
            block(s, f"result_conflict:{attempt}")
            return s

        commit(feature, f"import:{attempt}:conflict:{digest[7:23]}@{at}", conflict)
        raise Rejected("result_conflict", 3, attempt=attempt, kept=[a["result"]["digest"], digest])
    try:
        env = json.loads(data)
    except ValueError:
        env = None
    git = _git_facts(asg, limit(policy(st), "read_call_s", 30))
    found = diffs(env, asg, handle, producer, git) if env is not None else ["unparseable"]
    if found:
        def reject(s: State) -> State:
            s["attempts"][attempt]["rejected"].append({"object": ref, "digest": digest, "diffs": found, "at": at})
            return s

        commit(feature, f"import:{attempt}:reject:{digest[7:23]}@{at}", reject)
        raise Rejected("result_rejected", 1, attempt=attempt, diffs=found)
    assert isinstance(env, dict)
    record = {
        "object": ref, "digest": digest, "producer": producer, "native": env["native"],
        "raw_digest": env.get("raw_digest"), "status": env["body"]["status"], "head": git["head"],
        "body_kind": env["body_kind"], "at": at,
    }

    def accept(s: State) -> State:
        target = s["attempts"][attempt]
        if target.get("result"):
            raise _Duplicate
        target["result"] = record
        unblock(s, f"native_result_unparseable:{attempt}")
        settle(s, attempt, at)
        return s

    try:
        commit(feature, f"import:{attempt}:{digest[7:23]}@{at}", accept)
    except _Duplicate:
        return import_result(feature, token, attempt, file)
    return {"attempt": attempt, "duplicate": False, "result": record,
            "ended": store.load(feature)[1]["attempts"][attempt]["end"] is not None}
