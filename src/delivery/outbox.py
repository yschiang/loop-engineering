"""Outbox operations and staged dispatch recovery (design §11, DR-07)."""

from __future__ import annotations

from typing import Any, Protocol

EXTRA_RETRIES = 2  # D13: each infra operation may be retried twice after the first attempt


class ResponseUnknown(Exception):
    """The external call's outcome is unknown (response lost, timeout, 5xx)."""


class GitHubPort(Protocol):
    def post_comment(self, target: str, body: str) -> dict[str, Any]: ...
    def find_comment(self, target: str, marker: str) -> dict[str, Any] | None: ...


class RuntimePort(Protocol):
    session_list_consistent: bool

    def create_session(self, title: str) -> str: ...
    def find_sessions(self, marker: str) -> list[str]: ...
    def send_prompt(self, session: str, text: str) -> str: ...
    def list_messages(self, session: str) -> list[dict[str, Any]]: ...
    def stop(self, session: str) -> bool: ...


def new_comment_op(state: dict[str, Any], op_id: str, target: str, body: str, run_id: str) -> dict[str, Any]:
    raise NotImplementedError


def new_dispatch_op(state: dict[str, Any], op_id: str, attempt_id: str, prompt: str) -> dict[str, Any]:
    raise NotImplementedError


def advance(store: Any, state: dict[str, Any], op_id: str, github: GitHubPort | None = None,
            runtime: RuntimePort | None = None) -> dict[str, Any]:
    raise NotImplementedError
