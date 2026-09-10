"""Carry your download history to another computer, so nothing is fetched twice.

The PDFs are not the important part. What matters is the record of what has
already been downloaded, because that is what makes a re-run skip a statement
instead of pulling it again. Move that, and a fresh install on a new machine
picks up exactly where the old one left off, whether or not you copied a single
PDF across.

    python migrate.py --export history.ppz
    python migrate.py --import history.ppz --dry-run
    python migrate.py --import history.ppz

WHAT COMES ACROSS

Each install's progress.json, which is a dict of records keyed by a stable
document identity. Two fields in each record decide whether a document is
skipped on the next run, and BOTH are needed:

  * downloaded_ok, the permanent marker, set once a PDF has been written
  * state, because records made before that marker existed are skipped on a
    terminal state alone, and that is most of them

An import never deletes and never downgrades. A document marked done stays
done, and anything the target install already knew about it is kept.

PATHS ARE REWRITTEN

Records carry the absolute path the PDF was written to. On another machine
those point at a folder that does not exist, so the root is rewritten to the
target install as the records are merged. Where a path cannot be rewritten it
is cleared rather than left pointing somewhere false, because one part of the
skip logic asks whether a review copy is still on disk and a stale path would
answer that wrongly.

THE EXPORT FILE HOLDS PERSONAL DATA

It is a plain zip, so treat it like the archive it describes. Depending on
which apps you run it can contain account labels and the last four digits of
account numbers, document titles, order numbers and purchase totals, itemised
purchases, and store locations. It holds no passwords, no cookies and no
session tokens.

--minimal writes only the fields a skip decision reads. On a real archive that
took the file from 330 KB to 64 KB and removed every item name, order number
and purchase total. Be clear about what it does NOT remove: the recorded PDF
path stays, and filenames embed account labels, so a line like
"Statements\\2026-08-18 Statement - FREEDOM (...0962).pdf" survives. It is a
much smaller and much less revealing file, not an anonymous one. The cost is
that the new machine starts with no history to report on until it runs.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCHEMA = 1

# The fields a skip decision actually reads. Everything else is history.
SKIP_FIELDS = ("state", "downloaded_ok", "pdf_path", "discovered_at", "updated_at")

# Read out of an install's own storage.py, the same way the status report does,
# so an install is identified by what it IS rather than what its folder is
# called. Folders get renamed; a provider does not.
PROVIDER_RE = re.compile(r"provider\s*=\s*[\"']([^\"']+)[\"']")
KIND_RE = re.compile(r"kind\s*=\s*(DOCUMENT|RECEIPT)")

# A terminal state means done even without the downloaded_ok marker. Kept in
# step with the apps' own should_skip.
TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}


def _say(line=""):
    """Console-safe. Account labels are scraped from bank pages and can hold
    characters the Windows console codepage cannot encode, which would
    otherwise end the run with a UnicodeEncodeError instead of a report."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def identify(install: Path):
    """(provider, kind) for an install folder, or (None, None) if it is not one."""
    if not (install / "progress.json").is_file():
        return None, None
    src = ""
    try:
        src = (install / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    p = PROVIDER_RE.search(src)
    k = KIND_RE.search(src)
    return (p.group(1) if p else install.name), (k.group(1) if k else None)


def _records(path: Path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def scan(root: Path):
    """Every install under root that has a history worth moving."""
    found = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        provider, kind = identify(child)
        if provider is None:
            continue
        recs = _records(child / "progress.json")
        if recs is None:
            _say("  skipping %s, its progress.json could not be read" % child.name)
            continue
        found.append({"folder": child.name, "provider": provider,
                      "kind": kind, "path": child, "records": recs})
    return found


# -- export ------------------------------------------------------------------

def export(root: Path, out: Path, minimal: bool = False) -> int:
    installs = scan(root)
    if not installs:
        _say("No installs with a download history were found under %s" % root)
        return 1

    manifest = {"schema": SCHEMA, "created": datetime.now().isoformat(timespec="seconds"),
                "source_root": str(root), "minimal": bool(minimal), "apps": []}
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for app in installs:
            recs = app["records"]
            if minimal:
                recs = {k: {f: v[f] for f in SKIP_FIELDS if f in v}
                        for k, v in recs.items()}
            done = sum(1 for r in app["records"].values()
                       if r.get("downloaded_ok") or r.get("state") in TERMINAL)
            manifest["apps"].append({"folder": app["folder"], "provider": app["provider"],
                                     "kind": app["kind"], "records": len(recs),
                                     "already_downloaded": done})
            z.writestr("apps/%s/progress.json" % app["folder"],
                       json.dumps(recs, indent=2, ensure_ascii=False))
            total += len(recs)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("README.txt", _READ_ME)

    _say("Exported %d records from %d installs" % (total, len(installs)))
    _say("  to %s" % out)
    for a in manifest["apps"]:
        _say("    %-32s %5d records, %d already downloaded"
             % (a["provider"][:32], a["records"], a["already_downloaded"]))
    _say()
    _say("This file describes your archive, so keep it as private as the archive.")
    _say("It holds no passwords, cookies or session tokens.")
    if minimal:
        _say("Written with --minimal, so item names, order numbers and totals are")
        _say("left out. Recorded filenames remain, and those name accounts.")
    else:
        _say("It can contain account labels, document titles, order numbers,")
        _say("purchase totals and itemised purchases. Use --minimal to leave")
        _say("most of that out.")
    return 0


_READ_ME = """PaperPull download history.

Created by tools/migrate.py. Restore it on another computer with:

    python migrate.py --import <this file>

It carries the record of which documents have already been downloaded, so a
fresh install skips them instead of fetching them again. It does NOT contain
any PDF, and it does NOT contain any password, cookie or session token.

Depending on which apps you run it may contain account labels, document
titles, order numbers, purchase totals and store locations. Keep it as private
as the archive it describes.
"""


# -- import ------------------------------------------------------------------

def _is_absolute(path: str) -> bool:
    """True for a path that names a particular machine, on either platform.

    Path.is_absolute answers for the platform this code is running on, and an
    export written on Windows can be imported on a Mac, where a drive-letter
    path would otherwise look relative and be kept as-is.
    """
    p = (path or "").replace("\\", "/")
    return p.startswith("/") or (len(p) > 2 and p[1] == ":" and p[2] == "/")


def _rewrite_path(old: str, old_root: str, new_install: Path, old_folder: str) -> str:
    """Point a recorded PDF path at this machine, or clear it.

    A path that cannot be rewritten is CLEARED rather than left alone. The
    skip logic asks whether a manual-review copy is still on disk, and a path
    from another computer would answer that question wrongly.
    """
    if not old:
        return ""
    # The apps do not agree on this. Some record a path relative to their own
    # folder, others the full absolute one. A relative path is already portable
    # and is left exactly as it is. Only an absolute path names a machine.
    if not _is_absolute(old):
        return old
    try:
        marker = "%s%s%s" % (old_root.rstrip("\\/"), "\\", old_folder)
        alt = "%s/%s" % (old_root.rstrip("\\/"), old_folder)
        for m in (marker, alt):
            if old.lower().startswith(m.lower()):
                tail = old[len(m):].lstrip("\\/")
                return str(new_install / Path(tail.replace("\\", "/")))
    except Exception:
        pass
    return ""


def _merge(target: dict, incoming: dict, old_root: str,
           install: Path, old_folder: str):
    """Fold incoming records into target. Never deletes, never downgrades.

    The caller must hand over a DEEP copy. dict(records) copies only the outer
    mapping, so the record objects stay shared, and this function edits them in
    place. The plan pass then silently applied itself, and the apply pass that
    followed found nothing left to do and reported zero changes against a plan
    that had promised several.
    """
    added = updated = 0
    for key, inc in incoming.items():
        cur = target.get(key)
        rewritten = _rewrite_path(str(inc.get("pdf_path") or ""),
                                  old_root, install, old_folder)
        if cur is None:
            rec = dict(inc)
            rec["pdf_path"] = rewritten
            rec["imported_at"] = datetime.now().isoformat(timespec="seconds")
            target[key] = rec
            added += 1
            continue
        # Present on both sides. The target wins on content, because it
        # describes THIS machine, but a document already downloaded anywhere
        # stays downloaded.
        changed = False
        if inc.get("downloaded_ok") and not cur.get("downloaded_ok"):
            cur["downloaded_ok"] = True
            changed = True
        if cur.get("state") not in TERMINAL and inc.get("state") in TERMINAL:
            cur["state"] = inc["state"]
            changed = True
        if changed:
            cur["imported_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1
    return added, updated


def do_import(archive: Path, root: Path, dry_run: bool = False,
              assume_yes: bool = False) -> int:
    try:
        z = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile):
        _say("%s is not a readable export file." % archive)
        return 1
    with z:
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError):
            _say("%s has no manifest, so it was not made by this tool." % archive)
            return 1
        if manifest.get("schema") != SCHEMA:
            _say("That export was written by a different version of this tool "
                 "(schema %s, this understands %s)." % (manifest.get("schema"), SCHEMA))
            return 1

        here = {}
        for app in scan(root):
            here.setdefault(app["provider"].lower(), app)
            here.setdefault(app["folder"].lower(), app)

        plan, missing = [], []
        for entry in manifest.get("apps", []):
            match = here.get(str(entry.get("provider", "")).lower()) or \
                here.get(str(entry.get("folder", "")).lower())
            if match is None:
                missing.append(entry)
                continue
            try:
                incoming = json.loads(
                    z.read("apps/%s/progress.json" % entry["folder"]).decode("utf-8"))
            except (KeyError, ValueError):
                missing.append(entry)
                continue
            plan.append((entry, match, incoming))

        _say("Import plan, from %s" % archive)
        _say("  into %s" % root)
        _say()
        for entry, match, incoming in plan:
            preview = copy.deepcopy(match["records"])
            added, updated = _merge(preview, incoming,
                                    manifest.get("source_root", ""),
                                    match["path"], entry["folder"])
            _say("  %-30s %4d new, %4d marked done, %d already known"
                 % (match["provider"][:30], added, updated, len(match["records"])))
        for entry in missing:
            _say("  %-30s NOT INSTALLED HERE, skipped"
                 % str(entry.get("provider"))[:30])
        if not plan:
            _say()
            _say("Nothing to import. None of those providers are installed under %s" % root)
            return 1
        _say()

        if dry_run:
            _say("Dry run, nothing was written.")
            return 0
        if not assume_yes:
            try:
                answer = input("Apply this? Existing files are backed up first [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                _say("Nothing was written.")
                return 1

        for entry, match, incoming in plan:
            path = match["path"] / "progress.json"
            backups = match["path"] / "Backups"
            try:
                backups.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                (backups / ("progress.%s.before-import.bak" % stamp)).write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError as e:
                _say("  could not back up %s (%s), skipping it" % (match["provider"], e))
                continue
            merged = copy.deepcopy(match["records"])
            added, updated = _merge(merged, incoming,
                                    manifest.get("source_root", ""),
                                    match["path"], entry["folder"])
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(path)
            _say("  %-30s %4d new, %4d marked done" % (match["provider"][:30], added, updated))

        _say()
        _say("Done. Run each app as usual, it will skip what you already have.")
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Move your PaperPull download history between computers.")
    ap.add_argument("--export", metavar="FILE", help="write a history file")
    ap.add_argument("--import", dest="imp", metavar="FILE", help="read a history file")
    ap.add_argument("--root", metavar="DIR", default=None,
                    help="the folder holding your installs (default: this file's parent)")
    ap.add_argument("--minimal", action="store_true",
                    help="export only what a skip decision needs, far less personal data")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask before writing")
    args = ap.parse_args(argv)

    if bool(args.export) == bool(args.imp):
        ap.error("choose one of --export or --import")

    root = Path(args.root).expanduser() if args.root else Path(__file__).resolve().parent
    if not root.is_dir():
        _say("%s is not a folder." % root)
        return 1

    if args.export:
        return export(root, Path(args.export).expanduser(), minimal=args.minimal)
    return do_import(Path(args.imp).expanduser(), root,
                     dry_run=args.dry_run, assume_yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
