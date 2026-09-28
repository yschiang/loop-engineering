"""M-TPOL t7: structure of .github/workflows/loopctl-ci.yml against workflow.yaml (validation §6).

Only the structure is checked here; real CI behaviour is evidenced by B1's G3 run.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "loopctl-ci.yml"
POLICY = ROOT / "workflow.yaml"
HEAD_SHA = "${{ github.event.pull_request.head.sha }}"
ARTIFACT = "tested-sha-${{ github.job }}-${{ github.run_attempt }}"
RUNNER_PLATFORM = {"ubuntu-24.04": "linux", "macos-15": "darwin"}
EXTRA_COMMANDS = {
    "unit-linux": [
        "uv run ruff check .",
        "uv run mypy src",
        "scripts/dist-smoke.sh",
        'scripts/hooks/commit-msg --range "$BASE_SHA..$HEAD_SHA"',
    ]
}


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _uses(step: dict, action: str) -> bool:
    return str(step.get("uses", "")).startswith(action + "@")


def job_problems(job: dict) -> list[str]:
    problems = []
    steps = job.get("steps", [])
    platform = RUNNER_PLATFORM.get(job.get("runs-on"))
    if platform is None:
        problems.append(f"runs-on {job.get('runs-on')!r} has no known platform")
    if not isinstance(job.get("timeout-minutes"), int):
        problems.append("timeout-minutes missing")
    ordered = [
        ("checkout of PR head SHA", lambda s: _uses(s, "actions/checkout") and s.get("with", {}).get("ref") == HEAD_SHA),
        ("git rev-parse HEAD check against PR head SHA", lambda s: "git rev-parse HEAD" in s.get("run", "") and HEAD_SHA in json.dumps(s)),
        (f"upload of {ARTIFACT} before tests", lambda s: _uses(s, "actions/upload-artifact") and s.get("with", {}).get("name") == ARTIFACT),
        ("uv sync --frozen", lambda s: "uv sync --frozen" in s.get("run", "")),
        ("uv run pytest with LOOPCTL_EXPECT_PLATFORM", lambda s: s.get("run", "").strip().startswith("uv run pytest") and s.get("env", {}).get("LOOPCTL_EXPECT_PLATFORM") == platform),
    ]
    last = -1
    for label, match in ordered:
        index = next((i for i, s in enumerate(steps) if match(s)), None)
        if index is None:
            problems.append(f"missing step: {label}")
        elif index < last:
            problems.append(f"step out of order: {label}")
        else:
            last = index
    for step in steps:
        uses = step.get("uses")
        if uses and not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses):
            problems.append(f"action not pinned to a full commit SHA: {uses}")
    return problems


def problems(ci: dict, policy: dict, ci_bytes: bytes) -> list[str]:
    found = []
    on = ci.get("on", ci.get(True))  # YAML 1.1 reads a bare `on` key as True
    if not isinstance(on, dict) or list(on) != ["pull_request"]:
        found.append(f"on: trigger must be only pull_request, got {list(on or {})}")
    if ci.get("permissions") != {"contents": "read"}:
        found.append("permissions must be contents: read")
    if "concurrency" in ci:
        found.append("concurrency must not be set")
    g3 = policy["g3"]
    if g3.get("workflow_blob_sha") != blob_sha(ci_bytes):
        found.append("g3.workflow_blob_sha does not match the workflow file blob")
    jobs = ci.get("jobs", {})
    for check in g3["required_checks"]:
        name = check["name"]
        if name not in jobs:
            found.append(f"job {name}: required check has no job of the same name")
            continue
        found += [f"job {name}: {p}" for p in job_problems(jobs[name])]
        runs = [s.get("run", "") for s in jobs[name].get("steps", [])]
        found += [
            f"job {name}: missing step: {cmd}"
            for cmd in EXTRA_COMMANDS.get(name, [])
            if not any(cmd in r for r in runs)
        ]
    return found


def load() -> tuple[dict, dict, bytes]:
    assert CI.exists(), f"missing {CI.relative_to(ROOT)}"
    assert POLICY.exists(), f"missing {POLICY.relative_to(ROOT)}"
    ci_bytes = CI.read_bytes()
    return yaml.safe_load(ci_bytes), yaml.safe_load(POLICY.read_text()), ci_bytes


def test_t7_ci_workflow_matches_policy():
    ci, policy, ci_bytes = load()
    assert problems(ci, policy, ci_bytes) == []
    # D53: the required CI set is only unit-linux (validation §6.3).
    assert policy["g3"]["required_checks"] == [{"name": "unit-linux", "app": "github-actions"}]
    assert set(ci["jobs"]) == {"unit-linux"}
    assert policy["g3"]["workflow"] == str(CI.relative_to(ROOT))


def _drop_pytest(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    steps[:] = [s for s in steps if not s.get("run", "").startswith("uv run pytest")]


def _push_trigger(ci, policy):
    ci.pop(True, None)
    ci["on"] = {"push": {"branches": ["main"]}}


def _extra_push_trigger(ci, policy):
    ci[True]["push"] = {"branches": ["main"]}


def _drop_job(ci, policy):
    del ci["jobs"]["unit-linux"]


def _extra_required_check(ci, policy):
    policy["g3"]["required_checks"].append({"name": "unit-macos", "app": "github-actions"})


def _upload_after_tests(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    upload = next(s for s in steps if _uses(s, "actions/upload-artifact"))
    steps.remove(upload)
    steps.append(upload)


def _checkout_merge_ref(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    next(s for s in steps if _uses(s, "actions/checkout"))["with"].pop("ref")


def _unpinned_action(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    step = next(s for s in steps if _uses(s, "actions/checkout"))
    step["uses"] = "actions/checkout@v4"


def _no_frozen_sync(ci, policy):
    for s in ci["jobs"]["unit-linux"]["steps"]:
        if "uv sync --frozen" in s.get("run", ""):
            s["run"] = "uv sync"


def _blob_mismatch(ci, policy):
    policy["g3"]["workflow_blob_sha"] = "0" * 40


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (_drop_pytest, "job unit-linux: missing step: uv run pytest"),
        (_push_trigger, "on: trigger must be only pull_request"),
        (_extra_push_trigger, "on: trigger must be only pull_request"),
        (_drop_job, "job unit-linux: required check has no job"),
        (_extra_required_check, "job unit-macos: required check has no job"),
        (_upload_after_tests, "job unit-linux: step out of order: uv sync --frozen"),
        (_checkout_merge_ref, "job unit-linux: missing step: checkout of PR head SHA"),
        (_unpinned_action, "job unit-linux: action not pinned to a full commit SHA: actions/checkout@v4"),
        (_no_frozen_sync, "job unit-linux: missing step: uv sync --frozen"),
        (_blob_mismatch, "g3.workflow_blob_sha does not match"),
    ],
    ids=lambda v: getattr(v, "__name__", "").lstrip("_") or None,
)
def test_t7_variant_fails_and_names_the_job_or_field(mutate, expected):
    ci, policy, ci_bytes = load()
    ci, policy = copy.deepcopy(ci), copy.deepcopy(policy)
    mutate(ci, policy)
    found = problems(ci, policy, ci_bytes)
    assert any(p.startswith(expected) for p in found), found
