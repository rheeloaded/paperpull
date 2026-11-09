"""Filesystem, filename, CSV and progress storage shared by every PaperPull app.

Provider-specific facts (name, folders, routing, columns, config defaults)
come from the AppSpec the app binds at import time - see spec.py.

All writes are local. JSON files are written atomically (temp file + replace)
and CSV/JSON files are backed up with a timestamp before being rewritten.
"""
from __future__ import annotations

import csv
import json
import ntpath
import os
import re
import sys
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePath
from typing import Dict, Iterable, List, Optional

from . import shared_folder
from .characters import json_escaped, whole_characters, whole_json
from .run_reporting import on_one_line, one_line
from .sheets import read_stored, read_stored_row, store_value
from .spec import INFRASTRUCTURE_FOLDERS, RECEIPT

# ---------------------------------------------------------------------------
# Paths / configuration
# ---------------------------------------------------------------------------

_SPEC = None

# Logs, Diagnostics and Backups, which every app has and which hold a run's
# own records and never a document. Manual Review, the fourth folder every
# app has, is where a document is put aside.
_RECORD_FOLDERS = {folder.attr for folder in INFRASTRUCTURE_FOLDERS} - {"manual_review"}
# The folders that stay in the output folder, beside the run's records,
# whatever documents_dir says (#102). Manual Review is one of them, since a
# file put aside there failed its check and must never reach a folder
# another program watches.
_KEPT_WITH_RECORDS = {folder.attr for folder in INFRASTRUCTURE_FOLDERS}

# The documents folder load_config read for each output folder, by
# _folder_key of that folder (#102). Paths reads it, so every app gets it
# from the Paths it builds from its config's output_dir.
_DOCUMENTS = {}
# Each documents folder an account's documents were moved to, a JSON list
# of full paths in its output folder (Paths.documents_roots).
DOCUMENTS_FOLDERS = "documents-folders.json"
# The config file load_config last read, which Login asks about, since a
# sign-in is opened on that config's port (ports.say_at_sign_in).
_CONFIG_READ = None


def _folder_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def documents_dir_for(output_dir) -> str:
    """The documents folder load_config read for this output folder, or ""
    when documents go to the output folder itself."""
    return _DOCUMENTS.get(_folder_key(output_dir), "")


def bind(spec) -> None:
    """Attach this process's AppSpec. Called once by the app's storage shim."""
    global _SPEC, _CONFIG_READ
    _SPEC = spec
    # A documents folder belongs to the config load_config reads next, and
    # so does the file a sign-in asks about.
    _DOCUMENTS.clear()
    _CONFIG_READ = None
    from . import receipt_pdf
    receipt_pdf.bind(spec)


def spec():
    if _SPEC is None:
        raise RuntimeError(
            "No AppSpec bound. The app's storage.py must call "
            "paperpull_core.storage.bind(SPEC) at import time.")
    return _SPEC


def load_config(path: Optional[Path] = None) -> dict:
    """Read config.json and fill in this provider's defaults."""
    sp = spec()
    if path:
        p = Path(path)
        path = p if p.is_absolute() or p.exists() else (sp.project_dir / p)
    else:
        path = sp.project_dir / "config.json"
    if not path.exists():
        copy_cmd = ("copy config.example.json config.json"
                    if sys.platform == "win32"
                    else "cp config.example.json config.json")
        lines = ["No config file at " + one_line(path) + "."]
        if (sp.project_dir / "config.example.json").exists():
            lines += ["Create one from the template, then edit the paths in it:",
                      "    " + copy_cmd]
        lines += ["This file holds your own folders, port and settings, which is",
                  "why it is not shipped and never committed."]
        raise SystemExit("\n".join(lines))
    try:
        # utf-8-sig: a config saved from Notepad carries a BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(
            one_line(path) + " is not valid JSON: " + str(e) + "\n"
            "Open it and fix the syntax - a trailing comma is the usual cause.")
    held = _not_on_one_line(cfg, path)
    if held:
        raise SystemExit(
            "%s, so this run stopped before doing anything. A run prints its folders "
            "and names, and the control panel reads what it prints line by line, so a "
            "name has to be one line of plain text. Rename it, or change the setting, "
            "and run again." % held)
    _anchor_to_config(cfg, path)
    if os.environ.get("PAPERPULL_SERVER") == "1":
        hold_to_the_server(cfg, path)
        refuse_links_out(cfg["output_dir"], path)
        if cfg.get("documents_dir"):
            refuse_links_out(cfg["documents_dir"], path)
    cfg.setdefault("output_dir", str(Path.home() / "Downloads" / sp.provider))
    cfg.setdefault("min_pdf_bytes", 3000)
    cfg.setdefault("max_path_length", 240)
    cfg.setdefault("delay_min_seconds", 2.0)
    cfg.setdefault("delay_max_seconds", 4.0)
    cfg.setdefault("profile_dir", str(sp.project_dir / f"{sp.slug}-browser-profile"))
    cfg.setdefault("owner", "")
    cfg.setdefault("owner_in_filename", False)
    # Which browser to sign in with.
    #   auto      use a Chromium-based browser you already have, and offer to
    #             download a private copy only if there is none
    #   installed only one you already have, never download anything
    #   bundled   only this tool's own private copy, never touch yours
    # Whichever is used gets its OWN profile folder, so an everyday browser's
    # history, extensions and logins are never read or altered.
    cfg.setdefault("browser", "auto")
    for key, value in sp.config_defaults.items():
        cfg.setdefault(key, value)
    # How files are named (#50). Read here because every app loads its
    # config before it names anything, so no app has to remember to.
    set_filename_patterns(cfg)
    # Where documents go (#102), read here for the same reason.
    set_documents_dir(cfg, path)
    global _CONFIG_READ
    _CONFIG_READ = Path(path).absolute()
    return cfg


def config_read() -> Optional[Path]:
    """The config file load_config last read, or None before it has."""
    return _CONFIG_READ


# The settings that name a folder, which a run prints and puts in the paths
# it prints. account_labels, the name a person gave each account, is looked
# through as well, since it goes into what a run says of each document.
# owner is not, since no run prints it (a name typed at the prompt is one
# line), and the control panel writes it from what a person types.
_NAMED_SETTINGS = ("output_dir", "profile_dir", "documents_dir")
# The folder settings a relative path is read from the config's folder for.
_ANCHORED_SETTINGS = ("output_dir", "profile_dir")


def _anchor_to_config(cfg, path) -> None:
    """Make each relative folder setting absolute, read from the config
    file's own folder rather than from wherever the run was started, so
    "output_dir": "." means the same folder from the app folder, the repo
    root or the control panel. Done once, before anything checks or uses
    a folder, so the server's checks, Paths, the documents-folder keys and
    the browser profile all see the one path. abspath, not resolve: a
    folder reached through a link keeps the name it was given, as an
    absolute setting always has. documents_dir is left as written, since
    set_documents_dir refuses one that is not absolute (#102)."""
    if not isinstance(cfg, dict):
        return
    base = Path(path).absolute().parent
    for key in _ANCHORED_SETTINGS:
        value = cfg.get(key)
        # A Windows path (C:\\... or \\\\server\\...) is absolute wherever the
        # config is read, so it is never joined onto this folder.
        if (isinstance(value, str) and value.strip()
                and not os.path.isabs(value) and not ntpath.isabs(value)):
            cfg[key] = os.path.abspath(os.path.join(base, value))


def _not_on_one_line(cfg, path) -> str:
    """What in a config, or in the path it was read from, cannot be shown on
    one line of a run's output, said with each such character escaped, or ""
    when every name in it can.

    Linux and macOS take a line break in a file or folder name, and a JSON
    setting can hold one, so a config named config.<line break>... or a
    folder holding one would print a line of the run's output that the run
    never wrote. Every app reads its config here before it prints a path,
    and every path it prints is built from these and from names it made
    itself (sanitize_component takes control characters out of those), so
    they are refused here once, rather than escaped at every print."""
    where = Path(path).absolute()
    if not on_one_line(where):
        return "The config file's path, %s, %s" % (one_line(where), _held(where))
    if not isinstance(cfg, dict):
        return ""
    name = one_line(where.name)
    for key in _NAMED_SETTINGS:
        value = cfg.get(key)
        if isinstance(value, str) and not on_one_line(value):
            return "%s in %s, %s, %s" % (key, name, one_line(value), _held(value))
    labels = cfg.get("account_labels")
    if isinstance(labels, dict):
        for key, value in labels.items():
            if not (on_one_line(key) and (not isinstance(value, str) or on_one_line(value))):
                said = "%s: %s" % (key, value)
                return "account_labels in %s %s, in %s" % (name, _held(said), one_line(said))
    return ""


def _held(text) -> str:
    """What keeps text off one line, for _not_on_one_line to say. A name on
    Linux that is not UTF-8 is read with half of a character for each byte
    UTF-8 does not take, and a run can neither print such a name under the
    control panel, which runs it with PYTHONIOENCODING=utf-8, nor keep it
    in its records, where progress.json and the index CSV make each half
    whole as U+FFFD and so name a file that is not there. So it is refused
    too, and said for what it is."""
    text = str(text)
    if on_one_line("".join(c for c in text if not 0xD800 <= ord(c) <= 0xDFFF)):
        return ("holds a name that is not UTF-8 text, which a run can neither print nor keep "
                "in its records")
    return "holds a line break or another control character"


def _in_a_kept_folder(docs: str, out: str) -> bool:
    """Whether a folder is inside the output folder's Manual Review, Logs,
    Diagnostics or Backups, or a hidden folder of it, a browser's download
    folder among them."""
    try:
        parts = Path(os.path.realpath(docs)).relative_to(os.path.realpath(out)).parts
    except ValueError:
        return False
    kept = {f.name.lower() for f in INFRASTRUCTURE_FOLDERS}
    return bool(parts) and (parts[0].lower() in kept or parts[0].startswith("."))


def set_documents_dir(cfg: dict, path) -> str:
    """Take the documents folder a config names, for the Paths built from
    its output_dir, and return it, "" for the output folder itself (#102).

    It has to be an absolute path, a folder of its own. One that is not
    text or not absolute, that is a browser profile, is inside one or holds
    one, or that holds the output folder, is reported once and documents
    stay in the output folder as they always did, since a typo in a setting must never send documents
    somewhere nobody meant, and must never be the reason a run stops. On
    PaperPull Server hold_to_the_server has already held it inside the data
    folder. The config in memory is given the folder as it is used."""
    raw = cfg.get("documents_dir")
    if raw is None or raw == "":
        _DOCUMENTS[_folder_key(cfg["output_dir"])] = ""
        return ""
    name = Path(path).name if path else "config.json"
    why = ""
    if not isinstance(raw, str) or not raw.strip():
        why = "it is not a folder's path"
    elif not Path(raw.strip()).is_absolute():
        why = "it is not a full path, starting with a drive or a /"
    else:
        docs = os.path.normpath(raw.strip())
        profile = str(cfg.get("profile_dir") or "")
        out = str(cfg["output_dir"])
        if profile and (_inside(docs, profile) or _inside(profile, docs)):
            why = ("it is the browser profile, inside it or around it, and documents are "
                   "never kept with a signed-in profile")
        elif _inside(out, docs) and not _inside(docs, out):
            why = ("it holds the output folder, whose records and Manual Review would then "
                   "sit in it")
        elif _in_a_kept_folder(docs, out):
            why = ("it is inside the output folder's Manual Review, Logs, Diagnostics, "
                   "Backups or a hidden folder, which hold no document that passed its check")
    if why:
        print("The documents folder in %s is not used, since %s, so documents go to the "
              "output folder as before." % (name, why), flush=True)
        docs = ""
    cfg["documents_dir"] = docs
    _DOCUMENTS[_folder_key(cfg["output_dir"])] = docs
    return docs


# -- PaperPull Server ----------------------------------------------------------
#
# On PaperPull Server an install's config.json lives in /data, often a shared
# folder that other people on the network can write to. Some of its
# settings decide where a run reaches outside the install. profile_dir is
# where a signed-in browser profile is kept, cdp_url is the browser a run
# drives, output_dir is where documents and records are written, and a
# provider's url_settings (UKG's base_url) are the site its signed-in
# browser is sent to. So on the server none of them is taken from the file
# on trust. output_dir is judged where the run starts, and links made
# inside that folder later are not. The desktop reads them all exactly as
# it always has.

# A cdp_url the server connects to, matched whole. A URL parser and a
# browser can read one text as two different hosts, a backslash or an @ in
# it for instance, so nothing past a scheme, a loopback name, a port and a
# plain path is taken.
_LOOPBACK_CDP = re.compile(
    r"(?:https?|wss?)://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]*)?",
    re.IGNORECASE | re.ASCII)


def _provider_address(domains) -> "re.Pattern":
    """An address a url_setting may hold on the server, matched whole. It
    is https, a name of plain labels under one of the domains, and at most
    a slash after it. No port, user, path, query or fragment, since each
    is a way for a URL parser and a browser to read one text as two
    places, and an address with a path breaks the pages an app builds
    from it anyway."""
    return re.compile(
        r"https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:%s)/?"
        % "|".join(re.escape(d) for d in domains),
        re.IGNORECASE | re.ASCII)


def hold_to_the_server(cfg: dict, path: Path) -> None:
    """Hold a config read on PaperPull Server to the server's own places,
    from what the file itself says, before any default is filled in. The
    profile is always the one the panel gives the account, a cdp_url has
    to name a browser inside the container, output_dir has to lead inside
    the data folder, and each of the bound AppSpec's url_settings has to be
    an https address under one of the provider's own domains. SystemExit,
    before anything is opened or written, for any that does not."""
    name = Path(path).name
    profile = server_profile_dir(path)
    given = cfg.get("profile_dir")
    if given is not None and not (isinstance(given, str)
                                  and os.path.normpath(given) == os.path.normpath(profile)):
        print("%s names \"%s\" as profile_dir, but on PaperPull Server an account's "
              "signed-in browser profile is always kept on the profiles volume, "
              "so %s is used." % (name, given, profile), flush=True)
    cfg["profile_dir"] = profile

    cdp = cfg.get("cdp_url")
    if cdp and not (isinstance(cdp, str) and _LOOPBACK_CDP.fullmatch(cdp)):
        raise SystemExit(
            "%s names \"%s\" as cdp_url. PaperPull Server drives only a browser inside its "
            "own container, at 127.0.0.1 or localhost, so this run stopped before "
            "connecting to anything. Someone who can write to the shared folder may have "
            "changed it. Set it back to http://127.0.0.1 and the port in this provider's "
            "config.example.json." % (name, cdp))

    # The address is not repeated in the sentence, since a provider's own
    # address can name the person's employer.
    for key, domains in getattr(_SPEC, "url_settings", {}).items():
        address = cfg.get(key)
        if address is None or address == "":
            continue
        if not (isinstance(address, str) and _provider_address(domains).fullmatch(address)):
            raise SystemExit(
                "%s holds a %s that is not an https address on %s with nothing after the name, "
                "such as https://yourname.%s. On PaperPull Server a provider's address has to "
                "be on its own site, so this run stopped before opening any page. Someone who "
                "can write to the shared folder may have changed it. Open %s and set %s back "
                "to the address you sign in at."
                % (name, key, " or ".join(domains), domains[0], name, key))

    out = cfg.get("output_dir")
    if out is None:
        raise SystemExit("%s names no output_dir, and on PaperPull Server a run saves only "
                         "inside the data folder, so this run stopped before saving "
                         "anything. Set output_dir to \".\" for this provider's own folder."
                         % name)
    if not isinstance(out, str):
        raise SystemExit("output_dir in %s is not text, so this run stopped before "
                         "saving anything." % name)
    data = os.path.realpath(os.environ.get("APPS_ROOT") or "/data")
    where = os.path.realpath(out)
    if not _in_data(where, data):
        raise SystemExit(
            "%s sends this run's documents to %s, which is outside %s, the data folder, "
            "once its links are followed. On PaperPull Server a run's folder has to be "
            "inside it, so this run stopped before saving anything. Set output_dir to a "
            "folder inside %s, such as \".\" for this provider's own folder."
            % (name, where, data, data))

    # The documents folder (#102) is held the same way, never anywhere a
    # config in the shared folder says.
    docs = cfg.get("documents_dir")
    if isinstance(docs, str):
        # Judged as the run will use it (set_documents_dir).
        docs = cfg["documents_dir"] = docs.strip()
    if docs is None or docs == "":
        return
    if not (isinstance(docs, str) and Path(docs).is_absolute()):
        raise SystemExit("documents_dir in %s is not a full path, so this run stopped before "
                         "saving anything. Set it to a folder inside %s, or take it out."
                         % (name, data))
    where = os.path.realpath(docs)
    if not _in_data(where, data):
        raise SystemExit(
            "%s sends this run's documents to %s, which is outside %s, the data folder, "
            "once its links are followed. On PaperPull Server documents are kept only "
            "inside it, so this run stopped before saving anything. Set documents_dir to a "
            "folder inside %s, or take it out." % (name, where, data, data))


def _in_data(where: str, data: str) -> bool:
    """Whether a folder, its links already followed, is the data folder or
    inside it."""
    try:
        return os.path.commonpath([os.path.normcase(where), os.path.normcase(data)]) \
            == os.path.normcase(data)
    except ValueError:
        return False


def server_profile_dir(config_path) -> str:
    """The signed-in browser profile of the account a config is for, on the
    profiles volume, named exactly as the panel names it (profile_for in
    gui/server_mode.py). That is the install's folder name for config.json,
    and "<install> - <account>" for config.<account>.json."""
    path = Path(os.path.abspath(config_path))
    install, name = path.parent.name, path.name
    if name == "config.json":
        folder = install
    elif name.startswith("config.") and name.endswith(".json") and len(name) > len("config..json"):
        folder = "%s - %s" % (install, name[len("config."):-len(".json")])
    else:
        raise SystemExit(
            "On PaperPull Server an account's settings are read only from config.json or "
            "config.<account>.json in its provider's folder, and %s is neither, so this "
            "run stopped." % name)
    return str(Path(os.environ.get("PAPERPULL_PROFILES") or "/profiles") / folder)


def refuse_links_out(output_dir: str, path: Path) -> None:
    """On PaperPull Server, stop a run before it writes anything when the
    folder its documents go to holds a link, file or folder, that leads
    outside the data folder. Logs, Diagnostics, Backups, Manual Review, a
    year folder or a browser's download folder left as such a link would
    have every write into it land outside, the container's settings and
    browser profiles among the places it could reach. A folder that is a
    link staying in the data folder is looked through as well, and only
    the folders the app files into are walked below the first level, so a
    virtual environment's link to the system's Python stops nothing."""
    found = shared_folder.first_link_out(output_dir, [f.name for f in spec().folders])
    if found is None:
        return
    raise SystemExit(
        "%s sends this run's documents to %s, and %s, on the way to where it writes, is a "
        "link that leads to %s, outside %s, the data folder. On PaperPull Server a run writes nothing through a "
        "link out of the data folder, so this run stopped before writing anything. Someone "
        "who can write to the shared folder may have left it there. Remove the link, and "
        "run again."
        % (Path(path).name, os.path.realpath(output_dir), found, os.path.realpath(found),
           shared_folder.data_folder()))


_FILENAME_OWNER = ""

# The file naming pattern this run uses, or "" for the default of its kind.
_FILENAME_PATTERN = ""
_PATTERN_WARNED = set()
# The account holder's name for a pattern that asks for {owner}. Under the
# default the name appears only when owner_in_filename is on, as before,
# and somebody who writes {owner} into a pattern of their own wants it.
_PATTERN_OWNER = ""


def set_filename_patterns(config: dict) -> str:
    """Choose the pattern this app names files with, from its config.

    An app's own filename_pattern wins, then the one for its kind,
    filename_pattern_receipts or filename_pattern_statements, then the
    default, which is exactly how names were built before patterns
    existed. A pattern that cannot be used is reported once and the
    default is used instead, because a typo in a setting must never be
    the reason a download run stops. Returns the pattern chosen."""
    from . import naming
    global _FILENAME_PATTERN, _PATTERN_OWNER
    _PATTERN_OWNER = str((config or {}).get("owner") or "").strip()
    receipts = spec().kind == RECEIPT if _SPEC is not None else False
    chosen = ""
    for key in ("filename_pattern",
                "filename_pattern_receipts" if receipts
                else "filename_pattern_statements"):
        value = (config or {}).get(key)
        if isinstance(value, str) and value.strip():
            chosen = value.strip()
            break
    if chosen:
        problem = naming.check(chosen)
        if problem:
            if chosen not in _PATTERN_WARNED:
                _PATTERN_WARNED.add(chosen)
                print("The file naming pattern in config.json cannot be used, "
                      "so files keep their usual names. %s" % problem)
            chosen = ""
    _FILENAME_PATTERN = chosen
    return chosen


def set_filename_owner(name: str) -> None:
    """Name that build_pdf_filename prepends (only when owner_in_filename is on;
    the app passes '' otherwise)."""
    global _FILENAME_OWNER
    _FILENAME_OWNER = (name or "").strip()


def ensure_owner(config: dict, config_path) -> dict:
    """If the account holder's name isn't set, ask once on an interactive
    console and save it back to the config, so every document this account
    downloads is associated with that person. Skipped when non-interactive."""
    if config.get("owner"):
        return config
    if not sys.stdin or not sys.stdin.isatty():
        return config
    try:
        name = input("Whose account is this? Enter the account holder's name: ").strip()
    except (EOFError, KeyboardInterrupt):
        name = ""
    if not name:
        return config
    config["owner"] = name
    try:
        existing = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
        existing["owner"] = name
        if shared_folder.on_server() and shared_folder.linked(config_path):
            # Read through a link, so writing it back would copy whatever it
            # leads to into the shared folder.
            print("Your name was not saved, since %s is a link in the shared folder."
                  % Path(config_path).name)
            return config
        if shared_folder.on_server():
            # Replaced rather than written in place, so a link left at
            # the config's name in the shared folder is never written through.
            atomic_write_text(Path(config_path), json.dumps(existing, indent=2))
        else:
            Path(config_path).write_text(json.dumps(existing, indent=2), encoding="utf-8")
        print(f"Saved. Documents will be associated with: {name}\n")
    except Exception:
        pass
    return config


class Paths:
    """All well-known output paths, derived from the configured output dir.

    Folders and routing come from the AppSpec, so a provider declares *what*
    it files and where, and never reimplements *how*.

    An account's documents folder (#102), documents_dir in its config, is
    where its documents go once they are saved and checked, a folder
    somebody may have another program watch. A download is written and
    checked in the output folder as it always was, in the folder of its
    kind there, and one that fails its check is put aside in Manual Review
    beside it, on the same drive. Only a document saved and checked is
    moved to the same folder of its kind in the documents folder, by the
    app's own Rename (renaming.run_for), which the control panel runs after
    each download run for what that run saved, and for what was saved
    before when the person asks. So nothing half checked and no record ever
    reaches a watched folder. The documents folder is the one load_config
    read for this output folder (documents_dir_for), so every app gets it
    from the Paths it has always built, or `documents_dir` says it. Every
    path here is what it always was, documents_dir or not.
    """

    def __init__(self, output_dir, app_spec=None, documents_dir=None):
        self._spec = app_spec or spec()
        self.root = Path(output_dir)
        if documents_dir is None:
            documents_dir = documents_dir_for(output_dir)
        self.documents = Path(documents_dir) if documents_dir else self.root
        # Each documents folder this account's documents were moved to.
        self.documents_folders_json = self.root / DOCUMENTS_FOLDERS
        for folder in self._spec.folders:
            setattr(self, folder.attr, self.root / folder.name)
        for csv_spec in self._spec.csv_files:
            name = csv_spec.filename.format(provider=self._spec.provider)
            setattr(self, csv_spec.attr, self.root / name)
        self.progress_json = self.root / "progress.json"
        self.discovery_json = self.root / "discovery.json"
        # Whether the last listing was read to its end (listing.py).
        self.last_listing = self.root / "last-listing.json"
        self.run_summary = self.root / "run-summary.txt"

    def columns_for(self, csv_attr: str):
        for csv_spec in self._spec.csv_files:
            if csv_spec.attr == csv_attr:
                return list(csv_spec.columns)
        raise KeyError(csv_attr)

    def all_dirs(self):
        """Only the folders this provider actually fills.

        Anything else it can route to is created on demand by folder_for, so
        an empty folder never appears for a document type that cannot occur
        here."""
        return [self.root] + [getattr(self, f.attr)
                              for f in self._spec.folders if f.precreate]

    def ensure(self) -> None:
        for d in self.all_dirs():
            shared_folder.hold(d)
            d.mkdir(parents=True, exist_ok=True)
        # verify writability
        if shared_folder.on_server():
            # A name of its own, made new, since a guessable one in the
            # shared folder could be a link left there to write through.
            fd, probe = tempfile.mkstemp(dir=str(self.root), prefix=".write-probe-", suffix=".tmp")
            os.close(fd)
            os.unlink(probe)
            return
        probe = self.root / f".write-probe-{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    @staticmethod
    def _ready(folder: Path) -> Path:
        """Create a routed folder on demand, so ensure() only has to
        pre-create the folders this provider actually fills. On PaperPull
        Server the folder is held inside the data folder first, each time,
        since a link left as it in the shared folder would be followed by
        every write into it."""
        shared_folder.hold(folder)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def folder_for(self, key: str = "", document_type: str = "") -> Path:
        """Route a document to its folder.

        `key` is a purchase type ("Online" / "In-Store") for receipt apps and
        a category ("Statement" / "Tax Document" / ...) for document apps.
        An "Invoice" document_type wins over the key when the provider
        declares an invoices folder, because that is a different KIND of
        document rather than a different place it came from.
        """
        sp = self._spec
        if document_type == "Invoice" and "invoices" in sp.routes:
            return self._ready(getattr(self, sp.routes["invoices"]))
        attr = sp.routes.get(key)
        if attr is None:
            if sp.default_route is None:
                raise KeyError(
                    f"{sp.provider}: nothing routes {key!r}; declare it in "
                    f"AppSpec.routes or set a default_route")
            attr = sp.default_route
        return self._ready(getattr(self, attr))

    def filing_folders(self) -> List[Path]:
        """Every folder a document is filed in, every folder the app
        declares but Logs, Diagnostics and Backups, which hold a run's own
        records. That is the ones routing reaches, the ones an app files in
        by name, as Anthem does its ID cards and letters, and Manual Review,
        where a file that failed its check is put aside.

        The folders of each kind in the account's documents folder, and in
        every documents folder its documents were moved to before
        (documents_roots), are filing folders too (#102), so Rename, Review
        Names and every check of a file the app holds find a document
        wherever it was moved, and after the setting changes or is cleared
        as well. With no documents folder ever used, this is what it always
        was."""
        held = [getattr(self, folder.attr) for folder in self._spec.folders
                if folder.attr not in _RECORD_FOLDERS]
        seen = {_folder_key(f) for f in held}
        for root in [self.documents] + self.documents_roots():
            for folder in self._routed():
                path = Path(root) / folder.name
                if _folder_key(path) not in seen:
                    seen.add(_folder_key(path))
                    held.append(path)
        return held

    def _routed(self):
        """The folders a document is routed to, every folder but those kept
        beside the records."""
        return [f for f in self._spec.folders if f.attr not in _KEPT_WITH_RECORDS]

    def documents_roots(self) -> List[Path]:
        """Each documents folder this account's documents were moved to, as
        the Move wrote them down in documents-folders.json, a full path
        each. On PaperPull Server, where anybody on the share can edit the
        file, only one inside the data folder holding no link out of it, in
        it or in a folder of a kind in it (shared_folder.first_link_out),
        as the documents folder itself is held when a run starts."""
        try:
            with shared_folder.open_to_read(self.documents_folders_json, "r",
                                            encoding="utf-8") as f:
                listed = json.loads(f.read())
        except (OSError, ValueError, SystemExit):
            return []
        roots = []
        for item in listed if isinstance(listed, list) else ():
            if not (isinstance(item, str) and Path(item).is_absolute()):
                continue
            if shared_folder.on_server() and (
                    not _in_data(os.path.realpath(item), shared_folder.data_folder())
                    or shared_folder.first_link_out(item, [f.name for f in self._routed()])):
                continue
            roots.append(Path(item))
        return roots

    def documents_moves(self) -> Dict[Path, Path]:
        """Each folder of a kind a document may be in that is not where it
        belongs now, with the folder it belongs in, the same folder of its
        kind in the documents folder. That is the folders in the output
        folder and in each documents folder used before. With no documents
        folder set, it is each documents folder used before and the output
        folder, so a Move brings documents back. Empty when every document
        is where it belongs."""
        here = self.documents
        moves = {}
        for root in [self.root] + self.documents_roots():
            if _folder_key(root) == _folder_key(here):
                continue
            for folder in self._routed():
                moves[Path(root) / folder.name] = here / folder.name
        return moves

    def remember_documents(self) -> None:
        """Write down the documents folder in documents-folders.json, once
        documents are moved into it, so they are still found after the
        setting changes or is cleared."""
        if _folder_key(self.documents) == _folder_key(self.root):
            return
        known = [str(p) for p in self.documents_roots()]
        if any(_folder_key(p) == _folder_key(self.documents) for p in known):
            return
        atomic_write_text(self.documents_folders_json,
                          json.dumps(known + [str(self.documents)], indent=1))


# ---------------------------------------------------------------------------
# Windows-safe filenames
# ---------------------------------------------------------------------------

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component(name: str, max_len: int = 120) -> str:
    """Make a single filename component safe for Windows.

    Removes forbidden characters, control characters, trailing spaces and
    periods, guards against reserved device names and empty names.
    Apostrophes (e.g. Children's Clothing) are preserved. Half of a
    character is made whole first (characters.py), as the index writes it,
    since a Mac refuses a file name holding one.
    """
    name = _INVALID_CHARS.sub("", whole_characters(name or ""))
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" .")
    if not name:
        name = "Unnamed"
    stem = name.split(".")[0].strip().upper()
    if stem in _RESERVED:
        name = f"{name} File"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
        if not name:
            name = "Unnamed"
    return name


# ---------------------------------------------------------------------------
# Folders from a naming pattern (#101)
# ---------------------------------------------------------------------------

# The longest a folder a pattern names may be. A file's own name keeps the
# room it needs under the path limit, three folders deep included.
FOLDER_MAX = 60


class FileName(str):
    """A document's file name, and the folders a naming pattern files it in
    (#101).

    It is the name itself, so a caller that compares it with a saved file's
    name, prints it or writes it into a record reads the name alone, as it
    always did. `folder` is the folders the pattern names, one inside the
    other with a / between them, and "" for none. unique_path and
    fitted_name file the name there, inside the folder they are handed,
    which is the folder the document is routed to. Any change a caller
    makes to the name, a cut or an ending, gives plain text with no folder,
    and such a file is filed in the folder it was routed to, where every
    file went before a pattern could name folders."""

    folder = ""

    def __new__(cls, name: str, folder: str = ""):
        self = super().__new__(cls, name)
        self.folder = folder
        return self


def folder_of(filename) -> str:
    """The folders a name is filed in, as FileName.folder gives them, and ""
    for a name that is plain text."""
    return filename.folder if isinstance(filename, FileName) else ""


def _folder_name(text: str) -> str:
    """One folder a pattern names, made safe as a file name is, or "" when
    nothing is left of it, which leaves that folder out. Dots and spaces
    come off both ends, so ".." is nothing and a masked account such as
    "...1234" is not a hidden folder on a Mac."""
    cleaned = re.sub(r"\s+", " ", _INVALID_CHARS.sub("", text or "")).strip(" .")
    if not cleaned:
        return ""
    return sanitize_component(cleaned, max_len=FOLDER_MAX).strip(" .")


def file_name_of(parts: List[str]) -> FileName:
    """A file's name and folders from the text naming.render_path gives,
    the folders first and the name last, each made safe. A folder that
    comes to nothing is left out, so a document a folder's fields say
    nothing about is filed one folder up."""
    *folders, name = parts or [""]
    kept = [f for f in (_folder_name(text) for text in folders) if f]
    return FileName(sanitize_component(name) + ".pdf", "/".join(kept))


def _put_aside_in(directory: Path) -> bool:
    """Whether *directory* is Manual Review, where a document that failed its
    check is put aside, which stays one folder whatever a pattern names, so
    everything set aside is found in one place. Known by the name the bound
    app gives it, which is Manual Review in every app."""
    name = "Manual Review"
    if _SPEC is not None:
        try:
            name = _SPEC.folder("manual_review").name
        except KeyError:
            pass
    return Path(directory).name == name


def _inside(path, folder) -> bool:
    """Whether path is folder or inside it once the links on the way to
    each are followed."""
    try:
        real = os.path.normcase(os.path.realpath(path))
        home = os.path.normcase(os.path.realpath(folder))
        return os.path.commonpath([real, home]) == home
    except (OSError, ValueError):
        return False


def filing_folder(directory: Path, filename, max_path_length: int = 240) -> Path:
    """The folder *filename* is filed in, inside *directory*, the folder its
    document is routed to.

    That is *directory* itself for a name with no folder, for Manual
    Review, which stays one folder (_put_aside_in), for a name whose
    folders would leave no room for a name under max_path_length, for one
    where a file has the name of one of its folders, and for one whose
    folders lead outside *directory* once the links on the way are
    followed, a folder somebody made a link to another drive, say. A
    pattern never puts a file outside the folder it was routed to, and a
    folder it names never keeps a file from being saved. A download and
    Rename both ask here, so they agree where a file belongs."""
    directory = Path(directory)
    folder = folder_of(filename)
    if not folder or _put_aside_in(directory):
        return directory
    parts = folder.split("/")
    # Each is made safe already, which is asked again here, since a name is
    # text anybody can build, and one part that is not stays out of a path.
    if any(not part or _folder_name(part) != part for part in parts):
        return directory
    target = directory.joinpath(*parts)
    ext = os.path.splitext(filename)[1] or ".pdf"
    if max_path_length - len(str(target)) - 1 < len(ext) + 8:
        return directory
    at = directory
    for part in parts:
        at = at / part
        if os.path.lexists(at) and not at.is_dir():
            return directory
    if not _inside(target, directory):
        return directory
    return target


def _make_folder(folder: Path) -> bool:
    """Make a folder a pattern names, held inside the data folder first on
    PaperPull Server as every routed folder is (Paths._ready). False when it
    cannot be made, a file of its name being in the way, say."""
    shared_folder.hold(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return folder.is_dir()


def _one_folder(a, b) -> bool:
    if Path(a) == Path(b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def build_pdf_filename(purchase_date: str, summary: str,
                       document_type: str = "Receipt",
                       part: Optional[tuple] = None, owner=None,
                       record=None, pattern: Optional[str] = None) -> "FileName":
    """A document's file name, from the naming pattern (#50).

    With no pattern set, the default for the app's kind, which is exactly
    YYYY-MM-DD [Owner ]<Provider> <Summary> <Receipt|Invoice>[ (i of n)].pdf
    as it always was. `record` is the app's own record, which is where a
    pattern finds fields beyond the date, the summary and the kind, such as
    an order number or an account. `pattern` is for a preview, and a run
    leaves it out and uses the one its config chose.

    The name comes back as a FileName, which is the name and carries the
    folders a pattern with a / names (#101). Handed on unchanged to
    unique_path, the file is filed in them."""
    from . import naming
    date = (purchase_date or "0000-00-00").strip()
    summary = title_case(summary or "Purchase")
    who_name = _FILENAME_OWNER if owner is None else owner
    receipts = spec().kind == RECEIPT
    chosen = pattern or _FILENAME_PATTERN or (
        naming.DEFAULT_RECEIPTS if receipts else naming.DEFAULT_STATEMENTS)
    fields = naming.fields_of(record, date=date, summary=summary,
                              kind=document_type, provider=spec().provider,
                              owner=(who_name or "").strip(), part=part,
                              receipts=receipts)
    if (chosen not in (naming.DEFAULT_RECEIPTS, naming.DEFAULT_STATEMENTS)
            and owner is None and not fields["owner"]):
        fields["owner"] = _PATTERN_OWNER
    if chosen in (naming.DEFAULT_RECEIPTS, naming.DEFAULT_STATEMENTS):
        # The default says exactly what the call said, and nothing the
        # record adds. A statements app passes no kind, and filling it
        # from the record's category would rename every statement.
        fields["kind"] = document_type or ""
    try:
        parts = naming.render_path(chosen, fields)
    except naming.PatternError:
        parts = [naming.render(naming.DEFAULT_RECEIPTS if receipts
                               else naming.DEFAULT_STATEMENTS, fields)]
    return file_name_of(parts)


_SMALL_WORDS = {"and", "of", "the", "a", "an", "or", "for", "in", "on", "to"}


def title_case(text: str) -> str:
    """Title-case a summary, keeping small words lowercase (except first/last)
    and preserving apostrophe forms like Children's."""
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if 0 < i < len(words) - 1 and lw in _SMALL_WORDS:
            out.append(lw)
        elif "'" in w:
            # Children's -> Children's (capitalize first letter only)
            out.append(w[0].upper() + w[1:])
        elif len(w) > 1 and w[0].islower() and w[1].isupper():
            # A name spelled with a small first letter and a capital second,
            # iCloud, iPhone, iPad, eBay. Capitalizing it made "ICloud+" and
            # "IPhone" in the Apple app's file names.
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def unique_path(directory: Path, filename: str, max_path_length: int = 240,
                distinguisher: str = "", ignoring="",
                held: Iterable[str] = (), make: bool = True) -> Path:
    """Return a path in *directory* that does not collide with any existing
    file, case-insensitively. Never returns a path to an existing file.

    *directory* is the folder the document is routed to. A name carrying
    the folders a naming pattern names (FileName) is filed in them, inside
    *directory* (filing_folder), its collisions are looked for there, the
    folders count toward max_path_length, and they are made unless `make`
    is False, as Rename's preview asks. A folder that cannot be made leaves
    the file in *directory*.

    Two purchases on one day are one name, because a date and a summary are
    all most rows give. The old answer was ' (2)', which says nothing about
    which purchase it is and is not even stable, since it depends on what
    is in the folder at the moment it is written. Delete the first file and
    the next run gives that name to a different receipt.

    So when the caller knows something that tells the two apart, an order
    number or a payment id, that goes in the name instead and ' (2)' stays
    as the last resort. Nothing changes for a name that does not collide
    (#49, and the same complaint on #43).

    `held` are names taken although no file has them yet. Rename passes the
    names its plan has given other files, so a file wanting one is named
    as a download into a folder already holding that file would name it.

    `ignoring` is the file being renamed, as a path, which does not stand
    in its own way in the folder it is in. Given as a name alone it is a
    name in *directory*, and it counts only when the file is filed there,
    since a file of that name in a folder a pattern names is another file."""
    base = Path(directory)
    directory = filing_folder(base, filename, max_path_length)
    if make and directory != base and not _make_folder(directory):
        directory = base
    existing = {p.name.lower() for p in directory.iterdir()} if directory.exists() else set()
    # A file being renamed does not stand in its own way. Rename asks where a
    # file belongs while it is still there, and without this a file already
    # told apart by its order number was pushed on to " (2)".
    if isinstance(ignoring, PurePath):
        own = ignoring.name if _one_folder(ignoring.parent, directory) else ""
    else:
        own = ignoring if directory == base else ""
    existing.discard((own or "").lower())
    existing.update(name.lower() for name in held)
    return directory / _free_name(directory, filename, max_path_length, existing,
                                  distinguisher)


def refile(path: Path, directory: Path, filename, max_path_length: int = 240,
           distinguisher: str = "") -> Path:
    """Move a file a run has just saved to the name `filename` gives it, in
    *directory*, the folder its document is routed to, and in the folders
    the name carries there (FileName), and return where it is.

    For an app that learns a better name once a file is saved, from what
    the PDF says. It was done by asking unique_path for a name in the
    file's own folder, which is one of a pattern's folders when the
    pattern names some, so the name's folders would have been made inside
    them again. The file does not stand in its own way, a name already its
    own leaves it where it is, and it is never moved over another file. A
    folder of a pattern's it leaves empty is taken away, and so is one
    made for it when the move is refused, whose OSError is raised."""
    path = Path(path)
    target = unique_path(directory, filename, max_path_length,
                         distinguisher=distinguisher, ignoring=path)
    if target.name == path.name and _one_folder(target.parent, path.parent):
        return path
    try:
        # unique_path gives no name a file has, and one that came since, or
        # another file of a name differing only in case where a folder tells
        # case apart, is not replaced. The file itself under a change of
        # case is.
        if os.path.lexists(target) and not _one_folder(target, path):
            raise FileExistsError(17, "a file has that name", str(target))
        path.replace(target)
    except OSError:
        remove_empty(target.parent, [directory])
        raise
    remove_empty(path.parent, [directory])
    return target


def remove_empty(folder: Path, homes) -> None:
    """Take away `folder` when it holds nothing, and each folder above it
    left holding nothing, while each is inside one of `homes`, the folders
    a document is routed to, and is not one of them. A link is never taken
    away, and a folder holding anything never is, since the call that
    takes one away refuses a folder that is not empty."""
    real = []
    for home in homes:
        try:
            real.append(Path(home).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    folder = Path(folder)
    while True:
        try:
            where = folder.resolve()
        except (OSError, RuntimeError, ValueError):
            return
        inside = where not in real and not set(where.parents).isdisjoint(real)
        if not inside or shared_folder.linked(folder):
            return
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = folder.parent


def fitted_name(directory: Path, filename: str, max_path_length: int = 240) -> str:
    """*filename* as unique_path names it in *directory* when nothing there
    holds it, cut to fit max_path_length in the folder it is filed in
    (filing_folder). A download into a deep folder cuts a name so, and
    Rename has to know the name it cut to tell a file named right from one
    to rename. Raises ValueError, as unique_path does, for a folder too
    deep to file into."""
    where = filing_folder(Path(directory), filename, max_path_length)
    return _free_name(where, filename, max_path_length, set(), "")


def _free_name(directory: Path, filename: str, max_path_length: int,
               existing: set, distinguisher: str) -> str:
    """The name unique_path gives *filename* in *directory*, where `existing`
    is every name held there, in lower case."""
    stem, ext = os.path.splitext(filename)

    # An empty stem used to return the DIRECTORY itself, because "dir / ''" is
    # just "dir". The caller then tried to write a PDF over its own folder. It
    # is reachable whenever a scraped title sanitizes away to nothing.
    if not stem.strip(" ."):
        stem = "document"
        if not ext:
            ext = ".pdf"

    # The room a name has is what is left after the folder and the separator.
    # A folder deep enough to leave nothing is not something a shorter filename
    # can rescue, and returning an over-long path anyway only moved the failure
    # to the write, where it surfaced as an unexplained OS error.
    room = max_path_length - len(str(directory)) - 1
    if room < len(ext) + 8:
        raise ValueError(
            "%s is too deep to file into. The full path would exceed the %d "
            "character limit before a filename is added. Move the output "
            "folder somewhere shorter, or raise max_path_length in config.json."
            % (directory, max_path_length))

    def shorten(base: str, suffix: str) -> str:
        keep = room - len(ext) - len(suffix)
        return base[:max(1, keep)].rstrip(" .") + suffix + ext

    candidate = stem + ext
    if len(candidate) > room:
        candidate = shorten(stem, "")

    # What tells this one from the other, when the caller knows. It is
    # sanitized like any other part of a name, and it is not used when the
    # stem already carries it, which is how an app that puts the order
    # number in the summary itself avoids saying it twice.
    # sanitize_component turns an empty string into "Unnamed", which as a
    # distinguisher would tell two files apart by telling you nothing.
    raw_token = str(distinguisher or "").strip()
    token = sanitize_component(raw_token).strip(" .") if raw_token else ""
    if candidate.lower() in existing and token and token.lower() not in stem.lower():
        with_token = "%s %s" % (stem, token)
        candidate = with_token + ext
        if len(candidate) > room:
            candidate = shorten(with_token, "")
        if candidate.lower() not in existing:
            return candidate
        stem = with_token

    n = 1
    while candidate.lower() in existing:
        n += 1
        suffix = " (%d)" % n
        candidate = stem + suffix + ext
        if len(candidate) > room:
            candidate = shorten(stem, suffix)
    return candidate


# ---------------------------------------------------------------------------
# Atomic writes and backups
# ---------------------------------------------------------------------------

# How long a write waits for a file another program holds, in tries this
# many seconds apart, and so does a check that the file can be written.
_LOCKED_TRIES = 30
_LOCKED_PAUSE_S = 2

# Each file this run waited for and could not write, after a write gave up
# or free_to_write found it held. The save every app makes on its way out
# tries such a file once and does not wait its minute for it again
# (JsonStore.save).
_HELD = set()

# Each file the save on the way out could not write, which report_run_result
# reads, so a run whose run state was not saved never reads as finished.
_UNSAVED = []


def unsaved_on_leaving() -> list:
    """The files the save on the way out could not write, in this run."""
    return list(_UNSAVED)


def _held_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8", *,
                      tries: Optional[int] = None) -> None:
    """Write *path* whole or not at all, waiting up to a minute while
    another program holds it. With `tries` of 1 it is tried once, with no
    wait and nothing said, and PermissionError says the file was held."""
    path = Path(path)
    tries = _LOCKED_TRIES if tries is None else max(1, tries)
    # The replace below never writes through a link at the name itself,
    # but a folder on the way that is a link would be followed.
    shared_folder.hold(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # Windows: os.replace fails while the target is open in Excel etc.
        # Retry with a message instead of crashing mid-run.
        for attempt in range(tries):
            try:
                os.replace(tmp, path)
                _HELD.discard(_held_key(path))
                break
            except PermissionError:
                if tries > 1:
                    if attempt == 0:
                        print(f"  ! {path.name} is locked (open in Excel?). "
                              f"Close it - retrying for up to 60s...")
                    time.sleep(_LOCKED_PAUSE_S)
        else:
            _HELD.add(_held_key(path))
            raise PermissionError(
                f"{path} stayed locked. Close the program using it and re-run; "
                f"the pending update was not lost (progress is tracked).")
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def free_to_write(path: Path, say=print) -> bool:
    """Whether atomic_write_text could replace *path* now, after waiting the
    same minute it waits while another program holds the file.

    For a command that writes a file only after doing something it cannot
    easily undo, as Rename writes the index after renaming the files, so it
    can stop before it starts rather than halfway.

    Windows will not replace a file that another program holds without
    letting others delete it, which is how Excel holds a CSV it has open.
    It refuses to rename such a file onto itself just the same, and that
    changes nothing a write would not, so that is what is tried here. The
    only change is to a name spelled in other letter case on disk, which
    takes the case given, as it does when the file is written. A program
    that holds a file and lets others delete it, as a virus scanner may for
    a moment, is not seen this way, and the write waits for it as it always
    has. A file not there yet is free, and so is any file on macOS and
    Linux, which replace a file whoever has it open."""
    path = Path(path)
    for attempt in range(_LOCKED_TRIES):
        try:
            os.replace(path, path)
            _HELD.discard(_held_key(path))
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == 0:
                say(f"  ! {path.name} is open in another program, Excel perhaps. "
                    f"Close it, and this waits up to {_LOCKED_TRIES * _LOCKED_PAUSE_S} "
                    f"seconds for it.")
            time.sleep(_LOCKED_PAUSE_S)
        except OSError:
            return False
    _HELD.add(_held_key(path))
    return False


def atomic_write_json(path: Path, data, **how) -> None:
    """`how` is passed on to atomic_write_text only when given, so a test's
    stand-in for it that takes no `tries` serves every other save as before.
    Half of a character is written as its escape (characters.json_escaped),
    so the file is always written and reads back as it was written."""
    atomic_write_text(Path(path), json_text(data), **how)


def json_text(data, indent=2) -> str:
    """data as the JSON text atomic_write_json writes, which UTF-8 can always
    hold. For a JSON file written another way, Export history's say."""
    return json_escaped(json.dumps(data, indent=indent, ensure_ascii=False))


def backup_file(path: Path, backups_dir: Path) -> Optional[Path]:
    """Copy *path* into Backups with a timestamp. No-op if it doesn't exist."""
    path = Path(path)
    if not path.exists():
        return None
    backups_dir = Path(backups_dir)
    shared_folder.hold(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{path.stem}.{stamp}{path.suffix}.bak"
    server = shared_folder.on_server()
    # On the server a link left at the name counts as taken, so the copy is
    # never written through one, and the copy is made by a write that
    # refuses a link it finds there all the same.
    taken = os.path.lexists if server else os.path.exists
    n = 1
    while taken(dest):
        n += 1
        dest = backups_dir / f"{path.stem}.{stamp}-{n}{path.suffix}.bak"
    if server:
        # Read the way it is written, so a file swapped for a link while the
        # run goes on is never copied into the share from where it leads.
        with shared_folder.open_to_read(path, "rb") as src, \
                shared_folder.open_to_write(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        shutil.copystat(path, dest, follow_symlinks=False)
        return dest
    shutil.copy2(path, dest)
    return dest


# ---------------------------------------------------------------------------
# CSV files (UTF-8 with BOM for Excel)
# ---------------------------------------------------------------------------

class CsvFile:
    """An app's order history, receipt index or document index. They hold
    names other people chose and open in Excel on a double click, so every
    value goes in through sheets.store_value, which puts a quote in front
    of text a spreadsheet would take for a formula, and comes out through
    sheets.read_stored, which takes that quote off again. Whatever reads
    one of these files reads it here, or through read_stored_row as both
    spreadsheet tools do."""

    def __init__(self, path: Path, columns: List[str], backups_dir: Optional[Path] = None,
                 once: bool = False):
        self.path = Path(path)
        self.columns = columns
        self.backups_dir = backups_dir
        # A file that holds each row once. A document app's index gets a row
        # for each outcome, and an outcome that is tried again on the next
        # run, a capture that saved nothing, is written again on every run
        # it fails. Ally's index held seven rows, word for word alike, for one
        # tax form its page could not open (#152). A row of a saved file
        # carries the moment it was saved, so a second save is always a row
        # of its own. An order history holds one row per item bought, and two
        # alike items are two rows, so it never holds its rows once.
        self.once = once

    def _ensure_header(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            with shared_folder.open_to_write(self.path, "w", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=self.columns, quoting=csv.QUOTE_MINIMAL).writeheader()

    def _held(self) -> Optional[set]:
        """Every row the file holds, as read_stored gives it back, by this
        file's columns, or None when the file cannot be read as this app
        writes it. A file a person saved again from Excel in the code page
        of their Windows, with a name such as José in it, is not UTF-8, and
        a file with a field past the csv module's limit is not one it reads.
        Appending never read the file before, so such a file is appended to
        as it always was, rather than every row of a run failing to be
        written, with the files that run saved counted as failed."""
        if not self.path.exists():
            return set()
        try:
            with shared_folder.open_to_read(self.path, "r", encoding="utf-8-sig", newline="") as f:
                return {tuple(r.get(c) or "" for c in self.columns)
                        for r in (read_stored_row(row) for row in csv.DictReader(f))}
        except (OSError, UnicodeError, csv.Error):
            return None

    def append_rows(self, rows: Iterable[dict]) -> None:
        self._ensure_header()
        held = self._held() if self.once else None
        with shared_folder.open_to_write(self.path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore",
                               quoting=csv.QUOTE_MINIMAL)
            for row in rows:
                stored = {c: store_value(row.get(c, "")) for c in self.columns}
                if held is not None:
                    # As read_stored gives it back from the file, the way
                    # _held reads the rows already there.
                    written = tuple(read_stored(v) or "" for v in stored.values())
                    if written in held:
                        continue
                    held.add(written)
                w.writerow(stored)

    def read_all(self) -> List[dict]:
        if not self.path.exists():
            return []
        with shared_folder.open_to_read(self.path, "r", encoding="utf-8-sig", newline="") as f:
            return [read_stored_row(r) for r in csv.DictReader(f)]

    def rewrite(self, rows: List[dict], backup: bool = True) -> None:
        """Backup then atomically rewrite the whole file. A command that
        writes the same file again and again backs it up the first time."""
        if backup and self.backups_dir is not None:
            backup_file(self.path, self.backups_dir)
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=self.columns, extrasaction="ignore",
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows:
            w.writerow({c: store_value(row.get(c, "")) for c in self.columns})
        # utf-8-sig: prepend BOM manually since we write text atomically
        atomic_write_text(self.path, "﻿" + buf.getvalue())


# ---------------------------------------------------------------------------
# Progress / discovery stores
# ---------------------------------------------------------------------------

def _whole_key(key):
    return whole_characters(key) if isinstance(key, str) else key


def _whole_records(raw: dict) -> dict:
    """A store's records as its file holds them, with their text whole. Two
    keys that come out the same, one written with a half and one with
    U+FFFD in its place, say, are one record then, which keeps the fields
    of both, a later key's over an earlier one's, so nothing either held is
    lost."""
    made = whole_json(raw)
    if made is raw or len(made) == len(raw):
        return made
    out = {}
    for key, rec in raw.items():
        key, rec = _whole_key(key), whole_json(rec)
        if isinstance(out.get(key), dict) and isinstance(rec, dict):
            out[key] = {**out[key], **rec}
        else:
            out[key] = rec
    return out


class JsonStore:
    """A dict-of-records JSON file with atomic writes, backups, and
    corrupt-file recovery.

    It holds text whole, as the CSV files beside it do (characters.py). Half
    of a character in a record or a key is U+FFFD here, read or written, and
    a record is asked for by its key made whole the same way, so a key
    holding a half finds its record, and a CSV row naming it finds the same
    one. Up to now a half stopped the save with UnicodeEncodeError, and
    nothing was written down. Kept exactly instead, as its escape, the
    record and the row beside it disagreed, and Rename, which finds a
    receipt's record by the order number its row holds, left every such
    file as it was.

    So two keys that differ only by a half, or by a half and U+FFFD, are
    one record, as they are one row in a CSV. A name a disk gave Python,
    which Linux gives with a half for each byte it cannot read as UTF-8,
    is kept with U+FFFD there too and names no file, where the save used to
    stop. PaperPull makes no such name, since every name it makes is made
    whole (sanitize_component)."""

    def __init__(self, path: Path, backups_dir: Optional[Path] = None):
        self.path = Path(path)
        self.backups_dir = backups_dir
        self.data: Dict[str, dict] = {}
        self._loaded = False
        # The records as the file holds them, read or last written, or None
        # when that is not known. The save on the way out writes nothing
        # when the records are still these.
        self._as_written: Optional[str] = None

    def _canonical(self) -> str:
        return json.dumps(self.data, sort_keys=True, ensure_ascii=False, default=str)

    def load(self) -> Dict[str, dict]:
        if self.path.exists():
            broken = False
            try:
                with shared_folder.open_to_read(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.data = _whole_records(raw)
                    self._as_written = self._canonical()
                else:
                    # Valid JSON of the wrong shape, a list or a bare null.
                    # This used to fall through and leave data empty, so the
                    # next save replaced the file with {} and the record of
                    # everything ever downloaded went with it. It is as
                    # unusable as a truncated file, so it is treated as one.
                    broken = True
            except (json.JSONDecodeError, OSError):
                broken = True
            if broken:
                # Corrupt file: preserve it for inspection, start fresh,
                # try latest backup.
                if self.backups_dir is not None:
                    backup_file(self.path, self.backups_dir)
                recovered = self._recover_from_backup()
                self.data = recovered if recovered is not None else {}
        self._loaded = True
        return self.data

    def _recover_from_backup(self) -> Optional[Dict[str, dict]]:
        if self.backups_dir is None or not Path(self.backups_dir).exists():
            return None
        candidates = Path(self.backups_dir).glob(f"{self.path.stem}.*.bak")
        if shared_folder.on_server():
            # A backup left as a link is never read on the server, since
            # what it leads to would be saved into the share as the records.
            candidates = [c for c in candidates if not shared_folder.linked(c)]
        candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
        for c in candidates:
            try:
                with open(c, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return _whole_records(raw)
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def save(self, backup: bool = False, leaving: bool = False) -> None:
        """Write the records to the file.

        `leaving` is for the save every app makes on its way out, in the
        finally of its main. When another program holds the file, that save
        says in one line that the file was not written and where, and the
        run ends as it would have. It used to raise out of the finally after
        its minute, so the person saw a traceback in place of how the run
        ended, and the panel never got the run's result, which is written
        after it. A file this run already waited for and could not write, as
        when Rename's check finds progress.json held and stops, is tried once
        more and not waited for again."""
        if backup and self.backups_dir is not None:
            backup_file(self.path, self.backups_dir)
        if not leaving:
            atomic_write_json(self.path, self.data)
            self._as_written = self._canonical()
            return
        # A run that changed nothing, a preview or a Verify, has nothing to
        # write, and a held file then costs it nothing and is not reported.
        now = self._canonical()
        if now == self._as_written:
            return
        try:
            if _held_key(self.path) in _HELD:
                atomic_write_json(self.path, self.data, tries=1)
            else:
                atomic_write_json(self.path, self.data)
            self._as_written = now
        except PermissionError:
            _UNSAVED.append(str(self.path))
            print("  ! %s could not be written, so it keeps what was last saved in it. "
                  "Close any program that has it open before the next run." % self.path,
                  flush=True)

    def get(self, key: str) -> Optional[dict]:
        if not self._loaded:
            self.load()
        made = _whole_key(key)
        found = self.data.get(made)
        if found is None and made is not key:
            # Put into data straight under the key as given, not by update.
            found = self.data.get(key)
        return found

    def update(self, key: str, record: dict, save: bool = True) -> None:
        if not self._loaded:
            self.load()
        made = _whole_key(key)
        existing = self.data.get(made, {})
        if made is not key and key in self.data:
            # A record put into data straight under the key as given, not
            # by update, joins the one held under the key made whole, which
            # keeps its own fields over it, so neither is left to be lost
            # when the file is read whole again.
            put = whole_json(self.data.pop(key))
            if isinstance(put, dict) and isinstance(existing, dict):
                existing = {**put, **existing}
        key = made
        existing.update(whole_json(record))
        existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.data[key] = existing
        if save:
            self.save()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
