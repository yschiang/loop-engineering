"""policy.load: the profiles of workflow.yaml and the digest of the bytes
they were read from, never an exception (design DD-2)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ApprovedRun, Fakes, Result
from fakes import scenarios

from loopctl import policy

Cli = Callable[..., Result]

IMPLEMENTER = {
    "transport": "orca",
    "runtime": "claude",
    "provider": "anthropic",
    "model": "claude-opus-5-5",
    "probe_effort": "high",
    "workspace": "preflight-engineer",
    "orca_allowed": ["send", "check", "ask"],
    "keep": {
        "env": [
            "ANTHROPIC_BASE_URL",
            "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL",
            "ENABLE_TOOL_SEARCH",
        ],
        "hooks_matching": "ORCA_AGENT_HOOK",
        "plugins": ["superpowers@claude-plugins-official"],
    },
    "permissions": {
        "allow": [
            "Read",
            "Glob",
            "Grep",
            "Bash(git status*)",
            "Bash(git rev-parse *)",
            "Bash(ls *)",
            "Bash(cat *)",
            "Bash(pwd)",
        ],
        "deny": [
            "Bash(git push *)",
            "Bash(gh *)",
            "Bash(loopctl *)",
            "Bash(orca orchestration task-create *)",
            "Bash(orca orchestration worker-start *)",
            "Bash(orca orchestration run-create *)",
            "Bash(orca orchestration run-use *)",
        ],
    },
}

REVIEWER = {
    "transport": "orca",
    "runtime": "codex",
    "provider": "openai",
    "model": "gpt-6-astra",
    "probe_effort": "xhigh",
    "workspace": "preflight-reviewer",
    "sandbox": "read-only",
    "approval": "never",
    "config": {"check_for_update_on_startup": False, "features.hooks": False},
    "exclude": {"plugins": []},
}


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def example() -> Any:
    """The DD-2 example policy as a document to change."""
    return yaml.safe_load(scenarios.POLICY)


def written(path: Path, document: Any) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def profile_field(loaded: policy.Policy, role: str, name: str) -> Any:
    """A field of the role's Profile, or None when there is no such profile."""
    return getattr(loaded.profiles.get(role), name, None)


def test_profiles_are_parsed_with_the_file_digest(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(scenarios.POLICY)

    loaded = policy.load(path)

    implementer = profile_field(loaded, "implementer", "fields") or {}
    reviewer = profile_field(loaded, "reviewer", "fields") or {}
    for name, value in IMPLEMENTER.items():
        assert implementer.get(name) == value, name
    for name, value in REVIEWER.items():
        assert reviewer.get(name) == value, name
    assert loaded.digest == sha256(path.read_bytes())
    assert loaded.timeout_s == 900
    assert loaded.errors == []


def test_profile_missing_fields_is_invalid_not_an_error(tmp_path: Path) -> None:
    document = example()
    del document["profiles"]["reviewer"]["model"]

    loaded = policy.load(written(tmp_path / "no-model.yaml", document))

    assert profile_field(loaded, "reviewer", "invalid") == ["model"]
    assert profile_field(loaded, "implementer", "invalid") == []

    document = example()
    document["profiles"]["reviewer"]["runtime"] = "opencode"

    loaded = policy.load(written(tmp_path / "opencode.yaml", document))

    assert "runtime" in (profile_field(loaded, "reviewer", "invalid") or [])


def test_missing_profiles_and_roles_are_not_errors(tmp_path: Path) -> None:
    document = example()
    del document["profiles"]

    loaded = policy.load(written(tmp_path / "no-profiles.yaml", document))

    assert loaded.errors == []
    for role in ("implementer", "reviewer"):
        assert profile_field(loaded, role, "invalid") == ["profile_missing"], role

    document = example()
    del document["profiles"]["reviewer"]

    loaded = policy.load(written(tmp_path / "implementer-only.yaml", document))

    assert profile_field(loaded, "reviewer", "invalid") == ["profile_missing"]

    for plugins, invalid in [(["pdf"], ["exclude_plugins_unsupported"]), ([], [])]:
        document = example()
        document["profiles"]["reviewer"]["exclude"]["plugins"] = plugins

        path = written(tmp_path / f"exclude-{len(plugins)}.yaml", document)

        loaded = policy.load(path)

        assert profile_field(loaded, "reviewer", "invalid") == invalid, plugins


@pytest.mark.parametrize(
    ("text", "errors"),
    [
        pytest.param("profiles: [implementer\n", ["yaml_error"], id="yaml-error"),
        pytest.param("- profiles\n- preflight\n", ["not_a_mapping"], id="list"),
        pytest.param(
            "profiles: implementer\n", ["profiles_not_a_mapping"], id="profiles-string"
        ),
        pytest.param(
            "preflight:\n  timeout_s: -1\n", ["timeout_invalid"], id="negative-timeout"
        ),
        pytest.param(None, ["unreadable"], id="missing-file"),
    ],
)
def test_malformed_policy_is_reported_not_raised(
    tmp_path: Path, text: str | None, errors: list[str]
) -> None:
    path = tmp_path / "workflow.yaml"
    if text is not None:
        path.write_text(text)

    loaded = policy.load(path)

    assert loaded.errors == errors
    assert loaded.timeout_s == 900
    assert loaded.digest == (None if text is None else sha256(text.encode()))


# The DD-2 example with a date YAML parses but cannot build: PyYAML raises
# ValueError ("month must be in 1..12"), not a YAMLError.
UNCONSTRUCTIBLE = scenarios.POLICY + "created_at: 2026-99-99\n"


def outcome(path: Path) -> policy.Policy | Exception:
    """What policy.load(path) gives: the Policy, or the exception it raised."""
    try:
        return policy.load(path)
    except Exception as error:
        return error


def test_unconstructible_scalar_is_a_yaml_error(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(UNCONSTRUCTIBLE)

    loaded = outcome(path)

    assert not isinstance(loaded, Exception), loaded
    assert loaded.errors == ["yaml_error"]
    assert loaded.digest == sha256(path.read_bytes())
    assert loaded.timeout_s == 900


def with_implementer_line(line: str) -> str:
    """The DD-2 example with `line` as one more field of the Implementer
    profile."""
    head, reviewer, tail = scenarios.POLICY.partition("  reviewer:\n")
    return f"{head}    {line}\n{reviewer}{tail}"


def baseline_reviewer(tmp_path: Path) -> policy.Profile | None:
    """The Reviewer profile of the DD-2 example, unchanged."""
    path = tmp_path / "baseline.yaml"
    path.write_text(scenarios.POLICY)
    return policy.load(path).profiles.get("reviewer")


# Values safe_load builds that canonical JSON cannot hold (T2.1-02).
@pytest.mark.parametrize(
    "line",
    [
        pytest.param("notes: 2026-10-03", id="date"),
        pytest.param("notes: !!binary aGVsbG8=", id="binary"),
        pytest.param("notes: !!set {a, b}", id="set"),
        pytest.param("notes: {a: 1, 2: b}", id="string-and-integer-keys"),
        pytest.param("notes: {2: b}", id="integer-key"),
        pytest.param("notes: .nan", id="nan"),
        pytest.param("notes: .inf", id="infinity"),
    ],
)
def test_profile_values_that_are_not_json_make_it_invalid(
    tmp_path: Path, line: str
) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(with_implementer_line(line))

    loaded = policy.load(path)

    assert loaded.errors == []
    assert profile_field(loaded, "implementer", "invalid") == ["profile_not_json"]
    assert profile_field(loaded, "implementer", "fields") == {}
    assert loaded.profiles.get("reviewer") == baseline_reviewer(tmp_path)


# An anchor used inside its own value builds a container that holds itself;
# one used beside it only shares a container, which JSON writes twice.
@pytest.mark.parametrize(
    ("line", "profile"),
    [
        pytest.param(
            "notes: &notes {again: *notes}",
            policy.Profile("implementer", {}, ["profile_not_json"]),
            id="mapping-in-itself",
        ),
        pytest.param(
            "notes: &notes [*notes]",
            policy.Profile("implementer", {}, ["profile_not_json"]),
            id="list-in-itself",
        ),
        pytest.param(
            "notes: [&notes [a], *notes]",
            policy.Profile("implementer", {**IMPLEMENTER, "notes": [["a"], ["a"]]}, []),
            id="list-twice",
        ),
    ],
)
def test_aliases_are_json_unless_a_value_holds_itself(
    tmp_path: Path, line: str, profile: policy.Profile
) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(with_implementer_line(line))

    loaded = outcome(path)

    assert not isinstance(loaded, Exception), loaded
    assert loaded.errors == []
    assert loaded.profiles.get("implementer") == profile
    assert loaded.profiles.get("reviewer") == baseline_reviewer(tmp_path)


REPO = "yschiang/loop-engineering"
FEATURE = "orca-preflight"


@pytest.mark.parametrize(
    ("case", "status"),
    [
        pytest.param("registered", "not_approved", id="registered-not-approved"),
        pytest.param("changed", "digest_mismatch", id="changed-after-approval"),
        pytest.param("unregistered", "not_registered", id="not-registered"),
        pytest.param("unreadable", "unreadable", id="file-unreadable"),
    ],
)
def test_preflight_refuses_without_an_approved_policy(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    fakes: Fakes,
    home: Path,
    case: str,
    status: str,
) -> None:
    run = approved_run(
        REPO,
        FEATURE,
        scenarios.POLICY,
        register=case != "unregistered",
        approve=case in ("changed", "unreadable"),
    )
    if case == "changed":
        run.policy.write_text(scenarios.POLICY + "# changed after the approval\n")
    if case == "unreadable":
        run.policy.unlink()

    r = cli("preflight", *run.run, "--role", "implementer")

    assert r.code == 1
    assert r.get("result", "error") == "policy_not_approved"
    assert r.get("result", "policy") == status
    assert r.get("result", "policy") == cli("status", *run.run).get(
        "result", "policy", "status"
    )
    assert fakes.calls() == []
    assert list((home / "repos").rglob("receipts")) == []


def test_approved_policy_is_not_refused(
    cli: Cli, approved_run: Callable[..., ApprovedRun]
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)

    r = cli("preflight", *run.run, "--role", "implementer")

    assert r.get("result", "error") != "policy_not_approved"
    assert r.code != 1


def test_unapproved_unconstructible_policy_is_refused(
    cli: Cli, approved_run: Callable[..., ApprovedRun], fakes: Fakes
) -> None:
    run = approved_run(REPO, FEATURE, UNCONSTRUCTIBLE, approve=False)

    r = cli("preflight", *run.run, "--role", "implementer")

    assert r.exc is None
    assert r.code == 1
    assert r.get("result", "error") == "policy_not_approved"
    assert r.get("result", "policy") == "not_approved"
    assert fakes.calls() == []
