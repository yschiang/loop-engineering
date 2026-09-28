"""Feature state store (design §3 internal contract). Stub: implemented under T2.1."""

from collections.abc import Callable
from typing import Any

SCHEMA_VERSION = 1


class StoreError(Exception):
    pass


class FeatureNotFound(StoreError):
    pass


class UntrustedState(StoreError):
    pass


class RevisionConflict(StoreError):
    pass


class TransitionConflict(StoreError):
    pass


class MissingObject(StoreError):
    pass


def load(feature: str) -> tuple[int, dict[str, Any]]:
    raise NotImplementedError


def commit(
    feature: str,
    expected_revision: int,
    transition_id: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> int:
    raise NotImplementedError


def put_object(data: bytes) -> str:
    raise NotImplementedError


def get_object(digest: str) -> bytes:
    raise NotImplementedError


def object_ref(digest: str) -> dict[str, str]:
    raise NotImplementedError


def conflicts(feature: str) -> list[str]:
    raise NotImplementedError
