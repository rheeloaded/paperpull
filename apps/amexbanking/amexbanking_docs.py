"""American Express Banking statement downloader (local, supervised).
Covers CASA deposit accounts: Business Checking, Personal Checking, and Savings.

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

READ-ONLY: this tool only reads the Documents area and downloads PDFs that
American Express already generated. It never transfers funds, pays bills,
moves money, or changes any account setting. Everything stays on this machine;
nothing is sent to any external service.
"""
from __future__ import annotations

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

from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import pressing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import NEW_LIST_NOTE, lists_what_it_saved, report_run_result
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
        print("Run this from a real console window.")
        raise SystemExit(3)


class Document:
    """One American Express Business document."""

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
        self.document_id = document_id
        self.account_token = account_token or kw.get("account_token", "")
        self.occurrence = occurrence
        self.ambiguous = ambiguous
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


def _absolute(path, root: Path) -> str:
    """path as an absolute path, a relative one read from the output folder
    (older records hold paths relative to wherever a run was started)."""
    p = Path(str(path))
    return str(p if p.is_absolute() else Path(root) / p)


def _path_key(path, root: Path) -> str:
    """One spelling for one file, to compare index rows and records by."""
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(_absolute(path, root)))


def migrate_legacy_keys(records: dict) -> int:
    return _migrate_account_keys(records, lambda r: Document.from_dict(r).key)


class App:
    _journal = None
    _requests = None
    _list_cut_short = False

    def __init__(self, args):
        self.args = args
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
        # The account this run is on is read from the page each time (the
        # switcher, the URL, each list request's own token). The first record
        # discovered is not used: after a switch, or with a second config
        # sharing this folder, it names a different account.
        configured_account = self.config.get("account_name") or self.config.get("account_label")
        if configured_account:
            site.SESSION.account_label = configured_account
            site.SESSION.label_configured = True
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
        }

    def _setup_logging(self):
        logfile = self.paths.logs / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(fh)
        if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
            root.addHandler(logging.StreamHandler(sys.stdout))
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
            live = [p for p in ctx.pages if not p.is_closed()]
            amex_pages = [p for p in live if site.is_safe_url(p.url or "")]
            doc_pages = [p for p in amex_pages if any(k in (p.url or "").lower() for k in ("document", "statement", "checking"))]
            self._work_page = doc_pages[0] if doc_pages else (amex_pages[0] if amex_pages else tabs.new_tab(ctx))
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.requests
        return self._work_page

    def close(self):
        try:
            if self._cdp_mode:
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

    def check_session(self, page) -> None:
        if site.looks_signed_out(page):
            self.write_failure("check the session", "the session has expired")
            raise SystemExit("Signed-out screen detected. Please log in again via login.bat and retry.")
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"\n!! {challenge}")
            self.write_failure("check the session", challenge)
            ask("Complete the challenge in your browser, then press Enter here to continue... ")

    def cmd_open_browser(self):
        profile = Path(self.config["profile_dir"]).resolve()
        profile.mkdir(parents=True, exist_ok=True)
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9303")
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
                                                    mode=self.config.get("browser", "auto"),
                                                    prefer_real=True)
        print(f"Opened {name} with your profile.")
        print("Sign in to American Express Business, open Statements, then leave that window open.")

    def cmd_login(self):
        self.stats["mode"] = "login"
        page = self.page()
        self.check_session(page)
        listed = site.ensure_statements(page)
        if listed:
            print("Success: connected to your signed-in browser and American Express page is ready.")
        else:
            print("Connected, but Statements list was not found yet. Make sure Statements is open.")

    def _in_scope(self, doc: Document) -> bool:
        if self.args.type and doc.category.lower() != self.args.type.lower():
            return False
        if not doc_types.wanted(doc.category, self.config):
            return False
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and doc.date and doc.date < floor:
            return False
        if self.args.end_date and doc.date and doc.date > self.args.end_date:
            return False
        if self.args.year:
            y = (doc.date or "")[:4]
            if y != str(self.args.year):
                return False
        return True

    def _record_discover_doc(self, d: site.RawDoc) -> int:
        title = d.title or "Statement"
        date = (d.date_text or "").strip()
        href = d.href or ""
        account = re.sub(r"\s+", " ", (d.account or "")).strip()
        doc_id = getattr(d, "document_id", "") or href or getattr(d, "tag", "")

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
                       date=date, href=href, confidence=confidence,
                       account=account, date_text=date, document_id=doc_id,
                       account_token=getattr(d, "account_token", ""))
        existing = self.discovery.get(doc.key)
        if existing is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        return 0

    def cmd_discover(self, quiet: bool = False, finish: bool = True) -> int:
        listing.started(self)
        page = self.page()
        if not site.ensure_statements(page):
            self.check_session(page)
            if not site.ensure_statements(page):
                print("Could not reach American Express Business Statements. Sign in and open Statements, then try again.")
                raise SystemExit(0)

        self.check_session(page)
        raw = site.collect_documents(page)
        n_new = 0
        for d in raw:
            n_new += self._record_discover_doc(d)

        self.discovery.save()
        if raw:
            listing.read_whole(self)
        else:
            # Nothing captured: the list request timed out, was missed, or the
            # page was not the account's. That is a listing that stopped, not
            # an account with no documents, so it stays as started() noted it.
            log.warning("No documents were captured from the documents list; "
                        "this listing is not counted as whole.")
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
        in_scope = [d for d in docs if self._in_scope(d)]
        in_scope.sort(key=lambda d: d.date or "", reverse=True)
        if limit:
            return in_scope[:limit]
        return in_scope

    def _already_done(self, doc: Document) -> bool:
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(doc.key)
        if rec:
            if rec.get("downloaded_ok"):
                return True
            state = rec.get("state")
            if state in (State.COMPLETED.value, State.PDF_VERIFIED.value, State.NO_RECEIPT_AVAILABLE.value):
                return True
            p = rec.get("pdf_path", "")
            if p and Path(p).exists():
                if receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok:
                    rec["downloaded_ok"] = True
                    rec["state"] = State.PDF_VERIFIED.value
                    self.progress.update(doc.key, rec)
                    return True
        found = self._file_on_disk_for(doc)
        if found is None:
            return False
        # Adopting a file already saved is no download attempt, so it is
        # written straight to the record rather than through _record.
        doc.pdf_path = str(found)
        doc.pdf_filename = found.name
        doc.downloaded_ok = True
        doc.state = State.PDF_VERIFIED.value
        self.progress.update(doc.key, doc.to_dict())
        return True

    def _file_on_disk_for(self, doc: Document) -> Optional[Path]:
        """A valid PDF already in the category folder that is this document,
        for a record lost or left failed (supports flat, nested or renamed).

        Several documents can share a date (a month-end Statement and a 1099,
        two 1099s for one year, Checking and Savings statements), so a file
        is taken only when it can be told apart: one named with this
        document's id suffix, or else the only date-matching PDF that no
        other record already owns. Several unowned matches are left alone
        rather than guessed at."""
        if not doc.date:
            return None
        folder = self.paths.folder_for(doc.category)
        if not folder.exists():
            return None
        owned = {_path_key(r.get("pdf_path"), self.paths.root)
                 for k, r in self.progress.data.items()
                 if k != doc.key and r.get("pdf_path")}
        min_bytes = self.config["min_pdf_bytes"]
        candidates = [f for f in folder.glob(f"**/{doc.date}*.pdf")
                      if f.is_file() and _path_key(f, self.paths.root) not in owned]
        suffix = (doc.document_id or "")[-6:]
        if suffix:
            for f in candidates:
                if suffix in f.stem and receipt_pdf.validate_pdf(f, min_bytes).ok:
                    return f
        valid = [f for f in candidates if receipt_pdf.validate_pdf(f, min_bytes).ok]
        if len(valid) == 1:
            return valid[0]
        if len(valid) > 1:
            log.info("%d unclaimed PDFs dated %s in %s; not guessing which is %s",
                     len(valid), doc.date, folder, doc.key)
        return None

    def _on_its_site(self):
        return tabs.on_its_site(self, site.is_safe_url, "American Express Business",
                                self._open_documents)

    def _open_documents(self, page):
        if not site.ensure_statements(page):
            self.check_session(page)
            site.ensure_statements(page)

    def process(self, docs: List[Document], dry_run: bool = False):
        to_process = [d for d in docs if not self._already_done(d)]
        if self.args.max_docs:
            to_process = to_process[:int(self.args.max_docs)]

        print(f"\nDocuments to download: {len(to_process)} (of {len(docs)} in scope)")
        if not to_process:
            return

        for i, doc in enumerate(to_process, 1):
            filename = build_pdf_filename(doc.date, doc.summary, "", record=doc,
                                          owner=self.config.get("owner", "") if self.config.get("owner_in_filename") else None)
            print(f"[{i}/{len(to_process)}] {doc.date} - {doc.summary}")
            if dry_run:
                print(f"  Plan: {filename}")
                continue

            try:
                page = self._on_its_site()
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
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        raw_doc = site.RawDoc(
            title=doc.title, date_text=doc.date, href=doc.href,
            category=doc.category, tag=doc.document_id, document_id=doc.document_id,
            account=doc.account, account_token=getattr(doc, "account_token", "")
        )
        saved = site.amexbanking_download(page, raw_doc, out_path)
        if not saved:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF (see the log)")
            self._write_row(doc, "Capture failed", "Needs Manual Review")
            self.write_failure('capture the document', 'the document would not render')
            self.stats["manual_review"] += 1
            print("  Could not capture this document - marked for manual review.")
            return

        doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
        self._record(doc, State.PDF_SAVED)
        valid = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"])
        if valid.ok:
            doc.pdf_size, doc.pdf_pages = str(valid.size_bytes), str(valid.page_count)
            doc.downloaded_ok = True
            self._record(doc, State.PDF_VERIFIED)
            self._write_row(doc, "Success", "Verified")
            self.stats["new_files"].append(str(out_path))
            bucket = {"Statement": "statements", "Tax Document": "tax_documents"}
            self.stats[bucket.get(doc.category, "other")] += 1
            self.stats["dates"].append(doc.date)
            print(f"  Saved: {out_path.name} ({valid.size_bytes:,} bytes, {valid.page_count} pages)")
        else:
            self.stats["validation_failures"] += 1
            self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=valid.reason)
            self._write_row(doc, valid.reason, "Needs Manual Review")
            print(f"  !! PDF failed validation: {valid.reason}")

    def _record(self, doc: Document, state: State, notes: str = ""):
        doc.state = state.value
        if notes:
            doc.notes = notes
        if state == State.PDF_VERIFIED:
            doc.downloaded_ok = True
        rec = doc.to_dict()
        # A document saved before keeps its record while a Download again
        # saves no copy of its own (paperpull_core.saved_copy).
        if saved_copy.holds(self, doc.key, rec):
            return
        self.progress.update(doc.key, rec)
        self.discovery.update(doc.key, {"state": state.value})

    def _write_row(self, doc: Document, status: str, processing: str):
        row = {
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
            "Downloaded At": now_iso(),
            "Verified At": now_iso() if processing == "Verified" else "",
            "Processing Status": processing,
            "Notes": doc.notes,
        }
        self.index_csv.append_rows([row])

    def cmd_pilot(self):
        self.stats["mode"] = "pilot"
        print("Reading the documents list first...")
        self.cmd_discover(quiet=True, finish=False)
        docs = self._select(limit=int(self.config["pilot_count"]))
        if not docs:
            print("No documents in scope to pilot.")
            return
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
            print(f"    State:  {state}")
            print(f"    PDF:    {rec.get('pdf_filename') or '(none)'}"
                  f"  ({rec.get('pdf_size') or '?'} bytes, {rec.get('pdf_pages') or '?'} pages)")
            # A Download again that saved nothing kept the saved copy's
            # record as it was, so it is said here (paperpull_core.saved_copy).
            if saved_copy.tried(self, d.key):
                problems.append(f"{d.key}: {saved_copy.tried(self, d.key)}")
            if state not in (State.COMPLETED.value, State.PDF_VERIFIED.value):
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
        # A full run reads the list every time, or a statement that appeared
        # since the last run would never be seen. Resume carries on from the
        # list already read, and reads one only when there is none.
        if mode_name != "resume" or not self.discovery.data:
            print("Reading the documents list first...")
            self.cmd_discover(quiet=True, finish=False)
        docs = self._select()
        if not docs:
            print("No documents in scope to download.")
            return
        self.process(docs, dry_run=self.args.dry_run)

    def cmd_resume(self):
        self.cmd_run("resume")

    def _reconcile_index(self):
        """Ensure all verified documents on disk are present in index_csv so renaming can find them."""
        root = self.paths.root
        rows = self.index_csv.read_all()
        # One row per file. The same file was once written both as an absolute
        # and as a cwd-relative path, and a rename then made the pair
        # identical, so rows are compared by the file they name, and any
        # repeats already in the index are taken out (with a backup).
        kept, known_paths = [], set()
        for r in rows:
            key = _path_key(r.get("PDF Full Path"), root)
            if key and key in known_paths:
                continue
            if key:
                known_paths.add(key)
            kept.append(r)
        if len(kept) != len(rows):
            log.info("Removed %d repeated rows from the document index", len(rows) - len(kept))
            self.index_csv.rewrite(kept, backup=True)
        new_rows = []
        for d in [Document.from_dict(v) for v in self.progress.data.values()]:
            if d.downloaded_ok or d.state in (State.COMPLETED.value, State.PDF_VERIFIED.value):
                p = _absolute(d.pdf_path, root) if d.pdf_path else ""
                if p and Path(p).exists() and _path_key(p, root) not in known_paths:
                    new_rows.append({
                        "Account Holder": self.config.get("owner", ""),
                        "Document Date": d.date,
                        "Category": d.category,
                        "Document Summary": d.summary,
                        "Document Title": d.title,
                        "Period": d.period,
                        "PDF Filename": d.pdf_filename or Path(p).name,
                        "PDF Full Path": p,
                        "PDF File Size": d.pdf_size or str(Path(p).stat().st_size),
                        "PDF Page Count": d.pdf_pages or "",
                        "Source URL": d.href,
                        "Classification Confidence": d.confidence or "High",
                        "Downloaded At": d.discovered_at or now_iso(),
                        "Verified At": now_iso(),
                        "Processing Status": "Verified",
                        "Notes": "",
                    })
                    known_paths.add(_path_key(p, root))
        if new_rows:
            self.index_csv.append_rows(new_rows)

    def cmd_rename(self):
        self.stats["mode"] = "rename"
        self._reconcile_index()
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
            r = receipt_pdf.validate_pdf(Path(_absolute(p, self.paths.root)),
                                         self.config["min_pdf_bytes"])
            if not r.ok:
                bad += 1
                print(f"  BAD {row.get('PDF Filename', '')}: {r.reason}")
            else:
                row["Verified At"] = now_iso()
        self.index_csv.rewrite(rows)
        print(f"\nVerified {len(rows)} index rows; {bad} problem(s).")

    @property
    def requests(self):
        if self._requests is None:
            self._requests = Requests(self.browser(), is_safe_url=site.is_safe_url)
        return self._requests

    @property
    def journal(self):
        if self._journal is None:
            self._journal = Journal(self.paths.logs, "amexbanking")
        return self._journal

    def write_failure(self, step: str, reason: str, text: str = "",
                      details: Optional[dict] = None) -> None:
        failure.write_failure(self.paths.diagnostics, "amexbanking",
                              self.stats.get("mode", ""), step, reason,
                              text=text, details=details,
                              owner=self.config.get("owner", ""))

    def write_survey(self) -> None:
        """The survey Diagnose is safe to send, written beside the detailed
        file on the same list of what may leave that the failure file uses."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=None,
            journal=self._journal,
            requests=self._requests,
            provider='American Express Banking')

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = words_for('American Express Banking', site)
        page = self.page()
        info = {"timestamp": now_iso()}
        stopped = None
        try:
            info["statements_ready"] = site.ensure_statements(page)
            info["url"] = page.url
            info["title"] = page.title()
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)

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
            info["collected"] = len(docs)
            info["samples"] = [
                {"title": d.title, "date": d.date_text, "category": d.category, "tag": d.tag}
                for d in docs[:8]
            ]
        except pressing.Stop as stop:
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
            stopped = stop
        except Exception as e:
            info["error"] = str(e)

        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        if stopped is not None:
            pressing.say(stopped)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print(f"Documents collected: {shape_tree(info.get('collected', '?'), words)}")
        for s in info.get("samples", [])[:5]:
            print(shape_label(f"  [{s['category']}] {s['date']}  {s['title'][:50]}",
                              words, collapse=False))

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='American Express Banking',
                       owner=self.config.get("owner", ""))

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
    p = argparse.ArgumentParser(description="American Express Banking statement downloader (Business Checking, Personal Checking, Savings)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--open-browser", action="store_true", help="open dedicated browser")
    g.add_argument("--login", action="store_true", help="verify connection")
    g.add_argument("--discover", action="store_true", help="list documents")
    g.add_argument("--pilot", action="store_true", help="pilot download newest 5")
    g.add_argument("--all", action="store_true", help="download all in scope")
    g.add_argument("--resume", action="store_true", help="resume previous run")
    g.add_argument("--verify", action="store_true", help="verify saved PDFs")
    g.add_argument("--rename", action="store_true", help="rename saved PDFs")
    g.add_argument("--diagnose", action="store_true", help="dump page diagnosis")
    g.add_argument("--record", action="store_true", help="record user session")

    p.add_argument("--config", help="path to config.json")
    p.add_argument("--apply", action="store_true", help="with --rename, actually rename")
    p.add_argument("--yes", action="store_true", help="skip confirmations")
    p.add_argument("--year", type=int, help="filter by year")
    p.add_argument("--start-date", help="earliest date (YYYY-MM-DD)")
    p.add_argument("--end-date", help="latest date (YYYY-MM-DD)")
    p.add_argument("--type", help="filter by document type")
    p.add_argument("--max-docs", type=int, help="limit download count")
    p.add_argument("--dry-run", action="store_true", help="plan filenames without downloading")
    p.add_argument("--redownload", action="store_true", help="re-download previously saved docs")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    for d in (args.start_date, args.end_date):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            print(f"Bad date '{d}': use YYYY-MM-DD")
            return 2
    app = App(args)
    try:
        if args.open_browser:
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
        # A press it would not make, or one that brought nothing, stops the
        # run here, with the reason said and the failure file written.
        pressing.stop_run(app, stop)
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
