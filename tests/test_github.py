"""M-GH h1–h13 (with h4a–h4e): push, pr_ensure, PR / CI observation and G3 (design §4, §5, §8;
T6.1).

Every command goes through the public CLI in-process (`loopctl.cli.main`); `loopctl.clock.now`
is the only clock and is monkeypatched. Git is real: the fixture repo, its linked feature
worktree and a bare `origin` in tmp; a shim on PATH logs every git argv before exec'ing the
real git (push counts). `gh` is the route fake tests/fakes/bin/gh (format in its docstring):
a small fake GitHub whose answers the helpers below build per test.

G1 is the real T3.1 path (evidence red / green / assess) where the test is about the order
G1 → push (h7, h10); elsewhere it is a store-API fixture of T3.1's records of a passed G1
(validation M-G1 used the same approach for attempt metadata).
"""

import copy
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_g1 import IMPL_DOUBLE, Env, policy_doc
from test_writes import CLI, FEATURE, commit_all, git

from loopctl import gates, observe, store

ROOT = Path(__file__).resolve().parents[1]
GH_FAKE = ROOT / "tests" / "fakes" / "bin" / "gh"
SCENARIOS = ROOT / "tests" / "fakes" / "scenarios" / "gh"
REPO = "yschiang/loop-engineering"
BRANCH = "feat"
WF = ".github/workflows/loopctl-ci.yml"
JOB = "unit-linux"
PR = 17
ACCEPT = "Accept: application/vnd.github+json"
MARKER = f"loopctl-op:{FEATURE}/pr_ensure"
B0_REMOTE = "b" * 40  # the PR's base tip as GitHub reports it (only compared, never fetched)
B1_REMOTE = "c" * 40


# --- the fake GitHub --------------------------------------------------------------------------


def api(path: str) -> list[str]:
    return ["api", "--include", "-H", ACCEPT, path]


def page(body: Any, nxt: str | None = None, status: int = 200) -> dict:
    out: dict[str, Any] = {"status": status, "body": body}
    if nxt:
        out["headers"] = {"Link": f'<{nxt}>; rel="next", <{nxt}&last=1>; rel="last"'}
    return out


class GitHub:
    """Routes of the fake `gh` scenario; re-setting a route id keeps its call count."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.routes: dict[str, dict] = {}
        self.flush()

    def set(self, rid: str, match: list[str], *responses: dict, **extra: Any) -> None:
        self.routes[rid] = {"id": rid, "match": match, "responses": [copy.deepcopy(r) for r in responses], **extra}
        self.flush()

    def flush(self) -> None:
        self.path.write_text(json.dumps({"routes": list(self.routes.values())}))


def pr_json(env: "GhEnv", *, number: int = PR, head_sha: str | None = None, head_ref: str = BRANCH,
            head_repo: str | None = None, base_ref: str = "main", base_repo: str | None = None,
            base_sha: str = B0_REMOTE, mergeable: bool | None = True, marker: bool = True,
            state: str = "open") -> dict:
    repo = env.gh_repo
    body = f"loopctl feature {FEATURE}\n\n<!-- {MARKER} -->\n" if marker else "opened by hand"
    return {
        "number": number, "node_id": f"PR_kw{number}", "html_url": f"https://github.com/{repo}/pull/{number}",
        "state": state, "body": body, "mergeable": mergeable, "mergeable_state": "clean" if mergeable else "unknown",
        "head": {"ref": head_ref, "sha": head_sha or env.h, "repo": {"full_name": head_repo or repo}},
        "base": {"ref": base_ref, "sha": base_sha, "repo": {"full_name": base_repo or repo}},
    }


def job(name: str = JOB, conclusion: str | None = "success", status: str = "completed", attempt: int = 1,
        url: bool = True) -> dict:
    return {"id": 9000 + attempt, "name": name, "status": status,
            "conclusion": conclusion if status == "completed" else None, "run_attempt": attempt,
            "html_url": f"https://github.com/{REPO}/actions/runs/1/job/{9000 + attempt}" if url else None}


def run(env: "GhEnv", run_id: int = 101, number: int | None = 41, attempt: int | None = 1, *,
        event: str = "pull_request", prs: tuple[int, ...] = (PR,), path: str = WF, head: str | None = None,
        status: str = "completed", jobs: list[dict] | None = None, tested: dict | None = None,
        **run_extra: Any) -> dict:
    """A workflow run of H and what GitHub holds for its latest attempt: jobs, and the
    tested-SHA artifact contents by name (default: one correct artifact per success job)."""
    jobs = [job(attempt=attempt or 1)] if jobs is None else jobs
    if tested is None:
        tested = {
            f"tested-sha-{j['name']}-{attempt}": {"run_id": str(run_id), "run_attempt": str(attempt), "job": j["name"],
                                                  "check_name": j["name"], "tested_sha": head or env.h}
            for j in jobs if j["conclusion"] == "success"
        }
    return {"id": run_id, "run_number": number, "run_attempt": attempt, "event": event, "head_sha": head or env.h,
            "path": path, "pull_requests": [{"number": n} for n in prs], "status": status,
            "conclusion": None if status != "completed" else "success",
            "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}", "jobs": jobs, "tested": tested,
            **run_extra}


# --- environment ------------------------------------------------------------------------------


class GhEnv(Env):
    """test_g1's Env (repo, linked worktree, approved plan, registered policy) plus: the CI
    workflow the policy binds, a bare `origin`, the plan's push remote, fake gh, a git shim."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        super().__init__(tmp_path, monkeypatch, capsys)
        self.write(WF, (ROOT / WF).read_text(), self.repo)
        self.b0 = commit_all(self.repo, "ci workflow")
        git(self.wt, "merge", "-q", "--ff-only", "main")
        self.real_git = str(shutil.which("git"))
        self.remote = tmp_path / "remote.git"
        subprocess.run([self.real_git, "init", "-q", "--bare", str(self.remote)], check=True)
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "main")
        bindir = tmp_path / "gh-bin"
        bindir.mkdir()
        (bindir / "gh").symlink_to(GH_FAKE)
        self.gitlog = tmp_path / "git-argv.log"
        shim = bindir / "git"
        shim.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{self.gitlog}'\nexec '{self.real_git}' \"$@\"\n")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        self.log, self.scenario = tmp_path / "gh-log.jsonl", tmp_path / "gh-scenario.json"
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_SCENARIO", str(self.scenario))
        self.gh = GitHub(self.scenario)
        self.gh_repo = REPO
        self.h = ""
        self.pol_path = tmp_path / "workflow.yaml"

    # --- setup ----------------------------------------------------------------------------

    def start(self, tasks: tuple[str, ...] = ("T1",), *, repo: str = REPO, policy: Any = None,
              approve_policy: bool = True, remote: str | None = "origin", **limits: float) -> None:
        self.gh_repo = repo
        doc = policy_doc(None, **limits)
        if policy is not None:
            policy(doc)
        self.pol_path.write_text(yaml.safe_dump(doc))
        spec, plan = self.tmp / "spec.md", self.tmp / "plan.md"
        spec.write_text("# spec\n")
        workspace = {"source": str(self.repo), "worktree": str(self.wt), "branch": BRANCH, "base": "main"}
        if remote is not None:
            workspace["remote"] = remote
        from test_g1 import TASKS

        block = yaml.safe_dump({"workspace": workspace, "tasks": [{"id": t, **TASKS[t]} for t in tasks]},
                               sort_keys=False)
        plan.write_text(f"# plan\n\n```loopctl-plan\n{block}```\n")
        code, out = self.cli("init", "--repo", repo, "--repo-id", "R_1", "--feature", FEATURE, "--issue", "7")
        assert code == 0, out
        code, out = self.cli("claim", "--feature", FEATURE, "--actor", "orchestrate")
        assert code == 0, out
        self.token = out["result"]["token"]
        for argv in (
            ["register", "policy", "--locator", str(self.pol_path), "--version", "p1"],
            ["register", "binding", "--role", "spec", "--locator", str(spec), "--version", "s1"],
            ["register", "plan", "--locator", str(plan), "--version", "v1", "--producer", "implementer",
             "--calibrated-from", str(spec)],
            ["decide", "approve_plan", "--id=approve-1", "--actor=human:alice", f"--target={plan}",
             "--version=v1", "--reason=approved with the user"],
        ):
            code, out = self.cli(*argv, "--feature", FEATURE, f"--token={self.token}")
            assert code == 0, out
        if approve_policy:
            self.approve_policy("pc-1")
        worktree = {"kind": "worktree_create", "status": "succeeded", "facts": {"pane": "w1:p1"}}
        self.mutate("implementing", lambda s: {**s, "phase": "implementing", "writes": {"worktree": worktree}})

    def policy_digest(self) -> str:
        return store.digest(self.pol_path.read_bytes())

    def approve_policy(self, did: str) -> None:
        code, out = self.decide("policy_change", id=did, target=str(self.pol_path), version=self.policy_digest(),
                                reason="required CI set approved (D53)")
        assert code == 0, out

    def reregister_policy(self, change: Any) -> None:
        doc = yaml.safe_load(self.pol_path.read_text())
        change(doc)
        self.pol_path.write_text(yaml.safe_dump(doc))
        code, out = self.cli("register", "policy", "--feature", FEATURE, f"--token={self.token}", "--locator",
                             str(self.pol_path), "--version", "p2")
        assert code == 0, out

    def g1_fixture(self, status: str = "passed") -> str:
        """T3.1's records of an assessed G1 at a new feature head H (store API)."""
        self.dispatch("T1-a1")
        self.write("src/calc.py", IMPL_DOUBLE)
        self.h = self.commit("T1-a1: double")
        self.complete("T1-a1")
        at = self.clock().isoformat()
        green = {"id": "green-1", "n": 1, "kind": "green", "status": "passed", "head": self.h,
                 "checkout_head": self.h, "results_seen": 1, "started_at": at, "ended_at": at}
        reasons = [] if status == "passed" else [f"fixture_{status}"]
        g1 = {"status": status, "reasons": reasons, "head": self.h, "green": "green-1", "green_seen": "green-1",
              "results_seen": 1, "units": {}, "integration": {}, "applicability": [], "unattributed": [],
              "heads": [self.h], "assessed_at": at}
        self.mutate("g1", lambda s: {**s, "evidence": {**s.get("evidence", {}), "green-1": green},
                                     "gates": {**s.get("gates", {}), "g1": g1}})
        return self.h

    def real_g1(self) -> str:
        """The T3.1 public path: Red captured by the worker, Green at H, assess → passed."""
        _, self.h = self.task_done()
        assert self.next() == {"action": "evidence_green", "head": self.h}
        code, out = self.green()
        assert code == 0, out
        assert self.next() == {"action": "assess"}
        code, out = self.assess()
        assert code == 0 and self.g1()["status"] == "passed", out
        return self.h

    # --- CLI --------------------------------------------------------------------------------

    def write_op(self, kind: str, op_id: str) -> tuple[int, dict]:
        return self.cli("write", kind, "--feature", FEATURE, f"--token={self.token}", "--id", op_id)

    def observe(self, source: str, *extra: str) -> tuple[int, dict]:
        return self.cli("observe", source, "--feature", FEATURE, f"--token={self.token}", *extra)

    def decide(self, kind: str, **fields: str) -> tuple[int, dict]:
        argv = ["decide", kind, "--feature", FEATURE, f"--token={self.token}"]
        values = {"actor": "human:alice", "version": "v1", "reason": "checked by hand", **fields}
        argv += [f"--{k.replace('_', '-')}={v}" for k, v in values.items()]
        return self.cli(*argv)

    def safety(self) -> dict | None:
        return self.cli("safety", "--feature", FEATURE)[1]["safety"]

    def g3(self) -> dict:
        return dict(self.state()["gates"]["g3"])

    def blockers(self) -> list[str]:
        return list(self.state()["blockers"])

    # --- fake calls ---------------------------------------------------------------------------

    def calls(self, route: str | None = None) -> list[dict]:
        if not self.log.exists():
            return []
        found = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in found if route is None or c.get("route") == route]

    def unexpected(self) -> list[dict]:
        return [c for c in self.calls() if c.get("unexpected")]

    def pushes(self) -> list[str]:
        if not self.gitlog.exists():
            return []
        return [line for line in self.gitlog.read_text().splitlines() if " push --porcelain " in line]

    def remote_ref(self, ref: str = f"refs/heads/{BRANCH}") -> str | None:
        done = subprocess.run([self.real_git, "--git-dir", str(self.remote), "rev-parse", "--verify", "--quiet", ref],
                              capture_output=True, text=True, check=False)
        return done.stdout.strip() or None

    def remote_git(self, *args: str, git_dir: Path | None = None) -> None:
        subprocess.run([self.real_git, "--git-dir", str(git_dir or self.remote), *args], check=True,
                       capture_output=True)

    # --- GitHub state ---------------------------------------------------------------------------

    def pr_routes(self, query: list[dict] | None = None, create: dict | None = None,
                  get: dict | None = None) -> None:
        owner = self.gh_repo.split("/")[0]
        self.gh.set("pr_query", api(f"repos/{self.gh_repo}/pulls?state=open&head={owner}:{BRANCH}&per_page=100"),
                    page(query or []))
        self.gh.set("pr_create", ["api", "--include", "--method", "POST", f"repos/{self.gh_repo}/pulls", "**"],
                    create or page(pr_json(self), status=201))
        self.gh.set("pr_get", api(f"repos/{self.gh_repo}/pulls/{PR}"), page(get or pr_json(self)))

    def ci(self, runs: list[dict], *, rules: int | list[str] = 403, statuses: list[dict] | None = None,
           check_runs: list[dict] | None = None, pages: int = 1, head: str | None = None) -> None:
        """Everything `observe ci` may read for H: rules, runs (in `pages` pages), jobs of each
        run's latest attempt, artifacts and their download, check-runs, commit statuses."""
        repo, h = self.gh_repo, head or self.h
        if isinstance(rules, int):
            self.gh.set("rules", api(f"repos/{repo}/rules/branches/main?per_page=100"),
                        page({"message": "Resource not accessible by integration"}, status=rules))
        else:
            checks = [{"context": c, "integration_id": 15368} for c in rules]
            body = [{"type": "required_status_checks", "ruleset_id": 1,
                     "parameters": {"strict_required_status_checks_policy": False, "required_status_checks": checks}}]
            self.gh.set("rules", api(f"repos/{repo}/rules/branches/main?per_page=100"), page(body))
        visible = [{k: v for k, v in r.items() if k not in ("jobs", "tested")} for r in runs]
        base = f"repos/{repo}/actions/runs?head_sha={h}&per_page=100"
        chunks = [visible[i::pages] for i in range(pages)] if pages > 1 else [visible]
        for n, chunk in enumerate(chunks, start=1):
            path = base if n == 1 else f"{base}&page={n}"
            nxt = f"{base}&page={n + 1}" if n < len(chunks) else None
            self.gh.set(f"runs_p{n}", api(path), page({"total_count": len(visible), "workflow_runs": chunk}, nxt))
        for r in runs:
            if r["run_attempt"] is None:
                continue
            self.gh.set(f"jobs_{r['id']}_{r['run_attempt']}",
                        api(f"repos/{repo}/actions/runs/{r['id']}/attempts/{r['run_attempt']}/jobs?per_page=100"),
                        page({"total_count": len(r["jobs"]), "jobs": r["jobs"]}))
            artifacts = [{"id": 700 + i, "name": name, "expired": False} for i, name in enumerate(r["tested"])]
            self.gh.set(f"artifacts_{r['id']}", api(f"repos/{repo}/actions/runs/{r['id']}/artifacts?per_page=100"),
                        page({"total_count": len(artifacts), "artifacts": artifacts}))
            for name, content in r["tested"].items():
                self.gh.set(f"download_{r['id']}_{name}",
                            ["run", "download", str(r["id"]), "--repo", repo, "--name", name, "--dir", "*"],
                            {"stdout": "", "effects": [{"write": "{dir}/tested-sha.json", "json": content}]},
                            capture={"dir": r"--dir (\S+)"})
        self.gh.set("check_runs", api(f"repos/{repo}/commits/{h}/check-runs?per_page=100"),
                    page({"total_count": len(check_runs or []), "check_runs": check_runs or []}))
        self.gh.set("statuses", api(f"repos/{repo}/commits/{h}/statuses?per_page=100"), page(statuses or []))

    # --- the path to G3 -------------------------------------------------------------------------

    def push(self) -> None:
        assert self.next() == {"action": "write", "op": "push", "id": f"push.{self.h}"}
        code, out = self.write_op("push", f"push.{self.h}")
        assert code == 0, out
        assert out["result"]["op"]["status"] == "succeeded", out

    def open_pr(self, *, mergeable: bool | None = True) -> None:
        """push → pr_ensure (none open → created) → observe pr."""
        self.push()
        self.pr_routes(get=pr_json(self, mergeable=mergeable))
        assert self.next() == {"action": "write", "op": "pr_ensure", "id": "pr_ensure"}
        code, out = self.write_op("pr_ensure", "pr_ensure")
        assert code == 0, out
        assert self.next()["action"] == "observe"
        code, out = self.observe("pr")
        assert code == 0, out

    def to_g3(self, runs: list[dict], **ci: Any) -> dict:
        self.ci(runs, **ci)
        assert self.next() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": self.ci_key}
        code, out = self.observe("ci")
        assert code == 0, out
        return self.g3()

    @property
    def ci_key(self) -> str:
        return f"ci:{self.gh_repo}:{self.h}"


@pytest.fixture
def env(tmp_path, monkeypatch, capsys) -> GhEnv:
    return GhEnv(tmp_path, monkeypatch, capsys)


def started(env: GhEnv, **kw: Any) -> GhEnv:
    env.start(**kw)
    env.g1_fixture()
    return env


def check(g3: dict, name: str = JOB) -> dict:
    return dict(g3["checks"][name])


# --- h1: G3 policy source (AC-A01, D49) -------------------------------------------------------


H1_UNKNOWN = {
    "no_policy": "policy_not_registered",
    "not_approved": "policy_not_approved",
    "digest_mismatch": "policy_digest_mismatch",
    "other_repo": "rules_unreadable_other_repo",
    "workflow_digest": "workflow_digest_mismatch",
}


@pytest.mark.parametrize("case", ["rules_readable", "approved_policy", *H1_UNKNOWN])
def test_h1_policy_source_matrix(env, case):
    policy = (lambda d: d["g3"].update(workflow_blob_sha="0" * 40)) if case == "workflow_digest" else None
    started(env, repo="someone/else" if case == "other_repo" else REPO, policy=policy,
            approve_policy=case != "not_approved")
    env.open_pr()
    if case == "no_policy":
        env.mutate("unregister", lambda s: {**s, "versions": {k: v for k, v in s["versions"].items() if k != "policy"}})
    if case == "digest_mismatch":
        env.reregister_policy(lambda d: d["limits"].update(poll_github_s=61))  # pc-1 approved the old digest
    env.ci([run(env)], rules=[JOB] if case == "rules_readable" else 403)
    code, out = env.observe("ci")
    assert code == 0, out
    g3 = env.g3()
    source = g3["source"]
    if case == "rules_readable":
        assert (g3["status"], source["kind"], source["github_rules_verified"]) == ("passed", "rules", True), g3
        assert source["required"] == [JOB]
    elif case == "approved_policy":
        assert (g3["status"], source["kind"], source["github_rules_verified"]) == ("passed", "approved_policy", False)
        assert (source["policy_change"], source["policy_digest"]) == ("pc-1", env.policy_digest())
        assert source["required"] == [JOB]
    else:
        reason = H1_UNKNOWN[case]
        assert g3["status"] == "unknown" and reason in g3["reasons"], g3
        assert f"g3_policy:{reason}" in env.blockers()
        nxt = env.next()
        assert nxt["action"] == "human" and f"g3_policy:{reason}" in nxt["blockers"]
        assert nxt["decision_kinds"] == ["policy_change"]
        assert env.state()["batches"] == {}  # unknown + Blocked, no correction round
    assert env.unexpected() == []


def test_h1_a_policy_change_after_the_block_lets_the_same_ci_pass(env):
    started(env, approve_policy=False)
    env.open_pr()
    env.ci([run(env)])
    assert env.observe("ci")[0] == 0
    assert env.g3()["status"] == "unknown" and "g3_policy:policy_not_approved" in env.blockers()
    assert env.safety() is None
    env.approve_policy("pc-late")
    assert env.safety() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert (g3["status"], g3["source"]["policy_change"]) == ("passed", "pc-late")
    assert not [b for b in env.blockers() if b.startswith("g3_policy:")]
    assert env.next() == {"action": "human", "blockers": ["g3_passed"], "decision_kinds": []}


# --- h2: required check states -------------------------------------------------------------------


H2 = {
    "missing": ([], "pending", f"missing:{JOB}"),
    "pending": ([job(status="in_progress")], "pending", f"pending:{JOB}:101"),
    "cancelled": ([job(conclusion="cancelled")], "failed", f"cancelled:{JOB}:101"),
    "timed_out": ([job(conclusion="timed_out")], "failed", f"timed_out:{JOB}:101"),
    "failure": ([job(conclusion="failure")], "failed", f"failure:{JOB}:101"),
    "unknown": ([job(conclusion="mystery")], "unknown", f"conclusion_unknown:{JOB}:101"),
    "stale": ([job(conclusion="stale")], "failed", f"stale:{JOB}:101"),
    "skipped": ([job(conclusion="skipped")], "failed", f"skipped:{JOB}:101"),
    "neutral": ([job(conclusion="neutral")], "failed", f"neutral:{JOB}:101"),
    # a Linux-only case that skips on Linux fails the session (M-TPOL), so the job fails
    "test_policy_failure": ([job(conclusion="failure")], "failed", f"failure:{JOB}:101"),
}


@pytest.mark.parametrize("case", [*H2, "empty_required_set"])
def test_h2_required_check_states_never_pass(env, case):
    empty = case == "empty_required_set"
    started(env, policy=(lambda d: d["g3"].update(required_checks=[])) if empty else None)
    env.open_pr()
    if empty:
        env.ci([run(env)])
        status, reason = "unknown", "required_set_empty"
    else:
        jobs, status, reason = H2[case]
        env.ci([run(env, jobs=jobs)] if case != "missing" else [])
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert g3["status"] == status and reason in g3["reasons"], g3
    if empty:
        assert "g3_policy:required_set_empty" in env.blockers()
    assert env.next()["action"] != "done"


# --- h3: the generic exception mechanism ------------------------------------------------------


@pytest.mark.parametrize("case", ["skipped_with_decision", "failure_excepted", "no_decision", "unknown_decision",
                                  "no_check"])
def test_h3_exceptions_need_a_decision_and_only_cover_skipped_or_neutral(env, case):
    entry = {"check": JOB, "conclusion": "failure" if case == "failure_excepted" else "skipped", "decision": "pc-1"}
    if case == "no_decision":
        entry.pop("decision")
    if case == "unknown_decision":
        entry["decision"] = "pc-nope"
    if case == "no_check":
        entry.pop("check")
    started(env, policy=lambda d: d["g3"].update(exceptions=[entry]))
    env.open_pr()
    conclusion = "failure" if case == "failure_excepted" else "skipped"
    env.ci([run(env, jobs=[job(conclusion=conclusion)])])
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    if case == "skipped_with_decision":
        assert g3["status"] == "passed", g3
        assert check(g3)["runs"][0]["via"] == {"exception": "pc-1", "conclusion": "skipped"}
    else:
        name = None if case == "no_check" else JOB
        assert g3["status"] == "unknown", g3
        assert f"policy_invalid:exception:{name}" in g3["reasons"]
        assert f"g3_policy:policy_invalid:exception:{name}" in env.blockers()


# --- h4, h4a–h4e: run / attempt selection -----------------------------------------------------


def h4_state(env: GhEnv, case: str) -> tuple[list[dict], dict]:
    extra: dict[str, Any] = {}
    if case == "old_attempt_success_new_pending":
        runs = [run(env, attempt=2, status="in_progress", jobs=[job(status="in_progress", attempt=2)])]
        env.gh.set("jobs_old", api(f"repos/{REPO}/actions/runs/101/attempts/1/jobs?per_page=100"),
                   page({"total_count": 1, "jobs": [job()]}))
    elif case == "new_attempt_queued_without_start":
        runs = [run(env, attempt=2, status="queued", jobs=[], run_started_at=None)]
    elif case == "same_name_other_app":
        runs = []
        extra["check_runs"] = [{"name": JOB, "status": "completed", "conclusion": "success", "head_sha": env.h,
                                "app": {"slug": "other-ci"}, "html_url": "https://ci.example/1"}]
    elif case == "same_app_other_workflow":
        runs = [run(env, path=".github/workflows/other.yml")]
    elif case == "no_run_number":
        runs = [run(env, number=None)]
    elif case == "no_run_attempt":
        runs = [run(env, attempt=None, jobs=[], tested={})]
    elif case == "duplicate_run_number":
        runs = [run(env), run(env, run_id=102, number=41)]
    elif case == "commit_status_only":
        runs = []
        extra["statuses"] = [{"context": JOB, "state": "success", "creator": {"login": "someone"}}]
    else:  # three_pages_latest_on_page_3
        runs = [run(env, run_id=90 + i, number=30 + i, path=f".github/workflows/other{i}.yml") for i in range(2)]
        runs.append(run(env))
        extra["pages"] = 3
    return runs, extra


H4 = {
    "old_attempt_success_new_pending": ("pending", f"pending:{JOB}:101"),
    "new_attempt_queued_without_start": ("pending", f"missing:{JOB}:run:101"),
    "same_name_other_app": ("pending", f"missing:{JOB}"),
    "same_app_other_workflow": ("pending", f"missing:{JOB}"),
    "no_run_number": ("unknown", "run_identity_missing:101"),
    "no_run_attempt": ("unknown", "run_identity_missing:101"),
    "duplicate_run_number": ("unknown", "duplicate_run_number:41"),
    "commit_status_only": ("unknown", f"commit_status_only:{JOB}"),
    "three_pages_latest_on_page_3": ("passed", None),
}


@pytest.mark.parametrize("case", H4)
def test_h4_latest_attempt_per_run_identity_and_all_pages(env, case):
    started(env)
    env.open_pr()
    runs, extra = h4_state(env, case)
    g3 = env.to_g3(runs, **extra)
    status, reason = H4[case]
    assert g3["status"] == status, g3
    if reason:
        assert reason in g3["reasons"], g3
    if case == "old_attempt_success_new_pending":
        assert env.calls("jobs_old") == []  # the replaced attempt is not read, never falls back
    if case == "same_name_other_app":
        assert {"name": JOB, "app": "other-ci"} in g3["ignored"]
    if case == "same_app_other_workflow":
        assert {"run_id": 101, "path": ".github/workflows/other.yml"} in g3["ignored"]
    if case == "three_pages_latest_on_page_3":
        assert [len(env.calls(f"runs_p{n}")) for n in (1, 2, 3)] == [1, 1, 1]
        assert check(g3)["runs"][0]["run_id"] == 101
    assert env.unexpected() == []


def test_h4a_a_push_event_run_of_h_is_unexpected_context_not_a_pass(env):
    started(env)
    env.open_pr()
    g3 = env.to_g3([run(env, 101, 41, jobs=[job(conclusion="failure")]),
                    run(env, 102, 42, event="push", prs=())])
    assert g3["status"] == "unknown" and "unexpected_event_context:102" in g3["reasons"], g3


@pytest.mark.parametrize("rerun", ["pending", "failure", "success"])
def test_h4b_every_pr_run_of_h_counts_with_its_latest_attempt(env, rerun):
    started(env)
    env.open_pr()
    if rerun == "pending":
        first = run(env, 101, 41, 2, status="in_progress", jobs=[job(status="in_progress", attempt=2)])
    else:
        first = run(env, 101, 41, 2, jobs=[job(conclusion=rerun, attempt=2)])
    g3 = env.to_g3([first, run(env, 102, 42)])
    assert g3["status"] == {"pending": "pending", "failure": "failed", "success": "passed"}[rerun], g3
    runs = check(g3)["runs"]
    assert [(r["run_number"], r["run_attempt"]) for r in runs] == [(41, 2), (42, 1)]


def test_h4c_a_later_run_success_does_not_hide_an_earlier_run_failure(env):
    started(env)
    env.open_pr()
    g3 = env.to_g3([run(env, 101, 41, jobs=[job(conclusion="failure")]), run(env, 102, 42)])
    assert g3["status"] == "failed" and f"failure:{JOB}:101" in g3["reasons"], g3


def test_h4d_an_older_attempt_and_an_old_head_run_are_not_required(env):
    started(env)
    env.open_pr()
    old_head = run(env, 90, 40, head="0" * 40, jobs=[job(conclusion="failure")])
    g3 = env.to_g3([run(env, 101, 41, 2, jobs=[job(attempt=2)]), old_head])
    assert g3["status"] == "passed", g3
    assert [(r["run_id"], r["run_attempt"]) for r in check(g3)["runs"]] == [(101, 2)]


def test_h4e_a_run_of_another_pr_is_unexpected_context(env):
    started(env)
    env.open_pr()
    g3 = env.to_g3([run(env, prs=(99,))])
    assert g3["status"] == "unknown" and "unexpected_event_context:101" in g3["reasons"], g3


def test_h4_a_counted_check_keeps_its_identity_and_readable_url(env):
    started(env)
    env.open_pr()
    g3 = env.to_g3([run(env)])
    record = check(g3)["runs"][0]
    assert {k: record[k] for k in ("name", "app", "workflow", "run_id", "run_attempt", "run_number", "event",
                                   "head_sha", "status", "conclusion", "tested_sha")} == {
        "name": JOB, "app": "github-actions", "workflow": WF, "run_id": 101, "run_attempt": 1, "run_number": 41,
        "event": "pull_request", "head_sha": env.h, "status": "completed", "conclusion": "success",
        "tested_sha": env.h}
    assert record["url"].startswith("https://github.com/")
    env.ci([run(env, jobs=[job(url=False)])])
    env.clock.advance(seconds=60)
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert g3["status"] == "unknown" and f"check_url_missing:{JOB}:101" in g3["reasons"]


# --- h5: an integration SHA as the tested source ----------------------------------------------


def test_h5_a_check_that_tested_another_sha_is_unsupported_integration_source(env):
    started(env)
    env.open_pr()
    merge_sha = "d" * 40
    tested = {f"tested-sha-{JOB}-1": {"run_id": "101", "run_attempt": "1", "job": JOB, "check_name": JOB,
                                      "tested_sha": merge_sha}}
    g3 = env.to_g3([run(env, tested=tested)])
    assert g3["status"] == "unknown" and f"unsupported_integration_source:{JOB}:101" in g3["reasons"], g3
    assert env.next()["action"] == "human"


# --- h6: observation order ---------------------------------------------------------------------


def test_h6_older_pr_reads_arriving_late_never_restore_an_older_head(env, monkeypatch):
    started(env)
    env.push()
    env.pr_routes()
    assert env.write_op("pr_ensure", "pr_ensure")[0] == 0
    h1, h2 = "1" * 40, "2" * 40
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, head_sha=h1)), page(pr_json(env, head_sha=h2)))
    original = observe.FETCHERS["pr"]
    inner: dict = {}

    def late(*args, **kwargs):
        older = original(*args, **kwargs)  # sees h1 …
        monkeypatch.setitem(observe.FETCHERS, "pr", original)
        inner["code"], inner["out"] = env.observe("pr")  # … a newer read (h2) commits first
        return older

    monkeypatch.setitem(observe.FETCHERS, "pr", late)
    code, out = env.observe("pr")
    assert (code, inner["code"]) == (0, 0), (out, inner)
    assert out["result"]["outcome"] == "superseded" and out["result"]["seq"] < inner["out"]["result"]["seq"]
    st = env.state()
    assert st["versions"]["facts"]["head"] == h2
    assert st["observations"]["current"][f"pr:{PR}"]["pr"]["fact"]["head"]["sha"] == h2
    old = [e for e in st["observations"]["history"] if e["seq"] == out["result"]["seq"]]
    assert len(old) == 1 and old[0]["superseded"] is True

    # across purposes: a `pass` read (older seq, h1) arriving after a `pr` read (newer seq, h3)
    h3 = "3" * 40
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, head_sha=h1)))

    def late_pass(*args, **kwargs):
        older = original(*args, **kwargs)
        monkeypatch.setitem(observe.FETCHERS, "pr", original)
        env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, head_sha=h3)))
        inner["code"], inner["out"] = env.observe("pr")
        return older

    monkeypatch.setitem(observe.FETCHERS, "pr", late_pass)
    code, out = env.observe("pr", "--purpose", "pass")
    assert (code, inner["code"]) == (0, 0)
    assert out["result"]["seq"] < inner["out"]["result"]["seq"]
    st = env.state()
    assert st["versions"]["facts"]["head"] == h3  # the later-arriving older `pass` read does not win
    assert st["observations"]["current"][f"pr:{PR}"]["pass"]["fact"]["head"]["sha"] == h1


# --- h7: version changes while H stays ----------------------------------------------------------


def g3_passed_real(env: GhEnv) -> None:
    env.start()
    env.real_g1()
    env.open_pr()
    env.clock.advance(seconds=1)
    assert env.to_g3([run(env)])["status"] == "passed"
    assert env.next() == {"action": "human", "blockers": ["g3_passed"], "decision_kinds": []}


def reobserve(env: GhEnv) -> dict:
    """G3 column: re-observed (PR, then CI) before anything else."""
    assert env.next()["action"] == "observe" and env.next()["source"] == "pr"
    assert env.observe("pr")[0] == 0
    assert env.next() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    assert env.observe("ci")[0] == 0
    return env.g3()


def reassess(env: GhEnv) -> None:
    """G1 column: recomputed at the unchanged H from the stored evidence (no new Red)."""
    before = env.g1()["assessed_at"]
    assert env.next() == {"action": "assess"}
    env.clock.advance(seconds=5)
    assert env.assess()[0] == 0
    g1 = env.g1()
    assert (g1["status"], g1["head"]) == ("passed", env.h) and g1["assessed_at"] != before


def test_h7_base_moves_without_trigger_green_reruns_at_h_and_g3_reuses_h(env):
    g3_passed_real(env)
    approval, pushes = env.state()["approval"], len(env.pushes())
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, base_sha=B1_REMOTE)))
    env.clock.advance(seconds=60)
    assert env.observe("pr")[0] == 0
    assert env.state()["integration_required"] == {}
    assert env.g3()["status"] == "pending" and "ci_observation_stale" in env.g3()["reasons"]
    assert env.next() == {"action": "evidence_green", "head": env.h}  # at H itself, not a temporary merge
    code, out = env.green()
    assert code == 0, out
    assert (out["result"]["evidence"]["head"], out["result"]["evidence"]["checkout_head"]) == (env.h, env.h)
    assert env.next() == {"action": "assess"}
    env.clock.advance(seconds=5)
    assert env.assess()[0] == 0
    assert env.next() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    assert env.observe("ci")[0] == 0
    binding = env.state()["g1_binding"]
    assert (binding["head"], binding["base"], binding["green"]) == (env.h, B1_REMOTE, out["result"]["evidence"]["id"])
    assert binding["history"][-1]["reason"] == "base_rebound"
    g3 = env.g3()
    assert g3["status"] == "passed"
    assert {"reason": "head_only_h_unchanged", "head": env.h, "base_from": B0_REMOTE,
            "base_to": B1_REMOTE} in g3["applicability"]
    assert env.state()["approval"] == approval  # no new approval needed
    assert len(env.pushes()) == pushes  # H did not change: nothing new to push


@pytest.mark.parametrize("role", ["spec", "ac", "design", "skill", "plan"])
def test_h7_a_contract_binding_change_waits_for_approval_then_reassesses_and_reobserves(env, role):
    g3_passed_real(env)
    calls, pushes = len(env.calls()), len(env.pushes())
    new = env.tmp / f"{role}-v2.md"
    new.write_text(f"# {role} v2\n")
    if role == "plan":
        text = (env.tmp / "plan.md").read_text().replace("# plan", "# plan v2")
        (env.tmp / "plan.md").write_text(text)
        argv = ["register", "plan", "--locator", str(env.tmp / "plan.md"), "--version", "v2", "--producer",
                "implementer", "--calibrated-from", str(env.tmp / "spec.md")]
    else:
        argv = ["register", "binding", "--role", role, "--locator", str(new), "--version", "x2"]
    code, out = env.cli(*argv, "--feature", FEATURE, f"--token={env.token}")
    assert code == 0 and out["result"]["approval_invalidated"] is True, out
    assert env.next() == {"action": "human", "blockers": ["plan_not_approved"], "decision_kinds": ["approve_plan"]}
    assert (len(env.calls()), len(env.pushes())) == (calls, pushes)  # 0 dispatch, 0 push, 0 GitHub call
    target = str(env.tmp / "plan.md")
    code, out = env.cli("decide", "approve_plan", "--feature", FEATURE, f"--token={env.token}", "--id=approve-2",
                        "--actor=human:alice", f"--target={target}", f"--version={'v2' if role == 'plan' else 'v1'}",
                        "--reason=re-approved")
    assert code == 0, out
    reassess(env)
    g3 = reobserve(env)
    assert g3["status"] == "passed" and g3["contract"]["approval"] == "approve-2"


def test_h7_a_policy_change_needs_its_policy_change_before_g3_can_pass_again(env):
    g3_passed_real(env)
    env.reregister_policy(lambda d: d["limits"].update(poll_github_s=61))
    assert env.state()["approval"]["decision"] == "approve-1"  # policy is not an approval binding
    reassess(env)
    g3 = reobserve(env)
    assert g3["status"] == "unknown" and "policy_digest_mismatch" in g3["reasons"], g3
    nxt = env.next()
    assert nxt["action"] == "human" and nxt["decision_kinds"] == ["policy_change"]
    env.approve_policy("pc-2")
    assert env.safety() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert (g3["status"], g3["source"]["policy_change"]) == ("passed", "pc-2")


def test_h7_on_the_rules_path_a_policy_change_alone_never_turns_g3_passed(env):
    started(env, policy=lambda d: d["g3"].update(workflow_blob_sha="0" * 40), approve_policy=False)
    env.open_pr()
    env.ci([run(env)], rules=[JOB])
    assert env.observe("ci")[0] == 0
    assert (env.g3()["status"], env.g3()["reasons"]) == ("unknown", ["workflow_digest_mismatch"])
    real_blob = policy_doc(None)["g3"]["workflow_blob_sha"]
    env.reregister_policy(lambda d: d["g3"].update(workflow_blob_sha=real_blob))
    for _ in range(2):  # observing again does not make the new policy count
        env.clock.advance(seconds=60)
        assert env.observe("ci")[0] == 0
        g3 = env.g3()
        assert (g3["status"], g3["reasons"]) == ("unknown", ["policy_change_required"]), g3
    env.approve_policy("pc-2")
    assert env.safety() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert (g3["status"], g3["source"]["kind"], g3["source"]["policy_change"]) == ("passed", "rules", "pc-2")


def test_h7_a_new_controller_version_recomputes_without_an_approval(env, monkeypatch):
    g3_passed_real(env)
    decided = set(env.state()["decisions"])
    monkeypatch.setattr(gates, "controller_version", lambda: "9.9.9")
    reassess(env)
    g3 = reobserve(env)
    assert g3["status"] == "passed" and g3["contract"]["controller"] == "9.9.9"
    assert set(env.state()["decisions"]) == decided


def test_h7_a_pr_retargeted_to_another_base_branch_blocks_without_rebinding(env):
    g3_passed_real(env)
    recorded = dict(env.state()["pr"])
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, base_ref="release")))
    env.clock.advance(seconds=60)
    assert env.observe("pr")[0] == 0
    assert "pr_identity_changed:base_branch" in env.blockers()
    assert env.state()["pr"] == recorded
    nxt = env.next()
    assert nxt["action"] == "human" and "pr_identity_changed:base_branch" in nxt["blockers"]


# --- h8, h9: read failures and pending polls -----------------------------------------------------


def test_h8_ci_read_failures_block_after_three_and_survive_seq_session_restart(env):
    started(env)
    env.open_pr()
    env.ci([run(env)])
    env.gh.set("runs_p1", api(f"repos/{REPO}/actions/runs?head_sha={env.h}&per_page=100"),
               page({"message": "boom"}, status=502))

    def fail_three(first: int) -> None:
        for n in range(first, first + 3):
            code, out = env.observe("ci")
            assert env.state()["read_budget"][env.ci_key]["consecutive_failures"] == n
            assert (code, out["result"]["error"]) == ((1, "read_failed") if n < first + 2 else (3, "read_exhausted"))
            env.clock.advance(seconds=60)

    fail_three(1)
    assert f"read_exhausted:{env.ci_key}" in env.blockers()
    calls = len(env.calls())
    code, out = env.observe("ci")  # new seq
    assert (code, out["result"]["error"]) == (3, "read_exhausted")
    restarted = subprocess.run(
        [sys.executable, "-c", CLI, "observe", "ci", "--feature", FEATURE, f"--token={env.token}"],
        cwd=env.repo, env=dict(os.environ), capture_output=True, text=True, check=False,
    )
    assert restarted.returncode == 3, restarted.stdout + restarted.stderr
    assert env.safety() is None
    nxt = env.next()
    assert f"read_exhausted:{env.ci_key}" in nxt["blockers"] and nxt["decision_kinds"] == ["resolve_read"]
    assert len(env.calls()) == calls  # 0 automatic fetches
    assert env.state()["read_budget"][env.ci_key]["consecutive_failures"] == 3

    assert env.decide("resolve_read", id="rr-1", target=env.ci_key)[0] == 0
    assert env.safety() == {"action": "observe", "source": "ci", "purpose": "ci", "read_key": env.ci_key}
    fail_three(4)  # one new allowance of three; the count is not reset
    assert env.state()["read_budget"][env.ci_key]["grants"] == ["rr-1"]
    assert env.observe("ci")[1]["result"]["error"] == "read_exhausted"


def test_h8_a_failed_page_fails_the_whole_read(env):
    started(env)
    env.open_pr()
    env.ci([run(env, 90, 30, path=".github/workflows/x.yml"), run(env)], pages=2)
    env.gh.set("runs_p2", api(f"repos/{REPO}/actions/runs?head_sha={env.h}&per_page=100&page=2"),
               page({"message": "bad gateway"}, status=502))
    code, out = env.observe("ci")
    assert (code, out["result"]["error"]) == (1, "read_failed"), out
    st = env.state()
    assert st["read_budget"][env.ci_key]["consecutive_failures"] == 1
    assert env.ci_key not in st["observations"]["current"]  # page 1 is not taken as a partial result
    assert env.g3()["status"] == "pending" and "ci_not_observed" in env.g3()["reasons"]


def test_h9_pending_polls_do_not_count_as_failures_and_follow_the_poll_interval(env):
    started(env)
    env.open_pr()
    env.ci([run(env)])
    jobs = f"repos/{REPO}/actions/runs/101/attempts/1/jobs?per_page=100"
    busy = page({"total_count": 1, "jobs": [job(status="in_progress")]})
    env.gh.set("jobs_101_1", api(jobs), busy, busy, page({"total_count": 1, "jobs": [job()]}))
    ci_reads, waits = 0, []
    for _ in range(12):
        nxt = env.next()
        if nxt["action"] == "wait":
            waits.append(nxt)
            env.clock.advance(seconds=nxt["poll_after_s"])
            continue
        if nxt["action"] != "observe":
            break
        assert env.observe(nxt["source"])[0] == 0
        ci_reads += nxt["source"] == "ci"
        assert env.state()["read_budget"][nxt["read_key"]]["consecutive_failures"] == 0
        if ci_reads == 1:
            activity = [a for a in env.state()["activities"] if a["kind"] == "ci_wait"]
            assert activity == [{"kind": "ci_wait", "head": env.h, "start": activity[0]["start"], "end": None}]
    assert ci_reads == 3 and env.g3()["status"] == "passed"
    assert waits and all(w["poll_after_s"] <= 60 and w["reason"] == f"ci_pending:{env.h}" for w in waits)
    ends = [a["end"] for a in env.state()["activities"] if a["kind"] == "ci_wait"]
    assert ends == [env.clock().isoformat()]  # the CI wait ends when every required check is terminal
    assert env.next() == {"action": "human", "blockers": ["g3_passed"], "decision_kinds": []}


# --- h10: the PR positive path and pr_ensure -----------------------------------------------------


def test_h10_g1_passed_then_push_then_pr_ensure_records_the_pr_identity(env):
    env.start()
    h = env.real_g1()
    assert env.next() == {"action": "write", "op": "push", "id": f"push.{h}"}
    code, out = env.write_op("push", f"push.{h}")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert env.remote_ref() == h and len(env.pushes()) == 1

    snapshot = env.tmp / "state-at-query.json"
    env.pr_routes()
    env.gh.routes["pr_query"]["responses"][0]["effects"] = [
        {"run": ["cp", str(env.home / "features" / FEATURE / "feature.json"), str(snapshot)]}]
    env.gh.flush()
    assert env.next() == {"action": "write", "op": "pr_ensure", "id": "pr_ensure"}
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out

    before = json.loads(snapshot.read_text())["writes"]["pr_ensure"]  # persisted before any GitHub call
    assert before["status"] == "in_flight"
    assert before["prepared"]["marker"] == MARKER
    assert {k: before["prepared"]["expected"][k] for k in ("repo", "head_repo", "head_branch", "head_sha",
                                                           "base_repo", "base_branch", "marker")} == {
        "repo": REPO, "head_repo": REPO, "head_branch": BRANCH, "head_sha": h, "base_repo": REPO,
        "base_branch": "main", "marker": MARKER}
    create = env.calls("pr_create")
    assert len(create) == 1
    assert any(a.startswith("body=") and MARKER in a for a in create[0]["argv"])
    assert f"head={BRANCH}" in create[0]["argv"] and "base=main" in create[0]["argv"]
    pr = env.state()["pr"]
    assert {k: pr[k] for k in ("number", "node_id", "url", "head_repo", "head_branch", "head_sha", "base_repo",
                               "base_branch", "origin")} == {
        "number": PR, "node_id": f"PR_kw{PR}", "url": f"https://github.com/{REPO}/pull/{PR}", "head_repo": REPO,
        "head_branch": BRANCH, "head_sha": h, "base_repo": REPO, "base_branch": "main", "origin": "created"}
    # only now does the loop go on (to PR / CI observation; review dispatch is T5.1's, after this)
    assert env.next() == {"action": "observe", "source": "pr", "purpose": "pr", "read_key": f"pr:{PR}"}
    assert env.unexpected() == []


@pytest.mark.parametrize("status", ["failed", "pending"])
def test_h10_no_push_and_no_pr_call_before_g1_passed(env, status):
    env.start()
    h = env.g1_fixture(status)
    assert env.next()["action"] == "human"
    for kind, op_id in (("push", f"push.{h}"), ("pr_ensure", "pr_ensure")):
        code, out = env.write_op(kind, op_id)
        assert (code, out["result"]["error"]) == (1, "g1_not_passed"), out
    assert (env.pushes(), env.calls()) == ([], [])
    assert "push" not in json.dumps(env.state()["writes"])


def test_h10_pr_ensure_is_not_routable_before_the_push(env):
    started(env)
    env.pr_routes()
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert (code, out["result"]["error"]) == (1, "not_routable"), out
    assert out["result"]["next"] == {"action": "write", "op": "push", "id": f"push.{env.h}"}
    assert env.calls() == []


@pytest.mark.parametrize("case", ["one_match", "other_base", "other_sha", "two_open"])
def test_h10_precreate_query_matrix(env, case):
    started(env)
    env.push()
    found = {
        "one_match": [pr_json(env, marker=False)],
        "other_base": [pr_json(env, base_ref="release", marker=False)],
        "other_sha": [pr_json(env, head_sha="e" * 40, marker=False)],
        "two_open": [pr_json(env, marker=False), pr_json(env, number=18, base_ref="release", marker=False)],
    }[case]
    env.pr_routes(query=found)
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert env.calls("pr_create") == []  # never created when one is open for the branch
    if case == "one_match":
        assert code == 0 and env.state()["pr"]["origin"] == "existing", out
        assert env.state()["pr"]["number"] == PR
    else:
        reason = "pr_ambiguous" if case == "two_open" else "pr_identity_mismatch"
        assert (code, out["result"]["error"]) == (3, reason), out
        assert f"{reason}:pr_ensure" in env.blockers() and "pr" not in env.state()
        code, out = env.write_op("pr_ensure", "pr_ensure")  # resent: refused, still no call
        assert code == 3 and env.calls("pr_create") == []


def test_h10_a_created_pr_other_than_the_expected_one_is_recorded_and_blocks(env):
    started(env)
    env.push()
    env.pr_routes(create=page(pr_json(env, head_sha="e" * 40), status=201))  # the branch moved meanwhile
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out  # it exists: never created again
    assert env.state()["pr"]["head_sha"] == "e" * 40
    assert "pr_identity_mismatch:pr_ensure" in env.blockers()
    assert env.next()["action"] == "human" and len(env.calls("pr_create")) == 1


def test_h10_a_refused_create_blocks_and_is_not_retried(env):
    started(env)
    env.push()
    env.pr_routes(create=page({"message": "Resource not accessible by integration"}, status=403))
    for _ in range(2):
        code, out = env.write_op("pr_ensure", "pr_ensure")
        assert (code, out["result"]["error"]) == (3, "pr_create_rejected"), out
    assert len(env.calls("pr_create")) == 1 and "pr" not in env.state()


def test_h10_delayed_creation_stays_unknown_and_is_never_created_twice(env):
    started(env)
    env.push()
    owner_path = f"repos/{REPO}/pulls?state=open&head=yschiang:{BRANCH}&per_page=100"
    env.pr_routes(create=page({"message": "upstream timeout"}, status=502))
    env.gh.set("pr_query", api(owner_path), page([]), page([]), page([pr_json(env)]))
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert code == 0 and out["result"]["op"]["status"] == "unknown", out
    assert env.safety() == {"action": "write", "op": "pr_ensure", "id": "pr_ensure"}  # read back only
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert (code, out["result"]["error"]) == (3, "write_unknown"), out
    # GitHub now shows the PR (the request took effect late): still no second create, no rebind
    env.clock.advance(seconds=60)
    for _ in range(2):
        code, out = env.write_op("pr_ensure", "pr_ensure")
        assert code == 3
    nxt = env.next()
    assert nxt["action"] == "human" and "write_unknown:pr_ensure" in nxt["blockers"]
    assert nxt["decision_kinds"] == ["resolve_operation"]
    assert len(env.calls("pr_create")) == 1 and "pr" not in env.state()


@pytest.mark.parametrize("case", ["marker_and_identity", "marker_other_base", "identity_without_marker"])
def test_h10_unknown_create_is_only_read_back(env, case):
    started(env)
    env.push()
    found = {
        "marker_and_identity": [pr_json(env)],
        "marker_other_base": [pr_json(env, base_ref="release")],
        "identity_without_marker": [pr_json(env, marker=False)],
    }[case]
    env.pr_routes(create=page({"message": "bad gateway"}, status=502), get=found[0])
    owner_path = f"repos/{REPO}/pulls?state=open&head=yschiang:{BRANCH}&per_page=100"
    env.gh.set("pr_query", api(owner_path), page([]), page(found))
    assert env.write_op("pr_ensure", "pr_ensure")[1]["result"]["op"]["status"] == "unknown"
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert len(env.calls("pr_create")) == 1
    if case == "marker_and_identity":
        assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
        pr = env.state()["pr"]
        assert (pr["origin"], pr["number"], env.state()["writes"]["pr_ensure"]["resolved_by"]) == (
            "created", PR, "readback")
        return
    assert (code, out["result"]["error"]) == (3, "write_unknown"), out
    assert "pr" not in env.state()
    if case == "identity_without_marker":  # a human binds the matching PR after checking it
        evidence = env.tmp / "checked.txt"
        evidence.write_text("PR 17 opened by the same request; GitHub dropped the body\n")
        code, out = env.decide("resolve_operation", id="ro-1", target="pr_ensure", bind=str(PR), evidence=str(evidence))
        assert code == 0, out
        code, out = env.write_op("pr_ensure", "pr_ensure")
        assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
        pr = env.state()["pr"]
        assert (pr["origin"], env.state()["writes"]["pr_ensure"]["resolved_by"]) == ("existing", "human")
        assert len(env.calls("pr_create")) == 1


def test_h10_bind_is_refused_when_the_fresh_read_does_not_match(env):
    started(env)
    env.push()
    env.pr_routes(create=page({"message": "bad gateway"}, status=502), get=pr_json(env, base_ref="release"))
    assert env.write_op("pr_ensure", "pr_ensure")[1]["result"]["op"]["status"] == "unknown"
    assert env.write_op("pr_ensure", "pr_ensure")[0] == 3  # read back: absent
    evidence = env.tmp / "checked.txt"
    evidence.write_text("looked at PR 17\n")
    assert env.decide("resolve_operation", id="ro-1", target="pr_ensure", bind=str(PR), evidence=str(evidence))[0] == 0
    code, out = env.write_op("pr_ensure", "pr_ensure")
    assert (code, out["result"]["error"]) == (3, "resolution_rejected"), out
    assert env.state()["writes"]["pr_ensure"]["status"] == "unknown" and "pr" not in env.state()


# --- h11: write push ---------------------------------------------------------------------------


FORCE = ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d", "--prune")


def test_h11_push_argv_is_a_plain_fast_forward_of_h_to_the_plan_branch(env):
    started(env)
    env.push()
    op = env.state()["writes"][f"push.{env.h}"]
    argv = json.loads(store.get_object(op["prepared"]["argv"][store.OBJECT_KEY]))
    assert argv == ["git", "-C", str(env.repo), "push", "--porcelain", "origin", f"{env.h}:refs/heads/{BRANCH}"]
    assert not set(argv) & set(FORCE) and not any(a.startswith("+") for a in argv)
    assert op["prepared"]["call_limit_s"] == 120
    assert env.pushes() == [f"-C {env.repo} push --porcelain origin {env.h}:refs/heads/{BRANCH}"]


def test_h11_a_non_fast_forward_rejection_fails_and_blocks_without_rebase_or_force(env):
    started(env)
    git(env.repo, "checkout", "-q", "-b", "side", "main")
    env.write("side.txt", "someone else\n", env.repo)
    side = commit_all(env.repo, "side")
    git(env.repo, "checkout", "-q", "main")
    git(env.repo, "push", "-q", "origin", f"{side}:refs/heads/{BRANCH}")
    before = len(env.pushes())
    code, out = env.write_op("push", f"push.{env.h}")
    assert (code, out["result"]["error"]) == (3, "push_rejected"), out
    op = env.state()["writes"][f"push.{env.h}"]
    assert (op["status"], op["blocked"]) == ("failed", "push_rejected")
    assert f"push_rejected:push.{env.h}" in env.blockers()
    assert env.remote_ref() == side
    code, out = env.write_op("push", f"push.{env.h}")
    assert code == 3
    assert len(env.pushes()) == before + 1
    log = env.gitlog.read_text()
    assert "rebase" not in log and "--force" not in log


def slow_post_receive(env: GhEnv, git_dir: Path | None = None) -> None:
    """The remote updates the ref and then keeps the client waiting (the reply is lost)."""
    hook = (git_dir or env.remote) / "hooks" / "post-receive"
    hook.write_text("#!/bin/sh\nsleep 2\n")
    hook.chmod(0o755)


def test_h11_an_unknown_push_is_read_back_and_succeeds_when_the_remote_ref_is_h(env):
    started(env, push_call_s=0.5)
    slow_post_receive(env)
    code, out = env.write_op("push", f"push.{env.h}")
    assert code == 0 and out["result"]["op"]["status"] == "unknown", out
    assert env.safety() == {"action": "write", "op": "push", "id": f"push.{env.h}"}
    code, out = env.write_op("push", f"push.{env.h}")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    op = env.state()["writes"][f"push.{env.h}"]
    assert (op["resolved_by"], len(op["attempts"]), len(env.pushes())) == ("readback", 1, 1)


@pytest.mark.parametrize("case", ["remote_at_another_sha", "h_on_another_ref", "h_only_on_a_fork"])
def test_h11_an_unknown_push_is_not_resent_when_the_target_ref_is_not_h(env, case):
    started(env, push_call_s=0.5)
    slow_post_receive(env)
    assert env.write_op("push", f"push.{env.h}")[1]["result"]["op"]["status"] == "unknown"
    ref = f"refs/heads/{BRANCH}"
    if case == "remote_at_another_sha":
        env.remote_git("update-ref", ref, env.b0)
    elif case == "h_on_another_ref":
        env.remote_git("update-ref", "refs/heads/elsewhere", env.h)
        env.remote_git("update-ref", "-d", ref)
    else:
        fork = env.tmp / "fork.git"
        subprocess.run([env.real_git, "clone", "-q", "--bare", str(env.remote), str(fork)], check=True)
        env.remote_git("update-ref", "-d", ref)
    code, out = env.write_op("push", f"push.{env.h}")
    assert (code, out["result"]["error"]) == (3, "write_unknown"), out
    op = env.state()["writes"][f"push.{env.h}"]
    assert op["status"] == "unknown" and op["resolved_by"] is None
    assert env.write_op("push", f"push.{env.h}")[0] == 3
    assert len(env.pushes()) == 1  # 0 resends
    assert env.next()["decision_kinds"] == ["resolve_operation"]


def test_h11_the_same_sha_is_resent_within_the_retry_limit(env):
    started(env)
    git(env.repo, "remote", "set-url", "origin", str(env.tmp / "missing.git"))
    code, out = env.write_op("push", f"push.{env.h}")  # nothing reached any remote
    assert code == 0 and out["result"]["op"]["status"] == "failed", out
    assert env.state()["writes"][f"push.{env.h}"]["attempts"][0]["reason"] == "remote_unreachable"
    git(env.repo, "remote", "set-url", "origin", str(env.remote))
    subprocess.run([env.real_git, "-C", str(env.repo), "push", "-q", "origin", f"{env.h}:refs/heads/{BRANCH}"],
                   check=True)  # H is already there (the same fast-forward): the resend is a no-op
    assert env.next() == {"action": "write", "op": "push", "id": f"push.{env.h}"}
    code, out = env.write_op("push", f"push.{env.h}")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert len(env.pushes()) == 2 and env.remote_ref() == env.h


def test_h11_a_third_undelivered_push_exhausts_the_retries(env):
    started(env)
    git(env.repo, "remote", "set-url", "origin", str(env.tmp / "missing.git"))
    for n in (1, 2):
        code, out = env.write_op("push", f"push.{env.h}")
        assert code == 0, out
        assert (out["result"]["op"]["status"], out["result"]["op"]["attempts"]) == ("failed", n)
    code, out = env.write_op("push", f"push.{env.h}")
    assert (code, out["result"]["error"]) == (3, "retry_exhausted"), out
    assert f"retry_exhausted:push.{env.h}" in env.blockers()
    code, out = env.write_op("push", f"push.{env.h}")
    assert code == 3 and len(env.pushes()) == 3


# --- h12: the tested-SHA artifact of every job ---------------------------------------------------


def two_jobs(d: dict) -> None:
    d["g3"]["required_checks"] = [{"name": "unit-linux", "app": "github-actions"},
                                  {"name": "unit-macos", "app": "github-actions"}]


H12 = ["all_match", "one_job_missing", "run_id", "run_attempt", "job", "check_name", "sha_not_h",
       "rerun_with_only_the_old_attempt"]


@pytest.mark.parametrize("case", H12)
def test_h12_every_required_job_needs_its_own_matching_tested_sha_artifact(env, case):
    started(env, policy=two_jobs)
    env.open_pr()
    attempt = 2 if case == "rerun_with_only_the_old_attempt" else 1
    jobs = [job("unit-linux", attempt=attempt), job("unit-macos", attempt=attempt)]
    tested = {f"tested-sha-{j}-{attempt}": {"run_id": "101", "run_attempt": str(attempt), "job": j, "check_name": j,
                                            "tested_sha": env.h} for j in ("unit-linux", "unit-macos")}
    if case == "one_job_missing":
        tested.pop("tested-sha-unit-macos-1")
    elif case == "rerun_with_only_the_old_attempt":
        tested = {k.replace("-2", "-1"): {**v, "run_attempt": "1"} for k, v in tested.items()}
    elif case == "sha_not_h":
        tested["tested-sha-unit-macos-1"]["tested_sha"] = "f" * 40
    elif case != "all_match":
        tested["tested-sha-unit-macos-1"][case] = "other"
    g3 = env.to_g3([run(env, attempt=attempt, jobs=jobs, tested=tested)])
    if case == "all_match":
        assert g3["status"] == "passed", g3
        assert {r["tested_sha"] for c in g3["checks"].values() for r in c["runs"]} == {env.h}
        return
    assert g3["status"] == "unknown", g3
    expected = {
        "one_job_missing": "tested_sha_missing:unit-macos:101",
        "rerun_with_only_the_old_attempt": "tested_sha_missing:unit-linux:101",
        "sha_not_h": "unsupported_integration_source:unit-macos:101",
    }.get(case, f"tested_sha_mismatch:{case}:unit-macos:101")
    assert expected in g3["reasons"], g3


# --- h13: integration triggers -------------------------------------------------------------------


def trigger_key(base_tip: str, head: str) -> str:
    return f"base_integration:{REPO}:main:{base_tip}:{head}"


@pytest.mark.parametrize("case", ["mergeable_false", "reviewer_finding", "human_revise"])
def test_h13_a_trigger_records_integration_required_with_its_source(env, case):
    started(env)
    env.open_pr(mergeable=case != "mergeable_false")
    if case == "reviewer_finding":
        finding = {"id": "F-7", "status": "open", "category": "correctness_security", "blocking": True,
                   "base_incompatible": True}
        env.mutate("finding", lambda s: {**s, "findings": {**s["findings"], "F-7": finding}})
    if case == "human_revise":
        assert env.decide("revise", id="rv-1", target="base_integration", version=env.h,
                          reason="integrate the new base first")[0] == 0
    if case != "mergeable_false":
        env.clock.advance(seconds=60)
        assert env.observe("pr")[0] == 0
    required = env.state()["integration_required"]
    source = {"mergeable_false": "mergeable_false", "reviewer_finding": "finding:F-7",
              "human_revise": "decision:rv-1"}[case]
    assert list(required) == [trigger_key(B0_REMOTE, env.h)]
    entry = required[trigger_key(B0_REMOTE, env.h)]
    assert (entry["base"], entry["base_tip"], entry["head"], entry["sources"]) == (
        f"{REPO}:main", B0_REMOTE, env.h, [source])
    nxt = env.next()
    assert nxt == {"action": "human", "blockers": [f"integration_required:{trigger_key(B0_REMOTE, env.h)}"],
                   "decision_kinds": []}
    # T6.1 only detects: no integration finding, no batch (T5.1 creates and dedupes those)
    assert env.state()["batches"] == {}
    assert set(env.state()["findings"]) == ({"F-7"} if case == "reviewer_finding" else set())


def test_h13_the_same_base_b_h_is_one_trigger_key(env):
    started(env)
    env.open_pr(mergeable=False)
    for _ in range(2):
        env.clock.advance(seconds=60)
        assert env.observe("pr")[0] == 0
    assert env.decide("revise", id="rv-1", target="base_integration", version=env.h, reason="same base")[0] == 0
    env.clock.advance(seconds=60)
    assert env.observe("pr")[0] == 0
    required = env.state()["integration_required"]
    assert list(required) == [trigger_key(B0_REMOTE, env.h)]
    assert required[trigger_key(B0_REMOTE, env.h)]["sources"] == ["mergeable_false", "decision:rv-1"]


def test_h13_a_conflict_without_a_ci_run_is_ci_unavailable_not_pending(env):
    started(env)
    env.open_pr(mergeable=False)
    env.ci([])
    assert env.observe("ci")[0] == 0
    g3 = env.g3()
    assert g3["status"] == "unknown" and "ci_unavailable_conflict" in g3["reasons"], g3


def test_h13_mergeable_null_keeps_g3_pending_then_true_does_not_integrate(env):
    started(env)
    env.open_pr(mergeable=None)
    g3 = env.to_g3([run(env)])
    assert g3["status"] == "pending" and "mergeable_unknown" in g3["reasons"], g3
    for _ in range(3):  # still null: pending (the CI-wait timeout is T7.1's, b4)
        env.clock.advance(seconds=60)
        assert env.observe("pr")[0] == 0
        assert env.g3()["status"] == "pending"
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, mergeable=True)))
    env.clock.advance(seconds=60)
    assert env.observe("pr")[0] == 0
    assert env.g3()["status"] == "passed" and env.state()["integration_required"] == {}


def test_h13_base_moved_and_mergeable_true_only_rebinds(env):
    started(env)
    env.open_pr()
    assert env.to_g3([run(env)])["status"] == "passed"
    env.gh.set("pr_get", api(f"repos/{REPO}/pulls/{PR}"), page(pr_json(env, base_sha=B1_REMOTE)))
    env.clock.advance(seconds=60)
    assert env.observe("pr")[0] == 0
    assert env.state()["integration_required"] == {}
    assert env.state()["g1_binding"]["pending"]["base"] == B1_REMOTE
    assert env.next() == {"action": "evidence_green", "head": env.h}


# --- the reference scenario files ------------------------------------------------------------------


def test_reference_scenario_files_drive_the_same_g3(env, monkeypatch):
    """tests/fakes/scenarios/gh/*.json: the fake's format with env placeholders."""
    started(env)
    monkeypatch.setenv("GH_REPO", REPO)
    monkeypatch.setenv("GH_HEAD", env.h)
    monkeypatch.setenv("GH_PR", str(PR))
    env.push()
    routes: list[dict] = []
    for name in ("pr-created.json", "ci-unit-linux-success.json"):
        routes += json.loads((SCENARIOS / name).read_text())["routes"]
    env.scenario.write_text(json.dumps({"routes": routes}))
    assert env.write_op("pr_ensure", "pr_ensure")[0] == 0
    assert env.observe("pr")[0] == 0
    assert env.observe("ci")[0] == 0
    assert env.g3()["status"] == "passed"
    assert env.unexpected() == []
