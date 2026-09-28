"""Gates (design §7, §8). T3.1 adds G1; T6.1 (G3), T5.1 (G2) and T6.2 (Pass) add theirs
without changing the G1 rules (tasks.md shared-file table).

`route` is pure (called by `loopctl.next`). `assess` reads git and may run a diagnostic replay.

G1 at the current head H (the feature branch in the source repository):
  units: every task of the approved plan (`task:<T>`; an empty task set fails) and every
  finding of every correction batch found in `assignments` (`batch:<B>:<F>`). A unit passes
  with one eligible original Red, an accepted independent N/A (keyed `task:<T>` /
  `batch:<B>` in `state.na`), or — integration batches only — a merge with no author edits.
  A Red is eligible only if every check holds, each on its own (D51-R07):
    integrity  producer, raw objects vs digests, exit re-derived from the raw junit,
               provenance (attempt, task, batch, findings, worktree) vs the assignment,
               snapshot commit/tree/parent/ref vs git;
    lineage    its attempt has a completed result whose commit C is an ancestor of H
               (a stopped or abandoned attempt's Red does not transfer);
    scope      snapshot changes and the attempt's range (dispatch head..C) are in scope
               (integration: author edits only, imports verified against merge-tree);
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
from pathlib import Path
from typing import Any

import yaml

from loopctl import assignments, store
from loopctl import evidence as ev
from loopctl.observe import Rejected, block, commit, limit, now_iso, owned

State = dict[str, Any]
ORDER = ("passed", "pending", "failed", "blocked")
G1_BLOCKERS = ("original_red_unavailable:", "history_rewritten", "integration_scope_exceeded:", "red_contradicted:")
DOCS = ("*.md", "*.rst", "docs/*")  # "only documentation changed" after the last attempt (G05)


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
            base["units"] = {u: {"status": "blocked", "reasons": ["history_rewritten"], "red": None, "via": None,
                                 "invalid": {}} for u in units}
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

    def _unit(self, unit: str) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "passed", "reasons": [], "red": None, "via": None, "invalid": {}}
        eligible = [a for a in self._attempts_of(unit) if a in self.eligible]
        checks = [self.integration[a] for a in eligible if a in self.integration]
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
            elif out["red"] is None:
                out["red"] = r["id"]
        invalid = [f"red_invalid:{rid}:{w}" for rid, whys in out["invalid"].items() for w in whys]
        if out["red"]:
            return self._contradiction(out, unit, invalid)
        if checks and all(not (c["author"]["conflict"] or c["author"]["additional"]) for c in checks):
            return {**out, "via": "import"}  # a pure import needs no Red for upstream behaviour
        na = self._na(unit, eligible)
        if na is not None:
            status, reasons = na
            if status == "passed":
                return {**out, "via": "na"}
            return {**out, "status": status, "reasons": [*reasons, *invalid]}
        return {**out, "status": "blocked", "reasons": [f"original_red_unavailable:{unit}", *invalid]}

    def _contradiction(self, out: dict[str, Any], unit: str, invalid: list[str]) -> dict[str, Any]:
        r = self.evidence[out["red"]]
        tree = r["snapshot"]["tree"]
        failing = set(r["failing"])
        others = [e for e in self.evidence.values() if e["id"] != r["id"] and e["kind"] in ("red", "green")
                  and failing & set(e.get("passing") or [])]
        if not any((e["snapshot"]["tree"] if e["kind"] == "red" else self.tree(e["head"])) == tree for e in others):
            return {**out, "via": "red"}
        runs = [e for e in ev.records(self.st, "replay") if e.get("of") == r["id"] and "reproduced" in e]
        if not runs:
            self.replays.append(r["id"])
            return {**out, "status": "pending", "reasons": [f"replay_pending:{r['id']}"], "via": "red"}
        if runs[-1]["reproduced"]:
            return {**out, "via": "red"}
        return {**out, "status": "blocked", "red": None,
                "reasons": [f"red_contradicted:{r['id']}", f"original_red_unavailable:{unit}", *invalid]}

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
        allowed = list(asg["scope"])
        check = self.integration.get(r["attempt"])
        if check is not None:  # integration: verified imports are not author edits
            paths = [p for p in paths if not self._imported(check, snap, p)]
            allowed += check["conflicts"]
        else:
            paths += self.changed(asg["head"], c)
        return [f"scope:{p}" for p in _unique(sorted(paths)) if not in_scope(p, allowed)]

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
        outside = [p for p in additional if not in_scope(p, asg["scope"])]
        out |= {
            "auto_tree": auto, "conflicts": conflicts,
            "imported": sorted(set(self.changed(pinned_h, auto)) - edits),
            "author": {"conflict": sorted(edits & set(conflicts)), "additional": additional},
            "rejected": [f"hidden_edit:{p}" for p in outside if p in base_changed],
            "exceeded": [p for p in outside if p not in base_changed],
        }
        out["status"] = "scope_exceeded" if out["exceeded"] else "rejected" if out["rejected"] else "ok"
        return out

    # N/A (design §7; the same independence checks as G2)
    def _na(self, unit: str, eligible: list[str]) -> tuple[str, list[str]] | None:
        kind, _, rest = unit.partition(":")
        key = f"task:{rest}" if kind == "task" else f"batch:{rest.split(':', 1)[0]}"
        rec = (self.st.get("na") or {}).get(key)
        if rec is None:
            return None
        reviewer = rec.get("reviewer") or {}
        if reviewer.get("role") != "reviewer":
            return "failed", [f"na_self_declared:{unit}"]
        if rec.get("status") == "pending":
            return "pending", [f"na_pending:{unit}"]
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
        if rec.get("attempt") not in eligible or rec.get("head") != self.eligible.get(rec.get("attempt")):
            found.append(("failed", f"na_diff_mismatch:{unit}"))
        if not found:
            return "passed", []
        return worst([s for s, _ in found]), [r for _, r in found]

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
