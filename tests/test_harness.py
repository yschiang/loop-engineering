"""The test harness itself: the fakes of the external tools, the fake clock
and the probe repositories (design DD-10)."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Clock, Fakes, ProbeRepo, Result, git

import loopctl.clock

pytest_plugins = ["pytester"]

TESTS = Path(__file__).resolve().parent
SENTINEL = TESTS / "fakes" / "sentinel"

Inner = Callable[[str], pytest.RunResult]


@pytest.fixture
def inner(
    pytester: pytest.Pytester, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> Inner:
    """Run a test module in a child pytest process with the repo's conftest
    and fakes, and with only minbin/ and sentinel/ on PATH: a tool the
    isolation misses resolves to a sentinel, never to a real tool (DD-10)."""
    tests = pytester.mkdir("tests")
    shutil.copy(TESTS / "conftest.py", tests / "conftest.py")
    shutil.copytree(
        TESTS / "fakes", tests / "fakes", ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setenv("PATH", f"{fakes.minbin}{os.pathsep}{SENTINEL}")

    def run(source: str) -> pytest.RunResult:
        (tests / "test_inner.py").write_text(textwrap.dedent(source))
        return pytester.runpytest_subprocess(str(tests))

    return run


def test_fake_tool_replays_the_scenario_and_logs_argv(fakes: Fakes) -> None:
    fakes({"orca": [{"match": ["--version"], "stdout": "9.9.9\n"}]})

    done = subprocess.run(["orca", "--version"], capture_output=True, text=True)

    assert done.stdout == "9.9.9\n"
    assert done.returncode == 0
    calls = [{"tool": call["tool"], "argv": call["argv"]} for call in fakes.calls()]
    assert calls == [{"tool": "orca", "argv": ["--version"]}]


def test_unexpected_call_fails_the_test_at_teardown(inner: Inner) -> None:
    result = inner(
        """
        import subprocess

        def test_calls_a_tool_without_a_scenario(fakes):
            done = subprocess.run(
                ["orca", "worker-start"], capture_output=True, text=True
            )
            assert done.returncode == 97
        """
    )

    outcomes = result.parseoutcomes()
    assert (outcomes.get("passed"), outcomes.get("errors")) == (1, 1)
    output = result.stdout.str()
    assert "unexpected" in output
    assert '["worker-start"]' in output


def test_real_tools_are_never_reached(inner: Inner) -> None:
    result = inner(
        """
        import shutil
        import subprocess
        from pathlib import Path

        TOOLS = ("orca", "claude", "codex")

        def test_tools_resolve_to_the_fakes():
            for tool in TOOLS:
                found = shutil.which(tool)
                assert found is not None, tool
                assert Path(found).parent.name == "fakebin", found
            versions = {
                tool: subprocess.run(
                    [tool, "--version"], capture_output=True, text=True
                ).stdout
                for tool in TOOLS
            }
            assert versions == {
                "orca": "1.4.218\\n",
                "claude": "2.1.288 (Claude Code)\\n",
                "codex": "codex-cli 0.157.0\\n",
            }
        """
    )

    result.assert_outcomes(passed=1)


def test_without_removes_the_tool_from_path(inner: Inner) -> None:
    result = inner(
        """
        import shutil

        def test_claude_is_gone(fakes):
            fakes.without("claude")

            assert shutil.which("claude") is None
            assert shutil.which("git") is not None
            assert shutil.which("sh") is not None
        """
    )

    result.assert_outcomes(passed=1)


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True)


def test_capture_substitution_and_effects(fakes: Fakes, tmp_path: Path) -> None:
    out, watched = tmp_path / "out", tmp_path / "watched"
    (watched / "sub").mkdir(parents=True)
    (watched / "a.txt").write_text("a")
    (watched / "sub" / "b.txt").write_text("b")
    fakes(
        {
            "orca": [
                {
                    "match": ["terminal", "create", "--title", {"capture": "title"}],
                    "stdout": "created\n",
                },
                {
                    "match": ["terminal", "send"],
                    "stdout": "sent to {title}\n",
                    "effects": [
                        {
                            "write": {
                                "path": str(out / "{title}.jsonl"),
                                "text": "marker {title}\n",
                            }
                        }
                    ],
                },
                {
                    "match": ["terminal", "close"],
                    "effects": [{"state": {"closed": True}}],
                },
                {
                    "match": ["terminal", "list"],
                    "effects": [{"snapshot": str(watched)}],
                },
                {"match": ["terminal", "wait"], "stdout": "timeout\n", "repeat": True},
            ],
            "ps": [
                {
                    "match": ["-ax"],
                    "when": {"closed": None},
                    "stdout": "claude {title}\n",
                    "repeat": True,
                },
                {
                    "match": ["-ax"],
                    "when": {"closed": True},
                    "stdout": "",
                    "repeat": True,
                },
            ],
        }
    )

    assert run("orca", "terminal", "create", "--title", "PFM-0123456789ab").stdout == (
        "created\n"
    )
    # The captured title is substituted in the next answer and effect.
    assert run("orca", "terminal", "send").stdout == "sent to PFM-0123456789ab\n"
    assert (out / "PFM-0123456789ab.jsonl").read_text() == "marker PFM-0123456789ab\n"
    assert fakes.calls()[0]["captured"] == {"title": "PFM-0123456789ab"}

    # A state effect changes what later calls answer.
    assert run("ps", "-ax").stdout == "claude PFM-0123456789ab\n"
    assert run("orca", "terminal", "close").returncode == 0
    assert run("ps", "-ax").stdout == ""

    # A snapshot logs the files of a directory as they are at the call.
    assert run("orca", "terminal", "list").returncode == 0
    assert fakes.calls()[-1]["snapshot"] == {
        str(watched): {"a.txt": "a", "sub/b.txt": "b"}
    }

    # A repeat entry answers every call alike.
    assert [run("orca", "terminal", "wait").stdout for _ in range(3)] == [
        "timeout\n"
    ] * 3

    # `--version` keeps its default while the scenario lists other calls.
    assert run("orca", "--version").stdout == "1.4.218\n"
    assert run("claude", "--version").stdout == "2.1.288 (Claude Code)\n"


def test_kill_parent_interrupts_the_caller(
    fakes: Fakes, cli_proc: Callable[..., Result]
) -> None:
    fakes({"orca": [{"match": ["x"], "effects": [{"kill_parent": True}]}]})

    r = cli_proc(prelude='import subprocess\nsubprocess.run(["orca", "x"])')

    assert r.code == -9


def test_clock_sleep_advances_fake_time(clock: Clock) -> None:
    started = time.monotonic()
    before = datetime.datetime.fromisoformat(loopctl.clock.now())

    loopctl.clock.sleep(5)

    after = datetime.datetime.fromisoformat(loopctl.clock.now())
    assert after - before == datetime.timedelta(seconds=5)
    assert time.monotonic() - started < 1


def common_dir(workspace: Path) -> str:
    return os.path.realpath(
        git("-C", workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )


def origin_of(workspace: Path) -> str:
    return os.path.realpath(git("-C", workspace, "remote", "get-url", "origin"))


def test_probe_repo_offers_linked_and_independent_workspaces(
    probe_repo: Callable[..., ProbeRepo],
) -> None:
    linked = probe_repo(reviewer="linked")
    clone = probe_repo(reviewer="clone")

    assert common_dir(linked.implementer) == common_dir(linked.reviewer)
    assert common_dir(clone.implementer) != common_dir(clone.reviewer)
    for layout in (linked, clone):
        assert {origin_of(layout.implementer), origin_of(layout.reviewer)} == {
            os.path.realpath(layout.origin)
        }
