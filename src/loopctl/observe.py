"""Read-only bounded observation (design §5): seq, version watermark, read-failure budget,
and the `worker` / `native` sources (T2.3). T6.1 adds `pr` / `ci` on the same mechanism.

State (top-level fields owned here):
  observations = {seq, version_seq,
                  requests: {"<seq>": {read_key, source, purpose, at, versions}},
                  current:  {read_key: {purpose: {seq, at, fact, raw}}},
                  history:  [{seq, at, read_key, purpose, fact, raw, superseded}]}
  read_budget  = {read_key: {consecutive_failures, allowance, grants, last_at, last_error}}
  versions.facts (head/base/merge_base) move only with seq > observations.version_seq.

The seq is persisted (in the lock) before the fetch; a fetch whose seq is older than the
current fact of the same read_key and purpose only goes to history. The module also holds
the shared helpers the writes/assignments layers use (policy, owner check, commit loop,
blockers) and the writer-end rule (design §6), since both writes (stop) and observations
(native turn) establish it. Tools are imported only inside the fetch functions, so the
state core (`loopctl.next`) never loads subprocess.
"""

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from loopctl import clock, store
from loopctl import state as state_mod

State = dict[str, Any]
SOURCES = ("worker", "native")
GITHUB_SOURCES = ("pr", "ci")  # T6.1
READ_FAILURES_MAX = 3  # D16; workflow.yaml limits.read_failures_max
RECOVERY_KINDS = {"read_exhausted": "resolve_read"}


class Rejected(Exception):
    """A refused or failed command: `code` is the CLI exit code, `detail` goes to `result`."""

    def __init__(self, error: str, code: int = 1, **detail: Any) -> None:
        super().__init__(error)
        self.error, self.code, self.detail = error, code, detail


class ReadFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- shared helpers -----------------------------------------------------------------------


def policy(state: State) -> dict[str, Any]:
    """The bound loopctl policy: the registered policy's content, else ./workflow.yaml."""
    registered = (state.get("versions") or {}).get("policy") or {}
    try:
        if registered.get("content"):
            data = store.get_object(registered["content"][store.OBJECT_KEY])
        else:
            data = Path("workflow.yaml").read_bytes()
        doc = yaml.safe_load(data)
    except (OSError, yaml.YAMLError, store.StoreError):
        doc = None
    if not isinstance(doc, dict):
        raise Rejected("policy_unreadable", 3)
    return doc


def limit(pol: dict[str, Any], key: str, default: float) -> float:
    return float((pol.get("limits") or {}).get(key, default))


def owned(feature: str, token: str | None) -> tuple[int, State]:
    revision, st = store.load(feature)
    if not state_mod.is_owner(st, token):
        raise Rejected("not_owner", 4, feature=feature)
    return revision, st


def commit(feature: str, tid: str, mutate: Callable[[State], State]) -> int:
    """Commit on the latest revision; a lost revision race reloads and applies again."""
    while True:
        revision, _ = store.load(feature)
        try:
            return store.commit(feature, revision, tid, mutate)
        except store.RevisionConflict:
            continue


def block(st: State, reason: str) -> None:
    if reason not in st.setdefault("blockers", []):
        st["blockers"].append(reason)


def unblock(st: State, *reasons: str) -> None:
    st["blockers"] = [b for b in st.get("blockers", []) if b not in reasons]


def now_iso() -> str:
    return clock.now().isoformat()


def _observations(st: State) -> dict[str, Any]:
    obs = st.setdefault("observations", {})
    for key, empty in (("seq", 0), ("version_seq", 0), ("requests", {}), ("current", {}), ("history", [])):
        obs.setdefault(key, empty)
    return obs


def current(st: State, read_key: str, purpose: str) -> dict[str, Any] | None:
    found = ((st.get("observations") or {}).get("current") or {}).get(read_key, {}).get(purpose)
    return dict(found) if found else None


# --- seq and version watermark ------------------------------------------------------------


def allocate(feature: str, read_key: str, source: str, purpose: str) -> int:
    """Persist the next seq and the request context before fetching (design §5)."""
    at, box = now_iso(), {}

    def mutate(st: State) -> State:
        obs = _observations(st)
        obs["seq"] += 1
        box["seq"] = obs["seq"]
        versions = dict((st.get("versions") or {}).get("facts") or {})
        obs["requests"][str(obs["seq"])] = {
            "read_key": read_key, "source": source, "purpose": purpose, "at": at, "versions": versions
        }
        return st

    commit(feature, f"observe:{read_key}:seq@{at}:{secrets.token_hex(6)}", mutate)
    return int(box["seq"])


def record(
    st: State,
    seq: int,
    read_key: str,
    purpose: str,
    fact: dict[str, Any],
    raw: str | None,
    at: str,
    versions: dict[str, str] | None = None,
) -> str:
    """Pure: file a fetched fact. Returns `fetched`, or `superseded` for a late older seq."""
    obs = _observations(st)
    entry = {"seq": seq, "at": at, "fact": fact, "raw": store.object_ref(raw) if raw else None}
    slot = obs["current"].setdefault(read_key, {})
    prev = slot.get(purpose)
    if prev is not None and prev["seq"] > seq:
        obs["history"].append({**entry, "read_key": read_key, "purpose": purpose, "superseded": True})
        outcome = "superseded"
    else:
        if prev is not None:
            obs["history"].append({**prev, "read_key": read_key, "purpose": purpose, "superseded": False})
        slot[purpose] = entry
        outcome = "fetched"
    if versions and seq > obs["version_seq"]:
        vs = st.setdefault("versions", {})
        vs["facts"] = {**(vs.get("facts") or {}), **versions}
        obs["version_seq"] = seq
    return outcome


def commit_fact(
    feature: str,
    seq: int,
    read_key: str,
    purpose: str,
    fact: dict[str, Any],
    raw: str | None,
    versions: dict[str, str] | None = None,
    after: Callable[[State, str, str], None] | None = None,
    per: int = READ_FAILURES_MAX,
) -> str:
    """Commit a fetched fact at its seq; `after(state, outcome, at)` adds the source's effects."""
    at, box = now_iso(), {}

    def mutate(st: State) -> State:
        box["outcome"] = record(st, seq, read_key, purpose, fact, raw, at, versions)
        _succeeded(st, read_key, at, per)
        if after is not None:
            after(st, box["outcome"], at)
        return st

    commit(feature, f"observe:{read_key}:{seq}", mutate)
    return str(box["outcome"])


# --- read-failure budget (AC-A05, D16) ----------------------------------------------------


def _budget(st: State, read_key: str, per: int = READ_FAILURES_MAX) -> dict[str, Any]:
    entry: dict[str, Any] = st.setdefault("read_budget", {}).setdefault(read_key, {})
    for key, value in (("consecutive_failures", 0), ("allowance", per), ("per", per), ("grants", []),
                       ("last_at", None), ("last_error", None)):
        entry.setdefault(key, value)
    return entry


def pending_grants(st: State, read_key: str) -> list[str]:
    """resolve_read decisions for this key whose one new allowance is not applied yet."""
    granted = ((st.get("read_budget") or {}).get(read_key) or {}).get("grants", [])
    decided = sorted((st.get("decisions") or {}).values(), key=lambda d: d["seq"])
    return [
        d["id"] for d in decided
        if d["kind"] == "resolve_read" and d["target"] == read_key and d["id"] not in granted
    ]


def exhausted(st: State, read_key: str) -> bool:
    entry = (st.get("read_budget") or {}).get(read_key)
    if entry is None:
        return False
    return bool(entry.get("consecutive_failures", 0) >= entry.get("allowance", READ_FAILURES_MAX))


def _grant(st: State, read_key: str, per: int) -> State:
    """Each resolve_read gives one new allowance of `per` failures; counts are not reset."""
    entry = _budget(st, read_key, per)
    for decision in pending_grants(st, read_key):
        entry["allowance"] = max(entry["allowance"], entry["consecutive_failures"]) + per
        entry["grants"].append(decision)
    if not exhausted(st, read_key):
        unblock(st, f"read_exhausted:{read_key}")
    return st


def _succeeded(st: State, read_key: str, at: str, per: int) -> None:
    """Any successful fetch (even of pending content) resets the consecutive count."""
    entry = _budget(st, read_key, per)
    entry.update(consecutive_failures=0, allowance=entry["per"], last_at=at, last_error=None)
    unblock(st, f"read_exhausted:{read_key}")


def _failed(feature: str, seq: int, read_key: str, reason: str, per: int) -> dict[str, Any]:
    at, box = now_iso(), {}

    def mutate(st: State) -> State:
        entry = _budget(st, read_key, per)
        entry["consecutive_failures"] += 1
        entry.update(last_at=at, last_error={"seq": seq, "reason": reason})
        _observations(st)["history"].append(
            {"seq": seq, "at": at, "read_key": read_key, "fact": None, "error": reason, "superseded": False}
        )
        if exhausted(st, read_key):
            block(st, f"read_exhausted:{read_key}")
        box["budget"] = dict(entry)
        return st

    commit(feature, f"observe:{read_key}:{seq}:failed", mutate)
    return dict(box["budget"])


# --- writer end (design §6, D04) ----------------------------------------------------------


def native_turn_complete(st: State, attempt: str) -> bool:
    found = current(st, f"native:{attempt}", "native")
    return bool(found and found["fact"].get("marker_found") and found["fact"].get("turn_complete"))


def settle(st: State, attempt: str, at: str) -> None:
    """Record the writer end once authoritative evidence exists: an imported result plus a
    finished native turn, or a stop confirmed by process-info. Idle/done never counts."""
    a = (st.get("attempts") or {}).get(attempt)
    if a is None or a.get("end"):
        return
    stop = (st.get("writes") or {}).get(f"{attempt}.stop")
    if stop is not None and stop["status"] == "succeeded":
        evidence = "stop_confirmed"
    elif a.get("result") and native_turn_complete(st, attempt):
        evidence = "result_and_native_turn"
    else:
        return
    a["end"] = {"evidence": evidence, "at": at}
    for activity in st.get("activities", []):
        if activity.get("attempt") == attempt and activity["kind"] in ("worker", "review") and not activity["end"]:
            activity["end"] = at


# --- sources ------------------------------------------------------------------------------


def _worker(st: State, attempt: str, pol: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    from loopctl.tools import herdr

    handle = st["attempts"][attempt]["handle"]
    args = herdr.argv(handle["herdr_session"], ["agent", "get", handle["agent_name"]])
    try:
        doc, raw = herdr.read(args, limit(pol, "read_call_s", 30))
    except herdr.ReadFailed as e:
        raise ReadFailed(e.reason) from e
    if "error" in doc:
        return {"error": (doc.get("error") or {}).get("code")}, raw, {}
    found = (doc.get("result") or {}).get("agent") or {}
    fact = {k: found.get(k) for k in ("agent_status", "pane_id", "cwd", "interactive_ready")}
    return fact, raw, {}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _segment(entries: list[Any], own: str, is_user: Callable[[Any], bool], text: Callable[[Any], str]) -> list[Any] | None:
    """Entries from the user message carrying our marker up to another op's marker."""
    from loopctl.tools.herdr import MARKER

    start = next((i for i, e in enumerate(entries) if is_user(e) and own in MARKER.findall(text(e))), None)
    if start is None:
        return None
    end = next(
        (j for j in range(start + 1, len(entries))
         if is_user(entries[j]) and set(MARKER.findall(text(entries[j]))) - {own}),
        len(entries),
    )
    return entries[start:end]


def _result_text(turn_complete: bool, text: str, message_id: str | None) -> dict[str, Any] | None:
    if not turn_complete:
        return None
    return {"text": text, "message_id": message_id}


def _claude(handle: dict[str, Any], own: str) -> tuple[dict[str, Any], bytes | None]:
    sid = handle["native_session_id"]
    files = sorted((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"))
    if not files:
        return {"found": False, "session_id": None, "marker_found": False, "turn_complete": False}, None
    try:
        raw = files[0].read_bytes()
    except OSError as e:
        raise ReadFailed("native_unreadable") from e
    entries = []
    for line in raw.decode(errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue  # a line still being appended
    seg = _segment(
        entries, own,
        lambda e: e.get("type") == "user",
        lambda e: _text((e.get("message") or {}).get("content")),
    )
    fact: dict[str, Any] = {"found": True, "session_id": sid, "marker_found": seg is not None}
    seg = seg or []
    assistants = [e for e in seg if e.get("type") == "assistant"]

    def blocks(e: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        content = (e.get("message") or {}).get("content")
        return [b for b in content if isinstance(b, dict) and b.get("type") == kind] if isinstance(content, list) else []

    used = {b.get("id") for e in assistants for b in blocks(e, "tool_use")}
    answered = {b.get("tool_use_id") for e in seg if e.get("type") == "user" for b in blocks(e, "tool_result")}
    last = assistants[-1] if assistants else None
    complete = bool(last) and (last or {}).get("message", {}).get("stop_reason") == "end_turn" and not (used - answered)
    message_id = ((last or {}).get("message") or {}).get("id")
    fact.update(
        turn_complete=complete,
        pending_tool_calls=len(used - answered),
        cwd=seg[0].get("cwd") if seg else None,
        models=sorted({str(m) for e in assistants if (m := (e.get("message") or {}).get("model"))}),
        final_message_id=message_id,
        result=_result_text(complete, _text((last or {}).get("message", {}).get("content")), message_id),
    )
    return fact, raw


def _opencode(handle: dict[str, Any], own: str, worktree: str, timeout_s: float) -> tuple[dict[str, Any], bytes | None, str | None]:
    from loopctl import tools

    def run_json(args: list[str]) -> tuple[Any, str]:
        try:
            out = tools.run(["opencode", *args], timeout_s)
            return json.loads(out), out
        except tools.ToolError as e:
            raise ReadFailed("read_timeout" if e.code is None else "client_error") from e
        except ValueError as e:
            raise ReadFailed("unparseable_output") from e

    if handle.get("native_session_id"):
        candidates = [handle["native_session_id"]]
    else:
        listed, _ = run_json(["session", "list", "--format", "json"])
        here = [s for s in listed if s.get("directory") and str(Path(s["directory"]).resolve()) == str(Path(worktree).resolve())]
        here.sort(key=lambda s: s.get("updated") or (s.get("time") or {}).get("updated", 0), reverse=True)
        candidates = [s["id"] for s in here[:5]]
    for sid in candidates:
        data, out = run_json(["export", sid])
        messages = data.get("messages", [])
        seg = _segment(
            messages, own,
            lambda m: (m.get("info") or {}).get("role") == "user",
            lambda m: "\n".join(str(p.get("text", "")) for p in m.get("parts", []) if isinstance(p, dict)),
        )
        if seg is None:
            continue
        assistants = [m for m in seg if (m.get("info") or {}).get("role") == "assistant"]
        running = [p for m in assistants for p in m.get("parts", []) if p.get("type") == "tool"
                   and (p.get("state") or {}).get("status") in ("pending", "running")]
        last = assistants[-1] if assistants else None
        complete = bool(last) and ((last or {}).get("info") or {}).get("finish") == "stop" and not running
        message_id = ((last or {}).get("info") or {}).get("id")
        text = "\n".join(str(p.get("text", "")) for p in (last or {}).get("parts", []) if p.get("type") == "text")
        native_id = (data.get("info") or {}).get("id")
        return {
            "found": True, "session_id": native_id, "marker_found": True, "turn_complete": complete,
            "pending_tool_calls": len(running), "cwd": (data.get("info") or {}).get("directory"),
            "models": sorted({(m.get("info") or {}).get("modelID") for m in assistants} - {None}),
            "final_message_id": message_id, "result": _result_text(complete, text, message_id),
        }, out.encode(), native_id
    return {"found": False, "session_id": None, "marker_found": False, "turn_complete": False}, None, None


def _native(st: State, attempt: str, pol: dict[str, Any]) -> tuple[dict[str, Any], bytes | None, dict[str, Any]]:
    handle = st["attempts"][attempt]["handle"]
    own = f"loopctl-op:{st['feature']}/{attempt}.prompt"
    if handle["runtime"] == "opencode":
        worktree = st["assignments"][attempt]["worktree"]
        fact, raw, native_id = _opencode(handle, own, worktree, limit(pol, "read_call_s", 30))
        return fact, raw, ({"native_session_id": native_id} if native_id else {})
    fact, raw = _claude(handle, own)
    return fact, raw, {}


def _pr(st: State, target: dict[str, Any], pol: dict[str, Any]) -> tuple[dict[str, Any], str]:
    from loopctl.tools import gh

    try:
        return gh.read_pr(target["repo"], target["pr"]["number"], limit(pol, "read_call_s", 30))
    except gh.ReadFailed as e:
        raise ReadFailed(e.reason) from e


def _ci(st: State, target: dict[str, Any], pol: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Every page of every GitHub read of H, plus the CI workflow's blob at H (local git)."""
    from loopctl.tools import evidence as git_tools
    from loopctl.tools import gh

    read_s = limit(pol, "read_call_s", 30)
    try:
        fact, raw = gh.read_ci(target["repo"], target["head"], target["base_branch"], target["workflow"],
                               target["names"], read_s)
    except gh.ReadFailed as e:
        raise ReadFailed(e.reason) from e
    blob = None
    if target["workflow"] and target["source"]:
        try:
            blob = git_tools.blob(target["source"], target["head"], target["workflow"], read_s)
        except git_tools.GitError as e:
            raise ReadFailed("git_unreadable") from e
    return {**fact, "workflow_blob": blob}, raw


# The fetch per source (a seam: tests reorder reads through it). A worker / native fetch returns
# (fact, raw bytes or text, handle updates), a pr / ci fetch (fact, raw); either raises
# ReadFailed on a transport failure.
FETCHERS: dict[str, Callable[..., Any]] = {"worker": _worker, "native": _native, "pr": _pr, "ci": _ci}


def _native_effects(
    attempt: str, fact: dict[str, Any], handle_update: dict[str, Any], result_file: bool
) -> Callable[[State, str, str], None]:
    def after(st: State, outcome: str, at: str) -> None:
        if outcome != "fetched":
            return  # a late older read changes nothing
        a = st["attempts"][attempt]
        for key, value in handle_update.items():
            if a["handle"].get(key) is None:  # learned from the runtime, never invented
                a["handle"][key] = value
        unparseable = fact.get("turn_complete") and _parsed(fact.get("result")) is None
        if unparseable and a.get("result") is None and not result_file:
            block(st, f"native_result_unparseable:{attempt}")
        settle(st, attempt, at)

    return after


def _parsed(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The result envelope in the final native message: the whole text, or its last ```json block."""
    if not result:
        return None
    text = store.get_object(result["text"][store.OBJECT_KEY]).decode() if isinstance(result.get("text"), dict) else str(result.get("text", ""))
    candidates = [text.strip()]
    fence = text.rsplit("```json", 1)
    if len(fence) == 2:
        candidates.append(fence[1].split("```", 1)[0].strip())
    for candidate in reversed(candidates):
        try:
            doc = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def parsed_native_result(st: State, attempt: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(envelope, fact) when the current native fact carries a parseable final result."""
    found = current(st, f"native:{attempt}", "native")
    if not found or not found["fact"].get("turn_complete"):
        return None
    doc = _parsed(found["fact"].get("result"))
    return (doc, found["fact"]) if doc is not None else None


def _observe_github(feature: str, token: str | None, source: str, purpose: str | None) -> dict[str, Any]:
    """`observe pr|ci` (T6.1): read keys `pr:<number>` and `ci:<repo>:<H>`; the same seq,
    watermark and read-failure budget as worker / native. A general-purpose read also records
    its effects (PR identity, integration triggers, G1 binding, G3); another purpose (T6.2's
    `pass`) only files its fact."""
    from loopctl import gates

    _, st = owned(feature, token)
    target = gates.github_target(st)
    if target["pr"] is None:
        raise Rejected("pr_identity_missing", source=source)
    if source == "ci" and target["head"] is None:
        raise Rejected("head_unknown", source=source)
    purpose = purpose or source
    read_key = f"pr:{target['pr']['number']}" if source == "pr" else f"ci:{target['repo']}:{target['head']}"
    pol = gates.registered_policy(st)[0] or {}
    per = int(limit(pol, "read_failures_max", READ_FAILURES_MAX))
    if ids := pending_grants(st, read_key):
        commit(feature, f"observe:{read_key}:grant:{','.join(ids)}", lambda s: _grant(s, read_key, per))
        _, st = store.load(feature)
    if exhausted(st, read_key):
        raise Rejected("read_exhausted", 3, read_key=read_key, budget=st["read_budget"][read_key])
    if source == "ci" and purpose == "ci" and not gates.ci_wait_started(st, target["head"]):
        at = now_iso()
        commit(feature, f"observe:{read_key}:ci_wait@{at}", lambda s: gates.start_ci_wait(s, target["head"], at))
    seq = allocate(feature, read_key, source, purpose)
    context = gates.observation_context(st)
    try:
        try:
            fact, raw = FETCHERS[source](st, target, pol)
        except (KeyError, TypeError, AttributeError, ValueError, UnicodeDecodeError) as e:
            raise ReadFailed("unparseable_output") from e  # a reply of an unexpected shape
    except ReadFailed as e:
        budget = _failed(feature, seq, read_key, e.reason, per)
        detail = {"read_key": read_key, "seq": seq, "reason": e.reason, "budget": budget}
        if budget["consecutive_failures"] >= budget["allowance"]:
            raise Rejected("read_exhausted", 3, **detail) from e
        raise Rejected("read_failed", 1, **detail) from e
    fact = {**fact, "context": context}
    raw_ref = store.put_object(raw.encode())
    versions = None
    if source == "pr" and fact.get("found"):
        versions = {"head": fact["head"]["sha"], "base": fact["base"]["sha"]}
    after = gates.after_github(source) if purpose == source else None
    outcome = commit_fact(feature, seq, read_key, purpose, fact, raw_ref, versions=versions, after=after, per=per)
    return {"read_key": read_key, "seq": seq, "outcome": outcome, "fact": fact}


def observe(feature: str, token: str | None, source: str, attempt: str, purpose: str | None) -> dict[str, Any]:
    if source in GITHUB_SOURCES:
        return _observe_github(feature, token, source, purpose)
    if source not in SOURCES:
        raise Rejected("unsupported", 2, source=source)
    _, st = owned(feature, token)
    if attempt not in (st.get("attempts") or {}):
        raise Rejected("unknown_attempt", attempt=attempt)
    purpose = purpose or source
    read_key = f"{source}:{attempt}"
    pol = policy(st)
    per = int(limit(pol, "read_failures_max", READ_FAILURES_MAX))
    if ids := pending_grants(st, read_key):
        commit(feature, f"observe:{read_key}:grant:{','.join(ids)}", lambda s: _grant(s, read_key, per))
        _, st = store.load(feature)
    if exhausted(st, read_key):
        raise Rejected("read_exhausted", 3, read_key=read_key, budget=st["read_budget"][read_key])
    seq = allocate(feature, read_key, source, purpose)
    try:
        try:
            fact, raw, handle_update = FETCHERS[source](st, attempt, pol)
        except (KeyError, TypeError, AttributeError, UnicodeDecodeError) as e:
            raise ReadFailed("unparseable_output") from e  # a reply of an unexpected shape
    except ReadFailed as e:
        budget = _failed(feature, seq, read_key, e.reason, per)
        detail = {"read_key": read_key, "seq": seq, "reason": e.reason, "budget": budget}
        if budget["consecutive_failures"] >= budget["allowance"]:
            raise Rejected("read_exhausted", 3, **detail) from e
        raise Rejected("read_failed", 1, **detail) from e
    if isinstance(raw, str):
        raw = raw.encode()
    raw_ref = store.put_object(raw) if raw is not None else None
    if isinstance(fact.get("result"), dict) and "text" in fact["result"]:
        text = fact["result"]["text"].encode()
        fact["result"] = {**fact["result"], "text": store.object_ref(store.put_object(text)),
                          "raw_digest": store.digest(text)}
    after = None
    if source == "native" and purpose == "native":
        result_file = Path(st["assignments"][attempt]["result_path"]).is_file()
        after = _native_effects(attempt, fact, handle_update, result_file)
    outcome = commit_fact(feature, seq, read_key, purpose, fact, raw_ref, after=after, per=per)
    return {"read_key": read_key, "seq": seq, "outcome": outcome, "fact": fact}


def safety(state: State) -> dict[str, Any] | None:
    """A resolve_read decision waiting to grant its one new allowance comes first; then (T6.1)
    a policy_change recorded after G3 found no usable policy."""
    for read_key in sorted(state.get("read_budget") or {}):
        if exhausted(state, read_key) and pending_grants(state, read_key):
            source, _, attempt = read_key.partition(":")
            if source in SOURCES:
                return {"action": "observe", "source": source, "purpose": source, "read_key": read_key,
                        "attempt": attempt}
            if source in GITHUB_SOURCES:
                return {"action": "observe", "source": source, "purpose": source, "read_key": read_key}
    from loopctl import gates

    return gates.policy_recheck(state)
