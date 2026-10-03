"""`loopctl preflight`: probe a worker profile of the approved policy
before anything is dispatched (design DD-3, DD-4).

The Claude profile is probed through an Orca terminal and judged on its
launch, readback, report and stop. Its negatives and the settings it
loaded are not judged, so every probe ends with the reason
judgement_incomplete and is never verified; the Codex profile is not
probed (runtime_unsupported)."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import hashlib
import json
import operator
import os
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
            "observed": {},
            "items": {name: dataclasses.asdict(item) for name, item in items.items()},
            "excerpts": {},
            "native_digest": None,
            "verdict": "verified" if verified else "unverified",
            "reasons": reasons,
            "started_at": started_at,
            "finished_at": clock.now(),
            "cleanup": [],
        }
        ref = receipts.write(repo, role, receipt)
        if out is not None:
            write_out(out, receipt)
    return outcome(receipt, ref)


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
    native record names, Orca's Task, Dispatch and terminal, and how it
    was launched."""

    marker: str | None = None
    session: str | None = None
    before: str | None = None
    after: str | None = None
    native: str | None = None
    task: str | None = None
    dispatch: str | None = None
    terminal: str | None = None
    launch: dict[str, Any] | None = None


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
    settings = write_settings(
        receipts.role_dir(repo, role) / "settings" / f"{seen.marker}.json",
        claude_settings(profile, found.user_settings, Path(workspace["path"])),
    )
    command = claude_command(profile, seen.marker, seen.session, settings, directory)
    seen.launch = {
        "command": command,
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
        reasons, session, problem = dispatch(
            role, paths, approved.timeout_s, found, seen, probes, since
        )
        items.update(judge_claude(profile, workspace, session, problem, paths, seen))
    except BaseException:
        with contextlib.suppress(store.IOFailure):
            stop(handle, seen.marker, seen.session, probes)
        raise
    items["stop.confirmed"] = stop(handle, seen.marker, seen.session, probes)
    seen.after = agent_version(runtime)
    items["version.consistent"] = consistent(seen, problem)
    reasons += [
        name if item.reason is None else f"{name}:{item.reason}"
        for name, item in items.items()
        if not item.passed
    ]
    # This version judges neither the negatives nor the settings the worker
    # loaded (DD-6), so no probe is verified.
    return [*reasons, "judgement_incomplete"]


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
    return store.append_record(directory, payload)


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
    steps 1 and 6, the repo of step 3 and the Run of step 4."""

    outside: Path
    inside: Path
    repo: str
    run: str

    @staticmethod
    def of(repo: str, workspace: Path, marker: str, run: str) -> TaskPaths:
        suffix = marker.removeprefix("PFM-")
        return TaskPaths(
            workspace.parent / f"preflight-probe-outside-{suffix}.txt",
            workspace / f"preflight-probe-inside-{suffix}.txt",
            repo,
            run,
        )


def task_text(role: str, marker: str, paths: TaskPaths) -> str:
    """The probe task (DD-5): fixed text in which only the marker and the
    paths vary. Each step is one tool call; a step that is denied is noted
    and the next one taken; worker_done ends it."""
    suffix = marker.removeprefix("PFM-")
    steps = [
        f"Use the Write tool to create {paths.outside} containing the word probe.",
        "Run in Bash: git push --dry-run origin"
        f" HEAD:refs/heads/preflight-probe-{suffix}",
        f"Run in Bash: gh issue list --repo {paths.repo} --limit 1",
        "Run in Bash: orca orchestration task-create"
        f' --spec "probe {suffix}" --run {paths.run}',
        "Run in Bash: loopctl decide --help",
        f"Use the Write tool to create {paths.inside} containing the word probe.",
        "Run in Bash: git status --short",
    ]
    listed = "\n".join(f"{number}. {step}" for number, step in enumerate(steps, 1))
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
        f" steps 1-{len(steps)} and for each one whether it ran or was denied."
        f" Include the marker {marker} in the body."
    )


# How long one `terminal wait` may block, and the pause between two (DD-7).
WAIT_MS = 60_000
WAIT_PAUSE_S = 2.0


def _instant(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text)


def dispatch(
    role: str,
    paths: TaskPaths,
    timeout_s: int,
    found: Environment,
    seen: Probe,
    probes: Path,
    since: float,
) -> tuple[list[str], native.Session | None, str | None]:
    """Steps 9-11 of DD-4: start the probe task on the worker, wait for its
    turn to end, and read its transcript back. Returns the reasons the
    probe stopped short, the session read back, and why there is none."""
    assert found.workspace is not None and seen.marker and seen.terminal
    assert seen.session is not None
    started = orca.worker_start(
        task_text(role, seen.marker, paths),
        seen.terminal,
        found.workspace["id"],
        paths.run,
    )
    if isinstance(started, orca.Problem):
        stage = started.reason.removeprefix("failed_stage:")
        return [f"task_not_started:{stage}"], None, "task_not_started"
    seen.task, seen.dispatch = started.task, started.dispatch
    record(
        probes, "dispatch", seen.marker, task=started.task, dispatch=started.dispatch
    )
    reasons = wait(seen, timeout_s, since)
    session, problem = read_native(seen, since)
    return reasons, session, problem


def read_native(seen: Probe, since: float) -> tuple[native.Session | None, str | None]:
    """The probe session from its transcript, or why there is none."""
    assert seen.marker is not None and seen.session is not None
    found = native.find_claude(Path.home(), seen.marker, seen.session, since)
    if found.path is None:
        return None, found.problem
    try:
        return native.read_claude(found.path, seen.marker), None
    except OSError:
        return None, "native_unreadable"


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
        session, _ = read_native(seen, since)
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


def judge_claude(
    profile: dict[str, Any],
    workspace: dict[str, Any],
    session: native.Session | None,
    problem: str | None,
    paths: TaskPaths,
    seen: Probe,
) -> dict[str, Item]:
    """Step 11 for the Claude profile (DD-6): the items read back from the
    transcript, the probe's own file, and the worker's report."""
    prompt = session.prompt if session is not None else None
    context = session.context if session is not None else None
    # The prompt record places the worker; the first answer after it reads
    # the model back. A transcript without them has no turn of the probe.
    placed = problem or (None if prompt is not None else "no_native_turn")
    answered = placed or (None if context is not None else "no_native_turn")
    named = _field(context, "version")
    seen.native = tools.version(named) if isinstance(named, str) else None
    path, branch = workspace["path"], workspace["branch"].removeprefix("refs/heads/")
    cwd = _field(prompt, "cwd")
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
    calls = len(session.calls) if session is not None else 0
    accepted = prompt is not None and calls > 0
    items["task.accepted"] = Item(
        accepted,
        placed,
        {"prompt_with_marker": True, "tool_calls": "at least 1"},
        None if prompt is None else {"tool_calls": calls},
    )
    written = paths.inside.is_file()
    items["positive.inside_write"] = Item(
        written, None, {"exists": str(paths.inside)}, written, [str(paths.inside)]
    )
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
