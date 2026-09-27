"""`delivery` command line entry point (design §1)."""

import argparse
import sys
from pathlib import Path

# Commands whose behavior lands in later S1 tasks exit 2 with an explicit message instead of pretending success.
COMMANDS = {
    "init": "initialise workflow.yaml and .delivery/ for a repo",
    "start": "start a feature run under the feature authority",
    "adopt": "adopt an existing feature after owner handoff",
    "status": "show phase, gates, blockers and next action",
    "resume": "resume a run after reconciling external facts",
    "decide": "record a human decision (run outside worker sandboxes)",
    "reconcile": "import results and converge pending operations",
    "preflight": "check the selected runtime/sandbox profile",
    "evidence": "run a command and capture evidence",
    "submit-result": "submit a worker result into its inbox",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delivery", description="Orca delivery controller")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text)
        if name == "status":
            cmd.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help()
        return 2
    if args.command == "status":
        from delivery.publication import render_status
        from delivery.store import Store

        loaded = Store(args.run_dir).load()
        print(render_status(loaded.state))
        if loaded.blocked:
            print("state not trusted: " + "; ".join(loaded.reasons))
            return 1
        return 0
    print(f"delivery {args.command}: not available in this build", file=sys.stderr)
    return 2
