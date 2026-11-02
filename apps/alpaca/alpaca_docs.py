"""Alpaca statement and trade confirmation downloader (local, supervised).

Alpaca keeps a Live brokerage account's documents on one page of its
dashboard, app.alpaca.markets/account/documents: monthly account
statements, crypto account statements and trade confirmations, each with
its own Download. This saves those PDFs. The orchestrator below is the
same one every other statement app runs on. Everything about the site
itself is in alpaca_site.py.

Usage:
    python alpaca_docs.py --login       verify connection to your browser
    python alpaca_docs.py --discover    list available documents
    python alpaca_docs.py --pilot       download the newest few, then stop
    python alpaca_docs.py --all         download everything in scope
    python alpaca_docs.py --resume      continue an interrupted run
    python alpaca_docs.py --verify      re-validate every saved PDF
    python alpaca_docs.py --diagnose    dump page structure (no downloads)
    python alpaca_docs.py --record      record the path you take to one document
    python alpaca_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement

READ-ONLY: this tool only reads the Live account's documents page and saves
the PDFs Alpaca already generated. It never trades, transfers, deposits,
withdraws, switches accounts, or changes any setting, and it never runs on
a Paper account. Everything stays on this machine, and nothing is sent to
any external service.
"""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import pressing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import NEW_LIST_NOTE, lists_what_it_saved, report_run_result

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

from paperpull_core import capture
from paperpull_core import doc_types, receipt_pdf
from paperpull_core import browser as browser_launcher
import alpaca_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import PROJECT_DIR, set_filename_owner
log = logging.getLogger("alpaca_docs")


FILENAME_PATTERN_KEYS = ("filename_pattern", "filename_pattern_statements",
                         "filename_pattern_receipts")


def _names_owner(pattern) -> bool:
    """Whether a file naming pattern asks for {owner} anywhere, inside an
    optional part or as one of a field's alternatives. A pattern that does
    not parse names nothing (the core reports it and uses the default)."""
    from paperpull_core import naming
    if not isinstance(pattern, str) or not pattern.strip():
        return False
    try:
        parts = naming.parse(pattern)
    except naming.PatternError:
        return False

    def walk(nodes) -> bool:
        for node in nodes:
            if isinstance(node, naming._Optional) and walk(node.parts):
                return True
            if isinstance(node, naming._Field) and "owner" in node.names:
                return True
        return False
    return walk(parts)


def keep_owner_out_of_names(config: dict) -> List[str]:
    """Name files without the account holder's name. An Alpaca account is
    often held by a company, and its name is private to this app as the
    account number is, so owner_in_filename is ignored and a file naming
    pattern that asks for {owner} is refused, the default used instead.
    Says once which settings were set aside, and returns their names."""
    from paperpull_core.storage import set_filename_patterns
    set_aside = ["owner_in_filename"] if config.get("owner_in_filename") else []
    cleaned = dict(config, owner="")
    for key in FILENAME_PATTERN_KEYS:
        if _names_owner(config.get(key)):
            cleaned[key] = ""
            set_aside.append(key)
    set_filename_patterns(cleaned)
    set_filename_owner("")
    if set_aside:
        log.warning("file names never carry the account holder's name here, "
                    "set aside: %s", ", ".join(set_aside))
        print("Alpaca file names never carry the account holder's name, so these "
              "settings in config.json are not used: %s" % ", ".join(set_aside))
    return set_aside


def check_start_dates(args, config: dict) -> None:
    """Refuse a start date that is not a day that exists. --start-date and
    default_start_date decide which documents are wanted and how far back
    the list must reach (site.reaches_back), so one that cannot be read
    would leave documents out unnoticed. Exits with 2."""
    for said, value in (("--start-date", getattr(args, "start_date", None)),
                        ("--end-date", getattr(args, "end_date", None)),
                        ("default_start_date in config.json", config.get("default_start_date"))):
        if value and site.calendar_date(value) != value:
            print(f"{said} is not a date this can read. Use YYYY-MM-DD, a day that exists.")
            raise SystemExit(2)


def pilot_failed(progress: dict, docs) -> bool:
    """True unless every document the pilot chose is recorded as completed.
    The gate a pilot is: nothing else runs until one document has landed."""
    if not docs:
        return True
    for d in docs:
        rec = progress.get(d.key) if isinstance(progress, dict) else None
        if not isinstance(rec, dict) or rec.get("state") != State.COMPLETED.value:
            return True
    return False


def persistable(url: str) -> str:
    """A URL as it may be written to discovery.json, progress.json or the
    index CSV: scheme, host and path only. A query string can carry a
    signed token or an account id, and a stored one would outlive the
    session it belonged to. Anything that is not an https URL is kept
    as it is when it has no "?" or "#", else cut at the first of them."""
    from urllib.parse import urlsplit, urlunsplit
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parts = urlsplit(u)
    except ValueError:
        return u.split("?", 1)[0].split("#", 1)[0]
    if parts.scheme and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return u.split("?", 1)[0].split("#", 1)[0]


DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


def notice_summary(title: str) -> str:
    """What a document the rules file as Other is called in its file name,
    its own title cut at a word near sixty characters. Only the three kept
    types are listed, so this is a fallback."""
    text = re.sub(r"\s+", " ", title or "").strip().rstrip(".!?")
    if len(text) <= 60:
        return text or "Notice"
    return text[:60].rsplit(" ", 1)[0]


class Document:
    """One Alpaca statement or trade confirmation."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", doc_type="", **kw):
        self.title = title
        # One account is read, the Live one, and nothing about it is written.
        self.account = account
        # What binds the record to one row when it is taken: its type as the
        # list answered it, which is also what its row shows.
        self.doc_type = doc_type
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        # Alpaca's uuid for the document. Private: never logged, said or in
        # a file name.
        self.document_id = document_id
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
        self.notes = kw.get("notes", "")
        self.discovered_at = kw.get("discovered_at", now_iso())

    @property
    def key(self) -> str:
        """Stable identity. The document's uuid, which no other document
        carries. A record without one falls back to category, date and
        title."""
        if self.document_id:
            return f"id:{self.account}:{self.document_id}" if self.account \
                else f"id:{self.document_id}"
        acct = _account_component(sanitize_component(self.account or ""))
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


def migrate_legacy_keys(records: dict) -> int:
    """Move records written while the account was cut to forty characters.

    Only a record whose key is exactly the new one with the last four taken
    off is moved, so nothing is guessed. An archive whose account names were
    short enough to fit has no such records and nothing happens.
    """
    return _migrate_account_keys(records, lambda r: Document.from_dict(r).key)


def told_apart_by(record: dict) -> str:
    """What a statement's file adds to its name when another file already
    has that name, the same on every run and never " (2)"
    (core/tests/test_every_app_renames_each_file_for_its_own_record): six
    letters of a hash of its documentId, never the id itself, which is
    private. A crypto statement and a brokerage statement keep names of
    their own through the rules, so little reaches this. The download and Rename both ask this, so they
    agree."""
    doc_id = str((record or {}).get("document_id") or "").strip()
    return hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:6] if doc_id else ""


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
        check_start_dates(args, self.config)
        keep_owner_out_of_names(self.config)
        self.paths = Paths(Path(self.config["output_dir"]))
        self.paths.ensure()
        self._setup_logging()

        self.progress = JsonStore(self.paths.progress_json, self.paths.backups)
        self.discovery = JsonStore(self.paths.discovery_json, self.paths.backups)
        self.progress.load()
        self.discovery.load()
        for store in (self.progress, self.discovery):
            if migrate_legacy_keys(store.data):
                store.save(backup=True)
        self.index_csv = CsvFile(self.paths.document_index_csv,
                                 DOCUMENT_INDEX_COLUMNS, self.paths.backups)
        self.rules = doc_types.load_rules()
        # The owner's name first. The site adds the account switcher's text,
        # the account's uuid and every document uuid as soon as it reads them.
        site.set_private_words([self.config.get("owner", "")])
        # When the run first opened the documents page, for the deadline,
        # and what the list skipped (site.Run).
        self.run = site.Run()

        self._pw = None
        self._browser = None
        self._context = None
        self._work_page = None
        self._cdp_mode = False
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "discovered": 0, "statements": 0,
            "other": 0, "skipped_completed": 0, "skipped_out_of_scope": 0,
            "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
            "left_for_next_run": 0, "validation_failures": 0, "dates": [], "new_files": [],
            "alike": 0,
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
            # Reuse the person's own tab on Alpaca's site, the page they left
            # open for this. With none open, a tab of this run's own is
            # opened, never a tab of another site (tabs.new_tab), which loads
            # the dashboard in the same signed-in browser. Matched on the parsed
            # host, never a substring, since "provider.com" in an address also
            # matches "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            dom = [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = dom[0] if dom else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # A real Edge or Chrome attached over CDP saves a download itself,
        # into its own Downloads folder, so the browser is pointed at a
        # folder under the output and the site layer takes each document's
        # download from there through the core.
        # One folder of the app's own, kept from run to run and never
        # emptied (site.Run).
        self._dl_dir = Path(self.config["output_dir"]) / ".alpaca-downloads"
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
        # As the tab is let go: a download no capture took, or one that
        # came after its capture stopped waiting, is canceled and what it
        # left discarded, and the run stops listening (site.Run.close).
        try:
            self.run.close()
        except Exception as e:
            log.warning("the run's downloads could not be swept (%s)", type(e).__name__)
        try:
            if self._cdp_mode:
                # Never close the user's own signed-in tab, just detach.
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
        # A tab off Alpaca is never asked anything, read or
        # prompted about: nothing on another site is this run's to resolve.
        try:
            where = page.url or ""
        except Exception:
            where = ""
        # A blank tab this run opened itself is where the site layer opens
        # the documents page, and anything else off app.alpaca.markets stops.
        if not site.is_safe_url(where) and not (tabs.is_own(page) and where in ("", "about:blank")):
            self.progress.save(backup=True)
            print("\n!! The browser tab left Alpaca, so this run stops.")
            print("   Nothing was pressed there. Open Alpaca with login.bat and run this again.")
            raise SystemExit(0)
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
        # Signed out: the run stops for the account holder.
        try:
            site.check_signed_in(page)
        except site.SessionExpired:
            self.session_ended()

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in. The tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9292")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        # A real Edge or Chrome first, which is also what the site's own
        # sign-in expects. Any Chromium-based browser will do.
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        print("Checking the connection to your signed-in Alpaca browser...\n")
        page = self.page()
        # What only a signed-in Live account shows, the documents page with
        # its list. Nothing is pressed.
        listed = site.goto_documents(page, self.run)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Alpaca shows its sign-in page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif listed:
            print("Success. Connected, and your Live account's documents page opened.")
            print("Keep that browser window OPEN, then run the diagnostics or pilot.")
        else:
            print("Connected, but the Live account's documents page did not open. If the")
            print("account switcher shows a Paper account, choose your Live account there")
            print("yourself, since this app never switches it. Then re-run --login.")
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

    def _record_rawdoc(self, r, source_url: str) -> int:
        """Record one document (a RawDoc) read from the documents page.
        Returns 1 if new. Its file name is its date and the rules' summary
        for its title."""
        title = re.sub(r"\s+", " ", (r.title or "")).strip()
        if not title:
            return 0
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        if category == doc_types.OTHER:
            summary = notice_summary(title)
        date = (r.date_text or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date, _ = site.parse_period_date(title)
            date = date or ""
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc = Document(title=title, category=category, summary=summary,
                       date=date, confidence=confidence, source_url=persistable(source_url),
                       href=persistable(getattr(r, "href", "") or ""),
                       document_id=(getattr(r, "document_id", "") or "").strip(),
                       doc_type=getattr(r, "doc_type", "") or "")
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        # refresh what binds the record to its row when it is taken
        self.discovery.update(doc.key, {"source_url": persistable(source_url),
                                        "doc_type": doc.doc_type}, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        n_new = 0
        # The documents page is opened and read in one go by the site
        # layer, so a sign-out, a Paper account or the deadline anywhere on
        # the way reaches the boundary below and stops the run, rather than
        # a prompt to sign in again.
        self.check_session(page)
        # The run's own start date, which the list must reach back to
        # unless it holds the account's application (site.reaches_back).
        self.run.floor = self.args.start_date or self.config.get("default_start_date") or None
        try:
            docs = site.collect_download_docs(page, self.run)
        except site.SessionExpired:
            self.session_ended()
        except site.NotLive:
            self.not_live()
        except site.DeadlineReached:
            self.deadline_reached()
        except site.WindowNotWhole:
            # The page asked for a window this cannot call whole, which
            # needs a page change or a bug, so nothing in it is kept.
            print("\n!! Alpaca's list of documents was asked for a window that does not run from")
            print("   its start to yesterday or later, so it may be missing documents, and this")
            print("   run stops rather than call the list read. Run it again later.")
            self.write_failure("read the documents list", "the list's window is not whole")
            raise SystemExit(1)
        except site.ListTooShort as short:
            # Running again would stop the same way: only a start date the
            # list reaches lets it be called whole.
            print("\n!! Alpaca's list of documents starts at "
                  f"{short.start or 'a date it did not give'} and holds no account application,")
            print("   so it may not reach back to your account's first documents, and this run")
            print("   stops rather than call the list read. To take what the list holds, set")
            print("   --start-date, or default_start_date in config.json, to that date or later.")
            self.write_failure("read the documents list", "the list does not reach back to the account")
            raise SystemExit(1)
        except site.ListStopped as stop:
            # What was listed is kept, and the listing stays noted as one
            # that stopped, so neither this run nor a Resume calls it whole.
            for r in stop.docs:
                self._record_rawdoc(r, site.DOCUMENTS_URL)
            self.discovery.save()
            print(f"\n!! The list of Alpaca statements and trade confirmations stopped partway, since {stop}.")
            print(f"   The {len(stop.docs)} document(s) listed before it stopped are kept,")
            print("   and this run stops rather than call the list read. Run it again.")
            self.write_failure("read the documents list", "the list stopped partway")
            raise SystemExit(1)
        # Documents of one type on one date, left unsaved, for the run
        # summary and the panel.
        self.stats["alike"] = int((getattr(self.run, "counts", {}) or {}).get("alike", 0))
        for r in docs:
            n_new += self._record_rawdoc(r, site.DOCUMENTS_URL)
        self.discovery.save()
        log.info("documents page: %d documents, %d new", len(docs), n_new)

        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
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
            # What the list held and this app does not take, by kind and
            # count only. Each is listed by Alpaca and never pressed.
            counts = getattr(self.run, "counts", {}) or {}
            for key, said in (("twins", "JSON copies of trade confirmations"),
                              ("applications", "account applications"),
                              ("tax", "tax forms, not collected yet"),
                              ("other", "documents of a type this app does not know"),
                              ("alike", "documents sharing a type and date with another, "
                                        "which a row cannot tell apart")):
                if counts.get(key):
                    print(f"  Skipped, {said}: {counts[key]}")
        return n_new

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
        # a review copy counts only if its PDF is still present and valid, and
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on app.alpaca.markets and
        never a tab of another site. With no tab of the person's on the site
        the documents page is opened in a tab of this run's own, the way
        discovery opens it (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "Alpaca",
                                self._open_documents)

    def _open_documents(self, page):
        """The documents page, opened by its address the way discovery
        opens it."""
        if not site.goto_documents(page, self.run):
            self.check_session(page)
            site.goto_documents(page, self.run)

    def process(self, docs: List[Document], dry_run: bool = False):
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            # A run takes no further document once its time is up, counted
            # from when it first opened the documents page (site.Run).
            if not dry_run and self.run.past_deadline():
                self.deadline_reached()
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
            except site.SessionExpired:
                # Alpaca answered as a signed-out session. Every document
                # after it would get the same answer, so the run stops here,
                # with nothing recorded against this one.
                self.session_ended()
            except site.NotLive:
                self.not_live()
            except site.DeadlineReached:
                self.deadline_reached()
            except site.ListStopped as stop:
                # The documents page could not be read again for this
                # document, or its list changed before the press. Every
                # document after it reads the same list, so the run stops
                # here rather than send each one to review.
                self.list_changed(stop)
            except Exception as e:
                # Neither the record's key nor the error's words are said:
                # both can carry a document id or a page's words.
                log.error("Failed on the %s dated %s (%s)",
                          doc.summary or "document", doc.date or "?", type(e).__name__)
                self._record(doc, State.FAILED, notes="failed (%s)" % type(e).__name__)
                self.stats["failed"] += 1
            self._delay()

    def session_ended(self) -> None:
        """Stop the run because Alpaca has signed the session out.
        Progress is saved, nothing is recorded for review, and the run ends
        as one that stopped (tabs.stop)."""
        tabs.stop(self, [
            "Alpaca answered as signed out, so this run stops here.",
            "Everything saved so far is kept. Sign in again in the open browser",
            "window, then run Resume to carry on from where this stopped.",
        ])

    def not_live(self) -> None:
        """Stop the run because the page is not the Live account's documents
        page: a Paper account, a switcher that could not be read, or a page
        that settled elsewhere. Nothing was pressed, and nothing is recorded
        for review."""
        tabs.stop(self, [
            "Alpaca is not showing your Live account's documents page, so this run stops here.",
            "Nothing was pressed. Choose your Live account in Alpaca's account switcher",
            "yourself (this app never switches it, and never reads a Paper account),",
            "then run Resume to carry on from where this stopped.",
        ])

    def deadline_reached(self) -> None:
        """Stop the run before anything more is pressed once it has been at
        Alpaca for site.DEADLINE_S since it first opened the documents page.
        Progress is saved and nothing is recorded for review."""
        tabs.stop(self, [
            "This run has been at Alpaca for %d minutes, so it stops before the next press."
            % (site.DEADLINE_S // 60),
            "Everything saved so far is kept. Run Resume to carry on from where this stopped.",
        ])

    def list_changed(self, stop) -> None:
        """Stop the run because the list could not be read again while a
        document was sought. Nothing is recorded against the document, and
        the run leaves as one whose list did not end whole, which only a run
        that lists carries on from (listing.read_again_stopped)."""
        log.info("the list could not be read again: %s", stop)
        self.write_failure("read the documents list again", "the list changed or stopped")
        listing.read_again_stopped(self, (
            "The Alpaca documents list could not be read again, so this "
            "run stops here."))

    def download_one(self, page, doc: Document, filename: str):
        """Save one document. The site layer opens the documents page again,
        reads its list afresh, binds the record to exactly one listed
        document and one row, and only then presses that row's Download,
        taking the download."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # Only a name already taken in the folder gets a hash of the
        # document id (told_apart_by).
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=told_apart_by(doc.to_dict()))
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        # The site layer opens the documents page itself, finds this
        # document and takes it.
        trace: list = []
        try:
            saved = site.download_document(page, self.run, self._dl_dir, out_path,
                                           document_id=doc.document_id, iso_date=doc.date,
                                           doc_type=doc.doc_type, trace=trace)
        except site.DocumentTurnedOff:
            # Alpaca has turned this document's Download off for now, so
            # nothing was pressed. It is left as it was, recorded nowhere,
            # and the next run takes it, and this run goes on to the next one.
            log.info("the %s dated %s is left for the next run: its Download is turned off",
                     doc.summary or "document", doc.date or "?")
            self.stats["left_for_next_run"] += 1
            print("  Alpaca has turned this document's Download off for now - "
                  "left for the next run.")
            return
        # A capture that failed must not leave a convincing empty file behind.
        if out_path.exists() and (
                out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            saved = False
        if not saved:
            attempt = self.paths.diagnostics / "download-attempt.json"
            write_shaped(attempt, {
                "timestamp": now_iso(), "date": doc.date,
                "landed_on": site.redact(page.url or ""),
                "responses": trace[:80]}, words_for('Alpaca', site))
            print(f"  What the site answered is in {attempt}, attach it to the issue.")
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF")
            self._write_row(doc, "Capture failed", "Needs Manual Review")
            self.write_failure('capture the document', 'the document would not render')
            self.stats["manual_review"] += 1
            print("  Could not capture this document - marked for manual review.")
            return

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
        if doc.category == doc_types.STATEMENT:
            self.stats["statements"] += 1
        else:
            self.stats["other"] += 1
        print(f"  Saved: {out_path.name}")

    # -- records -----------------------------------------------------------

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
            # Left blank: the holder here is often a company whose name is
            # private (keep_owner_out_of_names), and the index is a file.
            "Account Holder": "",
            "Document Date": doc.date,
            "Category": doc.category,
            "Document Summary": doc.summary,
            "Document Title": doc.title,
            "Period": doc.period,
            "PDF Filename": doc.pdf_filename,
            "PDF Full Path": doc.pdf_path,
            "PDF File Size": doc.pdf_size,
            "PDF Page Count": doc.pdf_pages,
            "Source URL": persistable(doc.href),
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
        # The pilot takes the newest brokerage statement on purpose: the
        # kind of document every account has, from the folder the survey
        # did not reach.
        docs = [d for d in self._select(limit=0) if d.doc_type == "account_statement"]
        docs = docs[:max(1, int(self.config.get("pilot_count", 1) or 1))]
        if not docs:
            print("\nNo brokerage statement in scope to pilot. Run --diagnose.")
            return
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)
        self._pilot_report(docs)
        if not self.args.dry_run and pilot_failed(self.progress.data, docs):
            # A pilot is the gate before a full run, so a pilot whose document
            # did not land as a valid PDF is a run that stopped, not a clean one.
            raise SystemExit(1)

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
            # Said by date and summary, never by the record's key, which
            # carries the document id.
            which = f"{d.date or '?'} {d.summary or ''}".strip()
            if saved_copy.tried(self, d.key):
                problems.append(f"{which}: {saved_copy.tried(self, d.key)}")
            if state != State.COMPLETED.value:
                problems.append(f"{which}: {state} - {rec.get('notes', '')}")
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
            print(f"This downloads ALL available Alpaca statements and trade confirmations ({scope}).")
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
        # Resume reads no list of its own. With nothing listed, or after a
        # run that stopped before it had the whole list, it says so and stops
        # as a run that stopped, rather than call the run finished
        # (paperpull_core.listing).
        docs = [d for d in self._select() if not self._already_done(d)]
        listing.resume(self, docs, lambda left: self.process(left, dry_run=self.args.dry_run))


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
            # Only the list and link calls are described. Every other
            # answer on Alpaca's host, the account's details, owners and
            # billing among them, holds personal data and is never read.
            self._requests = Requests(getattr(self, "_work_page", None),
                                      getattr(site, "is_census_url", None))
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
            provider='Alpaca', text=text, extra=extra)
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
            provider='Alpaca',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        """Survey the documents page and write a file a tester can attach to
        the GitHub issue. No screenshot, no page label, digit runs masked.
        Nothing is downloaded and nothing is pressed: the documents page is
        opened by its address and read as it drew itself."""
        self.stats["mode"] = "diagnose"
        words = words_for('Alpaca', site)
        page = self.page()
        info = {"timestamp": now_iso(),
                "note": Fixed("A survey of the Alpaca documents page, by counts. "
                              "It is what a repair of the site layer is checked against.")}
        stopped = None
        try:
            try:
                found = site.goto_documents(page, self.run)
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
            info["survey"] = site.survey(page)
            info["row_counts"] = {}
            for name, sel in [("doc_row", site.FALLBACK["doc_row"]),
                              ("download controls", site.ROW_CONTROL),
                              ("tables", site.TABLE),
                              ("account switchers", site.SWITCHER)]:
                try:
                    info["row_counts"][name] = page.locator(sel).count()
                except Exception as e:
                    info["row_counts"][name] = f"ERR {type(e).__name__}"
            # The documents drawn now, by date and type only. The rows name
            # no account.
            docs = site.collect_documents(page)
            info["documents_recognized"] = [{"date": d.date_text, "kind": d.kind, "row": d.text}
                                            for d in docs[:40]]
            info["rows_collected"] = len(docs)
        except pressing.Stop as stop:
            # A press past the documents page it would not make ends the
            # look there, and the file still says what was seen and why it
            # stopped.
            stopped = stop
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
        except Exception as e:
            info["error"] = type(e).__name__
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
        print("then attach it to the Alpaca issue on GitHub. No screenshot was taken.")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Alpaca',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Alpaca Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Other documents:           {s['other']}",
            f"Skipped (already done):    {s['skipped_completed']}",
            f"Skipped (out of scope):    {s['skipped_out_of_scope']}",
            f"Needs manual review:       {s['manual_review']}",
            f"Failed:                    {s['failed']}",
            f"Left for the next run:     {s.get('left_for_next_run', 0)}",
            f"Left unsaved, alike:       {s.get('alike', 0)}",
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
        description="Local supervised Alpaca statement and trade confirmation downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download the newest brokerage statement, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "survey the documents page, pressing nothing (no downloads)"),
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
    ap.add_argument("--type", help="Statement")
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
        if d and site.calendar_date(d) != d:
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
        try:
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
        finally:
            # Whatever the saving did, the run's downloads are swept and
            # its listener let go with the tab.
            app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
