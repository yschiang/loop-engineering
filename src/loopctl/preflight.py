"""Capability preflight for a selected profile (design §6). Never reads or writes feature state."""

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from loopctl import clock

ROLES = ("implementer", "reviewer")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def static_reasons(policy: dict[str, Any], role: str, root: Path) -> list[str]:
    """Checks on the approved settings alone; any reason means unverified before launching."""
    profiles = policy.get("profiles") or {}
    reasons = [f"profile_missing:{r}" for r in ROLES if r not in profiles]
    reasons += [f"profile_model_missing:{r}" for r in ROLES if r in profiles and not profiles[r].get("model")]
    models = [profiles[r].get("model") for r in ROLES if r in profiles]
    if len(models) == 2 and models[0] and models[0] == models[1]:
        reasons.append(f"models_identical:{models[0]}")
    settings = profiles.get(role, {}).get("settings")
    if role in profiles and not (settings and (root / settings).is_file()):
        reasons.append(f"profile_settings_missing:{role}")
    return reasons


def run(role: str, out: Path, root: Path) -> dict[str, Any]:
    receipt: dict[str, Any] = {"role": role, "observed_at": clock.now().isoformat()}
    policy_path = root / "workflow.yaml"
    try:
        policy_bytes = policy_path.read_bytes()
        policy = yaml.safe_load(policy_bytes)
    except (OSError, yaml.YAMLError) as e:
        policy_bytes, policy = b"", {}
        reasons = [f"workflow_unreadable:{type(e).__name__}"]
    else:
        reasons = static_reasons(policy, role, root)
    profile = (policy.get("profiles") or {}).get(role, {})
    receipt.update(
        workflow_digest=_sha256(policy_bytes),
        profile=profile,
        profile_digest=_sha256(json.dumps(profile, sort_keys=True).encode()),
    )
    receipt.update(verdict="unverified" if reasons else "verified", reasons=reasons)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
