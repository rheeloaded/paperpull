r"""Receipt & Statement Downloaders - local control panel.

A tiny FastAPI app that discovers the downloader apps, lists their accounts,
and runs an action (Login / Discover / Pilot / Run All / Resume / Verify / Diagnose),
streaming the live output to the browser. It only ever runs the predefined
per-app commands - nothing from user input is passed to a shell.

Run it:  python -m uvicorn app:app --port 8765   (or use run_gui.bat)
Then open http://127.0.0.1:8765

Where it looks for the downloaders, most specific first:

  APPS_ROOT environment variable   the override, for running from the repo
  the settings file                 what you chose the first time it ran,
                                    changeable from the page
  ../apps                           the repo layout

An installed copy has no ../apps, so the first time it runs the page asks for
the folder that already holds your downloaders and remembers it. Nothing is
moved or copied, and the old way of running them keeps working alongside.

  set APPS_ROOT=C:\path\to\Receipt and Statement Downloader
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import mimetypes
import os
from datetime import date, datetime
import re
import shutil
import stat
import subprocess
import sysconfig
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile
import time
from typing import Optional
import sys
from pathlib import Path

import run_result

from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from starlette.datastructures import MutableHeaders

# PaperPull targets Python 3.11+ (README, and core/pyproject.toml's
# requires-python). Nothing here declared that, so a reader - or a scanner -
# landing in this file had no way to know which version it is written against.
# Say it once, and fail with a sentence rather than something obscure.
if sys.version_info < (3, 11):
    raise SystemExit(
        "PaperPull needs Python 3.11 or newer; this is "
        f"{sys.version_info.major}.{sys.version_info.minor}.")

HERE = Path(__file__).resolve().parent
try:
    VERSION = (HERE.parent / "VERSION").read_text(encoding="utf-8").strip()
except Exception:
    VERSION = "0.1.0"
# -- where the downloaders live ----------------------------------------------
#
# Three sources, most specific first.
#
#   APPS_ROOT environment variable   the override, for running from the repo
#   the settings file                 what the person chose the first time the
#                                     panel ran, and can change from the page
#   apps/ beside this file            the repo layout, for a checkout
#
# An installed copy of this panel has no apps/ beside it, so without the
# settings file it would show an empty list and a hint to set an environment
# variable, which is not something to ask of somebody who just ran an
# installer. The page asks for the folder instead, once, and remembers it.
# Pointing at the folder they already have means nothing moves, nothing is
# migrated, and the old way of running things keeps working alongside.

_DEFAULT_ROOT = HERE.parent / "apps"


def _settings_path() -> Path:
    """Per-user, per-platform, and never inside the install folder, so an
    upgrade that replaces the program does not lose the choice.

    On Windows that means Roaming AppData. Local AppData is where the
    installer puts the program itself, and the file sat beside it for two
    releases, surviving only because nothing happened to delete it. A file
    from there is moved across the first time this runs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        new = base / "PaperPull" / "settings.json"
        old = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") \
            / "PaperPull" / "settings.json"
        if not new.exists() and old.is_file():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(new))
            except OSError:
                return old
        return new
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PaperPull" / "settings.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") \
        / "paperpull" / "settings.json"


def _read_settings() -> dict:
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(data: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def apps_root() -> Path:
    if _SAMPLE is not None:
        return _SAMPLE
    env = os.environ.get("APPS_ROOT")
    if env:
        return Path(env).expanduser()
    saved = _read_settings().get("apps_root")
    if saved:
        return Path(saved).expanduser()
    if _is_packaged():
        # Never inside the bundle. On macOS that is a folder under
        # /Applications the system will not let anything write into, and on
        # either platform an upgrade replaces it.
        return Path.home() / "Documents" / "PaperPull"
    return _DEFAULT_ROOT


def root_source() -> str:
    if _SAMPLE is not None:
        return "sample"
    if os.environ.get("APPS_ROOT"):
        return "environment"
    if _read_settings().get("apps_root"):
        return "settings"
    return "default"


# -- the sample archive -------------------------------------------------------
#
# A folder of invented statements and receipts, written on request rather
# than carried around, so somebody who has just installed the program can
# see a filled Status tab and build both spreadsheets before deciding
# whether to point this at a bank.
# It is also the only way to see the program work without an account, which
# is what a reviewer with no account of their own needs.
#
# Looking at it is a mode this process is in, not a saved setting. Nothing
# is written to the settings file, and restarting the panel leaves it.

_SAMPLE: Optional[Path] = None


def _sample_builder() -> Optional[Path]:
    """tools/make_sample.py, which writes the archive rather than the
    archive itself being carried around. It is a few hundred lines of plain
    Python against a fixed seed, so the same folder comes out every time,
    and the repository never has to hold a tree of files that look exactly
    like the real statements .gitignore exists to keep out."""
    for cand in (HERE.parent / "tools" / "make_sample.py",
                 HERE / "make_sample.py"):
        if cand.is_file():
            return cand
    return None


def _sample_dest() -> Path:
    """Where the sample lives once built. Beside the settings file, because
    the install folder is replaced by an upgrade and macOS will not let
    anything write inside it, and spreadsheets get built into this."""
    return _settings_path().parent / "sample"


def _open_sample() -> Path:
    """Build the sample once, and answer with it."""
    dest = _sample_dest()
    if (dest / "README.txt").is_file():
        return dest
    builder = _sample_builder()
    if builder is None:
        raise HTTPException(500, "this copy of PaperPull did not ship the sample archive")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("paperpull_make_sample", builder)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.build(dest)
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, "could not build the sample archive: %s" % e)
    return dest


def _looks_like_installs(root: Path) -> int:
    """How many app folders sit directly under root. Zero means this is not
    the folder, or not yet."""
    if not root.is_dir():
        return 0
    n = 0
    try:
        for d in root.iterdir():
            if d.is_dir() and _entry_script(d):
                n += 1
    except OSError:
        return 0
    return n
# Resolved once. Importing by path is not free and the panel can be
# refreshed repeatedly. False means looked for and not found.
_STATUS_MOD = None
_EXPORT_MOD = None
_LAST_EXPORT = None     # path of the spreadsheet this panel wrote last, for Reveal
# Apps with a downloader process alive right now. Removing one of these
# would pull the folder out from under a run.
_RUNNING: set = set()

# action -> argparse flags. run_all / resume get --yes so they don't block on a
# confirmation prompt. Login is resolved per-app (open-browser vs login).
ACTIONS = {
    "login":    {"label": "Login",    "flags": ["__LOGIN__"]},
    "discover": {"label": "Discover", "flags": ["--discover"]},
    "pilot":    {"label": "Pilot",    "flags": ["--pilot"]},
    "resume":   {"label": "Resume",   "flags": ["--resume", "--yes"]},
    "all":      {"label": "Run All",  "flags": ["--all", "--yes"]},
    "verify":   {"label": "Verify",   "flags": ["--verify"]},
    # Reads the provider's page and writes a survey to Diagnostics. Downloads
    # nothing. It is how a provider built without an account gets tested by
    # someone who has one, and how a broken one gets repaired.
    "diagnose": {"label": "Diagnose", "flags": ["--diagnose"]},
    # Watches one signed-in page while the person clicks their way to a
    # document, and writes what they did to Diagnostics. Downloads nothing
    # and captures no keystroke. It is the one-round version of Diagnose:
    # a survey guesses which control matters, a recording knows.
    "record": {"label": "Record", "flags": ["--record"]},
    # Renaming what is already downloaded, so a naming improvement reaches
    # the files you already have without asking the provider for them
    # again. Two buttons because it is two steps: the first one changes
    # nothing and prints what it would do, the second does it. A panel
    # with one button would show a preview and leave nowhere to go.
    "rename": {"label": "Rename preview", "flags": ["--rename"]},
    "rename_apply": {"label": "Apply renames", "flags": ["--rename", "--apply"]},
    # Moving the documents an account saved before it had a documents folder
    # into that folder (#102). The app's own Rename does it, told to by the
    # environment (core renaming.MOVE_DOCUMENTS_ENV), so it keeps every rule
    # a rename keeps and every app moves alike. A preview first, as above.
    "move_documents": {"label": "Preview move", "flags": ["--rename"],
                       "env": {"PAPERPULL_MOVE_DOCUMENTS": "1"}},
    "move_documents_apply": {"label": "Move documents", "flags": ["--rename", "--apply"],
                             "env": {"PAPERPULL_MOVE_DOCUMENTS": "1"}},
}
# The actions for when something is off, kept behind a "more" link so the
# main panel stays the four a normal day needs. Verify re-checks saved PDFs,
# Diagnose surveys the page. Both are harmless and both are rarely wanted.
MORE_ACTIONS = ("verify", "diagnose", "record", "rename", "rename_apply",
                "move_documents", "move_documents_apply")
# The actions that finish on their own when the page that started them goes,
# since each moves files and then writes the ledgers that name them (#102).
FINISHED_WHEN_LEFT = ("rename_apply", "move_documents_apply")
# An app's own script, never a hidden file. A Mac writing to a network
# drive or a disk it does not format itself leaves "._ally_docs.py" beside
# ally_docs.py, a few bytes of its own about the file, and that sorts first,
# so Login on a server whose apps sit on such a drive ran it and Python
# refused its null bytes (#76).
ENTRY_RE = re.compile(r"[^.].*_(receipts|docs)\.py$")

# Every app takes the same three scope flags. The panel passes them through
# on any run except Login, which has nothing to scope. A scoped run skips the
# years outside its window on providers with a year picker (see
# paperpull_core.scope), and the apps filter what they found by date either
# way. Unscoped is the default and still walks everything.
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DATE_RE = re.compile(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _scope_flags(year: str = "", start: str = "", end: str = "") -> list:
    """argparse flags for the scope the page asked for, or [] for unscoped.
    Anything that is not a plain year or an ISO date is refused rather than
    passed on to a subprocess command line."""
    year, start, end = (year or "").strip(), (start or "").strip(), (end or "").strip()
    if year and not _YEAR_RE.match(year):
        raise HTTPException(400, "year must be four digits")
    for label, value in (("start", start), ("end", end)):
        if value and not _DATE_RE.match(value):
            raise HTTPException(400, f"{label} date must be YYYY-MM-DD")
    if start and end and start > end:
        raise HTTPException(400, "start date is after end date")
    flags = []
    if year:
        flags += ["--year", year]
    if start:
        flags += ["--start-date", start]
    if end:
        flags += ["--end-date", end]
    return flags


# Download again. Every app takes --redownload, which makes it go through
# every document in scope again, the ones it already downloaded included,
# and fetch again each one whose file is gone. A file still there is never
# overwritten. Most apps save a second copy beside it under a name of its
# own, and Target leaves an invoice still on file as it is. Downloads are
# otherwise remembered for good, so somebody who deleted their PDFs after
# importing them elsewhere has no other way to get them back.
#
# The panel adds the flag to Pilot and Run All only, only to a run scoped to
# a year or to both a start and an end date, so a whole history is never
# asked for again by accident, and only when the request says the person
# agreed to the page's question. Both arrive as JSON true in a POST body,
# never as text, and what reaches the app is this one fixed flag.
REDOWNLOAD_FLAG = "--redownload"
REDOWNLOAD_ACTIONS = ("pilot", "all")


def _redownload_ok(action: str, scope_flags, redownload, confirmed) -> bool:
    """Whether a run may download again. False when it did not ask, True
    when it asked and may, and a refusal saying why for anything else."""
    if redownload is False:
        return False
    if redownload is not True:
        raise HTTPException(400, "redownload is true or false")
    if server_mode.enabled():
        # PaperPull Server hands every file a run saves to its plug-ins as
        # a new document, and the Paperless one copies each into Paperless.
        # Downloading again there would send Paperless every document in the
        # range a second time, so the server does not offer it.
        raise HTTPException(404, "Download again is not offered on PaperPull Server. "
                                 "Each copy would go to Paperless a second time.")
    if action not in REDOWNLOAD_ACTIONS:
        raise HTTPException(400, "Download again works with Pilot and Run All only.")
    # One date alone is open at its other end, and From 1990 or To today is
    # a whole history, so it takes a year or both ends.
    chosen = {flag for flag in scope_flags if flag.startswith("--")}
    if "--year" not in chosen and not {"--start-date", "--end-date"} <= chosen:
        raise HTTPException(400, "Download again needs a year, or both a From and a To "
                                 "date, chosen in Scope, so a whole history is never "
                                 "asked for again by accident.")
    if confirmed is not True:
        raise HTTPException(400, "Download again needs the question on the page answered "
                                 "first.")
    return True


# What a run asked for in a body holds, and of what kind. Anything else is
# refused, so a body cannot carry more than the page itself sends.
_RUN_TEXT = ("app", "account", "action", "year", "start", "end")
_RUN_CHOICES = ("redownload", "confirmed")


def _run_request(body) -> dict:
    """The run a JSON body asks for, each field checked for its kind."""
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    if set(body) - set(_RUN_TEXT) - set(_RUN_CHOICES):
        raise HTTPException(400, "a run's body holds only app, account, action, year, "
                                 "start, end, redownload and confirmed")
    asked = {"account": "primary", "year": "", "start": "", "end": "",
             "redownload": False, "confirmed": False}
    for key in _RUN_TEXT:
        if key in body:
            if type(body[key]) is not str:
                raise HTTPException(400, "%s is text" % key)
            asked[key] = body[key]
    for key in _RUN_CHOICES:
        if key in body:
            if type(body[key]) is not bool:
                raise HTTPException(400, "%s is true or false" % key)
            asked[key] = body[key]
    for key in ("app", "action"):
        if not asked.get(key):
            raise HTTPException(400, "a run needs its %s" % key)
    return asked

# FastAPI serves /docs, /docs/oauth2-redirect, /redoc and /openapi.json
# unless it is told not to. /docs and /redoc load their script from
# cdn.jsdelivr.net, so opening either one ran another site's script as the
# panel's own page, and a script on the panel's own page can start a run.
# Nothing in PaperPull uses any of the four, so the panel goes without
# them, and PaperPull Server with it, since it serves this same app.
app = FastAPI(title="PaperPull", docs_url=None, redoc_url=None, openapi_url=None)

# PaperPull Server's sign-in, its gate and its browser screen. They do
# nothing unless PAPERPULL_SERVER=1, which only the server image sets.
import server_mode  # noqa: E402

server_mode.install(app)

# The panel runs the apps' commands, so it answers only what its own page
# asked for. A request has to pass three checks.
#
#   The Host header names one of the addresses the panel is served on. A
#   website can point a name of its own at 127.0.0.1 (DNS rebinding), and the
#   browser then takes that site's page for the panel's own, so every check
#   after this one sees a request from the panel's page. Only the name the
#   request was made to tells the two apart.
#
#   Sec-Fetch-Site, which every current browser sends and no page can set,
#   says same-origin. It says none when the browser opened the address by
#   itself, typed in or from a link in an email, and only a page is opened
#   that way, so the API refuses it.
#
#   Origin and Referer, when sent, name the very address the request was
#   made to.
#
# There is no CORS middleware, so another site's script cannot read an answer
# either, and no page of another site may show the panel in a frame of its
# own (NotInAFrame).

# The names the desktop panel is served on. Every launcher binds 127.0.0.1
# and opens http://127.0.0.1 at its port, and localhost is this computer by
# its other name.
_OWN_NAMES = {"127.0.0.1", "localhost", "::1"}
_HOST_RE = re.compile(r"^(\[[0-9a-f:.]+\]|[a-z0-9._-]+)(:[0-9]{1,5})?$")


def _host_name(value) -> str:
    """The name in a Host header, in lower case and without its port, or ""
    when the header is not a plain name or address."""
    m = _HOST_RE.match((value or "").strip().lower())
    return m.group(1).strip("[]") if m else ""


def _host_allowed(value) -> bool:
    """Whether a request was made to one of the panel's own addresses.
    PaperPull Server is reached by the NAS's address and names, so it keeps
    a list of its own (server_mode.host_allowed)."""
    name = _host_name(value)
    if server_mode.enabled():
        return server_mode.host_allowed(name)
    return name in _OWN_NAMES


def _same_origin_only(request: Request) -> None:
    """Refuse anything a different site set off, and anything the browser
    opened by itself.

    Origin and Referer answer this whenever they are sent, and a page can
    arrange for neither to be. An <img> does not carry an Origin, and a
    page that declares `no-referrer` strips the other, which left a plain
    GET able to reach this panel from a website somebody was merely
    visiting. /api/run is a GET, and it starts a download.

    Sec-Fetch-Site is the one that closes it. Every current browser sends
    it on every request, page script cannot set it, and it says plainly
    where the request came from, same-origin for the panel's own page and
    cross-site for somebody else's. It says none when the browser opened
    the address by itself, for an address typed into the bar or a link
    opened from an email, a chat or a PDF, and such a request carries no
    Origin or Referer either. The panel's own page never asks for the API
    that way, since its script uses fetch and EventSource, and the
    download buttons of PaperPull Server send the page to an address by
    script, which the browser marks same-origin. So none is refused here,
    where it let such a link start a run, and only the pages a browser
    opens by their address take it. The header is absent from curl and
    from browsers old enough not to know it, Safari before 16.4 among
    them, and those are allowed through, because the header being missing
    is not the same as it saying cross-site.

    None of that tells the panel's page from a page that pointed a name of
    its own at this computer, since the browser takes the two for one
    origin. The Host header does, so it has to be one of the panel's own
    addresses, and Origin and Referer have to name that very address, the
    port included, on the desktop and on PaperPull Server alike
    (server_mode.same_origin). An Origin of null, which a browser sends for
    a page that keeps its address to itself, and an empty one name no
    address at all, so both are refused, where the empty host they parse
    to used to pass for this computer.
    """
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not (_host_allowed(headers.get("host")) and server_mode.same_origin(headers)):
        # The one refusal a person meets by doing something ordinary,
        # opening an address of the API by hand, so it says why.
        if (headers.get("sec-fetch-site") or "").strip().lower() == "none":
            raise HTTPException(403, "only the panel's own page asks for this, never a link "
                                     "or an address typed in")
        raise HTTPException(403, "cross-origin request refused")


class OwnAddressOnly:
    """Every request, to a page, a file or the Browser Screen alike, has to
    be made to one of the panel's own addresses, and any other is refused
    before the rest of the panel sees it. _same_origin_only asks again for
    the API, so neither check depends on the other being in place."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        hosts = [v.decode("latin-1") for k, v in scope.get("headers") or [] if k.lower() == b"host"]
        if len(hosts) == 1 and _host_allowed(hosts[0]):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        said = _not_its_address(hosts[0] if len(hosts) == 1 else "", scope).encode("utf-8")
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(said)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": said})


def _not_its_address(host: str, scope) -> str:
    """What a request made to another address is told, which says what the
    right one is and nothing about the person."""
    if server_mode.enabled():
        return server_mode.not_its_name(_host_name(host))
    server = scope.get("server") or ()
    port = ":%d" % server[1] if len(server) > 1 and isinstance(server[1], int) else ""
    return ("This is PaperPull's control panel. It answers only at http://127.0.0.1%s "
            "and http://localhost%s, on this computer.\n" % (port, port))


def _frameable(path: str) -> bool:
    """Whether a page of the panel's own may show this answer in a frame,
    noVNC's files and the Browser Screen asking for the password again,
    which the panel's docked sign-in window shows in place of noVNC."""
    return path.startswith("/screen/novnc/") or path == "/screen/again"


class NotInAFrame:
    """No page of another site may show the panel inside one of its own,
    where a click it asks for could land on Run All instead. Every answer
    the panel makes says so, X-Frame-Options for older browsers and
    frame-ancestors for the rest, in a policy of its own beside any the
    answer already carries. noVNC's page alone may be framed by a page of
    the panel's own, since the Browser Screen of PaperPull Server is that
    page in a frame, and so may what stands in its place there."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        own = _frameable(scope.get("path", ""))

        async def framed(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                headers["X-Frame-Options"] = "SAMEORIGIN" if own else "DENY"
                headers.append("Content-Security-Policy",
                               "frame-ancestors 'self'" if own else "frame-ancestors 'none'")
            await send(message)

        await self.app(scope, receive, framed)


# The answers the same for everyone, which a browser may keep, the icon and
# the typefaces for a day, noVNC's files while they are still the image's.
_ANYONES = "/favicon.ico"
_ANYONES_UNDER = ("/fonts/", "/screen/novnc/")


class KeptPrivate:
    """Every answer the panel makes says two things more. nosniff, so a
    browser takes a file for the kind its answer names and never runs one
    as a script or shows it as a page because its bytes look like one. And
    no-store, so no browser or proxy keeps a copy of a page, a record, a
    spreadsheet or a download to show later, after a sign-out or to the
    next person at that computer, on every answer but the ones that are the
    same for everyone. An answer that said no-cache, a run's stream among
    them, is told no-store instead, since no-cache still lets a copy be
    kept. Answers made before the rest of the panel sees a request, a
    refusal of the address or of the sign-in, carry both too."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        anyones = path == _ANYONES or path.startswith(_ANYONES_UNDER)

        async def said(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                if not anyones and "no-store" not in (headers.get("cache-control") or "").lower():
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, said)


# Added after the server's sign-in gate, so these come first, the frame and
# privacy headers outermost of the panel's own, so that a refusal carries
# them too.
app.add_middleware(OwnAddressOnly)
app.add_middleware(NotInAFrame)
app.add_middleware(KeptPrivate)


def _desktop_only() -> None:
    """Showing a file in this computer's file manager, or choosing the
    folder the downloaders are in, means nothing on PaperPull Server, whose
    documents are in the shared folder it was given."""
    if server_mode.enabled():
        raise HTTPException(404, "not on PaperPull Server")


def _not_in_sample() -> None:
    """Anything that changes an archive is refused while the panel is
    looking at the sample. Reading it and building spreadsheets from it are
    the point, so those are not guarded."""
    if _SAMPLE is not None:
        raise HTTPException(409, "the panel is looking at the sample archive. "
                                 "Leave the sample first.")


def _entry_script(app_dir: Path):
    for p in sorted(app_dir.glob("*.py")):
        if ENTRY_RE.match(p.name):
            return p
    return None


def _server_template_for(install_dir: Path):
    """On PaperPull Server, the one shipped template an install runs, or None.

    Provider code on the server comes from the image, never from the data
    folder. An install is tied to its template by its single entry-shaped
    script's name, the same signal refresh_installs matches on. This is fail
    closed. The install must hold exactly one entry-shaped script, and that
    name must be the entry script of exactly one template the image ships,
    or the install does not map and nothing is run for it. A renamed
    provider folder still resolves, since its entry script keeps its name. A
    second, added or renamed script, or a name no template ships, does not,
    so a writable data folder cannot steer the server onto an unintended
    provider's code.
    """
    root = _templates_root()
    if root is None:
        return None
    entries = [p for p in sorted(install_dir.glob("*.py")) if ENTRY_RE.match(p.name)]
    if len(entries) != 1:
        return None
    name = entries[0].name
    matches = [d for d in root.iterdir()
               if d.is_dir() and (d / name).is_file()
               and _entry_script(d) is not None and _entry_script(d).name == name]
    if len(matches) != 1:
        return None
    return matches[0]


def _venv_python(app_dir: Path):
    r"""The app's own interpreter, on either venv layout.

    Windows puts it in .venv\Scripts\python.exe; macOS and Linux use
    .venv/bin/python."""
    for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
        candidate = app_dir / ".venv" / rel
        if candidate.exists():
            return candidate
    return None


def _python_for(app_dir: Path) -> str:
    """The interpreter to run one app with.

    The app's own venv when it has one, otherwise this program's own. In
    the packaged build that is the single bundled interpreter, which
    carries the shared core and every app's dependencies. In a checkout it
    is gui/.venv, the one environment setup-all builds for every app
    (#65). Before setup-all has filled it, it holds the panel's packages
    and none of an app's, and an app run under it died on `No module
    named 'paperpull_core'`, a sentence about the wrong interpreter that
    tells a tester nothing. The run endpoint refuses that case before it
    gets here (setup_needed)."""
    venv = _venv_python(app_dir)
    return str(venv) if venv else sys.executable


# What every app imports. In a checkout the panel's own interpreter runs
# an app with no venv of its own, so it has to have these, which setup-all
# gives it. The shared core brings pypdf with it.
APP_NEEDS = ("paperpull_core", "playwright", "pypdf")

# {(interpreter, PYTHONPATH, when its packages folder last changed): answer}
_RUNS_APPS: dict = {}


def _packages_stamp():
    """When this interpreter's packages folder last changed, which every pip
    install and uninstall does, or None."""
    try:
        return Path(sysconfig.get_paths()["purelib"]).stat().st_mtime_ns
    except (OSError, KeyError):
        return None


def _runs_apps() -> bool:
    """Whether this program's own interpreter can run an app, asked of a
    new process of it, as a run starts one.

    Asking this process would be wrong both ways. The naming page puts the
    core on the panel's own path, which no run inherits, and a core that
    setup-all installs while the panel is open reaches only a process
    started after it. The answer is kept until the packages folder
    changes, so a page that lists every app starts one process, not one
    for each. The page's first list of apps asks it off the event loop,
    and a request on the loop that asks again waits at most the limit."""
    key = (sys.executable, os.environ.get("PYTHONPATH", ""), _packages_stamp())
    if key not in _RUNS_APPS:
        probe = ("import importlib.util as u, sys; "
                 "sys.exit(not all(map(u.find_spec, %r)))" % (list(APP_NEEDS),))
        try:
            ok = subprocess.run([sys.executable, "-c", probe], cwd=str(HERE),
                                stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _RUNS_APPS.clear()
        _RUNS_APPS[key] = ok
    return _RUNS_APPS[key]


def setup_needed(meta: dict) -> str:
    """Why this app cannot be run yet, or "".

    Only ever true in a checkout, apart from the sample archive. The
    packaged build has no venv anywhere and does not need one, and in a
    checkout an app with no venv of its own runs on the panel's, once
    setup-all has given it what an app needs."""
    if _SAMPLE is not None:
        return ("This is the sample archive, so there is nothing to sign in "
                "to and nothing to download.\n\n"
                "Everything already in it was invented to show what a real "
                "archive looks like. Accounts and both spreadsheets "
                "work on it exactly as they would on yours.\n\n"
                "To see the sign-in step, leave the sample, add a provider, "
                "open it and press Open sign-in window. Your own browser opens "
                "on that provider's sign-in page. Nothing is downloaded until "
                "you have signed in there yourself, and PaperPull never sees "
                "what you type.")
    if _is_packaged() or _venv_python(Path(meta["dir"])) is not None or _runs_apps():
        return ""
    script = "setup-all.command" if sys.platform != "win32" else "setup-all.bat"
    return ("This provider is not set up yet, so there is nothing to run "
            "it with.\n\n"
            "  1. Open  %s\n"
            "  2. Double-click  %s  and let it finish\n"
            "  3. Come back here and RELOAD this page\n\n"
            "setup-all sets up every provider at once, in one environment "
            "they all share, so it is needed only once." % (HERE.parent, script))


def _login_flag(script: Path) -> str:
    try:
        text = script.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    return "--open-browser" if "--open-browser" in text else "--login"


def _accounts(app_dir: Path):
    accts = ["primary"]
    for cfg in sorted(app_dir.glob("config.*.json")):
        if cfg.name == "config.example.json":
            continue
        name = cfg.name[len("config."):-len(".json")]
        # Linux and macOS take a line break in a file name, and the panel
        # never makes such a config (_LABEL_RE), so one is not an account it
        # lists or runs. Its name would be on the command line each of its
        # runs shows, and in what the run prints. On the server /data may be
        # a shared folder others can write to.
        if not run_result.on_one_line(name):
            continue
        accts.append(name)
    return accts


def discover_apps():
    apps = {}
    if not apps_root().exists():
        return apps
    server = server_mode.enabled()
    for d in sorted(apps_root().iterdir()):
        # A provider folder whose name holds a line break, which Linux and
        # macOS allow, is not one the panel lists or runs, for the reason
        # _accounts gives.
        if not d.is_dir() or not run_result.on_one_line(d.name):
            continue
        script = _entry_script(d)
        if not script:
            continue
        if server:
            # PaperPull Server runs the image's copy of the provider, found
            # by its full path, with the image's own interpreter. The data
            # folder decides none of this, so a file changed or planted in
            # /data cannot change which code or interpreter runs. The login
            # flag is read from the trusted template, not the /data script.
            # An install that does not map to exactly one shipped template
            # is listed but not runnable (_start_run refuses it), rather
            # than falling back to anything in /data.
            tmpl = _server_template_for(d)
            tmpl_entry = _entry_script(tmpl) if tmpl else None
            apps[d.name] = {
                "name": d.name,
                "dir": str(d),
                "script": str(tmpl_entry) if tmpl_entry else script.name,
                "script_name": (tmpl_entry.name if tmpl_entry else script.name),
                "template_dir": str(tmpl) if tmpl else None,
                "python": sys.executable,
                "login_flag": _login_flag(tmpl_entry) if tmpl_entry else "--login",
                "accounts": _accounts(d),
                # The server never uses a /data virtual environment and needs
                # no setup, so both read honestly here.
                "has_venv": False,
                "needs_setup": False,
                "runnable": tmpl is not None,
                "reviews_names": _reviews_names(tmpl_entry),
            }
            continue
        apps[d.name] = {
            "name": d.name,
            "dir": str(d),
            "script": script.name,
            "script_name": script.name,
            "template_dir": None,
            "python": _python_for(d),
            "login_flag": _login_flag(script),
            "accounts": _accounts(d),
            "has_venv": _venv_python(d) is not None,
            # Only a checkout is ever told to run setup, and only until
            # setup-all has given the panel's own interpreter what an app
            # needs. The packaged app has no per-app venv and needs none,
            # the interpreter it falls back to carries everything, and
            # nothing in the sample is ever run, so there it is advice
            # about a problem that cannot arise.
            "needs_setup": (_SAMPLE is None and _venv_python(d) is None
                            and not _is_packaged() and not _runs_apps()),
            "runnable": True,
            "reviews_names": _reviews_names(script),
        }
    return apps


def _reviews_names(script) -> bool:
    """Whether an app has Review Names, which every receipt app has and no
    document app does (core/tests/test_every_app_reviews_a_name_once.py
    counts them). On the server it is the image's own script that says."""
    return bool(script) and Path(script).name.endswith("_receipts.py")


@app.get("/api/apps", dependencies=[Depends(_same_origin_only)])
def api_apps():
    refreshed = refresh_installs()
    apps = discover_apps()
    return {"apps_root": str(apps_root()), "root_source": root_source(), "actions": {k: v["label"] for k, v in ACTIONS.items()},
            "more_actions": list(MORE_ACTIONS), "redownload_actions": list(REDOWNLOAD_ACTIONS),
            "apps": apps, "refreshed": refreshed,
            # What the server's header says about where new documents go, and
            # why this host cannot give Chrome its sandbox, if it cannot.
            "server": ({"paperless": server_mode.paperless_connected(),
                        "sandbox": server_mode.sandbox_problem()}
                       if server_mode.enabled() else None)}


# -- the panel's tools ---------------------------------------------------------
#
# The Status tab, both spreadsheets, the sample and Add a person each run a
# script from tools/, loaded by its path. In a checkout, in the desktop
# package and in the server image it sits in tools/ beside the panel's own
# folder (server/build.py and server/Dockerfile carry every one the panel
# names, and gui/tests/test_every_panel_tool_reaches_the_server.py fails on
# one they leave out). Older desktop layouts kept some of them beside the
# installs instead, and the desktop still looks there for those.
#
# PaperPull Server never does. There the apps root is the shared folder,
# which anybody who may write to the share can fill, and a script found
# there would run inside the container that holds every signed-in browser
# profile.

def _tool_places(name: str) -> tuple:
    """Where tools/<name> may be, in the order looked."""
    own = HERE.parent / "tools" / name
    if server_mode.enabled():
        return (own,)
    return (own, apps_root() / name, apps_root().parent / name, HERE.parent / name)


# -- how current each archive is ---------------------------------------------

def _status_module():
    """tools/status.py, imported from wherever this deployment keeps it.

    The control panel can be run from the repo or from the folder holding the
    installs, and the reporter does not sit in the same place relative to both.
    If it cannot be found the panel says so and everything else carries on,
    because a missing report is no reason to lose the buttons that actually
    download things.
    """
    global _STATUS_MOD
    if _STATUS_MOD is not None:
        return _STATUS_MOD or None
    import importlib.util
    for cand in _tool_places("status.py"):
        try:
            if not cand.is_file():
                continue
            spec = importlib.util.spec_from_file_location("paperpull_status", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _STATUS_MOD = mod
            return mod
        except Exception:
            continue
    _STATUS_MOD = False
    return None


def _export_module():
    """tools/export_purchases.py, found the same way as the status reporter."""
    global _EXPORT_MOD
    if _EXPORT_MOD is not None:
        return _EXPORT_MOD or None
    import importlib.util
    for cand in _tool_places("export_purchases.py"):
        try:
            if not cand.is_file():
                continue
            spec = importlib.util.spec_from_file_location("paperpull_export", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _EXPORT_MOD = mod
            return mod
        except Exception:
            continue
    _EXPORT_MOD = False
    return None


@app.post("/api/export", dependencies=[Depends(_same_origin_only)])
async def api_export(request: Request):
    """Every purchase from every receipt archive under the root, as one
    spreadsheet written beside the installs. Rebuilt from the apps' own
    order-history CSVs each time, so nothing here reads a PDF and the file
    is never the copy anyone edits."""
    global _LAST_EXPORT
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    as_csv = bool(body.get("csv"))
    provider = str(body.get("provider") or "").strip() or None
    mod = _export_module()
    if mod is None:
        return {"ok": False, "reason": "export_purchases.py was not found next to this control panel."}
    if provider:
        # Only a provider the exporter itself found may be named, so the page
        # cannot steer the filename or the folder walk.
        known = {p["provider"].lower(): p["provider"] for p in mod.providers(apps_root())}
        if provider.lower() not in known:
            return {"ok": False, "reason": f"no order history for {provider!r} under {apps_root()}"}
        provider = known[provider.lower()]
    try:
        result = mod.export(apps_root(), None, provider, as_csv)
    except Exception as e:
        return {"ok": False, "reason": "the export failed, %s" % str(e).splitlines()[0][:120]}
    if not result["sources"]:
        return {"ok": False, "reason": "no '<Provider> Order History.csv' under %s. Receipt apps "
                "(Amazon, Target, Walmart, Gap) write one after a run." % apps_root()}
    _LAST_EXPORT = Path(result["path"])
    return {"ok": True, **result}


@app.get("/api/export/providers", dependencies=[Depends(_same_origin_only)])
def api_export_providers():
    """Which providers a spreadsheet makes sense for. Receipt archives have
    line items. Statement archives do not, and are left off the list rather
    than offered a button that would produce an empty file."""
    mod = _export_module()
    if mod is None:
        return {"available": False, "providers": []}
    try:
        return {"available": True, "providers": mod.providers(apps_root())}
    except Exception as e:
        return {"available": False, "providers": [], "reason": str(e).splitlines()[0][:120]}


def _transactions_tool() -> Optional[Path]:
    """tools/export_transactions.py, wherever this deployment keeps it. It
    runs as a subprocess rather than in-process, because reading hundreds
    of PDFs takes minutes and the page wants to watch it happen."""
    for cand in _tool_places("export_transactions.py"):
        if cand.is_file():
            return cand
    return None


@app.get("/api/export/transactions/providers", dependencies=[Depends(_same_origin_only)])
def api_export_transactions_providers():
    """Statement archives with PDFs on disk, the ones a transactions
    workbook can be built from."""
    tool = _transactions_tool()
    if tool is None:
        return {"available": False, "providers": [], "reason": "export_transactions.py was not found next to this control panel."}
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("paperpull_export_tx", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {"available": True, "providers": mod.providers(apps_root())}
    except Exception as e:
        return {"available": False, "providers": [], "reason": str(e).splitlines()[0][:120]}


def _event(data="", name: Optional[str] = None) -> str:
    """One event of a stream the page reads, the only way one is written
    (gui/tests/test_stream_lines.py holds every stream to it).

    The stream is lines, and an empty line ends an event, so its data is
    written as one line whatever it holds. A line break in it, which a name
    from the disk can carry on Linux and macOS (a person's config, a folder
    the panel lives in, a provider folder in /data on the server), is
    written as \\n and so can never end the event early or start a line
    naming another (a result, a done)."""
    return (("event: %s\n" % run_result.one_line(name) if name else "")
            + "data: %s\n\n" % run_result.one_line(data))


@app.get("/api/export/transactions", dependencies=[Depends(_same_origin_only)])
def api_export_transactions(provider: str = "", csv: str = ""):
    """Build the transactions workbook, streaming the tool's progress the
    way a run streams. Only a provider the tool itself lists may be named."""
    tool = _transactions_tool()
    if tool is None:
        raise HTTPException(404, "export_transactions.py was not found next to this control panel.")
    provider = (provider or "").strip()
    if provider:
        known = {p["provider"].lower(): p["provider"]
                 for p in api_export_transactions_providers().get("providers", [])}
        if provider.lower() not in known:
            raise HTTPException(400, f"no statement archive for {provider!r}")
        provider = known[provider.lower()]
    cmd = [sys.executable, str(tool), "--root", str(apps_root())]
    if provider:
        cmd += ["--provider", provider]
    if csv in ("1", "true", "yes"):
        cmd += ["--csv"]

    async def stream():
        global _LAST_EXPORT
        yield _event("$ export_transactions.py " + " ".join(cmd[3:]))
        # The version goes to the app so that a file it writes says which
        # build wrote it. Every failure file so far has carried an empty
        # version, which is the one field that says what a tester ran.
        # The mark is the one its line naming the spreadsheet carries, so
        # that only that line, never a provider's folder name it printed,
        # says which file Show and the server's download hand over.
        mark = run_result.new_mark()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   PAPERPULL_VERSION=VERSION, **{run_result.MARK_ENV: mark})
        try:
            proc = subprocess.Popen(cmd, cwd=str(tool.parent), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, env=env)
        except Exception as e:
            yield _event("[failed to start] %s" % e)
            yield _event(1, "done")
            return
        wrote = None
        try:
            while True:
                line = await to_thread.run_sync(proc.stdout.readline)
                if not line:
                    break
                said = run_result.exported(line.rstrip("\r\n"), mark)
                if said is not None:
                    wrote = said
                    continue
                yield _event(line.rstrip())
            code = await to_thread.run_sync(proc.wait)
            # It writes only into the folder it was given, so a path
            # anywhere else is not its spreadsheet.
            if code == 0 and wrote and Path(wrote).resolve().parent == apps_root().resolve():
                _LAST_EXPORT = Path(wrote)
                yield _event(json.dumps({"path": wrote}), "result")
            yield _event(code, "done")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if proc.stdout:
                proc.stdout.close()
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/export/reveal", dependencies=[Depends(_same_origin_only), Depends(_desktop_only)])
def api_export_reveal():
    """Show the last spreadsheet this panel wrote in the file manager. Takes no
    path from the page on purpose, only the one the server itself wrote."""
    p = _LAST_EXPORT
    if not p or not p.is_file():
        raise HTTPException(404, "nothing exported yet")
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except Exception as e:
        raise HTTPException(500, "could not open the folder, %s" % e)
    return {"ok": True}


@app.get("/api/export/download", dependencies=[Depends(_same_origin_only)])
def api_export_download():
    """On PaperPull Server, the last spreadsheet this panel wrote, handed to
    the browser, where the desktop shows it in a folder. Like reveal, it
    takes no path from the page, only the one the panel itself wrote.

    That name is in the data folder, often a share others can write, and
    one of them could have put a link there since the export ended, to the
    server's settings in /config or a signed-in profile. So it is opened
    again now, as a file of its own inside the folder the export was given,
    and sent from that same open (_open_plain), where a file response
    opened it again by name and followed a link."""
    if not server_mode.enabled():
        raise HTTPException(404)
    p = _LAST_EXPORT
    if not p or not os.path.lexists(p):
        raise HTTPException(404, "nothing exported yet")
    fd = _exported(p)
    if fd is None:
        raise HTTPException(404, "That spreadsheet is no longer the one this panel wrote. "
                                 "Export it again.")
    fh = os.fdopen(fd, "rb")
    size = os.fstat(fd).st_size

    def chunks():
        # No more than it held when it was opened, the length the browser
        # is told, though a share writer could still be adding to it.
        left = size
        try:
            while left > 0:
                part = fh.read(min(1024 * 1024, left))
                if not part:
                    return
                left -= len(part)
                yield part
        finally:
            fh.close()
    kind = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return StreamingResponse(chunks(), media_type=kind,
                             headers={**_attachment(p.name), "Content-Length": str(size)})


def _exported(p: Path):
    """An open handle on the spreadsheet at p, or None. Only a file of its
    own inside the folder both exports write into, the apps root, and on
    the server only when that folder is inside the data folder."""
    root = os.path.realpath(apps_root())
    if server_mode.enabled():
        data = os.path.realpath(server_mode.data_root())
        try:
            if os.path.commonpath([_same(root), _same(data)]) != _same(data):
                return None
        except ValueError:
            return None
    return _open_plain(p, root)


def _jsonable(value):
    """Dates arrive as date/datetime objects, which JSON cannot carry."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@app.get("/api/status", dependencies=[Depends(_same_origin_only)])
def api_status():
    """How current each archive is, and which periods look missing.

    Deliberately a plain def rather than async. The scan walks every install
    and reads each state file, which takes seconds across a full set, and a
    sync endpoint is handed to a worker thread instead of stalling the event
    loop while somebody is watching a download stream.
    """
    mod = _status_module()
    if mod is None:
        return {"available": False, "rows": [], "gaps": [],
                "reason": "status.py was not found next to this control panel.",
                "root": str(apps_root())}
    try:
        rows = mod.scan_all(apps_root())
    except Exception as e:
        return {"available": False, "rows": [], "gaps": [],
                "reason": "the scan failed, %s" % str(e).splitlines()[0][:120],
                "root": str(apps_root())}

    out, gaps = [], []
    for row in rows:
        try:
            grouped = [_jsonable(g) for g in mod.group_gaps(row.get("gaps") or [])]
        except Exception:
            grouped = []
        if grouped:
            gaps.append({"provider": row.get("provider") or row.get("folder"),
                         "windows": grouped})
        item = {k: _jsonable(v) for k, v in row.items() if k != "gaps"}
        item["label"] = mod.LABEL.get(row.get("status"), str(row.get("status")))
        item["cadence"] = mod._fmt_cadence(row.get("cadence_days"))
        out.append(item)
    return {"available": True, "root": str(apps_root()), "rows": out, "gaps": gaps}


# -- every account at a glance ---------------------------------------------------
#
# The home page answers "what needs me" with one row per provider and person.
# A row comes from three things, the status reporter run on that account's
# own folder, the panel's own record of the runs it started there, and
# whether one of them is running now. Nothing here says an account is signed
# in, since nothing short of a run can know that (a page with no sign-in
# challenge on it is not a session).

RUN_LOG = "panel-runs.json"
RUN_LOG_KEEP = 20
# (app name, account) -> {"action", "started"} for each run streaming now.
_RUNS: dict = {}
# The runs that download, whose ending decides whether an account was left
# partway. A Login, a Discover or a Verify that stops leaves nothing to
# continue, so it never makes a row say Continue.
DOWNLOAD_ACTIONS = ("pilot", "all", "resume")
# The files a row lists as the newest it saved.
LATEST_SHOWN = 4


def _account_root(meta: dict, account: str) -> Path:
    """The folder an account's documents and records are written to."""
    return server_mode.output_root(Path(meta["dir"]), account)


def _read_run_log(root: Path) -> list:
    try:
        raw = json.loads((root / RUN_LOG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _note_run(root: Path, entry: dict) -> None:
    """Put a run's outcome first in its account's run log, keeping the
    newest RUN_LOG_KEEP. Best effort. A folder that cannot be written keeps
    no log, and a run is never failed for it."""
    path = root / RUN_LOG
    text = json.dumps(([entry] + _read_run_log(root))[:RUN_LOG_KEEP], indent=1)
    try:
        # A new file of its own, never one already there. On the server the
        # folder is in the shared folder, where a link left at a fixed name
        # would have this write land wherever it points. The swap below
        # replaces a link at the log's own name rather than follow it.
        tmp = root / ("%s.%s.tmp" % (RUN_LOG, os.urandom(6).hex()))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                     0o666)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        return
    # On Windows a reader holding the log, OneDrive's sync, a virus scanner
    # or another tab reading the accounts, makes the swap fail for a moment.
    # A few short tries, since this can run on the panel's own thread when a
    # page goes away, then the leftover is cleared.
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            break
    try:
        tmp.unlink()
    except OSError:
        pass


def _saved_this_run(root: Path, started: float) -> list:
    """The names of the files a run saved, from the new-this-run.txt it
    wrote, for the page to list. A list older than the run is the last
    run's, left in place by a run that stopped before writing its own."""
    listed = root / "new-this-run.txt"
    try:
        if listed.stat().st_mtime < started:
            return []
        lines = listed.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    names = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\\/]", line)[-1]
        if name and name not in names:
            names.append(name)
    return names[:500]


def _latest_saved(root: Path) -> list:
    """The newest files an account saved, as {"name", "date"}, read from its
    own records. Names only, so nothing here ever names a path to open."""
    try:
        raw = json.loads((root / "progress.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    found = []
    for rec in raw.values() if isinstance(raw, dict) else ():
        if not isinstance(rec, dict):
            continue
        # A record from before an app wrote downloaded_ok has none at all,
        # and one it finished says Completed. Target's from before 0.41.1 are
        # that way, so its page said Nothing saved yet over 67 receipts. One
        # that says downloaded_ok false was not saved.
        ok = rec.get("downloaded_ok")
        if not (ok is True or (ok is None and rec.get("state") == "Completed")):
            continue
        name = rec.get("pdf_filename")
        if not isinstance(name, str) or not name.strip():
            continue
        when = rec.get("date") or rec.get("purchase_date") or ""
        found.append({"name": re.split(r"[\\/]", name)[-1],
                      "date": when if isinstance(when, str) else ""})
    found.sort(key=lambda f: f["date"], reverse=True)
    return found[:LATEST_SHOWN]


def _provider_of(meta: dict) -> tuple:
    """(provider name, kind) for an install, from its own storage.py, the
    way the welcome list reads a template."""
    try:
        src = (Path(meta["dir"]) / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        src = ""
    p, k = _PROVIDER_RE.search(src), _KIND_RE.search(src)
    name = meta["name"]
    for tail in (" Statements", " Receipts"):
        if name.endswith(tail):
            name = name[:-len(tail)]
    return (p.group(1) if p else name), (k.group(1) if k else "")


def _last_outcome(entry) -> str:
    """How a logged run ended, in one word the page turns into a sentence.
    "" for a run that finished cleanly or no run at all."""
    if not entry:
        return ""
    if entry.get("closed"):
        return "closed"
    code = entry.get("exit_code")
    result = entry.get("result") if isinstance(entry.get("result"), dict) else None
    if code == 130:
        return "interrupted"
    if code not in (0, None):
        return "failed"
    if result and result.get("stopped"):
        # A Resume that stopped because no run read the list to its end,
        # which only Pilot or Run All carries on from. Continue would only
        # stop there again (#124).
        return "unlisted" if result.get("list_not_read") else "stopped"
    if result and result.get("attention"):
        return "attention"
    return ""


# The order the home page lists accounts in, most in need first.
STATE_ORDER = ("stopped", "attention", "unreadable", "overdue", "due", "gap",
               "never", "not_started", "nostatus", "unknown", "current", "ongoing")


def _account_state(row, outcome: str, gaps: list, known: bool = True) -> str:
    """One word for where an account stands. A run that did not finish
    comes first, since the next step is to continue it. Then what the last
    run left to look at, then how current the archive is, then gaps. An
    archive whose status could not be read is never called not started."""
    if outcome in ("closed", "interrupted", "failed", "stopped", "unlisted"):
        return "stopped"
    if outcome == "attention":
        return "attention"
    if row is None:
        return "not_started" if known else "nostatus"
    status = str(row.get("status") or "")
    if status in ("unreadable", "overdue", "due", "never"):
        return status
    if gaps:
        return "gap"
    return status if status in STATE_ORDER else "unknown"


def _owner_of(meta: dict, account: str) -> str:
    """The account holder's name as the account's config gives it, or ""."""
    config = Path(meta["dir"]) / ("config.json" if account == "primary"
                                  else "config.%s.json" % account)
    try:
        owner = json.loads(config.read_text(encoding="utf-8-sig")).get("owner")
    except (OSError, ValueError, AttributeError):
        return ""
    return owner.strip()[:80] if isinstance(owner, str) else ""


def _account_row(mod, cards: dict, name: str, meta: dict, provider: str, kind: str,
                 slug: str, account: str) -> dict:
    """One provider and person, with where they stand."""
    root = _account_root(meta, account)
    row, known = None, mod is not None
    if mod is not None:
        try:
            row = mod.scan_install(root)
        except Exception:
            row, known = None, False
    gaps = []
    if row is not None:
        try:
            gaps = [_jsonable(g) for g in mod.group_gaps(row.get("gaps") or [])]
        except Exception:
            gaps = []
    log = _read_run_log(root)
    last = next((e for e in log if e.get("action") in DOWNLOAD_ACTIONS), None)
    outcome = _last_outcome(last)
    running = _RUNS.get((name, account))
    return {
        "app": name, "account": account, "provider": provider,
        "owner": _owner_of(meta, account),
        "gets": cards.get(slug, {}).get("documents", ""),
        "kind": (row or {}).get("kind") or kind,
        "state": _account_state(row, outcome, gaps, known),
        "documents": (row or {}).get("documents") or 0,
        "newest": _jsonable((row or {}).get("newest")),
        # When the app last finished a run at all, from its own run
        # summary, so a run from a terminal counts as a check too.
        "checked": _jsonable((row or {}).get("last_run")),
        "age_days": (row or {}).get("age_days"),
        "cadence_days": (row or {}).get("cadence_days"),
        "cadence": mod._fmt_cadence((row or {}).get("cadence_days")) if mod else "-",
        "gaps": gaps,
        "last_run": last, "last_outcome": outcome,
        "runs": log[:5],
        "latest": _latest_saved(root),
        "running": dict(running) if running else None,
        "runnable": meta.get("runnable", True),
        "needs_setup": meta.get("needs_setup", False),
    }


def account_rows() -> list:
    """Every provider and person, with where each stands. One account that
    cannot be read, a config written by hand say, gets a row that says so
    and never takes the others' rows down with it."""
    mod = _status_module()
    cards = _provider_notes()
    rows = []
    for name, meta in discover_apps().items():
        provider, kind = _provider_of(meta)
        # The template an install came from is named for its entry script,
        # chase_docs.py for apps/chase, which is how its line is found.
        slug = str(meta.get("script_name") or "").rsplit("_", 1)[0]
        for account in meta["accounts"]:
            try:
                rows.append(_account_row(mod, cards, name, meta, provider, kind, slug, account))
            except Exception:
                running = _RUNS.get((name, account))
                rows.append({
                    "app": name, "account": account, "provider": provider, "owner": "",
                    "gets": cards.get(slug, {}).get("documents", ""), "kind": kind,
                    "state": "nostatus", "documents": 0, "newest": None, "checked": None,
                    "age_days": None, "cadence_days": None, "cadence": "-", "gaps": [],
                    "last_run": None, "last_outcome": "", "runs": [], "latest": [],
                    "running": dict(running) if running else None,
                    "runnable": meta.get("runnable", True),
                    "needs_setup": meta.get("needs_setup", False)})
    order = {s: i for i, s in enumerate(STATE_ORDER)}
    rows.sort(key=lambda r: (order.get(r["state"], len(order)), -(r["age_days"] or 0),
                             r["provider"].lower(), r["account"] != "primary", r["account"]))
    return rows


@app.get("/api/accounts", dependencies=[Depends(_same_origin_only)])
def api_accounts():
    """The home page's rows. A plain def, so the folder walk runs in a
    worker thread and a download streaming meanwhile is not held up."""
    return {"root": str(apps_root()), "root_source": root_source(),
            "status_available": _status_module() is not None,
            "accounts": account_rows()}


@app.post("/api/reveal", dependencies=[Depends(_same_origin_only), Depends(_desktop_only)])
async def api_reveal(request: Request):
    """Show one account's folder in the file manager. Takes the app's name
    and the account, both checked against what the panel itself found, and
    never a path."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    name = str((body or {}).get("app") or "")
    account = str((body or {}).get("account") or "primary")
    apps = discover_apps()
    if name not in apps or account not in apps[name]["accounts"]:
        raise HTTPException(404, "unknown app or account")
    try:
        folder = _account_root(apps[name], account)
    except ValueError:
        raise HTTPException(404, "that account's config names no folder PaperPull can read")
    if not folder.is_dir():
        raise HTTPException(404, "that account has no folder yet")
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        raise HTTPException(500, "could not open the folder, %s" % e)
    return {"ok": True}



@app.post("/api/sample", dependencies=[Depends(_same_origin_only)])
async def api_sample(request: Request):
    """Look at the sample archive, or stop looking at it.

    Takes {"on": true} or {"on": false}. Turning it on copies the shipped
    sample somewhere writable the first time and points the panel there.
    Turning it off puts the panel back on whatever root it had, which was
    never changed, because this is a mode and not a setting.
    """
    global _SAMPLE, _STATUS_MOD, _EXPORT_MOD
    try:
        body = await request.json()
    except Exception:
        body = {}
    _SAMPLE = _open_sample() if (body or {}).get("on", True) else None
    _STATUS_MOD = None      # both are looked for relative to the root
    _EXPORT_MOD = None
    return {"sample": _SAMPLE is not None, "root": str(apps_root()),
            "apps": _looks_like_installs(apps_root())}


@app.get("/api/root", dependencies=[Depends(_same_origin_only)])
def api_root_get():
    root = apps_root()
    return {"root": str(root), "exists": root.is_dir(),
            "apps": _looks_like_installs(root), "source": root_source(),
            "settings_file": str(_settings_path())}


@app.post("/api/root", dependencies=[Depends(_same_origin_only), Depends(_desktop_only),
                                     Depends(_not_in_sample)])
async def api_root_set(request: Request):
    """Remember where the downloaders live.

    Takes a folder path typed into the page. It must exist and it must be a
    folder, and the response says how many apps were found there so the
    person can tell at once whether they pointed at the right place. It does
    not refuse an empty folder outright, because pointing at a folder before
    moving the installs into it is a reasonable order of operations.
    """
    if os.environ.get("APPS_ROOT"):
        raise HTTPException(409, "APPS_ROOT is set in the environment, which "
                                 "overrides any saved choice. Unset it first.")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    raw = str((body or {}).get("root") or "").strip().strip('"')
    if not raw:
        raise HTTPException(400, "no folder given")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise HTTPException(400, "give the full path, starting from the drive "
                                 "or from /")
    if not root.is_dir():
        raise HTTPException(400, "that folder does not exist")
    data = _read_settings()
    data["apps_root"] = str(root.resolve())
    try:
        _write_settings(data)
    except OSError as e:
        raise HTTPException(500, "could not save the choice: %s" % e)
    global _STATUS_MOD, _EXPORT_MOD
    _STATUS_MOD = None      # the status report is looked for relative to root
    _EXPORT_MOD = None      # and so is the exporter
    return {"root": str(root.resolve()), "exists": True,
            "apps": _looks_like_installs(root), "source": "settings",
            "settings_file": str(_settings_path())}


# -- setting up from nothing --------------------------------------------------
#
# A brand-new user has nothing to point at. Asking them where their
# downloaders are is a question they cannot answer, and the first version of
# this panel asked exactly that. What they need is to choose a folder, tick
# the providers they hold accounts with, and have the installs made for them
# from the templates the package already ships.

# Either quote, and a double-quoted name may hold an apostrophe. The first
# version stopped at any quote, which read provider="Lowe's" as "Lowe".
_PROVIDER_RE = re.compile(r"""provider\s*=\s*["']((?<=")[^"]+(?=")|(?<=')[^']+(?='))""")
_KIND_RE = re.compile(r"kind\s*=\s*(DOCUMENT|RECEIPT)")

# Never copied into a new install. A template in a repo checkout can have all
# of these sitting beside the code.
_TEMPLATE_SKIP = {".venv", "__pycache__", ".pytest_cache", "tests", "Backups",
                  "Logs", "Diagnostics", "Manual Review", "config.json",
                  "progress.json", "discovery.json"}


def _is_someones_own(name: str) -> bool:
    """A file that belongs to whoever set that folder up, not to the code.

    config.json was listed by name, and a second person's account is
    config.<label>.json, which no list knew about. In a checkout used as
    the template root, one of those on disk would have been copied into
    every install as though it were part of the app, handing them an
    account nobody asked for, pointing at somebody else's folders and
    carrying their name. config.example.json is the one that does ship,
    because it is the template for a config rather than one.
    """
    low = name.lower()
    if low == "config.example.json":
        return False
    return low.startswith("config.") and low.endswith(".json")


def _templates_root() -> Path | None:
    """Where the shipped app code lives. templates/apps in a package, apps/ in
    a checkout. None when neither exists."""
    for cand in (HERE.parent / "templates" / "apps", HERE.parent / "apps"):
        if cand.is_dir() and any(_entry_script(d) for d in cand.iterdir() if d.is_dir()):
            return cand
    return None


def _is_packaged() -> bool:
    """True inside the built package (templates/apps and no apps/ checkout).
    A checkout has Python and per-app venvs, the package has neither."""
    return ((HERE.parent / "templates" / "apps").is_dir()
            and not (HERE.parent / "apps").is_dir())


LAUNCHER_SUFFIXES = (".bat", ".command")

# The double-click files that also run in a folder the packaged app made,
# which has no venv, because they look for the app's own Python when the
# folder has no setup file (see tools/make_unix_launchers.py). review_names
# asks for one name at a time, so it cannot run in the panel. The rest call
# a venv the package never makes, or a system Python it cannot assume.
PACKAGED_LAUNCHERS = {"review_names.bat", "review_names.command"}


def _launcher_left_out(item: Path) -> bool:
    """Whether a template file is a double-click file this install could
    not run. A checkout install gets every one, a packaged install only
    those that find the app's own Python."""
    return (item.suffix.lower() in LAUNCHER_SUFFIXES and _is_packaged()
            and item.name.lower() not in PACKAGED_LAUNCHERS)


PROVIDER_CARDS = HERE / "providers.json"


def _provider_notes() -> dict:
    """What each app downloads, in a line written for the person choosing
    providers, keyed by slug, from providers.json beside this file.

    The welcome list used to show the "What it downloads" column of
    PROVIDERS.md, which is written for GitHub and carries who tested an app,
    issue numbers and how it reads the site, so a new user picking their
    bank read "Confirmed by @watling777 ... (#26)". providers.json holds the
    short line, the group the provider sits in and whether it has been run
    on a real account yet. Best effort. A missing or broken file just means
    no note, never another document's text."""
    try:
        data = json.loads(PROVIDER_CARDS.read_text(encoding="utf-8"))
        groups, cards = data["groups"], data["providers"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    notes = {}
    for slug, card in cards.items() if isinstance(cards, dict) else ():
        if not isinstance(card, dict):
            continue
        group = card.get("group", "")
        notes[slug] = {"documents": card.get("gets", ""),
                       "group": group,
                       "category": groups.get(group, "") if isinstance(groups, dict) else "",
                       "tested": card.get("tested", True) is not False,
                       "note": card.get("note", "")}
    return notes


def install_folder_name(provider: str, kind: str) -> str:
    """"Chase Statements", "Amazon Receipts". The same convention the existing
    installs use, so a folder made here sits naturally beside one made by
    hand."""
    return "%s %s" % (provider, "Receipts" if kind == "RECEIPT" else "Statements")


def list_providers() -> list:
    """Every provider an install can be made for, with what it downloads."""
    root = _templates_root()
    if root is None:
        return []
    notes = _provider_notes()
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not _entry_script(d):
            continue
        try:
            src = (d / "storage.py").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            src = ""
        p = _PROVIDER_RE.search(src)
        k = _KIND_RE.search(src)
        provider = p.group(1) if p else d.name
        kind = k.group(1) if k else "DOCUMENT"
        n = notes.get(d.name, {})
        out.append({"slug": d.name, "provider": provider, "kind": kind,
                    "folder": install_folder_name(provider, kind),
                    "documents": n.get("documents", ""),
                    "category": n.get("category", ""),
                    "group": n.get("group", ""),
                    "tested": n.get("tested", True),
                    "note": n.get("note", "")})
    return out


def create_install(root: Path, slug: str, owner: str = "") -> str:
    """Make one install from its template. Returns "created" or "exists".
    Never overwrites, because an existing folder may hold years of history."""
    tmpl_root = _templates_root()
    if tmpl_root is None:
        raise HTTPException(500, "no templates are available to create from")
    src = tmpl_root / slug
    if not src.is_dir() or not _entry_script(src):
        raise HTTPException(400, "unknown provider %r" % slug)
    info = next(p for p in list_providers() if p["slug"] == slug)
    dst = root / info["folder"]
    if dst.exists():
        return "exists"
    # Most double-click launchers call .venv\Scripts\python.exe, which the
    # packaged app never has, and setup.bat wants a system Python it cannot
    # assume. Copied into a packaged install they are a folder of files that
    # all fail, right where a new user goes looking. The panel does their
    # job. review_names finds the app's own Python, so it goes in
    # (_launcher_left_out).
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        # Exact names, plus anything profile-shaped. A profile folder is
        # named <slug>-browser-profile, and in a repo checkout it can be
        # sitting there signed in. The test that copies a fake one with a
        # Cookies file inside is what caught this.
        if any(part in _TEMPLATE_SKIP or _is_someones_own(part)
               or "browser-profile" in part.lower()
               or part.lower().endswith(".pdf")
               for part in rel.parts):
            continue
        if _launcher_left_out(item):
            continue
        if item.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        else:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / rel)
    example = dst / "config.example.json"
    if example.is_file():
        # The example IS the config for a fresh install. Its output_dir and
        # profile_dir are relative to the install folder, and its port is
        # already unique to this app.
        shutil.copy2(example, dst / "config.json")
    if owner:
        _set_owner(dst / "config.json", owner)
    if server_mode.enabled():
        _set_profile(dst / "config.json", server_mode.profile_for(dst.name))
    return "created"


def _set_profile(config: Path, profile: str) -> None:
    """Where an install's signed-in browser profile lives. On PaperPull
    Server that is the profiles volume, since the install itself is in the
    shared folder, which anyone the share is open to can read. A run there
    takes the profile from the volume whatever the file says
    (paperpull_core.storage.server_profile_dir), so this keeps the file
    saying what is true."""
    if not server_mode.own_file(config):
        return
    with _CONFIG_WRITES:
        try:
            data = json.loads(config.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        data["profile_dir"] = profile
        _write_text(config, json.dumps(data, indent=2))


def _set_owner(config: Path, owner: str) -> None:
    """The account holder's name, written once when the install is made.

    An app asks for this on its first run at a console. Started from this
    panel its stdin is closed, so it cannot ask and the name stays empty,
    and an empty name is the one thing that stops redaction taking a
    person's name out of a survey or a recording. So it is asked for
    here, where somebody is looking at a screen."""
    if not server_mode.own_file(config):
        return
    try:
        with _CONFIG_WRITES:
            data = json.loads(config.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                return
            data["owner"] = owner[:80]
            _write_text(config, json.dumps(data, indent=2))
    except (OSError, ValueError):
        pass


def _write_text(path: Path, text: str) -> None:
    """path.write_text, and on PaperPull Server a new file moved into its
    place in a folder held inside the data folder, so a link left at the
    name in the shared folder is replaced rather than written through."""
    if server_mode.enabled():
        server_mode.write_in_data(path, text)
    else:
        path.write_text(text, encoding="utf-8")


def _replace_text(path: Path, text: str) -> None:
    """Written beside itself and moved into place, so a crash part way
    leaves the old file whole. On the server the file beside it is a new
    one of its own, never a fixed name a link could be left at."""
    if server_mode.enabled():
        server_mode.write_in_data(path, text)
        return
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _make_folder(folder: Path) -> None:
    """mkdir, held inside the data folder first on the server."""
    server_mode.hold_in_data(folder)
    folder.mkdir(parents=True, exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    """shutil.copy2, and on the server a copy written the way
    _write_text writes, which never writes through a link at dst."""
    if not server_mode.enabled():
        shutil.copy2(src, dst)
        return
    server_mode.write_in_data(dst, Path(src).read_bytes())
    shutil.copystat(src, dst)


def _template_files(src: Path):
    """The files a template ships to an install, the same filter the first
    copy uses. Sorted, since rglob yields in whatever order the filesystem
    lists, which APFS does not keep by name, and the refresh reports these
    files in this order (#111)."""
    for item in sorted(src.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        if any(part in _TEMPLATE_SKIP or _is_someones_own(part)
               or "browser-profile" in part.lower()
               or part.lower().endswith(".pdf") for part in rel.parts):
            continue
        if _launcher_left_out(item):
            continue
        yield rel, item


def refresh_install_code(dst: Path, src: Path) -> list:
    """Bring one install's code up to the shipped version. Returns the
    files replaced.

    An install is made by copying a template once, and until this existed
    it was never touched again: a provider fix shipped in a release reached
    new installs only, and everyone who had already set the provider up
    kept running the code from the day they did. The first AT&T tester
    installed the release with the repair, clicked Diagnose, and sent back
    a survey from the old code, which is how this was found.

    Only what the template ships is compared, byte for byte, so config,
    progress, the PDFs and the browser profile are never in question. A
    file that differs is backed up under Backups/code-<time>/ before it is
    replaced, so an edited document_rules.json is a copy away."""
    replaced = []
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    for rel, item in _template_files(src):
        target = dst / rel
        new = item.read_bytes()
        # On the server a file left as a link in the shared folder is
        # replaced and never read, so what it leads to is neither compared,
        # backed up into the share nor written.
        through_link = server_mode.enabled() and not server_mode.own_file(target)
        try:
            if not through_link and target.is_file() and target.read_bytes() == new:
                continue
        except OSError:
            continue
        if not through_link and target.is_file():
            bak = dst / "Backups" / ("code-" + stamp) / rel
            _make_folder(bak.parent)
            _copy_file(target, bak)
        _make_folder(target.parent)
        _copy_file(item, target)
        replaced.append(str(rel))
    replaced.extend(ensure_core(dst, stamp))
    replaced.extend("config.json: " + k for k in ensure_settings(dst, stamp))
    return replaced


def ensure_settings(dst: Path, stamp: str = "") -> list:
    """Settings the template has gained since this install was made.

    config.example.json becomes config.json once, when an install is
    created, and is never looked at again. So a setting added to a
    provider afterwards reaches new installs only, and everybody who set
    that provider up earlier carries on as though it did not exist. That
    is how the wrong-document check came to be switched on in six
    templates and off in all six installs.

    Only keys the install does not have are added. A value somebody
    changed is theirs and is never touched, and neither is a key the
    template has dropped, because an old setting still doing a job is
    not this function's business.

    The file is backed up before it is written, like the code is."""
    example, live = dst / "config.example.json", dst / "config.json"
    if not (example.is_file() and live.is_file()):
        return []
    if not (server_mode.own_file(live) and server_mode.own_file(example)):
        return []
    # Read and written as the panel's other writes of a config are.
    with _CONFIG_WRITES:
        return _add_settings(dst, example, live, stamp)


def _add_settings(dst: Path, example: Path, live: Path, stamp: str) -> list:
    try:
        template = json.loads(example.read_text(encoding="utf-8-sig"))
        current = json.loads(live.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(template, dict) or not isinstance(current, dict):
        return []

    added = [k for k in template
             if k not in current and not str(k).startswith("//")]
    if not added:
        return []
    merged = dict(current)
    for key in added:
        merged[key] = template[key]
    try:
        bak = dst / "Backups" / ("code-" + (stamp or "settings")) / "config.json"
        _make_folder(bak.parent)
        _copy_file(live, bak)
        _write_text(live, json.dumps(merged, indent=2) + "\n")
    except OSError:
        return []
    return added


def _site_packages(venv: Path):
    """Where a venv keeps its packages, on either platform."""
    for rel in ("Lib/site-packages", "lib/site-packages"):
        d = venv / rel
        if d.is_dir():
            return d
    for d in sorted(venv.glob("lib/python*/site-packages")):
        if d.is_dir():
            return d
    return None


def ensure_core(dst: Path, stamp: str = "") -> list:
    """The shared core inside one checkout install's venv, current.

    A checkout install carries its own copy of paperpull_core, and an
    entry script written against a newer core than that copy dies on
    Login over a keyword the copy never heard of. The package has no
    venv, its interpreter carries the core, so there is nothing to do.

    It also SEEDS the copy when there is none, which is the case for
    every provider added from this panel. setup.bat installs the core
    from the repo two folders up when the install sits inside it, or
    from a wheel the packaged build ships. An install made here has
    neither,
    so setup finished cleanly and left a venv that could not import
    anything. Found by adding Costco and running it.

    An install inside this checkout is the exception. Its setup.bat finds
    the core two folders up and installs it editable, so it already runs
    the checkout's core as it changes, and a copy put beside that wins
    every import. Nothing ever refreshed such a copy, since refresh_installs
    passes over the checkout's own apps, so every core change after the
    day it was made missed that app. So nothing is copied there, and a copy
    an earlier panel left is taken out."""
    if server_mode.enabled():
        # The server runs every app with the image's own core, and never an
        # install's venv, so a .venv in the shared folder is only something
        # a copy could be written through.
        return []
    core_src = HERE.parent / "core" / "paperpull_core"
    venv = dst / ".venv"
    if not core_src.is_dir() or not venv.is_dir():
        return []
    if _on_checkout_editable_core(dst):
        _drop_core_copy(venv)
        return []
    stamp = stamp or datetime.now().strftime("%Y-%m-%d-%H%M%S")
    pkg = None
    for init in venv.rglob("paperpull_core/__init__.py"):
        pkg = init.parent
        break
    if pkg is None:
        site = _site_packages(venv)
        if site is None:
            return []
        pkg = site / "paperpull_core"
        try:
            pkg.mkdir(parents=True, exist_ok=True)
        except OSError:
            return []
    out = []
    for item in sorted(core_src.glob("*.py")):
        target = pkg / item.name
        new = item.read_bytes()
        try:
            if target.is_file() and target.read_bytes() == new:
                continue
            if target.is_file():
                bak = dst / "Backups" / ("code-" + stamp) / "paperpull_core" / item.name
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, bak)
            shutil.copy2(item, target)
        except OSError:
            continue
        out.append("paperpull_core/" + item.name)
    return out


def _editable_core(venv: Path):
    """The core folder an editable install in this venv runs, or None.

    `pip install -e` leaves the package in its source folder and puts only
    a finder in site-packages, which Python asks after its own search of
    site-packages, so a paperpull_core folder there wins over it. pip
    records the install in the dist-info's direct_url.json (PEP 610), which
    says whether it is editable and where the source is. None as well when
    that source no longer holds a core, as after the checkout was moved,
    since then the venv has no core of its own to run, and when the source
    is the folder in site-packages itself, which is no editable install. A
    file this cannot read is passed over, so it never stops the listing."""
    site = _site_packages(venv)
    if site is None:
        return None
    for info in sorted(site.glob("paperpull_core-*.dist-info")):
        try:
            data = json.loads((info / "direct_url.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        dir_info = data.get("dir_info")
        if not (isinstance(dir_info, dict) and dir_info.get("editable") is True):
            continue
        try:
            url = urllib.parse.urlparse(str(data.get("url", "")))
            if url.scheme != "file" or url.netloc not in ("", "localhost"):
                continue
            pkg = Path(urllib.request.url2pathname(url.path)) / "paperpull_core"
            if ((pkg / "__init__.py").is_file()
                    and pkg.resolve() != (site / "paperpull_core").resolve()):
                return pkg
        except (OSError, ValueError):
            continue
    return None


def _on_checkout_editable_core(dst: Path) -> bool:
    """Whether an install sits inside the checkout this panel runs from and
    its venv runs the core as an editable install, which is what the app's
    own setup.bat makes there."""
    if _is_packaged():
        return False
    try:
        inside = dst.resolve().is_relative_to(HERE.parent.resolve())
    except OSError:
        return False
    return inside and _editable_core(dst / ".venv") is not None


def _drop_core_copy(venv: Path) -> bool:
    """Take out a paperpull_core folder sitting in site-packages over an
    editable install. pip keeps an editable package in its source folder,
    so only an earlier panel's ensure_core put one there. It is renamed off
    the import path in one step first, so a failure part way through never
    leaves half a package for an import to find, and then deleted. A link
    is someone's own doing and is left alone. True when a copy came out."""
    site = _site_packages(venv)
    if site is None:
        return False
    pkg = site / "paperpull_core"
    try:
        if not pkg.is_dir() or pkg.resolve() != pkg.parent.resolve() / pkg.name:
            return False
        gone = site / ("paperpull_core-panel-copy-%d" % time.time_ns())
        pkg.rename(gone)
    except OSError:
        return False
    shutil.rmtree(gone, ignore_errors=True)
    return True


_REFRESHED_ROOTS: set = set()


def refresh_installs(force: bool = False) -> dict:
    """Every install under the apps root, brought up to the shipped code,
    once per panel run per root. Returns {install folder: [files]} for the
    ones that changed. An install is matched to its template by the entry
    script's name, so a renamed folder still gets its provider's code."""
    if _SAMPLE is not None:
        # The sample's entry scripts are stubs and its folders are named
        # after providers, so this would happily fill it with real app code
        # and a Backups folder. Nothing in it is ever run, so nothing in it
        # needs updating.
        return {}
    root = apps_root()
    key = str(root)
    seeded = _seed_missing_cores(root)
    if key in _REFRESHED_ROOTS and not force:
        return seeded
    _REFRESHED_ROOTS.add(key)
    tmpl_root = _templates_root()
    if tmpl_root is None or not root.is_dir():
        return seeded
    by_entry = {}
    for d in tmpl_root.iterdir():
        if d.is_dir():
            script = _entry_script(d)
            if script:
                by_entry[script.name] = d
    out = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name in _RUNNING:
            continue
        script = _entry_script(d)
        src = by_entry.get(script.name) if script else None
        if src is None or src.resolve() == d.resolve():
            continue
        try:
            changed = refresh_install_code(d, src)
        except OSError:
            continue
        if changed:
            out.setdefault(d.name, []).extend(changed)
    return out


def _seed_missing_cores(root: Path) -> dict:
    """Any install whose venv has no core yet, given one.

    Cheap enough to do on every call, unlike the file sweep above, and it
    has to be, because setup.bat is run after the panel has already
    started and a memo would leave the answer a restart away."""
    out = {}
    if not root.is_dir():
        return out
    try:
        installs = sorted(root.iterdir())
    except OSError:
        return out
    for d in installs:
        if not d.is_dir() or d.name in _RUNNING or not _entry_script(d):
            continue
        venv = d / ".venv"
        if not venv.is_dir():
            continue
        # An install in this checkout on an editable core goes to ensure_core
        # even with a copy in it, which is how a copy an earlier panel left
        # there comes out. Nothing else ever looks at the checkout's own apps.
        if (not _on_checkout_editable_core(d)
                and any(True for _ in venv.rglob("paperpull_core/__init__.py"))):
            continue
        made = ensure_core(d)
        if made:
            out[d.name] = made
    return out


@app.get("/api/providers", dependencies=[Depends(_same_origin_only)])
def api_providers():
    installed = set()
    root = apps_root()
    if root.is_dir():
        installed = {d.name for d in root.iterdir() if d.is_dir() and _entry_script(d)}
    out = list_providers()
    for p in out:
        p["installed"] = p["folder"] in installed
    suggested = (server_mode.data_root() if server_mode.enabled()
                 else Path.home() / "Documents" / "PaperPull")
    return {"providers": out, "templates": _templates_root() is not None,
            "suggested_root": str(suggested), "server": server_mode.enabled()}


@app.post("/api/create", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_create(request: Request):
    """Make installs for the chosen providers under the chosen folder, and
    remember that folder. The folder is created if it does not exist, since a
    new user has no reason to have made one first.

    On PaperPull Server there is no choosing. Every install goes in the
    shared folder the container was given, whatever the page sent, and
    nothing is remembered, since the image sets that folder every start."""
    server = server_mode.enabled()
    if os.environ.get("APPS_ROOT") and not server:
        raise HTTPException(409, "APPS_ROOT is set in the environment, which "
                                 "overrides any saved choice. Unset it first.")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    raw = str((body or {}).get("root") or "").strip().strip('"')
    if server:
        raw = str(server_mode.data_root())
    owner = str((body or {}).get("owner") or "").strip()[:80]
    slugs = (body or {}).get("providers") or []
    if not raw:
        raise HTTPException(400, "no folder given")
    if not isinstance(slugs, list) or not slugs:
        raise HTTPException(400, "choose at least one provider")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise HTTPException(400, "give the full path, starting from the drive "
                                 "or from /")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, "could not create that folder: %s" % e)

    created, existed = [], []
    for slug in slugs:
        if not isinstance(slug, str):
            continue
        result = create_install(root, slug, owner=owner)
        (created if result == "created" else existed).append(slug)

    if not server:
        data = _read_settings()
        data["apps_root"] = str(root.resolve())
        try:
            _write_settings(data)
        except OSError as e:
            raise HTTPException(500, "could not save the choice: %s" % e)
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"root": str(root.resolve()), "created": created, "existed": existed,
            "owner": owner, "apps": _looks_like_installs(root)}


# -- a second person's account ------------------------------------------------
#
# The panel's Account dropdown lists config.<name>.json files beside an
# app's config.json, and every action passes the chosen one as --config, so
# a second account is its own folder, profile and port with nothing shared.
# Making one used to need a terminal, which a packaged Mac install does not
# put on the PATH. tools/add_account.py does the work, the same code the
# launcher's add-account command runs.

_ACCOUNT_MOD = None
_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _account_module():
    global _ACCOUNT_MOD
    if _ACCOUNT_MOD is not None:
        return _ACCOUNT_MOD or None
    import importlib.util
    for cand in _tool_places("add_account.py"):
        try:
            if not cand.is_file():
                continue
            spec = importlib.util.spec_from_file_location("paperpull_add_account", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _ACCOUNT_MOD = mod
            return mod
        except Exception:
            continue
    _ACCOUNT_MOD = False
    return None


@app.post("/api/account", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_account(request: Request):
    """Make config.<label>.json for one app, a second person's account with
    its own folder beside the first one's, its own browser profile and its
    own debugging port. The app must be one the panel discovered, the label
    is kept to a filename-safe slug, and an existing account is never
    overwritten, since its progress.json is someone's download history."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    body = body if isinstance(body, dict) else {}
    name = str(body.get("app") or "")
    label = str(body.get("label") or "").strip().lower()
    owner = str(body.get("owner") or "").strip()[:80]
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "unknown app")
    if not _LABEL_RE.match(label):
        raise HTTPException(400, "the label is used in a filename, so letters, digits, - and _ only, "
                                 "starting with a letter or digit")
    if label in ("primary", "example") or label in apps[name]["accounts"]:
        raise HTTPException(409, "there is already an account called %r in %s" % (label, name))
    app_dir = Path(apps[name]["dir"])
    dest = _make_account(app_dir, label, owner)
    cfg = json.loads(dest.read_text(encoding="utf-8"))
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"app": name, "account": label, "config": dest.name,
            "output_dir": cfg.get("output_dir", ""), "cdp_url": cfg.get("cdp_url", ""),
            "owner": cfg.get("owner", "")}


def _make_account(app_dir: Path, label: str, owner: str) -> Path:
    """config.<label>.json for a second person on an install, with its
    profile on the profiles volume on PaperPull Server. The label is
    checked by the caller. Returns the new config's path."""
    mod = _account_module()
    if mod is None:
        raise HTTPException(500, "add_account.py was not found next to this control panel")
    if not (app_dir / "config.json").is_file():
        raise HTTPException(409, "%s has no config.json yet. Run Login once for the first account, "
                                 "then add the second." % app_dir.name)
    if server_mode.enabled():
        # make_config copies the first person's config into the new one and
        # makes the new person's folder, so a config left as a link in the
        # shared folder would have what it leads to copied into the share,
        # and a folder that leads out would be made outside.
        base = app_dir / "config.json"
        if not server_mode.own_file(base):
            raise HTTPException(409, "%s's config.json is a link in the shared folder, so no "
                                     "person was added." % app_dir.name)
        try:
            first = json.loads(base.read_text(encoding="utf-8-sig"))
            server_mode.hold_in_data(app_dir / mod.output_dir_for(app_dir, first, label))
        except (OSError, ValueError, TypeError, AttributeError):
            raise HTTPException(409, "%s's folder for a second person would be outside the data "
                                     "folder, so no person was added." % app_dir.name)
    try:
        dest = mod.make_config(app_dir, label, owner=owner)
    except Exception as e:
        raise HTTPException(500, "could not make the account: %s" % str(e).splitlines()[0][:160])
    if dest is None:
        raise HTTPException(409, "%s has no config.json yet." % app_dir.name)
    if server_mode.enabled():
        # make_config puts the profile in the account's own folder, which on
        # the server is the shared folder, so it moves to the profiles volume.
        _set_profile(Path(dest), server_mode.profile_for(app_dir.name, label))
    return Path(dest)


# -- moving to another computer (#67) -----------------------------------------
#
# Somebody who moves from the desktop app to PaperPull Server, or to a new
# computer, has a history that says what is already downloaded, and without
# it the new machine downloads every document again, which on the server
# hands every one of them to Paperless a second time. Export history writes
# that history, with each provider's and person's settings, into a file
# tools/migrate.py reads, and Import a history file sets up each provider
# and person the file names that is not set up here and folds the history
# in. No sign-in, browser profile or PDF is ever in the file.

_MIGRATE_MOD = None
_IMPORTING = threading.Lock()
# The file as the page sends it, base64 and all. A real archive of thirty
# providers exported to 330 KB.
HISTORY_MAX_BYTES = 16 * 1024 * 1024


def _migrate_module():
    """tools/migrate.py beside this panel, in a checkout, in the desktop
    package and in the server image alike. Never one from the apps root,
    which on the server is a folder the whole network may write to."""
    global _MIGRATE_MOD
    if _MIGRATE_MOD is not None:
        return _MIGRATE_MOD or None
    import importlib.util
    cand = HERE.parent / "tools" / "migrate.py"
    try:
        spec = importlib.util.spec_from_file_location("paperpull_migrate", cand)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MIGRATE_MOD = mod
    except Exception:
        _MIGRATE_MOD = False
    return _MIGRATE_MOD or None


def _history_keep():
    """Which folders a history export or import may read and write. On
    PaperPull Server only those inside the data folder, wherever a config in
    the shared folder points, and only where progress.json is no link,
    since what was read through one would be exported or written back into
    the share. On the desktop every one, as before."""
    if not server_mode.enabled():
        return None
    return lambda where: (server_mode.inside_data(where)
                          and not server_mode.linked(Path(where) / "progress.json"))


def _history_outside(where: Path) -> bool:
    keep = _history_keep()
    return keep is not None and not keep(where)


def _migrate_or_fail():
    mod = _migrate_module()
    if mod is None:
        raise HTTPException(500, "migrate.py was not found next to this control panel")
    return mod


@app.get("/api/history/export", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
def api_history_export():
    """The history file, handed to the browser. Written in memory, so no
    copy of it is left on this computer or in the server's shared folder."""
    mod = _migrate_or_fail()
    data, _ = mod.build(apps_root(), keep=_history_keep())
    if data is None:
        raise HTTPException(404, "there is no download history here to export yet")
    name = "PaperPull history %s.ppz" % date.today().isoformat()
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name,
                             "Cache-Control": "no-store"})


async def _history_upload(request: Request):
    """(the export's manifest with its records, the root it goes into, and
    whether that root was chosen on the welcome page) from what the page
    sent, a JSON body holding the file in base64 and, on the welcome page,
    the folder chosen there."""
    import base64
    if int(request.headers.get("content-length") or 0) > HISTORY_MAX_BYTES:
        raise HTTPException(413, "that file is far larger than any download history")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > HISTORY_MAX_BYTES:
            raise HTTPException(413, "that file is far larger than any download history")
    try:
        data = json.loads(bytes(body).decode("utf-8"))
        raw = base64.b64decode(str(data.get("file") or ""), validate=True)
    except Exception:
        raise HTTPException(400, "expected the history file")
    mod = _migrate_or_fail()
    try:
        manifest = mod.read(raw)
    except mod.NotAnExport as e:
        raise HTTPException(400, str(e))
    root, chosen = _history_root(str(data.get("root") or "").strip().strip('"'))
    return mod, manifest, root, chosen


def _history_root(raw: str):
    """Where an import goes. The shared folder on PaperPull Server, the
    folder chosen on the welcome page when it sent one, otherwise the apps
    root the panel is on. (root, whether it was chosen here)."""
    if server_mode.enabled():
        return server_mode.data_root(), False
    if not raw:
        return apps_root(), False
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise HTTPException(400, "give the full path, starting from the drive or from /")
    if os.path.normcase(str(root)) == os.path.normcase(str(apps_root())):
        return apps_root(), False
    if os.environ.get("APPS_ROOT"):
        raise HTTPException(409, "APPS_ROOT is set in the environment, which "
                                 "overrides any saved choice. Unset it first.")
    return root, True


def _apply_settings(mod, cfg_path: Path, install: Path, settings: dict) -> None:
    """A file's settings, written into a config the import just made. Only
    what tools/migrate.py allows for this install, a file name pattern only
    when it passes the same check the File names tab makes, and never the
    folders, profile, browser or port, which belong to this computer."""
    if not server_mode.own_file(cfg_path):
        return
    naming = _naming()
    with _CONFIG_WRITES:
        cfg = _read_json(cfg_path)
        if not isinstance(cfg, dict):
            return
        take = mod.settings_to_apply(install, cfg, settings,
                                     check_pattern=naming.check if naming else None)
        if not take:
            return
        cfg.update(take)
        _replace_text(cfg_path, json.dumps(cfg, indent=2) + "\n")


def _template_for(entry: dict, providers: list):
    want = entry["provider"].lower()
    for p in providers:
        if p["provider"].lower() == want and entry.get("kind") in (None, p["kind"]):
            return p
    return None


def _history_place(mod, entry, places, providers, root: Path, apply: bool):
    """Where a provider or person the file names will keep its history when
    nothing here does yet, set up when apply is true. (place, why not)."""
    tmpl = _template_for(entry, providers)
    if tmpl is None:
        return None, "this version of PaperPull has no %s" % entry["provider"]
    account = entry["account"]
    if account != "primary" and (not _LABEL_RE.match(account) or account == "example"):
        return None, "its person's label cannot be used here"
    want = tmpl["provider"].lower()
    first = next((p for p in places if p["provider"].lower() == want
                  and p["account"] == "primary"), None)
    if first is None:
        install = root / tmpl["folder"]
        if install.exists():
            return None, "a folder named %s is already there" % tmpl["folder"]
        where = install
        if apply:
            root.mkdir(parents=True, exist_ok=True)
            owner = entry["settings"].get("owner") if account == "primary" else ""
            if create_install(root, tmpl["slug"], owner=str(owner or "")[:80]) != "created":
                return None, "a folder named %s is already there" % tmpl["folder"]
            if account == "primary":
                _apply_settings(mod, install / "config.json", install, entry["settings"])
            cfg = _read_json(install / "config.json") or {}
            where = mod.output_dir_of(install, cfg, tmpl["provider"])
        if _history_outside(where):
            return None, "its folder is outside the data folder"
        have = mod.history_at(where)
        if have is None:
            return None, "the history already in %s could not be read" % where.name
        first = {"folder": where.name, "install": install.name, "account": "primary",
                 "provider": tmpl["provider"], "kind": tmpl["kind"], "path": where,
                 "records": have, "settings": {}, "config": install / "config.json",
                 "made": True}
        places.append(first)
        if account == "primary":
            return first, ""
    if first.get("config") is None:
        return None, "its first person's folder has no app to add a person to"
    install = root / first["install"]
    if (install / ("config.%s.json" % account)).exists():
        # There, and its history could not be read, so it was not listed.
        # Never written over, since it is somebody's account.
        return None, "%s already has a person called %s" % (install.name, account)
    # The folder the person gets, asked of add_account, which makes it, and
    # read before anything is made. It can already hold their history, left
    # behind when the provider was removed, and that is added to, never
    # written over.
    cfg = (_read_json(install / "config.json")
           or _read_json(_templates_root() / tmpl["slug"] / "config.example.json") or {})
    acct = _account_module()
    rel = (acct.output_dir_for(install, cfg, account) if acct
           else str(Path("..") / ("%s - %s" % (install.name, account))))
    where = mod.output_dir_of(install, {"output_dir": rel}, tmpl["provider"])
    if _history_outside(where):
        return None, "its folder is outside the data folder"
    have = mod.history_at(where)
    if have is None:
        return None, "the history already in %s could not be read" % where.name
    owner = str(entry["settings"].get("owner") or "")[:80]
    if apply:
        dest = _make_account(install, account, owner)
        _apply_settings(mod, dest, install, entry["settings"])
        made = mod.output_dir_of(install, _read_json(dest) or {}, tmpl["provider"])
        if _history_outside(made):
            return None, "its folder is outside the data folder"
        if made != where:
            where, have = made, mod.history_at(made) or {}
    place = {"folder": where.name, "install": install.name, "account": account,
             "provider": tmpl["provider"], "kind": tmpl["kind"], "path": where,
             "records": have, "settings": {}, "config": install / ("config.%s.json" % account),
             "made": True}
    places.append(place)
    return place, ""


def _history_walk(mod, manifest: dict, root: Path, apply: bool) -> list:
    """What importing the file does here, one row for each provider and
    person it names, done when apply is true. The plan and the import are
    this same walk, so they cannot disagree."""
    providers = list_providers()
    places = mod.scan(root, _history_keep()) if root.is_dir() else []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = []
    for entry in manifest["apps"]:
        incoming = entry["incoming"]
        row = {"provider": entry["provider"], "account": entry["account"],
               "records": len(incoming or {}),
               "downloaded": sum(1 for r in (incoming or {}).values() if mod._done(r))}
        rows.append(row)
        if incoming is None:
            row.update(action="skipped", why="its history is missing from the file")
            continue
        place = mod.match(entry, places)
        how = "fill in"
        if place is None:
            try:
                place, why = _history_place(mod, entry, places, providers, root, apply)
            except (OSError, HTTPException) as e:
                place, why = None, "it could not be set up, %s" % (
                    e.detail if isinstance(e, HTTPException) else e)
            if place is None:
                row.update(action="skipped", why=why)
                continue
            how = "set up" if entry["account"] == "primary" else "add person"
        row["action"] = how
        if place["account"] != "primary":
            row["account"] = place["account"]
        records, added, updated = mod.merged(place, entry, manifest)
        row.update(new=added, marked=updated, known=len(place["records"]))
        if apply and (added or updated):
            try:
                if server_mode.enabled():
                    mod.write_history(place["path"], records, stamp,
                                      write=server_mode.write_in_data)
                else:
                    mod.write_history(place["path"], records, stamp)
            except OSError as e:
                row.update(failed="its history could not be written, %s" % e)
                continue
            place["records"] = records
    return rows


@app.post("/api/history/plan", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_history_plan(request: Request):
    """What Import would do with a history file. Writes nothing."""
    mod, manifest, root, _ = await _history_upload(request)
    rows = await to_thread.run_sync(_history_walk, mod, manifest, root, False)
    return {"root": str(root), "rows": rows, "made": manifest.get("created") or "",
            "version": manifest.get("version") or ""}


@app.post("/api/history/import", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_history_import(request: Request):
    """Set up each provider and person a history file names that is not
    set up here, with their settings, and fold in what each had already
    downloaded, so nothing it had is downloaded here again. A progress.json
    already here is backed up before it is written, and nothing is ever
    taken out of one."""
    mod, manifest, root, chosen = await _history_upload(request)
    # Taken, then the runs asked, with nothing awaited between, and a run
    # asks whether an import holds it just before it counts itself running
    # (_start_run), so the two never overlap. A run reads progress.json when
    # it starts and writes it as it goes, over what an import wrote.
    if not _IMPORTING.acquire(blocking=False):
        raise HTTPException(409, "an import is already under way")
    if _RUNNING:
        _IMPORTING.release()
        raise HTTPException(409, "a provider is running right now. Import once it has finished.")
    try:
        rows = await to_thread.run_sync(_history_walk, mod, manifest, root, True)
    finally:
        _IMPORTING.release()
    # A folder chosen on the welcome page is remembered once it holds what
    # was imported, set up now or already there.
    if chosen and any(r.get("action") in ("set up", "add person", "fill in")
                      and not r.get("failed") for r in rows):
        data = _read_settings()
        data["apps_root"] = str(root.resolve())
        try:
            _write_settings(data)
        except OSError as e:
            raise HTTPException(500, "the import is done, and the folder could not be "
                                     "remembered: %s" % e)
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"root": str(root), "rows": rows}


# -- stopping a recording -----------------------------------------------------

def _diagnostics_of(meta: dict, account: str = "primary") -> Path:
    """An account's Diagnostics folder, wherever its config sends output. A
    second person's config sends theirs to their own folder, which is where
    their recording waits and their failure file is written. Found the way
    a run's own folder is found, so a config that names no usable folder
    raises ValueError rather than lead to the first person's folder."""
    return _account_root(meta, account) / "Diagnostics"


def _account_named(meta: dict, account) -> str:
    """The account a request names, only one the panel itself found for
    that app, so a name from the page can never point at another folder."""
    account = str(account or "primary")
    if account not in (meta.get("accounts") or ["primary"]):
        raise HTTPException(404, "unknown account")
    return account


def _latest_failure(meta: dict, account: str = "primary", pattern: str = "failure-*.json"):
    """The newest failure file an app wrote, if it wrote one recently.
    `pattern` finds the survey Diagnose writes, or the recording, the same
    way.

    A run that stops early writes one of these by itself. It is the most
    useful thing a tester can attach and the easiest to never notice, so
    the panel offers it rather than leaving a path in a console.

    Recent means this hour. An older one belongs to a run nobody is
    looking at any more, and offering that would have somebody attach the
    wrong failure to the right issue."""
    import time

    def written(path):
        # failure-<command>-<YYYYmmdd>-<HHMMSS>.json. The command comes first,
        # so names sort by command, and a Pilot's older file sorted after a
        # Discover's newer one. The time the name carries decides, and the
        # file's own time where a name carries none.
        parts = path.stem.split("-")
        stamp = "".join(parts[-2:])
        if len(parts) >= 4 and len(stamp) == 14 and stamp.isdigit():
            return stamp
        try:
            return time.strftime("%Y%m%d%H%M%S", time.localtime(path.stat().st_mtime))
        except OSError:
            return ""
    try:
        inside = _inside(meta, account, "Diagnostics")
        found = sorted(Path(inside).glob(pattern), key=written)
    except (OSError, ValueError):
        return None
    for path in reversed(found):
        fd = _open_plain(path, inside)
        if fd is None:
            continue
        try:
            if time.time() - os.fstat(fd).st_mtime < 3600:
                return path
        except OSError:
            continue
        finally:
            os.close(fd)
    return None


@app.get("/api/failure/latest", dependencies=[Depends(_same_origin_only)])
def api_failure_latest(app: str = "", account: str = "primary"):
    """Whether the run that just stopped left a file worth attaching."""
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    found = _latest_failure(apps[app], _account_named(apps[app], account))
    if found is None:
        return {"found": False}
    return {"found": True, "name": found.name}


@app.post("/api/failure/reveal", dependencies=[Depends(_same_origin_only), Depends(_desktop_only)])
async def api_failure_reveal(request: Request):
    """Show that file in the file manager. Takes no path from the page,
    only the app name, and finds the file here the same way."""
    body = await request.json()
    name = str((body or {}).get("app") or "")
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "unknown app")
    found = _latest_failure(apps[name], _account_named(apps[name], (body or {}).get("account")))
    if found is None:
        raise HTTPException(404, "no recent failure file")
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(found)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(found)])
        else:
            subprocess.Popen(["xdg-open", str(found.parent)])
    except Exception as e:
        raise HTTPException(500, "could not open the folder, %s" % e)
    return {"ok": True}


@app.get("/api/failure/download", dependencies=[Depends(_same_origin_only)])
def api_failure_download(app: str = "", account: str = "primary"):
    """On PaperPull Server, the newest failure file of one app, handed to the
    browser to attach to an issue. Only the app's name comes from the page,
    and the file is found here the way reveal finds it."""
    if not server_mode.enabled():
        raise HTTPException(404)
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    account = _account_named(apps[app], account)
    found = _latest_failure(apps[app], account)
    if found is None:
        raise HTTPException(404, "no recent failure file")
    return _handed(apps[app], account, "Diagnostics", found)


# On PaperPull Server the data folder is usually a share others can write
# to, and the container also holds every signed-in browser profile. A link
# planted in the share, as a file or as a folder the panel reads from, would
# hand the browser a file from anywhere the server can read, cookies among
# them. So a file the panel hands over is opened without following a link
# and judged by what the open reached, and it is sent from that same open,
# so nothing swapped in after the check is read.

def _same(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _inside(meta: dict, account: str, name: str) -> str:
    """Where a file the panel hands over has to be, the account's own folder,
    resolved, with `name` joined on and not resolved, so a folder of that
    name that is a link leads nowhere this accepts. On the server the
    account's folder has to be inside the shared data folder. ValueError
    when it cannot be told or is not."""
    root = os.path.realpath(_account_root(meta, account))
    if server_mode.enabled():
        data = os.path.realpath(server_mode.data_root())
        if os.path.commonpath([_same(root), _same(data)]) != _same(data):
            raise ValueError("the account's folder is outside the data folder")
    return os.path.join(root, name)


def _open_plain(path, inside: str):
    """An open handle on a file of its own inside `inside`, or None. Not a
    link, not reached through one, not one of several hard links to one
    file, and judged by the file the open reached (/proc/self/fd on Linux).
    Anything but a plain file, a named pipe or a device, is refused before
    it is opened, and the open never waits, since opening a pipe waits for
    a writer and would hold the panel's thread for good."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError("not a file of its own")
        # On Linux, where the server runs, only what the open reached
        # counts, and a /proc that cannot be read refuses. Elsewhere, the
        # desktop, the path is resolved.
        if sys.platform.startswith("linux"):
            real = os.readlink("/proc/self/fd/%d" % fd)
        else:
            real = os.path.realpath(path)
        if os.path.commonpath([_same(real), _same(inside)]) != _same(inside):
            raise ValueError("outside")
        return fd
    except (OSError, ValueError):
        os.close(fd)
        return None


def _attachment(name: str) -> dict:
    return {"Content-Disposition": "attachment; filename*=utf-8''%s" % urllib.parse.quote(name)}


# A support report, a recording or a failure file is a few kilobytes. Far
# more is not one of them.
HANDED_MOST = 20 * 1024 * 1024


def _handed(meta: dict, account: str, name: str, path: Path) -> Response:
    """One small file from the account's `name` folder, read from the one
    open that was checked (_open_plain)."""
    try:
        inside = _inside(meta, account, name)
    except ValueError:
        raise HTTPException(404, "that account's folder cannot be read here")
    fd = _open_plain(path, inside)
    if fd is None:
        raise HTTPException(404, "that file cannot be handed over")
    with os.fdopen(fd, "rb") as fh:
        data = fh.read(HANDED_MOST + 1)
    if len(data) > HANDED_MOST:
        raise HTTPException(413, "that file is too large to be a report")
    kind = "application/json" if path.suffix.lower() == ".json" else "application/octet-stream"
    return Response(content=data, media_type=kind, headers=_attachment(path.name))


# What Diagnose and Record write that may leave the machine, by the run's
# action. The survey is the file Diagnose says to attach, and the recording
# is built from the same fixed word list. A screenshot is not on this list,
# since it is a picture of the page and stays where it was taken.
REPORT_FILES = {"diagnose": "survey-*.json", "record": "recording.json"}


@app.get("/api/diagnostics/download", dependencies=[Depends(_same_origin_only)])
def api_diagnostics_download(app: str = "", account: str = "primary", action: str = ""):
    """On PaperPull Server, the file a support report or a recording wrote
    in the last hour, handed to the browser to attach to an issue, where
    the desktop opens the folder. Only the app, the account and which of
    the two come from the page, and the file is found here."""
    if not server_mode.enabled():
        raise HTTPException(404)
    if action not in REPORT_FILES:
        raise HTTPException(400, "diagnose or record")
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    account = _account_named(apps[app], account)
    found = _latest_failure(apps[app], account, REPORT_FILES[action])
    if found is None:
        raise HTTPException(404, "There is no file from the last hour to download. Run it again, "
                                 "then download its file.")
    return _handed(apps[app], account, "Diagnostics", found)


def _set_aside(meta: dict, account: str):
    """Every file in an account's Manual Review folder, as (path, name in
    the zip), hidden ones left out, and where they must be (_inside). Each
    is checked again as it is opened (_open_plain). A Manual Review that is
    a link holds nothing."""
    try:
        inside = _inside(meta, account, "Manual Review")
    except ValueError:
        raise HTTPException(404, "that account's folder cannot be read here")
    out = []
    if os.path.islink(inside):
        return out, inside
    for here, dirs, files in os.walk(inside):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and not os.path.islink(os.path.join(here, d)))
        for name in sorted(files):
            if not name.startswith("."):
                path = Path(here) / name
                out.append((path, "Manual Review/" + path.relative_to(inside).as_posix()))
    return out, inside


# The most the set-aside zip holds. Far past any folder of set-aside
# documents, and it keeps a planted giant from filling the server's disk.
ASIDE_MOST = 2 * 1024 ** 3


def _zip_time(seconds: float) -> tuple:
    """A file's time as a zip can hold it, 1980 to 2107."""
    try:
        when = time.localtime(seconds)[:6]
    except (OverflowError, OSError, ValueError):
        when = (1980, 1, 1, 0, 0, 0)
    return min(max(when, (1980, 1, 1, 0, 0, 0)), (2107, 12, 31, 23, 59, 58))


def _zip_name(arc: str) -> str:
    """A name in the zip no unzip can take out of its folder. A backslash
    is a separator to a Windows unzip, and a Linux file name may hold one."""
    return arc.replace("\\", "_")


@app.get("/api/aside/download", dependencies=[Depends(_same_origin_only)])
def api_aside_download(app: str = "", account: str = "primary"):
    """On PaperPull Server, the documents an account has set aside for a
    look, in one zip, where the desktop opens the provider's folder. They
    sit in the account's Manual Review folder, where a run puts a document
    it would not file under a name it could be wrong about."""
    if not server_mode.enabled():
        raise HTTPException(404)
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    files, inside = _set_aside(apps[app], _account_named(apps[app], account))
    named = "%s set aside.zip" % (app if account == "primary" else "%s %s" % (app, account))
    # A file of no name, which the system removes when it is closed or the
    # panel ends, so a download cut short leaves nothing behind.
    out = tempfile.TemporaryFile()
    put = 0
    try:
        # Stored, not compressed, since a PDF already is.
        total = 0
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            for path, arc in files:
                fd = _open_plain(path, inside)
                if fd is None:
                    continue
                with os.fdopen(fd, "rb") as fh:
                    st = os.fstat(fh.fileno())
                    total += st.st_size
                    if total > ASIDE_MOST:
                        raise HTTPException(413, "What is set aside is too large to download "
                                                 "here. Copy it from the Manual Review folder "
                                                 "on the server.")
                    info = zipfile.ZipInfo(_zip_name(arc), date_time=_zip_time(st.st_mtime))
                    with z.open(info, "w", force_zip64=True) as dest:
                        shutil.copyfileobj(fh, dest, 1024 * 1024)
                put += 1
    except BaseException:
        out.close()
        raise
    if not put:
        out.close()
        raise HTTPException(404, "Nothing is set aside for this account now.")
    out.seek(0)

    def chunks():
        try:
            while True:
                part = out.read(1024 * 1024)
                if not part:
                    return
                yield part
        finally:
            out.close()
    return StreamingResponse(chunks(), media_type="application/zip", headers=_attachment(named))


@app.post("/api/record/stop", dependencies=[Depends(_same_origin_only)])
async def api_record_stop(request: Request):
    """End a recording that is waiting on us.

    A recording has no natural end, so the app waits. At a console it
    waits on Enter. Started from here its input is closed, so it watches
    for this file instead. Writing it is the Stop button."""
    body = await request.json()
    name = str((body or {}).get("app") or "")
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "unknown app")
    try:
        target = _diagnostics_of(apps[name], _account_named(apps[name], (body or {}).get("account")))
    except ValueError:
        raise HTTPException(404, "that account's config names no folder PaperPull can read")
    try:
        _make_folder(target)
        _write_text(target / ".stop-recording", "stop\n")
    except OSError as e:
        raise HTTPException(500, "could not signal the recording: %s" % e)
    return {"app": name, "stopping": True}


# -- removing a provider ------------------------------------------------------
#
# The one action in this panel that could destroy something, so it does not.
# The install folder is MOVED into Removed/ beside the others, where the panel
# no longer lists it, and nothing inside it is touched. PDFs not yet filed
# elsewhere, the download history, the signed-in browser profile, all of it is
# still there for whoever wants to delete it deliberately with a file manager.
# A provider somebody stopped needing is not the same as a provider whose
# records they want gone, and the panel should not guess which.

REMOVED_DIR = "Removed"


def _removal_summary(folder: Path) -> dict:
    pdfs = 0
    for p in folder.rglob("*.pdf"):
        if ".venv" not in p.parts and "browser-profile" not in str(p):
            pdfs += 1
    history = 0
    try:
        raw = json.loads((folder / "progress.json").read_text(encoding="utf-8-sig"))
        history = sum(1 for v in raw.values() if isinstance(v, dict)) if isinstance(raw, dict) else 0
    except (OSError, ValueError):
        pass
    profile = any(d.is_dir() and "browser-profile" in d.name for d in folder.iterdir())
    return {"pdfs": pdfs, "history": history, "profile": profile}


@app.post("/api/remove", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_remove(request: Request):
    """Move an install out of the list. The name must be one the panel
    itself discovered, so nothing outside the root can ever be named."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    name = str((body or {}).get("app") or "")
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "unknown app")
    if name in _RUNNING:
        raise HTTPException(409, "that provider is running right now. Wait for it "
                                 "to finish, or close the tab it is running in.")
    src = Path(apps[name]["dir"])
    root = apps_root()
    if src.parent.resolve() != root.resolve():
        raise HTTPException(400, "that folder is not directly under the apps root")

    summary = _removal_summary(src)
    dest_dir = root / REMOVED_DIR
    dest = dest_dir / name
    # On the server a link left at the name counts as taken, and Removed is
    # held inside the data folder, since a move to another disk copies the
    # whole install to wherever a link would lead.
    taken = os.path.lexists if server_mode.enabled() else os.path.exists
    if taken(dest):
        dest = dest_dir / ("%s (%s)" % (name, datetime.now().strftime("%Y%m%d-%H%M%S")))
    try:
        _make_folder(dest_dir)
        shutil.move(str(src), str(dest))
    except OSError as e:
        raise HTTPException(500, "could not move the folder: %s. Is a file in it "
                                 "open, or a browser still signed in there?" % e)
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"app": name, "moved_to": str(dest), **summary}


def _build_cmd(app_meta: dict, account: str, action: str, scope_flags=(), redownload=False):
    if action not in ACTIONS:
        raise HTTPException(400, "unknown action")
    if account not in app_meta["accounts"]:
        raise HTTPException(400, "unknown account")
    flags = []
    for f in ACTIONS[action]["flags"]:
        flags.append(app_meta["login_flag"] if f == "__LOGIN__" else f)
    if action != "login":
        flags += list(scope_flags)
    if redownload is not False:
        # _redownload_ok has said yes before this is reached. This is the
        # last word on the command line itself, so nothing that skipped
        # that check can put the flag on any other action.
        if redownload is not True or action not in REDOWNLOAD_ACTIONS:
            raise ValueError("%s goes only on %s" % (REDOWNLOAD_FLAG, " and ".join(REDOWNLOAD_ACTIONS)))
        flags.append(REDOWNLOAD_FLAG)
    return _command(app_meta, account, flags)


def _command(app_meta: dict, account: str, flags: list) -> list:
    """The command that runs an app's own script with these flags, for
    this account."""
    interp = [app_meta["python"]]
    if server_mode.enabled():
        # -P keeps the current directory and the script's own directory off
        # sys.path, so nothing in the /data folder is ever importable. The
        # trusted template folder reaches the run through PYTHONPATH, set in
        # _run_env, which -P still honors (unlike -I, which would drop it).
        interp.append("-P")
    cmd = [*interp, app_meta["script"], *flags]
    if account != "primary":
        cmd += ["--config", f"config.{account}.json"]
    return cmd


def _review_cmd(app_meta: dict, account: str) -> list:
    """Review Names for one account, which only a receipt app has. It is
    kept out of ACTIONS, the table every app is sent, and is reached only
    through /api/review-names, which hands it what it would otherwise ask
    in a console (renaming.REVIEW_LIST_ENV, REVIEW_ANSWERS_ENV)."""
    if not app_meta.get("reviews_names"):
        raise HTTPException(400, "%s has no Review Names. Only receipt providers do."
                            % app_meta.get("name", "This provider"))
    if account not in app_meta["accounts"]:
        raise HTTPException(400, "unknown account")
    return _command(app_meta, account, ["--review-names"])


def _run_env(meta: dict) -> dict:
    """The environment a run is launched with.

    On PaperPull Server the data anchor and the only import root are set
    here, and nowhere else. PAPERPULL_DATA_DIR points the core's data at
    the install's /data folder (AppSpec repoints project_dir to it), and
    PYTHONPATH is the trusted template folder alone, so under -P the
    shipped siblings import and nothing from /data does. The version goes
    to every run so a file it writes records the build that wrote it."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
               PAPERPULL_VERSION=VERSION)
    if server_mode.enabled():
        env["PAPERPULL_DATA_DIR"] = meta.get("dir", "")
        # A real server run always carries the template folder (discover_apps
        # sets it with runnable, and _start_run refuses a run without it), so
        # the import root is the trusted template and nothing else. The guard
        # is only for a hand-built meta in a test, which runs no real import.
        template_dir = meta.get("template_dir")
        if template_dir:
            env["PYTHONPATH"] = template_dir
    return env


@app.get("/api/run", dependencies=[Depends(_same_origin_only)])
def api_run(app: str, account: str = "primary", action: str = "pilot",
            year: str = "", start: str = "", end: str = "",
            redownload: Optional[str] = None, confirmed: Optional[str] = None):
    # Download again is asked for in a POST body only. An address that
    # carries it is refused rather than run as an ordinary run, which would
    # skip everything already downloaded and look as if it had worked.
    if redownload is not None or confirmed is not None:
        raise HTTPException(400, "Download again is asked for in a POST body, "
                                 "never in an address.")
    return _start_run(app, account, action, _scope_flags(year, start, end))


@app.post("/api/run", dependencies=[Depends(_same_origin_only)])
async def api_run_body(request: Request):
    """The run GET /api/run starts, asked for with a JSON body instead.

    It is how the page asks to download again, since that is a box the
    person ticked and a question they agreed to, and both arrive as JSON
    true or false, never as text an address could carry. A body that is
    not JSON, holds anything more, or has a field of the wrong kind is
    refused before anything starts."""
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind != "application/json":
        raise HTTPException(415, "a run's body is JSON")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    asked = _run_request(body)
    scope = _scope_flags(asked["year"], asked["start"], asked["end"])
    again = _redownload_ok(asked["action"], scope, asked["redownload"], asked["confirmed"])
    # In the threadpool, as FastAPI runs the GET handler, since finding the
    # apps reads every install's folder and would hold up every other
    # request on the event loop meanwhile.
    return await to_thread.run_sync(_start_run, asked["app"], asked["account"],
                                    asked["action"], scope, again)


# -- Review Names --------------------------------------------------------------
#
# Every receipt app asks, in a console, for a better name for each receipt it
# was unsure of (core renaming.review_names). The panel has no console, and
# PaperPull Server has none at all, so the panel asks in two steps instead.
# The first has the app write the receipts it would ask about to a file of
# the panel's own and rename nothing, and the page shows them. The second
# hands the app what the person typed, in a file of that run's own, and the
# app renames each receipt given a new name by the very rules a console
# review follows. The app reads where each file is from these two, the same
# names core renaming reads (gui/tests/test_review_names.py holds them alike).
REVIEW_LIST_ENV = "PAPERPULL_REVIEW_LIST"
REVIEW_ANSWERS_ENV = "PAPERPULL_REVIEW_ANSWERS"
HANDED = "review.json"
# A list longer than a person types in one go is refused, as are fields far
# longer than any receipt's. The app cuts a summary to its own limit.
REVIEW_MOST = 2000
REVIEW_FIELD_MOST = {"id": 4096, "number": 200, "summary": 1000}
REVIEW_LIST_SECONDS = 120


def _hand_over(text: str) -> Path:
    """A folder only this user can read, holding `text` for one run."""
    folder = Path(tempfile.mkdtemp(prefix="paperpull-review-"))
    try:
        (folder / HANDED).write_text(text, encoding="utf-8")
    except BaseException:
        _drop(folder)
        raise
    return folder


def _drop(folder) -> None:
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def _review_body(body) -> dict:
    """What a Review Names request holds, each field checked for its kind."""
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    for key in ("app", "account"):
        if key in body and type(body[key]) is not str:
            raise HTTPException(400, "%s is text" % key)
    if not body.get("app"):
        raise HTTPException(400, "Review Names needs its app")
    return {"app": body["app"], "account": body.get("account") or "primary"}


def _review_answers(raw) -> list:
    """The new summaries a person typed, as a list of {id, number, summary},
    every field text. A blank summary keeps its name and is left out."""
    if not isinstance(raw, list):
        raise HTTPException(400, "answers is a list")
    if len(raw) > REVIEW_MOST:
        raise HTTPException(400, "at most %d answers at a time" % REVIEW_MOST)
    out = []
    for a in raw:
        if not isinstance(a, dict) or set(a) != set(REVIEW_FIELD_MOST):
            raise HTTPException(400, "each answer holds id, number and summary")
        for key, most in REVIEW_FIELD_MOST.items():
            if type(a[key]) is not str or len(a[key]) > most:
                raise HTTPException(400, "an answer's %s is text of at most %d characters"
                                    % (key, most))
        if a["id"] and a["summary"].strip():
            out.append({k: a[k] for k in REVIEW_FIELD_MOST})
    return out


def _review_list(app: str, account: str) -> dict:
    """The receipts the app would ask about, as it writes them, with what it
    said while finding them (rows it leaves out, and why)."""
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    meta = apps[app]
    if server_mode.enabled() and not meta.get("runnable", True):
        raise HTTPException(409, "This install does not match a provider PaperPull ships, "
                                 "so it will not be run.")
    blocked = setup_needed(meta)
    if blocked:
        raise HTTPException(409, blocked.splitlines()[0] if blocked.strip() else "setup needed")
    cmd = _review_cmd(meta, account)
    folder = None
    try:
        try:
            folder = Path(tempfile.mkdtemp(prefix="paperpull-review-"))
        except OSError as e:
            raise HTTPException(500, "Review Names had nowhere to list into, %s" % e)
        mark = run_result.new_mark()
        env = dict(_run_env(meta), **{REVIEW_LIST_ENV: str(folder / HANDED),
                                      run_result.MARK_ENV: mark})
        try:
            # A closed pipe, as a run has, so the app asks nothing. What it
            # says on stderr stays with the rest, so a crash says why.
            done = subprocess.run(cmd, cwd=meta["dir"], input="", stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                  errors="replace", env=env, timeout=REVIEW_LIST_SECONDS)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Review Names did not finish listing in %d seconds."
                                % REVIEW_LIST_SECONDS)
        except OSError as e:
            raise HTTPException(500, "Review Names could not start, %s" % e)
        said = [line.rstrip() for line in (done.stdout or "").splitlines()
                if line.strip() and run_result.parse(line, mark) is None]
        try:
            listed = json.loads((folder / HANDED).read_text(encoding="utf-8"))
            receipts = listed["receipts"]
            if not isinstance(receipts, list):
                raise ValueError("not a list")
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(500, " ".join(said[-3:]) or
                                "Review Names ended with code %s and listed nothing."
                                % done.returncode)
        return {"receipts": receipts, "said": said}
    finally:
        _drop(folder)


async def _review_json(request: Request):
    """A Review Names request's body, which is JSON, as a run's is."""
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind != "application/json":
        raise HTTPException(415, "Review Names is asked for with a JSON body")
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")


@app.post("/api/review-names", dependencies=[Depends(_same_origin_only)])
async def api_review_names(request: Request):
    """The receipts an app would ask a better name for. Renames nothing it
    names, but an app may write its own records while it reads them (Target
    mends an order's list of invoices), so the list counts as a run of that
    account, refused while one goes or a history is imported, and holding
    off both while it lists. Checked and claimed with nothing awaited
    between, as _start_run claims a run."""
    body = await _review_json(request)
    asked = _review_body(body)
    if set(body) - {"app", "account"}:
        raise HTTPException(400, "a Review Names list holds only app and account")
    app_name, account = asked["app"], asked["account"]
    if _IMPORTING.locked():
        raise HTTPException(409, "A history file is being imported. Review names once it "
                                 "has finished.")
    if (app_name, account) in _RUNS:
        raise HTTPException(409, "%s is running for this account. Review names once it has "
                                 "finished." % app_name)
    _RUNS[(app_name, account)] = {"action": "review_names_list",
                                  "started": datetime.now().isoformat(timespec="seconds")}
    _RUNNING.add(app_name)
    try:
        return await to_thread.run_sync(_review_list, app_name, account)
    finally:
        _RUNS.pop((app_name, account), None)
        if not any(a == app_name for a, _ in _RUNS):
            _RUNNING.discard(app_name)


@app.post("/api/review-names/apply", dependencies=[Depends(_same_origin_only)])
async def api_review_names_apply(request: Request):
    """Rename each receipt given a new summary, streamed as a run is."""
    body = await _review_json(request)
    asked = _review_body(body)
    if set(body) - {"app", "account", "answers"}:
        raise HTTPException(400, "Review Names holds only app, account and answers")
    answers = _review_answers(body.get("answers"))
    return await to_thread.run_sync(_start_run, asked["app"], asked["account"],
                                    "review_names", (), False,
                                    json.dumps({"answers": answers}))


def _start_run(app: str, account: str, action: str, scope_flags, redownload=False,
               review: Optional[str] = None):
    """A run of one app for one account, streamed to the page. `review` is
    Review Names' new summaries as JSON, handed to the app in a file of this
    run's own that is gone once the run ends (_hand_over)."""
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    meta = apps[app]

    if server_mode.enabled() and not meta.get("runnable", True):
        # Fail closed. The install does not map to exactly one provider the
        # image ships, so there is no trusted code to run for it, and the
        # server never falls back to code in the /data folder.
        detail = ("This install does not match a provider PaperPull ships, so "
                  "it will not be run. Its folder must hold exactly one "
                  "provider script whose name is one PaperPull ships. Remove "
                  "any extra script, or add the provider again from the panel.")

        async def refuse_unmapped():
            for line in detail.splitlines():
                yield _event(line)
            yield _event(1, "done")
        return StreamingResponse(refuse_unmapped(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    blocked = setup_needed(meta)
    cmd = (_review_cmd(meta, account) if review is not None
           else _build_cmd(meta, account, action, scope_flags, redownload))
    # The account's folder inside the one documents folder, for a provider or
    # person added since it was saved, written once the request is a run the
    # panel knows (an unknown action or account is refused just above) and
    # only while nothing below would refuse it, so a request that runs
    # nothing changes nothing. Asked again in the stream with nothing awaited,
    # so two tabs pressing at once may both get here, and both write the
    # same folder. Only before a download run, the one whose documents go
    # there. A Move or a Rename goes where the config says, which is where
    # the page says it goes, the account's own folder for one with no
    # setting.
    documents_said = []
    if review is None and action in DOWNLOAD_ACTIONS and not blocked \
            and not _IMPORTING.locked() and (app, account) not in _RUNS:
        try:
            documents_said = _documents_before_run(apps, app, account)
        except Exception as e:
            # Never the reason a run does not start. Its documents go where
            # its config already says.
            documents_said = ["Documents stay where they were, since the folder for every "
                              "provider could not be applied (%s)." % type(e).__name__]

    if blocked:
        # Said here rather than let the app start under an interpreter
        # that cannot import it. The page already carries a warning, and
        # a warning above the buttons is not what somebody reads when a
        # button has just produced a traceback.
        # A missing venv is a failure and is reported as one. Being in the
        # sample is not, so it does not get a red dot and an exit code, or
        # the first thing anyone tries there looks like a broken program.
        code = 0 if _SAMPLE is not None else 1

        async def refuse():
            for line in blocked.splitlines():
                yield _event(line)
            yield _event(code, "done")
        return StreamingResponse(refuse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # Deliberately an *async* generator. With a plain sync one, Starlette wraps
    # it in iterate_in_threadpool, which never calls .close() on it - so the
    # cleanup below would never run and a closed tab left the downloader going.
    async def stream():
        yield _event("$ " + " ".join(cmd))
        for line in documents_said:
            yield _event(line)
        # On the server this sets PAPERPULL_DATA_DIR (the install's /data
        # folder) and PYTHONPATH (the trusted template folder), the two
        # things that keep code on the image side and data on the /data
        # side. On the desktop it only carries the version through.
        env = _run_env(meta)
        # This run's mark, which only its own result line carries, so a
        # line it printed from a name or a provider's text can never be
        # taken for its counts (run_result.parse).
        mark = run_result.new_mark()
        env[run_result.MARK_ENV] = mark
        # What an action tells the app beyond its flags, the Move's mark
        # (ACTIONS). Review Names carries its own below.
        if review is None:
            env.update(ACTIONS.get(action, {}).get("env", {}))
        # When the run began, so that only a list of new files this run
        # wrote is handed to the server's plug-ins afterwards.
        started = time.time()
        # Asked with nothing awaited before the run counts itself, so an
        # import cannot start in between (api_history_import).
        if _IMPORTING.locked():
            yield _event("A history file is being imported. Run this once it has finished.")
            yield _event(1, "done")
            return
        # One run per account. A second, from another tab, would put two
        # downloaders on one progress.json, one browser and one folder.
        # Checked and claimed with nothing awaited between, so two requests
        # cannot both get through.
        if (app, account) in _RUNS:
            yield _event("%s is already running for this account, in another tab "
                         "or window. Wait for it to finish there." % app)
            yield _event(1, "done")
            return
        # Where the run's log goes, worked out before the run is claimed, so
        # nothing that can fail sits between the claim and the code that
        # lets it go. A folder that cannot be worked out keeps no log.
        try:
            root = _account_root(meta, account)
        except Exception:
            root = None
        _RUNS[(app, account)] = {"action": action,
                                 "started": datetime.now().isoformat(timespec="seconds")}
        noted = False
        handed = None
        # What the run saved, read once its process has ended (below).
        saved = None

        def note(code, result, closed=False):
            if root is None:
                return
            try:
                _note_run(root, {
                    "action": action, "account": account,
                    "started": _RUNS.get((app, account), {}).get("started", ""),
                    "ended": datetime.now().isoformat(timespec="seconds"),
                    "exit_code": code, "closed": closed, "result": result,
                    "scope": list(scope_flags), "redownload": bool(redownload),
                    "saved": _saved_this_run(root, started) if saved is None else saved})
            except Exception:
                pass
        try:
            _RUNNING.add(app)
            if review is not None:
                handed = _hand_over(review)
                env[REVIEW_ANSWERS_ENV] = str(handed / HANDED)
            proc = subprocess.Popen(
                cmd, cwd=meta["dir"],
                # No stdin. The panel cannot answer a prompt, so an app must
                # not be able to ask: inheriting this server's terminal makes
                # sys.stdin.isatty() true, and the app then asks "Whose
                # account is this?" on a first run and waits forever for input
                # nobody can give. Worse, input() writes its prompt without a
                # newline, so the line-reader below never yields it - the page
                # shows a run that started and then nothing at all.
                # With no stdin, input() raises EOFError, the apps report that
                # no interactive console is available, and the run ends. That
                # matches what the panel already promises: a run that needs an
                # answer ends rather than hanging.
                #
                # A PIPE that is closed straight away, not DEVNULL. On Windows
                # DEVNULL is the NUL device, which is a character device, so
                # sys.stdin.isatty() reports True. Every "is anyone there?"
                # check in the apps then passes, prints its prompt, and only
                # learns the truth when input() hits EOF, which left "Whose
                # account is this?" sitting in the panel output of every fresh
                # install. A closed pipe answers isatty() honestly, so those
                # checks skip the prompt entirely, and input() still gets EOF.
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=env)
            # Closed at once. The child sees a pipe, so isatty() is False, and
            # any read reaches EOF immediately.
            try:
                proc.stdin.close()
            except OSError:
                pass
        except Exception as e:
            _drop(handed)
            _RUNS.pop((app, account), None)
            if not any(a == app for a, _ in _RUNS):
                _RUNNING.discard(app)
            yield _event("[failed to start] %s" % e)
            yield _event(1, "done")
            return
        # Closing the browser tab closes this generator. Without the finally
        # below, the downloader kept running unseen - still driving your
        # signed-in browser over CDP and still writing PDFs and progress.json -
        # with nothing on screen. Worse, believing it had stopped, you could
        # press Run again and put two runs on one progress.json, one CDP port
        # and one output folder. Stopping is safe: downloaded_ok is only set
        # after a document is saved, so a re-run resumes and re-fetches nothing.
        result = None
        read_all = False
        try:
            while True:
                # readline blocks, so it goes to a worker thread rather than
                # stalling the event loop for every other request.
                line = await to_thread.run_sync(proc.stdout.readline)
                if not line:
                    read_all = True
                    break
                parsed = run_result.parse(line.rstrip("\r\n"), mark)
                if parsed is not None:
                    result = parsed
                else:
                    yield _event(line.rstrip())
            code = await to_thread.run_sync(proc.wait)
            # What the run saved, from its new-this-run.txt, read as soon as
            # it has ended and before anything else runs for the account.
            # The move below is the app's own Rename, which wrote a list of
            # its own with nothing in it (#103), so a list read after it said
            # a run that saved 23 statements had saved nothing. Read once,
            # this is what the move takes, the page lists and the log keeps.
            saved = _saved_this_run(root, started) if root is not None else []
            # On PaperPull Server the plug-ins hear the run ended, the
            # Paperless copy among them, and what they say joins the output.
            if server_mode.enabled():
                said = await to_thread.run_sync(server_mode.after_run, meta, account,
                                                action, started, code, result)
                for told in said:
                    yield _event(told)
            # Then what a download run saved and checked moves to the
            # account's documents folder, if it has one (#102), after the
            # plug-ins have read each file where the run saved it.
            if action in DOWNLOAD_ACTIONS and root is not None:
                said = await to_thread.run_sync(_move_new_documents, meta, account, saved, env)
                for told in said:
                    yield _event(told)
            if result is not None:
                yield _event(json.dumps(result), "result")
            # The files this run saved, by name, for the page to list under
            # its one-line outcome. The log below keeps them for the home page.
            yield _event(json.dumps(saved), "saved")
            # Marked first. The note's thread finishes even when the page
            # goes meanwhile, so marking it after would note the run twice.
            noted = True
            await to_thread.run_sync(note, code, result)
            yield _event()
            yield _event(code, "done")
        finally:
            if not noted and action in FINISHED_WHEN_LEFT and proc.poll() is None:
                # A Rename or a Move applying its changes moves every file and
                # only then writes the ledgers, so stopped partway it would
                # leave files the index no longer names. It finishes on its
                # own, its output read and dropped, and the account stays
                # claimed until it has.
                def finish():
                    try:
                        for _line in proc.stdout:
                            pass
                        note(proc.wait(), result)
                    finally:
                        _RUNS.pop((app, account), None)
                        if not any(a == app for a, _ in _RUNS):
                            _RUNNING.discard(app)
                        if proc.stdout:
                            proc.stdout.close()
                        _drop(handed)
                threading.Thread(target=finish, daemon=True).start()
            else:
                if not noted:
                    # The page went away before the run was noted. A run that
                    # had already ended by itself, say while the Paperless copy
                    # ran, is noted with its own code, but only once its output
                    # was read to the end, or its counts were, since a code of
                    # 0 with the counts line still unread could hide a run that
                    # stopped. Any other is stopped by this, and its row says so.
                    ended = proc.poll() if (read_all or result is not None) else None
                    if ended is not None:
                        note(ended, result)
                    else:
                        note(None, result, True)
                _RUNS.pop((app, account), None)
                # Another person's run of the same app may still be going.
                if not any(a == app for a, _ in _RUNS):
                    _RUNNING.discard(app)
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                if proc.stdout:
                    proc.stdout.close()
                _drop(handed)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# -- file names from a pattern (#50) ------------------------------------------
#
# The page that sets how files are named. The engine is paperpull_core.naming
# and the apps already build every name through it, so this only reads an
# app's records to preview with and writes the pattern into its config.
# Nothing here renames a file. That is Rename preview and Apply renames,
# which already ask the app what each file should be called.

_NAMING = None
SHARED_KEYS = {"receipts": "filename_pattern_receipts",
               "statements": "filename_pattern_statements"}
OWN_KEY = "filename_pattern"


def _naming():
    """paperpull_core.naming, from the core the panel ships beside, or
    None, in which case the page says it is unavailable and nothing else
    is affected."""
    global _NAMING
    if _NAMING is None:
        core = HERE.parent / "core"
        if (core / "paperpull_core" / "naming.py").is_file() and str(core) not in sys.path:
            sys.path.insert(0, str(core))
        try:
            from paperpull_core import naming as mod
            _NAMING = mod
        except Exception:
            _NAMING = False
    return _NAMING or None


def _storage_src(d: Path) -> str:
    try:
        return (d / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _naming_kind(d: Path) -> str:
    """From the app's own spec, the same kind storage uses to pick which
    pattern applies, so the page and a run never disagree."""
    k = _KIND_RE.search(_storage_src(d))
    return "receipts" if k and k.group(1) == "RECEIPT" else "statements"


def _provider_name(d: Path) -> str:
    m = _PROVIDER_RE.search(_storage_src(d))
    return m.group(1) if m else d.name


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _config_files(d: Path) -> list:
    """Every account's config in an install, the first person's first."""
    out = [d / "config.json"] if (d / "config.json").is_file() else []
    out += [p for p in sorted(d.glob("config.*.json")) if p.name != "config.example.json"]
    return out


def _naming_output(d: Path) -> Optional[Path]:
    """The first person's output folder, where a run keeps its records and
    files, and None where it cannot be read. Read from the config, since
    it is not always the install."""
    if server_mode.enabled():
        # On the server the config is in the shared folder, so only a folder
        # inside the data folder is read, the way a run's own folder is found.
        try:
            return server_mode.output_root(d, "primary")
        except ValueError:
            return None
    cfg = _read_json(d / "config.json") or {}
    # The same default load_config gives an absent output_dir.
    out = Path(cfg.get("output_dir") or (Path.home() / "Downloads" / _provider_name(d)))
    return out if out.is_absolute() else d / out


def _naming_records(d: Path) -> list:
    """The first person's records, for the preview and the fill rates."""
    out = _naming_output(d)
    if out is None:
        return []
    data = _read_json(out / "progress.json")
    if isinstance(data, dict):
        data = list(data.values())
    return [r for r in (data or []) if isinstance(r, dict)]


def _named_where(record: dict, out: Optional[Path], documents: str = "") -> str:
    """A saved file as the preview shows it, its name, and the folders a
    naming pattern filed it in before it (#101), "Chase/2026/2026-01-31
    Chase Statement.pdf", inside the folder its kind is filed in. Read
    from the record's own path without touching the disk, and the name
    alone for a path that is in a folder of neither the output folder nor
    the account's documents folder (#102)."""
    name = str(record.get("pdf_filename") or "")
    raw = record.get("pdf_path")
    if out is None or not isinstance(raw, str) or not raw.strip():
        return name
    path = Path(raw.strip())
    if not path.is_absolute():
        path = out / path
    # The deeper first, as a documents folder inside the output folder is.
    roots = sorted([out] + ([Path(documents)] if documents else []),
                   key=lambda p: len(str(p)), reverse=True)
    for root in roots:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if len(parts) < 3 or parts[-1] != name or ".." in parts:
            return name
        return "/".join(parts[1:])
    return name


def _newest_saved(records, n=3):
    saved = [r for r in records if r.get("pdf_filename")]
    saved.sort(key=lambda r: str(r.get("date") or r.get("purchase_date") or ""),
               reverse=True)
    return saved[:n]


def _naming_app(name: str) -> Path:
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "no such app")
    return Path(apps[name]["dir"])


def _write_config(cfg_path: Path, key: str, value: str, stamp: str,
                  why: str = "naming", keep_empty: bool = False, when=None) -> bool:
    """Set or clear one key, backed up first and written in one step, so a
    crash part way leaves the old file whole. The copy goes in
    Backups/<why>-<stamp>. With keep_empty an empty value is written as
    "", rather than the key taken out. `when` is asked of the config as it
    is read here, and nothing is written unless it says True, so a choice
    saved since the caller looked at the config is kept."""
    if not server_mode.own_file(cfg_path):
        return False
    # One write at a time (_CONFIG_WRITES), the config read inside it.
    with _CONFIG_WRITES:
        return _write_config_now(cfg_path, key, value, stamp, why, keep_empty, when)


# Held while one config is read, copied and written, by every writer of an
# account's config in the panel. Two at once, a run filling in its documents
# folder in one tab and a save in another, each read the config before the
# other wrote it and took the same Backups folder, so one change was lost,
# and the copy kept was the other's change or, once the two tripped over
# one temporary file, no copy at all.
_CONFIG_WRITES = threading.Lock()


def _write_config_now(cfg_path: Path, key: str, value: str, stamp: str, why: str,
                      keep_empty: bool, when=None) -> bool:
    current = _read_json(cfg_path)
    if not isinstance(current, dict):
        return False
    if when is not None and not when(current):
        return False
    if keep_empty and not value:
        if current.get(key) == "":
            return False
    elif (current.get(key) or "") == value:
        return False
    if value or keep_empty:
        current[key] = value
    else:
        current.pop(key, None)
    # A copy of its own, never one an earlier write in the same second kept.
    folder, n = cfg_path.parent / "Backups" / ("%s-%s" % (why, stamp)), 1
    while os.path.lexists(folder / cfg_path.name):
        n += 1
        folder = cfg_path.parent / "Backups" / ("%s-%s-%d" % (why, stamp, n))
    bak = folder / cfg_path.name
    was = [os.path.lexists(p) for p in (folder, folder.parent)]
    try:
        _make_folder(folder)
        _copy_file(cfg_path, bak)
        _replace_text(cfg_path, json.dumps(current, indent=2) + "\n")
    except OSError:
        # The config is as it was, so what was made for its copy goes again,
        # or a config that cannot be written would gain a copy each time it
        # is tried, as the documents folder is before a run. Not on
        # PaperPull Server, where a folder of the share may be a link by now
        # and nothing is ever taken away through one.
        if not server_mode.enabled():
            try:
                if os.path.lexists(bak):
                    # A copy of a read-only config is read-only too, and
                    # Windows will not delete a read-only file.
                    os.chmod(bak, stat.S_IREAD | stat.S_IWRITE)
                    bak.unlink()
                for made, there in zip((folder, folder.parent), was):
                    if there:
                        break
                    made.rmdir()
            except OSError:
                pass
        return False
    return True


@app.get("/api/naming", dependencies=[Depends(_same_origin_only)])
def api_naming(app: str):
    naming = _naming()
    d = _naming_app(app)
    if naming is None:
        return {"available": False}
    kind = _naming_kind(d)
    cfg = _read_json(d / "config.json") or {}
    records = _naming_records(d)
    return {
        "available": True,
        "kind": kind,
        "provider": _provider_name(d),
        "fields": list(naming.FIELDS),
        "default": naming.DEFAULT_RECEIPTS,
        "shared": cfg.get(SHARED_KEYS[kind]) or "",
        "own": cfg.get(OWN_KEY) or "",
        "fill": naming.fill_rates(records, receipts=(kind == "receipts")),
    }


@app.post("/api/naming/preview", dependencies=[Depends(_same_origin_only)])
async def api_naming_preview(request: Request):
    body = await request.json()
    naming = _naming()
    d = _naming_app(str(body.get("app") or ""))
    if naming is None:
        raise HTTPException(503, "file naming is not available in this install")
    pattern = str(body.get("pattern") or "").strip()
    if pattern == naming.DEFAULT_RECEIPTS:
        # Under the default a name is what the app built at the time,
        # which is the name already on disk.
        pattern = ""
    problem = naming.check(pattern) if pattern else None
    kind = _naming_kind(d)
    cfg = _read_json(d / "config.json") or {}
    provider = _provider_name(d)
    out = _naming_output(d)
    names = []
    for r in _newest_saved(_naming_records(d)):
        # With the folders a pattern filed it in, as the new name shows the
        # folders it would be filed in.
        current = _named_where(r, out, cfg.get(DOCUMENTS_KEY) if isinstance(
            cfg.get(DOCUMENTS_KEY), str) else "")
        # The default names no folder, so a file a pattern put in folders
        # goes back to the folder of its kind, under the name it has.
        new = current if pattern else str(r.get("pdf_filename") or "")
        if pattern and not problem:
            try:
                new = naming.preview(
                    pattern, r, provider=provider, owner=cfg.get("owner") or "",
                    receipts=(kind == "receipts"),
                    document_type=(str(r.get("document_type") or "Receipt")
                                   if kind == "receipts" else ""))
            except Exception:
                new = current
        names.append({"current": current, "new": new})
    return {"problem": problem, "names": names}


@app.post("/api/naming/save",
          dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_naming_save(request: Request):
    """Write a pattern where it applies. "shared" goes into every install of
    this app's kind, every account's config, so all receipts apps or all
    statements apps name alike. "own" goes into this app's configs only
    and wins over the shared one. An empty pattern clears it, which is
    the default. Nothing is renamed."""
    body = await request.json()
    naming = _naming()
    d = _naming_app(str(body.get("app") or ""))
    if naming is None:
        raise HTTPException(503, "file naming is not available in this install")
    scope = body.get("scope")
    if scope not in ("shared", "own"):
        raise HTTPException(400, "scope is shared or own")
    pattern = str(body.get("pattern") or "").strip()
    if pattern == naming.DEFAULT_RECEIPTS:
        pattern = ""
    if pattern:
        problem = naming.check(pattern)
        if problem:
            raise HTTPException(400, problem)
    kind = _naming_kind(d)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    found = discover_apps()
    if scope == "own":
        targets, key = {k: Path(a["dir"]) for k, a in found.items()
                        if Path(a["dir"]) == d}, OWN_KEY
    else:
        targets = {k: Path(a["dir"]) for k, a in found.items()
                   if _naming_kind(Path(a["dir"])) == kind}
        key = SHARED_KEYS[kind]
    written = 0
    changed = []
    for name, install in targets.items():
        wrote = sum(_write_config(cfg, key, pattern, stamp)
                    for cfg in _config_files(install))
        written += wrote
        # What the page offers to rename. An app with its own pattern is
        # not named by the shared one, so a shared change leaves its
        # files as they are.
        if wrote and not (scope == "shared" and
                          (_read_json(install / "config.json") or {}).get(OWN_KEY)):
            changed.append(name)
    return {"written": written, "installs": len(targets), "key": key,
            "changed": changed}


# -- the documents folder (#102) ----------------------------------------------
#
# Each account can send the folders its documents are routed to, Statements,
# Tax Documents, Receipts and the rest, to a folder of its own, one a program
# such as Paperless may watch. Its records, Manual Review, Logs, Diagnostics
# and Backups stay in its own folder, so nothing half checked reaches a
# watched folder (core storage.Paths). Setting it moves nothing. Documents
# saved before stay where they are, still found, until the person moves
# them, which the app's own Rename does (ACTIONS).
#
# The page sets one documents folder for every account, kept in the panel's
# settings, and each account gets a folder of its own inside it, named as
# its own folder is beside the install: "<install>" for the first person and
# "<install> - <account>" for each other one. The panel writes that folder
# into each account's config as documents_dir, a copy of the config kept
# first, when the setting is saved, and before a run of one whose config
# names no documents folder yet, so a provider or person added later gets
# theirs too, and a run from a terminal finds the same folder the panel
# would use. A config that names one, its own folder included, is changed
# only when the person saves something on the page.

DOCUMENTS_KEY = "documents_dir"
# The one documents folder, in the panel's settings.
DOCUMENTS_ROOT_KEY = "documents_root"
# The folders that stay in an account's own folder whatever its documents
# folder says, as core storage keeps them (_KEPT_WITH_RECORDS).
KEPT_FOLDERS = ("Manual Review", "Logs", "Diagnostics", "Backups")
# Each documents folder an account's documents were moved to, in its folder.
DOCUMENTS_FOLDERS = "documents-folders.json"
# What tells an app's Rename to move documents (core renaming.MOVE_DOCUMENTS_ENV).
MOVE_DOCUMENTS_ENV = "PAPERPULL_MOVE_DOCUMENTS"


def _account_config(meta: dict, account: str) -> Path:
    return Path(meta["dir"]) / ("config.json" if account == "primary"
                                else "config.%s.json" % account)


def _config_of(meta: dict, account: str) -> dict:
    """An account's config, or {} for one that is missing, is not JSON or
    holds something other than an object, a list or a number written by
    hand or left in the shared folder, so one such file stops nothing that
    reads the others."""
    cfg = _read_json(_account_config(meta, account))
    return cfg if isinstance(cfg, dict) else {}


def _documents_of(meta: dict, account: str) -> str:
    """The documents folder an account's config names, or ""."""
    value = _config_of(meta, account).get(DOCUMENTS_KEY)
    return value if isinstance(value, str) else ""


def _within(path, folder) -> bool:
    """Whether path is folder or inside it, where the links on the way to
    each lead."""
    try:
        where, home = Path(path).resolve(), Path(folder).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return where == home or home in where.parents


def _profiles_known(apps: dict) -> list:
    """Every browser profile the panel can name, each account's profile_dir
    and, on PaperPull Server, the profiles volume they are all kept on."""
    out = []
    if server_mode.enabled():
        out.append(Path(os.environ.get("PAPERPULL_PROFILES") or "/profiles"))
    for meta in apps.values():
        install = Path(meta["dir"])
        for account in meta["accounts"]:
            profile = _config_of(meta, account).get("profile_dir")
            if isinstance(profile, str) and profile.strip():
                path = Path(profile.strip())
                out.append(path if path.is_absolute() else install / path)
    return out


def _documents_problem(apps: dict, app_name: str, account: str, folder: str):
    """Why a folder cannot be an account's documents folder, or None. It has
    to be a full path, never a browser profile or inside or around one,
    never a folder holding a provider's own folder, and never inside the
    folder another account keeps its records in. On PaperPull Server it has
    to be inside the data folder, where its links lead."""
    # A run refuses a config naming such a folder (core load_config), since
    # it prints its folders, so the panel never saves one.
    if not run_result.on_one_line(folder):
        return ("A folder's path has to be one line of plain text, with no line break "
                "or other control character in it.")
    if not Path(folder).is_absolute():
        return "Give the folder's full path, starting with a drive letter or a /."
    target = Path(os.path.normpath(folder))
    if server_mode.enabled() and not server_mode.inside_data(target):
        return ("On PaperPull Server documents are kept inside the data folder, %s. "
                "Choose a folder in it." % server_mode.data_root())
    for profile in _profiles_known(apps):
        if _within(target, profile) or _within(profile, target):
            return ("That folder is a browser profile, is inside one or holds one, and "
                    "documents are never kept with a signed-in browser. Choose a folder "
                    "of their own.")
    for name, meta in apps.items():
        if _within(meta["dir"], target):
            return ("That folder holds %s's own folder, with its settings and records. "
                    "Choose a folder of their own." % name)
        for other in meta["accounts"]:
            try:
                root = _account_root(meta, other)
            except ValueError:
                continue
            who = name if other == "primary" else "%s, %s" % (name, other)
            # Around any account's own folder, this one's included, its
            # records and Manual Review would sit in the watched folder.
            if _within(root, target):
                return ("That folder holds the folder %s keeps its records and Manual Review "
                        "in. Choose a folder of their own." % who)
            if (name, other) != (app_name, account) and _within(target, root):
                return ("That folder is inside the folder %s keeps its records in. "
                        "Choose a folder of its own." % who)
            if (name, other) == (app_name, account) and _within(target, root):
                # Inside its own folder it may be, but not where a document
                # that failed its check or a run's own records are kept.
                try:
                    first = target.resolve().relative_to(root.resolve()).parts[:1]
                except (ValueError, OSError, RuntimeError):
                    first = ()
                if first and (first[0] in KEPT_FOLDERS or first[0].startswith(".")):
                    return ("That folder is inside %s, where documents that failed their "
                            "check or a run's own records are kept. Choose a folder of their "
                            "own." % first[0])
    return None


def _documents_root() -> str:
    """The one documents folder the page set, or "" for none."""
    value = _read_settings().get(DOCUMENTS_ROOT_KEY)
    return value if isinstance(value, str) else ""


def _documents_for(meta: dict, account: str, root: str) -> str:
    """The folder an account's documents go to inside the one documents
    folder, named as its own folder is beside the install, or "" when no
    documents folder is set."""
    if not root:
        return ""
    name = meta["name"] if account == "primary" else "%s - %s" % (meta["name"], account)
    return os.path.normpath(os.path.join(root, name))


def _follows_root(meta: dict, account: str, root: str) -> bool:
    """Whether an account's documents folder follows the one documents
    folder, its config naming none or the folder the root gives it. Any
    other value, "" for its own folder included, is one set for it alone."""
    return _follows(_config_of(meta, account), meta, account, root)


def _follows(cfg: dict, meta: dict, account: str, root: str) -> bool:
    """_follows_root of a config already read."""
    if DOCUMENTS_KEY not in cfg:
        return True
    value = cfg[DOCUMENTS_KEY]
    return bool(root) and isinstance(value, str) and value != "" and \
        os.path.normpath(value) == _documents_for(meta, account, root)


def _documents_counts(apps: dict, root: str) -> tuple[int, list]:
    """How many configured accounts follow the one documents folder, and
    each that keeps a folder of its own instead, by the name the page gives
    it and the folder its config names, "" for the folder its records are
    in. Those are what Use it for every provider replaces, so the page
    lists them before it is pressed."""
    following, own = 0, []
    if not root:
        return 0, []
    for name, meta in apps.items():
        for account in meta.get("accounts", ()):
            cfg_path = _account_config(meta, account)
            if not cfg_path.is_file():
                continue
            if _follows_root(meta, account, root):
                following += 1
            else:
                own.append({"who": _who(name, account), "folder": _documents_of(meta, account)})
    return following, own


def _documents_root_problem(apps: dict, root: str, force: bool = False):
    """Why a folder cannot be the one documents folder, or None. The folder
    itself is judged as an account's would be, belonging to no account, so
    it never holds or sits inside a provider's folder, an account's records
    or a browser profile, and so is the folder of every account that
    follows it."""
    problem = _documents_problem(apps, "", "", root)
    if problem:
        return problem
    old = _documents_root()
    # A folder set for one person alone is kept, unless every provider is
    # given its folder in it, and may not hold this one.
    held = None if force else _root_held_by(apps, root, old)
    if held:
        return ("%s has a folder of their own, %s, that holds that folder, so every provider's "
                "folder would be inside theirs. Choose another folder for them first."
                % held)
    for name, meta in apps.items():
        for account in meta.get("accounts", ()):
            if not force and not _follows_root(meta, account, old):
                continue
            problem = _in_root_problem(apps, name, account, root)
            if problem:
                return "%s would get %s inside it. %s" % (
                    _who(name, account), _documents_for(meta, account, root), problem)
    return None


def _in_root_name(name: str) -> str:
    """A folder's name as Windows and macOS tell names apart, which is
    without case and without the dots and spaces Windows takes off its end."""
    return name.rstrip(" .").casefold()


def _in_root_problem(apps: dict, app_name: str, account: str, root: str):
    """Why an account cannot have its folder inside the one documents
    folder, or None. It has to be one folder in it, named for the account
    alone, which no other provider or person would get as well, and to pass
    as any documents folder does (_documents_problem). An install or a
    config named for another's folder, "Chase Statements - spouse" beside
    Chase Statements' second person, would put two people's documents in
    one folder."""
    meta = apps[app_name]
    want = _documents_for(meta, account, root)
    name = meta["name"] if account == "primary" else "%s - %s" % (meta["name"], account)
    if Path(want).name != name or Path(want).parent != Path(os.path.normpath(root)):
        return "That is not one folder inside it, as each provider's and person's has to be."
    for other_name, other in apps.items():
        for other_account in other.get("accounts", ()):
            if (other_name, other_account) == (app_name, account):
                continue
            theirs = Path(_documents_for(other, other_account, root)).name
            if _in_root_name(theirs) == _in_root_name(name):
                return ("%s would get that same folder, and no two providers or people share "
                        "one." % _who(other_name, other_account))
            # A folder set for another alone, before the one documents
            # folder was, that is this folder or inside it.
            own = _documents_of(other, other_account)
            if own and Path(own).is_absolute() and _within(own, want):
                return ("%s has that folder, or one inside it, as a folder of their own. Choose "
                        "another folder for them first." % _who(other_name, other_account))
    return _documents_problem(apps, app_name, account, want)


def _root_held_by(apps: dict, root: str, followed: str, skip=None):
    """The first account that keeps a folder of its own holding the one
    documents folder `root`, or that is it, as (the name the page gives it,
    that folder), or None. An account following `followed`, the documents
    folder in force until now, has none of its own, and `skip` is an (app,
    account) whose folder is about to be replaced. Every account following
    the root would have its documents inside that one person's folder."""
    for name, meta in apps.items():
        for account in meta.get("accounts", ()):
            if (name, account) == skip or not _account_config(meta, account).is_file() \
                    or _follows_root(meta, account, followed):
                continue
            own = _documents_of(meta, account)
            if own and Path(own).is_absolute() and _within(root, own):
                return _who(name, account), own
    return None


def _root_held_problem(apps: dict, root: str, skip=None):
    """Why no account may follow the one documents folder, set as it is,
    into a folder in it, or None (_root_held_by)."""
    held = _root_held_by(apps, root, root, skip=skip)
    if held:
        return ("%s has a folder of their own, %s, that holds the folder for every provider. "
                "Choose another folder for them first." % held)
    return None


def _own_in_root_problem(apps: dict, app_name: str, account: str, folder: str, root: str):
    """Why a folder set for one account alone cannot be used while the one
    documents folder is set, or None. It may not be that folder itself,
    where every provider's folder is, nor another provider's or person's
    folder inside it, or a folder inside that one."""
    if not root:
        return None
    if _within(folder, root) and _within(root, folder):
        return ("That is the folder for every provider itself. Use the folder for every "
                "provider gives this one its folder inside it, or choose another folder.")
    if _within(root, folder):
        return ("That folder holds the folder for every provider, so every provider's folder "
                "would be inside it. Choose another folder.")
    for other_name, other in apps.items():
        for other_account in other.get("accounts", ()):
            if (other_name, other_account) != (app_name, account) and \
                    _within(folder, _documents_for(other, other_account, root)):
                return ("That folder is %s's folder inside the folder for every provider, or "
                        "inside it. Choose a folder of their own."
                        % _who(other_name, other_account))
    return None


def _sync_documents(apps: dict, old: str, only=None, force: bool = False,
                    missed: Optional[list] = None) -> int:
    """Give each account that follows the one documents folder, `old` being
    the root it followed until now, its folder inside the root set now,
    clearing it when none is set, and return how many configs changed. An
    account with a folder of its own, or no config yet, is passed by,
    unless `force` is True to apply the root to every account.
    `only` is an (app, account) to write that one alone, as a run does
    before it starts. One whose folder in the root is refused, a provider
    installed inside the documents folder since it was saved for instance,
    keeps what its config says. Each whose config should have changed and
    could not be written is put in `missed`, by the name the page gives it."""
    root = _documents_root()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    written = 0
    for name, meta in apps.items():
        for account in meta.get("accounts", ()):
            if only is not None and (name, account) != only:
                continue
            cfg_path = _account_config(meta, account)
            if not cfg_path.is_file():
                continue
            if not force and not _follows_root(meta, account, old):
                continue
            want = _documents_for(meta, account, root)
            if want and _in_root_problem(apps, name, account, root):
                continue
            # Asked again of the config as it is written, so a folder of
            # their own saved in another tab since is kept.
            still = None if force else (
                lambda cfg, meta=meta, account=account: _follows(cfg, meta, account, old))
            if _write_config(cfg_path, DOCUMENTS_KEY, want, stamp, why="documents", when=still):
                written += 1
                continue
            if not force and not _follows_root(meta, account, old):
                continue
            # Nothing to change, or a config that could not be read or written.
            now = _read_json(cfg_path)
            if missed is not None and not (isinstance(now, dict)
                                           and (now.get(DOCUMENTS_KEY) or "") == want):
                missed.append(_who(name, account))
    return written


def _who(app_name: str, account: str) -> str:
    """A provider and person as the page names them."""
    return app_name if account == "primary" else "%s, %s" % (app_name, account)


def _documents_before_run(apps: dict, app_name: str, account: str) -> list:
    """Before a run, give an account whose config names no documents folder
    at all, a provider or person added since the one documents folder was
    saved, its folder inside it, and return what the run's output says of
    that. A config naming any documents folder, "" for its own folder
    included, is never changed here, so a folder somebody chose stays
    theirs. Nothing when no documents folder is set."""
    root = _documents_root()
    meta = apps.get(app_name)
    if not root or meta is None:
        return []
    cfg = _read_json(_account_config(meta, account))
    if not isinstance(cfg, dict) or DOCUMENTS_KEY in cfg:
        return []
    want = _documents_for(meta, account, root)
    problem = _in_root_problem(apps, app_name, account, root) or _root_held_problem(apps, root)
    if problem:
        return ["Documents stay where they were. %s would get %s inside the folder for every "
                "provider. %s" % (_who(app_name, account), want, problem)]
    missed = []
    if _sync_documents(apps, root, only=(app_name, account), missed=missed):
        return ["Documents go to %s from this run on, inside the folder for every provider "
                "set in Settings." % want]
    if missed:
        return ["Documents stay where they were. %s would get %s inside the folder for every "
                "provider, and its config could not be written." % (missed[0], want)]
    return []


def _documents_roots(root: Path) -> list:
    """Each documents folder an account's documents were moved to, as the
    Move wrote them down in its folder (core storage.Paths.documents_roots)."""
    listed = _read_json(root / DOCUMENTS_FOLDERS)
    return [Path(p) for p in (listed if isinstance(listed, list) else ())
            if isinstance(p, str) and Path(p).is_absolute()]


def _file_key_of(raw: str, root: Path) -> str:
    path = Path(raw.strip())
    path = path if path.is_absolute() else root / path
    return os.path.normcase(os.path.abspath(str(path)))


def _indexed_files(root: Path):
    """Each file an account's index names, by its index of documents or of
    receipts in its folder, or None when it has no index there. Each row is
    read as the app wrote it, the quote it puts before a value that starts
    like a formula taken off again (paperpull_core.sheets)."""
    _naming()          # the core beside the panel, on the path
    try:
        from paperpull_core.sheets import read_stored_row
    except ImportError:
        return None
    found = None
    for index in sorted(root.glob("* Index.csv")):
        try:
            with open(index, encoding="utf-8-sig", newline="") as fh:
                rows = [read_stored_row(r) for r in csv.DictReader(fh)]
        except (OSError, ValueError, csv.Error):
            continue
        found = found if found is not None else set()
        found |= {_file_key_of(r["PDF Full Path"], root) for r in rows
                  if isinstance(r.get("PDF Full Path"), str) and r["PDF Full Path"].strip()}
    return found


def _documents_left(meta: dict, account: str) -> int:
    """How many documents an account's records name that are saved and
    checked, and are in a folder of their kind in its own folder or in a
    documents folder it used before, and so not yet in its documents folder,
    as the Move would count them. Read from its progress.json, each file
    counted once and only while it is there, never one in Manual Review."""
    try:
        root = _account_root(meta, account)
        home = root.resolve()
        docs = _documents_of(meta, account)
        here = Path(docs).resolve() if docs else home
        roots = [home] + [r.resolve() for r in _documents_roots(root)]
    except (ValueError, OSError, RuntimeError):
        return 0
    data = _read_json(root / "progress.json")
    indexed = _indexed_files(root)
    seen = set()
    for rec in data.values() if isinstance(data, dict) else ():
        if not isinstance(rec, dict) or not (
                rec.get("downloaded_ok") is True or rec.get("state") in ("Completed",
                                                                        "PDF Verified")):
            continue
        # The Move takes a file an index row names, and each other invoice
        # of an order split into several.
        main = rec.get("pdf_path")
        if indexed is not None and isinstance(main, str) and \
                _file_key_of(main, root) not in indexed:
            main = None
        invoices = rec.get("invoices")
        files = [main] + [e.get("file") for e in (invoices if isinstance(invoices, list) else ())
                          if isinstance(e, dict) and e.get("kept", True)]
        for raw in files:
            if not isinstance(raw, str) or not raw.strip().lower().endswith(".pdf"):
                continue
            path = Path(raw.strip())
            path = path if path.is_absolute() else root / path
            try:
                where = path.resolve()
            except (OSError, RuntimeError):
                continue
            if here in where.parents or not where.is_file():
                continue
            for top in roots:
                if top == here or top not in where.parents:
                    continue
                parts = where.relative_to(top).parts
                if len(parts) >= 2 and not (top == home and parts[0] in KEPT_FOLDERS):
                    seen.add(os.path.normcase(str(where)))
                break
    return len(seen)


def _move_new_documents(meta: dict, account: str, saved: list, env: dict) -> list:
    """Once a download run has ended, move what it saved and checked into the
    account's documents folder, through the app's own Rename told to move
    the documents its run listed in new-this-run.txt alone (#102). Nothing
    for an account with no documents folder, or a run that listed nothing
    since it started (`saved`, the list the page shows). The lines to show
    beneath the run's own."""
    if not _documents_of(meta, account):
        return []
    if not saved:
        return []
    cmd = _command(meta, account, ["--rename", "--apply"])
    mark = run_result.new_mark()
    try:
        proc = subprocess.Popen(cmd, cwd=meta["dir"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace",
                                env=dict(env, **{MOVE_DOCUMENTS_ENV: "new",
                                                 run_result.MARK_ENV: mark}))
    except Exception as e:
        return ["", "The new documents could not be moved to the documents folder (%s). "
                    "Settings, Documents folder, can move them." % type(e).__name__]
    try:
        proc.stdin.close()
    except OSError:
        pass
    said = [line.rstrip() for line in proc.stdout
            if run_result.parse(line.rstrip("\r\n"), mark) is None]
    if proc.wait():
        said.append("Not every new document was moved to the documents folder. Settings, "
                    "Documents folder, can move them.")
    return [""] + said


def _documents_account(app_name: str, account: str):
    apps = discover_apps()
    meta = apps.get(app_name)
    if meta is None or account not in meta["accounts"]:
        raise HTTPException(404, "unknown app or account")
    try:
        root = _account_root(meta, account)
    except ValueError:
        raise HTTPException(404, "that account's config names no folder PaperPull can read")
    return apps, meta, root


def _documents_answer(meta: dict, account: str, root: Path, apps: dict = None) -> dict:
    docs_root = _documents_root()
    if apps is None:
        apps = discover_apps()
    following, own = _documents_counts(apps, docs_root)
    # Why the folder the page would say they get from their next download
    # is one that run will refuse (_documents_before_run), or "".
    refused = ""
    if docs_root and DOCUMENTS_KEY not in _config_of(meta, account) and meta["name"] in apps:
        refused = (_in_root_problem(apps, meta["name"], account, docs_root)
                   or _root_held_problem(apps, docs_root) or "")
    return {"documents_dir": _documents_of(meta, account), "output_dir": str(root),
            "documents_root": docs_root,
            "follows": bool(docs_root) and _follows_root(meta, account, docs_root),
            "in_root": _documents_for(meta, account, docs_root),
            "in_root_refused": refused,
            "following": following,
            "unfollowed": len(own),
            "own": own,
            "left": _documents_left(meta, account),
            "kept": list(KEPT_FOLDERS)}


async def _folder_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    folder = body.get("folder", "")
    if not isinstance(folder, str) or len(folder) > 1000:
        raise HTTPException(400, "folder is the folder's path as text")
    body["folder"] = folder.strip()
    return body


@app.get("/api/documents", dependencies=[Depends(_same_origin_only)])
def api_documents(app: str, account: str = "primary"):
    apps, meta, root = _documents_account(app, account)
    return _documents_answer(meta, account, root, apps=apps)


@app.post("/api/documents", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_documents_save(request: Request):
    """Give one account a documents folder of its own, in its own config, a
    copy kept in Backups first, or, with "follow", set it back to its folder
    inside the one documents folder. An empty folder, or the account's own
    folder, is its own folder, kept as that even when a documents folder is
    set. Nothing is moved."""
    body = await _folder_body(request)
    # Off the event loop, since every account's config is read and a folder
    # on a share that does not answer would hold every other request.
    return await to_thread.run_sync(_save_account_documents, body)


def _save_account_documents(body: dict) -> dict:
    folder = body["folder"]
    app_name, account = str(body.get("app") or ""), str(body.get("account") or "primary")
    apps, meta, root = _documents_account(app_name, account)
    docs_root = _documents_root()
    follow = body.get("follow") is True
    if follow:
        folder = _documents_for(meta, account, docs_root)
    elif folder and Path(folder).is_absolute() and _within(folder, root) and _within(root, folder):
        # The account's own folder, where its documents go already.
        folder = ""
    if folder and follow:
        problem = _in_root_problem(apps, app_name, account, docs_root) or \
            _root_held_problem(apps, docs_root, skip=(app_name, account))
        if problem:
            raise HTTPException(400, "%s would get %s inside the folder for every provider. %s"
                                % (_who(app_name, account), folder, problem))
    elif folder:
        problem = (_documents_problem(apps, app_name, account, folder)
                   or _own_in_root_problem(apps, app_name, account, folder, docs_root))
        if problem:
            raise HTTPException(400, problem)
    if folder:
        folder = os.path.normpath(folder)
    cfg_path = _account_config(meta, account)
    if not cfg_path.is_file():
        raise HTTPException(404, "that account has no settings yet")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Its own folder is written as "" while a documents folder is set, so
    # the account stays out of it, and is no setting at all when none is.
    written = _write_config(cfg_path, DOCUMENTS_KEY, folder, stamp, why="documents",
                            keep_empty=bool(docs_root) and body.get("follow") is not True)
    return dict(_documents_answer(meta, account, root, apps=apps), written=written)


@app.post("/api/documents/root",
          dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_documents_root_save(request: Request):
    """Set or clear the one documents folder, in the panel's settings, and
    give every account that follows it its folder inside it, in its own
    config, a copy of each config kept in Backups first. An account with a
    folder of its own keeps it, unless "all" is True to apply it to all
    accounts. Every following account's folder has to pass, or nothing is
    saved. Nothing is moved. "all" is taken only with the folder already
    saved, the one whose accounts with a folder of their own the page
    listed before it was pressed."""
    body = await _folder_body(request)
    # Off the event loop, as an account's own folder is (_save_account_documents).
    return await to_thread.run_sync(_save_documents_root, body["folder"], body.get("all") is True)


def _save_documents_root(folder: str, apply_all: bool) -> dict:
    if _IMPORTING.locked():
        # An import fills in the configs it sets up, and the two would each
        # write a config the other had just read.
        raise HTTPException(409, "A history file is being imported. Save this once it has "
                                 "finished.")
    if apply_all and (not folder or os.path.normpath(folder) != _documents_root()):
        raise HTTPException(409, "Save that folder first. Use it for every provider gives every "
                                 "provider and person a folder inside the folder saved.")
    apps = discover_apps()
    if folder:
        problem = _documents_root_problem(apps, folder, force=apply_all)
        if problem:
            raise HTTPException(400, problem)
        folder = os.path.normpath(folder)
    data = _read_settings()
    old = data.get(DOCUMENTS_ROOT_KEY) if isinstance(data.get(DOCUMENTS_ROOT_KEY), str) else ""
    if folder:
        data[DOCUMENTS_ROOT_KEY] = folder
    else:
        data.pop(DOCUMENTS_ROOT_KEY, None)
    try:
        _write_settings(data)
    except OSError as e:
        raise HTTPException(500, "could not save the folder: %s" % e)
    missed = []
    written = _sync_documents(apps, old, force=apply_all, missed=missed)
    following, own = _documents_counts(apps, folder)
    return {"documents_root": folder, "written": old != folder or bool(written),
            "configs": written, "following": following, "unfollowed": len(own),
            "own": own, "missed": missed}


# -- the terms of use ---------------------------------------------------------
#
# TERMS.md, accepted from the page the first time it opens, once for each
# version of the terms. The version is the terms' effective date, the date at
# the top of TERMS.md, so changing the terms means changing both, and the
# page asks again. The answer is kept in the settings file, so on the server
# it lives in /config and is asked once for the box, not once per browser.
# The page is told in the HTML whether to ask, so nothing waits on a request,
# and a page that cannot save the answer still goes on, asking again next
# time. The apps' own commands do not ask.
TERMS_VERSION = "2026-10-13"


def terms_due() -> bool:
    return _read_settings().get("terms_accepted") != TERMS_VERSION


@app.post("/api/terms", dependencies=[Depends(_same_origin_only)])
async def api_terms(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    if not isinstance(body, dict) or body.get("accepted") != TERMS_VERSION:
        raise HTTPException(409, "those are not the current terms, reload the page")
    data = _read_settings()
    data["terms_accepted"] = TERMS_VERSION
    try:
        _write_settings(data)
    except OSError as e:
        raise HTTPException(500, "could not save the answer: %s" % e)
    return {"accepted": TERMS_VERSION}


# The line along the bottom of the page. The desktop one says the panel runs
# on this computer and offers the paid Store edition. Neither is true of
# PaperPull Server, which is free and runs on a box of the person's own, so
# the server says that instead and keeps only the donation link.
FOOTER_DESKTOP = (
    '<span>PaperPull v__VERSION__ &middot; read-only, runs locally</span>\n'
    '  <span>Free, and it costs money to make. Show your appreciation: '
    '<a href="https://ko-fi.com/rheeloaded" target="_blank" rel="noopener">donate on Ko-fi</a> or '
    '<a href="https://github.com/rheeloaded/paperpull#support" target="_blank" rel="noopener">'
    'buy the Store edition</a></span>')
FOOTER_SERVER = (
    '<span>PaperPull Server v__VERSION__ &middot; read-only, runs on your own server</span>\n'
    '  <span>Free, and it costs money to make. If it saves you time, you can '
    '<a href="https://ko-fi.com/rheeloaded" target="_blank" rel="noopener">donate on Ko-fi</a>.</span>')


# The panel's page carries its whole script inline, in one block.
_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)


def _script_policy(page: str) -> str:
    """The page's policy for scripts. Only the very script the page was
    served with may run, named by its hash, so a script that found its way
    into the page some other way, through a name or a title shown in it,
    never runs, and nor does a plugin or a frame of another kind. The
    browser hashes a script with its line breaks made plain, and _page
    reads the files that way, so the hash is of the very text it hashes."""
    hashes = []
    for script in _SCRIPT_RE.findall(page):
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
        hashes.append("'sha256-%s'" % digest)
    return ("script-src %s; object-src 'none'; base-uri 'none'; form-action 'self'"
            % (" ".join(hashes) or "'none'"))


def index() -> str:
    """The panel's page, filled in for this edition and this person."""
    server = server_mode.enabled()
    bar = server_mode.server_bar() if server else ""
    footer = FOOTER_SERVER if server else FOOTER_DESKTOP
    return (HTML.replace("__FOOTER__", footer)
            .replace("__VERSION__", VERSION).replace("__SERVER_BAR__", bar)
            .replace("__SERVER__", "true" if server else "false")
            .replace("__TERMS_VERSION__", TERMS_VERSION)
            .replace("__TERMS_DUE__", "true" if terms_due() else "false"))


@app.get("/", response_class=HTMLResponse)
def panel_page():
    """The panel's page, with the policy that lets only its own script run."""
    page = index()
    return HTMLResponse(page, headers={"Content-Security-Policy": _script_policy(page)})


# The PaperPull icon, for the browser tab the panel opens in. There is one
# icon file, and each kind of copy keeps it in its own place, the repo and
# the server image in packaging/ beside this folder, the Windows package and
# the Mac bundle's Resources right beside it.
_ICON_PLACES = (HERE.parent / "packaging" / "paperpull.ico",
                HERE.parent / "paperpull.ico")


def _icon_file() -> Optional[Path]:
    return next((p for p in _ICON_PLACES if p.is_file()), None)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """The icon itself. It is the same for everyone and says nothing about
    the person, so it is served to any request, the way a page's icon is."""
    icon = _icon_file()
    if icon is None:
        raise HTTPException(404, "no icon")
    return Response(content=icon.read_bytes(), media_type="image/x-icon",
                    headers={"Cache-Control": "max-age=86400"})


STATIC = HERE / "static"
# The panel's two typefaces, gui/static/fonts, licensed under the SIL Open
# Font License (NOTICE.md). Served by name from this list and nothing else,
# so no request can name another file.
FONTS = ("AtkinsonHyperlegibleNext.ttf", "AtkinsonHyperlegibleMono.ttf")


@app.get("/fonts/{name}", include_in_schema=False)
def font(name: str):
    """One of the panel's typefaces. Like the icon they are the same for
    everyone and say nothing about the person. On the server they come only
    after the password, as every page does. Kept for a day in the browser."""
    if name not in FONTS:
        raise HTTPException(404, "no such font")
    try:
        data = (STATIC / "fonts" / name).read_bytes()
    except OSError:
        raise HTTPException(404, "no such font")
    return Response(content=data, media_type="font/ttf",
                    headers={"Cache-Control": "max-age=86400"})


def _page() -> str:
    """The panel's one page, from gui/static. index.html is the page with
    __CSS__ and __JS__ where its style and script go, so the page still
    arrives whole in one answer and nothing else needs a route. Read once,
    at import. A copy missing any of the three is a broken build, and says
    so here rather than serving half a page."""
    def read(name):
        return (STATIC / name).read_text(encoding="utf-8")
    return (read("index.html").replace("__CSS__", read("app.css"), 1)
            .replace("__JS__", read("app.js"), 1))


HTML = _page()

