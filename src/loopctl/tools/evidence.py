"""Git reads and the bounded evidence command (design §7, §8; T3.1).

History is only read here, except for what G1 itself needs: a snapshot commit with its
keep-alive ref (`evidence red`), and the temporary detached checkout of `evidence green` /
replay (`worktree add --detach`, removed afterwards). The evidence command runs in its own
process group; at the time limit the whole group is killed.
"""

import contextlib
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

# The snapshot commit is loopctl's, not the worker's; nothing depends on the user's git identity.
_IDENTITY = {
    "GIT_AUTHOR_NAME": "loopctl", "GIT_AUTHOR_EMAIL": "loopctl@localhost",
    "GIT_COMMITTER_NAME": "loopctl", "GIT_COMMITTER_EMAIL": "loopctl@localhost",
}


class GitError(Exception):
    pass


def _git(repo: str | Path, args: list[str], timeout_s: float, env: dict[str, str] | None = None,
         ok: tuple[int, ...] = (0,)) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=timeout_s, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {' '.join(args)}: {e}") from e
    if done.returncode not in ok:
        raise GitError(f"git {' '.join(args)} exited {done.returncode}: {done.stderr.strip()}")
    return done.returncode, done.stdout


def git(repo: str | Path, timeout_s: float, *args: str) -> str:
    return _git(repo, list(args), timeout_s)[1].strip()


def toplevel(cwd: Path, timeout_s: float) -> str | None:
    try:
        return git(cwd, timeout_s, "rev-parse", "--show-toplevel")
    except GitError:
        return None


def rev_parse(repo: str, rev: str, timeout_s: float) -> str | None:
    try:
        return git(repo, timeout_s, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    except GitError:
        return None


def tree_of(repo: str, rev: str, timeout_s: float) -> str | None:
    try:
        return git(repo, timeout_s, "rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}")
    except GitError:
        return None


def is_ancestor(repo: str, older: str, newer: str, timeout_s: float) -> bool:
    """older == newer counts (git merge-base --is-ancestor)."""
    code, _ = _git(repo, ["merge-base", "--is-ancestor", older, newer], timeout_s, ok=(0, 1))
    return code == 0


def parents(repo: str, commit: str, timeout_s: float) -> list[str]:
    return git(repo, timeout_s, "rev-list", "--parents", "-n", "1", commit).split()[1:]


def changed(repo: str, a: str, b: str, timeout_s: float) -> list[str]:
    """Paths whose content differs between two commits or trees (no rename detection)."""
    out = _git(repo, ["diff", "--no-renames", "--name-only", "-z", a, b], timeout_s)[1]
    return sorted(p for p in out.split("\0") if p)


def show(repo: str, rev: str, path: str, timeout_s: float) -> str | None:
    """The file at rev, or None when the path does not exist there."""
    code, out = _git(repo, ["cat-file", "-p", f"{rev}:{path}"], timeout_s, ok=(0, 128))
    return out if code == 0 else None


def blob(repo: str, rev: str, path: str, timeout_s: float) -> str | None:
    code, out = _git(repo, ["rev-parse", "--verify", "--quiet", f"{rev}:{path}"], timeout_s, ok=(0, 1, 128))
    return out.strip() if code == 0 else None


def merge_base(repo: str, a: str, b: str, timeout_s: float) -> str:
    return git(repo, timeout_s, "merge-base", a, b)


def rev_list(repo: str, include: list[str], exclude: list[str], timeout_s: float) -> list[str]:
    args = ["rev-list", *include, "--not", *exclude] if exclude else ["rev-list", *include]
    return git(repo, timeout_s, *args).split()


def merge_tree(repo: str, head: str, base_tip: str, timeout_s: float) -> tuple[str, list[str]]:
    """(automatic merge tree, conflicted paths) from `git merge-tree --write-tree` (git ≥ 2.38)."""
    code, out = _git(repo, ["merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", head, base_tip],
                     timeout_s, ok=(0, 1))
    fields = [f for f in out.split("\0") if f]
    if not fields:
        raise GitError("merge-tree wrote no tree")
    return fields[0], sorted(set(fields[1:])) if code == 1 else []


def worktree_tree(worktree: str, timeout_s: float) -> tuple[str, str]:
    """(HEAD, tree of the worktree as it is now): HEAD plus every change, untracked non-ignored
    files included, except loopctl's own `.loopctl/` result location. Built in a temporary
    index; the worktree's own index is not touched."""
    head = git(worktree, timeout_s, "rev-parse", "HEAD")
    fd, index = tempfile.mkstemp(prefix="loopctl-index-")
    os.close(fd)
    os.unlink(index)
    env = {**os.environ, "GIT_INDEX_FILE": index}
    try:
        _git(worktree, ["read-tree", "HEAD"], timeout_s, env=env)
        _git(worktree, ["add", "-A", "--", ".", ":(exclude).loopctl"], timeout_s, env=env)
        return head, _git(worktree, ["write-tree"], timeout_s, env=env)[1].strip()
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(index)


def worktree_changes(worktree: str, since: str, timeout_s: float) -> tuple[str, list[str]]:
    """(HEAD, paths changed since `since`): the commits since then plus what `worktree_tree`
    records on top of HEAD — the same change set G1 scope-checks (snapshot and range)."""
    head, tree = worktree_tree(worktree, timeout_s)
    return head, sorted(set(changed(worktree, since, head, timeout_s)) | set(changed(worktree, since, tree, timeout_s)))


def snapshot(worktree: str, ref: str, message: str, timeout_s: float) -> dict[str, str]:
    """Record the worktree as it is now (`worktree_tree`). A clean worktree is HEAD itself;
    otherwise a commit whose only parent is HEAD. `ref` keeps it alive for G1."""
    head, tree = worktree_tree(worktree, timeout_s)
    commit = head
    if tree != git(worktree, timeout_s, "rev-parse", "HEAD^{tree}"):
        env = {**os.environ, **_IDENTITY}
        commit = _git(worktree, ["commit-tree", tree, "-p", head, "-m", message], timeout_s, env=env)[1].strip()
    git(worktree, timeout_s, "update-ref", ref, commit)
    return {"commit": commit, "tree": tree, "parent": head, "ref": ref}


def add_checkout(repo: str, path: Path, rev: str, timeout_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, timeout_s, "worktree", "add", "--detach", str(path), rev)


def remove_checkout(repo: str, path: Path, timeout_s: float) -> bool:
    """True when the checkout is gone; False leaves it for a human (design §7)."""
    try:
        git(repo, timeout_s, "worktree", "remove", "--force", str(path))
    except GitError:
        return False
    return not path.exists()


def run_command(argv: list[str], cwd: str, timeout_s: float) -> dict[str, Any]:
    """Run argv (no shell) in its own process group within timeout_s. At the limit the whole
    group is killed; the output so far is kept (truncated by the kill)."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
        except OSError as e:
            return {"exit": None, "timed_out": False, "elapsed_s": 0.0, "stdout": b"",
                    "stderr": str(e).encode(), "spawn_error": True}
        timed_out = False
        try:
            code: int | None = proc.wait(timeout=max(timeout_s, 0.0))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            code = None
        elapsed = time.monotonic() - started
        out.seek(0)
        err.seek(0)
        return {"exit": code, "timed_out": timed_out, "elapsed_s": round(elapsed, 3), "stdout": out.read(),
                "stderr": err.read(), "spawn_error": False}


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)  # the leader's pgid is its pid (start_new_session)
    proc.wait()
