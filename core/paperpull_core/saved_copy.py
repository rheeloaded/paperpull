"""The record of a receipt or a document already saved, and a Download
again that saves no copy of its own.

A receipt app saves a purchase once for good. Its record in progress.json
then carries downloaded_ok and names the saved file, with the summary, the
confidence and the state it ended in, and Rename, Review Names, the Pilot
report, the panel's naming preview and its Status all read it. The panel's
Download again runs an app with --redownload, so the app takes such a
purchase again, from discovery.json, which holds no file. Every step of
the attempt wrote the whole purchase into the record. One that ended with
nothing saved, at a page that would not open, a page that was not the
purchase's, no receipt, a control it could not read, an error, or a copy
that failed its check and was put aside, left the record naming no file
or the copy put aside, with the attempt's summary and state, and after a
wrong page with another purchase's facts. Rename then named the saved file
for them, and Review Names no longer took the record for the saved copy's.

So holds() stands between each receipt app's _record_state and the record.
Until this run has saved a copy of its own for a purchase, a write to the
record of one saved before changes nothing in it but its notes, which say
what the attempt came to. Discovery's state is left as it was as well,
since Apple and Uber read it to tell which purchases are settled. A write
that saves a copy carries downloaded_ok True, and from then on the
attempt's writes take the record as they always did, since it now names
the attempt's own copy. downloaded_ok is never taken away here, so a
purchase saved once is still never fetched again by a plain run, and only
another Download again tries it.

A document app is the same. Its one _record wrote the whole document as
discovery lists it, which names no file and was never downloaded, so an
attempt that saved nothing also took downloaded_ok off a saved document
and the next plain run fetched it again, a copy the person may have
deleted on purpose after importing it elsewhere. Capital One and Schwab
write the id a later listing gives a known document into discovery, so
the attempt wrote that id over the one the file was saved under as well.
holds() stands between each document app's _record and the record in the
same way, and a purchase here is a document there.

holding() is the same question for a write an app makes outside
_record_state, Kroger's store in the purchase list and Walmart's date read
off an order page, and tried() is what the Pilot report says of an
attempt held in this run.
"""
from __future__ import annotations

import os

# The first words of what an attempt that saved nothing adds to the saved
# copy's notes. A later attempt's entry takes the place of the one found by
# them, so the notes say only how the latest one ended.
NOTE = "Download again saved nothing new"
_ENTRY = NOTE + ", and only another Download again tries it (%s)"

# Kept on the app, since a run is one app object and a new run starts with
# neither. The purchases this run has saved a copy of, and the entry each
# held attempt left in the notes.
_SAVED_NOW = "_saved_copies_this_run"
_HELD_NOW = "_held_attempts_this_run"


def _kept_on(app, name: str, empty):
    found = getattr(app, name, None)
    if found is None:
        found = empty
        setattr(app, name, found)
    return found


def holding(app, key: str) -> bool:
    """True while the record of `key` is that of a purchase saved before
    and this run has saved no copy of its own for it."""
    if key in _kept_on(app, _SAVED_NOW, set()):
        return False
    return bool((app.progress.get(key) or {}).get("downloaded_ok"))


def holds(app, key: str, rec: dict, also=()) -> bool:
    """True when `rec` is a write over the record of a purchase saved
    before, by an attempt that has saved no copy of its own in this run.
    The record then keeps everything it had, its notes say how the attempt
    ended, and the app writes nothing more, to progress or to discovery.

    `also` names keys of the attempt's own that are written all the same,
    Target's list of the invoices a walk put on disk, so that none of them
    is saved twice."""
    if rec.get("downloaded_ok") is True:
        _kept_on(app, _SAVED_NOW, set()).add(key)
        _kept_on(app, _HELD_NOW, {}).pop(key, None)
        return False
    if not holding(app, key):
        return False
    old = app.progress.get(key) or {}
    if rec.get("state") != _ON_ITS_WAY and _names_its_copy(old, rec):
        # The write takes the record, and no longer says the document is
        # saved. A receipt's record carries no downloaded_ok of its own and
        # a write merges into the record, so it is said here.
        rec["downloaded_ok"] = False
        return False
    patch = {name: rec[name] for name in also if name in rec}
    entry = _ENTRY % ", ".join(_said(rec.get("state"), rec.get("notes")))
    patch["notes"] = "; ".join(
        [p for p in str(old.get("notes") or "").split("; ") if p and not p.startswith(NOTE)]
        + [entry])
    app.progress.update(key, patch)
    _kept_on(app, _HELD_NOW, {})[key] = entry
    return True


# The state an app writes between putting a copy on disk and checking it.
# The copy is on its way, to be kept or put aside, so the attempt is judged
# by the write that ends it.
_ON_ITS_WAY = "PDF Saved"


def _names_its_copy(old: dict, rec: dict) -> bool:
    """Whether the write that ends an attempt names the saved record's own
    file as the attempt's copy.

    The person deleted the saved file, the usual reason for Download again,
    so the attempt saved under that very name. A copy that failed its check
    and could not be moved to Manual Review stayed there. A record kept as
    it was then vouched for that copy as the one saved, and no later run
    fetched the document again, so that write takes the record and the next
    plain run fetches it again. The file's size is not asked. A person who
    runs OCR over a saved PDF, or annotates it, changes its size, and the
    saved copy is still theirs. A copy an error cut short before any write
    named it, or a run ended just after "PDF Saved", is not told apart from
    the saved one here."""
    path = str(old.get("pdf_path") or "")
    return bool(path) and _one_file(str(rec.get("pdf_path") or ""), path)


def _one_file(a: str, b: str) -> bool:
    """Whether two recorded paths name one file. A run records a path
    relative to the folder it works in, the install, but a run that 0.62.0
    to 0.65.0 started in another folder recorded the full path (#166). So
    two paths are one file when they read alike, or when each read from
    the folder this run works in is the same path, or when the two are one
    file on disk."""
    if not a:
        return False
    if a == b:
        return True
    try:
        if os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
            return True
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def tried(app, key: str) -> str:
    """The entry a Download again held in this run left in the notes of
    `key`, or empty when there was none."""
    return _kept_on(app, _HELD_NOW, {}).get(key, "")


def _said(state, notes) -> list:
    """The attempt's state and its own notes, each a part of one entry. An
    app joins a purchase's notes with semicolons, so they are taken apart
    here and joined with commas inside the entry."""
    return [w for w in [str(state or "")] + str(notes or "").split("; ") if w]
