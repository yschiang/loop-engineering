"""Worker OS permission boundary: profile generation and negative-probe suite (design §10, DR-01)."""

from __future__ import annotations

import hashlib
import subprocess
import sys
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
    # Run outside the sandbox; exit 0 means the forbidden effect happened. For tools that hide EPERM.
    effect_check: tuple[str, ...] | None = None


@dataclass
class IsolationReport:
    status: str  # verified | unverified
    launcher: str
    profile_digest: str
    results: list[dict[str, str]] = field(default_factory=list)


# A denial only counts when the OS reported it; any other failure is an error, never a pass.
PERMISSION_MARKERS = ("Operation not permitted", "Permission denied")


class UnsupportedPlatform(Exception):
    pass


def _q(path: Path) -> str:
    return '"' + str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(b: Boundary) -> str:
    """Later rules win in Seatbelt: deny writes, then re-allow the attempt's own dirs, then deny reads."""
    lines = ["(version 1)", "(allow default)"]
    lines += [f"(deny file-write* (subpath {_q(p)}))" for p in b.deny_write]
    lines += [f"(allow file-write* (subpath {_q(p)}))" for p in b.allow_write]
    lines += [f"(deny file-read* (subpath {_q(p)}))" for p in b.deny_read]
    return "\n".join(lines)


def launch_argv(b: Boundary, argv: list[str]) -> list[str]:
    if sys.platform == "darwin":
        return ["sandbox-exec", "-p", seatbelt_profile(b), *argv]
    raise UnsupportedPlatform(f"no verified sandbox launcher for {sys.platform}")


def run_suite(b: Boundary, probes: list[Probe], required: list[str]) -> IsolationReport:
    """verified only if every required probe ran and matched: denials by the OS, allowed ones succeeding."""
    try:
        profile = seatbelt_profile(b)
        launcher = launch_argv(b, [])[0]
    except UnsupportedPlatform:
        return IsolationReport("unverified", "none", "", [{"name": n, "expect": "denied", "outcome": "not_run"}
                                                          for n in required])
    results: list[dict[str, str]] = []
    for probe in probes:
        proc = subprocess.run(launch_argv(b, list(probe.argv)), capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            outcome = "allowed"
        elif probe.effect_check is not None:
            happened = subprocess.run(list(probe.effect_check), capture_output=True, check=False).returncode == 0
            outcome = "allowed" if happened else "denied"
        elif any(m in proc.stderr for m in PERMISSION_MARKERS):
            outcome = "denied"
        else:
            outcome = "error"
        results.append({"name": probe.name, "expect": probe.expect, "outcome": outcome,
                        "exit_code": str(proc.returncode), "stderr_tail": proc.stderr[-300:]})
    ran = {r["name"]: r for r in results}
    ok = all(n in ran and ran[n]["outcome"] == ran[n]["expect"] for n in required)
    for n in required:
        if n not in ran:
            results.append({"name": n, "expect": "denied", "outcome": "not_run"})
    return IsolationReport("verified" if ok else "unverified", launcher,
                           hashlib.sha256(profile.encode()).hexdigest(), results)
