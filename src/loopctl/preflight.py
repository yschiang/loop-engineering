"""`loopctl preflight`: probe a worker profile of the approved policy
before anything is dispatched (design DD-3, DD-4).

No worker is probed: a preflight whose profile and environment hold ends
with the reason probe_not_available, so its verdict is never verified."""

from __future__ import annotations

import dataclasses
import json
import os
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
        if not reasons:
            reasons = environment_reasons(repo, role, approved, found)
        if not reasons:
            reasons = ["probe_not_available"]
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
                "agent_cli_before": None,
                "agent_cli_after": None,
                "native": None,
            },
            "marker": None,
            "native_session_id": None,
            "orca": {
                "run": found.run, "task": None, "dispatch": None, "terminal": None
            },
            "launch": None,
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
        reasons += user_settings_reasons()
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


def user_settings_reasons() -> list[str]:
    """Whether the user's Claude settings, the source of what the profile
    keeps (DD-5), can be read as a JSON object."""
    path = Path.home() / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return ["user_settings_unreadable"]
    return [] if isinstance(settings, dict) else ["user_settings_unreadable"]


def _field(value: Any, *path: str) -> Any:
    """A nested field of JSON `value`; None when a step is missing."""
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def current_versions(runtime: str | None) -> receipts.Versions:
    return receipts.Versions(None, None)
