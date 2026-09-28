"""loopctl CLI entry (design §2).

stdout is one JSON object {ok, revision, result, blocked, next, safety}.
Exit codes: 0 ok, 1 rejected, 2 usage, 3 Blocked, 4 not_owner, 5 state untrusted.
Each task adds only its own subcommands here (tasks.md shared-file table).
"""

import argparse
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from loopctl import next as next_step
from loopctl import preflight, state, store

EXIT_OK, EXIT_REJECTED, EXIT_USAGE, EXIT_BLOCKED, EXIT_UNTRUSTED = 0, 1, 2, 3, 5


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
    token = secrets.token_urlsafe(32)
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
        }[args.command](args)
    sys.stdout.write(json.dumps(out) + "\n")
    return code
