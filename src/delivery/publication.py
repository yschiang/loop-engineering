"""Review publication content and human-readable status (AC-F13, F14, D01)."""

from __future__ import annotations

from typing import Any

from delivery.correction import MAX_ROUNDS
from delivery.outbox import new_comment_op


def register_publication(state: dict[str, Any], run_id: str, review: dict[str, Any]) -> tuple[str, str]:
    """Full review to the PR, then an actionable issue summary linking to it; the verdict is untouched."""
    ids = f"run {run_id} · review {review['review_id']} · result {review['result_id']} · {review['version_key']}"
    rows = "\n".join(f"- {f['id']} ({'blocking' if f['blocking'] else 'non-blocking'}): {f['problem']} "
                      f"→ expected: {f['expected']}" for f in review["findings"])
    pr_body = (f"## Review {review['review_id']}: {review['verdict']}\n{ids}\n"
               f"head {review['head']} · base {review['base']} · spec {review['spec']}\n\n{rows}")
    blocking = ", ".join(f["id"] for f in review["findings"] if f["blocking"]) or "none"
    issue_body = (f"Review {review['review_id']} ({review['verdict']}), result {review['result_id']}: "
                  f"blocking findings {blocking}. Full review: {{pr_url}}")
    pr_op, issue_op = f"op-pub-pr-{review['result_id']}", f"op-pub-issue-{review['result_id']}"
    new_comment_op(state, pr_op, "pr", pr_body, run_id)
    new_comment_op(state, issue_op, "issue", issue_body, run_id)
    state["operations"][issue_op]["depends_on"] = pr_op
    return pr_op, issue_op


def publication_status(state: dict[str, Any], op_ids: tuple[str, str]) -> str:
    states = [state["operations"][o]["state"] for o in op_ids]
    if all(s == "succeeded" for s in states):
        return "published"
    if "blocked" in states:
        return "blocked"
    if any(s in ("in_flight", "outcome_unknown") for s in states):
        return "publishing"
    return "pending"


def render_status(state: dict[str, Any]) -> str:
    nxt = state.get("next_action") or {}
    budget = state.get("budget", {})
    lines = [f"phase: {state['phase']}", f"version: {state.get('versions_key', '-')}",
             f"next: {nxt.get('kind', '-')} — {nxt.get('detail', '')}", "gates:"]
    for gate, a in state.get("gates", {}).items():
        lines.append(f"  {gate}: {a['status']} @ {a.get('version_key', '-')}  {'; '.join(a.get('reasons', []))}")
    lines.append("blockers:" if state.get("blockers") else "blockers: none")
    lines += [f"  {b['kind']}: " + ", ".join(f"{k}={v}" for k, v in b.items() if k != "kind")
              for b in state.get("blockers", [])]
    lines.append(f"budget: rounds {budget.get('correction_rounds_used', 0)}/{MAX_ROUNDS}, "
                 f"active {budget.get('active_seconds', 0)}s")
    return "\n".join(lines)
