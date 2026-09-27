"""M-TPOL t1–t6: the collection/skip/failure policy (validation §0, design §11).

Each case runs a child pytest session (pytester, in-process) with this repo's real
pytest settings and conftest; the platform is simulated by overriding the conftest's
single platform function in the child copy.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LOOPCTL_EXPECT_PLATFORM", raising=False)

    def run(platform: str, tests: str | None, *args: str) -> pytest.RunResult:
        pytester.makepyprojecttoml((ROOT / "pyproject.toml").read_text())
        pytester.makeconftest(
            (ROOT / "tests" / "conftest.py").read_text()
            + f"\n\ndef current_platform() -> str:\n    return {platform!r}\n"
        )
        pytester.mkdir("tests")
        if tests is not None:
            (pytester.path / "tests" / "test_case.py").write_text(tests)
        return pytester.runpytest(*args)

    return run


def test_t1_only_on_other_platform_is_skipped_and_session_passes(session):
    result = session(
        "darwin",
        "import pytest\n"
        "@pytest.mark.only_on('linux')\n"
        "def test_linux_only(): pass\n"
        "def test_everywhere(): pass\n",
    )
    result.assert_outcomes(passed=1, skipped=1)
    assert result.ret == 0


def test_t2_only_on_own_platform_skipping_itself_fails_session(session):
    result = session(
        "linux",
        "import pytest\n"
        "@pytest.mark.only_on('linux')\n"
        "def test_needs_tool(): pytest.skip('missing tool')\n",
    )
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*test_case.py::test_needs_tool*"])


@pytest.mark.parametrize(
    "body",
    [
        "@pytest.mark.skipif(True, reason='platform: linux only')\ndef test_x(): pass\n",
        "def test_x(): pytest.skip('platform')\n",
    ],
    ids=["skipif-platform-reason", "skip-call-platform-reason"],
)
def test_t3_skip_without_only_on_fails_session_even_with_platform_reason(session, body):
    result = session("linux", "import pytest\n" + body)
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*test_case.py::test_x*"])


@pytest.mark.parametrize(
    "tests,args",
    [(None, ()), ("def test_a(): pass\n", ("-k", "no_such_test"))],
    ids=["empty-dir", "all-filtered"],
)
def test_t4_zero_collected_fails_session(session, tests, args):
    result = session("linux", tests, *args)
    assert result.ret != 0


@pytest.mark.parametrize(
    "body",
    [
        "@pytest.mark.xfail\ndef test_x(): assert False\n",
        "@pytest.mark.xfail(strict=False)\ndef test_x(): pass\n",
    ],
    ids=["xfail", "xpass"],
)
def test_t5_xfail_and_xpass_fail_session(session, body):
    result = session("linux", "import pytest\n" + body)
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*test_case.py::test_x*"])


def test_t6_expected_platform_mismatch_fails_session(session, monkeypatch):
    monkeypatch.setenv("LOOPCTL_EXPECT_PLATFORM", "linux")
    result = session("darwin", "def test_a(): pass\n")
    result.assert_outcomes(passed=1)
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*LOOPCTL_EXPECT_PLATFORM*linux*darwin*"])
