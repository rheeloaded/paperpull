"""Finding a newer PaperPull, and on a Mac installing it.

WHAT THIS DOES

    check      ask GitHub for the newest release and say whether it is newer
    install    download that release's disk image, prove it is the file
               GitHub published and the app the same publisher signed, and
               put the new app beside the old one, ready
    restart    hand the swap to a small script that waits for this panel to
               exit, replaces the app and opens it again

Only the Mac bundle installs itself. Every other copy (Windows, a checkout, a
Python someone runs by hand) is told a new version exists and is sent to the
release page, because replacing a running program there is a different job
with different ways to go wrong, and it is not tested here.

WHAT IT WILL NOT DO

Contact anything on its own. Nothing here runs at launch or in the
background: the only requests are the ones the person starts, by pressing
Check github.com for an update and then Update now, and the check stays off
until they turn it on in Settings (gui/app.py). The Microsoft Store edition
updates through the Store and PaperPull Server through docker compose pull,
so neither is offered any of this (offered).

Trust nothing it was not given. The release is read from GitHub's API over
TLS. The disk image is fetched only from this project's own release
downloads and must match the SHA-256 GitHub records for that asset. The app
inside it must pass codesign and Gatekeeper and carry the same Team ID as the
app already running, so a disk image swapped on the way, or a release made by
somebody else, is refused. A copy that is not signed at all (one built on
this Mac for testing) is never replaced.

THE SWAP

The new app is staged next to the installed one, so putting it in place is two
renames on one volume. The old app is kept until the new one is in place and
put back if anything fails. The staged app's signature and publisher are
checked again just before the swap, so nothing changed while it waited is
put in place. The script outlives this process (it is started in
a session of its own) and writes what it did to
~/Library/Logs/PaperPull/update.log.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from paperpull_core.urls import is_safe_url

REPO = "rheeloaded/paperpull"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
DOWNLOAD_PREFIX = "https://github.com/%s/releases/download/" % REPO
RELEASE_PAGE = "https://github.com/%s/releases/tag/" % REPO

# How long a check stays good, so opening the panel ten times a day asks once.
# A disk image is about 135 MB. Anything past this is not one of ours.
MAX_DMG = 1024 * 1024 * 1024
NOTES_SHOWN = 4000

_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_TAG = re.compile(r"^v\d{1,4}\.\d{1,4}\.\d{1,4}$")
_DMG = re.compile(r"^PaperPull-\d{1,4}\.\d{1,4}\.\d{1,4}-(arm64|x86_64)\.dmg$")
# The hosts a request or a redirect may reach, each exactly. The release
# list is api.github.com, a disk image's address is github.com, and GitHub
# serves its bytes from release-assets.githubusercontent.com (measured on
# v0.63.0), objects.githubusercontent.com before that. Not any other host
# under githubusercontent.com, which also serves anybody's raw files.
_HOSTS = ("github.com", "api.github.com",
          "release-assets.githubusercontent.com", "objects.githubusercontent.com")
# macOS keeps its root certificates here, the ones its own curl trusts. The
# Python inside the app is python-build-standalone's, which is not sure to
# find them by itself, so they are added to whatever it finds.
_MAC_ROOTS = "/etc/ssl/cert.pem"


class UpdateError(Exception):
    """Something the person can be told in a sentence."""


# -- versions ---------------------------------------------------------------

def parse_version(text) -> Optional[tuple]:
    m = _VERSION.match(str(text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(latest, current) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


# -- where this copy lives --------------------------------------------------

def bundle_path(gui_dir: Optional[Path] = None) -> Optional[Path]:
    """The PaperPull.app this panel is running from, or None when it is not
    running from one. gui/ sits in Contents/Resources of the bundle."""
    if sys.platform != "darwin":
        return None
    here = Path(gui_dir or Path(__file__).resolve().parent)
    res = here.parent
    contents = res.parent
    app = contents.parent
    if (res.name == "Resources" and contents.name == "Contents"
            and app.suffix == ".app" and (contents / "Info.plist").is_file()):
        return app
    return None


def offered(executable: Optional[str] = None) -> bool:
    """Whether this copy should offer the check at all. The Store edition
    runs from a Microsoft Store package and updates through the Store. A
    copy that cannot tell is not offered it."""
    try:
        from paperpull_core.browser import _in_a_store_package
    except ImportError:
        return False
    return not _in_a_store_package(executable or sys.executable)


def architecture() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def can_install(app: Optional[Path]) -> tuple[bool, str]:
    """Whether this copy can replace itself, and if not, why."""
    if app is None:
        return False, "This copy was not installed from the Mac disk image."
    if not os.access(app.parent, os.W_OK):
        return False, ("PaperPull is in a folder this account cannot change. "
                       "Download the new disk image and drag it over the old one.")
    if not _team_id(app):
        return False, ("This copy is not signed, so it cannot tell that an "
                       "update is from the same publisher.")
    return True, ""


# -- talking to GitHub ------------------------------------------------------

def _host_ok(url: str) -> bool:
    """An https address on one of GitHub's hosts, read the way the shared
    check reads every address (paperpull_core.urls)."""
    return is_safe_url(url, _HOSTS, subdomains=False)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_ok(newurl):
            raise urllib.error.URLError("redirected somewhere that is not GitHub")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _tls() -> ssl.SSLContext:
    """Certificates checked as always, with the Mac's own roots added."""
    ctx = ssl.create_default_context()
    if sys.platform == "darwin" and os.path.isfile(_MAC_ROOTS):
        try:
            ctx.load_verify_locations(cafile=_MAC_ROOTS)
        except (OSError, ssl.SSLError):
            pass
    return ctx


def _open(url: str, timeout: float = 20):
    if not _host_ok(url):
        raise UpdateError("refusing to fetch from somewhere that is not GitHub")
    opener = urllib.request.build_opener(_Redirects, urllib.request.HTTPSHandler(context=_tls()))
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "PaperPull-update-check"})
    return opener.open(req, timeout=timeout)


# What a request can end in besides an answer: refused, cut short, timed out.
_NET_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError)


def fetch_json(url: str) -> dict:
    """GitHub's answer as a dict. Replaced in tests."""
    try:
        with _open(url) as r:
            raw = r.read(2 * 1024 * 1024 + 1)
    except _NET_ERRORS as e:
        raise UpdateError("could not reach GitHub: %s" % getattr(e, "reason", e))
    if len(raw) > 2 * 1024 * 1024:
        raise UpdateError("GitHub's answer was larger than expected")
    try:
        data = json.loads(raw)
    except ValueError:
        raise UpdateError("GitHub's answer was not understood")
    if not isinstance(data, dict):
        raise UpdateError("GitHub's answer was not understood")
    return data


def read_release(data: dict, arch: Optional[str] = None) -> dict:
    """What matters in a release, checked. The disk image is None unless it
    is this project's, for this Mac, and GitHub recorded a SHA-256 for it."""
    arch = arch or architecture()
    tag = str(data.get("tag_name") or "")
    if not _TAG.match(tag) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("the newest release is not a version number")
    version = tag[1:]
    want = "PaperPull-%s-%s.dmg" % (version, arch)
    asset = None
    for a in data.get("assets") or []:
        if not isinstance(a, dict) or a.get("name") != want or not _DMG.match(want):
            continue
        digest = str(a.get("digest") or "")
        url = str(a.get("browser_download_url") or "")
        size = a.get("size")
        if (digest.startswith("sha256:") and re.fullmatch(r"[0-9a-f]{64}", digest[7:])
                and url == DOWNLOAD_PREFIX + tag + "/" + want
                and isinstance(size, int) and 0 < size <= MAX_DMG):
            asset = {"name": want, "url": url, "size": size, "sha256": digest[7:]}
        break
    return {"version": version, "tag": tag, "page": RELEASE_PAGE + tag,
            "published": str(data.get("published_at") or "")[:10],
            "notes": str(data.get("body") or "")[:NOTES_SHOWN], "asset": asset}


def check_latest(current: str, arch: Optional[str] = None) -> dict:
    """The newest release, and whether it is newer than `current`."""
    rel = read_release(fetch_json(API_LATEST), arch)
    rel["newer"] = is_newer(rel["version"], current)
    return rel


# -- downloading ------------------------------------------------------------

def download(asset: dict, dest: Path, progress: Callable[[int, int], None] = None) -> None:
    """The asset's bytes into `dest`, only if they are the bytes GitHub said."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    got = 0
    try:
        with _open(asset["url"], timeout=30) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > asset["size"]:
                    raise UpdateError("the download was larger than GitHub said")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(got, asset["size"])
        if got != asset["size"]:
            raise UpdateError("the download stopped early")
        if h.hexdigest() != asset["sha256"]:
            raise UpdateError("the download does not match the checksum GitHub recorded")
        part.replace(dest)
    except _NET_ERRORS as e:
        raise UpdateError("the download failed: %s" % getattr(e, "reason", e))
    finally:
        part.unlink(missing_ok=True)


# -- opening it, and proving it ---------------------------------------------

def _run(cmd: list, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _team_id(app: Path) -> str:
    """The Developer ID team that signed `app`, or '' when it is unsigned."""
    try:
        p = _run(["/usr/bin/codesign", "-dv", "--verbose=2", str(app)], timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"^TeamIdentifier=(\w+)$", p.stderr or "", re.M)
    return m.group(1) if m else ""


def stage_app(dmg: Path, work: Path, target: Path) -> None:
    """Copy PaperPull.app out of the disk image to `target`."""
    mnt = work / "mnt"
    mnt.mkdir(parents=True, exist_ok=True)
    p = _run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
              "-mountpoint", str(mnt), str(dmg)])
    if p.returncode != 0:
        raise UpdateError("the disk image would not open")
    try:
        src = mnt / "PaperPull.app"
        if not src.is_dir() or src.is_symlink():
            raise UpdateError("the disk image holds no PaperPull.app")
        if target.exists():
            shutil.rmtree(target)
        p = _run(["/usr/bin/ditto", str(src), str(target)])
        if p.returncode != 0:
            # A disk that filled up leaves part of an app behind.
            shutil.rmtree(target, ignore_errors=True)
            raise UpdateError("the app could not be copied out of the disk image")
    finally:
        _run(["/usr/bin/hdiutil", "detach", "-force", str(mnt)], timeout=60)


def verify_app(new_app: Path, current_app: Path, version: str) -> None:
    """Refuse anything that is not the next release, from the same publisher."""
    try:
        got = (new_app / "Contents" / "Resources" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        raise UpdateError("the new app does not say its version")
    if got != version:
        raise UpdateError("the new app is version %s, not %s" % (got, version))
    if _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(new_app)],
            timeout=300).returncode != 0:
        raise UpdateError("the new app's signature is not valid")
    if _run(["/usr/sbin/spctl", "--assess", "--type", "execute", str(new_app)],
            timeout=300).returncode != 0:
        raise UpdateError("macOS would not accept the new app")
    new_team, old_team = _team_id(new_app), _team_id(current_app)
    if not new_team or new_team != old_team:
        raise UpdateError("the new app was not signed by the same publisher")


SWAP_SCRIPT = r"""#!/bin/bash
# Replaces PaperPull.app once the panel has exited, then opens it.
# Arguments: panel pid, installed app, staged app, backup path, log file.
PID="$1"; OLD="$2"; NEW="$3"; BAK="$4"; LOG="$5"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "== $(date) update starting"
alive() {  # PID may name several processes, the panel and the window around it
  for p in $PID; do kill -0 "$p" 2>/dev/null && return 0; done
  return 1
}
for _ in $(seq 1 120); do
  alive || break
  sleep 0.5
done
HERE="$(cd "$(dirname "$0")" && pwd)"
if alive; then
  echo "the panel did not exit, leaving the installed app alone"
  rm -rf "$NEW"
  [ -n "$HERE" ] && rm -rf "$HERE"
  exit 1
fi
rm -rf "$BAK"
if mv "$OLD" "$BAK"; then
  if mv "$NEW" "$OLD"; then
    rm -rf "$BAK"
    echo "replaced"
  else
    rm -rf "$NEW"
    if mv "$BAK" "$OLD"; then
      echo "could not put the new app in place, the old one is back"
    else
      echo "could not put the new app in place, and the old one could not be put back, it is at $BAK"
    fi
  fi
else
  rm -rf "$NEW"
  echo "could not move the installed app aside, nothing changed"
fi
[ -d "$OLD" ] && open "$OLD"
[ -n "$HERE" ] && rm -rf "$HERE"
"""


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "PaperPull" / "update.log"


def _is_inside(pid: int, app: Path) -> bool:
    """True when process `pid` is an executable inside the bundle `app`."""
    if pid <= 1:
        return False
    try:
        p = _run(["/bin/ps", "-o", "comm=", "-p", str(pid)], timeout=10)
    except Exception:
        return False
    return (p.stdout or "").strip().startswith(str(app) + "/")


def _parent_of(pid: int) -> int:
    """The parent of process `pid`, or 0 when it cannot be read."""
    try:
        p = _run(["/bin/ps", "-o", "ppid=", "-p", str(pid)], timeout=10)
        return int((p.stdout or "").strip() or 0)
    except Exception:
        return 0


def start_swap(current_app: Path, staged_app: Path, work: Path, pid: Optional[int] = None) -> None:
    """Start the script that replaces the app after this process is gone."""
    script = work / "swap.sh"
    script.write_text(SWAP_SCRIPT, encoding="utf-8")
    script.chmod(0o700)
    backup = current_app.parent / ".PaperPull.old.app"
    waits = [str(pid or os.getpid())]
    if pid is None:
        # The host that started the panel and the window around it quit just
        # after it (gui/mac_host.py, packaging/macos/launcher.m). The swap
        # waits for each of them that runs from this app, so macOS opens the
        # new app rather than bring the closing one forward.
        up = os.getppid()
        for _ in range(4):
            if not _is_inside(up, current_app):
                break
            waits.append(str(up))
            up = _parent_of(up)
    subprocess.Popen(
        ["/bin/bash", str(script), " ".join(waits), str(current_app),
         str(staged_app), str(backup), str(log_path())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, start_new_session=True)


def staged_path(current_app: Path) -> Path:
    return current_app.parent / ".PaperPull.new.app"


# -- the one install in flight ----------------------------------------------

class Install:
    """Downloading and checking a release, in a thread, with a state the page
    can poll. There is at most one."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.phase = "idle"        # idle, downloading, checking, ready, error
        self.done = 0
        self.total = 0
        self.error = ""
        self.version = ""
        self.work: Optional[Path] = None
        self.app: Optional[Path] = None
        self.staged: Optional[Path] = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"phase": self.phase, "done": self.done, "total": self.total,
                    "error": self.error, "version": self.version}

    def busy(self) -> bool:
        return self.phase in ("downloading", "checking", "restarting")

    def start(self, current: str, app: Path, arch: Optional[str] = None) -> None:
        with self._lock:
            if self.busy():
                return
            self.reset()
            self.phase, self.version, self.app = "downloading", "", app
        threading.Thread(target=self._go, args=(current, app, arch), daemon=True).start()

    def _fail(self, text: str):
        with self._lock:
            self.phase, self.error = "error", text

    def _progress(self, done: int, total: int):
        self.done, self.total = done, total

    def _go(self, current: str, app: Path, arch: Optional[str]):
        work = staged = None
        try:
            # Read the release again rather than trust anything kept from the
            # last check.
            rel = check_latest(current, arch)
            if not rel["newer"]:
                raise UpdateError("PaperPull is already up to date")
            if not rel["asset"]:
                raise UpdateError("that release has no disk image for this Mac")
            self.version = rel["version"]
            work = Path(tempfile.mkdtemp(prefix="paperpull-update-"))
            dmg = work / rel["asset"]["name"]
            download(rel["asset"], dmg, self._progress)
            with self._lock:
                self.phase = "checking"
            staged = staged_path(app)
            stage_app(dmg, work, staged)
            dmg.unlink(missing_ok=True)   # 135 MB nobody needs now
            verify_app(staged, app, rel["version"])
            with self._lock:
                self.work, self.staged, self.phase = work, staged, "ready"
            work = staged = None  # swap.sh is written into work at restart
        except UpdateError as e:
            self._fail(str(e))
        except Exception as e:
            # Whatever went wrong, the page must not wait on "downloading"
            # for good, and a press of Try again must be able to start over.
            self._fail("the update could not be prepared: %s" % e)
        finally:
            if staged is not None:
                shutil.rmtree(staged, ignore_errors=True)
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)

    def restart(self, last_look: Optional[Callable[[], str]] = None) -> None:
        """Hand over to the swap script. The caller then exits the process.

        Only one press gets this far, since the phase leaves "ready" at once.
        `last_look`, asked once the staged app has been checked again, names
        anything that must not be cut off by the exit, and then nothing is
        started."""
        with self._lock:
            if self.phase != "ready" or not self.staged or not self.staged.is_dir():
                raise UpdateError("no update is ready")
            self.phase = "restarting"
            work, app, staged, version = self.work, self.app, self.staged, self.version
        try:
            verify_app(staged, app, version)
        except UpdateError:
            shutil.rmtree(staged, ignore_errors=True)
            with self._lock:
                self.reset()
            raise
        except Exception:
            with self._lock:
                self.phase = "ready"
            raise
        why = last_look() if last_look else ""
        if why:
            with self._lock:
                self.phase = "ready"
            raise UpdateError(why)
        try:
            start_swap(app, staged, work)
        except Exception:
            with self._lock:
                self.phase = "ready"
            raise


INSTALL = Install()
