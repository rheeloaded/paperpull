"""Whether this Linux host can give Chrome its sandbox, asked before Chrome is.

    python -m paperpull_core.host_sandbox     one line saying what was found

Chrome's sandbox on Linux has two halves. Every page runs inside user, PID
and network namespaces of its own, which an ordinary user makes through a
user namespace, and inside a seccomp-bpf filter that limits the system calls
it may make. Chrome's setuid helper, which stands in for user namespaces, is
set up only in a container given SYS_ADMIN on a kernel with seccomp
(server/chrome.sh), and PaperPull never starts a browser without its
sandbox, so where the host cannot make a user namespace and the helper is
not set up, Chrome stops the moment it starts. On Synology DSM, whose 4.4
kernel has neither user namespaces nor seccomp, that left a black Browser
Screen and nothing saying why (#110).

So the server asks the kernel the same two questions before Chrome does, as
the user Chrome runs as, in a child process of its own so nothing here
changes this one. It is said once at the container's start (server/start.sh),
in the panel (gui/server_mode.py), by the self-test, and at a sign-in whose
Chrome did not start (paperpull_core.browser). Nothing here turns the
sandbox off or asks for less of it. It only says why it cannot start.

Without the seccomp-bpf filter Chrome does not stop by itself. It starts
with the namespace half of its sandbox and nothing limiting its system
calls, which a kernel with user namespaces and no seccomp allows once the
container's profile is removed by hand. So there the server does not start
Chrome at all (refuses_chrome), at a sign-in, in a browser of an app's own,
in the receipt renderer and in the self-test, and says why, while the panel
stays up.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
from functools import lru_cache
from typing import NamedTuple

# Where SERVER.md explains it, named in every sentence below. The first is
# about any host without user namespaces, Synology DSM the one seen so far,
# and the second, under When something is wrong, holds what to check when
# the container's profile is why.
SECTION = '"On Synology" in SERVER.md'
PROFILE_SECTION = '"Chrome does not start" in SERVER.md'

# The child's two questions. A user namespace made as Chrome makes one, the
# ids mapped and a PID and a network namespace made inside it. Then the
# seccomp-bpf filter, asked for with no filter at all, which a kernel that
# has the filter refuses with EFAULT, since it cannot read the filter, and a
# kernel without it refuses with EINVAL, since it does not know the mode.
# Nothing is installed either way, and every argument is a full-width zero
# so the missing filter is a true NULL.
_PROBE = r"""
import ctypes, json, os
out = {}
try:
    libc = ctypes.CDLL(None, use_errno=True)
    zero = ctypes.c_ulong(0)
    r = libc.prctl(ctypes.c_int(22), ctypes.c_ulong(2), zero, zero, zero)
    out["seccomp_bpf"] = 0 if r == 0 else ctypes.get_errno()
except Exception:
    out["seccomp_bpf"] = None
uid, gid = os.getuid(), os.getgid()
try:
    os.unshare(os.CLONE_NEWUSER)
    try:
        with open("/proc/self/setgroups", "w") as f:
            f.write("deny")
    except FileNotFoundError:
        pass
    with open("/proc/self/uid_map", "w") as f:
        f.write("0 %d 1" % uid)
    with open("/proc/self/gid_map", "w") as f:
        f.write("0 %d 1" % gid)
    os.unshare(os.CLONE_NEWPID | os.CLONE_NEWNET)
    out["userns"] = 0
except AttributeError:
    out["userns"] = None
except OSError as e:
    out["userns"] = e.errno or None
print(json.dumps(out))
"""


class Sandbox(NamedTuple):
    """What the host offers Chrome's sandbox.

    userns       "yes", "no" for a kernel without user namespaces, "refused"
                 when the kernel has them and this container may not make
                 one, "limit" when the host allows none, or "unknown"
    seccomp_bpf  "yes", "no" for a kernel without the filter, or "unknown"
    profile      the container's own seccomp profile, "applied", "none" for
                 a container with no profile at all, "no-kernel" for a
                 kernel without seccomp, or "unknown". Said, never judged.
    suid_helper  "yes" when Chrome's setuid helper is ready to stand in for
                 user namespaces, setuid root on a file system that honors
                 the bit, in a container holding CAP_SYS_ADMIN, else "no"
    """
    userns: str
    seccomp_bpf: str
    profile: str
    suid_helper: str = "no"


UNKNOWN = Sandbox("unknown", "unknown", "unknown")

# Chrome's setuid helper in the Chrome the container runs, which
# server/chrome.sh makes setuid root only in a container given SYS_ADMIN on
# a kernel with seccomp, and leaves without the bit everywhere else.
HELPER = "/browser/current/opt/google/chrome/chrome-sandbox"


PR_GET_NO_NEW_PRIVS = 39


def _asked_no_new_privs():
    """1 or 0, prctl(PR_GET_NO_NEW_PRIVS) for this process, or None where it
    cannot be asked."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        zero = ctypes.c_ulong(0)
        answer = libc.prctl(ctypes.c_int(PR_GET_NO_NEW_PRIVS), zero, zero, zero, zero)
    except Exception:
        return None
    return answer if answer in (0, 1) else None


def no_new_privs(status: str = "") -> bool:
    """Whether no-new-privileges holds for this process and so for what it
    starts, which has the kernel ignore every setuid bit. Asked of the
    kernel with prctl, which Linux has had since 3.5. The NoNewPrivs line of
    /proc/self/status (status, or read here), which came only in 4.10,
    later than some of the kernels the setuid helper is for, answers only
    where prctl cannot be asked."""
    asked = _asked_no_new_privs()
    if asked is not None:
        return asked == 1
    for line in str(status or _status()).splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip() == "NoNewPrivs":
            return value.strip() not in ("", "0")
    return False


def suid_helper(status: str, path: str = HELPER) -> str:
    """Whether the setuid helper is ready, "yes" or "no". It needs its bit,
    root as its owner, a file system that does not ignore the bit, and
    CAP_SYS_ADMIN, bit 21 of CapBnd in status, to make the sandbox's
    namespaces. no-new-privileges has the kernel ignore the bit, so the
    helper never runs as root under it (measured with Chrome 155, whose
    sandbox then does not start)."""
    caps = ""
    for line in str(status or "").splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip() == "CapBnd":
            caps = value.strip()
    if no_new_privs(status):
        return "no"
    try:
        admin = bool((int(caps, 16) >> 21) & 1)
        st = os.stat(path)
        honored = not os.statvfs(path).f_flag & os.ST_NOSUID
    except (ValueError, OSError, AttributeError):
        return "no"
    setuid_root = st.st_uid == 0 and bool(st.st_mode & stat.S_ISUID)
    return "yes" if admin and honored and setuid_root else "no"


def stands_in(found: Sandbox) -> bool:
    """Whether the setuid helper gives Chrome its whole sandbox in place of
    user namespaces, which it does only beside the seccomp-bpf filter."""
    return found.suid_helper == "yes" and found.seccomp_bpf == "yes"


def read(probe: dict, status: str) -> Sandbox:
    """What the child found and /proc/self/status says, read into a Sandbox.
    probe holds the errno each question ended with, 0 for none, or None
    when it could not be asked."""
    probe = probe if isinstance(probe, dict) else {}
    found = probe.get("userns")
    if found == 0:
        userns = "yes"
    elif found == errno.EINVAL:
        # unshare refuses a flag the kernel was built without.
        userns = "no"
    elif found in (errno.EPERM, errno.EACCES):
        # Docker's own profile refuses it to a container without
        # CAP_SYS_ADMIN, as does a host that keeps user namespaces from
        # ordinary users.
        userns = "refused"
    elif found in (errno.ENOSPC, errno.EUSERS):
        userns = "limit"
    else:
        userns = "unknown"

    fields = {}
    for line in str(status or "").splitlines():
        name, sep, value = line.partition(":")
        if sep:
            fields[name.strip()] = value.strip()

    bpf = probe.get("seccomp_bpf")
    if bpf == errno.EFAULT or bpf == 0:
        seccomp_bpf = "yes"
    elif bpf == errno.EINVAL:
        seccomp_bpf = "no"
    elif "Seccomp_filters" in fields:
        # Written only by a kernel with the filter, from 5.9 on.
        seccomp_bpf = "yes"
    elif status and "Seccomp" not in fields:
        # No Seccomp line at all is a kernel built without seccomp.
        seccomp_bpf = "no"
    else:
        seccomp_bpf = "unknown"

    mode = fields.get("Seccomp")
    if mode is None:
        profile = "no-kernel" if status else "unknown"
    elif mode == "0":
        profile = "none"
    elif mode in ("1", "2"):
        profile = "applied"
    else:
        profile = "unknown"
    return Sandbox(userns, seccomp_bpf, profile)


def stops_chrome(found: Sandbox) -> bool:
    """Whether what was found stops Chrome before it opens a window. With no
    user namespace to be had it ends at once, measured with Chrome 154 in
    the server image. Without seccomp-bpf alone it still starts, with the
    namespace half of its sandbox only, which refuses_chrome is for. A
    ready setuid helper beside the filter stands in for user namespaces."""
    if stands_in(found):
        return False
    return found.userns in ("no", "refused", "limit")


def refuses_chrome(found: Sandbox) -> bool:
    """Whether the server must not start Chrome at all, since it would start
    with half its sandbox. A kernel without the seccomp-bpf filter lets
    Chrome run with its namespaces and nothing limiting its system calls,
    and the setuid helper never makes up for it (stands_in asks for the
    filter). A host that could not be told is not refused."""
    return found.seccomp_bpf == "no" and not stands_in(found)


def problem(found: Sandbox) -> str:
    """Why Chrome's sandbox cannot start on this host, in a sentence, or ""
    when nothing found stands in its way."""
    if stands_in(found):
        return ""
    end = ("so Chrome's sandbox cannot start here, and PaperPull will not start "
           "Chrome without it. Sign-in windows cannot open on this host. See %s." % SECTION)
    if found.userns == "no":
        if found.seccomp_bpf == "no":
            return "This host's kernel has no user namespaces and no seccomp-bpf filter, " + end
        return "This host's kernel has no user namespaces, " + end
    if found.userns == "limit":
        return ("This host allows no user namespaces (user.max_user_namespaces is 0), "
                + end)
    if found.userns == "refused":
        return ("This container may not make user namespaces, so Chrome's sandbox cannot "
                "start, and PaperPull will not start Chrome without it. Usually the security "
                "profile seccomp-chrome.json is not applied. See %s." % PROFILE_SECTION)
    if found.seccomp_bpf == "no":
        return ("This host's kernel has no seccomp-bpf filter, the other half of Chrome's "
                "sandbox, so Chrome would run with only half its sandbox here, and PaperPull "
                "will not start Chrome that way. Sign-in windows cannot open on this host. "
                "See %s." % SECTION)
    return ""


def _status() -> str:
    try:
        with open("/proc/self/status", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def probe() -> dict:
    """The child's answers, or {} when it could not be run."""
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _PROBE], capture_output=True,
                              text=True, timeout=20, stdin=subprocess.DEVNULL)
        answer = json.loads(done.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {}
    return answer if isinstance(answer, dict) else {}


@lru_cache(maxsize=1)
def check() -> Sandbox:
    """What this host offers Chrome's sandbox, asked once per process. Off
    Linux there is nothing to ask, and nothing is said."""
    if not sys.platform.startswith("linux"):
        return UNKNOWN
    status = _status()
    return read(probe(), status)._replace(suid_helper=suid_helper(status))


# Said after the rest, never a problem by itself. A container with no
# profile has Docker's guard on its system calls off altogether, which
# Chrome does not need and is worth knowing.
_PROFILE_SAID = {
    "none": " The container runs with no seccomp profile at all.",
    "no-kernel": " The kernel has no seccomp, so the container runs with no seccomp profile.",
}


def line(found: Sandbox) -> str:
    """The one line the container's log carries at its start."""
    said = problem(found)
    if not said and found.userns == "yes" and found.seccomp_bpf == "yes":
        said = ("This host can give Chrome its sandbox, user namespaces and seccomp-bpf "
                "both work here.")
    elif not said and stands_in(found):
        said = ("This host can give Chrome its sandbox, Chrome's setuid helper in place of "
                "user namespaces, and seccomp-bpf.")
    elif not said:
        said = ("Whether this host can give Chrome its sandbox could not be told (user "
                "namespaces %s, seccomp-bpf %s)." % (found.userns, found.seccomp_bpf))
    return "[sandbox] " + said + _PROFILE_SAID.get(found.profile, "")


def main() -> int:
    found = check()
    print(line(found), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
