"""loopctl CLI contract owned by T1.1 (design §2): envelope, `status` on empty state, usage errors."""

import importlib.util
import json

import pytest

from loopctl.cli import main

ENVELOPE = {"ok", "revision", "result", "blocked", "next", "safety"}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_status_on_empty_state_hands_over_to_human(capsys, fakes):
    code, out = run(capsys, "status")
    assert code == 0
    assert set(out) == ENVELOPE
    assert out["ok"] is True
    assert out["revision"] is None
    assert out["result"] == {"phase": "empty", "feature": None}
    assert out["blocked"] is None
    assert out["next"] == {"action": "human", "blockers": ["no_feature"], "decision_kinds": []}
    assert out["safety"] is None
    assert fakes.calls() == []


@pytest.mark.parametrize(
    "command", ["merge", "close", "release", "deploy", "adopt", "delegate", "frobnicate"]
)
def test_unsupported_command_is_usage_error_with_zero_external_calls(capsys, fakes, command):
    code, out = run(capsys, command, "--id", "x")
    assert code == 2
    assert set(out) == ENVELOPE
    assert out["ok"] is False
    assert out["result"]["error"] == "usage"
    assert fakes.calls() == []


@pytest.fixture
def no_feature(tmp_path, monkeypatch, fakes):
    monkeypatch.setenv("LOOPCTL_HOME", str(tmp_path / "home"))
    return fakes


@pytest.mark.parametrize(
    "argv",
    [
        ["observe", "--feature", "F-1", "worker", "--attempt", "T1-a1"],
        ["observe", "--feature", "F-1", "--attempt", "T1-a1", "native"],
        ["observe", "worker", "--feature", "F-1", "--attempt", "T1-a1"],
        ["observe", "--feature", "F-1", "pr"],
        ["observe", "ci", "--feature", "F-1"],
    ],
)
def test_observe_options_may_come_before_or_after_the_source(capsys, no_feature, argv):
    code, out = run(capsys, *argv)
    assert (code, out["result"]["error"]) == (1, "feature_not_found"), out  # parsed, then read
    assert no_feature.calls() == []


@pytest.mark.parametrize(
    "argv",
    [
        ["observe", "frobnicate", "--feature", "F-1", "--attempt", "T1-a1"],
        ["observe", "--feature", "F-1", "--attempt", "T1-a1", "frobnicate"],
    ],
)
def test_observe_an_unknown_source_is_unsupported(capsys, no_feature, argv):
    code, out = run(capsys, *argv)
    assert (code, out["result"]["error"], out["result"]["source"]) == (2, "unsupported", "frobnicate"), out
    assert no_feature.calls() == []


@pytest.mark.parametrize(
    "argv",
    [
        ["observe", "worker", "--feature", "F-1"],
        ["observe", "--feature", "F-1", "native"],
        ["observe", "--feature", "F-1", "frobnicate"],
    ],
)
def test_observe_attempt_is_required_by_the_parser_unless_the_source_is_pr_or_ci(capsys, no_feature, argv):
    code, out = run(capsys, *argv)
    assert (code, out["result"]["error"]) == (2, "usage"), out
    assert out["result"]["message"] == "the following arguments are required: --attempt"
    assert no_feature.calls() == []


def test_help_exits_zero(capsys):
    assert main(["--help"]) == 0
    assert "status" in capsys.readouterr().out


def test_old_delivery_package_is_not_importable():
    assert importlib.util.find_spec("delivery") is None
