"""Task 1.4: events.jsonl pending history, ID dedup, torn tail, mid-file corruption (AC-D10)."""

import json

import pytest

from delivery.events import EventConflict, EventLog, flush_pending
from delivery.store import Store


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def committed_with_pending(tmp_path, events):
    s = Store(tmp_path)
    s.commit({"schema_version": 1, "pending_history": events})
    return s


def test_pending_history_committed_before_crash_is_appended_once(tmp_path):
    ev = [{"id": "e1", "type": "phase", "to": "planning"}, {"id": "e2", "type": "phase", "to": "awaiting_approval"}]
    committed_with_pending(tmp_path, ev)  # crash here: snapshot committed, history not yet written
    s = Store(tmp_path)
    s.load()
    log = EventLog(tmp_path / "events.jsonl")
    assert not flush_pending(s, log).blocked
    assert [e["id"] for e in lines(log.path)] == ["e1", "e2"]
    assert s.load().state["pending_history"] == []


def test_replaying_already_written_events_does_not_duplicate(tmp_path):
    ev = [{"id": "e1", "type": "phase", "to": "planning"}]
    log = EventLog(tmp_path / "events.jsonl")
    log.append(ev)  # crash after append, before the snapshot cleared pending_history
    s = committed_with_pending(tmp_path, ev)
    assert not flush_pending(s, log).blocked
    assert [e["id"] for e in lines(log.path)] == ["e1"]


def test_same_id_with_different_content_is_a_conflict(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append([{"id": "e1", "type": "phase", "to": "planning"}])
    with pytest.raises(EventConflict):
        log.append([{"id": "e1", "type": "phase", "to": "blocked"}])
    assert len(lines(log.path)) == 1


def test_torn_tail_is_saved_for_diagnosis_and_truncated(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append([{"id": "e1", "type": "x"}])
    good = log.path.read_bytes()
    torn = b'{"id": "e2", "ty'
    log.path.write_bytes(good + torn)
    r = log.recover()
    assert not r.blocked
    assert r.diagnostic is not None and r.diagnostic.read_bytes() == good + torn
    assert log.path.read_bytes() == good
    log.append([{"id": "e2", "type": "x"}])
    assert [e["id"] for e in lines(log.path)] == ["e1", "e2"]


def test_mid_file_corruption_blocks_and_leaves_file(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    body = b'{"id": "e1"}\nGARBAGE\n{"id": "e3"}\n'
    log.path.write_bytes(body)
    r = log.recover()
    assert r.blocked
    assert log.path.read_bytes() == body


def test_flush_blocks_on_conflicting_history(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append([{"id": "e1", "to": "planning"}])
    s = committed_with_pending(tmp_path, [{"id": "e1", "to": "blocked"}])
    r = flush_pending(s, log)
    assert r.blocked
    assert s.load().state["pending_history"] == [{"id": "e1", "to": "blocked"}]
