"""M-TPOL t7: .github/workflows/loopctl-ci.yml against workflow.yaml (validation §6).

Checks the structure, and runs each job's steps before the artifact upload locally in a
scratch checkout: the SHA check must fail on a HEAD other than the PR head, and the uploaded
file must carry the §6.1 fields. Real CI behaviour is evidenced by B1's G3 run.
"""

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
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


SHA_CHECK_NAME = "git rev-parse HEAD check"
SHA_CHECK = f"{SHA_CHECK_NAME} against PR head SHA"
UPLOAD = f"upload of {ARTIFACT} before tests"
# The simulated run: GITHUB_SHA is the merge commit a pull_request run would test by default.
RUN_ID, RUN_ATTEMPT, MERGE_SHA = "4242", "2", "f" * 40
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _uses(step: dict, action: str) -> bool:
    return str(step.get("uses", "")).startswith(action + "@")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _checkout(work: Path) -> tuple[str, str]:
    """A scratch repo standing for the checkout: (an older commit, the checked-out HEAD)."""
    _git(work, "init", "-q")
    for message in ("older", "head"):
        _git(work, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", message)
    return _git(work, "rev-parse", "HEAD~1"), _git(work, "rev-parse", "HEAD")


def _run_step(name: str, job: dict, step: dict, pr_head: str, work: Path) -> int:
    """Run one `run:` step the way Actions does (bash -e), with ${{ }} and env substituted."""
    context = {
        "github.event.pull_request.head.sha": pr_head,
        "github.job": name,
        "github.run_id": RUN_ID,
        "github.run_attempt": RUN_ATTEMPT,
    }

    def expand(text: str) -> str:  # an unknown expression stays as is and breaks the bash step
        return EXPRESSION.sub(lambda m: context.get(m.group(1), m.group(0)), text)

    env = {
        **os.environ,
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
        "GITHUB_JOB": name,
        "GITHUB_SHA": MERGE_SHA,
        **{k: expand(str(v)) for k, v in {**job.get("env", {}), **step.get("env", {})}.items()},
    }
    script = expand(step["run"])
    bash = ["bash", "-e", "-c", script]
    return subprocess.run(bash, cwd=work, env=env, capture_output=True, timeout=30, check=False).returncode


def _run_before_upload(name: str, job: dict, check: int, upload: int) -> list[str]:
    """The SHA check fails only on a HEAD other than the PR head; the steps before the upload
    produce the uploaded file with the validation §6.1 fields."""
    steps = job["steps"]
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        older, head = _checkout(work)
        if _run_step(name, job, steps[check], head, work) != 0:
            problems.append(f"{SHA_CHECK_NAME} fails when HEAD is the PR head SHA")
        if _run_step(name, job, steps[check], older, work) == 0:
            problems.append(f"{SHA_CHECK_NAME} does not fail when HEAD differs from the PR head SHA")
        for step in steps[:upload]:
            if "run" in step and _run_step(name, job, step, head, work) != 0:
                return [*problems, f"step before the upload fails: {step.get('name', step['run'])}"]
        path = steps[upload].get("with", {}).get("path")
        produced = work / str(path)
        if not path or not produced.is_file():
            return [*problems, f"upload of {ARTIFACT}: path {path!r} is not a file written before the upload"]
        try:
            record = json.loads(produced.read_text())
        except ValueError:
            record = None
        record = record if isinstance(record, dict) else {}
    expected = {"run_id": RUN_ID, "run_attempt": RUN_ATTEMPT, "job": name, "check_name": name, "tested_sha": head}
    problems += [
        f"{path} field {field}: expected {want!r}, got {record.get(field)!r}"
        for field, want in expected.items()
        if record.get(field) != want
    ]
    return problems


def job_problems(name: str, job: dict) -> list[str]:
    problems = []
    steps = job.get("steps", [])
    platform = RUNNER_PLATFORM.get(job.get("runs-on"))
    if platform is None:
        problems.append(f"runs-on {job.get('runs-on')!r} has no known platform")
    if not isinstance(job.get("timeout-minutes"), int):
        problems.append("timeout-minutes missing")
    ordered = [
        ("checkout of PR head SHA", lambda s: _uses(s, "actions/checkout") and s.get("with", {}).get("ref") == HEAD_SHA),
        (SHA_CHECK, lambda s: "git rev-parse HEAD" in s.get("run", "")),
        (UPLOAD, lambda s: _uses(s, "actions/upload-artifact") and s.get("with", {}).get("name") == ARTIFACT),
        ("uv sync --frozen", lambda s: "uv sync --frozen" in s.get("run", "")),
        ("uv run pytest with LOOPCTL_EXPECT_PLATFORM", lambda s: s.get("run", "").strip().startswith("uv run pytest") and s.get("env", {}).get("LOOPCTL_EXPECT_PLATFORM") == platform),
    ]
    last = -1
    found: dict[str, int] = {}
    for label, match in ordered:
        index = next((i for i, s in enumerate(steps) if match(s)), None)
        if index is None:
            problems.append(f"missing step: {label}")
        elif index < last:
            problems.append(f"step out of order: {label}")
        else:
            last = found[label] = index
    for step in steps:
        uses = step.get("uses")
        if uses and not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses):
            problems.append(f"action not pinned to a full commit SHA: {uses}")
    if len(found) == len(ordered):  # only an ordered prefix is run: never the test commands
        problems += _run_before_upload(name, job, found[SHA_CHECK], found[UPLOAD])
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
        found += [f"job {name}: {p}" for p in job_problems(name, jobs[name])]
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


def _step_running(ci, text: str) -> dict:
    return next(s for s in ci["jobs"]["unit-linux"]["steps"] if text in s.get("run", ""))


def _echo_only_sha_check(ci, policy):
    _step_running(ci, "git rev-parse HEAD")["run"] = f'echo "$(git rev-parse HEAD) {HEAD_SHA}"'


def _empty_artifact(ci, policy):
    _step_running(ci, "tested-sha.json")["run"] = ": > tested-sha.json"


def _empty_object_artifact(ci, policy):
    _step_running(ci, "tested-sha.json")["run"] = "echo '{}' > tested-sha.json"


def _artifact_records_merge_sha(ci, policy):
    step = _step_running(ci, "tested-sha.json")
    step["run"] = step["run"].replace('os.environ["HEAD_SHA"]', 'os.environ["GITHUB_SHA"]')


def _upload_other_file(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    next(s for s in steps if _uses(s, "actions/upload-artifact"))["with"]["path"] = "other.json"


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
        (_echo_only_sha_check, "job unit-linux: git rev-parse HEAD check does not fail when HEAD differs from the PR head SHA"),
        (_empty_artifact, "job unit-linux: tested-sha.json field run_id"),
        (_empty_object_artifact, "job unit-linux: tested-sha.json field run_id"),
        (_artifact_records_merge_sha, "job unit-linux: tested-sha.json field tested_sha"),
        (_upload_other_file, "job unit-linux: upload of tested-sha-${{ github.job }}-${{ github.run_attempt }}: path 'other.json'"),
    ],
    ids=lambda v: getattr(v, "__name__", "").lstrip("_") or None,
)
def test_t7_variant_fails_and_names_the_job_or_field(mutate, expected):
    ci, policy, ci_bytes = load()
    ci, policy = copy.deepcopy(ci), copy.deepcopy(policy)
    mutate(ci, policy)
    found = problems(ci, policy, ci_bytes)
    assert any(p.startswith(expected) for p in found), found
