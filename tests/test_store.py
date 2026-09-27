"""Task 1.3 (DR-09): durable blobs, commit barrier, reference integrity, schema and manual edits."""

import hashlib
import json

import pytest

from delivery.store import (
    BlobConflict,
    ManualEditDetected,
    NotDurable,
    SchemaMismatch,
    StateCorrupt,
    StateMissing,
    Store,
)


def ref_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_committed_state_round_trips_with_revision(tmp_path):
    s = Store(tmp_path)
    h = s.put_blob(b"evidence")
    rev = s.commit({"schema_version": 1, "gates": {"g1": {"evidence": [h.ref]}}})
    loaded = Store(tmp_path).load()
    assert rev == 1
    assert not loaded.blocked
    assert loaded.state["revision"] == 1
    assert loaded.state["gates"]["g1"]["evidence"] == [ref_of(b"evidence")]


def test_commit_rejects_reference_to_blob_not_made_durable(tmp_path):
    s = Store(tmp_path)
    missing = ref_of(b"never written")
    with pytest.raises(NotDurable):
        s.commit({"schema_version": 1, "evidence": [missing]})
    assert not (tmp_path / "run.json").exists()


def test_leftover_tmp_files_do_not_disturb_resume(tmp_path):
    s = Store(tmp_path)
    h = s.put_blob(b"log")
    s.commit({"schema_version": 1, "e": [h.ref]})
    (tmp_path / "blobs" / ".tmp-crashed").write_bytes(b"partial")
    (tmp_path / ".tmp-run-crashed").write_text('{"schema_version": 1, "half')
    linked_tmp = tmp_path / "blobs" / ".tmp-linked"
    linked_tmp.write_bytes(b"log")  # crash after link, before unlink of tmp
    r = Store(tmp_path).load()
    assert not r.blocked
    assert r.state["e"] == [h.ref]


def test_missing_referenced_blob_blocks_and_leaves_files(tmp_path):
    s = Store(tmp_path)
    h = s.put_blob(b"receipt")
    s.commit({"schema_version": 1, "r": [h.ref]})
    h.path.unlink()
    before = (tmp_path / "run.json").read_bytes()
    r = Store(tmp_path).load()
    assert r.blocked
    assert any(h.ref in reason for reason in r.reasons)
    assert (tmp_path / "run.json").read_bytes() == before


def test_corrupted_referenced_blob_blocks(tmp_path):
    s = Store(tmp_path)
    h = s.put_blob(b"original")
    s.commit({"schema_version": 1, "r": [h.ref]})
    h.path.write_bytes(b"tampered")
    assert Store(tmp_path).load().blocked


def test_named_write_once_collision_with_different_bytes_keeps_both(tmp_path):
    s = Store(tmp_path)
    s.put_blob(b"first result", name="results/a1.json")
    with pytest.raises(BlobConflict):
        s.put_blob(b"second result", name="results/a1.json")
    assert (tmp_path / "results" / "a1.json").read_bytes() == b"first result"
    conflicts = list((tmp_path / "results").glob("a1.json.conflict-*"))
    assert [c.read_bytes() for c in conflicts] == [b"second result"]


def test_named_write_once_same_bytes_is_idempotent(tmp_path):
    s = Store(tmp_path)
    a = s.put_blob(b"same", name="results/a1.json")
    b = s.put_blob(b"same", name="results/a1.json")
    assert a == b


def test_missing_state_is_explicit_error(tmp_path):
    with pytest.raises(StateMissing):
        Store(tmp_path).load()


def test_unparseable_state_is_explicit_error_and_untouched(tmp_path):
    (tmp_path / "run.json").write_text('{"schema_version": 1,')
    with pytest.raises(StateCorrupt):
        Store(tmp_path).load()
    assert (tmp_path / "run.json").read_text() == '{"schema_version": 1,'


def test_unknown_schema_version_is_rejected(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({"schema_version": 99, "revision": 1}))
    with pytest.raises(SchemaMismatch):
        Store(tmp_path).load()


def test_external_edit_between_load_and_commit_is_detected(tmp_path):
    s = Store(tmp_path)
    s.commit({"schema_version": 1, "gates": {"g1": "missing"}})
    s2 = Store(tmp_path)
    state = s2.load().state
    edited = dict(state, gates={"g1": "passed"})
    (tmp_path / "run.json").write_text(json.dumps(edited))
    with pytest.raises(ManualEditDetected):
        s2.commit(dict(state, note="next"))
    assert json.loads((tmp_path / "run.json").read_text())["gates"] == {"g1": "passed"}
