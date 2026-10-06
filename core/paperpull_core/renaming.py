"""Renaming files that are already downloaded, without downloading them again.

A naming scheme improves and the files already on disk keep the old one.
A tester asked how to re-pull five GitHub receipts so they would take the
new names, which is the wrong trade twice over. It asks the provider for
documents it has already given, and on a provider with a daily cap, eBay
being the one we know of, those requests are the ones you wanted for
something else. Nothing about the file needs fetching. Only its name is
wrong (#43, #49).

Review Names is here too. Every receipt app runs it to rename the receipts
it was unsure how to name, one at a time, to a summary the person types.

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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .models import State
from .storage import build_pdf_filename, title_case, unique_path


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
    spellings: dict = field(default_factory=dict) # another spelling -> old path str


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
                                 distinguisher=token, ignoring=old_path.name)
            # Told apart already, by the same order number it would be told
            # apart by now. It used to be pushed on to " (2)" because its own
            # name counted as taken, and five real files were asked to move.
            if target.name.lower() == old_path.name.lower() and str(target).lower() not in claimed:
                claimed.add(str(target).lower())
                changes[slot] = Change(row, old_path, target.name, reason="already named that")
                continue
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
    moved = _moved(result)
    for row in rows:
        old_path = (row.get(path_key) or "").strip()
        old_name = (row.get(name_key) or "").strip()
        new_path = moved(old_path)
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
    moved = _moved(result)
    data = getattr(progress, "data", None) or {}
    for key, rec in list(data.items()):
        if not isinstance(rec, dict):
            continue
        new_path = moved((rec.get(path_field) or "").strip())
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


def _moved(result: Result):
    """Where a recorded path's file went, by the path as the rename wrote
    it or by another spelling run_for found naming the same file before it
    moved. Rename finds a record by its file however its path is written,
    and a record left with its old spelling would no longer name the file
    it was found by, so the next rename would name the file from its row
    and the one after from its record again. Spellings are compared while
    the files are there, since after the move two spellings that read alike
    may be two files, as names differing only in case are in a folder that
    tells case apart."""
    def find(raw: str) -> Optional[str]:
        if not raw:
            return None
        return result.mapping.get(raw) or result.mapping.get(result.spellings.get(raw, ""))
    return find


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
    current = _Known(app, primary_rows)

    def build_name(row):
        # The whole record, not the row alone, because a pattern can name
        # a file for its order number, account or total (#50), and a
        # rename that left them out would name a file differently from a
        # download under the very same pattern.
        record = current.record_for(row)
        if record is None:
            return ""          # whose file it is cannot be told, so it keeps its name
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

    # Every other spelling of a file about to move, in the ledgers and the
    # run state, read while the file is still there to be compared.
    spellings = current.spellings(changes, [r for _csv, rows in ledgers for r in rows],
                                  getattr(app.progress, "data", None) or {})
    result = apply(changes, say=say)
    result.spellings = spellings
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
    """How a ledger row is matched to a record when no record names the
    row's own file (_Known.record_for).

    A receipt is its order number. A document has none in its row, so it
    is its date and its title, which a document app's own key may add an
    account or a count to."""
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


def _keys_of_record(rec: dict) -> list:
    """Every key a ledger row could be matched to this record by. A
    document kept by an id is a document of its date and title as well,
    which is all its row carries, so it is counted among the documents of
    that date and title."""
    key = _key_of_record(rec)
    if key is None:
        return []
    keys = [key]
    if key[0] == "order" and not str(rec.get("order_number") or "").strip():
        date = str(rec.get("date") or rec.get("purchase_date") or "").strip()
        if date:
            keys.append(("doc", date, str(rec.get("title") or "").strip()))
    return keys


class _Known:
    """What the app knows about each document today, and which document a
    ledger row is.

    A document is one key of the app's own, the one progress and discovery
    both keep its records under. Progress first and discovery over it,
    because discovery is the one an app refreshes when it learns to read a
    page better, and progress still holds anything discovery no longer
    lists. A value discovery leaves empty does not wipe one progress has.

    A row is the document whose record names the row's own file. A date
    and a title do not say which document a row is. American Family titles
    every bill's statement "Account Statement" and its date, and Citi every
    card's "Monthly Statement" and its date, so two bills with a statement
    of one day were merged here into one record, the later one, and Rename
    offered to give the first bill's file the second bill's account and a
    " (2)" (the release review of 0.44.0). A record names a row's file when
    its path is that very file, and two spellings that read alike are
    compared as files (_one_file), since a folder that tells case apart can
    hold two files whose names differ only in case. A row whose file no
    record names is matched by its order number, or by its date and title
    when one document alone has them and no record of that date and title
    names a file. Any other row is named from the row alone, a name that
    leaves out what a record would have added, and never one that says
    another document's. A file that rows of the index give to two
    documents, as when a deleted file's name was taken by a later download,
    or whose record has another order number than its row, keeps its name,
    since whose file it is cannot be told."""

    def __init__(self, app, rows=()):
        self.records = {}      # the app's key -> what it knows of that document
        self._by_file = {}     # a file -> each key whose records name it -> their spellings
        self._by_key = {}      # a row key -> the keys whose records carry it
        self._keys = {}        # the app's key -> the row keys its records carry
        self._named = set()    # the keys whose records name a file at all
        self._rows_at = {}     # a file -> (spelling, row key) of each row naming it
        self._files = {}       # a path as recorded -> _same_file of it
        for store_name in ("progress", "discovery"):
            store = getattr(app, store_name, None)
            data = getattr(store, "data", None)
            if not isinstance(data, dict):
                continue
            for name, rec in data.items():
                if not isinstance(rec, dict):
                    continue
                merged = self.records.setdefault(name, {})
                merged.update({k: v for k, v in rec.items() if v not in (None, "")})
                raw = str(rec.get("pdf_path") or "").strip()
                where = self._file(raw)
                if where:
                    # A dict for its order, so a choice between keys is
                    # made the same way on every run.
                    self._by_file.setdefault(where, {}).setdefault(name, set()).add(raw)
                    self._named.add(name)
                for key in _keys_of_record(rec):
                    self._by_key.setdefault(key, {})[name] = True
                    self._keys.setdefault(name, set()).add(key)
        for row in rows:
            raw = (row.get("PDF Full Path") or "").strip()
            where = self._file(raw)
            if where:
                self._rows_at.setdefault(where, []).append((raw, _record_key(row)))

    def _file(self, raw) -> str:
        raw = str(raw or "").strip()
        if not raw:
            return ""
        if raw not in self._files:
            self._files[raw] = _same_file(raw)
        return self._files[raw]

    def record_for(self, row: dict):
        """The record of the document this row is, {} when that cannot be
        told, and None when whose file this is cannot be told either."""
        key = _record_key(row)
        raw = (row.get("PDF Full Path") or "").strip()
        where = self._file(raw)
        if any(k != key and _one_file(r, raw) for r, k in self._rows_at.get(where, ())):
            return None
        named = [n for n, spelled in self._by_file.get(where, {}).items()
                 if any(_one_file(s, raw) for s in spelled)]
        if named:
            # Several records naming one file is a rename's own view at
            # work. Robinhood and Newrez show it a copy of a record dated
            # as the row now is, beside the record itself, and the copy is
            # the one the row's own date and title name.
            if len(named) > 1:
                named = [n for n in named if n in self._by_key.get(key, ())]
            if len(named) != 1:
                return {}
            # A record with another order number than its row's is another
            # purchase's, as when a deleted file's name was taken by a later
            # purchase and the later one's record is gone.
            if key[0] == "order" and key not in self._keys.get(named[0], ()):
                return None
            return self.records[named[0]]
        # An order number names one purchase, whichever of its files a row
        # is. A date and a title name a document only when one document has
        # them and no record of that date and title names a file. A record
        # naming another file may be another bill's or a newer copy of this
        # one, and a record naming none may be another bill's while this
        # row's own record names its newer copy, as after Download again
        # took a second copy of one bill and failed on the other's.
        found = list(self._by_key.get(key, ()))
        if key[0] != "order" and any(n in self._named for n in found):
            return {}
        return self.records[found[0]] if len(found) == 1 else {}

    def spellings(self, changes, rows, records) -> dict:
        """Each other spelling, among these rows' and records' paths, of a
        file one of the changes is about to move, with the change's own path
        for it. Read before the move, while the two can still be compared as
        files."""
        moving = {}
        for c in changes:
            if c.renaming and c.new_path:
                old = str(c.old_path)
                moving.setdefault(self._file(old), []).append(old)
        raws = [(r.get("PDF Full Path") or "").strip() for r in rows]
        raws += [str(rec.get("pdf_path") or "").strip() for rec in records.values()
                 if isinstance(rec, dict)]
        out = {}
        for raw in raws:
            for old in moving.get(self._file(raw), ()):
                if raw != old and _one_file(raw, old):
                    out[raw] = old
        return out


def _one_file(a: str, b: str) -> bool:
    """Whether two spellings are one file on disk now. Two that read alike
    after _same_file are two files where a folder tells case apart, so a
    spelling that is not the same text has to be shown to be the same file."""
    if a == b:
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _same_file(raw: str) -> str:
    """A recorded path resolved, and in one case on Windows and macOS,
    whose file systems ignore case unless a folder or volume is set to tell
    it apart. Every spelling of one file reads alike this way, and
    _one_file says whether two that read alike are one file. "" for a path
    that cannot be read as one."""
    try:
        path = os.path.realpath(raw)
    except (OSError, ValueError):
        try:
            path = os.path.abspath(raw)
        except (OSError, ValueError):
            return ""
    if os.name == "nt" or sys.platform == "darwin":
        path = path.lower()
    return path


# ---------------------------------------------------------------------------
# Review Names, the command every receipt app runs
# ---------------------------------------------------------------------------

# The note every rename leaves on its row. It is what tells a name somebody
# fixed from one still to be looked at, since a receipt renamed before its
# confidence was marked High as well still says Low (#47).
REVIEWED = "renamed via --review-names"


@dataclass(frozen=True)
class ReviewWords:
    """What Review Names prints around each receipt. An app keeps the words
    it has always printed."""

    current: str = "    Current file: "
    items: str = "    Items: "
    question: str = "    New summary (blank=keep, q=quit): "
    renamed: str = "    Renamed -> "


WORDS = ReviewWords()

# Apple and Uber, written after the rest, print the same without the colons.
PLAIN_WORDS = ReviewWords(current="    Current file  ", items="    Items  ",
                          question="    New summary (blank=keep, q=quit) ",
                          renamed="    Renamed to ")


def held_receipt(row: dict, paths) -> Optional[Path]:
    """The receipt a row of the index names, when it is a PDF in a folder
    the app files receipts in, and None for anything else.

    A row written for a purchase with no receipt has an empty path, which
    reads as the folder the app runs in, and that folder exists. A new name
    typed for such a row had the app rename the folder it runs in, which no
    system allows, and the review stopped with a traceback partway through.
    A row can also name the output folder itself, a file reached by
    climbing out of it through "..", a file somewhere else, one no longer
    on disk, or, with the output folder set to the app's own folder, the
    app's config file. None of those is a receipt this app holds."""
    text = (row.get("PDF Full Path") or "").strip()
    if not text:
        return None
    try:
        path = Path(text).resolve()
        folders = [Path(folder).resolve() for folder in paths.filing_folders()]
        held = (path.suffix.lower() == ".pdf" and path.is_file()
                and any(folder in path.parents for folder in folders))
    except (OSError, RuntimeError, ValueError):
        return None
    return Path(text) if held else None


def review_names(app, ask, words: ReviewWords = WORDS,
                 record_for: Optional[Callable[[str, dict], dict]] = None) -> None:
    """Ask for a better name for each receipt the app was unsure of, and
    rename the file to it.

    One function for every receipt app, so what may be renamed is decided
    once. `ask` is the app's own, which stops cleanly when no console is
    attached. `record_for(key, record)` gives the record a new name is
    built from, for an app that knows more than its progress record holds.
    Without it the progress record is used.

    Only a receipt the app holds is offered (held_receipt). A rename that
    fails is said, that receipt keeps its name, and the review goes on.
    Each rename is written to progress.json as it happens, and the CSVs
    are written however the review ends, a quit, a console that went away,
    Ctrl+C or an error, so they name the files as they are on disk."""
    rows = app.index_csv.read_all()
    # A row somebody already renamed is left out, even one renamed before
    # its confidence was marked High as well (#47).
    review = []
    for r in rows:
        unsure = (r.get("Classification Confidence") == "Low"
                  or "Review" in (r.get("Processing Status") or ""))
        if unsure and REVIEWED not in (r.get("Notes") or ""):
            path = held_receipt(r, app.paths)
            if path is not None:
                review.append((r, path))
    if not review:
        print("No receipts need name review.")
        return
    print(f"{len(review)} receipt(s) need review. Enter a new summary, "
          "press Enter to keep, or 'q' to stop.\n")
    order_rows = app.order_csv.read_all()
    changed = False
    try:
        for r, old_path in review:
            key = f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}"
            prog = app.progress.get(key) or {}
            items = [i.get("name", "") for i in prog.get("items", [])][:10]
            print(f"  {r.get('Purchase Date')}  #{r.get('Order or Receipt Number')}"
                  f"  [{r.get('Classification Confidence')}]")
            print(f"{words.current}{r.get('PDF Filename')}")
            if items:
                print(f"{words.items}{'; '.join(items)}")
            new = ask(words.question).strip()
            if new.lower() == "q":
                break
            if not new:
                print()
                continue
            new_summary = title_case(new)
            date = r.get("Purchase Date") or old_path.name[:10]
            doc_type = r.get("Document Type") or "Receipt"
            record = record_for(key, prog) if record_for else prog
            new_name = build_pdf_filename(date, new_summary, doc_type, record=record)
            try:
                new_path = unique_path(old_path.parent, new_name,
                                       app.config["max_path_length"])
                old_path.rename(new_path)  # unique_path guarantees no overwrite
            except (OSError, ValueError) as e:
                print(f"    It could not be renamed ({type(e).__name__}), so it keeps "
                      "its name.\n")
                continue
            changed = True
            old_filename = r.get("PDF Filename")
            r["PDF Filename"] = new_path.name
            r["PDF Full Path"] = str(new_path)
            r["Purchase Summary"] = new_summary
            r["Processing Status"] = "Completed"
            r["Classification Confidence"] = "High"
            r["Notes"] = (r.get("Notes", "") + "; " + REVIEWED).strip("; ")
            for orow in order_rows:
                if (orow.get("Order or Receipt Number") == r.get("Order or Receipt Number")
                        and orow.get("PDF Filename") == old_filename):
                    orow["PDF Filename"] = new_path.name
                    orow["Purchase Summary"] = new_summary
                    orow["Processing Status"] = "Completed"
            app.progress.update(key, {  # key (purchase identifier) unchanged
                "summary": new_summary, "pdf_filename": new_path.name,
                "pdf_path": str(new_path), "confidence": "High",
                "state": State.COMPLETED.value})
            print(f"{words.renamed}{new_path.name}\n")
    finally:
        if changed:
            app.index_csv.rewrite(rows)
            app.order_csv.rewrite(order_rows)
            print("CSV files and progress.json updated.")
