"""Task 2.12: `delivery status --run-dir` shows the current run without reading history (AC-D01)."""

import subprocess
import sys
from pathlib import Path

from delivery.store import Store


def test_status_command_prints_current_phase_gates_and_blockers(tmp_path):
    Store(tmp_path).commit({"schema_version": 1, "phase": "blocked", "versions_key": "vk:v9",
                            "next_action": {"kind": "decide", "detail": "dispute on F-0004"},
                            "gates": {"g1": {"status": "passed", "version_key": "vk:v9", "reasons": []}},
                            "blockers": [{"kind": "dispute_upheld", "finding_id": "F-0004"}],
                            "budget": {"correction_rounds_used": 2}})
    exe = Path(sys.executable).parent / "delivery"
    p = subprocess.run([str(exe), "status", "--run-dir", str(tmp_path)], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    for text in ("blocked", "vk:v9", "g1: passed", "dispute_upheld", "F-0004", "decide", "rounds 2/3"):
        assert text in p.stdout, text
