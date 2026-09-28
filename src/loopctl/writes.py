"""External writes (design §4): the op state machine, retry and readback rules (T2.3).

T6.1 / T6.2 only add op kinds and their tool functions; the state machine stays.

  writes[op_id] = {kind, status: prepared|in_flight|succeeded|failed|unknown|superseded,
                   prepared: {argv: {$object}, argv_digest, marker, expected, session,
                              call_limit_s, read_limit_s, readback_max, readback_interval_s,
                              max_attempts},
                   approval: the approval decision it was prepared under,
                   attempts: [{n, started_at, ended_at, outcome, reason, receipt}],
                   readbacks: [{seq, at, attempt, result, detail, observation, [decision]}],
                   facts, resolved_by: readback|human|None, resolutions: {decision id: …},
                   blocked: write_unknown|readback_exhausted|retry_exhausted|None,
                   superseded: {reason, approval, current, at}}

`write <op> --id` consumes the op once in the lock, runs its fixed argv once, and records the
receipt. A call past its time limit is unknown, never failed. Retries: only after a recorded
not-delivered outcome, at most `infra_extra_retries` more calls. An unknown op is only read
back (at most `readback_max` per call attempt, every read counts) or resolved by a human
`resolve_operation`; nothing is ever resent on a guess.

Superseded (Lead ruling 2026-09-28, T2.3 review verdict): a never-sent op (prepared, or failed
and not delivered, also once its retries are exhausted) whose approval is no longer the current
one is stale. Its argv is never sent; the controller marks it superseded (terminal) when it is
written or when the next op is prepared, clearing its own retry_exhausted blocker, and routing
continues with a fresh op ID (`current_id`) that has its own retry count. Until then that
blocker is obsolete (`live_blockers`); every other blocker stays. An in_flight or unknown op is
never superseded: it may have taken effect.
"""

import json
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from loopctl import clock, store
from loopctl.observe import (
    Rejected,
    allocate,
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
GH_KINDS = ("push", "pr_ensure")  # T6.1: tools.gh op calls and readbacks
KINDS = ("worktree_create", "agent_start", "prompt", "stop", *GH_KINDS)
# T6.1: a delivered request the remote refused (non-fast-forward push, a PR create refused) or
# a pre-create query that forbids creating (one open PR of another identity, several open PRs)
REFUSALS = ("push_rejected", "pr_identity_mismatch", "pr_ambiguous", "pr_create_rejected")
BLOCKED_REASONS = ("write_unknown", "readback_exhausted", "retry_exhausted", *REFUSALS)
RECOVERY_KINDS = {"write_unknown": "resolve_operation", "readback_exhausted": "resolve_operation"}
STATUS = {"succeeded": "succeeded", "failed_not_delivered": "failed", "rejected": "failed", "unknown": "unknown"}
STALE_GRACE_S = 30.0  # an in_flight op older than its call limit + this lost its process
# (state, kind, op_id, policy, feature) -> spec {argv, expected, marker?, session?, on_prepare?}
Prepare = Callable[[State, str, str, dict[str, Any], str], dict[str, Any]]


class _Skip(Exception):
    """The transition no longer applies (another process got there first)."""


class _Refused(Exception):
    def __init__(self, rejected: Rejected) -> None:
        super().__init__(rejected.error)
        self.rejected = rejected


def _herdr() -> Any:
    from loopctl.tools import herdr

    return herdr


def _gh() -> Any:
    from loopctl.tools import gh

    return gh


def _op_call(op: dict[str, Any], argv: Any) -> dict[str, Any]:
    p = op["prepared"]
    if op["kind"] in GH_KINDS:
        return dict(_gh().op_call(op["kind"], argv, float(p["call_limit_s"]), p["expected"], float(p["read_limit_s"])))
    return dict(_herdr().op_call(op["kind"], argv, float(p["call_limit_s"])))


def _op_readback(op: dict[str, Any], observed: str | None = None) -> dict[str, Any]:
    p = op["prepared"]
    if op["kind"] in GH_KINDS:
        return dict(_gh().readback(op["kind"], p["expected"], float(p["read_limit_s"]), observed))
    return dict(_herdr().readback(op["kind"], p["session"], p["expected"], float(p["read_limit_s"])))


def view(op_id: str, op: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": op_id, "kind": op["kind"], "status": op["status"], "attempts": len(op["attempts"]),
        "readbacks": len(op["readbacks"]), "blocked": op.get("blocked"), "resolved_by": op.get("resolved_by"),
    }


def _superseded(op_id: str, op: dict[str, Any]) -> Rejected:
    return Rejected("op_superseded", 1, op=view(op_id, op), superseded=op["superseded"], performed="none")


def _set_blocked(st: State, op_id: str, reason: str) -> None:
    st["writes"][op_id]["blocked"] = reason
    block(st, f"{reason}:{op_id}")


def _blocking(op_id: str, reason: str) -> Callable[[State], State]:
    def mutate(st: State) -> State:
        _set_blocked(st, op_id, reason)
        return st

    return mutate


def _clear_blocked(st: State, op_id: str) -> None:
    st["writes"][op_id]["blocked"] = None
    unblock(st, *(f"{r}:{op_id}" for r in BLOCKED_REASONS))


def stale_at(op: dict[str, Any]) -> datetime:
    started = datetime.fromisoformat(op["attempts"][-1]["started_at"])
    return started + timedelta(seconds=float(op["prepared"]["call_limit_s"]) + STALE_GRACE_S)


def _call_readbacks(op: dict[str, Any]) -> list[dict[str, Any]]:
    """Readbacks of the latest call attempt (a human-authorized read is not counted)."""
    n = len(op["attempts"])
    return [r for r in op["readbacks"] if r["attempt"] == n and not r.get("decision")]


def approval_of(st: State) -> str | None:
    return (st.get("approval") or {}).get("decision")


def prepared_under_current(st: State, op: dict[str, Any]) -> bool:
    """An op persisted without its approval (before ops recorded it) fails closed."""
    return "approval" in op and op["approval"] == approval_of(st)


def stale(st: State, op_id: str) -> bool:
    """Never sent, and not prepared under the current approval. A stop is always allowed
    (D47). Of the Blocked ops only retry_exhausted is certainly undelivered; a refused one
    stays for a human."""
    op = (st.get("writes") or {}).get(op_id)
    return (
        op is not None and op.get("kind") in KINDS and op["kind"] != "stop" and op.get("status") in ("prepared", "failed")
        and op.get("blocked") in (None, "retry_exhausted") and not prepared_under_current(st, op)
    )


def obsolete(st: State, blocker: str) -> bool:
    """The blocker of a stale op: cleared when that op is superseded, never waited on."""
    reason, _, op_id = blocker.partition(":")
    op = (st.get("writes") or {}).get(op_id) or {}
    return reason in BLOCKED_REASONS and op.get("blocked") == reason and stale(st, op_id)


def live_blockers(st: State, blocked: list[str] | None = None) -> list[str]:
    """The recorded blockers (or `blocked`) without the obsolete ones."""
    return [b for b in (st.get("blockers", []) if blocked is None else blocked) if not obsolete(st, b)]


def current_id(st: State, base: str) -> str:
    """The op routing continues with: `base`, or `base~N` once the ops before it were
    superseded (or are stale, and superseded when this one is prepared)."""
    ops, n, op_id = st.get("writes") or {}, 1, base
    while op_id in ops and (ops[op_id]["status"] == "superseded" or stale(st, op_id)):
        n += 1
        op_id = f"{base}~{n}"
    return op_id


def _supersede_stale(st: State, at: str) -> None:
    """Mark every stale op superseded, clearing its own retry_exhausted blocker. An
    agent_start never sent started no agent: its attempt ends with it."""
    for op_id in sorted(st.get("writes") or {}):
        if not stale(st, op_id):
            continue
        op = st["writes"][op_id]
        op["status"] = "superseded"
        op["superseded"] = {"reason": "approval_changed" if "approval" in op else "approval_unrecorded",
                            "approval": op.get("approval"), "current": approval_of(st), "at": at}
        if op.get("blocked"):
            op["superseded"]["blocked"] = op["blocked"]
            _clear_blocked(st, op_id)
        a = (st.get("attempts") or {}).get(op_id.removesuffix(".agent_start"))
        if op["kind"] == "agent_start" and a is not None and not a.get("end"):
            a["end"] = {"evidence": "superseded", "at": at}
            for activity in st.get("activities", []):
                if activity.get("attempt") == op_id.removesuffix(".agent_start") and not activity["end"]:
                    activity["end"] = at


def refusal(st: State, op_id: str) -> Rejected | None:
    """Why a prepared or retryable op may not be sent now (design §2, §8): the feature is
    Blocked, or routing no longer offers it. A stop is always allowed (D47); readback of a sent
    op never comes here, and a stale op is superseded before."""
    from loopctl import next as next_step

    op = st["writes"][op_id]
    if op["kind"] == "stop":
        return None
    if found := live_blockers(st):
        return Rejected("feature_blocked", 3, blockers=found)
    allowed = next_step.next_action(st, [])
    if allowed != {"action": "write", "op": op["kind"], "id": op_id}:
        return Rejected("not_routable", op=op_id, next=allowed)
    return None


def pending_resolution(st: State, op_id: str) -> dict[str, Any] | None:
    done = st["writes"][op_id].get("resolutions", {})
    for d in sorted((st.get("decisions") or {}).values(), key=lambda d: d["seq"]):
        if d["kind"] == "resolve_operation" and d["target"] == op_id and d["id"] not in done:
            return dict(d)
    return None


def _settle_op(st: State, op_id: str, at: str) -> None:
    op = st["writes"][op_id]
    if op["kind"] == "stop":
        settle(st, op_id.removesuffix(".stop"), at)
    elif op["kind"] == "pr_ensure" and op["status"] == "succeeded" and st.get("pr") is None:
        _record_pr(st, op_id, at)


def _record_pr(st: State, op_id: str, at: str) -> None:
    """The PR identity (design §4): number, node id, url, head/base repo, branch, SHA, origin."""
    op = st["writes"][op_id]
    found = op["facts"]["pr"]
    st["pr"] = {**{k: found[k] for k in ("number", "node_id", "url", "head_repo", "head_branch", "head_sha",
                                         "base_repo", "base_branch", "origin")}, "op": op_id, "at": at}
    if op["facts"].get("differs"):  # GitHub created a PR other than the one persisted as expected
        block(st, f"pr_identity_mismatch:{op_id}")


def _report(feature: str, op_id: str, performed: str) -> dict[str, Any]:
    op = store.load(feature)[1]["writes"][op_id]
    if op.get("blocked"):
        raise Rejected(op["blocked"], 3, op=view(op_id, op), performed=performed)
    return {"op": view(op_id, op), "performed": performed}


def write(feature: str, token: str | None, kind: str, op_id: str, prepare: Prepare) -> dict[str, Any]:
    if kind not in KINDS:
        raise Rejected("unsupported", 2, op=kind)
    if kind in GH_KINDS:
        prepare = github_spec
    _, st = owned(feature, token)
    pol = policy(st)
    if op_id not in (st.get("writes") or {}):
        _prepare(feature, kind, op_id, prepare(st, kind, op_id, pol, feature), pol)
        st = store.load(feature)[1]
    op = st["writes"][op_id]
    if op["kind"] != kind:
        raise Rejected("op_kind_mismatch", op=op_id, kind=op["kind"])
    if (decision := pending_resolution(st, op_id)) is not None:
        return _resolve(feature, op_id, decision)
    if op.get("blocked") and stale(st, op_id):
        return _retire(feature, op_id)
    if op.get("blocked"):
        raise Rejected(op["blocked"], 3, op=view(op_id, op), performed="none")
    status = op["status"]
    if status == "succeeded":
        return {"op": view(op_id, op), "performed": "none"}
    if status == "superseded":
        raise _superseded(op_id, op)
    if status == "in_flight":
        if clock.now() < stale_at(op):
            raise Rejected("op_in_flight", 1, op=view(op_id, op))
        _interrupted(feature, op_id, len(op["attempts"]))
        status = "unknown"
    if status == "unknown":
        return _readback(feature, op_id)
    return _call(feature, op_id)


def _prepare(feature: str, kind: str, op_id: str, spec: dict[str, Any], pol: dict[str, Any]) -> None:
    """Persist the op (fixed argv, marker, expected identity) before any external call."""
    at = now_iso()
    argv_ref = store.put_object(json.dumps(spec["argv"]).encode())
    extra = int((pol.get("budget") or {}).get("infra_extra_retries", 2))
    prepared = {
        "argv": store.object_ref(argv_ref),
        "argv_digest": argv_ref,
        "marker": spec.get("marker"),
        "expected": spec["expected"],
        "session": spec.get("session"),
        "call_limit_s": spec.get("call_limit_s", limit(pol, "write_call_s", 60)),
        "read_limit_s": limit(pol, "read_call_s", 30),
        "readback_max": int(limit(pol, "readback_max", 3)),
        "readback_interval_s": limit(pol, "stop_readback_interval_s", 10),
        "max_attempts": 1 + extra,
    }
    on_prepare = spec.get("on_prepare")

    def mutate(st: State) -> State:
        if op_id in st.setdefault("writes", {}):
            raise _Skip
        _supersede_stale(st, at)
        st["writes"][op_id] = {
            "kind": kind, "status": "prepared", "prepared": prepared, "prepared_at": at, "attempts": [],
            "readbacks": [], "facts": {}, "resolved_by": None, "resolutions": {}, "blocked": None,
            "approval": approval_of(st),
        }
        if st.get("phase") == "approved":
            st["phase"] = "implementing"
        if on_prepare is not None:
            on_prepare(st, at)
        return st

    try:
        commit(feature, f"write:{op_id}:prepare@{at}:{secrets.token_hex(6)}", mutate)
    except _Skip:
        pass  # prepared concurrently: the first prepared op is the op


def _interrupted(feature: str, op_id: str, n: int) -> None:
    """The calling process vanished mid-call: the request may have gone out → unknown."""
    at = now_iso()

    def mutate(st: State) -> State:
        op = st["writes"][op_id]
        if op["status"] != "in_flight" or len(op["attempts"]) != n:
            raise _Skip
        op["attempts"][-1].update(ended_at=at, outcome="unknown", reason="interrupted")
        op["status"] = "unknown"
        return st

    try:
        commit(feature, f"write:{op_id}:interrupted:{n}", mutate)
    except _Skip:
        pass


def _retire(feature: str, op_id: str) -> dict[str, Any]:
    """A retry-exhausted op of an earlier approval: superseded, never sent again."""
    at = now_iso()

    def mutate(st: State) -> State:
        if not stale(st, op_id):
            raise _Skip
        _supersede_stale(st, at)
        return st

    try:
        commit(feature, f"write:{op_id}:retire@{at}:{secrets.token_hex(6)}", mutate)
    except _Skip:
        pass
    op = store.load(feature)[1]["writes"][op_id]
    if op["status"] == "superseded":
        raise _superseded(op_id, op)
    raise Rejected(op["blocked"] or "op_state_changed", 3 if op.get("blocked") else 1, op=view(op_id, op),
                   performed="none")


def _call(feature: str, op_id: str) -> dict[str, Any]:
    op = store.load(feature)[1]["writes"][op_id]
    prepared = op["prepared"]
    n = len(op["attempts"]) + 1
    if n > prepared["max_attempts"]:
        commit(feature, f"write:{op_id}:retry_exhausted:{n}", _blocking(op_id, "retry_exhausted"))
        return _report(feature, op_id, "none")
    started = now_iso()

    def consume(st: State) -> State:
        o = st["writes"][op_id]
        if o["status"] not in ("prepared", "failed") or len(o["attempts"]) != n - 1 or o.get("blocked"):
            raise _Skip
        if stale(st, op_id):
            _supersede_stale(st, started)
            return st
        if (refused := refusal(st, op_id)) is not None:
            raise _Refused(refused)
        o["status"] = "in_flight"
        o["attempts"].append(
            {"n": n, "started_at": started, "ended_at": None, "outcome": None, "reason": None, "receipt": None}
        )
        return st

    try:
        commit(feature, f"write:{op_id}:consume:{n}:{secrets.token_hex(6)}", consume)
    except _Refused as e:
        raise e.rejected from None
    except _Skip:
        op = store.load(feature)[1]["writes"][op_id]
        if op["status"] == "succeeded":
            return {"op": view(op_id, op), "performed": "none"}
        if op["status"] == "superseded":
            raise _superseded(op_id, op) from None
        raise Rejected("op_in_flight" if op["status"] == "in_flight" else "op_state_changed", 1, op=view(op_id, op)) from None
    op = store.load(feature)[1]["writes"][op_id]
    if op["status"] == "superseded":  # its argv was never sent; routing has a fresh op
        raise _superseded(op_id, op)

    argv = json.loads(store.get_object(prepared["argv"][store.OBJECT_KEY]))
    result = _op_call(op, argv)  # the one call
    ended = now_iso()
    receipt = store.put_object(result["receipt"].encode())

    def record(st: State) -> State:
        o = st["writes"][op_id]
        o["attempts"][-1].update(
            ended_at=ended, outcome=result["outcome"], reason=result["reason"], receipt=store.object_ref(receipt)
        )
        o["status"] = STATUS[result["outcome"]]
        if o["status"] == "succeeded":
            o["facts"] = {**o["facts"], **result["facts"]}
        if result["outcome"] == "rejected":  # refused, not undelivered: never retried
            o["facts"] = {**o["facts"], **result["facts"]}
            _set_blocked(st, op_id, result["block"])
        elif o["status"] == "failed" and n >= prepared["max_attempts"]:
            _set_blocked(st, op_id, "retry_exhausted")
        _settle_op(st, op_id, ended)
        return st

    commit(feature, f"write:{op_id}:outcome:{n}", record)
    return _report(feature, op_id, "call")


def _observation(read: dict[str, Any]) -> str:
    return store.put_object(json.dumps({k: read[k] for k in ("result", "detail", "raw")}, sort_keys=True).encode())


def _readback(feature: str, op_id: str) -> dict[str, Any]:
    op = store.load(feature)[1]["writes"][op_id]
    prepared = op["prepared"]
    if len(_call_readbacks(op)) >= prepared["readback_max"]:
        commit(feature, f"write:{op_id}:readback_exhausted:{len(op['attempts'])}", _blocking(op_id, "readback_exhausted"))
        return _report(feature, op_id, "none")
    seq = allocate(feature, f"op:{op_id}", "op", "readback")
    read = _op_readback(op)
    at, ref, n = now_iso(), _observation(read), len(op["attempts"])

    def mutate(st: State) -> State:
        o = st["writes"][op_id]
        o["readbacks"].append({"seq": seq, "at": at, "attempt": n, "result": read["result"],
                               "detail": read["detail"], "observation": store.object_ref(ref)})
        if read["result"] == "confirmed":
            o.update(status="succeeded", resolved_by="readback")
            o["facts"] = {**o["facts"], **read["facts"]}
            _clear_blocked(st, op_id)
        elif read["result"] in ("absent", "mismatch"):  # not proof of either outcome
            _set_blocked(st, op_id, "write_unknown")
        elif len(_call_readbacks(o)) >= prepared["readback_max"]:
            _set_blocked(st, op_id, "readback_exhausted")
        _settle_op(st, op_id, at)
        return st

    commit(feature, f"write:{op_id}:readback:{seq}", mutate)
    return _report(feature, op_id, "readback")


def _resolve(feature: str, op_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Apply a human resolve_operation (design §4): --bind needs one fresh matching read;
    --not-delivered needs evidence that is not the controller's own not-found observation."""
    op = store.load(feature)[1]["writes"][op_id]
    prepared, mode = op["prepared"], decision["resolution"]["mode"]
    read: dict[str, Any] | None = None
    reason = None
    if op["status"] != "unknown":
        reason = f"op_not_unknown:{op['status']}"
    elif mode == "bind":
        observed = decision["resolution"]["observed"]
        # expected.bind None (pr_ensure): the number is unknown before creation, so the one fresh
        # read of the named PR must match the persisted identity instead
        if prepared["expected"]["bind"] is not None and observed != prepared["expected"]["bind"]:
            reason = "bind_differs_from_expected"
        else:
            seq = allocate(feature, f"op:{op_id}", "op", "resolve_operation")
            read = _op_readback(op, observed)
            read = {**read, "seq": seq, "observation": _observation(read)}
            if read["result"] != "confirmed":
                reason = f"read_{read['result']}:{read['detail']}"
    else:
        own = {r["observation"][store.OBJECT_KEY] for r in op["readbacks"]}
        own |= {a["receipt"][store.OBJECT_KEY] for a in op["attempts"] if a.get("receipt")}
        if decision["evidence"][store.OBJECT_KEY] in own:
            reason = "not_found_is_not_evidence"
    at = now_iso()

    def mutate(st: State) -> State:
        o = st["writes"][op_id]
        if read is not None:
            o["readbacks"].append({
                "seq": read["seq"], "at": at, "attempt": len(o["attempts"]), "decision": decision["id"],
                "result": read["result"], "detail": read["detail"], "observation": store.object_ref(read["observation"]),
            })
        o["resolutions"][decision["id"]] = {"status": "rejected" if reason else "applied", "mode": mode,
                                            "reason": reason, "at": at}
        if reason:
            if o["status"] == "unknown":
                _set_blocked(st, op_id, o.get("blocked") or "write_unknown")
            return st
        _clear_blocked(st, op_id)
        o["resolved_by"] = "human"
        if mode == "bind":
            o["status"] = "succeeded"
            o["facts"] = {**o["facts"], **(read or {}).get("facts", {})}
        else:
            o["status"] = "failed"  # not delivered: retries stay within the op's limit
            if len(o["attempts"]) >= prepared["max_attempts"]:
                _set_blocked(st, op_id, "retry_exhausted")
        _settle_op(st, op_id, at)
        return st

    commit(feature, f"write:{op_id}:resolve:{decision['id']}", mutate)
    if reason:
        op = store.load(feature)[1]["writes"][op_id]
        raise Rejected("resolution_rejected", 3, decision=decision["id"], reason=reason, op=view(op_id, op))
    return _report(feature, op_id, "resolution")


def github_spec(state: State, kind: str, op_id: str, pol: dict[str, Any], feature: str) -> dict[str, Any]:
    """T6.1: the fixed argv, expected identity and marker of `push` / `pr_ensure` (design §4).
    Only after G1 passed at H, and only the op `next` offers (push before pr_ensure)."""
    from loopctl import gates
    from loopctl import next as next_step

    g1 = (state.get("gates") or {}).get("g1") or {}
    if g1.get("status") != "passed":
        raise Rejected("g1_not_passed", 1, op=op_id, g1=g1.get("status", "pending"))
    if found := live_blockers(state):
        raise Rejected("feature_blocked", 3, blockers=found)
    allowed = next_step.next_action(state, [])
    if allowed != {"action": "write", "op": kind, "id": op_id}:
        raise Rejected("not_routable", op=op_id, next=allowed)
    ws = gates.github_workspace(state)
    assert ws is not None  # routing offered a GitHub op
    head, repo, ref = g1["head"], state["repo"], f"refs/heads/{ws['branch']}"
    if kind == "push":  # a plain fast-forward of H: no force, no + refspec, no delete (design §4)
        argv = ["git", "-C", ws["source"], "push", "--porcelain", ws["remote"], f"{head}:{ref}"]
        expected = {"source": ws["source"], "remote": ws["remote"], "ref": ref, "sha": head, "bind": head}
        return {"argv": argv, "expected": expected, "call_limit_s": limit(pol, "push_call_s", 120)}
    marker = f"loopctl-op:{feature}/{op_id}"
    expected = {"repo": repo, "head_repo": repo, "head_branch": ws["branch"], "head_sha": head, "base_repo": repo,
                "base_branch": ws["base"], "marker": marker, "bind": None}
    body = f"loopctl feature {feature} (issue {state.get('issue')}).\n\nHead: {head}\n\n<!-- {marker} -->\n"
    create = ["gh", "api", "--include", "--method", "POST", f"repos/{repo}/pulls",
              "-f", f"title=loopctl {feature}: issue {state.get('issue')}", "-f", f"head={ws['branch']}",
              "-f", f"base={ws['base']}", "-f", f"body={body}"]
    query = f"repos/{repo}/pulls?state=open&head={repo.split('/')[0]}:{ws['branch']}&per_page=100"
    return {"argv": {"query": query, "create": create}, "expected": expected, "marker": marker,
            "call_limit_s": limit(pol, "pr_ensure_call_s", 120)}


def safety(state: State, now: datetime) -> dict[str, Any] | None:
    """Readbacks and pending human resolutions come before any other action."""
    for op_id in sorted(state.get("writes") or {}):
        op = state["writes"][op_id]
        if op.get("kind") not in KINDS or "prepared" not in op:
            continue  # not an op of this state machine (e.g. a later task's kind): no action
        action = {"action": "write", "op": op["kind"], "id": op_id}
        if pending_resolution(state, op_id) is not None:
            return action
        if op.get("blocked"):
            continue
        if op["status"] == "in_flight" and now >= stale_at(op):
            return action
        if op["status"] == "unknown":
            reads = _call_readbacks(op)
            if reads and reads[-1]["result"] in ("pending", "transport_error"):
                due = datetime.fromisoformat(reads[-1]["at"]) + timedelta(seconds=float(op["prepared"]["readback_interval_s"]))
                if now < due:
                    return {"action": "wait", "poll_after_s": (due - now).total_seconds(), "reason": f"readback:{op_id}"}
            return action
    return None
