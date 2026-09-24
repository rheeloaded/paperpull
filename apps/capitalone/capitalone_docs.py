"""Capital One bank and card statements, tax forms and letters."""
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
import capitalone_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import stable_occurrences as _stable_occurrences
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
from storage import (ALL_CATEGORIES, LETTER as CAT_LETTER,
                     STATEMENT as CAT_STATEMENT, TAX as CAT_TAX)
log = logging.getLogger("capitalone_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", confidence="", account="", account_ref="",
                 account_desc="", last4="", doc_type="", document_id="",
                 dataset_id="", occurrence=0, **kw):
        self.title = title
        self.account = account
        self.account_ref = account_ref
        self.account_desc = account_desc
        self.last4 = last4
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period




        self.doc_type = doc_type

        self.document_id = document_id
        self.dataset_id = dataset_id

        self.occurrence = occurrence



        self.downloaded_ok = kw.get("downloaded_ok", False)
        self.href = href
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
        # Keep the last four. Cutting to forty characters made two cards
        # of the same product collide, because the masked digits that say
        # which one it is sit at the end, and the second card's whole
        # history was then read as already downloaded and dropped.
        acct = _account_component(sanitize_component(self.account or ""))
        base = (f"{acct}:{self.doc_type}:{self.date}:"
                f"{sanitize_component(self.title)[:60]}")
        return base if not self.occurrence else f"{base}#{self.occurrence}"

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


class App:
    _journal = None
    _requests = None

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
            "letters": 0, "other": 0, "skipped_completed": 0,
            "skipped_out_of_scope": 0, "manual_review": 0, "failed": 0,
            "duplicate_filenames": 0, "validation_failures": 0,
            "dates": [], "new_files": [],
        }


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
        if self._cdp_mode:


            live = [p for p in ctx.pages if not p.is_closed()]
            c1 = [p for p in live if site.is_safe_url(p.url or "")]
            c1 = c1 or [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = c1[0] if c1 else ctx.new_page()
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
        self._pw = self._browser = self._context = self._work_page = None


    def check_session(self, page) -> None:
        challenge = site.detect_security_challenge(page)
        if challenge:
            self.progress.save(backup=True)
            print(f"\n!! {challenge}")
            print("Stopped. Please resolve it yourself in the browser window.")
            print("I will NOT attempt to bypass any security check.")
            ask("Press Enter once the page looks normal (or Ctrl+C to quit)... ")
        if site.looks_signed_out(page):
            self.progress.save(backup=True)
            print("\n!! Capital One appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            ask("Press Enter after you are signed in... ")
            site.goto_documents(page)


    def cmd_open_browser(self):
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), '9247')
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url, prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        print("Checking the connection to your signed-in Capital One browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Capital One shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and the signed-in portal is visible.")
            print("Keep that browser window OPEN, then run run_pilot.")
        else:
            print("Connected and signed in, but the document center did not render.")
            print("Open your account in that browser, then run --diagnose.")
        self.close()

    def _in_scope(self, doc: Document) -> bool:
        a = self.args
        if not doc_types.wanted(doc.category, self.config):
            return False
        if a.type and doc.category.lower() != a.type.lower():
            return False
        if getattr(a, "account", None) and (doc.last4 or "") != str(a.account).strip()[-4:]:
            return False
        if a.year and not (doc.date or "").startswith(str(a.year)):
            return False


        floor = a.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if a.end_date and (not doc.date or doc.date > a.end_date):
            return False
        return True

    def _account_label(self, account: str) -> str:
        labels = self.config.get("account_labels") or {}
        return labels.get(account) or account

    def _record_c1_doc(self, d: dict) -> int:
        title = re.sub(r"\s+", " ", (d.get("title") or "")).strip()
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category = d.get("category") or ""


        _cat, summary, confidence = doc_types.classify_document(title, self.rules)
        if category == CAT_STATEMENT:

            summary, confidence = title or "Statement", doc_types.HIGH
        elif category == CAT_LETTER:
            summary, confidence = title or "Letter", doc_types.HIGH
        elif category == CAT_TAX:
            if _cat != doc_types.TAX:
                summary, confidence = title or "Tax Form", doc_types.MEDIUM
        else:
            summary = summary or title or "Document"
            confidence = doc_types.LOW
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        date = (d.get("date") or "").strip()
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        account = re.sub(r"\s+", " ", (d.get("account") or "")).strip()
        self.stats.setdefault("accounts", {})
        self.stats["accounts"][account] = self.stats["accounts"].get(account, 0) + 1
        label = self._account_label(account)
        full_summary = f"{summary} - {label}" if label else summary
        if d.get("occurrence"):
            full_summary = f"{full_summary} ({int(d['occurrence']) + 1})"
        doc = Document(title=title, category=category, summary=full_summary,
                       date=date, period=d.get("period") or "",
                       confidence=confidence, account=account,
                       account_ref=d.get("account_ref") or "",
                       account_desc=d.get("account_desc") or "",
                       last4=site.account_last4(d.get("account_desc") or ""),
                       doc_type=d.get("doc_type") or "",
                       document_id=d.get("document_id") or "",
                       dataset_id=d.get("dataset_id") or "",
                       occurrence=int(d.get("occurrence", 0) or 0),
                       href=site.URLS["documents"])
        existing = self.discovery.get(doc.key)
        if existing is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1

        if doc.document_id and existing.get("document_id") != doc.document_id:
            self.discovery.update(doc.key, {"document_id": doc.document_id,
                                            "dataset_id": doc.dataset_id},
                                  save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        page = self.page()
        if not site.ensure_documents(page):
            self.check_session(page)
            if not site.ensure_documents(page):
                print("Could not open your Capital One document center. Sign in in")
                print("the browser, then try again.")
                return 0
        self.check_session(page)






        raw = site.collect_documents(page)
        log.info("Capital One: %d document(s) across all accounts", len(raw))
        n_new = 0
        # Which of several documents sharing a type, a title, a date and an
        # account this is. The site numbers them as it walks the answer, so
        # a different order next time would hand one document the other's
        # number, and the one already downloaded would be skipped as done
        # while the other arrived beside it. A number already given stays
        # with the document it was given to.
        for d, occ in zip(raw, _stable_occurrences(
                raw, self.discovery.data, fields=("doc_type", "title", "date"))):
            d["occurrence"] = occ
            n_new += self._record_c1_doc(d)

        self.discovery.save()
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
            accounts = self.stats.get("accounts") or {}
            if accounts:
                print(f"\n  Accounts seen ({len(accounts)}):")
                for name, n in sorted(accounts.items(), key=lambda kv: -kv[1]):
                    print(f"    {n:4}  {name}")
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


        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False


    def process(self, docs: List[Document], dry_run: bool = False):
        page = self.page()
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            filename = build_pdf_filename(doc.date, doc.summary, "")
            if dry_run:
                print(f"  DRY RUN - would save: {filename}")
                continue
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
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        out_path = unique_path(folder, filename, self.config["max_path_length"])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        if not site.ensure_documents(page):
            self.check_session(page)
            site.ensure_documents(page)
        saved = site.download_document(page, doc.doc_type, doc.title, doc.date,
                                       doc.account_desc, doc.account_ref,
                                       out_path, occurrence=doc.occurrence,
                                       document_id_hint=doc.document_id,
                                       dataset_id_hint=doc.dataset_id)
        if not saved:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF (see the log)")
            self._write_row(doc, "Capture failed", "Needs Manual Review")
            self.write_failure('capture the document', 'the document would not render')
            self.stats["manual_review"] += 1
            print("  Could not capture this document - marked for manual review.")
            return


        if receipt_pdf.is_zip(out_path):
            extracted = receipt_pdf.extract_pdfs_from_zip(out_path, out_path)
            if not extracted:
                self._record(doc, State.NEEDS_MANUAL_REVIEW,
                             notes="Downloaded archive contained no PDF")
                self._write_row(doc, "Archive with no PDF", "Needs Manual Review")
                self.write_failure('open the downloaded archive', 'the archive held no pdf')
                self.stats["manual_review"] += 1
                print("  !! Download was an archive with no PDF - manual review.")
                return
            out_path = extracted[0]
            if len(extracted) > 1:
                doc.notes = (doc.notes + "; " if doc.notes else "") + \
                    f"archive contained {len(extracted)} PDFs"
                for extra in extracted[1:]:
                    print(f"  + extracted: {extra.name}")
            log.info("Extracted %d PDF(s) from ZIP for %s", len(extracted), doc.title)

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
        doc.downloaded_ok = True
        self._record(doc, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self._write_row(doc, "Downloaded", "Completed")
        self.stats["new_files"].append(str(out_path))
        if doc.date:
            self.stats["dates"].append(doc.date)
        if doc.category == CAT_TAX:
            self.stats["tax_documents"] += 1
        elif doc.category == CAT_LETTER:
            self.stats["letters"] += 1
        elif doc.category == CAT_STATEMENT:
            self.stats["statements"] += 1
        else:
            self.stats["other"] += 1
        print(f"  Saved: {out_path.name}")


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
            "Document Date": doc.date,
            "Category": doc.category,
            "Document Summary": doc.summary,
            "Document Title": doc.title,
            "Account": doc.account,
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
            print(f"This downloads ALL available Capital One documents ({scope}).")
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
        unless --apply is given."""
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
        path = failure.write_failure(
            self.paths.diagnostics,
            command=self.stats.get("mode") or "run",
            step=step, reason=reason,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Capital One', text=text, extra=extra)
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
            provider='Capital One')

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        import json as _json
        page = self.page()
        info = {"timestamp": now_iso()}
        try:
            found = site.goto_documents(page)
            info["documents_page_found"] = found
            info["url"] = page.url
            info["title"] = page.title()
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)

            docs = site.collect_documents(page)
            kinds = {}
            samples = []
            by_account = {}
            for d in docs:
                kinds[d["category"]] = kinds.get(d["category"], 0) + 1
                label = site.redact_label(d["account"])
                by_account[label] = by_account.get(label, 0) + 1
                if len(samples) < 8:
                    samples.append({"doc_type": d["doc_type"],
                                    "title": d["title"][:80],
                                    "category": d["category"],
                                    "date": d["date"], "period": d["period"]})
            info["documents_total"] = len(docs)
            info["documents_by_category"] = kinds
            info["documents_by_account"] = by_account
            info["samples"] = samples

            ui = site.read_page_ui(page) or {}
            info["rendered"] = {
                "headings": ui.get("headings"),
                "rows_on_screen": len(ui.get("rows") or []),
                "row_labels": [site.redact_label(r) for r in (ui.get("rows") or [])[:8]],
            }
            info["controls"] = [{"text": c[:60], "safe": site.is_safe_control(c)}
                                for c in (ui.get("buttons") or [])[:60]]
            page.screenshot(path=str(self.paths.diagnostics / "diagnose-documents.png"),
                            full_page=True)
        except Exception as e:
            info["error"] = str(e)
        out = self.paths.diagnostics / "diagnose-documents.json"
        atomic_write_text(out, _json.dumps(info, indent=2))
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. It")
        print("  carries the page's own words, so it stays on this machine")
        print("  unless you decide to send it.")
        print(f"Documents page found: {info.get('documents_page_found')}")
        print(f"Documents (API): {info.get('documents_total')}  "
              f"{info.get('documents_by_category')}")
        print(f"Accounts: {info.get('documents_by_account')}")
        r = info.get("rendered") or {}
        print(f"Rendered: headings={r.get('headings')} "
              f"rows on screen={r.get('rows_on_screen')}")
        if info.get("error"):
            print(f"Error: {info['error']}")


    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Capital One',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Capital One Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Tax documents downloaded:  {s['tax_documents']}",
            f"Letters downloaded:        {s['letters']}",
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
        description="Local supervised Capital One document downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download the 5 newest in-scope documents, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "dump the document center structure (no downloads)"),
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
    ap.add_argument("--type", help="one of: " + ", ".join(ALL_CATEGORIES))
    ap.add_argument("--account", help="only this account (last four digits)")
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
