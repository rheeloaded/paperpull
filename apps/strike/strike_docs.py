"""Strike statement and tax-form downloader (local, supervised).

Usage:
    python strike_docs.py --login       verify connection to your browser
    python strike_docs.py --discover    list available documents
    python strike_docs.py --pilot       download the 5 newest, then stop
    python strike_docs.py --all         download everything in scope
    python strike_docs.py --resume      continue an interrupted run
    python strike_docs.py --verify      re-validate every saved file
    python strike_docs.py --diagnose    dump page structure (no downloads)
    python strike_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement|"Tax Document"

READ-ONLY: this tool only reads Strike's Documents API and downloads the
statements and tax forms Strike already generated. It never buys, sells,
sends, receives, deposits, withdraws, opens a loan, or changes any setting.
Everything stays on this machine. Nothing is sent to any external service.

Mapped 2026-11-27. See the STATUS block in strike_site.py for the API and
what is taken: each monthly statement as a PDF with its CSV beside it, each
year's transactions as a CSV, and tax forms.
"""
from __future__ import annotations

from paperpull_core import delivery
from paperpull_core import identity
from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import (NEW_LIST_NOTE, NOTHING_OPENED, NOTHING_RECORDED,
                                          after_sign_in, lists_what_it_saved, not_signed_in, report_run_result)

import argparse
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import doc_types, intake, receipt_pdf, shared_folder
from paperpull_core import browser as browser_launcher
import strike_site as site
from paperpull_core.models import State
from paperpull_core.keys import stable_occurrences as _stable_occurrences
from paperpull_core.words import shape_label, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("strike_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


def write_bytes(path: Path, data: bytes) -> None:
    """Put bytes at path whole or not at all, through the core's
    shared_folder, which never writes through a link left at the name."""
    part = path.with_name(path.name + ".part")
    try:
        shared_folder.write_bytes(part, data)
        os.replace(part, path)
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass


def as_csv(filename: str) -> str:
    """The name a PDF would be saved under, ending in .csv instead."""
    return filename[:-4] + ".csv" if filename.lower().endswith(".pdf") else filename + ".csv"


class Document:
    """One Strike document: a monthly statement, a year's transactions, or
    a tax form."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", kind="", year=0, month=0,
                 tax_id="", file_name="", occurrence=0, **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text
        self.document_id = document_id
        self.kind = kind                # "Month", "Year" or "Tax"
        self.year = year
        self.month = month
        self.tax_id = tax_id            # a hint only, looked up again by name and year
        self.file_name = file_name      # the name Strike gives a tax form
        self.occurrence = occurrence    # nth tax form with this name and year
        # Sticky "was successfully downloaded at least once" marker. Once set,
        # the document is never re-downloaded even if you delete the file.
        self.downloaded_ok = kw.get("downloaded_ok", False)
        # A monthly statement is two files. Each is marked when it is saved,
        # so a run that saved the PDF and not the CSV asks only for the CSV.
        self.pdf_ok = kw.get("pdf_ok", False)
        self.csv_ok = kw.get("csv_ok", False)
        self.csv_path = kw.get("csv_path", "")
        self.invoices = kw.get("invoices", [])
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
        """Kind and date, and for a tax form its name, never Strike's id."""
        base = f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}"
        return base if not self.occurrence else f"{base}#{self.occurrence}"

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
        # each config points at its own output_dir, profile_dir and port.
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
            "other": 0, "csv_files": 0, "skipped_completed": 0, "skipped_out_of_scope": 0,
            "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
            "validation_failures": 0, "dates": [], "new_files": [],
        }

    @property
    def wants_csv(self) -> bool:
        return bool(self.config.get("save_statement_csv", True))

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
            # The person's own dashboard tab, matched by parsed host. With
            # none open, a tab of this run's own is opened, never a tab of
            # another site. Strike's session is a cookie, so that tab can
            # open the Documents page by its address (tabs.on_its_site).
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
            print("\n!! Strike appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile."""
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9327")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=False,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print(f"Sign in, keep the window OPEN, then {after_sign_in()}.")

    def cmd_login(self):
        print("Checking the connection to your signed-in Strike browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Strike shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and your statements list answers.")
            print("Keep that browser window OPEN, then run the diagnostics or pilot.")
        else:
            print("Connected, but the statements list did not answer, so this cannot say")
            print("whether you are signed in. Look at the browser window and answer")
            print("anything Strike asks there yourself. If it shows your dashboard,")
            print("run --diagnose.")
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

    def _record_doc(self, doc: Document) -> int:
        """Record one listed document. Returns 1 if new."""
        if doc_types.should_skip(doc.title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(doc.title, self.rules)
        if doc.kind == "Tax":
            category = doc_types.TAX
        elif category == doc_types.OTHER:
            category = doc_types.STATEMENT
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc.category, doc.summary, doc.confidence = category, summary, confidence
        existing = self.discovery.get(doc.key)
        if existing is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        if doc.tax_id and existing.get("tax_id") != doc.tax_id:
            self.discovery.update(doc.key, {"tax_id": doc.tax_id}, save=False)
        return 0

    @staticmethod
    def statement_doc(entry: dict) -> Document:
        year, month = entry["year"], entry["month"]
        if entry["type"] == "Month":
            return Document(title="Account Statement %s %d" % (MONTHS[month - 1], year),
                            date=site.month_end(year, month),
                            period="%04d-%02d" % (year, month), kind="Month",
                            year=year, month=month, href=site.STATEMENTS_API)
        return Document(title="%d Annual Transactions" % year, date="%04d-12-31" % year,
                        period="%04d" % year, kind="Year", year=year, month=0,
                        href=site.STATEMENTS_API)

    @staticmethod
    def tax_doc(entry: dict, occurrence: int = 0) -> Document:
        return Document(title=entry["file_name"], date="%04d-12-31" % entry["year"],
                        period="%04d" % entry["year"], kind="Tax", year=entry["year"],
                        tax_id=entry["id"], file_name=entry["file_name"],
                        occurrence=occurrence, href=site.TAX_API)

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        if not site.ensure_statements(page):
            self.check_session(page)
            if not site.ensure_statements(page):
                self.write_failure("open the statements list", "the statements list did not answer")
                print("Could not read your Strike statements. Sign in in the browser")
                print("(the tab should be on dashboard.strike.me), then try again.")
                raise SystemExit(0)
        self.check_session(page)

        try:
            statements = site.list_statements(page)
            taxes = site.list_tax_documents(page)
        except site.ListStopped as e:
            self.write_failure("read the documents list", str(e))
            print(f"!! Strike's documents list could not be read whole: {e}.")
            print("   Nothing was listed, and nothing is downloaded until it can be.")
            raise SystemExit(0)
        log.info("Strike: %d statement entr(ies), %d tax form(s)", len(statements), len(taxes))

        n_new = 0
        for entry in statements:
            n_new += self._record_doc(self.statement_doc(entry))
        # Two tax forms can share a name and a year (a corrected form, say),
        # so the nth such pair is keyed with its position, a number that
        # stays with the form it was first given to.
        rows = [{"title": t["file_name"], "date": "%04d-12-31" % t["year"]} for t in taxes]
        for t, occ in zip(taxes, _stable_occurrences(rows, self.discovery.data)):
            n_new += self._record_doc(self.tax_doc(t, occ))
        self.discovery.save()
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
        return n_new

    def _select(self, limit: Optional[int] = None) -> List[Document]:
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        docs = [d for d in docs if self._in_scope(d)]
        docs.sort(key=lambda d: d.date or "0000", reverse=True)
        limit = limit if limit is not None else self.args.max_docs
        return docs[:limit] if limit else docs

    def _already_done(self, doc: Document) -> bool:
        """A document saved once is done for good, even if its files are
        deleted later. A monthly statement whose PDF was saved and whose CSV
        was not, while CSVs are wanted, is not done: the next run asks for
        the CSV alone. --redownload fetches everything in scope again."""
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(doc.key)
        if not rec:
            return False
        if rec.get("kind") == "Month" and self.wants_csv and rec.get("pdf_ok") \
                and not rec.get("csv_ok"):
            return False
        if rec.get("downloaded_ok"):
            return True
        state = rec.get("state")
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return receipt_pdf.copy_still_valid(p, self.config["min_pdf_bytes"])
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on dashboard.strike.me and
        never a tab of another site. Strike's session is a cookie, so with no
        tab of the person's there, one is opened at the Documents page by its
        address (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "Strike",
                                open_documents=site.goto_documents)

    def process(self, docs: List[Document], dry_run: bool = False):
        all_rows = [site.identity_for(d) for d in docs]
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            filename = build_pdf_filename(doc.date, doc.summary, "", record=doc)
            if dry_run:
                print(f"  DRY RUN - would save: {filename}"
                      + (" as its CSV" if doc.kind == "Year" else ""))
                if doc.kind == "Month" and self.wants_csv:
                    print("  DRY RUN - and its CSV beside it")
                continue
            try:
                self.journal.op("next_item" if i > 1 else "open_item",
                                "take a document", ordinal=i)
            except Exception:
                pass
            try:
                page = self._on_its_site()
                self.download_one(
                    page, doc, filename,
                    rivals=identity.rivals_for(all_rows, i - 1))
            except KeyboardInterrupt:
                print("\nInterrupted. Progress saved; run --resume to continue.")
                raise
            except site.SessionExpired:
                print("Stopped. Everything downloaded so far is saved.")
                raise SystemExit(0)
            except site.ListStopped:
                # The tax forms list is read again for each form. When it
                # stops, every later form would read it and stop the same
                # way, so the run stops here and the panel offers a run that
                # lists first (listing.read_again_stopped).
                self.write_failure("read the documents list again", "the documents list stopped")
                listing.read_again_stopped(
                    self, "Strike's documents list could not be read whole again. "
                          "Everything downloaded so far is saved.")
            except Exception as e:
                log.warning("Failed on %s: %s", doc.key, failure.error_kind(e))
                self._record(doc, State.FAILED, notes=failure.error_kind(e))
                self.stats["failed"] += 1
            self._delay()

    def download_one(self, page, doc: Document, filename: str, rivals=()):
        """Download one document's file or files.

        A monthly statement is its PDF, checked by the core to print this
        month's closing day, and then its CSV beside it. A year's entry is
        its CSV alone. A tax form is the PDF Strike gives."""
        self.check_session(page)
        if not site.ensure_statements(page):
            self.check_session(page)
            site.ensure_statements(page)
        try:
            # Carry over what an earlier run saved of this statement.
            rec = self.progress.get(doc.key) or {}
            if rec.get("pdf_ok") and not getattr(self.args, "redownload", False):
                for f in ("pdf_ok", "pdf_path", "pdf_filename", "pdf_size", "pdf_pages",
                          "invoices"):
                    setattr(doc, f, rec.get(f, getattr(doc, f)))
            if doc.kind == "Year":
                self._take_year_csv(page, doc, filename)
                return
            if not doc.pdf_ok:
                if not self._take_pdf(page, doc, filename, rivals):
                    return
            else:
                print(f"  The PDF was saved before: {doc.pdf_filename}")
            if doc.kind == "Month" and self.wants_csv:
                if not self._take_month_csv(page, doc):
                    return
        except site.SessionExpired:
            print("\n  !! Strike answered with a sign-in error instead of a document.")
            print("     Your session has expired. Sign in again in the open")
            print("     browser, then run Resume.")
            self.stats["session_expired"] = 1
            raise
        self._completed(doc)

    def _take_pdf(self, page, doc: Document, filename: str, rivals) -> bool:
        folder = self.paths.folder_for(doc.category)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.tax_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1
        if doc.kind == "Month":
            data = site.statement_bytes(page, doc.year, doc.month, "pdf")
        else:
            data = site.tax_bytes(page, self._tax_id(page, doc))
        got = delivery.place(
            data, out_path,
            expect=site.identity_for(doc),
            rivals=rivals,
            journal=self.journal,
            strict=bool(self.config.get("refuse_wrong_documents", False)))
        print("  %s" % got.say())
        if got.outcome == delivery.WRONG:
            why = "the document that came back is not the one it was listed as"
            self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
            self._write_row(doc, "Wrong document", "Needs Manual Review")
            self.write_failure("save the document", why)
            self.stats["manual_review"] += 1
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
            print("  Nothing was saved for it. The file was destroyed")
            print("  rather than filed under this document's name.")
            return False
        saved = got.ok
        if not saved:
            self._record(doc, State.FAILED, notes="Could not capture the document PDF")
            self._write_row(doc, "Capture failed", State.FAILED.value)
            self.write_failure('capture the document', 'the document would not render')
            self.stats["failed"] += 1
            print("  Could not capture this document. Nothing was saved, and the next run tries it again.")
            return False

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
            return False
        doc.pdf_size, doc.pdf_pages = result.size_bytes, result.page_count
        doc.pdf_ok = True
        self.stats["new_files"].append(str(out_path))
        self._record(doc, State.PDF_SAVED)
        print(f"  Saved: {out_path.name}")
        return True

    def _tax_id(self, page, doc: Document) -> str:
        """The tax form's id in a fresh list, found by its name and year."""
        n = 0
        for t in site.list_tax_documents(page):
            if t["file_name"] == doc.file_name and t["year"] == doc.year:
                if n == doc.occurrence:
                    return t["id"]
                n += 1
        if doc.tax_id:
            log.info("a tax form is not in the fresh list, trying the stored id")
            return doc.tax_id
        raise RuntimeError("the tax form is no longer listed")

    def _take_month_csv(self, page, doc: Document) -> bool:
        """The month's CSV, beside its PDF and named from it."""
        data = site.statement_bytes(page, doc.year, doc.month, "csv")
        why = site.csv_problem(data, doc.year, doc.month) if data else "nothing came back"
        if why:
            note = f"The statement CSV was not saved, {why}; tried again next run"
            self._record(doc, State.FAILED, notes=note)
            self.write_failure("save the statement csv", why)
            self.stats["failed"] += 1
            print(f"  !! The CSV was not saved: {why}. The PDF is kept, and the next")
            print("     run asks for the CSV alone.")
            return False
        pdf = Path(doc.pdf_path)
        target = unique_path(pdf.parent, as_csv(pdf.name), self.config["max_path_length"])
        write_bytes(target, data)
        doc.csv_path, doc.csv_ok = str(target), True
        # Listed with its PDF, so a Rename or a move takes both.
        doc.invoices = [{"file": str(pdf), "kept": True, "part": "1 of 2"},
                        {"file": str(target), "kept": True, "part": "2 of 2"}]
        self.stats["new_files"].append(str(target))
        self.stats["csv_files"] += 1
        self._record(doc, State.PDF_SAVED)
        print(f"  Saved: {target.name}")
        return True

    def _take_year_csv(self, page, doc: Document, filename: str) -> None:
        """A year's transactions, as the CSV the page offers for it."""
        # The name and the folders a naming pattern gives it, as a PDF's
        # would be, with the CSV's ending put on the path unique_path gave.
        named = unique_path(self.paths.folder_for(doc.category), filename,
                            self.config["max_path_length"])
        if named.name != filename:
            self.stats["duplicate_filenames"] += 1
        target = unique_path(named.parent, as_csv(named.name), self.config["max_path_length"])
        data = site.statement_bytes(page, doc.year, None, "csv")
        why = site.csv_problem(data, doc.year, None) if data else "nothing came back"
        if why:
            self._record(doc, State.FAILED, notes=f"The annual CSV was not saved, {why}")
            self._write_row(doc, "Capture failed", State.FAILED.value)
            self.write_failure("save the annual transactions csv", why)
            self.stats["failed"] += 1
            print(f"  !! Not saved: {why}. The next run tries it again.")
            return
        write_bytes(target, data)
        doc.pdf_path, doc.pdf_filename = str(target), target.name
        doc.pdf_size, doc.pdf_pages = len(data), ""
        doc.csv_path, doc.csv_ok = str(target), True
        self.stats["new_files"].append(str(target))
        self.stats["csv_files"] += 1
        print(f"  Saved: {target.name}")
        self._completed(doc)

    def _completed(self, doc: Document) -> None:
        doc.downloaded_ok = True   # done for good, even if the files are deleted later
        self._record(doc, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self._write_row(doc, "Downloaded", "Completed")
        if doc.date:
            self.stats["dates"].append(doc.date)
        if doc.category == doc_types.TAX:
            self.stats["tax_documents"] += 1
        elif doc.category == doc_types.STATEMENT:
            self.stats["statements"] += 1
        else:
            self.stats["other"] += 1

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
        if doc.kind == "Month" and doc.csv_ok and doc.csv_path:
            notes = "; ".join(x for x in (notes, "CSV beside it: %s" % Path(doc.csv_path).name) if x)
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
            # Which list the document came from, never an address of its own.
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
            print(f"    File:   {rec.get('pdf_filename', '(none)')}"
                  f"  ({rec.get('pdf_size', '?')} bytes, {rec.get('pdf_pages', '?') or '-'} pages)")
            if rec.get("kind") == "Month" and rec.get("csv_path"):
                print(f"    CSV:    {Path(rec['csv_path']).name}")
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
            print(f"This downloads ALL available Strike documents ({scope}).")
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
        listing.resume(self, docs, lambda left: self.process(left, dry_run=self.args.dry_run))

    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.
        A statement's CSV moves with its PDF. A preview unless --apply."""
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
            if p.lower().endswith(".csv"):
                problem = self._csv_file_problem(Path(p))
                if problem:
                    bad += 1
                    print(f"  BAD {row.get('PDF Filename', '')}: {problem}")
                else:
                    row["Verified At"] = now_iso()
                continue
            r = receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"])
            if not r.ok:
                bad += 1
                print(f"  BAD {row.get('PDF Filename', '')}: {r.reason}")
            else:
                row["Verified At"] = now_iso()
            beside = Path(as_csv(p))
            try:
                there = beside.is_file()
            except OSError:
                there = False
            if there:
                problem = self._csv_file_problem(beside)
                if problem:
                    bad += 1
                    print(f"  BAD {beside.name}: {problem}")
        self.index_csv.rewrite(rows)
        print(f"\nVerified {len(rows)} index rows; {bad} problem(s).")

    @staticmethod
    def _csv_file_problem(path: Path) -> str:
        try:
            return site.csv_problem(intake.read_file(path, "A saved statement CSV"))
        except intake.TooLarge:
            return "the file is larger than a statement CSV can be"
        except OSError:
            return "the file is missing"

    @property
    def requests(self):
        """Which of Strike's own calls happened, and what came back."""
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
        """What the page looked like when this went wrong, to a file. One
        per run."""
        if self.stats.get("failure_files"):
            return
        extra = {"postmortem": postmortem} if postmortem else None
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
            provider='Strike', text=text, extra=extra)
        if not path:
            return
        self.stats["failure_files"] = 1
        try:
            import json as _failure_json
            said = failure.summarize(_failure_json.loads(
                intake.read_file(path, "The failure file").decode("utf-8")))
        except Exception:
            said = []
        if said:
            print("  What it noticed:")
            for line in said[:6]:
                print("    - %s" % line)
        print("  Read it through, then attach it to this provider's issue on")
        print("  GitHub. It is the one thing that saves a round of guessing.")

    def write_survey(self) -> None:
        """The survey Diagnose is safe to send."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Strike')

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = words_for('Strike', site)
        page = self.page()
        info = {"timestamp": now_iso(), "collected": 0}
        try:
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            info["mapped"] = bool(site.DOCUMENT_TYPES)
            info["survey"] = site.survey(page)
            info["samples"] = []
            if site.on_dashboard(page):
                docs = site.list_documents(page)
                info["collected"] = len(docs)
                statements = [e for e in docs if "type" in e]
                taxes = [e for e in docs if "type" not in e]
                for d in [self.statement_doc(s) for s in statements[:10]] + \
                         [self.tax_doc(t) for t in taxes[:4]]:
                    cat, summ, _ = doc_types.classify_document(d.title, self.rules)
                    info["samples"].append({"title": d.title[:90], "date": d.date,
                                            "category": cat, "summary": summ})
            # No screenshot. The dashboard shows balances.
        except Exception as e:
            info["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        sv = info.get("survey") or {}
        print(f"Pages surveyed: {len(sv.get('pages', []))}   "
              f"JSON responses seen: {len(sv.get('responses', []))}")
        print(f"Documents listed: {shape_tree(info.get('collected', '?'), words)}")
        for s in info.get("samples", [])[:5]:
            print(shape_label(f"  [{s['category']}] {s['date']}  {s['summary']}  <- {s['title'][:50]}",
                              words, collapse=False))

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document. Downloads nothing,
        and captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='Strike',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Strike Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"CSV files saved:           {s['csv_files']}",
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
        # A plain list of exactly the files downloaded THIS run. Not for
        # Verify or a dry run, which save nothing (lists_what_it_saved).
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
        description="Local supervised Strike document downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download the 5 newest in-scope documents, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved file"),
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
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
        return 130
    finally:
        app.progress.save(leaving=True)
        app.discovery.save(leaving=True)
        # Discover and Rename download nothing, so the run summary and
        # new-this-run.txt stay as the last download run wrote them (#103).
        if app.stats["mode"] in ("discover", "rename"):
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    if app.stats.get("session_expired"):
        return 2
    if app.stats.get("failed") or app.stats.get("manual_review"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
