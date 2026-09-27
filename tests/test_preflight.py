"""M-PRE f1–f6: `loopctl preflight --role R --out P` decision logic with fake herdr (design §6)."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from loopctl import clock
from loopctl.cli import main

ROOT = Path(__file__).resolve().parents[1]
FROZEN = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


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
