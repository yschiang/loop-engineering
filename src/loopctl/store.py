"""The run store: one current state per repo and feature, history first (D3, D4)."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from loopctl import clock
from loopctl.next import derive, unresolved

State = dict[str, Any]
Key = tuple[str, str]

SCHEMA_VERSION = 1


def home() -> Path:
    return Path(os.environ.get("LOOPCTL_HOME") or Path.home() / ".loopctl")


def run_dir(key: Key) -> Path:
    repo, feature = key
    return home() / "runs" / repo / feature


def objects_dir() -> Path:
    return home() / "objects"


def digest(value: Any) -> str:
    """sha256 of the canonical JSON of `value`."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _dump(value: Any) -> bytes:
    """The file form: sorted keys, indented."""
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode()


class RunNotFound(Exception):
    """No run directory for this repo and feature."""


class RunExists(Exception):
    """`create` found the run directory already in place."""


class RevisionConflict(Exception):
    """The state is no longer at the expected revision; re-read and redo."""


class UntrustedState(Exception):
    """The run cannot be trusted: `reason`, and the files that exist."""

    def __init__(self, reason: str, files: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.files = files


class TransitionConflict(Exception):
    """Conflicts no human has resolved yet block the run: exit 3 with the
    conflicts and the files that exist (D6)."""

    def __init__(self, conflicts: list[str], files: list[str]) -> None:
        super().__init__(", ".join(conflicts))
        self.conflicts = conflicts
        self.files = files


class TransitionRejected(Exception):
    """The content that the resolved conflict `cid` ruled out for its
    transition: exit 1, no longer Blocked (D6)."""

    def __init__(self, cid: str) -> None:
        super().__init__(cid)
        self.cid = cid


class UnknownTarget(Exception):
    """`resolves` names no unresolved conflict: exit 1 (D4 step 4)."""


class ObjectError(Exception):
    """A stored object is missing or does not match its digest: `reason`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IOFailure(OSError):
    """An OSError of the store: the operation `op` that failed, and whether
    the change was already committed when it failed (D2, D4)."""

    def __init__(self, op: str, error: OSError, *, committed: bool) -> None:
        super().__init__(error.errno, error.strerror)
        self.op = op
        self.committed = committed


class Revision(int):
    """What `commit` returns: the revision the run is at, with the state at
    that revision. `duplicate` is true when the transition was already
    committed with the same payload, so nothing was written (D4 step 3)."""

    state: State
    duplicate: bool

    def __new__(
        cls, revision: int, state: State, *, duplicate: bool = False
    ) -> Revision:
        value = super().__new__(cls, revision)
        value.state = state
        value.duplicate = duplicate
        return value


@dataclasses.dataclass
class _Progress:
    """The operation a store call is in, and whether its change is committed:
    after the history link of `commit`, or after the rename of `create`."""

    op: str
    committed: bool = False


@contextlib.contextmanager
def _reporting(op: str) -> Iterator[_Progress]:
    """Raise an OSError of the block as an IOFailure at its progress."""
    progress = _Progress(op)
    try:
        yield progress
    except IOFailure:
        raise
    except OSError as error:
        raise IOFailure(progress.op, error, committed=progress.committed) from error


def load(key: Key) -> tuple[int, State]:
    """The current (revision, state) of a run; reading never writes (D4)."""
    revision, state, _ = _read(key)
    return revision, state


def _read(key: Key, *, locked: bool = False) -> tuple[int, State, bool]:
    """`load`, and whether the state is the committed history record one
    revision ahead of feature.json. `locked` says the caller holds the
    run's lock, so no commit can change the files while they are read."""
    with _reporting("read_state"):
        return _load(key, locked)


def _load(key: Key, locked: bool) -> tuple[int, State, bool]:
    path = run_dir(key)
    if not path.is_dir():
        raise RunNotFound()

    def untrusted(reason: str) -> UntrustedState:
        return UntrustedState(reason, _files(path))

    try:
        data = (path / "feature.json").read_bytes()
    except FileNotFoundError:
        raise untrusted("state_missing") from None
    # Only init makes the lock file; no other command recreates it.
    if not (path / "lock").is_file():
        raise untrusted("lock_missing")
    try:
        state = json.loads(data)
    except ValueError:
        raise untrusted("state_corrupt") from None
    if not isinstance(state, dict):
        raise untrusted("state_corrupt")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise untrusted(f"unknown_schema:{json.dumps(state.get('schema_version'))}")
    revision = state.get("revision")
    if type(revision) is not int or revision < 1:
        raise untrusted("state_corrupt")
    history = path / "history"
    try:
        current = _intact_record((history / f"{revision}.json").read_bytes())
    except FileNotFoundError:
        raise untrusted(f"history_missing:{revision}") from None
    # Only a state the store itself recorded is trusted; any other edit of
    # feature.json or of its record is a manual edit, never a decision.
    if current is None or current["state_digest"] != digest(state):
        raise untrusted("manual_edit")
    # A commit leaves history at most one revision ahead (step 8.1); more
    # means feature.json was put back to an older revision. Never trusted,
    # never rolled back: that could revive what a later commit revoked.
    latest = _latest_revision(history)
    if latest > revision + 1:
        if not locked:
            # Read without the lock, a feature.json from before a commit and
            # the history after it look the same; decide on what is read
            # again under a shared lock, while no commit is in progress.
            with _locked(path, fcntl.LOCK_SH):
                return _load(key, True)
        raise untrusted(f"history_ahead:{latest}")
    # Committed but not yet in feature.json: the next history record that
    # follows this state is the current one. Reading never writes.
    try:
        ahead = _intact_record((history / f"{revision + 1}.json").read_bytes())
    except FileNotFoundError:
        return revision, state, False
    if ahead is None or ahead["state"].get("revision") != revision + 1:
        raise untrusted("manual_edit")
    if ahead.get("prev_digest") != digest(state):
        raise untrusted(f"history_fork:{revision + 1}")
    return revision + 1, ahead["state"], True


HISTORY_RECORD = re.compile(r"([1-9][0-9]*)\.json")


def _latest_revision(history: Path) -> int:
    """The largest revision with a record in `history`, 0 when none."""
    revisions = [
        int(match[1])
        for name in os.listdir(history)
        if (match := HISTORY_RECORD.fullmatch(name))
    ]
    return max(revisions, default=0)


def _intact_record(data: bytes) -> State | None:
    """The history record in `data` if its state matches its state_digest."""
    try:
        record = json.loads(data)
    except ValueError:
        return None
    if (
        isinstance(record, dict)
        and isinstance(record.get("state"), dict)
        and record.get("state_digest") == digest(record["state"])
    ):
        return record
    return None


def create(key: Key, transition_id: str, payload: Any, state: State) -> int:
    """Build the run beside its place, then rename it there; revision 1.

    The rename is the commit point: an OSError before it leaves no run, one
    after it leaves revision 1 in place."""
    path = run_dir(key)
    state = derive(
        {
            **state,
            "schema_version": SCHEMA_VERSION,
            "revision": 1,
            "transitions": {transition_id: _accepted(1, payload)},
        }
    )
    record = {
        "revision": 1,
        "transition_id": transition_id,
        "payload_digest": digest(payload),
        "prev_digest": None,
        "state_digest": digest(state),
        "committed_at": clock.now(),
        "state": state,
    }
    with _reporting("write_run") as progress:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=path.parent, prefix=f".tmp-{path.name}-"))
        try:
            (tmp / "history").mkdir()
            _write_new(tmp / "history" / "1.json", _dump(record))
            _write_new(tmp / "feature.json", _dump(state))
            _write_new(tmp / "lock", b"")
            _sync_dir(tmp / "history")
            _sync_dir(tmp)
            # rename would replace an empty directory; a non-empty one fails it.
            if path.exists():
                raise RunExists()
            progress.op = "rename_run"
            try:
                os.rename(tmp, path)
            except OSError as error:
                if error.errno in (errno.EEXIST, errno.ENOTEMPTY):
                    raise RunExists() from error
                raise
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        progress.op, progress.committed = "sync_run_parent", True
        _sync_dir(path.parent)
    return 1


def commit(
    key: Key,
    expected_revision: int,
    transition_id: str,
    payload: Any,
    mutate: Callable[[State], State],
    *,
    authorize: Callable[[State], None],
    resolves: str | None = None,
) -> Revision:
    """Commit `mutate` of the current state as the next revision (D4).

    `authorize` comes before any other check, and every check writes
    nothing when it fails, except that a different payload of a committed
    transition with no open conflict is recorded as one (D6). While a
    conflict is unresolved, only the transition that `resolves` it goes
    through; the payload of that transition gives the resolution's `id`
    and `choice`. Only a transition that will be written first catches a
    lagging feature.json up (step 8.1). Returns the new revision, or the
    current one when `mutate` changes nothing or when `transition_id` was
    already committed with this payload (a duplicate). An OSError is raised
    as an IOFailure that says whether the history link was already made."""
    with _reporting("read_state") as progress:
        # A missing or untrusted run fails here, before the run is locked.
        load(key)
        progress.op = "lock"
        with _locked(run_dir(key)):
            return _commit(
                key, expected_revision, transition_id, payload, mutate, authorize,
                resolves, progress,
            )


@contextlib.contextmanager
def _locked(path: Path, operation: int = fcntl.LOCK_EX) -> Iterator[None]:
    """Hold the flock of the run's existing lock file; never create it. A
    shared lock opens the file read-only."""
    flags = os.O_RDONLY if operation == fcntl.LOCK_SH else os.O_RDWR
    try:
        fd = os.open(path / "lock", flags)
    except FileNotFoundError:
        raise UntrustedState("lock_missing", _files(path)) from None
    try:
        fcntl.flock(fd, operation)
        yield
    finally:
        os.close(fd)


def _commit(
    key: Key,
    expected_revision: int,
    transition_id: str,
    payload: Any,
    mutate: Callable[[State], State],
    authorize: Callable[[State], None],
    resolves: str | None,
    progress: _Progress,
) -> Revision:
    path = run_dir(key)
    revision, state, ahead = _read(key, locked=True)  # step 1
    authorize(state)  # step 2
    accepted = state["transitions"].get(transition_id)  # step 3
    if accepted is not None:
        if accepted["payload_digest"] == digest(payload):
            return Revision(revision, state, duplicate=True)
        conflicts = state["conflicts"]
        # Content a resolution ruled out stays refused, even while a later
        # conflict on the same transition is open.
        for cid, conflict in sorted(conflicts.items()):
            if (
                conflict["transition_id"] == transition_id
                and conflict["resolved_by"] is not None
                and digest(_ruled_out(conflict)) == digest(payload)
            ):
                raise TransitionRejected(cid)
        # One open conflict per transition: until a human resolves it, any
        # other content, the same attempt included, is Blocked on it and
        # recorded nowhere. So the content a conflict keeps as committed is
        # always the one accepted when it was detected (D6).
        for cid in unresolved(state):
            if conflicts[cid]["transition_id"] == transition_id:
                raise TransitionConflict([cid], _files(path))
        cid = conflict_id(transition_id, payload)
        conflict = {
            "transition_id": transition_id,
            "committed_revision": accepted["revision"],
            "committed_payload": accepted["payload"],
            "attempted_payload": payload,
            "detected_at": clock.now(),
            "resolved_by": None,
            "choice": None,
        }
        _write(
            path, revision, state, ahead, state["transitions"],
            f"conflict:{cid}",
            {"transition_id": transition_id, "attempted": digest(payload)},
            derive({**state, "conflicts": {**conflicts, cid: conflict}}),
            progress,
        )
        raise TransitionConflict([cid], _files(path))
    blocking = unresolved(state)  # step 4
    if resolves is not None:
        if resolves not in blocking:
            raise UnknownTarget()
    elif blocking:
        raise TransitionConflict(blocking, _files(path))
    if revision != expected_revision:  # step 5
        raise RevisionConflict()
    new = mutate(copy.deepcopy(state))  # step 6
    transitions = state["transitions"]
    if resolves is not None:
        # The store's record of the resolution, before derive sees it.
        conflict = {
            **new["conflicts"][resolves],
            "resolved_by": payload["id"],
            "choice": payload["choice"],
        }
        new["conflicts"] = {**new["conflicts"], resolves: conflict}
        if conflict["choice"] == "attempted":
            # From now on the identity accepts the attempted content.
            transitions = {
                **transitions,
                conflict["transition_id"]: _accepted(
                    revision + 1, conflict["attempted_payload"]
                ),
            }
    new = derive(new)
    if new == state:
        return Revision(revision, state)
    new = _write(
        path, revision, state, ahead, transitions, transition_id, payload, new,
        progress,
    )
    return Revision(revision + 1, new)


def conflict_id(transition_id: str, payload: Any) -> str:
    """The conflict of attempting `payload` on `transition_id` (D6)."""
    text = transition_id + digest(payload)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _ruled_out(conflict: State) -> Any:
    """The content a resolved conflict ruled out for its transition (D6)."""
    if conflict["choice"] == "attempted":
        return conflict["committed_payload"]
    return conflict["attempted_payload"]


def _accepted(revision: int, payload: Any) -> State:
    """What `transitions` keeps of the content a transition accepts; the
    payload itself too, so a later conflict can show it (D6)."""
    return {"revision": revision, "payload_digest": digest(payload), "payload": payload}


def _write(
    path: Path,
    revision: int,
    state: State,
    ahead: bool,
    transitions: State,
    transition_id: str,
    payload: Any,
    new: State,
    progress: _Progress,
) -> State:
    """Commit `new` as the revision after `state` (D4 steps 7 and 8), with
    `transitions` and this transition as its bookkeeping."""
    for ref in _references(new):  # step 7
        try:
            get_object(ref)
        except ObjectError as error:
            raise UntrustedState(error.reason, _files(path)) from None
    # step 8
    if ahead:
        # 8.1: catch feature.json up with the committed record it lags
        # behind first, so history is never more than one revision ahead.
        _replace_state(path, state, progress, name="lagging_state")
    new["revision"] = revision + 1
    new["transitions"] = {
        **transitions,
        transition_id: _accepted(revision + 1, payload),
    }
    record = {
        "revision": revision + 1,
        "transition_id": transition_id,
        "payload_digest": digest(payload),
        "prev_digest": digest(state),
        "state_digest": digest(new),
        "committed_at": clock.now(),
        "state": new,
    }
    _link_history(path, revision + 1, record, progress)
    _replace_state(path, new, progress)
    return new


def put_object(data: bytes) -> str:
    """Store `data` under its sha256, write-once; returns `sha256:<hex>`."""
    hexdigest = hashlib.sha256(data).hexdigest()
    path = objects_dir() / hexdigest
    with _reporting("write_object"):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = _write_tmp(path.parent, data)
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            finally:
                os.unlink(tmp)
            _sync_dir(path.parent)
    return "sha256:" + hexdigest


OBJECT_REF = re.compile(r"sha256:([0-9a-f]{64})")


def get_object(ref: str) -> bytes:
    """The bytes stored as `ref`, checked against it."""
    match = OBJECT_REF.fullmatch(ref) if isinstance(ref, str) else None
    if match is None:
        raise ObjectError(f"object_missing:{ref}")
    with _reporting("read_object"):
        try:
            data = (objects_dir() / match[1]).read_bytes()
        except FileNotFoundError:
            raise ObjectError(f"object_missing:{ref}") from None
    if hashlib.sha256(data).hexdigest() != match[1]:
        raise ObjectError(f"object_corrupt:{ref}")
    return data


def _references(value: Any) -> Iterator[Any]:
    """Every `{"$object": d}` reference in a state, as d."""
    if isinstance(value, dict):
        if "$object" in value:
            yield value["$object"]
        for item in value.values():
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def files(key: Key) -> list[str]:
    """The files of a run, as sorted relative paths; reading never writes."""
    with _reporting("list_files"):
        return _files(run_dir(key))


def _files(path: Path) -> list[str]:
    """The files under a run directory, as sorted relative paths."""
    return sorted(
        item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()
    )


def _sync_file(fd: int) -> None:
    os.fsync(fd)
    if sys.platform == "darwin":
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_synced(fd: int, data: bytes) -> None:
    with os.fdopen(fd, "wb") as file:
        file.write(data)
        file.flush()
        _sync_file(file.fileno())


def _write_new(path: Path, data: bytes) -> None:
    _write_synced(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), data)


def _write_tmp(directory: Path, data: bytes) -> Path:
    """A synced temporary file in `directory`; removed again if that fails."""
    fd, name = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        _write_synced(fd, data)
    except BaseException:
        os.unlink(name)
        raise
    return Path(name)


def _link_history(
    path: Path, revision: int, record: State, progress: _Progress
) -> None:
    """Write-once: os.link fails if this revision is already committed.

    The link is the commit point; a failure after it leaves the revision
    committed."""
    progress.op = "write_history"
    tmp = _write_tmp(path, _dump(record))
    progress.op = "link_history"
    try:
        os.link(tmp, path / "history" / f"{revision}.json")
    except BaseException:
        os.unlink(tmp)
        raise
    progress.op, progress.committed = "sync_history", True
    os.unlink(tmp)
    _sync_dir(path / "history")


def _replace_state(
    path: Path, state: State, progress: _Progress, *, name: str = "state"
) -> None:
    """Replace feature.json with `state`; `name` names the operations."""
    progress.op = f"write_{name}"
    tmp = _write_tmp(path, _dump(state))
    progress.op = f"replace_{name}"
    try:
        os.replace(tmp, path / "feature.json")
    except BaseException:
        os.unlink(tmp)
        raise
    progress.op = f"sync_{name}"
    _sync_dir(path)


# Write-once records outside the run state (design DD-1, DD-8): numbered
# `<seq>.json` files, as the history of a run. No lock is taken yet:
# locked_dir holds nothing.


@dataclasses.dataclass(frozen=True)
class Records:
    """The records of a directory in their order, and the names of the
    files that could not be read as one."""

    items: list[dict[str, Any]]
    skipped: list[str]


class Busy(Exception):
    """Another holder has the lock of the directory (DD-8)."""


def append_record(dir: Path, payload: dict[str, Any]) -> int:
    """Write `payload` with its `seq` as the next record of `dir`, made on
    first use; returns the seq once the record is synced.

    Write-once: the record is linked into place whole, so a reader never
    sees part of it, and a number another writer took first is never
    overwritten; the next number is tried instead."""
    with _reporting("write_record"):
        dir.mkdir(parents=True, exist_ok=True)
        seq = _latest_revision(dir) + 1
        while True:
            tmp = _write_tmp(dir, _dump({**payload, "seq": seq}))
            try:
                os.link(tmp, dir / f"{seq}.json")
            except FileExistsError:
                seq += 1
                continue
            finally:
                os.unlink(tmp)
            break
        _sync_dir(dir)
    return seq


def list_records(dir: Path) -> Records:
    """The records of `dir` in the order of their seq; a file that is not a
    whole JSON object is skipped and named. No `dir` has no record."""
    with _reporting("list_records"):
        try:
            names = os.listdir(dir)
        except FileNotFoundError:
            return Records([], [])
        numbered = sorted(
            (int(match[1]), name)
            for name in names
            if (match := HISTORY_RECORD.fullmatch(name))
        )
        items: list[dict[str, Any]] = []
        skipped: list[str] = []
        for _, name in numbered:
            try:
                record = json.loads((dir / name).read_bytes())
            except ValueError:
                record = None
            if isinstance(record, dict):
                items.append(record)
            else:
                skipped.append(name)
    return Records(items, skipped)


@contextlib.contextmanager
def locked_dir(dir: Path) -> Iterator[None]:
    yield
