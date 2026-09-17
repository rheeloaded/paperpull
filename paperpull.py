"""One command for every app.

    python paperpull.py <app> <command> [--account NAME] [args for the app]
    python paperpull.py list

    python paperpull.py pge setup          make the app's environment
    python paperpull.py pge login          open the sign-in browser
    python paperpull.py pge pilot          download the newest few
    python paperpull.py pge all --yes      download everything in scope
    python paperpull.py chase resume --account spouse

Every app is one Python script that takes one flag, and this finds the app,
picks the interpreter it should run under, and passes the flag. Anything it
does not recognise after the command goes to the app as it is, so
`paperpull robinhood all --year 2025` works the way `--year 2025` does on the
script itself.

<app> is the folder name under apps/ (pge, chase), the folder name of an
install ("PG&E Statements"), or the provider's name, matched without regard
to case. The control panel does the same job with buttons, and this is the
same thing for a terminal.

Where the apps are, in order: --root, the APPS_ROOT environment variable, the
folder the control panel was pointed at, then apps/ beside this file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The same commands the control panel offers, with the flag each one means.
# login is resolved per app, since a CDP app opens a browser and the one
# app that drives Playwright's own browser only checks the connection. A
# command not listed here becomes --<command>, so the receipt apps' own
# modes (online, instore, review-names) need no entry.
COMMANDS = {
    "setup":    None,
    "login":    None,
    "discover": ["--discover"],
    "pilot":    ["--pilot"],
    "all":      ["--all"],
    "resume":   ["--resume"],
    "verify":   ["--verify"],
    "diagnose": ["--diagnose"],
    "dry-run":  ["--dry-run"],
}

ENTRY_RE = re.compile(r".*_(receipts|docs)\.py$")


# -- where the apps are --------------------------------------------------------

def settings_path() -> Path:
    """The control panel's settings file, read only, so the terminal and the
    panel agree on which folder holds the installs."""
    if sys.platform == "win32":
        # Roaming AppData, where the panel keeps it. The panel moves a file
        # left in Local AppData by an earlier version, and until it has run
        # once this falls back to reading it there.
        new = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") \
            / "PaperPull" / "settings.json"
        old = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") \
            / "PaperPull" / "settings.json"
        return new if new.exists() or not old.exists() else old
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PaperPull" / "settings.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") \
        / "paperpull" / "settings.json"


def apps_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("APPS_ROOT")
    if env:
        return Path(env).expanduser()
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8")).get("apps_root")
    except (OSError, ValueError, AttributeError):
        saved = None
    if saved:
        return Path(saved).expanduser()
    if (HERE / "templates" / "apps").is_dir() and not (HERE / "apps").is_dir():
        # The packaged app. Its apps/ folder is a template set, not installs.
        return Path.home() / "Documents" / "PaperPull"
    return HERE / "apps"


# -- which app -----------------------------------------------------------------

def entry_script(app_dir: Path) -> Path | None:
    for p in sorted(app_dir.glob("*.py")):
        if ENTRY_RE.match(p.name) and "test" not in p.name:
            return p
    return None


def provider_name(app_dir: Path) -> str:
    """The provider string from the app's storage.py, or empty."""
    try:
        text = (app_dir / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r'provider\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def list_apps(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [d for d in sorted(root.iterdir(), key=lambda p: p.name.lower())
            if d.is_dir() and entry_script(d)]


def _slug(app_dir: Path) -> str:
    script = entry_script(app_dir)
    return script.name.rsplit("_", 1)[0] if script else ""


def find_app(root: Path, wanted: str) -> Path:
    """Folder name, slug or provider, case-insensitively. Exactly one match,
    or an error that lists what was found."""
    apps = list_apps(root)
    if not apps:
        raise SystemExit("No apps under %s. Point --root at the folder that holds them." % root)
    w = wanted.strip().lower()
    exact = [d for d in apps if d.name.lower() == w or _slug(d).lower() == w]
    if len(exact) == 1:
        return exact[0]
    loose = [d for d in apps
             if w in d.name.lower() or w == provider_name(d).lower()
             or w in provider_name(d).lower()]
    if len(loose) == 1:
        return loose[0]
    if not loose:
        raise SystemExit("No app called %r under %s. Try: python paperpull.py list"
                         % (wanted, root))
    raise SystemExit("%r matches more than one app: %s. Use the folder name."
                     % (wanted, ", ".join(d.name for d in loose)))


# -- how to run it -------------------------------------------------------------

def interpreter(app_dir: Path) -> Path:
    """The app's own venv when it has one, otherwise the Python running this,
    which in the packaged app is the one that carries every dependency."""
    for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
        cand = app_dir / ".venv" / rel
        if cand.exists():
            return cand
    return Path(sys.executable)


def has_core() -> bool:
    import importlib.util
    return importlib.util.find_spec("paperpull_core") is not None


def login_flag(script: Path) -> str:
    try:
        text = script.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    return "--open-browser" if "--open-browser" in text else "--login"


def account_flags(app_dir: Path, account: str | None) -> list[str]:
    if not account or account == "primary":
        return []
    cfg = app_dir / ("config.%s.json" % account)
    if not cfg.is_file():
        raise SystemExit("No %s in %s. Add the account first (python add_account.py)."
                         % (cfg.name, app_dir.name))
    return ["--config", cfg.name]


def build_argv(app_dir: Path, command: str, account: str | None,
               extra: list[str]) -> list[str]:
    script = entry_script(app_dir)
    if command == "login":
        flags = [login_flag(script)]
    elif command in COMMANDS:
        flags = list(COMMANDS[command])
    else:
        flags = ["--" + command]
    return [str(interpreter(app_dir)), script.name, *flags,
            *account_flags(app_dir, account), *extra]


def run(app_dir: Path, argv: list[str]) -> int:
    return subprocess.call(argv, cwd=str(app_dir))


# -- setup ---------------------------------------------------------------------

def core_source() -> list[str]:
    """How the shared core gets into a venv. A checkout installs it editable
    from core/; a copy shipped without the source carries a wheel."""
    if (HERE / "core" / "pyproject.toml").is_file():
        return ["-e", str(HERE / "core")]
    wheels = sorted((HERE / "core").glob("paperpull_core-*.whl"))
    if wheels:
        return [str(wheels[-1])]
    raise SystemExit("Neither core/pyproject.toml nor a core wheel is beside paperpull.py, "
                     "so the shared core cannot be installed.")


def setup(app_dir: Path) -> int:
    """What setup.bat does. A venv, the app's requirements, the shared core.
    No browser download, that is offered at sign-in if none is found."""
    venv_py = interpreter(app_dir)
    if venv_py == Path(sys.executable):
        print("Creating .venv in %s" % app_dir.name)
        rc = subprocess.call([sys.executable, "-m", "venv", str(app_dir / ".venv")])
        if rc:
            return rc
        venv_py = interpreter(app_dir)
    else:
        print("Reusing .venv in %s" % app_dir.name)
    steps = [
        [str(venv_py), "-m", "pip", "install", "-q", "--upgrade", "pip"],
        [str(venv_py), "-m", "pip", "install", "-q", "-r", str(app_dir / "requirements.txt")],
        [str(venv_py), "-m", "pip", "install", "-q", *core_source()],
    ]
    for step in steps:
        rc = subprocess.call(step, cwd=str(app_dir))
        if rc:
            print("Setup FAILED at: %s" % " ".join(step[2:]))
            return rc
    print("Setup complete. Next: python paperpull.py %s login" % _slug(app_dir))
    return 0


# -- entry ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="paperpull",
        description="Run any PaperPull app from one place.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="commands: " + ", ".join(COMMANDS) + "\n"
               "anything after the command that is not --account goes to the app")
    ap.add_argument("--root", metavar="DIR", help="folder holding the apps")
    ap.add_argument("app", help="folder name, slug or provider, or 'list'")
    ap.add_argument("command", nargs="?",
                    help="one of the commands below, or any other mode the app "
                         "has, which is passed as --<command>")
    ap.add_argument("--account", metavar="NAME",
                    help="a second account, i.e. config.NAME.json")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args, extra = ap.parse_known_args(argv)
    root = apps_root(args.root)

    if args.app == "list":
        apps = list_apps(root)
        if not apps:
            print("No apps under %s" % root)
            return 1
        print("apps under %s\n" % root)
        for d in apps:
            venv = "" if interpreter(d) != Path(sys.executable) else "   (no .venv, run setup)"
            print("  %-36s %-14s %s%s" % (d.name, _slug(d), provider_name(d), venv))
        return 0

    if not args.command:
        ap.error("a command is required after the app: " + ", ".join(COMMANDS))

    app_dir = find_app(root, args.app)
    if args.command == "setup":
        return setup(app_dir)
    if interpreter(app_dir) == Path(sys.executable) and not has_core():
        raise SystemExit(
            "%s has no .venv and this Python does not have paperpull_core. "
            "Run: python paperpull.py %s setup" % (app_dir.name, args.app))
    argv_out = build_argv(app_dir, args.command, args.account, extra)
    print("$ " + " ".join(argv_out[1:]) + "   (in %s)" % app_dir.name, flush=True)
    return run(app_dir, argv_out)


if __name__ == "__main__":
    sys.exit(main())
