"""Robinhood statement & tax-document downloader (local, supervised).

Usage:
    python robinhood_docs.py --login       verify connection to your browser
    python robinhood_docs.py --discover    list available documents
    python robinhood_docs.py --pilot       download the 5 newest, then stop
    python robinhood_docs.py --all         download everything in scope
    python robinhood_docs.py --resume      continue an interrupted run
    python robinhood_docs.py --verify      re-validate every saved PDF
    python robinhood_docs.py --diagnose    dump page structure (no downloads)
    python robinhood_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement|"Tax Document"

READ-ONLY: this tool only reads the Documents area and downloads PDFs that
Robinhood already generated. It never transfers funds, trades, rebalances,
or changes any account setting. Everything stays on this machine; nothing is
sent to any external service.
"""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import renaming
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import report_run_result

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
import robinhood_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import is_done
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("robinhood_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One Robinhood document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        self.document_id = document_id  # Robinhood's stable per-document UUID
        self.source_url = kw.get("source_url", "")  # page where the doc's download link lives
        # The year the page shows beside a tax form whose title carries none,
        # so the download presses that year's control and no other (#62).
        self.tax_year = kw.get("tax_year", "")
        # The end of the tax year a form prints, for one the page gave no
        # year. It names the file and its ledger row, never the key, which
        # is what the page lists every run.
        self.printed_date = kw.get("printed_date", "")
        # The key a form saved without a date was remembered by, before the
        # page's year gave it one. Kept so a page that shows it without a
        # year again is still known to be done.
        self.undated_key = kw.get("undated_key", "")
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
        """Stable identity. Robinhood's API gives each document a durable
        documentId (UUID) - use it. Fall back to category:date:title:account
        for anything discovered without one."""
        if self.document_id:
            return f"id:{self.document_id}"
        # Keep the last four. Cutting to forty characters made two cards
        # of the same product collide, because the masked digits that say
        # which one it is sit at the end, and the second card's whole
        # history was then read as already downloaded and dropped.
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


def _clear(path) -> None:
    """Remove a file this run made and is not keeping."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


class _Ledger:
    """The index as a rename reads it, written through to the real one."""

    def __init__(self, csv, rows):
        self._csv, self._rows = csv, rows
        self.columns = csv.columns

    def read_all(self):
        return self._rows

    def rewrite(self, rows):
        self._csv.rewrite(rows)


class _Records:
    """Records as a rename reads them, which is only ever `.data`."""

    def __init__(self, data):
        self.data = data


class _DatedTaxForms:
    """This app as a rename sees it, with a tax form saved without a date
    dated after all (#62).

    A form whose title named no year was saved as 0000-00-00, with a ledger
    row that has no date. Rename names a file from its row, so a date the
    record learned later never reached the file. Here each such row is
    dated from what is known now, in this view only, so a preview changes
    nothing and an applied rename writes the row along with the file.

    A row is dated only by the year its own file prints. A date some record
    of the same title has is not evidence about this file, and several
    rows of one title each carry their own. A row whose file is gone or
    prints no clear year keeps no date, and the file its name. The rename
    finds a row's record by its date and title, so when no record is dated
    that way it is shown a copy of the undated record dated as its row is,
    and a naming pattern that uses the record still has it."""

    def __init__(self, app, read_text=None):
        read_text = read_text or receipt_pdf.pdf_text
        self.config = app.config
        self.progress = app.progress
        dated, undated = set(), {}
        for store in (app.progress, app.discovery):
            for rec in (getattr(store, "data", None) or {}).values():
                if not isinstance(rec, dict) or rec.get("category") != doc_types.TAX:
                    continue
                title = (rec.get("title") or "").strip()
                if rec.get("date"):
                    dated.add((rec["date"], title))
                elif store is app.progress:
                    undated.setdefault(title, []).append(rec)
        rows = app.index_csv.read_all()
        copies = {}
        for row in rows:
            if ((row.get("Category") or "").strip() != doc_types.TAX
                    or (row.get("Document Date") or "").strip()):
                continue
            path = (row.get("PDF Full Path") or "").strip()
            if not path or not Path(path).exists():
                continue
            year = site.printed_tax_year(read_text(Path(path)))
            if not year:
                continue
            date = f"{year}-12-31"
            title = (row.get("Document Title") or "").strip()
            row["Document Date"] = date
            if not (row.get("Period") or "").strip():
                row["Period"] = f"Tax Year {year}"
            if (date, title) not in dated and len(undated.get(title, [])) == 1:
                copies["dated by form:%s:%s" % (date, title)] = dict(
                    undated[title][0], date=date, period=f"Tax Year {year}")
        self.index_csv = _Ledger(app.index_csv, rows)
        data = dict(getattr(app.discovery, "data", None) or {})
        data.update(copies)
        self.discovery = _Records(data)


class App:
    _journal = None
    _requests = None
    # Every key the current discovery listed, None outside one.
    _listed_now = None
    # (title, date) of what the individual page listed in the current
    # discovery, None outside one.
    _individual_listed = None

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
            "crypto_refused": 0, "wrong_document": 0, "notes": [],
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
            self._context = self._pw.chromium.launch_persistent_context(
                str(profile), headless=False, accept_downloads=True,
                viewport={"width": 1400, "height": 950})
            self._cdp_mode = False
        self._context.set_default_timeout(30000)
        return self._context

    def page(self):
        ctx = self.browser()
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        self._work_page = ctx.new_page() if self._cdp_mode else (
            ctx.pages[0] if ctx.pages else ctx.new_page())
        self.requests
        return self._work_page

    def close(self):
        try:
            if self._cdp_mode:
                if self._work_page is not None and not self._work_page.is_closed():
                    self._work_page.close()
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

    def check_session(self, page) -> bool:
        """Raise/pause on sign-out or security challenges.

        True when the person was asked to sign in again and the page was
        left on the documents page, so a caller that had opened something
        else has to open it again before it reads anything. False
        otherwise."""
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
            print("\n!! Robinhood appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)
            return True
        return False

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9224")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=False,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        print("Checking the connection to your signed-in Robinhood browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Robinhood shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and the Documents page is visible.")
            print("Keep that browser window OPEN, then run run_pilot.bat.")
        else:
            print("Connected, but the Documents list did not load, so this cannot say")
            print("whether you are signed in. Look at the browser window and answer")
            print("anything Robinhood asks there yourself. If it shows your account, open")
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
        # Hard floor: never process documents before the configured start date
        # (You already has Robinhood documents from 2023 and earlier).
        floor = a.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if a.end_date and (not doc.date or doc.date > a.end_date):
            return False
        return True

    def _record_raw(self, r, tax_year: str = "") -> int:
        """Turn one scraped row into a discovery record. Returns 1 if new."""
        if doc_types.should_skip(r.title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(
            r.title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        if r.date_text:
            date, period = site.parse_period_date(r.date_text)
        elif tax_year:
            # Tax-table rows carry no date; file them at the tax year end.
            date, period = f"{tax_year}-12-31", f"Tax Year {tax_year}"
        else:
            date, period = site.parse_period_date(r.text or r.title)
        # Keep the account in the summary so files stay distinguishable
        # (several accounts produce the same form in the same year).
        acct = (r.account or "").strip()
        full_summary = f"{summary} {acct}".strip() if acct else summary
        doc = Document(title=r.title, category=category, summary=full_summary,
                       date=date or "", period=period, href=r.href,
                       row_index=r.row_index, confidence=confidence,
                       date_text=getattr(r, "date_text", ""))
        doc.account = acct
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        self.discovery.update(doc.key, {"row_index": r.row_index,
                                        "href": r.href}, save=False)
        return 0

    def _record_rawdoc(self, r, source_url: str) -> int:
        """Record one scraped document (a RawDoc) from a Robinhood page.
        Returns 1 if new."""
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
        tax_year = (getattr(r, "tax_year", "") or "").strip()
        date = (r.date_text or "").strip()
        if tax_year and source_url != site.TAX_URL:
            # Only the tax page dates a form by what surrounds it. Anywhere
            # else the years around it are statement years.
            tax_year = date = ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date, _ = site.parse_period_date(title)
            date = date or ""
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        # The crypto address can show another account's list. A crypto page
        # document with the title and date of one the individual page listed
        # in this run is that list, or a statement named exactly like it, and
        # either way saving it would save the individual statement twice. It
        # is refused, and the run says so (#62).
        if self._individual_listed is not None:
            if source_url == site.STATEMENT_URLS[0]:
                self._individual_listed.add((title, date))
            elif site.account_for(source_url) and (title, date) in self._individual_listed:
                self.stats["crypto_refused"] = self.stats.get("crypto_refused", 0) + 1
                log.warning("refused %r from the %s page, the individual page lists "
                            "it too", title, site.account_for(source_url))
                return 0
        # A statement belongs to the account whose page lists it. A crypto
        # statement and an individual one of the same month can carry the
        # same title, and without the account they were one key, so the
        # second was taken as done and its page could be pressed for the
        # first (#62). The individual page gives no account, so every key
        # and name saved before stays as it was. Anything else a statements
        # page lists is the tax page's own document and keeps that key.
        account = site.account_for(source_url) if category == doc_types.STATEMENT else ""
        if account and account.lower() not in summary.lower():
            summary = f"{account} {summary}"
        doc = Document(title=title, category=category, summary=summary,
                       date=date, confidence=confidence, source_url=source_url,
                       account=account, tax_year=tax_year,
                       period=f"Tax Year {tax_year}" if tax_year else "")
        if self._listed_now is not None:
            self._listed_now.add(doc.key)
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            if account:
                self._adopt_legacy(doc)
            return 1
        # refresh which page the doc's download link lives on
        self.discovery.update(doc.key, {"source_url": source_url}, save=False)
        return 0

    @staticmethod
    def _legacy_key(doc: Document) -> str:
        """The key a statement of an account page had before the account
        was part of it, when the crypto page was read before and its
        statements were keyed like the individual ones."""
        return Document.from_dict(dict(doc.to_dict(), account="")).key

    def _legacy_record(self, doc: Document) -> Optional[dict]:
        """The record a statement was saved under before its account was in
        its key, or None. Only one that was saved from this account's own
        page, since the same key is also an individual statement's."""
        if not doc.account:
            return None
        rec = self.progress.get(self._legacy_key(doc))
        if isinstance(rec, dict) and site.account_for(rec.get("source_url", "")) == doc.account:
            return rec
        return None

    def _adopt_legacy(self, doc: Document) -> None:
        """Move a crypto statement saved under its old key to its new one.

        Only a finished record saved from the crypto page itself, and only
        when nothing holds the new key. Its discovery entry goes with it
        when that entry is the crypto page's too, or the next run would
        press the crypto page for it under the old key and save it twice."""
        rec = self._legacy_record(doc)
        if rec is None or not is_done(rec) or self.progress.get(doc.key) is not None:
            return
        old = self._legacy_key(doc)
        moved = dict(rec, account=doc.account, summary=doc.summary, legacy_key=old)
        del self.progress.data[old]
        self.progress.update(doc.key, moved, save=False)
        self.progress.save(backup=True)
        listed = self.discovery.data.get(old)
        if isinstance(listed, dict) and listed.get("source_url") == doc.source_url:
            self.discovery.data.pop(old, None)
        self.discovery.update(doc.key, {"state": moved.get("state", "")}, save=False)
        log.info("a %s statement saved under its old key is kept under its new one",
                 doc.account)

    def _note(self, text: str) -> None:
        """Something the run did not do, said in the log, on screen and in
        the run summary, never silently."""
        log.warning(text)
        print("  !! " + text)
        self.stats.setdefault("notes", []).append(text)

    def cmd_discover(self, quiet: bool = False) -> int:
        page = self.page()
        n_new = 0
        self._listed_now = set()
        self._individual_listed = set()
        individual_read = False
        # Robinhood lists documents as click-to-download <a download> links on
        # per-section pages (Individual statements, Crypto statements, Tax
        # center). Scan each page and scrape its download links.
        for url, label in site.document_source_urls():
            account = site.account_for(url)
            if account and not individual_read:
                self._note(f"The {label} page was not read, because the individual "
                           "statements it is checked against were not read in this run.")
                continue
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
            except Exception as e:
                log.info("could not open %s: %s", url, e)
                continue
            # Signing in again at a console leaves the page on the first
            # documents page, not this section, and its links would be
            # recorded as this section's. So the section is opened again for
            # as long as the check had to ask, which also asks again when
            # the person answered before they had signed in.
            while self.check_session(page):
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
            # An account page is read only where it was asked for. Checked
            # before anything is pressed and again before the list is read.
            if account and not site.at_address(page.url, url):
                self._note(f"The {label} page opened another address and was not read.")
                continue
            # Robinhood paginates statements behind a "View More" button; click
            # it (and any lazy-load) until the full list is present.
            site.expand_all(page)
            site.scroll_full_page(page, rounds=6)
            site.expand_all(page)
            if account and not site.at_address(page.url, url):
                self._note(f"The {label} page moved to another address and was not read.")
                continue
            docs = site.collect_download_docs(page, tax_page=(url == site.TAX_URL))
            before = n_new
            for r in docs:
                n_new += self._record_rawdoc(r, url)
            self.discovery.save()
            log.info("%s (%s): %d download links, %d new", label, url,
                     len(docs), n_new - before)
            if url == site.STATEMENT_URLS[0]:
                individual_read = True
            self._delay(0.4)

        refused = self.stats.get("crypto_refused", 0)
        if refused:
            # Counted as refused documents too, so the panel says the run
            # needs attention rather than that it was clean.
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + refused
            self._note(f"{refused} document(s) on the crypto statements page were not "
                       "read, because each has the title and date of one on the "
                       "individual page. That is the page showing the individual "
                       "account's list, or crypto statements named exactly like "
                       "individual ones. Nothing was saved for them.")
        self._individual_listed = None

        moved = self._date_saved_forms(self._listed_now)
        if moved:
            print(f"  {moved} tax form(s) saved without a date now have the date "
                  "their page shows. Rename gives their files that date.")
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
        if not rec and doc.category == doc_types.TAX and not doc.date:
            # A form saved without a date and dated since is kept under its
            # dated key. A page that lists it without a year again is still
            # listing that form.
            rec = next((r for r in self.progress.data.values()
                        if isinstance(r, dict) and r.get("undated_key") == doc.key), None)
        if not rec:
            # A crypto statement saved when the crypto page was read before,
            # keyed as an individual one. Only a record saved from that page.
            rec = self._legacy_record(doc)
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

    def _date_saved_forms(self, listed_now: Optional[set] = None) -> int:
        """Move a tax form saved without a date to the key its page now
        dates it by (#62). Returns how many moved.

        Before the page's year was read, a form whose title named no year
        was saved as 0000-00-00 under a key with no date. The page now
        gives that form a date and so a new key, and without this the form
        would be fetched a second time beside the file already saved.

        Only when it is certain which listed form the saved one is. The
        year printed in the saved file says so when it can be read. Without
        it, the one form of that title whose tax year had ended when the
        saved one was first listed, because a form cannot be listed before
        its year is over. Anything less certain moves nothing, and a second
        copy is the worst that follows, never a form marked done that was
        not saved.

        The record moves, it is not copied, so it is counted once. The key
        it came from goes with it, for _already_done. The ledger row keeps
        its empty date until Rename, which reads the date from here, so the
        file and its row change together.

        `listed_now` is every key this discovery listed. A form of a title
        the page now dates, listed before without a date and never saved,
        is that old reading of the same page. It is taken off the list, or
        the next run presses the first control of that title, whatever its
        year, and saves it again as 0000-00-00."""
        listed = {}
        for key, rec in (self.discovery.data or {}).items():
            if (isinstance(rec, dict) and rec.get("category") == doc_types.TAX
                    and rec.get("date")
                    and (listed_now is None or key in listed_now)):
                listed.setdefault((rec.get("title", ""), rec.get("account", "")),
                                  []).append((key, rec))
        dropped = 0
        if listed_now is not None:
            for key, rec in list((self.discovery.data or {}).items()):
                if (isinstance(rec, dict) and rec.get("category") == doc_types.TAX
                        and not rec.get("date") and key not in listed_now
                        and (rec.get("title", ""), rec.get("account", "")) in listed
                        and not is_done(self.progress.get(key) or {})):
                    self.discovery.data.pop(key, None)
                    log.info("a tax form listed before without a date is listed "
                             "by its year now")
                    dropped += 1
        moved = 0
        for key, rec in list((self.progress.data or {}).items()):
            if (not isinstance(rec, dict) or rec.get("category") != doc_types.TAX
                    or rec.get("date") or not is_done(rec)):
                continue
            found = self._which_listed_form(
                rec, listed.get((rec.get("title", ""), rec.get("account", "")), []))
            if found is None:
                continue
            new_key, listed_rec = found
            if self.progress.get(new_key) is not None:
                continue
            moved_rec = dict(rec)
            moved_rec.update(date=listed_rec["date"],
                             period=listed_rec.get("period") or rec.get("period", ""),
                             tax_year=listed_rec.get("tax_year", ""),
                             source_url=listed_rec.get("source_url") or rec.get("source_url", ""),
                             undated_key=key)
            del self.progress.data[key]
            self.progress.update(new_key, moved_rec, save=False)
            self.discovery.data.pop(key, None)
            self.discovery.update(new_key, {"state": moved_rec.get("state", ""),
                                            "undated_key": key}, save=False)
            log.info("a tax form saved without a date is the one listed for %s",
                     listed_rec["date"])
            moved += 1
        if moved:
            self.progress.save(backup=True)
        if moved or dropped:
            self.discovery.save()
        return moved

    @staticmethod
    def _which_listed_form(rec: dict, listed: list):
        """(key, record) of the listed form a saved undated one is, or None.

        Only by the year printed in the saved file itself. When it was
        listed or saved says nothing about which year's form it is, since a
        form comes out in the year after its own, so a file that is gone or
        prints no clear year moves nowhere."""
        path = (rec.get("pdf_path") or "").strip()
        if not listed or not path or not Path(path).exists():
            return None
        year = site.printed_tax_year(receipt_pdf.pdf_text(Path(path)))
        same = [x for x in listed if year and x[1]["date"] == f"{year}-12-31"]
        return same[0] if len(same) == 1 else None

    # -- processing --------------------------------------------------------

    def process(self, docs: List[Document], dry_run: bool = False):
        page = self.page()
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
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
                self.download_one(page, doc, filename)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress saved; run --resume to continue.")
                raise
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    def download_one(self, page, doc: Document, filename: str):
        """Download one document PDF by navigating to the page that holds its
        download link and clicking it (Robinhood fires a real download event)."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # The last of the document id, used only if the name is taken.
        # Two documents on one day used to differ by " (2)", which says
        # nothing about which is which and moves between them when a file
        # is deleted (#49, and the same complaint on #43).
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        # Go to the section page that holds this document's download link, then
        # click the link matching its title.
        source = doc.source_url or site.STATEMENT_URLS[0]
        try:
            page.goto(source, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            # Signing in again at a console leaves the page on the first
            # documents page, and this document was looked for by its title
            # there. So its own section is opened again for as long as the
            # check had to ask.
            while self.check_session(page):
                page.goto(source, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            # Older statements are hidden behind "View More" pagination, so the
            # list must be fully expanded before the control can be found.
            site.expand_all(page)
            site.scroll_full_page(page, rounds=6)
            site.expand_all(page)
        except Exception as e:
            log.info("could not open source page %s: %s", source, e)
        # A tax form lands beside its place first, and is put in place only
        # once the year it prints has been read against what it was listed as.
        target = out_path
        if doc.category == doc_types.TAX:
            out_path = target.with_name(target.name + ".delivering")
            _clear(out_path)
        saved = site.download_named(page, doc.title, out_path,
                                    year=getattr(doc, "tax_year", "") or "")
        if not saved:
            _clear(out_path if out_path != target else None)
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

        doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
        self._record(doc, State.PDF_SAVED)

        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"])
        if not result.ok:
            self.stats["validation_failures"] += 1
            quarantine = unique_path(self.paths.manual_review, target.name,
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

        # A form set with more than one file arrives here as a ZIP, and the
        # extraction above is what unpacks it. A second mechanism for that
        # used to be written out below, walking a list of extra links, and it
        # never ran once: the list was created empty and nothing ever put a
        # link in it. Removed rather than left looking like a feature.
        if doc.category == doc_types.TAX:
            out_path = self._settle_tax_form(doc, out_path, target)
            if out_path is None:
                return
            doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
        doc.pdf_size, doc.pdf_pages = result.size_bytes, result.page_count
        doc.downloaded_ok = True   # done for good, even if the file is deleted later
        self._record(doc, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self._write_row(doc, "Downloaded", "Completed")
        self.stats["new_files"].append(str(out_path))
        if doc.date or doc.printed_date:
            self.stats["dates"].append(doc.date or doc.printed_date)
        if doc.category == doc_types.TAX:
            self.stats["tax_documents"] += 1
        elif doc.category == doc_types.INSURANCE:
            self.stats["insurance_documents"] += 1
        elif doc.category == doc_types.STATEMENT:
            self.stats["statements"] += 1
        else:
            self.stats["other"] += 1
        print(f"  Saved: {out_path.name}")

    def _settle_tax_form(self, doc: Document, path: Path, target: Path) -> Optional[Path]:
        """Put a tax form in place once the year it prints has been read, or
        say why it was not, and return where it is, or None (#62).

        A form the page dated that prints another year goes to Manual
        Review and neither year is recorded as done, since one of the two
        readings is wrong and nothing says which. A form the page gave no
        year is named for the year it prints. If a form of that title and
        that year is saved already, this is a second copy of it and is not
        kept, and the listing is remembered as that form. A form that
        prints no clear year keeps the name it was saved under."""
        year = site.printed_tax_year(receipt_pdf.pdf_text(path))
        listed = doc.date[:4] if doc.date.endswith("-12-31") else ""
        final = target
        if doc.date:
            if listed and year and year != listed:
                self._refuse_other_year(doc, path, target, listed, year)
                return None
        elif year:
            twin = self._saved_form_of_year(doc, year)
            if twin is not None:
                key, rec = twin
                _clear(path)
                # The listing is that form. Nothing of its own is kept, not
                # even the note that a file was on its way.
                self.progress.data.pop(doc.key, None)
                self.progress.update(key, {"undated_key": doc.key})
                self.stats["skipped_completed"] += 1
                print(f"  Already saved as {rec.get('pdf_filename') or 'a form of that year'}"
                      " - this copy was not kept.")
                return None
            doc.printed_date = f"{year}-12-31"
            doc.period = doc.period or f"Tax Year {year}"
            final = unique_path(target.parent,
                                build_pdf_filename(doc.printed_date, doc.summary, "", record=doc),
                                self.config["max_path_length"], ignoring=path.name)
        else:
            log.info("no tax year could be read from %s", target.name)
        if path == final:
            return final
        try:
            path.replace(final)
        except OSError as e:
            # The row still carries the date, so Rename can finish this.
            log.info("could not put %s in place: %s", final.name, e)
            return path
        return final

    def _saved_form_of_year(self, doc: Document, year: str):
        """(key, record) of a saved form of this title and tax year, or None.
        Not one whose own file prints another year."""
        want = f"{year}-12-31"
        for key, rec in (self.progress.data or {}).items():
            if (not isinstance(rec, dict) or rec.get("category") != doc_types.TAX
                    or rec.get("date") != want or not is_done(rec)
                    or (rec.get("title") or "") != doc.title
                    or (rec.get("account") or "") != (doc.account or "")):
                continue
            own = (rec.get("pdf_path") or "").strip()
            if own and Path(own).exists():
                printed = site.printed_tax_year(receipt_pdf.pdf_text(Path(own)))
                if printed and printed != year:
                    continue
            return key, rec
        return None

    def _refuse_other_year(self, doc: Document, path: Path, target: Path,
                           listed: str, printed: str) -> None:
        """A form listed for one tax year that prints another goes to Manual
        Review. The record keeps no path, so the copy there never counts as
        done, and the next run asks for it again."""
        quarantine = unique_path(self.paths.manual_review, target.name,
                                 self.config["max_path_length"])
        try:
            path.replace(quarantine)
        except OSError as e:
            log.info("could not move %s to manual review: %s", target.name, e)
            _clear(path)
            quarantine = None
        said = (f"Listed for tax year {listed}, and the form prints {printed}. Moved "
                "to Manual Review, and neither year is recorded as done.")
        doc.notes = (doc.notes + "; " if doc.notes else "") + said
        doc.pdf_path = str(quarantine) if quarantine else ""
        doc.pdf_filename = quarantine.name if quarantine else ""
        self._write_row(doc, "Prints another tax year", "Needs Manual Review")
        doc.pdf_path = doc.pdf_filename = ""
        self._record(doc, State.NEEDS_MANUAL_REVIEW)
        self.write_failure('check the saved tax form', 'the form prints another tax year')
        self.stats["manual_review"] += 1
        self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        print("  !! " + said)

    # -- records -----------------------------------------------------------

    def _record(self, doc: Document, state: State, notes: str = ""):
        doc.state = state.value
        if notes:
            doc.notes = (doc.notes + "; " if doc.notes else "") + notes
        self.progress.update(doc.key, doc.to_dict())
        self.discovery.update(doc.key, {"state": state.value})

    def _write_row(self, doc: Document, status: str, processing: str):
        notes = "; ".join(x for x in (doc.notes, status) if x)
        self.index_csv.append_rows([{
            "Account Holder": self.config.get("owner", ""),
            # The date the file is named for, which is what Rename reads.
            "Document Date": doc.date or doc.printed_date,
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
            print(f"This downloads ALL available Robinhood documents ({scope}).")
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
        docs = [d for d in self._select() if not self._already_done(d)]
        if not docs:
            print("Nothing to resume - everything in scope is complete.")
            return
        print(f"Resuming: {len(docs)} document(s) remaining.")
        self.process(docs, dry_run=self.args.dry_run)


    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.

        A naming scheme improves and the files on disk keep the old one.
        Nothing about them needs fetching, only their names are wrong, so
        nothing is asked of the provider here (#43, #49). A preview
        unless --apply is given.

        A tax form saved as 0000-00-00 is dated here, from the form it was
        found to be or the year it prints, so it takes that name (#62)."""
        self.stats["mode"] = "rename"
        renaming.run_for(_DatedTaxForms(self),
                         apply_changes=bool(getattr(self.args, "apply", False)))

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
                      postmortem: dict = None) -> None:
        """What the page looked like when this went wrong, to a file.

        Written without anybody having to know to ask for it, because a
        tester who has to be told to run a second command is a tester who
        sends one file and waits a day for the request for the other.

        One per run. A run where thirty documents fail for one reason
        does not need thirty files, and the first is taken while the page
        is still sitting on the thing that broke."""
        if self.stats.get("failure_files"):
            return
        extra = {"postmortem": postmortem} if postmortem else None
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
            provider='Robinhood', text=text, extra=extra)
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

    def write_survey(self) -> None:
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
            provider='Robinhood')

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        page = self.page()
        info = {"timestamp": now_iso()}
        try:
            found = site.goto_documents(page)
            info["documents_page_found"] = found
            info["url"] = page.url
            info["title"] = page.title()
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
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
            docs = site.collect_documents(page)
            info["collected"] = len(docs)
            info["samples"] = []
            for d in docs[:8]:
                cat, summ, conf = doc_types.classify_document(d.title, self.rules)
                date, period = site.parse_period_date(d.text or d.title)
                info["samples"].append({
                    "title": d.title[:90], "href": (d.href or "")[:100],
                    "text": (d.text or "").replace("\n", " | ")[:160],
                    "category": cat, "summary": summ, "date": date, "period": period})
            controls = []
            for role in ("button", "link"):
                loc = page.get_by_role(role)
                for i in range(min(loc.count(), 60)):
                    try:
                        t = (loc.nth(i).inner_text(timeout=400) or "").strip()[:60]
                    except Exception:
                        t = ""
                    if t:
                        controls.append({"role": role, "text": t,
                                         "safe": site.is_safe_control(t)})
            info["controls"] = controls
            page.screenshot(path=str(self.paths.diagnostics / "diagnose-documents.png"),
                            full_page=True)
        except Exception as e:
            info["error"] = str(e)
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words_for('Robinhood', site))
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print("  The screenshot beside it shows the page as it is, so it stays")
        print("  on this machine.")
        print(f"Rows collected: {info.get('collected', '?')}")
        for s in info.get("samples", [])[:5]:
            print(f"  [{s['category']}] {s['date']}  {s['summary']}  <- {s['title'][:50]}")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Robinhood',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Robinhood Documents - run summary",
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
            f"Refused as the wrong one:  {s.get('wrong_document', 0)}",
            f"Crypto listings refused:   {s.get('crypto_refused', 0)}",
            f"Earliest date processed:   {dates[0] if dates else '-'}",
            f"Latest date processed:     {dates[-1] if dates else '-'}",
            "",
        ] + [f"Not done: {note}" for note in s.get("notes", [])]
            + ([""] if s.get("notes") else [])))
        # A plain list of exactly the files downloaded THIS run (all new,
        # since already-downloaded documents are skipped). Handy for knowing
        # what to import into paperless-ngx, and safe to ignore/delete.
        atomic_write_text(
            self.paths.root / "new-this-run.txt",
            f"# {len(new_files)} file(s) downloaded on this run "
            f"({s['ended']}):\n" + "\n".join(sorted(new_files)) + "\n")
        if new_files:
            print(f"\n{len(new_files)} NEW file(s) downloaded this run "
                  f"(listed in new-this-run.txt).")
        report_run_result(s)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Local supervised Robinhood document downloader (read-only)")
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
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
        return 130
    finally:
        app.progress.save()
        app.discovery.save()
        # A run that only looked at the page writes no summary. The
        # summary rewrites new-this-run.txt, and for a mode that
        # downloads nothing that means replacing the real list from
        # the last download run with an empty one.
        if app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
