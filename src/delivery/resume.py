"""Resume: load state, check trust, recover history, converge operations, import results, re-read versions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def resume(run_dir: Path, github: Any, runtime: Any, assignments: dict[str, dict[str, Any]],
           read_versions: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    raise NotImplementedError
