"""American Express Banking statement downloader (local, supervised).
Covers deposit accounts, Business Checking, Personal Checking and Savings.

Usage:
    python amexbanking_docs.py --login       verify connection to your browser
    python amexbanking_docs.py --discover    list available documents
    python amexbanking_docs.py --pilot       download the 5 newest, then stop
    python amexbanking_docs.py --all         download everything in scope
    python amexbanking_docs.py --resume      continue an interrupted run
    python amexbanking_docs.py --verify      re-validate every saved PDF
    python amexbanking_docs.py --diagnose    dump page structure (no downloads)
    python amexbanking_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement|"Tax Document"

READ-ONLY. This tool only reads the Documents area and downloads PDFs that
American Express already generated. It never transfers funds, pays bills,
moves money, or changes any account setting. Everything stays on this
machine, and nothing is sent to any external service.
"""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import (NEW_LIST_NOTE, NOTHING_OPENED, NOTHING_RECORDED,
                                          after_sign_in, lists_what_it_saved, not_signed_in,
                                          report_run_result)

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
import amexbanking_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import shape_label, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("amexbanking_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One American Express Banking document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", occurrence=0, ambiguous=False,
                 account_token="", **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text
        # The id American Express gives the document, which its PDF is asked
        # for by, and the token of the account whose list named it.
        self.document_id = document_id
        self.account_token = account_token
        self.occurrence = occurrence
        self.ambiguous = ambiguous
        # Sticky "was successfully downloaded at least once" marker. Once set,
        # the document is never re-downloaded even if you delete the PDF.
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
        if self.document_id:
            return f"id:{self.document_id}"
        acct = _account_component(sanitize_component(self.account or ""))
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


def migrate_legacy_keys(records: dict) -> int:
    return _migrate_account_keys(records, lambda r: Document.from_dict(r).key)


class App:
    _journal = None
    _requests = None
    # Set when a part of the list was not read, so the run goes on with what
    # it read and stops at its end rather than finish (_stop_if_cut_short).
    _list_cut_short = False
    # Set when all that kept the list from being whole is a list that
    # answered with no documents, which a new account shows.
    _only_short_lists = False

    def __init__(self, args):
        self.args = args
        # --config lets one copy of the code serve several accounts. Each
        # config points at its own output_dir, profile_dir and port.
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
        # The account this run is on is read from the page each time, once
        # its list has answered. The first record discovered is not used,
        # since after a switch it names another account. A name set in the
        # config is this config's one account's.
        configured_account = self.config.get("account_name")
        if configured_account:
            site.SESSION.account_label = configured_account
            site.SESSION.label_configured = True
        self.index_csv = CsvFile(self.paths.document_index_csv,
                                 DOCUMENT_INDEX_COLUMNS, self.paths.backups, once=True)
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
                raise not_signed_in(cdp_url, e)
            if not self._browser.contexts:
                raise SystemExit("Connected browser has no context; open a tab and retry.")
            self._context = self._browser.contexts[0]
            self._cdp_mode = True
        else:
            profile = Path(self.config["profile_dir"])
            profile.mkdir(parents=True, exist_ok=True)
            self._context = browser_launcher.launch_own_browser(
                self._pw.chromium, str(profile), headless=False, accept_downloads=True,
                viewport={"width": 1400, "height": 950})
            self._cdp_mode = False
        self._context.set_default_timeout(30000)
        return self._context

    def page(self):
        ctx = self.browser()
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        if self._cdp_mode:
            # Reuse the person's own tab on American Express, the page they
            # left open for this. With none open, a tab of this run's own is
            # opened, never a tab of another site, since the session is a
            # cookie a new tab shares (tabs.new_tab). Matched on the parsed
            # host, never a substring.
            live = [p for p in ctx.pages if not p.is_closed()]
            amex_pages = [p for p in live if site.is_safe_url(p.url or "")]
            doc_pages = [p for p in amex_pages if site.on_documents_page(p)]
            self._work_page = doc_pages[0] if doc_pages else (amex_pages[0] if amex_pages else tabs.new_tab(ctx))
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.requests
        return self._work_page

    def close(self):
        try:
            if self._cdp_mode:
                pass  # never close the user's own signed-in tab
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
        # Under the panel there is nobody to answer a prompt, so when there
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
            print("\n!! American Express appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)

    def session_ended(self) -> None:
        """Stop the run because American Express answered as signed out.
        Progress is saved, nothing is recorded for review, and the run ends
        as one that stopped (tabs.stop)."""
        tabs.stop(self, [
            "American Express answered as signed out, so this run stops here.",
            "Sign in again in the open browser window, then press Resume to carry on.",
        ])

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile."""
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9307")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
                                                    prefer_real=True,
                                                    mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print(f"Sign in, open your account's Statements, keep the window OPEN, then {after_sign_in()}.")

    def cmd_login(self):
        print("Checking the connection to your signed-in American Express browser...\n")
        page = self.page()
        ok = site.ensure_statements(page)
        challenge = site.detect_security_challenge(page)
        # The page's address says nothing of the session. The documents list
        # the page asks for answering does.
        listed = bool(ok and not challenge and site.answers_its_list(page))
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but American Express shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif listed:
            print("Success: connected, and American Express answers with your documents list.")
            print("Keep that browser window OPEN, then run the diagnostics or pilot.")
        else:
            print("Connected, but the Documents and Statements list did not answer, so this")
            print("cannot say whether you are signed in. Look at the browser window and")
            print("answer anything American Express asks there yourself, open your")
            print("account's Statements, then run Login again.")
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

    def _record_discover_doc(self, d: site.RawDoc) -> int:
        """Record one listed document. Returns 1 if new."""
        title = d.title or "Statement"
        date = (d.date_text or "").strip()
        account = re.sub(r"\s+", " ", (d.account or "")).strip()
        doc_id = d.document_id

        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if category == doc_types.OTHER and re.search(r"statement", title, re.I):
            category = doc_types.STATEMENT
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0

        doc = Document(title=title, category=category, summary=summary,
                       date=date, href=d.href or "", confidence=confidence,
                       account=account, date_text=date, document_id=doc_id,
                       account_token=d.account_token)
        existing = self.discovery.get(doc.key)
        if existing is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        if (existing.get("account_token") != doc.account_token
                or existing.get("account") != doc.account):
            # The same document named again, with the token its list was
            # asked with this time, which is the one its PDF is asked with.
            existing["account_token"] = doc.account_token
            existing["account"] = doc.account
            self.discovery.update(doc.key, existing, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False, finish: bool = True) -> int:
        # A list read only in part (passed_over) keeps the documents it
        # found, and Pilot and Run All go on with them, but the run stops at
        # its end rather than finish. With finish=False the caller does that
        # once it has used them. A listing that stops on the way, however it
        # stops, is noted as one that stopped (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        if not site.ensure_statements(page):
            self.check_session(page)
            if not site.ensure_statements(page):
                print("Could not open your American Express Documents and Statements list.")
                print("Sign in, open your account's Statements, then try again.")
                # Nothing was listed, so this run stops here rather than
                # finish clean (paperpull_core.listing).
                raise SystemExit(0)
        self.check_session(page)

        raw = None
        try:
            raw = site.collect_documents(page)
        except site.SessionExpired:
            self.session_ended()
        if raw is None:
            print("American Express's Documents and Statements page is open, but its list")
            print("did not answer, so nothing was downloaded. Sign in, open Statements,")
            print("and try again. If it keeps happening, run Diagnose and attach the file")
            print("it writes to an issue.")
            self.write_failure("read the documents list", "the documents list did not answer")
            raise SystemExit(0)
        log.info("American Express Banking: %d document(s) read from the list", len(raw))
        passed_over = list(raw.passed_over)
        if passed_over:
            # A part of the list that did not answer, a document that could
            # not be read, or lists of more than one account, is a part of
            # the list missing, so the list is not noted whole, and the run
            # goes on with what it read and stops at its end.
            self._list_cut_short = True
            self._only_short_lists = not set(passed_over) - {site.EMPTY_LIST}
            log.info("American Express Banking: the list was not read through the %s",
                     " and the ".join(passed_over))
            print("\n  American Express Banking's documents list was not read whole.")
            if site.EMPTY_LIST in passed_over:
                print("  The list answered with no documents, which a new account does and a")
                print("  list that did not load can too, so it is not noted as read whole.")
            if site.SEVERAL_ACCOUNTS in passed_over:
                print("  The page asked for the lists of more than one account, which this app")
                print("  cannot tell apart, so none of them was taken. Please say so on the")
                print("  American Express Banking issue on GitHub.")
            if not self._only_short_lists:
                print("  A part of the list or a document on it could not be read.")
                print("  What was read is kept, and this run stops at its end rather than finish.")
                print("  Pilot or Run All reads the list again.")
                self.write_failure("read the documents list", "some of the list could not be read")
        n_new = 0
        for d in raw:
            n_new += self._record_discover_doc(d)

        self.discovery.save()
        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing). A list read
        # in part is not, and the listing stays one that stopped.
        if not self._list_cut_short:
            listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)

        if not quiet:
            docs = [Document.from_dict(v) for v in self.discovery.data.values()]
            print("\nDiscovery %s. Documents known: %d"
                  % ("read part of the documents list" if self._list_cut_short else "complete",
                     len(docs)))
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
        if finish:
            self._stop_if_cut_short()
        return n_new

    def _stop_if_cut_short(self) -> None:
        """A run that did not read the whole documents list did not finish,
        and must not read as a clean one. Once it has used what came, it
        leaves on SystemExit the way a run leaves on a sign-out, which the
        panel reports as a run that stopped."""
        if self._list_cut_short and not self._only_short_lists:
            # A list that answered empty alone stops nothing. A run stopped
            # for it would stop on every run of a new account.
            print("\nNot all of American Express Banking's documents list was read, so this")
            print("run stops here rather than finish. Everything it saved is kept.")
            print("Run it again later to read the rest.")
            raise SystemExit(0)

    def _select(self, limit: Optional[int] = None) -> List[Document]:
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        docs = [d for d in docs if self._in_scope(d)]
        docs.sort(key=lambda d: d.date or "0000", reverse=True)
        limit = limit if limit is not None else self.args.max_docs
        return docs[:limit] if limit else docs

    def _already_done(self, doc: Document) -> bool:
        """Skip documents already handled. A document that was successfully
        downloaded once is done FOR GOOD, and is not downloaded again even if
        you later delete the PDF. Use --redownload to override."""
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(doc.key)
        if not rec:
            return False
        if rec.get("downloaded_ok"):
            return True
        state = rec.get("state")
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        # A review copy counts only if its PDF is still present and valid,
        # and a failed one is tried again.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on American Express's own
        site and never a tab of another site. The session is a cookie a new
        tab shares, so with no tab of the person's on the site the documents
        page is opened in a tab of this run's own (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "American Express Banking",
                                self._open_documents)

    def _open_documents(self, page):
        """Documents and Statements, opened by its address the way discovery
        opens it."""
        if not site.ensure_statements(page):
            self.check_session(page)
            site.ensure_statements(page)

    def process(self, docs: List[Document], dry_run: bool = False):
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
                page = self._on_its_site()
                self.download_one(page, doc, filename)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress saved; run --resume to continue.")
                raise
            except site.SessionExpired:
                # American Express answered a document as a signed-out
                # session. Every document after it would get the same, so the
                # run stops here, with nothing recorded against this one.
                self.session_ended()
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    def download_one(self, page, doc: Document, filename: str):
        """Download one document's PDF straight to its final path, asked for
        by the document's own id and its own account's token, never by its
        place in the list."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # The last of the document id, used only if the name is taken.
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        raw_doc = site.RawDoc(
            title=doc.title, date_text=doc.date, href=doc.href,
            category=doc.category, tag=doc.document_id, document_id=doc.document_id,
            account=doc.account, account_token=doc.account_token)
        saved = site.amexbanking_download(page, raw_doc, out_path)
        if not saved:
            # Nothing was saved, so nothing is in Manual Review. A failure,
            # which the next run tries again (#152).
            self._record(doc, State.FAILED,
                         notes="Could not capture the document PDF (see the log)")
            self._write_row(doc, "Capture failed", State.FAILED.value)
            self.write_failure('capture the document', 'the document would not render')
            self.stats["failed"] += 1
            print("  Could not capture this document. Nothing was saved, and the next run tries it again.")
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
        if doc.category == doc_types.TAX:
            self.stats["tax_documents"] += 1
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
        self.cmd_discover(finish=False)
        docs = self._select(limit=self.config.get("pilot_count", 5))
        if not docs:
            print("\nNo documents in scope to pilot. Run --diagnose.")
            self._stop_if_cut_short()
            return
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)
        self._pilot_report(docs)
        self._stop_if_cut_short()

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
            print(f"This downloads ALL available American Express Banking documents ({scope}).")
            print("Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover(finish=False)
        docs = self._select()
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)
        self._stop_if_cut_short()

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
        A preview unless --apply is given."""
        self.stats["mode"] = "rename"
        renaming.run_for(self, apply_changes=bool(getattr(self.args, "apply", False)))

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
        Made on first use like the journal, and started at once, because it
        only sees what arrives after it starts listening."""
        if self._requests is None:
            self._requests = Requests(getattr(self, "_work_page", None),
                                      getattr(site, "is_safe_url", None))
            self._requests.start()
        return self._requests

    @property
    def journal(self):
        """The run's journal, made the first time anything writes to it."""
        if self._journal is None:
            self._journal = Journal(getattr(self, "_work_page", None),
                                    getattr(site, "FALLBACK", None))
        return self._journal

    def write_failure(self, step: str, reason: str, text: str = "",
                      postmortem: dict = None) -> None:
        """What the page looked like when this went wrong, to a file. One per
        run, taken while the page still shows what broke."""
        if self.stats.get("failure_files"):
            return
        extra = {"postmortem": postmortem} if postmortem else None
        # A checkpoint at the moment it gave up, which also makes the journal
        # when nothing had written to it yet.
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
            provider='American Express Banking', text=text, extra=extra)
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
        """The survey Diagnose is safe to send, written beside the detailed
        file on the same list of what may leave that the failure file uses."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='American Express Banking')

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = words_for('American Express Banking', site)
        page = self.page()
        info = {"timestamp": now_iso()}
        try:
            info["documents_page_found"] = site.ensure_statements(page)
            info["url"] = page.url
            info["title"] = page.title()
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            info["list_answers"] = [{"status": a.status, "token": bool(a.token),
                                     "statements": len(a.data.get("statements") or [])
                                     if isinstance(a.data, dict)
                                     and isinstance(a.data.get("statements"), list) else None}
                                    for a in site.SESSION.answers]
            controls = []
            for role in ("tab", "button", "link"):
                loc = page.get_by_role(role)
                for i in range(min(loc.count(), 40)):
                    try:
                        t = (loc.nth(i).inner_text(timeout=400) or "").strip()[:60]
                        if t and not site._forbidden(t):
                            controls.append({"role": role, "text": t, "safe": site.is_safe_control(t)})
                    except Exception:
                        pass
            info["controls"] = controls

            docs = site.collect_documents(page)
            info["collected"] = len(docs) if docs is not None else None
            info["passed_over"] = list(docs.passed_over) if docs is not None else []
            info["samples"] = [
                {"title": d.title, "date": d.date_text, "category": d.category}
                for d in (docs or [])[:8]
            ]
        except site.SessionExpired:
            info["signed_out"] = True
        except Exception as e:
            info["error"] = str(e)

        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print(f"Documents collected: {shape_tree(info.get('collected', '?'), words)}")
        for part in info.get("passed_over", []):
            print(f"  passed over: {shape_label(part, words)}")
        for s in info.get("samples", [])[:5]:
            print(shape_label(f"  [{s['category']}] {s['date']}  {s['title'][:50]}",
                              words, collapse=False))

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='American Express Banking',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "American Express Banking - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Tax documents downloaded:  {s['tax_documents']}",
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
        # The files saved THIS run. Not for Verify or a dry run, which save
        # nothing and leave the list as the last download run wrote it.
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
        description="American Express Banking statement downloader (read-only)")
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
    ap.add_argument("--type", help='Statement or "Tax Document"')
    ap.add_argument("--yes", action="store_true", help="skip the --all confirmation")
    ap.add_argument("--redownload", action="store_true",
                    help="re-download everything in scope, ignoring the "
                         "'already downloaded' memory (rebuilds deleted files)")
    ap.add_argument("--config", help="use an alternate config file, e.g. "
                                     "config.biz2.json (separate account)")
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
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
        return 130
    finally:
        app.progress.save(leaving=True)
        app.discovery.save(leaving=True)
        if app.stats["mode"] in ("discover", "rename"):
            # Discover and Rename download nothing, so the run summary and
            # new-this-run.txt stay as the last download run wrote them, and
            # only the panel is told how it ended (#103).
            report_run_result(app.stats)
        # A run that only looked at the page writes no summary, which would
        # replace new-this-run.txt with an empty list.
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
