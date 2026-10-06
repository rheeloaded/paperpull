"""Vanguard statements, tax forms, letters and trade confirmations."""
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

from paperpull_core import doc_types, receipt_pdf, scope
from paperpull_core import browser as browser_launcher
import vanguard_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import stable_occurrences as _stable_occurrences
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import capture
from paperpull_core import pressing
from paperpull_core import renaming
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import report_run_result
from paperpull_core.words import shape, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
from storage import (ALL_CATEGORIES, CONFIRM as CAT_CONFIRM,
                     LETTER as CAT_LETTER, REPORT as CAT_REPORT,
                     STATEMENT as CAT_STATEMENT, TAX as CAT_TAX)
log = logging.getLogger("vanguard_docs")

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
                 href="", confidence="", account="", account_id="",
                 last4="", charitable=False, doc_type="", on_demand_type="",
                 document_id="", occurrence=0, **kw):
        self.title = title
        self.account = account
        self.account_id = account_id
        self.last4 = last4


        self.charitable = charitable
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period




        self.doc_type = doc_type
        self.on_demand_type = on_demand_type
        self.document_id = document_id



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
            "letters": 0, "trade_confirmations": 0, "reports": 0,
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
            # Reuse the person's own tab on Vanguard's site, the page they
            # left open for this. With none open, a tab of this run's own is
            # opened, never a tab of another site, since the session is a
            # cookie a new tab shares (tabs.new_tab). Matched on the parsed
            # host, never a substring, since "provider.com" in an address also
            # matches "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            vanguard = [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = vanguard[0] if vanguard else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # A file in the download folder that is an exact copy of a document
        # in the archive is one the browser was left holding, and goes.
        # Nothing else is touched (capture.clear_archived_copies).
        capture.clear_archived_copies(
            Path(self.config["output_dir"]) / ".vanguard-downloads",
            [r.get("pdf_path") for r in self.progress.data.values() if isinstance(r, dict)])
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
            print("\n!! Vanguard appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)


    def cmd_open_browser(self):
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), '9282')
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
        print("Checking the connection to your signed-in Vanguard browser...\n")
        page = self.page()
        ok = site.goto_documents(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Vanguard shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and the Statements & Tax Forms page is visible.")
            print("Keep that browser window OPEN, then run run_pilot.")
        else:
            print("Connected, but the documents page did not load, so this cannot say")
            print("whether you are signed in. Look at the browser window and answer")
            print("anything Vanguard asks there yourself. If it shows your account, open")
            print("Accounts > Statements & Tax Forms in it, then run --diagnose.")
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

    def _record_vanguard_doc(self, d: dict, charitable_ids: set) -> int:
        title = re.sub(r"\s+", " ", (d.get("title") or "")).strip()
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category = d.get("category") or ""


        _cat, summary, confidence = doc_types.classify_document(title, self.rules)
        if category == CAT_STATEMENT:
            # The kind alone. The title is "Account Statement - <account>",
            # and the account is added once below, where it was being added
            # a second time (review of #57).
            kind = title.split(" - ", 1)[0].strip() if title else ""
            summary, confidence = kind or "Statement", doc_types.HIGH
        elif category == CAT_CONFIRM:

            summary, confidence = title or "Trade Confirmation", doc_types.HIGH
        elif category == CAT_LETTER:
            summary, confidence = title or "Letter", doc_types.HIGH
        elif category == CAT_REPORT:
            summary, confidence = title or "Report", doc_types.HIGH
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
        account_id = d.get("account_id") or ""
        doc = Document(title=title, category=category, summary=full_summary,
                       date=date, period=d.get("period") or "",
                       confidence=confidence, account=account,
                       account_id=account_id, last4=account_id[-4:],
                       charitable=account_id in charitable_ids,
                       doc_type=d.get("doc_type") or "",
                       on_demand_type=d.get("on_demand_type") or "",
                       document_id=d.get("document_id") or "",
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
                                            "on_demand_type": doc.on_demand_type},
                                  save=False)
        # The name a known document would be given today, which is what
        # Rename reads, so a file saved under an older name can take the new
        # one without being downloaded again. The key is the title and does
        # not change.
        if existing.get("summary") != doc.summary:
            self.discovery.update(doc.key, {"summary": doc.summary}, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        if not site.ensure_statements(page):
            self.check_session(page)
            if not site.ensure_statements(page):
                print("Could not open your Vanguard statements page. Sign in in the")
                print("browser, then try again.")
                return 0
        self.check_session(page)






        # No Vanguard account is a charitable one (list_accounts says so of
        # every account), and asking it walked every year of the picker a
        # second time before the walk that reads the statements.
        charitable_ids: set = set()
        raw = site.collect_documents(
            page, keep=scope.period_filter(self.args, self.config))
        log.info("Vanguard: %d document(s) across all accounts", len(raw))
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
            n_new += self._record_vanguard_doc(d, charitable_ids)

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


    def _on_its_site(self):
        """The tab the next document is taken in, on Vanguard's own site and
        never a tab of another site. Vanguard keeps its session in a cookie
        a new tab shares, so with no tab of the person's on the site the
        documents page is opened in a tab of this run's own
        (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "Vanguard",
                                self._open_documents)

    def _open_documents(self, page):
        """Vanguard's documents page, opened by its address the way discovery
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
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()


    def download_one(self, page, doc: Document, filename: str):
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

        if not site.ensure_statements(page):
            self.check_session(page)
            site.ensure_statements(page)
        saved = site.download_document(page, doc.account_id, doc.charitable,
                                       doc.doc_type, doc.title, doc.date,
                                       out_path, occurrence=doc.occurrence,
                                       document_id_hint=doc.document_id,
                                       on_demand_type_hint=doc.on_demand_type,
                                       dl_dir=Path(self.config["output_dir"]) / ".vanguard-downloads")
        # A failed capture must not leave a file behind. Playwright's
        # save_as creates the target before the bytes arrive, so a
        # capture that fails leaves a ZERO BYTE file with a convincing
        # statement name in the output folder (the five-ghost-files
        # lesson). The site layer removes its own failures; this guard
        # catches anything it missed.
        try:
            if (not saved and out_path.exists()
                    and (out_path.stat().st_size == 0
                         or out_path.read_bytes()[:5] != b"%PDF-")):
                out_path.unlink()
        except OSError:
            pass
        if not saved:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF (see the log)")
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
        elif doc.category == CAT_CONFIRM:
            self.stats["trade_confirmations"] += 1
        elif doc.category == CAT_REPORT:
            self.stats["reports"] += 1
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
            print(f"This downloads ALL available Vanguard documents ({scope}).")
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
            provider='Vanguard', text=text, extra=extra)
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
            provider='Vanguard')

    def cmd_diagnose(self):
        """The statements app as this browser sees it, in counts and field
        names, to Diagnostics/diagnose-documents.json. One walk of the year
        picker, the page's own calls listened to, nothing downloaded and no
        screenshot taken, since a picture of a brokerage page carries every
        balance and account number on it."""
        self.stats["mode"] = "diagnose"
        words = words_for('Vanguard', site)
        page = self.page()
        info = {"timestamp": now_iso()}
        try:
            found = site.goto_documents(page)
            info["documents_page_found"] = found
            info["url"] = page.url
            info["title"] = page.title()
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            stmts = site.collect_statements_json(page)
            kinds, by_account, samples = {}, {}, []
            for s in stmts:
                cat, date, period, _title = site.classify_document(s)
                kinds[cat] = kinds.get(cat, 0) + 1
                label = site.redact_label(site.account_label_from_statement(s))
                by_account[label] = by_account.get(label, 0) + 1
                if len(samples) < 8:
                    samples.append({"category": cat, "date": date, "period": period,
                                    "frequency": s.get("frequencyType"),
                                    "statement_type": s.get("statementType"),
                                    "fields": sorted(k for k in s if isinstance(k, str))})
            info["documents_total"] = len(stmts)
            info["documents_by_category"] = kinds
            info["documents_by_account"] = by_account
            info["samples"] = samples
            ui = site.read_page_ui(page) or {}
            info["rendered"] = {"years": ui.get("years")}
        except Exception as e:
            info["error"] = str(e)
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print(f"Documents page found: {shape_tree(info.get('documents_page_found'), words)}")
        print(f"Accounts: {len(info.get('documents_by_account') or {})}")
        print(f"Documents (API): {shape_tree(info.get('documents_total'), words)}  "
              f"{shape_tree(info.get('documents_by_category'), words)}")
        print(f"Years on the picker: "
              f"{shape_tree((info.get('rendered') or {}).get('years'), words)}")
        if info.get("error"):
            print(f"Error: {shape(info['error'], words)}")

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Vanguard',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Vanguard Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Tax documents downloaded:  {s['tax_documents']}",
            f"Letters downloaded:        {s['letters']}",
            f"Trade confirms downloaded: {s['trade_confirmations']}",
            f"Reports downloaded:        {s['reports']}",
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
        description="Local supervised Vanguard document downloader (read-only)")
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
    except pressing.Stop as stop:
        # A press it would not make stops the run here, with the reason
        # said and the failure file written.
        pressing.stop_run(app, stop)
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
