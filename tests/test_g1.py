"""M-G1 g1–g15, g3b: the G1 evidence gate (design §7, §8; T3.1).

Every command goes through the public CLI in-process (`loopctl.cli.main`); `loopctl.clock.now`
is the only clock and is monkeypatched. Repositories are real git repos in tmp dirs (merge,
merge-tree, rebase, detached checkouts). Evidence commands are the registered test policy's
`suite`: pytest of the fixture repo (g15: a sleeping fake suite).

Attempt metadata — assignment and attempt records, finding and batch IDs, the N/A
eligibility records and fixture replays — is written with the store API, as T2.3 dispatch
and T5.1 would write it (validation M-G1: "finding ID 與 batch ID 在 T3.1 以 attempt metadata
的 fixture 提供"). g1 runs the whole public path through the T2.3 Harness instead.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_writes import (
    FEATURE,
    PLAN,
    T0,
    TASK_ACS,
    TASK_SCOPE,
    Clock,
    Harness,
    c_process_info,
    c_send_keys,
    commit_all,
    finished_turn,
    git,
)

from loopctl import clock, store
from loopctl.cli import main

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feat"
PANE = "w1:p1"
SUITE = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={junit_out}"]
REVIEWER = {"role": "reviewer", "model": "gpt-6-astra", "native_session_id": "ses_rev1", "capability": "verified"}
TASKS = {
    "T1": {"acs": [{"id": "AC-1", "verify": "pytest tests/test_double.py"}],
           "scope": ["src/calc.py", "tests/test_double.py"]},
    "T2": {"acs": [{"id": "AC-2", "verify": "pytest tests/test_triple.py"}],
           "scope": ["src/calc.py", "tests/test_triple.py"]},
    "D1": {"acs": [{"id": "AC-3", "verify": "manual: usage and settings stay as documented"}],
           "scope": ["docs/usage.md", "config/app.yaml", "tests/test_base.py", "migrations/*.sql"]},
    "TA": {"acs": [{"id": "AC-4", "verify": "pytest tests/test_a.py"}],
           "scope": ["src/a.py", "tests/test_a.py"]},
}
CALC = "def double(x):\n    return x\n\n\ndef triple(x):\n    return x\n"
BASE_TEST = """import os
from pathlib import Path


def test_base():
    # g15(c): lock a directory inside a linked checkout so it cannot be removed
    if os.environ.get("G15_LOCK") and Path(".git").is_file():
        Path("locked/inner").mkdir(parents=True)
        Path("locked/inner/f").write_text("x")
        os.chmod("locked", 0o500)
    assert True
"""
SHA_TEST = """import os
import subprocess
from pathlib import Path


def test_records_the_sha_it_runs_at():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if os.environ.get("G5_SHA_OUT"):
        Path(os.environ["G5_SHA_OUT"]).write_text(head)
    assert head != os.environ.get("G5_FAIL_AT", "")
"""
FILES = {
    "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["src"]\ntestpaths = ["tests"]\n',
    ".gitignore": "__pycache__/\n",
    "src/calc.py": CALC,
    "src/a.py": "def a():\n    return 1\n",
    "src/p.py": "P = 1\n",
    "tests/test_base.py": BASE_TEST,
    "tests/test_sha.py": SHA_TEST,
    "tests/test_a.py": "from a import a\n\n\ndef test_a_one():\n    assert a() == 1\n",
    "tests/test_p.py": "from p import P\n\n\ndef test_p():\n    assert P in (1, 2)\n",
    "docs/usage.md": "# Usage\n",
    "config/app.yaml": "# retry settings\nretries: 3\n",
}
RED_DOUBLE = "from calc import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
IMPL_DOUBLE = "def double(x):\n    return 2 * x\n\n\ndef triple(x):\n    return x\n"
# g15: a fake suite that starts a grandchild in its process group and outlives the limit.
SLEEPER = (
    "import os, subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    "open(os.environ['G15_PID'], 'w').write(str(child.pid))\n"
    "time.sleep(5)\n"
)


def policy_doc(suite: list[str] | None = None, **limits: float) -> dict:
    doc = yaml.safe_load((ROOT / "workflow.yaml").read_text())
    doc["evidence"]["commands"]["suite"] = {"argv": suite or SUITE}
    doc["limits"].update(limits)
    return doc


def plan_text(repo: Path, wt: Path, tasks: tuple[str, ...]) -> str:
    block = yaml.safe_dump(
        {"workspace": {"source": str(repo), "worktree": str(wt), "branch": BRANCH, "base": "main"},
         "tasks": [{"id": t, **TASKS[t]} for t in tasks]},
        sort_keys=False,
    )
    return f"# plan\n\n```loopctl-plan\n{block}```\n"


class WallClock:
    """`clock.now` moving with real time from T0 (g15 measures a real time limit)."""

    def __init__(self) -> None:
        self.m0 = time.monotonic()

    def __call__(self):
        return T0 + timedelta(seconds=time.monotonic() - self.m0)


class Env:
    """One feature with an approved plan over a real repo and its linked worktree."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        self.tmp, self.mp, self.capsys = tmp_path, monkeypatch, capsys
        self.home = tmp_path / "loopctl-home"
        monkeypatch.setenv("LOOPCTL_HOME", str(self.home))
        monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
        self.clock: Any = Clock()
        monkeypatch.setattr(clock, "now", self.clock)
        self.repo, self.wt = tmp_path / "repo", tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        for rel, text in FILES.items():
            self.write(rel, text, self.repo)
        self.b0 = commit_all(self.repo, "base")
        git(self.repo, "worktree", "add", "-q", "-b", BRANCH, str(self.wt), "main")
        monkeypatch.chdir(self.repo)
        self.token = ""

    def wall_clock(self) -> None:
        self.clock = WallClock()
        self.mp.setattr(clock, "now", self.clock)

    # --- files and git --------------------------------------------------------------------

    def write(self, rel: str, text: str, root: Path | None = None) -> None:
        path = (root or self.wt) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message: str, root: Path | None = None) -> str:
        return commit_all(root or self.wt, message)

    def head(self, root: Path | None = None) -> str:
        return git(root or self.wt, "rev-parse", "HEAD")

    def gitx(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            capture_output=True, text=True, check=check,
        )

    # --- CLI ------------------------------------------------------------------------------

    def cli(self, *argv: str) -> tuple[int, dict]:
        code = main(list(argv))
        return code, json.loads(self.capsys.readouterr().out)

    def start(self, tasks: tuple[str, ...] = ("T1",), suite: list[str] | None = None, **limits: float) -> None:
        pol, spec, plan = self.tmp / "workflow.yaml", self.tmp / "spec.md", self.tmp / "plan.md"
        pol.write_text(yaml.safe_dump(policy_doc(suite, **limits)))
        spec.write_text("# spec\n")
        plan.write_text(plan_text(self.repo, self.wt, tasks))
        code, out = self.cli("init", "--repo", "yschiang/loop-engineering", "--repo-id", "R_1",
                             "--feature", FEATURE, "--issue", "7")
        assert code == 0, out
        code, out = self.cli("claim", "--feature", FEATURE, "--actor", "orchestrate")
        assert code == 0, out
        self.token = out["result"]["token"]
        tok = f"--token={self.token}"
        for argv in (
            ["register", "policy", "--locator", str(pol), "--version", "p1"],
            ["register", "binding", "--role", "spec", "--locator", str(spec), "--version", "s1"],
            ["register", "plan", "--locator", str(plan), "--version", "v1", "--producer", "implementer",
             "--calibrated-from", str(spec)],
            ["decide", "approve_plan", "--id=approve-1", "--actor=human:alice", f"--target={plan}",
             "--version=v1", "--reason=approved with the user"],
        ):
            code, out = self.cli(*argv, "--feature", FEATURE, tok)
            assert code == 0, out
        worktree = {"kind": "worktree_create", "status": "succeeded", "facts": {"pane": PANE}}
        self.mutate("implementing", lambda s: {**s, "phase": "implementing", "writes": {"worktree": worktree}})

    def red(self, attempt: str, *extra: str, cwd: Path | None = None, command: str = "suite") -> tuple[int, dict]:
        self.mp.chdir(cwd or self.wt)
        try:
            return self.cli("evidence", "red", "--feature", FEATURE, "--attempt", attempt,
                            "--command-id", command, *extra)
        finally:
            self.mp.chdir(self.repo)

    def captured(self, attempt: str, *extra: str, cwd: Path | None = None) -> str:
        """`evidence red` that must record a behaviour failure; returns the evidence id."""
        code, out = self.red(attempt, *extra, cwd=cwd)
        assert code == 0, out
        record = out["result"]["evidence"]
        assert record["status"] == "test_failed", record
        return str(record["id"])

    def green(self) -> tuple[int, dict]:
        return self.cli("evidence", "green", "--feature", FEATURE, f"--token={self.token}")

    def assess(self) -> tuple[int, dict]:
        return self.cli("assess", "--feature", FEATURE, f"--token={self.token}")

    def next(self) -> dict:
        return dict(self.cli("next", "--feature", FEATURE)[1]["next"])

    # --- state fixtures (what T2.3 dispatch / T5.1 would record) --------------------------

    def state(self) -> dict:
        return store.load(FEATURE)[1]

    def g1(self) -> dict:
        return dict(self.state()["gates"]["g1"])

    def evidence(self, eid: str) -> dict:
        return dict(self.state()["evidence"][eid])

    def mutate(self, tid: str, fn: Callable[[dict], Any]) -> None:
        def apply(s: dict) -> dict:
            out = fn(s)
            return s if out is None else out

        rev, _ = store.load(FEATURE)
        store.commit(FEATURE, rev, f"test:{tid}:{uuid.uuid4().hex[:8]}", apply)

    def dispatch(
        self, attempt: str, *, batch: str | None = None, findings: tuple[str, ...] = (),
        scope: list[str] | None = None, integration: tuple[str, str] | None = None,
        worktree: Path | None = None, head: str | None = None,
    ) -> dict:
        wt = worktree or self.wt
        task_id = None if batch else attempt.rsplit("-", 1)[0]
        task = TASKS.get(task_id or "", {"acs": [], "scope": []})
        st = self.state()
        at = self.clock().isoformat()
        asg = {
            "attempt_id": attempt, "task_id": task_id, "batch_id": batch, "finding_ids": list(findings),
            "role": "implementer",
            "profile": {"transport": "herdr", "runtime": "claude-code", "provider": "anthropic",
                        "model": "claude-opus-5-5", "effort": "high", "settings": "profiles/implementer.claude-settings.json"},
            "worktree": str(wt), "branch": BRANCH, "base": "main",
            "head": head or (integration[0] if integration else self.head(wt)), "pr": None,
            "plan": {k: st["plan"][k] for k in ("locator", "version", "digest")},
            "digests": dict(st["approval"]["digests"]), "acs": task["acs"],
            "scope": scope if scope is not None else task["scope"],
            "result_path": str(wt / ".loopctl" / "results" / f"{attempt}.json"), "result_schema": 1,
        }
        if integration:
            asg["integration"] = {"head": integration[0], "base_tip": integration[1]}
        handle = {"herdr_session": None, "pane": PANE, "agent_name": f"lc-{FEATURE}-{attempt}",
                  "native_session_id": str(uuid.uuid4()), "runtime": "claude-code"}

        def add(s: dict) -> None:
            s.setdefault("assignments", {})[attempt] = asg
            s["attempts"][attempt] = {
                "n": len(s["attempts"]) + 1, "task_id": task_id, "role": "implementer", "handle": handle,
                "poll_s": 30, "started_at": at, "result": None, "rejected": [], "conflicts": [], "end": None,
            }
            s.setdefault("activities", []).append({"kind": "worker", "attempt": attempt, "start": at, "end": None})

        self.mutate(f"dispatch:{attempt}", add)
        return asg

    def _end(self, attempt: str, result: dict | None, evidence: str) -> None:
        at = self.clock().isoformat()

        def end(s: dict) -> None:
            s["attempts"][attempt]["result"] = result
            s["attempts"][attempt]["end"] = {"evidence": evidence, "at": at}
            for activity in s["activities"]:
                if activity.get("attempt") == attempt and activity["kind"] == "worker" and not activity["end"]:
                    activity["end"] = at

        self.mutate(f"end:{attempt}", end)

    def complete(self, attempt: str, head: str | None = None, status: str = "completed") -> str:
        """The attempt's result is imported and its writer ended (T2.3 records)."""
        wt = Path(self.state()["assignments"][attempt]["worktree"])
        head = head or self.head(wt)
        data = json.dumps({"attempt_id": attempt, "head": head}).encode()
        result = {
            "object": store.object_ref(store.put_object(data)), "digest": store.digest(data),
            "producer": "worker", "native": {"runtime": "claude-code", "session_id": "x"}, "raw_digest": None,
            "status": status, "head": head, "body_kind": "implementation", "at": self.clock().isoformat(),
        }
        self._end(attempt, result, "result_and_native_turn")
        return head

    def abandon(self, attempt: str) -> None:
        """Stopped by a confirmed stop, without a result (design §7: its Red does not transfer)."""
        self._end(attempt, None, "stop_confirmed")

    def na(self, unit: str, attempt: str, status: str = "accepted", *, reviewer: dict | None = REVIEWER,
           behavior_change: bool | None = False, head: str | None = None) -> None:
        head = head or self.state()["attempts"][attempt]["result"]["head"]
        record = {"attempt": attempt, "head": head, "status": status, "behavior_change": behavior_change,
                  "reason": "fixture eligibility", "reviewer": reviewer}
        self.mutate(f"na:{unit}", lambda s: {**s, "na": {**s.get("na", {}), unit: record}})

    def fixture_replay(self, of: str) -> None:
        """A replay of `of` that reproduced its failure (g3b, g11: it must not rescue the Red)."""
        failing = self.evidence(of)["failing"]
        record = {"id": f"replay-fixture-{of}", "kind": "replay", "of": of, "status": "test_failed",
                  "reproduced": True, "failing": failing}
        self.mutate(f"replay:{of}", lambda s: {**s, "evidence": {**s["evidence"], record["id"]: record}})

    # --- the usual TDD task ---------------------------------------------------------------

    def task_done(self, attempt: str = "T1-a1", red: bool = True) -> tuple[str | None, str]:
        """T1: failing test (captured uncommitted), then the implementation, one commit."""
        if attempt not in self.state().get("attempts", {}):
            self.dispatch(attempt)
        self.write("tests/test_double.py", RED_DOUBLE)
        eid = self.captured(attempt) if red else None
        self.write("src/calc.py", IMPL_DOUBLE)
        head = self.commit(f"{attempt}: double")
        self.complete(attempt)
        return eid, head


@pytest.fixture
def env(tmp_path, monkeypatch, capsys) -> Env:
    return Env(tmp_path, monkeypatch, capsys)


def unit_red(env: Env, unit: str) -> str | None:
    return env.g1()["units"][unit].get("red")


def replays(env: Env) -> list[dict]:
    return [e for e in env.state().get("evidence", {}).values() if e["kind"] == "replay"]


# --- g1: the public path ----------------------------------------------------------------------

INGEST_RED = """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest import parse  # noqa: E402


def test_parse_strips_whitespace():
    assert parse("  a  ") == "a"
"""


@pytest.fixture
def h(tmp_path, monkeypatch, capsys, fakes) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys, fakes)


def test_g1_original_red_and_head_green_pass_without_replay(h, tmp_path):
    """Approved plan → worker Red through `evidence red` → import → `next` gives evidence_green
    → Green in a clean checkout → `next` gives assess → G1 passed; no replay."""
    text = (h.repo / PLAN).read_text().partition("```loopctl-plan")[0]
    block = yaml.safe_dump(
        {"workspace": {"source": str(h.repo), "worktree": str(h.wt), "branch": "feat/ingest", "base": "main"},
         "tasks": [{"id": "T1", "acs": TASK_ACS["T1"], "scope": TASK_SCOPE["T1"]}]},
        sort_keys=False,
    )
    (h.repo / PLAN).write_text(f"{text}```loopctl-plan\n{block}```\n")
    (h.repo / ".git" / "info" / "exclude").write_text("__pycache__/\n")
    h.start()
    pol = tmp_path / "evidence-policy.yaml"
    pol.write_text(yaml.safe_dump(policy_doc()))
    code, out = h.cli("register", "policy", "--feature", FEATURE, f"--token={h.token}", "--locator", str(pol),
                      "--version", "p1")
    assert code == 0, out
    h.dispatch()

    # The worker writes the failing test first and captures it with the one loopctl command it may run.
    (h.wt / "tests" / "test_ingest.py").write_text(INGEST_RED)
    h.monkeypatch.chdir(h.wt)
    code, out = h.cli("evidence", "red", "--feature", FEATURE, "--attempt", "T1-a1", "--command-id", "suite")
    h.monkeypatch.chdir(h.repo)
    assert code == 0, out
    red = out["result"]["evidence"]
    assert (red["status"], red["exit"], red["attempt"], red["task_id"]) == ("test_failed", 1, "T1-a1", "T1")
    assert red["failing"] == ["tests.test_ingest::test_parse_strips_whitespace"]
    t1 = h.work()  # the implementation (and the test) in one commit

    env = h.envelope()
    h.put_result(env)
    assert h.import_result()[0] == 0
    h.transcript(finished_turn(h, json.dumps(env)))
    assert h.observe("native")[0] == 0
    assert h.next() == {"action": "write", "op": "stop", "id": "T1-a1.stop"}
    h.expect(c_send_keys(), c_process_info(running=False))
    assert h.write("stop", "T1-a1.stop")[0] == 0
    assert h.write("stop", "T1-a1.stop")[0] == 0

    assert h.next() == {"action": "evidence_green", "head": t1}
    code, out = h.cli("evidence", "green", "--feature", FEATURE, f"--token={h.token}")
    assert code == 0, out
    green = out["result"]["evidence"]
    assert (green["status"], green["head"], green["checkout_head"]) == ("passed", t1, t1)

    assert h.next() == {"action": "assess"}
    code, out = h.cli("assess", "--feature", FEATURE, f"--token={h.token}")
    assert code == 0, out
    g1 = h.state()["gates"]["g1"]
    assert (g1["status"], g1["head"], g1["green"]) == ("passed", t1, green["id"])
    assert g1["units"]["task:T1"]["red"] == red["id"]
    assert [e for e in h.state()["evidence"].values() if e["kind"] == "replay"] == []
    assert h.next() == {"action": "human", "blockers": ["g1_passed"], "decision_kinds": []}
    assert h.unexpected() == []


# --- g2: replay is only a diagnostic ----------------------------------------------------------

FLAKY_DOUBLE = """import os

from calc import double


def test_double():
    if os.environ.get("G2_FLIP") == "pass":
        return
    assert double(2) == 4
"""


@pytest.mark.parametrize("replay", ["reproduced", "not_reproduced"])
def test_g2_contradictory_evidence_gets_a_diagnostic_replay(env, monkeypatch, replay):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", FLAKY_DOUBLE)
    red = env.captured("T1-a1")
    monkeypatch.setenv("G2_FLIP", "pass")  # the same snapshot now passes: the evidence contradicts itself
    code, out = env.red("T1-a1")
    assert code == 0 and out["result"]["evidence"]["status"] == "passed", out
    assert out["result"]["evidence"]["snapshot"]["tree"] == env.evidence(red)["snapshot"]["tree"]
    monkeypatch.delenv("G2_FLIP")
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    assert env.green()[0] == 0

    if replay == "not_reproduced":
        monkeypatch.setenv("G2_FLIP", "pass")
    code, out = env.assess()
    runs = replays(env)
    assert len(runs) == 1 and runs[0]["of"] == red
    g1 = env.g1()
    if replay == "reproduced":
        assert code == 0, out
        assert runs[0]["reproduced"] is True
        assert g1["status"] == "passed"
        assert unit_red(env, "task:T1") == red  # still the original, never the replay
    else:
        assert code == 3, out
        assert runs[0]["reproduced"] is False
        assert g1["status"] == "blocked"
        assert f"red_contradicted:{red}" in g1["reasons"]
        assert f"red_contradicted:{red}" in env.state()["blockers"]
        assert unit_red(env, "task:T1") is None
    assert all(e["kind"] != "red" or e["id"] != runs[0]["id"] for e in env.state()["evidence"].values())


# --- g3: each polluted field of an original Red ----------------------------------------------


def _pollute(field: str, env: Env) -> Callable[[dict], None]:
    other = store.object_ref(store.put_object(b"forged: 1 passed\n"))

    def apply(e: dict) -> None:
        if field == "raw":
            e["raw"]["stdout"] = other
        elif field == "exit":
            e["exit"] = 0
        elif field == "task":
            e["task_id"] = "T9"
        elif field == "snapshot":
            e["snapshot"]["tree"] = git(env.repo, "rev-parse", f"{env.b0}^{{tree}}")
        elif field == "producer":
            e["producer"] = {"tool": "worker"}

    return apply


@pytest.mark.parametrize(
    "field,reason",
    [("raw", "raw"), ("exit", "exit"), ("task", "provenance:task"), ("snapshot", "snapshot"),
     ("producer", "producer")],
)
def test_g3_each_polluted_field_fails_g1_with_its_reason(env, field, reason):
    env.start()
    red, _ = env.task_done()
    assert env.green()[0] == 0
    change = _pollute(field, env)
    env.mutate(f"pollute:{field}", lambda s: change(s["evidence"][red]))
    code, out = env.assess()
    g1 = env.g1()
    assert code == 3, out
    assert g1["status"] == "blocked"
    assert f"red_invalid:{red}:{reason}" in g1["reasons"], g1["reasons"]
    assert "original_red_unavailable:task:T1" in g1["reasons"]


# --- g3b: the three eligibility rules (D51-R07) ------------------------------------------------


def test_g3b_a_snapshot_outside_the_task_scope(env):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", RED_DOUBLE)
    env.write("docs/usage.md", "# Usage\n\nscratch\n")  # uncommitted, outside T1's scope
    red = env.captured("T1-a1")
    env.write("docs/usage.md", FILES["docs/usage.md"])
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    env.fixture_replay(red)
    assert env.green()[0] == 0
    assert env.assess()[0] == 3
    g1 = env.g1()
    assert f"red_invalid:{red}:scope:docs/usage.md" in g1["reasons"]
    assert "original_red_unavailable:task:T1" in g1["reasons"]


def test_g3b_a_attempt_commit_outside_the_task_scope(env):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", RED_DOUBLE)
    red = env.captured("T1-a1")
    env.write("src/calc.py", IMPL_DOUBLE)
    env.write("docs/usage.md", "# Usage\n\nchanged by T1\n")
    env.commit("double and docs")
    env.complete("T1-a1")  # fixture: recorded as T2.3 would have, bypassing its import check
    env.fixture_replay(red)
    assert env.green()[0] == 0
    assert env.assess()[0] == 3
    g1 = env.g1()
    assert f"red_invalid:{red}:scope:docs/usage.md" in g1["reasons"]
    assert g1["status"] == "blocked"


SIBLING_TEST = "from calc import double\n\n\ndef test_double_three():\n    assert double(3) == 6\n"


def test_g3b_b_a_sibling_snapshot_with_only_a_common_parent_is_not_the_attempts_red(env):
    env.start()
    wt2 = env.tmp / "wt-sibling"
    git(env.repo, "worktree", "add", "-q", "--detach", str(wt2), "main")
    env.dispatch("T1-s1", worktree=wt2)
    env.write("tests/test_double.py", SIBLING_TEST, wt2)
    sibling = env.captured("T1-s1", cwd=wt2)
    env.abandon("T1-s1")
    assert env.evidence(sibling)["snapshot"]["parent"] == env.b0  # the same parent as T1-a1

    env.dispatch("T1-a1")
    env.write("tests/test_double.py", RED_DOUBLE)
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    env.fixture_replay(sibling)
    assert env.green()[0] == 0
    assert env.assess()[0] == 3
    g1 = env.g1()
    assert f"red_invalid:{sibling}:attempt_abandoned" in g1["reasons"]
    assert "original_red_unavailable:task:T1" in g1["reasons"]
    assert unit_red(env, "task:T1") is None


@pytest.mark.parametrize("case", ["committed_red_in_history", "red_before_the_attempt", "discarded_test"])
def test_g3b_mapping_needs_the_snapshot_in_the_attempt_history_or_its_test_delta(env, case):
    """The capture record alone is not enough: the snapshot commit must be in the attempt's own
    history, or the failing tests' delta must be in the attempt commit (design §7)."""
    env.start()
    if case == "red_before_the_attempt":  # a failing test that predates the attempt
        env.write("tests/test_double.py", RED_DOUBLE)
        env.commit("a failing test from before the attempt")
    env.dispatch("T1-a1")
    if case == "committed_red_in_history":
        env.write("tests/test_double.py", RED_DOUBLE)
        env.commit("failing test first")
    elif case == "discarded_test":
        env.write("tests/test_double.py", SIBLING_TEST)
    red = env.captured("T1-a1")
    if case == "discarded_test":
        env.write("tests/test_double.py", RED_DOUBLE)  # the captured test never reaches the commit
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    assert env.green()[0] == 0
    env.assess()
    g1 = env.g1()
    if case == "committed_red_in_history":
        assert env.evidence(red)["snapshot"]["commit"] == env.evidence(red)["snapshot"]["parent"]  # clean capture
        assert g1["status"] == "passed", g1["reasons"]
        assert unit_red(env, "task:T1") == red
    else:
        assert g1["status"] == "blocked"
        assert f"red_invalid:{red}:unmapped" in g1["reasons"]


def test_next_offers_green_again_when_the_head_moved_after_green(env):
    env.start()
    env.task_done()
    assert env.next()["action"] == "evidence_green"
    assert env.green()[0] == 0
    assert env.next() == {"action": "assess"}
    env.write("docs/usage.md", "# Usage\n\nlater\n")
    d = env.commit("docs after Green")
    env.assess()
    g1 = env.g1()
    assert (g1["status"], g1["head"]) == ("pending", d)
    assert f"green_missing:{d}" in g1["reasons"]
    assert env.next() == {"action": "evidence_green", "head": d}
    assert env.green()[0] == 0
    assert env.next() == {"action": "assess"}
    assert env.assess()[0] == 0 and env.g1()["status"] == "passed"
    assert env.next() == {"action": "human", "blockers": ["g1_passed"], "decision_kinds": []}


def test_evidence_red_after_the_result_is_imported_is_refused(env):
    env.start()
    env.dispatch("T1-a1")
    env.mutate("result", lambda s: s["attempts"]["T1-a1"].update(result={"status": "completed", "head": env.b0}))
    code, out = env.red("T1-a1")
    assert (code, out["result"]["error"]) == (1, "result_already_imported"), out


def test_g3b_c_an_attempt_that_is_not_an_ancestor_of_h(env):
    env.start()
    red, _ = env.task_done()
    # The feature branch goes on from the base without the attempt's commit.
    env.gitx(env.wt, "reset", "-q", "--hard", env.b0)
    env.write("src/calc.py", IMPL_DOUBLE)
    h = env.commit("double, elsewhere")
    env.fixture_replay(red)
    assert env.green()[0] == 0
    assert env.assess()[0] == 3
    g1 = env.g1()
    assert g1["head"] == h
    assert f"red_invalid:{red}:attempt_not_ancestor" in g1["reasons"]
    assert not any(r.startswith("history_rewritten") for r in g1["reasons"])


def test_g3b_d_an_uncommitted_red_maps_to_the_attempt_by_its_test_delta(env):
    env.start()
    red, head = env.task_done()
    assert env.green()[0] == 0
    assert env.assess()[0] == 0
    snapshot = env.evidence(red)["snapshot"]
    assert snapshot["commit"] != head and snapshot["parent"] == env.b0  # not the same SHA
    assert env.g1()["status"] == "passed"
    assert unit_red(env, "task:T1") == red
    assert replays(env) == []


# --- g4 ----------------------------------------------------------------------------------------


def test_g4_a_task_without_an_original_red_blocks(env):
    env.start()
    env.task_done(red=False)
    assert env.green()[0] == 0
    code, out = env.assess()
    assert code == 3, out
    g1 = env.g1()
    assert g1["status"] == "blocked"
    assert "original_red_unavailable:task:T1" in g1["reasons"]
    assert "original_red_unavailable:task:T1" in env.state()["blockers"]


def test_g4_an_empty_task_set_fails(env):
    env.start(tasks=())
    _, out = env.assess()
    g1 = env.g1()
    assert g1["status"] == "failed", out
    assert "task_set_empty" in g1["reasons"]


@pytest.mark.parametrize(
    "broken,status",
    [("def test_double(:\n    pass\n", "collection_error"),
     ("def test_double():\n    from calc import quadruple\n    assert quadruple(1) == 4\n", "not_behavior_failure")],
)
def test_g4_a_syntax_or_import_error_is_not_a_red(env, broken, status):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", broken)
    code, out = env.red("T1-a1")
    assert code == 0, out
    bad = out["result"]["evidence"]
    assert bad["status"] == status
    env.write("tests/test_double.py", RED_DOUBLE)
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    assert env.green()[0] == 0
    assert env.assess()[0] == 3
    g1 = env.g1()
    assert f"red_invalid:{bad['id']}:not_a_red:{status}" in g1["reasons"]
    assert "original_red_unavailable:task:T1" in g1["reasons"]


# --- g5: evidence outside the repo; a docs-only head after the code -----------------------------


@pytest.mark.parametrize("green_at_d", ["passes", "fails"])
def test_g5_docs_commit_after_the_code_reruns_green_at_d(env, monkeypatch, green_at_d):
    env.start()
    red, _ = env.task_done()
    ref = env.evidence(red)
    env.write("docs/usage.md", f"# Usage\n\nG1 evidence: {red} ({ref['raw_digest']['stdout']})\n")
    d = env.commit("docs: cite the evidence")
    sha_out = env.tmp / "green-sha.txt"
    monkeypatch.setenv("G5_SHA_OUT", str(sha_out))
    if green_at_d == "fails":
        monkeypatch.setenv("G5_FAIL_AT", d)
    code, out = env.green()
    assert code == 0, out
    green = out["result"]["evidence"]
    assert (green["head"], green["checkout_head"], sha_out.read_text()) == (d, d, d)  # D, not C
    assert not [p for p in git(env.wt, "ls-files").splitlines() if p.startswith(".loopctl")]
    assert env.home not in env.repo.parents and not (env.repo / "objects").exists()

    env.assess()
    g1 = env.g1()
    assert g1["head"] == d
    assert unit_red(env, "task:T1") == red  # the original Red still applies through lineage
    assert {"reason": "docs_only", "commits": [d], "paths": ["docs/usage.md"]} in g1["applicability"]
    if green_at_d == "passes":
        assert g1["status"] == "passed"
    else:
        assert g1["status"] == "failed" and "integration_regression" in g1["reasons"]


# --- g6 ----------------------------------------------------------------------------------------

RED_TRIPLE = "from calc import triple\n\n\ndef test_triple():\n    assert triple(2) == 6\n"


def test_g6_integration_regression_fails_g1_and_gives_no_g2(env):
    env.start(tasks=("T1", "T2"))
    env.task_done()
    env.dispatch("T2-a1")
    env.write("tests/test_triple.py", RED_TRIPLE)
    env.captured("T2-a1")
    env.write("src/calc.py", "def double(x):\n    return x + x + 1\n\n\ndef triple(x):\n    return 3 * x\n")
    env.commit("triple (breaks double)")
    env.complete("T2-a1")
    code, out = env.green()
    assert code == 0 and out["result"]["evidence"]["status"] == "test_failed", out
    assert env.assess()[0] == 0
    g1 = env.g1()
    assert g1["status"] == "failed"
    assert "integration_regression" in g1["reasons"]
    assert {u: v["status"] for u, v in g1["units"].items()} == {"task:T1": "passed", "task:T2": "passed"}
    assert "g2" not in env.state()["gates"]
    nxt = env.next()
    assert nxt["action"] == "human" and "g1_failed" in nxt["blockers"]


# --- g7 / g8: N/A --------------------------------------------------------------------------------


def _docs_task(env: Env, changes: dict[str, str]) -> str:
    env.start(tasks=("D1",))
    env.dispatch("D1-a1")
    for rel, text in changes.items():
        env.write(rel, text)
    head = env.commit("D1")
    env.complete("D1-a1")
    return head


@pytest.mark.parametrize(
    "changes",
    [{"docs/usage.md": "# Usage\n\nRun `calc` with one number.\n"},
     {"config/app.yaml": "# retry settings (tuned in the runbook)\nretries: 3\n",
      "tests/test_base.py": BASE_TEST.replace("def test_base():", "# a smoke test\ndef test_base():")}],
    ids=["docs_only", "yaml_and_test_comments"],
)
def test_g7_accepted_na_passes_g1_and_leaves_g2_g3_pending(env, changes):
    _docs_task(env, changes)
    env.na("task:D1", "D1-a1")
    assert env.green()[0] == 0
    assert env.assess()[0] == 0
    g1 = env.g1()
    assert g1["status"] == "passed", g1["reasons"]
    assert g1["units"]["task:D1"]["via"] == "na"
    _, out = env.cli("status", "--feature", FEATURE)
    assert out["result"]["gates"]["g2"]["status"] == "pending"
    assert out["result"]["gates"]["g3"]["status"] == "pending"


@pytest.mark.parametrize(
    "case,changes,na,reason,status",
    [
        ("self_declared", {"docs/usage.md": "# Usage!\n"}, {"reviewer": None}, "na_self_declared", "failed"),
        ("implementer_says_so", {"docs/usage.md": "# Usage!\n"},
         {"reviewer": {**REVIEWER, "role": "implementer"}}, "na_self_declared", "failed"),
        ("pending", {"docs/usage.md": "# Usage!\n"}, {"status": "pending", "behavior_change": None},
         "na_pending", "pending"),
        ("config_value", {"config/app.yaml": "# retry settings\nretries: 5\n"},
         {"status": "rejected", "behavior_change": True}, "na_rejected", "blocked"),
        ("test_assertion", {"tests/test_base.py": BASE_TEST.replace("assert True", "assert 1 + 1 == 2")},
         {"status": "rejected", "behavior_change": True}, "na_rejected", "blocked"),
        ("migration", {"migrations/0001_add_retries.sql": "ALTER TABLE jobs ADD COLUMN retries INT;\n"},
         {"status": "rejected", "behavior_change": True}, "na_rejected", "blocked"),
        ("model_mismatch", {"docs/usage.md": "# Usage!\n"}, {"reviewer": {**REVIEWER, "model": "gpt-6-sol"}},
         "na_model_mismatch", "failed"),
        ("same_model_as_implementer", {"docs/usage.md": "# Usage!\n"},
         {"reviewer": {**REVIEWER, "model": "claude-opus-5-5"}}, "na_not_independent", "failed"),
        ("capability_unverified", {"docs/usage.md": "# Usage!\n"},
         {"reviewer": {**REVIEWER, "capability": "unverified"}}, "na_capability_unverified", "failed"),
    ],
)
def test_g8_na_that_is_not_an_independent_acceptance_does_not_pass(env, case, changes, na, reason, status):
    _docs_task(env, changes)
    env.na("task:D1", "D1-a1", **na)
    assert env.green()[0] == 0
    env.assess()
    g1 = env.g1()
    assert g1["status"] == status, g1
    assert f"{reason}:task:D1" in g1["reasons"], g1["reasons"]
    if status == "blocked":
        assert "original_red_unavailable:task:D1" in g1["reasons"]


def test_g8_na_reviewer_session_of_the_implementer_is_not_independent(env):
    _docs_task(env, {"docs/usage.md": "# Usage!\n"})
    session = env.state()["attempts"]["D1-a1"]["handle"]["native_session_id"]
    env.na("task:D1", "D1-a1", reviewer={**REVIEWER, "native_session_id": session})
    assert env.green()[0] == 0
    env.assess()
    assert "na_not_independent:task:D1" in env.g1()["reasons"]


# --- g9 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra,code",
    [(("--", "touch", "{marker}"), 2), (("--argv", "touch {marker}"), 2)],
    ids=["trailing_argv", "argv_option"],
)
def test_g9_evidence_red_with_worker_argv_is_refused(env, extra, code):
    env.start()
    env.dispatch("T1-a1")
    marker = env.tmp / "marker"
    got, out = env.red("T1-a1", *(a.replace("{marker}", str(marker)) for a in extra))
    assert got == code, out
    assert not marker.exists()
    assert env.state().get("evidence", {}) == {}
    assert [a for a in env.state()["activities"] if a["kind"] == "evidence"] == []


def test_g9_a_command_id_outside_the_policy_is_refused(env):
    env.start()
    env.dispatch("T1-a1")
    marker = env.tmp / "marker"
    code, out = env.red("T1-a1", command=f"touch {marker}")
    assert code == 1 and out["result"]["error"] == "unknown_command_id", out
    assert not marker.exists()
    assert env.state().get("evidence", {}) == {}


def test_g9_the_command_never_comes_from_a_workflow_yaml_in_the_worktree(env):
    """Without a registered (bound) policy, the worktree's own workflow.yaml is worker-written."""
    env.start()
    env.dispatch("T1-a1")
    marker = env.tmp / "marker"
    doc = policy_doc(suite=[sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"])
    env.write("workflow.yaml", yaml.safe_dump(doc))
    env.mutate("unbind", lambda s: {**s, "versions": {k: v for k, v in s["versions"].items() if k != "policy"}})
    code, out = env.red("T1-a1")
    assert (code, out["result"]["error"]) == (3, "policy_not_registered"), out
    assert not marker.exists()
    assert env.state().get("evidence", {}) == {}
    assert env.cli("evidence", "green", "--feature", FEATURE, f"--token={env.token}")[0] == 3
    assert not marker.exists()


def test_evidence_red_only_runs_in_the_attempts_worktree_while_it_is_active(env):
    env.start()
    env.dispatch("T1-a1")
    code, out = env.red("T1-a1", cwd=env.repo)
    assert (code, out["result"]["error"]) == (1, "not_in_attempt_worktree"), out
    env.abandon("T1-a1")
    code, out = env.red("T1-a1")
    assert (code, out["result"]["error"]) == (1, "attempt_ended"), out
    assert env.state().get("evidence", {}) == {}


def test_evidence_green_and_assess_need_the_owner_token(env):
    env.start()
    assert env.cli("evidence", "green", "--feature", FEATURE, "--token=nope")[0] == 4
    assert env.cli("assess", "--feature", FEATURE, "--token=nope")[0] == 4


# --- g10: behaviour-changing corrections --------------------------------------------------------

RED_ROUND = RED_DOUBLE + "\n\ndef test_double_truncates():\n    assert double(1.25) == 2\n"
IMPL_ROUND = IMPL_DOUBLE.replace("return 2 * x", "return int(2 * x)")
FIX_SCOPE = ["src/calc.py", "tests/test_double.py", "docs/usage.md"]


def _correction(env: Env, attempt: str, batch: str, findings: tuple[str, ...], kind: str,
                red_findings: tuple[str, ...] | None, docs_only: bool = False) -> str | None:
    env.mutate(f"batch:{batch}", lambda s: {**s, "batches": {**s["batches"], batch: {"kind": kind,
                                                                                         "findings": list(findings)}}})
    env.dispatch(attempt, batch=batch, findings=findings, scope=FIX_SCOPE)
    eid = None
    if docs_only:
        env.write("docs/usage.md", f"# Usage\n\n{batch}: double works for any integer.\n")
    else:
        env.write("tests/test_double.py", RED_ROUND + f"\n# {batch}\n")
        if red_findings is not None:
            eid = env.captured(attempt, *(f"--finding={f}" for f in red_findings))
        env.write("src/calc.py", IMPL_ROUND + f"\n# {batch}\n")
    env.commit(f"{batch}: fix")
    env.complete(attempt)
    return eid


@pytest.mark.parametrize("kind", ["pre_review_g1", "g2_fix"])
@pytest.mark.parametrize("variant", ["a", "b", "c_other_batch", "c_other_finding", "d", "e"])
def test_g10_a_behaviour_changing_correction_needs_its_own_bound_red(env, kind, variant):
    env.start()
    env.task_done()
    if variant == "a":
        red = _correction(env, "B1-a1", "B1", ("F-1",), kind, ("F-1",))
    elif variant == "b":
        _correction(env, "B1-a1", "B1", ("F-1",), kind, None)
    elif variant == "c_other_batch":
        other = _correction(env, "B0-a1", "B0", ("F-0",), kind, ("F-0",))
        env.write("src/calc.py", env.wt.joinpath("src/calc.py").read_text() + "# B1 tweak\n")
        env.mutate("batch:B1", lambda s: {**s, "batches": {**s["batches"], "B1": {"kind": kind, "findings": ["F-1"]}}})
        env.dispatch("B1-a1", batch="B1", findings=("F-1",), scope=FIX_SCOPE)
        env.commit("B1: fix")
        env.complete("B1-a1")
    elif variant == "c_other_finding":
        env.dispatch("B1-a1", batch="B1", findings=("F-1",), scope=FIX_SCOPE)
        env.write("tests/test_double.py", RED_ROUND)
        code, out = env.red("B1-a1", "--finding=F-9")
        assert (code, out["result"]["error"]) == (1, "finding_not_in_assignment"), out
        env.write("src/calc.py", IMPL_ROUND)
        env.commit("B1: fix")
        env.complete("B1-a1")
    elif variant == "d":
        red = _correction(env, "B1-a1", "B1", ("F-1", "F-2"), kind, ("F-1",))
    else:
        _correction(env, "B1-a1", "B1", ("F-1",), kind, None, docs_only=True)
        env.na("batch:B1", "B1-a1")
    assert env.green()[0] == 0
    env.assess()
    g1 = env.g1()
    if variant == "a":
        assert g1["status"] == "passed", g1["reasons"]
        assert unit_red(env, "batch:B1:F-1") == red
    elif variant in ("b", "c_other_finding"):
        assert g1["status"] == "blocked"
        assert "original_red_unavailable:batch:B1:F-1" in g1["reasons"]
    elif variant == "c_other_batch":
        assert g1["status"] == "blocked"
        assert unit_red(env, "batch:B0:F-0") == other
        assert "original_red_unavailable:batch:B1:F-1" in g1["reasons"]
    elif variant == "d":
        assert g1["status"] == "blocked"
        assert unit_red(env, "batch:B1:F-1") == red
        assert "original_red_unavailable:batch:B1:F-2" in g1["reasons"]
        assert "original_red_unavailable:batch:B1:F-1" not in g1["reasons"]
    else:
        assert g1["status"] == "passed", g1["reasons"]
        assert g1["units"]["batch:B1:F-1"]["via"] == "na"


# --- g11: an abandoned attempt's Red does not transfer -------------------------------------------


@pytest.mark.parametrize("variant", ["a", "b"])
def test_g11_the_red_of_an_abandoned_attempt_does_not_transfer(env, variant):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", RED_DOUBLE)
    first = env.captured("T1-a1")
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("A1 work in progress")
    env.abandon("T1-a1")
    env.gitx(env.wt, "reset", "-q", "--hard", env.b0)  # A2 starts over from the base
    env.dispatch("T1-a2")
    env.write("tests/test_double.py", RED_DOUBLE)
    second = env.captured("T1-a2") if variant == "a" else None
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("A2: double")
    env.complete("T1-a2")
    if variant == "b":
        env.fixture_replay(first)
    assert env.green()[0] == 0
    env.assess()
    g1 = env.g1()
    assert g1["units"]["task:T1"]["invalid"][first] == ["attempt_abandoned"]
    if variant == "a":
        assert g1["status"] == "passed", g1["reasons"]
        assert unit_red(env, "task:T1") == second
    else:
        assert g1["status"] == "blocked"
        assert "original_red_unavailable:task:T1" in g1["reasons"]


# --- g12 ---------------------------------------------------------------------------------------


def test_g12_rewritten_history_blocks_and_nothing_is_pushed_or_rebased(env, fakes):
    fakes.install("gh")
    env.start()
    _, c1 = env.task_done()
    assert env.green()[0] == 0
    assert env.assess()[0] == 0 and env.g1()["status"] == "passed"
    env.gitx(env.wt, "commit", "-q", "--amend", "-m", "rewritten outside loopctl")  # rebase + force-push
    rewritten = env.head()
    code, out = env.assess()
    assert code == 3, out
    g1 = env.g1()
    assert g1["status"] == "blocked"
    assert f"history_rewritten:{c1}" in g1["reasons"]
    assert unit_red(env, "task:T1") is None
    assert "history_rewritten" in env.state()["blockers"]
    assert git(env.repo, "rev-parse", f"refs/heads/{BRANCH}") == rewritten
    assert fakes.calls() == []
    nxt = env.next()
    assert nxt["action"] == "human" and "history_rewritten" in nxt["blockers"]


# --- g13: integration merge, imports and author edits (real git) ------------------------------


def _integration(env: Env, variant: str) -> tuple[str, str, str | None]:
    """Steps 1–4 of validation g13; returns (H, B1, the integration Red or None)."""
    env.start(tasks=("TA",))
    env.dispatch("TA-a1")
    env.write("tests/test_a.py", "from a import a\n\n\ndef test_a_two():\n    assert a() == 2\n")
    env.captured("TA-a1")
    env.write("src/a.py", "def a():\n    return 2\n")
    h = env.commit("TA: a returns 2")
    env.complete("TA-a1")
    if variant == "g":  # H and B1 will also conflict on docs/usage.md, outside F-I's scope
        env.write("docs/usage.md", "# Usage\n\nfeature docs\n")
        h = env.commit("docs: feature usage")
        env.write("docs/usage.md", "# Usage\n\nbase docs\n", env.repo)

    env.write("src/p.py", "P = 2\n", env.repo)
    if variant != "a":
        env.write("src/a.py", "def a():\n    return 3\n", env.repo)
        env.write("tests/test_a.py", "from a import a\n\n\ndef test_a_three():\n    assert a() == 3\n", env.repo)
    b1 = env.commit("base moves: a and p", env.repo)
    target = "main"
    if variant == "e_other_parent":
        env.write("docs/usage.md", "# Usage\n\nbase docs\n", env.repo)
        env.commit("base moves again", env.repo)
    env.dispatch("I1-a1", batch="BI", findings=("F-I",), scope=["src/a.py", "tests/test_a.py"],
                 integration=(h, b1))
    if variant == "a":
        env.gitx(env.wt, "merge", "-q", "--no-edit", target)
        env.complete("I1-a1")
        return h, b1, None
    squash = ["--squash"] if variant == "e_squash" else []
    merged = env.gitx(env.wt, "merge", "-q", "--no-edit", *squash, target, check=False)
    assert merged.returncode != 0  # a and its test conflict
    env.write("src/a.py", "def a():\n    return 2\n")  # ours for now: the new test must fail first
    env.write("tests/test_a.py", "from a import a\n\n\ndef test_a_five():\n    assert a() == 5\n")
    red = None if variant == "d" else env.captured("I1-a1", "--finding=F-I")
    env.write("src/a.py", "def a():\n    return 5\n")  # the author's resolution (behaviour)
    if variant == "c":
        env.write("src/p.py", "P = 2  # tweaked while merging\n")
    if variant == "f":
        env.write("docs/usage.md", "# Usage\n\nneeded to resolve the merge\n")
    if variant == "g":
        env.write("docs/usage.md", "# Usage\n\nfeature and base docs\n")  # resolves a conflict outside the scope
    env.gitx(env.wt, "add", "-A")
    if variant == "e_squash":
        env.gitx(env.wt, "commit", "-q", "-m", "squash the base")
    else:
        env.gitx(env.wt, "commit", "-q", "--no-edit")
    env.complete("I1-a1")
    return h, b1, red


@pytest.mark.parametrize("variant", ["a", "b", "c", "d", "e_squash", "e_other_parent", "f", "g"])
def test_g13_integration_attempt_imports_and_author_edits(env, variant):
    h, b1, red = _integration(env, variant)
    m = env.head()
    assert env.green()[0] == 0
    env.assess()
    g1 = env.g1()
    check = g1["integration"].get("I1-a1", {})
    assert "g2" not in env.state()["gates"] and "g3" not in env.state()["gates"]
    if variant == "a":
        assert git(env.wt, "rev-list", "--parents", "-n", "1", m).split()[1:] == [h, b1]
        assert check["imported"] == ["src/p.py"] and check["author"] == {"conflict": [], "additional": []}
        assert g1["units"]["batch:BI:F-I"] == {**g1["units"]["batch:BI:F-I"], "status": "passed", "via": "import"}
        assert g1["units"]["task:TA"]["status"] == "passed"  # H is still an ancestor
        assert g1["status"] == "passed", g1["reasons"]
    elif variant == "b":
        assert check["imported"] == ["src/p.py"]
        assert check["author"] == {"conflict": ["src/a.py", "tests/test_a.py"], "additional": []}
        assert unit_red(env, "batch:BI:F-I") == red
        assert g1["status"] == "passed", g1["reasons"]
    elif variant == "c":
        assert check["author"]["additional"] == ["src/p.py"]
        assert g1["status"] == "failed"
        assert "integration_rejected:I1-a1:hidden_edit:src/p.py" in g1["reasons"]
    elif variant == "d":
        assert g1["status"] == "blocked"
        assert "original_red_unavailable:batch:BI:F-I" in g1["reasons"]
    elif variant.startswith("e_"):
        assert g1["status"] == "failed"
        assert "integration_rejected:I1-a1:parents" in g1["reasons"]
    else:  # f: an additional edit, g: a conflict resolution, both outside the scope
        if variant == "g":
            assert check["author"]["conflict"] == ["docs/usage.md", "src/a.py", "tests/test_a.py"]
        assert g1["status"] == "blocked"
        assert "integration_scope_exceeded:I1-a1:docs/usage.md" in g1["reasons"]
        assert "integration_scope_exceeded:I1-a1" in env.state()["blockers"]


# --- g14 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("h_itself", ["passes", "fails"])
def test_g14_green_runs_in_a_clean_checkout_of_h(env, h_itself):
    env.start()
    env.dispatch("T1-a1")
    env.write("tests/test_double.py", RED_DOUBLE)
    env.captured("T1-a1")
    if h_itself == "passes":
        env.write("src/calc.py", IMPL_DOUBLE)
        h = env.commit("double")
        env.write("tests/test_untracked.py", "def test_only_here():\n    assert False\n")
    else:
        env.write("src/calc.py", "from helper import TWO\n\n\ndef double(x):\n    return TWO * x\n\n\n"
                                 "def triple(x):\n    return x\n")
        h = env.commit("double (helper not committed)")
        env.write("src/helper.py", "TWO = 2\n")  # untracked: only the worktree has it
    env.complete("T1-a1")
    in_worktree = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=env.wt,
                                 capture_output=True, text=True, check=False)
    assert (in_worktree.returncode == 0) == (h_itself == "fails")  # the worktree says the opposite
    code, out = env.green()
    assert code == 0, out
    green = out["result"]["evidence"]
    assert (green["head"], green["checkout_head"]) == (h, h)
    assert (green["status"] == "passed") == (h_itself == "passes")
    assert not Path(green["checkout"]).exists()
    assert green["checkout"] not in git(env.repo, "worktree", "list")


# --- g15: the evidence command's time limit ---------------------------------------------------


def _wait_dead(pid: int, within_s: float = 5.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        done = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                              check=False).stdout
        if done.strip().startswith("Z"):
            return True
        time.sleep(0.05)
    return False


def test_g15_a_green_past_its_limit_kills_the_group_and_blocks(env, monkeypatch):
    pid_file = env.tmp / "grandchild.pid"
    monkeypatch.setenv("G15_PID", str(pid_file))
    env.wall_clock()
    env.start(suite=[sys.executable, "-c", SLEEPER, "{junit_out}"], evidence_call_s=1)
    env.dispatch("T1-a1")
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    started = time.monotonic()
    code, out = env.green()
    assert code == 3 and out["result"]["error"] == "evidence_timeout", out
    assert time.monotonic() - started < 4.5  # not the suite's 5 s
    assert _wait_dead(int(pid_file.read_text()))  # the whole process group, grandchild included
    st = env.state()
    green = next(e for e in st["evidence"].values() if e["kind"] == "green")
    assert (green["status"], green["cause"], green["limit_s"]) == ("evidence_timeout", "call_limit", 1.0)
    activity = next(a for a in st["activities"] if a["kind"] == "evidence")
    assert activity["evidence"] == green["id"] and activity["end"] is not None
    spent = datetime.fromisoformat(activity["end"]) - datetime.fromisoformat(activity["start"])
    assert spent >= timedelta(seconds=0.9)
    assert f"evidence_timeout:{green['id']}" in st["blockers"]
    assert not Path(green["checkout"]).exists()
    nxt = env.next()
    assert nxt["action"] == "human"  # 0 new workers, 0 automatic reruns
    env.assess()
    assert env.g1()["status"] != "passed"
    assert [e["kind"] for e in env.state()["evidence"].values()] == ["green"]


def test_g15_b_the_limit_is_the_remaining_active_budget(env, monkeypatch):
    monkeypatch.setenv("G15_PID", str(env.tmp / "grandchild.pid"))
    env.wall_clock()
    env.start(suite=[sys.executable, "-c", SLEEPER, "{junit_out}"])  # evidence_call_s stays 900
    used = {"kind": "worker", "attempt": "T0-a1", "start": (T0 - timedelta(hours=4) + timedelta(seconds=2)).isoformat(),
            "end": T0.isoformat()}
    env.mutate("budget", lambda s: {**s, "activities": [used]})
    env.dispatch("T1-a1")
    env.write("src/calc.py", IMPL_DOUBLE)
    env.commit("double")
    env.complete("T1-a1")
    code, out = env.green()
    assert code == 3 and out["result"]["error"] == "evidence_timeout", out
    st = env.state()
    green = next(e for e in st["evidence"].values() if e["kind"] == "green")
    assert green["cause"] == "active_budget"
    assert 1.0 < green["limit_s"] <= 2.0
    activity = next(a for a in st["activities"] if a["kind"] == "evidence")
    assert activity["end"] is not None
    assert f"evidence_timeout:{green['id']}" not in st["blockers"]  # expiry routing is T7.1's (b7)
    env.assess()
    assert env.g1()["status"] != "passed"


def test_g15_c_a_checkout_that_cannot_be_removed_is_listed_for_a_human(env, monkeypatch):
    env.start()
    env.task_done()
    monkeypatch.setenv("G15_LOCK", "1")
    code, out = env.green()
    green = out["result"]["evidence"]
    try:
        assert code == 0, out
        assert green["status"] == "passed"  # the verdict is recorded as usual
        assert Path(green["checkout"]).exists()
        assert f"checkout_not_removed:{green['checkout']}" in env.state()["blockers"]
    finally:
        locked = Path(green["checkout"]) / "locked"
        if locked.exists():
            os.chmod(locked, stat.S_IRWXU)
            shutil.rmtree(green["checkout"], ignore_errors=True)
