"""Fake agents behind FakeRuntime: they act on the dispatched assignment like real workers would."""

import json
import subprocess
from pathlib import Path

from delivery.runner import evidence_record, run_evidence

from .fakes import FakeRuntime


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class AgentRuntime(FakeRuntime):
    """Implementer: write test → capture Red with the real runner → implement → commit → result.
    Reviewer: return the scripted verdict for its review number."""

    def __init__(self, reviews, skip_red=False, fix_spec=None, attempt_specs=None, tamper_red=False):
        super().__init__()
        self.attempt_specs = dict(attempt_specs or {})  # attempt_id -> spec overriding the task spec
        self.tamper_red = tamper_red
        self.assignments = []
        self.reviews = list(reviews)
        self.skip_red = skip_red
        self.fix_spec = fix_spec  # what the worker decides to change for a correction batch

    def send_prompt(self, session, text):
        mid = super().send_prompt(session, text)
        a = json.loads(text.split("\n", 1)[1])
        (self._implement if a["role"] == "implementer" else self._review)(session, a)
        return mid

    def _implement(self, session, a):
        clone, inbox = Path(a["clone_path"]), Path(a["inbox"])
        for k, v in (("user.email", "w@x"), ("user.name", "worker")):
            git(clone, "config", k, v)
        self.assignments.append(a)
        spec = self.attempt_specs.get(a["attempt_id"]) or a["task"].get("spec") or self.fix_spec
        for path, body in spec["tests"].items():
            (clone / path).parent.mkdir(parents=True, exist_ok=True)
            (clone / path).write_text(body)
        evidence = []
        if not self.skip_red:
            red = run_evidence("red", a["task_id"], a["attempt_id"], a["g1_argv"], str(clone), a["base_sha"],
                               a["scope"]["paths"], a["excludes"])
            rec = evidence_record(red)
            for name in ("stdout", "stderr"):
                (inbox / f"red.{name}").write_bytes(getattr(red, name) + (b"tampered" if self.tamper_red else b""))
            evidence.append(rec)
        for path, body in spec["impl"].items():
            (clone / path).parent.mkdir(parents=True, exist_ok=True)
            (clone / path).write_text(body)
        git(clone, "add", "-A")
        git(clone, "commit", "-qm", f"{a['task_id']}: implement")
        head = git(clone, "rev-parse", "HEAD")
        changed = git(clone, "diff", "--name-only", a["base_sha"], head).split()
        responses = {fid: {"kind": "fix_submitted", "commit": head} for fid in a.get("batch", {}).get("findings", [])}
        result = {"run_id": a["run_id"], "task_id": a["task_id"], "attempt_id": a["attempt_id"],
                  "execution_status": "succeeded", "observed": {"cwd": str(clone), "base": a["base_sha"], "head": head},
                  "changed_paths": changed, "evidence": evidence, "responses": responses,
                  "producer": {"session": session, "actual_model": "impl-model"}}
        (inbox / "result.json").write_text(json.dumps(result))

    def _review(self, session, a):
        script = self.reviews.pop(0)
        result = {"run_id": a["run_id"], "task_id": a["task_id"], "attempt_id": a["attempt_id"],
                  "execution_status": "succeeded", "observed": {"cwd": a["clone_path"], "base": a["base_sha"],
                                                                "head": a["base_sha"]},
                  "changed_paths": [], "verdict": script["verdict"], "version_key": a["version_key"],
                  "read_contract": a["contract"], "findings": script.get("findings", []),
                  "closures": [{"finding_id": f, "reason": "verified fixed"} for f in script.get("close", [])],
                  "producer": {"session": session, "actual_model": script.get("model", "gpt-r")}}
        (Path(a["inbox"]) / "result.json").write_text(json.dumps(result))


class RepoGitHub:
    """Fake GitHub for one repo: PRs by head branch, check runs per SHA from a CI script."""

    def __init__(self, ctl, ci=lambda sha, n: "success", required=("test",)):
        self.ctl, self.ci, self.required = ctl, ci, set(required)
        self.prs, self.ensure_calls, self.check_reads = {}, 0, 0

    def ensure_pr(self, target, body):
        self.ensure_calls += 1
        pr = self.prs.setdefault(target, {"number": len(self.prs) + 1, "body": body})
        pr["head"] = git(self.ctl, "rev-parse", f"refs/heads/{target}")
        pr["body"] = body
        return {"number": pr["number"], "url": f"https://gh/pull/{pr['number']}", "head": pr["head"]}

    def find_pr(self, target, marker):
        pr = self.prs.get(target)
        return {"number": pr["number"], "url": f"https://gh/pull/{pr['number']}"} if pr and marker in pr["body"] else None

    def pr_head(self, number):
        return next(p["head"] for p in self.prs.values() if p["number"] == number)

    def required_checks(self):
        return set(self.required)

    def list_checks(self, sha):
        self.check_reads += 1
        return [{"name": "test", "app": "github-actions", "head_sha": sha, "status": "completed",
                 "conclusion": self.ci(sha, self.check_reads), "started_at": "t", "id": 1}]
