"""Task 1.9 (design §10.4): keychain and `gh auth token` denial, against synthetic credentials only.

Outputs are discarded inside the probe shell; only exit status is recorded, so no secret is captured.
"""

import shutil
import subprocess
import sys

import pytest

from delivery.sandbox import Boundary, Probe, run_suite

pytestmark = [pytest.mark.os, pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt launcher")]
KEYCHAIN_SERVICES = ("com.apple.SecurityServer", "com.apple.securityd.xpc")


@pytest.fixture
def creds(tmp_path):
    t = tmp_path.resolve()
    kc = t / "probe.keychain-db"
    subprocess.run(["security", "create-keychain", "-p", "probe-pw", str(kc)], check=True)
    subprocess.run(["security", "unlock-keychain", "-p", "probe-pw", str(kc)], check=True)
    subprocess.run(["security", "add-generic-password", "-a", "probe", "-s", "orca-probe", "-w", "synthetic",
                    str(kc)], check=True)
    gh_dir = t / "gh"
    gh_dir.mkdir()
    (gh_dir / "hosts.yml").write_text("github.com:\n    oauth_token: synthetic-token\n    user: probe\n"
                                      "    git_protocol: https\n")
    yield kc, gh_dir
    subprocess.run(["security", "delete-keychain", str(kc)], check=False)


def probes(kc, gh_dir):
    keychain = f"security find-generic-password -a probe -s orca-probe {kc} >/dev/null 2>&1"
    gh = f"GH_CONFIG_DIR={gh_dir} GH_TOKEN= GITHUB_TOKEN= gh auth token --hostname github.com >/dev/null 2>&1"
    out = [Probe("keychain_item:direct", ("/bin/sh", "-c", keychain), "denied", control=True)]
    if shutil.which("gh"):
        out.append(Probe("gh_auth_token:direct", ("/bin/sh", "-c", gh), "denied", control=True))
    return out


def test_credential_probes_denied_while_control_succeeds(creds, tmp_path):
    kc, gh_dir = creds
    if not shutil.which("gh"):
        pytest.fail("gh CLI is required for the design 10.4 gh auth token probe")
    b = Boundary(allow_write=(tmp_path / "clone",), deny_write=(), deny_read=(gh_dir, kc),
                 deny_services=KEYCHAIN_SERVICES)
    p = probes(kc, gh_dir)
    report = run_suite(b, p, required=[x.name for x in p])
    assert [(r["name"], r["outcome"]) for r in report.results] == [
        ("keychain_item:direct", "denied"), ("gh_auth_token:direct", "denied")]
    assert report.status == "verified"


def test_probe_is_inconclusive_when_control_cannot_reach_the_credential(tmp_path):
    missing = tmp_path / "none.keychain-db"
    p = [Probe("keychain_item:direct", ("/bin/sh", "-c", f"security find-generic-password -s x {missing} >/dev/null"),
               "denied", control=True)]
    report = run_suite(Boundary((), (), (), ()), p, required=["keychain_item:direct"])
    assert report.results[0]["outcome"] == "inconclusive"
    assert report.status == "unverified"


def test_missing_keychain_rule_is_detected(creds, tmp_path):
    kc, gh_dir = creds
    weak = Boundary(allow_write=(tmp_path / "clone",), deny_write=(), deny_read=(gh_dir,), deny_services=())
    p = probes(kc, gh_dir)[:1]
    report = run_suite(weak, p, required=[x.name for x in p])
    assert report.results[0]["outcome"] == "allowed"
    assert report.status == "unverified"
