"""GitHub and remote-git calls (T6.1): the `push` / `pr_ensure` op calls and their readbacks,
and the bounded reads of `observe pr|ci` (design §4, §5, §8).

Every GitHub read is `gh api --include <path>` (status line + headers + JSON body, the same
on error answers); pages of 100 are followed through the `Link: rel="next"` header until the
last one, and one failing page fails the whole read (no partial result). Each subprocess is
bounded by its own time limit. These functions only classify one call; whether to retry,
read back or block is decided by loopctl.writes / loopctl.gates, never here.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from loopctl.tools import ToolError, run

API = ["gh", "api", "--include", "-H", "Accept: application/vnd.github+json"]
MAX_PAGES = 50
LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
STATUS_LINE = re.compile(r"HTTP/\S+ (\d{3})")
# git push failed before reaching any remote: nothing was sent (verified messages of git 2.x)
PUSH_NOT_DELIVERED = ("does not appear to be a git repository", "Could not resolve host", "Connection refused",
                      "unable to access")
IDENTITY = ("head_repo", "head_branch", "head_sha", "base_repo", "base_branch")


class ReadFailed(Exception):
    """A transport failure of a read (time limit, lost client, 5xx, unparseable reply, a page)."""

    def __init__(self, reason: str, raw: str = "") -> None:
        super().__init__(reason)
        self.reason, self.raw = reason, raw


def _timed_out(e: ToolError) -> bool:
    return isinstance(e.__cause__, subprocess.TimeoutExpired)


def _receipt(e: ToolError) -> str:
    return f"exit: {e.code}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}"


def _parse(text: str) -> tuple[int, dict[str, str], Any]:
    """`gh api --include` output → (status, lower-cased headers, JSON body or None)."""
    norm = text.replace("\r\n", "\n")
    m = STATUS_LINE.match(norm)
    if not m:
        raise ValueError("no status line")
    head, _, body = norm.partition("\n\n")
    headers = {}
    for line in head.split("\n")[1:]:
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    return int(m.group(1)), headers, (json.loads(body) if body.strip() else None)


def _request(args: list[str], timeout_s: float) -> tuple[int, dict[str, str], Any, str]:
    try:
        out = run(args, timeout_s)
    except ToolError as e:
        if _timed_out(e):
            raise ReadFailed("read_timeout") from e
        if not e.stdout.strip():  # no answer at all
            raise ReadFailed("client_error" if e.code is not None else "client_not_started", e.stderr) from e
        out = e.stdout  # an HTTP error answer: gh exits 1 with the response on stdout
    try:
        status, headers, doc = _parse(out)
    except ValueError:
        raise ReadFailed("unparseable_output", out) from None
    return status, headers, doc, out


class _Unreadable(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def _pages(path: str, timeout_s: float, key: str | None, raws: list[str],
           unreadable: tuple[int, ...] = ()) -> list[Any]:
    """Every item of every page; `_Unreadable` when the first page answers a status in `unreadable`."""
    items: list[Any] = []
    url = path
    for n in range(MAX_PAGES):
        status, headers, doc, raw = _request([*API, url], timeout_s)
        raws.append(raw)
        if n == 0 and status in unreadable:
            raise _Unreadable(status)
        if status != 200:
            raise ReadFailed(f"http_{status}", raw)
        found = doc.get(key) if key and isinstance(doc, dict) else doc
        if not isinstance(found, list):
            raise ReadFailed("unparseable_output", raw)
        items += found
        nxt = LINK_NEXT.search(headers.get("link", ""))
        if not nxt:
            return items
        url = nxt.group(1)
    raise ReadFailed("too_many_pages")


# --- PR identity ------------------------------------------------------------------------------


def identity(pr: dict[str, Any], marker: str | None) -> dict[str, Any]:
    head, base = pr.get("head") or {}, pr.get("base") or {}
    return {
        "number": pr.get("number"), "node_id": pr.get("node_id"), "url": pr.get("html_url"), "state": pr.get("state"),
        "head_repo": (head.get("repo") or {}).get("full_name"), "head_branch": head.get("ref"),
        "head_sha": head.get("sha"), "base_repo": (base.get("repo") or {}).get("full_name"),
        "base_branch": base.get("ref"), "base_sha": base.get("sha"),
        "marker": bool(marker) and str(marker) in str(pr.get("body") or ""),
    }


def differs(found: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    return [f for f in IDENTITY if found.get(f) != expected[f]]


def _with_origin(found: dict[str, Any]) -> dict[str, Any]:
    return {**found, "origin": "created" if found["marker"] else "existing"}


# --- op calls ---------------------------------------------------------------------------------


def _push(argv: list[str], timeout_s: float, expected: dict[str, Any]) -> dict[str, Any]:
    try:
        out = run(argv, timeout_s)
    except ToolError as e:
        receipt = _receipt(e)
        if _timed_out(e):
            return {"outcome": "unknown", "reason": "call_timeout", "receipt": receipt, "facts": {}}
        if e.code is None:
            return {"outcome": "failed_not_delivered", "reason": "client_not_started", "receipt": receipt, "facts": {}}
        text = e.stdout + e.stderr
        if "[rejected]" in text or "[remote rejected]" in text:  # delivered, refused: never forced
            return {"outcome": "rejected", "block": "push_rejected", "reason": "non_fast_forward",
                    "receipt": receipt, "facts": {}}
        if any(s in text for s in PUSH_NOT_DELIVERED):
            return {"outcome": "failed_not_delivered", "reason": "remote_unreachable", "receipt": receipt,
                    "facts": {}}
        return {"outcome": "unknown", "reason": "client_exited", "receipt": receipt, "facts": {}}
    facts = {"remote": expected["remote"], "ref": expected["ref"], "sha": expected["sha"]}
    return {"outcome": "succeeded", "reason": None, "receipt": out, "facts": facts}


def _pr_ensure(argv: dict[str, Any], timeout_s: float, expected: dict[str, Any], read_s: float) -> dict[str, Any]:
    """Query every open PR of the head branch, then create once only when there is none."""
    raws: list[str] = []
    try:
        listed = _pages(argv["query"], read_s, None, raws) or []
    except ReadFailed as e:  # the create was never sent
        return {"outcome": "failed_not_delivered", "reason": f"precreate_query:{e.reason}",
                "receipt": "\n".join(raws + [e.raw]), "facts": {}}
    found = [identity(p, expected["marker"]) for p in listed if isinstance(p, dict)]
    found = [f for f in found if (f["head_repo"], f["head_branch"]) == (expected["head_repo"], expected["head_branch"])]
    receipt = "\n".join(raws)
    if len(found) > 1:
        return {"outcome": "rejected", "block": "pr_ambiguous", "reason": f"open_prs:{[f['number'] for f in found]}",
                "receipt": receipt, "facts": {}}
    if found:
        diff = differs(found[0], expected)
        if diff:
            return {"outcome": "rejected", "block": "pr_identity_mismatch", "reason": f"differs:{','.join(diff)}",
                    "receipt": receipt, "facts": {"found": found[0]}}
        # not created by this call: origin=existing, whatever the body says (design §4)
        return {"outcome": "succeeded", "reason": "existing_open_pr", "receipt": receipt,
                "facts": {"pr": {**found[0], "origin": "existing"}}}
    try:
        out = run(argv["create"], timeout_s)
    except ToolError as e:
        if _timed_out(e):
            return {"outcome": "unknown", "reason": "call_timeout", "receipt": receipt + "\n" + _receipt(e), "facts": {}}
        if e.code is None:
            return {"outcome": "failed_not_delivered", "reason": "client_not_started",
                    "receipt": receipt + "\n" + _receipt(e), "facts": {}}
        out = e.stdout
    receipt += "\n" + out
    try:
        status, _, doc = _parse(out)
    except ValueError:
        return {"outcome": "unknown", "reason": "unparseable_output", "receipt": receipt, "facts": {}}
    if status == 201 and isinstance(doc, dict):
        created = identity(doc, expected["marker"])
        return {"outcome": "succeeded", "reason": None, "receipt": receipt,
                "facts": {"pr": {**created, "origin": "created"}, "differs": differs(created, expected)}}
    if 400 <= status < 500 and status != 422:  # refused before anything was created
        return {"outcome": "rejected", "block": "pr_create_rejected", "reason": f"http_{status}", "receipt": receipt,
                "facts": {}}
    return {"outcome": "unknown", "reason": f"http_{status}", "receipt": receipt, "facts": {}}  # 422 / 5xx: may exist


def op_call(kind: str, argv: Any, timeout_s: float, expected: dict[str, Any], read_s: float) -> dict[str, Any]:
    """One op call: {outcome: succeeded|failed_not_delivered|rejected|unknown, reason, receipt, facts[, block]}."""
    if kind == "push":
        return _push(argv, timeout_s, expected)
    return _pr_ensure(argv, timeout_s, expected, read_s)


# --- readbacks ----------------------------------------------------------------------------------


def _read_push(expected: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    try:
        out = run(["git", "-C", expected["source"], "ls-remote", expected["remote"]], timeout_s)
    except ToolError as e:
        return {"result": "transport_error", "detail": "read_timeout" if _timed_out(e) else "client_error",
                "raw": _receipt(e), "facts": {}}
    refs: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref:
            refs[ref] = sha
    target = refs.get(expected["ref"])
    if target == expected["sha"]:
        return {"result": "confirmed", "detail": None, "raw": out,
                "facts": {"remote": expected["remote"], "ref": expected["ref"], "sha": expected["sha"]}}
    elsewhere = sorted(r for r, sha in refs.items() if sha == expected["sha"])
    if elsewhere:
        return {"result": "mismatch", "detail": f"sha_on_other_ref:{elsewhere[0]}", "raw": out, "facts": {}}
    if target is not None:
        return {"result": "mismatch", "detail": f"remote_ref_at:{target}", "raw": out, "facts": {}}
    return {"result": "absent", "detail": "ref_absent", "raw": out, "facts": {}}


def _read_pr_ensure(expected: dict[str, Any], timeout_s: float, observed: str | None) -> dict[str, Any]:
    raws: list[str] = []
    try:
        if observed is not None:  # resolve_operation --bind <number>: one fresh read of that PR
            if not observed.isdigit():
                return {"result": "mismatch", "detail": "bind_not_a_pr_number", "raw": "", "facts": {}}
            status, _, doc, raw = _request([*API, f"repos/{expected['repo']}/pulls/{observed}"], timeout_s)
            raws.append(raw)
            if status == 404:
                return {"result": "absent", "detail": "pr_not_found", "raw": raw, "facts": {}}
            if status != 200 or not isinstance(doc, dict):
                return {"result": "transport_error", "detail": f"http_{status}", "raw": raw, "facts": {}}
            named = identity(doc, expected["marker"])
            diff = differs(named, expected)
            if diff:
                return {"result": "mismatch", "detail": f"differs:{','.join(diff)}", "raw": raw, "facts": {}}
            return {"result": "confirmed", "detail": None, "raw": raw, "facts": {"pr": _with_origin(named)}}
        owner = expected["head_repo"].split("/")[0]
        listed = _pages(f"repos/{expected['repo']}/pulls?state=open&head={owner}:{expected['head_branch']}&per_page=100",
                        timeout_s, None, raws) or []
    except ReadFailed as e:
        return {"result": "transport_error", "detail": e.reason, "raw": "\n".join(raws + [e.raw]), "facts": {}}
    raw = "\n".join(raws)
    found = [identity(p, expected["marker"]) for p in listed if isinstance(p, dict)]
    marked = [f for f in found if f["marker"]]
    if marked:
        if len(marked) == 1 and not differs(marked[0], expected):
            return {"result": "confirmed", "detail": None, "raw": raw, "facts": {"pr": _with_origin(marked[0])}}
        return {"result": "mismatch", "detail": "marker_identity_mismatch", "raw": raw, "facts": {}}
    if any(not differs(f, expected) for f in found):
        return {"result": "mismatch", "detail": "identity_without_marker", "raw": raw, "facts": {}}
    return {"result": "absent", "detail": "pr_not_found", "raw": raw, "facts": {}}


def readback(kind: str, expected: dict[str, Any], timeout_s: float, observed: str | None = None) -> dict[str, Any]:
    """One read-only check of an op's effect against its persisted expected identity:
    {result: confirmed|absent|mismatch|transport_error, detail, raw, facts}."""
    if kind == "push":
        return _read_push(expected, timeout_s)
    return _read_pr_ensure(expected, timeout_s, observed)


# --- observe pr / ci ------------------------------------------------------------------------------


def read_pr(repo: str, number: int, timeout_s: float) -> tuple[dict[str, Any], str]:
    status, _, doc, raw = _request([*API, f"repos/{repo}/pulls/{number}"], timeout_s)
    if status == 404:
        return {"found": False, "number": number}, raw
    if status != 200 or not isinstance(doc, dict):
        raise ReadFailed(f"http_{status}", raw)
    head, base = doc.get("head") or {}, doc.get("base") or {}
    fact = {
        "found": True, "number": doc.get("number"), "node_id": doc.get("node_id"), "url": doc.get("html_url"),
        "state": doc.get("state"), "mergeable": doc.get("mergeable"), "mergeable_state": doc.get("mergeable_state"),
        "head": {"repo": (head.get("repo") or {}).get("full_name"), "ref": head.get("ref"), "sha": head.get("sha")},
        "base": {"repo": (base.get("repo") or {}).get("full_name"), "ref": base.get("ref"), "sha": base.get("sha")},
    }
    return fact, raw


def _download(repo: str, run_id: int, name: str, timeout_s: float) -> dict[str, Any]:
    """The tested-SHA artifact's content, read from the file itself (not only its name)."""
    with tempfile.TemporaryDirectory(prefix="loopctl-artifact-") as d:
        try:
            run(["gh", "run", "download", str(run_id), "--repo", repo, "--name", name, "--dir", d], timeout_s)
        except ToolError as e:
            raise ReadFailed("read_timeout" if _timed_out(e) else "artifact_download_failed", _receipt(e)) from e
        path = Path(d) / "tested-sha.json"
        if not path.is_file():
            return {"content": None, "error": "file_missing"}
        try:
            content = json.loads(path.read_text())
        except ValueError:
            return {"content": None, "error": "unparseable"}
    return {"content": content, "error": None} if isinstance(content, dict) else {"content": None, "error": "not_an_object"}


def _job(j: dict[str, Any]) -> dict[str, Any]:
    return {k: j.get(k) for k in ("id", "name", "status", "conclusion", "run_attempt", "html_url", "check_run_url")}


def read_ci(repo: str, head: str, base_branch: str, workflow: str | None, names: list[str],
            timeout_s: float) -> tuple[dict[str, Any], str]:
    """Everything G3 judges for H: the branch rules (403/404 = unreadable), every workflow run of
    H with the jobs of each policy-workflow run's latest attempt, the tested-SHA artifact of each
    successful required job, the check-runs and the commit statuses of H."""
    raws: list[str] = []
    rules: dict[str, Any]
    try:
        rules_items = _pages(f"repos/{repo}/rules/branches/{base_branch}?per_page=100", timeout_s, None, raws,
                             unreadable=(403, 404))
    except _Unreadable as e:
        rules = {"status": "unreadable", "http": e.status, "required": []}
    else:
        required = [{"context": c.get("context"), "integration_id": c.get("integration_id")}
                    for r in rules_items if isinstance(r, dict) and r.get("type") == "required_status_checks"
                    for c in ((r.get("parameters") or {}).get("required_status_checks") or [])]
        rules = {"status": "readable", "http": 200, "required": required}
    wanted = set(names) | {str(c["context"]) for c in rules["required"]}
    runs = []
    listed = _pages(f"repos/{repo}/actions/runs?head_sha={head}&per_page=100", timeout_s, "workflow_runs", raws) or []
    for r in sorted((r for r in listed if isinstance(r, dict)), key=lambda r: (r.get("id") is None, r.get("id") or 0)):
        entry: dict[str, Any] = {k: r.get(k) for k in ("id", "run_number", "run_attempt", "event", "head_sha",
                                                       "check_suite_id", "status", "conclusion", "html_url")}
        entry |= {"path": str(r.get("path") or "").split("@", 1)[0],
                  "pull_requests": [p.get("number") for p in (r.get("pull_requests") or []) if isinstance(p, dict)],
                  "jobs": None, "artifacts": None, "tested": {}}
        if entry["path"] == workflow and entry["head_sha"] == head and entry["id"] is not None \
                and entry["run_attempt"] is not None:
            jobs_path = f"repos/{repo}/actions/runs/{entry['id']}/attempts/{entry['run_attempt']}/jobs?per_page=100"
            entry["jobs"] = [_job(j) for j in _pages(jobs_path, timeout_s, "jobs", raws) or [] if isinstance(j, dict)]
            success = [j for j in entry["jobs"] if j["name"] in wanted and j["status"] == "completed"
                       and j["conclusion"] == "success"]
            if success:
                arts = _pages(f"repos/{repo}/actions/runs/{entry['id']}/artifacts?per_page=100", timeout_s, "artifacts",
                              raws) or []
                entry["artifacts"] = [{k: a.get(k) for k in ("id", "name", "expired")} for a in arts
                                      if isinstance(a, dict)]
                for j in success:
                    name = f"tested-sha-{j['name']}-{entry['run_attempt']}"
                    if any(a["name"] == name and not a["expired"] for a in entry["artifacts"]):
                        entry["tested"][name] = _download(repo, entry["id"], name, timeout_s)
        runs.append(entry)
    # filter=all: every run's check-runs of H, not only the latest one per name (GitHub's default)
    check_runs = [{"id": c.get("id"), "name": c.get("name"), "app": (c.get("app") or {}).get("slug"),
                   "check_suite": (c.get("check_suite") or {}).get("id"), "status": c.get("status"),
                   "conclusion": c.get("conclusion"), "head_sha": c.get("head_sha"), "url": c.get("html_url")}
                  for c in _pages(f"repos/{repo}/commits/{head}/check-runs?filter=all&per_page=100", timeout_s,
                                  "check_runs", raws) or [] if isinstance(c, dict)]
    statuses = [{"context": s.get("context"), "state": s.get("state")}
                for s in _pages(f"repos/{repo}/commits/{head}/statuses?per_page=100", timeout_s, None, raws) or []
                if isinstance(s, dict)]
    fact = {"repo": repo, "head": head, "rules": rules, "runs": runs, "check_runs": check_runs, "statuses": statuses}
    return fact, json.dumps({"pages": raws})
