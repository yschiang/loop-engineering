"""Write-once records outside the run state, and the latest preflight receipt
of each repo and role, read back by its digest (design DD-6, DD-8)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import dig

from loopctl import receipts, store

REPO = "yschiang/loop-engineering"


def receipt(role: str, verdict: str) -> dict[str, Any]:
    reasons = [] if verdict == "verified" else ["task.worker_done"]
    return {"schema": 1, "role": role, "verdict": verdict, "reasons": reasons}


def index_dir(home: Path, role: str) -> Path:
    """The receipt index of `role` in the layout of DD-8."""
    return home / "repos" / REPO / "preflight" / role / "receipts"


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


def test_latest_receipt_wins_and_reads_back_by_digest(home: Path) -> None:
    verified = receipt("implementer", "verified")
    unverified = receipt("implementer", "unverified")

    refs = [
        receipts.write(REPO, "implementer", verified),
        receipts.write(REPO, "implementer", unverified),
    ]
    latest = receipts.latest(REPO, "implementer")

    assert dig(latest, "verdict") == "unverified"
    assert latest == unverified
    index = store.list_records(index_dir(home, "implementer"))
    assert [item.get("receipt") for item in index.items] == refs
    for ref in refs:
        data = (home / "objects" / ref.removeprefix("sha256:")).read_bytes()
        assert "sha256:" + hashlib.sha256(data).hexdigest() == ref
    assert [json.loads(store.get_object(ref)) for ref in refs] == [
        verified,
        unverified,
    ]


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param("object-changed", id="a-object-changed"),
        pytest.param("object-deleted", id="b-object-deleted"),
        pytest.param("newer-index-incomplete", id="c-newer-index-incomplete"),
    ],
)
def test_tampered_receipt_is_reported_not_trusted(home: Path, tamper: str) -> None:
    receipts.write(REPO, "implementer", receipt("implementer", "verified"))
    ref = receipts.write(REPO, "implementer", receipt("implementer", "unverified"))
    newest = home / "objects" / ref.removeprefix("sha256:")
    if tamper == "object-changed":
        newest.write_text(json.dumps(receipt("implementer", "verified")))
    elif tamper == "object-deleted":
        newest.unlink()
    else:
        (index_dir(home, "implementer") / "3.json").write_text('{"seq": 3, "rec')
    named = "3.json" if tamper == "newer-index-incomplete" else ref

    with pytest.raises(receipts.ReceiptCorrupt, match=re.escape(named)):
        receipts.latest(REPO, "implementer")


@pytest.mark.parametrize(
    "newer",
    [
        pytest.param(True, id="newer-index-incomplete"),
        pytest.param(False, id="alone"),
    ],
)
def test_misnumbered_index_record_is_not_trusted(home: Path, newer: bool) -> None:
    receipts.write(REPO, "implementer", receipt("implementer", "verified"))
    index = index_dir(home, "implementer")
    record = json.loads((index / "1.json").read_text())
    (index / "1.json").write_text(json.dumps({**record, "seq": 2}))
    if newer:
        (index / "2.json").write_text("{")
    named = "2.json" if newer else "1.json"

    with pytest.raises(receipts.ReceiptCorrupt, match=re.escape(named)):
        receipts.latest(REPO, "implementer")
    assert "1.json" in store.list_records(index).skipped


def test_roles_keep_separate_latest_receipts(home: Path) -> None:
    implementer = receipt("implementer", "verified")
    reviewer = receipt("reviewer", "unverified")

    receipts.write(REPO, "implementer", implementer)
    receipts.write(REPO, "reviewer", reviewer)

    assert receipts.latest(REPO, "implementer") == implementer
    assert receipts.latest(REPO, "reviewer") == reviewer
