"""loopctl CLI entry (design §2).

stdout is one JSON object {ok, revision, result, blocked, next, safety}.
Exit codes: 0 ok, 1 rejected, 2 usage, 3 Blocked, 4 not_owner, 5 state untrusted.
Each task adds only its own subcommands here (tasks.md shared-file table).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from loopctl import preflight

EXIT_OK, EXIT_USAGE, EXIT_BLOCKED = 0, 2, 3


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


def _parser() -> _Parser:
    parser = _Parser(prog="loopctl", description="Thin delivery-loop controller.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="read-only: phase, gates, blockers, next and safety actions")
    pf = sub.add_parser("preflight", help="capability probe of a selected profile (design §6)")
    pf.add_argument("--role", required=True, choices=preflight.ROLES)
    pf.add_argument("--out", required=True, type=Path, help="receipt JSON path")
    return parser


def _status(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    # ponytail: no feature store until T2.1, so the state is always empty here.
    return EXIT_OK, envelope(
        True, result={"phase": "empty", "feature": None}, next_=human(["no_feature"])
    )


def _preflight(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    receipt = preflight.run(args.role, args.out, Path.cwd())
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
        code, out = {"status": _status, "preflight": _preflight}[args.command](args)
    sys.stdout.write(json.dumps(out) + "\n")
    return code
