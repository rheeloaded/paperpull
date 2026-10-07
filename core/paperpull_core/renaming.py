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
* And only a document the app holds, a PDF in a folder it files documents
  in (held_document). A ledger can name anything, the output folder
  itself, a file somewhere else, the app's own config, and none of those
  is the app's to rename.
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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .models import State
from .storage import build_pdf_filename, fitted_name, title_case, unique_path


@dataclass
class Change:
    """One file's old and new name, and why it is or is not changing."""

    row: dict
    old_path: Path
    new_name: str
    reason: str = ""
    new_path: Optional[Path] = None
    # The limit new_path was cut to fit, which a name found again at apply
    # keeps to as well.
    max_path_length: int = 240

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
    stranded: dict = field(default_factory=dict)  # aside path str -> old path str


# Why a row naming something on disk is left out of a rename, when that
# something is not a document the app holds (held_document).
NOT_HELD = "not a PDF in a folder this app files documents in"


def held_document(text: str, folders) -> Optional[Path]:
    """The file a row's path names, when it is a PDF in one of `folders`,
    the folders the app files documents in (Paths.filing_folders), and
    None for anything else.

    An app writes its own index, but an index can name anything. An empty
    path reads as the folder the app runs in, which exists. An index copied
    with its output folder to a new place names the files in the old one,
    and one edited by hand names whatever was typed. So a row can name the
    output folder itself, a folder the app files in, a file reached by
    climbing out of them through "..", a file somewhere else, one in Logs,
    or, with the output folder set to the app's own folder, the app's
    config file. None of those is a document this app holds, and neither
    is a file no longer on disk, one that is not a PDF, or a link, which a
    rename would move in place of the file it leads to."""
    return _held(text, _real(folders))


def held_row(row: dict, folders, path_key: str = "PDF Full Path") -> Optional[Path]:
    """held_document for a row of an index, which also holds a PDF still
    under the name it was written to beside its place, ending
    ".pdf.delivering", when the row says it was saved. Robinhood records a
    tax form so when moving it into place fails, for Rename to finish. It
    also leaves a form that failed its check so, when moving that one to
    Manual Review fails, and that row says it needs review."""
    return _held_row(row, _real(folders), path_key)


def _held_row(row: dict, real_folders: List[Path],
              path_key: str = "PDF Full Path") -> Optional[Path]:
    saved = (row.get("Processing Status") or "").strip().lower() == "completed"
    return _held(row.get(path_key), real_folders, staged=saved)


def _real(folders) -> List[Path]:
    """Each folder where it really is, with links and ".." followed, as a
    file's path is before it is compared with them. Once for a whole plan,
    since finding that out takes the file system a while on Windows. A
    folder that cannot be read that way holds nothing here."""
    real = []
    for folder in folders:
        try:
            real.append(Path(folder).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return real


def _held(text: str, real_folders: List[Path], staged: bool = False) -> Optional[Path]:
    """held_document, with the folders already found where they really are,
    and with `staged` a PDF under its staging name as well."""
    text = (text or "").strip()
    if not text:
        return None
    ends = (".pdf", ".pdf.delivering") if staged else (".pdf",)
    try:
        path = Path(text).resolve()
        held = (path.name.lower().endswith(ends) and path.is_file()
                and not Path(text).is_symlink()
                and not set(path.parents).isdisjoint(real_folders))
    except (OSError, RuntimeError, ValueError):
        return None
    return Path(text) if held else None


def plan(rows: Iterable[dict], build_name: Callable[[dict], str], *,
         folders: Iterable[Path],
         distinguisher: Optional[Callable[[dict], str]] = None,
         path_key: str = "PDF Full Path",
         name_key: str = "PDF Filename",
         max_path_length: int = 240) -> List[Change]:
    """What every file would be called, without touching anything.

    `build_name` is handed a ledger row and returns the name that row
    should have. It is the only part that knows the naming scheme, so a
    scheme that becomes configurable later changes there and nothing
    here has to know about it.

    `folders` are the folders the app files documents in
    (Paths.filing_folders). A row naming anything on disk that is not a PDF
    in one of them is left out with the reason NOT_HELD (held_row), so no
    ledger can have a rename touch a folder, the app's config or a file it
    does not hold.

    `distinguisher` is handed the same row and returns whatever tells it
    from another file wanting the same name, an order number usually.
    Without it a file called "... Receipt (2)" is renamed to "(3)", which
    is the same complaint one number worse, since the name it wants is
    held by the file it collided with in the first place.

    `max_path_length` is the app's own limit. Every name is cut to fit it
    in the file's folder the way a download cuts it, so a file whose
    download cut its name is named right already, and no rename gives a
    file a longer path than its download would have.
    """
    inside = _real(folders)
    changes: List[Change] = []
    wanted = []                       # (slot, row, old_path, name cut to fit, whole name)

    for row in rows:
        raw = (row.get(path_key) or "").strip()
        old_name = (row.get(name_key) or "").strip()
        if not raw and not old_name:
            continue
        old_path = Path(raw) if raw else Path(old_name)
        if raw and old_path.exists() and _held_row(row, inside, path_key) is None:
            changes.append(Change(row, old_path, old_name, reason=NOT_HELD))
            continue
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
        # The name cut to fit max_path_length in the file's folder, as a
        # download cuts it. Taken whole, a file whose download had cut its
        # name was offered the whole name back, a path longer than the
        # limit the download kept to.
        whole = new_name
        try:
            new_name = fitted_name(old_path.parent, whole, max_path_length)
        except ValueError:
            changes.append(Change(row, old_path, old_name,
                                  reason="its folder is too deep for any name to fit "
                                         "max_path_length"))
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
        wanted.append((len(changes), row, old_path, new_name, whole))
        changes.append(None)

    # A name is free if nothing holds it, and also if the only thing
    # holding it is a file that is itself moving out of the way. Two files
    # that want each other's names is the case that proves it, and without
    # this pass each would be pushed to a " (2)" by a collision that was
    # about to stop existing. Freeing them is apply's job.
    leaving = {str(p).lower() for _i, _r, p, _n, _w in wanted}
    claimed = {}                      # a folder -> the names given out in it

    for slot, row, old_path, new_name, whole in wanted:
        target = old_path.parent / new_name
        given = claimed.setdefault(str(old_path.parent).lower(), set())
        free = ((not target.exists() or str(target).lower() in leaving)
                and new_name.lower() not in given)
        if not free:
            token = ""
            if distinguisher is not None:
                try:
                    token = distinguisher(row) or ""
                except Exception:
                    token = ""
            # The whole name, as a download hands it over, and the names this
            # plan gave out held as files a download found there would hold
            # them, so a file wanting one is told apart by its order number
            # first, as a download tells it. They used to be held only after
            # unique_path had answered, and a " (2)" put on its answer was
            # cut off again whenever the name had to be cut to fit, so
            # plan() never returned.
            target = unique_path(old_path.parent, whole, max_path_length,
                                 distinguisher=token, ignoring=old_path.name, held=given)
            # Told apart already, by the same order number it would be told
            # apart by now. It used to be pushed on to " (2)" because its own
            # name counted as taken, and five real files were asked to move.
            if target.name.lower() == old_path.name.lower():
                given.add(target.name.lower())
                changes[slot] = Change(row, old_path, target.name, reason="already named that")
                continue
        given.add(target.name.lower())
        changes[slot] = Change(row, old_path, target.name, new_path=target,
                               max_path_length=max_path_length)
    return changes


def describe(changes: Iterable[Change], say=print, limit: int = 0) -> None:
    """The plan, in the order a person would read it, and how many rows
    name something the app does not hold, which it leaves alone."""
    changes = list(changes)
    moving = [c for c in changes if c.renaming]
    if not moving:
        say("Every file is already named the way this app names them.")
    else:
        say("%d file(s) would be renamed." % len(moving))
        shown = moving if limit <= 0 else moving[:limit]
        for c in shown:
            say("  %s" % c.old_name)
            say("    -> %s" % c.new_name)
        if len(shown) < len(moving):
            say("  ... and %d more." % (len(moving) - len(shown)))
    left = sum(1 for c in changes if c.reason == NOT_HELD)
    if left:
        say("%d row(s) of the index name something other than a PDF in this app's "
            "folders, so they are left alone." % left)


# A rename refused because another program has the file open, as a virus
# scanner or a sync client may open a file just renamed, is tried this many
# times, this many seconds apart.
_TRIES = 5
_RETRY_PAUSE = 0.4


def apply(changes: Iterable[Change], say=print) -> Result:
    """Do the renames, and say what happened to each.

    A file wanting the name of another file in this same plan waits for
    that one to move first, so each chain of names goes from its free end
    and every file lands on the name the preview gave it. A rename onto a
    name still in use would refuse or overwrite depending on the platform,
    and a file meeting one took a name beside it the preview never gave.
    When a file of a chain cannot move, those waiting on its name keep
    their own.

    Files wanting each other's names in a ring, as two swapping names do,
    have no free end, so one of them goes to a temporary name first. When
    a rename in a ring is refused, the ring goes back as it was, since a
    file left partway would sit under a name the ledger gives another
    file. A file that cannot leave its temporary name is said by name and
    kept in Result.stranded, and when its own name holds another file by
    then, Result.mapping gives it the temporary name, so no ledger names
    the other file for it.
    """
    changes = [c for c in changes if c.renaming and c.new_path]
    result = Result()
    by_old = {}                       # a file (_file_key) -> its change
    for c in changes:
        # One rename for one file. A second change for a file already in
        # the plan would move whatever took the file's name after it left.
        by_old.setdefault(_file_key(c.old_path), c)
    todo = list(by_old.values())
    # The file each new name is held by, asked of the disk before anything
    # moves, so a name spelled in another case is the file's own wherever
    # the folder ignores case, a share or a USB drive on Linux included.
    holds = {id(c): by_old.get(_file_key(c.new_path)) if c.new_path.exists() else None
             for c in todo}

    def holder(c: Change) -> Optional[Change]:
        """The change whose file has c's new name now."""
        return holds[id(c)]

    moved, done = set(), set()        # ids of changes
    for first in todo:
        # Follow the names from this file to the end of its chain, or round
        # to a file already met, which makes a ring.
        path, at = [], {}
        c = first
        while c is not None and id(c) not in done and id(c) not in at:
            at[id(c)] = len(path)
            path.append(c)
            c = holder(c)
        if c is not None and id(c) in at:
            ring, path = path[at[id(c)]:], path[:at[id(c)]]
            _rename_ring(ring, moved, result, say)
            done.update(id(r) for r in ring)
        for c in reversed(path):      # the free end first
            _rename_one(c, holder(c), moved, result, say)
            done.add(id(c))
    result.skipped = len(changes) - result.renamed - result.failed
    return result


def _rename_one(c: Change, holder: Optional[Change], moved: set, result: Result,
                say) -> None:
    """One file of a chain, once the file holding its new name has moved."""
    if holder is not None and id(holder) not in moved:
        say("  could not rename %s, since %s could not be renamed first"
            % (c.old_name, holder.old_name))
        result.failed += 1
        return
    error = _land(c, c.old_path)
    if error:
        say("  could not rename %s (%s)" % (c.old_name, error.__class__.__name__))
        result.failed += 1
        return
    moved.add(id(c))
    _renamed(c, result)


def _rename_ring(ring: List[Change], moved: set, result: Result, say) -> None:
    """Files wanting each other's names, ring[i] the name of ring[i + 1] and
    the last ring[0]'s. ring[0] goes aside, then each file from the last
    back takes the name the one after it has left, and ring[0] goes last.
    A file renamed only in letter case is a ring of one."""
    first = ring[0]
    aside = first.old_path.with_name(first.old_path.name + ".renaming")
    n = 0
    while aside.exists():
        n += 1
        aside = first.old_path.with_name("%s.renaming%d" % (first.old_path.name, n))
    try:
        _retried_rename(first.old_path, aside)
    except OSError as e:
        say("  could not move %s (%s)" % (first.old_name, e.__class__.__name__))
        _also_left(ring[1:], say)
        result.failed += len(ring)
        return

    went = []
    for c in list(reversed(ring[1:])) + [first]:
        error = _land(c, aside if c is first else c.old_path)
        if not error:
            went.append(c)
            continue
        say("  could not rename %s (%s)" % (c.old_name, error.__class__.__name__))
        # Back as it was, the last to move first, each into the name the
        # one after it has just given back. One that cannot go back keeps
        # its new name, and so do those that moved before it, whose old
        # names it holds.
        kept = []
        for w in reversed(went):
            if kept or not _put(w.new_path, w.old_path):
                kept.append(w)
        for w in kept:
            say("  %s stays renamed to %s, since it could not be renamed back"
                % (w.old_name, w.new_path.name))
            moved.add(id(w))
            _renamed(w, result)
        result.failed += len(ring) - len(kept)
        home = _put(aside, first.old_path)
        _also_left([r for r in ring if r is not c and r not in kept
                    and (home or r is not first)], say)
        if home:
            return
        result.stranded[str(aside)] = str(first.old_path)
        if first.old_path.exists():
            # Its name holds another file now, so its rows and record
            # follow it to where it is, never to that file.
            result.mapping[str(first.old_path)] = str(aside)
            result.names[first.old_name] = aside.name
            if kept:
                why = "%s could not give its name back" % ring[-1].old_name
            else:
                why = "another file has taken its name"
            say("  %s is left as %s, since %s. The index and the run state name it "
                "there." % (first.old_name, aside.name, why))
        else:
            say("  %s is left as %s, since it could not be renamed back. Rename it "
                "to %s by hand." % (first.old_name, aside.name, first.old_name))
        return
    for c in went:
        moved.add(id(c))
        _renamed(c, result)


def _also_left(left: List[Change], say) -> None:
    """Say the other files of a ring were left with the names they had."""
    if len(left) == 1:
        say("  so %s, which trades names with it, keeps its name" % left[0].old_name)
    elif left:
        say("  so %s, which trade names with it, keep their names"
            % _listed(c.old_name for c in left))


def _land(c: Change, source: Path) -> Optional[Exception]:
    """Rename source to c's new name, and None, or the error that refused it.
    Never over another file, including one that appeared while this was
    running, and never past the limit the plan kept to."""
    try:
        if c.new_path.exists():
            c.new_path = unique_path(c.new_path.parent, c.new_path.name,
                                     c.max_path_length)
        _retried_rename(source, c.new_path)
    except (OSError, ValueError) as e:
        # ValueError when no name beside it fits the folder's limit.
        return e
    return None


def _put(source: Path, target: Path) -> bool:
    """Rename source back to target, unless something is there already."""
    try:
        if target.exists():
            return False
        _retried_rename(source, target)
    except OSError:
        return False
    return True


def _retried_rename(source: Path, target: Path) -> None:
    for attempt in range(_TRIES):
        # Looked for at every try, since a rename overwrites on Linux and
        # macOS, and a file can come while this waits.
        if target.exists():
            raise FileExistsError(17, "a file has that name", str(target))
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == _TRIES - 1:
                raise
            time.sleep(_RETRY_PAUSE)


def _file_key(path: Path):
    """The file at path, the same for every spelling of its name, or for a
    name nothing is under, the name as _same_file reads it."""
    try:
        stat = os.stat(path)
        if stat.st_ino:
            return (stat.st_dev, stat.st_ino)
    except (OSError, ValueError):
        pass
    return _same_file(str(path)) or str(path)


def _renamed(c: Change, result: Result) -> None:
    result.renamed += 1
    result.mapping[str(c.old_path)] = str(c.new_path)
    result.names[c.old_path.name] = c.new_path.name


def _listed(names) -> str:
    """"a", "a and b", "a, b and c"."""
    names = list(names)
    if len(names) < 2:
        return "".join(names)
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


def update_rows(rows: Iterable[dict], result: Result, *,
                path_key: str = "PDF Full Path",
                name_key: str = "PDF Filename",
                note: str = "",
                numbered: Optional[dict] = None) -> int:
    """Point a ledger at the files as they are now called.

    Verify reads the full path out of the index, so a rename that skipped
    this would report every file on disk as missing. Any CSV carrying
    either column is worth passing, which on a receipt app is the index
    and the order history both.

    A row that names its file by its path follows that file alone. Matched
    by name as well, a row Rename left alone took the new name of another
    file that had the same old one, and of two files of one name in two
    folders each row took whichever new name came last. A row with a name
    and no path, as in the order history, follows the file of its own order
    or document number when `numbered` says which that is (_numbered), and
    the name alone only when it carries no number.
    """
    touched = 0
    moved = _moved(result)
    for row in rows:
        old_path = (row.get(path_key) or "").strip()
        if old_path:
            new_path = moved(old_path)
            if not new_path:
                continue
            row[path_key] = new_path
            new_name = Path(new_path).name
        else:
            old_name = (row.get(name_key) or "").strip()
            number = _first(row, _ID_KEYS) if numbered is not None else ""
            new_name = (numbered.get((number, old_name)) if number
                        else result.names.get(old_name))
            if not new_name:
                continue
        if name_key in row:
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
    second download. Renaming a file must not disturb it. A record that
    names its file by its path follows that file alone, as a row does.
    """
    touched = 0
    moved = _moved(result)
    data = getattr(progress, "data", None) or {}
    for key, rec in list(data.items()):
        if not isinstance(rec, dict):
            continue
        recorded = (rec.get(path_field) or "").strip()
        if recorded:
            new_path = moved(recorded)
            if not new_path:
                continue
            patch = {path_field: new_path, filename_field: Path(new_path).name}
        else:
            new_name = result.names.get((rec.get(filename_field) or "").strip())
            if not new_name:
                continue
            patch = {filename_field: new_name}
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


def told_apart_by(record) -> str:
    """What a download adds to a file's name when another file already has
    that name (unique_path), read from the file's own record. A purchase is
    told apart by its order number. A document is told apart by the last
    six characters of the id its record keeps, which is what the document
    apps' downloads hand unique_path. Wealthfront's hands it nothing and
    keeps no id, so the two agree there too. A record with neither adds
    nothing, and its file was told apart by " (2)". PayPal tells a business
    statement apart by the first day it covers and hands run_for that rule
    of its own."""
    if not isinstance(record, dict):
        return ""
    number = str(record.get("order_number") or "").strip()
    if number:
        return number
    return str(record.get("document_id") or "")[-6:]


def run_for(app, apply_changes: bool = False, say=print,
            told_apart: Optional[Callable[[dict], str]] = None) -> Result:
    """Rename this app's files to the names it would give them today.

    One function rather than forty-eight, because the ledger is the same
    shape everywhere: a CSV carrying PDF Filename, sometimes a second one
    carrying it too, and progress.json. What differs is only which column
    holds the date and the summary, which is what the lists above are for.

    Nothing is downloaded, nothing moves folder, and the identity that
    stops a second download is not touched.

    `told_apart` is handed a document's record and returns what the app's
    download adds to its name when another file has that name, for an app
    whose download does not tell its files apart by told_apart_by.
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

    rule = told_apart or told_apart_by

    def distinguisher(row):
        # What the download told this file apart by when its name was
        # taken, so a file it told apart keeps that, and a file wanting a
        # name another file has is told apart as a download into that
        # folder would tell it. A receipt's row carries its order number. A
        # document's row carries no id, so the record naming the row's own
        # file is asked, as it was written down when the file was saved,
        # and a row whose record cannot be told adds nothing. The second of
        # two statements of one day and one summary is saved as
        # "... Monthly Statement OC2222.pdf", and asking the row alone
        # offered to rename it to "... (2).pdf" under the very pattern it
        # was saved by (#43, #49). Asking what a later listing wrote over
        # the id offered it another id.
        number = (row.get("Order or Receipt Number") or "").strip()
        if number:
            return number
        record = current.record_for(row, saved=True)
        return rule(record) if record else ""

    changes = plan(primary_rows, build_name, folders=app.paths.filing_folders(),
                   distinguisher=distinguisher,
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
    # A file left under a temporary name while its own name holds another
    # file is in the mapping too, with nothing renamed perhaps.
    if not result.mapping:
        _say_stranded(result, say)
        return result
    numbered = _numbered(changes, result)
    for csv, rows in ledgers:
        if update_rows(rows, result, note="renamed", numbered=numbered):
            csv.rewrite(rows)
    update_progress(app.progress, result)
    if result.renamed:
        say("")
        say("Renamed %d file(s). The index and the run state now point at them."
            % result.renamed)
    if result.renamed and result.failed - len(result.stranded):
        say("%d could not be renamed and were left alone."
            % (result.failed - len(result.stranded)))
    _say_stranded(result, say)
    return result


def _say_stranded(result: Result, say) -> None:
    if result.stranded:
        say("%d could not be renamed and %s left under a temporary name, as said above."
            % (len(result.stranded), "was" if len(result.stranded) == 1 else "were"))


def _numbered(changes: Iterable[Change], result: Result) -> dict:
    """The new name of each file renamed, by the order or document number
    of the row the plan read and the file's old name. The order history
    carries a number and a file name and no path, and matched by the name
    alone, two receipts of one name in two folders both took whichever new
    name came last, which Review Names could then no longer put right."""
    out = {}
    for c in changes:
        new = result.mapping.get(str(c.old_path))
        number = _first(c.row, _ID_KEYS)
        if new and number:
            out[(number, c.old_path.name)] = Path(new).name
    return out


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
        self._saved = {}       # the app's key -> what its records naming a file said
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
                    # What was written down when the file was saved, from
                    # progress first. A later listing refreshes discovery,
                    # and Capital One, Schwab and Vanguard write a provider's
                    # id there over the one their download told the file
                    # apart by.
                    saved = self._saved.setdefault(name, {})
                    for k, v in rec.items():
                        if v not in (None, "") and k not in saved:
                            saved[k] = v
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

    def record_for(self, row: dict, saved: bool = False):
        """The record of the document this row is, {} when that cannot be
        told, and None when whose file this is cannot be told either. With
        `saved`, a record that names a file is given as the stores naming
        that file wrote it down, progress first, without what a later
        listing has written into discovery since."""
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
            return self._view(named[0], saved)
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
        return self._view(found[0], saved) if len(found) == 1 else {}

    def _view(self, name: str, saved: bool) -> dict:
        """The record under the app's key `name`, as record_for gives it."""
        if saved and name in self._saved:
            return self._saved[name]
        return self.records[name]

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
    the app files receipts in, and None for anything else (held_document).

    A row written for a purchase with no receipt has an empty path, which
    reads as the folder the app runs in, and that folder exists. A new name
    typed for such a row had the app rename the folder it runs in, which no
    system allows, and the review stopped with a traceback partway through."""
    return held_document(row.get("PDF Full Path"), paths.filing_folders())


def _write_down(app, rows: List[dict], order_rows: List[dict], backup: bool) -> None:
    """Both CSVs as the review now has them, the order history even when
    the index could not be written."""
    try:
        app.index_csv.rewrite(rows, backup=backup)
    finally:
        app.order_csv.rewrite(order_rows, backup=backup)


def review_names(app, ask, words: ReviewWords = WORDS,
                 record_for: Optional[Callable[[str, dict], dict]] = None) -> None:
    """Ask for a better name for each receipt the app was unsure of, and
    rename the file to it.

    One function for every receipt app, so what may be renamed is decided
    once. `ask` is the app's own, which stops cleanly when no console is
    attached. `record_for(key, record)` gives the record a new name is
    built from, for an app that knows more than its progress record holds.
    Without it the progress record is used.

    Only a receipt the app holds is offered (held_receipt), each file once.
    A rename that fails is said, that receipt keeps its name, and the
    review goes on. Each rename is written to progress.json and to both
    CSVs as it happens, so they name the files as they are on disk however
    the review ends. Closing the console window ends the process at once,
    with nothing run after it, so writing at the end would not be enough.

    A new name marks a receipt Completed only when its record says it was
    saved, with downloaded_ok. One put aside because its PDF failed its
    check keeps the state its run gave it. A purchase's record takes a new
    name only when it names the file renamed, or when there is none yet,
    so an older copy of a purchase whose record names another copy leaves
    that record as it is."""
    rows = app.index_csv.read_all()
    # A row somebody already renamed is left out, even one renamed before
    # its confidence was marked High as well (#47).
    review, offered, left_out = [], set(), 0
    for r in rows:
        unsure = (r.get("Classification Confidence") == "Low"
                  or "Review" in (r.get("Processing Status") or ""))
        if not unsure or REVIEWED in (r.get("Notes") or ""):
            continue
        path = held_receipt(r, app.paths)
        if path is None:
            left_out += 1
        elif str(path) not in offered:
            offered.add(str(path))
            review.append((r, path))
    if left_out:
        print(f"{left_out} row(s) marked for review have no receipt PDF in this "
              "app's folders to rename, so they are left out.")
    if not review:
        print("No receipts need name review.")
        return
    print(f"{len(review)} receipt(s) need review. Enter a new summary, "
          "press Enter to keep, or 'q' to stop.\n")
    order_rows = app.order_csv.read_all()
    written = pending = False
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
            pending = True
            number = r.get("Order or Receipt Number")
            old_filename = r.get("PDF Filename")
            # The purchase's record says what a run fetches, and it speaks for
            # this file only when it names it, or when there is no record
            # yet. An older copy, put aside before a later run saved the
            # receipt or put aside a newer copy, keeps rows of its own, and
            # only those take its new name. Written into the record, it moved
            # the record off the copy the last run left.
            ours = not prog or str(Path(prog.get("pdf_path") or "")) == str(old_path)
            # Completed is for a receipt that was saved and marked for review
            # for its name alone, which its record says with downloaded_ok. A
            # receipt put aside in Manual Review because its PDF failed its
            # check has none, and marked Completed no run fetched it again,
            # though its copy was the one that failed.
            saved = ours and bool(prog.get("downloaded_ok"))
            # Every index row of this purchase naming this file follows it.
            # Target once wrote two for most invoice orders, and the one not
            # renamed named a file that was gone. A row of another purchase
            # is left as it is, since its other records are not this one's.
            for row in rows:
                text = (row.get("PDF Full Path") or "").strip()
                if (row.get("Order or Receipt Number") != number or not text
                        or str(Path(text)) != str(old_path)):
                    continue
                row["PDF Filename"] = new_path.name
                row["PDF Full Path"] = str(new_path)
                row["Purchase Summary"] = new_summary
                if saved:
                    row["Processing Status"] = "Completed"
                row["Classification Confidence"] = "High"
                row["Notes"] = (row.get("Notes", "") + "; " + REVIEWED).strip("; ")
            for orow in order_rows:
                if (orow.get("Order or Receipt Number") == number
                        and orow.get("PDF Filename") == old_filename):
                    orow["PDF Filename"] = new_path.name
                    orow["Purchase Summary"] = new_summary
                    if saved:
                        orow["Processing Status"] = "Completed"
            if ours:
                named = {"summary": new_summary, "pdf_filename": new_path.name,
                         "pdf_path": str(new_path), "confidence": "High"}
                if saved:
                    named["state"] = State.COMPLETED.value
                app.progress.update(key, named)  # key (purchase identifier) unchanged
            _write_down(app, rows, order_rows, backup=not written)
            pending, written = False, True
            print(f"{words.renamed}{new_path.name}\n")
    finally:
        # A rename whose rows were not written down yet, because something
        # between the two went wrong or the writing itself was cut short.
        if pending:
            _write_down(app, rows, order_rows, backup=not written)
            written = True
        if written:
            print("CSV files and progress.json updated.")
