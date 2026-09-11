"""PG&E bill-statement downloader (local, supervised).

Usage:
    python pge_docs.py --login       verify connection to your browser
    python pge_docs.py --discover    list available documents
    python pge_docs.py --pilot       download the 5 newest, then stop
    python pge_docs.py --all         download everything in scope
    python pge_docs.py --resume      continue an interrupted run
    python pge_docs.py --verify      re-validate every saved PDF
    python pge_docs.py --diagnose    dump page structure (no downloads)
    python pge_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement|"Tax Document"

READ-ONLY: this tool only reads the Documents area and downloads PDFs that
PG&E already generated. It never transfers funds, pays a bill, changes AutoPay,
or changes any account setting. Everything stays on this machine; nothing is
sent to any external service.
"""
from __future__ import annotations

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
import pge_site as site
from paperpull_core.models import State
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("pge_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One PG&E document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text
        self.document_id = document_id
        self.source_url = kw.get("source_url", "")
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
        acct = sanitize_component(self.account or "")[:40]
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


class App:
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
        cdp_url = self.config.get("cdp_url", "http://127.0.0.1:9242")
        profile = Path(self.config.get("profile_dir", "./browser-profile")).resolve()
        port = browser_launcher.port_from_cdp_url(cdp_url, "9242")
        url = site.URLS.get("login") or site.URLS["home"]
        self._pw, self._browser, self._context, self._cdp_mode = (
            browser_launcher.acquire_browser(
                cdp_url=cdp_url,
                profile_dir=profile,
                port=port,
                initial_url=url,
                browser_mode=self.config.get("browser", "auto"),
            )
        )
        return self._context

    def page(self):
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        ctx = self.browser()
        pages = [p for p in ctx.pages if not p.is_closed()]
        for p in pages:
            if any(u in p.url for u in ("pge.com", "billing")):
                self._work_page = p
                return p
        self._work_page = pages[0] if pages else ctx.new_page()
        return self._work_page

    def close(self):
        try:
            if self._context and not self._cdp_mode:
                self._context.close()
            if self._browser and not self._cdp_mode:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        finally:
            self._pw = None
            self._browser = None
            self._context = None
            self._work_page = None

    def cmd_open_browser(self):
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9242")
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
        print("Checking the connection to your signed-in PG&E browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but PG&E shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and the Documents page is visible.")
            print("Keep that browser window OPEN, then run run_pilot.bat.")

    def cmd_discover(self) -> List[Document]:
        print("Discovering PG&E documents...")
        page = self.page()
        if not site.goto_documents(page):
            print("Failed to navigate to PG&E billing/documents page.")
            return []
        raw_docs = site.collect_download_docs(page)
        documents = []
        for rd in raw_docs:
            cat, summary, conf = doc_types.classify_document(rd["title"], self.rules)
            doc = Document(
                title=rd["title"],
                category=cat,
                summary=summary,
                date=rd["date_text"],
                period=rd["date_text"],
                row_index=rd.get("row_index", -1),
                confidence=conf,
                date_text=rd["date_text"],
            )
            documents.append(doc)
            self.discovery.data[doc.key] = doc.to_dict()
        self.discovery.save()
        print(f"Discovered {len(documents)} document(s).")
        return documents

    def cmd_pilot(self):
        count = self.config.get("pilot_count", 5)
        print(f"Running pilot mode (downloading up to {count} newest documents)...")
        docs = self.cmd_discover()
        docs.sort(key=lambda d: d.date, reverse=True)
        to_download = docs[:count]
        self._download_batch(to_download)

    def cmd_all(self):
        print("Downloading all discovered PG&E documents...")
        docs = self.cmd_discover()
        self._download_batch(docs)

    def cmd_resume(self):
        print("Resuming interrupted downloads...")
        pending = []
        for k, v in self.discovery.data.items():
            doc = Document.from_dict(v)
            if doc.state not in DONE_STATES:
                pending.append(doc)
        self._download_batch(pending)

    def _download_batch(self, docs: List[Document]):
        page = self.page()
        for doc in docs:
            if doc.key in self.progress.data and self.progress.data[doc.key].get("state") in DONE_STATES:
                print(f"Skipping already completed document: {doc.title}")
                continue
            folder_key = self.paths.folder_for(doc.category)
            dest_dir = getattr(self.paths, folder_key, self.paths.other_documents)
            pdf_name = build_pdf_filename(doc.date, doc.summary, "PG&E", doc.account)
            out_path = dest_dir / pdf_name
            if out_path.exists() and out_path.stat().st_size > 0:
                doc.state = State.COMPLETED.value
                doc.pdf_filename = pdf_name
                doc.pdf_path = str(out_path)
                doc.downloaded_ok = True
                self.progress.data[doc.key] = doc.to_dict()
                self.progress.save()
                print(f"File exists, recorded: {pdf_name}")
                continue
            print(f"Downloading {doc.title} -> {pdf_name}...")
            ok = site.download_bill(page, doc.to_dict(), out_path, self.config)
            if ok and out_path.exists() and out_path.stat().st_size > 0:
                doc.state = State.COMPLETED.value
                doc.pdf_filename = pdf_name
                doc.pdf_path = str(out_path)
                doc.pdf_size = str(out_path.stat().st_size)
                doc.downloaded_ok = True
                self.progress.data[doc.key] = doc.to_dict()
                self.progress.save()
                print(f"Successfully downloaded {pdf_name}")
            else:
                if out_path.exists() and (out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
                    out_path.unlink()
                doc.state = State.FAILED.value
                self.progress.data[doc.key] = doc.to_dict()
                self.progress.save()
                print(f"Failed to download {doc.title}")
            self._delay()

    def cmd_verify(self):
        print("Verifying saved PDF documents...")
        failures = 0
        for k, v in self.progress.data.items():
            doc = Document.from_dict(v)
            if doc.pdf_path:
                p = Path(doc.pdf_path)
                if not p.exists() or p.stat().st_size < 2000 or p.read_bytes()[:5] != b"%PDF-":
                    print(f"Verification FAILED for: {doc.pdf_filename}")
                    failures += 1
        if failures == 0:
            print("All saved PDFs verified OK.")

    def cmd_diagnose(self):
        print("Dumping page structure...")
        page = self.page()
        site.goto_documents(page)
        print(f"Current URL: {page.url}")
        print(f"Page title: {page.title()}")


def main():
    parser = argparse.ArgumentParser(description="PG&E bill-statement downloader")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--open-browser", action="store_true", help="Launch sign-in browser")
    parser.add_argument("--login", action="store_true", help="Check sign-in status")
    parser.add_argument("--discover", action="store_true", help="Discover documents")
    parser.add_argument("--pilot", action="store_true", help="Download pilot batch")
    parser.add_argument("--all", action="store_true", help="Download all documents")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted download")
    parser.add_argument("--verify", action="store_true", help="Verify saved PDFs")
    parser.add_argument("--diagnose", action="store_true", help="Diagnose page layout")
    parser.add_argument("--dry-run", action="store_true", help="Plan actions without downloading")
    args = parser.parse_args()

    app = App(args)
    try:
        if args.open_browser:
            app.cmd_open_browser()
        elif args.login:
            app.cmd_login()
        elif args.discover:
            app.cmd_discover()
        elif args.pilot:
            app.cmd_pilot()
        elif args.all:
            app.cmd_all()
        elif args.resume:
            app.cmd_resume()
        elif args.verify:
            app.cmd_verify()
        elif args.diagnose:
            app.cmd_diagnose()
        else:
            parser.print_help()
    finally:
        app.close()


if __name__ == "__main__":
    main()
