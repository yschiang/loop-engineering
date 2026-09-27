"""Task 2.11: resume/reconcile after crashes - no re-dispatch, no re-post, versions re-read (AC-D07, D09, D14, D15)."""

import json
import subprocess
import sys

from delivery.outbox import new_comment_op, new_dispatch_op
from delivery.resume import resume
from delivery.store import Store
from delivery.versions import version_key

from .fakes import FakeGitHub, FakeRuntime

VS = {"repo_id": "r", "pr_number": 34, "head_sha": "H", "base_ref": "main", "base_tip": "B", "merge_base": "B",
      "bindings": {"plan": "p"}, "skills": {}, "controller_version": "0.1.0"}
ASSIGN = {"a1": {"run_id": "r1", "task_id": "2.3", "attempt_id": "a1", "clone_path": "/w/a1",
                 "base_sha": "T0", "scope": {"paths": ["src"]}}}


def seed(tmp_path, **extra):
    k = version_key(VS)
    state = {"schema_version": 1, "phase": "checking", "versions": VS, "operations": {}, "imported_results": {},
             "blockers": [], "pending_history": [], "pass_history": [], "current_pass": None,
             "budget": {"correction_rounds_used": 2}, "registry": {"seq": 1, "findings": {"F-0001": {"id": "F-0001"}}},
             "gates": {g: {"gate": g, "status": "passed", "version_key": k, "evidence": []} for g in ("g1", "g2", "g3")}}
    state.update(extra)
    return state


def inbox(tmp_path, body):
    f = tmp_path / "inbox" / "a1" / "result.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(body))


RESULT = {"run_id": "r1", "task_id": "2.3", "attempt_id": "a1", "execution_status": "succeeded",
          "observed": {"cwd": "/w/a1", "base": "T0", "head": "A1"}, "changed_paths": ["src/x.py"]}


def test_restart_imports_finished_work_resumes_only_pending_publication(tmp_path):
    state = seed(tmp_path)
    new_dispatch_op(state, "op-d", "a1", "do 2.3")
    state["operations"]["op-d"].update(stage="prompt_accepted", state="running", session_id="s1")
    new_comment_op(state, "op-c", "issue/1", "summary", "r1")
    Store(tmp_path).commit(state)
    inbox(tmp_path, RESULT)
    gh, rt = FakeGitHub(), FakeRuntime()
    s = resume(tmp_path, gh, rt, ASSIGN, read_versions=lambda: VS)
    assert s["imported_results"].keys() == {"a1"}
    assert s["operations"]["op-c"]["state"] == "succeeded" and gh.posts == 1
    assert (rt.creates, rt.sends) == (0, 0)
    assert s["registry"]["findings"].keys() == {"F-0001"} and s["budget"]["correction_rounds_used"] == 2
    s2 = resume(tmp_path, gh, rt, ASSIGN, read_versions=lambda: VS)
    assert gh.posts == 1 and s2["imported_results"] == s["imported_results"]


def test_changed_external_version_invalidates_pass_and_is_recorded(tmp_path):
    k = version_key(VS)
    state = seed(tmp_path, phase="ready_for_acceptance", current_pass={"version_key": k},
                 pass_history=[{"version_key": k}], acceptance={"history": [{"status": "accepted", "version_key": k}]})
    Store(tmp_path).commit(state)
    s = resume(tmp_path, FakeGitHub(), FakeRuntime(), ASSIGN, read_versions=lambda: {**VS, "head_sha": "H2"})
    assert s["current_pass"] is None
    assert s["versions"]["head_sha"] == "H2"
    assert s["gates"]["g1"]["status"] == "stale"
    assert s["resume_log"][-1]["seen_versions"]["head_sha"] == "H2"


def test_untrusted_state_blocks_before_any_external_call(tmp_path):
    state = seed(tmp_path)
    new_comment_op(state, "op-c", "issue/1", "summary", "r1")
    store = Store(tmp_path)
    h = store.put_blob(b"receipt")
    state["receipt_ref"] = h.ref
    store.commit(state)
    h.path.unlink()
    gh = FakeGitHub()
    s = resume(tmp_path, gh, FakeRuntime(), ASSIGN, read_versions=lambda: VS)
    assert s["phase"] == "blocked" and gh.posts == 0


def test_controller_killed_after_registering_op_executes_it_exactly_once(tmp_path):
    code = ("import os,sys; from pathlib import Path; from delivery.store import Store;"
            "from delivery.outbox import new_comment_op; s=Store(Path(sys.argv[1]));"
            "st=json.loads(sys.argv[2]); new_comment_op(st,'op-c','issue/1','summary','r1');"
            "st['operations']['op-c']['state']='in_flight'; s.commit(st); os._exit(137)")
    p = subprocess.run([sys.executable, "-c", "import json;" + code, str(tmp_path), json.dumps(seed(tmp_path))],
                       check=False)
    assert p.returncode == 137
    gh = FakeGitHub()
    s = resume(tmp_path, gh, FakeRuntime(), ASSIGN, read_versions=lambda: VS)
    assert s["operations"]["op-c"]["state"] == "succeeded" and gh.posts == 1
