"""Builders of what the fakes answer and of the user's own files, in the
shapes of the research samples (design DD-10;
docs/research/2026-10-03/orca-preflight/samples)."""

from __future__ import annotations

from typing import Any

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
