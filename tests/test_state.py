"""M-STATE s1–s7: feature state store, `init`/`claim`/`status`/`next` (design §2, §3)."""

import hashlib
import json
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from loopctl import state as loopctl_state
from loopctl import store
from loopctl.cli import main

FEATURE = "F-1"
CLI = "import sys; from loopctl.cli import main; sys.exit(main(sys.argv[1:]))"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes) -> Path:
    home = tmp_path / "loopctl-home"
    monkeypatch.setenv("LOOPCTL_HOME", str(home))
    return home


def fdir(home: Path, feature: str = FEATURE) -> Path:
    return home / "features" / feature


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def init(capsys, feature: str = FEATURE) -> dict:
    code, out = run(
        capsys, "init", "--repo", "yschiang/loop-engineering", "--repo-id", "R_1",
        "--feature", feature, "--issue", "7",
    )
    assert code == 0, out
    return out


def claim(capsys, actor: str, feature: str = FEATURE) -> dict:
    code, out = run(capsys, "claim", "--feature", feature, "--actor", actor)
    assert code == 0, out
    return out


def at_revision_3(capsys) -> None:
    """init (1) → claim (2) → a budget-carrying transition (3)."""
    init(capsys)
    claim(capsys, "alice")
    rev = store.commit(FEATURE, 2, "t-3", lambda s: {**s, "budget": {"active_used_s": 5400}})
    assert rev == 3


def child(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", *argv], capture_output=True, text=True, check=False
    )


# A commit that is killed (os._exit, no cleanup) at a named point of the store.
CRASH = """
import os, sys
from loopctl import store
point, expected, tid = sys.argv[1], int(sys.argv[2]), sys.argv[3]
die = lambda *a, **k: os._exit(9)
mutate = lambda s: {**s, "note": tid}
if point == "mutate":
    mutate = die
elif point != "after_return":
    setattr(store, point, die)
store.commit("F-1", expected, tid, mutate)
os._exit(9)
"""


@pytest.mark.parametrize("point", ["mutate", "_link_history"])
def test_s1_interrupt_before_commit_keeps_old_revision(capsys, home, fakes, point):
    at_revision_3(capsys)
    current = fdir(home) / "feature.json"
    before = current.read_bytes()

    assert child(CRASH, point, "3", "t-4").returncode == 9

    code, out = run(capsys, "status", "--feature", FEATURE)
    assert code == 0, out
    assert out["revision"] == 3
    assert current.read_bytes() == before
    assert not (fdir(home) / "history" / "4.json").exists()
    rev, state = store.load(FEATURE)
    assert rev == 3 and "note" not in state
    assert fakes.calls() == []
    # The interrupted attempt leaves nothing that blocks a later commit.
    assert store.commit(FEATURE, 3, "t-4", lambda s: {**s, "note": "t-4"}) == 4


@pytest.mark.parametrize("point", ["_replace_current", "after_return"])
def test_s2_interrupt_after_commit_keeps_new_revision_once(capsys, home, fakes, point):
    at_revision_3(capsys)

    assert child(CRASH, point, "3", "t-4").returncode == 9

    code, out = run(capsys, "status", "--feature", FEATURE)
    assert code == 0, out
    assert out["revision"] == 4
    rev, state = store.load(FEATURE)
    assert (rev, state["note"]) == (4, "t-4")
    # Replaying the same transition is not applied twice.
    assert store.commit(FEATURE, 3, "t-4", lambda s: {**s, "note": "t-4"}) == 4
    assert store.load(FEATURE)[0] == 4
    history = sorted(p.name for p in (fdir(home) / "history").iterdir())
    assert history == ["1.json", "2.json", "3.json", "4.json"]
    for n in range(1, 5):
        record = json.loads((fdir(home) / "history" / f"{n}.json").read_text())
        assert record["revision"] == n and record["state"]["revision"] == n
    assert json.loads((fdir(home) / "feature.json").read_text())["revision"] == 4
    assert fakes.calls() == []


def _missing(home: Path) -> None:
    (fdir(home) / "feature.json").unlink()


def _bad_json(home: Path) -> None:
    (fdir(home) / "feature.json").write_bytes(b'{"schema_version": 1, "phase": ')


def _edit(home: Path, change) -> None:
    path = fdir(home) / "feature.json"
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc, sort_keys=True, indent=2))


def _schema_9(home: Path) -> None:
    _edit(home, lambda d: d.update(schema_version=9))


def _hand_edited_gate(home: Path) -> None:
    _edit(home, lambda d: d["gates"].update(g1={"status": "passed", "reasons": []}))


def _transition_conflict(home: Path) -> None:
    with pytest.raises(store.TransitionConflict):
        store.commit(FEATURE, 3, "t-3", lambda s: {**s, "budget": {"active_used_s": 0}})


@pytest.mark.parametrize(
    ("corrupt", "code", "reason"),
    [
        (_missing, 5, "untrusted_state:state_missing"),
        (_bad_json, 5, "untrusted_state:state_corrupt"),
        (_schema_9, 5, "untrusted_state:unknown_schema:9"),
        (_hand_edited_gate, 5, "untrusted_state:manual_edit"),
        (_transition_conflict, 3, "transition_conflict:t-3"),
    ],
    ids=["missing", "bad_json", "schema_9", "hand_edited_gate", "transition_conflict"],
)
def test_s3_untrusted_state_stops_without_touching_it(capsys, home, fakes, corrupt, code, reason):
    at_revision_3(capsys)
    corrupt(home)
    before = snapshot(home)

    for command in ("status", "next"):
        got, out = run(capsys, command, "--feature", FEATURE)
        assert got == code, out
        assert out["ok"] is False
        assert reason in out["blocked"]["reasons"]
        assert out["next"]["action"] == "human"
        assert reason in out["next"]["blockers"]
        assert out["safety"] is None
    # init does not rebuild an empty state over it.
    got, out = run(
        capsys, "init", "--repo", "yschiang/loop-engineering", "--repo-id", "R_1",
        "--feature", FEATURE, "--issue", "7",
    )
    assert got != 0, out

    assert snapshot(home) == before
    record = json.loads((fdir(home) / "history" / "3.json").read_text())
    assert record["state"]["budget"] == {"active_used_s": 5400}
    assert fakes.calls() == []


def test_s4_concurrent_claims_exactly_one_wins_and_token_plaintext_is_not_stored(capsys, home):
    init(capsys)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CLI, "claim", "--feature", FEATURE, "--actor", actor],
            stdout=subprocess.PIPE, text=True,
        )
        for actor in ("alice", "bob")
    ]
    results = [(p.wait(), json.loads(p.communicate()[0])) for p in procs]

    winners = [out for code, out in results if code == 0]
    losers = [out for code, out in results if code != 0]
    assert len(winners) == 1 and len(losers) == 1
    assert [code for code, _ in results].count(1) == 1
    assert losers[0]["ok"] is False
    token = winners[0]["result"]["token"]
    actor = winners[0]["result"]["actor"]

    rev, state = store.load(FEATURE)
    assert rev == 2
    assert state["owner"]["actor"] == actor
    assert state["owner"]["token_digest"] == "sha256:" + hashlib.sha256(token.encode()).hexdigest()
    assert state["schema_version"] == store.SCHEMA_VERSION == 1
    assert losers[0]["result"] == {"error": "already_claimed", "feature": FEATURE, "owner": actor}
    assert loopctl_state.is_owner(state, token)
    assert not loopctl_state.is_owner(state, token + "x")
    assert not loopctl_state.is_owner(state, None)
    for blob in snapshot(home).values():
        assert token.encode() not in blob

    code, out = run(capsys, "status", "--feature", FEATURE)
    assert code == 0 and out["result"]["owner"] == {"actor": actor}
    assert token not in json.dumps(out)


COMMIT = """
import sys
from loopctl import store
try:
    rev = store.commit("F-1", int(sys.argv[1]), sys.argv[2], lambda s: {**s, "note": sys.argv[2]})
except store.RevisionConflict:
    print("conflict")
else:
    print(rev)
"""


def test_s4_concurrent_commits_on_one_revision_exactly_one_commits(capsys, home):
    init(capsys)
    claim(capsys, "alice")
    procs = [
        subprocess.Popen([sys.executable, "-c", COMMIT, "2", tid], stdout=subprocess.PIPE, text=True)
        for tid in ("t-a", "t-b")
    ]
    outcomes = sorted(p.communicate()[0].strip() for p in procs)
    assert outcomes == ["3", "conflict"]
    rev, state = store.load(FEATURE)
    assert rev == 3 and state["note"] in ("t-a", "t-b")


def test_s5_status_human_shows_phase_gates_blockers_and_next(capsys, home, fakes):
    init(capsys)
    claim(capsys, "alice")
    code, out = run(capsys, "status", "--feature", FEATURE)
    assert code == 0, out
    assert out["revision"] == 2
    assert out["result"]["phase"] == "planning"
    assert out["result"]["gates"] == {
        g: {"status": "pending", "reasons": ["not_evaluated"]} for g in ("g1", "g2", "g3")
    }
    assert out["result"]["blockers"] == []
    assert out["next"] == {
        "action": "human", "blockers": ["plan_not_registered"], "decision_kinds": []
    }

    store.commit(
        FEATURE, 2, "t-s5",
        lambda s: {
            **s,
            "gates": {"g1": {"status": "failed", "reasons": ["original_red_unavailable:T1"]}},
            "blockers": ["original_red_unavailable:T1"],
        },
    )
    code, out = run(capsys, "status", "--feature", FEATURE, "--human")
    assert code == 3, out
    text = out["result"]["human"]
    assert "phase: planning" in text
    assert "g1: failed (original_red_unavailable:T1)" in text
    assert "g2: pending (not_evaluated)" in text
    assert "g3: pending (not_evaluated)" in text
    assert "blockers: original_red_unavailable:T1" in text
    assert "next: human" in text
    assert out["next"] == {
        "action": "human", "blockers": ["original_red_unavailable:T1"], "decision_kinds": []
    }
    assert fakes.calls() == []


def test_s6_document_digests_are_not_object_refs_but_missing_evidence_refs_are_rejected(
    capsys, home
):
    init(capsys)
    claim(capsys, "alice")
    digest = store.put_object(b"raw red output\n")
    assert digest == "sha256:" + hashlib.sha256(b"raw red output\n").hexdigest()
    assert store.put_object(b"raw red output\n") == digest
    assert store.get_object(digest) == b"raw red output\n"

    absent = "sha256:" + "0" * 64
    rev = store.commit(FEATURE, 2, "t-doc", lambda s: {**s, "versions": {"spec": absent}})
    assert rev == 3

    with pytest.raises(store.MissingObject):
        store.commit(
            FEATURE, 3, "t-ev", lambda s: {**s, "evidence": {"red": store.object_ref(absent)}}
        )
    rev, state = store.load(FEATURE)
    assert rev == 3 and "evidence" not in state
    with pytest.raises(store.MissingObject):
        store.get_object(absent)

    rev = store.commit(
        FEATURE, 3, "t-ev2", lambda s: {**s, "evidence": {"red": store.object_ref(digest)}}
    )
    assert rev == 4


def _corrupt_object(home: Path, data: bytes) -> str:
    """Save data as an object, then truncate the object file in place."""
    ref = store.put_object(data)
    (home / "objects" / ref.removeprefix("sha256:")).write_bytes(data[:3])
    return ref


def test_s6_put_object_rejects_a_corrupt_existing_object_and_keeps_its_bytes(home):
    _corrupt_object(home, b"raw red output\n")
    before = snapshot(home)

    with pytest.raises(store.UntrustedState, match="object_corrupt"):
        store.put_object(b"raw red output\n")
    assert snapshot(home) == before


def test_s6_commit_rejects_a_reference_to_a_corrupt_object_without_changing_any_file(
    capsys, home
):
    init(capsys)
    claim(capsys, "alice")
    ref = _corrupt_object(home, b"raw red output\n")
    before = snapshot(home)

    with pytest.raises(store.UntrustedState, match="object_corrupt"):
        store.commit(FEATURE, 2, "t-ev", lambda s: {**s, "evidence": {"red": store.object_ref(ref)}})
    assert snapshot(home) == before
    rev, state = store.load(FEATURE)
    assert rev == 2 and "evidence" not in state


def test_s6_first_commit_rejects_a_reference_to_a_corrupt_object_and_creates_nothing(home):
    ref = _corrupt_object(home, b"raw red output\n")
    before = snapshot(home)

    with pytest.raises(store.UntrustedState, match="object_corrupt"):
        store.commit(FEATURE, 0, "t-1", lambda s: {"evidence": {"red": store.object_ref(ref)}})
    assert snapshot(home) == before
    assert not fdir(home).exists()


def test_s7_uninitialised_feature_is_reported_absent_and_nothing_is_taken_over(
    capsys, home, fakes
):
    init(capsys, "F-other")  # present, unclaimed: a fallback claim would take it
    before = snapshot(home)

    for argv in (
        ["status", "--feature", "F-missing"],
        ["next", "--feature", "F-missing"],
        ["claim", "--feature", "F-missing", "--actor", "bob"],
    ):
        code, out = run(capsys, *argv)
        assert code == 1, out
        assert out["ok"] is False
        assert out["result"] == {"error": "feature_not_found", "feature": "F-missing"}
        assert out["next"]["action"] == "human"

    code, out = run(capsys, "claim", "--actor", "bob")
    assert code == 2 and out["result"]["error"] == "usage"
    code, out = run(capsys, "status")
    assert code == 0 and out["result"] == {"phase": "empty", "feature": None}

    assert snapshot(home) == before
    assert not fdir(home, "F-missing").exists()
    assert store.load("F-other")[1]["owner"] is None
    assert fakes.calls() == []


def test_claim_token_is_accepted_in_space_form_even_when_randomness_starts_with_0xf8(
    capsys, home, tmp_path, monkeypatch
):
    """D53: a token starting with '-' made `--token <value>` a usage error.

    0xf8 as the first random byte is the value token_urlsafe renders as a leading '-'.
    """
    monkeypatch.setattr(secrets, "token_bytes", lambda n=32: b"\xf8" + b"\x00" * (n - 1))
    init(capsys)
    token = claim(capsys, "alice")["result"]["token"]
    doc = tmp_path / "sa.md"
    doc.write_text("confirmed\n")
    code, out = run(
        capsys, "register", "binding", "--feature", FEATURE, "--token", token,
        "--role", "sa", "--locator", str(doc), "--version", "sa-1",
    )
    assert code == 0, out
    assert out["ok"] is True


def test_generated_tokens_never_start_with_dash_and_keep_256_bits(monkeypatch):
    tokens = [loopctl_state.new_token() for _ in range(2000)]
    for first in range(256):
        monkeypatch.setattr(secrets, "token_bytes", lambda n=32, b=first: bytes([b]) * n)
        tokens.append(loopctl_state.new_token())
    assert not [t for t in tokens if t.startswith("-")]
    assert all(len(t) == 64 and int(t, 16) >= 0 for t in tokens)
    assert len(set(tokens[:2000])) == 2000


def test_state_core_does_not_import_subprocess_or_tools():
    """cleanup-map §1: the core keeps its dependency direction (no subprocess, no tools)."""
    code = (
        "import sys; import loopctl.store, loopctl.state, loopctl.next; "
        "bad = sorted(m for m in sys.modules if m == 'subprocess' or m.startswith('loopctl.tools')); "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    done = child(code)
    assert done.returncode == 0, done.stdout + done.stderr
