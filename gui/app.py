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

import json
import os
from datetime import date, datetime
import re
import shutil
import subprocess
from typing import Optional
import sys
from pathlib import Path
from urllib.parse import urlsplit

import run_result

from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

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
}
# The actions for when something is off, kept behind a "more" link so the
# main panel stays the four a normal day needs. Verify re-checks saved PDFs,
# Diagnose surveys the page. Both are harmless and both are rarely wanted.
MORE_ACTIONS = ("verify", "diagnose", "record", "rename", "rename_apply")
ENTRY_RE = re.compile(r".*_(receipts|docs)\.py$")

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

app = FastAPI(title="PaperPull")

# The panel runs the apps' commands, so its API must only answer requests that
# originate from the panel page itself (served on localhost). A CSRF attempt
# driven by another website carries an Origin/Referer whose host is that site;
# same-origin requests from the panel carry a localhost host or no such header
# at all. There is no CORS middleware, so cross-origin JS can't read responses
# either - this closes the remaining "trigger a run" vector.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", ""}


def _same_origin_only(request: Request) -> None:
    """Refuse anything a different site set off.

    Origin and Referer answer this whenever they are sent, and a page can
    arrange for neither to be. An <img> does not carry an Origin, and a
    page that declares `no-referrer` strips the other, which left a plain
    GET able to reach this panel from a website somebody was merely
    visiting. /api/run is a GET, and it starts a download.

    Sec-Fetch-Site is the one that closes it. Every current browser sends
    it on every request, page script cannot set it, and it says plainly
    where the request came from: same-origin for the panel's own page,
    cross-site for somebody else's, none for an address typed in. It is
    absent from curl and from browsers old enough not to know it, and
    those are allowed through, because the header being missing is not
    the same as it saying cross-site.
    """
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site and site not in ("same-origin", "none"):
        raise HTTPException(403, "cross-origin request refused")
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        host = (urlsplit(value).hostname or "").lower()
        if host not in _LOCAL_HOSTS:
            raise HTTPException(403, "cross-origin request refused")


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

    Falling back to this program's own is right for the packaged build,
    whose single bundled interpreter carries the shared core and every
    app's dependencies. In a checkout it is a trap: the panel's venv has
    fastapi and nothing else, so an app that has not been set up ran
    under it and died on `No module named 'paperpull_core'`, a sentence
    about the wrong interpreter that tells a tester nothing. The run
    endpoint refuses that case before it gets here."""
    venv = _venv_python(app_dir)
    return str(venv) if venv else sys.executable


def setup_needed(meta: dict) -> str:
    """Why this app cannot be run yet, or "".

    Only ever true in a checkout, apart from the sample archive. The
    packaged build has no venv anywhere and does not need one."""
    if _SAMPLE is not None:
        return ("This is the sample archive, so there is nothing to sign in "
                "to and nothing to download.\n\n"
                "Everything already in it was invented to show what a real "
                "archive looks like. The Status tab and both spreadsheets "
                "work on it exactly as they would on yours.\n\n"
                "To see the sign-in step, leave the sample, add a provider, "
                "and press Login. Your own browser opens on that provider's "
                "sign-in page. Nothing is downloaded until you have signed "
                "in there yourself, and PaperPull never sees what you type.")
    if _is_packaged() or _venv_python(Path(meta["dir"])) is not None:
        return ""
    script = "setup.command" if sys.platform != "win32" else "setup.bat"
    return ("This provider is not set up yet, so there is nothing to run "
            "it with.\n\n"
            "  1. Open  %s\n"
            "  2. Double-click  %s  and let it finish\n"
            "  3. Come back here and RELOAD this page\n\n"
            "Step 3 is not optional. Reloading is what puts the shared "
            "code into the new folder. Without it the buttons will fail "
            "on an import error." % (meta["dir"], script))


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
        accts.append(name)
    return accts


def discover_apps():
    apps = {}
    if not apps_root().exists():
        return apps
    for d in sorted(apps_root().iterdir()):
        if not d.is_dir():
            continue
        script = _entry_script(d)
        if not script:
            continue
        apps[d.name] = {
            "name": d.name,
            "dir": str(d),
            "script": script.name,
            "python": _python_for(d),
            "login_flag": _login_flag(script),
            "accounts": _accounts(d),
            "has_venv": _venv_python(d) is not None,
            # Only a checkout is ever told to run setup. The packaged app
            # has no per-app venv and needs none, the interpreter it falls
            # back to carries everything, and nothing in the sample is ever
            # run, so there it is advice about a problem that cannot arise.
            "needs_setup": (_SAMPLE is None and _venv_python(d) is None
                            and not _is_packaged()),
        }
    return apps


@app.get("/api/apps", dependencies=[Depends(_same_origin_only)])
def api_apps():
    refreshed = refresh_installs()
    apps = discover_apps()
    return {"apps_root": str(apps_root()), "root_source": root_source(), "actions": {k: v["label"] for k, v in ACTIONS.items()},
            "more_actions": list(MORE_ACTIONS), "apps": apps, "refreshed": refreshed}


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
    for cand in (HERE.parent / "tools" / "status.py",
                 apps_root() / "status.py",
                 apps_root().parent / "status.py",
                 HERE.parent / "status.py"):
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
    for cand in (HERE.parent / "tools" / "export_purchases.py",
                 apps_root() / "export_purchases.py",
                 apps_root().parent / "export_purchases.py",
                 HERE.parent / "export_purchases.py"):
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
    for cand in (HERE.parent / "tools" / "export_transactions.py",
                 apps_root() / "export_transactions.py",
                 apps_root().parent / "export_transactions.py",
                 HERE.parent / "export_transactions.py"):
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
        yield f"data: $ export_transactions.py {' '.join(cmd[3:])}\n\n"
        # The version goes to the app so that a file it writes says which
        # build wrote it. Every failure file so far has carried an empty
        # version, which is the one field that says what a tester ran.
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   PAPERPULL_VERSION=VERSION)
        try:
            proc = subprocess.Popen(cmd, cwd=str(tool.parent), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, env=env)
        except Exception as e:
            yield f"data: [failed to start] {e}\n\n"
            yield "event: done\ndata: 1\n\n"
            return
        wrote = None
        try:
            while True:
                line = await to_thread.run_sync(proc.stdout.readline)
                if not line:
                    break
                if line.startswith("Wrote "):
                    wrote = line[6:].strip()
                yield f"data: {line.rstrip()}\n\n"
            code = await to_thread.run_sync(proc.wait)
            if code == 0 and wrote:
                _LAST_EXPORT = Path(wrote)
                yield f"event: result\ndata: {json.dumps({'path': wrote})}\n\n"
            yield f"event: done\ndata: {code}\n\n"
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


@app.post("/api/export/reveal", dependencies=[Depends(_same_origin_only)])
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


@app.post("/api/root", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
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


def _provider_notes() -> dict:
    """What each app downloads, from the table in PROVIDERS.md, keyed by slug.
    Best effort. A missing file or a changed table just means no note."""
    notes = {}
    try:
        text = (HERE.parent / "PROVIDERS.md").read_text(encoding="utf-8")
    except OSError:
        return notes
    for line in text.splitlines():
        m = re.match(r"\|\s*\[`([a-z0-9_]+)`\][^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if m:
            notes[m.group(1)] = {"documents": m.group(3).strip(),
                                 "category": m.group(4).strip()}
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
                    "category": n.get("category", "")})
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
    # The double-click launchers call .venv\Scripts\python.exe, which the
    # packaged app never has, and setup.bat wants a system Python it cannot
    # assume. Copied into a packaged install they are a folder of files that
    # all fail, right where a new user goes looking. The panel does their job.
    skip_launchers = _is_packaged()
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
        if skip_launchers and item.suffix.lower() in LAUNCHER_SUFFIXES:
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
    return "created"


def _set_owner(config: Path, owner: str) -> None:
    """The account holder's name, written once when the install is made.

    An app asks for this on its first run at a console. Started from this
    panel its stdin is closed, so it cannot ask and the name stays empty,
    and an empty name is the one thing that stops redaction taking a
    person's name out of a survey or a recording. So it is asked for
    here, where somebody is looking at a screen."""
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return
        data["owner"] = owner[:80]
        config.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _template_files(src: Path):
    """The files a template ships to an install, the same filter the first
    copy uses."""
    skip_launchers = _is_packaged()
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        if any(part in _TEMPLATE_SKIP or _is_someones_own(part)
               or "browser-profile" in part.lower()
               or part.lower().endswith(".pdf") for part in rel.parts):
            continue
        if skip_launchers and item.suffix.lower() in LAUNCHER_SUFFIXES:
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
        try:
            if target.is_file() and target.read_bytes() == new:
                continue
        except OSError:
            continue
        if target.is_file():
            bak = dst / "Backups" / ("code-" + stamp) / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, bak)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
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
        bak.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, bak)
        live.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
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
    anything. Found by adding Costco and running it."""
    core_src = HERE.parent / "core" / "paperpull_core"
    venv = dst / ".venv"
    if not core_src.is_dir() or not venv.is_dir():
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
        if any(True for _ in venv.rglob("paperpull_core/__init__.py")):
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
    return {"providers": out, "templates": _templates_root() is not None,
            "suggested_root": str(Path.home() / "Documents" / "PaperPull")}


@app.post("/api/create", dependencies=[Depends(_same_origin_only), Depends(_not_in_sample)])
async def api_create(request: Request):
    """Make installs for the chosen providers under the chosen folder, and
    remember that folder. The folder is created if it does not exist, since a
    new user has no reason to have made one first."""
    if os.environ.get("APPS_ROOT"):
        raise HTTPException(409, "APPS_ROOT is set in the environment, which "
                                 "overrides any saved choice. Unset it first.")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON body")
    raw = str((body or {}).get("root") or "").strip().strip('"')
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
    for cand in (HERE.parent / "tools" / "add_account.py",
                 apps_root() / "add_account.py",
                 apps_root().parent / "add_account.py"):
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
    mod = _account_module()
    if mod is None:
        raise HTTPException(500, "add_account.py was not found next to this control panel")
    app_dir = Path(apps[name]["dir"])
    if not (app_dir / "config.json").is_file():
        raise HTTPException(409, "%s has no config.json yet. Run Login once for the first account, "
                                 "then add the second." % name)
    try:
        dest = mod.make_config(app_dir, label, owner=owner)
    except Exception as e:
        raise HTTPException(500, "could not make the account: %s" % str(e).splitlines()[0][:160])
    cfg = json.loads(Path(dest).read_text(encoding="utf-8"))
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"app": name, "account": label, "config": Path(dest).name,
            "output_dir": cfg.get("output_dir", ""), "cdp_url": cfg.get("cdp_url", ""),
            "owner": cfg.get("owner", "")}


# -- stopping a recording -----------------------------------------------------

def _diagnostics_of(meta: dict) -> Path:
    """An app's Diagnostics folder, wherever its config sends output."""
    app_dir = Path(meta["dir"])
    out = ""
    try:
        cfg = json.loads((app_dir / "config.json").read_text(encoding="utf-8-sig"))
        out = str(cfg.get("output_dir") or "")
    except (OSError, ValueError):
        pass
    base = Path(out).expanduser() if out else app_dir
    if not base.is_absolute():
        base = (app_dir / base)
    return base / "Diagnostics"


def _latest_failure(meta: dict):
    """The newest failure file an app wrote, if it wrote one recently.

    A run that stops early writes one of these by itself. It is the most
    useful thing a tester can attach and the easiest to never notice, so
    the panel offers it rather than leaving a path in a console.

    Recent means this hour. An older one belongs to a run nobody is
    looking at any more, and offering that would have somebody attach the
    wrong failure to the right issue."""
    import time
    try:
        found = sorted(_diagnostics_of(meta).glob("failure-*.json"))
    except OSError:
        return None
    for path in reversed(found):
        try:
            if time.time() - path.stat().st_mtime < 3600:
                return path
        except OSError:
            continue
    return None


@app.get("/api/failure/latest", dependencies=[Depends(_same_origin_only)])
def api_failure_latest(app: str = ""):
    """Whether the run that just stopped left a file worth attaching."""
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    found = _latest_failure(apps[app])
    if found is None:
        return {"found": False}
    return {"found": True, "name": found.name}


@app.post("/api/failure/reveal", dependencies=[Depends(_same_origin_only)])
async def api_failure_reveal(request: Request):
    """Show that file in the file manager. Takes no path from the page,
    only the app name, and finds the file here the same way."""
    body = await request.json()
    name = str((body or {}).get("app") or "")
    apps = discover_apps()
    if name not in apps:
        raise HTTPException(404, "unknown app")
    found = _latest_failure(apps[name])
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
    target = _diagnostics_of(apps[name])
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / ".stop-recording").write_text("stop\n", encoding="utf-8")
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
    if dest.exists():
        dest = dest_dir / ("%s (%s)" % (name, datetime.now().strftime("%Y%m%d-%H%M%S")))
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    except OSError as e:
        raise HTTPException(500, "could not move the folder: %s. Is a file in it "
                                 "open, or a browser still signed in there?" % e)
    global _STATUS_MOD
    _STATUS_MOD = None
    return {"app": name, "moved_to": str(dest), **summary}


def _build_cmd(app_meta: dict, account: str, action: str, scope_flags=()):
    if action not in ACTIONS:
        raise HTTPException(400, "unknown action")
    if account not in app_meta["accounts"]:
        raise HTTPException(400, "unknown account")
    flags = []
    for f in ACTIONS[action]["flags"]:
        flags.append(app_meta["login_flag"] if f == "__LOGIN__" else f)
    if action != "login":
        flags += list(scope_flags)
    cmd = [app_meta["python"], app_meta["script"], *flags]
    if account != "primary":
        cmd += ["--config", f"config.{account}.json"]
    return cmd


@app.get("/api/run", dependencies=[Depends(_same_origin_only)])
def api_run(app: str, account: str = "primary", action: str = "pilot",
            year: str = "", start: str = "", end: str = ""):
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    meta = apps[app]
    blocked = setup_needed(meta)
    cmd = _build_cmd(meta, account, action, _scope_flags(year, start, end))

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
                yield "data: %s\n\n" % line
            yield "event: done\ndata: %d\n\n" % code
        return StreamingResponse(refuse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # Deliberately an *async* generator. With a plain sync one, Starlette wraps
    # it in iterate_in_threadpool, which never calls .close() on it - so the
    # cleanup below would never run and a closed tab left the downloader going.
    async def stream():
        yield f"data: $ {' '.join(cmd)}\n\n"
        # The version goes to the app so that a file it writes says which
        # build wrote it. Every failure file so far has carried an empty
        # version, which is the one field that says what a tester ran.
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   PAPERPULL_VERSION=VERSION)
        try:
            _RUNNING.add(app)
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
            yield f"data: [failed to start] {e}\n\n"
            yield "event: done\ndata: 1\n\n"
            return
        # Closing the browser tab closes this generator. Without the finally
        # below, the downloader kept running unseen - still driving your
        # signed-in browser over CDP and still writing PDFs and progress.json -
        # with nothing on screen. Worse, believing it had stopped, you could
        # press Run again and put two runs on one progress.json, one CDP port
        # and one output folder. Stopping is safe: downloaded_ok is only set
        # after a document is saved, so a re-run resumes and re-fetches nothing.
        result = None
        try:
            while True:
                # readline blocks, so it goes to a worker thread rather than
                # stalling the event loop for every other request.
                line = await to_thread.run_sync(proc.stdout.readline)
                if not line:
                    break
                parsed = run_result.parse(line)
                if parsed is not None:
                    result = parsed
                else:
                    yield f"data: {line.rstrip()}\n\n"
            code = await to_thread.run_sync(proc.wait)
            if result is not None:
                yield f"event: result\ndata: {json.dumps(result)}\n\n"
            yield "data: \n\n"
            yield f"event: done\ndata: {code}\n\n"
        finally:
            _RUNNING.discard(app)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if proc.stdout:
                proc.stdout.close()

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


def _naming_records(d: Path) -> list:
    """The first person's records, for the preview and the fill rates.
    Read from the output folder the config names, since that is where a
    run keeps them, and it is not always the install."""
    cfg = _read_json(d / "config.json") or {}
    # The same default load_config gives an absent output_dir.
    out = Path(cfg.get("output_dir") or (Path.home() / "Downloads" / _provider_name(d)))
    if not out.is_absolute():
        out = d / out
    data = _read_json(out / "progress.json")
    if isinstance(data, dict):
        data = list(data.values())
    return [r for r in (data or []) if isinstance(r, dict)]


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


def _write_config(cfg_path: Path, key: str, value: str, stamp: str) -> bool:
    """Set or clear one key, backed up first and written in one step, so a
    crash part way leaves the old file whole."""
    current = _read_json(cfg_path)
    if not isinstance(current, dict):
        return False
    if (current.get(key) or "") == value:
        return False
    if value:
        current[key] = value
    else:
        current.pop(key, None)
    try:
        bak = cfg_path.parent / "Backups" / ("naming-" + stamp) / cfg_path.name
        bak.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg_path, bak)
        tmp = cfg_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cfg_path)
    except OSError:
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
    names = []
    for r in _newest_saved(_naming_records(d)):
        current = str(r.get("pdf_filename") or "")
        new = current
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


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML.replace("__VERSION__", VERSION)


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperPull</title>
<style>
  :root { color-scheme: light dark; --bg:#0f1115; --panel:#171a21; --fg:#e6e6e6;
          --muted:#98a0ad; --accent:#4c8dff; --line:#262b36; --ok:#3ecf8e; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--fg); display:flex; flex-direction:column; height:100vh; }
  header { padding:18px 22px; border-bottom:1px solid var(--line); }
  header h1 { margin:0; font-size:18px; }
  header h1 .tag { color:var(--muted); font-weight:400; }
  header h1 .ver { color:var(--accent); font-weight:400; font-size:13px; vertical-align:middle; }
  header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
  main { display:grid; grid-template-columns: 320px 1fr; grid-template-rows: minmax(0, 1fr); gap:0; flex:1; min-height:0; }
  footer { padding:8px 22px; border-top:1px solid var(--line); font-size:12px;
           color:var(--muted); display:flex; justify-content:space-between; align-items:center; }
  footer a { color:var(--accent); text-decoration:none; }
  footer a:hover { text-decoration:underline; }
  .setup { flex:1; overflow:auto; padding:32px 22px; }
  .setup > * { max-width:600px; margin-left:auto; margin-right:auto; }
  .setup h2 { font-size:22px; margin:0 0 8px; }
  .setup p.lead { color:var(--muted); margin:0 0 22px; line-height:1.5; }
  .setup label { text-transform:none; letter-spacing:0; font-size:14px;
                 color:var(--fg); margin:16px 0 6px; }
  .stwrap button.nmchip { display:inline-flex; flex-direction:column; align-items:flex-start;
                          line-height:1.25; padding:5px 10px; text-align:left; }
  .nmchip small { color:var(--muted); font-size:11px; }
  .nmchip.nmnone { opacity:.5; }
  #panenm label { text-transform:none; letter-spacing:0; font-size:14px; color:var(--fg); }
  #nmpattern { width:100%; padding:8px 10px; background:var(--panel); color:var(--fg);
               border:1px solid var(--line); border-radius:6px; font-size:14px;
               font-family:ui-monospace,Consolas,monospace; }
  .setup input[type=text] { width:100%; font:inherit; padding:8px 10px;
                            background:var(--panel); color:var(--fg);
                            border:1px solid var(--line); border-radius:6px; }
  .setup .providers { max-height:300px; overflow:auto; border:1px solid var(--line);
                      border-radius:6px; padding:2px 10px; }
  .setup .providers label { display:flex; gap:10px; align-items:flex-start;
                            margin:0; padding:8px 2px; border-bottom:1px solid var(--line);
                            font-size:14px; cursor:pointer; }
  .setup .providers label:last-child { border-bottom:0; }
  .setup .providers input { margin-top:3px; flex:none; }
  .setup .providers .hint { display:block; font-size:12px; margin:1px 0 0; }
  .setup button { font:inherit; padding:8px 18px; }
  .setup button.primary { grid-column:auto; }
  .controls { padding:20px 22px; border-right:1px solid var(--line); overflow:auto; }
  .tabs { display:flex; gap:2px; padding:0 22px; border-bottom:1px solid var(--line); }
  .tabs button { background:none; border:0; border-bottom:2px solid transparent;
                 color:var(--muted); padding:10px 14px; font:inherit; cursor:pointer; }
  .tabs button.on { color:var(--fg); border-bottom-color:var(--accent); }
  .stwrap { flex:1; overflow:auto; padding:16px 22px; }
  .stwrap button { background:var(--panel); color:var(--fg); border:1px solid var(--line);
                   border-radius:6px; padding:6px 12px; font:inherit; cursor:pointer; }
  table.st { border-collapse:collapse; width:100%; font-size:13px; }
  table.st th { text-align:left; color:var(--muted); font-weight:500;
                border-bottom:1px solid var(--line); padding:6px 10px 6px 0; }
  table.st td { padding:6px 10px 6px 0; border-bottom:1px solid var(--line); }
  /* Headers align with their columns. The .num rule used to reach only the
     cells, so "Docs" sat at the left of a column whose numbers sat at the
     right, a screen-width apart on a wide window. Every column except
     Provider shrinks to its content, so labels and values stay together. */
  table.st th.num, table.st td.num { text-align:right; }
  table.st th:not(:first-child), table.st td:not(:first-child) {
    width:1%; white-space:nowrap; padding-left:18px; }
  .pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; }
  .pill.overdue { background:#4a1d1d; color:#ff9a9a; }
  .pill.due { background:#4a3a1d; color:#ffd08a; }
  .pill.current { background:#1d4a35; color:var(--ok); }
  .pill.other { background:var(--line); color:var(--muted); }
  .gapbox { margin-top:18px; border-left:3px solid var(--accent); padding:2px 0 2px 12px; }
  .gapbox h3 { margin:0 0 4px; font-size:14px; }
  .gapbox p { color:var(--muted); font-size:13px; margin:2px 0; }
  label { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.04em;
          color:var(--muted); margin:16px 0 6px; }
  select { width:100%; padding:9px 10px; background:var(--panel); color:var(--fg);
           border:1px solid var(--line); border-radius:8px; font-size:14px; }
  .scope { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .scope input[type=date] { width:100%; padding:8px 10px; background:var(--panel); color:var(--fg);
           border:1px solid var(--line); border-radius:8px; font-size:13px; box-sizing:border-box; }
  .scope input[type=date]:disabled { opacity:.45; }
  .scope .sub { font-size:11px; color:var(--muted); text-transform:none; letter-spacing:0; margin:6px 0 4px; }
  .actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:20px; }
  .actions.more { margin-top:8px; }
  .morelink { font-size:12px; color:var(--muted); margin-top:10px; }
  .morelink a { color:var(--accent); text-decoration:none; }
  .morehint { font-size:12px; color:var(--muted); margin:6px 0 0; }
  button { padding:10px; border:1px solid var(--line); border-radius:8px; cursor:pointer;
           background:var(--panel); color:var(--fg); font-size:14px; }
  button:hover { border-color:var(--accent); }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; grid-column:1/3; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .hint { font-size:12px; color:var(--muted); margin-top:16px; }
  .samplebar { display:none; align-items:center; gap:12px; flex-wrap:wrap;
    padding:8px 20px; font-size:13px; background:#2a2411; color:#ffcf6b;
    border-bottom:1px solid #4a3f1c; }
  .samplebar b { color:#ffe1a3; }
  .samplebar button { font:inherit; font-size:12px; padding:3px 12px; }
  .warn { color:#ffcf6b; }
  .console { background:#0b0d11; margin:0; padding:16px 20px; overflow:auto;
             font:13px/1.55 ui-monospace,Consolas,monospace; white-space:pre-wrap; }
  .status { padding:8px 20px; border-bottom:1px solid var(--line); font-size:13px; color:var(--muted); }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--muted); margin-right:8px; }
  .dot.run { background:var(--accent); animation:pulse 1s infinite; }
  .dot.warn { background:#e6a23c; } .dot.ok { background:var(--ok); } .dot.err { background:#ff5c5c; }
  @keyframes pulse { 50% { opacity:.3; } }
</style>
</head>
<body>
<header>
  <h1>PaperPull <span class="ver">v__VERSION__</span><span class="tag"> &middot; Receipt &amp; Statement Downloader</span></h1>
  <p id="root">control panel</p>
</header>
<div id="samplebar" class="samplebar">
  <span><b>Sample archive.</b> Every document here is invented. Nothing signs
  in and nothing downloads, and your own archive is untouched.</span>
  <button onclick="leaveSample()">Leave the sample</button>
</div>
<section id="setup" class="setup" style="display:none">
  <div id="newuser">
    <h2>Welcome to PaperPull</h2>
    <p class="lead">Two steps. Choose where your downloads will live, then tick
    the providers you have accounts with. A folder is set up for each one, and
    nothing is downloaded until you ask.</p>
    <label>Folder for your downloads</label>
    <input id="newroot" type="text">
    <label>Providers you have accounts with</label>
    <div id="providers" class="providers"></div>
    <div style="margin-top:14px; display:flex; gap:10px; align-items:center;">
      <button class="primary" onclick="createInstalls()">Set up</button>
      <span class="hint" style="margin:0" id="newmsg"></span>
    </div>
  </div>
  <p class="hint" style="margin-top:26px">
    <a href="#" onclick="openSample(); return false;" style="color:var(--accent)">Not ready to sign in to anything? See a sample archive</a><br>
    Invented statements and receipts, so you can try the Status tab and both
    spreadsheets before you point this at a real account. Nothing is
    downloaded and nothing of yours is touched.
  </p>
  <p class="hint" style="margin-top:18px">
    <a href="#" onclick="toggleExisting(); return false;" style="color:var(--accent)">Already have PaperPull downloaders from before?</a>
  </p>
  <div id="existing" style="display:none">
    <p class="hint" style="margin-top:6px">
      Paste the full path of the folder that holds them, the one with
      <i>Chase Statements</i>, <i>Amazon Receipts</i> and so on inside it.
      Nothing is moved or copied. This panel works on what is already there,
      and your existing way of running them keeps working too.
    </p>
    <input id="rootinput" type="text" placeholder="C:\Users\you\Documents\Receipt and Statement Downloader">
    <div style="margin-top:10px; display:flex; gap:10px; align-items:center;">
      <button onclick="saveRoot()">Use this folder</button>
      <span class="hint" style="margin:0" id="rootmsg"></span>
    </div>
  </div>
</section>
<main>
  <div class="controls">
    <label for="app">App <a href="#" id="addlink" onclick="addProvider(); return false;" style="color:var(--accent); font-weight:400; font-size:12px; margin-left:8px;">add a provider</a> <a href="#" id="removelink" onclick="removeProvider(); return false;" style="color:var(--muted); font-weight:400; font-size:12px; margin-left:8px;">remove</a></label>
    <select id="app"></select>
    <label for="account">Account <a href="#" id="addacct" onclick="addAccount(); return false;" style="color:var(--accent); font-weight:400; font-size:12px; margin-left:8px;">add a person</a></label>
    <select id="account"></select>
    <label for="year">Scope</label>
    <select id="year" onchange="onScope()"></select>
    <div class="scope">
      <div><div class="sub">From</div><input id="start" type="date" onchange="onScope()"></div>
      <div><div class="sub">To</div><input id="end" type="date" onchange="onScope()"></div>
    </div>
    <p class="hint" id="scopehint" style="margin-top:8px"></p>
    <div class="actions" id="actions"></div>
    <button id="stoprec" class="primary" style="display:none;margin-top:8px"
            onclick="stopRecording()">Stop recording</button>
    <p class="morelink"><a href="#" id="morelink" onclick="toggleMore(); return false;">more</a></p>
    <div id="morebox" style="display:none">
      <div class="actions more" id="moreactions"></div>
      <p class="morehint"><b>Verify</b> re-checks every saved PDF. <b>Diagnose</b> reads the
         provider's page and writes two files to its Diagnostics folder, downloading nothing.
         The one whose name starts with <b>survey-</b> holds counts and states and no text
         from your account, and that is the one to attach to an issue. The detailed
         file beside it, and its screenshot, carry the page's own words, so
         they stay on this machine unless you decide to send them.</p>
      <p class="morehint"><b>Rename preview</b> shows what this app would call the files you
         already have, and changes nothing. <b>Apply renames</b> then renames them where they
         sit. Nothing is downloaded either way, nothing moves between folders, and only files
         this app downloaded are touched.</p>
    </div>
    <p class="hint">1. <b>Login</b> opens a browser. Sign in yourself and leave it open.<br>
       2. <b>Pilot</b> tests the newest few.<br>
       3. <b>Run All</b> downloads everything you don't already have.</p>
    <p class="hint" style="border-left:3px solid var(--accent); padding-left:10px;">
       ↻ <b>Safe to re-run.</b> Run All and Resume skip any statement or receipt
       you've already downloaded. Nothing is ever fetched twice, even if you
       deleted the PDFs after importing them elsewhere.</p>
    <p class="hint warn" id="venvwarn" style="display:none"></p>
  </div>
  <div style="display:flex; flex-direction:column; min-width:0;">
  <div class="tabs">
    <button id="tabout" class="on" onclick="showTab('out')">Output</button>
    <button id="tabst" onclick="showTab('st')">Status</button>
    <button id="tabxl" onclick="showTab('xl')">Spreadsheet</button>
    <button id="tabnm" onclick="showTab('nm')">File names</button>
  </div>
  <div id="paneout" style="display:flex; flex-direction:column; min-height:0; flex:1;">
    <div class="status"><span class="dot" id="dot"></span><span id="statustext">idle</span></div>
    <pre class="console" id="console"></pre>
    <p class="hint warn" id="failnote" style="display:none;margin:6px 0 0">
       This run wrote a file about what went wrong. It holds counts and states
       and no text from your account. Read it, then attach it to this
       provider&#39;s issue.
       <button id="failreveal" onclick="revealFailure()">Show the file to attach</button></p>
  </div>
  <div id="panest" class="stwrap" style="display:none;">
    <p><button onclick="loadStatus()">Refresh</button>
       <span class="hint" id="stnote"></span></p>
    <div id="stbody">not loaded yet</div>
  </div>
  <div id="panexl" class="stwrap" style="display:none;">
    <p class="hint" style="margin-top:0">Every purchase from a receipt archive, one row
       per item, newest first, with an Orders sheet and a Summary of spend per year.
       Built from what the apps already recorded while downloading, so it takes a
       second and no PDF is opened. Rebuilt from scratch each time. Edit a copy, not
       this file.</p>
    <p><select id="xlprovider" style="width:auto; min-width:220px; display:inline-block; margin-right:8px"></select>
       <span class="hint" id="xlnote"></span></p>
    <p><button class="primary" id="xlbuild" onclick="buildSpreadsheet(false)">Build Excel workbook</button>
       <button onclick="buildSpreadsheet(true)">Build CSV instead</button>
       <button id="xlreveal" onclick="revealSpreadsheet()" style="display:none">Show in folder</button></p>
    <div id="xlbody"></div>
    <h3 style="margin:26px 0 6px; font-size:15px">Statements</h3>
    <p class="hint" style="margin-top:0">The transactions inside your statement PDFs, one row
       each, with a Statements sheet that says whether every statement adds up. Each PDF is
       read once and remembered, so the first build takes a few minutes for a big archive and
       the next takes seconds. Money in is positive, money out is negative, for a bank account
       and a card alike. A statement that does not reconcile is still exported, with the
       difference shown, so you know which rows to doubt.</p>
    <p><select id="txprovider" style="width:auto; min-width:220px; display:inline-block; margin-right:8px"></select>
       <span class="hint" id="txnote"></span></p>
    <p><button class="primary" id="txbuild" onclick="buildTransactions(false)">Build transactions workbook</button>
       <button id="txcsv" onclick="buildTransactions(true)">Build CSV instead</button>
       <button id="txreveal" onclick="revealSpreadsheet()" style="display:none">Show in folder</button></p>
    <pre class="console" id="txlog" style="max-height:220px; display:none"></pre>
  </div>
  <div id="panenm" class="stwrap" style="display:none;">
    <p class="hint" style="margin-top:0">How the files this app downloads are named. Add
       the parts you want, in order. A part marked <b>skip if empty</b> is left out, with
       the separator in front of it, whenever a document does not have it, so no name ends
       in a stray dash. Saving renames nothing. Once you save, the page offers to rename
       the files you already have, preview first.</p>
    <p id="nmunavail" class="hint warn" style="display:none">File naming is not available
       in this install. Update PaperPull to get it.</p>
    <div id="nmbody">
      <p><b id="nmapp"></b> <span class="hint" id="nmkind"></span></p>
      <p><label style="display:inline"><input type="radio" name="nmscope" value="shared" checked
           onchange="nmScope()"> <span id="nmsharedlabel">every app of this kind</span></label>
         &nbsp; <label style="display:inline"><input type="radio" name="nmscope" value="own"
           onchange="nmScope()"> <span id="nmownlabel">only this app</span></label></p>
      <p style="margin:0 0 6px">
        <span class="hint">Separator</span>
        <select id="nmsep" style="width:auto; display:inline-block">
          <option value=" ">space</option><option value=" - ">&nbsp;-&nbsp;</option>
          <option value=" -- ">&nbsp;--&nbsp;</option><option value="_">_</option>
          <option value="">none</option></select>
        <span class="hint" style="margin-left:10px">Date as</span>
        <select id="nmdate" style="width:auto; display:inline-block">
          <option>yyyy-mm-dd</option><option>yyyymmdd</option><option>mm-dd-yyyy</option>
          <option>dd mmm yyyy</option><option>mmmm d yyyy</option></select>
        <label style="display:inline; margin-left:10px"><input type="checkbox" id="nmskip" checked>
          skip if empty</label></p>
      <p class="hint" style="margin:0 0 6px">Click a part to add it where the cursor is.
         Under each is how many of the files you already have from this app carry it. A
         part on none of them would always come out empty, so it is shown faded.</p>
      <div id="nmfields" style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px"></div>
      <input id="nmpattern" type="text" spellcheck="false" autocomplete="off"
             oninput="nmChanged()" placeholder="an empty box means the default">
      <p class="hint warn" id="nmproblem" style="display:none; margin:6px 0 0"></p>
      <div id="nmpreview" style="margin:10px 0"></div>
      <p><button class="primary" onclick="nmSave()">Save</button>
         <button onclick="nmDefault()">Back to the default</button>
         <button onclick="nmClear()">Start empty</button>
         <span class="hint" id="nmnote" style="margin-left:8px"></span></p>
      <div id="nmoffer" style="display:none; border-left:3px solid var(--accent);
           padding:2px 0 2px 12px; margin:6px 0 14px">
        <p style="margin:4px 0"><b>Rename the files you already have to match?</b></p>
        <p class="hint" style="margin:4px 0" id="nmofferapps"></p>
        <p class="hint" style="margin:4px 0">Preview first. It lists every file that would
           change, in the Output tab, and changes nothing. Renaming then does exactly that.
           Nothing is downloaded or deleted, nothing moves between folders, and each app's
           index follows its files, so nothing is ever downloaded twice. The preview can
           also list files an app would now summarize better than when it saved them.</p>
        <p style="margin:4px 0"><button id="nmprevbtn" onclick="nmRename(false)">Preview renames</button>
           <button id="nmapplybtn" class="primary" onclick="nmRename(true)" disabled>Rename them</button>
           <button onclick="nmOffer(null)">Not now</button>
           <span class="hint" id="nmofferstate" style="margin-left:8px"></span></p>
      </div>
      <p class="hint">Written by hand, <code>{date:yyyymmdd}[ - {provider}][ -- {number|kind}]</code>
         is the date, then the provider, then the order number, or the kind when there is
         no number. Square brackets make a part that is skipped when empty, and
         <code>{a|b}</code> takes the first that has a value.</p>
    </div>
  </div>
  </div>
</main>
<footer>
  <span>PaperPull v__VERSION__ &middot; read-only, runs locally</span>
  <span>Free, and it costs money to make. Show your appreciation: <a href="https://ko-fi.com/rheeloaded" target="_blank" rel="noopener">donate on Ko-fi</a> or <a href="https://github.com/rheeloaded/paperpull#support" target="_blank" rel="noopener">buy the Store edition</a></span>
</footer>
<script>
async function saveRoot() {
  const root = $('rootinput').value.trim();
  $('rootmsg').textContent = '';
  if (!root) { $('rootmsg').textContent = 'paste the folder path first'; return; }
  let r;
  try {
    r = await fetch('/api/root', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root})});
  } catch (e) { $('rootmsg').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('rootmsg').textContent = d.detail || 'that did not work'; return; }
  if (d.apps === 0) {
    $('rootmsg').textContent = 'saved, but no downloaders were found there yet';
  } else {
    $('rootmsg').textContent = 'found ' + d.apps + ' downloader' + (d.apps === 1 ? '' : 's');
  }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
}

function changeRoot() {
  $('setup').style.display = 'block';
  $('rootinput').value = META.apps_root || '';
  $('rootinput').focus();
}

async function setSample(on) {
  const r = await fetch('/api/sample', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({on: on})});
  if (!r.ok) { alert(((await r.json()).detail) || 'could not switch'); return; }
  STATUS_LOADED = false; XL_LOADED = false;
  showTab('out');
  await load();
}
const openSample = () => setSample(true);
const leaveSample = () => setSample(false);

let PROVIDERS = null;

function showSetup(on) {
  $('setup').style.display = on ? 'block' : 'none';
  document.querySelector('main').style.display = on ? 'none' : '';
}

function toggleExisting() {
  const e = $('existing');
  e.style.display = e.style.display === 'none' ? 'block' : 'none';
  if (e.style.display === 'block') $('rootinput').focus();
}

async function loadProviders(onlyMissing) {
  const d = await (await fetch('/api/providers')).json();
  PROVIDERS = d;
  if (!$('newroot').value) $('newroot').value = d.suggested_root || '';
  const box = $('providers');
  if (!d.templates) { box.textContent = 'No provider templates are available in this copy.'; return; }
  const rows = d.providers.filter(p => !onlyMissing || !p.installed);
  if (!rows.length) { box.textContent = 'Every provider is already set up.'; return; }
  box.innerHTML = rows.map(p =>
    '<label><input type="checkbox" value="' + esc(p.slug) + '"' +
    (p.installed ? ' disabled checked' : '') + '>' +
    '<span><b>' + esc(p.provider) + '</b>' +
    (p.documents ? '<span class="hint">' + esc(p.documents) + '</span>' : '') +
    (p.installed ? '<span class="hint">already set up</span>' : '') +
    '</span></label>').join('');
}

async function createInstalls() {
  const root = $('newroot').value.trim();
  const picked = [...document.querySelectorAll('#providers input:checked:not(:disabled)')].map(i => i.value);
  $('newmsg').textContent = '';
  if (!root) { $('newmsg').textContent = 'choose a folder first'; return; }
  if (!picked.length) { $('newmsg').textContent = 'tick at least one provider'; return; }
  // Asked here because an app started from this panel has no stdin to
  // ask on, and without it redaction cannot take this person's name out
  // of a survey or a recording.
  const owner = (prompt(
    'Whose documents are these?\n\n' +
    'The name on the account, as the provider writes it. It never leaves ' +
    'this computer. It is what lets PaperPull remove your name from a file ' +
    'before you send it to anyone.\n\n' +
    'Leave it blank to skip.') || '').trim();
  $('newmsg').textContent = 'setting up...';
  let r;
  try {
    r = await fetch('/api/create', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({root, providers: picked, owner})});
  } catch (e) { $('newmsg').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('newmsg').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
  const n = d.created.length;
  $('console').textContent =
    'Set up ' + n + ' provider' + (n === 1 ? '' : 's') + ' under\n' + d.root +
    (d.owner ? '\nDocuments will be filed under ' + d.owner + '.' :
     '\nNo name was given, so nothing can be removed from a file for you.') +
    '\n\nNext: pick one above, click Login, and sign in when the browser opens.';
}

async function addProvider() {
  showSetup(true);
  $('newuser').style.display = 'block';
  $('existing').style.display = 'none';
  $('newroot').value = META.apps_root || '';
  await loadProviders(true);
}

async function addAccount() {
  const name = $('app').value;
  if (!name) return;
  const label = (prompt(
    'A second person on "' + name + '".\n\n' +
    'They get their own folder beside this one, their own sign-in window and their own ' +
    'download history, so nothing mixes with the first account.\n\n' +
    'Short label for the account (letters, digits, - or _), for example spouse or alex:') || '').trim();
  if (!label) return;
  const owner = (prompt('Their name, as it should appear on the documents (optional):') || '').trim();
  let r;
  try {
    r = await fetch('/api/account', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app: name, label, owner})});
  } catch (e) { $('console').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('console').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false;
  await load();
  $('app').value = name; onApp();
  $('account').value = d.account;
  $('console').textContent =
    'Added "' + d.account + '" to ' + name + (d.owner ? ' for ' + d.owner : '') + '.\n\n' +
    'Downloads go to ' + d.output_dir + '\n' +
    (d.cdp_url ? 'Sign-in browser on ' + d.cdp_url + '\n' : '') +
    '\nThe Account box above is set to it. Click Login, sign in as that person in the window ' +
    'that opens, then Pilot.';
}

async function removeProvider() {
  const name = $('app').value;
  if (!name) return;
  const ok = confirm(
    'Remove "' + name + '" from PaperPull?\n\n' +
    'Nothing is deleted. Its folder is moved into a "Removed" folder beside the ' +
    'others, with its PDFs, download history and signed-in browser profile all ' +
    'still inside. Delete that folder yourself whenever you are sure.\n\n' +
    'It will no longer appear in this list.');
  if (!ok) return;
  let r;
  try {
    r = await fetch('/api/remove', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app: name})});
  } catch (e) { $('console').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('console').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
  const kept = [];
  if (d.pdfs) kept.push(d.pdfs + ' PDF' + (d.pdfs === 1 ? '' : 's'));
  if (d.history) kept.push('a history of ' + d.history + ' document' + (d.history === 1 ? '' : 's'));
  if (d.profile) kept.push('a signed-in browser profile');
  $('console').textContent =
    'Removed "' + d.app + '" from the list.\n\nIts folder was moved to\n' + d.moved_to +
    (kept.length ? '\n\nStill inside it: ' + kept.join(', ') + '.' : '') +
    '\n\nNothing was deleted. Delete that folder yourself when you are sure you no longer ' +
    'need what is in it. Until then, moving it back restores the provider.';
}

let STATUS_LOADED = false;

// Which providers get a spreadsheet. Receipt archives have line items, so
// they are listed, each with its second-account folders folded in. Statement
// archives are not offered one, since they have documents, not purchases.
let XL_LOADED = false;
async function loadExportProviders() {
  const sel = $('xlprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  XL_LOADED = true;
  const provs = (d.providers || []);
  sel.append(new Option('All providers', ''));
  for (const p of provs) sel.append(new Option(p.provider, p.provider));
  const names = provs.map(p => p.provider).join(', ');
  $('xlnote').textContent = provs.length
    ? 'Receipt archives found, ' + names + '. Statement archives have no line items and are not offered.'
    : 'No receipt archive found under this folder. Amazon, Target, Walmart and Gap write one after a run.';
  $('xlbuild').disabled = !provs.length;
}
async function loadTransactionProviders() {
  const sel = $('txprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/transactions/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  const provs = d.providers || [];
  sel.append(new Option('All statement archives', ''));
  for (const p of provs) sel.append(new Option(p.provider + ' (' + p.pdfs + ' PDFs)', p.provider));
  $('txnote').textContent = provs.length
    ? 'Archives with PDFs on disk, ' + provs.map(p => p.provider).join(', ') + '.'
    : (d.reason || 'No statement PDFs on disk under this folder.');
  $('txbuild').disabled = !provs.length; $('txcsv').disabled = !provs.length;
}
let txes = null;
function buildTransactions(asCsv) {
  if (txes) txes.close();
  const log = $('txlog'); log.textContent = ''; log.style.display = 'block';
  $('txreveal').style.display = 'none';
  $('txbuild').disabled = true; $('txcsv').disabled = true;
  const q = new URLSearchParams({provider: $('txprovider').value, csv: asCsv ? '1' : ''});
  txes = new EventSource('/api/export/transactions?' + q.toString());
  txes.onmessage = e => { log.textContent += e.data + '\n'; log.scrollTop = log.scrollHeight; };
  txes.addEventListener('result', e => { $('txreveal').style.display = ''; });
  txes.addEventListener('done', e => {
    txes.close(); txes = null;
    $('txbuild').disabled = false; $('txcsv').disabled = false;
    if (e.data !== '0') log.textContent += '(ended with code ' + e.data + ')\n';
  });
  txes.onerror = () => { if (txes) { txes.close(); txes = null; } $('txbuild').disabled = false; $('txcsv').disabled = false; };
}
async function buildSpreadsheet(asCsv) {
  $('xlbody').textContent = 'building...';
  $('xlreveal').style.display = 'none';
  let d;
  const provider = $('xlprovider').value;
  try {
    d = await (await fetch('/api/export', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({csv: asCsv, provider})})).json();
  } catch (e) { $('xlbody').textContent = 'could not reach the control panel'; return; }
  if (!d.ok) { $('xlbody').textContent = d.reason || 'the export failed'; return; }
  let html = '<table class="st"><tr><th>Provider</th><th class="num">Line items</th></tr>';
  for (const [p, n] of Object.entries(d.providers).sort()) {
    html += '<tr><td>' + esc(p) + '</td><td class="num">' + n + '</td></tr>';
  }
  html += '</table>';
  html += '<p style="margin-top:14px"><b>' + d.purchases + ' purchases</b> across ' + d.orders + ' orders.</p>';
  html += '<p class="hint">Wrote <code>' + esc(d.path) + '</code></p>';
  if (d.openpyxl_missing) html += '<p class="hint warn">openpyxl is not installed here, so this is a .csv. Run <code>pip install openpyxl</code> in the panel\'s environment for an .xlsx.</p>';
  $('xlbody').innerHTML = html;
  $('xlreveal').style.display = '';
}
async function revealSpreadsheet() {
  try { await fetch('/api/export/reveal', {method: 'POST'}); } catch (e) {}
}
function showTab(which) {
  const isSt = which === 'st', isXl = which === 'xl', isNm = which === 'nm';
  const other = isSt || isXl || isNm;
  $('paneout').style.display = other ? 'none' : 'flex';
  $('panest').style.display  = isSt ? 'block' : 'none';
  $('panexl').style.display  = isXl ? 'block' : 'none';
  $('panenm').style.display  = isNm ? 'block' : 'none';
  $('tabout').className = other ? '' : 'on';
  $('tabst').className  = isSt ? 'on' : '';
  $('tabxl').className  = isXl ? 'on' : '';
  $('tabnm').className  = isNm ? 'on' : '';
  if (isSt && !STATUS_LOADED) loadStatus();
  if (isXl && !XL_LOADED) { loadExportProviders(); loadTransactionProviders(); }
  if (isNm) loadNaming();
}

// -- file names (#50) --------------------------------------------------------
let NM = null, NM_TIMER = null;
function nmScopeValue() { return document.querySelector('input[name=nmscope]:checked').value; }
async function loadNaming() {
  const app = $('app').value;
  if (!app) return;
  let d;
  try { d = await (await fetch('/api/naming?app=' + encodeURIComponent(app))).json(); }
  catch (e) { return; }
  $('nmunavail').style.display = d.available ? 'none' : 'block';
  $('nmbody').style.display = d.available ? 'block' : 'none';
  if (!d.available) return;
  NM = d;
  const kind = d.kind === 'receipts' ? 'receipts' : 'statements';
  $('nmapp').textContent = d.provider;
  $('nmkind').textContent = 'a ' + kind + ' app';
  $('nmsharedlabel').textContent = 'every ' + kind + ' app';
  $('nmownlabel').textContent = 'only ' + d.provider;
  document.querySelector('input[name=nmscope][value=' + (d.own ? 'own' : 'shared') + ']').checked = true;
  $('nmpattern').value = d.own || d.shared || d.default;
  $('nmnote').textContent = '';
  const box = $('nmfields'); box.innerHTML = '';
  const n = d.fill.records;
  const receipts = d.kind === 'receipts';
  for (const f of d.fields) {
    // An order total, a store and online or in store are things a receipt
    // has. On a statements app they would only ever come out empty.
    if (!receipts && (f === 'total' || f === 'store' || f === 'type')) continue;
    const b = document.createElement('button');
    b.className = 'nmchip';
    const got = d.fill.filled[f] || 0;
    const name = document.createElement('span');
    name.textContent = nmLabel(f, receipts);
    const how = document.createElement('small');
    how.textContent = nmHowMany(f, got, n);
    b.append(name, how);
    b.title = 'Adds {' + f + '} to the pattern';
    if (n && f !== 'owner' && f !== 'part' && !got) b.classList.add('nmnone');
    b.onclick = () => nmInsert(f);
    box.append(b);
  }
  nmChanged();
}
function nmLabel(f, receipts) {
  return ({date: 'Date', year: 'Year', month: 'Month', provider: 'Provider',
           owner: 'Account holder', kind: 'Document type', summary: 'Description',
           number: receipts ? 'Order number' : 'Document number', account: 'Account',
           total: 'Order total', store: 'Store', type: 'Online or in store',
           part: 'Part, like 1 of 3'})[f] || f;
}
// How many of the files already downloaded have this part, in words, so
// nobody builds a name on something this provider never gives.
function nmHowMany(f, got, n) {
  if (f === 'owner') return 'from your settings';
  if (f === 'part') return 'only on a split order';
  if (!n) return '';
  if (got >= n) return 'on every file';
  if (got === 0) return 'on none of your files';
  const pct = Math.round(100 * got / n);
  return pct >= 90 ? 'on almost every file' : 'on ' + got + ' of ' + n + ' files';
}
function nmScope() {
  if (!NM) return;
  $('nmpattern').value = (nmScopeValue() === 'own' ? NM.own : '') || NM.shared || NM.default;
  nmChanged();
}
function nmInsert(field) {
  const inp = $('nmpattern');
  const text = inp.value;
  const at = inp.selectionStart == null ? text.length : inp.selectionStart;
  const sep = at > 0 ? $('nmsep').value : '';
  const f = field === 'date' ? '{date:' + $('nmdate').value + '}' : '{' + field + '}';
  // A date and a provider are always there, so they are never optional.
  const skip = $('nmskip').checked && field !== 'date' && field !== 'provider';
  const part = skip ? '[' + sep + f + ']' : sep + f;
  inp.value = text.slice(0, at) + part + text.slice(at);
  inp.focus();
  inp.selectionStart = inp.selectionEnd = at + part.length;
  nmChanged();
}
function nmChanged() {
  clearTimeout(NM_TIMER);
  NM_TIMER = setTimeout(nmPreview, 250);
}
async function nmPreview() {
  const pattern = $('nmpattern').value;
  let d;
  try {
    d = await (await fetch('/api/naming/preview', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('app').value, pattern})})).json();
  } catch (e) { return; }
  const pr = $('nmproblem');
  pr.style.display = d.problem ? 'block' : 'none';
  pr.textContent = d.problem || '';
  const box = $('nmpreview'); box.innerHTML = '';
  if (!d.names || !d.names.length) {
    box.innerHTML = '<p class="hint">No files from this app yet, so there is nothing to preview.</p>';
    return;
  }
  const t = document.createElement('table'); t.className = 'st';
  t.innerHTML = '<thead><tr><th>Your newest files now</th><th>With this pattern</th></tr></thead>';
  const tb = document.createElement('tbody');
  for (const n of d.names) {
    const tr = document.createElement('tr');
    const a = document.createElement('td'); a.textContent = n.current;
    const b = document.createElement('td'); b.textContent = n.new;
    if (n.new !== n.current) b.style.fontWeight = '600';
    tr.append(a, b); tb.append(tr);
  }
  t.append(tb); box.append(t);
}
async function nmSave() {
  let r, d;
  try {
    r = await fetch('/api/naming/save', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('app').value, scope: nmScopeValue(),
                            pattern: $('nmpattern').value})});
    d = await r.json();
  } catch (e) { $('nmnote').textContent = 'could not reach the control panel'; return; }
  if (!r.ok) { $('nmnote').textContent = d.detail || 'not saved'; return; }
  await loadNaming();
  $('nmnote').textContent = d.written ? 'Saved. New downloads use it.' : 'Nothing to change.';
  if (d.changed && d.changed.length) nmOffer(d.changed);
}

// The offer to bring files already on disk into line, one app and one
// account at a time, through the app's own --rename. Renaming is never
// offered until a preview of the same apps has finished cleanly.
let NM_OFFER = null, NM_PREVIEWED = false;
function nmOffer(apps) {
  NM_OFFER = apps; NM_PREVIEWED = false;
  $('nmoffer').style.display = apps ? 'block' : 'none';
  if (!apps) return;
  $('nmofferapps').textContent = (apps.length === 1 ? 'In ' : 'In these ' + apps.length + ' apps, ') +
    apps.join(', ') + ', every account.';
  $('nmapplybtn').disabled = true;
  $('nmprevbtn').disabled = false;
  $('nmofferstate').textContent = '';
  $('nmoffer').scrollIntoView({block: 'nearest'});
}
function nmPairs() {
  const pairs = [];
  for (const a of NM_OFFER || []) {
    const m = META.apps[a];
    if (!m) continue;
    for (const acc of (m.accounts && m.accounts.length ? m.accounts : ['primary'])) pairs.push([a, acc]);
  }
  return pairs;
}
function nmRename(apply) {
  const pairs = nmPairs();
  if (!pairs.length) return;
  if (apply && !NM_PREVIEWED) return;
  if (apply && !confirm('Rename the files the preview listed, in ' + NM_OFFER.length +
      (NM_OFFER.length === 1 ? ' app?' : ' apps?') +
      ' Nothing is downloaded or deleted, and each app\'s index follows its files.')) return;
  const action = apply ? 'rename_apply' : 'rename';
  showTab('out');
  $('console').textContent = '';
  let i = 0;
  const next = (code) => {
    if (code !== undefined && code !== '0') {
      $('nmofferstate').textContent = 'Stopped at ' + pairs[i - 1].join(', ') +
        ', which did not finish. Its output says why.';
      return;
    }
    if (i >= pairs.length) {
      if (apply) {
        $('nmofferstate').textContent = 'Renamed. The Output tab lists each file.';
        $('nmapplybtn').disabled = true; $('nmprevbtn').disabled = true;
        loadNaming();
      } else {
        NM_PREVIEWED = true;
        $('nmapplybtn').disabled = false;
        $('console').textContent += '\n== That is the whole preview. Nothing has been changed. ' +
          'To rename these files, go back to File names and press Rename them. ==\n';
        $('console').scrollTop = $('console').scrollHeight;
        $('nmofferstate').textContent = 'Preview done. Read it in the Output tab, then rename here.';
      }
      return;
    }
    const [app, account] = pairs[i++];
    $('console').textContent += (i > 1 ? '\n' : '') + '== ' + app +
      (account === 'primary' ? '' : ', ' + account) + ' ==\n';
    run(action, {app, account, append: true, onDone: next});
  };
  $('nmofferstate').textContent = apply ? 'Renaming...' : 'Previewing...';
  next();
}
function nmDefault() { $('nmpattern').value = NM ? NM.default : ''; nmChanged(); }
function nmClear() { $('nmpattern').value = ''; $('nmpattern').focus(); nmChanged(); }

function pillClass(s) {
  if (s === 'OVERDUE') return 'overdue';
  if (s === 'due') return 'due';
  if (s === 'current') return 'current';
  return 'other';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadStatus() {
  $('stbody').textContent = 'scanning...';
  $('stnote').textContent = '';
  let d;
  try { d = await (await fetch('/api/status')).json(); }
  catch (e) { $('stbody').textContent = 'could not reach the control panel'; return; }
  STATUS_LOADED = true;
  if (!d.available) { $('stbody').textContent = d.reason || 'status is unavailable'; return; }
  if (!d.rows.length) { $('stbody').textContent = 'no archives found under ' + d.root; return; }
  const body = d.rows.map(r =>
    '<tr><td>' + esc(r.provider || r.folder) + '</td>' +
    '<td class="num">' + (r.documents == null ? '' : r.documents) + '</td>' +
    '<td>' + esc(r.newest || '') + '</td>' +
    '<td class="num">' + (r.age_days == null ? '' : r.age_days + ' d') + '</td>' +
    '<td>' + esc(r.cadence || '') + '</td>' +
    '<td><span class="pill ' + pillClass(r.label) + '">' + esc(r.label) + '</span></td></tr>'
  ).join('');
  let html = '<table class="st"><thead><tr><th>Provider</th><th class="num">Docs</th>' +
    '<th>Newest</th><th class="num">Age</th><th>Every</th><th>Status</th></tr></thead><tbody>' +
    body + '</tbody></table>';
  if (d.gaps.length) {
    html += '<div class="gapbox"><h3>Possible gaps</h3>' +
      '<p>A run that looks current can still be missing periods in the middle.</p>';
    for (const g of d.gaps) {
      html += '<p style="margin-top:8px"><b>' + esc(g.provider) + '</b></p>';
      for (const w of g.windows) {
        const who = w.count > 1
          ? (w.count + ' series, including ' + (w.labels[0] || ''))
          : (w.labels[0] || '');
        html += '<p>' + esc(w.after) + ' to ' + esc(w.before) + ' &middot; ' +
                esc(String(w.missing)) + ' missing &middot; ' + esc(who) + '</p>';
      }
    }
    html += '</div>';
  }
  $('stbody').innerHTML = html;
  $('stnote').textContent = 'scanned ' + d.root;
}

let META = null, es = null;
const $ = id => document.getElementById(id);

async function load() {
  META = await (await fetch('/api/apps')).json();
  const inSample = META.root_source === 'sample';
  $('samplebar').style.display = inSample ? 'flex' : 'none';
  $('root').innerHTML = 'apps root: ' + esc(META.apps_root) +
    (inSample ? ' <span class="hint">(the sample)</span>'
     : (META.root_source === 'environment' ? ' <span class="hint">(from APPS_ROOT)</span>'
        : ' <a href="#" onclick="changeRoot(); return false;" style="color:var(--accent)">change</a>')
       // Reachable with an archive already open, not just from the welcome
       // screen, or the only people who could ever see it are new ones.
       + ' <a href="#" onclick="openSample(); return false;" style="color:var(--muted)">see the sample</a>');
  const fresh = Object.keys(META.refreshed || {});
  if (fresh.length) {
    $('root').innerHTML += '<br><span class="hint">updated to this version\'s code: ' +
      esc(fresh.join(', ')) + ' (the old files are in each folder\'s Backups)</span>';
  }
  const appSel = $('app');
  appSel.innerHTML = '';
  const keys = Object.keys(META.apps);
  if (!keys.length) {
    showSetup(true);
    $('newuser').style.display = 'block';
    $('existing').style.display = 'none';
    $('addlink').style.display = 'none';
    $('removelink').style.display = 'none';
    loadProviders(false);
    if (META.root_source !== 'environment') $('newroot').focus();
    return;
  }
  showSetup(false);
  // Nothing in the sample can be added to, renamed or removed, so the links
  // that would try are not offered.
  $('addlink').style.display = inSample ? 'none' : '';
  $('removelink').style.display = inSample ? 'none' : '';
  $('addacct').style.display = inSample ? 'none' : '';
  for (const k of keys) appSel.append(new Option(META.apps[k].name, k));
  appSel.onchange = onApp;
  fillScope();
  const acts = $('actions'); acts.innerHTML = '';
  const more = $('moreactions'); more.innerHTML = '';
  const tucked = new Set(META.more_actions || []);
  for (const [k, label] of Object.entries(META.actions)) {
    const b = document.createElement('button');
    b.textContent = label; b.className = (k === 'all') ? 'primary' : '';
    b.onclick = () => run(k);
    (tucked.has(k) ? more : acts).append(b);
  }
  let open = false;
  try { open = localStorage.getItem('moreactions') === '1'; } catch (e) {}
  showMore(open);
  onApp();
}
// The rarely wanted actions sit behind one link. Open or closed is
// remembered in this browser only, like the scope.
function showMore(on) {
  $('morebox').style.display = on ? 'block' : 'none';
  $('morelink').textContent = on ? 'fewer' : 'more';
  try { localStorage.setItem('moreactions', on ? '1' : '0'); } catch (e) {}
}
function toggleMore() { showMore($('morebox').style.display === 'none'); }
function onApp() {
  const m = META.apps[$('app').value];
  if ($('panenm').style.display === 'block') loadNaming();
  const accSel = $('account'); accSel.innerHTML = '';
  for (const a of m.accounts) accSel.append(new Option(a, a));
  const warn = $('venvwarn');
  if (m.needs_setup) { warn.style.display='block';
    warn.textContent = '⚠ No .venv in this app yet. Run setup.bat there first, or output may show import errors.'; }
  else warn.style.display='none';
}
function setStatus(cls, text) { $('dot').className = 'dot ' + cls; $('statustext').textContent = text; }
// Scope. "All years" is the default and walks everything, which is what keeps
// each archive's discovery complete for the Status tab. One year, or a date
// range, makes the run skip the years outside it on sites with a year picker.
// The choice is remembered in this browser only.
function fillScope() {
  const sel = $('year'); sel.innerHTML = '';
  sel.append(new Option('All years (default)', ''));
  const now = new Date().getFullYear();
  for (let y = now; y >= now - 15; y--) sel.append(new Option(String(y), String(y)));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('scope') || '{}'); } catch (e) {}
  sel.value = saved.year || '';
  if (sel.value !== (saved.year || '')) sel.value = '';
  $('start').value = saved.start || '';
  $('end').value = saved.end || '';
  onScope();
}
function scopeValues() {
  return { year: $('year').value, start: $('start').value, end: $('end').value };
}
function onScope() {
  const s = scopeValues();
  const oneYear = s.year !== '';
  $('start').disabled = oneYear; $('end').disabled = oneYear;
  let text;
  if (oneYear) text = `Only ${s.year}. Years outside it are skipped where the site has a year picker.`;
  else if (s.start || s.end) text = `${s.start || 'the beginning'} to ${s.end || 'today'}. Years outside that are skipped where the site has a year picker.`;
  else text = 'Every year. Slower on sites with a year picker, and the only way the Status tab sees the whole archive.';
  $('scopehint').textContent = text;
  try { localStorage.setItem('scope', JSON.stringify(s)); } catch (e) {}
}
// opts is for a run the page starts for itself rather than from a button,
// the File names page's renames. It names the app and account, leaves the
// Scope out, adds to the console instead of clearing it, and is told when
// the run ends.
function run(action, opts) {
  opts = opts || {};
  if (es) es.close();
  const app = opts.app || $('app').value, account = opts.account || $('account').value;
  const s = opts.app ? {year: '', start: '', end: ''} : scopeValues();
  if (s.year === '' && s.start && s.end && s.start > s.end) {
    setStatus('err', 'the From date is after the To date'); return;
  }
  const q = new URLSearchParams({ app, account, action });
  if (s.year) q.set('year', s.year); else { if (s.start) q.set('start', s.start); if (s.end) q.set('end', s.end); }
  if (!opts.append) $('console').textContent = '';
  $('failnote').style.display = 'none';
  const scoped = s.year ? ` (${s.year})` : (s.start || s.end) ? ` (${s.start || '…'} to ${s.end || '…'})` : '';
  setStatus('run', `running ${action} on ${app} / ${account}${scoped}`);
  // Only the buttons this run locked are unlocked at the end. The Spreadsheet
  // tab's build buttons stay disabled when there is nothing to build from.
  document.querySelectorAll('button:not(#tabout):not(#tabst):not(#tabxl):not(#tabnm):not(#stoprec):not(:disabled)')
    .forEach(b => { b.disabled = true; b.dataset.runlock = '1'; });
  // A recording waits for the person, so it needs a way to say when. The
  // app this run belongs to is remembered here rather than read back off
  // the App list when Stop is pressed, because the App list is not locked
  // during a run and a recording stopped against the wrong provider would
  // never stop at all.
  recordingApp = (action === 'record') ? app : null;
  $('stoprec').style.display = recordingApp ? 'block' : 'none';
  es = new EventSource(`/api/run?${q.toString()}`);
  const con = $('console');
  let result = null;
  es.addEventListener('result', e => { result = JSON.parse(e.data); });
  es.onmessage = e => { con.textContent += e.data + '\n'; con.scrollTop = con.scrollHeight; };
  es.addEventListener('done', e => {
    const code = e.data;
    if (code !== '0') {
      setStatus('err', code === '130' ? 'interrupted, progress saved' : `exited (code ${code}), check output`);
    } else if (result && result.stopped) {
      setStatus('warn', 'stopped before finishing, see the output, then press Resume');
    } else if (result && result.attention) {
      const details = [];
      if (result.wrong_document) details.push(`${result.wrong_document} refused as the wrong document`);
      if (result.manual_review) details.push(`${result.manual_review} need review`);
      if (result.failed) details.push(`${result.failed} failed`);
      if (result.validation_failures) details.push(`${result.validation_failures} PDF validation failures`);
      setStatus('warn', `finished, needs attention (${details.join(', ')})`);
    } else if (result) {
      setStatus('ok', 'finished, no issues reported');
    } else if (META && META.root_source === 'sample') {
      setStatus('ok', 'nothing to run in the sample');
    } else {
      setStatus('warn', 'finished, check output (no run summary)');
    }
    $('stoprec').style.display = 'none';
    recordingApp = null;
    unlockButtons();
    es.close(); es = null;
    if (code !== '0' || (result && result.attention)) checkFailure(app);
    if (opts.onDone) opts.onDone(code);
  });
  es.onerror = () => { if (es) { setStatus('err','connection lost'); $('stoprec').style.display = 'none'; recordingApp = null; unlockButtons(); es.close(); es=null; if (opts.onDone) opts.onDone('lost'); } };
}
let failureApp = null;
async function checkFailure(app) {
  try {
    const r = await fetch(`/api/failure/latest?app=${encodeURIComponent(app)}`);
    const d = await r.json();
    if (d.found) { failureApp = app; $('failnote').style.display = ''; }
  } catch (e) {}
}
async function revealFailure() {
  if (!failureApp) return;
  try {
    await fetch('/api/failure/reveal', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: failureApp }) });
  } catch (e) {}
}
let recordingApp = null;
async function stopRecording() {
  if (!recordingApp) return;
  const b = $('stoprec');
  b.disabled = true; b.textContent = 'Stopping...';
  try {
    await fetch('/api/record/stop', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: recordingApp }) });
  } catch (e) {}
  b.disabled = false; b.textContent = 'Stop recording';
}
function unlockButtons() {
  document.querySelectorAll('button[data-runlock]').forEach(b => { b.disabled = false; delete b.dataset.runlock; });
}
load();
</script>
</body>
</html>
"""
