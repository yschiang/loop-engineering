"""Task 1.9 (DR-01): real macOS Seatbelt negative probes, direct and via grandchild (no runtime)."""

import subprocess
import sys

import pytest

from delivery.sandbox import Boundary, Probe, run_suite

pytestmark = [pytest.mark.os, pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt launcher")]

# /usr/local/bin/git on this host is an x86_64 build that cannot exec under Seatbelt ("Bad CPU type");
# probes pin Apple's /usr/bin/git so a denial is attributable to the boundary, not the binary.
GIT = "/usr/bin/git"
GRANDCHILD = "import subprocess,sys; sys.exit(subprocess.run(['/bin/sh','-c',sys.argv[1]]).returncode)"


def both(name, shell, expect, effect_check=None):
    return [Probe(f"{name}:direct", ("/bin/sh", "-c", shell), expect, effect_check),
            Probe(f"{name}:grandchild", (sys.executable, "-c", GRANDCHILD, shell), expect, effect_check)]


@pytest.fixture
def layout(tmp_path):
    t = tmp_path.resolve()
    ctl = t / "author"
    subprocess.run(["git", "init", "-q", str(ctl)], check=True)
    subprocess.run(["git", "-C", str(ctl), "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "base"], check=True)
    remote = ctl / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    dirs = {k: t / k for k in ("delivery", "features", "other_attempt", "clone", "rt", "inbox", "cred")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    (dirs["cred"] / "hosts.yml").write_text("oauth_token: fake\n")
    subprocess.run(["git", "clone", "-q", str(ctl), str(dirs["clone"] / "w")], check=True)
    boundary = Boundary(allow_write=(dirs["clone"], dirs["rt"], dirs["inbox"]),
                        deny_write=(ctl, dirs["delivery"], dirs["features"], dirs["other_attempt"]),
                        deny_read=(dirs["cred"],))
    probes = (both("write_author_worktree", f"echo x > {ctl}/f", "denied")
              + both("update_ref_author", f"{GIT} -C {ctl} update-ref refs/heads/evil HEAD", "denied")
              + both("write_run_json", f"echo x > {dirs['delivery']}/run.json", "denied")
              + both("write_authority", f"echo x > {dirs['features']}/authority.json", "denied")
              + both("write_blobs", f"mkdir -p {dirs['delivery']}/blobs && echo x > {dirs['delivery']}/blobs/x",
                     "denied")
              + both("write_other_attempt", f"echo x > {dirs['other_attempt']}/result.json", "denied")
              + both("write_other_attempt_clone", f"mkdir -p {dirs['other_attempt']}/clone && "
                     f"echo x > {dirs['other_attempt']}/clone/f", "denied")
              + both("read_credential", f"cat {dirs['cred']}/hosts.yml", "denied")
              # git reports "unable to create temporary object directory", not EPERM: judge by effect.
              + both("push_to_author_remote", f"{GIT} -C {dirs['clone']}/w push -q {remote} HEAD:refs/heads/x",
                     "denied", (GIT, "-C", str(remote), "rev-parse", "-q", "--verify", "refs/heads/x"))
              + both("write_own_clone", f"echo x > {dirs['clone']}/w/f", "allowed")
              + both("write_own_inbox", f"echo x > {dirs['inbox']}/result.json", "allowed"))
    return boundary, probes


def test_full_boundary_denies_every_forbidden_probe_and_allows_own_dirs(layout):
    boundary, probes = layout
    report = run_suite(boundary, probes, required=[p.name for p in probes])
    failed = [r for r in report.results if r["outcome"] != r["expect"]]
    assert failed == []
    assert report.status == "verified"
    assert report.launcher == "sandbox-exec" and len(report.profile_digest) == 64


def test_missing_deny_rule_makes_report_unverified(layout):
    boundary, probes = layout
    weak = Boundary(boundary.allow_write, boundary.deny_write[1:], boundary.deny_read)  # author repo writable
    report = run_suite(weak, probes, required=[p.name for p in probes])
    assert report.status == "unverified"
    assert any(r["name"] == "write_author_worktree:grandchild" and r["outcome"] == "allowed"
               for r in report.results)


def test_required_probe_not_run_keeps_report_unverified(layout):
    boundary, probes = layout
    report = run_suite(boundary, probes, required=[p.name for p in probes] + ["gh_auth_token:direct"])
    assert report.status == "unverified"
