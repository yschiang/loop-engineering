"""loopctl command line: parse, dispatch, print one JSON envelope (D2)."""

from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import json
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from loopctl import clock, decisions, preflight, state, store
from loopctl.next import unresolved

Envelope = dict[str, Any]
Handler = Callable[[argparse.Namespace], tuple[int, Envelope]]

EXIT_USAGE = 2
EXIT_BLOCKED = 3


def envelope(
    ok: bool,
    result: dict[str, Any],
    *,
    revision: int | None = None,
    blocked: Any = None,
    next: Any = None,
) -> Envelope:
    """The one output shape of every command; `safety` is always null here."""
    return {
        "ok": ok,
        "revision": revision,
        "result": result,
        "blocked": blocked,
        "next": next,
        "safety": None,
    }


def _key(args: argparse.Namespace) -> store.Key:
    return args.repo, args.feature


def refusal(code: int, error: str, **fields: Any) -> tuple[int, Envelope]:
    return code, envelope(False, {"error": error, **fields})


class NotOwner(Exception):
    """The token is missing or is not the owner's: exit 4 `not_owner`."""


def owner_token(token: str | None) -> Callable[[store.State], None]:
    """`authorize` for register and decide: `token` must be the owner's claim
    token. The store runs it before any other check or write (D4 step 2)."""

    def authorize(st: store.State) -> None:
        owner = st["owner"]
        if (
            token is None
            or owner is None
            or not hmac.compare_digest(state.token_digest(token), owner["token_digest"])
        ):
            raise NotOwner()

    return authorize


def guarded(handler: Handler) -> Handler:
    """Turn the refusals of the store and of a state check, and the I/O
    errors of the store, into envelopes."""

    def run(args: argparse.Namespace) -> tuple[int, Envelope]:
        try:
            return handler(args)
        except store.IOFailure as error:
            return refusal(
                6,
                "io_error",
                op=error.op,
                errno=errno.errorcode.get(error.errno) if error.errno else None,
                committed=error.committed,
            )
        except store.RunNotFound:
            return refusal(1, "run_not_found")
        except store.RunExists:
            return refusal(1, "run_exists")
        except store.UntrustedState as error:
            return refusal(
                5, "untrusted_state", reason=error.reason, files=error.files
            )
        except store.TransitionConflict as error:
            return refusal(
                EXIT_BLOCKED,
                "transition_conflict",
                blockers=conflict_blockers(error.conflicts),
                files=error.files,
            )
        except store.TransitionRejected as error:
            return refusal(1, f"transition_rejected:{error.cid}")
        except store.UnknownTarget:
            return refusal(1, "unknown_target")
        except state.AlreadyClaimed as error:
            return refusal(1, "already_claimed", owner=error.owner)
        except NotOwner:
            return refusal(4, "not_owner")
        except decisions.Unsupported as error:
            return refusal(EXIT_USAGE, "unsupported", kind=error.kind)
        except decisions.Rejected as error:
            return refusal(1, error.error, **error.fields)

    return run


def init(args: argparse.Namespace) -> tuple[int, Envelope]:
    # An existing run, trusted or not, is never overwritten or recreated.
    try:
        store.load(_key(args))
    except store.RunNotFound:
        pass
    else:
        return refusal(1, "run_exists")
    payload = {
        "repo": args.repo,
        "feature": args.feature,
        "issue": args.issue,
        "actor": args.actor,
    }
    initial = state.initial(
        args.repo, args.feature, args.issue, args.actor, clock.now()
    )
    revision = store.create(_key(args), "init", payload, initial)
    result = {"coordinator": initial["coordinator"]}
    return 0, envelope(True, result, revision=revision)


def unchecked(st: store.State) -> None:
    """`authorize` for claim: its own check (no owner yet) is in mutate."""


def commit_latest(
    key: store.Key,
    transition_id: str,
    payload: Any,
    mutate: Callable[[store.State], store.State],
    *,
    authorize: Callable[[store.State], None],
    resolves: str | None = None,
) -> store.Revision:
    """Commit at the current revision; when another transition went first,
    re-read and redo, so every check runs on the latest state (D4)."""
    while True:
        expected, _ = store.load(key)
        try:
            return store.commit(
                key, expected, transition_id, payload, mutate,
                authorize=authorize, resolves=resolves,
            )
        except store.RevisionConflict:
            continue


def claim(args: argparse.Namespace) -> tuple[int, Envelope]:
    token = secrets.token_hex(32)
    owner = {
        "actor": args.actor,
        "token_digest": state.token_digest(token),
        "claimed_at": clock.now(),
    }
    revision = commit_latest(
        _key(args),
        f"claim:{owner['token_digest']}",
        {"actor": args.actor},
        lambda st: state.claim(st, owner),
        authorize=unchecked,
    )
    result = {"token": token, "owner": state.owner_view(owner)}
    return 0, envelope(True, result, revision=revision)


def conflict_blockers(cids: list[str]) -> list[str]:
    return [f"transition_conflict:{cid}" for cid in cids]


def reading(
    key: store.Key, revision: int, st: store.State, result: dict[str, Any]
) -> tuple[int, Envelope]:
    """What status and next answer: exit 3 with the files of the run while a
    conflict is unresolved (D6), else exit 0."""
    if unresolved(st):
        result = {**result, "error": "transition_conflict", "files": store.files(key)}
        return EXIT_BLOCKED, envelope(
            False, result, revision=revision, next=st["next"]
        )
    return 0, envelope(True, result, revision=revision, next=st["next"])


def _policy_digest(st: store.State) -> str | None:
    """The digest of the registered policy file as it is now, read only
    (D11); None when there is none or it cannot be read."""
    policy = st["versions"]["policy"]
    if policy is None or policy.get("path") is None:
        return None
    content = _read(Path(policy["path"]))
    return None if content is None else "sha256:" + hashlib.sha256(content).hexdigest()


def status(args: argparse.Namespace) -> tuple[int, Envelope]:
    revision, st = store.load(_key(args))
    result = state.view(revision, st, _policy_digest(st))
    if args.human:
        result["human"] = state.human(result, st["next"])
    return reading(_key(args), revision, st, result)


def next_step(args: argparse.Namespace) -> tuple[int, Envelope]:
    revision, st = store.load(_key(args))
    result = {"phase": st["phase"], "blockers": st["blockers"]}
    return reading(_key(args), revision, st, result)


def decide(args: argparse.Namespace) -> tuple[int, Envelope]:
    payload = decisions.request(
        args.kind,
        {
            "id": args.id,
            "actor": args.actor,
            "target": args.target,
            "reason": args.reason,
            "source": args.source,
            "impact": args.impact,
            "version": args.version,
            "choice": args.choice,
            "open_questions": args.open_question,
        },
    )
    at = clock.now()
    revision = commit_latest(
        _key(args),
        f"decide:{payload['id']}",
        payload,
        lambda st: decisions.decide(st, payload, at),
        authorize=owner_token(args.token),
        # Only resolve_conflict goes through while its conflict blocks the run.
        resolves=payload["target"] if payload["kind"] == "resolve_conflict" else None,
    )
    # A duplicate answers with the record accepted for this id (D5).
    st = revision.state
    result = {
        "decision": st["decisions"][payload["id"]],
        "duplicate": revision.duplicate,
    }
    return 0, envelope(True, result, revision=int(revision), next=st["next"])


def _read(path: Path) -> bytes | None:
    """The bytes of a readable regular file, else None."""
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _content(args: argparse.Namespace) -> tuple[bytes, str | None]:
    """What `register` adopts (D9): the locator when it is a readable local
    file, relative to the cwd, else `--content-from`; with the locator's
    absolute path when it is that file. A policy is re-read from its own
    file (D11), so it never takes `--content-from`."""
    if args.kind == "policy" and args.content_from is not None:
        raise decisions.Rejected("locator_unreadable")
    locator = Path(args.locator)
    content = _read(locator)
    if content is not None:
        return content, str(locator.resolve())
    if args.content_from is not None:
        content = _read(Path(args.content_from))
        if content is not None:
            return content, None
    raise decisions.Rejected("locator_unreadable")


def register(args: argparse.Namespace) -> tuple[int, Envelope]:
    """`register plan|binding|policy` in the order of D9: the checks that need
    no state, the owner's token before anything is written, the content
    stored, then the commit, which checks the token again."""
    content, path = _content(args)
    payload = decisions.registration(
        args.kind,
        {
            "locator": args.locator,
            "path": path,
            "version": args.version,
            "source": args.source,
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "role": args.role,
            "producer": args.producer,
            "calibrated_from": args.calibrated_from,
        },
    )
    key, authorize = _key(args), owner_token(args.token)
    # A missing run, an untrusted state or a caller without the token is
    # refused before anything is written, the object included.
    _, current = store.load(key)
    authorize(current)
    store.put_object(content)
    at = clock.now()
    # As commit_latest, with the revision in the transition id (D5); the
    # commit is a no-op, and `unchanged`, for the same registration (D9).
    while True:
        expected, _ = store.load(key)
        try:
            revision = store.commit(
                key, expected, f"register:{expected}:{store.digest(payload)}",
                payload, lambda st: decisions.register(st, payload, at),
                authorize=authorize,
            )
        except store.RevisionConflict:
            continue
        # A duplicate means another caller committed this registration at
        # `expected` first; the store answers that before it checks the
        # revision (D4 step 3), so it is a stale revision too: redo it on
        # the latest state.
        if not revision.duplicate:
            break
    st = revision.state
    entry = decisions.registered(st, payload) or {}
    result = {name: value for name, value in entry.items() if name != "content"}
    result["unchanged"] = revision == expected
    return 0, envelope(True, result, revision=int(revision), next=st["next"])


def unsupported(args: argparse.Namespace) -> tuple[int, Envelope]:
    """`adopt` and `delegate`: not in this version; nothing is read or written."""
    return refusal(EXIT_USAGE, "unsupported", command=args.command)


def probe(args: argparse.Namespace) -> tuple[int, Envelope]:
    """`preflight`: probe the profile of `--role` for the run (DD-3); one
    preflight of a role at a time."""
    try:
        return preflight.run(_key(args), args.role, args.out)
    except store.Busy:
        return refusal(1, "preflight_running")


HANDLERS: dict[str, Handler] = {
    "init": guarded(init),
    "claim": guarded(claim),
    "status": guarded(status),
    "next": guarded(next_step),
    "register": guarded(register),
    "decide": guarded(decide),
    "preflight": guarded(probe),
    "adopt": unsupported,
    "delegate": unsupported,
}


class UsageError(Exception):
    """A command line the parser rejects; reported as exit 2 `usage`."""


class HelpExit(Exception):
    """`--help` was printed; main returns `status`."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class Parser(argparse.ArgumentParser):
    """argparse that raises instead of writing to stderr and exiting."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise HelpExit(status)


SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def repo_name(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 2 or not all(SEGMENT.fullmatch(part) for part in parts):
        raise argparse.ArgumentTypeError(f"expected owner/name, got {value!r}")
    return value


def feature_id(value: str) -> str:
    if not SEGMENT.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"expected a single path segment, got {value!r}"
        )
    return value


def _run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, type=repo_name, help="owner/name")
    parser.add_argument("--feature", required=True, type=feature_id)


def build_parser() -> Parser:
    parser = Parser(
        prog="loopctl",
        description="Durable run state and human decisions for one repo and feature.",
    )
    commands = parser.add_subparsers(dest="command", metavar="command", required=True)

    init = commands.add_parser("init", help="start a run for a repo and feature")
    _run_options(init)
    init.add_argument("--issue", required=True)
    init.add_argument("--actor", required=True)

    claim = commands.add_parser("claim", help="take the coordination right")
    _run_options(claim)
    claim.add_argument("--actor", required=True)

    status = commands.add_parser("status", help="show the run state")
    _run_options(status)
    status.add_argument("--human", action="store_true")

    nxt = commands.add_parser("next", help="show the one allowed next step")
    _run_options(nxt)

    register = commands.add_parser("register", help="register a native document")
    register.add_argument("kind", choices=["plan", "binding", "policy"])
    _run_options(register)
    register.add_argument("--token")
    register.add_argument("--locator", required=True)
    register.add_argument("--version", required=True)
    register.add_argument("--source", required=True)
    register.add_argument("--content-from")
    register.add_argument("--role", choices=["spec", "ac", "design", "sa"])
    register.add_argument("--producer", choices=["implementer", "project_lead"])
    register.add_argument("--calibrated-from")

    decide = commands.add_parser("decide", help="record a human decision")
    decide.add_argument("kind")
    _run_options(decide)
    decide.add_argument("--token")
    decide.add_argument("--id")
    decide.add_argument("--actor")
    decide.add_argument("--target")
    decide.add_argument("--reason")
    decide.add_argument("--source")
    decide.add_argument("--impact")
    decide.add_argument("--version")
    decide.add_argument("--choice")
    decide.add_argument("--open-question", action="append")

    probe = commands.add_parser(
        "preflight", help="probe a worker profile of the approved policy"
    )
    _run_options(probe)
    probe.add_argument("--role", required=True, choices=["implementer", "reviewer"])
    probe.add_argument("--out", type=Path)

    commands.add_parser("adopt", help="unsupported in this version")
    commands.add_parser("delegate", help="unsupported in this version")
    return parser


PASSTHROUGH = ("adopt", "delegate")
HELP = {"-h", "--help"}


def parse(argv: list[str]) -> argparse.Namespace:
    """Parse argv; `adopt` and `delegate` keep every other argument in `rest`.

    Their tail never reaches argparse, which would read `-host` as `-h` and
    reject `--help=foo`; only an exact `-h` or `--help` prints their usage.
    """
    parser = build_parser()
    if argv and argv[0] in PASSTHROUGH:
        command, rest = argv[0], argv[1:]
        if HELP.intersection(rest):
            parser.parse_args([command, "--help"])  # raises HelpExit
        return argparse.Namespace(command=command, rest=rest)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse(sys.argv[1:] if argv is None else argv)
    except HelpExit as done:
        return done.status
    except UsageError as error:
        code = EXIT_USAGE
        out = envelope(False, {"error": "usage", "message": str(error)})
    else:
        code, out = HANDLERS[args.command](args)
    print(json.dumps(out, ensure_ascii=False))
    return code
