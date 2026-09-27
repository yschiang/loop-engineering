"""Outbox operations and staged dispatch recovery (design §11, DR-07)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

EXTRA_RETRIES = 2  # D13: each infra operation may be retried twice after the first attempt


class ResponseUnknown(Exception):
    """The external call's outcome is unknown (response lost, timeout, 5xx)."""


class GitHubPort(Protocol):
    def post_comment(self, target: str, body: str) -> dict[str, Any]: ...
    def find_comment(self, target: str, marker: str) -> dict[str, Any] | None: ...


class RuntimePort(Protocol):
    session_list_consistent: bool

    def create_session(self, title: str) -> str: ...
    def find_sessions(self, marker: str) -> list[str]: ...
    def send_prompt(self, session: str, text: str) -> str: ...
    def list_messages(self, session: str) -> list[dict[str, Any]]: ...
    def stop(self, session: str) -> bool: ...


TERMINAL = ("succeeded", "blocked", "fenced")


def new_comment_op(state: dict[str, Any], op_id: str, target: str, body: str, run_id: str) -> dict[str, Any]:
    marker = f"<!-- orca-delivery op={op_id} run={run_id} -->"
    full = f"{body}\n\n{marker}"
    state.setdefault("operations", {})[op_id] = {
        "op_id": op_id, "kind": "pr_comment", "target": target, "body": full, "marker": marker,
        "payload_digest": hashlib.sha256(full.encode()).hexdigest(), "state": "pending",
        "attempts": [], "retries_used": 0, "receipt": None}
    return state


def new_dispatch_op(state: dict[str, Any], op_id: str, attempt_id: str, prompt: str) -> dict[str, Any]:
    marker = f"orca-delivery attempt={attempt_id}"
    state.setdefault("operations", {})[op_id] = {
        "op_id": op_id, "kind": "dispatch", "attempt_id": attempt_id, "marker": marker, "prompt": prompt,
        "payload_digest": hashlib.sha256(prompt.encode()).hexdigest(), "state": "pending",
        "stage": "session_pending", "create_started": False, "session_id": None, "native_message_id": None,
        "receipt": None, "retries_used": 0}
    return state


def _receipt(store: Any, body: dict[str, Any]) -> str:
    ref: str = store.put_blob(json.dumps(body, sort_keys=True).encode()).ref
    return ref


def _block(store: Any, state: dict[str, Any], op: dict[str, Any], reason: str) -> dict[str, Any]:
    op["state"] = "blocked"
    op["blocked_reason"] = reason
    state.setdefault("blockers", []).append({"kind": "operation_blocked", "op_id": op["op_id"], "reason": reason})
    store.commit(state)
    return state


def _advance_comment(store: Any, state: dict[str, Any], op: dict[str, Any], gh: GitHubPort) -> dict[str, Any]:
    if op["state"] == "in_flight":  # resumed: the previous call may or may not have happened
        op["state"] = "outcome_unknown"
    while op["state"] not in TERMINAL:
        if op["state"] == "outcome_unknown":
            try:
                found = gh.find_comment(op["target"], op["marker"])
            except ResponseUnknown as e:
                op["retries_used"] += 1
                if op["retries_used"] > EXTRA_RETRIES:
                    return _block(store, state, op, f"outcome unknown and marker lookup failed: {e}")
                store.commit(state)
                continue
            if found is not None:
                op.update(state="succeeded", receipt=_receipt(store, found))
                store.commit(state)
                break
            op["state"] = "pending"  # proven absent: a retry cannot duplicate
            if op["attempts"]:
                op["retries_used"] += 1
        if op["retries_used"] > EXTRA_RETRIES:
            return _block(store, state, op, f"{len(op['attempts'])} attempts failed")
        op["state"] = "in_flight"
        store.commit(state)
        try:
            receipt = gh.post_comment(op["target"], op["body"])
        except ResponseUnknown as e:
            op["attempts"].append({"outcome": "unknown", "error": str(e)})
            op["state"] = "outcome_unknown"
            store.commit(state)
            continue
        op["attempts"].append({"outcome": "ok"})
        op.update(state="succeeded", receipt=_receipt(store, receipt))
        store.commit(state)
    return state


def _prompt_text(op: dict[str, Any]) -> str:
    return f"{op['marker']} payload={op['payload_digest']}\n{op['prompt']}"


def _recover_prompt(store: Any, state: dict[str, Any], op: dict[str, Any], rt: RuntimePort) -> dict[str, Any]:
    head = f"{op['marker']} payload={op['payload_digest']}"
    for msg in rt.list_messages(op["session_id"]):
        if msg.get("role") == "user" and msg.get("text", "").startswith(head):
            op.update(stage="prompt_accepted", state="running", native_message_id=msg["id"],
                      receipt=_receipt(store, {"session": op["session_id"], "message": msg["id"],
                                                "source": "list_messages"}))
            store.commit(state)
            return state
    # Delivery cannot be proven: never resend into this session; fence the attempt instead.
    if not rt.stop(op["session_id"]):
        return _block(store, state, op, "prompt outcome unknown and session stop not confirmed")
    op["retries_used"] += 1
    if op["retries_used"] > EXTRA_RETRIES:
        return _block(store, state, op, "prompt delivery unprovable; retry budget exhausted")
    op.update(state="fenced", needs_new_attempt=True)
    store.commit(state)
    return state


def _advance_dispatch(store: Any, state: dict[str, Any], op: dict[str, Any], rt: RuntimePort) -> dict[str, Any]:
    op["state"] = "in_flight"
    if op["stage"] == "session_pending":
        if op["create_started"]:
            found = rt.find_sessions(op["marker"])
            if len(found) > 1:
                return _block(store, state, op, f"{len(found)} sessions carry marker {op['marker']}")
            if len(found) == 1:
                op.update(stage="session_created", session_id=found[0])
                store.commit(state)
            elif not rt.session_list_consistent:
                return _block(store, state, op, "no session found and runtime listing is not proven consistent")
        if op["stage"] == "session_pending":
            op["create_started"] = True
            store.commit(state)
            try:
                sid = rt.create_session(op["marker"])
            except ResponseUnknown:
                return _advance_dispatch(store, state, op, rt)
            op.update(stage="session_created", session_id=sid)
            store.commit(state)
    if op["stage"] == "session_created":
        op["stage"] = "prompt_sending"
        store.commit(state)
        try:
            mid = rt.send_prompt(op["session_id"], _prompt_text(op))
        except ResponseUnknown:
            return _recover_prompt(store, state, op, rt)
        op.update(stage="prompt_accepted", state="running", native_message_id=mid,
                  receipt=_receipt(store, {"session": op["session_id"], "message": mid, "source": "send"}))
        store.commit(state)
        return state
    if op["stage"] == "prompt_sending":
        return _recover_prompt(store, state, op, rt)
    return state


def advance(store: Any, state: dict[str, Any], op_id: str, github: GitHubPort | None = None,
            runtime: RuntimePort | None = None) -> dict[str, Any]:
    """Drive one operation from its persisted state; safe to call again after any crash."""
    op = state["operations"][op_id]
    if op["state"] in TERMINAL or (op["kind"] == "dispatch" and op["stage"] == "prompt_accepted"):
        return state
    if op["kind"] == "dispatch":
        if runtime is None:
            raise ValueError("dispatch needs a runtime adapter")
        return _advance_dispatch(store, state, op, runtime)
    if github is None:
        raise ValueError(f"{op['kind']} needs a GitHub adapter")
    return _advance_comment(store, state, op, github)
