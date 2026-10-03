"""Builders of what the fakes answer and of the user's own files, in the
shapes of the research samples (design DD-10;
docs/research/2026-10-03/orca-preflight/samples)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

# The example policy of design DD-2, verbatim.
POLICY = """\
profiles:
  implementer:
    transport: orca
    runtime: claude
    provider: anthropic
    model: claude-opus-5-5
    probe_effort: high
    workspace: preflight-engineer          # Orca 工作區的 displayName
    orca_allowed: [send, check, ask]       # worker 回報用的 orca 子命令
    keep:                                  # 從使用者設定帶入的部分（待決 2）
      env: [ANTHROPIC_BASE_URL, _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL, ENABLE_TOOL_SEARCH]
      hooks_matching: ORCA_AGENT_HOOK
      plugins: [superpowers@claude-plugins-official]
    permissions:
      allow: [Read, Glob, Grep, "Bash(git status*)", "Bash(git rev-parse *)", "Bash(ls *)", "Bash(cat *)", "Bash(pwd)"]
      deny: ["Bash(git push *)", "Bash(gh *)", "Bash(loopctl *)", "Bash(orca orchestration task-create *)", "Bash(orca orchestration worker-start *)", "Bash(orca orchestration run-create *)", "Bash(orca orchestration run-use *)"]
  reviewer:
    transport: orca
    runtime: codex
    provider: openai
    model: gpt-6-astra
    probe_effort: xhigh
    workspace: preflight-reviewer
    sandbox: read-only
    approval: never
    config: {check_for_update_on_startup: false, features.hooks: false}
    exclude: {plugins: []}                 # Codex 要排除的 plugin id；預設照 Feature 1 不排除
preflight:
  timeout_s: 900
"""  # noqa: E501

# The coordinator's Orca terminal, as the samples write a handle.
COORDINATOR_HANDLE = "term_1bf1a70d-64d0-4524-9edf-d46be8bc3470"

# The events of the 13 Orca hooks in the user's settings (research §6.1).
ORCA_HOOK_EVENTS = (
    "PermissionRequest",
    "PostCompact",
    "PostToolUse",
    "PostToolUseFailure",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "TeammateIdle",
    "UserPromptSubmit",
)

# The events of the 11 caveman hooks; the research counts them only.
CAVEMAN_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "Notification",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "SessionEnd",
)

# The tool events, whose hooks carry a matcher.
TOOL_EVENTS = ("PermissionRequest", "PostToolUse", "PostToolUseFailure", "PreToolUse")

# The user's enabled plugins (research §6.1).
PLUGINS = (
    "ralph-wiggum@claude-code-plugins",
    "clangd-lsp@claude-plugins-official",
    "gopls-lsp@claude-plugins-official",
    "superpowers@claude-plugins-official",
    "ponytail@ponytail",
    "frontend-design@claude-plugins-official",
)


def orca_hook(event: str) -> str:
    """An Orca hook command: inline shell that reports only inside an Orca
    terminal, as in the Claude sample's hook_success records."""
    return (
        'if [ -z "${ORCA_AGENT_HOOK_PORT-}" ] || [ -z "${ORCA_AGENT_HOOK_TOKEN-}" ]'
        ' || [ -z "${ORCA_PANE_KEY-}" ]; then exit 0; fi;'
        " { command -p curl -s -X POST"
        f' "http://127.0.0.1:${{ORCA_AGENT_HOOK_PORT}}/{event}"'
        ' -H "Authorization: Bearer ${ORCA_AGENT_HOOK_TOKEN}"'
        " --data-binary @-; } || true"
    )


def user_settings() -> dict[str, Any]:
    """~/.claude/settings.json as the user has it (research §6.1): the
    gateway env, six enabled plugins, and the hooks of Orca (13), caveman
    (11) and Herdr (1), all in the user source."""
    hooks: dict[str, list[dict[str, Any]]] = {}

    def add(event: str, command: str) -> None:
        group: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
        if event in TOOL_EVENTS:
            group = {"matcher": "*", **group}
        hooks.setdefault(event, []).append(group)

    for event in ORCA_HOOK_EVENTS:
        add(event, orca_hook(event))
    for event in CAVEMAN_HOOK_EVENTS:
        add(event, f"node ~/.claude/caveman/hooks/caveman.mjs {event}")
    add("SessionStart", "herdr agent-hook claude session-start")
    return {
        "model": "opus",
        "effortLevel": "high",
        "language": "Traditional Chinese",
        "env": {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787",
            "ENABLE_TOOL_SEARCH": "true",
            "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL": "1",
        },
        "enabledPlugins": {plugin: True for plugin in PLUGINS},
        "hooks": hooks,
        "skipDangerousModePermissionPrompt": True,
    }


# The repo the probes run for, and its remote identity in Orca.
REPO = "yschiang/loop-engineering"
CANONICAL_KEY = f"github.com/{REPO}"

# The ids of samples/orca: the Orca runtime, the author's git repo, the
# unrelated folder repo, and the Run bound to the coordinator's terminal.
RUNTIME_ID = "f4da8646-9b12-4612-9329-cde1baeeb4ef"
REPO_ID = "51c06003-80e7-43a0-9ced-35894a995a97"
FOLDER_REPO_ID = "8ab4509b-7790-493f-bfc1-e82837c32187"
BOUND_RUN = "run_b6098d2f6bed"

# The Orca repo of an independent clone of the same remote (DD-12), and the
# Run run-create makes when the coordinator's terminal has none.
CLONE_REPO_ID = "6c2d1f7e-3b8a-4e5f-9a1c-2d4e6f8a0b1c"
CREATED_RUN = "run_5f0c3a9e7d21"


class Workspaces(Protocol):
    """The paths of conftest's ProbeRepo that Orca reports."""

    author: Path
    clone: Path | None
    implementer: Path
    reviewer: Path


def orca_json(result: dict[str, Any]) -> str:
    """A successful `--json` answer of Orca, as the samples print it."""
    answer = {"id": "9e205843-d580-4c3d-a22c-7c270dab164b", "ok": True}
    answer |= {"result": result, "_meta": {"runtimeId": RUNTIME_ID}}
    return json.dumps(answer, indent=1) + "\n"


def orca_error(code: str, message: str) -> str:
    """A failed `--json` answer of Orca (samples/orca/terminal-wait-shell)."""
    answer = {"id": "8068691e-3fc0-442b-8bfc-361d285dac82", "ok": False}
    answer |= {"error": {"code": code, "message": message}}
    answer |= {"_meta": {"runtimeId": RUNTIME_ID}}
    return json.dumps(answer, indent=1) + "\n"


def orca_status(*, reachable: bool = True) -> dict[str, Any]:
    """The result of `orca status --json` (samples/orca/status.json, with
    the capability list cut short)."""
    runtime = {
        "state": "ready" if reachable else "unavailable",
        "reachable": reachable,
        "connectionState": "connected" if reachable else "disconnected",
        "runtimeId": RUNTIME_ID,
        "appVersion": "1.4.218",
        "capabilities": ["orchestration.contract.v1", "agent.launch.v2"],
    }
    return {
        "target": {"kind": "local"},
        "app": {"running": True, "pid": 97661, "desktopWindowStatus": "available"},
        "runtime": runtime,
        "graph": {"state": "ready"},
    }


def orca_repo(repo_id: str, path: Path, canonical_key: str) -> dict[str, Any]:
    """A git repo of `orca repo list --json` (samples/orca/repo-list.json)."""
    return {
        "id": repo_id,
        "path": str(path),
        "displayName": path.name,
        "badgeColor": "#737373",
        "addedAt": 1790998523792,
        "kind": "git",
        "gitUsername": "yschiang",
        "upstream": None,
        "gitRemoteIdentity": {
            "canonicalKey": canonical_key,
            "remoteName": "origin",
            "remoteUrl": f"https://{canonical_key}.git",
        },
    }


def folder_repo() -> dict[str, Any]:
    """The unrelated folder repo of samples/orca/repo-list.json."""
    return {
        "id": FOLDER_REPO_ID,
        "path": "/Users/johnson.chiang/workspace/gigaxfer",
        "displayName": "cross-node-xfer",
        "badgeColor": "#737373",
        "addedAt": 1790000157267,
        "kind": "folder",
        "upstream": None,
        "gitUsername": "",
    }


def _head(path: Path) -> str:
    """The commit `path` has checked out; "" when it is not a git worktree."""
    done = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def orca_worktree(
    repo_id: str, path: Path, display_name: str, *, main: bool = False
) -> dict[str, Any]:
    """A worktree of `orca worktree list --json`: `id` is
    `<repo-id>::<path>`, `branch` has refs/heads/ before the name
    (samples/orca/worktree-list.json). Each probe workspace is on the
    branch named after its directory, as probe_repo makes it."""
    head = _head(path)
    branch = "refs/heads/" + ("main" if main else path.name)
    git = {
        "path": str(path),
        "head": head,
        "branch": branch,
        "isBare": False,
        "isMainWorktree": main,
    }
    return {
        "id": f"{repo_id}::{path}",
        "repoId": repo_id,
        "projectId": f"github:{REPO}",
        "hostId": "local",
        "path": str(path),
        "head": head,
        "branch": branch,
        "isBare": False,
        "isMainWorktree": main,
        "displayName": display_name,
        "displayNameMode": "automatic" if main else "fixed",
        "isArchived": False,
        "workspaceStatus": "in-progress",
        "git": git,
    }


def orca_repos(probe: Workspaces) -> list[dict[str, Any]]:
    """What Orca has registered: the folder repo, the author's repo and,
    when the Reviewer works in an independent clone, the clone too."""
    repos = [folder_repo(), orca_repo(REPO_ID, probe.author, CANONICAL_KEY)]
    if probe.clone is not None:
        repos.append(orca_repo(CLONE_REPO_ID, probe.clone, CANONICAL_KEY))
    return repos


def orca_worktrees(probe: Workspaces) -> list[dict[str, Any]]:
    """The workspaces of orca_repos: each repo's main worktree, and the
    two probe workspaces, preflight-reviewer in the clone when there is
    one."""
    folder = Path("/Users/johnson.chiang/workspace/gigaxfer")
    reviewer_repo = REPO_ID if probe.clone is None else CLONE_REPO_ID
    worktrees = [
        orca_worktree(FOLDER_REPO_ID, folder, "Looper 0923", main=True),
        orca_worktree(REPO_ID, probe.author, "main", main=True),
        orca_worktree(REPO_ID, probe.implementer, "preflight-engineer"),
    ]
    if probe.clone is not None:
        worktrees.append(orca_worktree(CLONE_REPO_ID, probe.clone, "main", main=True))
    worktrees.append(orca_worktree(reviewer_repo, probe.reviewer, "preflight-reviewer"))
    return worktrees


def orca_run(run_id: str, objective: str) -> dict[str, Any]:
    """The Run of `run-current` and `run-create` (samples/orca/run-current)."""
    return {
        "run": {
            "id": run_id,
            "objective": objective,
            "coordinator_handle": COORDINATOR_HANDLE,
            "consumer_generation": 1,
            "legacy": 0,
            "created_at": "2026-10-03T00:00:00Z",
            "updated_at": "2026-10-03T00:00:00Z",
        }
    }


def environment(
    probe: Workspaces,
    *,
    run: str | None = None,
    reachable: bool = True,
    status: str | None = None,
    run_current: str | None = None,
    repos: list[dict[str, Any]] | None = None,
    worktrees: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Orca answering the environment queries of a preflight (DD-4 step 5)
    in their order, with everything in place: Orca reachable, a Run, and
    the repos and workspaces of `probe`.

    The coordinator's terminal has the Run `run` bound; with None it has
    none, and run-create makes CREATED_RUN. `status` and `run_current`
    replace the stdout of `orca status --json` and of `orca orchestration
    run-current --json`; `repos` and `worktrees` replace the lists.
    `terminal create` fails, so a preflight that gets that far ends at step
    8 without a worker. The `--version` of each tool is the fakes' own."""
    repos = orca_repos(probe) if repos is None else repos
    worktrees = orca_worktrees(probe) if worktrees is None else worktrees
    listed = {"worktrees": worktrees, "totalCount": len(worktrees), "truncated": False}
    bound = {"run": None} if run is None else orca_run(run, "loopctl preflight")
    created = [
        {
            "match": [
                "orchestration", "run-create",
                "--objective", {"capture": "objective"}, "--json",
            ],
            "stdout": orca_json(orca_run(CREATED_RUN, "loopctl preflight")),
        }
    ] if run is None else []  # fmt: skip
    return {
        "orca": [
            {
                "match": ["status", "--json"],
                "stdout": status or orca_json(orca_status(reachable=reachable)),
            },
            {
                "match": ["orchestration", "run-current", "--json"],
                "stdout": run_current or orca_json(bound),
            },
            *created,
            {
                "match": ["repo", "list", "--json"],
                "stdout": orca_json({"repos": repos}),
            },
            {"match": ["worktree", "list", "--json"], "stdout": orca_json(listed)},
            {
                "match": [
                    "terminal", "create",
                    "--worktree", {"capture": "worktree"},
                    "--title", {"capture": "marker"},
                    "--command", {"capture": "command"}, "--json",
                ],
                "stdout": orca_error(
                    "terminal_create_failed", "the scenario refuses a terminal"
                ),
                "exit": 1,
            },
        ]
    }  # fmt: skip
