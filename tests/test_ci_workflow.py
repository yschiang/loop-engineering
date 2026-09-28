"""M-TPOL t7: .github/workflows/loopctl-ci.yml against workflow.yaml (validation §6).

Checks the structure, and runs each job's steps before the artifact upload locally in a
scratch checkout: the SHA check must fail on a HEAD other than the PR head, and the uploaded
file must carry the §6.1 fields. Real CI behaviour is evidenced by B1's G3 run.

Workflow text is untrusted: steps are run only when the workflow passes the policy blob
binding, sets no workflow or job key or env name outside the allow-lists, and every step
before the upload is an approved command, and then only in the scratch dir with a minimal
environment.
"""

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
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
# The accepted SHA checks: the checked-out HEAD itself, compared for equality with the PR head.
SHA_CHECK_COMMANDS = frozenset(
    {f'test "$(git rev-parse HEAD)" = "{HEAD_SHA}"', f'[ "$(git rev-parse HEAD)" = "{HEAD_SHA}" ]'}
)
UPLOAD = f"upload of {ARTIFACT} before tests"
# The simulated run: GITHUB_SHA is the merge commit a pull_request run would test by default.
RUN_ID, RUN_ATTEMPT, MERGE_SHA = "4242", "2", "f" * 40
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

# The approved commands before the upload: a SHA check from SHA_CHECK_COMMANDS, or a producer
# `python3 - <<'EOF'` that only dumps literal field names mapped to PRODUCER_ENV values into a
# file in the working directory. An approved step has no other key (env, shell,
# continue-on-error, working-directory would change what runs or whether it counts).
STEP_KEYS = {"name", "run"}
PRODUCER = re.compile(r"python3 - <<'EOF'\n(?P<body>.*)\nEOF\n?", re.DOTALL)
PRODUCER_ENV = {"GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_SHA", "HEAD_SHA"}
# The simulated run applies no other workflow or job setting, so any other key or env name
# (BASH_ENV, defaults.run.shell, a job `if`, ...) is a named problem and nothing is run.
WORKFLOW_KEYS = {"name", "on", True, "permissions", "jobs"}  # YAML 1.1 reads a bare `on` key as True
JOB_KEYS = {"runs-on", "timeout-minutes", "env", "steps"}
WORKFLOW_ENV: frozenset[str] = frozenset()
JOB_ENV = {"HEAD_SHA"}  # the only workflow env a run step receives
STEP_ENV = {"LOOPCTL_EXPECT_PLATFORM", "BASE_SHA"}  # steps after the upload; approved steps have no env
FILE_NAME = re.compile(r"[\w-][\w.-]*", re.ASCII)
FIELD = re.compile(r"[a-z_]+")
BASH = shutil.which("bash") or "/bin/bash"
NOT_RUN = "step before the upload is not an approved command (not run): "
NOT_RUN_ALL = "(steps not run)"


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _uses(step: dict, action: str) -> bool:
    return str(step.get("uses", "")).startswith(action + "@")


def _is_env_value(node: ast.expr) -> bool:
    match node:
        case ast.Subscript(ast.Attribute(ast.Name("os"), "environ"), ast.Constant(str(name))):
            return name in PRODUCER_ENV
    return False


def _is_producer(run: str) -> bool:
    heredoc = PRODUCER.fullmatch(run)
    if not heredoc or any(line.strip() == "EOF" for line in heredoc["body"].splitlines()):
        return False
    try:
        body = ast.parse(heredoc["body"]).body
    except SyntaxError:
        return False
    match body:
        case [
            ast.Import([ast.alias("json", None), ast.alias("os", None)]),
            ast.Expr(
                ast.Call(
                    ast.Attribute(ast.Name("json"), "dump"),
                    [ast.Dict(keys, values), ast.Call(ast.Name("open"), [ast.Constant(str(path)), ast.Constant("w")], [])],
                    [],
                )
            ),
        ]:
            return (
                FILE_NAME.fullmatch(path) is not None
                and all(isinstance(k, ast.Constant) and FIELD.fullmatch(str(k.value)) for k in keys)
                and all(map(_is_env_value, values))
            )
    return False


def _unlisted(where: str, mapping: object, allowed: set | frozenset) -> list[str]:
    """Names only, never values: env values may be secrets."""
    if not isinstance(mapping, dict):
        return [f"{where} is not a mapping {NOT_RUN_ALL}"]
    return [f"{where} not allowed {NOT_RUN_ALL}: {key}" for key in mapping if key not in allowed]


def _is_approved(step: dict) -> bool:
    run = str(step.get("run", ""))
    return set(step) <= STEP_KEYS and (run.strip() in SHA_CHECK_COMMANDS or _is_producer(run))


def _sandbox_env(home: Path) -> dict[str, str]:
    """Nothing inherited from the test runner: an explicit PATH to git and python3, HOME in
    the scratch dir, no system git config."""
    tools = [shutil.which(tool) for tool in ("git", "python3")]
    path = dict.fromkeys([*(str(Path(t).parent) for t in tools if t), "/usr/bin", "/bin"])
    return {"PATH": os.pathsep.join(path), "HOME": str(home), "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    run = subprocess.run(["git", "-C", str(cwd), *args], env=_sandbox_env(cwd), check=True, capture_output=True, text=True)
    return run.stdout.strip()


def _checkout(work: Path) -> tuple[str, str]:
    """A scratch repo standing for the checkout: (an older commit, the checked-out HEAD)."""
    _git(work, "init", "-q")
    for message in ("older", "head"):
        _git(work, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", message)
    return _git(work, "rev-parse", "HEAD~1"), _git(work, "rev-parse", "HEAD")


def _run_step(name: str, job: dict, step: dict, pr_head: str, work: Path) -> int:
    """Run one `run:` step the way Actions does (bash -e), with ${{ }} substituted, in `work`
    with the sandbox env, the simulated GITHUB_* values and the job's JOB_ENV values."""
    context = {
        "github.event.pull_request.head.sha": pr_head,
        "github.job": name,
        "github.run_id": RUN_ID,
        "github.run_attempt": RUN_ATTEMPT,
    }

    def expand(text: str) -> str:  # an unknown expression stays as is and breaks the bash step
        return EXPRESSION.sub(lambda m: context.get(m.group(1), m.group(0)), text)

    env = {
        **_sandbox_env(work),
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
        "GITHUB_JOB": name,
        "GITHUB_SHA": MERGE_SHA,
        **{k: expand(str(v)) for k, v in job.get("env", {}).items() if k in JOB_ENV},
    }
    script = expand(step["run"])
    bash = [BASH, "--noprofile", "--norc", "-e", "-c", script]
    return subprocess.run(bash, cwd=work, env=env, capture_output=True, timeout=30, check=False).returncode


def _run_before_upload(name: str, job: dict, check: int, upload: int, *, run: bool) -> list[str]:
    """The SHA check fails only on a HEAD other than the PR head; the steps before the upload
    produce the uploaded file with the validation §6.1 fields. Nothing is run unless `run`,
    every `run:` step before the upload is approved and the upload path is a plain file name."""
    steps = job["steps"]
    unapproved = [NOT_RUN + str(s.get("name", s["run"])) for s in steps[:upload] if "run" in s and not _is_approved(s)]
    if unapproved:
        return unapproved
    path = steps[upload].get("with", {}).get("path")
    if not FILE_NAME.fullmatch(str(path)):
        return [f"upload of {ARTIFACT}: path {path!r} is not a file name in the checkout (not run)"]
    if not run:
        return []
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
        produced = work / str(path)
        if not produced.is_file():
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


def job_problems(name: str, job: dict, *, run_steps: bool) -> list[str]:
    problems = []
    steps = job.get("steps", [])
    platform = RUNNER_PLATFORM.get(job.get("runs-on"))
    if platform is None:
        problems.append(f"runs-on {job.get('runs-on')!r} has no known platform")
    if not isinstance(job.get("timeout-minutes"), int):
        problems.append("timeout-minutes missing")
    ordered = [
        ("checkout of PR head SHA", lambda s: _uses(s, "actions/checkout") and s.get("with", {}).get("ref") == HEAD_SHA),
        (SHA_CHECK, lambda s: s.get("run", "").strip() in SHA_CHECK_COMMANDS),
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
    unlisted = _unlisted("job key", job, JOB_KEYS) + _unlisted("job env", job.get("env", {}), JOB_ENV)
    for step in steps:
        label = step.get("name", step.get("run", step.get("uses")))
        unlisted += _unlisted(f"step env of {label}", step.get("env", {}), STEP_ENV)
    problems += unlisted
    if run_steps and len(found) == len(ordered):  # only approved steps before the upload are run
        problems += _run_before_upload(name, job, found[SHA_CHECK], found[UPLOAD], run=not unlisted)
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
    unlisted = _unlisted("workflow key", ci, WORKFLOW_KEYS) + _unlisted("workflow env", ci.get("env", {}), WORKFLOW_ENV)
    found += unlisted
    g3 = policy["g3"]
    bound = g3.get("workflow_blob_sha") == blob_sha(ci_bytes)
    if not bound:  # an unbound workflow is checked, never run
        found.append("g3.workflow_blob_sha does not match the workflow file blob")
    run_steps = bound and not unlisted
    jobs = ci.get("jobs", {})
    for check in g3["required_checks"]:
        name = check["name"]
        if name not in jobs:
            found.append(f"job {name}: required check has no job of the same name")
            continue
        found += [f"job {name}: {p}" for p in job_problems(name, jobs[name], run_steps=run_steps)]
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


def _sha_check_on_head_parent(ci, policy):
    _step_running(ci, "git rev-parse HEAD")["run"] = f'test "$(git rev-parse HEAD~1)" != "{HEAD_SHA}"'


def _sha_check_negated_on_head_parent(ci, policy):
    _step_running(ci, "git rev-parse HEAD")["run"] = f'! test "$(git rev-parse HEAD~1)" = "{HEAD_SHA}"'


def _sha_check_inequality(ci, policy):
    _step_running(ci, "git rev-parse HEAD")["run"] = f'test "$(git rev-parse HEAD)" != "{HEAD_SHA}"'


def _empty_artifact(ci, policy):
    _step_running(ci, "tested-sha.json")["run"] = ": > tested-sha.json"


def _empty_object_artifact(ci, policy):
    _step_running(ci, "tested-sha.json")["run"] = "echo '{}' > tested-sha.json"


def _producer_writes_empty_object(ci, policy):
    step = _step_running(ci, "tested-sha.json")
    step["run"] = "python3 - <<'EOF'\nimport json, os\njson.dump({}, open(\"tested-sha.json\", \"w\"))\nEOF\n"


def _upload_path_outside_checkout(ci, policy):
    steps = ci["jobs"]["unit-linux"]["steps"]
    next(s for s in steps if _uses(s, "actions/upload-artifact"))["with"]["path"] = "../tested-sha.json"


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
        (_echo_only_sha_check, f"job unit-linux: missing step: {SHA_CHECK}"),
        (_sha_check_on_head_parent, f"job unit-linux: missing step: {SHA_CHECK}"),
        (_sha_check_negated_on_head_parent, f"job unit-linux: missing step: {SHA_CHECK}"),
        (_sha_check_inequality, f"job unit-linux: missing step: {SHA_CHECK}"),
        (_empty_artifact, f"job unit-linux: {NOT_RUN}Write tested-sha.json"),
        (_empty_object_artifact, f"job unit-linux: {NOT_RUN}Write tested-sha.json"),
        (_producer_writes_empty_object, "job unit-linux: tested-sha.json field run_id"),
        (_artifact_records_merge_sha, "job unit-linux: tested-sha.json field tested_sha"),
        (_upload_other_file, "job unit-linux: upload of tested-sha-${{ github.job }}-${{ github.run_attempt }}: path 'other.json'"),
        (_upload_path_outside_checkout, f"job unit-linux: upload of {ARTIFACT}: path '../tested-sha.json' is not a file name"),
    ],
    ids=lambda v: getattr(v, "__name__", "").lstrip("_") or None,
)
def test_t7_variant_fails_and_names_the_job_or_field(mutate, expected):
    ci, policy, ci_bytes = load()
    ci, policy = copy.deepcopy(ci), copy.deepcopy(policy)
    mutate(ci, policy)
    found = problems(ci, policy, ci_bytes)
    assert any(p.startswith(expected) for p in found), found


def test_t7_sha_check_is_still_run_if_the_accepted_commands_admit_a_non_comparing_one(monkeypatch):
    """The run of the SHA check stays a second line behind SHA_CHECK_COMMANDS."""
    echo = f'echo "$(git rev-parse HEAD) {HEAD_SHA}"'
    monkeypatch.setattr(sys.modules[__name__], "SHA_CHECK_COMMANDS", SHA_CHECK_COMMANDS | {echo})
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    _echo_only_sha_check(ci, policy)
    found = problems(ci, policy, ci_bytes)
    expected = "job unit-linux: git rev-parse HEAD check does not fail when HEAD differs from the PR head SHA"
    assert expected in found, found


# Workflow text is untrusted: a step is run only if it is an approved command, only when the
# workflow passes the policy binding, and never with the test runner's environment.
PLANTED = "LOOPCTL_T7_PLANTED_SECRET"
JOB_NOT_RUN = f"job unit-linux: {NOT_RUN}"


def _insert_before_upload(ci, step: dict) -> None:
    steps = ci["jobs"]["unit-linux"]["steps"]
    steps.insert(next(i for i, s in enumerate(steps) if _uses(s, "actions/upload-artifact")), step)


def test_t7_unapproved_step_writing_outside_the_scratch_dir_is_not_run(tmp_path):
    marker = tmp_path / "outside-scratch"
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    _insert_before_upload(ci, {"name": "Plant marker", "run": f"touch '{marker}'"})
    found = problems(ci, policy, ci_bytes)
    assert not marker.exists()
    assert JOB_NOT_RUN + "Plant marker" in found, found


def test_t7_producer_reading_an_unlisted_env_value_is_not_run(monkeypatch):
    secret = "planted-" + "5" * 16
    monkeypatch.setenv(PLANTED, secret)
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    step = _step_running(ci, "tested-sha.json")
    step["run"] = step["run"].replace('os.environ["HEAD_SHA"]', f'os.environ["{PLANTED}"]')
    found = problems(ci, policy, ci_bytes)
    assert not any(secret in p for p in found), found
    assert JOB_NOT_RUN + step["name"] in found, found


@pytest.mark.parametrize("where", ["workflow", "job", "step"])
def test_t7_bash_env_from_the_workflow_is_not_sourced(tmp_path, where):
    marker = tmp_path / "sourced"
    script = tmp_path / "bash-env.sh"
    script.write_text(f"touch '{marker}'\n")
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    target = {"workflow": ci, "job": ci["jobs"]["unit-linux"]}.get(where) or _step_running(ci, "tested-sha.json")
    target.setdefault("env", {})["BASH_ENV"] = str(script)
    found = problems(ci, policy, ci_bytes)
    assert not marker.exists()
    expected = {
        "workflow": f"workflow env not allowed {NOT_RUN_ALL}: BASH_ENV",
        "job": f"job unit-linux: job env not allowed {NOT_RUN_ALL}: BASH_ENV",
        "step": f"job unit-linux: step env of Write tested-sha.json not allowed {NOT_RUN_ALL}: BASH_ENV",
    }[where]
    assert expected in found, found
    if where == "step":
        assert JOB_NOT_RUN + target["name"] in found, found


def _job_env(ci, name: str) -> None:
    ci["jobs"]["unit-linux"]["env"][name] = "x"


def _pytest_step_env(ci, name: str) -> None:
    _step_running(ci, "uv run pytest")["env"][name] = "x"


# Settings the simulated run does not apply change what the real steps do, so each one is a
# named problem and nothing is run: only allow-listed keys and env names count as evidence.
@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda ci: _job_env(ci, "GIT_DIR"), f"job unit-linux: job env not allowed {NOT_RUN_ALL}: GIT_DIR"),
        (lambda ci: ci.update(env={"GIT_DIR": "x"}), f"workflow env not allowed {NOT_RUN_ALL}: GIT_DIR"),
        (
            lambda ci: _pytest_step_env(ci, "BASH_ENV"),
            f"job unit-linux: step env of uv run pytest not allowed {NOT_RUN_ALL}: BASH_ENV",
        ),
        (
            lambda ci: ci["jobs"]["unit-linux"].update(defaults={"run": {"shell": "sh -e {0}"}}),
            f"job unit-linux: job key not allowed {NOT_RUN_ALL}: defaults",
        ),
        (lambda ci: ci.update(defaults={"run": {"shell": "sh -e {0}"}}), f"workflow key not allowed {NOT_RUN_ALL}: defaults"),
        (lambda ci: ci["jobs"]["unit-linux"].update({"if": "false"}), f"job unit-linux: job key not allowed {NOT_RUN_ALL}: if"),
        (lambda ci: ci["jobs"]["unit-linux"].update(env="${{ fromJSON('{}') }}"), f"job unit-linux: job env is not a mapping {NOT_RUN_ALL}"),
    ],
    ids=["job_env", "workflow_env", "step_env", "job_defaults", "workflow_defaults", "job_if", "job_env_expression"],
)
def test_t7_setting_not_on_the_allow_list_is_named_and_nothing_is_run(monkeypatch, mutate, expected):
    module = sys.modules[__name__]
    ran: list[str] = []
    for helper in ("_checkout", "_run_step"):
        real = getattr(module, helper)
        monkeypatch.setattr(module, helper, lambda *a, _real=real, _name=helper: ran.append(_name) or _real(*a))
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    mutate(ci)
    found = problems(ci, policy, ci_bytes)
    assert expected in found, found
    assert ran == [], ran


def test_t7_sha_check_that_may_fail_without_failing_the_job_is_not_run():
    ci, policy, ci_bytes = load()
    ci = copy.deepcopy(ci)
    step = _step_running(ci, "git rev-parse HEAD")
    step["continue-on-error"] = True
    found = problems(ci, policy, ci_bytes)
    assert JOB_NOT_RUN + step["name"] in found, found


def test_t7_workflow_failing_the_policy_binding_is_not_run(monkeypatch):
    module = sys.modules[__name__]
    ran: list[str] = []
    for helper in ("_checkout", "_run_step"):
        real = getattr(module, helper)
        monkeypatch.setattr(module, helper, lambda *a, _real=real, _name=helper: ran.append(_name) or _real(*a))
    ci, policy, ci_bytes = load()
    policy = copy.deepcopy(policy)
    _blob_mismatch(ci, policy)
    found = problems(ci, policy, ci_bytes)
    assert ran == [], ran
    assert any(p.startswith("g3.workflow_blob_sha does not match") for p in found), found


def test_t7_step_run_gets_no_inherited_environment(tmp_path, monkeypatch):
    """Test-authored steps run under the same restrictions as the approved workflow steps."""
    monkeypatch.setenv(PLANTED, "planted-" + "6" * 16)
    step = {"run": "env > env.txt"}
    assert _run_step("unit-linux", {"env": {"HEAD_SHA": HEAD_SHA}}, step, "a" * 40, tmp_path) == 0
    env = dict(line.split("=", 1) for line in (tmp_path / "env.txt").read_text().splitlines() if "=" in line)
    names = sorted(env)  # a failure prints only names, never an inherited value
    assert PLANTED not in names
    assert set(names) - {"PWD", "SHLVL", "_", "OLDPWD"} <= {
        "PATH", "HOME", "LC_ALL", "GIT_CONFIG_NOSYSTEM",
        "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_SHA", "HEAD_SHA",
    }, names
    home, head = env["HOME"], env["HEAD_SHA"]
    assert home == str(tmp_path)
    assert head == "a" * 40
