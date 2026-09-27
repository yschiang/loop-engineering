"""Task 1.6 (DR-06): feature authority across clones, lineage budget, project view repair."""

import json
import shutil
import subprocess
import sys

from delivery.authority import Authority
from delivery.store import Store

REPO, FEATURE = "github:yschiang/orca-delivery", "yschiang/orca-delivery#1"


def auth(home):
    return Authority(home, REPO, FEATURE)


def make_run(state_dir, rounds, active):
    Store(state_dir).commit({"schema_version": 1, "budget": {"correction_rounds_used": rounds,
                                                             "active_seconds": active}})


def test_concurrent_starts_from_two_processes_admit_exactly_one(tmp_path):
    code = ("import sys; from pathlib import Path; from delivery.authority import Authority;"
            "a=Authority(Path(sys.argv[1]), sys.argv[2], sys.argv[3]);"
            "o=a.start(sys.argv[4], sys.argv[5], sys.argv[6]); print(o.status)")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path / "home"), REPO, FEATURE,
                               str(tmp_path / f"clone{i}"), str(tmp_path / f"state{i}"), f"r{i}"],
                              stdout=subprocess.PIPE, text=True) for i in (1, 2)]
    outcomes = sorted(p.communicate()[0].strip() for p in procs)
    assert outcomes.count("created") == 1
    assert "resume" not in outcomes


def test_second_clone_is_refused_after_first_controller_exits(tmp_path):
    home = tmp_path / "home"
    a_state = tmp_path / "a" / "state"
    assert auth(home).start(str(tmp_path / "a"), str(a_state), "rA").status == "created"
    make_run(a_state, rounds=3, active=3600)
    out = auth(home).start(str(tmp_path / "b"), str(tmp_path / "b" / "state"), "rB")  # new process view
    assert out.status == "refused"
    assert out.state_dir == str(a_state) and out.run_id == "rA"
    assert auth(home).start(str(tmp_path / "a"), str(a_state), "rA").status == "resume"


def test_missing_registered_state_blocks_instead_of_creating_empty_run(tmp_path):
    home = tmp_path / "home"
    a_state = tmp_path / "a" / "state"
    auth(home).start(str(tmp_path / "a"), str(a_state), "rA")
    make_run(a_state, 1, 10)
    shutil.move(str(a_state), str(tmp_path / "moved"))
    out = auth(home).start(str(tmp_path / "b"), str(tmp_path / "b" / "state"), "rB")
    assert out.status == "blocked"
    assert not (tmp_path / "b" / "state").exists()


def test_abandoned_run_budget_is_inherited_by_replacement(tmp_path):
    home = tmp_path / "home"
    a_state = tmp_path / "a" / "state"
    auth(home).start(str(tmp_path / "a"), str(a_state), "rA")
    make_run(a_state, rounds=2, active=1800)
    auth(home).abandon("rA", {"kind": "abandon_run", "actor": "user", "reason": "clone lost",
                              "evidence": ["workers stopped"]})
    b_state = tmp_path / "b" / "state"
    assert auth(home).start(str(tmp_path / "b"), str(b_state), "rB").status == "created"
    make_run(b_state, rounds=1, active=600)
    b = auth(home).budget()
    assert not b.blocked
    assert (b.correction_rounds_used, b.active_seconds) == (3, 2400)


def test_abandon_requires_an_abandon_run_decision_with_evidence(tmp_path):
    home = tmp_path / "home"
    auth(home).start(str(tmp_path / "a"), str(tmp_path / "a" / "state"), "rA")
    for bad in ({"kind": "unblock", "actor": "u", "reason": "r", "evidence": ["x"]},
                {"kind": "abandon_run", "actor": "u", "reason": "r", "evidence": []}):
        try:
            auth(home).abandon("rA", bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    assert auth(home).start(str(tmp_path / "b"), str(tmp_path / "b" / "state"), "rB").status == "refused"


def test_unreadable_lineage_run_blocks_budget(tmp_path):
    home = tmp_path / "home"
    a_state = tmp_path / "a" / "state"
    auth(home).start(str(tmp_path / "a"), str(a_state), "rA")
    make_run(a_state, 1, 1)
    (a_state / "run.json").write_text("{broken")
    assert auth(home).budget().blocked


def test_deleted_project_view_is_repaired_from_authority(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "a"
    auth(home).start(str(repo), str(repo / ".delivery" / "runs" / "rA"), "rA")
    view = auth(home).repair_project_view(str(repo))
    view.unlink()
    view = auth(home).repair_project_view(str(repo))
    body = json.loads(view.read_text())
    assert body["features"][FEATURE]["active_run_id"] == "rA"
