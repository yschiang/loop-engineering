"""M-PRE f1–f6: `loopctl preflight --role R --out P` decision logic with fake herdr (design §6)."""

import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from loopctl import clock
from loopctl.cli import main

ROOT = Path(__file__).resolve().parents[1]
FROZEN = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout of the repo policy on branch main, as the preflight cwd."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "git@github.com:yschiang/loop-engineering.git")
    shutil.copy(ROOT / "workflow.yaml", repo)
    shutil.copytree(ROOT / "profiles", repo / "profiles")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "init")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(clock, "now", lambda: FROZEN)
    return repo


def edit_policy(repo: Path, change) -> None:
    policy = yaml.safe_load((repo / "workflow.yaml").read_text())
    change(policy)
    (repo / "workflow.yaml").write_text(yaml.safe_dump(policy))


def preflight(capsys, role: str, out: Path) -> tuple[int, dict, dict | None]:
    code = main(["preflight", "--role", role, "--out", str(out)])
    envelope = json.loads(capsys.readouterr().out)
    receipt = json.loads(out.read_text()) if out.exists() else None
    return code, envelope, receipt


def assert_blocked(code: int, envelope: dict, receipt: dict | None) -> None:
    assert code == 3
    assert receipt is not None and receipt["verdict"] == "unverified"
    assert envelope["ok"] is False
    assert envelope["blocked"] == {"reasons": receipt["reasons"]}
    assert envelope["next"] == {"action": "human", "blockers": receipt["reasons"], "decision_kinds": []}


def test_f1_selected_profile_without_model_is_unverified(repo, fakes, capsys, tmp_path):
    edit_policy(repo, lambda p: p["profiles"]["reviewer"].pop("model"))
    code, envelope, receipt = preflight(capsys, "reviewer", tmp_path / "out" / "reviewer.json")
    assert_blocked(code, envelope, receipt)
    assert "profile_model_missing:reviewer" in receipt["reasons"]
    assert receipt["role"] == "reviewer"
    assert receipt["observed_at"] == FROZEN.isoformat()
    assert fakes.calls() == []


@pytest.mark.parametrize("role", ["implementer", "reviewer"])
def test_f4_same_model_for_both_roles_is_unverified(repo, fakes, capsys, tmp_path, role):
    def same_model(policy):
        policy["profiles"]["reviewer"].update(provider="anthropic", model="claude-opus-5-5", effort="xhigh")

    edit_policy(repo, same_model)
    code, envelope, receipt = preflight(capsys, role, tmp_path / f"{role}.json")
    assert_blocked(code, envelope, receipt)
    assert "models_identical:claude-opus-5-5" in receipt["reasons"]
    assert fakes.calls() == []


# ---- probe cases: fake herdr (+ fake opencode for the reviewer's native record) ----

ROLES = ["implementer", "reviewer"]
NEGATIVES = ["write_outside", "git_push", "gh", "herdr", "loopctl_decide"]
RESOURCE = {
    "write_outside": "outside.txt",
    "git_push": "remote.git/refs/heads/probe",
    "gh": "gh.out",
    "herdr": "herdr.out",
    "loopctl_decide": "decide.out",
}
SCENARIOS = ROOT / "tests" / "fakes" / "scenarios" / "herdr"


@pytest.fixture
def probe(repo, fakes, tmp_path, monkeypatch):
    """Probe-ready checkout: fast limits (no waiting) and fake herdr/opencode on PATH."""

    def fast(policy):
        policy["timeouts"].update(worker_attempt_min=0, review_attempt_min=0)
        policy["limits"].update(poll_worker_s=0, stop_readback_interval_s=0)

    edit_policy(repo, fast)
    fakes.install("opencode")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # probe dirs stay under tmp_path
    return repo


def scenario(role: str) -> dict:
    return json.loads((SCENARIOS / f"preflight-{role}.json").read_text())


def call(s: dict, call_id: str) -> dict:
    return next(c for c in s["calls"] if c.get("id") == call_id)


def claude_entries(s: dict) -> list[dict]:
    return call(s, "prompt")["effects"][0]["jsonl"]


def opencode_export(s: dict) -> dict:
    return call(s, "export")["stdout"]


def run_probe(capsys, fakes, tmp_path, role: str, s: dict) -> tuple[int, dict, dict]:
    fakes.use(s)
    code, envelope, receipt = preflight(capsys, role, tmp_path / "out" / f"{role}.json")
    assert receipt is not None
    calls = fakes.calls()
    assert [c for c in calls if c.get("unexpected")] == []
    assert len(calls) == len(s["calls"]), "every scripted call is made"
    return code, envelope, receipt


def assert_verified(code: int, envelope: dict, receipt: dict) -> None:
    assert (code, receipt["verdict"], receipt["reasons"]) == (0, "verified", [])
    assert envelope["ok"] is True
    assert envelope["blocked"] is None


def make_not_denied(s: dict, role: str, negative: str) -> None:
    if role == "implementer":
        results = claude_entries(s)[2]["message"]["content"]
        result = next(r for r in results if r["tool_use_id"] == f"t-{negative}")
        result.update(is_error=False, content="ok")
    else:
        part = opencode_export(s)["messages"][1]["parts"][NEGATIVES.index(negative)]
        part["state"] = {"status": "completed", "input": part["state"]["input"], "output": "ok"}


def test_f2_both_selected_profiles_verified_without_unselected_runtimes(probe, fakes, capsys, tmp_path):
    fakes.install("codex", "orca")  # present but any call fails: must never be used
    for role in ROLES:
        fakes.log.unlink(missing_ok=True)
        code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, scenario(role))
        assert_verified(code, envelope, receipt)
        assert {c["tool"] for c in fakes.calls()} <= {"herdr", "opencode"}


@pytest.mark.parametrize("role,observed", [("implementer", "claude-sonnet-5"), ("reviewer", "gpt-6-luna")])
def test_f3_native_model_differs_from_profile_is_unverified(probe, fakes, capsys, tmp_path, role, observed):
    s = scenario(role)
    if role == "implementer":
        for entry in claude_entries(s):
            if entry["type"] == "assistant":
                entry["message"]["model"] = observed
    else:
        for message in opencode_export(s)["messages"][1:]:
            message["info"]["modelID"] = observed
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == ["model_mismatch"]
    assert receipt["model"]["observed"] == [observed]


@pytest.mark.parametrize("role", ROLES)
def test_f5a_all_negatives_denied_and_stop_confirmed_is_verified(probe, fakes, capsys, tmp_path, role):
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, scenario(role))
    assert_verified(code, envelope, receipt)
    prompt = next(c["argv"][-1] for c in fakes.calls() if c["argv"][:2] == ["agent", "prompt"])
    assert [n["name"] for n in receipt["negatives"]] == NEGATIVES
    for negative in receipt["negatives"]:
        assert negative["command"] in prompt
        assert negative["resource"].endswith(RESOURCE[negative["name"]].split("/")[0])
        assert (negative["denied"], negative["resource_unchanged"], negative["verified"]) == (True, True, True)
        assert negative["denial"]
    assert receipt["stop"]["stopped"] is True
    assert len(receipt["stop"]["readbacks"]) == 1
    assert receipt["model"] == {
        "requested": receipt["profile"]["model"],
        "observed": [receipt["profile"]["model"]],
        "verified": True,
    }
    assert receipt["effort"] == {"requested": receipt["profile"]["effort"], "observed": receipt["profile"]["effort"]}
    assert receipt["effort_verified"] is True
    assert receipt["herdr_version"] == "herdr 0.9.1"
    assert receipt["runtime_version"] in {"2.1.300", "1.18.32"}
    assert receipt["native_session_id"]


@pytest.mark.parametrize("negative", NEGATIVES)
@pytest.mark.parametrize("role", ROLES)
def test_f5b_negative_not_denied_is_unverified_for_that_negative(probe, fakes, capsys, tmp_path, role, negative):
    s = scenario(role)
    make_not_denied(s, role, negative)
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == [f"negative_not_denied:{negative}"]


@pytest.mark.parametrize("negative", NEGATIVES)
@pytest.mark.parametrize("role", ROLES)
def test_f5c_denied_but_resource_changed_is_unverified_for_that_negative(probe, fakes, capsys, tmp_path, role, negative):
    s = scenario(role)
    call(s, "prompt").setdefault("effects", []).append({"write": f"{{probe}}/{RESOURCE[negative]}", "text": "0" * 40 + "\n"})
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == [f"negative_resource_changed:{negative}"]
    changed = next(n for n in receipt["negatives"] if n["name"] == negative)
    assert (changed["denied"], changed["resource_unchanged"]) == (True, False)


@pytest.mark.parametrize("role", ROLES)
def test_f5d_agent_still_running_after_stop_is_unverified(probe, fakes, capsys, tmp_path, role):
    s = scenario(role)
    readback = call(s, "readback")
    readback["stdout"]["result"]["process_info"]["foreground_processes"] = [{"pid": 200, "name": "agent", "argv": ["agent"]}]
    s["calls"] += [readback, readback]  # readback_max = 3
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == ["stop_unconfirmed"]
    assert len(receipt["stop"]["readbacks"]) == 3


@pytest.mark.parametrize("role", ROLES)
def test_f5e_native_record_without_effort_is_verified_with_effort_unverified(probe, fakes, capsys, tmp_path, role):
    s = scenario(role)
    if role == "implementer":
        for entry in claude_entries(s):
            entry.pop("effort", None)
    else:
        for message in opencode_export(s)["messages"]:
            message["info"].pop("variant", None)
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_verified(code, envelope, receipt)
    assert receipt["effort_verified"] is False
    assert receipt["effort"]["observed"] is None


def test_f6a_native_location_matches_request(probe, fakes, capsys, tmp_path):
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, "implementer", scenario("implementer"))
    assert_verified(code, envelope, receipt)
    requested = {"repo": "yschiang/loop-engineering", "worktree": str(probe.resolve()), "branch": "main"}
    location = receipt["location"]
    assert location["requested"] == requested
    assert {k: location["actual"][k] for k in requested} == requested
    assert location["actual"]["cwd"] == str(probe.resolve())
    assert location["items"] == {"repo": True, "worktree": True, "branch": True}


def test_f6b_native_cwd_in_another_worktree_is_unverified(probe, fakes, capsys, tmp_path):
    other = (tmp_path / "other").resolve()
    git(probe, "worktree", "add", "-q", "-b", "other", str(other))
    s = scenario("implementer")
    for entry in claude_entries(s):
        entry["cwd"] = str(other)
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, "implementer", s)
    assert_blocked(code, envelope, receipt)
    assert "location:worktree" in receipt["reasons"]
    assert receipt["location"]["requested"]["worktree"] == str(probe.resolve())
    assert receipt["location"]["actual"]["worktree"] == str(other)
    assert receipt["location"]["items"]["worktree"] is False


def test_f6c_branch_differs_is_unverified(probe, fakes, capsys, tmp_path):
    s = scenario("implementer")
    call(s, "prompt")["effects"].append({"write": "{cwd}/.git/HEAD", "text": "ref: refs/heads/other\n"})
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, "implementer", s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == ["location:branch"]
    assert receipt["location"]["requested"]["branch"] == "main"
    assert receipt["location"]["actual"]["branch"] == "other"


def test_f6d_input_accepted_without_native_turn_is_unverified(probe, fakes, capsys, tmp_path):
    s = scenario("implementer")
    del claude_entries(s)[1:]
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, "implementer", s)
    assert_blocked(code, envelope, receipt)
    assert "no_native_turn" in receipt["reasons"]
    assert receipt["location"]["items"] == {"repo": False, "worktree": False, "branch": False}


@pytest.mark.parametrize("role", ROLES)
def test_f6e_only_shell_cwd_matches_is_unverified(probe, fakes, capsys, tmp_path, role):
    s = scenario(role)
    if role == "implementer":
        for entry in claude_entries(s):
            entry.pop("cwd")
    else:
        opencode_export(s)["info"].pop("directory")
    code, envelope, receipt = run_probe(capsys, fakes, tmp_path, role, s)
    assert_blocked(code, envelope, receipt)
    assert receipt["reasons"] == ["native_cwd_missing"]
    assert receipt["location"]["actual"]["cwd"] is None
    assert receipt["location"]["actual"]["shell_cwd"] == str(probe.resolve())
    assert receipt["location"]["items"] == {"repo": False, "worktree": False, "branch": False}
