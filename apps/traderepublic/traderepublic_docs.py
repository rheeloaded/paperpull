"""Download Trade Republic monthly account statement PDFs from a manually
signed-in browser. UNTESTED, built without an account, see traderepublic_site."""
from __future__ import annotations

from paperpull_core import delivery
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
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import doc_types, receipt_pdf
from paperpull_core import browser as browser_launcher
import traderepublic_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("traderepublic_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}
TITLE = "Trade Republic Account Statement"

# A month whose answer held no statement PDF. Recorded as Failed, so the
# next run asks again, and counted apart, never a sign-out and never done.
NO_STATEMENT_NOTE = "Trade Republic answered this month with no statement PDF"


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One month's Trade Republic account statement."""

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
        # The month, YYYY-MM. A statement is asked for by its month and
        # nothing else, so the month is its identity.
        self.document_id = document_id
        self.source_url = kw.get("source_url", "")
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
        """Stable identity, the statement's month. Category, date, title and
        account are the fallback for a record written without one."""
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
    """Move records written while the account was cut to forty characters.
    Trade Republic records carry no account, so nothing moves today."""
    return _migrate_account_keys(records, lambda r: Document.from_dict(r).key)


class App:
    _journal = None
    _requests = None

    def __init__(self, args):
        self.args = args
        # --config lets one copy of the code serve several people/accounts:
        # each config points at its own output_dir, profile_dir and port, so
        # progress.json, the index CSV, the PDFs and the browser session are
        # all kept separate. Trade Republic's statement names no account
        # here, so a second account needs its own config.
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
                                 DOCUMENT_INDEX_COLUMNS, self.paths.backups, once=True)
        self.rules = doc_types.load_rules()

        self._pw = None
        self._browser = None
        self._context = None
        self._work_page = None
        self._cdp_mode = False
        # The months of this run, worked out once, so a run that passes
        # midnight keeps the window it started with.
        self._months = None
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "discovered": 0, "statements": 0, "tax_documents": 0,
            "insurance_documents": 0,
            "other": 0, "skipped_completed": 0, "skipped_out_of_scope": 0,
            "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
            "validation_failures": 0, "no_statement": 0,
            "dates": [], "new_files": [],
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

    def months(self) -> List[site.Month]:
        if self._months is None:
            self._months = site.months()
        return self._months

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
                raise SystemExit("Connected browser has no context. Open a tab and retry.")
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
            # The person's own tab on the web app, the one on /boards first.
            # With none open, a tab of this run's own, which is never loaded
            # anywhere (tabs.new_tab), so the run then stops and says to open
            # the home page. Matched on the parsed host, never a substring.
            live = [p for p in ctx.pages if not p.is_closed()]
            ready = [p for p in live if site.is_ready_url(p.url or "")]
            dom = [p for p in live if site.is_app_url(p.url or "")]
            self._work_page = ready[0] if ready else (dom[0] if dom else tabs.new_tab(ctx))
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.requests
        return self._work_page

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
            print("\n!! Trade Republic appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile."""
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9320")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print(f"Sign in until the home page shows, keep the window OPEN, then {after_sign_in()}.")

    def cmd_login(self):
        print("Checking Trade Republic statement access...\n")
        page = self.page()
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but Trade Republic shows its sign-in page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif not site.is_ready_url(page.url or ""):
            print("Connected, but no Trade Republic tab is on its home page (Boards).")
            print("Sign in at app.traderepublic.com in that window until the home page")
            print("shows, keep it open, then re-run --login. Nothing was asked of Trade Republic.")
        else:
            proof, _month = site.prove_session(page, self.months())
            listed = site.proven(proof)
            if listed:
                print("Success: Trade Republic answered with a monthly statement.")
                print("Keep the window open, then run: paperpull traderepublic pilot")
            elif proof == site.SIGNED_OUT:
                print("Trade Republic answered that this window is not signed in.")
                print("Sign in again in the open browser window, then re-run --login.")
            elif proof == site.LIMITED:
                print("Trade Republic is limiting requests. Try again later.")
            else:
                print("Could not confirm a Trade Republic session. None of the newest")
                print("months answered with a statement PDF. Run Diagnose and attach its")
                print("file to the Trade Republic issue, since this app is untested.")
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

    def _record_rawdoc(self, m: site.Month) -> int:
        """Record one month, keyed by its period."""
        category, summary, confidence = doc_types.classify_document(TITLE, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and m.date < floor:
            self.stats["skipped_out_of_scope"] += 1
            return 0
        doc = Document(title=TITLE, category=category, summary=summary, date=m.date,
                       period=m.period, date_text=m.period, confidence=confidence,
                       source_url=site.READY_URL, document_id=m.period)
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        listing.started(self)
        page = self._on_its_site()
        self.check_session(page)
        months = self.months()
        # The months are worked out, not read, so the session is proven
        # first by a statement answering as a PDF, and nothing is recorded
        # without it (login_needs_the_list).
        proof, _month = site.prove_session(page, months)
        if proof == site.SIGNED_OUT:
            print("Trade Republic answered that this window is not signed in.")
            print("Sign in again in the open browser window, then run this again.")
            raise SystemExit(0)
        if proof == site.LIMITED:
            print("Trade Republic is limiting requests. Try again later.")
            raise SystemExit(0)
        if proof != site.PDF:
            self.write_failure("ask for the newest statements",
                               "none of the newest months answered with a statement pdf")
            print("Could not confirm a Trade Republic session. None of the newest months")
            print("answered with a statement PDF, so nothing was listed.")
            raise SystemExit(0)
        n_new = 0
        for m in months:
            n_new += self._record_rawdoc(m)
        self.discovery.save()
        log.info("Trade Republic months: %d in reach, %d new", len(months), n_new)
        # The whole window is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)

        if not quiet:
            docs = [Document.from_dict(v) for v in self.discovery.data.values()]
            print(f"\nDiscovery complete. Months known: {len(docs)}")
            dates = sorted(d.date for d in docs if d.date)
            if dates:
                print(f"  Date range: {dates[0]} .. {dates[-1]}")
            if self.stats["skipped_out_of_scope"]:
                print(f"  Skipped as out of scope: {self.stats['skipped_out_of_scope']}")
        return n_new

    def _select(self, limit: Optional[int] = None, *, pending_only: bool = False) -> List[Document]:
        docs = [Document.from_dict(v) for v in self.discovery.data.values()]
        docs = [d for d in docs if self._in_scope(d)]
        # A month recorded by an earlier run that has since passed out of the
        # route's reach is left alone, and said, rather than asked forever.
        reach = {m.period for m in self.months()}
        gone = [d for d in docs if site.month_of(d.document_id) and d.document_id not in reach]
        untried = [d for d in gone if not self._already_done(d)]
        if untried:
            print(f"  {len(untried)} month(s) not saved earlier are now past the "
                  f"{site.LOOKBACK_DAYS} days Trade Republic keeps and are not asked.")
        docs = [d for d in docs if d not in gone]
        if pending_only:
            docs = [d for d in docs if not self._already_done(d)]
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
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        if state == State.NEEDS_MANUAL_REVIEW.value:
            p = rec.get("pdf_path", "")
            return receipt_pdf.copy_still_valid(p, self.config["min_pdf_bytes"])
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The person's Trade Republic tab, on its home page (Boards)."""
        page = self.page()
        # A Trade Republic tab of the person's that is open but not on the
        # home page may be signed in, so the core's words for a tab that is
        # not open, which send the person to sign in again, would not help.
        if (tabs.on_site(page, site.is_app_url) and not tabs.is_own(page)
                and not site.is_ready_url(page.url or "")):
            tabs.stop(self, [
                "The Trade Republic tab is open but not on its home page (Boards).",
                "Sign in there if it asks, open the home page, keep the window open, "
                "and run this again. Nothing was asked of Trade Republic.",
            ])
        return tabs.on_its_site(self, site.is_ready_url, "Trade Republic")

    def process(self, docs: List[Document], dry_run: bool = False):
        self._empty_in_a_row = 0
        for i, doc in enumerate(docs, 1):
            print(f"\n[{i}/{len(docs)}] {doc.period or doc.date or '(no date)'}  "
                  f"{doc.category}  {doc.summary}")
            if self._already_done(doc):
                print("  Already downloaded and verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            filename = build_pdf_filename(doc.date, doc.summary, "", record=doc)
            if dry_run:
                print(f"  DRY RUN - would save: {filename}")
                continue
            try:
                self.journal.op("next_item" if i > 1 else "open_item",
                                "take a document", ordinal=i)
            except Exception:
                pass
            try:
                page = self._on_its_site()
                self.download_one(page, doc, filename)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress saved. Run --resume to continue.")
                raise
            except site.SessionExpired:
                # Already explained by download_one. Stop rather than ask
                # every later month of a signed-out session.
                print("Stopped. Everything downloaded so far is saved.")
                raise SystemExit(0)
            except site.ListStopped as stop:
                # Trade Republic limiting requests, or the tab gone. Every
                # later month would meet the same, so the run stops here
                # with this month left as it was.
                self.months_stopped(stop)
            except Exception as e:
                kind = failure.error_kind(e)
                log.info("Could not download the statement: %s", kind)
                self._record(doc, State.FAILED, notes=kind)
                self.stats["failed"] += 1
            self._delay()

    # How many months in a row may answer with no PDF before the session is
    # proven again. A session that ended without a 401 or a 403 would answer
    # every later month that way, and the run would ask all of them.
    EMPTY_BEFORE_A_CHECK = 3

    def _after_an_empty_month(self, page) -> None:
        self._empty_in_a_row = getattr(self, "_empty_in_a_row", 0) + 1
        if self._empty_in_a_row < self.EMPTY_BEFORE_A_CHECK:
            return
        self._empty_in_a_row = 0
        proof, _month = site.prove_session(page, self.months())
        if proof == site.SIGNED_OUT:
            raise site.SessionExpired()
        if not site.proven(proof):
            raise site.ListStopped(
                "Several months in a row answered with no statement PDF, and the newest "
                "months no longer answer either, so Trade Republic may have signed you out.")

    def months_stopped(self, stop) -> None:
        """Leave the month pending when Trade Republic cannot be asked any more."""
        log.info("Trade Republic statement download stopped before the month was saved")
        self.write_failure("ask for the month's statement", "trade republic could not be asked")
        listing.read_again_stopped(self, f"Trade Republic statement download stopped. {stop}")

    # What a month that saved nothing is recorded and said as: the record's
    # note, the failure file's step and its reason.
    _REFUSED = {
        site.NO_STATEMENT: (NO_STATEMENT_NOTE,
                            "ask for the month's statement", "the answer held no statement pdf"),
        site.TOO_LARGE: ("Trade Republic's answer was larger than a document may be",
                         "ask for the month's statement", "the answer was too large"),
        "refused": ("The PDF printed another month's first and last day",
                    "check the statement pdf", "the pdf named another month"),
        "unchecked": ("The PDF did not print this month's first and last day",
                      "check the statement pdf", "the pdf did not show its month"),
        "unreadable": ("The PDF's text could not be read",
                       "read the statement pdf", "the statement pdf could not be read"),
        delivery.NOT_PLACED: ("The statement could not be put in place in its folder",
                              "save the statement", "the folder would not take the file"),
        "": ("Could not capture the statement PDF",
             "capture the document", "the document would not arrive"),
    }

    def _saved_nothing(self, doc: Document, why: str, postmortem: dict = None) -> None:
        note, step, reason = self._REFUSED.get(why, self._REFUSED[""])
        if why == "refused":
            # A PDF that arrived and was another month, which puts the
            # run's other months in doubt too (run_reporting).
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        if why == site.NO_STATEMENT:
            self.stats["no_statement"] += 1
        self._record(doc, State.FAILED, notes=note)
        self._write_row(doc, "Capture failed", State.FAILED.value)
        self.write_failure(step, reason, postmortem=postmortem)
        self.stats["failed"] += 1
        print(f"  {note}. Nothing was saved, and the next run tries it again.")

    def download_one(self, page, doc: Document, filename: str):
        """Save one month. The site layer asks for the statement from inside
        the signed-in tab and hands back the bytes, which are checked to be
        this month's before delivery places them."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1
        month = site.month_of(doc.document_id)
        if month is None:
            self._saved_nothing(doc, "")
            return

        got = site.fetch_month(page, month)
        if got.kind == site.SIGNED_OUT:
            print("\n  !! Trade Republic answered that this window is not signed in.")
            print("     Sign in again in the open browser, then run:  paperpull traderepublic resume")
            self._record(doc, State.DISCOVERED, notes="Session expired before download")
            raise site.SessionExpired()
        if got.kind == site.LIMITED:
            raise site.ListStopped("Trade Republic is limiting requests. Try again later.")
        if got.kind != site.PDF:
            self._saved_nothing(doc, got.kind)
            self._after_an_empty_month(page)
            return
        self._empty_in_a_row = 0
        check = site.check_period(got.data, month)
        if not check.ok:
            self._saved_nothing(doc, check.outcome, postmortem={"identity": check.report()})
            return
        placed = delivery.place(got.data, out_path,
                                expect=site.identity_for(month),
                                rivals=site.rivals_for(month),
                                journal=self.journal, strict=True)
        print("  %s" % placed.say())
        if not placed.ok:
            why = "refused" if placed.outcome == delivery.WRONG else (
                delivery.NOT_PLACED if placed.outcome == delivery.NOT_PLACED else "")
            self._saved_nothing(doc, why, postmortem={"delivery": placed.report()})
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
            print(f"  !! Validation failed ({result.reason}), moved to Manual Review.")
            return

        doc.pdf_size, doc.pdf_pages = result.size_bytes, result.page_count
        doc.downloaded_ok = True   # done for good, even if the file is deleted later
        doc.notes = ""
        self._record(doc, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self._write_row(doc, "Downloaded", "Completed")
        self.stats["new_files"].append(str(out_path))
        if doc.date:
            self.stats["dates"].append(doc.date)
        self.stats["statements"] += 1
        print(f"  Saved: {out_path.name}")

    # -- records -----------------------------------------------------------

    def _record(self, doc: Document, state: State, notes: str = ""):
        doc.state = state.value
        if notes:
            # One note, this run's, so a month that answered later does not
            # keep the words of an earlier run that failed.
            doc.notes = notes
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
            print(f"\n  {rec.get('period', d.period)}  {rec.get('category', d.category)}")
            print(f"    State:  {state}")
            print(f"    PDF:    {rec.get('pdf_filename', '(none)')}"
                  f"  ({rec.get('pdf_size', '?')} bytes, {rec.get('pdf_pages', '?')} pages)")
            if saved_copy.tried(self, d.key):
                problems.append(f"{d.key}: {saved_copy.tried(self, d.key)}")
            if state != State.COMPLETED.value:
                problems.append(f"{d.key}: {state} - {rec.get('notes', '')}")
        print("\n" + "-" * 70)
        if problems:
            print("Needs attention:")
            for p in problems:
                print(f"  ! {p}")
            print("This app is untested. Attach the file in Diagnostics to the")
            print("Trade Republic issue on GitHub, see the app's README.")
        else:
            print("No problems detected in the pilot.")
        print(f"\nFiles are in:\n  {self.paths.root}")
        print("Nothing further runs until you explicitly start a full command.")

    def cmd_run(self, mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This downloads ALL available Trade Republic monthly statements.")
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
        """Rename what is already downloaded, without downloading it again."""
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
        print(f"\nVerified {len(rows)} index rows, {bad} problem(s).")

    @property
    def requests(self):
        """Which of the provider's own calls happened, and what came back."""
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
        per run, taken while the page is still sitting on what broke."""
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
            provider='Trade Republic', text=text, extra=extra)
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
        """The survey Diagnose is safe to send, on the same list of what may
        leave that the failure file uses."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Trade Republic')

    def cmd_diagnose(self):
        """Ask the newest month once and report what came back, as counts
        and yes or no, never a value. Saves nothing."""
        self.stats["mode"] = "diagnose"
        words = words_for("Trade Republic", site)
        page = self.page()
        url = page.url or ""
        info = {"timestamp": now_iso(), "signed_out": site.looks_signed_out(page),
                "on_app_host": site.is_app_url(url),
                "on_home_page": site.is_ready_url(url),
                "statements_read": 0}
        if info["on_home_page"]:
            months = self.months()[:site.PROBE_MONTHS]
            asked = []
            for m in months:
                try:
                    got = site.fetch_month(page, m)
                except site.ListStopped:
                    asked.append({"status_class": Fixed("none"), "answer": Fixed("tab closed")})
                    break
                one = {"status_class": site.status_class(got.status), "answer": Fixed(got.kind)}
                if got.kind == site.PDF:
                    one.update(site.survey_pdf(got.data, m))
                    info["statements_read"] += 1
                asked.append(one)
                if got.kind in (site.PDF, site.SIGNED_OUT, site.LIMITED):
                    break
            info["newest_months_asked"] = asked
            info["signed_out"] = info["signed_out"] or any(
                a["answer"] == site.SIGNED_OUT for a in asked)
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("Text that is not on PaperPull's fixed list is shown as its shape.")
        print(f"Statements read: {shape_tree(info['statements_read'], words)}")
        if not info["on_home_page"]:
            print("No Trade Republic tab is on its home page (Boards), so nothing was asked.")
            print("Sign in at app.traderepublic.com until the home page shows, then run this again.")
        print("Attach diagnose-documents.json and the survey file beside it in the")
        print("Diagnostics folder to the Trade Republic issue on GitHub. Both hold")
        print("counts and yes or no only, never a date, an amount or your details.")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document. Downloads nothing,
        and captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='Trade Republic',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Trade Republic Statements - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Months known:              {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Months with no statement:  {s['no_statement']}",
            f"Wrong month refused:       {s.get('wrong_document', 0)}",
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
        if lists_what_it_saved(s, self.args):
            atomic_write_text(
                self.paths.root / "new-this-run.txt",
                f"# {len(new_files)} file(s) downloaded on this run "
                f"({s['ended']}):\n" + NEW_LIST_NOTE
                + "\n".join(sorted(new_files)) + "\n")
            if new_files:
                print(f"\n{len(new_files)} NEW file(s) downloaded this run "
                      f"(listed in new-this-run.txt).")
        if s["no_statement"]:
            print(f"\n{s['no_statement']} month(s) answered with no statement PDF. They are "
                  "asked again on the next run.")
        report_run_result(s)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Local supervised Trade Republic statement downloader (read-only)")
    for name, help_text in [
            ("login", "verify connection to your signed-in browser"),
            ("discover", "list the months the statement route reaches; writes discovery.json"),
            ("pilot", "download a sample of the newest monthly statements"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "ask the newest months once each and write counts for a tester to send"),
            ("record", "record your own path to a document, so this app can be repaired (downloads nothing)"),
            ]:
        ap.add_argument(f"--{name}", action="store_true", help=help_text)
    ap.add_argument("--apply", action="store_true",
                    help="with --rename, actually rename (default is a preview)")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan filenames and save nothing (the session proof still asks one statement)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--start-date")
    ap.add_argument("--end-date")
    ap.add_argument("--max-docs", type=int)
    ap.add_argument("--type", help="Statement (Trade Republic account statements)")
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
        if app.stats["mode"] in ("discover", "rename"):
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
