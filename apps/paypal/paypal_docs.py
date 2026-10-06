"""PayPal monthly statement downloader (local, supervised).

Reads the monthly statements list on the signed-in PayPal Statements &
Taxes page, through the same endpoint the page uses, called from inside
the page, and saves each month's statement PDF. Nothing on that page is
clicked. A business account's statements are read from its own
statements page instead, from the list that page gets for itself, and
each is taken by pressing its row's Download control. The site layer,
paypal_site.py, holds every fact about paypal.com.

Usage:
    python paypal_docs.py --login       verify connection to your browser
    python paypal_docs.py --discover    list available documents
    python paypal_docs.py --pilot       download the 5 newest, then stop
    python paypal_docs.py --all         download everything in scope
    python paypal_docs.py --resume      continue an interrupted run
    python paypal_docs.py --verify      re-validate every saved PDF
    python paypal_docs.py --diagnose    dump page structure (no downloads)
    python paypal_docs.py --dry-run     plan filenames, save nothing

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N  --type Statement

READ-ONLY: this tool only reads the statements list and saves the PDFs
PayPal already generated. It never sends or requests money, transfers a
balance, applies for credit, saves an offer, or changes any account
setting. Everything stays on this machine; nothing is sent to any
external service.
"""
from __future__ import annotations

import json

from paperpull_core import delivery
from paperpull_core import failure
from paperpull_core import identity
from paperpull_core import renaming
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import report_run_result

import argparse
import logging
import random
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import doc_types, receipt_pdf
from paperpull_core import browser as browser_launcher
import paypal_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import migrate_account_keys as _migrate_account_keys
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_json, atomic_write_text, build_pdf_filename,
                     load_config, now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("paypal_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}

# Whether the last run that read PayPal's list read all of it, for Resume,
# which reads no list of its own. A run that stopped on the way left the
# list it knows short, or empty, and Resume used to call that complete.
LISTING_FILE = "last-listing.json"

# Why a business statement waits in Manual Review rather than being filed.
# The note its record carries, the word its row of the index gets and what
# its failure file says, for each.
REFUSED_NOTE = ("It names other days than it was listed under", "Names other days",
                "it names other days than it was listed under")
UNCHECKED_NOTE = ("Its days could not be checked in its own text", "Not checked",
                  "its days could not be checked in its own text")
TIED_NOTE = ("It names the days of a statement ending on the same day as plainly as its "
             "own", "Ties another statement",
             "it names another statement ending the same day as plainly")


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One PayPal document."""

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
        self.document_id = document_id  # unused, kind plus period is the identity
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
        """Stable identity. Category, date, title and account. PayPal has
        no document id, a statement is its month. The account part is empty
        for this site and kept so the key reads like every other statement
        app's."""
        if self.document_id:
            return f"id:{self.document_id}"
        # Keep the last four. Cutting to forty characters made two cards
        # of the same product collide, because the masked digits that say
        # which one it is sit at the end, and the second card's whole
        # history was then read as already downloaded and dropped.
        acct = _account_component(sanitize_component(self.account or ""))
        return f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"

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
        # A business account's statements are on another page of PayPal's
        # and are taken by a press (paypal_site, business section). Whether
        # the run is on one, the list that page last answered in the tab,
        # why it did not come when it did not, and whether a list said more
        # follow and this run could not read them.
        self._business = False
        self._reports = None
        self._unlisted = None
        self._listing_cut_short = False
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
            # Reuse the person's own tab on PayPal's site, the page they left
            # open for this. With none open, a tab of this run's own is
            # opened, never a tab of another site, since the session is a
            # cookie a new tab shares (tabs.new_tab). Matched on the parsed
            # host, never a substring, since "provider.com" in an address also
            # matches "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            dom = [p for p in live if site.is_safe_url(p.url or "")]
            self._work_page = dom[0] if dom else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # A personal account's PDF arrives as bytes from an in-page fetch. A
        # business statement's comes from a press, as a download Playwright
        # keeps where it keeps its own, or as a blob of the page's. The
        # browser is never pointed at a folder.
        self._dl_dir = None
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
            print("\n!! PayPal appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_documents(page)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9276")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS.get("documents") or site.URLS["home"]
        # A real Edge or Chrome first, the browser the site was mapped
        # in, and one signed-in tab is all the requests need.
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        print("Checking the connection to your signed-in PayPal browser...\n")
        page = self.page()
        ok = self._open_statements(page)
        challenge = site.detect_security_challenge(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run --login.")
        elif site.looks_signed_out(page):
            print("Connected, but PayPal shows a signed-out page.")
            print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
        elif ok:
            print("Success: connected and signed in to PayPal.")
            if self._business:
                print("It is a business account, and the list of its statements came")
                print("from Activity, All Reports, Statements.")
            print("Keep that browser window OPEN, then run:  paperpull paypal pilot")
        elif isinstance(self._unlisted, site.ReportsUnread):
            self._say_reports_unread(self._unlisted)
        elif isinstance(self._unlisted, site.SentElsewhere):
            self._say_sent_elsewhere(self._unlisted)
        else:
            where = site.landed_elsewhere(page)
            if where:
                # Say where PayPal sent the tab, a business account's
                # settings in #61, rather than send the person looking for
                # a page that account may not have.
                self._say_sent_elsewhere(site.SentElsewhere(
                    where, business=site.is_business_page(page.url or "")))
            else:
                print("Connected, but I could not open the PayPal statements page.")
                print("Open Settings, Statements & Taxes in that browser yourself, then run --diagnose.")
        self.close()

    def _open_statements(self, page) -> bool:
        """Whether the statements were seen. A personal account's statements
        page, or for a business account the list its own statements page
        gets as it loads, which is what proves its session (the list, never
        the absence of a sign-in page). When a business account's list did
        not come, why not is kept in _unlisted."""
        self._unlisted = None
        if site.goto_documents(page):
            return True
        if not site.is_business_page(page.url or ""):
            return False
        self._business = True
        landed = page.url or ""
        view = site.open_reports(page)
        self._reports = view
        if not view.listed:
            self._unlisted = site.why_unlisted(page, view, landed)
        return view.listed

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
        """Record one statement (a RawDoc) the list showed. Returns 1 if
        new. Its download link rides along in href."""
        title = re.sub(r"\s+", " ", (r.title or "")).strip()
        if not title:
            return 0
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        category, summary, confidence = doc_types.classify_document(title, self.rules)
        if not doc_types.wanted(category, self.config):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        date = (r.date_text or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date, _ = site.parse_period_date(title)
            date = date or ""
        floor = self.args.start_date or self.config.get("default_start_date")
        if floor and (not date or date < floor):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        # An account name, where a site has one, goes into the summary.
        # PayPal lists one account per sign-in, so this is empty.
        acct = (r.account or "").strip()
        full_summary = f"{acct} {summary}".strip() if acct else summary
        doc = Document(title=title, category=category, summary=full_summary,
                       date=date, confidence=confidence, source_url=source_url,
                       account=acct, href=r.href or "",
                       period=getattr(r, "period", "") or "")
        if self.discovery.get(doc.key) is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        # refresh the download link, in case it changed
        self.discovery.update(doc.key, {"source_url": source_url, "href": r.href or ""}, save=False)
        return 0

    def _read_statements(self, page):
        """The statements list, from one load of the statements page.

        A sign-in page or a security check goes to the person at the
        console, and the list is asked for once more after they have dealt
        with it. Nothing else is tried twice. This used to open the page,
        open it again, load it fresh and load it once more after a
        failure, and a business account's settings came back all four
        times (#61)."""
        try:
            return site.collect_download_docs(page)
        except site.SessionExpired:
            if not (site.looks_signed_out(page) or site.detect_security_challenge(page)):
                raise
            self.check_session(page)
        return site.collect_download_docs(page)

    def _say_sent_elsewhere(self, e, stopping: bool = False) -> None:
        """What the run saw instead of the statements, and what would show
        this app the way. Said once, with no traceback."""
        print(f"\n!! PayPal opened {e.where} instead of the statements page.")
        if e.business:
            print("   That is a business account's settings page, not a sign-in page,")
            print("   so signing in again would not change it.")
        else:
            print("   That is not a sign-in page, and not a page this app knows.")
        if getattr(e, "reports", False):
            print("   A business account keeps its statements under Activity, All")
            print("   Reports, and that page did not open with its list either.")
        if stopping:
            print("   So the run stops here rather than load it again. Nothing was")
            print("   downloaded.")
        print("   Either of these would show this app the way to your statements.")
        print("     Record, then click your way to one monthly statement in the")
        print("       browser window and open it, then stop the recording. Nothing")
        print("       you type is recorded.")
        print("     Diagnose, which reads the page and downloads nothing.")
        print('   Both are under "more" in the panel, or --record and --diagnose')
        print("   from a terminal. Read the file it writes in the Diagnostics")
        print("   folder, then attach it to the PayPal issue on GitHub.")

    def _say_reports_unread(self, e, stopping: bool = False) -> None:
        """A business account's statements page opened and its list never
        came. Said once, with no traceback."""
        print(f"\n!! PayPal's business statements page ({e.where}) opened, and the")
        print("   list it gets for itself never arrived, or came in a shape this")
        print("   app does not read. This app reads that list as the page loads and")
        print("   never asks for it itself.")
        if stopping:
            print("   So the run stops here. Nothing was downloaded.")
        print("   Run Diagnose, which reads that page and presses nothing, then read")
        print("   the file it writes in the Diagnostics folder and attach it to the")
        print("   PayPal issue on GitHub.")

    def _say_business_listing(self, listing) -> None:
        """What a business account's list held, the statements taken and every
        report left alone, so nothing is skipped without a word."""
        counts = listing.counts
        rows = sum(counts.values())
        print(f"\nPayPal's list of business statements held {rows} report(s).")
        print(f"  {counts.get(site.READY, 0)} ready PDF statement(s) this app takes.")
        if counts.get(site.OTHER_TYPE):
            print(f"  {counts[site.OTHER_TYPE]} in another kind of file, like CSV, left alone.")
        if counts.get(site.NOT_READY):
            print(f"  {counts[site.NOT_READY]} not ready yet. A later run takes each once PayPal")
            print("    has it ready. This app never asks PayPal to prepare one.")
        unread = len(listing.unread)
        if unread:
            print(f"  {unread} this app could not read, a status, a kind of file or the")
            print("    days it covers it does not know. Each was left alone and is")
            print("    counted as failed, and the file this run writes says what kind")
            print("    of value it was without saying the value.")
            same = listing.counts.get(site.UNREAD_SAME_DAY, 0)
            if same:
                print(f"    That count includes {same} known only by the day PayPal made them,")
                print("    the same day as another, so which is which could not be told.")
        if not listing.whole:
            print("  PayPal said more of the list follows, and this app could not page")
            print("    to it with the list's own next-page control.")

    def _listing_done(self, whole: bool) -> None:
        """Note whether this run read PayPal's whole list, for Resume."""
        try:
            atomic_write_json(self.paths.root / LISTING_FILE,
                              {"complete": bool(whole), "at": now_iso()})
        except OSError as e:
            log.info("could not note how the list was read: %s", e)

    def _last_listing(self) -> str:
        """"complete" or "stopped" for the last run that read PayPal's list,
        "" when none has said, as an install from before this knew."""
        try:
            got = json.loads((self.paths.root / LISTING_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        if not isinstance(got, dict) or not isinstance(got.get("complete"), bool):
            return ""
        return "complete" if got["complete"] else "stopped"

    def _stop_if_cut_short(self) -> None:
        """A run that read only part of PayPal's list did not finish, and must
        not read as a clean one. Once it has used what came, it leaves on
        SystemExit the way a run leaves on a sign-out, which the panel
        reports as a run that stopped."""
        if self._listing_cut_short:
            print("\nPayPal's list said more statements follow, and this app could not")
            print("page to them, so this run stops here rather than finish. Everything")
            print("it saved is kept. Run Diagnose and attach the file it writes to the")
            print("PayPal issue on GitHub.")
            raise SystemExit(0)

    def cmd_discover(self, quiet: bool = False) -> int:
        # Not whole until this has read all of PayPal's list. Noted first, so
        # every way out before the end leaves it so, a sign-in page or a
        # check that stops the run at the console's prompt among them.
        self._listing_done(False)
        page = self.page()
        n_new = 0
        try:
            docs = self._read_statements(page)
        except site.SentElsewhere as e:
            self._say_sent_elsewhere(e, stopping=True)
            raise SystemExit(0)
        except site.ReportsUnread as e:
            self._business = True
            self._say_reports_unread(e, stopping=True)
            self.write_failure("read the statements list", "the list never arrived")
            raise SystemExit(0)
        except site.SessionExpired as e:
            # Once, and in words. It used to leave as a traceback.
            print(f"\n!! PayPal did not hand over the statements list ({e}).")
            print("   Nothing was downloaded. If the browser window asks you to sign")
            print("   in, sign in there and run this again. If it stops here again,")
            print("   run Diagnose and attach its file to the PayPal issue on GitHub.")
            raise SystemExit(0)
        business = isinstance(docs, site.Listing)
        for r in docs:
            n_new += self._record_rawdoc(r, site.REPORTS_PAGE if business else site.BILLING_URL)
        self.discovery.save()
        log.info("Monthly statements: %d statements, %d new", len(docs), n_new)
        if business:
            self._business = True
            self._reports = docs.view
            self._listing_cut_short = not docs.whole
            self._say_business_listing(docs)
            if docs.unread:
                # Refused rather than guessed past, and written down, so the
                # run does not finish clean with a statement it never read.
                self.stats["failed"] += len(docs.unread)
                self.write_failure("read the statements list", "a row could not be read",
                                   postmortem={"rows": sum(docs.counts.values()),
                                               "unread": docs.unread[:20]})
        self._listing_done(not self._listing_cut_short)

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
            return bool(p and Path(p).exists()
                        and receipt_pdf.validate_pdf(Path(p), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing --------------------------------------------------------

    def _on_its_site(self):
        """The tab the next document is taken in, on PayPal's own site and
        never a tab of another site. PayPal keeps its session in a cookie a
        new tab shares, so with no tab of the person's on the site the
        documents page is opened in a tab of this run's own
        (tabs.on_its_site)."""
        return tabs.on_its_site(self, site.is_safe_url, "PayPal",
                                self._open_documents)

    def _open_documents(self, page):
        """PayPal's documents page, opened by its address the way discovery
        opens it. For a business statement that is the business statements
        page, whose list is kept for the press that follows."""
        if self._business:
            self._reports = site.open_reports(page)
            if not self._reports.listed:
                self.check_session(page)
                self._reports = site.open_reports(page)
            return
        if not site.goto_documents(page):
            self.check_session(page)
            site.goto_documents(page)

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
            # A business statement is known by its record, so its page is the
            # one opened for it, whatever the last run's was, and its page's
            # selectors are the ones the journal counts.
            self._business = site.business_ref(doc.href) is not None
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
                # Already explained by download_one. Stop rather than grind
                # through the rest producing empty "manual review" entries,
                # and stop as a stop. Returning here was read as a run that
                # finished clean, with nothing to look at (review of #61).
                print("Stopped. Everything downloaded so far is saved.")
                raise SystemExit(0)
            except (site.ReportsUnread, site.SentElsewhere) as e:
                # The business statements list did not come, so none of the
                # rest can be found either. Said once, and a stop.
                if isinstance(e, site.ReportsUnread):
                    self._say_reports_unread(e)
                else:
                    self._say_sent_elsewhere(e)
                self.write_failure("read the statements list", "the list never arrived")
                print("Stopped. Everything downloaded so far is saved.")
                raise SystemExit(0)
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    def _business_view(self, page):
        """The business statements list as the tab draws it now. What the last
        load heard is used while the tab still shows that page and has not
        been paged forward since, a list that never came included, so a
        page that did not answer is not loaded once more for nothing. The
        page is loaded again otherwise."""
        view = self._reports
        if view is not None and view.tab is page and view.forward == 0 \
                and site.on_reports(page):
            return view
        self._reports = site.open_reports(page)
        return self._reports

    def _business_rivals(self, ref) -> tuple:
        """The business statements listed beside this one, the ones a wrong
        document would most likely be, so its check compares the rows it
        could be confused with (identity.rivals_for)."""
        mine = ref.identity()
        if mine is None:
            return ()
        listed = []
        for rec in self.discovery.data.values():
            other = site.business_ref((rec or {}).get("href", ""))
            known = other.identity() if other is not None else None
            if known is not None and known not in listed:
                listed.append(known)
        listed.sort(key=lambda known: known.date)
        if mine not in listed:
            return ()
        return identity.rivals_for(listed, listed.index(mine))

    def _take_business(self, page, doc: Document, ref, out_path) -> Optional[bool]:
        """One business statement, pressed for in its own row and taken by the
        core's delivery, which arms every way a document can arrive before
        the press and checks it names the statement's days before it is
        put in place. A blob or an address the page saved it through is the
        way in only when nothing arrived (site.taken_from_the_page). True
        when it was saved and its days were found in its text, False when
        nothing usable came, and None when it is already recorded, a wrong
        document refused or a statement kept for review."""
        view = self._business_view(page)
        if not view.listed:
            why = site.why_unlisted(page, view)
            if isinstance(why, site.SessionExpired):
                print("\n  !! PayPal showed a sign-in page or a check instead of the")
                print("     business statements. Sign in again in the open browser,")
                print("     then press Resume to carry on.")
                self._record(doc, State.DISCOVERED, notes="Session expired before download")
            raise why
        rivals = self._business_rivals(ref)
        request, why = site.statement_request(page, ref, view, rivals=rivals)
        if request is None:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Not pressed for, because %s" % why)
            self._write_row(doc, "Not pressed for", "Needs Manual Review")
            self.write_failure("find the statement row", why)
            self.stats["manual_review"] += 1
            print(f"  Nothing was pressed for this statement, because {why}.")
            print("  It is marked for manual review, and a later run tries it again.")
            return None
        # A statement that names other days than it was listed under is kept
        # for a person in Manual Review rather than destroyed, unless
        # refuse_wrong_documents is set, as in every other app that checks.
        # The check can be wrong too, and a destroyed statement is one nobody
        # can look at, pressed for and destroyed again on every run. So the
        # delivery never destroys one here, and _destroyed decides.
        got = delivery.deliver(
            page, request, out_path,
            is_safe_url=site.is_safe_url, dl_dir=self._dl_dir, rivals=rivals,
            settle_ms=site.BUSINESS_SETTLE_MS, journal=self.journal, strict=False)
        if got.outcome in (delivery.NOTHING, delivery.NOT_A_PDF):
            data = site.taken_from_the_page(page, out_path)
            if data:
                got = delivery.place(data, out_path, expect=request.expect, rivals=rivals,
                                     journal=self.journal, strict=False)
        print("  %s" % got.say())
        if not got.ok:
            return False
        verdict = got.verdict.outcome if got.verdict is not None else identity.UNCHECKED
        if verdict == identity.REFUSED:
            if not self._destroyed(doc, out_path, got.verdict):
                self._to_review(doc, out_path, REFUSED_NOTE, got.verdict)
            return None
        if verdict != identity.VERIFIED:
            self._to_review(doc, out_path, UNCHECKED_NOTE, got.verdict)
            return None
        if self._ties_one_ending_the_same_day(out_path, request.expect, rivals):
            self._to_review(doc, out_path, TIED_NOTE, got.verdict)
            return None
        return True

    def _destroyed(self, doc: Document, out_path, verdict) -> bool:
        """With refuse_wrong_documents set, a statement whose text names
        another statement's days better than its own is not kept at all, as
        in every other app that checks, but only when it had a day of its
        own to be checked by (Verdict.checked). One whose first and last day
        are both other statements' days too had nothing of its own to count,
        so nothing says it is not this one, and it goes to Manual Review even
        then. True when it was destroyed."""
        if not self.config.get("refuse_wrong_documents", False):
            return False
        if verdict is None or not verdict.checked:
            return False
        try:
            out_path.unlink()
        except OSError as e:
            log.info("could not remove the refused statement: %s", e)
            return False
        why = "the statement that came does not name the days it was listed under"
        doc.pdf_path = doc.pdf_filename = ""
        self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
        self._write_row(doc, "Wrong document", "Needs Manual Review")
        self.write_failure("save the document", why)
        self.stats["manual_review"] += 1
        self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        print("  Nothing was saved for it. The file was destroyed rather")
        print("  than filed under this statement's name.")
        return True

    @staticmethod
    def _ties_one_ending_the_same_day(path, mine, rivals) -> bool:
        """Whether the saved statement's text names a statement listed as
        ending on the same day as this one as plainly as this one, the two
        compared alone (identity.distinguish with the other asked for).
        Among the whole list a statement's own days can all be shared, a
        custom statement's first day with July's and its last day with
        August's, and then nothing of it was counted, so a custom statement
        naming the first of August among its payments was filed as August's.
        Compared alone each keeps its first day, and a text naming both first
        days as plainly is neither's to file."""
        if mine is None:
            return False
        for rival in rivals or ():
            if rival == mine or getattr(rival, "date", "") != mine.date:
                continue
            if identity.distinguish(path, rival, [mine]).outcome == identity.VERIFIED:
                return True
        return False

    def _to_review(self, doc: Document, out_path, note, verdict=None) -> None:
        """Keep a business statement for a person to look at, never filed.
        One that names other days than it was listed under, one whose days
        could not be checked, a scan or one known only by the day it was
        made, and one naming a statement that ends on the same day as plainly
        as its own each go to Manual Review with a note saying which (`note`,
        one of the *_NOTE tuples). One that cannot be moved there is copied
        there and then removed, so it is never left in the archive under its
        name. When it cannot be removed either, its record points at it where
        it still is and says so."""
        why, word, failed = note
        review = unique_path(self.paths.manual_review, out_path.name,
                             self.config["max_path_length"])
        try:
            out_path.replace(review)
            kept, left = review, False
        except OSError as e:
            log.info("could not move the statement to Manual Review: %s", e)
            kept = self._copied(out_path, review)
            try:
                out_path.unlink()
                left = False
            except OSError as gone:
                log.info("could not remove it from the archive either: %s", gone)
                left = True
        if left:
            doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
            why += (", and it could not be removed from where it was saved, so it is "
                    "still there under the name it would have been filed by")
            if kept is not None:
                why += ", with a copy in Manual Review"
        elif kept is None:
            doc.pdf_path = doc.pdf_filename = ""
            why += ", and it could not be moved to Manual Review, so it was not kept"
        else:
            doc.pdf_path, doc.pdf_filename = str(kept), kept.name
        self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
        self._write_row(doc, word, "Needs Manual Review")
        self.write_failure("check the saved statement", failed,
                           postmortem={"identity": verdict.report()} if verdict else None)
        self.stats["manual_review"] += 1
        if left:
            print("  %s. Move it out of that folder yourself." % why)
        elif kept is None:
            print("  %s. A later run takes it again." % why)
        else:
            print("  %s, so it was put in Manual Review rather than filed." % why)

    @staticmethod
    def _copied(source, review) -> Optional[Path]:
        """A copy of the statement in Manual Review, for when it could not be
        moved there, or None when that failed too, with no part of one left."""
        try:
            shutil.copyfile(str(source), str(review))
            return review
        except OSError as e:
            log.info("could not copy the statement to Manual Review: %s", e)
            try:
                review.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def download_one(self, page, doc: Document, filename: str):
        """Save one statement. For a personal account the site layer asks
        for the PDF from inside the signed-in page and hands back the bytes.
        A business statement is pressed for in its own row (_take_business)."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        ref = site.business_ref(doc.href)
        # The last of the document id, used only if the name is taken.
        # Two documents on one day used to differ by " (2)", which says
        # nothing about which is which and moves between them when a file
        # is deleted (#49, and the same complaint on #43). A business
        # statement has no id, and two ending on the same day are told apart
        # by the first day each covers, the same name on every run.
        mark = (ref.start or ref.created) if ref is not None else (doc.document_id or "")[-6:]
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=mark)
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        if ref is not None:
            saved = self._take_business(page, doc, ref, out_path)
            if saved is None:
                return
        else:
            if not site.goto_documents(page):
                self.check_session(page)
                site.goto_documents(page)
            try:
                saved = site.download_bill(page, self._dl_dir, doc.date, out_path,
                                           href=doc.href, title=doc.title)
            except site.SessionExpired:
                # Stop the whole run. Continuing would file every remaining
                # statement as "manual review" and finish looking successful
                # while having saved nothing.
                print("\n  !! PayPal answered with a sign-in page instead of a statement.")
                print("     Your session has expired. Sign in again in the open")
                print("     browser, then run:  paperpull paypal resume")
                self._record(doc, State.DISCOVERED, notes="Session expired before download")
                raise
        # A capture that failed must not leave a convincing empty file behind.
        if out_path.exists() and (out_path.stat().st_size == 0
                                  or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            saved = False
        if not saved:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF")
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
        doc.downloaded_ok = True   # done for good, even if the file is deleted later
        self._record(doc, State.COMPLETED)
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
            print(f"This downloads ALL available PayPal documents ({scope}).")
            print("Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover()
        docs = self._select()
        print(f"\nDownloading {len(docs)} document(s)...")
        self.process(docs, dry_run=self.args.dry_run)
        self._stop_if_cut_short()

    def cmd_resume(self):
        """Carry on with the statements the last list held. Resume reads no
        list of its own, so when no run has read PayPal's list to its end,
        or the last one stopped before it did, it says so and leaves as a
        run that stopped. It used to say everything was complete, and the
        panel reported a clean run, after a run had stopped on a business
        account's settings page with nothing listed at all."""
        self.stats["mode"] = "resume"
        listing = self._last_listing()
        if not self.discovery.data and listing != "complete":
            print("Nothing to resume. No PayPal statements have been listed yet,")
            print("because no run has read PayPal's list to its end. Run Pilot or")
            print("Run All, which read the list first.")
            raise SystemExit(0)
        docs = [d for d in self._select() if not self._already_done(d)]
        if not docs and listing != "stopped":
            print("Nothing to resume - everything in scope is complete.")
            return
        if docs:
            print(f"Resuming: {len(docs)} document(s) remaining.")
            self.process(docs, dry_run=self.args.dry_run)
        else:
            print("Nothing left to resume from the statements listed so far.")
        if listing == "stopped":
            print("\nThe last run stopped before it read PayPal's whole list, so there")
            print("may be statements this app has not seen. Run Pilot or Run All to")
            print("read the list again.")
            raise SystemExit(0)


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
            self._journal = Journal(getattr(self, "_work_page", None), self._selectors())
        return self._journal

    def _selectors(self):
        """The selectors the journal and a failure file count. The business
        statements page's on a business account's run, since judged against
        that page the personal statements page's matched nothing and the
        file said they were wrong."""
        if getattr(self, "_business", False):
            return site.BUSINESS_FALLBACK
        return getattr(site, "FALLBACK", None)

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
            selectors=getattr(site, "FALLBACK", None) if not getattr(self, "_business", False)
            else site.BUSINESS_FALLBACK,
            journal=self._journal,
            requests=self._requests,
            provider='PayPal', text=text, extra=extra)
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
            selectors=self._selectors(),
            journal=self._journal,
            requests=self._requests,
            provider='PayPal')

    def cmd_diagnose(self):
        """Survey the statements page and what the list holds, and
        write a file a person can attach to a GitHub issue. No screenshot,
        digit runs masked, JSON bodies as shape only. Nothing is downloaded
        and nothing is clicked. For a business account the business
        statements page is surveyed as well (site.survey_business), its list
        answer as shapes, each report's status, kind of file and days as
        written, and one ready statement's Download control as it reads,
        without pressing it."""
        self.stats["mode"] = "diagnose"
        words = words_for('PayPal', site)
        page = self.page()
        info = {"timestamp": now_iso(),
                "note": Fixed("What the PayPal statements list looks like, "
                              "so the site layer can be repaired against it.")}
        try:
            found = site.goto_documents(page)
            info["documents_page_found"] = found
            info["landed_on"] = site.redact(page.url)
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            business = not found and site.is_business_page(page.url or "")
            info["business_account"] = business
            # So the survey written beside this counts the business page's
            # own selectors.
            self._business = business
            info["survey"] = site.survey(page)
            if found:
                site.expand_all(page)
                site.scroll_full_page(page)
            info["row_counts"] = {}
            for name, sel in [("doc_row", site.FALLBACK["doc_row"]),
                              ("table rows", "table tbody tr"),
                              ("pdf links", "a[href*='.pdf']"),
                              ("download attrs", "a[download]")]:
                try:
                    info["row_counts"][name] = page.locator(sel).count()
                except Exception as e:
                    info["row_counts"][name] = f"ERR {e}"
            found_docs = site.collect_download_docs(page) if found else []
            info["documents_recognized"] = [{"date": b.date_text, "kind": b.kind,
                                             "account": site.redact(b.account)}
                                            for b in found_docs[:40]]
            docs = site.collect_documents(page)
            info["rows_collected"] = len(docs)
            info["samples"] = []
            for d in docs[:12]:
                cat, summ, conf = doc_types.classify_document(d.title, self.rules)
                date, period = site.parse_period_date(d.text or d.title)
                info["samples"].append({
                    "title": d.title[:90], "href": (d.href or "")[:100],
                    "text": (d.text or "").replace("\n", " | ")[:160],
                    "category": cat, "summary": summ, "date": date, "period": period})
            if business:
                # Last, so the tab is left on the business statements page.
                info["business"] = site.survey_business(page)
        except Exception as e:
            info["error"] = str(e)[:300]
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        print(f"Documents page found: {shape_tree(info.get('documents_page_found', '?'), words)}, "
              f"documents recognized: {len(info.get('documents_recognized', []))}, "
              f"rows: {shape_tree(info.get('rows_collected', '?'), words)}")
        found_business = info.get("business") or {}
        if found_business:
            if found_business.get("listed"):
                print(f"The business statements list came, with "
                      f"{shape_tree(found_business.get('rows', 0), words)} report(s) in it.")
            else:
                print("The business statements list did not come.")
        print("Look through that file for anything you would not want public,")
        print("then attach it to the PayPal issue on GitHub. No screenshot was taken.")

    # -- summary -----------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='PayPal',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "PayPal Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
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
        description="Local supervised PayPal document downloader (read-only)")
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
    ap.add_argument("--type", help="Statement (the only kind this app saves)")
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
