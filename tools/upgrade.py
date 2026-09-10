"""Bring existing installs up to the current code without losing anything.

    python upgrade.py            look only, change nothing
    python upgrade.py --apply    make the changes
    python upgrade.py --root "D:\\path\\to\\installs"

WHAT THIS IS FOR

An install is code plus four things that must survive any upgrade.

    progress.json   what has already been downloaded, and the only reason a
                    re-run skips instead of fetching everything again
    config.json     where files go, which port, who the account belongs to
    the PDFs        whatever has not already been filed elsewhere
    the profile     the signed-in browser session

Replacing the code is the easy half. This handles the other half, which is
making sure the settings the new code reads are the settings the old install
actually has, and proving afterwards that the download history still says what
it said before.

Nothing here touches a PDF or a browser profile. It reads them to report, and
that is all.

WHAT IT CHANGES

    cdp_url  localhost -> 127.0.0.1
        A browser opened with --remote-debugging-port binds IPv4 only, while
        "localhost" resolves to ::1 first on a normal Windows machine. The
        attach then fails with a connection-refused error while the browser
        sits there listening, which reads as "the tool is broken" rather than
        "one character in a config is wrong".

    missing keys get their defaults written in
        So a config saved by an older version does not rely on the code
        filling gaps at load time, which makes the file self-describing and
        the next upgrade easier to reason about.

It refuses to write anything it cannot back up first.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Written into a config that lacks them, rather than left to load-time
# defaults, so the file says what the app is actually doing.
ADDED_DEFAULTS = {
    "browser": "auto",
}

TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}


def _say(line=""):
    """Console-safe, because account labels scraped from bank pages can hold
    characters the Windows console codepage cannot encode."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def _load_json(path: Path):
    """utf-8-sig, because a config edited in Notepad carries a byte order mark
    and json.loads rejects it."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as e:
        return None, str(e).splitlines()[0][:90]


def inspect(install: Path) -> dict | None:
    """What this install is, and what upgrading it would change."""
    cfg_path = install / "config.json"
    if not cfg_path.is_file():
        return None

    cfg, err = _load_json(cfg_path)
    report = {"name": install.name, "path": install, "changes": [],
              "config_error": err, "records": None, "already": None,
              "warnings": []}
    if cfg is None:
        report["warnings"].append("config.json could not be read (%s)" % err)
        return report

    url = str(cfg.get("cdp_url") or "")
    if "localhost" in url:
        report["changes"].append(
            ("cdp_url", url, url.replace("localhost", "127.0.0.1")))

    for key, value in ADDED_DEFAULTS.items():
        if key not in cfg:
            report["changes"].append((key, "(not set)", value))

    # The history, read but never written, because the whole point is proving
    # it survives untouched.
    recs, rerr = _load_json(install / "progress.json")
    if rerr == "missing":
        report["warnings"].append("no progress.json, so this install has no "
                                  "history to resume from")
    elif recs is None:
        report["warnings"].append("progress.json could not be read (%s). Do "
                                  "NOT upgrade this one until that is "
                                  "understood." % rerr)
    elif not isinstance(recs, dict):
        report["warnings"].append("progress.json is not in the expected shape")
    else:
        rows = [r for r in recs.values() if isinstance(r, dict)]
        report["records"] = len(rows)
        report["already"] = sum(
            1 for r in rows
            if r.get("downloaded_ok") or r.get("state") in TERMINAL)

    pdir = str(cfg.get("profile_dir") or "")
    if pdir:
        p = Path(pdir) if os.path.isabs(pdir) else install / pdir.lstrip("./")
        if not p.exists():
            report["warnings"].append(
                "no browser profile yet, so a sign-in will be needed (this is "
                "normal for an app not used before)")
    return report


def scan(root: Path):
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        got = inspect(child)
        if got:
            out.append(got)
    return out


def apply_changes(report: dict) -> bool:
    """Back up, then write. Returns False without writing if the backup fails."""
    cfg_path = report["path"] / "config.json"
    backups = report["path"] / "Backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg_path, backups / ("config.%s.before-upgrade.bak" % stamp))
    except OSError as e:
        _say("    could not back up config.json (%s), so nothing was changed" % e)
        return False

    cfg, err = _load_json(cfg_path)
    if cfg is None:
        _say("    config.json became unreadable (%s), nothing was changed" % err)
        return False

    for key, _old, new in report["changes"]:
        cfg[key] = new

    tmp = cfg_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        tmp.replace(cfg_path)
    except OSError as e:
        _say("    could not write config.json (%s)" % e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Upgrade existing PaperPull installs in place, safely.")
    ap.add_argument("--root", metavar="DIR", default=None,
                    help="the folder holding your installs "
                         "(default: this file's parent)")
    ap.add_argument("--apply", action="store_true",
                    help="make the changes (without this, nothing is written)")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser() if args.root \
        else Path(__file__).resolve().parent
    if not root.is_dir():
        _say("%s is not a folder." % root)
        return 1

    installs = scan(root)
    if not installs:
        _say("No installs were found under %s" % root)
        _say("Point --root at the folder that holds them.")
        return 1

    _say("Looking at %d install(s) under %s" % (len(installs), root))
    _say()

    total_changes = blocked = 0
    for r in installs:
        head = "  %-34s" % r["name"][:34]
        if r["records"] is not None:
            head += " %5d documents, %d already downloaded" % (
                r["records"], r["already"])
        _say(head)
        for key, old, new in r["changes"]:
            _say("      %-10s %s  ->  %s" % (key, old or "(empty)", new))
            total_changes += 1
        for w in r["warnings"]:
            _say("      note: %s" % w)
            if "Do NOT upgrade" in w:
                blocked += 1

    _say()
    if not total_changes:
        _say("Nothing needs changing. These installs are already current.")
        return 0

    if not args.apply:
        _say("%d change(s) to make. Nothing has been written." % total_changes)
        _say("Run again with --apply to make them.")
        return 0

    if blocked:
        _say("%d install(s) have an unreadable history. Fix those first."
             % blocked)
        return 1

    _say("Applying. The previous config.json is copied into each Backups")
    _say("folder first. PDFs, browser profiles and progress.json are not")
    _say("touched.")
    _say()
    done = 0
    for r in installs:
        if not r["changes"]:
            continue
        if apply_changes(r):
            _say("  %-34s updated" % r["name"][:34])
            done += 1

    _say()
    _say("%d install(s) updated." % done)
    _say("Re-run without --apply to confirm nothing is left outstanding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
