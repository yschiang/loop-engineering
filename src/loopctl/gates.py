"""Gates (design §7, §8). T3.1 adds G1; T6.1 (G3, and the route G1 passed → push → PR → CI),
T5.1 (G2) and T6.2 (Pass) add theirs without changing the G1 rules (tasks.md shared-file table).

`route` is pure (called by `loopctl.next`). `assess` reads git and may run a diagnostic replay.

G1 at the current head H (the feature branch in the source repository):
  units: every task of the approved plan (`task:<T>`; an empty task set fails) and every
  finding of every correction batch found in `assignments` (`batch:<B>:<F>`). A unit passes
  with one eligible original Red, or when every eligible attempt it answers for (a task's
  attempts; the batch's attempts that list the finding) is exempt on its own: an integration
  merge with no author edits, or the one attempt an accepted independent N/A judged (keyed
  `task:<T>` / `batch:<B>` in `state.na`; a batch record covers the findings its attempt lists).
  A Red is eligible only if every check holds, each on its own (D51-R07):
    integrity  producer, raw objects vs digests, exit re-derived from the raw junit,
               provenance (attempt, task, batch, findings, worktree) vs the assignment,
               snapshot commit/tree/parent/ref vs git;
    lineage    its attempt has a completed result whose commit C is an ancestor of H
               (a stopped or abandoned attempt's Red does not transfer);
    scope      snapshot changes and each commit of the attempt's range (dispatch head..C) are in scope
               (integration: author edits only — conflict resolutions included —, imports
               verified against merge-tree);
    mapping    the snapshot commit is in the attempt's own history, or the failing tests'
               delta (vs the dispatch head) is in C.
  A replay never makes a Red; it runs only when another run of the same tree passed one of
  the Red's failing tests, and then decides between continuing and Blocked.
  Green: the latest `evidence green` at H must have passed in a checkout of H.

State (fields owned here): gates.g1 = {status passed|pending|failed|blocked, reasons, head,
  green, green_seen, results_seen, units {unit: {status, reasons, red, via, invalid}},
  integration {attempt: classification}, applicability, unattributed, heads, assessed_at};
  and the G1 blockers in `blockers` (original_red_unavailable:<unit>, history_rewritten,
  integration_scope_exceeded:<attempt>, red_contradicted:<red>), recomputed by each assess.
"""

import fnmatch
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from loopctl import assignments, store, writes
from loopctl import evidence as ev
from loopctl.observe import (
    Rejected,
    block,
    commit,
    current,
    exhausted,
    limit,
    now_iso,
    owned,
)

State = dict[str, Any]
ORDER = ("passed", "pending", "failed", "blocked")
G1_BLOCKERS = ("original_red_unavailable:", "history_rewritten", "integration_scope_exceeded:", "red_contradicted:")
DOCS = ("*.md", "*.rst", "docs/*")  # "only documentation changed" after the last attempt (G05)


RECOVERY_KINDS = {"g3_policy": "policy_change"}  # T6.1: blocker prefix -> the decide kind for it


def human(blockers: list[str], kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": kinds or []}


def worst(statuses: list[str]) -> str:
    return max(statuses, key=ORDER.index) if statuses else "passed"


def in_scope(path: str, scope: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in scope)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# --- routing (pure; `next` calls it once dispatch has no task left) ------------------------


def route(state: State) -> dict[str, Any]:
    """evidence_green → assess → the G1 outcome; never a rerun of the same evidence."""
    done = ev.completed(state)
    latest_head = done[-1][2]["result"]["head"] if done else None
    greens = ev.records(state, "green")
    green = greens[-1] if greens else None
    g1 = (state.get("gates") or {}).get("g1")
    if green is None or green.get("results_seen", 0) < len(done):
        return {"action": "evidence_green", "head": latest_head}
    if green["status"] == "running":
        return human([f"evidence_interrupted:{green['id']}"])
    if g1 is None or g1.get("green_seen") != green["id"] or g1.get("results_seen", -1) < len(done):
        return {"action": "assess"}
    if g1["head"] != green["head"]:  # assess saw the head move after this Green
        return {"action": "evidence_green", "head": g1["head"]}
    if g1["status"] == "passed":
        return human(["g1_passed"])  # T6.1 routes to push from here
    return human([f"g1_{g1['status']}", *g1["reasons"]])


# --- assess ------------------------------------------------------------------------------


def _task_list(state: State) -> Any:
    plan = state.get("plan") or {}
    if not plan.get("content"):
        return None
    text = store.get_object(plan["content"][store.OBJECT_KEY]).decode(errors="replace")
    match = assignments.PLAN_BLOCK.search(text)
    try:
        doc = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        return None
    return doc.get("tasks") if isinstance(doc, dict) else None


class _G1:
    """One evaluation of G1 over a loaded state; git is read through `loopctl.tools.evidence`."""

    def __init__(self, state: State, pol: dict[str, Any]) -> None:
        from loopctl.tools import evidence as tools

        self.t, self.st, self.pol = tools, state, pol
        self.s = limit(pol, "read_call_s", 30)
        self.doc = assignments.plan_doc(state)
        self.asg: dict[str, Any] = state.get("assignments") or {}
        self.att: dict[str, Any] = state.get("attempts") or {}
        self.evidence: dict[str, Any] = state.get("evidence") or {}
        self.repo = self.doc["workspace"]["source"] if self.doc else ""
        self._anc: dict[tuple[str, str], bool] = {}
        self._trees: dict[str, str | None] = {}
        self.replays: list[str] = []

    # git, cached
    def anc(self, older: str, newer: str) -> bool:
        key = (older, newer)
        if key not in self._anc:
            try:
                self._anc[key] = self.t.is_ancestor(self.repo, older, newer, self.s)
            except self.t.GitError:
                self._anc[key] = False
        return self._anc[key]

    def tree(self, rev: str) -> str | None:
        if rev not in self._trees:
            self._trees[rev] = self.t.tree_of(self.repo, rev, self.s)
        return self._trees[rev]

    def changed(self, a: str, b: str) -> list[str]:
        return self.t.changed(self.repo, a, b, self.s)

    def commit_of(self, attempt: str) -> str | None:
        result = (self.att.get(attempt) or {}).get("result") or {}
        return result.get("head") if result.get("status") == "completed" else None

    # the whole gate
    def run(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "green_seen": (ev.records(self.st, "green") or [{}])[-1].get("id"),
            "results_seen": len(ev.completed(self.st)), "assessed_at": now_iso(),
            "units": {}, "integration": {}, "applicability": [], "unattributed": [],
        }
        if self.doc is None:
            empty = _task_list(self.st) == []
            reason = "task_set_empty" if empty else "plan_tasks_unusable"
            return {**base, "status": "failed", "reasons": [reason], "head": None, "green": None, "heads": []}
        ws = self.doc["workspace"]
        head = self.t.rev_parse(self.repo, f"refs/heads/{ws['branch']}", self.s)
        if head is None:
            raise Rejected("head_unreadable", 3, branch=ws["branch"])
        self.h = head
        prior = (self.st.get("gates") or {}).get("g1") or {}
        recorded = _unique([*prior.get("heads", []), *(g["head"] for g in ev.records(self.st, "green"))])
        base |= {"head": head, "heads": _unique([*recorded, head])}
        units = [f"task:{t['id']}" for t in self.doc["tasks"]] + self._batch_units()
        rewritten = [r for r in recorded if not self.anc(r, head)]
        if rewritten:  # every lineage-based Red eligibility is void (design §7)
            base["units"] = {u: {"status": "blocked", "reasons": ["history_rewritten"], "red": None, "reds": {},
                                 "via": None, "invalid": {}} for u in units}
            reasons = [f"history_rewritten:{r}" for r in rewritten]
            return {**base, "status": "blocked", "reasons": reasons, "green": None}

        self.eligible = {a: c for a in self.asg if (c := self.commit_of(a)) and self.anc(c, head)}
        base["integration"] = {a: self._integration(a) for a in sorted(self.eligible)
                               if self.asg[a].get("integration")}
        self.integration = base["integration"]
        statuses, reasons = [], []
        green, status, why = self._green()
        base["green"] = green
        statuses.append(status)
        reasons += why
        for unit in units:
            result = self._unit(unit)
            base["units"][unit] = result
            statuses.append(result["status"])
            if result["status"] != "passed":
                reasons += result["reasons"]
        status, why = self._unattributed(base)
        statuses.append(status)
        reasons += why
        return {**base, "status": worst(statuses), "reasons": _unique(reasons)}

    def _batch_units(self) -> list[str]:
        found: dict[str, list[str]] = {}
        for asg in self.asg.values():
            if asg.get("batch_id"):
                found.setdefault(asg["batch_id"], [])
                found[asg["batch_id"]] += [f for f in asg.get("finding_ids", []) if f not in found[asg["batch_id"]]]
        return [f"batch:{b}:{f}" for b in sorted(found) for f in found[b]]

    # Green at H
    def _green(self) -> tuple[str | None, str, list[str]]:
        at_h = [g for g in ev.records(self.st, "green") if g["head"] == self.h]
        if not at_h:
            return None, "pending", [f"green_missing:{self.h}"]
        g = at_h[-1]
        if g["status"] == "running":
            return g["id"], "pending", [f"green_running:{g['id']}"]
        if g.get("checkout_head") != self.h:
            return g["id"], "failed", ["green_head_mismatch"]
        if g["status"] == "passed":
            return g["id"], "passed", []
        if g["status"] == "test_failed":
            return g["id"], "failed", ["integration_regression"]
        if g["status"] == "evidence_timeout":
            return g["id"], "failed", [f"evidence_timeout:{g['id']}"]
        return g["id"], "failed", [f"green_{g['status']}"]

    # units
    def _attempts_of(self, unit: str) -> list[str]:
        kind, _, rest = unit.partition(":")
        if kind == "task":
            return [a for a, x in self.asg.items() if not x.get("batch_id") and x.get("task_id") == rest]
        batch = rest.split(":", 1)[0]
        return [a for a, x in self.asg.items() if x.get("batch_id") == batch]

    def _reds_of(self, unit: str) -> list[dict[str, Any]]:
        kind, _, rest = unit.partition(":")
        out = []
        for r in ev.records(self.st, "red"):
            owner = self.asg.get(str(r.get("attempt"))) or {}
            if kind == "task":
                claims = not r.get("batch_id") and r.get("task_id") == rest
                if claims or (not owner.get("batch_id") and owner.get("task_id") == rest):
                    out.append(r)
            else:
                batch, finding = rest.split(":", 1)
                if finding in r.get("finding_ids", []) and batch in (r.get("batch_id"), owner.get("batch_id")):
                    out.append(r)
        return out

    def _covering(self, unit: str) -> list[str]:
        """The eligible attempts this unit answers for: a task's attempts, or the batch's attempts
        that list the finding (an attempt listing no finding answers for every one)."""
        kind, _, rest = unit.partition(":")
        found = [a for a in self._attempts_of(unit) if a in self.eligible]
        if kind == "task":
            return found
        finding = rest.split(":", 1)[1]
        return [a for a in found if finding in (self.asg[a].get("finding_ids") or [finding])]

    def _pure_import(self, attempt: str) -> bool:
        c = self.integration.get(attempt)
        return c is not None and not (c["author"]["conflict"] or c["author"]["additional"])

    def _unit(self, unit: str) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "passed", "reasons": [], "red": None, "reds": {}, "via": None,
                               "invalid": {}}
        eligible = [a for a in self._attempts_of(unit) if a in self.eligible]
        rejected = [(a, c) for a in eligible if (c := self.integration.get(a)) and c["status"] != "ok"]
        if rejected:
            for a, c in rejected:
                out["reasons"] += [f"integration_rejected:{a}:{r}" for r in c["rejected"]]
                out["reasons"] += [f"integration_scope_exceeded:{a}:{p}" for p in c["exceeded"]]
            out["status"] = "blocked" if any(c["exceeded"] for _, c in rejected) else "failed"
            return out
        for r in self._reds_of(unit):
            why = self._check_red(r)
            if why:
                out["invalid"][r["id"]] = why
            else:  # an eligible Red is its own attempt's; the first one per attempt is judged
                out["reds"].setdefault(str(r["attempt"]), r["id"])
        out["red"] = next(iter(out["reds"].values()), None)
        invalid = [f"red_invalid:{rid}:{w}" for rid, whys in out["invalid"].items() for w in whys]
        unavailable = {**out, "status": "blocked", "reasons": [f"original_red_unavailable:{unit}", *invalid]}
        # each attempt the unit answers for needs its own Red or its own exemption (design §7)
        covering = self._covering(unit)
        bare = {a for a in covering if a not in out["reds"] and not self._pure_import(a)}
        via = "red" if out["reds"] else "import"  # a pure import needs no Red for upstream behaviour
        if bare or not covering:
            na = self._na(unit, covering)
            if na is None:
                return unavailable
            status, reasons, judged = na
            if status != "passed":
                return {**out, "status": status, "reasons": [*reasons, *invalid]}
            if not bare <= {judged}:
                return unavailable
            via = "red" if out["reds"] else "na"
        verdicts = {rid: self._contradiction(rid) for rid in out["reds"].values()}
        out["reds"] = {a: rid for a, rid in out["reds"].items() if verdicts[rid][0] != "blocked"}
        out["red"] = next(iter(out["reds"].values()), None)
        status = worst([s for s, _ in verdicts.values()])
        reasons = [x for _, why in verdicts.values() for x in why]
        if status == "blocked":
            return {**out, "status": status, "reasons": [*reasons, f"original_red_unavailable:{unit}", *invalid]}
        return {**out, "status": status, "reasons": reasons, "via": via}

    def _contradiction(self, rid: str) -> tuple[str, list[str]]:
        """Whether contradictory evidence leaves this Red standing (design §7: replay once)."""
        r = self.evidence[rid]
        tree = r["snapshot"]["tree"]
        failing = set(r["failing"])
        others = [e for e in self.evidence.values() if e["id"] != rid and e["kind"] in ("red", "green")
                  and failing & set(e.get("passing") or [])]
        if not any((e["snapshot"]["tree"] if e["kind"] == "red" else self.tree(e["head"])) == tree for e in others):
            return "passed", []
        runs = [e for e in ev.records(self.st, "replay") if e.get("of") == rid and "reproduced" in e]
        if not runs:
            self.replays.append(rid)
            return "pending", [f"replay_pending:{rid}"]
        if runs[-1]["reproduced"]:
            return "passed", []
        return "blocked", [f"red_contradicted:{rid}"]

    def _check_red(self, r: dict[str, Any]) -> list[str]:
        """Every reason this Red is not an eligible original Red (empty: eligible)."""
        why = [] if r.get("producer") == ev.producer("evidence red") else ["producer"]
        junit = self._raw(r, why)
        if r.get("status") != "test_failed":
            return [*why, f"not_a_red:{r.get('status')}"]
        derived = ev.classify(r.get("exit"), junit)
        if derived["status"] != "test_failed" or derived["failing"] != r.get("failing"):
            why.append("exit")
        asg = self.asg.get(str(r.get("attempt")))
        if asg is None:
            return [*why, "provenance:attempt"]
        for field, ok in (
            ("task", r.get("task_id") == asg.get("task_id")),
            ("batch", r.get("batch_id") == asg.get("batch_id")),
            ("finding", set(r.get("finding_ids", [])) <= set(asg.get("finding_ids", []))),
            ("worktree", Path(str(r.get("worktree"))).resolve() == Path(asg["worktree"]).resolve()),
        ):
            if not ok:
                why.append(f"provenance:{field}")
        snap = r.get("snapshot") or {}
        if not self._snapshot_ok(snap):
            return [*why, "snapshot"]
        c = self.commit_of(r["attempt"])
        if c is None:
            return [*why, "attempt_abandoned"]
        if r["attempt"] not in self.eligible:
            why.append("attempt_not_ancestor")
        why += self._scope(r, asg, c)
        if not self._mapped(r, asg, c):
            why.append("unmapped")
        return why

    def _raw(self, r: dict[str, Any], why: list[str]) -> str | None:
        """Each raw object must exist and match its recorded digest; returns the junit text."""
        pairs = {k: ((r.get("raw") or {}).get(k), (r.get("raw_digest") or {}).get(k)) for k in ("stdout", "stderr")}
        pairs["junit"] = (r.get("junit"), r.get("junit_digest"))
        texts: dict[str, bytes] = {}
        for name, (ref, digest) in pairs.items():
            if name == "junit" and ref is None and digest is None:
                continue
            try:
                data = store.get_object(ref[store.OBJECT_KEY])  # type: ignore[index]
            except (TypeError, KeyError, store.StoreError):
                data = None
            if data is None or store.digest(data) != digest:
                if "raw" not in why:
                    why.append("raw")
                continue
            texts[name] = data
        return texts["junit"].decode(errors="replace") if "junit" in texts else None

    def _snapshot_ok(self, snap: dict[str, Any]) -> bool:
        commit_, parent = snap.get("commit"), snap.get("parent")
        if not (commit_ and parent and snap.get("tree") and snap.get("ref")):
            return False
        if self.t.rev_parse(self.repo, snap["ref"], self.s) != commit_ or self.tree(commit_) != snap["tree"]:
            return False
        return commit_ == parent or self.t.parents(self.repo, commit_, self.s) == [parent]

    def _scope(self, r: dict[str, Any], asg: dict[str, Any], c: str) -> list[str]:
        snap = r["snapshot"]["commit"]
        paths = self.changed(asg["head"], snap)
        check = self.integration.get(r["attempt"])
        if check is not None:  # integration: verified imports are not author edits
            paths = [p for p in paths if not self._imported(check, snap, p)]
        else:  # every commit of the range, so an out-of-scope change reverted later still counts
            paths += self.changed(asg["head"], c) + self.t.range_changed(self.repo, asg["head"], c, self.s)
        return [f"scope:{p}" for p in _unique(sorted(paths)) if not in_scope(p, asg["scope"])]

    def _imported(self, check: dict[str, Any], rev: str, path: str) -> bool:
        return bool(check.get("auto_tree")) and (
            self.t.blob(self.repo, rev, path, self.s) == self.t.blob(self.repo, check["auto_tree"], path, self.s)
        )

    def _mapped(self, r: dict[str, Any], asg: dict[str, Any], c: str) -> bool:
        snap, start = r["snapshot"]["commit"], asg["head"]
        if self.anc(snap, c) and not self.anc(snap, start):
            return True  # the snapshot is in the attempt's own history
        modules = {f.split("::", 1)[0] for f in r["failing"]}
        for path in self.changed(start, snap):
            if not path.endswith(".py"):
                continue
            module = path[:-3].replace("/", ".")
            if not any(m == module or m.startswith(module + ".") for m in modules):
                continue
            new, final = self.t.show(self.repo, snap, path, self.s), self.t.show(self.repo, c, path, self.s)
            if new is None or final is None:
                continue
            delta = ev.added_lines(self.t.show(self.repo, start, path, self.s) or "", new)
            if delta and delta <= {line.rstrip() for line in final.splitlines()}:
                return True
        return False

    # integration attempts (design §8)
    def _integration(self, attempt: str) -> dict[str, Any]:
        asg, c = self.asg[attempt], self.eligible[attempt]
        pinned_h, pinned_b = asg["integration"]["head"], asg["integration"]["base_tip"]
        out: dict[str, Any] = {"status": "ok", "rejected": [], "exceeded": [], "parents": [], "auto_tree": None,
                               "conflicts": [], "imported": [], "author": {"conflict": [], "additional": []}}
        out["parents"] = self.t.parents(self.repo, c, self.s)
        if out["parents"] != [pinned_h, pinned_b]:
            return {**out, "status": "rejected", "rejected": ["parents"]}
        auto, conflicts = self.t.merge_tree(self.repo, pinned_h, pinned_b, self.s)
        edits = set(self.changed(auto, c))  # differs from the automatic merge: the author's
        base_changed = set(self.changed(self.t.merge_base(self.repo, pinned_h, pinned_b, self.s), pinned_b))
        additional = sorted(edits - set(conflicts))
        # both kinds of author edit must stay in the scope; a conflict path is not in it by itself
        outside = [p for p in sorted(edits) if not in_scope(p, asg["scope"])]
        hidden = [p for p in outside if p in additional and p in base_changed]
        out |= {
            "auto_tree": auto, "conflicts": conflicts,
            "imported": sorted(set(self.changed(pinned_h, auto)) - edits),
            "author": {"conflict": sorted(edits & set(conflicts)), "additional": additional},
            "rejected": [f"hidden_edit:{p}" for p in hidden],
            "exceeded": [p for p in outside if p not in hidden],  # resolving needs more scope: back to D11
        }
        out["status"] = "scope_exceeded" if out["exceeded"] else "rejected" if out["rejected"] else "ok"
        return out

    # N/A (design §7; the same independence checks as G2)
    def _na(self, unit: str, covering: list[str]) -> tuple[str, list[str], str] | None:
        """The N/A record's verdict for this unit and the one attempt it judged. A batch record
        applies only to the findings its attempt lists."""
        kind, _, rest = unit.partition(":")
        key = f"task:{rest}" if kind == "task" else f"batch:{rest.split(':', 1)[0]}"
        rec = (self.st.get("na") or {}).get(key)
        if rec is None:
            return None
        judged = str(rec.get("attempt"))
        if judged in self.eligible and judged in self._attempts_of(unit) and judged not in covering:
            return None  # an eligible attempt of the batch that answers for other findings
        reviewer = rec.get("reviewer") or {}
        if reviewer.get("role") != "reviewer":
            return "failed", [f"na_self_declared:{unit}"], judged
        if rec.get("status") == "pending":
            return "pending", [f"na_pending:{unit}"], judged
        found: list[tuple[str, str]] = []
        approved = ((self.pol.get("profiles") or {}).get("reviewer") or {}).get("model")
        if not approved or reviewer.get("model") != approved:
            found.append(("failed", f"na_model_mismatch:{unit}"))
        models = {(x.get("profile") or {}).get("model") for x in self.asg.values()}
        sessions = {(a.get("handle") or {}).get("native_session_id") for a in self.att.values()} - {None}
        if reviewer.get("model") in models or reviewer.get("native_session_id") in sessions:
            found.append(("failed", f"na_not_independent:{unit}"))
        if reviewer.get("capability") != "verified":
            found.append(("failed", f"na_capability_unverified:{unit}"))
        if rec.get("status") == "rejected" or rec.get("behavior_change"):
            found += [("blocked", f"na_rejected:{unit}"), ("blocked", f"original_red_unavailable:{unit}")]
        elif rec.get("status") != "accepted":
            found.append(("failed", f"na_status:{unit}:{rec.get('status')}"))
        if judged not in covering or rec.get("head") != self.eligible.get(judged):
            found.append(("failed", f"na_diff_mismatch:{unit}"))
        if not found:
            return "passed", [], judged
        return worst([s for s, _ in found]), [r for _, r in found], judged

    # commits of H that no eligible attempt made (G05: documentation after the code)
    def _unattributed(self, base: dict[str, Any]) -> tuple[str, list[str]]:
        started = sorted((a["n"], k) for k, a in self.att.items() if k in self.asg)
        if not started:
            return "passed", []
        start = self.asg[started[0][1]]["head"]
        ours: set[str] = set()
        for a, c in self.eligible.items():
            ours |= set(self.t.rev_list(self.repo, [c], [self.asg[a]["head"]], self.s))
        others = [c for c in reversed(self.t.rev_list(self.repo, [self.h], [start], self.s)) if c not in ours]
        if not others:
            return "passed", []
        paths = _unique([p for c in others for p in self.changed(self.t.parents(self.repo, c, self.s)[0], c)])
        base["unattributed"] = [{"commit": c} for c in others]
        if all(in_scope(p, list(DOCS)) for p in paths):
            base["applicability"].append({"reason": "docs_only", "commits": others, "paths": sorted(paths)})
            return "passed", []
        return "failed", [f"unattributed_change:{c}" for c in others]


def _blockers(g1: dict[str, Any]) -> list[str]:
    out = []
    for reason in g1["reasons"]:
        if reason.startswith("history_rewritten"):
            out.append("history_rewritten")
        elif reason.startswith("integration_scope_exceeded:"):
            out.append(":".join(reason.split(":")[:2]))
        elif reason.startswith(("original_red_unavailable:", "red_contradicted:")):
            out.append(reason)
    return _unique(out)


def assess(feature: str, token: str | None) -> dict[str, Any]:
    _, st = owned(feature, token)
    pol = ev.bound_policy(st)
    g1 = _G1(st, pol)
    result = g1.run()
    if g1.replays:  # contradictory evidence: diagnose once, then judge again
        for red_id in _unique(g1.replays):
            ev.replay(feature, red_id)
        _, st = store.load(feature)
        result = _G1(st, pol).run()
    blockers = _blockers(result)

    def record(s: State) -> State:
        s.setdefault("gates", {})["g1"] = result
        s["blockers"] = [b for b in s.get("blockers", []) if not b.startswith(G1_BLOCKERS)]
        for b in blockers:
            block(s, b)
        return s

    commit(feature, f"assess:g1@{result['assessed_at']}:{result.get('head')}:{secrets.token_hex(6)}", record)
    if result["status"] == "blocked":
        raise Rejected("g1_blocked", 3, g1=result)
    return {"g1": result}


# --- T6.1: G1 passed → push → pr_ensure → observe pr / ci → G3 --------------------------------
#
# State (fields owned here): pr (identity, written by writes on pr_ensure success), gates.g3,
# integration_required {key: {key, base, base_tip, head, sources, status}}, g1_binding {head,
# base, green, assessed_at, contract, pending, history}, and `ci_wait` activities.

ACTIONS_APP = "github-actions"
ACTIONS_APP_ID = 15368  # the GitHub Actions app, as branch rules name it (integration_id)
APPROVED_POLICY_REPO = "yschiang/loop-engineering"  # D49: the one repo whose approved policy may stand in
FAILED = ("failure", "cancelled", "timed_out", "stale", "action_required", "startup_failure")
EXEMPTABLE = ("skipped", "neutral")  # the only conclusions an exception may cover
G3_ORDER = ("passed", "failed", "pending", "unknown")


def controller_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("loopctl")
    except metadata.PackageNotFoundError:
        return "unknown"


def contract(state: State) -> dict[str, Any]:
    """What a G1 / G3 result is bound to besides H and the base (design §8 version table)."""
    return {"approval": (state.get("approval") or {}).get("decision"),
            "policy": ((state.get("versions") or {}).get("policy") or {}).get("digest"),
            "controller": controller_version()}


def github_workspace(state: State) -> dict[str, Any] | None:
    """The plan workspace plus its declared push `remote`; None when the plan declares none."""
    doc = assignments.plan_doc(state)
    if doc is None:
        return None
    match = assignments.PLAN_BLOCK.search(store.get_object(state["plan"]["content"][store.OBJECT_KEY]).decode(errors="replace"))
    try:
        raw = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        return None
    remote = ((raw.get("workspace") or {}) if isinstance(raw, dict) else {}).get("remote")
    if not isinstance(remote, str) or not remote:
        return None
    return {**doc["workspace"], "remote": remote}


def registered_policy(state: State) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(content, registration) of the registered policy only; G3 never reads a cwd file."""
    entry = (state.get("versions") or {}).get("policy")
    if not entry or not entry.get("content"):
        return None, entry
    try:
        doc = yaml.safe_load(store.get_object(entry["content"][store.OBJECT_KEY]))
    except (yaml.YAMLError, store.StoreError):
        return None, entry
    return (doc if isinstance(doc, dict) else None), entry


def _g3_policy(pol: dict[str, Any] | None) -> dict[str, Any]:
    g3 = (pol or {}).get("g3")
    return g3 if isinstance(g3, dict) else {}


def _passed_head(state: State) -> str | None:
    g1 = (state.get("gates") or {}).get("g1") or {}
    return g1.get("head") if g1.get("status") == "passed" else None


def github_target(state: State) -> dict[str, Any]:
    pol, _ = registered_policy(state)
    g3p, ws, pr = _g3_policy(pol), github_workspace(state), state.get("pr")
    names = [str(c["name"]) for c in g3p.get("required_checks") or [] if isinstance(c, dict) and c.get("name")]
    return {"repo": state.get("repo"), "head": _passed_head(state), "pr": pr, "workflow": g3p.get("workflow"),
            "names": names, "source": (ws or {}).get("source"),
            "base_branch": (pr or {}).get("base_branch") or (ws or {}).get("base")}


def current_pr(state: State) -> dict[str, Any] | None:
    pr = state.get("pr")
    return current(state, f"pr:{pr['number']}", "pr") if pr else None


def _pr_fact(state: State) -> dict[str, Any] | None:
    found = current_pr(state)
    return found["fact"] if found and found["fact"].get("found") else None


def current_ci(state: State, head: str) -> dict[str, Any] | None:
    return current(state, f"ci:{state.get('repo')}:{head}", "ci")


def observation_context(state: State) -> dict[str, Any]:
    """Saved with each pr / ci fact: a G3 result is only current for the same contract and base."""
    pf = _pr_fact(state)
    return {"contract": contract(state), "base": pf["base"]["sha"] if pf else None}


def open_integration(state: State, head: str) -> list[str]:
    return sorted(k for k, e in (state.get("integration_required") or {}).items()
                  if e["head"] == head and e.get("status", "open") == "open")


def _approving(state: State, entry: dict[str, Any] | None) -> str | None:
    """The latest human policy_change bound to this registration's locator and digest."""
    if not entry:
        return None
    found = [d for d in (state.get("decisions") or {}).values() if d["kind"] == "policy_change"
             and (d["target"], d["version"]) == (entry.get("locator"), entry.get("digest"))]
    return max(found, key=lambda d: d["seq"])["id"] if found else None


def _decision_kind(state: State, decision: Any) -> str | None:
    return ((state.get("decisions") or {}).get(str(decision)) or {}).get("kind") if decision else None


# --- G3 (pure) ----------------------------------------------------------------------------


def _policy_source(state: State, rules: dict[str, Any], pol: dict[str, Any] | None,
                   entry: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Design §8 source order: readable repo rules; else (403/404) the approved policy of
    yschiang/loop-engineering only; else unknown."""
    source: dict[str, Any] = {"kind": None, "github_rules_verified": None, "policy_locator": (entry or {}).get("locator"),
                              "policy_digest": (entry or {}).get("digest"), "policy_change": _approving(state, entry),
                              "required": []}
    if pol is None:
        return source, ["policy_not_registered"]
    if rules.get("status") == "readable":
        checks = rules.get("required") or []
        source |= {"kind": "rules", "github_rules_verified": True,
                   "required": _unique([str(c["context"]) for c in checks])}
        return source, [f"required_check_app_unsupported:{c['context']}" for c in checks
                        if c.get("integration_id") not in (None, ACTIONS_APP_ID)]
    source |= {"kind": "approved_policy", "github_rules_verified": False}
    if state.get("repo") != APPROVED_POLICY_REPO:
        return source, ["rules_unreadable_other_repo"]
    if pol.get("repo") != state.get("repo"):
        return source, ["policy_repo_mismatch"]
    if source["policy_change"] is None:
        earlier = [d for d in (state.get("decisions") or {}).values()
                   if d["kind"] == "policy_change" and d["target"] == (entry or {}).get("locator")]
        return source, ["policy_digest_mismatch" if earlier else "policy_not_approved"]
    checks = _g3_policy(pol).get("required_checks") or []
    source["required"] = _unique([str(c["name"]) for c in checks if isinstance(c, dict) and c.get("name")])
    return source, [f"required_check_app_unsupported:{c.get('name') if isinstance(c, dict) else c}" for c in checks
                    if not isinstance(c, dict) or c.get("app", ACTIONS_APP) != ACTIONS_APP]


def _valid_exception(state: State, e: Any) -> bool:
    """A named check, skipped / neutral only, bound to a recorded policy_change decision."""
    return isinstance(e, dict) and isinstance(e.get("check"), str) and bool(e["check"]) \
        and e.get("conclusion") in EXEMPTABLE and _decision_kind(state, e.get("decision")) == "policy_change"


def _policy_content(state: State, g3p: dict[str, Any], ci: dict[str, Any], pf: dict[str, Any] | None,
                    source: dict[str, Any]) -> list[str]:
    if not g3p:
        return ["policy_invalid:g3_missing"]
    why = [] if g3p.get("source") == "head" else ["policy_invalid:source"]  # first slice: head only
    why += [] if g3p.get("trigger_event") == "pull_request" else ["policy_invalid:trigger_event"]
    if not g3p.get("workflow"):
        why.append("policy_invalid:workflow")
    elif ci.get("workflow_blob") != g3p.get("workflow_blob_sha"):
        why.append("workflow_digest_mismatch")  # the CI workflow at H is not the approved one
    if pf is not None and pf["base"]["ref"] != g3p.get("base_branch"):
        why.append("base_branch_not_in_policy")
    for e in g3p.get("exceptions") or []:
        if not _valid_exception(state, e):
            why.append(f"policy_invalid:exception:{e.get('check') if isinstance(e, dict) else e}")
    if not source["required"]:
        why.append("required_set_empty")
    return why


def _tested(r: dict[str, Any], name: str, head: str) -> tuple[str, str | None, str | None]:
    """The job's own tested-SHA artifact of this run attempt, compared field by field."""
    found = (r.get("tested") or {}).get(f"tested-sha-{name}-{r['run_attempt']}")
    run_ref = f"{name}:{r['id']}"
    if found is None:
        return "unknown", f"tested_sha_missing:{run_ref}", None
    content = found.get("content")
    if not isinstance(content, dict):
        return "unknown", f"tested_sha_unreadable:{run_ref}", None
    for field, want in (("run_id", str(r["id"])), ("run_attempt", str(r["run_attempt"])), ("job", name),
                        ("check_name", name)):
        if str(content.get(field)) != want:
            return "unknown", f"tested_sha_mismatch:{field}:{run_ref}", content.get("tested_sha")
    if content.get("tested_sha") != head:
        return "unknown", f"unsupported_integration_source:{run_ref}", content.get("tested_sha")
    return "passed", None, head


def _check_run(r: dict[str, Any], j: dict[str, Any], name: str, head: str,
               ci: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The job's own check-run (the one its check_run_url names) and the first identity field
    that does not match (design §8): app github-actions, the job / check name, head_sha H, and
    the run's check suite, which carries the run's workflow path, event and PR."""
    wanted = str(j.get("check_run_url") or "").rsplit("/", 1)[-1]
    found = [c for c in ci.get("check_runs") or [] if wanted and str(c.get("id")) == wanted]
    run_ref = f"{name}:{r['id']}"
    if len(found) != 1:
        return None, f"check_run_missing:{run_ref}"
    c = found[0]
    for field, want in (("app", ACTIONS_APP), ("name", name), ("head_sha", head), ("check_suite", r.get("check_suite_id"))):
        if want is None or c.get(field) != want:
            return c, f"check_run_mismatch:{field}:{run_ref}"
    return c, None


def _check(name: str, runs: list[dict[str, Any]], ci: dict[str, Any], head: str,
           exceptions: dict[tuple[str, str], str]) -> dict[str, Any]:
    """One required check over every candidate run of H, each at its latest attempt."""
    if not runs:
        if any(s.get("context") == name for s in ci.get("statuses") or []):
            return {"status": "unknown", "reasons": [f"commit_status_only:{name}"], "runs": []}
        return {"status": "pending", "reasons": [f"missing:{name}"], "runs": []}
    marks: list[tuple[str, str]] = []
    records = []
    for r in sorted(runs, key=lambda r: (r["run_number"] is None, r["run_number"] or 0)):
        jobs = [j for j in r.get("jobs") or [] if j["name"] == name]
        if len(jobs) != 1:
            if jobs:
                marks.append(("unknown", f"ambiguous_job:{name}:{r['id']}"))
            else:
                marks.append(("pending" if r["status"] != "completed" else "unknown", f"missing:{name}:run:{r['id']}"))
            continue
        j = jobs[0]
        rec = {"name": name, "app": ACTIONS_APP, "workflow": r["path"], "run_id": r["id"], "run_attempt": r["run_attempt"],
               "run_number": r["run_number"], "event": r["event"], "head_sha": r["head_sha"], "status": j["status"],
               "conclusion": j["conclusion"], "url": j.get("html_url"), "check_run_id": None, "tested_sha": None,
               "via": None}
        records.append(rec)
        run_ref = f"{name}:{r['id']}"
        counts = j["status"] == "completed" and (
            j["conclusion"] == "success" or (j["conclusion"] in EXEMPTABLE and (name, j["conclusion"]) in exceptions))
        check_run, mismatch = _check_run(r, j, name, head, ci) if counts else (None, None)
        if check_run is not None and mismatch is None:
            rec["check_run_id"] = check_run["id"]
        if not j.get("html_url"):
            marks.append(("unknown", f"check_url_missing:{run_ref}"))
        elif j["status"] != "completed":
            marks.append(("pending", f"pending:{run_ref}"))
        elif mismatch:  # a job counts only through its own GitHub Actions check-run
            marks.append(("unknown", mismatch))
        elif j["conclusion"] == "success":
            status, why, rec["tested_sha"] = _tested(r, name, head)
            if why:
                marks.append((status, why))
            else:
                rec["via"] = "tested_sha"
        elif j["conclusion"] in EXEMPTABLE and (name, j["conclusion"]) in exceptions:
            rec["via"] = {"exception": exceptions[(name, j["conclusion"])], "conclusion": j["conclusion"]}
        elif j["conclusion"] in (*FAILED, *EXEMPTABLE):
            marks.append(("failed", f"{j['conclusion']}:{run_ref}"))
        else:
            marks.append(("unknown", f"conclusion_unknown:{run_ref}"))
    status = max((s for s, _ in marks), key=G3_ORDER.index) if marks else "passed"
    return {"status": status, "reasons": [w for _, w in marks], "runs": records}


def evaluate_g3(state: State, at: str) -> dict[str, Any]:
    """G3 at the head G1 passed (design §8): policy source, head only, event / PR identity, the
    latest attempt of every PR run of H, each job's tested-SHA artifact, no exceptions but
    skipped / neutral with a policy_change decision, and mergeable known."""
    head = str(_passed_head(state))
    pr, prev = state.get("pr"), (state.get("gates") or {}).get("g3") or {}
    same = prev.get("head") == head
    out: dict[str, Any] = {
        "status": "pending", "reasons": [], "head": head, "base": None, "source": prev.get("source") if same else None,
        "checks": {}, "ignored": [], "applicability": list(prev.get("applicability") or []) if same else [],
        "pr_seq": None, "ci_seq": None, "contract": contract(state), "policy_blockers": [], "evaluated_at": at,
        # every required check terminal and mergeable known: the CI wait is over (design §10)
        "ci_terminal": False,
        "decisions_seen": max((d["seq"] for d in (state.get("decisions") or {}).values()), default=0),
        # the policy digest G3 was judged under; another digest needs its own policy_change
        "policy_accepted": prev.get("policy_accepted"),
    }

    def done(status: str, reasons: list[str], policy: bool = False) -> dict[str, Any]:
        out["status"], out["reasons"] = status, _unique(reasons) if status != "passed" else []
        out["policy_blockers"] = [f"g3_policy:{r}" for r in out["reasons"]] if policy else []
        return out

    if pr is None:
        return done("pending", ["pr_identity_missing"])
    found, pf = current_pr(state), _pr_fact(state)
    if pf is not None:
        out["pr_seq"], out["base"] = found["seq"], pf["base"]["sha"]  # type: ignore[index]
        if same and prev.get("base") and out["base"] != prev["base"]:  # base moved, H did not (AC-G17)
            moved = {"reason": "head_only_h_unchanged", "head": head, "base_from": prev["base"], "base_to": out["base"]}
            if moved not in out["applicability"]:
                out["applicability"].append(moved)
    cif = current_ci(state, head)
    if cif is None:
        return done("pending", ["ci_not_observed"])
    ci, out["ci_seq"] = cif["fact"], cif["seq"]
    if ci.get("context") != {"contract": out["contract"], "base": out["base"]}:
        return done("pending", ["ci_observation_stale"])  # read before a contract / base change: observe again
    pol, entry = registered_policy(state)
    source, why = _policy_source(state, ci.get("rules") or {}, pol, entry)
    out["source"] = source
    if why:
        return done("unknown", why, policy=True)
    g3p = _g3_policy(pol)
    accepted = out["policy_accepted"] or source["policy_digest"]
    if source["policy_digest"] != accepted and source["policy_change"] is None:
        return done("unknown", ["policy_change_required"], policy=True)  # never passed by a policy change alone
    out["policy_accepted"] = source["policy_digest"]
    why = _policy_content(state, g3p, ci, pf, source)
    if why:
        return done("unknown", why, policy=True)
    wf, required = g3p["workflow"], source["required"]
    runs = [r for r in ci.get("runs") or [] if r["path"] == wf and r["head_sha"] == head]
    out["ignored"] = [{"run_id": r["id"], "path": r["path"]} for r in ci.get("runs") or []
                      if r["path"] != wf and r["head_sha"] == head]
    out["ignored"] += [{"name": c["name"], "app": c["app"]} for c in ci.get("check_runs") or []
                       if c["name"] in required and c["app"] != ACTIONS_APP]
    exceptions = {(e["check"], e["conclusion"]): str(e["decision"]) for e in g3p.get("exceptions") or []
                  if _valid_exception(state, e)}
    results = {name: _check(name, runs, ci, head, exceptions) for name in required}
    mergeable = pf.get("mergeable") if pf is not None else None
    # a conflicting PR without a run gets no pull_request run: there is nothing to wait for
    out["ci_terminal"] = (not runs and mergeable is False) or (
        pf is not None and pf["head"]["sha"] == head and mergeable is not None
        and all(c["status"] != "pending" for c in results.values()))
    unknown = [f"run_identity_missing:{r['id']}" for r in runs
               if r["id"] is None or r["run_number"] is None or r["run_attempt"] is None]
    numbers = [r["run_number"] for r in runs if r["run_number"] is not None]
    unknown += [f"duplicate_run_number:{n}" for n in sorted(set(numbers)) if numbers.count(n) > 1]
    unknown += [f"unexpected_event_context:{r['id']}" for r in runs
                if r["event"] != "pull_request" or r["pull_requests"] != [pr["number"]]]
    if unknown:
        return done("unknown", unknown)
    if not runs and mergeable is False:
        return done("unknown", ["ci_unavailable_conflict"])  # a conflicting PR gets no pull_request run
    statuses, reasons = [], []
    for name, result in results.items():
        out["checks"][name] = result
        statuses.append(result["status"])
        reasons += result["reasons"]
    if pf is None:
        statuses, reasons = [*statuses, "pending"], [*reasons, "pr_not_observed"]
    else:
        if pf["head"]["sha"] != head:
            statuses, reasons = [*statuses, "pending"], [*reasons, f"pr_head_differs:{pf['head']['sha']}"]
        if mergeable is None:  # still being computed: waits inside the CI window (T7.1 times it out)
            statuses, reasons = [*statuses, "pending"], [*reasons, "mergeable_unknown"]
    return done(max(statuses, key=G3_ORDER.index), reasons)


# --- effects of a pr / ci observation (the mutate of its commit; deterministic) ----------------


def _check_pr_identity(st: State) -> None:
    """A PR whose head or base repo / branch moved is Blocked, never re-bound (design §4)."""
    pr, found = st["pr"], current_pr(st)
    fact = found["fact"] if found else {}
    if not fact.get("found"):
        block(st, f"pr_missing:{pr['number']}")
        return
    if fact.get("state") != "open":
        block(st, f"pr_not_open:{pr['number']}")
    for field, value in (("head_repo", fact["head"]["repo"]), ("head_branch", fact["head"]["ref"]),
                         ("base_repo", fact["base"]["repo"]), ("base_branch", fact["base"]["ref"])):
        if value != pr[field]:
            block(st, f"pr_identity_changed:{field}")


def _detect_integration(st: State, head: str) -> None:
    """Integration triggers (design §8): mergeable=false, a Reviewer finding marked
    `base_incompatible`, a human `revise` targeting `base_integration`. One entry per trigger
    key (base repo/branch, pinned base tip B, H); T5.1 creates the finding and the batch."""
    pr, pf = st.get("pr"), _pr_fact(st)
    if pr is None or pf is None:
        return
    required = st.setdefault("integration_required", {})
    base = f"{pr['base_repo']}:{pr['base_branch']}"

    def add(tip: str, at_head: str, source: str) -> None:
        key = f"base_integration:{base}:{tip}:{at_head}"
        entry = required.setdefault(key, {"key": key, "base": base, "base_tip": tip, "head": at_head,
                                          "sources": [], "status": "open"})
        if source not in entry["sources"]:
            entry["sources"].append(source)

    if pf.get("mergeable") is False:
        add(pf["base"]["sha"], pf["head"]["sha"], "mergeable_false")
    seen = {s for e in required.values() for s in e["sources"]}
    for fid in sorted(st.get("findings") or {}):
        f = st["findings"][fid]
        if f.get("base_incompatible") and f.get("status", "open") == "open" and f"finding:{fid}" not in seen:
            add(pf["base"]["sha"], head, f"finding:{fid}")
    for d in sorted((st.get("decisions") or {}).values(), key=lambda d: d["seq"]):
        if d["kind"] == "revise" and d["target"] == "base_integration" and f"decision:{d['id']}" not in seen:
            add(pf["base"]["sha"], head, f"decision:{d['id']}")


def rebind_satisfied(state: State, binding: dict[str, Any]) -> bool:
    """A passing Green at H itself, run after the base moved, is what G1 is now assessed with."""
    g1 = (state.get("gates") or {}).get("g1") or {}
    green = next((e for e in ev.records(state, "green") if e["id"] == g1.get("green")), None)
    return bool(g1.get("status") == "passed" and green and green["head"] == binding["head"]
                and green["status"] == "passed" and green["n"] > binding["pending"]["after_green"])


def _update_binding(st: State, head: str, at: str) -> None:
    """G1's binding to the base and the contract (design §8): a moved base without a trigger
    needs a Green at H itself (not a temporary merge), then the new base is bound."""
    g1, pf = st["gates"]["g1"], _pr_fact(st)
    if pf is None:
        return
    tip, now = pf["base"]["sha"], contract(st)
    b = st.get("g1_binding")
    if b is None or b["head"] != head:
        st["g1_binding"] = {"head": head, "base": tip, "green": g1.get("green"), "assessed_at": g1.get("assessed_at"),
                            "contract": now, "pending": None,
                            "history": [{"reason": "bound", "base": tip, "green": g1.get("green"), "at": at}]}
        return
    if b.get("pending") and rebind_satisfied(st, b):
        b.update(base=b["pending"]["base"], green=g1.get("green"), assessed_at=g1.get("assessed_at"), pending=None)
        b["history"].append({"reason": "base_rebound", "base": b["base"], "green": b["green"], "at": at})
    if b["contract"] != now and g1.get("assessed_at") != b["assessed_at"]:
        b.update(contract=now, green=g1.get("green"), assessed_at=g1.get("assessed_at"))
        b["history"].append({"reason": "reassessed", "contract": now, "green": b["green"], "at": at})
    if tip != b["base"] and pf.get("mergeable") is True and not open_integration(st, head):
        greens = [e["n"] for e in ev.records(st, "green")]
        if b.get("pending"):
            b["pending"]["base"] = tip
        else:
            b["pending"] = {"base": tip, "after_green": max(greens, default=0), "at": at}


def ci_wait_started(state: State, head: str) -> bool:
    return any(a.get("kind") == "ci_wait" and a.get("head") == head for a in state.get("activities") or [])


def start_ci_wait(st: State, head: str, at: str) -> State:
    """The CI wait (design §10) starts at the first `observe ci` after the push of H succeeded;
    its timeout is T7.1's."""
    push = (st.get("writes") or {}).get(writes.current_id(st, f"push.{head}"), {})
    if push.get("status") == "succeeded" and not ci_wait_started(st, head):
        st.setdefault("activities", []).append({"kind": "ci_wait", "head": head, "start": at, "end": None})
    return st


def after_github(source: str) -> Any:
    def after(st: State, outcome: str, at: str) -> None:
        head = _passed_head(st)
        if outcome != "fetched" or head is None:
            return
        if source == "pr":
            _check_pr_identity(st)
        _detect_integration(st, head)
        _update_binding(st, head, at)
        g3 = evaluate_g3(st, at)
        st.setdefault("gates", {})["g3"] = g3
        st["blockers"] = [b for b in st.get("blockers", []) if not b.startswith("g3_policy:")]
        for reason in g3["policy_blockers"]:
            block(st, reason)
        # only a terminal CI ends the wait: a G3 unknown for its policy has not judged the checks
        # yet (its window still bounds it, T7.1)
        if g3["ci_terminal"]:
            for a in st.get("activities") or []:
                if a.get("kind") == "ci_wait" and a.get("head") == head and not a["end"]:
                    a["end"] = at

    return after


# --- routing after G1 passed (pure) -------------------------------------------------------------


def _op_step(state: State, kind: str, op_id: str, now: datetime) -> dict[str, Any] | None:
    op_id = writes.current_id(state, op_id)  # an op of an earlier approval is superseded by a fresh one
    op = (state.get("writes") or {}).get(op_id)
    if op is None or (op["status"] in ("prepared", "failed") and not op.get("blocked")):
        return {"action": "write", "op": kind, "id": op_id}
    if op["status"] == "succeeded":
        return None
    if op["status"] == "in_flight":
        wait = max(1.0, (writes.stale_at(op) - now).total_seconds())
        return {"action": "wait", "poll_after_s": wait, "reason": f"write_in_flight:{op_id}"}
    if op.get("blocked") and op["blocked"] in writes.REFUSALS + ("retry_exhausted",):
        return human([f"{op['blocked']}:{op_id}"])  # the feature blocker normally comes first
    return human([f"write_unknown:{op_id}"], ["resolve_operation"])  # safety normally reads it back


def _observe_action(source: str, read_key: str) -> dict[str, Any]:
    return {"action": "observe", "source": source, "purpose": source, "read_key": read_key}


def _due(state: State, read_key: str, poll_s: float, now: datetime) -> float:
    last = ((state.get("read_budget") or {}).get(read_key) or {}).get("last_at")
    if last is None:
        return 0.0
    return max(0.0, (datetime.fromisoformat(last) + timedelta(seconds=poll_s) - now).total_seconds())


def github_route(state: State, now: datetime) -> dict[str, Any]:
    """The next action once G1 passed at H: keep G1 bound to the current contract and base,
    push H, ensure the one PR, then observe the PR and CI until G3 is terminal."""
    ws = github_workspace(state)
    if ws is None:
        return human(["g1_passed"])  # the plan declares no push remote: nothing to push to
    g1 = state["gates"]["g1"]
    head = g1["head"]
    b = state.get("g1_binding")
    if b and b["head"] == head:
        if b["contract"] != contract(state) and g1.get("assessed_at") == b["assessed_at"]:
            return {"action": "assess"}  # approval, policy or controller changed: recompute G1
        if b.get("pending") and not rebind_satisfied(state, b):
            return {"action": "evidence_green", "head": head}  # base moved: Green at H itself
    for kind, op_id in (("push", f"push.{head}"), ("pr_ensure", "pr_ensure")):
        if (step := _op_step(state, kind, op_id, now)) is not None:
            return step
    pr = state.get("pr")
    if pr is None:
        return human(["pr_identity_missing"])
    if keys := open_integration(state, head):
        return human([f"integration_required:{k}" for k in keys])  # the path is T5.1's
    ctx = observation_context(state)
    pr_key, ci_key = f"pr:{pr['number']}", f"ci:{state['repo']}:{head}"
    found = current_pr(state)
    if found is None or (found["fact"].get("context") or {}).get("contract") != ctx["contract"]:
        return _observe_action("pr", pr_key)
    cif = current_ci(state, head)
    g3 = (state.get("gates") or {}).get("g3") or {}
    if cif is None or cif["fact"].get("context") != ctx or g3.get("head") != head:
        return _observe_action("ci", ci_key)
    if g3["status"] == "passed":
        return human(["g3_passed"])  # T5.1 / T6.2 continue from here
    if g3["status"] != "pending":
        return human([f"g3_{g3['status']}", *g3["reasons"]])
    pol, _ = registered_policy(state)
    poll = limit(pol or {}, "poll_github_s", 60)
    waits = {key: _due(state, key, poll, now) for key in (pr_key, ci_key)}
    for source, key in (("pr", pr_key), ("ci", ci_key)):
        if waits[key] == 0:
            return _observe_action(source, key)
    return {"action": "wait", "poll_after_s": min(waits.values()), "reason": f"ci_pending:{head}"}


def policy_recheck(state: State) -> dict[str, Any] | None:
    """Safety: a policy_change recorded after G3 found no usable policy → observe CI again."""
    g3 = (state.get("gates") or {}).get("g3") or {}
    if not g3.get("policy_blockers"):
        return None
    read_key = f"ci:{state.get('repo')}:{g3['head']}"
    if exhausted(state, read_key):
        return None
    newer = [d for d in (state.get("decisions") or {}).values()
             if d["kind"] == "policy_change" and d["seq"] > g3.get("decisions_seen", 0)]
    return _observe_action("ci", read_key) if newer else None
