"""Consorsbank document downloader, a first shell for a tester (#178).

Usage:
    python consorsbank_docs.py --open-browser  open a sign-in window of its own
    python consorsbank_docs.py --login         check the connection to that browser
    python consorsbank_docs.py --record        record your own path to a document
    python consorsbank_docs.py --diagnose      survey the open page (no downloads)

NOT BUILT YET. This first build opens Consorsbank's site for you to sign
in, and lets Record and Diagnose watch the page you leave open. Discover,
Pilot and Run All say it is not built yet and stop, Resume says nothing has
been listed yet, and nothing is listed or downloaded. A recording of one
trip to a document is what the real app is built from
(docs/testing-a-provider.md).

READ-ONLY. This build presses nothing on the bank's pages. It never pays,
transfers money, buys or sells, or changes any account setting. Everything
stays on this machine. Nothing is sent to any external service.

See the STATUS block in consorsbank_site.py for what is known.
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
                                          after_sign_in, lists_what_it_saved,
                                          not_signed_in, report_run_result)

import argparse
import logging
import random
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import doc_types, receipt_pdf, scope
from paperpull_core import browser as browser_launcher
import consorsbank_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.words import shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("consorsbank_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One Consorsbank document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", occurrence=0, **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        self.document_id = document_id
        self.occurrence = occurrence    # nth document with this title, date and account
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
        """Category, date, title and account. A Consorsbank sign-in can
        hold a current account, a depot and a card, whose documents can
        share a day, so the account is what tells one from another.
        Which id, if any, a document carries, and how two of one account
        and one day are told apart, wait on the recording, so neither is
        keyed on yet. Nothing is listed in this first build, so no key
        has been written."""
        acct = _account_component(sanitize_component(self.account or ""))
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


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
            # Reuse the person's own tab on Consorsbank's site, the page
            # they left open for this. With none open, a tab of this run's
            # own is opened, never a tab of another site (tabs.new_tab).
            # Matched on the parsed host, never a substring, since
            # "provider.com" in an address also matches
            # "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            mine = [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = mine[0] if mine else tabs.new_tab(ctx)
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
            print("\n!! Consorsbank appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)

    def not_built(self, e: Exception) -> None:
        """Say that this first build reads nothing, and stop the run as one
        that stopped, never as a clean run that found nothing. Nothing was
        asked of the bank's pages (consorsbank_site.NotBuilt)."""
        print()
        for line in textwrap.wrap(str(e) or site.NOT_BUILT, width=72):
            print(line)
        raise SystemExit(0)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in, and the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9310")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            # A bank's or a broker's sign-in is the likeliest place to
            # turn a bare Chromium away, so the person's own Edge or Chrome
            # is tried first, in a profile of its own.
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        # This first build downloads nothing, so the step after signing in
        # is a recording of one trip to a document.
        print("Sign in, keep the window OPEN, then")
        print(f"{after_sign_in(record=True)}, and click your way to one document.")

    def cmd_login(self):
        """What the browser shows, and never a claim of a session. This first
        build knows no shape of a signed-in Consorsbank page, so it can
        name a sign-in page or a check, and otherwise says it cannot tell."""
        print("Checking the connection to your Consorsbank browser...\n")
        page = self.page()
        if not site.is_safe_url(page.url or "") and tabs.is_own(page):
            # No tab of the person's was on the site, so the one this run
            # opened is sent to the sign-in page.
            site.open_sign_in(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run Login.")
        elif not site.is_safe_url(page.url or ""):
            print("Connected, but no tab is on consorsbank.de. Open it in that")
            print("window and sign in yourself, then run Login again.")
        elif site.looks_signed_out(page):
            print("Connected, and the tab shows a sign-in page. Sign in there")
            print("yourself, answer any code it sends, and keep the window OPEN.")
        else:
            print("Connected to the browser, on consorsbank.de. This first build")
            print("does not read your accounts yet, so it cannot tell whether you are")
            print("signed in. If the window shows your accounts, open the page with")
            print(f"your documents, then {after_sign_in(record=True)}, and click")
            print("your way to one.")
        self.close()

    def _in_scope(self, doc: Document) -> bool:
        a = self.args
        if not doc_types.wanted(doc.category, self.config):
            return False
        if a.type and doc.category.lower() != a.type.lower():
            return False
        if a.year and not (doc.date or "").startswith(str(a.year)):
            return False
        floor = a.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if a.end_date and (not doc.date or doc.date > a.end_date):
            return False
        return True

    def _record_document(self, d: dict) -> int:
        """Record one listed document {title, date, account}. Returns 1 if new.
        Nothing reaches here until collect_documents is built."""
        title = re.sub(r"\s+", " ", (d.get("title") or "")).strip() or "Statement"
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc = Document(title=title, category=category, summary=summary,
                       date=(d.get("date") or "").strip(), confidence=confidence,
                       account=re.sub(r"\s+", " ", (d.get("account") or "")).strip(),
                       href=d.get("href", ""))
        if self.discovery.get(doc.key) is not None:
            return 0
        rec = doc.to_dict()
        rec["state"] = State.DISCOVERED.value
        self.discovery.update(doc.key, rec, save=False)
        return 1

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        # The browser is attached as every Discover attaches it, so a run
        # with none open says to sign in first. No tab is opened, read or
        # pressed. This first build cannot read the list, so it says so and
        # stops here (consorsbank_site.NotBuilt), and the list is never noted whole.
        self.browser()
        try:
            raw = site.collect_documents(None, keep=scope.period_filter(self.args, self.config),
                                         config=self.config)
        except site.NotBuilt as e:
            self.not_built(e)
        n_new = 0
        for d in raw:
            n_new += self._record_document(d)
        self.discovery.save()
        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)
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
        # a review copy counts only if its PDF is still present and valid,
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on Consorsbank's own
        site and never a tab of another site. How the site keeps a session is
        not known yet, so no page is opened by its address, and with no tab
        of the person's on the site the run stops and says so
        (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "Consorsbank", None)

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
            except site.NotBuilt as e:
                # Every document would say the same, so the run stops here.
                self.not_built(e)
            except site.SessionExpired:
                # Already explained by download_one. Stop rather than grind
                # through the rest producing empty "manual review" entries.
                print("Stopped. Everything downloaded so far is saved.")
                # Left with the stop in flight, which is what the core
                # reports as a run that stopped. A return here finished
                # the run clean, with documents still to download.
                raise SystemExit(0)
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    def download_one(self, page, doc: Document, filename: str):
        """Download one document PDF straight to its final path. This first
        build has no way to, and site.download_document says so."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # The last of the document id, used only if the name is taken.
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1
        try:
            saved = site.download_document(page, doc.title, doc.date, out_path,
                                           occurrence=doc.occurrence,
                                           account=doc.account)
        except site.SessionExpired:
            print("\n  !! Consorsbank answered with a sign-in page instead of a document.")
            print("     Your session has expired. Sign in again in the open")
            print("     browser, then run Resume.")
            self.stats["session_expired"] = 1
            raise
        if not saved:
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
        self.cmd_discover()
        # --max-docs takes fewer, so a first try can be one document.
        limit = self.config.get("pilot_count", 5)
        if self.args.max_docs:
            limit = min(limit, self.args.max_docs)
        docs = self._select(limit=limit)
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
        # Not built, so there is nothing to ask YES for. Discover says so
        # and stops before anything is asked of the browser.
        self.cmd_discover()
        docs = self._select()
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)

    def cmd_resume(self):
        self.stats["mode"] = "resume"
        # Resume reads no list of its own. This first build never lists, so
        # with nothing listed it says so and stops as a run that stopped,
        # and Pilot then says it is not built yet (paperpull_core.listing).
        docs = [d for d in self._select() if not self._already_done(d)]
        listing.resume(self, docs, lambda left: self.process(left, dry_run=self.args.dry_run))

    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.
        Nothing is asked of the provider here (#43, #49). A preview unless
        --apply is given."""
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

        Made on first use like the journal, and started at once, because
        it only sees what arrives after it starts listening."""
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
        differently because of this."""
        if self._journal is None:
            self._journal = Journal(getattr(self, "_work_page", None),
                                    getattr(site, "FALLBACK", None))
        return self._journal

    def write_failure(self, step: str, reason: str, text: str = "",
                      postmortem: dict = None, extra: dict = None) -> None:
        """What the page looked like when this went wrong, to a file.

        Written without anybody having to know to ask for it. One per run,
        taken while the page is still sitting on the thing that broke.
        `extra` holds only our own words, counts and yes or no."""
        if self.stats.get("failure_files"):
            return
        extra = dict(extra or {})
        if postmortem:
            extra["postmortem"] = postmortem
        extra = extra or None
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
            provider='Consorsbank', text=text, extra=extra)
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
        print("  Read it through, then attach it to a new issue on GitHub.")
        print("  It is the one thing that saves a round of guessing.")

    def write_survey(self, stopped=None) -> None:
        """The survey Diagnose is safe to send, on the same list of what may
        leave that the failure file uses, saying why Diagnose stopped when a
        press stopped it."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Consorsbank',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = words_for('Consorsbank', site)
        page = self.page()
        info = {"timestamp": now_iso()}
        try:
            info["on_site"] = site.is_safe_url(page.url or "")
            info["signed_out"] = site.looks_signed_out(page)
            # The account holder's name is never written, even where its
            # parts are ordinary words on the fixed list.
            site.set_private_words([self.config.get("owner", "")])
            info["challenge"] = site.detect_security_challenge(page)
            info["mapped"] = not getattr(site, "NOT_MAPPED", "")
            # The page the person left open, read and nothing else. Nothing
            # is followed or pressed (consorsbank_site.survey).
            info["survey"] = site.survey(page)
            try:
                info["collected"] = len(site.collect_documents(page))
            except Exception as e:
                info["collected"] = type(e).__name__
            # No screenshot. Its pages show balances, and a PNG of one
            # would sit in Diagnostics where it is easy to attach to a bug
            # report by accident.
        except Exception as e:
            info["error"] = type(e).__name__
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        sv = info.get("survey") or {}
        pages = sv.get("pages", [])
        print(f"Pages surveyed: {len(pages)}   "
              f"on consorsbank.de: {sum(1 for p in pages if p.get('on_site'))}")
        print(f"Documents listed: {shape_tree(info.get('collected', '?'), words)}")
        print("This first build lists nothing yet. A recording of one trip to a")
        print(f"document is what it needs, {after_sign_in(record=True)}.")

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written to take the same one. Downloads nothing, and captures no
        keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='Consorsbank',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    # -- summary -----------------------------------------------------------

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Consorsbank Documents - run summary",
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
        description="Local supervised Consorsbank document downloader "
                    "(read-only, not built yet)")
    for name, help_text in [
            ("login", "check the connection to your browser"),
            ("discover", "not built yet, says so and stops"),
            ("pilot", "not built yet, says so and stops"),
            ("all", "not built yet, says so and stops"),
            ("resume", "nothing is listed yet, says so and stops"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "survey the open page (no downloads, nothing pressed)"),
            ("record", "record your own path to a document, so this app can be built (downloads nothing)"),
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
    ap.add_argument("--type", help="a kind, such as Statement or 'Tax Document'")
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
            # them, and only the panel is told how it ended (#103).
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    # A run that saved nothing must not look like a clean run.
    if app.stats.get("session_expired"):
        return 2
    if app.stats.get("failed") or app.stats.get("manual_review"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
