"""The host check counts Chrome's setuid helper as standing in for user
namespaces, and only where the whole sandbox is still there.

server/chrome.sh makes the helper setuid root in a container given
SYS_ADMIN on a kernel with seccomp. The host check then has to say Chrome
can have its sandbox, or the panel, the container's log and a sign-in would
all say sign-in windows cannot open on a host where they do. And without
the seccomp-bpf filter the helper gives only half the sandbox, so it never
stands in there (a Synology DiskStation, kernel 4.4.302+, measured layer 1
SUID with seccomp off). Without the filter the server starts no Chrome at
all, helper or not (refuses_chrome).
"""
import os
import stat
import sys
from types import SimpleNamespace

import pytest

from paperpull_core import host_sandbox as hs

ADMIN = "CapBnd:\t00000000a82425fb\n"     # CAP_SYS_ADMIN, bit 21, held
NO_ADMIN = "CapBnd:\t00000000a80425fb\n"  # Docker's default set


def found(userns="no", seccomp_bpf="yes", suid_helper="yes"):
    return hs.Sandbox(userns, seccomp_bpf, "applied", suid_helper)


def test_a_ready_helper_beside_the_filter_stands_in():
    assert hs.stands_in(found())
    assert hs.problem(found()) == ""
    assert not hs.stops_chrome(found())
    assert "setuid helper in place of user namespaces" in hs.line(found())


@pytest.mark.parametrize("userns", ["no", "limit", "refused"])
def test_without_the_filter_the_helper_is_no_stand_in(userns):
    half = found(userns=userns, seccomp_bpf="no")
    assert not hs.stands_in(half)
    assert hs.problem(half)
    assert hs.stops_chrome(half)
    assert hs.refuses_chrome(half)


@pytest.mark.parametrize("userns", ["yes", "unknown"])
def test_a_ready_helper_without_the_filter_is_refused_where_chrome_would_start(userns):
    """With user namespaces Chrome would start with half its sandbox, the
    helper ready or not, so the server refuses it before it starts."""
    half = found(userns=userns, seccomp_bpf="no")
    assert not hs.stands_in(half) and not hs.stops_chrome(half)
    assert hs.refuses_chrome(half)
    assert "no seccomp-bpf filter" in hs.problem(half)


def test_a_ready_helper_beside_the_filter_is_never_refused():
    assert not hs.refuses_chrome(found())
    assert not hs.refuses_chrome(found(seccomp_bpf="unknown"))


def test_without_a_ready_helper_nothing_changes():
    plain = found(suid_helper="no")
    assert not hs.stands_in(plain)
    assert "no user namespaces" in hs.problem(plain)
    assert hs.stops_chrome(plain)
    # Three fields, as every other caller writes it, mean no helper.
    assert hs.Sandbox("no", "yes", "applied").suid_helper == "no"
    assert hs.UNKNOWN.suid_helper == "no"


@pytest.fixture
def helper_file(monkeypatch):
    """A helper whose owner, mode and file system the test chooses."""
    state = {"uid": 0, "mode": stat.S_IFREG | stat.S_ISUID | 0o755, "flag": 0}
    # hs.os is the os module itself, so pytest's own reporting calls this
    # too, with follow_symlinks, when a test here fails.
    monkeypatch.setattr(hs.os, "stat",
                        lambda path, **_: SimpleNamespace(st_uid=state["uid"], st_mode=state["mode"]))
    monkeypatch.setattr(hs.os, "statvfs", lambda path: SimpleNamespace(f_flag=state["flag"]),
                        raising=False)
    monkeypatch.setattr(hs.os, "ST_NOSUID", 2, raising=False)
    # The kernel is not asked, so the status text decides, as where prctl
    # cannot be asked.
    monkeypatch.setattr(hs, "_asked_no_new_privs", lambda: None)
    return state


def test_a_setuid_root_helper_with_the_capability_is_ready(helper_file):
    assert hs.suid_helper(ADMIN) == "yes"


def test_the_helper_is_ready_where_new_privileges_are_allowed(helper_file):
    assert hs.suid_helper("NoNewPrivs:\t0\n" + ADMIN) == "yes"


@pytest.mark.parametrize("asked,ready", [(1, "no"), (0, "yes")])
def test_the_kernels_own_answer_comes_first(helper_file, monkeypatch, asked, ready):
    """/proc/self/status has a NoNewPrivs line only from Linux 4.10, and a
    kernel without user namespaces, the one the helper is for, may be older.
    prctl answers on every kernel since 3.5, so its answer decides."""
    monkeypatch.setattr(hs, "_asked_no_new_privs", lambda: asked)
    assert hs.suid_helper(ADMIN) == ready
    assert hs.suid_helper("NoNewPrivs:\t%d\n" % (1 - asked) + ADMIN) == ready


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="asks a Linux kernel")
def test_prctl_says_what_the_status_line_says():
    line = [l for l in hs._status().splitlines() if l.startswith("NoNewPrivs:")]
    asked = hs._asked_no_new_privs()
    assert asked in (0, 1)
    if line:
        assert asked == int(line[0].split(":")[1])
    assert hs.no_new_privs() == (asked == 1)


@pytest.mark.parametrize("change", ["no capability", "no CapBnd", "not root", "no bit", "nosuid",
                                    "no new privileges"])
def test_anything_less_is_not_ready(helper_file, change):
    """no-new-privileges has the kernel ignore the setuid bit, and Chrome 155's
    sandbox did not start under it in a container given SYS_ADMIN, with the
    helper setuid root and user namespaces refused (measured 2026-10-19)."""
    status = {"no capability": NO_ADMIN, "no CapBnd": "Name:\tpython\n",
              "no new privileges": "NoNewPrivs:\t1\n" + ADMIN}.get(change, ADMIN)
    if change == "not root":
        helper_file["uid"] = 1000
    if change == "no bit":
        helper_file["mode"] = stat.S_IFREG | 0o755
    if change == "nosuid":
        helper_file["flag"] = 2
    assert hs.suid_helper(status) == "no"


def test_a_missing_helper_is_not_ready(monkeypatch):
    def missing(path, **_):
        raise FileNotFoundError(path)
    monkeypatch.setattr(hs.os, "stat", missing)
    assert hs.suid_helper(ADMIN) == "no"


def test_the_helper_asked_about_is_the_one_chrome_sh_sets():
    script = (os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    chrome_sh = open(os.path.join(script, "server", "chrome.sh"), encoding="utf-8").read()
    assert hs.HELPER == "/browser/current/opt/google/chrome/chrome-sandbox"
    assert 'BROWSER=/browser' in chrome_sh and "/opt/google/chrome/chrome-sandbox" in chrome_sh
