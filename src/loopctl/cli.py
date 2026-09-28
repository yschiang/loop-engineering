"""loopctl CLI entry (design §2).

stdout is one JSON object {ok, revision, result, blocked, next, safety}.
Exit codes: 0 ok, 1 rejected, 2 usage, 3 Blocked, 4 not_owner, 5 state untrusted.
Each task adds only its own subcommands here (tasks.md shared-file table).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from loopctl import (
    assignments,
    clock,
    decisions,
    evidence,
    gates,
    observe,
    preflight,
    state,
    store,
    writes,
)
from loopctl import next as next_step

EXIT_OK, EXIT_REJECTED, EXIT_USAGE, EXIT_BLOCKED, EXIT_UNTRUSTED = 0, 1, 2, 3, 5
EXIT_NOT_OWNER = 4


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        raise _UsageError(message)


def envelope(
    ok: bool,
    result: Any = None,
    blocked: Any = None,
    next_: Any = None,
    revision: Any = None,
    safety: Any = None,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "revision": revision,
        "result": result,
        "blocked": blocked,
        "next": next_,
        "safety": safety,
    }


def human(blockers: list[str], decision_kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": decision_kinds or []}


def _herdr_session(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise argparse.ArgumentTypeError(f"invalid session name {value!r} (want [A-Za-z0-9._-]+)")
    return value


def _feature_id(value: str) -> str:
    if not store.FEATURE_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(f"invalid feature id {value!r}")
    return value


def _parser() -> _Parser:
    parser = _Parser(prog="loopctl", description="Thin delivery-loop controller.")
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status", help="read-only: phase, gates, blockers, next and safety actions")
    st.add_argument("--feature", type=_feature_id, help="feature id (default: none, empty state)")
    st.add_argument("--human", action="store_true", help="add a readable rendering (result.human)")
    nx = sub.add_parser("next", help="read-only: the next allowed action (design §2 vocabulary)")
    nx.add_argument("--feature", required=True, type=_feature_id)
    it = sub.add_parser("init", help="create a feature from a direct user hand-off")
    it.add_argument("--repo", required=True)
    it.add_argument("--repo-id", required=True)
    it.add_argument("--feature", required=True, type=_feature_id)
    it.add_argument("--issue", required=True)
    cl = sub.add_parser("claim", help="take coordination; the token is printed once")
    cl.add_argument("--feature", required=True, type=_feature_id)
    cl.add_argument("--actor", required=True)
    rg = sub.add_parser("register", help="register a native artifact: locator, version, digest")
    rg.add_argument("kind", choices=decisions.REGISTER_KINDS)
    rg.add_argument("--feature", required=True, type=_feature_id)
    rg.add_argument("--token")
    rg.add_argument("--locator", required=True, help="native path, recorded as given")
    rg.add_argument("--version", required=True)
    rg.add_argument("--digest", help="required when the locator is not a readable file")
    rg.add_argument("--producer", choices=decisions.PRODUCERS, help="plan only")
    rg.add_argument("--calibrated-from", help="plan only: calibration source")
    rg.add_argument("--role", choices=decisions.BINDING_ROLES, help="binding only")
    dc = sub.add_parser("decide", help="record a human decision (first-slice kinds only)")
    dc.add_argument("kind")
    dc.add_argument("--feature", type=_feature_id)
    dc.add_argument("--token")
    dc.add_argument("--id", help="decision id; resending the same decision is idempotent")
    dc.add_argument("--actor", help="human:<name>; any other identity is rejected")
    dc.add_argument("--target")
    dc.add_argument("--version")
    dc.add_argument("--reason")
    dc.add_argument("--evidence", help="evidence file, stored as a content-addressed object")
    dc.add_argument("--bind", help="resolve_operation: the observed result to bind")
    dc.add_argument("--not-delivered", action="store_true", help="resolve_operation")
    dc.add_argument("--category", help="reclassify_finding")
    wr = sub.add_parser("write", help="one external write op with a fixed argv (design §4)")
    wr.add_argument("op", help=f"op kind: {', '.join(writes.KINDS)}")
    wr.add_argument("--feature", required=True, type=_feature_id)
    wr.add_argument("--token")
    wr.add_argument("--id", required=True, dest="op_id", help="op id, as given by next/safety")
    rs = sub.add_parser("result", help="import a worker result (design §8 envelope)")
    rs_sub = rs.add_subparsers(dest="result_command", required=True)
    ri = rs_sub.add_parser("import", help="import the result of one attempt")
    ri.add_argument("--feature", required=True, type=_feature_id)
    ri.add_argument("--token")
    ri.add_argument("--attempt", required=True)
    ri.add_argument("--file", help="result file (default: the assignment's result location)")
    sf = sub.add_parser("safety", help="read-only: actions that must come first (design §2, §10)")
    sf.add_argument("--feature", required=True, type=_feature_id)
    ob = sub.add_parser("observe", help="bounded read-only fetch (design §5)")
    ob.add_argument("source", help=f"source: {', '.join(observe.SOURCES)}")
    ob.add_argument("--feature", required=True, type=_feature_id)
    ob.add_argument("--token")
    ob.add_argument("--attempt", required=True)
    ob.add_argument("--purpose", help="default: the source's general purpose")
    ev = sub.add_parser("evidence", help="run a policy evidence command (design §7)")
    ev_sub = ev.add_subparsers(dest="evidence_command", required=True)
    er = ev_sub.add_parser("red", help="worker: capture a Red in the attempt's worktree")
    er.add_argument("--feature", required=True, type=_feature_id)
    er.add_argument("--attempt", required=True)
    er.add_argument("--command-id", required=True, help="a command id of workflow.yaml evidence.commands")
    er.add_argument("--finding", action="append", default=[], help="correction attempts: a finding this Red covers")
    eg = ev_sub.add_parser("green", help="coordinator: run Green in a clean checkout of the feature head")
    eg.add_argument("--feature", required=True, type=_feature_id)
    eg.add_argument("--token")
    asg = sub.add_parser("assess", help="compute the gates (G1) at the current feature head")
    asg.add_argument("--feature", required=True, type=_feature_id)
    asg.add_argument("--token")
    pf = sub.add_parser("preflight", help="capability probe of a selected profile (design §6)")
    pf.add_argument("--role", required=True, choices=preflight.ROLES)
    pf.add_argument("--out", required=True, type=Path, help="receipt JSON path")
    pf.add_argument(
        "--herdr-session",
        type=_herdr_session,
        help="named Herdr session for every Herdr control call (default: the caller's session)",
    )
    return parser


Outcome = tuple[int, dict[str, Any]]


def _not_found(feature: str) -> Outcome:
    return EXIT_REJECTED, envelope(
        False,
        result={"error": "feature_not_found", "feature": feature},
        next_=human([f"feature_not_found:{feature}"]),
    )


def _rejected(error: str, revision: Any = None, **detail: Any) -> Outcome:
    return EXIT_REJECTED, envelope(
        False, result={"error": error, **detail}, revision=revision, next_=human([error])
    )


def _store_failure(feature: str, e: store.StoreError) -> Outcome:
    if isinstance(e, store.FeatureNotFound):
        return _not_found(feature)
    if isinstance(e, store.UntrustedState):
        reasons = [f"untrusted_state:{e}"]
        return EXIT_UNTRUSTED, envelope(
            False,
            result={"error": "untrusted_state", "feature": feature, "reason": str(e)},
            blocked={"reasons": reasons},
            next_=human(reasons),
        )
    if isinstance(e, store.TransitionConflict):
        reasons = [f"transition_conflict:{t}" for t in store.conflicts(feature)]
        return EXIT_BLOCKED, envelope(
            False,
            result={"error": "transition_conflict", "feature": feature},
            blocked={"reasons": reasons},
            next_=human(reasons),
        )
    if isinstance(e, store.RevisionConflict):
        return _rejected("revision_conflict", feature=feature, message=str(e))
    return _rejected(type(e).__name__, feature=feature, message=str(e))


def _read(args: argparse.Namespace) -> Outcome:
    """status/next for one feature: read-only, never creates or repairs state."""
    try:
        revision, st = store.load(args.feature)
        blocked = state.blockers(st, store.conflicts(args.feature))
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    action = next_step.next_action(st, blocked)
    result = state.view(st, blocked)
    if getattr(args, "human", False):
        result["human"] = state.render_human(result, revision, action)
    if args.command == "next":
        result = {"feature": args.feature, "phase": st["phase"]}
    if blocked:
        return EXIT_BLOCKED, envelope(
            False, result=result, revision=revision, blocked={"reasons": blocked}, next_=action
        )
    return EXIT_OK, envelope(True, result=result, revision=revision, next_=action)


def _status(args: argparse.Namespace) -> Outcome:
    if args.feature is not None:
        return _read(args)
    return EXIT_OK, envelope(
        True, result={"phase": "empty", "feature": None}, next_=human(["no_feature"])
    )


def _init(args: argparse.Namespace) -> Outcome:
    new = state.new_feature(args.repo, args.repo_id, args.issue)
    tid = "init:" + store.digest(json.dumps(new, sort_keys=True).encode())
    try:
        store.load(args.feature)
    except store.FeatureNotFound:
        pass
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    else:
        return _rejected("feature_exists", feature=args.feature)
    try:
        revision = store.commit(args.feature, 0, tid, lambda _: new)
    except store.RevisionConflict:
        return _rejected("feature_exists", feature=args.feature)
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    return EXIT_OK, envelope(
        True,
        result={"feature": args.feature, "phase": new["phase"]},
        revision=revision,
        next_=next_step.next_action(new, []),
    )


class _Rejected(Exception):
    pass


def _claim(args: argparse.Namespace) -> Outcome:
    token = state.new_token()
    owner = {"actor": args.actor, "token_digest": state.token_digest(token)}

    def take(st: state.State) -> state.State:
        if st.get("owner"):
            raise _Rejected(st["owner"]["actor"])
        return {**st, "owner": owner}

    try:
        while True:  # a lost race reloads, so the loser sees who owns it
            revision, _ = store.load(args.feature)
            try:
                revision = store.commit(
                    args.feature, revision, f"claim:{owner['token_digest']}", take
                )
                break
            except store.RevisionConflict:
                continue
    except _Rejected as e:
        return _rejected("already_claimed", feature=args.feature, owner=str(e))
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    return EXIT_OK, envelope(
        True,
        result={"feature": args.feature, "actor": args.actor, "token": token},
        revision=revision,
    )


def _not_owner(feature: str, revision: int) -> Outcome:
    return EXIT_NOT_OWNER, envelope(
        False,
        result={"error": "not_owner", "feature": feature},
        revision=revision,
        next_=human(["not_owner"]),
    )


def _commit_latest(feature: str, tid: Any, mutate: Any) -> int:
    """Commit on the latest revision; a lost revision race reloads and applies again."""
    while True:
        revision, _ = store.load(feature)
        try:
            return store.commit(feature, revision, tid(revision), mutate)
        except store.RevisionConflict:
            continue


def _after(feature: str, result: dict[str, Any]) -> Outcome:
    revision, st = store.load(feature)
    blocked = state.blockers(st, store.conflicts(feature))
    return EXIT_OK, envelope(
        True, result=result, revision=revision, next_=next_step.next_action(st, blocked)
    )


def _read_file(locator: str) -> bytes | None:
    path = Path(locator)
    return path.read_bytes() if path.is_file() else None


def _register(args: argparse.Namespace) -> Outcome:
    try:
        revision, st = store.load(args.feature)
        if not state.is_owner(st, args.token):
            return _not_owner(args.feature, revision)
        data = _read_file(args.locator)
        if args.digest is not None and not decisions.valid_digest(args.digest):
            raise decisions.Rejected("invalid_digest", digest=args.digest)
        if data is None and args.digest is None:
            raise decisions.Rejected("locator_unreadable", locator=args.locator)
        found = store.digest(data) if data is not None else args.digest
        if args.digest is not None and found != args.digest:
            raise decisions.Rejected("digest_mismatch", expected=args.digest, found=found)
        entry = decisions.artifact(
            args.kind,
            locator=args.locator,
            version=args.version,
            digest=found,
            content=store.object_ref(store.put_object(data)) if data is not None else None,
            producer=args.producer,
            calibrated_from=args.calibrated_from,
            role=args.role,
        )
        key = store.digest(json.dumps(entry, sort_keys=True).encode())[7:23]
        _commit_latest(
            args.feature,
            lambda rev: f"register:{args.kind}:{rev}:{key}",
            lambda s: decisions.register(s, args.kind, entry),
        )
        _, new = store.load(args.feature)
    except decisions.Rejected as e:
        return _rejected(e.error, revision=revision, feature=args.feature, **e.detail)
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    invalidated = st.get("approval") is not None and new.get("approval") is None
    return _after(
        args.feature,
        {"feature": args.feature, args.kind: entry, "approval_invalidated": invalidated},
    )


def _decide(args: argparse.Namespace) -> Outcome:
    fields = {
        k: getattr(args, k)
        for k in ("feature", "id", "actor", "target", "version", "reason", "evidence", "bind")
    }
    fields |= {"not_delivered": args.not_delivered, "category": args.category}
    revision = None
    try:
        rec = decisions.request(args.kind, fields)
        revision, st = store.load(args.feature)
        if not state.is_owner(st, args.token):
            return _not_owner(args.feature, revision)
        if args.evidence:
            data = _read_file(args.evidence)
            if data is None:
                raise decisions.Rejected("evidence_unreadable", evidence=args.evidence)
            rec["evidence"] = store.object_ref(store.put_object(data))
        if rec["id"] in st["decisions"]:
            raise decisions.Duplicate(st["decisions"][rec["id"]])
        at = clock.now().isoformat()
        _commit_latest(
            args.feature,
            lambda _: f"decide:{rec['id']}@{at}",
            lambda s: decisions.decide(s, rec, at),
        )
    except decisions.Rejected as e:
        code = EXIT_USAGE if e.error == "unsupported" else EXIT_REJECTED
        return code, envelope(
            False, result={"error": e.error, **e.detail}, revision=revision, next_=human([e.error])
        )
    except decisions.Duplicate as d:
        if not decisions.same(d.record, rec):
            return _rejected("decision_id_conflict", revision=revision, id=rec["id"])
        return _after(args.feature, {"decision": d.record, "duplicate": True})
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    decided = store.load(args.feature)[1]["decisions"][rec["id"]]
    return _after(args.feature, {"decision": decided, "duplicate": False})


def _effect_failure(feature: str, e: observe.Rejected) -> Outcome:
    """A refused or blocked write/observe/import: the error, plus the state's own next."""
    revision, blocked, next_ = None, None, human([e.error])
    if e.code not in (EXIT_USAGE, EXIT_NOT_OWNER):
        try:
            revision, st = store.load(feature)
            reasons = state.blockers(st, store.conflicts(feature))
            blocked = {"reasons": reasons} if reasons else None
            next_ = next_step.next_action(st, reasons)
        except store.StoreError:
            pass
    return e.code, envelope(
        False, result={"error": e.error, **e.detail}, revision=revision, blocked=blocked, next_=next_
    )


def _effect(feature: str, run: Any) -> Outcome:
    try:
        result = run()
    except observe.Rejected as e:
        return _effect_failure(feature, e)
    except store.StoreError as e:
        return _store_failure(feature, e)
    return _after(feature, result)


def _write(args: argparse.Namespace) -> Outcome:
    return _effect(
        args.feature,
        lambda: writes.write(args.feature, args.token, args.op, args.op_id, assignments.op_spec),
    )


def _result(args: argparse.Namespace) -> Outcome:
    return _effect(
        args.feature,
        lambda: assignments.import_result(args.feature, args.token, args.attempt, args.file),
    )


def _observe(args: argparse.Namespace) -> Outcome:
    return _effect(
        args.feature,
        lambda: observe.observe(args.feature, args.token, args.source, args.attempt, args.purpose),
    )


def _evidence(args: argparse.Namespace) -> Outcome:
    if args.evidence_command == "red":
        return _effect(
            args.feature,
            lambda: evidence.red(args.feature, args.attempt, args.command_id, args.finding, Path.cwd()),
        )
    return _effect(args.feature, lambda: evidence.green(args.feature, args.token))


def _assess(args: argparse.Namespace) -> Outcome:
    return _effect(args.feature, lambda: gates.assess(args.feature, args.token))


def _safety(args: argparse.Namespace) -> Outcome:
    """Read-only: the action that must come before any other (readback, recovery), or null."""
    try:
        revision, st = store.load(args.feature)
        blocked = state.blockers(st, store.conflicts(args.feature))
    except store.StoreError as e:
        return _store_failure(args.feature, e)
    first = next_step.safety_action(st, blocked)
    return (EXIT_BLOCKED if blocked else EXIT_OK), envelope(
        not blocked,
        result={"feature": args.feature, "phase": st["phase"]},
        revision=revision,
        blocked={"reasons": blocked} if blocked else None,
        safety=first,
    )


def _preflight(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    receipt = preflight.run(args.role, args.out, Path.cwd(), args.herdr_session)
    result = {"receipt": str(args.out), "verdict": receipt["verdict"]}
    if receipt["verdict"] == "verified":
        return EXIT_OK, envelope(True, result=result)
    reasons = receipt["reasons"]
    return EXIT_BLOCKED, envelope(
        False, result=result, blocked={"reasons": reasons}, next_=human(reasons)
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _UsageError as e:
        code, out = EXIT_USAGE, envelope(False, result={"error": "usage", "message": str(e)})
    except SystemExit as e:  # --help
        return int(e.code or 0)
    else:
        code, out = {
            "status": _status,
            "preflight": _preflight,
            "init": _init,
            "claim": _claim,
            "next": _read,
            "register": _register,
            "decide": _decide,
            "write": _write,
            "result": _result,
            "safety": _safety,
            "observe": _observe,
            "evidence": _evidence,
            "assess": _assess,
        }[args.command](args)
    sys.stdout.write(json.dumps(out) + "\n")
    return code
