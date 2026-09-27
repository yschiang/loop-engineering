"""Worker OS permission boundary: profile generation and negative-probe suite (design §10, DR-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Boundary:
    allow_write: tuple[Path, ...]
    deny_write: tuple[Path, ...]
    deny_read: tuple[Path, ...]


@dataclass(frozen=True)
class Probe:
    name: str
    argv: tuple[str, ...]
    expect: str  # "denied" | "allowed"


@dataclass
class IsolationReport:
    status: str  # verified | unverified
    launcher: str
    profile_digest: str
    results: list[dict[str, str]] = field(default_factory=list)


def seatbelt_profile(b: Boundary) -> str:
    raise NotImplementedError


def launch_argv(b: Boundary, argv: list[str]) -> list[str]:
    raise NotImplementedError


def run_suite(b: Boundary, probes: list[Probe], required: list[str]) -> IsolationReport:
    raise NotImplementedError
