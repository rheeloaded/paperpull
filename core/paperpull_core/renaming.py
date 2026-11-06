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
* A file moves only within the folder it is filed in, Statements or
  Receipts or the like, into the folders a naming pattern with a / names
  there and back out of them (#101). It never moves to another of the
  app's folders, and a file in Manual Review stays in Manual Review, with
  no folders. A folder a rename leaves empty inside one of those is taken
  away, and never one of those folders themselves or one holding anything.
* The invoices of an order split into several move together. Target and
  Amazon save one as "(1 of 2)", "(2 of 2)" and so on, with one index row
  for the order and the others in the record's list of invoices or its
  notes, and each takes the name the order's row gives the first, with its
  own part (_invoices_alone, _review_others).
* Preview is the default everywhere. A caller has to ask for the change.
* Rename never ends with a file moved and a ledger still giving it the
  name it had. Every ledger is shown to be writable before a file moves,
  and when one still cannot be written, every file goes back under the
  name it had (run_for, put_back). Review Names keeps the same rule for
  each receipt it renames (review_names, _undo).
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from . import shared_folder
from .characters import whole_json
from .models import State
from .storage import (FileName, build_pdf_filename, filing_folder, fitted_name,
                      free_to_write, remove_empty, sanitize_component, title_case,
                      unique_path)


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
    # The folder the file is filed in, Statements or the like, inside which
    # a pattern's folders are (_Homes), for saying where a file moves.
    home: Optional[Path] = None

    @property
    def renaming(self) -> bool:
        return not self.reason

    @property
    def old_name(self) -> str:
        return self.old_path.name

    @property
    def moves(self) -> bool:
        """Whether the file goes to another folder, as a pattern's folders
        have it (#101)."""
        return (self.new_path is not None
                and not _same_folder(self.new_path.parent, self.old_path.parent))

    def shown(self, path: Path) -> str:
        """A path as a person reads it in a plan, from inside the folder the
        file is filed in, "Chase/2026/2026-01-31 Chase Statement.pdf"."""
        if self.home is not None:
            try:
                return Path(path).relative_to(self.home).as_posix()
            except ValueError:
                pass
        return Path(path).name


@dataclass
class Result:
    renamed: int = 0
    skipped: int = 0
    failed: int = 0
    mapping: dict = field(default_factory=dict)   # old path str -> new path str
    names: dict = field(default_factory=dict)     # old name -> new name
    spellings: dict = field(default_factory=dict) # another spelling -> old path str
    stranded: dict = field(default_factory=dict)  # aside path str -> old path str
    # Each old name two files renamed had, each given a new name of its own,
    # in two folders. A record or row knowing a file by its name alone
    # cannot say which it is, so it takes neither new name.
    unclear: set = field(default_factory=set)
    # Each folder a rename made for a pattern's folders, the outermost first,
    # so one left with nothing in it can be taken away (tidy).
    made: list = field(default_factory=list)


# Why a row naming something on disk is left out of a rename, when that
# something is not a document the app holds (held_document).
NOT_HELD = "not a PDF in a folder this app files documents in"


def held_document(text: str, folders) -> Optional[Path]:
    """The file a row's path names, when it is a document (VALID_DOC_EXTS) in
    one of `folders`, the folders the app files documents in
    (Paths.filing_folders), and None for anything else.

    An app writes its own index, but an index can name anything. An empty
    path reads as the folder the app runs in, which exists. An index copied
    with its output folder to a new place names the files in the old one,
    and one edited by hand names whatever was typed. So a row can name the
    output folder itself, a folder the app files in, a file reached by
    climbing out of them through "..", a file somewhere else, one in Logs,
    or, with the output folder set to the app's own folder, the app's
    config file. None of those is a document this app holds, and neither
    is a file no longer on disk, one of any other kind, or a link, which a
    rename would move in place of the file it leads to."""
    return _held(text, _real(folders))


def held_row(row: dict, folders, path_key: str = "PDF Full Path") -> Optional[Path]:
    """held_document for a row of an index, which also holds a PDF still
    under the name it was written to beside its place, ending
    ".pdf.delivering", when the row says it was saved. Robinhood records a
    tax form so when moving it into place fails, for Rename to finish. It
    also leaves a form that failed its check so, when moving that one to
    Manual Review fails, and that row says it needs review.

    It also holds a PDF Rename left under the temporary name it gives a file
    trading names with others (apply), ending ".pdf.renaming" and perhaps a
    number. Rename points a row there when the file's own name holds another
    file by then, and the next Rename finishes it. Left out as not held, it
    stayed there for good."""
    return _held_row(row, _real(folders), path_key)


def _held_row(row: dict, real_folders: List[Path],
              path_key: str = "PDF Full Path") -> Optional[Path]:
    saved = (row.get("Processing Status") or "").strip().lower() == "completed"
    return _held(row.get(path_key), real_folders, staged=saved, aside=True)


# The temporary name apply gives a file trading names with others
# (_rename_ring), once or, for a file put aside again, more than once.
_ASIDE = re.compile(r"\.pdf(\.renaming\d*)+$")
# What a document ends in. A Wealthfront tax form can come with a workbook or
# a table beside its PDF, and those go where the PDF goes (_invoices_alone).
VALID_DOC_EXTS = (".pdf", ".xls", ".xlsx", ".csv")


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


def _held(text: str, real_folders: List[Path], staged: bool = False,
          aside: bool = False) -> Optional[Path]:
    """held_document, with the folders already found where they really are,
    with `staged` a PDF under its staging name as well, and with `aside` one
    under Rename's temporary name. Kroger hands it a record's path, and one
    that is not text holds nothing (_text)."""
    text = _text(text)
    if not text:
        return None
    ends = VALID_DOC_EXTS + (".pdf.delivering",) if staged else VALID_DOC_EXTS
    try:
        path = Path(text).resolve()
        name = path.name.lower()
        held = ((name.endswith(ends) or (aside and _ASIDE.search(name))) and path.is_file()
                and not Path(text).is_symlink()
                and not set(path.parents).isdisjoint(real_folders))
    except (OSError, RuntimeError, ValueError):
        return None
    return Path(text) if held else None


def _same_folder(a, b) -> bool:
    """Whether two paths are one folder, by their spelling or else on disk,
    so a folder spelled in another case where the disk ignores case is the
    same folder."""
    if Path(a) == Path(b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


class _Homes:
    """Which of an app's folders each file is filed in, and whether a
    pattern's folders apply there.

    `folders` are the folders the app files documents in
    (Paths.filing_folders) and `flat` those of them a file stays in with no
    folders of a pattern's, Manual Review, where a file that failed its
    check is put aside."""

    def __init__(self, folders: Iterable[Path], flat: Iterable[Path] = ()):
        # Each folder as the app spells it, with where it really is.
        self._pairs = []
        for folder in folders:
            real = _real([folder])
            if real:
                self._pairs.append((Path(folder), real[0]))
        self.real = [real for _folder, real in self._pairs]
        self._flat = _real(flat)
        self._seen = {}

    def _where(self, path: Path) -> Optional[Path]:
        key = str(path)
        if key not in self._seen:
            try:
                self._seen[key] = Path(path).resolve()
            except (OSError, RuntimeError, ValueError):
                self._seen[key] = None
        return self._seen[key]

    def home(self, path: Path) -> Optional[Path]:
        """The folder of the app's that `path` is filed in, or None.

        It is the folder the file really is in, with links and ".." on the
        way followed, never the one its path's spelling seems to name. A
        path written "Statements/../Manual Review/x.pdf", or one through a
        link inside Statements to Manual Review, is filed in Manual Review,
        and taking it for one in Statements would move a file put aside
        into the pattern's folders there. It is spelled as the path spells
        it when one of the path's own folders is it and the path climbs
        through no "..", and as the app spells it otherwise."""
        real = self._where(path)
        if real is None:
            return None
        found = None
        for folder, where in self._pairs:
            if where in real.parents and (found is None
                                          or len(where.parts) > len(found[1].parts)):
                found = (folder, where)
        if found is None:
            return None
        if ".." not in Path(path).parts:
            for parent in Path(path).parents:
                if self._where(parent) == found[1]:
                    return parent
        return found[0]

    def is_flat(self, home: Path) -> bool:
        try:
            return Path(home).resolve() in self._flat
        except (OSError, RuntimeError, ValueError):
            return False

    def placed(self, path: Path, name):
        """(the folder a file at `path` is filed in, the name it takes
        there). A name a pattern gave folders keeps them, unless the file
        is in a folder where files stay flat, where it is the name alone.
        A file in none of the app's folders keeps the folder it is in."""
        home = self.home(path)
        if home is None:
            return Path(path).parent, str(name)
        if self.is_flat(home):
            return home, str(name)
        return home, name


def plan(rows: Iterable[dict], build_name: Callable[[dict], str], *,
         folders: Iterable[Path],
         distinguisher: Optional[Callable[[dict], str]] = None,
         path_key: str = "PDF Full Path",
         name_key: str = "PDF Filename",
         max_path_length: int = 240,
         flat: Iterable[Path] = (),
         moved_to: Optional[Callable[[Path], Optional[Path]]] = None) -> List[Change]:
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

    A name carrying a pattern's folders (storage.FileName) is filed in
    them, inside the folder of `folders` the file is in, as a download
    files it there (storage.filing_folder), and a file in a pattern's
    folder whose name now carries none goes back to that folder itself
    (#101). A file in one of `flat`, Manual Review, keeps its folder and
    takes the name alone.

    `moved_to` is handed the folder a file is filed in and returns the
    folder it is to be filed in instead, or None to keep it there. Moving
    the documents saved before into an account's documents folder plans
    so (#102).
    """
    homes = _Homes(folders, flat)
    inside = homes.real
    changes: List[Change] = []
    wanted = []        # (slot, row, old_path, name cut to fit, whole name, home, folder)

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
            new_name = build_name(row) or ""
            # Stripped as before, keeping the folders a pattern names.
            new_name = (FileName(new_name.strip(), new_name.folder)
                        if isinstance(new_name, FileName) else new_name.strip())
        except Exception as e:                       # a row too thin to name
            changes.append(Change(row, old_path, old_name,
                                  reason="could not work out a name (%s)" % type(e).__name__))
            continue
        if not new_name:
            changes.append(Change(row, old_path, old_name,
                                  reason="nothing to name it from"))
            continue
        # The folder the file is filed in, and the folder the name files it
        # in there, a pattern's folders or that folder itself.
        home, whole = homes.placed(old_path, new_name)
        if moved_to is not None:
            home = moved_to(home) or home
        # The name cut to fit max_path_length in the file's folder, as a
        # download cuts it. Taken whole, a file whose download had cut its
        # name was offered the whole name back, a path longer than the
        # limit the download kept to.
        try:
            where = filing_folder(home, whole, max_path_length)
            new_name = fitted_name(home, whole, max_path_length)
        except ValueError:
            changes.append(Change(row, old_path, old_name,
                                  reason="its folder is too deep for any name to fit "
                                         "max_path_length"))
            continue
        if new_name == old_path.name and _same_folder(where, old_path.parent):
            changes.append(Change(row, old_path, new_name, reason="already named that"))
            continue
        if not raw or not old_path.exists():
            changes.append(Change(row, old_path, new_name,
                                  reason="not on disk, so only the record would change"))
            continue
        # A placeholder, so the plan reads back in the ledger's own order
        # rather than with everything that could not be renamed first.
        wanted.append((len(changes), row, old_path, new_name, whole, home, where))
        changes.append(None)

    # A name is free if nothing holds it, and also if the only thing
    # holding it is a file that is itself moving out of the way. Two files
    # that want each other's names is the case that proves it, and without
    # this pass each would be pushed to a " (2)" by a collision that was
    # about to stop existing. Freeing them is apply's job.
    leaving = {str(w[2]).lower() for w in wanted}
    claimed = {}                      # a folder -> the names given out in it
    planned = {}                      # a file (_file_key) -> the change planned for it

    for slot, row, old_path, new_name, whole, home, where in wanted:
        # One change for each file. Download again can leave two rows of one
        # purchase naming one file, and the second row was given a name of
        # its own beside the first's. The preview counted the file twice and
        # listed it with two new names, apply renamed it once, and the name
        # given out for nothing was held from another file wanting it, which
        # took " (3)" with " (2)" free and was moved again by the next
        # Rename. A file the first row left with its name, as one told apart
        # already, was moved on to " (2)" for the second. Every row naming
        # the file follows it by its path when the ledgers are written
        # (update_rows).
        key = _file_key(old_path)
        first = planned.get(key)
        if first is not None:
            changes[slot] = Change(row, old_path, first.new_name, home=first.home,
                                   reason=first.reason or "renamed for another row of the index")
            continue
        target = where / new_name
        given = claimed.setdefault(str(where).lower(), set())
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
            # plan() never returned. The file stands in its own way only in
            # the folder it is in, and a preview makes no folder.
            target = unique_path(home, whole, max_path_length, distinguisher=token,
                                 ignoring=old_path, held=given, make=False)
            # Told apart already, by the same order number it would be told
            # apart by now. It used to be pushed on to " (2)" because its own
            # name counted as taken, and five real files were asked to move.
            if (target.name.lower() == old_path.name.lower()
                    and _same_folder(target.parent, old_path.parent)):
                given.add(target.name.lower())
                changes[slot] = planned[key] = Change(row, old_path, target.name, home=home,
                                                      reason="already named that")
                continue
        given.add(target.name.lower())
        changes[slot] = planned[key] = Change(row, old_path, target.name, new_path=target,
                                              max_path_length=max_path_length, home=home)
    return changes


def describe(changes: Iterable[Change], say=print, limit: int = 0,
             documents: bool = False) -> None:
    """The plan, in the order a person would read it, and how many rows
    name something the app does not hold, which it leaves alone. With
    `documents`, the plan of moving documents saved before into the
    documents folder (#102), each with where it is and where it goes."""
    changes = list(changes)
    moving = [c for c in changes if c.renaming]
    if not moving:
        say("Every document is in the documents folder already." if documents
            else "Every file is already named the way this app names them.")
    else:
        say("%d file(s) would be %s." % (len(moving), "moved" if documents else "renamed"))
        elsewhere = sum(1 for c in moving if c.moves)
        if elsewhere and not documents:
            say("%d of them would move to another folder, as the naming pattern's "
                "folders have it." % elsewhere)
        shown = moving if limit <= 0 else moving[:limit]
        for c in shown:
            # Where a file moves, the folders it leaves and the ones it goes
            # to, inside the folder it is filed in, or the whole of each when
            # it goes to the documents folder.
            if documents:
                say("  %s" % c.old_path)
                say("    -> %s" % c.new_path)
                continue
            say("  %s" % (c.shown(c.old_path) if c.moves else c.old_name))
            say("    -> %s" % (c.shown(c.new_path) if c.moves else c.new_name))
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
    error = _land(c, c.old_path, result)
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
        error = _land(c, aside if c is first else c.old_path, result)
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


def _land(c: Change, source: Path, result: Result) -> Optional[Exception]:
    """Rename source to c's new name, and None, or the error that refused it.
    Never over another file, including one that appeared while this was
    running, and never past the limit the plan kept to. A folder of a
    pattern's the file goes to is made first, and noted in result."""
    try:
        _make_folders(c.new_path.parent, result)
        if c.new_path.exists():
            c.new_path = unique_path(c.new_path.parent, c.new_path.name,
                                     c.max_path_length)
        _retried_rename(source, c.new_path)
    except (OSError, ValueError) as e:
        # ValueError when no name beside it fits the folder's limit.
        return e
    return None


def _make_folders(folder: Path, result: Result) -> None:
    """Make a folder a file is moving to when it is not there yet, held
    inside the data folder first on PaperPull Server, as every folder a run
    writes into is, and note in result each folder made, the outermost
    first, so one left with nothing in it can be taken away (tidy). The
    folder is held each time, made already or not, since a folder the share
    holds can be a link."""
    try:
        shared_folder.hold(folder)
    except shared_folder.LeadsOut as e:
        # Refused as a move is, so this file stays where it is and the files
        # moved before it are still written down where they went. Stopping
        # the run here would leave them moved and the ledgers not.
        raise PermissionError(13, str(e), str(folder)) from e
    if folder.is_dir():
        return
    missing, at = [], folder
    while not os.path.lexists(at) and at.parent != at:
        missing.append(at)
        at = at.parent
    folder.mkdir(parents=True, exist_ok=True)
    result.made.extend(str(m) for m in reversed(missing))


def tidy(result: Result, folders: Iterable[Path]) -> None:
    """Take away each folder a rename left with nothing in it, the folders
    files moved out of and those it made for files that then did not move,
    and each folder above one taken away that is left empty too.

    Only a folder inside one of `folders`, the folders the app files in,
    and never one of those, a folder holding anything or a link. A folder
    is taken away by the call that refuses one holding anything, so a file
    arriving meanwhile keeps its folder."""
    folders = list(folders)
    candidates = [Path(m) for m in reversed(result.made)]
    candidates += [Path(old).parent for old in result.mapping]
    seen = set()
    for folder in candidates:
        # Up from each, until a folder that is not empty. One that is not
        # may be empty once a folder inside it from a later candidate is
        # taken away, and is asked again then.
        if str(folder) not in seen:
            seen.add(str(folder))
            remove_empty(folder, folders)


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
        except OSError as e:
            if not _another_drive(e):
                raise
            _moved_across(source, target)
            return


def _another_drive(e: OSError) -> bool:
    """Whether a rename was refused because its two names are on two drives
    or shares, as a documents folder on a NAS is from the output folder."""
    return e.errno == errno.EXDEV or getattr(e, "winerror", None) == 17


def _moved_across(source: Path, target: Path) -> None:
    """Move a file to another drive or share, where a rename cannot go
    (#102). It is copied beside its new name under a temporary one, given
    its name only while nothing has it, and taken away from where it was
    only once it is whole there. A failure leaves it where it was and
    nothing under its new name, and when it cannot be taken away from where
    it was, the copy goes again, so there are never two."""
    part = target.with_name(".%s.moving" % target.name)
    n = 0
    while os.path.lexists(part):
        n += 1
        part = target.with_name(".%s.moving%d" % (target.name, n))
    try:
        with shared_folder.open_to_write(part, "wb") as out, open(source, "rb") as src:
            shutil.copyfileobj(src, out)
        # Its times, and never its attributes, so the copy is one this can
        # take away again, a file marked read-only included.
        st = os.stat(source)
        os.utime(part, (st.st_atime, st.st_mtime))
        if os.path.lexists(target):
            raise FileExistsError(17, "a file has that name", str(target))
        part.rename(target)
    except BaseException:
        _remove_copy(part)
        raise
    try:
        source.unlink()
    except BaseException:
        # A file marked read-only, or held open, cannot leave where it was,
        # so the copy goes again and the file stays where its ledgers say.
        _remove_copy(target)
        raise


def _remove_copy(path: Path) -> None:
    """Take away a copy _moved_across made, writable or not, since it is
    this program's own."""
    for attempt in range(2):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt:
                return
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                return


def _file_key(path: Path):
    """The file at path, the same for every spelling of its name, or for a
    name nothing is under, the name as _same_file reads it."""
    try:
        st = os.stat(path)
        if st.st_ino:
            return (st.st_dev, st.st_ino)
    except (OSError, ValueError):
        pass
    return _same_file(str(path)) or str(path)


def _renamed(c: Change, result: Result) -> None:
    result.renamed += 1
    result.mapping[str(c.old_path)] = str(c.new_path)
    # Two files of one name in two folders, given two new names, as a
    # pattern's folders make likely, leave that name saying neither.
    if result.names.get(c.old_path.name, c.new_path.name) != c.new_path.name:
        result.unclear.add(c.old_path.name)
    result.names[c.old_path.name] = c.new_path.name


# What holds a name put_back wants when the file there is none of the files
# apply moved, one that came while the ledgers were written.
_OTHER = -1


def put_back(result: Result) -> List[tuple]:
    """Every file `apply` moved, back under the name it had, never over
    another file. Returns (where it is now, the path it had) for each file
    that could not be put back, in the order they were tried, each chain
    from its free end, so renaming them back by hand in that order works.

    The renames are undone the way apply did them, turned round. A file
    whose old name another of them holds now waits for that one to go back
    first, so each chain goes back from its free end. Files holding each
    other's old names, as two that swapped do, are a ring, and one of them
    goes aside under a temporary name so the rest can go back, then goes
    last. A file renamed only in letter case is a ring of one where the
    folder ignores case. A file apply left under a temporary name
    (Result.stranded) goes home with the rest. A file whose old name holds
    a file none of these is stays where it is, and so does each file
    waiting for it."""
    moves = _moved_by(result)
    # The file each old name holds now, asked of the disk before anything
    # moves, as apply asks it, so a name spelled in another case is the
    # file's own wherever the folder ignores case.
    at = {}
    for i, (where, _old) in enumerate(moves):
        at.setdefault(_file_key(where), i)
    holds = [at.get(_file_key(old), _OTHER) if old.exists() else None
             for _where, old in moves]
    home, done, stuck = set(), set(), {}
    for first in range(len(moves)):
        # Follow the old names from this file to the end of its chain, or
        # round to a file already met, which makes a ring.
        path, seen = [], {}
        i = first
        while i is not None and i != _OTHER and i not in done and i not in seen:
            seen[i] = len(path)
            path.append(i)
            i = holds[i]
        if i is not None and i != _OTHER and i in seen:
            ring, path = path[seen[i]:], path[:seen[i]]
            _ring_back(ring, moves, home, stuck)
            done.update(ring)
        for j in reversed(path):          # the free end first
            holder = holds[j]
            if (holder is None or holder in home) and _put(*moves[j]):
                home.add(j)
            else:
                stuck[j] = moves[j]
            done.add(j)
    return list(stuck.values())


def _moved_by(result: Result) -> List[tuple]:
    """(where it is now, the path it had) for each file apply moved, once
    each. A file left under a temporary name while its own name holds
    another file is in Result.mapping and Result.stranded both."""
    moves = {}
    for old, new in result.mapping.items():
        moves[new] = (Path(new), Path(old))
    for aside, old in result.stranded.items():
        moves[aside] = (Path(aside), Path(old))
    return list(moves.values())


def _ring_back(ring: List[int], moves: List[tuple], home: set, stuck: dict) -> None:
    """Files of put_back holding each other's old names, ring[i] the old
    name of ring[i + 1] and the last ring[0]'s, back as _rename_ring moved
    them, turned round. ring[0] goes aside, then each file from the last
    back takes its old name, which the one after it has just left, and
    ring[0] goes last. When one cannot go back, those before it keep where
    they are, since it still holds their old names, and so does ring[0],
    back where it was if nothing has taken that, or else under the
    temporary name."""
    where, old = moves[ring[0]]
    # Not a name any of these files is to go back to either.
    wanted = {_same_file(str(o)) for _w, o in moves}
    aside = where.with_name(where.name + ".renaming")
    n = 0
    while aside.exists() or _same_file(str(aside)) in wanted:
        n += 1
        aside = where.with_name("%s.renaming%d" % (where.name, n))
    if not _put(where, aside):
        for i in ring:
            stuck[i] = moves[i]
        return
    went = True
    for i in reversed(ring[1:]):
        if went and _put(*moves[i]):
            home.add(i)
        else:
            went = False
            stuck[i] = moves[i]
    if went and _put(aside, old):
        home.add(ring[0])
        return
    stuck[ring[0]] = (where, old) if _put(aside, where) else (aside, old)


def _write_ledgers(app, ledgers, result: Result, numbered: dict, say=print,
                   note: str = "renamed") -> None:
    """Point each ledger at the files as they are now called, the index
    first, then the order history, then the run state.

    When one cannot be written, each written before it is written back, the
    run state is put back as it was in memory too, since every app saves it
    on its way out, and every file goes back under the name it had
    (put_back). Then it says what happened and stops with SystemExit(1),
    so the panel does not report the files renamed. Ctrl+C while it writes
    puts everything back the same and stops as Ctrl+C."""
    before = [[dict(r) for r in rows] for _csv, rows in ledgers]
    records = _records_of(app.progress)
    written, writing = [], ""
    try:
        for (csv, rows), rows_before in zip(ledgers, before):
            writing = _name_of(csv)
            if update_rows(rows, result, note=note, numbered=numbered):
                csv.rewrite(rows)
                written.append((csv, rows_before))
        writing = _name_of(app.progress)
        update_progress(app.progress, result, numbered=numbered)
    except BaseException as e:
        moved = len(_moved_by(result))
        stuck, unwritten = _undo(records, written, result)
        if isinstance(e, KeyboardInterrupt):
            what = "Rename was stopped while it wrote %s" % writing
        else:
            what = "%s could not be written (%s)" % (writing, type(e).__name__)
        say("")
        if not stuck:
            say("%s, so every file was put back under the name it had and nothing was "
                "renamed." % what)
        else:
            if len(stuck) < moved:
                say("%s, so Rename put back the files it had renamed, all but %d."
                    % (what, len(stuck)))
            else:
                say("%s, and Rename could not put back the files it had renamed." % what)
            if unwritten:
                say("The run state still gives each of those the name it had, so rename "
                    "each back to it by hand.")
            else:
                say("The index and the run state still give each of those the name it had, "
                    "so rename each back to it by hand.")
            for where, old in stuck:
                # A file in another folder, a documents folder on another
                # drive included, is said where it is and where it goes.
                elsewhere = not _same_folder(where.parent, old.parent)
                say("  %s" % (where if elsewhere else where.name))
                say("    back to %s" % (old if elsewhere else old.name))
        for csv in unwritten:
            say("%s could not be put back either, so it still names the files by their "
                "new names." % _name_of(csv))
            if getattr(csv, "backups_dir", None):
                say("The copy it had before this Rename is in the Backups folder.")
        if isinstance(e, PermissionError):
            say("Close any program that has %s open and run Rename again." % writing)
        if isinstance(e, OSError):
            raise SystemExit(1) from e
        raise


def _records_of(progress):
    """The run state's records in memory, and a copy of each for _undo to
    put back."""
    data = getattr(progress, "data", None)
    if not isinstance(data, dict):
        return None
    return data, {k: dict(v) if isinstance(v, dict) else v for k, v in data.items()}


def _undo(records, written: list, result: Result) -> tuple:
    """Undo what was written into the ledgers after files moved, once a
    write has failed. The run state's records go back as they were in
    memory (_records_of), and a record made since is taken away, because
    every app saves the run state on its way out. Each CSV in `written`, as
    (the CSV, the rows it had), goes back to those rows, the last written
    first, and every file moved goes back under the name it had (put_back).
    Returns the files that could not go back, as put_back gives them, and
    the CSVs that could not be written back."""
    if records is not None:
        data, copies = records
        data.clear()
        data.update(copies)
    unwritten = []
    for csv, rows_before in reversed(written):
        # Ctrl+C while a write back waits for a ledger stops that wait
        # and no more, so the files still go home.
        try:
            csv.rewrite(rows_before)
        except BaseException:
            unwritten.append(csv)
    return put_back(result), unwritten


def _ledger_files(app, ledgers) -> List[Path]:
    """The file behind each ledger a rename writes, the run state's too,
    for each one kept in a file."""
    stores = [csv for csv, _rows in ledgers] + [getattr(app, "progress", None)]
    return [Path(store.path) for store in stores if getattr(store, "path", None)]


def _name_of(store) -> str:
    """What a ledger is called when Rename speaks of it, its file's name."""
    path = getattr(store, "path", None)
    if path:
        return Path(path).name
    columns = getattr(store, "columns", None)
    if columns is None:
        return "the run state"
    return "the index" if "PDF Full Path" in columns else "the order history"


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

    The other invoices of an order split into several, which a row's notes
    name, are named there as a rename left them, by the row's own order
    number (_follow_also_saved), whether or not the row's own file moved.
    """
    touched = 0
    moved = _moved(result)
    for row in rows:
        old_path = (row.get(path_key) or "").strip()
        number = _first(row, _ID_KEYS) if numbered is not None else ""
        new_path = None
        if old_path:
            new_path = moved(old_path)
            new_name = Path(new_path).name if new_path else None
        else:
            old_name = (row.get(name_key) or "").strip()
            # A name two files renamed both had says neither (Result.unclear).
            new_name = (numbered.get((number, old_name)) if number
                        else None if old_name in result.unclear
                        else result.names.get(old_name))
        notes = (_follow_also_saved(row.get("Notes"), lambda name: numbered.get((number, name)))
                 if number else None)
        if not new_name and notes is None:
            continue
        if notes is not None:
            row["Notes"] = notes
        if new_name:
            if new_path:
                row[path_key] = new_path
            if name_key in row:
                row[name_key] = new_name
            if note and "Notes" in row:
                row["Notes"] = ((row.get("Notes") or "") + "; " + note).strip("; ")
        touched += 1
    return touched


def update_progress(progress, result: Result, *,
                    filename_field: str = "pdf_filename",
                    path_field: str = "pdf_path",
                    numbered: Optional[dict] = None) -> int:
    """The same for the run state, whose key is never touched.

    The key is the purchase or document identity, which is what stops a
    second download. Renaming a file must not disturb it. A record that
    names its file by its path follows that file alone, as a row does.
    Its notes name the other invoices of an order split into several as a
    rename left them, by the record's own order number, when `numbered`
    says what each file of that number was renamed to (_numbered).
    """
    touched = 0
    moved = _moved(result)
    data = getattr(progress, "data", None) or {}
    for key, rec in list(data.items()):
        if not isinstance(rec, dict):
            continue
        patch = {}
        recorded = _text(rec.get(path_field))
        if recorded:
            new_path = moved(recorded)
            if new_path:
                patch = {path_field: new_path, filename_field: Path(new_path).name}
        else:
            named = _text(rec.get(filename_field))
            new_name = None if named in result.unclear else result.names.get(named)
            if new_name:
                patch = {filename_field: new_name}
        # Whether or not pdf_path moved, since it names one invoice of an
        # order split into several and Rename may move another.
        invoices = _follow_invoices(rec.get("invoices"), moved)
        if invoices is not None:
            patch["invoices"] = invoices
        number = (str(rec.get("order_number") or str(key).partition(":")[2]).strip()
                  if numbered else "")
        notes = (_follow_also_saved(rec.get("notes"), lambda name: numbered.get((number, name)))
                 if number else None)
        if notes is not None:
            patch["notes"] = notes
        if not patch:
            continue
        progress.update(key, patch, save=False)
        touched += 1
    if touched:
        progress.save()
    return touched


def _text(value) -> str:
    """A path or name a record holds, and "" for anything but text or a
    path. progress.json can be edited by hand or left damaged, and a
    number, a list or a mapping where a path belongs names no file. Read as
    text it stopped a Rename after its files had moved, with progress.json
    not saved, so every record went on naming a file that was gone."""
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    return value.strip() if isinstance(value, str) else ""


def _follow_invoices(invoices, moved: Callable[[str], Optional[str]]) -> Optional[list]:
    """A record's list of invoices with each entry whose file moved naming
    it where it went (`moved` gives that, or None), and None when no entry
    changed.

    Target keeps every invoice of an order split into several in this list,
    and only one of them in pdf_path. A rename corrected the rows and
    pdf_path and left the list naming the old file, which Review Names,
    Rename and Target's own walk all read as the order's, so a later file
    given that freed name was taken for this order's as well."""
    if not isinstance(invoices, list):
        return None
    out, changed = [], False
    for e in invoices:
        raw = _text(e.get("file")) if isinstance(e, dict) else ""
        new = moved(raw) if raw else None
        if new and new != raw:
            e, changed = dict(e, file=new), True
        out.append(e)
    return out if changed else None


# The words a run writes into an order's notes before the other invoices of an
# order it saved in several, Target's "Also saved a.pdf, b.pdf" and Amazon's
# "Also saved: a.pdf, b.pdf". Every name ends ".pdf", so a name with a comma
# in it is read whole.
_ALSO_SAVED = re.compile(r"(?P<head>Also saved:? )(?P<names>.+?\.pdf(?:, .+?\.pdf)*)"
                         r"(?=$|;|\. )")
_NEXT_NAME = re.compile(r"(?<=\.pdf), ")


def _plain_name(name: str) -> bool:
    """Whether text read out of notes is a file's name alone. Notes can be
    edited by hand, and a name with a folder in it would reach past the
    folder the order's invoices were saved in."""
    return (bool(name) and name == name.strip() and name not in (".", "..")
            and "/" not in name and "\\" not in name and Path(name).name == name)


def _also_saved_names(notes) -> List[str]:
    """Each file name an order's notes say was saved beside its first
    invoice, in the order they are written."""
    if not isinstance(notes, str) or "Also saved" not in notes:
        return []
    return [name for m in _ALSO_SAVED.finditer(notes)
            for name in _NEXT_NAME.split(m.group("names")) if _plain_name(name)]


def _also_saved(rec) -> List[str]:
    """Each other invoice of an order its record's notes name, as a path in
    the folder of the record's pdf_path, where the run that wrote the notes
    saved them beside the first. Amazon names them nowhere else."""
    recorded = _text(rec.get("pdf_path")) if isinstance(rec, dict) else ""
    if not recorded:
        return []
    folder = Path(recorded).parent
    return [str(folder / name) for name in _also_saved_names(rec.get("notes"))]


def _follow_also_saved(notes, new_name: Callable[[str], Optional[str]]) -> Optional[str]:
    """Notes with each name an "Also saved" list in them gives replaced by
    the name `new_name` gives for it, or None when no name changed. The
    other invoices of an order are found by their names there, Amazon's
    only record of them, so notes left with the old names lost them."""
    if not isinstance(notes, str) or "Also saved" not in notes:
        return None
    changed = False

    def followed(m):
        nonlocal changed
        names = _NEXT_NAME.split(m.group("names"))
        for i, name in enumerate(names):
            new = new_name(name) if _plain_name(name) else None
            if new and new != name:
                names[i], changed = new, True
        return m.group("head") + ", ".join(names)

    out = _ALSO_SAVED.sub(followed, notes)
    return out if changed else None


def _other_invoices(rec, main: str) -> List[str]:
    """The invoices of an order split into several, as its record names
    them, but for `main`, the file the order's index row names, or every
    one when `main` is "", each once as it is first spelled.

    Target keeps each invoice in the record's list of invoices, and one put
    aside in Manual Review because it failed its check is not filed with
    the rest. Amazon names the others in the record's notes alone, and
    Target names them there as well (_also_saved)."""
    if not isinstance(rec, dict):
        return []
    invoices = rec.get("invoices")
    listed = [_text(e.get("file")) for e in (invoices if isinstance(invoices, list) else ())
              if isinstance(e, dict) and e.get("kept", True)]
    seen = {_same_file(main)} if main else set()
    out = []
    for raw in listed + _also_saved(rec):
        where = _same_file(raw) if raw else ""
        if where and where not in seen:
            seen.add(where)
            out.append(raw)
    return out


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


# Set by the control panel for the Rename it starts to move documents into
# an account's documents folder, each under the name it has, renaming
# nothing (#102). "1" is the Move a person asks for, every document saved
# and checked that is not in the documents folder. "new" is what the panel
# starts once a download run has ended, the documents that run listed in
# new-this-run.txt alone. Every app's Rename is this core's, so every app
# moves them alike.
MOVE_DOCUMENTS_ENV = "PAPERPULL_MOVE_DOCUMENTS"

# The fields that say which document a file holds, the ones a pattern's
# {number} is made of. Rename reads them as they were written down when the
# file was saved (run_for).
_AS_SAVED = ("order_number", "document_id")


def run_for(app, apply_changes: bool = False, say=print,
            told_apart: Optional[Callable[[dict], str]] = None,
            told_apart_before: Iterable[Callable[[dict], str]] = (),
            as_saved: Iterable[str] = ()) -> Result:
    """Rename this app's files to the names it would give them today.

    One function rather than forty-eight, because the ledger is the same
    shape everywhere: a CSV carrying PDF Filename, sometimes a second one
    carrying it too, and progress.json. What differs is only which column
    holds the date and the summary, which is what the lists above are for.

    Nothing is downloaded, the identity that stops a second download is
    not touched, and a file moves only into or out of the folders a naming
    pattern names inside the folder it is filed in (#101). A folder the
    files left with nothing in it is taken away once the ledgers follow
    them, and one made for a file that did not move is taken away whatever
    happens (tidy).

    `told_apart` is handed a document's record and returns what the app's
    download adds to its name when another file has that name, for an app
    whose download does not tell its files apart by told_apart_by.
    `told_apart_before` are the rules an earlier version of the app told
    its files apart by, so a file whose name only an earlier one can be
    read from, as the old copy Download again leaves, keeps its ending in
    the words of `told_apart` (_Known.told_apart_in_its_name).

    Which document a file holds, its order number or the provider's id, is
    read as it was written down when the file was saved, and so is what
    tells it apart. An id a listing gives a document only after its file was
    saved never reaches that file's name.

    `as_saved` are the fields an app's download changes after its listing
    wrote them, as Ally names a statement from what its PDF says. Rename
    reads those from the record as it was written down when the file was
    saved, since the listing's record over it still holds what the list
    said.
    """
    as_saved = tuple(as_saved)
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
        # Which document the file holds, as it was when the file was saved.
        # Capital One and Schwab write the id a later listing gives over the
        # one in discovery. Schwab says its ids are not stable from one
        # listing to the next, so a {number} pattern could rename every file
        # after a Discover, and two statements of one day, one title and one
        # account take each other's ids when the list comes back in another
        # order, so a file was named for the statement it does not hold.
        # The fields an app names in `as_saved` are read the same way, as
        # Ally names a statement from what its PDF says.
        saved = current.record_for(row, saved=True) or {}
        record = dict(record, **{k: saved.get(k, "") for k in (*_AS_SAVED, *as_saved)})
        summary = _text(record.get("summary")) or _first(row, _SUMMARY_KEYS)
        raw = (row.get("PDF Full Path") or "").strip()
        orig_ext = Path(raw).suffix if raw else ""
        name = build_pdf_filename(_first(row, _DATE_KEYS), summary,
                                  _first(row, _TYPE_KEYS), part=_part_of(row),
                                  record=record)
        if orig_ext and orig_ext.lower() != ".pdf" and orig_ext.lower() in VALID_DOC_EXTS:
            if isinstance(name, FileName):
                name = FileName(Path(name).stem + orig_ext, name.folder)
            else:
                name = Path(name).stem + orig_ext
        return name

    rule = told_apart or told_apart_by
    before = tuple(told_apart_before)
    limit = app.config.get("max_path_length", 240)
    folders = app.paths.filing_folders()
    # Manual Review keeps a file put aside with no folders of a pattern's.
    flat = [f for f in (getattr(app.paths, "manual_review", None),) if f is not None]
    homes = _Homes(folders, flat)

    def filed_in(row, name) -> Path:
        """The folder a row's file is filed in under `name`, as plan and a
        download file it (storage.filing_folder)."""
        home, name = homes.placed(Path((row.get("PDF Full Path") or "").strip()), name)
        return filing_folder(home, name, limit)

    # Moving documents into the documents folder (#102). Each file keeps its
    # name and the folders it is in, and goes from the folder of its kind
    # where it is to the same folder in the documents folder, by every rule
    # a rename keeps. Only a document saved and checked moves, never one put
    # aside in Manual Review, and with "new", only what the last download
    # run saved and listed in new-this-run.txt, as the panel asks once a
    # download run has ended.
    mode = os.environ.get(MOVE_DOCUMENTS_ENV, "").strip()
    documents = mode in ("1", "new")
    earlier = {}
    only = None
    if documents:
        for old, new in (getattr(app.paths, "documents_moves", dict)() or {}).items():
            try:
                earlier[Path(old).resolve()] = Path(new)
            except (OSError, RuntimeError, ValueError):
                continue
        if not earlier:
            say("Every document of this account is in its documents folder already, so "
                "there are none to move.")
            return Result()
        if mode == "new":
            only = _listed_this_run(app)
        say("Moving %s into %s." % ("the documents this run saved" if mode == "new"
                                    else "the documents saved before", app.paths.documents))

    def moved_to(home) -> Optional[Path]:
        try:
            return earlier.get(Path(home).resolve())
        except (OSError, RuntimeError, ValueError):
            return None

    def kept_name(row):
        """A row's file under the name it has, with the folders it is in
        inside the folder of its kind, for a move that changes neither, or
        "", which leaves it where it is, for one not saved and checked."""
        raw = (row.get("PDF Full Path") or "").strip()
        home = homes.home(Path(raw)) if raw else None
        if home is None or not raw.lower().endswith(VALID_DOC_EXTS):
            return ""
        if only is not None and _same_file(raw) not in only:
            return ""
        if "manual review" in (row.get("Processing Status") or "").lower():
            return ""
        record = current.record_for(row, saved=True) or {}
        if not (record.get("downloaded_ok") is True
                or record.get("state") in (State.COMPLETED.value, State.PDF_VERIFIED.value)):
            return ""
        # The record has to name this very file. One a purchase keeps by its
        # order number may speak for an earlier copy, as when Download again
        # saved a copy that failed its check beside the one that passed. Its
        # notes name the other invoices of an order Amazon saved in several.
        invoices = record.get("invoices")
        named = [record.get("pdf_path")] + [
            e.get("file") for e in (invoices if isinstance(invoices, list) else ())
            if isinstance(e, dict) and e.get("kept", True)] + _also_saved(record)
        if not any(_text(n) and _one_file(_text(n), raw) for n in named):
            return ""
        try:
            inside = Path(raw).resolve().relative_to(Path(home).resolve())
        except (OSError, RuntimeError, ValueError):
            return ""
        return FileName(Path(raw).name, "/".join(inside.parts[:-1]))

    name_for = kept_name if documents else build_name
    # Only one invoice of an order split into several has an index row.
    # Each of the others is planned as a row of its own, never written into
    # the index, so every invoice of the order takes a new name or goes to
    # the documents folder, and the run state follows each (update_progress).
    planned_rows = primary_rows + _invoices_alone(app, primary_rows, documents)

    def distinguisher(row):
        # What the download told this file apart by when its name was
        # taken, so a file it told apart keeps that, and a file wanting a
        # name another file has is told apart as a download into that
        # folder would tell it. A receipt's row carries its order number. A
        # document's row carries no id, so the record naming the row's own
        # file is asked, as it was written down when the file was saved,
        # and a row whose record cannot be told adds only an ending its
        # name already has (told_apart_in_its_name). The second of
        # two statements of one day and one summary is saved as
        # "... Monthly Statement OC2222.pdf", and asking the row alone
        # offered to rename it to "... (2).pdf" under the very pattern it
        # was saved by (#43, #49). Asking what a later listing wrote over
        # the id offered it another id.
        number = (row.get("Order or Receipt Number") or "").strip()
        if number:
            return number
        record = current.record_for(row, saved=True)
        if record:
            return rule(record)
        # Whose file it is cannot be told. Download again leaves the old copy
        # of a document so, "... OC2222.pdf" beside the "... OC2222 (2).pdf"
        # its record now names, and with nothing added it was offered
        # "... (2).pdf" under the very pattern it was saved by.
        token = (current.told_apart_in_its_name(row, rule, before)
                 if record == {} else "")
        # Kept only where it fits whole, a count after it included. Cut to
        # fit, it no longer read as that ending, so the next Rename moved the
        # file again, and the one after that moved another into its name.
        name = name_for(row)
        if token and not _fits_whole(filed_in(row, name), name, token, limit):
            return ""
        return token

    changes = plan(planned_rows, name_for, folders=folders, flat=flat,
                   distinguisher=distinguisher, max_path_length=limit,
                   moved_to=moved_to if documents else None)
    describe(changes, say=say, limit=0 if apply_changes else 20, documents=documents)

    if not apply_changes:
        if any(c.renaming for c in changes):
            say("")
            say("Nothing has been changed. Run this again with --apply to do it.")
        return Result()
    if not any(c.renaming and c.new_path for c in changes):
        return Result()

    # The ledgers are written after the files move, so each has to be one
    # that can be written before any file moves. Excel holds a CSV it has
    # open so that nothing can replace it, and the write that found that out
    # after the files had moved gave up after its minute. Waiting the same
    # minute here, while nothing has moved, lets a person close it, and when
    # it stays open nothing is renamed.
    held = [p for p in _ledger_files(app, ledgers) if not free_to_write(p, say=say)]
    if held:
        them = "it" if len(held) == 1 else "them"
        say("")
        say("Nothing was renamed, since %s could not be written, and Rename writes the "
            "new names into %s as it renames. Close any program that has %s open and "
            "run Rename again." % (_listed([p.name for p in held]), them, them))
        raise SystemExit(1)

    # Every other spelling of a file about to move, in the ledgers and the
    # run state, read while the file is still there to be compared.
    spellings = current.spellings(changes, [r for _csv, rows in ledgers for r in rows],
                                  getattr(app.progress, "data", None) or {})
    result = apply(changes, say=say)
    result.spellings = spellings
    # A file left under a temporary name while its own name holds another
    # file is in the mapping too, with nothing renamed perhaps.
    if not result.mapping:
        tidy(result, folders)
        _say_stranded(result, say)
        return result
    # The ledgers are written after the files move, and a write that cannot
    # be done, the index open in Excel, gave up after its minute with every
    # renamed file still named by its old name in the index and the run
    # state. Verify then found each one missing, and the next Rename, reading
    # rows whose files were gone, said every file was already named the way
    # the app names it. Now every file goes back when a write fails, and a
    # folder made for one is taken away with it.
    try:
        _write_ledgers(app, ledgers, result, _numbered(changes, result), say=say,
                       note="moved to the documents folder" if documents else "renamed")
    finally:
        tidy(result, folders)
    if result.renamed and documents:
        # Written down, so they are found there after the setting changes.
        try:
            app.paths.remember_documents()
        except OSError as e:
            say("%s could not be written (%s). The documents moved are found where they "
                "are as long as the documents folder stays set."
                % (storage_name(app.paths), type(e).__name__))
        say("")
        say("Moved %d file(s) to %s. The index and the run state now point at them."
            % (result.renamed, app.paths.documents))
    elif result.renamed:
        say("")
        say("Renamed %d file(s). The index and the run state now point at them."
            % result.renamed)
    if result.renamed and result.failed - len(result.stranded):
        say("%d could not be renamed and were left alone."
            % (result.failed - len(result.stranded)))
    _say_stranded(result, say)
    return result


def storage_name(paths) -> str:
    return Path(getattr(paths, "documents_folders_json", "documents-folders.json")).name


def _listed_this_run(app) -> set:
    """Each file the last download run saved and checked, as it listed them
    in new-this-run.txt in the output folder (every app writes it), read as
    _same_file reads a path."""
    listed = Path(app.paths.root) / "new-this-run.txt"
    try:
        with shared_folder.open_to_read(listed, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, SystemExit):
        return set()
    return {_same_file(line.strip()) for line in lines
            if line.strip() and not line.startswith("#")}


def _invoices_alone(app, rows, documents: bool = True) -> List[dict]:
    """A row for each invoice of an order split into several that no index
    row names, each carrying the order's number, so a rename or a move takes
    every invoice of the order. The order has one index row, for the invoice
    naming its items. Target keeps every invoice in the record's list of
    invoices and Amazon names the others in its notes (_other_invoices), and
    a rename that took only the file the row names left them under the name
    the order had before.

    Each is a copy of the order's own index row, the one naming the record's
    pdf_path or else another of the order's, with the invoice's file in it,
    so its name is built from the order's date and kind as the first's is.
    A rename leaves out the invoices of an order with no index row, whose
    first it does not rename either, and one whose name does not say which
    invoice of the order it is, since its new name is built from that part
    (_part_of). A move keeps every name, so it needs neither. An invoice
    another purchase's rows, record, list of invoices or notes name as well
    keeps its name, as any file does whose purchase cannot be told
    (_Known.record_for).

    A document can list its files the same way, the workbook that came with
    a Wealthfront tax form. It has no order, so its row is the one naming its
    pdf_path, and each file's row carries no number and is the document's
    through the record's list. Told apart by its ending or a " (2)", such a
    file goes with a rename whether or not its name still gives its part
    (_LISTED)."""
    named = {_same_file((r.get("PDF Full Path") or "").strip()) for r in rows
             if (r.get("PDF Full Path") or "").strip()}
    extra = []
    data = getattr(getattr(app, "progress", None), "data", None) or {}
    for key, rec in data.items():
        # Every invoice the record names, the one in pdf_path included when
        # its list does, since the index row may name another of them.
        invoices = _other_invoices(rec, "")
        if not invoices:
            continue
        number = str(rec.get("order_number") or str(key).partition(":")[2]).strip()
        main = _text(rec.get("pdf_path"))
        where = _same_file(main) if main else ""
        theirs = [r for r in rows
                  if (r.get("Order or Receipt Number") or "").strip() == number] if number else []
        own = next((r for r in theirs
                    if where and _same_file((r.get("PDF Full Path") or "").strip()) == where
                    and _one_file((r.get("PDF Full Path") or "").strip(), main)),
                   theirs[0] if theirs else None)
        # What follows the first colon of a document's key is no order number,
        # and on a row it made the document's own file nobody's. A purchase
        # keeps to its own rows, since one naming its file may be another's.
        if own is None and where and not rec.get("order_number"):
            own = next((r for r in rows
                        if _same_file((r.get("PDF Full Path") or "").strip()) == where
                        and _one_file((r.get("PDF Full Path") or "").strip(), main)), None)
            if own is not None:
                number = ""
        for raw in invoices:
            if _same_file(raw) in named:
                continue
            row = dict(own or {}, **{
                "PDF Full Path": raw, "PDF Filename": Path(raw).name,
                "Order or Receipt Number": number,
                "Purchase Date": str((own or {}).get("Purchase Date")
                                     or rec.get("purchase_date") or ""),
                "Processing Status": "Completed", "Notes": "", _LISTED: not number})
            if not documents and (own is None or (number and _part_of(row) is None)):
                continue
            named.add(_same_file(raw))
            extra.append(row)
    return extra


def _fits_whole(folder: Path, name: str, token: str, max_path_length: int) -> bool:
    """Whether `name` with `token` after it and a count after that, as
    unique_path writes the second file told apart by one ending, fits
    max_path_length whole in `folder`, the one the row's file is filed in
    under that name."""
    stem, ext = os.path.splitext(name)
    return len(str(folder)) + len("/%s %s (99)%s" % (stem, token, ext)) <= max_path_length


def _say_stranded(result: Result, say) -> None:
    if result.stranded:
        say("%d could not be renamed and %s left under a temporary name, as said above."
            % (len(result.stranded), "was" if len(result.stranded) == 1 else "were"))


def _numbered(changes: Iterable[Change], result: Result) -> dict:
    """The new name of each file renamed, by the order or document number
    of the row the plan read and the file's old name. The order history
    carries a number and a file name and no path, and matched by the name
    alone, two receipts of one name in two folders both took whichever new
    name came last, which Review Names could then no longer put right.

    Two files of one purchase and one name in two folders, given two new
    names, are told apart by neither, so the order history's row of that
    name keeps it rather than take the other file's (#101)."""
    out, unclear = {}, set()
    for c in changes:
        new = result.mapping.get(str(c.old_path))
        number = _first(c.row, _ID_KEYS)
        if new and number:
            key = (number, c.old_path.name)
            if out.get(key, Path(new).name) != Path(new).name:
                unclear.add(key)
            out[key] = Path(new).name
    for key in unclear:
        del out[key]
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


_PART = re.compile(r"\((\d+) of (\d+)\)", re.IGNORECASE)

# On a row _invoices_alone builds for a file a document's record lists. It is
# never written to the index.
_LISTED = "Listed By Its Document"

# The " (2)" unique_path puts after a name, and after what told it apart, when
# both are taken.
_NUMBERED = re.compile(r" \(\d+\)$")


def _part_of(row: dict):
    """The "(1 of 3)" a file was given when its order came as several
    invoices. Only the file knows it, and dropping it would rename the
    first of a split order as though it were the whole.

    The part ends the name, or is followed only by what unique_path adds
    when the name is taken, the row's own order number, a " (2)", or both.
    Read only at the very end, the part of a file a download or Review
    Names told apart was lost, "... Invoice (1 of 2) 1234.pdf" renamed to
    "... Invoice.pdf". Anything else after it is not a part, and nothing
    after it is for a row with no order number, a document's, which is
    read only at the very end as it always was, but for the " (2)" of a file
    a document's record lists (_LISTED)."""
    name = (row.get("PDF Filename") or "").strip()
    stem, ext = os.path.splitext(name)
    found = list(_PART.finditer(stem)) if ext.lower() in VALID_DOC_EXTS else []
    if not found:
        return None
    last = found[-1]
    rest = stem[last.end():].lower()
    if rest:
        number = (row.get("Order or Receipt Number") or "").strip()
        told = sanitize_component(number).strip(" .").lower() if number else ""
        # An order number may itself end with what reads as a count.
        if (not (told or row.get(_LISTED))
                or not {rest, _NUMBERED.sub("", rest)} & {"", " " + told}):
            return None
    return (int(last.group(1)), int(last.group(2)))


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
    another document's. A file that rows of the index or records give to
    two purchases or documents keeps its name, since whose file it is
    cannot be told. That is a deleted file's name taken by a later
    download, whichever of the two kept its rows, and a record with
    another order number than its row."""

    def __init__(self, app, rows=()):
        self.records = {}      # the app's key -> what it knows of that document
        self._saved = {}       # the app's key -> what its records naming a file said
        self._by_file = {}     # a file -> each key whose records name it -> their spellings
        self._claims = {}      # the same with Target's invoices of an order as well
        self._stands_for = {}  # a rename view's copy of a record -> the record's key
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
            # Robinhood's and Newrez's rename views show a copy of a record
            # dated as its row now is, under a key of its own, and Robinhood
            # keeps a form it dated since under a new key. Each view says
            # which key stands for which, so the two count as one document.
            self._stands_for.update(getattr(store, "stand_ins", None) or {})
            for name, rec in data.items():
                if not isinstance(rec, dict):
                    continue
                merged = self.records.setdefault(name, {})
                merged.update({k: v for k, v in rec.items() if v not in (None, "")})
                raw = _text(rec.get("pdf_path"))
                where = self._file(raw)
                # Target keeps each invoice of an order split into several in
                # the record's invoices, and only one of them in pdf_path.
                # Target and Amazon name the others in its notes as well.
                invoices = rec.get("invoices")
                files = [_text(e.get("file")) if isinstance(e, dict) else ""
                         for e in (invoices if isinstance(invoices, list) else ())]
                for file in files + _also_saved(rec):
                    if self._file(file):
                        self._claims.setdefault(self._file(file), {}).setdefault(
                            name, set()).add(file)
                if where:
                    self._claims.setdefault(where, {}).setdefault(name, set()).add(raw)
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
        # A deleted file's name taken by a later download leaves two records
        # naming the file, or a record whose order number is not its row's
        # when the later one's record is gone. The later one's rows may never
        # have reached the index, open in Excel through its run, and the row
        # here was then the deleted one's, so the file was named for it.
        owners = {self._owner(n) for n, spelled in self._claims.get(where, {}).items()
                  if any(_one_file(s, raw) for s in spelled)}
        if key[0] == "order":
            owners.add(key)
        if len(owners) > 1:
            return None
        named = [n for n, spelled in self._by_file.get(where, {}).items()
                 if any(_one_file(s, raw) for s in spelled)]
        # A file only one record's list names is that record's, as the
        # workbook of a Wealthfront tax form is (_invoices_alone).
        if not named and len(owners) == 1:
            named = [n for n, spelled in self._claims.get(where, {}).items()
                     if any(_one_file(s, raw) for s in spelled)]
        if named:
            # Several records of one document naming one file is a rename's
            # own view at work. Robinhood and Newrez show it a copy of a
            # record dated as the row now is, beside the record itself, and
            # the copy is the one the row's own date and title name.
            if len(named) > 1:
                named = [n for n in named if n in self._by_key.get(key, ())]
            if len(named) != 1:
                return {}
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

    def told_apart_in_its_name(self, row: dict, rule: Callable[[dict], str],
                               before: Iterable[Callable[[dict], str]] = ()) -> str:
        """What the file of a row whose record cannot be told was told apart
        by, when its name already says so, and "" otherwise.

        Each document of the row's date and title is asked what its download
        adds to a name (`rule`), and the answer is the one of those the
        file's name ends with, as unique_path writes it, with or without a
        " (n)" after. Two different ones, or none, give "". A name that
        ends with what an earlier version of the app added for a document
        (`before`) is given what `rule` adds for that same document, its
        ending in today's words, as Anthem's " EOB1" became " EOB 1".

        A name never says whose file it is, and this does not ask it to. The
        file is still named from its row alone, never for any of these
        documents. Only what tells it apart is read, and only an ending the
        name already has, so a rename keeps that ending, or says it as the
        app says it today, and can add nothing the name did not say."""
        stem = Path((row.get("PDF Full Path") or "").strip()).stem
        stem = _NUMBERED.sub("", stem).lower()

        def ending(asked, record) -> str:
            told = str(asked(record) or "").strip()
            return sanitize_component(told).strip(" .") if told else ""

        ends = set()
        for name in self._by_key.get(_record_key(row), ()):
            record = self._view(name, True)
            token = ending(rule, record)
            if not token:
                continue
            said = [token] + [ending(older, record) for older in before]
            if any(e and stem.endswith(" " + e.lower()) for e in said):
                ends.add(token)
        return ends.pop() if len(ends) == 1 else ""

    def _owner(self, name: str):
        """Whose record the app's key `name` holds, shaped as _record_key
        shapes a receipt's row. A purchase is its order number, a document
        the provider's id it keeps or else its key, as _key_of_record has
        them, and a key a rename view says stands for another's record that
        record's owner."""
        seen = {name}
        while self._stands_for.get(name, name) not in seen:
            name = self._stands_for[name]
            seen.add(name)
        # As written down when the file was saved. A later listing writes
        # another statement's id over a document's in discovery at times.
        rec = self._saved.get(name) or self.records.get(name) or {}
        number = str(rec.get("order_number") or rec.get("document_id") or "").strip()
        return ("order", number) if number else ("key", name)

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
        raws += [_text(rec.get("pdf_path")) for rec in records.values()
                 if isinstance(rec, dict)]
        # Each invoice of a record's list as well, which update_progress
        # carries to where its file went (_follow_invoices).
        raws += [_text(e.get("file")) for rec in records.values()
                 if isinstance(rec, dict) and isinstance(rec.get("invoices"), list)
                 for e in rec["invoices"] if isinstance(e, dict)]
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


def _name_key(name: str) -> str:
    """A file's name as _same_file reads a path, in one case on Windows and
    macOS, so a note or a row spelling a name in another case than the file
    names that file there."""
    return name.lower() if os.name == "nt" or sys.platform == "darwin" else name


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
    # Each other invoice of an order renamed with its first. Said apart, so
    # the panel, which counts the receipts renamed by the lines saying
    # "Renamed", counts the receipts given a name, not every file.
    also: str = "    Also renamed -> "


WORDS = ReviewWords()

# What a person types to keep a receipt's name, which is never a summary.
# The panel's empty box once read "Keep this name", and typed into four
# boxes it renamed four receipts "... Keep This Name Invoice.pdf". The
# panel's own list (KEEP_WORDS in gui/static/app.js) is the same.
KEEP_WORDS = frozenset({
    "keep", "keep it", "keep this", "keep name", "keep the name", "keep this name",
    "keep its name", "keep same", "keep the same", "keep the same name", "same",
    "same name", "the same", "no change", "unchanged", "leave it", "leave as is",
    "leave blank", "leave it blank", "leave blank to keep this name",
})


def keeps_name(text) -> bool:
    """Whether a typed summary asks to keep the name rather than give one,
    read without case, punctuation or extra spaces."""
    if not isinstance(text, str):
        return False
    return " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split()) in KEEP_WORDS

# Apple and Uber, written after the rest, print the same without the colons.
PLAIN_WORDS = ReviewWords(current="    Current file  ", items="    Items  ",
                          question="    New summary (blank=keep, q=quit) ",
                          renamed="    Renamed to ", also="    Also renamed to ")


def held_receipt(row: dict, paths) -> Optional[Path]:
    """The receipt a row of the index names, when it is a PDF in a folder
    the app files receipts in, and None for anything else (held_document).

    A row written for a purchase with no receipt has an empty path, which
    reads as the folder the app runs in, and that folder exists. A new name
    typed for such a row had the app rename the folder it runs in, which no
    system allows, and the review stopped with a traceback partway through."""
    return held_document(row.get("PDF Full Path"), paths.filing_folders())


def _numbers_naming(rows: Iterable[dict], records: dict, lists: bool = True,
                    notes: bool = False) -> dict:
    """Each file the index rows and progress records name (_same_file of
    it), with each spelling naming it and the order number of the purchase
    whose row or record it is. A record's number is its order_number, or
    what its key, Purchase.key, has after the purchase type. A record names
    its pdf_path, and each file of its invoices as well, since Target keeps
    every invoice of an order split into several there and only one of them
    in pdf_path and the order's index row. Without `lists`, the list of
    invoices is left out. With `notes`, each other invoice its notes say was
    also saved is named too, Amazon's only record of them (_also_saved).
    Each comes with the list's entry that names it, or None for a row, a
    pdf_path or notes."""
    out = {}
    named = [((r.get("PDF Full Path") or "").strip(),
              (r.get("Order or Receipt Number") or "").strip(), None) for r in rows]
    for key, rec in records.items():
        if not isinstance(rec, dict):
            continue
        number = str(rec.get("order_number") or str(key).partition(":")[2]).strip()
        invoices = rec.get("invoices") if lists else None
        named.append((_text(rec.get("pdf_path")), number, None))
        named += [(_text(e.get("file")), number, e) for e in (
            invoices if isinstance(invoices, list) else ()) if isinstance(e, dict)]
        if notes:
            named += [(raw, number, None) for raw in _also_saved(rec)]
    for raw, number, entry in named:
        where = _same_file(raw) if raw else ""
        if where:
            out.setdefault(where, []).append((raw, number, entry))
    return out


def _say_review_undone(e: BaseException, writing: str, moved: bool, stuck: list,
                       unwritten: list, earlier: bool, renaming: bool = False) -> None:
    """What Review Names says when a write for a receipt failed and what it
    had done for that receipt was undone (_undo). `moved` says the receipt
    was renamed, `stuck` and `unwritten` are what _undo could not put back,
    and `earlier` says receipts renamed before it in this review were
    written down. With `renaming`, it was stopped while the other invoices
    of the receipt's order were renamed, before anything was written."""
    if renaming:
        what = ("Review Names was stopped while it renamed the other invoices of the order"
                if isinstance(e, KeyboardInterrupt) else
                "The other invoices of the order could not be renamed (%s)" % type(e).__name__)
    elif isinstance(e, KeyboardInterrupt):
        what = "Review Names was stopped while it wrote %s" % writing
    else:
        what = "%s could not be written (%s)" % (writing, type(e).__name__)
    print()
    if stuck:
        print("%s, and the receipt could not be put back under the name it had, so rename "
              "it back to that by hand." % what)
        for where, old in stuck:
            print("  %s" % where.name)
            print("    back to %s" % old.name)
    elif moved:
        print("%s, so the receipt was put back under the name it had." % what)
    else:
        print("%s, so the receipt keeps the name it had." % what)
    for csv in unwritten:
        print("%s could not be put back either, so it still has what was written for this "
              "receipt." % _name_of(csv))
        if getattr(csv, "backups_dir", None):
            print("The copy it had before Review Names started is in the Backups folder.")
    if earlier:
        print("Each receipt renamed before it keeps its new name, written down as it was "
              "renamed.")
    if isinstance(e, PermissionError):
        print("Close any program that has %s open and run Review Names again." % writing)


def named_by_another(rows: Iterable[dict], records: dict, lists: bool = True,
                     claims: Optional[Callable[[dict, str], bool]] = None,
                     notes: bool = False) -> Callable[[str, str], bool]:
    """Whether a file is named by an index row or progress record of
    another purchase than the one whose order number is given, asked as
    another(path, number). A record names its pdf_path and each file of its
    list of invoices (_numbers_naming), or only its pdf_path without
    `lists`, since rows and pdf_path follow every rename and a list an
    earlier rename left behind may name an old file. With `notes`, a record
    names each other invoice its notes say was also saved as well.
    `claims(entry, path)`, when given, says whether another purchase's list
    entry naming the file is a claim on it, asked only of a file asked
    about. Two spellings are one file only when they are shown to be
    (_one_file)."""
    numbers = _numbers_naming(rows, records, lists, notes)

    def another(raw: str, number: str) -> bool:
        raw = str(raw or "").strip()
        number = str(number or "").strip()
        where = _same_file(raw) if raw else ""
        return bool(where) and any(
            n != number and _one_file(r, raw)
            and (entry is None or claims is None or claims(entry, raw))
            for r, n, entry in numbers.get(where, ()))
    return another


def _review_others(record: dict, row: dict, path: Path, folders,
                   claimed: Callable[[str, str], bool]) -> List[Path]:
    """The other invoices of the order whose first invoice, `path`, a row
    offered for review names, which a new name for it renames as well.

    Only when the purchase's record names `path`, since an older copy of a
    purchase is not the first of the invoices its record lists. Each is a
    PDF the app holds (held_document) whose name says which invoice of the
    order it is (_part_of), since its new name keeps that part, and that no
    other purchase's rows, record, list of invoices or notes name, since
    whose invoice it is cannot be told then (`claimed`)."""
    recorded = _text(record.get("pdf_path")) if isinstance(record, dict) else ""
    if not recorded or str(Path(recorded)) != str(path):
        return []
    number = _number_of(row)
    out = []
    for raw in _other_invoices(record, str(path)):
        held = held_document(raw, folders)
        if (held is None or claimed(raw, number)
                or _part_of({"PDF Filename": held.name,
                             "Order or Receipt Number": number}) is None):
            continue
        out.append(held)
    return out


def _shown_renamed(new: Path, old: Path, home) -> str:
    """A new name as Review Names says it, with the folders a pattern filed
    the file in, inside the folder it is filed in, when it went to another
    folder."""
    if not _same_folder(new.parent, old.parent):
        return Path(os.path.relpath(new, home)).as_posix()
    return new.name


# The control panel has no console to ask in, so it asks Review Names in two
# steps through these, each naming a file in a folder of the panel's own.
# The first has the review write the receipts it would ask about to that
# file and rename nothing. The second hands it the new summaries a person
# typed in the panel, and only the receipts given one are renamed, by the
# same rules as a review in a console. The panel sets them for the run it
# starts and nothing else does, which is how PaperPull Server, with no
# console at all, reviews names.
REVIEW_LIST_ENV = "PAPERPULL_REVIEW_LIST"
REVIEW_ANSWERS_ENV = "PAPERPULL_REVIEW_ANSWERS"
# The longest summary taken from the panel. A file name keeps the room it
# needs for the date, the provider and the kind (unique_path cuts the rest).
SUMMARY_MAX = 120


def _one_line(text: str) -> str:
    """Text as one line, without control characters, with single spaces."""
    return " ".join("".join(c for c in text if c.isprintable() or c.isspace()).split())


def _number_of(row: dict) -> str:
    return (row.get("Order or Receipt Number") or "").strip()


def _write_review_list(where: Path, app, review: list) -> None:
    """The receipts a review would ask about, written for the control panel
    to show. Each is known by its file as the review finds it, with its
    order number, so a new name comes back for that file and that purchase
    and no other. Written beside itself and then moved into place, so the
    panel never reads half of it."""
    out = []
    for r, path in review:
        key = f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}"
        prog = app.progress.get(key) or {}
        items = prog.get("items")
        items = [_text(i.get("name")) for i in (items if isinstance(items, list) else ())
                 if isinstance(i, dict)][:10]
        out.append({"id": str(path), "number": _number_of(r),
                    "date": _text(r.get("Purchase Date")),
                    "confidence": _text(r.get("Classification Confidence")),
                    "status": _text(r.get("Processing Status")),
                    "file": path.name, "summary": _text(r.get("Purchase Summary")),
                    "items": [i for i in items if i]})
    part = where.with_name(where.name + ".part")
    with shared_folder.open_to_write(part, "w", encoding="utf-8") as f:
        f.write(json.dumps({"receipts": out}))
    os.replace(part, where)


def _panel_answers(raw: str) -> dict:
    """The new summaries the control panel handed over, by (file, order
    number). A blank one keeps its name, so it is left out. A file that
    cannot be read stops the review before anything is renamed."""
    try:
        data = whole_json(json.loads(Path(raw).read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        print("The new names from the control panel could not be read (%s), so nothing "
              "was renamed." % type(e).__name__)
        raise SystemExit(1)
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        print("The new names from the control panel were not a list, so nothing was renamed.")
        raise SystemExit(1)
    out = {}
    for a in answers:
        if not isinstance(a, dict):
            continue
        rid, number, summary = a.get("id"), a.get("number"), a.get("summary")
        if not (isinstance(rid, str) and isinstance(number, str) and isinstance(summary, str)):
            continue
        summary = _one_line(summary)[:SUMMARY_MAX].strip()
        # Words that ask to keep the name keep it, as a blank box does.
        if rid and summary and not keeps_name(summary):
            out[(rid, number.strip())] = summary
    return out


def review_names(app, ask, words: ReviewWords = WORDS,
                 record_for: Optional[Callable[[str, dict], dict]] = None) -> None:
    """Ask for a better name for each receipt the app was unsure of, and
    rename the file to it.

    One function for every receipt app, so what may be renamed is decided
    once. `ask` is the app's own, which stops cleanly when no console is
    attached. `record_for(key, record)` gives the record a new name is
    built from, for an app that knows more than its progress record holds.
    Without it the progress record is used.

    Only a receipt the app holds is offered (held_receipt), each file once,
    and not a file another purchase's index rows or progress record name as
    well, since whose receipt it is cannot be told. The summary a file
    already has leaves it where it is. A rename that fails is said, that
    receipt keeps its name, and the review goes on. Each rename is written
    to both CSVs and progress.json as it happens, so they name the files as
    they are on disk however the review ends. Closing the console window
    ends the process at once, with nothing run after it, so writing at the
    end would not be enough.

    Each of those three is shown to be writable before the first question,
    and when one stays held, nothing is asked and nothing is renamed. When a
    write still fails after a receipt was renamed, that receipt goes back
    under the name it had, never over another file, what was written for it
    is written back, and the review says so and stops, with SystemExit(1)
    when the file system refused the write and with the error itself
    otherwise, Ctrl+C included (_undo).

    A new name marks a receipt Completed only when its record says it was
    saved, with downloaded_ok. One put aside because its PDF failed its
    check keeps the state its run gave it. A purchase's record takes a new
    name only when it names the file renamed, or when there is none yet,
    so an older copy of a purchase whose record names another copy leaves
    that record as it is.

    The first invoice of an order split into several takes the order's
    other invoices with it, each with its own part, and the order's notes,
    rows and list of invoices name them as they are now (_review_others).
    One that cannot be renamed keeps its name and is said, and everything
    still names it there. A write that fails puts every one of them back.

    Run by the control panel, REVIEW_LIST_ENV has it write the receipts it
    would ask about and rename nothing, and REVIEW_ANSWERS_ENV has it take
    the new summaries from the panel instead of asking. A summary given for
    a file no longer waiting for review, or for another purchase's file, is
    said and left alone."""
    listing = os.environ.get(REVIEW_LIST_ENV, "").strip()
    answered = os.environ.get(REVIEW_ANSWERS_ENV, "").strip()
    answers = _panel_answers(answered) if answered and not listing else None
    rows = app.index_csv.read_all()
    another = named_by_another(rows, getattr(app.progress, "data", None) or {})
    # A row somebody already renamed is left out, even one renamed before
    # its confidence was marked High as well (#47).
    review, offered, left_out, shared = [], set(), 0, 0
    for r in rows:
        unsure = (r.get("Classification Confidence") == "Low"
                  or "Review" in (r.get("Processing Status") or ""))
        if not unsure or REVIEWED in (r.get("Notes") or ""):
            continue
        path = held_receipt(r, app.paths)
        if path is None:
            left_out += 1
        elif another(str(path), r.get("Order or Receipt Number")):
            # A file deleted once it was imported elsewhere leaves its name
            # free, and a later purchase of the same day and summary is
            # saved under it. Whose receipt the file is cannot be told, and
            # a new name for the older purchase's row renamed the later
            # one's file and left the later one's rows and record naming a
            # file that was gone.
            shared += 1
        elif str(path) not in offered:
            offered.add(str(path))
            review.append((r, path))
    if left_out:
        print(f"{left_out} row(s) marked for review have no receipt PDF in this "
              "app's folders to rename, so they are left out.")
    if shared:
        print(f"{shared} row(s) marked for review name a file that another purchase's "
              "rows or record also name, so whose receipt it is cannot be told and "
              "they are left out.")
    if listing:
        _write_review_list(Path(listing), app, review)
        print(f"{len(review)} receipt(s) need review." if review
              else "No receipts need name review.")
        return
    if not review:
        print("No receipts need name review.")
        return
    if answers is not None:
        # Only the receipts given a new name, each for the very file and
        # purchase it was shown for. The rest keep their names, as Enter
        # keeps one in a console.
        given = [(r, p) for r, p in review if (str(p), _number_of(r)) in answers]
        stale = len(answers) - len(given)
        if stale:
            print(f"{stale} new name(s) were for receipts no longer waiting for review, so "
                  "nothing was done with them. Open Review names again to see the list as "
                  "it is now.")
        if not given:
            print("No receipt was given a new name, so nothing was renamed.")
            return
        review = given
    order_rows = app.order_csv.read_all()
    # Each new name is written into the index, the order history and
    # progress.json just after its file is renamed, so each has to be one
    # that can be written before a file moves. With the index open in Excel
    # a receipt was renamed and the index kept the name it had, so Verify
    # reported the file missing. Waiting the minute a write waits, while
    # nothing has moved, lets a person close it, and when one stays open
    # nothing is asked and nothing is renamed.
    held = [p for p in _ledger_files(app, [(app.index_csv, rows), (app.order_csv, order_rows)])
            if not free_to_write(p)]
    if held:
        them = "it" if len(held) == 1 else "them"
        print()
        print("Nothing was renamed, since %s could not be written, and Review Names writes "
              "each new name into %s as it renames. Close any program that has %s open and "
              "run Review Names again." % (_listed([p.name for p in held]), them, them))
        raise SystemExit(1)
    if answers is not None:
        print(f"Renaming {len(review)} receipt(s) given a new name.\n")
    else:
        print(f"{len(review)} receipt(s) need review. Enter a new summary, "
              "press Enter to keep, or 'q' to stop.\n")
    # The folder each receipt is filed in, inside which a naming pattern's
    # folders are, as Rename and a download have them (#101). One put aside
    # in Manual Review stays there, with no folders.
    folders = app.paths.filing_folders()
    homes = _Homes(folders, [f for f in (getattr(app.paths, "manual_review", None),)
                             if f is not None])
    # The other invoices of each order whose first invoice a receipt offered
    # is, found before anything is renamed, so a file this review gives a
    # name is never taken for another order's invoice (_review_others).
    claimed = named_by_another(rows, getattr(app.progress, "data", None) or {}, notes=True)
    others = {str(p): _review_others(
        app.progress.get(f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}") or {},
        r, p, folders, claimed) for r, p in review}
    carried = set()         # each other invoice renamed with the first of its order
    written = stopped = False
    try:
        for r, old_path in review:
            if _same_file(str(old_path)) in carried:
                # An other invoice of an order, with an index row of its own
                # marked for review, renamed with the first of the order.
                print(f"  {r.get('Purchase Date')}  #{r.get('Order or Receipt Number')}")
                print("    It was renamed with the other invoices of its order.\n")
                continue
            key = f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}"
            prog = app.progress.get(key) or {}
            # A list of mappings, each name text, as a damaged record's items
            # stopped the review here (_text).
            items = prog.get("items")
            items = [_text(i.get("name")) for i in (items if isinstance(items, list) else ())
                     if isinstance(i, dict)][:10]
            print(f"  {r.get('Purchase Date')}  #{r.get('Order or Receipt Number')}"
                  f"  [{r.get('Classification Confidence')}]")
            print(f"{words.current}{r.get('PDF Filename')}")
            if items:
                print(f"{words.items}{'; '.join(items)}")
            if answers is not None:
                # Typed in the panel, where "q" is a summary like any other.
                new = answers[(str(old_path), _number_of(r))]
                print(f"    New summary: {new}")
            else:
                new = ask(words.question).strip()
                if new.lower() == "q":
                    break
            if keeps_name(new):
                print("    That keeps its name.\n")
                continue
            if not new:
                print()
                continue
            new_summary = title_case(new)
            date = r.get("Purchase Date") or old_path.name[:10]
            doc_type = r.get("Document Type") or "Receipt"
            record = record_for(key, prog) if record_for else prog
            # The "(1 of 2)" of an order split into several invoices, read
            # from the file as Rename reads it. Left out, the first invoice
            # was renamed as though it were the whole order, and no Rename
            # could put it back, since the name it reads the part from had
            # lost it.
            new_name = build_pdf_filename(date, new_summary, doc_type, part=_part_of(r),
                                          record=record)
            # The ledgers as they are before this receipt, and the file it
            # moves, so a write that fails can undo what was done for it.
            records = _records_of(app.progress)
            rows_before = [dict(row) for row in rows]
            order_rows_before = [dict(orow) for orow in order_rows]
            moved = Result()
            # The purchase's record says what a run fetches, and it speaks
            # for this file only when it names it, or when there is no
            # record yet. An older copy, put aside before a later run saved
            # the receipt or put aside a newer copy, keeps rows of its own,
            # and only those take its new name. Written into the record, it
            # moved the record off the copy the last run left.
            # A record whose path is not text names no file, as an empty
            # one names none (_text). Handed to Path, it stopped the review
            # with the receipt renamed and its record never written.
            recorded = prog.get("pdf_path")
            if not isinstance(recorded, (str, os.PathLike)):
                recorded = ""
            ours = not prog or str(Path(recorded)) == str(old_path)
            # The other invoices of the order, when this is its first, which
            # take the new name with it (_review_others, which asked the
            # record before anything moved). One deleted since the review
            # began is not there to rename.
            siblings = [s for s in others.get(str(old_path), ()) if s.is_file()]
            # Each entry of the record's list of invoices naming this file or
            # one of those, however it is spelled, with the file it names,
            # told while the files are there to be compared, since afterwards
            # two spellings that read alike may be two files where a folder
            # tells case apart.
            invoices = prog.get("invoices")
            listed = {_text(e.get("file"))
                      for e in (invoices if isinstance(invoices, list) else ())
                      if isinstance(e, dict)}
            spelled = {}
            for file in [old_path] + siblings:
                spelled.update({raw: str(file) for raw in listed
                                if raw and raw not in spelled and _one_file(raw, str(file))})
            # And each index row of the purchase naming one of the other
            # invoices, however it spells it, told the same way. The list
            # may spell an invoice in another case than its row does.
            rowed = {}
            for row in rows:
                text = (row.get("PDF Full Path") or "").strip()
                if row.get("Order or Receipt Number") == r.get("Order or Receipt Number") and text:
                    rowed.update({text: str(s) for s in siblings
                                  if text not in rowed and _one_file(text, str(s))})
            home, new_name = homes.placed(old_path, new_name)
            try:
                # The file does not stand in its own way. Asked for a free
                # name as though it were another file's, the summary it
                # already had moved it to "... (2).pdf", and the next Rename
                # offered to move it back. It stands in its own way only in
                # the folder it is in, since one of its name in a pattern's
                # folder is another file.
                # A name another order's file has is told apart by the order
                # number, as a download and Rename tell it. Told apart by
                # " (2)", the next Rename moved the file again, and the first
                # invoice of a split order lost its part on the way.
                new_path = unique_path(home, new_name,
                                       app.config["max_path_length"],
                                       distinguisher=(r.get("Order or Receipt Number")
                                                      or "").strip(),
                                       ignoring=old_path, make=False)
                if (new_path.name != old_path.name
                        or not _same_folder(new_path.parent, old_path.parent)):
                    # unique_path compares names in one case, so a folder
                    # that tells case apart can hold another file of the
                    # name a change of case gives, which a rename there
                    # would replace.
                    # A link whose file is gone has the name as well.
                    if (os.path.lexists(new_path)
                            and not _one_file(str(new_path), str(old_path))):
                        raise FileExistsError(17, "Another file has that name", str(new_path))
                    _make_folders(new_path.parent, moved)
                    old_path.rename(new_path)
                    moved.mapping[str(old_path)] = str(new_path)
                elif not old_path.is_file():
                    # Deleted while the question waited. A rename would have
                    # failed, and the rows would be marked for a file gone.
                    raise FileNotFoundError(2, "The file is no longer there", str(old_path))
            except (OSError, ValueError) as e:
                # A folder made for it and left empty goes too.
                tidy(moved, folders)
                print(f"    It could not be renamed ({type(e).__name__}), so it keeps "
                      "its name.\n")
                continue
            # Then each other invoice of the order, by the same rules, with its
            # own part read from its own name as Rename reads it. Left behind,
            # a new summary reached part of the order, and someone looking for
            # the order by it found the rest under the name it had before. One
            # that cannot be renamed, held open by another program, keeps its
            # name, and the record, the rows and the notes still name it
            # there, so the next Rename, which names it from the record, finds
            # it and gives it the new name. Amazon's notes name it in the
            # folder of the first, so where a pattern's folders took the first
            # to another folder, only Target's list still leads Rename to it.
            told = (r.get("Order or Receipt Number") or "").strip()
            also, refused = {}, []
            try:
                for sibling in siblings:
                    part = _part_of({"PDF Filename": sibling.name,
                                     "Order or Receipt Number": told})
                    place, name = homes.placed(sibling, build_pdf_filename(
                        date, new_summary, doc_type, part=part, record=record))
                    try:
                        target = unique_path(place, name, app.config["max_path_length"],
                                             distinguisher=told, ignoring=sibling, make=False)
                        if (target.name == sibling.name
                                and _same_folder(target.parent, sibling.parent)):
                            continue
                        if os.path.lexists(target) and not _one_file(str(target), str(sibling)):
                            raise FileExistsError(17, "Another file has that name", str(target))
                        _make_folders(target.parent, moved)
                        sibling.rename(target)
                    except (OSError, ValueError) as e:
                        refused.append("    %s could not be renamed (%s), so it keeps its name."
                                       % (sibling.name, type(e).__name__))
                        continue
                    moved.mapping[str(sibling)] = str(target)
                    also[sibling] = (target, place)
            except BaseException as e:
                # Stopped while the other invoices moved, by Ctrl+C, with
                # nothing written down for this receipt yet. Every file of it
                # goes back under the name it had, since the ledgers still
                # name each so, and left renamed, the first was a file Verify
                # reported missing and no Rename could find again.
                stopped = True
                stuck = put_back(moved)
                tidy(moved, folders)
                _say_review_undone(e, "", bool(moved.mapping), stuck, [], written,
                                   renaming=True)
                raise
            # Where each file of this receipt is now, and the new name of each
            # other invoice of the order renamed, which its notes name it by,
            # read in one case where the file system ignores case.
            went_to = {str(old_path): new_path}
            went_to.update({str(s): w for s, (w, _place) in also.items()})
            renamed = {_name_key(s.name): w.name for s, (w, _place) in also.items()}

            def names(name) -> Optional[str]:
                return renamed.get(_name_key(name)) if isinstance(name, str) else None
            # The index first, then the order history, then progress.json,
            # as Rename writes them. A file left renamed when the index could
            # not be written, opened in Excel after the check above, kept the
            # name it had in the index, so Verify reported it missing and the
            # next run was confused. Now the receipt goes back under the name
            # it had and what was written for it is written back (_undo).
            done, writing = [], _name_of(app.index_csv)
            try:
                number = r.get("Order or Receipt Number")
                old_filename = r.get("PDF Filename")
                # Completed is for a receipt that was saved and marked for
                # review for its name alone, which its record says with
                # downloaded_ok. A receipt put aside in Manual Review because
                # its PDF failed its check has none, and marked Completed no
                # run fetched it again, though its copy was the one that failed.
                saved = ours and bool(prog.get("downloaded_ok"))
                # Every index row of this purchase naming this file follows it.
                # Target once wrote two for most invoice orders, and the one not
                # renamed named a file that was gone. A row of another purchase
                # is left as it is, since its other records are not this one's.
                # A row naming another invoice of the order renamed with it
                # follows that, and every row of the purchase names those in
                # its notes as they are now.
                for row in rows:
                    if row.get("Order or Receipt Number") != number:
                        continue
                    notes = _follow_also_saved(row.get("Notes"), names)
                    if notes is not None:
                        row["Notes"] = notes
                    text = (row.get("PDF Full Path") or "").strip()
                    went = (went_to.get(str(Path(text))) or went_to.get(rowed.get(text, ""))
                            if text else None)
                    if went is None:
                        continue
                    row["PDF Filename"] = went.name
                    row["PDF Full Path"] = str(went)
                    row["Purchase Summary"] = new_summary
                    if saved:
                        row["Processing Status"] = "Completed"
                    row["Classification Confidence"] = "High"
                    row["Notes"] = (row.get("Notes", "") + "; " + REVIEWED).strip("; ")
                app.index_csv.rewrite(rows, backup=not written)
                done.append((app.index_csv, rows_before))
                writing = _name_of(app.order_csv)
                for orow in order_rows:
                    if orow.get("Order or Receipt Number") != number:
                        continue
                    notes = _follow_also_saved(orow.get("Notes"), names)
                    if notes is not None:
                        orow["Notes"] = notes
                    filename = orow.get("PDF Filename")
                    went = (new_path.name if filename == old_filename
                            else names(filename) if filename else None)
                    if not went:
                        continue
                    orow["PDF Filename"] = went
                    orow["Purchase Summary"] = new_summary
                    if saved:
                        orow["Processing Status"] = "Completed"
                app.order_csv.rewrite(order_rows, backup=not written)
                done.append((app.order_csv, order_rows_before))
                # An entry of the record's list of invoices naming one of these
                # files follows it, whether or not the record speaks for it
                # otherwise, since it names that very file (_follow_invoices).
                invoices = _follow_invoices(invoices, lambda raw: (
                    str(went_to[spelled[raw]]) if spelled.get(raw) in went_to else None))
                if ours:
                    writing = _name_of(app.progress)
                    named = {"summary": new_summary, "pdf_filename": new_path.name,
                             "pdf_path": str(new_path), "confidence": "High"}
                    if saved:
                        named["state"] = State.COMPLETED.value
                    if invoices is not None:
                        named["invoices"] = invoices
                    notes = _follow_also_saved(prog.get("notes"), names)
                    if notes is not None:
                        named["notes"] = notes
                    app.progress.update(key, named)  # key (purchase identifier) unchanged
                elif invoices is not None:
                    writing = _name_of(app.progress)
                    app.progress.update(key, {"invoices": invoices})
            except BaseException as e:
                stopped = True
                stuck, unwritten = _undo(records, done, moved)
                # Back in its own folder, a folder made for it goes with it.
                tidy(moved, folders)
                _say_review_undone(e, writing, bool(moved.mapping), stuck, unwritten, written)
                if isinstance(e, OSError):
                    raise SystemExit(1) from e
                raise
            written = True
            carried.update(_same_file(str(s)) for s in also)
            # Written down where it is now, so a folder it left empty goes.
            tidy(moved, folders)
            if str(old_path) not in moved.mapping:
                said = ["    It already has that name, so the file stays as it is."]
            else:
                said = [words.renamed + _shown_renamed(new_path, old_path, home)]
            said += [words.also + _shown_renamed(w, s, place)
                     for s, (w, place) in also.items()]
            print("\n".join(said + refused) + "\n")
    finally:
        # Said by the review's own words instead when a write failed.
        if written and not stopped:
            print("CSV files and progress.json updated.")
