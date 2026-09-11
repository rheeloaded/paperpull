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
                 href="", row_index=-1, page_number=1, confidence="", account="",
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
        self.page_number = int(page_number or kw.get("page_number", 1))
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
                      logging.StreamHandler(sys.stdout)],
            force=True)
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
            portal_tabs = [p for p in live if (p.url or "").startswith("https://") and "bill-and-payment-history" in (p.url or "")]
            if not portal_tabs:
                portal_tabs = [p for p in live if (p.url or "").startswith("https://") and site.is_safe_url(p.url or "")]
            self._work_page = portal_tabs[0] if portal_tabs else (live[0] if live else ctx.new_page())
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
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

    def _in_scope(self, doc: Document) -> bool:
        a = self.args
        if not doc_types.wanted(doc.category, self.config):
            return False
        if getattr(a, "type", None) and doc.category.lower() != a.type.lower():
            return False
        if getattr(a, "year", None) and not (doc.date or "").startswith(str(a.year)):
            return False
        floor = getattr(a, "start_date", None) or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if getattr(a, "end_date", None) and (not doc.date or doc.date > a.end_date):
            return False
        return True

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
                page_number=rd.get("page_number", 1),
                confidence=conf,
                date_text=rd["date_text"],
            )
            documents.append(doc)
            self.discovery.data[doc.key] = doc.to_dict()
        self.discovery.save()
        print(f"Discovered {len(documents)} document(s).")
        return documents

    def cmd_pilot(self):
        count = getattr(self.args, "max_docs", None) or self.config.get("pilot_count", 5)
        print(f"Running pilot mode (downloading up to {count} newest documents)...")
        docs = [d for d in self.cmd_discover() if self._in_scope(d)]
        docs.sort(key=lambda d: d.date, reverse=True)
        to_download = docs[:count]
        self._download_batch(to_download)

    def cmd_all(self):
        print("Downloading all in-scope discovered PG&E documents...")
        docs = [d for d in self.cmd_discover() if self._in_scope(d)]
        docs.sort(key=lambda d: d.date, reverse=True)
        if getattr(self.args, "max_docs", None):
            docs = docs[:self.args.max_docs]
        self._download_batch(docs)

    def cmd_resume(self):
        print("Resuming interrupted downloads...")
        pending = []
        for k, v in self.discovery.data.items():
            doc = Document.from_dict(v)
            if self._in_scope(doc) and doc.state not in DONE_STATES:
                pending.append(doc)
        pending.sort(key=lambda d: d.date, reverse=True)
        if getattr(self.args, "max_docs", None):
            pending = pending[:self.args.max_docs]
        self._download_batch(pending)

    def _download_batch(self, docs: List[Document]):
        page = self.page()
        for doc in docs:
            if not self._in_scope(doc):
                continue
            if not getattr(self.args, "redownload", False) and doc.key in self.progress.data and self.progress.data[doc.key].get("state") in DONE_STATES:
                print(f"Skipping already completed document: {doc.title}")
                continue
            dest_dir = self.paths.folder_for(doc.category)
            pdf_name = build_pdf_filename(doc.date, doc.summary, "PG&E", doc.account)
            out_path = dest_dir / pdf_name
            if getattr(self.args, "dry_run", False):
                print(f"  [dry-run] Plan: {doc.title} -> {pdf_name}")
                continue
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
        import json as _json
        print("Dumping page structure...")
        page = self.page()
        site.goto_documents(page)
        print(f"Current URL: {page.url}")
        print(f"Page title: {page.title()}")

        info = {
            "url": page.url,
            "title": page.title(),
            "timestamp": now_iso(),
            "row_counts": {},
        }
        for name, sel in [("doc_row", site.FALLBACK["doc_row"]),
                          ("doc_link", site.FALLBACK["doc_link"]),
                          ("pdf links", "a[href*='.pdf']"),
                          ("all links", "a"),
                          ("all buttons", "button")]:
            try:
                info["row_counts"][name] = page.locator(sel).count()
            except Exception as e:
                info["row_counts"][name] = f"ERR {e}"

        docs = site.collect_download_docs(page)
        info["collected"] = len(docs)
        info["samples"] = docs[:8]

        controls = []
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role)
                for i in range(min(loc.count(), 60)):
                    try:
                        t = (loc.nth(i).inner_text(timeout=400) or "").strip()[:60]
                    except Exception:
                        t = ""
                    if t:
                        controls.append({"role": role, "text": t, "safe": site.is_safe_control(t)})
            except Exception:
                pass
        info["controls"] = controls

        try:
            self.paths.diagnostics.mkdir(parents=True, exist_ok=True)
            shot_path = self.paths.diagnostics / "diagnose-documents.png"
            page.screenshot(path=str(shot_path), full_page=True)
            info["screenshot"] = str(shot_path)
        except Exception as e:
            info["screenshot_error"] = str(e)

        out = self.paths.diagnostics / "diagnose-documents.json"
        atomic_write_text(out, _json.dumps(info, indent=2))
        print(f"Wrote diagnostic report: {out}")
        print(f"Counts: {info['row_counts']}")
        print(f"Statements collected: {info['collected']}")
        if controls:
            print("Found clickable controls:")
            for c in controls[:10]:
                print(f"  [{'SAFE' if c['safe'] else 'BLOCK'}] {c['role']}: {c['text']}")


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--year", type=int, help="Filter downloads by statement year (e.g. 2025)")
    parser.add_argument("--start-date", help="Earliest statement date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Latest statement date YYYY-MM-DD")
    parser.add_argument("--max-docs", type=int, help="Maximum number of documents to download")
    parser.add_argument("--type", help="Statement or category filter")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--redownload", action="store_true", help="Re-download documents even if already completed")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    for d in (args.start_date, args.end_date):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            print(f"Bad date '{d}': use YYYY-MM-DD")
            return 2

    # If filter flags were passed without an explicit action, default to --all
    if not (args.open_browser or args.login or args.discover or args.pilot or
            args.all or args.resume or args.verify or args.diagnose):
        if args.year or args.start_date or args.end_date or args.type or args.max_docs:
            args.all = True

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
