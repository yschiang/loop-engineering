import subprocess
import sys
from pathlib import Path

COMMANDS = ["init", "start", "adopt", "status", "resume", "decide", "reconcile", "preflight",
            "evidence", "submit-result"]


def test_cli_help_lists_commands():
    # Breaks if the `delivery` console script is missing or its help omits a designed command (design §1).
    exe = Path(sys.executable).parent / "delivery"
    p = subprocess.run([str(exe), "--help"], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    for cmd in COMMANDS:
        assert cmd in p.stdout
