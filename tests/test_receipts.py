"""Write-once records outside the run state, and the latest preflight receipt
of each repo and role, read back by its digest (design DD-6, DD-8)."""

from __future__ import annotations

from pathlib import Path

from loopctl import store


def test_records_are_write_once_and_ordered(tmp_path: Path) -> None:
    directory = tmp_path / "records"
    directory.mkdir()
    payloads = [{"kind": "started"}, {"kind": "terminal"}, {"kind": "closed"}]

    seqs = [store.append_record(directory, payload) for payload in payloads]
    (directory / "4.json").write_text('{"kind": "dispatch", ')
    records = store.list_records(directory)

    assert len(records.items) == 3
    assert seqs == [1, 2, 3]
    assert records.items == [
        {**payload, "seq": seq} for seq, payload in zip(seqs, payloads, strict=True)
    ]
    assert records.skipped == ["4.json"]
