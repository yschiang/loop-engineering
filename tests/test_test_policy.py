"""The test policy ends a session in failure when it is violated (AC-G21).

Each test starts a child session with pytester. The child loads the repo's
own tests/conftest.py and the [tool.pytest.ini_options] text of
pyproject.toml unchanged; the platform is simulated by replacing
current_platform() in the child's conftest.
"""

from __future__ import annotations

import shutil
import textwrap
import types
from collections.abc import Callable
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"
PYPROJECT = ROOT / "pyproject.toml"


def ini_options_text() -> str:
    """The [tool.pytest.ini_options] section of pyproject.toml, verbatim."""
    lines = PYPROJECT.read_text().splitlines(keepends=True)
    start = lines.index("[tool.pytest.ini_options]\n")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
        len(lines),
    )
    return "".join(lines[start:end])


class SimulatedPlatform:
    """Replace current_platform() in the child's conftest before anything runs."""

    def __init__(self, name: str) -> None:
        self.name = name

    @pytest.hookimpl(tryfirst=True)
    def pytest_configure(self, config: pytest.Config) -> None:
        for plugin in config.pluginmanager.get_plugins():
            if isinstance(plugin, types.ModuleType) and hasattr(
                plugin, "current_platform"
            ):
                plugin.current_platform = lambda: self.name


Child = Callable[..., pytest.RunResult]


@pytest.fixture
def child(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Child:
    monkeypatch.delenv("LOOPCTL_EXPECT_PLATFORM", raising=False)
    pytester.makepyprojecttoml(ini_options_text())
    tests = pytester.mkdir("tests")
    (tests / "conftest.py").write_text(CONFTEST.read_text())
    # The conftest's autouse tool isolation installs the fakes from here.
    shutil.copytree(
        CONFTEST.parent / "fakes",
        tests / "fakes",
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    def run(platform: str, files: dict[str, str], *args: str) -> pytest.RunResult:
        for name, source in files.items():
            (tests / name).write_text(textwrap.dedent(source))
        return pytester.runpytest(*args, plugins=[SimulatedPlatform(platform)])

    return run


def test_t1_only_on_foreign_platform_skips_and_session_passes(child: Child) -> None:
    result = child(
        "darwin",
        {
            "test_case.py": """
                import pytest

                @pytest.mark.only_on("linux")
                def test_linux_only():
                    pass

                def test_everywhere():
                    pass
            """
        },
    )
    assert result.ret == 0
    result.assert_outcomes(passed=1, skipped=1)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("assert False", id="xfail"),
        pytest.param("pass", id="xpass"),
    ],
)
def test_t5_xfail_and_xpass_fail_session(child: Child, body: str) -> None:
    result = child(
        "linux",
        {
            "test_case.py": f"""
                import pytest

                @pytest.mark.xfail(strict=False, reason="known issue")
                def test_case():
                    {body}
            """
        },
    )
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*loopctl test policy*", "*test_case.py::test_case*"])


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            """
            @pytest.mark.only_on("linux")
            def test_case():
                pytest.skip("missing tool")
            """,
            id="only_on-own-platform-skips-itself",
        ),
        pytest.param(
            """
            @pytest.mark.skipif(True, reason="platform: linux only")
            def test_case():
                pass
            """,
            id="skipif-with-platform-reason",
        ),
        pytest.param(
            """
            def test_case():
                pytest.skip("platform")
            """,
            id="skip-named-platform",
        ),
    ],
)
def test_t2_skip_not_from_only_on_fails_session(child: Child, case: str) -> None:
    source = "import pytest\n" + textwrap.dedent(case)
    result = child("linux", {"test_case.py": source})
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*loopctl test policy*", "*test_case.py::test_case*"])


@pytest.mark.parametrize(
    ("files", "args"),
    [
        pytest.param({}, (), id="empty-directory"),
        pytest.param(
            {"test_case.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"},
            ("-k", "no_such_test"),
            id="all-deselected",
        ),
    ],
)
def test_t4_zero_collected_fails_session(
    child: Child, files: dict[str, str], args: tuple[str, ...]
) -> None:
    result = child("linux", files, *args)
    assert result.ret != 0


def test_t6_expected_platform_mismatch_fails_session(
    child: Child, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOPCTL_EXPECT_PLATFORM", "linux")
    result = child("darwin", {"test_case.py": "def test_case():\n    pass\n"})
    assert result.ret != 0
    result.stdout.fnmatch_lines(
        ["*loopctl test policy*", "*LOOPCTL_EXPECT_PLATFORM=linux*darwin*"]
    )
