"""Renaming files that are already downloaded, without downloading them again.

A naming scheme improves and the files already on disk keep the old one.
A tester asked how to re-pull five GitHub receipts so they would take the
new names, which is the wrong trade twice over. It asks the provider for
documents it has already given, and on a provider with a daily cap, eBay
being the one we know of, those requests are the ones you wanted for
something else. Nothing about the file needs fetching. Only its name is
wrong (#43, #49).

WHY THIS IS SAFE

A filename is never an identity here. A receipt is remembered by its
order number and a document by its date and title, in progress.json, and
that is what stops a second download. So renaming a file cannot make an
app forget it, cannot cause a re-download, and cannot lose a record.

What it can break is the ledger, because Verify reads a full path out of
the index CSV and would report every file missing. So the rename and the
ledger update are one operation here rather than two things a caller has
to remember.

THE RULES

* Only a file the ledger knows about is ever touched. Nothing scans a
  folder and renames what it finds, so a file somebody put there by hand
  is not this program's business.
* Nothing is ever overwritten. A target that exists gets the same
  treatment any new download gets.
* A file that is already correctly named is left alone, so running this
  twice does nothing the second time.
* Nothing moves between folders. A rename here changes a name, never a
  location.
* Preview is the default everywhere. A caller has to ask for the change.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .storage import unique_path


@dataclass
class Change:
    """One file's old and new name, and why it is or is not changing."""

    row: dict
    old_path: Path
    new_name: str
    reason: str = ""
    new_path: Optional[Path] = None

    @property
    def renaming(self) -> bool:
        return not self.reason

    @property
    def old_name(self) -> str:
        return self.old_path.name


@dataclass
class Result:
    renamed: int = 0
    skipped: int = 0
    failed: int = 0
    mapping: dict = field(default_factory=dict)   # old path str -> new path str
    names: dict = field(default_factory=dict)     # old name -> new name


def plan(rows: Iterable[dict], build_name: Callable[[dict], str], *,
         distinguisher: Optional[Callable[[dict], str]] = None,
         path_key: str = "PDF Full Path",
         name_key: str = "PDF Filename",
         max_path_length: int = 240) -> List[Change]:
    """What every file would be called, without touching anything.

    `build_name` is handed a ledger row and returns the name that row
    should have. It is the only part that knows the naming scheme, so a
    scheme that becomes configurable later changes there and nothing
    here has to know about it.

    `distinguisher` is handed the same row and returns whatever tells it
    from another file wanting the same name, an order number usually.
    Without it a file called "... Receipt (2)" is renamed to "(3)", which
    is the same complaint one number worse, since the name it wants is
    held by the file it collided with in the first place.
    """
    changes: List[Change] = []
    wanted = []                       # (row, old_path, desired name)

    for row in rows:
        raw = (row.get(path_key) or "").strip()
        old_name = (row.get(name_key) or "").strip()
        if not raw and not old_name:
            continue
        old_path = Path(raw) if raw else Path(old_name)
        try:
            new_name = (build_name(row) or "").strip()
        except Exception as e:                       # a row too thin to name
            changes.append(Change(row, old_path, old_name,
                                  reason="could not work out a name (%s)" % type(e).__name__))
            continue
        if not new_name:
            changes.append(Change(row, old_path, old_name,
                                  reason="nothing to name it from"))
            continue
        if new_name == old_path.name:
            changes.append(Change(row, old_path, new_name, reason="already named that"))
            continue
        if not raw or not old_path.exists():
            changes.append(Change(row, old_path, new_name,
                                  reason="not on disk, so only the record would change"))
            continue
        # A placeholder, so the plan reads back in the ledger's own order
        # rather than with everything that could not be renamed first.
        wanted.append((len(changes), row, old_path, new_name))
        changes.append(None)

    # A name is free if nothing holds it, and also if the only thing
    # holding it is a file that is itself moving out of the way. Two files
    # that want each other's names is the case that proves it, and without
    # this pass each would be pushed to a " (2)" by a collision that was
    # about to stop existing. Freeing them is apply's job.
    leaving = {str(p).lower() for _i, _r, p, _n in wanted}
    claimed = set()

    for slot, row, old_path, new_name in wanted:
        target = old_path.parent / new_name
        key = str(target).lower()
        free = (not target.exists() or key in leaving) and key not in claimed
        if not free:
            token = ""
            if distinguisher is not None:
                try:
                    token = distinguisher(row) or ""
                except Exception:
                    token = ""
            target = unique_path(old_path.parent, new_name, max_path_length,
                                 distinguisher=token)
            n = 1
            stem, ext = os.path.splitext(target.name)
            while str(target).lower() in claimed:
                n += 1
                target = unique_path(old_path.parent, "%s (%d)%s" % (stem, n, ext),
                                     max_path_length)
        claimed.add(str(target).lower())
        changes[slot] = Change(row, old_path, target.name, new_path=target)
    return changes


def describe(changes: Iterable[Change], say=print, limit: int = 0) -> None:
    """The plan, in the order a person would read it."""
    moving = [c for c in changes if c.renaming]
    if not moving:
        say("Every file is already named the way this app names them.")
        return
    say("%d file(s) would be renamed." % len(moving))
    shown = moving if limit <= 0 else moving[:limit]
    for c in shown:
        say("  %s" % c.old_name)
        say("    -> %s" % c.new_name)
    if len(shown) < len(moving):
        say("  ... and %d more." % (len(moving) - len(shown)))


def apply(changes: Iterable[Change], say=print) -> Result:
    """Do the renames, and say what happened to each.

    Two files can want each other's names, which a straight rename would
    resolve by refusing or by overwriting depending on the platform. Any
    file whose target is another file in this same plan goes to a
    temporary name first, so the whole set lands whatever order it is in.
    """
    changes = [c for c in changes if c.renaming and c.new_path]
    result = Result()
    sources = {str(c.old_path).lower() for c in changes}
    staged = []

    for c in changes:
        if str(c.new_path).lower() in sources:
            tmp = c.old_path.with_name(c.old_path.name + ".renaming")
            n = 0
            while tmp.exists():
                n += 1
                tmp = c.old_path.with_name("%s.renaming%d" % (c.old_path.name, n))
            try:
                os.replace(c.old_path, tmp)
                staged.append((c, tmp))
                continue
            except OSError as e:
                say("  could not move %s (%s)" % (c.old_name, e.__class__.__name__))
                result.failed += 1
                continue
        staged.append((c, c.old_path))

    for c, source in staged:
        try:
            # Never over another file, including one that appeared while
            # this was running.
            if c.new_path.exists():
                c.new_path = unique_path(c.new_path.parent, c.new_path.name)
            source.rename(c.new_path)
        except OSError as e:
            say("  could not rename %s (%s)" % (c.old_name, e.__class__.__name__))
            result.failed += 1
            try:                                     # put a staged file back
                if source != c.old_path and not c.old_path.exists():
                    source.rename(c.old_path)
            except OSError:
                pass
            continue
        result.renamed += 1
        result.mapping[str(c.old_path)] = str(c.new_path)
        result.names[c.old_path.name] = c.new_path.name
    result.skipped = len(list(changes)) - result.renamed - result.failed
    return result


def update_rows(rows: Iterable[dict], result: Result, *,
                path_key: str = "PDF Full Path",
                name_key: str = "PDF Filename",
                note: str = "") -> int:
    """Point a ledger at the files as they are now called.

    Verify reads the full path out of the index, so a rename that skipped
    this would report every file on disk as missing. Any CSV carrying
    either column is worth passing, which on a receipt app is the index
    and the order history both.
    """
    touched = 0
    for row in rows:
        old_path = (row.get(path_key) or "").strip()
        old_name = (row.get(name_key) or "").strip()
        new_path = result.mapping.get(old_path)
        new_name = result.names.get(old_name)
        if not new_path and not new_name:
            continue
        if new_path and path_key in row:
            row[path_key] = new_path
            new_name = new_name or Path(new_path).name
        if new_name and name_key in row:
            row[name_key] = new_name
        if note and "Notes" in row:
            row["Notes"] = ((row.get("Notes") or "") + "; " + note).strip("; ")
        touched += 1
    return touched


def update_progress(progress, result: Result, *,
                    filename_field: str = "pdf_filename",
                    path_field: str = "pdf_path") -> int:
    """The same for the run state, whose key is never touched.

    The key is the purchase or document identity, which is what stops a
    second download. Renaming a file must not disturb it.
    """
    touched = 0
    data = getattr(progress, "data", None) or {}
    for key, rec in list(data.items()):
        if not isinstance(rec, dict):
            continue
        new_path = result.mapping.get((rec.get(path_field) or "").strip())
        new_name = result.names.get((rec.get(filename_field) or "").strip())
        if not new_path and not new_name:
            continue
        patch = {}
        if new_path:
            patch[path_field] = new_path
            new_name = new_name or Path(new_path).name
        if new_name:
            patch[filename_field] = new_name
        progress.update(key, patch, save=False)
        touched += 1
    if touched:
        progress.save()
    return touched


# ---------------------------------------------------------------------------
# The command every app runs
# ---------------------------------------------------------------------------

# Which column holds what, on a receipt app and on a document app. Both
# shapes are here so an app does not have to say which it is.
_DATE_KEYS = ("Purchase Date", "Document Date", "Statement Date")
_SUMMARY_KEYS = ("Purchase Summary", "Document Summary")
_TYPE_KEYS = ("Document Type",)
_ID_KEYS = ("Order or Receipt Number", "Document ID")


def _first(row: dict, keys) -> str:
    for k in keys:
        value = (row.get(k) or "").strip()
        if value:
            return value
    return ""


def run_for(app, apply_changes: bool = False, say=print) -> Result:
    """Rename this app's files to the names it would give them today.

    One function rather than forty-eight, because the ledger is the same
    shape everywhere: a CSV carrying PDF Filename, sometimes a second one
    carrying it too, and progress.json. What differs is only which column
    holds the date and the summary, which is what the lists above are for.

    Nothing is downloaded, nothing moves folder, and the identity that
    stops a second download is not touched.
    """
    from .storage import build_pdf_filename

    # Every app holds its index as self.index_csv, and a receipt app holds
    # the order history as self.order_csv as well. That is the same in all
    # forty-eight, which is why this is one function rather than forty-eight.
    ledgers = []
    for attr in ("index_csv", "order_csv"):
        csv = getattr(app, attr, None)
        if csv is None or "PDF Filename" not in getattr(csv, "columns", []):
            continue
        ledgers.append((csv, csv.read_all()))

    if not ledgers:
        say("This app keeps no index of what it downloaded, so there is "
            "nothing to rename from.")
        return Result()

    # The ledger carrying a full path is the one that says where the files
    # are. Another carrying the name alone is corrected to match.
    primary_rows = None
    for _csv, rows in ledgers:
        if rows and "PDF Full Path" in rows[0]:
            primary_rows = rows
            break
    if primary_rows is None:
        say("Nothing downloaded yet, so there is nothing to rename.")
        return Result()

    # What the app calls a document TODAY, which is not what the index
    # says. The index row was written when the file was downloaded, and an
    # app that has since learned to read something better, the kind of
    # account a bill belongs to for instance, keeps that in the record it
    # discovers from. Reading the row alone gave back the name the file
    # already had, so a rename reported that everything was already named
    # correctly while the filenames plainly lacked the new part (#26).
    current = _records_now(app)

    def build_name(row):
        # The whole record, not the row alone, because a pattern can name
        # a file for its order number, account or total (#50), and a
        # rename that left them out would name a file differently from a
        # download under the very same pattern.
        record = current.get(_record_key(row)) or {}
        summary = (record.get("summary") or "").strip() or _first(row, _SUMMARY_KEYS)
        return build_pdf_filename(_first(row, _DATE_KEYS), summary,
                                  _first(row, _TYPE_KEYS), part=_part_of(row),
                                  record=record)

    changes = plan(primary_rows, build_name,
                   distinguisher=lambda row: _first(row, _ID_KEYS),
                   max_path_length=app.config.get("max_path_length", 240))
    describe(changes, say=say, limit=0 if apply_changes else 20)

    if not apply_changes:
        if any(c.renaming for c in changes):
            say("")
            say("Nothing has been changed. Run this again with --apply to do it.")
        return Result()

    result = apply(changes, say=say)
    if not result.renamed:
        return result
    for csv, rows in ledgers:
        if update_rows(rows, result, note="renamed"):
            csv.rewrite(rows)
    update_progress(app.progress, result)
    say("")
    say("Renamed %d file(s). The index and the run state now point at them."
        % result.renamed)
    if result.failed:
        say("%d could not be renamed and were left alone." % result.failed)
    return result


def _record_key(row: dict):
    """How a ledger row is matched to the record the app discovers from.

    A receipt is its order number. A document has none, so it is its date
    and its title, which is what a document app already keys on."""
    order = _first(row, _ID_KEYS)
    if order:
        return ("order", order)
    return ("doc", _first(row, _DATE_KEYS), (row.get("Document Title") or "").strip())


_PART = re.compile(r"\((\d+) of (\d+)\)\.pdf$", re.IGNORECASE)


def _part_of(row: dict):
    """The "(1 of 3)" a file was given when its order came as several
    invoices. Only the file knows it, and dropping it would rename the
    first of a split order as though it were the whole."""
    m = _PART.search((row.get("PDF Filename") or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _key_of_record(rec: dict):
    """The same key _record_key gives a ledger row, from a record."""
    order = str(rec.get("order_number") or rec.get("document_id") or "").strip()
    if order:
        return ("order", order)
    date = str(rec.get("date") or rec.get("purchase_date") or "").strip()
    if not date:
        return None
    return ("doc", date, str(rec.get("title") or "").strip())


def _records_now(app) -> dict:
    """What the app knows about each document today, by row key.

    Progress first and discovery over it, because discovery is the one an
    app refreshes when it learns to read a page better, and progress
    still holds anything discovery no longer lists. A value discovery
    leaves empty does not wipe one progress has."""
    out = {}
    for store_name in ("progress", "discovery"):
        store = getattr(app, store_name, None)
        data = getattr(store, "data", None)
        if not isinstance(data, dict):
            continue
        for rec in data.values():
            if not isinstance(rec, dict):
                continue
            key = _key_of_record(rec)
            if key is None:
                continue
            merged = out.setdefault(key, {})
            merged.update({k: v for k, v in rec.items() if v not in (None, "")})
    return out
