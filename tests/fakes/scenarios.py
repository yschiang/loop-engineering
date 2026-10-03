"""Builders of what the fakes answer and of the user's own files, in the
shapes of the research samples (design DD-10;
docs/research/2026-10-03/orca-preflight/samples)."""

from __future__ import annotations

import json
import re
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


# The probe worker's terminal, Task and Dispatch, as in the samples.
PROBE_HANDLE = "term_2766ee02-11f9-417d-bc1a-e3500d53c235"
PROBE_TASK = "task_6701bb271487"
PROBE_DISPATCH = "ctx_32ae95da31d6"

# What the fake `claude --version` prints by default (DD-10).
CLAUDE_VERSION = "2.1.288"

# The skills the Claude sample lists: those of the kept superpowers plugin
# and of no plugin.
SKILLS = (
    "openspec-apply-change",
    "openspec-propose",
    "superpowers:brainstorming",
    "superpowers:test-driven-development",
    "superpowers:using-superpowers",
    "superpowers:writing-plans",
    "update-config",
    "code-review",
    "init",
)

# The SessionStart hook of the superpowers plugin (Claude sample, line 6).
SUPERPOWERS_HOOK = '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start'


def claude_project(home: Path, workspace: Path) -> Path:
    """Where Claude Code keeps the transcripts of sessions run in
    `workspace`: every character of the path that is not a letter or a
    digit becomes '-'."""
    name = re.sub(r"[^A-Za-z0-9]", "-", str(workspace))
    return home / ".claude" / "projects" / name


def probe_files(workspace: Path, marker: str) -> tuple[Path, Path]:
    """The files of probe steps 1 and 6: outside the workspace, next to it,
    and inside it (DD-5)."""
    suffix = marker.removeprefix("PFM-")
    return (
        workspace.parent / f"preflight-probe-outside-{suffix}.txt",
        workspace / f"preflight-probe-inside-{suffix}.txt",
    )


def probe_steps(workspace: Path, marker: str, run: str) -> list[tuple[str, str]]:
    """The tool calls of probe steps 1-7, as Claude makes them: (tool, its
    file path or command) (DD-5)."""
    suffix = marker.removeprefix("PFM-")
    outside, inside = probe_files(workspace, marker)
    return [
        ("Write", str(outside)),
        ("Bash", f"git push --dry-run origin HEAD:refs/heads/preflight-probe-{suffix}"),
        ("Bash", f"gh issue list --repo {REPO} --limit 1"),
        ("Bash", f'orca orchestration task-create --spec "probe {suffix}" --run {run}'),
        ("Bash", "loopctl decide --help"),
        ("Write", str(inside)),
        ("Bash", "git status --short"),
    ]


class _Transcript:
    """The records of a Claude transcript, in the order and with the fields
    of the Claude sample: each record links to the one before it."""

    def __init__(self, base: dict[str, Any]) -> None:
        self.base = base
        self.records: list[dict[str, Any]] = []
        self.parent: str | None = None
        self.count = 0

    def meta(self, **fields: Any) -> None:
        self.records.append({**fields, "sessionId": self.base["sessionId"]})

    def add(self, kind: str, **fields: Any) -> str:
        self.count += 1
        uuid = f"{self.count:08x}-0000-4000-8000-{self.count:012x}"
        stamp = f"2026-10-03T03:51:{self.count % 60:02d}.000Z"
        record = {"parentUuid": self.parent, "isSidechain": False, **fields}
        record |= {"type": kind, "uuid": uuid, "timestamp": stamp, **self.base}
        self.records.append(record)
        self.parent = uuid
        return uuid

    def hook(self, event: str, name: str, command: str) -> None:
        attachment = {
            "type": "hook_success",
            "hookName": name,
            "toolUseID": "e84e03be-1176-4dde-b1c8-6672472918e3",
            "hookEvent": event,
            "content": "",
            "stdout": "{}\n",
            "stderr": "",
            "exitCode": 0,
            "command": command,
            "durationMs": 40,
        }
        self.add("attachment", attachment=attachment)

    def assistant(self, content: list[dict[str, Any]], stop: str, **fields: Any) -> str:
        message = {
            "model": fields.pop("model"),
            "id": "msg_011CfedAtx6YqBjVsWpP3cpQ",
            "type": "message",
            "role": "assistant",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
        }
        return self.add(
            "assistant",
            message=message,
            requestId="req_011CfedAs3WVYXf4LB8aEMSc",
            **fields,
        )

    def text(self) -> str:
        return "".join(json.dumps(record) + "\n" for record in self.records)


def claude_transcript(
    workspace: Path,
    marker: str,
    session: str,
    run: str,
    *,
    model: str = "claude-opus-5-5",
    effort: str | None = "high",
    cwd: Path | None = None,
    omit: tuple[str, ...] = (),
    version: str = CLAUDE_VERSION,
    turn: str = "complete",
    ai_title_first: bool = False,
) -> str:
    """The transcript of a probe worker that did every step as the profile
    allows (research P4): steps 1-5 denied by a permission rule, steps 6
    and 7 run, worker_done sent and the turn ended.

    `cwd` is where the worker ran, the workspace unless given; `omit`
    drops the fields `effort` and `cwd` from every record. `turn` is
    `prompt_only` for a worker that never answered. `ai_title_first`
    writes the session title, which also holds the marker, before the
    prompt."""
    where = workspace if cwd is None else cwd
    base: dict[str, Any] = {
        "userType": "external",
        "entrypoint": "cli",
        "cwd": str(where),
        "sessionId": session,
        "version": version,
        "gitBranch": workspace.name,
    }
    if "cwd" in omit:
        del base["cwd"]
    t = _Transcript(base)
    efforts = {} if "effort" in omit or effort is None else {"effort": effort}
    efforts |= {"perTurnEffort": effort} if efforts else {}
    title = {"type": "ai-title", "aiTitle": f"Preflight probe {marker}"}
    t.meta(type="last-prompt", leafUuid="01a546a4-ae1e-48ff-a1f7-99ff6b8192f3")
    t.meta(type="mode", mode="normal")
    t.meta(type="permission-mode", permissionMode="dontAsk")
    t.meta(type="atis-latch", atis="")
    if ai_title_first:
        t.meta(**title)
    t.hook("SessionStart", "SessionStart:startup", orca_hook("SessionStart"))
    t.hook("SessionStart", "SessionStart:startup", SUPERPOWERS_HOOK)
    steps = probe_steps(workspace, marker, run)
    brief = "\n".join(
        f"{number}. Use the Write tool to create {target} containing the word probe."
        if tool == "Write"
        else f"{number}. Run in Bash: {target}"
        for number, (tool, target) in enumerate(steps, 1)
    )
    prompt = (
        "Please carry out this task from my Orca coordinator by following the"
        ' brief I pasted below. \n\n<pasted_content id="5472">\n'
        "You are working inside Orca, a multi-agent IDE. You are a dispatched"
        f" worker.\nYour coordinator's terminal handle is: {COORDINATOR_HANDLE}\n"
        f"Your task ID is: {PROBE_TASK}\n\n"
        f"PREFLIGHT PROBE {marker}\n\n{brief}\n\n"
        "Then report completion with the worker_done command given in your"
        f" instructions. Include the marker {marker} in the body.\n"
        '</pasted_content id="5472">\n'
    )
    t.add(
        "user",
        promptId="d0436dc3-a419-4824-9cf7-b0b4e80eec0a",
        message={"role": "user", "content": prompt},
        permissionMode="dontAsk",
        origin={"kind": "human"},
        promptSource="typed",
        turnOrigin="human",
        turnPosition={"promptIndex": 1, "turnIndex": 1},
    )
    listing = {
        "type": "skill_listing",
        "content": "".join(f"- {name}: a skill\n" for name in SKILLS),
        "skillCount": len(SKILLS),
        "isInitial": True,
        "names": list(SKILLS),
    }
    t.add("attachment", attachment=listing)
    if turn == "prompt_only":
        return t.text()
    if not ai_title_first:
        t.meta(**title)
    thinking = {"type": "thinking", "thinking": "", "signature": "CAQS5woK"}
    t.assistant([thinking], "tool_use", model=model, **efforts)
    report = (
        f"orca orchestration send --from {PROBE_HANDLE} --dispatch-capability"
        f' dcap_<redacted> --type worker_done --subject "Preflight probe {marker}'
        f' complete" --body "{marker}: ran all 7 probe steps in order."'
    )
    calls = [*steps, ("Bash", report)]
    for number, (tool, target) in enumerate(calls, 1):
        call = f"toolu_{number:024d}"
        field = "file_path" if tool == "Write" else "command"
        given = {field: target} | ({"content": "probe\n"} if tool == "Write" else {})
        use = {"type": "tool_use", "id": call, "name": tool, "input": given}
        source = t.assistant([use], "tool_use", model=model, **efforts)
        t.hook("PreToolUse", f"PreToolUse:{tool}", orca_hook("PreToolUse"))
        denied = number <= 5
        if denied:
            said = f"Permission to use {tool} with {field} {target} has been denied."
        else:
            said = "Sent msg_a23ee78d2551" if number == 8 else "done"
        result = {
            "type": "tool_result",
            "content": said,
            "is_error": denied,
            "tool_use_id": call,
        }
        marks = {"toolDenialKind": "permission-rule"} if denied else {}
        t.add(
            "user",
            promptId="d0436dc3-a419-4824-9cf7-b0b4e80eec0a",
            message={"role": "user", "content": [result]},
            toolUseResult=("Error: " if denied else "") + said,
            **marks,
            sourceToolAssistantUUID=source,
        )
        if not denied:
            t.hook("PostToolUse", f"PostToolUse:{tool}", orca_hook("PostToolUse"))
    summary = {"type": "text", "text": f"I ran all seven probe steps for {marker}."}
    t.assistant([summary], "end_turn", model=model, **efforts)
    t.hook("Stop", "Stop", orca_hook("Stop"))
    t.add("system", subtype="turn_duration", durationMs=31000, messageCount=40)
    return t.text()


def ps_lines(marker: str, session: str, *, environment: bool) -> str:
    """What `ps -Eww -ax -o command=` (`environment`) or `ps -ax -o
    command=` prints while the probe worker runs."""
    worker = f"claude --model claude-opus-5-5 --session-id {session}"
    if environment:
        worker += f" PREFLIGHT_MARKER={marker} ORCA_TERMINAL_HANDLE={PROBE_HANDLE}"
    return f"/sbin/launchd\n{worker}\n/usr/sbin/syslogd\n"


PS_ENVIRONMENT = ["-Eww", "-ax", "-o", "command="]
PS_COMMANDS = ["-ax", "-o", "command="]


def claude_probe(
    probe: Workspaces,
    home: Path,
    marker: str,
    session: str,
    *,
    run: str = BOUND_RUN,
    transcript: dict[str, Any] | None = None,
    files: str = "one",
    wait: str = "idle",
    worker_done: bool = True,
    failed_stage: str | None = None,
    running_after_close: int = 0,
    versions: tuple[str, str] | None = None,
    snapshot: Path | None = None,
    dispatched: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """The whole Orca conversation of a preflight that probes the Claude
    profile in `probe.implementer` (DD-4 steps 5-12a), the worker drawing
    `marker` and `session`: by default every step holds.

    `terminal create` writes the transcript, made by claude_transcript
    with `transcript` as its options, under `home`, and the file of step
    6. `files` is where the transcript goes: `one` named after the
    session, `none`, `two` copies, or one `misnamed`. `wait` is how each
    `terminal wait` ends: `idle`, `timeout`, or `failed` (the terminal is
    gone). The worker reports worker_done unless `worker_done` is False;
    `failed_stage` makes worker-start fail at that stage. After `terminal
    close`, the first `running_after_close` process listings still show
    the worker. `versions` is what `claude --version` prints before and
    after the terminal is closed; `snapshot` logs that directory when the
    terminal is created. Without `dispatched` the probe goes from creating
    the terminal straight to closing it: worker-start, the wait and
    worker-show are left out."""
    workspace = probe.implementer
    text = claude_transcript(workspace, marker, session, run, **(transcript or {}))
    project = claude_project(home, workspace)
    paths = {
        "one": [project / f"{session}.jsonl"],
        "none": [],
        "two": [
            project / f"{session}.jsonl",
            project.with_name(project.name + "-copy") / f"{session}.jsonl",
        ],
        "misnamed": [project / "00000000-0000-4000-8000-000000000000.jsonl"],
    }[files]
    _, inside = probe_files(workspace, marker)
    effects: list[dict[str, Any]] = []
    if snapshot is not None:
        effects.append({"snapshot": str(snapshot)})
    effects += [{"write": {"path": str(path), "text": text}} for path in paths]
    effects.append({"write": {"path": str(inside), "text": "probe\n"}})
    terminal = {
        "executionHostId": "local",
        "handle": PROBE_HANDLE,
        "hostPlatform": "darwin",
        "surface": "visible",
        "title": marker,
        "worktreeId": "{worktree}",
    }
    started = {
        "runId": run,
        "taskId": PROBE_TASK,
        "dispatchId": PROBE_DISPATCH,
        "state": "ready",
        "stage": "input_accepted",
        "mode": {"mode": "terminal", "preferred": "terminal"},
        "residualResources": [],
    }
    if failed_stage is None:
        start: dict[str, Any] = {"stdout": orca_json(started)}
    else:
        failure = orca_error("worker_start_failed", "the worker did not start")
        answer = json.loads(failure)
        answer["error"] |= {
            "state": "failed",
            "stage": failed_stage,
            "failedStage": failed_stage,
            "residualResources": [],
        }
        start = {"stdout": json.dumps(answer, indent=1) + "\n", "exit": 1}
    waited = {
        "idle": {"stdout": orca_json({"terminal": {"handle": PROBE_HANDLE}})},
        "timeout": {"stdout": orca_error("timeout", "timeout"), "exit": 1},
        "failed": {
            "stdout": orca_error("terminal_not_found", "the terminal has exited"),
            "exit": 1,
        },
    }[wait]
    dispatch = {
        "id": PROBE_DISPATCH,
        "runId": run,
        "taskId": PROBE_TASK,
        "assigneeHandle": PROBE_HANDLE,
        "status": "completed" if worker_done else "dispatched",
    }
    closed = {"close": {"handle": PROBE_HANDLE, "ptyKilled": True}}
    orca = environment(probe, run=run)["orca"][:-1]
    orca.append(
        {
            "match": [
                "terminal", "create",
                "--worktree", {"capture": "worktree"},
                "--title", {"capture": "marker"},
                "--command", {"capture": "command"}, "--json",
            ],
            "stdout": orca_json({"terminal": terminal}),
            "effects": effects,
        }
    )  # fmt: skip
    if dispatched:
        orca.append(
            {
                "match": [
                    "orchestration", "worker-start",
                    "--spec", {"capture": "spec"},
                    "--terminal", PROBE_HANDLE,
                    "--worktree", {"capture": "worker_worktree"},
                    "--run", run, "--json",
                ],
                **start,
            }
        )  # fmt: skip
    if dispatched and failed_stage is None:
        orca.append(
            {
                "match": [
                    "terminal", "wait", "--terminal", PROBE_HANDLE,
                    "--for", "tui-idle", "--timeout-ms", {"capture": "timeout_ms"},
                    "--json",
                ],
                **waited,
                "repeat": True,
            }
        )  # fmt: skip
        orca.append(
            {
                "match": [
                    "orchestration", "worker-show", "--dispatch", PROBE_DISPATCH,
                    "--json",
                ],
                "stdout": orca_json({"dispatch": dispatch}),
                "repeat": True,
            }
        )  # fmt: skip
    orca.append(
        {
            "match": ["terminal", "close", "--terminal", PROBE_HANDLE, "--json"],
            "stdout": orca_json(closed),
            "effects": [{"state": {"closed": True}}],
        }
    )
    listed = ps_lines(marker, session, environment=True)
    gone = "/sbin/launchd\n/usr/sbin/syslogd\n"
    ps = [{"match": PS_ENVIRONMENT, "stdout": listed}] * running_after_close
    ps += [
        {"match": PS_ENVIRONMENT, "stdout": gone},
        {"match": PS_COMMANDS, "stdout": gone},
    ]
    scenario = {"orca": orca, "ps": ps}
    if versions is not None:
        before, after = versions
        scenario["claude"] = [
            {
                "match": ["--version"],
                "stdout": f"{before} (Claude Code)\n",
                "when": {"closed": None},
                "repeat": True,
            },
            {
                "match": ["--version"],
                "stdout": f"{after} (Claude Code)\n",
                "when": {"closed": True},
                "repeat": True,
            },
        ]
    return scenario
