"""TreasuryDirect tax document downloader (local, supervised).

TreasuryDirect, the U.S. Treasury's own site for savings bonds and Treasury
securities, has no PDFs. This saves its pages as PDFs instead, Current
Holdings, Security History and Payment History as dated snapshots, and
lists each taxable year's Form 1099 from ManageDirect for you to save by
hand. The app moves through the site only by pressing its own links in
your signed-in tab, since opening one of its addresses ends the session,
and renders each page without running anything in it. The orchestrator
below is the same one every other statement app runs on. Everything about
the site itself is in treasurydirect_site.py.

Partly surveyed, as the surveyed block in treasurydirect_site.py and the
README's Validation status say. The 1099 pages are UNCONFIRMED.

Usage:
    python treasurydirect_docs.py --login       verify connection to your browser
    python treasurydirect_docs.py --discover    list available documents
    python treasurydirect_docs.py --pilot       download the newest few, then stop
    python treasurydirect_docs.py --all         download everything in scope
    python treasurydirect_docs.py --resume      continue an interrupted run
    python treasurydirect_docs.py --verify      re-validate every saved PDF
    python treasurydirect_docs.py --diagnose    dump page structure (no downloads)
    python treasurydirect_docs.py --record      record the path you take to one document
    python treasurydirect_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement | "Tax Document"

READ-ONLY: this tool only reads TreasuryDirect's pages and saves them as
PDFs. It never opens an address or submits a form. It never buys, redeems, converts, transfers or gifts a security,
changes a bank account, registration or setting, or signs in or out. It
never answers a one-time passcode or security question. Everything stays on
this machine, and nothing is sent to any external service.
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
import treasurydirect_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("treasurydirect_docs")


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


class Document:
    """One TreasuryDirect document: a dated snapshot of Current Holdings,
    Security History or Payment History, or a tax year's Form 1099."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", **kw):
        self.title = title
        # The digest of the account the document was listed on
        # (site.account_digest), never its number. Empty for a sign-in of
        # one account whose pages name none.
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        # "<kind>-<date>" for a snapshot or "<tax year>-1099", what it is known by.
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
        """Stable identity. The account's digest with the document's kind and
        day, or tax year, which no other document of that account carries,
        so one sign-in's accounts are kept apart. A record without one falls
        back to category, date and title."""
        acct = _account_component(sanitize_component(self.account or ""))
        if self.document_id:
            return f"id:{acct}:{self.document_id}" if acct else f"id:{self.document_id}"
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
    """What a document's file adds to its name when another file already
    has that name, the same on every run and never " (2)"
    (core/tests/test_every_app_renames_each_file_for_its_own_record). The
    first six letters of its account's digest, never the number, or its id
    when the record names no account. Every document of one account
    already has a name of its own, by kind and date, so this is reached
    when another account of the sign-in has a file of that name, or a
    file of that name is already in the folder. The download and Rename
    both ask this, so they agree."""
    record = record or {}
    return (str(record.get("account") or "").strip()[:6]
            or str(record.get("document_id") or "").strip())


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
        for store in (self.progress, self.discovery):
            if migrate_legacy_keys(store.data):
                store.save(backup=True)
        self.index_csv = CsvFile(self.paths.document_index_csv,
                                 DOCUMENT_INDEX_COLUMNS, self.paths.backups, once=True)
        self.rules = doc_types.load_rules()
        # The owner's name first. The site adds what names the account, its
        # number, taxpayer id and registration, from every page it reads.
        site.set_private_words([self.config.get("owner", "")])

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
            # Reuse the person's own tab on TreasuryDirect, the signed-in
            # page they left open. TreasuryDirect keeps its session in
            # the flow of that tab, so a tab of this run's own is opened only
            # to be found not signed in (tabs.on_its_site stops the run
            # then). Matched on the parsed host, never a substring, since
            # "provider.com" in an address also matches
            # "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            dom = [p for p in live if site.is_safe_url(p.url or "")]
            # A tab left on the log-in page comes after one that is signed
            # in: the person may have signed in again in a second tab.
            dom.sort(key=lambda p: site.looks_like_login_url(p.url or ""))
            self._work_page = dom[0] if dom else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
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
        """Stop the run unless the tab is a signed-in TreasuryDirect page
        with its top tabs.

        Nothing here waits at a prompt or tries anything on the page:
        TreasuryDirect's sign-in, its emailed passcode and any security
        question are the account holder's alone, so each one stops the run
        with what to do, and progress is already saved (#48). A tab off
        TreasuryDirect is never read or asked anything."""
        # Signed out first: an ended session lands on caia.treasury.gov,
        # which is not TreasuryDirect's own host but is its sign-in.
        if site.looks_signed_out(page):
            self.session_ended()
        if not site.is_safe_url(self._url_of(page)):
            tabs.stop(self, [
                "The browser tab is not on TreasuryDirect, so this run stops.",
                "Nothing was asked of TreasuryDirect. Open it with login.bat, sign in,",
                "keep the window open on your account, and run this again.",
            ])
        challenge = site.detect_security_challenge(page)
        if challenge:
            self.otp_required()
        if not site.goto_documents(page):
            self.not_live()

    @staticmethod
    def _url_of(page) -> str:
        try:
            return page.url or ""
        except Exception:
            return ""

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9294")
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
        print("Checking the connection to your signed-in TreasuryDirect browser...\n")
        page = self.page()
        challenge = site.detect_security_challenge(page)
        # What only a signed-in page shows: the account's top tabs.
        listed = site.goto_documents(page)
        # Nothing is pressed here: Login only says whether the tab is a
        # signed-in page the run could start from.
        if site.looks_signed_out(page):
            print("Connected, but TreasuryDirect shows its sign-in page or has ended the session.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif not site.is_safe_url(self._url_of(page)):
            print("Connected, but no tab is open on TreasuryDirect.")
            print("Sign in in the open browser window, then re-run --login.")
        elif challenge:
            print(f"!! {challenge}\nAnswer it yourself in the browser, then re-run --login.")
        elif listed:
            print("Success. Connected, and your TreasuryDirect account is open.")
            print("Keep that browser window OPEN, and do not use its Back button,")
            print("then run the diagnostics or pilot.")
        else:
            print("Connected, but the tab is not a signed-in TreasuryDirect page with its")
            print("tabs (My Account, Current Holdings, ManageDirect, History). Open your")
            print("account in it yourself, then re-run --login.")
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
        """Record one document (a RawDoc). Returns 1 if new. A 1099 is dated
        its tax year's December 31, the way every app files a tax form, and
        its period names the year; a snapshot is dated the day it is
        taken."""
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
        date = (r.date_text or "").strip()
        if not re.fullmatch(r"(19|20)\d{2}-\d{2}-\d{2}", date):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and date < floor:
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc = Document(title=title, category=category, summary=summary,
                       date=date, confidence=confidence,
                       period=f"Tax Year {date[:4]}" if category == doc_types.TAX else "",
                       source_url=persistable(source_url),
                       href=persistable(getattr(r, "href", "") or ""),
                       account=(getattr(r, "account", "") or "").strip(),
                       document_id=(getattr(r, "document_id", "") or "").strip())
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        # refresh which page the document's link lives on, and its own path
        self.discovery.update(doc.key, {"source_url": persistable(source_url),
                                        "href": persistable(getattr(r, "href", "") or "")}, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        n_new = 0
        # The site layer presses ManageDirect in the person's tab and reads
        # its tax years in one go, so a sign-out, a passcode or a tab moved
        # off the account anywhere on the way reaches the boundaries below
        # and stops the run.
        self.check_session(page)
        where = persistable(self._url_of(page))
        try:
            docs = site.collect_download_docs(page)
        except site.SessionExpired:
            self.session_ended()
        except site.OtpRequired:
            self.otp_required()
        except site.NotLive:
            self.not_live()
        except site.ListStopped as stop:
            # What was listed is kept, and the listing stays noted as one
            # that stopped, so neither this run nor a Resume calls it whole.
            for r in stop.docs:
                self._record_rawdoc(r, where)
            self.discovery.save()
            print(f"\n!! The TreasuryDirect list stopped partway, since {stop}.")
            print(f"   The {len(stop.docs)} document(s) listed before it stopped are kept,")
            print("   and this run stops rather than call the list read. Open the page it")
            print("   stopped on in the browser, run Diagnose and attach the file it writes")
            print("   to the TreasuryDirect issue.")
            self.write_failure("read the documents list", "the list stopped partway")
            raise SystemExit(1)
        for r in docs:
            n_new += self._record_rawdoc(r, where)
        self.discovery.save()
        log.info("TreasuryDirect: %d documents, %d new", len(docs), n_new)

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
                print(f"  Tax years: {dates[0][:4]} .. {dates[-1][:4]}")
            if self.stats["skipped_out_of_scope"]:
                print(f"  Skipped as out of scope: {self.stats['skipped_out_of_scope']}")
        return n_new

    def _select(self, limit: Optional[int] = None) -> List[Document]:
        """The documents in scope, newest first. A snapshot of an earlier
        day is never one, since it can no longer be taken under that day's
        name (site.is_stale), so neither a run nor Resume counts it as
        remaining."""
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        docs = [d for d in docs if self._in_scope(d) and not site.is_stale(d.document_id)]
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
        # A taxable year's 1099 set aside for the account holder is told
        # once. Later runs leave it as done, the person may have saved it
        # by hand already.
        if self._set_aside(doc, rec):
            return True
        # a review copy counts only if its PDF is still present and valid;
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    @staticmethod
    def _set_aside(doc: Document, rec: dict) -> bool:
        """Whether the record is a taxable year's 1099 set aside, with no
        file, for the account holder to save by hand. This build never
        presses a tax year's link (site.TAX_PAGES_SURVEYED), so one is only
        ever told, and a build that takes 1099s takes it again."""
        return (doc.document_id.endswith("-1099") and not site.TAX_PAGES_SURVEYED
                and (rec or {}).get("state") == State.NEEDS_MANUAL_REVIEW.value
                and not (rec or {}).get("pdf_path"))

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in: the person's own tab on
        TreasuryDirect. Its session lives in that tab's flow, which a tab of
        this run's own would not have, so with none open the run stops
        (tabs.on_its_site, given no way to open the documents)."""
        return tabs.on_its_site(self, site.is_safe_url, "TreasuryDirect")

    def process(self, docs: List[Document], dry_run: bool = False):
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                if self._set_aside(doc, self.progress.get(doc.key)):
                    print("  Listed on an earlier run for you to save by hand - skipping.")
                else:
                    print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            if site.is_stale(doc.document_id):
                # A snapshot shows the account as it is when taken, so one
                # recorded on an earlier day is not taken today under that
                # day's name. Today's is listed beside it.
                print("  A snapshot of an earlier day - not taken.")
                self.stats["skipped_out_of_scope"] += 1
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
            except site.SessionExpired:
                # TreasuryDirect answered as a signed-out session. Every
                # document after it would get the same answer, so the run
                # stops here, with nothing recorded against this one.
                self.session_ended()
            except site.OtpRequired:
                self.otp_required()
            except site.NotLive:
                self.not_live()
            except site.ListStopped as stop:
                # The page every document starts from could not tell which
                # account it is on. Every document after this one starts
                # there too, so the run stops here rather than send each one
                # to review.
                self.list_changed(stop)
            except Exception as e:
                # Only the kind of error is kept. A browser's message can carry
                # the page's address with its session id, or the page's words.
                # A press the core refused (pressing.Stop) is a SystemExit and
                # never reaches here: it stops the run in main().
                log.error("Failed on %s (%s)", doc.key, type(e).__name__)
                self._record(doc, State.FAILED, notes=type(e).__name__)
                self.stats["failed"] += 1
            self._delay()

    def session_ended(self) -> None:
        """Stop the run because TreasuryDirect has signed the session out.
        Progress is saved, nothing is recorded for review, and the run ends
        as one that stopped (tabs.stop)."""
        tabs.stop(self, [
            "TreasuryDirect answered as signed out, so this run stops here.",
            "Everything saved so far is kept. Sign in again in the open browser",
            "window, open your account, then run Resume to carry on.",
        ])

    def otp_required(self) -> None:
        """Stop the run because TreasuryDirect asked for a one-time passcode
        or a security answer, which this app never gives."""
        tabs.stop(self, [
            "TreasuryDirect is asking for a passcode or a security answer, so this run stops.",
            "This app never answers one. Answer it yourself in the browser window,",
            "then run Resume to carry on. Everything saved so far is kept.",
        ])

    def not_live(self) -> None:
        """Stop the run because the tab is not a signed-in TreasuryDirect
        page with its top tabs, the only place this app starts a press
        from. Nothing is opened in its place: TreasuryDirect ends a session
        whose pages are opened by anything but its own links."""
        tabs.stop(self, [
            "The TreasuryDirect tab is not on a page of your account, so nothing was pressed.",
            "Open your account in that tab yourself (My Account), keep the window",
            "open, and run this again.",
        ])

    def list_changed(self, stop) -> None:
        """Stop the run because the list could not be read again while a
        document was sought. Nothing is recorded against the document, and
        the run leaves as one whose list did not end whole, which only a run
        that lists carries on from (listing.read_again_stopped)."""
        log.info("the list could not be read again: %s", stop)
        self.write_failure("read the documents list again", "the list changed or stopped")
        listing.read_again_stopped(self, (
            "The TreasuryDirect account page could not be read again, so "
            "this run stops here."))

    def download_one(self, page, doc: Document, filename: str):
        """Save one document. The site layer moves the person's tab to it by
        pressing the page's own links, each one checked against the guards,
        and renders the page it lands on to a PDF inertly. No address is
        opened and no form is submitted."""
        self.check_session(page)
        if doc.document_id.endswith("-1099") and not site.TAX_PAGES_SURVEYED:
            # The year's link is never pressed until its page has been
            # surveyed, so the 1099 TreasuryDirect lists is left for the
            # account holder to save by hand, and they are told it exists.
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="TreasuryDirect lists a taxable year; open its 1099 yourself")
            self._write_row(doc, "Not taken", "Needs Manual Review")
            self.stats["manual_review"] += 1
            print(f"  TreasuryDirect lists tax year {doc.date[:4]} as taxable. This app does not")
            print("  open tax pages yet. Open ManageDirect, Manage My Taxes, that year, and")
            print("  print its 1099 to PDF yourself; Diagnose on that page helps the next build.")
            return
        folder = self.paths.folder_for(doc.category)
        # Only a name already taken in the folder gets the document's kind
        # (told_apart_by).
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=told_apart_by(doc.to_dict()))
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        trace: list = []
        try:
            saved = site.download_document(page, doc.document_id, doc.date, out_path,
                                           trace=trace, account=doc.account)
        except site.OtherAccount:
            # One sign-in can hold several accounts. A page of another one
            # is never saved under this document's name, so nothing is
            # rendered and the document is left for review.
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="the tab is on another TreasuryDirect account")
            self._write_row(doc, "Not taken", "Needs Manual Review")
            self.stats["manual_review"] += 1
            print("  The tab is on another TreasuryDirect account than this document was")
            print("  listed on, so nothing was saved. Open that account in the tab, then Resume.")
            return
        # A render that failed must not leave a convincing empty file behind.
        if out_path.exists() and (
                out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            saved = False
        if not saved:
            attempt = self.paths.diagnostics / "download-attempt.json"
            write_shaped(attempt, {
                "timestamp": now_iso(), "date": doc.date,
                "landed_on": site.redact(self._url_of(page)),
                "responses": trace[:80]}, words_for('TreasuryDirect', site))
            print(f"  What the site answered is in {attempt}, attach it to the issue.")
            self._record(doc, State.FAILED,
                         notes="Could not render the document page")
            self._write_row(doc, "Capture failed", State.FAILED.value)
            self.write_failure('capture the document', 'the document would not render')
            self.stats["failed"] += 1
            print("  Could not capture this document. Nothing was saved, and the next run tries it again.")
            return

        doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
        self._record(doc, State.PDF_SAVED)

        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"])
        if result.ok and not site.pdf_names_document(doc.document_id, receipt_pdf.pdf_text(out_path)):
            # A page rendered blank, or the wrong page, is a valid PDF that
            # is not the document; it is never marked saved.
            result = receipt_pdf.ValidationResult(False, "the PDF's text does not name the document",
                                                  size_bytes=result.size_bytes, page_count=result.page_count)
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
        docs = self._select(limit=self.config.get("pilot_count", 5))
        if not docs:
            print("\nNo documents in scope to pilot. Run --diagnose.")
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
            if saved_copy.tried(self, d.key):
                problems.append(f"{d.key}: {saved_copy.tried(self, d.key)}")
            if state != State.COMPLETED.value:
                problems.append(f"{d.key}: {state} - {rec.get('notes', '')}")
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
            print(f"This downloads ALL available TreasuryDirect tax documents ({scope}).")
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
            provider='TreasuryDirect', text=text, extra=extra)
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
            provider='TreasuryDirect',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        """Survey the TreasuryDirect tab as it is and write a file a tester can attach
        to the GitHub issue. No screenshot, digit runs masked, the page's
        words as their shapes. Nothing is saved, nothing is pressed and the
        tab is not moved: open the page to be surveyed (ManageDirect, a
        history, a 1099) in the tab yourself first."""
        self.stats["mode"] = "diagnose"
        words = words_for('TreasuryDirect', site)
        page = self.page()
        info = {"timestamp": now_iso(),
                "note": Fixed("A survey of the TreasuryDirect page open in the tab. It is what "
                              "the first repair of the site layer is checked against.")}
        stopped = None
        try:
            info["landed_on"] = site.redact(self._url_of(page))
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
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
            info["survey"] = site.survey(page)
            docs = site.collect_documents(page)
            info["links_collected"] = len(docs)
            info["samples"] = [{"title": d.title[:90], "path": d.href[:100], "section": d.text[:90]}
                               for d in docs[:40]]
        except pressing.Stop as stop:
            # A press past the documents page it would not make ends the
            # look there, and the file still says what was seen and why it
            # stopped.
            stopped = stop
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
        except Exception as e:
            info["error"] = type(e).__name__ + ": " + site.redact(str(e))[:300]
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
        print(f"Signed-in page found: {shape_tree(info.get('documents_page_found', '?'), words)}, "
              f"links: {shape_tree(info.get('links_collected', '?'), words)}")
        print("Look through that file for anything you would not want public,")
        print("then attach it to the TreasuryDirect issue on GitHub. No screenshot was taken.")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='TreasuryDirect',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "TreasuryDirect Documents - run summary",
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
        description="Local supervised TreasuryDirect tax document downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download the 5 newest in-scope documents, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "survey the open TreasuryDirect page (no downloads, nothing pressed)"),
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
    ap.add_argument("--type", help="Statement or Tax Document")
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
