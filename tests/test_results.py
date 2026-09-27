"""Task 1.5: result import from inbox - dedup, conflict, identity checks (AC-D05, D07, D08)."""

import json

from delivery.results import import_result
from delivery.store import Store

ASSIGNMENT = {"run_id": "r1", "task_id": "2.3", "attempt_id": "a1", "clone_path": "/w/a1/clone",
              "base_sha": "b" * 40, "scope": {"paths": ["src", "tests"]}}


def result(**over):
    body = {"run_id": "r1", "task_id": "2.3", "attempt_id": "a1", "execution_status": "succeeded",
            "observed": {"cwd": "/w/a1/clone", "base": "b" * 40, "head": "c" * 40},
            "changed_paths": ["src/app.py"]}
    body.update(over)
    return body


def write_inbox(tmp_path, body, name="result.json"):
    f = tmp_path / "inbox" / "a1" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(json.dumps(body).encode())
    return f


def fresh(tmp_path):
    return Store(tmp_path / "run"), {"schema_version": 1, "imported_results": {}, "blockers": []}


def test_valid_result_is_stored_durably_and_recorded(tmp_path):
    store, state = fresh(tmp_path)
    f = write_inbox(tmp_path, result())
    out = import_result(store, state, ASSIGNMENT, f)
    assert out.status == "imported"
    assert out.state["imported_results"]["a1"] == out.ref
    assert store.blob_path(out.ref).read_bytes() == f.read_bytes()
    store.commit(out.state)  # the snapshot may reference it: it was made durable first


def test_reimport_after_lost_notification_or_crash_is_a_noop(tmp_path):
    store, state = fresh(tmp_path)
    f = write_inbox(tmp_path, result())
    first = import_result(store, state, ASSIGNMENT, f)
    store.commit(first.state)
    again = import_result(Store(tmp_path / "run"), first.state, ASSIGNMENT, f)
    assert again.status == "duplicate"
    assert again.state == first.state


def test_same_attempt_with_different_bytes_is_conflict_and_keeps_both(tmp_path):
    store, state = fresh(tmp_path)
    first = import_result(store, state, ASSIGNMENT, write_inbox(tmp_path, result()))
    other = write_inbox(tmp_path, result(execution_status="failed"), name="result-2.json")
    out = import_result(store, first.state, ASSIGNMENT, other)
    assert out.status == "conflict"
    assert out.state["imported_results"]["a1"] == first.ref
    assert store.blob_path(out.ref).read_bytes() == other.read_bytes()
    assert any(b["kind"] == "result_conflict" and b["attempt_id"] == "a1" for b in out.state["blockers"])


def test_identity_mismatches_are_rejected_but_kept(tmp_path):
    cases = {
        "attempt_id": result(attempt_id="a0"),
        "observed.cwd": result(observed={"cwd": "/elsewhere", "base": "b" * 40, "head": "c" * 40}),
        "observed.base": result(observed={"cwd": "/w/a1/clone", "base": "d" * 40, "head": "c" * 40}),
        "scope": result(changed_paths=["src/app.py", "outside.txt"]),
    }
    for field_name, body in cases.items():
        store, state = fresh(tmp_path / field_name)
        out = import_result(store, state, ASSIGNMENT, write_inbox(tmp_path / field_name, body))
        assert out.status == "rejected", field_name
        assert any(field_name in r for r in out.reasons), (field_name, out.reasons)
        assert out.state["imported_results"] == {}
        assert store.blob_path(out.ref).exists()
