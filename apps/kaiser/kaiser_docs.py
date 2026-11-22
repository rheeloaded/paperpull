"""Archive Kaiser Permanente My Documents from a manually signed-in browser."""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import listing, pressing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.characters import whole_json
from paperpull_core.run_reporting import (NEW_LIST_NOTE, NOTHING_OPENED, NOTHING_RECORDED,
                                          after_sign_in, lists_what_it_saved, not_signed_in, report_run_result)

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, NoReturn, Optional

from playwright.sync_api import Error as BrowserError

from paperpull_core import doc_types, intake, receipt_pdf
from paperpull_core import browser as browser_launcher
import kaiser_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.words import shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_json, atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("kaiser_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}
RESUME_SCOPE = (*listing.SCOPE_FLAGS, "type", "max_docs")


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One Kaiser Permanente document."""

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
        """Stable identity. Kaiser Permanente gives every bill its own
        identity, so its digest is the key. Category, date, title and account are the
        fallback for a record written without one."""
        if self.document_id:
            return f"id:{self.document_id}"
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
        self._sign_in_resume = self.paths.last_listing.with_name("kaiser-sign-in-resume.json")
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
        self._current_bill_ids = None
        self._current_bills = {}
        self._listing_source = None
        self._listing_anchors = set()
        self._recovering_sign_in = False
        self._pdf_copies = None
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
                self._browser = self._pw.chromium.connect_over_cdp(cdp_url, timeout=15000)
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
        self._work_page = self._wait_for_bill_tab(ctx)
        self.requests
        return self._work_page

    def _wait_for_bill_tab(self, ctx):
        deadline = time.monotonic() + site.BILL_PAGE_WAIT_SECONDS
        announced = False
        while True:
            provider_tabs = [page for page in ctx.pages
                             if tabs.on_site(page, site.is_session_url)]
            history_tabs = [page for page in provider_tabs if site.is_history_tab(page)]
            if self._listing_source:
                history_tabs = [page for page in history_tabs if site.list_source_url(page) == self._listing_source]
            if len(history_tabs) > 1:
                raise SystemExit("Leave one Kaiser document list open for this account.")
            if history_tabs:
                return history_tabs[0]

            billing_tabs = [page for page in provider_tabs if site.can_lead_to_bill_list(page.url)
                            and (self._listing_source is None
                                 or site.list_source_url(page) in (None, self._listing_source))]
            expired = next((page for page in provider_tabs if site.looks_signed_out(page)), None)
            if expired is not None and (not billing_tabs or expired in billing_tabs):
                return expired
            remaining = deadline - time.monotonic()
            if remaining <= 0 and (billing_tabs or self._recovering_sign_in):
                raise TimeoutError("Kaiser Permanente's document list did not finish loading. "
                                   + site.OPEN_BILL_LIST)
            if remaining <= 0 or (not billing_tabs and not announced and not self._recovering_sign_in):
                return (billing_tabs or provider_tabs or [tabs.new_tab(ctx)])[0]
            if not announced:
                print("Waiting for Kaiser Permanente's My Documents page. " + site.OPEN_BILL_LIST, flush=True)
                announced = True
            try:
                interval = min(250, remaining * 1000)
                if billing_tabs:
                    billing_tabs[0].wait_for_timeout(interval)
                else:
                    ctx.wait_for_event("page", timeout=interval)
            except BrowserError:
                # A link can replace its old tab with a new one during loading.
                continue

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
            raise site.SessionExpired()

    def _stop_for_sign_in(self, message="Kaiser Permanente signed you out.") -> NoReturn:
        self.progress.save(backup=True)
        print(f"\n!! {message}")
        print("Sign in to the same Kaiser Permanente account and reopen the document list.")
        # The panel's existing stop reporting uses the unanswered sign-in
        # prompt to offer its sign-in window followed by Continue.
        if browser_launcher.ask_or_none("Press Enter once the document list is open... ") is None:
            print("Choose Open sign-in window in PaperPull to sign in and continue.")
            raise SystemExit(0)
        print("Run --resume to continue with the pending documents.")
        raise SystemExit(0)

    def _remember_sign_in_resume(self, pending=None) -> None:
        if self.args.redownload:
            return
        scope = {name: getattr(self.args, name) for name in RESUME_SCOPE}
        if self.stats["mode"] == "pilot":
            scope["max_docs"] = self.config["pilot_count"]
        # A native row's control ID and date can repeat in another account.
        # Only already verified billing statements can anchor recovery.
        atomic_write_json(self._sign_in_resume, {
            "scope": scope, "pending": pending, "source": self._listing_source,
            "anchors": sorted(self._listing_anchors),
        })

    def _sign_in_checkpoint(self):
        try:
            return whole_json(json.loads(self._sign_in_resume.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9323")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        checkpoint = self._sign_in_checkpoint()
        if checkpoint and checkpoint.get("source") == site.medical.SOURCE_URL:
            url = site.URLS["medical_billing"]
        # The account holder signs in using the dedicated Chrome or Edge profile.
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print(f"Sign in, keep the window OPEN, then {after_sign_in()}.")

    def cmd_login(self):
        print("Checking Kaiser Permanente documents...\n")
        page = self.page()
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Kaiser Permanente shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        else:
            ok = site.bill_list_ready(page)
            if ok:
                print("Success: the Kaiser Permanente document list answered.")
                print("Keep the window open, then run: paperpull kaiser pilot")
            else:
                print("Could not read the Kaiser Permanente document list.")
                print(site.OPEN_BILL_LIST)
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
        """Record one statement without storing its temporary download address."""
        title = r.title
        # Only the classifier's fixed words name a file or reach the run's
        # output. A My Documents title is the site's own text, and on a
        # health account it can carry a name, a clinic or a condition.
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        date = r.date_text
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and date < floor:
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc = Document(title=title, category=category, summary=summary, date=date,
                       confidence=confidence, source_url=source_url, account=r.account,
                       document_id=r.document_id)
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        return 0

    def cmd_discover(self, quiet: bool = False, *, checkpoint: dict | None = None) -> int:
        listing.started(self)
        n_new = 0
        try:
            page = self._on_its_site()
            source = site.list_source_url(page)
            if self._listing_source and source and source != self._listing_source:
                self._stop_for_sign_in("Reopen the same Kaiser Permanente document list to continue.")
            self._listing_source = source or self._listing_source
            self.check_session(page)
            docs = site.collect_download_docs(page)
        except (site.SessionExpired, site.ListStopped) as stop:
            if isinstance(stop, site.ListStopped) and not site.looks_signed_out(page):
                self.write_failure("read My Documents", "My Documents did not answer")
                print(f"Kaiser Permanente document discovery stopped. {stop}")
                raise SystemExit(0)
            docs = None
        except pressing.Stop:
            if not site.looks_signed_out(page):
                raise
            docs = None
        if docs is None:
            if self.stats["mode"] in ("all", "pilot") or (
                    self.stats["mode"] == "resume" and not self._sign_in_resume.exists()):
                self._remember_sign_in_resume()
            self._stop_for_sign_in()
        visible_anchors = {doc.document_id for doc in docs
                           if isinstance(doc, (site.Bill, site.medical.MedicalBill))}
        if checkpoint is not None:
            anchors = set(checkpoint.get("anchors", ()))
            if not anchors or not anchors.issubset(visible_anchors):
                listing.read_again_stopped(self, "PaperPull could not verify the original Kaiser account. "
                                           "Check the account in the browser before choosing Get new documents.")
            pending = checkpoint.get("pending")
            if pending is not None:
                expected = set(pending)
                completed = {record.get("document_id") for record in self.discovery.data.values()
                             if record.get("document_id") in expected
                             and self._already_done(Document.from_dict(record))}
                visible_ids = {doc.document_id for doc in docs}
                if expected - completed - visible_ids:
                    listing.read_again_stopped(self, "Kaiser no longer lists every pending document. "
                                               "The pending items remain in the original run.")
                docs = [doc for doc in docs if doc.document_id in expected]
        self._listing_anchors = visible_anchors
        self._current_bills = {row.document_id: row for row in docs}
        self._current_bill_ids = set(self._current_bills)
        for r in docs:
            n_new += self._record_rawdoc(r, site.bill_source_url(r))
        self.discovery.save()
        log.info("Kaiser Permanente documents: %d listed, %d new", len(docs), n_new)

        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)

        if not quiet:
            docs = [Document.from_dict(v) for v in self.discovery.data.values()
                    if v.get("document_id") in self._current_bill_ids]
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

    def _select(self, limit: Optional[int] = None, *, pending_only: bool = False,
                pending_ids: set[str] | None = None) -> List[Document]:
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        self.stats["discovered"] = len(docs)
        docs = [d for d in docs if self._in_scope(d)]
        if pending_only:
            docs = [d for d in docs if not self._already_done(d)]
        if self._current_bill_ids is not None:
            docs = [d for d in docs if d.document_id in self._current_bill_ids]
        if pending_ids is not None:
            docs = [d for d in docs if d.document_id in pending_ids]
        docs.sort(key=lambda d: (d.date, d.document_id), reverse=True)
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
        # a review copy counts only if its PDF is still present and valid;
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return receipt_pdf.copy_still_valid(p, self.config["min_pdf_bytes"])
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """Use the account's Bills tab already open in the PaperPull browser."""
        return tabs.on_its_site(self, site.is_session_url, "Kaiser Permanente")

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
                self._remember_sign_in_resume([d.document_id for d in docs if not self._already_done(d)])
                self._stop_for_sign_in()
            except site.ListStopped as stop:
                self.list_changed(stop)
            except pressing.Stop:
                raise
            except Exception as error:
                kind = failure.error_kind(error)
                log.info("Could not download the statement: %s", kind)
                self._record(doc, State.FAILED, notes=kind)
                self.stats["failed"] += 1
            self._delay()

    def list_changed(self, stop) -> None:
        """Leave the statement pending when the list or session needs attention."""
        log.info("Kaiser Permanente bill download stopped before the selected document was saved")
        self.write_failure("read My Documents again", "My Documents did not answer")
        listing.read_again_stopped(self, (
            f"Kaiser Permanente bill download stopped. {stop}"))

    def _known_pdfs(self) -> dict[str, Path]:
        """Find completed PDFs already saved by the connector, including earlier views."""
        if self._pdf_copies is None:
            self._pdf_copies = {}
            root = self.paths.root.resolve()
            for record in self.progress.data.values():
                done = record.get("downloaded_ok") or record.get("state") in (
                    State.COMPLETED.value, State.PDF_VERIFIED.value)
                if not done or not record.get("pdf_path"):
                    continue
                try:
                    path = Path(record["pdf_path"]).resolve()
                    if path.is_relative_to(root):
                        digest = intake.plain_sha256(path)
                        if digest:
                            self._pdf_copies.setdefault(digest, path)
                except (OSError, ValueError, intake.TooLarge):
                    continue
        return self._pdf_copies

    def download_one(self, page, doc: Document, filename: str):
        """Save one statement. The site layer asks for the PDF from
        inside the signed-in page and hands back the bytes."""
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

        bill = self._current_bills[doc.document_id]
        reuse = isinstance(bill, site.NativeDocument) and not self.args.redownload
        saved = site.download_bill(page, bill, out_path,
                                   existing_pdfs=self._known_pdfs() if reuse else None)
        # A capture that failed must not leave a convincing empty file behind.
        if out_path.exists() and (out_path.stat().st_size == 0
                                  or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            saved = False
        if not saved:
            self._record(doc, State.FAILED,
                         notes="Could not capture the document PDF")
            self._write_row(doc, "Capture failed", State.FAILED.value)
            self.write_failure('capture the document', 'the document would not render')
            self.stats["failed"] += 1
            print("  Could not capture this document. Nothing was saved, and the next run tries it again.")
            return

        reused = saved != out_path
        out_path = saved
        if not reused:
            doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
            self._record(doc, State.PDF_SAVED)

        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"])
        if not result.ok:
            self.stats["validation_failures"] += 1
            if reused:
                self._record(doc, State.FAILED, notes="The archived copy could not be verified")
                self.stats["failed"] += 1
                return
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
        if reused and not self.args.redownload:
            # The existing file keeps its own index row and can be renamed
            # independently of this duplicate listing.
            doc.pdf_path, doc.pdf_filename = "", ""
            self._record(doc, State.COMPLETED, notes="Matched an already archived PDF")
            self.stats["skipped_completed"] += 1
            print("  The original PDF is already saved in this archive.")
            return
        self._record(doc, State.COMPLETED)
        if self._pdf_copies is not None:
            digest = intake.plain_sha256(out_path)
            if digest:
                self._pdf_copies[digest] = out_path
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
            "Source URL": doc.source_url,
            "Classification Confidence": doc.confidence,
            "Downloaded At": now_iso() if doc.pdf_filename else "",
            "Verified At": now_iso() if doc.pdf_pages else "",
            "Processing Status": processing,
            "Notes": notes,
        }])

    # -- modes -------------------------------------------------------------

    def cmd_pilot(self):
        self.stats["mode"] = "dry-run" if self.args.dry_run else "pilot"
        if not self.args.dry_run:
            print("PILOT MODE - limited supervised test run.\n")
            self.cmd_discover()
            self._sign_in_resume.unlink(missing_ok=True)
        docs = self._select(limit=self.config.get("pilot_count", 5))
        if self.args.dry_run:
            self.process(docs, dry_run=True)
            return
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
            print(f"    Kind:   {rec.get('summary', d.summary)}")
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
        if self.args.dry_run:
            self.stats["mode"] = "dry-run"
            print("Previewing documents from the saved list.")
            self.process(self._select(), dry_run=True)
            return
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            scope = ", ".join(self.config.get("document_types", []))
            print(f"This downloads ALL available items from the open Kaiser Permanente document list ({scope}).")
            print("Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover()
        self._sign_in_resume.unlink(missing_ok=True)
        docs = self._select()
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)

    def cmd_resume(self):
        self.stats["mode"] = "dry-run" if self.args.dry_run else "resume"
        pending_ids = None
        checkpoint = self._sign_in_checkpoint()
        if checkpoint is not None:
            self._listing_source = checkpoint.get("source")
            self._recovering_sign_in = not self.args.dry_run
            for flag in RESUME_SCOPE:
                if getattr(self.args, flag) is None:
                    setattr(self.args, flag, checkpoint["scope"][flag])
            if checkpoint["pending"] is not None:
                pending_ids = set(checkpoint["pending"])
        if not self.args.dry_run:
            listing.read_again_first(self, noun="documents")
            self.cmd_discover(quiet=True, checkpoint=checkpoint)
        docs = self._select(pending_only=True, pending_ids=pending_ids)
        listing.resume(self, docs, lambda left: self.process(left, dry_run=self.args.dry_run),
                       noun="documents")
        if not self.args.dry_run and checkpoint is not None:
            intended = docs if pending_ids is None else [
                Document.from_dict(record) for record in self.discovery.data.values()
                if record.get("document_id") in pending_ids
            ]
            if all(self._already_done(doc) for doc in intended):
                self._sign_in_resume.unlink(missing_ok=True)


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
                      postmortem: dict = None, extra: dict = None) -> None:
        """What the page looked like when this went wrong, to a file.

        Written without anybody having to know to ask for it, because a
        tester who has to be told to run a second command is a tester who
        sends one file and waits a day for the request for the other.

        One per run. A run where thirty documents fail for one reason
        does not need thirty files, and the first is taken while the page
        is still sitting on the thing that broke."""
        if self.stats.get("failure_files"):
            return
        extra = dict(extra or {})
        if postmortem:
            extra["postmortem"] = postmortem
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
            provider='Kaiser Permanente', text=text, extra=extra)
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
        print("  PaperPull saved a local diagnostic report.")

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
            provider='Kaiser Permanente',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        """Report only statement counts and page state, without recording a screenshot."""
        self.stats["mode"] = "diagnose"
        words = words_for("Kaiser Permanente", site)
        page = self.page()
        info = {"timestamp": now_iso()}
        stopped = None
        try:
            info["signed_out"] = bool(site.looks_signed_out(page))
            info["documents_page_found"] = bool(site.is_history_tab(page)) and not info["signed_out"]
            if not info["signed_out"]:
                # A tab that is not a document list stops here at once,
                # with nothing pressed (ListStopped).
                info["documents_total"] = len(site.collect_download_docs(page))
        except (site.SessionExpired, site.ListStopped) as error:
            info["error"] = type(error).__name__
        except pressing.Stop as stop:
            # A press the look would not make ends it there, and the file
            # still says what was seen and why it stopped.
            stopped = stop
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
        self._diagnose_stopped = stopped
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        if stopped is not None:
            pressing.say(stopped)
        print(f"Wrote {out}")
        print("Text that is not on PaperPull's fixed list is shown as its shape.")
        print(f"Bills recognized: {shape_tree(info.get('documents_total', 'unavailable'), words)}")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='Kaiser Permanente',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Kaiser Permanente Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Bills downloaded:          {s['statements']}",
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
        description="Local supervised Kaiser Permanente document downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list available documents; writes discovery.json"),
            ("pilot", "download a sample of the newest in-scope documents"),
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
    ap.add_argument("--type", help="Statement (Kaiser Permanente bills)")
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
        pressing.stop_run(app, stop)
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
        return 130
    finally:
        app.progress.save(leaving=True)
        app.discovery.save(leaving=True)
        # Discover and Rename report their outcome without replacing the
        # previous run's summary. Dry runs write a summary and preserve the
        # last download list through lists_what_it_saved.
        if app.stats["mode"] in ("discover", "rename"):
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
