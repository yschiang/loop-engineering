"""Test-only policy (design §11, validation §0). Not a product hook, not a registry.

The session fails (exit != 0) on: zero collected (pytest's own exit 5); any skip not
produced by `only_on` on a foreign platform; any xfail or xpass; or a CI job's
LOOPCTL_EXPECT_PLATFORM that differs from the actual platform.
"""

import json
import os
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_violations = pytest.StashKey[list[str]]()
_platform_skips = pytest.StashKey[set[str]]()


def current_platform() -> str:
    """The single platform function; t1–t6 simulate platforms by overriding it."""
    return sys.platform


def pytest_configure(config: pytest.Config) -> None:
    config.stash[_violations] = []
    config.stash[_platform_skips] = set()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    marker = item.get_closest_marker("only_on")
    if marker is not None and marker.args[0] != current_platform():
        item.config.stash[_platform_skips].add(item.nodeid)
        pytest.skip(f"only_on({marker.args[0]})")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    violations = item.config.stash[_violations]
    if hasattr(report, "wasxfail"):
        kind = "xfail" if report.skipped else "xpass"
        violations.append(f"{kind} is not allowed: {item.nodeid}")
    elif report.skipped and not (
        report.when == "setup" and item.nodeid in item.config.stash[_platform_skips]
    ):
        violations.append(f"skip not produced by only_on: {item.nodeid}")
    return report


def pytest_sessionfinish(session: pytest.Session) -> None:
    violations = session.config.stash[_violations]
    expected = os.environ.get("LOOPCTL_EXPECT_PLATFORM")
    if expected and expected != current_platform():
        violations.append(
            f"LOOPCTL_EXPECT_PLATFORM={expected} but actual platform is {current_platform()}"
        )
    if violations and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    violations = config.stash.get(_violations, [])
    if violations:
        terminalreporter.section("loopctl test policy violations")
        for line in violations:
            terminalreporter.line(line)


FAKE_BIN = Path(__file__).parent / "fakes" / "bin" / "herdr"


class Fakes:
    """PATH-injected scenario fakes (tests/fakes/bin/herdr, format in its docstring)."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bin = root / "fakebin"
        self.bin.mkdir()
        self.log = root / "fake-log.jsonl"
        self.scenario = root / "fake-scenario.json"
        self.use({"calls": []})
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_SCENARIO", str(self.scenario))
        self.install("herdr")

    def install(self, *tools: str) -> None:
        for tool in tools:
            (self.bin / tool).symlink_to(FAKE_BIN)

    def use(self, scenario: dict) -> None:
        self.scenario.write_text(json.dumps(scenario))

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fakes:
    return Fakes(tmp_path, monkeypatch)
