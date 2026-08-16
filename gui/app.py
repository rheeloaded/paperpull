r"""Receipt & Statement Downloaders - local control panel.

A tiny FastAPI app that discovers the downloader apps, lists their accounts,
and runs an action (Login / Discover / Pilot / Run All / Resume / Verify),
streaming the live output to the browser. It only ever runs the predefined
per-app commands - nothing from user input is passed to a shell.

Run it:  python -m uvicorn app:app --port 8765   (or use run_gui.bat)
Then open http://127.0.0.1:8765

By default it drives the apps in ../apps. Point it at your existing working
copies instead with the APPS_ROOT environment variable, e.g.:
  set APPS_ROOT=C:\path\to\Receipt and Statement Downloader
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

HERE = Path(__file__).resolve().parent
try:
    VERSION = (HERE.parent / "VERSION").read_text(encoding="utf-8").strip()
except Exception:
    VERSION = "0.1.0"
APPS_ROOT = Path(os.environ.get("APPS_ROOT", str(HERE.parent / "apps")))

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


def _entry_script(app_dir: Path):
    for p in sorted(app_dir.glob("*.py")):
        if ENTRY_RE.match(p.name):
            return p
    return None


def _python_for(app_dir: Path) -> str:
    venv = app_dir / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


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
    if not APPS_ROOT.exists():
        return apps
    for d in sorted(APPS_ROOT.iterdir()):
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
            "has_venv": (d / ".venv" / "Scripts" / "python.exe").exists(),
        }
    return apps


@app.get("/api/apps")
def api_apps():
    apps = discover_apps()
    return {"apps_root": str(APPS_ROOT), "actions": {k: v["label"] for k, v in ACTIONS.items()},
            "apps": apps}


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


@app.get("/api/run")
def api_run(app: str, account: str = "primary", action: str = "pilot"):
    apps = discover_apps()
    if app not in apps:
        raise HTTPException(404, "unknown app")
    meta = apps[app]
    cmd = _build_cmd(meta, account, action)

    def stream():
        yield f"data: $ {' '.join(cmd)}\n\n"
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.Popen(
                cmd, cwd=meta["dir"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=env)
        except Exception as e:
            yield f"data: [failed to start] {e}\n\n"
            yield "event: done\ndata: 1\n\n"
            return
        for line in iter(proc.stdout.readline, ""):
            yield f"data: {line.rstrip()}\n\n"
        proc.stdout.close()
        code = proc.wait()
        yield f"data: \n\n"
        yield f"event: done\ndata: {code}\n\n"

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
  .controls { padding:20px 22px; border-right:1px solid var(--line); overflow:auto; }
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
<main>
  <div class="controls">
    <label for="app">App</label>
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
    <div class="status"><span class="dot" id="dot"></span><span id="statustext">idle</span></div>
    <pre class="console" id="console"></pre>
  </div>
</main>
<footer>
  <span>PaperPull v__VERSION__ — read-only, runs locally</span>
  <span>☕ <a href="https://ko-fi.com/rheeloaded" target="_blank" rel="noopener">Support this project on Ko-fi</a></span>
</footer>
<script>
let META = null, es = null;
const $ = id => document.getElementById(id);

async function load() {
  META = await (await fetch('/api/apps')).json();
  $('root').textContent = 'apps root: ' + META.apps_root;
  const appSel = $('app');
  appSel.innerHTML = '';
  const keys = Object.keys(META.apps);
  if (!keys.length) { $('console').textContent = 'No apps found under ' + META.apps_root + '.\nSet APPS_ROOT to your downloaders folder.'; return; }
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
