"""Evidence commands (design §2, §7; T3.1): `evidence red` (worker), `evidence green`
(coordinator) and the diagnostic replay G1 runs on contradictory evidence.

Only policy commands run (`workflow.yaml` `evidence.commands`); `{junit_out}` is the only
placeholder and loopctl fills it. Tools are imported inside the effectful functions, so the
state core (`loopctl.next` → `loopctl.gates`) never loads subprocess.
"""

from pathlib import Path
from typing import Any

from loopctl.observe import Rejected

State = dict[str, Any]


def red(feature: str, attempt: str, command_id: str, findings: list[str], cwd: Path) -> dict[str, Any]:
    raise Rejected("not_implemented", 1)


def green(feature: str, token: str | None) -> dict[str, Any]:
    raise Rejected("not_implemented", 1)
