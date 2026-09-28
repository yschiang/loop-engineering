"""Human decisions and native artifact registration (design §2 `register`, `decide`).

Owned only by T2.2. This module is the record layer: it validates a decision, records it
with actor, time, target, version and reason, and applies only the planning effects
(approve_plan, scope_change, re-registration of a bound artifact). The effects of
resolve_read, resolve_operation, budget_extension, accept, return and the finding kinds
belong to the modules that own those fields; they read `decisions` and are keyed by the
decision id, so a resent decision takes effect once.

Everything here is pure: file reads, objects and the clock stay at the CLI boundary, so
a transition's mutate is deterministic (store.commit replays compare bytes).
"""

import re
from typing import Any

State = dict[str, Any]

KINDS = (
    "approve_plan",
    "revise",
    "scope_change",
    "accept",
    "return",
    "resolve_finding",
    "waive_finding",
    "reclassify_finding",
    "resolve_operation",
    "resolve_read",
    "budget_extension",
    "policy_change",
    "handoff",
)
REGISTER_KINDS = ("plan", "binding", "policy")
PRODUCERS = ("implementer", "project_lead")
BINDING_ROLES = ("spec", "design", "ac", "sa", "skill", "baseline")
# Bindings an approval covers (design §8 version table); sa and baseline are not.
APPROVAL_ROLES = ("spec", "design", "ac", "skill")
# The plan fields an approval binds (AC-O06): any change needs a new approve_plan.
PLAN_BINDING = ("locator", "version", "digest", "producer", "calibrated_from")
CATEGORIES = ("spec_ac", "correctness_security", "missing_verification", "preference")
REQUIRED = ("feature", "id", "actor", "target", "version", "reason")
FINDING_KINDS = ("resolve_finding", "waive_finding", "reclassify_finding")

_HUMAN = re.compile(r"human:[A-Za-z0-9][A-Za-z0-9._@-]*")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_EXTENSION = re.compile(
    r"active:[1-9][0-9]*|rounds:\+1|attempts:[A-Za-z0-9][A-Za-z0-9._-]*:\+1|ci_wait:[0-9a-f]{40}"
)


class Rejected(Exception):
    def __init__(self, error: str, **detail: Any) -> None:
        super().__init__(error)
        self.error = error
        self.detail = detail


class Duplicate(Exception):
    """The decision id is already recorded; `record` is the committed one."""

    def __init__(self, record: dict[str, Any]) -> None:
        super().__init__(record["id"])
        self.record = record


def is_human(actor: str) -> bool:
    """Only `human:<name>` decides; agents, sessions and role markers never do (O19)."""
    return bool(_HUMAN.fullmatch(actor))


def request(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Checks that need no state; returns the record without time and sequence."""
    if kind not in KINDS:
        raise Rejected("unsupported", kind=kind)
    required = [*REQUIRED]
    if kind == "resolve_operation":
        required.append("evidence")
    if kind == "reclassify_finding":
        required.append("category")
    missing = [f for f in required if not fields.get(f)]
    if missing:
        raise Rejected("missing_fields", fields=missing)
    if not is_human(fields["actor"]):
        raise Rejected("actor_not_human", actor=fields["actor"])
    record = {"id": fields["id"], "kind": kind}
    record |= {f: fields[f] for f in ("actor", "target", "version", "reason")}
    if kind == "resolve_operation":
        if bool(fields.get("bind")) == bool(fields.get("not_delivered")):
            raise Rejected("resolution_required", options=["--bind", "--not-delivered"])
        record["resolution"] = (
            {"mode": "bind", "observed": fields["bind"]}
            if fields.get("bind")
            else {"mode": "not_delivered"}
        )
    if kind == "reclassify_finding":
        if fields["category"] not in CATEGORIES:
            raise Rejected("invalid_category", category=fields["category"])
        record["category"] = fields["category"]
    if kind == "budget_extension" and not _EXTENSION.fullmatch(fields["target"]):
        raise Rejected(
            "invalid_target",
            target=fields["target"],
            allowed=["active:<minutes>", "rounds:+1", "attempts:<unit>:+1", "ci_wait:<H>"],
        )
    return record


def same(committed: dict[str, Any], record: dict[str, Any]) -> bool:
    """A resend matches when every requested field equals the committed record."""
    return all(committed.get(k) == v for k, v in record.items())


def plan_approvable(plan: dict[str, Any] | None) -> bool:
    """A Project Lead draft or an uncalibrated plan is not an approvable plan (O22)."""
    return bool(plan and plan["producer"] == "implementer" and plan["calibrated_from"])


def plan_binding(plan: dict[str, Any]) -> dict[str, Any]:
    return {k: plan[k] for k in PLAN_BINDING}


def bound_digests(state: State) -> dict[str, str]:
    plan = state.get("plan")
    out = {"plan": plan["digest"]} if plan else {}
    bindings = state.get("versions", {}).get("bindings", {})
    out |= {role: b["digest"] for role, b in bindings.items() if role in APPROVAL_ROLES}
    return out


def _check(state: State, rec: dict[str, Any]) -> None:
    kind, target = rec["kind"], rec["target"]
    if kind == "approve_plan":
        plan = state.get("plan")
        if state["phase"] not in ("planning", "awaiting_approval"):
            raise Rejected("phase_not_awaiting_approval", phase=state["phase"])
        if plan is None:
            raise Rejected("plan_not_registered")
        if not plan_approvable(plan):
            raise Rejected("plan_not_calibrated", producer=plan["producer"])
        if (target, rec["version"]) != (plan["locator"], plan["version"]):
            raise Rejected(
                "plan_version_mismatch", registered=[plan["locator"], plan["version"]]
            )
    elif kind in ("accept", "return"):
        acceptance = state.get("acceptance") or {}
        if state["phase"] != "pass" or acceptance.get("status") != "pending":
            raise Rejected("no_pass", phase=state["phase"])
        if rec["version"] != acceptance.get("version_key"):
            raise Rejected("version_not_current", current=acceptance.get("version_key"))
    elif kind in FINDING_KINDS:
        if target not in state.get("findings", {}):
            raise Rejected("unknown_target", target=target)
    elif kind == "resolve_operation":
        if target not in state.get("writes", {}):
            raise Rejected("unknown_target", target=target)
    elif kind == "resolve_read":
        if target not in state.get("read_budget", {}):
            raise Rejected("unknown_target", target=target)
    elif kind == "policy_change":
        policy = state.get("versions", {}).get("policy")
        if policy is None:
            raise Rejected("policy_not_registered")
        if (target, rec["version"]) != (policy["locator"], policy["digest"]):
            raise Rejected("policy_digest_mismatch", registered=[policy["locator"], policy["digest"]])


def decide(state: State, rec: dict[str, Any], at: str) -> State:
    """The mutate of a decision transition: record it, then the planning effects only."""
    recorded = state.get("decisions", {})
    if rec["id"] in recorded:
        raise Duplicate(recorded[rec["id"]])
    _check(state, rec)
    new = {**state, "decisions": {**recorded, rec["id"]: {**rec, "at": at, "seq": len(recorded) + 1}}}
    if rec["kind"] == "approve_plan":
        plan = state["plan"]
        new["approval"] = {
            "decision": rec["id"],
            "plan": plan_binding(plan),
            "digests": bound_digests(state),
        }
        new["phase"] = "approved"
    elif rec["kind"] == "scope_change" and state["phase"] != "planning":
        # First slice: the whole run stops until a new approve_plan (O23 partial is S2).
        new["approval"] = None
        new["phase"] = "awaiting_approval"
    return new


def artifact(
    kind: str,
    *,
    locator: str,
    version: str,
    digest: str,
    content: dict[str, str] | None,
    producer: str | None = None,
    calibrated_from: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """A registration entry: the native locator as given, version, digest, content ref.

    A plan is registered only with readable content: dispatch and the gates read it back,
    so a digest never stands in for it (AC-O03, AC-O04)."""
    if kind == "plan" and not producer:
        raise Rejected("missing_fields", fields=["producer"])
    if kind == "plan" and content is None:
        raise Rejected("locator_unreadable", locator=locator)
    if kind == "binding" and not role:
        raise Rejected("missing_fields", fields=["role"])
    entry: dict[str, Any] = {
        "locator": locator, "version": version, "digest": digest, "content": content
    }
    if kind == "plan":
        entry |= {"producer": producer, "calibrated_from": calibrated_from}
    if kind == "binding":
        entry["role"] = role
    return entry


def register(state: State, kind: str, entry: dict[str, Any]) -> State:
    """The mutate of a registration. A changed plan binding, or a changed spec/design/AC/skill
    digest, revokes the approval: the run waits for a new approve_plan (design §8 version
    table)."""
    versions = dict(state.get("versions", {}))
    new = {**state}
    if kind == "plan":
        new["plan"] = entry
    elif kind == "binding":
        versions["bindings"] = {**versions.get("bindings", {}), entry["role"]: entry}
    else:
        versions["policy"] = entry
    new["versions"] = versions
    approval = state.get("approval")
    if approval and (
        plan_binding(new["plan"]) != approval["plan"] or bound_digests(new) != approval["digests"]
    ):
        new["approval"] = None
        new["phase"] = "awaiting_approval"
    return new


def valid_digest(value: str) -> bool:
    return bool(_DIGEST.fullmatch(value))
