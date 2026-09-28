"""The subprocess boundary: loopctl runs external programs only through `run`."""

import subprocess
import tempfile
from pathlib import Path


class ToolError(Exception):
    def __init__(self, argv: list[str], code: int | None, stdout: str, stderr: str) -> None:
        super().__init__(f"{argv[0]} exited {code}: {stderr.strip() or stdout.strip()}")
        self.argv, self.code, self.stdout, self.stderr = argv, code, stdout, stderr


def run(argv: list[str], timeout_s: float, cwd: Path | None = None) -> str:
    """Run argv (no shell) within timeout_s; return stdout or raise ToolError.

    Stdout goes to a temporary file, not a pipe: a child that writes without blocking and exits
    at once (`opencode export`) loses whatever the pipe could not hold.
    """
    with tempfile.TemporaryFile("w+") as out:
        try:
            done = subprocess.run(
                argv, stdout=out, stderr=subprocess.PIPE, text=True, timeout=timeout_s, cwd=cwd, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ToolError(argv, None, "", str(e)) from e
        out.seek(0)
        stdout = out.read()
    if done.returncode != 0:
        raise ToolError(argv, done.returncode, stdout, done.stderr)
    return stdout
