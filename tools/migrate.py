"""Carry your download history to another computer, so nothing is fetched twice.

The PDFs are not the important part. What matters is the record of what has
already been downloaded, because that is what makes a re-run skip a statement
instead of pulling it again. Move that, and a fresh install on a new machine
picks up exactly where the old one left off, whether or not you copied a single
PDF across.

    python migrate.py --export history.ppz
    python migrate.py --import history.ppz --dry-run
    python migrate.py --import history.ppz

The control panel does the same with Export history and Import a history file
on its Status tab, on the desktop and on PaperPull Server alike, and its import also
sets up each provider and each person the file names that is not set up yet,
with their settings (#67). This command only fills in what is already set up.

WHAT COMES ACROSS

For each provider, and for each second person on it (a config.<name>.json),
the progress.json its runs keep, which is a dict of records keyed by a stable
document identity. Two fields in each record decide whether a document is
skipped on the next run, and BOTH are needed:

  * downloaded_ok, the permanent marker, set once a PDF has been written
  * state, because records made before that marker existed are skipped on a
    terminal state alone, and that is most of them

An import never deletes and never downgrades. A document marked done stays
done, and anything the target install already knew about it is kept.

Each person's settings come along too, the ones somebody chose rather than
the ones that name a computer. That is every key the provider's
config.example.json lists, the file name patterns, and nothing in
MACHINE_KEYS, the download folder, the documents folder, the browser profile,
the browser and its debugging port, which the new machine decides for itself.
An import writes settings only into a provider or person it sets up, never
over one already there.

PATHS ARE REWRITTEN

Records carry the absolute path the PDF was written to. On another machine
those point at a folder that does not exist, so the folder is rewritten to the
target's as the records are merged. Where a path cannot be rewritten, or would
lead out of that folder, it is cleared rather than left pointing somewhere
false, because one part of the skip logic asks whether a review copy is still
on disk and a stale path would answer that wrongly.

THE EXPORT FILE HOLDS PERSONAL DATA

It is a plain zip, so treat it like the archive it describes. Depending on
which apps you run it can contain account labels and the last four digits of
account numbers, document titles, order numbers and purchase totals, itemized
purchases, store locations and the account holders' names. It holds no
passwords, no cookies and no session tokens.

--minimal writes only the fields a skip decision reads, and no settings. For
Robinhood those include each document's category, date, title and account,
the parts its record keys are made of, the key a tax form was saved under
before its year was read, which of Robinhood's four fixed statement and tax
pages listed it, and the SHA-256 digests of the saved file and of its text,
which say nothing of what the file holds. For American Family they include each document's
date, the masked last four of the account or policy its bill is told by and
the saved file's digest, so a statement with the bytes of another bill's is
still caught. For E*TRADE they include each document's date and the saved
file's digest, so a download with the bytes of another document of that
day is still set aside. For AT&T they include each bill's kind, date and account,
which is only Wireless or Internet, all three in its key already, and the
saved file's size and page count, so a bill 0.34.0 saved under the wrong
year is still found and fetched again. For Optum Bank a tax form, and
never a statement, keeps its product, title and id, which its key holds
already (a title to sixty characters), and the address of its file on
Optum's site. That address adds Optum's own number for a form saved under
the key of its title, so a corrected form listed under the same title is
still told from it. For Target an order filed as its invoices keeps its
list of those saved, each one's file, which of the order's invoices it is,
the number Target prints on it, whether it was kept or put aside for review
and whether it names the order, and its size and page count, so an order
with an invoice still to fetch fetches only that one. The invoice number is
Target's own, not the order's, and nothing else in the file holds it. Each
file name holds the order's date and summary, which can be the name of its
one main item, as its PDF path does once the order is done. Until then
that path is empty, so for an order still to finish the list adds them.
An Apple purchase not saved yet keeps the start times of the runs on which
Apple refused its receipt or it was not asked, so the third refusal still
saves a record of the purchase, and one saved keeps neither. A NetBenefits
statement keeps its kind, date, title, place among same-day twins and
account, which is the plan's name its file name holds too, so a sign-in
with one plan that gains another does not save its history again. On a
sign-in with several plans it also keeps the plan's digest, the digests
of the other plans a combined statement names and the digest of the
statement's text, so a plan whose own statement is that one is not saved
twice. None of these is a plan or employer number. It leaves out the
employer's name a combined statement was made under and whether a
statement waits in Manual Review for one to tell its plan, so after the
move such a statement is set aside like any other in Manual Review, never
filed, and is made and judged again once its file there is gone. An
American Express Banking document keeps the token the page's list gave its
account and the last four digits its account switcher showed, so after the
move a config still refuses a list of another account rather than save its
statements under this one. The token is the page's own word for the
account, not its number, and no sign-in.
A record still under a key that left out its account's
last four, as the apps did past forty characters until 0.34.0 and Chase did
at any length until 0.17.1, also keeps what its key is built from
and what the app compares before moving it, the document's kind, date,
title, account, place among same-day twins and id. The app needs them to move
it to the key that keeps the last four when it loads, and without the move it
downloads that document again. Its key holds most of that already. What they
add is the account's whole label and the document's whole title, where the
key holds the first forty and sixty characters less those a file name cannot
hold, and for Capital One and Schwab a document's category and the
provider's id for it. A label ends in the last four, which every key written
since holds too. On a real archive that took the file from 330 KB to 64 KB,
with no list of items and no purchase total left in it. Be clear about what
it does NOT remove. A receipt's key holds its order number, the recorded PDF
path stays, and file names embed account labels and a receipt's summary,
which can be the name of its one main item, so a line like
"Statements\\2026-08-18 Statement - FREEDOM (...0962).pdf" survives. It is a
much smaller and much less revealing file, not an anonymous one. The cost is
that the new machine starts with no history to report on until it runs.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import posixpath
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# The core beside this tool comes first, so an older copy installed in the
# interpreter's own environment never stands in for it.
_CORE = Path(__file__).resolve().parents[1] / "core"
if (_CORE / "paperpull_core").is_dir():
    sys.path.insert(0, str(_CORE))
from paperpull_core.keys import account_component  # noqa: E402
from paperpull_core.not_shown import DAYS_KEY, asked_again, set_aside  # noqa: E402
from paperpull_core.ports import is_example  # noqa: E402
from paperpull_core.storage import json_text, sanitize_component  # noqa: E402

# The file this writes. Version 1 had one entry per folder and no people or
# settings, and still imports.
SCHEMA = 2
READS = (1, 2)

# The fields a skip decision actually reads. Everything else is history.
# The days a receipt page showed nothing are read too, since a receipt they
# set aside is final in Meijer only while its record holds them, and every
# receipt app's skip line says why from them (paperpull_core.not_shown).
SKIP_FIELDS = ("state", "downloaded_ok", "pdf_path", "discovered_at", "updated_at",
               DAYS_KEY)

# The fields one provider's skip decisions read besides those, by the name
# its storage.py gives it, carried for that provider alone, since the same
# field can hold more in another app. Robinhood takes a tax form listed again
# without its year as the one saved under its undated key, a key shaped like
# every record's, and a crypto statement saved under its old key as done only
# when the crypto page listed it, one of Robinhood's four fixed statement and
# tax pages (_already_done). It moves a form saved without a date to the key
# of the year its page now lists, or keeps a second copy of it out, by its
# category, date, title and account, the parts of its key, which hold no
# account number (_date_saved_forms, _saved_form_of_year). And it knows a
# statement of one account page that is another's saved one by those and the
# digest of the saved file or of its text (_other_accounts_statement). American Family trusts
# neither copy when a statement it takes has the very bytes of another bill's
# statement of that date, found by each saved one's digest, date and account
# part, the masked last four of the bill's account or policy, which its key
# and file name hold too (download_one). E*TRADE sets a new download aside
# when it has the very bytes of another document of its date, found by each
# saved one's digest and date (_same_bytes_elsewhere, #96). AT&T clears the marker of a bill
# 0.34.0 saved under the wrong year as it loads, one found by the same date
# a year later on a bill of the same kind and account, Wireless or
# Internet, saved with the same size and page count (#26,
# clear_wrong_year_copies). Target counts an invoice of an order as saved by
# the order's list of those it saved, by Target's number for it or its place
# among the order's, and whether a file is still there, kept or put aside
# (_invoices_on_file). An order with one still to fetch has no row in the
# receipt index, so without the list it saves the others a second time.
# Every app's skip decisions, and every walk of its saved records, are read
# against these by core/tests/test_a_minimal_history_skips_what_the_app_did.py.
PROVIDER_SKIP_FIELDS = {"Robinhood": ("undated_key", "source_url", "category", "date",
                                      "title", "account", "pdf_sha256", "text_sha256"),
                        "American Family": ("pdf_sha256", "date", "account"),
                        "ETRADE": ("pdf_sha256", "date"),
                        "AT&T": ("category", "date", "account", "pdf_size", "pdf_pages"),
                        "Target": ("invoices",),
                        # A requested statement of a card's month already
                        # saved, as a regular statement the list has since
                        # dropped, is the same statement and is not taken
                        # again, found by each saved record's date and its
                        # card's name, which the key holds too and which
                        # carries no digits (citi_docs._saved_months, #103).
                        "Citi": ("date", "account"),
                        # A combined statement covers its employer's other
                        # plans for one period, found by the plans' digests,
                        # the digest of its text and the parts of the key
                        # (netbenefits_docs._covered_already). A period saved
                        # while the login had one plan is found by the plan's
                        # name, its account, which its file name holds too
                        # (_saved_with_one_plan). None names a person or an
                        # account number.
                        "NetBenefits": ("category", "date", "title", "occurrence", "covers",
                                        "plan", "text_sha256", "account"),
                        # A config keeps to the account its records were
                        # listed under, by the list's own token for it and
                        # the last four digits the account switcher shows,
                        # and stops when the window shows another
                        # (amexbanking_docs.App._held_accounts).
                        "American Express Banking": ("account_token", "account_digits")}


def _optum_form(rec: dict) -> bool:
    """An Optum Bank tax form, by the address of its file on Optum's site
    that its record keeps."""
    return "/tax_documents/" in str(rec.get("href") or "")


# Fields one provider reads off one kind of its records alone, carried for
# that kind alone, with what tells it. When Optum Bank lists a corrected
# tax form under the title of the one it corrects, the form already saved
# under the key of that title keeps it. It is found by having no id of its
# own and by its product, title and the address of its file on Optum's
# site (optum_docs.hold_known_forms), and no statement is read there.
PROVIDER_KIND_FIELDS = {"Optum Bank": (_optum_form, ("href", "account", "title",
                                                     "document_id"))}

# Fields one provider reads off a purchase it has not finished, to go on
# from where an earlier run stopped, carried only while the purchase is not
# done and filled in together. Apple counts the separate runs on which it
# refused a purchase's receipt, and those on which it did not ask, each by
# the time the run started, and saves a record of the purchase on the third
# (_apple_refused, _would_make_a_record), saying how many it was not asked
# on. Read and run through the tool by
# core/tests/test_an_unfinished_purchase_goes_on_after_a_minimal_move.py.
PROVIDER_UNFINISHED_FIELDS = {"Apple": ("refused_runs", "not_asked_runs")}

# What an app builds a document's key from, and compares with a record
# already under the new key, to move a record off a key that cut the account
# to forty characters as it loads (paperpull_core.keys.migrate_account_keys,
# and Chase's own copy). Capital One, Schwab, Interactive Brokers and
# Vanguard key a document by its type and its place among same-day twins and
# keep its id beside the key, and Ally's key reads the account its list gave.
# Carried only for a record still under such a key. Every app that moves one
# is read and run through the tool by
# core/tests/test_a_minimal_history_moves_a_cut_key.py.
KEY_FIELDS = ("category", "doc_type", "date", "title", "account", "listed_account",
              "occurrence", "document_id")

# Fields one provider keeps only for this computer's runs, left out of every
# export, full or --minimal. Chase Business mints its account ids and its
# statement ids anew each sign-in, so its records keep account_ref and
# documentId empty, and both fields are left out all the same so no record
# an earlier build wrote can carry one. The key holds a short unsalted
# digest of the account's class and last four, never the digits, so a moved
# history still skips the statement, full or --minimal
# (chasebusiness_docs.Document.key). The record's own account_digest is read
# only by Rename, to tell two accounts' files apart (told_apart_by), so a
# full export keeps it and --minimal leaves it out like any Rename-only
# field. The digest is no secret, since a last four has only ten thousand
# values. Checked by core/tests/test_migrate_tool.py.
PROVIDER_PRIVATE_FIELDS = {"Chase Business": ("account_ref", "document_id")}

# Chase has kept an account's last four in its key since 0.17.1 whatever its
# length, where the other apps keep it only past forty characters, so its
# own move takes a short account's record off an old key too
# (chase_docs.Document.key and migrate_legacy_keys).
LAST_FOUR_AT_ANY_LENGTH = {"Chase"}

# Read out of an install's own storage.py, the same way the status report does,
# so an install is identified by what it IS rather than what its folder is
# called. Folders get renamed; a provider does not.
# Either quote, and a double-quoted name may hold an apostrophe ("Lowe's").
PROVIDER_RE = re.compile(r"""provider\s*=\s*["']((?<=")[^"]+(?=")|(?<=')[^']+(?='))""")
KIND_RE = re.compile(r"kind\s*=\s*(DOCUMENT|RECEIPT)")
# An app's own script, as the control panel finds it, never a hidden file.
ENTRY_RE = re.compile(r"[^.].*_(receipts|docs)\.py$")

# A terminal state means done even without the downloaded_ok marker. Kept in
# step with the apps' own should_skip.
TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}

# Settings that name this computer. Another machine has its own folders, its
# own profiles and its own browser, so these never travel, and an import
# never writes them, whatever a file says.
MACHINE_KEYS = ("output_dir", "profile_dir", "cdp_url", "browser", "documents_dir")
# The control panel's File names tab writes these, and no config.example.json
# lists them.
NAMING_KEYS = ("filename_pattern", "filename_pattern_receipts",
               "filename_pattern_statements")
# What load_config gives every app, so an install made before its
# config.example.json existed still carries them.
CORE_SETTINGS = ("owner", "owner_in_filename", "default_start_date", "min_pdf_bytes",
                 "max_path_length", "delay_min_seconds", "delay_max_seconds")
# The longest a setting may be once written as JSON. The longest real one is a
# list of account labels.
MAX_SETTING_CHARS = 4000

# How much of a file handed over is read. A real archive of thirty providers
# exported to 330 KB, so these stop only a file that is not one, including a
# zip that says it is small and unpacks to far more. PaperPull Server reads
# what anyone signed in sends, on a NAS, and a megabyte of tiny records
# becomes more than ten in memory, so they are kept well short of that.
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_RECORDS_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_RECORDS = 200000
MAX_ENTRIES = 500


class NotAnExport(Exception):
    """A file this cannot import, with a sentence saying why."""


def _say(line=""):
    """Console-safe. Account labels are scraped from bank pages and can hold
    characters the Windows console codepage cannot encode, which would
    otherwise end the run with a UnicodeEncodeError instead of a report."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(
            encoding="utf-8").strip()
    except OSError:
        return ""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _entry_script(folder: Path):
    try:
        for p in sorted(folder.glob("*.py")):
            if ENTRY_RE.match(p.name):
                return p
    except OSError:
        pass
    return None


def _provider_kind(folder: Path):
    """(provider, kind) from the folder's storage.py, the folder's name and
    None when it has none."""
    src = ""
    try:
        src = (folder / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    p = PROVIDER_RE.search(src)
    k = KIND_RE.search(src)
    return (p.group(1) if p else folder.name), (k.group(1) if k else None)


def identify(install: Path):
    """(provider, kind) for an install folder, or (None, None) if it is not one."""
    if not (install / "progress.json").is_file():
        return None, None
    return _provider_kind(install)


def _records(path: Path):
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


# -- where each person's history is kept ---------------------------------------

def account_configs(install: Path) -> list:
    """(label, config file) for every person on an install, the first one,
    "primary", first. The example and a copy of it nobody filled in are no
    person's (paperpull_core.ports.is_example), as the control panel lists
    them."""
    out = [("primary", install / "config.json")]
    for p in sorted(install.glob("config.*.json")):
        if not is_example(p):
            out.append((p.name[len("config."):-len(".json")], p))
    return out


def output_dir_of(install: Path, cfg: dict, provider: str) -> Path:
    """Where a person's runs keep their records. A relative folder is the
    install's, since a run starts there, and none at all is load_config's
    default."""
    raw = str(cfg.get("output_dir") or "") or str(Path.home() / "Downloads" / provider)
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = install / p
    return Path(os.path.normpath(str(p)))


def settings_allowed(install: Path) -> set:
    """The settings that travel for an install. Every key its own
    config.example.json lists, the core's and the file name patterns, and
    never one that names this computer or a comment."""
    example = _read_json(install / "config.example.json")
    keys = set(example) if isinstance(example, dict) else set()
    keys |= set(CORE_SETTINGS) | set(NAMING_KEYS)
    return {k for k in keys if not k.startswith("//") and k not in MACHINE_KEYS}


def _fits(value) -> bool:
    try:
        return len(json.dumps(value)) <= MAX_SETTING_CHARS
    except (TypeError, ValueError):
        return False


def settings_of(install: Path, cfg: dict) -> dict:
    """The settings a person chose, as an export carries them."""
    allowed = settings_allowed(install)
    return {k: cfg[k] for k in sorted(allowed) if k in cfg and _fits(cfg[k])}


def _same_kind(ref, value) -> bool:
    """Whether a value is the kind of thing the install's own setting is, so
    a file cannot turn a number into a list or a switch into a word."""
    if isinstance(ref, bool) or isinstance(value, bool):
        return isinstance(ref, bool) and isinstance(value, bool)
    if isinstance(ref, (int, float)):
        return isinstance(value, (int, float))
    for kind in (str, list, dict):
        if isinstance(ref, kind):
            return isinstance(value, kind)
    return value is None or isinstance(value, (str, int, float))


def settings_to_apply(install: Path, cfg: dict, settings: dict, check_pattern=None) -> dict:
    """What of a file's settings may be written into a config this import
    just made. Only the keys settings_allowed gives this install, each the
    same kind as the install's own value, and a file name pattern only when
    check_pattern finds nothing wrong with it. With no way to check a
    pattern, none is taken."""
    if not isinstance(settings, dict):
        return {}
    allowed = settings_allowed(install)
    example = _read_json(install / "config.example.json")
    example = example if isinstance(example, dict) else {}
    out = {}
    for key, value in settings.items():
        if key not in allowed or not _fits(value):
            continue
        ref = example.get(key, cfg.get(key))
        if ref is not None and not _same_kind(ref, value):
            continue
        if key in NAMING_KEYS:
            if not isinstance(value, str):
                continue
            if value and (check_pattern is None or check_pattern(value)):
                continue
        if key == "owner":
            value = str(value or "").strip()[:80]
        out[key] = value
    return out


def scan(root: Path, keep=None) -> list:
    """Every place under root that keeps a history, one for each person on
    each install, then any folder with a history and no app of its own.
    keep, when given, says whether a folder may be read at all, and one it
    refuses is left out with a line saying so (the panel on PaperPull Server
    keeps to its data folder that way).

    A second person's folder sits beside the install, holding records and
    no app, so it is found through the person's config and not again as a
    folder of its own."""
    found, claimed = [], set()
    try:
        children = [c for c in sorted(root.iterdir())
                    if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        return found
    for install in children:
        script = _entry_script(install)
        if script is None:
            continue
        provider, kind = _provider_kind(install)
        for label, cfg_path in account_configs(install):
            if cfg_path.is_file():
                cfg = _read_json(cfg_path)
                if not isinstance(cfg, dict):
                    _say("  skipping %s, its %s could not be read" % (install.name, cfg_path.name))
                    continue
                where = output_dir_of(install, cfg, provider)
            else:
                # Not set up yet, or set up before configs, when the
                # records sat beside the app.
                cfg, where = {}, install
            key = os.path.normcase(str(where))
            if key in claimed:
                continue
            claimed.add(key)
            if keep is not None and not keep(where):
                _say("  skipping %s, its folder is outside the data folder" % where.name)
                continue
            recs = {}
            if (where / "progress.json").is_file():
                recs = _records(where / "progress.json")
                if recs is None:
                    _say("  skipping %s, its progress.json could not be read" % where.name)
                    continue
            found.append({"folder": where.name, "install": install.name, "account": label,
                          "provider": provider, "kind": kind, "path": where,
                          "records": recs, "settings": settings_of(install, cfg),
                          "config": cfg_path if cfg_path.is_file() else None})
    for child in children:
        if os.path.normcase(str(child)) in claimed or _entry_script(child) is not None:
            continue
        if keep is not None and not keep(child):
            continue
        provider, kind = identify(child)
        if provider is None:
            continue
        recs = _records(child / "progress.json")
        if recs is None:
            _say("  skipping %s, its progress.json could not be read" % child.name)
            continue
        found.append({"folder": child.name, "install": child.name, "account": "primary",
                      "provider": provider, "kind": kind, "path": child,
                      "records": recs, "settings": {}, "config": None})
    return found


def _done(rec: dict) -> bool:
    """Skipped by the app, as its own _already_done decides. A record an
    older version finished when the receipt page did not show the receipt
    is asked for again, so it is not done (paperpull_core.not_shown)."""
    return bool(rec.get("downloaded_ok")
                or (rec.get("state") in TERMINAL and not asked_again(rec)))


def skip_fields_of(provider: str) -> tuple:
    """The fields --minimal carries for one provider's records."""
    return SKIP_FIELDS + PROVIDER_SKIP_FIELDS.get(provider, ())


def _own_fields(rec: dict, provider: str) -> tuple:
    """The fields one provider's own checks read off this record, besides
    those every app's skip decision reads."""
    which, fields = PROVIDER_KIND_FIELDS.get(provider, (None, ()))
    unfinished = () if _done(rec) else PROVIDER_UNFINISHED_FIELDS.get(provider, ())
    return (PROVIDER_SKIP_FIELDS.get(provider, ()) + (fields if fields and which(rec) else ())
            + unfinished)


def _skip_fields(rec: dict, provider: str = "") -> dict:
    """The fields a skip decision reads, the provider's own among them. For
    a record asked for again that is its last note too, one of the fixed
    words an older version wrote, which says nothing of the purchase."""
    out = {f: rec[f] for f in SKIP_FIELDS + _own_fields(rec, provider) if f in rec}
    if asked_again(rec):
        out["notes"] = str(rec.get("notes") or "").rsplit("; ", 1)[-1].strip()
    return out


def describe(entry: dict) -> str:
    """A provider, and the person when it is not the first one."""
    acct = entry.get("account") or "primary"
    return entry["provider"] if acct == "primary" else "%s (%s)" % (entry["provider"], acct)


def _reader(place: dict, places: list) -> str:
    """The provider whose code reads this place's records. A folder left with
    records and no app is named for its folder, and a second person's sits
    beside the install, named "<install> - <name>" by tools/add_account.py,
    so it would miss its provider's own fields."""
    if (place["path"] / "storage.py").is_file():
        return place["provider"]
    beside = [p for p in places if (p["path"] / "storage.py").is_file()
              and place["folder"].startswith(p["folder"] + " - ")]
    return max(beside, key=lambda p: len(p["folder"]))["provider"] if beside else place["provider"]


def _under_cut_key(key: str, rec: dict, provider: str = "") -> bool:
    """Whether a record is still under a key that left out its account's
    last four, so the app moves it to the key that keeps them as it loads.
    Its key holds the account cut to forty characters and not the account
    with the last four, each built as the provider's app builds them. An
    account with no last four, or one that fits outside Chase, is the same
    both ways and never moves."""
    account = rec.get("account")
    if not account or not isinstance(account, str):
        return False
    raw = sanitize_component(account)
    whole = account_component(raw)
    if provider in LAST_FOUR_AT_ANY_LENGTH:
        # Cut to nothing, the account is its last four alone, as "-1234".
        whole = raw[:40] + account_component(raw, limit=0)
    return raw[:40] in key and whole not in key


def _key_fields(key: str, rec: dict, provider: str = "") -> dict:
    """What the app rebuilds a record's key from, for a record still under
    a key that left out the last four, and nothing for any other."""
    if not _under_cut_key(str(key), rec, provider):
        return {}
    return {f: rec[f] for f in KEY_FIELDS if f in rec}


# -- export ------------------------------------------------------------------

def build(root: Path, minimal: bool = False, keep=None):
    """(the export file's bytes, its manifest), or (None, None) when nothing
    under root keeps a history. Written in memory, so the control panel can
    hand it to a browser without leaving a copy anywhere. keep is scan's."""
    places = scan(root, keep)
    if not places:
        return None, None
    manifest = {"schema": SCHEMA, "created": datetime.now().isoformat(timespec="seconds"),
                "version": _version(), "source_root": str(root), "minimal": bool(minimal),
                "apps": []}
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for place in places:
            recs = place["records"]
            reader = _reader(place, places)
            if minimal:
                recs = {k: dict(_skip_fields(v, reader), **_key_fields(k, v, reader))
                        for k, v in recs.items()}
            private = PROVIDER_PRIVATE_FIELDS.get(reader, ())
            if private:
                recs = {k: {f: x for f, x in v.items() if f not in private}
                        for k, v in recs.items()}
            name, n = place["folder"], 2
            while name.lower() in used:
                name, n = "%s (%d)" % (place["folder"], n), n + 1
            used.add(name.lower())
            member = "apps/%s/progress.json" % name
            entry = {"folder": place["folder"], "install": place["install"],
                     "account": place["account"], "provider": place["provider"],
                     "kind": place["kind"], "source_dir": str(place["path"]),
                     "records": len(recs),
                     "already_downloaded": sum(1 for r in place["records"].values() if _done(r)),
                     "file": member}
            if not minimal:
                entry["settings"] = place["settings"]
            manifest["apps"].append(entry)
            z.writestr(member, json_text(recs))
        z.writestr("manifest.json", json_text(manifest))
        z.writestr("README.txt", _READ_ME)
    return buf.getvalue(), manifest


def export(root: Path, out: Path, minimal: bool = False) -> int:
    data, manifest = build(root, minimal)
    if data is None:
        _say("No installs with a download history were found under %s" % root)
        return 1
    out.write_bytes(data)

    total = sum(a["records"] for a in manifest["apps"])
    _say("Exported %d records from %d places" % (total, len(manifest["apps"])))
    _say("  to %s" % out)
    for a in manifest["apps"]:
        _say("    %-32s %5d records, %d already downloaded"
             % (describe(a)[:32], a["records"], a["already_downloaded"]))
    _say()
    _say("This file describes your archive, so keep it as private as the archive.")
    _say("It holds no passwords, cookies or session tokens.")
    if minimal:
        _say("Written with --minimal, so item lists, totals and settings are left out.")
        _say("Order and invoice numbers remain, and so do recorded file names, which")
        _say("can name accounts and items.")
    else:
        _say("It can contain account labels, document titles, order numbers,")
        _say("purchase totals, itemized purchases and account holders' names.")
        _say("Use --minimal to leave most of that out.")
    return 0


_READ_ME = """PaperPull download history.

Made by PaperPull's Export history, or by tools/migrate.py. Bring it to
another computer, or to PaperPull Server, with Import a history file on the
control panel's Status tab, or with:

    python migrate.py --import <this file>

It carries the record of which documents have already been downloaded, so a
fresh install skips them instead of fetching them again, and each provider's
and person's settings. It does NOT contain any PDF, and it does NOT contain
any password, cookie or session token.

Depending on which apps you run it may contain account labels, document
titles, order numbers, purchase totals, store locations and the account
holders' names. Keep it as private as the archive it describes.
"""


# -- reading a file ----------------------------------------------------------

def _member(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """One file inside the zip, read no further than limit, whatever size
    the zip says it is."""
    try:
        with z.open(name) as f:
            data = f.read(limit + 1)
    except KeyError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, EOFError) as e:
        raise NotAnExport("Part of that file could not be read (%s)." % str(e)[:80])
    if len(data) > limit:
        raise NotAnExport("That file is far larger than any download history, "
                          "so it was not read.")
    return data


def _entry(raw: dict, schema: int):
    """One provider or person from a manifest, in the shape this version
    reads, or None when it names nothing."""
    folder = str(raw.get("folder") or "")
    provider = str(raw.get("provider") or folder)
    if not provider:
        return None
    account = str(raw.get("account") or "primary").strip().lower() if schema >= 2 else "primary"
    member = str(raw.get("file") or "") if schema >= 2 else ""
    settings = raw.get("settings") if schema >= 2 else None
    return {"schema": schema, "folder": folder, "provider": provider,
            "kind": raw.get("kind") if raw.get("kind") in ("DOCUMENT", "RECEIPT") else None,
            "account": account or "primary",
            "source_dir": str(raw.get("source_dir") or "") if schema >= 2 else "",
            "settings": settings if isinstance(settings, dict) else {},
            "file": member or "apps/%s/progress.json" % folder,
            "incoming": None}


def read(source) -> dict:
    """An export's manifest, every entry with the records it carries under
    "incoming" (None when the file lacks them), from a path or the file's
    bytes. Raises NotAnExport with a sentence for a file it will not read."""
    try:
        z = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray))
                            else source)
    except (OSError, zipfile.BadZipFile, ValueError):
        raise NotAnExport("That is not a readable export file.")
    with z:
        try:
            manifest = json.loads(_member(z, "manifest.json", MAX_MANIFEST_BYTES).decode("utf-8"))
        except (KeyError, ValueError):
            raise NotAnExport("That file has no manifest, so it was not made by PaperPull.")
        if not isinstance(manifest, dict):
            raise NotAnExport("That file has no manifest, so it was not made by PaperPull.")
        schema = manifest.get("schema")
        if schema not in READS:
            raise NotAnExport("That export was written by a different version of PaperPull "
                              "(schema %s, this one reads %s)."
                              % (schema, " and ".join(str(s) for s in READS)))
        apps = manifest.get("apps")
        if not isinstance(apps, list) or len(apps) > MAX_ENTRIES:
            raise NotAnExport("That file's manifest lists no providers.")
        entries, total, count, read_once = [], 0, 0, set()
        too_big = NotAnExport("That file is far larger than any download history, "
                              "so it was not read.")
        for raw in apps:
            entry = _entry(raw, schema) if isinstance(raw, dict) else None
            if entry is None:
                continue
            # Each entry has a file of its own. Several naming one would
            # each read it again, and pass the limits as several small ones.
            if entry["file"] in read_once:
                raise NotAnExport("That file names one history for two places, "
                                  "so it was not made by PaperPull.")
            read_once.add(entry["file"])
            entries.append(entry)
            try:
                data = _member(z, entry["file"], MAX_RECORDS_BYTES)
            except KeyError:
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise too_big
            try:
                recs = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(recs, dict):
                count += len(recs)
                if count > MAX_RECORDS:
                    raise too_big
                entry["incoming"] = {str(k): v for k, v in recs.items() if isinstance(v, dict)}
    out = {k: v for k, v in manifest.items() if k != "apps"}
    out["schema"] = schema
    out["apps"] = entries
    return out


def match(entry: dict, places: list):
    """The place here that keeps this entry's history. The same provider and
    person, then, only for a file from before people were told apart, a
    folder of the same name, which is how a second person's folder came
    across then. A newer file says whose each history is, and a folder's
    name says nothing more, since two people's output folders can share one
    and a folder can hold another provider's history."""
    provider = entry["provider"].lower()
    for place in places:
        if place["provider"].lower() == provider and place["account"] == entry["account"]:
            return place
    folder = (entry.get("folder") or "").lower()
    if folder and entry.get("schema", 1) < 2:
        for place in places:
            if place["folder"].lower() == folder:
                return place
    return None


def history_at(where: Path):
    """The records a place already keeps, {} when it keeps none yet, None
    when its progress.json is there and cannot be read."""
    path = Path(where) / "progress.json"
    return _records(path) if path.is_file() else {}


def bases_of(entry: dict, manifest: dict) -> list:
    """The folders an entry's paths were written under on the other machine."""
    out = []
    if entry.get("source_dir"):
        out.append(entry["source_dir"])
    root = str(manifest.get("source_root") or "")
    if root and entry.get("folder"):
        out.append(root.rstrip("\\/") + "/" + entry["folder"])
    return out


# -- import ------------------------------------------------------------------

def _is_absolute(path: str) -> bool:
    """True for a path that names a particular machine, on either platform.

    Path.is_absolute answers for the platform this code is running on, and an
    export written on Windows can be imported on a Mac, where a drive-letter
    path would otherwise look relative and be kept as-is.
    """
    p = (path or "").replace("\\", "/")
    return p.startswith("/") or (len(p) > 2 and p[1] == ":" and p[2] == "/")


def _stays_inside(rel: str) -> bool:
    """Whether a path relative to a folder stays inside it."""
    p = rel.replace("\\", "/")
    if not p or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return False
    norm = posixpath.normpath(p)
    return norm not in (".", "..") and not norm.startswith("../")


def _rewrite_path(old: str, old_bases, new_base: Path) -> str:
    """Point a recorded PDF path at this machine, or clear it.

    A path that cannot be rewritten is CLEARED rather than left alone. The
    skip logic asks whether a manual-review copy is still on disk, and a path
    from another computer would answer that question wrongly. So is one
    under the old folder that would lead back out of it once moved.
    """
    if not old:
        return ""
    # The apps do not agree on this. Some record a path relative to their own
    # folder, others the full absolute one. A relative path is already portable
    # and is left exactly as it is. Only an absolute path names a machine. A
    # second person's paths begin with "..", since their folder sits beside
    # the install a run starts in, so a relative path is never judged by
    # whether it leaves a folder (a saved invoice with no path is taken
    # again by Target).
    if not _is_absolute(old):
        return old
    norm = old.replace("\\", "/")
    for base in old_bases or ():
        b = str(base or "").replace("\\", "/").rstrip("/")
        # The folder itself and then a separator, so "Bank Statements" is
        # never taken for the start of "Bank Statements - spouse".
        if b and norm.lower().startswith(b.lower() + "/"):
            tail = norm[len(b) + 1:]
            if _stays_inside(tail):
                return str(new_base / Path(posixpath.normpath(tail)))
            return ""
    return ""


def _under(path: str, old_bases) -> bool:
    norm = path.replace("\\", "/").lower()
    return any(b and norm.startswith(b + "/")
               for b in (str(x or "").replace("\\", "/").rstrip("/").lower()
                         for x in old_bases or ()))


def _moved(rec: dict, old_bases, new_base: Path) -> dict:
    """A record from another machine with its paths pointed at this one.

    Target keeps one file for each invoice of an order as well. An invoice
    whose path names some other folder of that machine, or a relative one,
    keeps it, since a saved invoice counts as saved whether or not its file
    is there, and an entry with no file is not counted at all. One under the
    old folder that would lead out of it once moved is cleared, as a PDF
    path is."""
    rec = dict(rec)
    rec["pdf_path"] = _rewrite_path(str(rec.get("pdf_path") or ""), old_bases, new_base)
    invoices = rec.get("invoices")
    if isinstance(invoices, list):
        out = []
        for inv in invoices:
            if isinstance(inv, dict) and isinstance(inv.get("file"), str) and inv["file"]:
                old = inv["file"]
                moved = _rewrite_path(old, old_bases, new_base)
                if not moved and _is_absolute(old) and not _under(old, old_bases):
                    moved = old
                inv = dict(inv, file=moved)
            out.append(inv)
        rec["invoices"] = out
    return rec


def _merge(target: dict, incoming: dict, old_bases, new_base: Path, home=None,
           provider: str = ""):
    """Fold incoming records into target, `provider`'s, whose own checks
    read the fields _own_fields names. Never deletes, never downgrades.
    `home` is the folder the target's app runs in, which a relative path in
    its records is read against, new_base when not given.

    The caller must hand over a DEEP copy. dict(records) copies only the outer
    mapping, so the record objects stay shared, and this function edits them in
    place. The plan pass then silently applied itself, and the apply pass that
    followed found nothing left to do and reported zero changes against a plan
    that had promised several.
    """
    added = updated = 0
    for key, inc in incoming.items():
        cur = target.get(key)
        if cur is None:
            rec = _moved(inc, old_bases, new_base)
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
        # A record an older --minimal brought here holds none of what its
        # key is built from, where a record the app wrote holds all of it.
        # It takes that from a file that carries it, so the app can move it
        # off a key that left out the last four.
        if not any(f in cur for f in KEY_FIELDS):
            carried = {f: inc[f] for f in KEY_FIELDS if f in inc}
            if carried:
                cur.update(carried)
                changed = True
        # It lacks what its provider's own checks read too, the digest of a
        # saved statement, the address of a saved form or the list of an
        # order's saved invoices, which a newer file carries. Each field it
        # lacks is filled in, with its paths pointed at this machine as a
        # record added is, and one it holds stays, since a run here wrote it
        # or emptied it on purpose.
        here = _moved(inc, old_bases, new_base)
        lacking = {f: here[f] for f in _own_fields(inc, provider) if f in inc and f not in cur}
        # Where a run stopped on the old computer goes on here only for a
        # purchase this install has not finished either, and only when it
        # holds none of it, since its own runs counted with one list and not
        # the other would say they were not asked on runs never refused.
        unfinished = PROVIDER_UNFINISHED_FIELDS.get(provider, ())
        if _done(cur) or any(f in cur for f in unfinished):
            lacking = {f: v for f, v in lacking.items() if f not in unfinished}
        if lacking:
            cur.update(lacking)
            changed = True
        if _takes_the_state(cur, inc, Path(home or new_base)):
            cur["state"] = inc["state"]
            # The state comes with what it was written with. A receipt set
            # aside is final in Meijer only with its days, and a note an
            # older version wrote here would have it asked for again.
            if DAYS_KEY in inc:
                cur[DAYS_KEY] = list(inc[DAYS_KEY] or [])
            if asked_again(cur):
                cur["notes"] = _last_note_replaced(cur, inc)
            changed = True
        if changed:
            cur["imported_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1
    return added, updated


def merged(place: dict, entry: dict, manifest: dict):
    """(the place's records with the entry's folded in, how many were added,
    how many were marked done). The place's own records are not touched, so
    a plan and the import that follows count the same."""
    out = copy.deepcopy(place["records"])
    added, updated = _merge(out, entry["incoming"] or {}, bases_of(entry, manifest),
                            Path(place["path"]), home_of(place),
                            provider=place.get("provider", ""))
    return out, added, updated


def home_of(place: dict) -> Path:
    """The folder a place's app runs in, the install that holds the
    person's config. A relative path in its records is read against it,
    as the app reads it. A folder with no config is its own."""
    config = place.get("config")
    return Path(config).parent if config else Path(place["path"])


def write_history(where: Path, records: dict, stamp: str, write=None) -> None:
    """A place's progress.json, written in one step, with the one it
    replaces kept in its Backups first. Raises OSError. write, when given,
    writes each of the two files whole in place of the plain writes here
    (the control panel on PaperPull Server passes one that never writes
    through a link left in the shared folder)."""
    path = Path(where) / "progress.json"
    Path(where).mkdir(parents=True, exist_ok=True)
    text = json_text(records)
    if path.is_file():
        backups = Path(where) / "Backups"
        backups.mkdir(parents=True, exist_ok=True)
        kept = backups / ("progress.%s.before-import.bak" % stamp)
        if write is not None:
            write(kept, path.read_bytes())
        else:
            kept.write_bytes(path.read_bytes())
    if write is not None:
        write(path, text)
        return
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _takes_the_state(cur: dict, inc: dict, home: Path) -> bool:
    """Whether a record the target already had takes the incoming state.
    Only one this install has not finished, and only for a state that
    finishes it. A record an older version gave up on here is asked for
    again, and takes a state only from a record that settled it, a save or
    a receipt set aside. An export from before 0.45.0 carried no notes, so
    its record of the same gave-up purchase looks finished without them.

    A copy put aside for review here keeps its record while the copy is
    still on disk. Every app holds that done, and deleting the copy is how
    a person asks for it again (#42), which a final state from elsewhere
    would end."""
    if not _done(dict(inc, downloaded_ok=False)):
        return False
    if _in_review_here(cur, home):
        return False
    if cur.get("state") not in TERMINAL:
        return True
    return (asked_again(cur)
            and (inc.get("state") != "No Receipt Available" or set_aside(inc)))


def _in_review_here(rec: dict, home: Path) -> bool:
    """A record of this install whose copy put aside for review is still
    where it says. A relative path is the app's own folder's, home, since
    an install made with config.example.json writes into "." and a second
    person's folder is "../<install> - <name>". The apps also ask that the
    copy opens. One that does not keeps its record too, and the app tries
    the purchase again, as it would have without the import."""
    if rec.get("state") != "Needs Manual Review":
        return False
    path = str(rec.get("pdf_path") or "")
    if not path:
        return False
    try:
        where = Path(path) if _is_absolute(path) else Path(home) / path.replace("\\", "/")
        return where.is_file()
    except (OSError, ValueError):
        return False


def _last_note_replaced(cur: dict, inc: dict) -> str:
    """The target's notes, its last one, written with the state it gives up,
    swapped for the incoming last note. The notes before it stay."""
    kept = str(cur.get("notes") or "").rsplit("; ", 1)
    kept = kept[0] if len(kept) > 1 else ""
    last = str(inc.get("notes") or "").rsplit("; ", 1)[-1].strip()
    return "; ".join(n for n in (kept, last) if n)


def do_import(archive: Path, root: Path, dry_run: bool = False,
              assume_yes: bool = False) -> int:
    try:
        manifest = read(archive)
    except NotAnExport as e:
        _say("%s %s" % (archive, e))
        return 1

    places = scan(root)
    plan, missing = [], []
    for entry in manifest["apps"]:
        place = match(entry, places) if entry["incoming"] is not None else None
        (plan if place is not None else missing).append((entry, place))

    _say("Import plan, from %s" % archive)
    _say("  into %s" % root)
    _say()
    for entry, place in plan:
        _, added, updated = merged(place, entry, manifest)
        _say("  %-30s %4d new, %4d marked done, %d already known"
             % (describe(place)[:30], added, updated, len(place["records"])))
    for entry, _ in missing:
        why = ("ITS HISTORY IS MISSING FROM THE FILE" if entry["incoming"] is None
               else "NOT SET UP HERE")
        _say("  %-30s %s, skipped" % (describe(entry)[:30], why))
    if missing and any(e["incoming"] is not None for e, _ in missing):
        _say("  Import a history file on the control panel's Status tab sets those up.")
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

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for entry, place in plan:
        records, added, updated = merged(place, entry, manifest)
        try:
            write_history(place["path"], records, stamp)
        except OSError as e:
            _say("  could not write %s (%s), skipping it" % (describe(place), e))
            continue
        place["records"] = records
        _say("  %-30s %4d new, %4d marked done" % (describe(place)[:30], added, updated))

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
