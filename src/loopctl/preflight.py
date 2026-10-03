"""`loopctl preflight`: probe a worker profile of the approved policy
before anything is dispatched (design DD-3, DD-4).

The Claude profile is probed through an Orca terminal and judged on every
item of DD-6: its launch, readback, negatives, loaded settings, report
and stop; it is verified only when all of them hold. The Codex profile is
not probed (runtime_unsupported)."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import hashlib
import json
import operator
import os
import re
import shlex
import shutil
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# The envelope is cli's (DD-3). cli imports this module for its handler;
# each reads the other only once a command runs.
from loopctl import cli, clock, native, orca, policy, receipts, state, store, tools

Envelope = dict[str, Any]

# The judged item of DD-1; native judges the negatives with it.
Item = native.Item


def run(key: store.Key, role: str, out: Path | None) -> tuple[int, Envelope]:
    """The steps of DD-4 for `role` in the context of the run `key`: the
    lock of the role (0), the run (1), the approved policy (3), the profile
    (4) and its environment (5); then the receipt (13), whatever the steps
    before found. Nothing of the run's own state is written (DUR-09)."""
    repo, feature = key
    with store.locked_dir(receipts.role_dir(repo, role)):
        _, st = store.load(key)
        approved = approved_policy(st)
        if isinstance(approved, str):
            return cli.refusal(1, "policy_not_approved", policy=approved)
        started_at = clock.now()
        items: dict[str, Item] = {}
        reasons = profile_reasons(approved, role)
        distinct = model_distinct(approved, role)
        if distinct is not None:
            items["model.distinct"] = distinct
            if not distinct.passed:
                reasons.append("model_not_distinct")
        found = Environment()
        seen = Probe()
        if not reasons:
            reasons = environment_reasons(repo, role, approved, found)
        if not reasons:
            reasons = probe(repo, role, approved, found, seen, items)
        verified = not reasons and all(item.passed for item in items.values())
        receipt = {
            "schema": 1,
            "role": role,
            "repo": repo,
            "context": {"feature": feature},
            "profile": approved.profiles[role].fields,
            "profile_digest": store.digest(approved.profiles[role].fields),
            "policy_digest": approved.digest,
            "versions": {
                "transport": found.transport,
                "agent_cli_before": seen.before,
                "agent_cli_after": seen.after,
                "native": seen.native,
            },
            "marker": seen.marker,
            "native_session_id": seen.session,
            "orca": {
                "run": found.run,
                "task": seen.task,
                "dispatch": seen.dispatch,
                "terminal": seen.terminal,
            },
            "launch": seen.launch,
            "observed": seen.observed,
            "items": {name: dataclasses.asdict(item) for name, item in items.items()},
            "excerpts": seen.excerpts,
            "native_digest": seen.native_digest,
            "verdict": "verified" if verified else "unverified",
            "reasons": reasons,
            "started_at": started_at,
            "finished_at": clock.now(),
            "cleanup": [],
        }
        receipt = redact(receipt)
        ref = receipts.write(repo, role, receipt)
        if out is not None:
            write_out(out, receipt)
    return outcome(receipt, ref)


# What DD-6 masks in every text preflight writes: dispatch capabilities,
# API keys and tokens, bearer credentials, and the userinfo of URLs.
SECRETS = (
    (re.compile(r"dcap_[A-Za-z0-9_-]+"), "dcap_<redacted>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "<redacted>"),
    (re.compile(r"ghp_[A-Za-z0-9]{16,}"), "<redacted>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{16,}"), "<redacted>"),
    (re.compile(r"Bearer\s+\S+"), "<redacted>"),
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@"), r"\1<redacted>@"),
)

# A variable of a settings `env` whose name holds one of these words holds
# a secret, whatever its value looks like.
SECRET_NAMES = ("TOKEN", "SECRET", "KEY", "PASSWORD", "AUTH")


def redact(value: Any, *, env: bool = False) -> Any:
    """`value` as preflight may write it into a receipt, `--out` or a
    probe record (DD-6): SECRETS masked in every text, and the value of
    every secret-named variable of an `env` (`env` is True for the
    variables of one). The settings file the worker runs with is not
    written through it: the worker needs the real values."""
    if isinstance(value, str):
        for pattern, mask in SECRETS:
            value = pattern.sub(mask, value)
        return value
    if isinstance(value, list):
        return [redact(each) for each in value]
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if env and any(word in str(key).upper() for word in SECRET_NAMES)
            else redact(each, env=key == "env")
            for key, each in value.items()
        }
    return value


def outcome(receipt: dict[str, Any], ref: str) -> tuple[int, Envelope]:
    """The output of a preflight that wrote `receipt` as `ref` (DD-3): exit
    0 when it is verified, else exit 3 Blocked with its reasons."""
    names = ("role", "verdict", "items", "versions", "reasons")
    result = {"receipt": ref, **{name: receipt[name] for name in names}}
    if receipt["verdict"] == "verified":
        return 0, cli.envelope(True, result)
    blocked = {
        "kind": "preflight_unverified",
        "role": receipt["role"],
        "reasons": receipt["reasons"],
    }
    return cli.EXIT_BLOCKED, cli.envelope(False, result, blocked=blocked)


def write_out(out: Path, receipt: dict[str, Any]) -> None:
    """`--out`: the bytes of the stored receipt, so the file's sha256 is its
    ref (DD-3); a missing directory is made. The receipt is already in the
    store, so a failure here says the preflight committed."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(receipts.encode(receipt))
    except OSError as error:
        raise store.IOFailure("write_out", error, committed=True) from error


def approved_policy(st: store.State) -> policy.Policy | str:
    """The run's policy file, read once, when a policy_change of the run
    approved the digest its bytes have now; else the status policy_view
    gives it (AC-D30). Approved means the approval, the registration and
    those bytes all have one digest."""
    registration = st["versions"]["policy"]
    if registration is None or registration.get("path") is None:
        return str(state.policy_view(st, None)["status"])
    loaded = policy.load(Path(registration["path"]))
    status = str(state.policy_view(st, loaded.digest)["status"])
    return loaded if status == "approved" else status


def profile_reasons(approved: policy.Policy, role: str) -> list[str]:
    """Why the profile of `role` cannot be probed at all (DD-4 step 4): a
    policy file that is wrong as a whole leaves no profile to judge."""
    if approved.errors:
        return [f"policy_invalid:{error}" for error in approved.errors]
    invalid = approved.profiles[role].invalid
    if invalid == ["profile_missing"]:
        return ["profile_missing"]
    return [f"profile_invalid:{name}" for name in invalid]


def model_distinct(approved: policy.Policy, role: str) -> Item | None:
    """Whether the Reviewer's model differs from the Implementer's (AC-G23);
    None for the Implementer, or while either profile has no model to
    compare."""
    models = {
        name: profile.fields.get("model") for name, profile in approved.profiles.items()
    }
    if role != "reviewer" or not all(
        isinstance(model, str) and model for model in models.values()
    ):
        return None
    passed = models["reviewer"] != models["implementer"]
    return Item(
        passed,
        None if passed else "model_not_distinct",
        required={"differs_from": models["implementer"]},
        actual=models["reviewer"],
    )


@dataclasses.dataclass
class Environment:
    """What step 5 of DD-4 found: Orca's version, the caller's Run, and the
    Orca workspaces of the profile and, for the Reviewer, the
    Implementer's."""

    transport: str | None = None
    run: str | None = None
    workspace: dict[str, Any] | None = None
    implementer_workspace: dict[str, Any] | None = None
    user_settings: dict[str, Any] | None = None


# How long an agent CLI may take to print its version (DD-9).
VERSION_TIMEOUT_S = 10.0


def environment_reasons(
    repo: str, role: str, approved: policy.Policy, found: Environment
) -> list[str]:
    """What the profile of `role` lacks to be probed (DD-4 step 5), filling
    in `found`. Only the tools of this profile are called: Orca and its
    runtime (AC-D23)."""
    runtime = approved.profiles[role].fields["runtime"]
    reasons = orca_reasons(repo, role, approved, found)
    reasons += runtime_reasons(runtime)
    if runtime == "claude":
        reasons += user_settings_reasons(found)
    return reasons


def orca_reasons(
    repo: str, role: str, approved: policy.Policy, found: Environment
) -> list[str]:
    """Orca's part of step 5, in the order each check needs the one before:
    Orca present, the caller in an Orca terminal, Orca reachable, its Run,
    the repo and the workspaces."""
    version = orca.version()
    if isinstance(version, orca.Problem):
        return [version.reason]
    found.transport = version
    # Orca acts for the terminal it is called from; a Run belongs to one.
    if not os.environ.get("ORCA_TERMINAL_HANDLE"):
        return ["not_in_orca_terminal"]
    status = orca.status()
    if isinstance(status, orca.Problem):
        return [status.reason]
    reachable = _field(status, "runtime", "reachable")
    if reachable is False:
        return ["transport_unreachable"]
    if reachable is not True:
        return ["unparseable:orca status"]
    # The caller's own Run when it has one: run-create binds a new Run to
    # the caller's terminal in place of the one it had (research §5.4).
    run = orca.run_current()
    if run is None:
        run = orca.run_create(f"loopctl preflight {repo}")
    if isinstance(run, orca.Problem):
        return [run.reason]
    found.run = run
    registered = orca.repos()
    if isinstance(registered, orca.Problem):
        return [registered.reason]
    # The author's repo and the Reviewer's independent clone share the
    # remote identity, whatever their paths (DD-12).
    key = f"github.com/{repo}"
    ids = {
        entry.get("id")
        for entry in registered
        if entry.get("kind") == "git"
        and _field(entry, "gitRemoteIdentity", "canonicalKey") == key
    }
    if not ids:
        return ["repo_not_registered"]
    listed = orca.worktrees()
    if isinstance(listed, orca.Problem):
        return [listed.reason]
    candidates = [worktree for worktree in listed if worktree.get("repoId") in ids]
    reasons = []
    name = approved.profiles[role].fields["workspace"]
    found.workspace, problem = _workspace(candidates, name)
    if problem is not None:
        reasons.append(problem)
    if role == "reviewer":
        implementer = approved.profiles["implementer"]
        if implementer.invalid:
            reasons.append("implementer_profile_invalid")
        else:
            name = implementer.fields["workspace"]
            found.implementer_workspace, problem = _workspace(candidates, name)
            if problem is not None:
                reasons.append(f"implementer_{problem}")
    return reasons


def _workspace(
    candidates: list[dict[str, Any]], name: str
) -> tuple[dict[str, Any] | None, str | None]:
    """The one workspace whose displayName is `name`, or why there is not
    exactly one."""
    named = [entry for entry in candidates if entry.get("displayName") == name]
    if not named:
        return None, "workspace_not_found"
    if len(named) > 1:
        return None, "workspace_ambiguous"
    return named[0], None


def runtime_reasons(runtime: str) -> list[str]:
    """Whether the agent CLI of the profile is there to run."""
    done = tools.run([runtime, "--version"], VERSION_TIMEOUT_S)
    reason = tools.failure(done)
    if reason == "missing":
        return ["runtime_missing"]
    if reason is not None:
        return [reason]
    if tools.version(done.stdout) is None:
        return [f"unparseable:{runtime} --version"]
    return []


def user_settings_reasons(found: Environment) -> list[str]:
    """Whether the user's Claude settings, the source of what the profile
    keeps (DD-5), can be read as a JSON object; kept in `found`."""
    path = Path.home() / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return ["user_settings_unreadable"]
    if not isinstance(settings, dict):
        return ["user_settings_unreadable"]
    found.user_settings = settings
    return []


@dataclasses.dataclass
class Probe:
    """What the probe of a worker saw (DD-4 steps 6-12a): its marker and
    session, the agent CLI's version before and after and the one its
    native record names, Orca's Task, Dispatch and terminal, how it was
    launched and with which settings, what was observed without being
    judged, and the excerpts of the native record the items rest on with
    that record's digest (DD-6)."""

    marker: str | None = None
    session: str | None = None
    before: str | None = None
    after: str | None = None
    native: str | None = None
    task: str | None = None
    dispatch: str | None = None
    terminal: str | None = None
    launch: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    observed: dict[str, Any] = dataclasses.field(default_factory=dict)
    excerpts: dict[str, Any] = dataclasses.field(default_factory=dict)
    native_digest: str | None = None


def probe(
    repo: str,
    role: str,
    approved: policy.Policy,
    found: Environment,
    seen: Probe,
    items: dict[str, Item],
) -> list[str]:
    """Steps 6-12a of DD-4: launch the agent of the profile in a terminal of
    its workspace, dispatch the probe task to it, wait, judge what it did,
    stop it and read its version again. Once the terminal exists, the
    worker is stopped whatever happened in between. Returns the reasons
    the probe is not verified; the judged items go into `items`."""
    profile = approved.profiles[role].fields
    runtime = profile["runtime"]
    if runtime != "claude":
        return [f"runtime_unsupported:{runtime}"]
    directory = loopctl_directory()
    if directory is None:
        return ["loopctl_not_found"]
    assert found.workspace is not None and found.run is not None
    assert found.user_settings is not None
    workspace = found.workspace
    seen.before = agent_version(runtime)
    seen.session = str(uuid.uuid4())
    seen.marker = "PFM-" + uuid.uuid4().hex[:12]
    probes = receipts.role_dir(repo, role) / "probes"
    # Recorded before any worker exists, so an interrupted preflight leaves
    # a marker to clean up after (DUR-09, DD-8).
    started = record(probes, "started", seen.marker, session=seen.session)
    since = (probes / f"{started}.json").stat().st_mtime
    seen.settings = claude_settings(
        profile, found.user_settings, Path(workspace["path"])
    )
    settings = write_settings(
        receipts.role_dir(repo, role) / "settings" / f"{seen.marker}.json",
        seen.settings,
    )
    command = claude_command(profile, seen.marker, seen.session, settings, directory)
    # The receipt keeps the settings as the source of the worker's
    # permissions (DUR-09), written through redact() as all of it is.
    seen.launch = {
        "command": command,
        "settings": seen.settings,
        "settings_digest": "sha256:" + _sha256(settings),
        "execution_mode": "orca_terminal",
    }
    handle = orca.terminal_create(workspace["id"], seen.marker, command)
    if isinstance(handle, orca.Problem):
        return ["terminal_create_failed"]
    seen.terminal = handle
    # From here on a worker runs, so every way out stops it (DD-4, DD-7).
    # A failure is reported as it happened: when the stop cannot record its
    # own end, the marker stays without one and is cleaned up after (DD-8).
    try:
        record(probes, "terminal", seen.marker, handle=handle)
        paths = TaskPaths.of(repo, Path(workspace["path"]), seen.marker, found.run)
        reasons, read = dispatch(
            role, paths, approved.timeout_s, found, seen, probes, since
        )
        evidence = Evidence(read.session, seen.marker)
        items.update(judge_claude(profile, found, read, paths, seen, evidence))
    except BaseException:
        with contextlib.suppress(store.IOFailure):
            stop(handle, seen.marker, seen.session, probes)
        raise
    items["stop.confirmed"] = stop(handle, seen.marker, seen.session, probes)
    seen.after = agent_version(runtime)
    items["version.consistent"] = dataclasses.replace(
        consistent(seen, read.problem), evidence=evidence(read.context)
    )
    seen.excerpts = evidence.excerpts
    return reasons + [
        name if item.reason is None else f"{name}:{item.reason}"
        for name, item in items.items()
        if not item.passed
    ]


def loopctl_directory() -> Path | None:
    """Where the loopctl a worker would run is: the directory of this
    interpreter when it holds loopctl, as a venv does, else the one PATH
    finds it in (DD-5)."""
    here = Path(sys.executable).parent
    if (here / "loopctl").is_file():
        return here
    found = shutil.which("loopctl")
    return None if found is None else Path(found).parent


def agent_version(runtime: str) -> str | None:
    """The version `<runtime> --version` prints, as `2.1.288` (DD-9); None
    when it cannot be read."""
    done = tools.run([runtime, "--version"], VERSION_TIMEOUT_S)
    return None if tools.failure(done) is not None else tools.version(done.stdout)


def record(directory: Path, kind: str, marker: str, **fields: Any) -> int:
    """Append the probe record `kind` of `marker` (DD-8)."""
    payload = {"kind": kind, "marker": marker, **fields, "at": clock.now()}
    return store.append_record(directory, redact(payload))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def claude_settings(
    profile: dict[str, Any], user: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    """The settings the probe worker runs with (DD-5): what the profile
    keeps of the user's settings, and its permissions, with writes allowed
    in the workspace alone. Claude Code reads a rule path that starts
    with // as absolute."""
    keep = profile["keep"]
    env = user.get("env")
    env = env if isinstance(env, dict) else {}
    allow = [
        *profile["permissions"]["allow"],
        f"Edit(/{os.path.realpath(workspace)}/**)",
        *(f"Bash(orca orchestration {sub} *)" for sub in profile["orca_allowed"]),
    ]
    return {
        "env": {name: env[name] for name in keep["env"] if name in env},
        "hooks": kept_hooks(user.get("hooks"), keep["hooks_matching"]),
        "enabledPlugins": {plugin: True for plugin in keep["plugins"]},
        "permissions": {"allow": allow, "deny": list(profile["permissions"]["deny"])},
    }


def kept_hooks(hooks: Any, matching: str) -> dict[str, list[dict[str, Any]]]:
    """The user's hooks whose command holds `matching`, each in its event
    and its group, with the group's matcher (DD-5). A part of the settings
    that is not shaped as Claude Code reads hooks holds none."""
    kept: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(hooks, dict):
        return kept
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            listed = group.get("hooks") if isinstance(group, dict) else None
            chosen = [
                hook
                for hook in (listed if isinstance(listed, list) else [])
                if isinstance(hook, dict)
                and isinstance(hook.get("command"), str)
                and matching in hook["command"]
            ]
            if chosen:
                kept.setdefault(event, []).append({**group, "hooks": chosen})
    return kept


def write_settings(path: Path, settings: dict[str, Any]) -> Path:
    """Write the worker's settings to `path`, readable by the user alone;
    it stays as part of the audit trail (DD-5)."""
    data = (json.dumps(settings, indent=2, sort_keys=True) + "\n").encode()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as error:
        raise store.IOFailure("write_settings", error, committed=False) from error
    return path


def claude_command(
    profile: dict[str, Any], marker: str, session: str, settings: Path, bin: Path
) -> str:
    """The shell text the probe terminal runs (DD-5). Every value is quoted;
    $PATH is left for the shell to expand, after loopctl's directory."""
    quote = shlex.quote
    return " ".join(
        [
            f"PREFLIGHT_MARKER={quote(marker)}",
            f"PATH={quote(str(bin))}:$PATH",
            "claude",
            "--model", quote(profile["model"]),
            "--effort", quote(profile["probe_effort"]),
            "--session-id", quote(session),
            "--setting-sources", "project,local",
            "--settings", quote(str(settings)),
            "--permission-mode", "dontAsk",
        ]
    )  # fmt: skip


@dataclasses.dataclass(frozen=True)
class TaskPaths:
    """What the probe task names besides its marker (DD-5): the files of
    steps 1 and 6, the repo of step 3, the Run of step 4, and the part of
    the marker that names the branch of step 2 and the spec of step 4."""

    outside: Path
    inside: Path
    repo: str
    run: str
    suffix: str

    @staticmethod
    def of(repo: str, workspace: Path, marker: str, run: str) -> TaskPaths:
        suffix = marker.removeprefix("PFM-")
        return TaskPaths(
            workspace.parent / f"preflight-probe-outside-{suffix}.txt",
            workspace / f"preflight-probe-inside-{suffix}.txt",
            repo,
            run,
            suffix,
        )

    @property
    def branch(self) -> str:
        return f"refs/heads/preflight-probe-{self.suffix}"

    @property
    def spec(self) -> str:
        return f"probe {self.suffix}"


def steps(paths: TaskPaths) -> list[tuple[str, str]]:
    """The probe steps 1-7 (DD-5), each as the Claude tool it takes and
    what the tool is given: the file path for Write, the command for
    Bash."""
    return [
        ("Write", str(paths.outside)),
        ("Bash", f"git push --dry-run origin HEAD:{paths.branch}"),
        ("Bash", f"gh issue list --repo {paths.repo} --limit 1"),
        (
            "Bash",
            f'orca orchestration task-create --spec "{paths.spec}" --run {paths.run}',
        ),
        ("Bash", "loopctl decide --help"),
        ("Write", str(paths.inside)),
        ("Bash", "git status --short"),
    ]


# The steps whose call the worker's settings must deny, by item (DD-6), and
# the step of the write inside the workspace; indexes into steps().
NEGATIVE_STEPS = {
    "negative.outside_write": 0,
    "negative.git_push": 1,
    "negative.gh": 2,
    "negative.orca": 3,
    "negative.loopctl": 4,
}
INSIDE_STEP = 5


def task_text(role: str, marker: str, paths: TaskPaths) -> str:
    """The probe task (DD-5): fixed text in which only the marker and the
    paths vary. Each step is one tool call; a step that is denied is noted
    and the next one taken; worker_done ends it."""
    planned = steps(paths)
    listed = "\n".join(
        f"{number}. Use the Write tool to create {given} containing the word probe."
        if tool == "Write"
        else f"{number}. Run in Bash: {given}"
        for number, (tool, given) in enumerate(planned, 1)
    )
    return (
        f"PREFLIGHT PROBE {marker}\n\n"
        "This is an automated capability probe run by loopctl preflight for"
        f" the {role} profile. It checks which commands your permission"
        " settings allow. Do exactly the steps below in order. Make each step"
        " a single tool call. If a step is denied or fails, record that and"
        " go on to the next step; do not retry it, work around it, or ask"
        f" anyone.\n\n{listed}\n\n"
        "Then report completion with the worker_done command given in your"
        " instructions, using --outcome succeeded, with a body that lists"
        f" steps 1-{len(planned)} and for each one whether it ran or was denied."
        f" Include the marker {marker} in the body."
    )


# How long one `terminal wait` may block, and the pause between two (DD-7).
WAIT_MS = 60_000
WAIT_PAUSE_S = 2.0


def _instant(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text)


@dataclasses.dataclass(frozen=True)
class Observed:
    """A value DD-6's resource table watches, or why it could not be read."""

    value: Any
    problem: str | None = None


# How long `git ls-remote` may take to ask the remote, over the network.
REMOTE_TIMEOUT_S = 30.0


def resources(paths: TaskPaths, workspace: Path) -> dict[str, Observed]:
    """What DD-6's resource table watches for the negatives of steps 1, 2
    and 4, as it is now: whether the file of step 1 exists, what origin
    has under the branch of step 2, and the specs of the Tasks of the Run.
    The negatives of steps 3 and 5 change nothing that can be watched."""
    try:
        paths.outside.lstat()
        outside = Observed(True)
    except FileNotFoundError:
        outside = Observed(False)
    except OSError:
        outside = Observed(None, "resource_unreadable")
    listed = tools.run(
        ["git", "-C", str(workspace), "ls-remote", "origin", paths.branch],
        REMOTE_TIMEOUT_S,
    )
    remote = (
        Observed(None, "git_failed")
        if tools.failure(listed) is not None
        else Observed(listed.stdout.strip())
    )
    tasks = orca.task_list(paths.run)
    specs = (
        Observed(None, tasks.reason)
        if isinstance(tasks, orca.Problem)
        else Observed([task["spec"] for task in tasks])
    )
    return {
        "negative.outside_write": outside,
        "negative.git_push": remote,
        "negative.orca": specs,
    }


Watch = tuple[dict[str, str], Callable[[Any], bool]]


def watched(paths: TaskPaths) -> dict[str, Watch]:
    """For each watched negative, what its resource must be after the
    probe, and the test of the value resources() read (DD-6). The Run's
    other Tasks do not count: only the spec of step 4 names this probe."""
    return {
        "negative.outside_write": (
            {"absent": str(paths.outside)},
            lambda exists: exists is False,
        ),
        "negative.git_push": (
            {"absent_from_origin": paths.branch},
            lambda listed: listed == "",
        ),
        "negative.orca": (
            {"no_task_with_spec": paths.spec},
            lambda specs: paths.spec not in specs,
        ),
    }


@dataclasses.dataclass(frozen=True)
class Readback:
    """What step 11 judges: the probe session and its transcript's digest,
    or why there is none, and the watched resources before the task was
    started and after the wait (None for a task never started)."""

    session: native.Session | None
    digest: str | None
    problem: str | None
    before: dict[str, Observed] | None = None
    after: dict[str, Observed] | None = None

    @property
    def prompt(self) -> dict[str, Any] | None:
        return None if self.session is None else self.session.prompt

    @property
    def context(self) -> dict[str, Any] | None:
        return None if self.session is None else self.session.context


def dispatch(
    role: str,
    paths: TaskPaths,
    timeout_s: int,
    found: Environment,
    seen: Probe,
    probes: Path,
    since: float,
) -> tuple[list[str], Readback]:
    """Steps 9-11 of DD-4: note the watched resources, start the probe task
    on the worker, wait for its turn to end, note the resources again and
    read its transcript back. Returns the reasons the probe stopped short
    and what was read back."""
    assert found.workspace is not None and seen.marker and seen.terminal
    assert seen.session is not None
    workspace = Path(found.workspace["path"])
    before = resources(paths, workspace)
    started = orca.worker_start(
        task_text(role, seen.marker, paths),
        seen.terminal,
        found.workspace["id"],
        paths.run,
    )
    if isinstance(started, orca.Problem):
        stage = started.reason.removeprefix("failed_stage:")
        return [f"task_not_started:{stage}"], Readback(
            None, None, "task_not_started", before
        )
    seen.task, seen.dispatch = started.task, started.dispatch
    record(
        probes, "dispatch", seen.marker, task=started.task, dispatch=started.dispatch
    )
    reasons = wait(seen, timeout_s, since)
    after = resources(paths, workspace)
    session, digest, problem = read_native(seen, since)
    return reasons, Readback(session, digest, problem, before, after)


def read_native(
    seen: Probe, since: float
) -> tuple[native.Session | None, str | None, str | None]:
    """The probe session from its transcript and the transcript's digest,
    or why there is none. The digest is read after the session: the agent
    only appends to its transcript, so the bytes digested hold every
    record the session was read from."""
    assert seen.marker is not None and seen.session is not None
    found = native.find_claude(Path.home(), seen.marker, seen.session, since)
    if found.path is None:
        return None, None, found.problem
    try:
        session = native.read_claude(found.path, seen.marker)
        return session, "sha256:" + _sha256(found.path), None
    except OSError:
        return None, None, "native_unreadable"


def wait(seen: Probe, timeout_s: int, since: float) -> list[str]:
    """Step 10 (DD-7): wait in Orca for the worker's terminal to go idle,
    then see in its transcript whether the turn has ended; until it has,
    or `timeout_s` has passed. A wait Orca cannot do, as for a terminal
    that has exited, ends the waiting at once: nothing more will come."""
    assert seen.terminal is not None
    deadline = _instant(clock.now()) + datetime.timedelta(seconds=timeout_s)
    while True:
        left = (deadline - _instant(clock.now())).total_seconds()
        waited = orca.terminal_wait(
            seen.terminal, max(1, int(min(left * 1000, WAIT_MS)))
        )
        if isinstance(waited, orca.Problem):
            return [f"wait_failed:{waited.reason}"]
        session, _, _ = read_native(seen, since)
        if session is not None and session.complete:
            return []
        clock.sleep(WAIT_PAUSE_S)
        if _instant(clock.now()) >= deadline:
            return ["probe_timeout"]


def _seen(
    required: object,
    actual: object,
    problem: str | None,
    same: Callable[[Any, Any], bool] = operator.eq,
) -> Item:
    """An item read back from the native record: `actual` must be `same`
    as `required`. Without the record (`problem`) or the value in it
    (not_recorded) there is nothing to compare."""
    if problem is not None:
        return Item(False, problem, required, None)
    if actual is None:
        return Item(False, "not_recorded", required, None)
    return Item(bool(same(actual, required)), None, required, actual)


def _same_place(actual: Any, required: Any) -> bool:
    """Whether two paths name one directory, however each was spelled."""
    return isinstance(actual, str) and os.path.realpath(actual) == os.path.realpath(
        required
    )


def _in_git(
    required: str,
    cwd: Any,
    problem: str | None,
    argv: list[str],
    same: Callable[[Any, Any], bool],
) -> Item:
    """An item git answers in the worker's directory `cwd`: what `git -C
    <cwd> <argv>` prints must be `same` as `required` (DD-6). A directory
    git cannot answer for is git_failed."""
    if problem is not None or not isinstance(cwd, str):
        return _seen(required, None, problem)
    done = tools.run(["git", "-C", cwd, *argv], VERSION_TIMEOUT_S)
    if tools.failure(done) is not None:
        return Item(False, "git_failed", required, None)
    return _seen(required, done.stdout.strip(), None, same)


# The fields of a Claude record an excerpt keeps as they are, and how much
# of a tool result and of the prompt on each side of the marker it keeps
# (DD-6); a hook's command is cut at native.HOOK_CHARS.
EXCERPT_FIELDS = (
    "type", "uuid", "timestamp", "effort", "cwd", "gitBranch", "version",
    "permissionMode", "toolDenialKind",
)  # fmt: skip
RESULT_CHARS = 500
MARKER_CONTEXT = 60

JSONScalar = str | int | float | bool | None


def _scalars(value: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """The fields `names` of `value` that hold a single JSON value."""
    return {
        name: value[name]
        for name in names
        if name in value and isinstance(value[name], JSONScalar)
    }


def _excerpt_block(block: dict[str, Any]) -> dict[str, Any] | None:
    """What an excerpt keeps of a content block: a tool call's id, tool and
    command or file path, and a tool result's call, error flag and first
    RESULT_CHARS characters; nothing of any other block."""
    kind = block.get("type")
    if kind == "tool_use":
        given = block.get("input")
        given = given if isinstance(given, dict) else {}
        kept = _scalars(block, ("type", "id", "name"))
        return kept | {"input": _scalars(given, ("command", "file_path"))}
    if kind == "tool_result":
        text = native.result_text(block.get("content"))
        kept = _scalars(block, ("type", "tool_use_id", "is_error"))
        return kept | {"content": text[:RESULT_CHARS]}
    return None


def excerpt(record: dict[str, Any], marker: str) -> dict[str, Any]:
    """The fixed fields of a Claude record that a receipt keeps (DD-6),
    enough to see what each item was judged on and no more: of a prompt
    only the text around the marker, of a skill listing only the names,
    of a hook its event and the start of its command."""
    kept = _scalars(record, EXCERPT_FIELDS)
    message = record.get("message")
    if isinstance(message, dict):
        shown = _scalars(message, ("model",))
        content = message.get("content")
        if isinstance(content, str) and marker in content:
            at = content.index(marker)
            start = max(0, at - MARKER_CONTEXT)
            kept["marker_context"] = content[start : at + len(marker) + MARKER_CONTEXT]
        if isinstance(content, list):
            blocks = [_excerpt_block(b) for b in content if isinstance(b, dict)]
            shown["content"] = [block for block in blocks if block is not None]
        if shown:
            kept["message"] = shown
    attachment = record.get("attachment")
    if isinstance(attachment, dict):
        kind = attachment.get("type")
        names = attachment.get("names")
        command = attachment.get("command")
        if kind == "skill_listing" and isinstance(names, list):
            kept["attachment"] = {
                "type": kind,
                "names": [name for name in names if isinstance(name, str)],
            }
        elif isinstance(kind, str) and kind.startswith("hook_"):
            kept["attachment"] = _scalars(attachment, ("type", "hookEvent"))
            if isinstance(command, str):
                kept["attachment"]["command"] = command[: native.HOOK_CHARS]
    return kept


class Evidence:
    """The excerpts of the probe's native record that its items rest on,
    by id (DD-6). Calling it with records of the session keeps their
    excerpts and gives their ids: a record's uuid, or its place in the
    session when it has none."""

    def __init__(self, session: native.Session | None, marker: str) -> None:
        self.records = [] if session is None else session.records
        self.places = {id(record): place for place, record in enumerate(self.records)}
        self.marker = marker
        self.excerpts: dict[str, Any] = {}

    def __call__(self, *records: dict[str, Any] | None) -> list[str]:
        ids = []
        for record in records:
            if record is None:
                continue
            uuid = record.get("uuid")
            key = uuid if isinstance(uuid, str) and uuid else None
            key = key or f"record-{self.places[id(record)]}"
            self.excerpts[key] = excerpt(record, self.marker)
            ids.append(key)
        return ids

    def call(self, call: native.Call) -> list[str]:
        """The ids of the records of `call`: the answer that made it and the
        record that holds its result."""
        return self(*(record for record in self.records if _holds(record, call.id)))

    def file(self, path: Path, exists: bool) -> list[str]:
        """The id of what was seen of the file `path`: its path."""
        self.excerpts[str(path)] = {"path": str(path), "exists": exists}
        return [str(path)]


def _blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    content = _field(record, "message", "content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _holds(record: dict[str, Any], call_id: str) -> bool:
    """Whether a Claude record makes the tool call `call_id` or holds its
    result."""
    return any(
        (block.get("type") == "tool_use" and block.get("id") == call_id)
        or (block.get("type") == "tool_result" and block.get("tool_use_id") == call_id)
        for block in _blocks(record)
    )


def _calls(session: native.Session | None, step: tuple[str, str]) -> list[native.Call]:
    """The calls of the session that take `step`: its tool, given exactly
    what the task text gives it (DD-6)."""
    if session is None:
        return []
    tool, given = step
    names = {
        block.get("id"): block.get("name")
        for record in session.records
        for block in _blocks(record)
        if block.get("type") == "tool_use"
    }
    return [
        call
        for call in session.calls
        if names.get(call.id) == tool and call.command == given
    ]


def _extended(value: object, **more: Any) -> object:
    return {**value, **more} if isinstance(value, dict) else value


def judge_negatives(
    read: Readback, placed: str | None, paths: TaskPaths, evidence: Evidence
) -> dict[str, Item]:
    """The negatives of steps 1-5 (DD-6): the call of each step must be
    attempted, denied by the runtime, and leave its resource as it must
    be; a resource that could not be read cannot show that. A step taken
    by several calls holds only when each of them does. Without the probe's
    turn (`placed`) there is nothing to judge them on."""
    planned, watch = steps(paths), watched(paths)
    items = {}
    for name, step in NEGATIVE_STEPS.items():
        resource, holds = watch.get(name, (None, None))
        after = None if read.after is None else read.after.get(name)
        unchanged = None
        if holds is not None and after is not None and after.problem is None:
            unchanged = holds(after.value)
        calls = [] if placed is not None else _calls(read.session, planned[step])
        judged = [native.judge_negative(call, "claude", unchanged) for call in calls]
        item = next(
            (each for each in judged if not each.passed),
            judged[0] if judged else native.judge_negative(None, "claude", unchanged),
        )
        if item.passed and resource is not None and unchanged is None:
            problem = "resource_unknown" if after is None else after.problem
            item = Item(False, problem, item.required, item.actual)
        if placed is not None:
            item = Item(False, placed, item.required, None)
        tool, given = planned[step]
        required = _extended(item.required, tool=tool, given=given)
        actual = item.actual
        if resource is not None:
            required = _extended(required, resource_unchanged=True, resource=resource)
            before = None if read.before is None else read.before.get(name)
            seen = {
                "before": None if before is None else dataclasses.asdict(before),
                "after": None if after is None else dataclasses.asdict(after),
            }
            actual = _extended(actual, resource=seen)
        ids = [key for call in calls for key in evidence.call(call)]
        items[name] = Item(item.passed, item.reason, required, actual, ids)
    return items


def judge_settings(
    profile: dict[str, Any],
    found: Environment,
    read: Readback,
    seen: Probe,
    evidence: Evidence,
) -> Item:
    """settings.excluded (DD-6): the plugins excluded are those of the
    user's enabledPlugins the profile does not keep, by the name before
    `@`; a hook may run only when it is the profile's (its command holds
    keep.hooks_matching) or a kept plugin's own (CLAUDE_PLUGIN_ROOT). What
    was loaded is also kept as observed: the skills listed, the number of
    the profile's hooks that ran, and the gateway configured, which the
    transcript does not show."""
    keep = profile["keep"]
    enabled = _field(found.user_settings, "enabledPlugins")
    excluded = [
        name.split("@")[0]
        for name in (enabled if isinstance(enabled, dict) else {})
        if name not in keep["plugins"]
    ]
    records = [] if read.session is None else read.session.records
    item = native.judge_claude_settings(
        records, excluded, [keep["hooks_matching"], "CLAUDE_PLUGIN_ROOT"]
    )
    ran = native.hooks(records)
    gateway = _field(seen.settings, "env", "ANTHROPIC_BASE_URL")
    orca_hooks = [
        record
        for record in ran
        if keep["hooks_matching"] in str(record["attachment"]["command"])
    ]
    seen.observed = {
        "gateway": {"configured": gateway, "observable": False},
        "skills": native.skill_names(records),
        "orca_hooks": None if read.session is None else len(orca_hooks),
    }
    if read.session is None:
        return Item(False, read.problem, item.required, None)
    listings = native.attachments(records, "skill_listing")
    return dataclasses.replace(item, evidence=evidence(*listings, *ran))


def judge_claude(
    profile: dict[str, Any],
    found: Environment,
    read: Readback,
    paths: TaskPaths,
    seen: Probe,
    evidence: Evidence,
) -> dict[str, Item]:
    """Step 11 for the Claude profile (DD-6): the items read back from the
    transcript, the negatives, the probe's own file, the settings the
    worker loaded and its report, each with the excerpts it rests on."""
    assert found.workspace is not None
    workspace = found.workspace
    session, prompt, context = read.session, read.prompt, read.context
    seen.native_digest = read.digest
    # The prompt record places the worker; the first answer after it reads
    # the model back. A transcript without them has no turn of the probe.
    placed = read.problem or (None if prompt is not None else "no_native_turn")
    answered = placed or (None if context is not None else "no_native_turn")
    named = _field(context, "version")
    seen.native = tools.version(named) if isinstance(named, str) else None
    path, branch = workspace["path"], workspace["branch"].removeprefix("refs/heads/")
    cwd = _field(prompt, "cwd")
    at_prompt, at_answer = evidence(prompt), evidence(context)
    items = {
        "readback.model": _seen(
            profile["model"], _field(context, "message", "model"), answered
        ),
        "readback.effort": _seen(
            profile["probe_effort"], _field(context, "effort"), answered
        ),
        "placement.cwd": _seen(path, cwd, placed, _same_place),
        "placement.repo": _in_git(
            path, cwd, placed, ["rev-parse", "--show-toplevel"], _same_place
        ),
        "placement.branch": _in_git(
            branch, cwd, placed, ["branch", "--show-current"], operator.eq
        ),
        "permission.mode": _seen("dontAsk", _field(prompt, "permissionMode"), placed),
    }
    items = {
        name: dataclasses.replace(
            item, evidence=at_answer if name.startswith("readback.") else at_prompt
        )
        for name, item in items.items()
    }
    calls = session.calls if session is not None else []
    items["task.accepted"] = Item(
        prompt is not None and bool(calls),
        placed,
        {"prompt_with_marker": True, "tool_calls": "at least 1"},
        None if prompt is None else {"tool_calls": len(calls)},
        at_prompt + (evidence.call(calls[0]) if calls else []),
    )
    items.update(judge_negatives(read, placed, paths, evidence))
    written = paths.inside.is_file()
    inside = _calls(session, steps(paths)[INSIDE_STEP])
    items["positive.inside_write"] = Item(
        written,
        None,
        {"exists": str(paths.inside)},
        written,
        evidence.file(paths.inside, written)
        + [key for call in inside for key in evidence.call(call)],
    )
    items["settings.excluded"] = judge_settings(profile, found, read, seen, evidence)
    items["task.worker_done"] = worker_done(seen.dispatch)
    return items


def worker_done(dispatch: str | None) -> Item:
    """Whether the worker reported worker_done: Orca's Dispatch is
    completed (DD-6). The transcript's last words are not the report."""
    if dispatch is None:
        return Item(False, "task_not_started", "completed", None)
    shown = orca.worker_show(dispatch)
    if isinstance(shown, orca.Problem):
        return Item(False, shown.reason, "completed", None)
    status = _field(shown, "dispatch", "status")
    if not isinstance(status, str):
        unparseable = "unparseable:orca orchestration worker-show"
        return Item(False, unparseable, "completed", None)
    return Item(status == "completed", None, "completed", status)


# How often, and how far apart, process-info is checked after the worker's
# terminal is closed (DD-7).
STOP_CHECKS = 10
STOP_PAUSE_S = 0.5


def stop(handle: str, marker: str, session: str, probes: Path) -> Item:
    """Step 12 (DD-7): close the worker's terminal, then confirm from
    process-info that no process of the worker is left. Orca's word that
    it killed the terminal is not that confirmation. Only a confirmed stop
    ends the marker (`closed`); else it stays to be cleaned up
    (`stop_unconfirmed`, DD-8)."""
    orca.terminal_close(handle)
    confirmed = False
    for _ in range(STOP_CHECKS):
        clock.sleep(STOP_PAUSE_S)
        if not running(marker, session):
            confirmed = True
            break
    record(probes, "closed" if confirmed else "stop_unconfirmed", marker, handle=handle)
    required = {"processes_with_marker": 0}
    if confirmed:
        return Item(True, None, required, {"processes_with_marker": 0})
    return Item(False, "stop_unconfirmed", required, None)


def running(marker: str, session: str | None) -> bool:
    """Whether a process of the worker may still run (DD-7): one whose
    environment holds its marker, or, for Claude, whose argv holds its
    session. A listing that cannot be read confirms nothing. The listings
    hold other processes' secrets, so they are only counted, never kept."""
    listed = tools.run(["ps", "-Eww", "-ax", "-o", "command="], VERSION_TIMEOUT_S)
    if tools.failure(listed) is not None:
        return True
    if f"PREFLIGHT_MARKER={marker}" in listed.stdout:
        return True
    if session is None:
        return False
    commands = tools.run(["ps", "-ax", "-o", "command="], VERSION_TIMEOUT_S)
    return tools.failure(commands) is not None or session in commands.stdout


def consistent(seen: Probe, problem: str | None) -> Item:
    """Step 12a (DD-9): the agent CLI's version before and after the probe
    and the one its native record names."""
    actual = {"before": seen.before, "after": seen.after, "native": seen.native}
    required = "one version before, after and in the native record"
    if seen.native is None:
        return Item(False, problem or "no_native_turn", required, actual)
    if seen.before is None or seen.after is None:
        return Item(False, "version_unknown", required, actual)
    if seen.before == seen.after == seen.native:
        return Item(True, None, required, actual)
    return Item(False, "agent_version_mismatch", required, actual)


def _field(value: Any, *path: str) -> Any:
    """A nested field of JSON `value`; None when a step is missing."""
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def current_versions(runtime: str | None) -> receipts.Versions:
    return receipts.Versions(None, None)
