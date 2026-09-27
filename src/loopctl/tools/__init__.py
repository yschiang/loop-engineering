"""The subprocess boundary: loopctl runs external programs only through `run`."""

import subprocess
from pathlib import Path


class ToolError(Exception):
    def __init__(self, argv: list[str], code: int | None, stdout: str, stderr: str) -> None:
        super().__init__(f"{argv[0]} exited {code}: {stderr.strip() or stdout.strip()}")
        self.argv, self.code, self.stdout, self.stderr = argv, code, stdout, stderr


def run(argv: list[str], timeout_s: float, cwd: Path | None = None) -> str:
    """Run argv (no shell) within timeout_s; return stdout or raise ToolError."""
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s, cwd=cwd, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ToolError(argv, None, "", str(e)) from e
    if done.returncode != 0:
        raise ToolError(argv, done.returncode, done.stdout, done.stderr)
    return done.stdout
