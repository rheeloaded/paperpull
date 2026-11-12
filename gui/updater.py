"""Finding a newer PaperPull, and on a Mac or a Windows install, installing it.

WHAT THIS DOES

    check      ask GitHub for the newest release and say whether it is newer
    install    download that release's disk image or installer, prove it is
               the file GitHub published and that the same publisher signed
               it, and keep it ready
    restart    hand over to a small script that waits for this panel to exit,
               puts the new version in place and opens it again

Two copies install an update themselves. The Mac bundle (PaperPull.app) swaps
in the app from the new disk image, and a Windows copy installed by setup.exe
runs the new setup.exe over itself. Every other copy is told a new version
exists and is sent to the release page. That is the portable zip, which can
sit in any folder, beside anything, and whose zip as a whole carries no
signature, and a checkout or a Python someone runs by hand. PaperPull Server
is told too, with the steps to take the new image (gui/app.py), since a
container cannot replace its own image and is never given the Docker socket
that could.

WHAT IT WILL NOT DO

Contact anything on its own. Nothing here runs at launch or in the
background. The only requests are the ones the person starts, by pressing
Check github.com for an update and then Download from github.com, and the
check stays off until they turn it on in Settings (gui/app.py). The Microsoft
Store edition updates through the Store, which offers a version only once
Microsoft has certified it, so it is offered none of this (offered).

Trust nothing it was not given. The release is read from GitHub's API over
TLS. The file is fetched only from this project's own release downloads and
must match the SHA-256 GitHub records for that asset. On a Mac the app inside
the disk image must pass codesign and Gatekeeper and carry the same Team ID
as the app already running. On Windows the installer must carry a valid
Authenticode signature naming PaperPull's publisher, issued by Microsoft's ID
Verified code signing service, and say it is the version the release names.
So a file swapped on the way, or a release made by somebody else, is refused.
A copy that is not signed at all (one built on this computer for testing) is
never replaced.

THE SWAP ON A MAC

The new app is staged next to the installed one, so putting it in place is two
renames on one volume. The old app is kept until the new one is in place and
put back if anything fails. The staged app's signature and publisher are
checked again just before the swap, so nothing changed while it waited is
put in place. The script outlives this process (it is started in
a session of its own) and writes what it did to
~/Library/Logs/PaperPull/update.log.

THE INSTALL ON WINDOWS

The installer is checked again just before the panel closes, which it
refuses to do while another PaperPull program runs from the folder, since
the installer would close it. A PowerShell script then waits for the panel
and PaperPull.exe to exit, so no file the installer replaces is in use,
holds the installer open while it checks its SHA-256 one last time and
starts it, and runs it with only its progress showing. The installer keeps
the folder and the shortcuts the person chose. When it succeeds, the script
opens PaperPull again. When it fails, the folder can hold some new files and
some old, so the script keeps the installer and opens it again with its
usual window, so the install can be finished. When it never ran, the script
opens the copy the person had, if that copy's Python starts. It writes what
it did to update.log beside the panel's settings, in
AppData\\Roaming\\PaperPull.
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
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from paperpull_core.urls import is_safe_url

REPO = "rheeloaded/paperpull"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
DOWNLOAD_PREFIX = "https://github.com/%s/releases/download/" % REPO
RELEASE_PAGE = "https://github.com/%s/releases/tag/" % REPO

# A disk image is about 135 MB and the Windows installer about 55 MB.
# Anything past this is not one of ours.
MAX_DMG = 1024 * 1024 * 1024
NOTES_SHOWN = 4000

_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_TAG = re.compile(r"^v\d{1,4}\.\d{1,4}\.\d{1,4}$")
_DMG = re.compile(r"^PaperPull-\d{1,4}\.\d{1,4}\.\d{1,4}-(arm64|x86_64)\.dmg$")
_SETUP = re.compile(r"^PaperPull-\d{1,4}\.\d{1,4}\.\d{1,4}-setup\.exe$")

# Who signs the Windows installer. Azure Artifact Signing issues a
# certificate that lasts a few days, from one of Microsoft's ID Verified
# intermediates, which rotate (AOC CA 03 and 04 and EOC CA 04 so far), and the
# signature's timestamp keeps it valid after the certificate ends. The subject
# names the publisher and the city on file, so only its first and last parts
# are held here.
_SIGNER = re.compile(r"^CN=Bryan Rhee, O=Bryan Rhee, .*, C=US$")
_ISSUER = re.compile(r"^CN=Microsoft ID Verified CS (AOC|EOC) CA \d{2}, O=Microsoft Corporation, C=US$")
# Where the installer records the folder it installed in, for its next run.
# The installer asks for no administrator rights (packaging/build_windows.py),
# so it writes under the person's own key. PaperPull_is1 is the name Inno
# Setup gives an app with no AppId of its own.
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PaperPull_is1"
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


def windows_folder(gui_dir: Optional[Path] = None) -> Optional[Path]:
    """The folder a Windows package of PaperPull runs from, the installer's
    or the portable zip's, or None. gui\\ sits in it beside PaperPull.exe and
    the packaged Python (packaging/build_windows.py)."""
    if sys.platform != "win32":
        return None
    here = Path(gui_dir or Path(__file__).resolve().parent)
    top = here.parent
    if (here.name.lower() == "gui" and (top / "PaperPull.exe").is_file()
            and (top / "python" / "python.exe").is_file()):
        return top
    return None


def _installer_folder() -> str:
    """The folder setup.exe last installed PaperPull in, as it recorded it
    for its own next run, or "" when it never ran for this account. Inno
    Setup's own value comes first, since it is the one the next installer
    reads, and the one Windows lists second."""
    try:
        import winreg
    except ImportError:
        return ""
    for name in ("Inno Setup: App Path", "InstallLocation"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _same_folder(a, b) -> bool:
    def norm(p):
        return os.path.normcase(os.path.realpath(os.path.normpath(str(p))))
    return norm(a) == norm(b)


def installed_folder(gui_dir: Optional[Path] = None) -> Optional[Path]:
    """The folder setup.exe installed this panel in, or None. A copy is the
    installer's only when the installer recorded this very folder, since that
    is where the next installer puts the new version. A portable copy, even
    one beside an installed one, is not."""
    top = windows_folder(gui_dir)
    if top is None:
        return None
    recorded = _installer_folder()
    return top if recorded and _same_folder(recorded, top) else None


def offered(executable: Optional[str] = None) -> bool:
    """Whether this copy should offer the check at all. The Store edition
    runs from a Microsoft Store package and updates through the Store. A
    copy that cannot tell is not offered it."""
    try:
        from paperpull_core.browser import _in_a_store_package
    except ImportError:
        return False
    return not _in_a_store_package(executable or sys.executable)


def edition(gui_dir: Optional[Path] = None, executable: Optional[str] = None) -> str:
    """Which desktop copy this is, for what an update can do here.

        store     the Microsoft Store edition, which the Store updates
        mac       PaperPull.app, which swaps in the new app itself
        windows   installed by setup.exe, which runs the next one over itself
        portable  unzipped from the portable zip, which is only told
        other     a checkout, or a Python someone runs by hand, likewise

    PaperPull Server is the panel's to tell (gui/app.py)."""
    if not offered(executable):
        return "store"
    if bundle_path(gui_dir):
        return "mac"
    if installed_folder(gui_dir):
        return "windows"
    if windows_folder(gui_dir):
        return "portable"
    return "other"


def install_kind() -> str:
    """Which release file would install this copy, the Windows installer
    on Windows and the disk image everywhere else."""
    return "windows" if sys.platform == "win32" else "mac"


def install_location(gui_dir: Optional[Path] = None) -> Optional[Path]:
    """What an update would replace, the PaperPull.app on a Mac or the
    folder setup.exe installed into on Windows, or None."""
    if sys.platform == "win32":
        return installed_folder(gui_dir)
    return bundle_path(gui_dir)


def architecture() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


PORTABLE_SAYS = ("This copy was unzipped from the portable zip, so it does not replace "
                 "itself. Download the new zip from the release page and unzip it, or "
                 "install with setup.exe, which updates itself.")


def can_install(app: Optional[Path], kind: str = "mac") -> tuple[bool, str]:
    """Whether this copy can replace itself, and if not, why."""
    if kind == "windows":
        if app is None:
            if windows_folder():
                return False, PORTABLE_SAYS
            return False, ("This copy was not installed with setup.exe, so it does not "
                           "replace itself. Update a checkout with git pull.")
        if not os.access(app, os.W_OK):
            return False, ("PaperPull is in a folder this account cannot change. "
                           "Download the new setup.exe from the release page and run it.")
        # Whether this copy is signed, and whether the folder can really be
        # written, is asked once the person presses Download, since asking
        # here would start PowerShell and write a file every time the page
        # opens (Install._go).
        return True, ""
    if app is None and sys.platform != "darwin":
        return False, ("This copy does not replace itself. Update it the way you got it, "
                       "with git pull for a checkout.")
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


def read_release(data: dict, arch: Optional[str] = None, kind: str = "mac") -> dict:
    """What matters in a release, checked. The asset is None unless it is
    this project's, the disk image for this Mac or with kind "windows" the
    installer, and GitHub recorded a SHA-256 for it. With any other kind it
    is None, as for PaperPull Server, which no release file installs."""
    arch = arch or architecture()
    tag = str(data.get("tag_name") or "")
    if not _TAG.match(tag) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("the newest release is not a version number")
    version = tag[1:]
    if kind == "windows":
        want, shape = "PaperPull-%s-setup.exe" % version, _SETUP
    elif kind == "mac":
        want, shape = "PaperPull-%s-%s.dmg" % (version, arch), _DMG
    else:
        want, shape = "", None
    asset = None
    for a in data.get("assets") or []:
        if not isinstance(a, dict) or not shape or a.get("name") != want or not shape.match(want):
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


def check_latest(current: str, arch: Optional[str] = None, kind: str = "mac") -> dict:
    """The newest release, and whether it is newer than `current`."""
    rel = read_release(fetch_json(API_LATEST), arch, kind)
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
    """Where the swap or the install writes what it did. On Windows that is
    beside the panel's settings, never in the folder the installer replaces."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "PaperPull" / "update.log"
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


# -- the installer on Windows -----------------------------------------------

def _powershell() -> str:
    """Windows PowerShell by its full path, so no program of the same name
    elsewhere on PATH runs instead. Commands given with -Command are not
    scripts, so no execution policy stops them."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def _powershell_env(**extra: str) -> dict:
    """The panel's environment for Windows PowerShell, less PSModulePath.
    PowerShell 7 gives every program it starts its own module folders, so a
    PaperPull.exe opened from a PowerShell 7 window passes them on. Windows
    PowerShell then finds PowerShell 7's Security module before its own,
    cannot load it, and has no Get-AuthenticodeSignature. Given no
    PSModulePath, it uses its own folders."""
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    env.update(extra)
    return env

# A file's Authenticode signature, read the way the release workflow checks it
# (.github/workflows/build-windows.yml), with the version the file says it
# is. The file is named by an environment variable, so no path is ever read
# as PowerShell, and the script holds no double quote, since all of it is
# one argument on the command line. Where Windows lets PowerShell run only
# its restricted language (a PC an organization locks down), the script
# says so in one word, since what follows it would fail there, and so would
# the script that runs the installer.
_SIGNATURE_PS = r"""
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { 'restricted'; exit }
$f = $env:PAPERPULL_SIGNED
$s = Get-AuthenticodeSignature -LiteralPath $f
$c = $s.SignerCertificate
[pscustomobject]@{
  status = [string]$s.Status
  type = [string]$s.SignatureType
  subject = [string]$c.Subject
  issuer = [string]$c.Issuer
  version = [string](Get-Item -LiteralPath $f).VersionInfo.ProductVersion
} | ConvertTo-Json -Compress
"""

RESTRICTED_SAYS = ("Windows lets PowerShell run only its restricted commands on this PC, so "
                   "PaperPull cannot check an update itself. Download the new setup.exe from "
                   "the release page and run it")


def windows_signature(path: Path) -> dict:
    """What Windows says of the Authenticode signature on `path`, its
    status, type, subject and issuer, and the version the file says it is.
    {"restricted": True} where PowerShell runs only its restricted
    language, and empty when it could not be read. Replaced in tests."""
    env = _powershell_env(PAPERPULL_SIGNED=str(path))
    try:
        p = subprocess.run([_powershell(), "-NoLogo", "-NoProfile", "-NonInteractive",
                            "-Command", _SIGNATURE_PS],
                           capture_output=True, text=True, timeout=120, env=env,
                           stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return {}
    if (p.stdout or "").strip() == "restricted":
        return {"restricted": True}
    try:
        data = json.loads(p.stdout or "")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_signature(path: Path, what: str) -> dict:
    sig = windows_signature(path)
    if sig.get("restricted"):
        raise UpdateError(RESTRICTED_SAYS)
    if not sig:
        raise UpdateError("Windows could not say who signed %s" % what)
    return sig


def signed_by_publisher(sig: dict) -> bool:
    """A valid Authenticode signature by PaperPull's publisher, from one of
    Microsoft's ID Verified intermediates. A valid status means Windows
    traced the chain to a root it trusts and found the timestamp good."""
    return (sig.get("status") == "Valid" and sig.get("type") == "Authenticode"
            and bool(_SIGNER.match(str(sig.get("subject") or "")))
            and bool(_ISSUER.match(str(sig.get("issuer") or ""))))


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_installer(setup: Path, sha256: str, version: str) -> None:
    """Refuse anything that is not the release's own installer, signed by
    PaperPull's publisher and saying it is that version."""
    try:
        have = _sha256_of(setup)
    except OSError:
        raise UpdateError("the installer could not be read")
    if have != sha256:
        raise UpdateError("the installer does not match the checksum GitHub recorded")
    sig = _read_signature(setup, "the installer")
    if not signed_by_publisher(sig):
        raise UpdateError("the installer is not signed by PaperPull's publisher")
    got = str(sig.get("version") or "").strip()
    if got != version:
        raise UpdateError("the installer is version %s, not %s" % (got or "unknown", version))


def this_copy_is_signed(folder: Path) -> bool:
    """Whether the running copy's PaperPull.exe carries the publisher's
    signature, as every installed release's does. One built on this
    computer does not, and is never replaced."""
    return signed_by_publisher(_read_signature(folder / "PaperPull.exe", "this copy"))


def can_write(folder: Path) -> bool:
    """Whether this account can write in `folder`, found by writing there.
    os.access cannot tell on Windows, where it only reads the read-only flag."""
    try:
        fd, name = tempfile.mkstemp(prefix=".paperpull-write-check-", dir=str(folder))
    except OSError:
        return False
    os.close(fd)
    try:
        os.unlink(name)
    except OSError:
        pass
    return True


# Runs the installer once the panel has exited, then opens PaperPull again.
# Everything it is given comes in environment variables, set by
# start_installer, which it reads and then removes, so the programs it
# starts do not inherit them. It writes the file PAPERPULL_UPDATE_STARTED
# names once it is waiting, which is what lets the panel close, and from
# then on every way out of it opens PaperPull again, except a panel that
# never exits.
#
# The installer is held open while its SHA-256 is read one last time and
# while it starts, so it cannot change between that look and its start.
# /SILENT shows only the installer's progress, and the installer keeps the
# folder, the shortcuts and the tasks of the install before. Its [Run] entry
# skips a silent install, so the script opens PaperPull again itself.
#
# After the installer succeeds, the script opens PaperPull and waits on
# nothing else, since the first start of the new files can be slow while
# they are scanned. After an installer that ran and failed, the folder can
# hold some new files and some old, so the script opens the kept installer
# again with its usual window, for the person to finish the install, and
# never the copy it may have left half replaced. When the installer never
# ran, the copy is the one the person had, and the script opens it if its
# Python starts. A check that throws or takes a minute counts as a no, and
# then the kept installer opens instead. The installer is kept unless it
# installed, or was not the one checked, and one that was not is never
# opened. Its folder is removed only when it is one the panel made.
#
# Programs are started through .NET, never Start-Process, which reads a
# path with brackets in it as a pattern and can start another file. Single
# quotes only, as in _SIGNATURE_PS.
INSTALL_PS = r"""
$ErrorActionPreference = 'Stop'
$log = $env:PAPERPULL_UPDATE_LOG
$setup = $env:PAPERPULL_UPDATE_SETUP
$app = $env:PAPERPULL_UPDATE_APP
$sha256 = $env:PAPERPULL_UPDATE_SHA256
$version = $env:PAPERPULL_UPDATE_VERSION
$started = $env:PAPERPULL_UPDATE_STARTED
$waitFor = @($env:PAPERPULL_UPDATE_WAIT -split ' ' | Where-Object { $_ })
$deadline = (Get-Date).AddSeconds([int]$env:PAPERPULL_UPDATE_WAIT_S)
foreach ($name in @('LOG', 'SETUP', 'APP', 'SHA256', 'VERSION', 'STARTED', 'WAIT', 'WAIT_S')) {
  Remove-Item -Path ('Env:PAPERPULL_UPDATE_' + $name) -ErrorAction SilentlyContinue
}
$work = Split-Path -Parent $setup
$said = $false
$closed = $false
$ran = $false
$installed = $false
$keep = $true
function Say([string]$text) {
  try { Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $text) } catch { }
}
function Run([string]$file, [string]$arguments, [bool]$window) {
  $info = New-Object System.Diagnostics.ProcessStartInfo
  $info.FileName = $file
  $info.Arguments = $arguments
  $info.UseShellExecute = $window
  $info.WorkingDirectory = Split-Path -Parent $file
  return [System.Diagnostics.Process]::Start($info)
}
function Reopen {
  try {
    if ($installed) {
      $null = Run (Join-Path $app 'PaperPull.exe') '' $true
      Say 'opened PaperPull again'
      return
    }
    if ($ran -and (Test-Path -LiteralPath $setup -PathType Leaf)) {
      $null = Run $setup '' $true
      Say ('the installer did not finish, so it was opened with its usual window to finish the update, ' + $setup)
      return
    }
  } catch {
    Say ('could not open it, ' + $_)
  }
  $works = $false
  try {
    $python = Join-Path (Join-Path $app 'python') 'python.exe'
    if (Test-Path -LiteralPath $python -PathType Leaf) {
      $check = Run $python '-m uvicorn --version' $false
      if ($check.WaitForExit(60000)) { $works = $check.ExitCode -eq 0 }
      else { try { $check.Kill() } catch { } }
    }
  } catch {
    Say ('the Python in its folder would not start, ' + $_)
  }
  try {
    $exe = Join-Path $app 'PaperPull.exe'
    if ($works -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
      $null = Run $exe '' $true
      Say 'opened PaperPull again'
    } elseif ($keep -and (Test-Path -LiteralPath $setup -PathType Leaf)) {
      $null = Run $setup '' $true
      Say ('PaperPull does not start, so its installer was opened to finish the update, ' + $setup)
    } else {
      Say 'PaperPull does not start. Download the installer from the release page and run it.'
    }
  } catch {
    Say ('could not open PaperPull again, ' + $_)
  }
}
try {
  try { [void][IO.Directory]::CreateDirectory((Split-Path -Parent $log)) } catch { }
  Say ('== update to ' + $version + ' starting')
  Set-Content -LiteralPath $started -Value 'waiting'
  $said = $true
  foreach ($id in $waitFor) {
    $p = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
    if ($p) {
      $left = [int][Math]::Max(0, ($deadline - (Get-Date)).TotalMilliseconds)
      if (-not $p.WaitForExit($left)) { Say 'the panel did not exit, so nothing was installed'; exit 1 }
    }
  }
  $closed = $true
  $file = [IO.File]::Open($setup, 'Open', 'Read', 'Read')
  try {
    $hasher = [Security.Cryptography.SHA256]::Create()
    $have = -join ($hasher.ComputeHash($file) | ForEach-Object { $_.ToString('x2') })
    if ($have -ne $sha256) {
      Say 'the installer is not the one the panel checked, so it was not run'
      $keep = $false
      Reopen
      exit 1
    }
    $setupLog = Join-Path (Split-Path -Parent $log) 'setup.log'
    $run = Run $setup ('/SILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL /LOG=' + [char]34 + $setupLog + [char]34) $false
    $ran = $true
  } finally {
    $file.Dispose()
  }
  $run.WaitForExit()
  if ($run.ExitCode -eq 0) {
    Say 'installed'
    $installed = $true
    $keep = $false
  } else {
    Say ('the installer ended with ' + $run.ExitCode + ', see setup.log beside this file')
  }
  Reopen
} catch {
  Say ('stopped, ' + $_)
  if ($said) {
    if (-not $closed) { Start-Sleep -Seconds 5 }
    Reopen
  }
} finally {
  if (-not $keep -and (Split-Path -Leaf $work) -like 'paperpull-update-*') {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
  }
}
"""


def _image_of(pid: int) -> str:
    """The full path of the program process `pid` runs, or ""."""
    if sys.platform != "win32" or pid <= 0:
        return ""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        return buf.value if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        k32.CloseHandle(handle)


def _all_pids() -> list:
    """Every process id Windows lists, or none when it will not say."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.K32EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD))
    n = 4096
    while True:
        ids = (wintypes.DWORD * n)()
        got = wintypes.DWORD()
        if not k32.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(got)):
            return []
        count = got.value // ctypes.sizeof(wintypes.DWORD)
        if count < n:
            return list(ids[:count])
        n *= 2


def _inside(path, folder) -> bool:
    def norm(p):
        return os.path.normcase(os.path.realpath(os.path.normpath(str(p))))
    return norm(path).startswith(norm(folder).rstrip("\\/") + os.sep)


def programs_running_from(folder: Path, but=()) -> list:
    """The programs running from `folder`, other than the processes `but`
    names. The installer would close them, a download someone started from
    a terminal with paperpull.bat among them."""
    found = []
    for pid in _all_pids():
        if pid in but:
            continue
        image = _image_of(pid)
        if image and _inside(image, folder):
            found.append(image)
    return found


OTHERS_SAY = ("Another PaperPull program is running from its folder, such as a download "
              "started in a terminal or a spreadsheet being built. Let it finish or close "
              "it, then restart to update.")


def start_installer(folder: Path, setup: Path, sha256: str, version: str,
                    pid: Optional[int] = None, within: float = 20.0,
                    wait_s: int = 60) -> subprocess.Popen:
    """Start the script that runs `setup` once this panel has exited, and
    return once it says it is waiting. If it never says so the panel does
    not close, since nothing would install the update or open it again."""
    started = setup.parent / "started"
    started.unlink(missing_ok=True)
    waits = [str(pid or os.getpid())]
    if pid is None:
        # PaperPull.exe started the panel and exits just after it. It is in
        # the folder the installer replaces, so the script waits for it too.
        up = os.getppid()
        image = _image_of(up)
        if image and _same_folder(image, folder / "PaperPull.exe"):
            waits.append(str(up))
    env = _powershell_env(PAPERPULL_UPDATE_WAIT=" ".join(waits), PAPERPULL_UPDATE_WAIT_S=str(wait_s),
                          PAPERPULL_UPDATE_SETUP=str(setup), PAPERPULL_UPDATE_SHA256=sha256,
                          PAPERPULL_UPDATE_VERSION=version, PAPERPULL_UPDATE_APP=str(folder),
                          PAPERPULL_UPDATE_LOG=str(log_path()), PAPERPULL_UPDATE_STARTED=str(started))
    cmd = [_powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", INSTALL_PS]
    # Its own console with no window, and out of any job the panel runs in,
    # where that is allowed, so closing PaperPull's window ends nothing of
    # it. Not in a process group of its own, which would leave Ctrl+C turned
    # off in the PaperPull it opens again. It runs in the Windows folder,
    # since a folder a process is working in cannot be removed.
    kw = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True,
              cwd=os.environ.get("SystemRoot") or None)
    try:
        try:
            proc = subprocess.Popen(cmd, creationflags=_NO_WINDOW | _BREAKAWAY, **kw)
        except OSError:
            proc = subprocess.Popen(cmd, creationflags=_NO_WINDOW, **kw)
    except OSError as e:
        raise UpdateError("the installer could not be started (%s)" % e)
    deadline = time.monotonic() + within
    while time.monotonic() < deadline and proc.poll() is None:
        if started.is_file():
            return proc
        time.sleep(0.1)
    if started.is_file() and proc.poll() is None:
        return proc
    try:
        proc.kill()
    except OSError:
        pass
    raise UpdateError("the installer could not be started")


# -- the one install in flight ----------------------------------------------

class Install:
    """Downloading and checking a release, in a thread, with a state the page
    can poll. There is at most one. Its kind is "mac", where `app` is the
    PaperPull.app and `staged` the new app beside it, or "windows", where
    `app` is the installed folder and `staged` the checked setup.exe."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.phase = "idle"        # idle, downloading, checking, ready, error
        self.done = 0
        self.total = 0
        self.error = ""
        self.version = ""
        self.kind = "mac"
        self.sha256 = ""
        self.work: Optional[Path] = None
        self.app: Optional[Path] = None
        self.staged: Optional[Path] = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"phase": self.phase, "done": self.done, "total": self.total,
                    "error": self.error, "version": self.version}

    def busy(self) -> bool:
        return self.phase in ("downloading", "checking", "restarting")

    def start(self, current: str, app: Path, arch: Optional[str] = None, kind: str = "mac") -> None:
        with self._lock:
            # A ready update is kept for the press that puts it in place. A
            # second tab's Download would otherwise remove it from under that
            # press, or leave its installer behind.
            if self.busy() or self.phase == "ready":
                return
            self.reset()
            self.phase, self.version, self.app, self.kind = "downloading", "", app, kind
        threading.Thread(target=self._go, args=(current, app, arch, kind), daemon=True).start()

    def _fail(self, text: str):
        with self._lock:
            self.phase, self.error = "error", text

    def _progress(self, done: int, total: int):
        self.done, self.total = done, total

    def _go(self, current: str, app: Path, arch: Optional[str], kind: str = "mac"):
        work = staged = None
        try:
            if kind == "windows" and not this_copy_is_signed(app):
                raise UpdateError("this copy is not signed, so it cannot tell that an "
                                  "update is from the same publisher")
            if kind == "windows" and not can_write(app):
                raise UpdateError("PaperPull is in a folder this account cannot change, so its "
                                  "installer could not update it. Download the new setup.exe "
                                  "from the release page and run it")
            # Read the release again rather than trust anything kept from the
            # last check.
            rel = check_latest(current, arch, kind)
            if not rel["newer"]:
                raise UpdateError("PaperPull is already up to date")
            if not rel["asset"]:
                raise UpdateError("that release has no installer for Windows" if kind == "windows"
                                  else "that release has no disk image for this Mac")
            self.version = rel["version"]
            work = Path(tempfile.mkdtemp(prefix="paperpull-update-"))
            fetched = work / rel["asset"]["name"]
            download(rel["asset"], fetched, self._progress)
            with self._lock:
                self.phase = "checking"
            if kind == "windows":
                verify_installer(fetched, rel["asset"]["sha256"], rel["version"])
                with self._lock:
                    self.work, self.staged, self.sha256 = work, fetched, rel["asset"]["sha256"]
                    self.phase = "ready"
                work = None   # it holds the installer, removed by the script that runs it
                return
            staged = staged_path(app)
            stage_app(fetched, work, staged)
            fetched.unlink(missing_ok=True)   # 135 MB nobody needs now
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
        """Hand over to the swap script on a Mac, or the script that runs the
        installer on Windows. The caller then exits the process.

        Only one press gets this far, since the phase leaves "ready" at once.
        `last_look`, asked once the staged app has been checked again, names
        anything that must not be cut off by the exit, and then nothing is
        started."""
        with self._lock:
            windows = self.kind == "windows"
            there = self.staged and (self.staged.is_file() if windows else self.staged.is_dir())
            if self.phase != "ready" or not there:
                if self.phase == "ready":
                    # Removed while it waited, by a clean-up of the temp
                    # folder, say. Download starts over again.
                    self.reset()
                raise UpdateError("no update is ready")
            self.phase = "restarting"
            work, app, staged, version = self.work, self.app, self.staged, self.version
            sha256 = self.sha256
        try:
            if windows:
                verify_installer(staged, sha256, version)
            else:
                verify_app(staged, app, version)
        except UpdateError:
            shutil.rmtree(work if windows else staged, ignore_errors=True)
            with self._lock:
                self.reset()
            raise
        except Exception:
            with self._lock:
                self.phase = "ready"
            raise
        # The installer closes whatever runs from its folder, and a download
        # started from a terminal would be cut off, or hold a file open and
        # make the install fail halfway.
        # A list Windows will not give is no reason to refuse, since the
        # installer closes such programs itself.
        try:
            others = programs_running_from(app, {os.getpid(), os.getppid()}) if windows else []
        except Exception:
            others = []
        why = OTHERS_SAY if others else (last_look() if last_look else "")
        if why:
            with self._lock:
                self.phase = "ready"
            raise UpdateError(why)
        try:
            if windows:
                start_installer(app, staged, sha256, version)
            else:
                start_swap(app, staged, work)
        except Exception:
            with self._lock:
                # The script that never started may have taken the
                # installer with it, and then there is nothing to restart.
                if windows and not staged.is_file():
                    self.reset()
                else:
                    self.phase = "ready"
            raise


INSTALL = Install()
