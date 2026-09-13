r"""Receipt & Statement Downloaders - local control panel.

A tiny FastAPI app that discovers the downloader apps, lists their accounts,
and runs an action (Login / Discover / Pilot / Run All / Resume / Verify),
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
import sys
from pathlib import Path
from urllib.parse import urlsplit

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
    upgrade that replaces the program does not lose the choice."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "PaperPull" / "settings.json"
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
    env = os.environ.get("APPS_ROOT")
    if env:
        return Path(env).expanduser()
    saved = _read_settings().get("apps_root")
    if saved:
        return Path(saved).expanduser()
    return _DEFAULT_ROOT


def root_source() -> str:
    if os.environ.get("APPS_ROOT"):
        return "environment"
    if _read_settings().get("apps_root"):
        return "settings"
    return "default"


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

# action -> argparse flags. run_all / resume get --yes so they don't block on a
# confirmation prompt. Login is resolved per-app (open-browser vs login).
ACTIONS = {
    "login":    {"label": "Login",    "flags": ["__LOGIN__"]},
    "discover": {"label": "Discover", "flags": ["--discover"]},
    "pilot":    {"label": "Pilot",    "flags": ["--pilot"]},
    "all":      {"label": "Run All",  "flags": ["--all", "--yes"]},
    "resume":   {"label": "Resume",   "flags": ["--resume", "--yes"]},
    "verify":   {"label": "Verify",   "flags": ["--verify"]},
}
ENTRY_RE = re.compile(r".*_(receipts|docs)\.py$")

app = FastAPI(title="PaperPull")

# The panel runs the apps' commands, so its API must only answer requests that
# originate from the panel page itself (served on localhost). A CSRF attempt
# driven by another website carries an Origin/Referer whose host is that site;
# same-origin requests from the panel carry a localhost host or no such header
# at all. There is no CORS middleware, so cross-origin JS can't read responses
# either - this closes the remaining "trigger a run" vector.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", ""}


def _same_origin_only(request: Request) -> None:
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        host = (urlsplit(value).hostname or "").lower()
        if host not in _LOCAL_HOSTS:
            raise HTTPException(403, "cross-origin request refused")


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
    venv = _venv_python(app_dir)
    return str(venv) if venv else sys.executable


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
        }
    return apps


@app.get("/api/apps", dependencies=[Depends(_same_origin_only)])
def api_apps():
    apps = discover_apps()
    return {"apps_root": str(apps_root()), "root_source": root_source(), "actions": {k: v["label"] for k, v in ACTIONS.items()},
            "apps": apps}


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



@app.get("/api/root", dependencies=[Depends(_same_origin_only)])
def api_root_get():
    root = apps_root()
    return {"root": str(root), "exists": root.is_dir(),
            "apps": _looks_like_installs(root), "source": root_source(),
            "settings_file": str(_settings_path())}


@app.post("/api/root", dependencies=[Depends(_same_origin_only)])
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
    global _STATUS_MOD
    _STATUS_MOD = None      # the status report is looked for relative to root
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

_PROVIDER_RE = re.compile(r"provider\s*=\s*[\"']([^\"']+)[\"']")
_KIND_RE = re.compile(r"kind\s*=\s*(DOCUMENT|RECEIPT)")

# Never copied into a new install. A template in a repo checkout can have all
# of these sitting beside the code.
_TEMPLATE_SKIP = {".venv", "__pycache__", ".pytest_cache", "tests", "Backups",
                  "Logs", "Diagnostics", "Manual Review", "config.json",
                  "progress.json", "discovery.json"}


def _templates_root() -> Path | None:
    """Where the shipped app code lives. templates/apps in a package, apps/ in
    a checkout. None when neither exists."""
    for cand in (HERE.parent / "templates" / "apps", HERE.parent / "apps"):
        if cand.is_dir() and any(_entry_script(d) for d in cand.iterdir() if d.is_dir()):
            return cand
    return None


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


def create_install(root: Path, slug: str) -> str:
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
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        # Exact names, plus anything profile-shaped. A profile folder is
        # named <slug>-browser-profile, and in a repo checkout it can be
        # sitting there signed in. The test that copies a fake one with a
        # Cookies file inside is what caught this.
        if any(part in _TEMPLATE_SKIP or "browser-profile" in part.lower()
               or part.lower().endswith(".pdf")
               for part in rel.parts):
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
    return "created"


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


@app.post("/api/create", dependencies=[Depends(_same_origin_only)])
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
        result = create_install(root, slug)
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
            "apps": _looks_like_installs(root)}


def _build_cmd(app_meta: dict, account: str, action: str):
    if action not in ACTIONS:
        raise HTTPException(400, "unknown action")
    if account not in app_meta["accounts"]:
        raise HTTPException(400, "unknown account")
    flags = []
    for f in ACTIONS[action]["flags"]:
        flags.append(app_meta["login_flag"] if f == "__LOGIN__" else f)
    cmd = [app_meta["python"], app_meta["script"], *flags]
    if account != "primary":
        cmd += ["--config", f"config.{account}.json"]
    return cmd


@app.get("/api/run", dependencies=[Depends(_same_origin_only)])
def api_run(app: str, account: str = "primary", action: str = "pilot"):
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    meta = apps[app]
    cmd = _build_cmd(meta, account, action)

    # Deliberately an *async* generator. With a plain sync one, Starlette wraps
    # it in iterate_in_threadpool, which never calls .close() on it - so the
    # cleanup below would never run and a closed tab left the downloader going.
    async def stream():
        yield f"data: $ {' '.join(cmd)}\n\n"
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        try:
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
        try:
            while True:
                # readline blocks, so it goes to a worker thread rather than
                # stalling the event loop for every other request.
                line = await to_thread.run_sync(proc.stdout.readline)
                if not line:
                    break
                yield f"data: {line.rstrip()}\n\n"
            code = await to_thread.run_sync(proc.wait)
            yield "data: \n\n"
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
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


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
  main { display:grid; grid-template-columns: 320px 1fr; gap:0; flex:1; min-height:0; }
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
  table.st td.num { text-align:right; }
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
  .actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:20px; }
  button { padding:10px; border:1px solid var(--line); border-radius:8px; cursor:pointer;
           background:var(--panel); color:var(--fg); font-size:14px; }
  button:hover { border-color:var(--accent); }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; grid-column:1/3; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .hint { font-size:12px; color:var(--muted); margin-top:16px; }
  .warn { color:#ffcf6b; }
  .console { background:#0b0d11; margin:0; padding:16px 20px; overflow:auto;
             font:13px/1.55 ui-monospace,Consolas,monospace; white-space:pre-wrap; }
  .status { padding:8px 20px; border-bottom:1px solid var(--line); font-size:13px; color:var(--muted); }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--muted); margin-right:8px; }
  .dot.run { background:var(--accent); animation:pulse 1s infinite; }
  .dot.ok { background:var(--ok); } .dot.err { background:#ff5c5c; }
  @keyframes pulse { 50% { opacity:.3; } }
</style>
</head>
<body>
<header>
  <h1>PaperPull <span class="ver">v__VERSION__</span><span class="tag"> — Receipt &amp; Statement Downloader</span></h1>
  <p id="root">control panel</p>
</header>
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
    <label for="app">App <a href="#" id="addlink" onclick="addProvider(); return false;" style="color:var(--accent); font-weight:400; font-size:12px; margin-left:8px;">add a provider</a></label>
    <select id="app"></select>
    <label for="account">Account</label>
    <select id="account"></select>
    <div class="actions" id="actions"></div>
    <p class="hint">1. <b>Login</b> opens a browser — sign in yourself and leave it open.<br>
       2. <b>Pilot</b> tests the newest few.<br>
       3. <b>Run All</b> downloads everything you don't already have.</p>
    <p class="hint" style="border-left:3px solid var(--accent); padding-left:10px;">
       ↻ <b>Safe to re-run.</b> Run All and Resume skip any statement or receipt
       you've already downloaded — nothing is ever fetched twice, even if you
       deleted the PDFs after importing them elsewhere.</p>
    <p class="hint warn" id="venvwarn" style="display:none"></p>
  </div>
  <div style="display:flex; flex-direction:column; min-width:0;">
  <div class="tabs">
    <button id="tabout" class="on" onclick="showTab('out')">Output</button>
    <button id="tabst" onclick="showTab('st')">Status</button>
  </div>
  <div id="paneout" style="display:flex; flex-direction:column; min-height:0; flex:1;">
    <div class="status"><span class="dot" id="dot"></span><span id="statustext">idle</span></div>
    <pre class="console" id="console"></pre>
  </div>
  <div id="panest" class="stwrap" style="display:none;">
    <p><button onclick="loadStatus()">Refresh</button>
       <span class="hint" id="stnote"></span></p>
    <div id="stbody">not loaded yet</div>
  </div>
  </div>
</main>
<footer>
  <span>PaperPull v__VERSION__ — read-only, runs locally</span>
  <span>☕ <a href="https://ko-fi.com/rheeloaded" target="_blank" rel="noopener">Support this project on Ko-fi</a></span>
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
  STATUS_LOADED = false;
  await load();
}

function changeRoot() {
  $('setup').style.display = 'block';
  $('rootinput').value = META.apps_root || '';
  $('rootinput').focus();
}

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
  $('newmsg').textContent = 'setting up...';
  let r;
  try {
    r = await fetch('/api/create', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({root, providers: picked})});
  } catch (e) { $('newmsg').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('newmsg').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false;
  await load();
  const n = d.created.length;
  $('console').textContent =
    'Set up ' + n + ' provider' + (n === 1 ? '' : 's') + ' under\n' + d.root +
    '\n\nNext: pick one above, click Login, and sign in when the browser opens.';
}

async function addProvider() {
  showSetup(true);
  $('newuser').style.display = 'block';
  $('existing').style.display = 'none';
  $('newroot').value = META.apps_root || '';
  await loadProviders(true);
}

let STATUS_LOADED = false;

function showTab(which) {
  const isSt = which === 'st';
  $('paneout').style.display = isSt ? 'none' : 'flex';
  $('panest').style.display  = isSt ? 'block' : 'none';
  $('tabout').className = isSt ? '' : 'on';
  $('tabst').className  = isSt ? 'on' : '';
  if (isSt && !STATUS_LOADED) loadStatus();
}

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
  $('root').innerHTML = 'apps root: ' + esc(META.apps_root) +
    (META.root_source === 'environment' ? ' <span class="hint">(from APPS_ROOT)</span>'
     : ' <a href="#" onclick="changeRoot(); return false;" style="color:var(--accent)">change</a>');
  const appSel = $('app');
  appSel.innerHTML = '';
  const keys = Object.keys(META.apps);
  if (!keys.length) {
    showSetup(true);
    $('newuser').style.display = 'block';
    $('existing').style.display = 'none';
    $('addlink').style.display = 'none';
    loadProviders(false);
    if (META.root_source !== 'environment') $('newroot').focus();
    return;
  }
  showSetup(false);
  $('addlink').style.display = '';
  for (const k of keys) appSel.append(new Option(META.apps[k].name, k));
  appSel.onchange = onApp;
  const acts = $('actions'); acts.innerHTML = '';
  for (const [k, label] of Object.entries(META.actions)) {
    const b = document.createElement('button');
    b.textContent = label; b.className = (k === 'all') ? 'primary' : '';
    b.onclick = () => run(k);
    acts.append(b);
  }
  onApp();
}
function onApp() {
  const m = META.apps[$('app').value];
  const accSel = $('account'); accSel.innerHTML = '';
  for (const a of m.accounts) accSel.append(new Option(a, a));
  const warn = $('venvwarn');
  if (!m.has_venv) { warn.style.display='block';
    warn.textContent = '⚠ No .venv in this app yet — run setup.bat there first, or output may show import errors.'; }
  else warn.style.display='none';
}
function setStatus(cls, text) { $('dot').className = 'dot ' + cls; $('statustext').textContent = text; }
function run(action) {
  if (es) es.close();
  const app = $('app').value, account = $('account').value;
  $('console').textContent = '';
  setStatus('run', `running ${action} — ${app} / ${account}`);
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  es = new EventSource(`/api/run?app=${encodeURIComponent(app)}&account=${encodeURIComponent(account)}&action=${action}`);
  const con = $('console');
  es.onmessage = e => { con.textContent += e.data + '\n'; con.scrollTop = con.scrollHeight; };
  es.addEventListener('done', e => {
    const code = e.data;
    setStatus(code === '0' ? 'ok' : 'err', code === '0' ? 'finished' : `exited (code ${code})`);
    document.querySelectorAll('button').forEach(b => b.disabled = false);
    es.close(); es = null;
  });
  es.onerror = () => { if (es) { setStatus('err','connection lost'); document.querySelectorAll('button').forEach(b=>b.disabled=false); es.close(); es=null; } };
}
load();
</script>
</body>
</html>
"""
