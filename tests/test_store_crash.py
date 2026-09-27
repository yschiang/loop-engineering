"""Task 1.3 (DR-09): process-level SIGKILL invariants and Linux syscall ordering."""

import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time

import pytest

from delivery.store import Store

WRITER = r"""
import sys
from pathlib import Path
from delivery.store import Store
s = Store(Path(sys.argv[1]))
try:
    state = s.load().state
except Exception:
    state = {"schema_version": 1, "refs": []}
for i in range(10_000):
    h = s.put_blob(("payload-%d-%s" % (i, "x" * 4096)).encode())
    state = dict(state, refs=(state.get("refs", []) + [h.ref])[-20:])
    s.commit(state)
"""


def test_sigkill_at_random_points_keeps_invariants(tmp_path):
    rng = random.Random(1234)
    kills = 0
    for _ in range(200):
        p = subprocess.Popen([sys.executable, "-c", WRITER, str(tmp_path)])
        time.sleep(rng.uniform(0.0, 0.08))
        p.send_signal(signal.SIGKILL)
        p.wait()
        kills += p.returncode == -signal.SIGKILL
        if (tmp_path / "run.json").exists():
            r = Store(tmp_path).load()
            assert not r.blocked, r.reasons
    assert kills > 150  # most iterations were really interrupted mid-write


@pytest.mark.skipif((sys.platform != "linux" or shutil.which("strace") is None)
                    and not os.environ.get("DELIVERY_REQUIRE_LINUX_CHECKS"),
                    reason="syscall ordering is verified with strace on Linux CI only")
def test_blob_and_dir_fsync_precede_snapshot_rename(tmp_path):
    # CI sets DELIVERY_REQUIRE_LINUX_CHECKS so a missing strace fails instead of silently skipping.
    script = ("import sys; from pathlib import Path; from delivery.store import Store; s=Store(Path(sys.argv[1]));"
              "h=s.put_blob(b'x'); s.commit({'schema_version': 1, 'r': [h.ref]})")
    log = tmp_path / "trace.log"
    subprocess.run(["strace", "-f", "-y", "-o", str(log), "-e", "trace=fsync,fdatasync,rename,renameat,renameat2",
                    sys.executable, "-c", script, str(tmp_path / "run")], check=True, env=dict(os.environ))
    lines = log.read_text().splitlines()
    rename_idx = next(i for i, ln in enumerate(lines) if re.search(r"rename.*run\.json", ln))
    blob_fsync = [i for i, ln in enumerate(lines) if "fsync" in ln and "/blobs" in ln]
    assert blob_fsync and max(blob_fsync) < rename_idx
