"""The account part of a document's identity, and moving old ones over.

A document is remembered by a key built from its category, date, title and
account, and the account was cut to forty characters. Two cards of the same
product are named identically until the masked last four at the end, so
"MARRIOTT BONVOY BOUNDLESS CREDIT CARD (...1234)" and the same card ending
5678 produced the same key. The second card's entire history was read as
already downloaded and dropped, on every run, without a word anywhere.

It was found in Chase and fixed in Chase. Thirty-eight other apps had the
same forty characters, and the labels that overrun them are already sitting
in this repository's own fixtures: "U.S. Bank Cash+ Visa Signature Card
(...1234)" is forty-five characters and "Triple Cash Rewards World Elite
Mastercard ...7890" is fifty.

The key only changes for an account long enough to have been cut, so an
archive whose accounts are short is untouched and needs no migration at
all. For the rest, migrate_account_keys moves the record across the first
time the app runs, because a key that changes underneath an archive means
every document in it looks new and gets downloaded again beside the copy
already there.
"""
from __future__ import annotations

import re

# Any masked tail a provider writes: "(...1234)", "...1234", "****1234",
# "xxxx1234", or a plain trailing four digits.
_LAST_FOUR = re.compile(r"(\d{4})\s*\)?\s*$")
_ADDED_FOUR = re.compile(r"-\d{4}")

# What counts as finished, so a migration never lets a fresh discovery or a
# failed retry overwrite a completed record.
TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}


def account_component(account: str, limit: int = 40) -> str:
    """The account, short enough for a key and still telling two apart.

    Unchanged when it fits, which is most of them, so most archives never
    notice this exists. When it does not fit, the masked last four is kept,
    because that is the part that says which account this is.
    """
    raw = account or ""
    if len(raw) <= limit:
        return raw
    found = _LAST_FOUR.search(raw)
    return raw[:limit] + ("-" + found.group(1) if found else "")


def is_done(record: dict) -> bool:
    return bool(record.get("downloaded_ok") or record.get("state") in TERMINAL)


def _identity(record: dict) -> tuple:
    return tuple(record.get(field, "") for field in
                 ("category", "date", "title", "account", "document_id"))


def migrate_account_keys(records: dict, key_of) -> int:
    """Move records from the cut key to the one that keeps the last four.

    `key_of` takes a stored record and answers the key it should have now.

    A record is only moved when its current key is exactly the new key with
    the last four taken off, which is proof that this is the change being
    made and not some other difference. Anything else stays where it is,
    because guessing which record an unrecognized key belongs to is how one
    account's completed history ends up marking another's as done.
    """
    changed = 0
    for old_key, record in list(records.items()):
        if not isinstance(record, dict):
            continue
        try:
            new_key = key_of(record)
        except Exception:
            continue
        if not new_key or new_key == old_key:
            continue
        # Taking the added last four back out has to give exactly the key
        # this record is stored under. Anywhere in the key, because two apps
        # put the account first and the rest put it last.
        if not any(new_key[:m.start()] + new_key[m.end():] == old_key
                   for m in _ADDED_FOUR.finditer(new_key)):
            continue
        current = records.get(new_key)
        if current is not None and _identity(current) != _identity(record):
            continue
        # A fresh discovery or a failed retry must not erase finished history.
        winner = record if current is None or (
            is_done(record) and not is_done(current)) else current
        records[new_key] = dict(winner)
        del records[old_key]
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# Which one of several documents that share a title and a date
# ---------------------------------------------------------------------------

def stable_occurrences(rows, existing=None, fields=("title", "date")):
    """Number the rows that share a title and a date, the same way every run.

    Five apps have no account in the document's key and tell two documents
    of the same title and date apart by counting them: the first is 0, the
    next is 1. The counting followed the order the provider's API happened
    to answer in.

    Two accounts at Fidelity both have a Quarterly Statement for the same
    quarter. If that answer ever comes back the other way around, the one
    already downloaded takes the other's number, so it is skipped as done
    and the other is fetched again beside it, with the archive now wrong
    about which is which.

    A number already given to a document keeps it, which is looked up by
    what the document IS rather than where it appeared. Only a document
    nobody has seen takes a new number, the lowest one still free. An
    archive that already exists therefore keeps every key it has.
    """
    def tidy(value):
        # The stored record has been through the app's own cleanup and the
        # raw row has not, so both sides are tidied before being compared.
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def what_it_is(item):
        return tuple(tidy(item.get(f, "")) for f in fields) + (tidy(item.get("account")),)

    rows = list(rows)
    known = {}
    for record in (existing or {}).values():
        if not isinstance(record, dict):
            continue
        what = what_it_is(record)
        if what not in known:
            known[what] = record.get("occurrence", 0) or 0

    taken = {}
    out = [None] * len(rows)
    for i, row in enumerate(rows):
        group = tuple(tidy(row.get(f, "")) for f in fields)
        what = what_it_is(row)
        if what in known:
            occurrence = known.pop(what)
            if occurrence not in taken.setdefault(group, set()):
                taken[group].add(occurrence)
                out[i] = occurrence

    for i, row in enumerate(rows):
        if out[i] is not None:
            continue
        group = tuple(tidy(row.get(f, "")) for f in fields)
        used = taken.setdefault(group, set())
        occurrence = 0
        while occurrence in used:
            occurrence += 1
        used.add(occurrence)
        out[i] = occurrence
    return out
