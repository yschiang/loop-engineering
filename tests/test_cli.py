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


def test_help_exits_zero(capsys):
    assert main(["--help"]) == 0
    assert "status" in capsys.readouterr().out


def test_old_delivery_package_is_not_importable():
    assert importlib.util.find_spec("delivery") is None
