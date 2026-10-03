"""The policy file, workflow.yaml: its digest and its worker profiles, read
once (design DD-2)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# How long one probe waits for its worker when the policy does not say.
DEFAULT_TIMEOUT_S = 900

# The roles a policy has a profile for.
ROLES = ("implementer", "reviewer")

# The fields of every profile, and the values this version supports.
COMMON = ("transport", "runtime", "provider", "model", "probe_effort", "workspace")
SUPPORTED = {"transport": ("orca",), "runtime": ("claude", "codex")}

# How deep a profile may nest, its own mapping being level 1 and a scalar
# adding none. DD-2's deepest field is at level 3 (`keep.env` holds its
# items); the JSON encoders that write a receipt, which holds the profile at
# its level 2, exhaust Python's stack near level 990.
MAX_DEPTH = 32


@dataclass(frozen=True)
class Profile:
    """The profile of `role` as the file gives it, and what makes it
    unusable: missing or ill-typed fields, `profile_missing`, or an
    unsupported value. `fields` is always plain JSON data: a profile that
    holds anything else is `profile_not_json`, with no fields."""

    role: str
    fields: dict[str, Any]
    invalid: list[str]


@dataclass(frozen=True)
class Policy:
    """A policy file as read once: the digest of its bytes (None when they
    cannot be read), a profile for each role, the probe timeout, and the
    problems of the file as a whole. While `errors` is not empty, every
    profile is invalid and the timeout is the default."""

    digest: str | None
    profiles: dict[str, Profile]
    timeout_s: int
    errors: list[str]


def load(path: Path) -> Policy:
    """Read `path` once: the digest and the profiles come from the same
    bytes, so a change between the two cannot go unseen. Never raises."""
    try:
        data = path.read_bytes()
    except OSError:
        return _unusable(None, ["unreadable"])
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    try:
        document = yaml.safe_load(data)
    # Building the document also raises what the Python types it builds
    # raise, not only YAMLError: ValueError for `2026-99-99` or `!!int abc`,
    # AttributeError for `!!timestamp foo`, RecursionError for deep nesting.
    # Each means these bytes are not a YAML document this policy can be.
    except Exception:
        return _unusable(digest, ["yaml_error"])
    if not isinstance(document, dict):
        return _unusable(digest, ["not_a_mapping"])
    errors = []
    # No `profiles` is a policy without profiles, not a broken one.
    given = document.get("profiles", {})
    if not isinstance(given, dict):
        errors.append("profiles_not_a_mapping")
    timeout_s = _timeout(document.get("preflight", {}))
    if timeout_s is None:
        errors.append("timeout_invalid")
    if errors or timeout_s is None:
        return _unusable(digest, errors)
    profiles = {role: _profile(role, given.get(role)) for role in ROLES}
    return Policy(digest, profiles, timeout_s, [])


def _timeout(settings: Any) -> int | None:
    """`preflight.timeout_s`, the default when absent; None unless it is a
    positive integer."""
    if not isinstance(settings, dict):
        return None
    value = settings.get("timeout_s", DEFAULT_TIMEOUT_S)
    return value if type(value) is int and value > 0 else None


def _unusable(digest: str | None, errors: list[str]) -> Policy:
    """A policy file that is wrong as a whole: no profile of it can be used."""
    profiles = {role: Profile(role, {}, ["policy_invalid"]) for role in ROLES}
    return Policy(digest, profiles, DEFAULT_TIMEOUT_S, errors)


def _profile(role: str, fields: Any) -> Profile:
    if fields is None:
        return Profile(role, {}, ["profile_missing"])
    if not isinstance(fields, dict):
        return Profile(role, {}, ["profile_not_a_mapping"])
    # Every receipt carries the profile and the digest of its canonical JSON,
    # valid or not (DD-2, DD-8). safe_load also builds dates, bytes, sets,
    # non-string keys, NaN, containers that hold themselves and, from a few
    # aliases, values nested deeper than that JSON can be written.
    if not _plain(fields):
        return Profile(role, {}, ["profile_not_json"])
    return Profile(role, fields, _invalid(fields))


def _plain(fields: dict[str, Any]) -> bool:
    """Whether the profile `fields` is plain JSON data no deeper than
    MAX_DEPTH: None, bools, ints, finite floats, strings, and lists and
    string-keyed mappings of such values.

    The walk goes one level at a time, not by recursion, so no depth of the
    value can exhaust the stack. An alias makes one container appear
    wherever it is used: a level holds it once however often it is used, so
    the walk is at most MAX_DEPTH passes over the distinct containers, and
    a container that holds itself is on every level, so it ends past
    MAX_DEPTH."""
    level: list[Any] = [fields]
    for _ in range(MAX_DEPTH):
        below: dict[int, Any] = {}
        for container in level:
            items: Iterable[Any] = container
            if isinstance(container, dict):
                if not all(isinstance(key, str) for key in container):
                    return False
                items = container.values()
            for item in items:
                if isinstance(item, dict | list):
                    below[id(item)] = item
                elif not _scalar(item):
                    return False
        if not below:
            return True
        level = list(below.values())
    return False


def _scalar(value: Any) -> bool:
    """Whether `value` is a JSON scalar: None, a bool, an int, a finite
    float or a string."""
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, bool | int | str)


def _text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _texts(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _scalars(value: Any) -> bool:
    """A mapping of names to values a TOML literal can carry (DD-5)."""
    return isinstance(value, dict) and all(
        _text(key) and isinstance(item, bool | int | float | str)
        for key, item in value.items()
    )


Check = Callable[[Any], bool]


def _mapping(
    fields: dict[str, Any], name: str, checks: Mapping[str, Check]
) -> list[str]:
    """`name` when it is not a mapping, else `name.<key>` for each of its
    keys that fails its check."""
    value = fields.get(name)
    if not isinstance(value, dict):
        return [name]
    return [
        f"{name}.{key}" for key, check in checks.items() if not check(value.get(key))
    ]


def _invalid(fields: dict[str, Any]) -> list[str]:
    """What keeps the profile `fields` from use, in the order of DD-2: the
    common fields, then those its runtime needs."""
    invalid = [
        name
        for name in COMMON
        if not _text(fields.get(name))
        or fields[name] not in SUPPORTED.get(name, (fields[name],))
    ]
    runtime = fields.get("runtime")
    if runtime == "claude":
        if not _texts(fields.get("orca_allowed")):
            invalid.append("orca_allowed")
        keep = {"env": _texts, "hooks_matching": _text, "plugins": _texts}
        invalid += _mapping(fields, "keep", keep)
        invalid += _mapping(fields, "permissions", {"allow": _texts, "deny": _texts})
    elif runtime == "codex":
        invalid += [
            name for name in ("sandbox", "approval") if not _text(fields.get(name))
        ]
        if not _scalars(fields.get("config")):
            invalid.append("config")
        exclude = _mapping(fields, "exclude", {"plugins": _texts})
        # This version passes no plugin exclusion to Codex (DD-5): a profile
        # that asks for one would not be what runs.
        if not exclude and fields["exclude"]["plugins"]:
            exclude = ["exclude_plugins_unsupported"]
        invalid += exclude
    return invalid
