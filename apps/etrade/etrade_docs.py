"""E*TRADE statement and tax document downloader (local, supervised). CONFIRMED on a tester's account, see etrade_site.py.

This app was written without a E*TRADE account so that someone who holds one
can test it without writing code. The orchestrator below is the same one
every other statement app runs on. What has not been proven is the site layer,
etrade_site.py, which carries every guess about etrade.com and says which ones
most need a survey. Run --diagnose first and attach the Diagnostics file
to the GitHub issue. It takes no screenshot and masks digit runs.

Usage:
    python etrade_docs.py --login       verify connection to your browser
    python etrade_docs.py --discover    list available documents
    python etrade_docs.py --pilot       download the 5 newest, then stop
    python etrade_docs.py --all         download everything in scope
    python etrade_docs.py --resume      continue an interrupted run
    python etrade_docs.py --verify      re-validate every saved PDF
    python etrade_docs.py --diagnose    dump page structure (no downloads)
    python etrade_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement|"Tax Document"

READ-ONLY: this tool only reads the documents page and saves the PDFs E*TRADE
already generated. It never transfers, pays, sends money, opens
or closes anything, or changes any account setting. Everything stays on this machine; nothing is
sent to any external service.
"""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import pressing
from paperpull_core import capture
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import (NEW_LIST_NOTE, NOTHING_OPENED, NOTHING_RECORDED,
                                          lists_what_it_saved, report_run_result)

import argparse
import hashlib
import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import doc_types, receipt_pdf
from paperpull_core import browser as browser_launcher
import etrade_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import is_done as _is_done
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("etrade_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One E*TRADE document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", guid="", whole_label=False, entry="", **kw):
        self.title = title
        # What the list's Account column shows for the document, kept whole
        # for {account} and, when the sign-in has more than one account, the
        # summary (#96). Never written to a log.
        self.account = account
        # The list's own ids, "<documentGuid>|<documentId>". Kept apart from
        # document_id, which would make the key the id alone.
        self.guid = guid
        # Whether the key holds the whole label rather than its masked tail,
        # set when another label shows the same tail on a document of the
        # same date and title, where the tail cannot keep the keys apart.
        self.whole_label = bool(whole_label)
        # What tells a document the list gave no account from another of
        # the same date and title it gave none, set only then, so every
        # other key stays what it was (site.RawDoc.entry, #96).
        self.entry = entry
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        self.document_id = document_id  # unused, the date is the identity
        self.source_url = kw.get("source_url", "")  # page where the doc's download link lives
        # Sticky "was successfully downloaded at least once" marker. Once set,
        # the document is never re-downloaded even if you delete the PDF (e.g.
        # after importing it into paperless-ngx).
        self.downloaded_ok = kw.get("downloaded_ok", False)
        self.href = href
        self.row_index = row_index
        self.confidence = confidence
        self.state = kw.get("state", State.DISCOVERED.value)
        self.pdf_filename = kw.get("pdf_filename", "")
        self.pdf_path = kw.get("pdf_path", "")
        self.pdf_size = kw.get("pdf_size", "")
        self.pdf_pages = kw.get("pdf_pages", "")
        # What the saved PDF's bytes hash to, so another record's document
        # of the same date with the same bytes is known for what it is even
        # once this file has been deleted (#96).
        self.pdf_sha256 = kw.get("pdf_sha256", "")
        # What the download told this file apart by, written when it is
        # saved, so Rename tells it apart the same way (told_apart_by).
        self.told_apart = kw.get("told_apart", "")
        self.notes = kw.get("notes", "")
        self.discovered_at = kw.get("discovered_at", now_iso())

    @property
    def key(self) -> str:
        """Stable identity. Category, date, title and account. The list is
        read from the page, so there is no document id to store, and a
        document's date and kind tell one from the next, and its account
        one account's statement of the day from another's (#96).

        The account part is the masked last digits the list's label shows,
        "1234" for "Individual Brokerage -1234", since the words before them
        are a nickname a person can change on E*TRADE, and a key that moved
        with the nickname would download every statement again. A label
        with no masked digits is kept whole, and so is one whose tail
        another label shows on a document of the same date and title
        (whole_label), so the two never share a key. Until #96 the account never reached the record,
        so every key ended in "Unnamed", and adopt_account_keys moves those
        for a sign-in of one account, and relabel_by_statement, by what
        each one's saved PDF shows, for a sign-in of several.

        A document whose date, title and account another document shares,
        the list giving both no account or the same one, adds a digest of
        its entry, "Unnamed#<12 hex>" or "1234#<12 hex>", since otherwise
        they had one key and all but one were dropped (#96, and one
        account's two documents of a day once accounts were read, review).
        Every other document has no entry and keeps its key."""
        if self.document_id:
            return f"id:{self.document_id}"
        acct = account_key(self.account, whole=self.whole_label)
        if self.entry:
            acct = "%s#%s" % (acct, hashlib.sha256(self.entry.encode("utf-8")).hexdigest()[:12])
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


# A key that holds an account's whole label holds it up to this long.
WHOLE_LABEL_LIMIT = 80


def account_key(label: str, whole: bool = False) -> str:
    """The account part of a key, from the label the list's Account column
    shows. Its masked tails, "1234", or "1234+5678" for a document of two
    accounts, else, or when `whole`, the whole label (whole_label_key). For
    no account it is what the key always held, "Unnamed", so a document the
    list gives no account keeps the key it had."""
    label = re.sub(r"\s+", " ", label or "").strip()
    if not label:
        return _account_component(sanitize_component(label))
    tails = site.account_tails(label)
    if tails and not whole:
        return "+".join(tails)
    return whole_label_key(label)


def whole_label_key(label: str) -> str:
    """An account's whole label as a key holds it, never cut. Cut to forty
    characters and its last four, as the core keeps an account short, two
    accounts sharing their last four and their first forty characters, with
    statements of one date and title, had one key, and the second one's
    statement was recorded under the first one's summary and file name
    (release review of 0.53.0). A label longer than WHOLE_LABEL_LIMIT, or
    one a file name could not hold as it is, keeps its first forty
    characters and a digest of the whole label, so the key stays short and
    the same on every run, and two labels that differ anywhere differ in
    it."""
    tidy = re.sub(r"\s+", " ", label or "").strip()
    whole = sanitize_component(tidy, max_len=len(tidy) + 20)
    if whole == tidy and len(whole) <= WHOLE_LABEL_LIMIT:
        return whole
    digest = hashlib.sha256(tidy.encode("utf-8")).hexdigest()[:12]
    return "%s#%s" % (whole[:40].rstrip(), digest)


def told_apart_by(record: dict) -> str:
    """What a document's file adds to its name when another file already
    has that name, the same on every run. The last six characters of the
    id a record keeps, which an E*TRADE record never has, else what the
    download wrote down when it saved the file, the masked digits of its
    account, so of two accounts' statements under a pattern that leaves the
    account out, the second says whose it is rather than " (2)" (#96). A
    file saved before was told apart by " (2)" and its record says nothing,
    so Rename leaves it so. The download and Rename both ask this, so a
    rename tells a file apart the way its download did."""
    record = record if isinstance(record, dict) else {}
    return str(record.get("document_id") or "")[-6:] or str(record.get("told_apart") or "")


def legacy_key(doc: "Document") -> str:
    """The key a document had before its account reached the record (#96),
    the same category, date and title with no account, which the key
    writes as "Unnamed"."""
    return Document(category=doc.category, date=doc.date, title=doc.title).key


def _by_old_key(listed) -> dict:
    """The listed documents by the key each had before #96 (legacy_key)."""
    by_old: dict = {}
    for doc in listed:
        group = by_old.setdefault(legacy_key(doc), [])
        if doc.key not in {d.key for d in group}:
            group.append(doc)
    return by_old


def adopt_account_keys(records: dict, listed) -> int:
    """Move the records kept before the account reached them to the key
    their account gives them, for a sign-in of one account, after
    discovery has read the lists (#96).

    Until #96 every key ended in "Unnamed", no account. Each record still
    under such a key is moved to the key of the one document the lists now
    give that category, date and title, and takes its account and guid. Its
    state, downloaded_ok, pdf_path, summary and everything else go with
    it, so a statement saved before is never fetched again and its file
    keeps its name. When a record already sits under the new key, the one
    that holds the document more firmly stays (_standing), done before not
    done, then naming a file that is there before naming none, and when
    they hold it alike, the one already there. Matched by key alone, so a
    history moved with --minimal, which keeps no title or date in a record
    but keeps its state, downloaded_ok and pdf_path, moves the same.

    Only ever run for a sign-in whose lists name one account. With more
    than one, a record kept before may hold either account's statement,
    since two accounts' statements of one title and day were one record,
    and lists that left one account's statement out would credit it to
    the other (review of #96). Returns how many records moved."""
    changed = 0
    for old_key, docs in _by_old_key(listed).items():
        rec = records.get(old_key)
        if not isinstance(rec, dict) or len(docs) != 1:
            continue
        doc = docs[0]
        new_key = doc.key
        if new_key == old_key:
            continue
        firmer = _standing(records, old_key) > _standing(records, new_key)
        rec = dict(rec, account=doc.account, guid=doc.guid)
        if not isinstance(records.get(new_key), dict) or firmer:
            records[new_key] = rec
        del records[old_key]
        changed += 1
    return changed


# A key 0.56.0 gave a document the list gave no account whose date and
# title another such document shared, the key of no account and a digest,
# "<category>:<date>:<title>:Unnamed#<12 hex>". The digest is of its entry,
# its place among them, "#1", "#2", or in 0.56.0, the list's own ids for it,
# which change every time the list loads.
_UNNAMED_DIGEST_RE = re.compile(r"^(?P<legacy>.*:Unnamed)#(?P<digest>[0-9a-f]{12})$")
_PLACES = frozenset(hashlib.sha256(("#%d" % n).encode("utf-8")).hexdigest()[:12]
                    for n in range(1, 1000))


def keyed_by_ids(key: str, record) -> str:
    """The key of no account (legacy_key) a record 0.56.0 kept under the
    list's own ids sits beside, or "" for any other record. Read off the key
    alone, a key of no account and a digest of no place. Only a document
    with no account and an entry gets such a key (Document.key), so nothing
    else in the record can say otherwise, and a history moved with
    --minimal, which keeps neither the account nor the entry, is read the
    same."""
    m = _UNNAMED_DIGEST_RE.match(key or "")
    if not m or not isinstance(record, dict) or m.group("digest") in _PLACES:
        return ""
    return m.group("legacy")


def placed(key: str, record) -> str:
    """The key of no account a record kept by its place, "#1" or "#2",
    sits beside, or "" for any other record. Read off the key alone, as
    keyed_by_ids is."""
    m = _UNNAMED_DIGEST_RE.match(key or "")
    if not m or not isinstance(record, dict) or m.group("digest") not in _PLACES:
        return ""
    return m.group("legacy")


def _first_to_keep(records: dict, keys) -> str:
    """Of these records of one document, the one that stays. One that is done
    (keys.is_done), then one naming a file that is there (_held_under), then
    the first discovered, and of those one Discover listed together, the one
    whose file has the shortest name, "Statement.pdf" before "Statement
    (2).pdf". Each is read off what --minimal carries too, the file's name
    off its path."""
    def rank(key):
        rec = records[key]
        return (not _is_done(rec), not _held_under(records, key),
                str(rec.get("discovered_at") or ""), len(Path(str(rec.get("pdf_path") or "")).name), key)
    return min(keys, key=rank)


def _standing(records: dict, key: str) -> tuple:
    """How firmly the record under this key holds its document, to be
    compared with another's. Done (keys.is_done) first, then naming a file
    that is there (_held_under), the order _first_to_keep ranks them in. A
    Needs Manual Review copy whose PDF validates is done to _already_done
    and not to keys.is_done, and a record compared by keys.is_done alone
    gave way to one that held nothing, its file left with no record and its
    statement taken again (review of 0.56.1)."""
    rec = records.get(key)
    return (isinstance(rec, dict) and _is_done(rec), bool(_held_under(records, key)))


def fold_keys_by_ids(records: dict, listed) -> int:
    """Fold the records 0.56.0 kept under the list's own ids (keyed_by_ids)
    into the key of no account of their category, date and title, after
    discovery has read the lists (#96).

    0.56.0 told apart documents the list gave no account by the list's ids
    for each, and those change every time the list loads. The same
    statement came out of every list holding it and every Discover under a
    new key, and on one tester's sign-in a date of two statements held ten
    records, whose copies Run All saved as new files or set aside. A
    document the list gives no account is now told apart by its place, and
    is under the key of no account when no other such document shares its
    date and title, as it was before 0.56.0.

    When the lists give that category, date and title one document, every
    such record is that document. The record under the key of no account
    stays unless the first of the others to keep (_first_to_keep) holds the
    document more firmly (_standing), done where it is not, or naming a file
    that is there where it names none. Then that one takes the key, holding
    nothing of the ids any more. Either way the rest go. So a statement saved
    before, or set aside for review with its file, is never fetched again,
    and a statement with an account moves from that key the way every record
    kept before #96 does (adopt_account_keys, relabel_by_statement). When
    the lists give it more than one document, which of them each record
    holds cannot be told, so only the records that are not done and name no
    file that is there go, and the rest stay as they are. One the lists do
    not give now stays as it is. No file is touched.

    A record kept by its place, "#1" or "#2", of a date and title the lists
    gave more than one document with no account, goes too when the lists
    now give that date and title documents and none under its key, and it
    is not done and names no file that is there. The lists give that day
    one document under the key of no account now, or its documents their
    accounts (#96), and the place records were refused, never taken
    (review).

    Run only on lists read whole. Returns how many records moved or went."""
    by_old = _by_old_key(listed)
    groups: dict = {}
    changed = 0
    for key, rec in list(records.items()):
        legacy = keyed_by_ids(key, rec)
        if legacy and legacy in by_old:
            groups.setdefault(legacy, []).append(key)
            continue
        place = placed(key, rec)
        if place in by_old and key not in {d.key for d in by_old[place]} \
                and not _held_under(records, key):
            del records[key]
            changed += 1
    for legacy, keys in groups.items():
        if len({d.key for d in by_old[legacy]}) != 1:
            for key in keys:
                if not _held_under(records, key):
                    del records[key]
                    changed += 1
            continue
        keep = _first_to_keep(records, keys)
        if not isinstance(records.get(legacy), dict) or _standing(records, keep) > _standing(records, legacy):
            records[legacy] = dict(records[keep], entry="")
        for key in keys:
            del records[key]
            changed += 1
    return changed


def forget_superseded(records: dict, listed) -> int:
    """For a sign-in of several accounts, drop discovery's records kept
    before #96 that are not done, when the lists now give their category,
    date and title an account (#96). Each account's own record lists that
    statement now, and the old one, downloaded with no account, would find
    two rows naming it and be refused on every run, or take whichever one
    the page showed. A record that is done stays, and the run's progress is
    never touched here, so nothing saved before is credited to an account
    by the list alone (relabel_by_statement credits one by its own PDF).
    Returns how many records were dropped."""
    changed = 0
    for old_key, docs in _by_old_key(listed).items():
        rec = records.get(old_key)
        if not isinstance(rec, dict) or _is_done(rec):
            continue
        if all(d.key == old_key for d in docs):
            continue
        del records[old_key]
        changed += 1
    return changed


# Why relabel_by_statement leaves a record kept before #96 where it is, in
# fixed words, which the log counts. Never a label, digits or a PDF's text.
NOT_DONE = "not done"
TAKEN_AGAIN = "already taken again"
HOLDS_A_FILE = "its account's record holding a file"
OTHER_NUMBER = "another account number printed"
NO_FILE = "no saved file"
UNREADABLE = "a file that does not read"
NO_DIGITS = "no listed account's digits"
SEVERAL = "more than one account's digits"
SHARED = "digits two accounts share"
NOT_LISTED = "no listed statement of that account"
NO_ONE_TAIL = "an account listed without digits of its own"


def _held_under(records: dict, key: str) -> str:
    """Why a record under this key may not be replaced, or "" when it may.
    TAKEN_AGAIN when it is done (keys.is_done). HOLDS_A_FILE when it is not
    but names a file that is there, as a Needs Manual Review copy does,
    which _already_done counts as done while its PDF validates and which
    keys.is_done does not. Replaced, its file would be left with no record
    (review of the relabel). So everything _already_done counts as done
    is held, and more."""
    rec = records.get(key)
    if not isinstance(rec, dict):
        return ""
    if _is_done(rec):
        return TAKEN_AGAIN
    saved = str(rec.get("pdf_path") or "")
    try:
        return HOLDS_A_FILE if saved and Path(saved).exists() else ""
    except OSError:
        return HOLDS_A_FILE


def relabel_by_statement(progress: dict, discovery: dict, listed, min_bytes: int) -> dict:
    """For a sign-in of several accounts, move each record kept before #96
    to the account its own saved PDF shows, after discovery has read the
    lists (#96). The promise made on #96, read each saved PDF for its
    account's last digits, and move an old record to its account only when
    the file shows that account and no other.

    A record under a key with no account ("Unnamed") moves only when all of
    this holds. It is done (keys.is_done). Every listed document of its
    category, date and title names one account by masked digits. Not every
    one of those accounts has its statement of that day, or a file of it,
    under its own key already. Its saved PDF is there, validates and holds
    text. That text prints exactly one listed account's digits as the end
    of an account number (site.tails_printed), and no other listed
    account's digits end any run of digits anywhere in it
    (site.tails_seen), a year or an amount included. Those digits are no
    two accounts' (Document.whole_label, twins anywhere in the lists). No
    account number it prints ends in other digits, an account the lists no
    longer name included (site.account_numbers_printed). The lists give
    that account a document of the record's category, date and title. And
    no record under that document's key is done or names a file that is
    there (_held_under).

    It then moves to that key the way adopt_account_keys moves one,
    progress and discovery alike, and takes the document's account, its
    summary, which for a sign-in of several accounts ends with the account
    (App._document_of), and its guid when it has one. So the record reads
    as one the list gives now, and a Rename gives the file the name a
    statement downloaded now would have, the account in it, under the
    default pattern as under one with {account}. Its state, downloaded_ok,
    pdf_path and everything else go with it, so the statement is never
    fetched again. The file itself is never renamed or moved here, and
    keeps its name until a Rename. Anything else stays exactly as
    it is, and 0.53.0 takes each account's statement again under a name
    that says the account, as before.

    Only state, downloaded_ok and pdf_path are read off a saved record, all
    of which a history moved with --minimal keeps. Returns {"moved": n,
    "listed": n} and, for each record left, how many for each fixed reason
    above."""
    tally: dict = {"moved": 0, "listed": 0}

    def leave(why: str) -> None:
        tally[why] = tally.get(why, 0) + 1

    labels = {d.account for d in listed if d.account}
    every_tail = {t for label in labels for t in site.account_tails(label)}
    twins = {t for d in listed if d.whole_label for t in site.account_tails(d.account)}
    for old_key, docs in _by_old_key(listed).items():
        rec = progress.get(old_key)
        if not isinstance(rec, dict) or any(d.key == old_key for d in docs):
            continue
        if not _is_done(rec):
            leave(NOT_DONE)
            continue
        if any(len(site.account_tails(d.account)) != 1 for d in docs):
            leave(NO_ONE_TAIL)
            continue
        if all(_held_under(progress, d.key) for d in docs):
            # Each account's statement of that day is saved under its own
            # key, or a file of it is, so there is nothing for this record to
            # stand for, and its file is not read again on every Discover.
            leave(TAKEN_AGAIN)
            continue
        saved = str(rec.get("pdf_path") or "")
        try:
            there = bool(saved) and Path(saved).is_file()
        except OSError:
            there = False
        if not there:
            leave(NO_FILE)
            continue
        if not receipt_pdf.validate_pdf(Path(saved), min_bytes).ok:
            leave(UNREADABLE)
            continue
        text = receipt_pdf.pdf_text(Path(saved))
        if not text.strip():
            leave(UNREADABLE)
            continue
        shown = site.tails_printed(text, labels) & every_tail
        seen = site.tails_seen(text, every_tail)
        if not shown:
            leave(NO_DIGITS)
            continue
        if len(shown) > 1 or seen != shown:
            leave(SEVERAL)
            continue
        tail = next(iter(shown))
        if tail in twins:
            leave(SHARED)
            continue
        if any(not site.one_account(n, tail) for n in site.account_numbers_printed(text)):
            # Another account number, listed or not. A closed account's
            # statement printing its own number and a transfer to this one
            # would be credited to this one.
            leave(OTHER_NUMBER)
            continue
        mine = [d for d in docs if site.account_tails(d.account) == [tail]]
        if len(mine) != 1:
            leave(NOT_LISTED)
            continue
        doc = mine[0]
        why_held = _held_under(progress, doc.key)
        if why_held:
            leave(why_held)
            continue
        carried = {"account": doc.account, "summary": doc.summary}
        if doc.guid:
            carried["guid"] = doc.guid
        progress[doc.key] = dict(rec, **carried)
        del progress[old_key]
        tally["moved"] += 1
        held = discovery.get(old_key)
        if isinstance(held, dict):
            held = dict(held, **carried)
            other = discovery.get(doc.key)
            if not isinstance(other, dict) or (_is_done(held) and not _is_done(other)):
                discovery[doc.key] = held
            del discovery[old_key]
            tally["listed"] += 1
    return tally


def _one_account(held: str, doc: "Document") -> bool:
    """Whether a record's account and a listed document's are one account.
    By their digits when the key holds them, else by the whole label in
    one form (site.account_form). A record holding no account yet, kept
    before #96, may take one."""
    if not held or not doc.account:
        return True
    tails = site.account_tails(doc.account)
    if tails and not doc.whole_label:
        return site.account_tails(held) == tails
    return site.account_form(held) == site.account_form(doc.account)


class App:
    _journal = None
    _requests = None

    def __init__(self, args):
        self.args = args
        # --config lets one copy of the code serve several people/accounts:
        # each config points at its own output_dir, profile_dir and port, so
        # progress.json, the index CSV, the PDFs and the browser session are
        # all kept separate. Nothing is ever re-downloaded across accounts.
        cfg_path = Path(args.config) if getattr(args, "config", None) \
            else (PROJECT_DIR / "config.json")
        self.config = load_config(cfg_path)
        ensure_owner(self.config, cfg_path)
        set_filename_owner(self.config.get("owner", "") if self.config.get("owner_in_filename") else "")
        self.paths = Paths(Path(self.config["output_dir"]))
        self.paths.ensure()
        self._setup_logging()

        self.progress = JsonStore(self.paths.progress_json, self.paths.backups)
        self.discovery = JsonStore(self.paths.discovery_json, self.paths.backups)
        self.progress.load()
        self.discovery.load()
        # No key is moved as the records load. Until #96 no E*TRADE record
        # held an account, so the move off a key whose account was cut to
        # forty characters never had one to move, and the move to the key
        # an account gives needs the lists, so discovery makes it
        # (adopt_account_keys).
        self.index_csv = CsvFile(self.paths.document_index_csv,
                                 DOCUMENT_INDEX_COLUMNS, self.paths.backups)
        self.rules = doc_types.load_rules()

        self._pw = None
        self._browser = None
        self._context = None
        self._work_page = None
        self._cdp_mode = False
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "discovered": 0, "statements": 0, "tax_documents": 0,
            "insurance_documents": 0,
            "other": 0, "skipped_completed": 0, "skipped_out_of_scope": 0,
            "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
            "validation_failures": 0, "dates": [], "new_files": [],
        }

    # -- infrastructure ----------------------------------------------------

    def _setup_logging(self):
        logfile = self.paths.logs / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            handlers=[logging.FileHandler(logfile, encoding="utf-8"),
                      logging.StreamHandler(sys.stdout)])
        logging.getLogger("pypdf").setLevel(logging.ERROR)

    def _delay(self, factor: float = 1.0):
        time.sleep(random.uniform(
            float(self.config["delay_min_seconds"]) * factor,
            float(self.config["delay_max_seconds"]) * factor))

    def browser(self):
        if self._context is not None:
            return self._context
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        cdp_url = self.config.get("cdp_url")
        if cdp_url:
            try:
                self._browser = self._pw.chromium.connect_over_cdp(cdp_url)
            except Exception as e:
                self._pw.stop()
                self._pw = None
                raise SystemExit(
                    f"Could not connect to your signed-in browser at {cdp_url}.\n"
                    f"Run login.bat first and keep that browser window OPEN.\n({e})")
            if not self._browser.contexts:
                raise SystemExit("Connected browser has no context; open a tab and retry.")
            self._context = self._browser.contexts[0]
            self._cdp_mode = True
        else:
            profile = Path(self.config["profile_dir"])
            profile.mkdir(parents=True, exist_ok=True)
            self._context = browser_launcher.launch_own_browser(self._pw.chromium, 
                str(profile), headless=False, accept_downloads=True,
                viewport={"width": 1400, "height": 950})
            self._cdp_mode = False
        self._context.set_default_timeout(30000)
        return self._context

    def page(self):
        ctx = self.browser()
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        if self._cdp_mode:
            # Reuse the person's own tab on E*TRADE's site, the page they left
            # open for this. With none open, a tab of this run's own is
            # opened, never a tab of another site, since the session is a
            # cookie a new tab shares (tabs.new_tab). Matched on the parsed
            # host, never a substring, since "provider.com" in an address also
            # matches "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            dom = [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = dom[0] if dom else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # A real Edge or Chrome attached over CDP saves a download itself,
        # into its own Downloads folder, and Playwright never sees it. So
        # the browser is pointed at a folder under the output and the site
        # layer watches that folder after every click, alongside the
        # download event, PDF response and new tab it already catches.
        self._dl_dir = Path(self.config["output_dir"]) / ".etrade-downloads"
        site.set_download_dir(self._work_page, self._dl_dir)
        # A file here that is an exact copy of a document in the archive
        # is one the browser was left holding, and goes. Nothing else is
        # touched (capture.clear_archived_copies).
        capture.clear_archived_copies(
            self._dl_dir, [r.get("pdf_path") for r in self.progress.data.values()
                 if isinstance(r, dict)])
        self.requests
        return self._work_page

    def close(self):
        try:
            if self._cdp_mode:
                # Never close the user's own signed-in tab; just detach.
                pass
            elif self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._context = self._work_page = None

    # -- session safety ----------------------------------------------------

    def check_session(self, page) -> None:
        # Both of these used to wait at a prompt. Under the panel there is
        # nobody to answer, and waiting there took the run down with an
        # end-of-file rather than saying what had happened, so when there
        # is no console the run stops on its own terms and says what to do
        # about it. Progress is already saved either way (#48).
        challenge = site.detect_security_challenge(page)
        if challenge:
            self.progress.save(backup=True)
            print(f"\n!! {challenge}")
            print("Stopped. Please resolve it yourself in the browser window.")
            print("I will NOT attempt to bypass any security check.")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page looks normal (or Ctrl+C to quit)... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
        if site.looks_signed_out(page):
            self.progress.save(backup=True)
            print("\n!! E*TRADE appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9260")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        # A real Edge or Chrome first, since etrade.com runs bot protection that is happiest in a real browser.
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        print("Checking the connection to your signed-in E*TRADE browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but E*TRADE shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and the Documents page is visible.")
            print("Keep that browser window OPEN, then run the diagnostics or pilot.")
        else:
            print("Connected, but the Documents list did not load, so this cannot say")
            print("whether you are signed in. Look at the browser window and answer")
            print("anything E*TRADE asks there yourself. If it shows your account, open")
            print("your Documents/Statements page in it, then run --diagnose.")
        self.close()

    def _in_scope(self, doc: Document) -> bool:
        a = self.args
        if not doc_types.wanted(doc.category, self.config):
            return False
        if a.type and doc.category.lower() != a.type.lower():
            return False
        if a.year and not (doc.date or "").startswith(str(a.year)):
            return False
        # Hard floor: never process documents before the configured start date.
        floor = a.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if a.end_date and (not doc.date or doc.date > a.end_date):
            return False
        return True

    def _document_of(self, r, source_url: str, several: bool = False,
                     twins=frozenset()) -> Optional[Document]:
        """The Document one scraped document (a RawDoc) from a E*TRADE page
        is, or None when it is out of scope. It carries the account the
        list gave it and the list's ids, which discovery used to drop, so
        two accounts' statements of one day were one document and no file
        said which account it was (#96). When the sign-in has more than one
        account (`several`), the summary names the account too, " - <the
        account's label>", which puts it in the file name and the index's
        Document Summary. A sign-in of one account keeps the summary, and
        so the names, it always had. `twins` are the labels, in
        site.account_form, whose masked tail another label shows on a
        document of the same date and title (site.twins_on_one_day), and
        such a document is keyed by its whole label (Document.whole_label)."""
        title = re.sub(r"\s+", " ", (r.title or "")).strip()
        if not title:
            return None
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return None
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return None
        date = (r.date_text or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date, _ = site.parse_period_date(title)
            date = date or ""
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return None
        account = re.sub(r"\s+", " ", getattr(r, "account", "") or "").strip()
        if several and account:
            summary = f"{summary} - {account}"
        return Document(title=title, category=category, summary=summary,
                        date=date, confidence=confidence, source_url=source_url,
                        account=account, guid=getattr(r, "guid", "") or "",
                        whole_label=bool(account) and site.account_form(account) in twins,
                        entry=getattr(r, "entry", "") or "")

    def _record_rawdoc(self, r, source_url: str, several: bool = False, twins=frozenset()) -> int:
        """Record one scraped document (a RawDoc) from a E*TRADE page.
        Returns 1 if new."""
        doc = self._document_of(r, source_url, several, twins)
        return self._record_listed(doc) if doc is not None else 0

    def _adopt_account_keys(self, listed: List[Document], accounts: int) -> None:
        """The records kept before #96, under keys with no account. For a
        sign-in whose lists name one account, each moves to the key that
        account gives it (adopt_account_keys), progress and discovery alike,
        so nothing saved is fetched again. For several, an old record may
        hold either account's statement (review of #96), so one moves only
        when its own saved PDF shows its account and no other
        (relabel_by_statement). Every other record stays done under its old
        key, and each account's statement of it is taken again under a name
        that says the account. Then discovery's unfinished old records go
        (forget_superseded). Each store is backed up first when anything in
        it changes. The log says how many moved and how many were left for
        each fixed reason, never an account or a word of a PDF."""
        moved = forgotten = 0
        left: dict = {}
        if accounts == 1:
            moved = adopt_account_keys(self.progress.data, listed)
            if moved:
                self.progress.save(backup=True)
            forgotten = adopt_account_keys(self.discovery.data, listed)
        elif accounts > 1:
            left = relabel_by_statement(self.progress.data, self.discovery.data, listed,
                                        int(self.config.get("min_pdf_bytes", 2000)))
            moved, relisted = left.pop("moved"), left.pop("listed")
            if moved:
                self.progress.save(backup=True)
            forgotten = relisted + forget_superseded(self.discovery.data, listed)
        if forgotten:
            self.discovery.save(backup=True)
        if moved or forgotten:
            log.info("%d saved and %d listed record(s) moved or dropped for the accounts' keys",
                     moved, forgotten)
        if accounts > 1 and (moved or left):
            log.info("%d saved record(s) kept before 0.53.0 moved to the account their PDF shows, "
                     "%d left as they were%s", moved, sum(left.values()),
                     "".join(", %d for %s" % (n, why) for why, n in sorted(left.items())))

    def _fold_keys_by_ids(self, listed: List[Document]) -> None:
        """The records 0.56.0 kept under the list's own ids, folded into the
        key of no account (fold_keys_by_ids), progress and discovery alike,
        each store backed up first when anything in it changes. The log says
        how many, never a title or a file's name."""
        folded = fold_keys_by_ids(self.progress.data, listed)
        if folded:
            self.progress.save(backup=True)
        listed_folded = fold_keys_by_ids(self.discovery.data, listed)
        if listed_folded:
            self.discovery.save(backup=True)
        if folded or listed_folded:
            log.info("%d saved and %d listed record(s) kept under the list's ids by 0.56.0 folded "
                     "into one record for each document", folded, listed_folded)

    def _record_listed(self, doc: Document) -> int:
        """Record one listed document. Returns 1 if new.

        A document never gives another account to a record already under
        its key. The key followed by the record's summary and file name
        would then hold one account's statement under the other's name
        (release review of 0.53.0). Two accounts never share a key now, so
        this would be a key this app got wrong, and the list stops there,
        before either account's record is changed, rather than give the
        document a key of its own that no run before knew. The same account
        worded another way, its digits the same, is the same account, and
        its record takes the wording the list gives now."""
        held = self.discovery.get(doc.key)
        if held is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        if not _one_account(held.get("account") or "", doc):
            raise pressing.Stop(
                "record the list", "two accounts came out with one key",
                ["Two of the accounts on this sign-in came out with one key, so the list was "
                 "stopped before either one's record was changed.",
                 "Nothing was downloaded under the wrong account. Please attach the failure "
                 "file to the E*TRADE issue on GitHub."])
        # refresh which page the doc's download link lives on, and the
        # account and ids the list gives it now
        self.discovery.update(doc.key, {"source_url": doc.source_url, "account": doc.account,
                                        "guid": doc.guid}, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        # When a list was not read to its end, what the pages read gave is
        # recorded, no record kept before moves to another key, the listing
        # stays noted as one that stopped, and the run stops at the end of
        # this, Pilot, Run All and Resume included, before anything is taken.
        # The download chooses a row by what the lists said, and lists
        # missing a page can say a date holds one document when it holds two.
        page = self.page()
        n_new = 0
        # Open the documents page and read the date from every control that
        # fetches a statement or a tax document.
        if not site.goto_documents(page):
            self.check_session(page)
            site.goto_documents(page)
        self.check_session(page)
        docs = site.collect_download_docs(page)
        # Why a period's list was not read to its end, in fixed words, none
        # when every list was (site.Listing).
        unread = sorted(set(getattr(docs, "unread", ()) or ()))
        # Period words, counts and dates only, so a report that says
        # "found just 1" can be attached as it is (#36).
        try:
            write_shaped(self.paths.diagnostics / "discovery-trace.json", {"discovery": site.DISCOVERY_TRACE[:60]}, words_for('ETRADE', site))
        except Exception as e:
            log.info("could not write the discovery trace: %s", e)
        # How many accounts the lists name, which decides whether a file
        # name says the account. An account whose key the page's account
        # list gave no label is one too, never named, so a sign-in of two
        # with one of them unnamed is never taken for a sign-in of one and
        # its history moved by the list alone (review). Only the count is
        # ever logged (#96).
        accounts = len(site.accounts_in(docs)) + int(getattr(docs, "unnamed_accounts", 0) or 0)
        twins = site.twins_on_one_day(docs)
        pairs = [(r, self._document_of(r, site.BILLING_URL, accounts > 1, twins)) for r in docs]
        listed = [d for _r, d in pairs if d is not None]
        if site.ACCOUNTS_UNREAD not in unread and self._accounts_lost(pairs, listed):
            unread = sorted(set(unread) | {site.ACCOUNT_LOST})
        # Lists that missed the accounts give every document a key of no
        # account, which is no key a record of an account will match, so
        # nothing of them is recorded either (review).
        accounts_missed = bool({site.ACCOUNTS_UNREAD, site.ACCOUNT_LOST} & set(unread))
        if not unread:
            # Only lists read whole may move a record kept before. Lists
            # missing a page could give a date and title one document when
            # they hold two, or name one account of several and credit it
            # with another's statement (review of #96).
            self._fold_keys_by_ids(listed)
            self._adopt_account_keys(listed, accounts)
        for doc in [] if accounts_missed else listed:
            n_new += self._record_listed(doc)
        self.discovery.save()
        log.info("documents page: %d documents, %d new, %d account(s)", len(docs), n_new, accounts)
        # A document whose account the page's account list gave no label is
        # kept with no account, never another's (#96). Counted, never named.
        result = next((t for t in reversed(site.DISCOVERY_TRACE)
                       if isinstance(t, dict) and t.get("note") == "discovery result"), {})
        if result.get("documents_of_an_account_not_named"):
            log.info("%d document(s) of an account the page's account list gave no label, "
                     "kept with no account (%d account(s) labeled)",
                     int(result["documents_of_an_account_not_named"]), int(result.get("accounts_named") or 0))

        if unread:
            log.info("not every list was read to its end: %s", "; ".join(unread))
            print("\n!! E*TRADE's documents list could not be read whole (%s)," % unread[0])
            if accounts_missed:
                print("   so which account each document is for is not known, and nothing")
                print("   it read is recorded or moved.")
            else:
                print("   so some documents may be missing. What the pages read gave is kept.")
            self.write_failure("read the documents list", unread[0],
                               extra={"not_read_to_the_end": list(unread)})
        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
        if not unread:
            listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)

        if not quiet:
            docs = [Document.from_dict(v) for v in self.discovery.data.values()]
            print(f"\nDiscovery complete. Documents known: {len(docs)}")
            by_cat = {}
            for d in docs:
                by_cat.setdefault(d.category, []).append(d)
            for cat, group in sorted(by_cat.items()):
                years = {}
                for d in group:
                    y = (d.date or "?")[:4]
                    years[y] = years.get(y, 0) + 1
                spread = ", ".join(f"{y}: {c}" for y, c in sorted(years.items(), reverse=True))
                print(f"  {cat}: {len(group)}  ({spread})")
            dates = sorted(d.date for d in docs if d.date)
            if dates:
                print(f"  Date range: {dates[0]} .. {dates[-1]}")
            if self.stats["skipped_out_of_scope"]:
                print(f"  Skipped as out of scope: {self.stats['skipped_out_of_scope']}")
        if unread:
            # SystemExit, which the panel reports as a run that stopped
            # (run_reporting.stopped_early).
            print("\nE*TRADE's documents list could not be read whole, so this run")
            print("stops here and downloads nothing. Run it again later to read the rest.")
            raise SystemExit(0)
        return n_new

    def _accounts_lost(self, pairs, listed: List[Document]) -> int:
        """How many documents the lists give no account, on a date and title
        a saved record holds under an account's key that the lists do not
        give now. That record's account is this document's, likely, missing
        this time, its key with no label in the page's account list (review)
        or no key at all, as when the list stops carrying keyAccountNo
        (review of #119). Read as one of no account, the statement would be
        taken again under a key of none. Read off the keys alone, so a
        history moved with --minimal is read the same."""
        now = {d.key for d in listed}
        lost = 0
        for _raw, doc in pairs:
            if doc is None or (doc.account or "").strip():
                continue
            prefix = legacy_key(doc)[:-len("Unnamed")]
            if any(key.startswith(prefix) and key not in now and isinstance(rec, dict)
                   and not key[len(prefix):].startswith("Unnamed")
                   for key, rec in self.progress.data.items()):
                lost += 1
        return lost

    def _select(self, limit: Optional[int] = None) -> List[Document]:
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        docs = [d for d in docs if self._in_scope(d)]
        docs.sort(key=lambda d: d.date or "0000", reverse=True)
        limit = limit if limit is not None else self.args.max_docs
        return docs[:limit] if limit else docs

    def _already_done(self, doc: Document) -> bool:
        """Skip documents already handled. A document that was successfully
        downloaded once is done FOR GOOD - it is not re-downloaded even if you
        later delete the PDF (e.g. after importing it into paperless-ngx). Use
        --redownload to override and fetch everything in scope again."""
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(doc.key)
        if not rec:
            return False
        if rec.get("downloaded_ok"):
            return True
        state = rec.get("state")
        # terminal / already-completed (incl. records from before the
        # downloaded_ok marker existed): done, do not re-download.
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        # a review copy counts only if its PDF is still present and valid;
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on E*TRADE's own site and
        never a tab of another site. E*TRADE keeps its session in a cookie a
        new tab shares, so with no tab of the person's on the site the
        documents page is opened in a tab of this run's own
        (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "E*TRADE",
                                self._open_documents)

    def _open_documents(self, page):
        """E*TRADE's documents page, opened by its address the way discovery
        opens it."""
        if not site.goto_documents(page):
            self.check_session(page)
            site.goto_documents(page)

    def process(self, docs: List[Document], dry_run: bool = False):
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            if self._no_longer_shared(doc):
                print("  Listed before beside another document of its date, title and account,")
                print("  which the lists do not show now, so it is left as it is.")
                continue
            filename = build_pdf_filename(doc.date, doc.summary, "", record=doc)
            if dry_run:
                print(f"  DRY RUN - would save: {filename}")
                continue
            # Which document the run is on, so a failure file says how far
            # it got and whether it ever reached a second one.
            try:
                self.journal.op("next_item" if i > 1 else "open_item",
                                "take a document", ordinal=i)
            except Exception:
                pass
            try:
                page = self._on_its_site()
                self.download_one(page, doc, filename)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress saved; run --resume to continue.")
                raise
            except Exception as e:
                # By its date and title and the kind of failure only. The
                # exception's own words can hold the file's path, whose name
                # says the account (#96).
                log.error("Failed on the document of %s titled %s, %s", doc.date, doc.title,
                          type(e).__name__)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    @staticmethod
    def _no_longer_shared(doc: Document) -> bool:
        """Whether a document told apart from others of its date, title and
        account by its entry is one the lists the run read no longer give
        that date and title more than once for that account, or for no
        account when it has none. Only such a day gives a document an entry,
        and there the download refuses it, so with the day no longer shared
        it is a record of another listing, and the documents the lists give
        now are under keys of their own, their accounts' once the lists name
        them. Taken, the one row the page shows was saved once for every such
        record, and twice for a pair the lists showed as one (review). Never
        taken."""
        return bool(doc.entry) and not site._places_still_listed(doc.date, doc.title, doc.account)

    def download_one(self, page, doc: Document, filename: str):
        """Save one document. The site layer fetches the row's PDF link from
        inside the page when there is one, and otherwise clicks the row's
        own control and catches what arrives."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # The account's masked digits, used only if the name is taken.
        # Two documents on one day used to differ by " (2)", which says
        # nothing about which is which and moves between them when a file
        # is deleted (#49, and the same complaint on #43). Written down
        # with the file, so Rename tells it apart the same way (#96).
        doc.told_apart = "+".join(site.account_tails(doc.account))
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=told_apart_by(doc.to_dict()))
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        # Open the documents page and let the site layer find and fetch this one.
        if not site.goto_documents(page):
            self.check_session(page)
            site.goto_documents(page)
        trace: list = []
        saved = site.download_bill(page, self._dl_dir, doc.date, out_path,
                                   title=doc.title, trace=trace, account=doc.account)
        # A capture that failed must not leave a convincing empty file behind.
        # A ZIP the capture took stays, for the branch below that opens it.
        if out_path.exists() and not (saved and receipt_pdf.is_zip(out_path)) and (
                out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            saved = False
        if not saved:
            attempt = self.paths.diagnostics / "download-attempt.json"
            # Built from what may leave, since it goes on a public issue.
            # The address is its kind and plain words, and the trace holds
            # fixed words, counts and shapes (#36, review).
            write_shaped(attempt, {
                "timestamp": now_iso(), "date": doc.date,
                "landed_on": site.mask_href(page.url or ""),
                "responses": trace[:80]}, words_for('ETRADE', site))
            print(f"  What the site answered is in {attempt}, attach it to the issue.")
            if any(isinstance(t, dict) and t.get("why") == site.SHARED_WITH_NO_ACCOUNT for t in trace):
                # The list gave it no account, and gave its date and title
                # more than one document, so nothing was pressed. Taken, it
                # saved whichever account's statement the page showed (#96).
                self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=self.NO_ACCOUNT)
                self._write_row(doc, "Account not known", "Needs Manual Review")
                self.write_failure('choose the document', 'the list gave the document no account')
                self.stats["manual_review"] += 1
                print("  E*TRADE's list gave this document no account, and more than one document")
                print("  of its date and title, so which one it is cannot be told. Nothing was")
                print("  pressed, and it is marked for manual review.")
                return
            if any(isinstance(t, dict) and t.get("why") == site.TWICE_FOR_ONE_ACCOUNT for t in trace):
                # One account's two documents of a title and day, which no
                # row or link tells apart, so nothing was pressed (review).
                self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=self.TWICE)
                self._write_row(doc, "Two of one day", "Needs Manual Review")
                self.write_failure('choose the document', 'the list gave one account two documents of a day')
                self.stats["manual_review"] += 1
                print("  E*TRADE's list gave this account more than one document of this date and")
                print("  title, so which one it is cannot be told. Nothing was pressed, and it is")
                print("  marked for manual review.")
                return
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF")
            self._write_row(doc, "Capture failed", "Needs Manual Review")
            self.write_failure('capture the document', 'the document would not render')
            self.stats["manual_review"] += 1
            print("  Could not capture this document - marked for manual review.")
            return

        # Some tax forms arrive as a ZIP holding the PDF. One PDF and nothing
        # else is the document. Anything more is kept whole for a person to
        # open, since which file is this document cannot be told
        # (receipt_pdf.open_zip).
        if receipt_pdf.is_zip(out_path):
            opened = receipt_pdf.open_zip(out_path, self.paths.manual_review)
            if opened.pdf is None:
                self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=opened.reason)
                self._write_row(doc, "Archive kept for review", "Needs Manual Review")
                self.write_failure('open the downloaded archive', opened.failure)
                self.stats["manual_review"] += 1
                print(f"  !! {opened.reason}. Marked for manual review.")
                return
            out_path = opened.pdf
            log.info("Opened the ZIP for %s", doc.title)

        # The same bytes as another record's document of this date is that
        # document, taken again for this one from a page that showed only
        # it, so the new copy goes to Manual Review and is not kept as this
        # record's. The other record keeps its file (#96).
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        if self._same_bytes_elsewhere(doc, digest, out_path):
            quarantine = unique_path(self.paths.manual_review, out_path.name,
                                     self.config["max_path_length"])
            try:
                out_path.replace(quarantine)
            except OSError:
                quarantine = out_path
            doc.pdf_path, doc.pdf_filename, doc.pdf_sha256 = str(quarantine), quarantine.name, digest
            self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=self.SAME_PDF)
            self._write_row(doc, "Same PDF as another document's", "Needs Manual Review")
            self.write_failure('save the document', 'two documents gave the same file')
            self.stats["manual_review"] += 1
            print("  !! This is the same PDF as another document of this date already saved.")
            print("     The new copy is in Manual Review, for a person to tell apart.")
            return
        doc.pdf_sha256 = digest

        doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
        self._record(doc, State.PDF_SAVED)

        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"])
        if not result.ok:
            self.stats["validation_failures"] += 1
            quarantine = unique_path(self.paths.manual_review, out_path.name,
                                     self.config["max_path_length"])
            try:
                out_path.replace(quarantine)
            except OSError:
                quarantine = out_path
            doc.pdf_path, doc.pdf_filename = str(quarantine), quarantine.name
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes=f"PDF validation failed: {result.reason}")
            self._write_row(doc, "Validation failed", "Needs Manual Review")
            self.write_failure('validate the saved pdf', 'the saved pdf did not validate')
            self.stats["manual_review"] += 1
            print(f"  !! Validation failed ({result.reason}); moved to Manual Review.")
            return

        doc.pdf_size, doc.pdf_pages = result.size_bytes, result.page_count
        doc.downloaded_ok = True   # done for good, even if the file is deleted later
        self._record(doc, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self._write_row(doc, "Downloaded", "Completed")
        self.stats["new_files"].append(str(out_path))
        if doc.date:
            self.stats["dates"].append(doc.date)
        if doc.category == doc_types.TAX:
            self.stats["tax_documents"] += 1
        elif doc.category == doc_types.INSURANCE:
            self.stats["insurance_documents"] += 1
        elif doc.category == doc_types.STATEMENT:
            self.stats["statements"] += 1
        else:
            self.stats["other"] += 1
        print(f"  Saved: {out_path.name}")

    # -- records -----------------------------------------------------------

    NO_ACCOUNT = ("The list gave this document no account and more than one document of its "
                  "date and title, so nothing was pressed")
    SAME_PDF = "The same PDF as another document of this date"
    TWICE = ("The list gave this account more than one document of this date and title, so "
             "nothing was pressed")

    def _same_bytes_elsewhere(self, doc: Document, digest: str, out_path: Path) -> bool:
        """Whether another record of this document's date holds a saved file
        of these bytes, by the digest it kept, or for a record saved before
        digests were kept, by its file's own bytes. A record naming the very
        file just saved is not one, as when its own file was deleted and the
        name is free again. Nor, for a document of one account, is the
        record kept before 0.53.0 of its date and title, saved once for
        every account's statement of the day. Its bytes being this
        account's say only that it held this account's (#96)."""
        legacy = legacy_key(doc) if (doc.account or "").strip() else None
        for key, rec in self.progress.data.items():
            if key in (doc.key, legacy) or not isinstance(rec, dict) or rec.get("date") != doc.date:
                continue
            if rec.get("pdf_sha256"):
                if rec["pdf_sha256"] == digest:
                    return True
                continue
            saved = Path(str(rec.get("pdf_path") or ""))
            try:
                if not rec.get("pdf_path") or not saved.is_file() or saved.resolve() == out_path.resolve():
                    continue
                if hashlib.sha256(saved.read_bytes()).hexdigest() == digest:
                    return True
            except OSError:
                continue
        return False

    def _record(self, doc: Document, state: State, notes: str = ""):
        doc.state = state.value
        if notes:
            doc.notes = (doc.notes + "; " if doc.notes else "") + notes
        rec = doc.to_dict()
        # A document saved before keeps its record while a Download again
        # saves no copy of its own (paperpull_core.saved_copy).
        if saved_copy.holds(self, doc.key, rec):
            return
        self.progress.update(doc.key, rec)
        self.discovery.update(doc.key, {"state": state.value})

    def _write_row(self, doc: Document, status: str, processing: str):
        notes = "; ".join(x for x in (doc.notes, status) if x)
        self.index_csv.append_rows([{
            "Account Holder": self.config.get("owner", ""),
            "Document Date": doc.date,
            "Category": doc.category,
            "Document Summary": doc.summary,
            "Document Title": doc.title,
            "Period": doc.period,
            "PDF Filename": doc.pdf_filename,
            "PDF Full Path": doc.pdf_path,
            "PDF File Size": doc.pdf_size,
            "PDF Page Count": doc.pdf_pages,
            "Source URL": doc.href,
            "Classification Confidence": doc.confidence,
            "Downloaded At": now_iso() if doc.pdf_filename else "",
            "Verified At": now_iso() if doc.pdf_pages else "",
            "Processing Status": processing,
            "Notes": notes,
        }])

    # -- modes -------------------------------------------------------------

    def cmd_pilot(self):
        self.stats["mode"] = "pilot"
        print("PILOT MODE - limited supervised test run.\n")
        self.cmd_discover()
        docs = self._select(limit=self.config.get("pilot_count", 5))
        if not docs:
            print("\nNo documents in scope to pilot. Run --diagnose.")
            return
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)
        self._pilot_report(docs)

    def _pilot_report(self, docs: List[Document]):
        print("\n" + "=" * 70)
        print("PILOT RESULTS - inspect these before approving a full run")
        print("=" * 70)
        problems = []
        for d in docs:
            rec = self.progress.get(d.key) or {}
            state = rec.get("state", "?")
            print(f"\n  {rec.get('date', d.date)}  {rec.get('category', d.category)}")
            print(f"    Title:  {rec.get('title', d.title)[:70]}")
            print(f"    State:  {state}   [{rec.get('confidence', '')}]")
            print(f"    PDF:    {rec.get('pdf_filename', '(none)')}"
                  f"  ({rec.get('pdf_size', '?')} bytes, {rec.get('pdf_pages', '?')} pages)")
            # A Download again that saved nothing kept the saved copy's
            # record as it was, so it is said here (paperpull_core.saved_copy).
            if saved_copy.tried(self, d.key):
                problems.append(f"{d.date} {d.category} {d.title}: {saved_copy.tried(self, d.key)}")
            if state != State.COMPLETED.value:
                problems.append(f"{d.date} {d.category} {d.title}: {state} - {rec.get('notes', '')}")
        print("\n" + "-" * 70)
        if problems:
            print("Needs attention:")
            for p in problems:
                print(f"  ! {p}")
        else:
            print("No problems detected in the pilot.")
        print(f"\nFiles are in:\n  {self.paths.root}")
        print("Nothing further runs until you explicitly start a full command.")

    def cmd_run(self, mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            scope = ", ".join(self.config.get("document_types", []))
            print(f"This downloads ALL available E*TRADE documents ({scope}).")
            print("Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover()
        docs = self._select()
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)

    def cmd_resume(self):
        self.stats["mode"] = "resume"
        # With nothing listed, or after a run that stopped before it had the
        # whole list, Resume says so and stops as a run that stopped, rather
        # than call the run finished (paperpull_core.listing). It reads the
        # lists again only once it has something to carry on with.
        docs = [d for d in self._select() if not self._already_done(d)]
        listing.resume(self, docs, self._resume_from_the_lists)

    def _resume_from_the_lists(self, _known):
        """Carry on once the lists are read again. The download chooses a row
        by what the lists said, how many documents each date held and their
        titles. Those are read by discovery, and without them a row that does
        not name its document is refused. The app says to press Resume after
        a stopped run, so Resume reads the lists first, the way Pilot and Run
        do (#36, review). Lists read whole here let the run finish clean."""
        self.cmd_discover(quiet=True)
        docs = [d for d in self._select() if not self._already_done(d)]
        print(f"The lists, read again, leave {len(docs)} document(s) to take.")
        self.process(docs, dry_run=self.args.dry_run)


    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.

        A naming scheme improves and the files on disk keep the old one.
        Nothing about them needs fetching, only their names are wrong, so
        nothing is asked of the provider here (#43, #49). A preview
        unless --apply is given."""
        self.stats["mode"] = "rename"
        renaming.run_for(self, apply_changes=bool(getattr(self.args, "apply", False)),
                         told_apart=told_apart_by)

    def cmd_verify(self):
        self.stats["mode"] = "verify"
        rows = self.index_csv.read_all()
        if not rows:
            print("Document index is empty - nothing to verify.")
            return
        bad = 0
        for row in rows:
            p = row.get("PDF Full Path", "")
            if not p:
                continue
            r = receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"])
            if not r.ok:
                bad += 1
                print(f"  BAD {row.get('PDF Filename', '')}: {r.reason}")
            else:
                row["Verified At"] = now_iso()
        self.index_csv.rewrite(rows)
        print(f"\nVerified {len(rows)} index rows; {bad} problem(s).")

    @property
    def requests(self):
        """Which of the provider's own calls happened, and what came back.

        Made on first use like the journal, and started at once, because
        it only sees what arrives after it starts listening. An app that
        drives an API rather than a page has no selectors for the census
        to count, and this is what it has instead."""
        if self._requests is None:
            self._requests = Requests(getattr(self, "_work_page", None),
                                      getattr(site, "is_safe_url", None))
            self._requests.start()
        return self._requests

    @property
    def journal(self):
        """The run's journal, made the first time anything writes to it.

        Lazy, because a run that never opens a page has nothing to say
        and an app that fails before the browser is up must not fail
        differently because of this. It watches every selector the app
        declares, since choosing between them is a decision nobody can
        make before the first failure."""
        if self._journal is None:
            self._journal = Journal(getattr(self, "_work_page", None),
                                    getattr(site, "FALLBACK", None))
        return self._journal

    def write_failure(self, step: str, reason: str, text: str = "",
                      postmortem: dict = None, extra: dict = None) -> None:
        """What the page looked like when this went wrong, to a file.

        Written without anybody having to know to ask for it, because a
        tester who has to be told to run a second command is a tester who
        sends one file and waits a day for the request for the other.

        One per run. A run where thirty documents fail for one reason
        does not need thirty files, and the first is taken while the page
        is still sitting on the thing that broke.

        `extra` holds only our own words, counts, yes or no, and words that
        went through the word list, such as what covered a control."""
        if self.stats.get("failure_files"):
            return
        extra = dict(extra or {})
        if postmortem:
            extra["postmortem"] = postmortem
        extra = extra or None
        # A checkpoint at the moment it gave up. It is also what makes the
        # journal when nothing had written to it yet, and every tester file
        # sent in on 2026-09-25 came back without one for that reason.
        try:
            if getattr(self, "_work_page", None) is not None:
                self.journal.checkpoint("when the run gave up")
        except Exception:
            pass
        path = failure.write_failure(
            self.paths.diagnostics,
            command=self.stats.get("mode") or "run",
            step=step, reason=reason,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='ETRADE', text=text, extra=extra)
        if not path:
            return
        self.stats["failure_files"] = 1
        try:
            import json as _failure_json
            said = failure.summarize(_failure_json.loads(
                Path(path).read_text(encoding="utf-8")))
        except Exception:
            said = []
        if said:
            print("  What it noticed:")
            for line in said[:6]:
                print("    - %s" % line)
        print("  Read it through, then attach it to this provider's issue on")
        print("  GitHub. It is the one thing that saves a round of guessing.")

    def write_survey(self, stopped=None) -> None:
        """The survey Diagnose is safe to send.

        Diagnose writes a detailed file for repairing this provider, and
        that file holds the page's own title, the URL with its query
        string, the text of the rows it found and the labels of the
        controls. The panel said to attach it to an issue, which is not
        something that file is for.

        So this is written beside it, on the same list of what may leave
        that the failure file uses, and it is the one to send.
        """
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='ETRADE',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        """Survey the documents page and write a file a tester can attach to
        the GitHub issue. No screenshot, digit runs masked, JSON bodies as
        shape only. Nothing is downloaded and nothing but a documents link is
        followed."""
        self.stats["mode"] = "diagnose"
        words = words_for('ETRADE', site)
        page = self.page()
        info = {"timestamp": now_iso(), "unverified": True,
                "note": Fixed("E*TRADE app built without an account. This survey is what "
                              "the maintainer repairs the site layer against.")}
        stopped = None
        try:
            try:
                found = site.goto_documents(page)
            except pressing.Stop as stop:
                # The page would not open, and nothing past the stop was
                # pressed. What the window shows is surveyed all the same,
                # and no link on it is followed.
                stopped = stop
                found = False
                info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
            info["documents_page_found"] = found
            info["documents_page_opened"] = bool(found)
            info["landed_on"] = site.redact(page.url)
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            site.set_private_words([self.config.get("owner", "")])
            info["survey"] = site.survey(page, max_follow=0 if stopped is not None else 6)
            if found:
                site.expand_all(page)
                site.scroll_full_page(page)
            info["row_counts"] = {}
            for name, sel in [("doc_row", site.FALLBACK["doc_row"]),
                              ("table rows", "table tbody tr"),
                              ("pdf links", "a[href*='.pdf']"),
                              ("download attrs", "a[download]")]:
                try:
                    info["row_counts"][name] = page.locator(sel).count()
                except Exception as e:
                    info["row_counts"][name] = f"ERR {e}"
            found_docs = site.collect_download_docs(page) if found else []
            info["documents_recognized"] = [{"date": b.date_text, "kind": b.kind, "has_pdf_link": bool(b.href)}
                                            for b in found_docs[:40]]
            info["discovery"] = site.DISCOVERY_TRACE[:60]
            docs = site.collect_documents(page)
            info["rows_collected"] = len(docs)
            info["samples"] = []
            for d in docs[:12]:
                cat, summ, conf = doc_types.classify_document(d.title, self.rules)
                date, period = site.parse_period_date(d.text or d.title)
                info["samples"].append({
                    "title": d.title[:90], "href": (d.href or "")[:100],
                    "text": (d.text or "").replace("\n", " | ")[:160],
                    "category": cat, "summary": summ, "date": date, "period": period})
        except pressing.Stop as stop:
            # A press past the documents page it would not make ends the
            # look there, and the file still says what was seen and why it
            # stopped.
            stopped = stop
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
        except Exception as e:
            info["error"] = str(e)[:300]
        self._diagnose_stopped = stopped
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        if stopped is not None:
            # The stop's own words, as a run says them (pressing.say).
            pressing.say(stopped)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print(f"Documents page found: {shape_tree(info.get('documents_page_found', '?'), words)}, "
              f"documents recognized: {len(info.get('documents_recognized', []))}, "
              f"rows: {shape_tree(info.get('rows_collected', '?'), words)}")
        print("Look through that file for anything you would not want public,")
        print("then attach it to the E*TRADE issue on GitHub. No screenshot was taken.")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='ETRADE',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "E*TRADE Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Tax documents downloaded:  {s['tax_documents']}",
            f"Insurance docs downloaded: {s['insurance_documents']}",
            f"Other documents:           {s['other']}",
            f"Skipped (already done):    {s['skipped_completed']}",
            f"Skipped (out of scope):    {s['skipped_out_of_scope']}",
            f"Needs manual review:       {s['manual_review']}",
            f"Failed:                    {s['failed']}",
            f"Duplicate filenames (#'d): {s['duplicate_filenames']}",
            f"PDF validation failures:   {s['validation_failures']}",
            f"Earliest date processed:   {dates[0] if dates else '-'}",
            f"Latest date processed:     {dates[-1] if dates else '-'}",
            "",
        ]))
        # A plain list of exactly the files downloaded THIS run (all new,
        # since already-downloaded documents are skipped). Handy for knowing
        # what to import into paperless-ngx, and safe to ignore/delete.
        # Not for Verify or a dry run, which save nothing and leave the
        # list as the last download run wrote it (lists_what_it_saved).
        if lists_what_it_saved(s, self.args):
            atomic_write_text(
                self.paths.root / "new-this-run.txt",
                f"# {len(new_files)} file(s) downloaded on this run "
                f"({s['ended']}):\n" + NEW_LIST_NOTE
                + "\n".join(sorted(new_files)) + "\n")
            if new_files:
                print(f"\n{len(new_files)} NEW file(s) downloaded this run "
                      f"(listed in new-this-run.txt).")
        report_run_result(s)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Local supervised E*TRADE document downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download the 5 newest in-scope documents, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "dump the Documents page structure (no downloads)"),
            ("record", "record your own path to a document, so this app can be repaired (downloads nothing)"),
            ]:
        ap.add_argument(f"--{name}", action="store_true", help=help_text)
    ap.add_argument("--apply", action="store_true",
                    help="with --rename, actually rename (default is a preview)")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan filenames but download nothing")
    ap.add_argument("--year", type=int)
    ap.add_argument("--start-date")
    ap.add_argument("--end-date")
    ap.add_argument("--max-docs", type=int)
    ap.add_argument("--type", help="Statement or 'Tax Document'")
    ap.add_argument("--yes", action="store_true", help="skip the --all confirmation")
    ap.add_argument("--redownload", action="store_true",
                    help="re-download everything in scope, ignoring the "
                         "'already downloaded' memory (rebuilds deleted files)")
    ap.add_argument("--config", help="use an alternate config file, e.g. "
                                     "config.spouse.json (separate account)")
    ap.add_argument("--open-browser", action="store_true",
                    help="launch a sign-in browser using this config's profile/port")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    for d in (args.start_date, args.end_date):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            print(f"Bad date '{d}': use YYYY-MM-DD")
            return 2
    app = App(args)
    try:
        if getattr(args, "open_browser", False):
            app.cmd_open_browser()
        elif args.login:
            app.cmd_login()
        elif args.discover:
            app.stats["mode"] = "discover"
            app.cmd_discover()
        elif args.pilot:
            app.cmd_pilot()
        elif args.all:
            app.cmd_run("all")
        elif args.resume:
            app.cmd_resume()
        elif args.verify:
            app.cmd_verify()
        elif args.rename:
            app.cmd_rename()
        elif args.record:
            app.cmd_record()
        elif args.diagnose:
            app.cmd_diagnose()
            app.write_survey()
        elif args.dry_run:
            app.cmd_run("dry-run")
        else:
            build_parser().print_help()
            return 0
    except pressing.Stop as stop:
        # A press it would not make stops the run here, with the reason said
        # and the failure file written.
        pressing.stop_run(app, stop)
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
        return 130
    finally:
        app.progress.save(leaving=True)
        app.discovery.save(leaving=True)
        # A run that only looked at the page writes no summary. The
        # summary rewrites new-this-run.txt, and for a mode that
        # downloads nothing that means replacing the real list from
        # the last download run with an empty one.
        if app.stats["mode"] in ("discover", "rename"):
            # Discover and Rename download nothing, so the run summary
            # and new-this-run.txt stay as the last download run wrote
            # them, and only the panel is told how it ended. The panel
            # moves what a run saved into a documents folder with a
            # Rename, and its empty list made that run read as one that
            # saved nothing (#103).
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
