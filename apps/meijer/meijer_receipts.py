"""Meijer purchase-history & receipt downloader (local, supervised).

Usage:
    python meijer_receipts.py --login
    python meijer_receipts.py --discover
    python meijer_receipts.py --pilot            (newest few orders)
    python meijer_receipts.py --all
    python meijer_receipts.py --resume
    python meijer_receipts.py --verify
    python meijer_receipts.py --review-names
    python meijer_receipts.py --diagnose [--order-number N]
    python meijer_receipts.py --dry-run

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-purchases N  --order-number N

Everything runs locally. No receipt data leaves this machine.
Authentication is always manual (--login opens a browser and waits for you).
"""
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

from paperpull_core import classification, receipt_pdf
from paperpull_core import browser as browser_launcher
import meijer_site as site
from paperpull_core.models import (IN_STORE, ONLINE, Item, Purchase, State)
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, JsonStore, ORDER_HISTORY_COLUMNS, Paths,
                     RECEIPT_INDEX_COLUMNS, atomic_write_text, build_pdf_filename, load_config, now_iso, title_case,
                     unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
def _reason_words(reason: str) -> str:
    """Why a receipt failed its check, in words of the app's own. The check's
    own text can quote an error that carries a file path, and so the
    account's name, and the attempt file this goes into is posted publicly
    (review of 0.41.0)."""
    r = (reason or "").lower()
    for key, words in (("does not mention", "its words are not this purchase's"),
                       ("zero bytes", "it is empty"),
                       ("smaller than minimum", "it is too small"),
                       ("missing %pdf", "it is not a PDF"),
                       ("could not open", "it could not be opened"),
                       ("cannot read", "it could not be read"),
                       ("no pages", "it has no pages"),
                       ("does not exist", "it is not there")):
        if key in r:
            return words
    return "it failed its check"


log = logging.getLogger("meijer_receipts")

# What the file a tester attaches says an attempt came to, beside the
# press's own outcomes in meijer_site. Words of the fixed list only.
DROPPED_OFF = "dropped off the list"
LIST_DID_NOT_LOAD = "the list did not load"
PUT_ASIDE = "put aside in manual review"

# Marks a purchase's record in progress.json once its rows as no longer
# listed are in the CSVs, so they are written once (see _no_longer_listed).
UNLISTED_ROWS = "unlisted_rows_written"


def _today():
    """Today's date, asked for here so that a test can say which day it is."""
    return datetime.now().date()


def _months_before(day, months: int):
    """The day `months` months before `day`, or the last day of that month
    when it has fewer days."""
    import calendar
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return day.replace(year=year, month=month,
                       day=min(day.day, calendar.monthrange(year, month)[1]))


def ask(prompt: str) -> str:
    """input() that stops cleanly (progress already saved by callers) when
    no interactive console is attached, instead of corrupting the run."""
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this command from a real console window (use the .bat files).")
        raise SystemExit(3)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class App:
    _journal = None
    _requests = None
    # Purchases in a row whose list did not show on either look, and how
    # many of those end the run (see _list_did_not_load).
    _lists_missed = 0
    LISTS_MISSED_TO_STOP = 3
    # The purchases this run's discovery found on Meijer's list. None of
    # them is ever taken for one it no longer lists (see _dropped_off).
    _listed_now = frozenset()
    # The kinds of purchase whose rows this run's discovery read. Without
    # its own reading of the In-Store tab, as in Resume, a run never says a
    # store receipt has dropped off the list.
    _kinds_read = frozenset()
    # Every attempt this run wrote down for a tester, in the order they
    # came, and which purchase of the run is being worked on, as (its place,
    # how many in all). See _write_attempt.
    _attempts = None
    _place = (0, 0)

    def __init__(self, args):
        self.args = args
        # --config lets one copy of the code serve several people/accounts:
        # each config points at its own output_dir, profile_dir and port, so
        # progress.json, the CSVs, the PDFs and the browser session are all
        # kept separate. Nothing is ever re-downloaded across accounts.
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

        self.order_csv = CsvFile(self.paths.order_history_csv,
                                 ORDER_HISTORY_COLUMNS, self.paths.backups)
        self.index_csv = CsvFile(self.paths.receipt_index_csv,
                                 RECEIPT_INDEX_COLUMNS, self.paths.backups)
        self.rules = classification.load_rules()

        self._pw = None
        self._context = None
        self._browser = None
        self._work_page = None
        self._cdp_mode = False
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "online_discovered": 0,
            "receipts_downloaded": 0,
            "skipped_completed": 0, "canceled": 0, "no_receipt": 0,
            "no_longer_listed": 0,
            "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
            "validation_failures": 0, "dates_processed": [], "new_files": [],
        }

    # -- infrastructure -----------------------------------------------------

    def _setup_logging(self):
        logfile = self.paths.logs / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
        fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        logging.basicConfig(level=logging.INFO, format=fmt,
                            handlers=[logging.FileHandler(logfile, encoding="utf-8"),
                                      logging.StreamHandler(sys.stdout)])
        logging.getLogger("pypdf").setLevel(logging.ERROR)

    def _delay(self, factor: float = 1.0):
        lo = float(self.config["delay_min_seconds"]) * factor
        hi = float(self.config["delay_max_seconds"]) * factor
        time.sleep(random.uniform(lo, hi))

    def browser(self):
        """Return the supervised browser context.

        The default mode is CDP-attach: the user runs `login.bat`, which
        opens an ordinary Chromium and lets the user sign in as a human
        (handling any verification themselves). This tool then connects to
        that already-open browser over the DevTools protocol and reads the
        pages the user is authorized to see, so the sign-in and any
        multi-factor step stay entirely with the user and the session is
        never scripted. Plain Chromium is enough for Meijer - it does not block
        it - so no stealth or evasion is used anywhere. Set "cdp_url" to ""
        in config.json to fall back to launching a dedicated browser with
        its own persistent profile instead.
        """
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
                    f"Run login.bat first and keep that browser window OPEN.\n"
                    f"({e})")
            if not self._browser.contexts:
                raise SystemExit("Connected browser has no context; open a tab and retry.")
            self._context = self._browser.contexts[0]
            self._cdp_mode = True
            # Install the print-suppression hook at context level so any popup
            # window Meijer opens to print also has window.print() intercepted
            # (prevents the modal native print dialog from freezing the browser).
            try:
                self._context.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
            except Exception:
                pass
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
        """A dedicated work page carrying the print-suppression hook.

        In CDP mode a fresh page in the existing (authenticated) context
        shares the user's session AND receives our init script, existing
        human-opened tabs are left untouched."""
        ctx = self.browser()
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        if self._cdp_mode:
            self._work_page = ctx.new_page()
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            self._work_page.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
        except Exception:
            pass
        self.requests
        return self._work_page

    def close(self):
        # In CDP mode the browser belongs to the user: close only our own
        # work page and disconnect; never close the user's browser.
        try:
            if self._cdp_mode:
                if self._work_page is not None and not self._work_page.is_closed():
                    self._work_page.close()
            elif self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._work_page = None
        self._pw = None

    # -- session safety -----------------------------------------------------

    def check_session(self, page) -> bool:
        """Raise/pause on sign-out or security challenges.

        True when the person was asked to sign in again and the page was
        left on the order list, so a caller that had opened something
        else has to open it again before it reads anything. False
        otherwise."""
        # Both of these used to wait at a prompt. Under the panel there is
        # nobody to answer, and waiting there took the run down with an
        # end-of-file rather than saying what had happened, so when there
        # is no console the run stops on its own terms and says what to do
        # about it. Progress is already saved either way (#48).
        challenge = site.detect_security_challenge(page)
        if challenge:
            self.progress.save(backup=True)
            print(f"\n!! {challenge}")
            print("Processing stopped. Please resolve the challenge yourself in the")
            print("browser window. I will NOT attempt to bypass it.")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page looks normal again (or Ctrl+C to quit)... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
        if site.looks_signed_out(page):
            self.progress.save(backup=True)
            print("\n!! Meijer appears to have signed you out.")
            print("Please sign in manually in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in again... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)
            site.goto_orders(page)
            return True
        return False

    # -- commands -----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9266")
        profile = self.config["profile_dir"]
        url = site.URLS.get("orders") or site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def _look_at_orders(self, page):
        """Open the orders page and say what is there, as (listed,
        challenge).

        Only the list shows a signed-in session, its tabs, a row, or its own
        words that there are no orders. When it does not come the page is
        looked at again for a little while. The list can come a moment late,
        and a bot check can leave the page blank and a moment later turn it
        into the check, so one look at the blank page finds nothing to name.
        That one look is how --login said Success on a page with no list on
        it."""
        if site.goto_orders(page):
            return True, site.detect_security_challenge(page)
        challenge = site.challenge_after_a_moment(page)
        return site.orders_listed(page), challenge

    def _open_orders(self, page) -> None:
        """Open the orders page and go on only once its list is there.

        Discovery used to go on from a page the list never came to, find no
        rows on it and finish as though there were no orders, so a run read
        as clean with its new receipts missed."""
        while True:
            listed, challenge = self._look_at_orders(page)
            if listed:
                # Checked once below, as it always was. Going round again
                # here would ask forever about a word on a page that is fine.
                break
            if challenge or site.looks_signed_out(page):
                # Asked about, or under the panel the run stops there.
                self.check_session(page)
                continue
            self.progress.save(backup=True)
            print("\n!! Your Meijer orders did not load, so this cannot find any of")
            print("them. Look at the browser window. If Meijer is asking you to prove")
            print("you are a person, to sign in, or for a code, answer it there")
            print("yourself. I will NOT attempt to bypass it.")
            self.write_failure("open the order list", "the order list did not appear")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page shows your orders (or Ctrl+C to quit)... ") is None:
                print("Once it shows your orders, run this again.")
                raise SystemExit(0)
        self.check_session(page)

    def _read_both_tabs(self, page) -> list:
        """Open the orders page and read the rows on both of its tabs, each
        once its rows show.

        A tab whose rows did not come is not a tab with nothing on it. The
        In-Store rows come only after that tab is pressed, and they used to
        be read at the press's own pause, so rows that came later were read
        as none, and the Online tab's "You haven't placed any orders yet" was
        then taken to speak for both tabs, which told a run with receipts
        to find that there were none. Before that, the Online tab's words
        were believed before anything opened the other tab, and a tester who
        only shops in the store was told twice that the account had no
        orders (#42). What the In-Store tab says when there are no receipts
        has not been seen, so a tab without rows is never read as empty.

        When one tab gave rows, the run goes on with them and says which tab
        showed nothing. When neither did, nothing is claimed, and the run
        asks the person to look, or stops under the panel, as it does when
        the orders page itself does not load."""
        while True:
            self._open_orders(page)
            facts: dict = {}
            found = site.collect_both_tabs(page, facts)
            self._kinds_read = frozenset(facts.get("read") or ())
            unread = facts.get("unread") or []
            if found and not unread:
                return found
            # Rows that showed and were gone again by the time they were read
            # leave no tab named, and then both are.
            named = unread or ["In-Store Receipts", "Online Orders"]
            where = "Meijer's %s %s" % (" and ".join(named), "tab" if len(named) == 1 else "tabs")
            seconds = site.LIST_WAIT_MS // 1000
            if found:
                # The tab was looked at for the whole wait, and a Pilot or Run
                # All still presses the receipts found on it before, so this
                # says only what discovery found there.
                print(f"\nNothing showed on {where} within {seconds} seconds, so this run")
                print("found nothing new there. The next run looks again.")
                return found
            self.progress.save(backup=True)
            print(f"\n!! Nothing showed on {where} within {seconds} seconds, so this")
            print("cannot say whether there is anything there to find. Look at the browser")
            print("window. If Meijer is asking you to prove you are a person, to sign in, or")
            print("for a code, answer it there yourself. I will NOT attempt to bypass it.")
            self.write_failure("read both tabs of the order list", "a tab showed nothing")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page shows your receipts (or Ctrl+C to quit)... ") is None:
                print("Once it shows them, run this again.")
                raise SystemExit(0)

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode: the browser is launched by login.bat (not here). This
            # just verifies we can connect and that you are signed in.
            print("Checking the connection to your signed-in Meijer browser...\n")
            page = self.page()
            listed, challenge = self._look_at_orders(page)
            if challenge:
                print(f"!! {challenge}")
                print("Resolve it yourself in the browser window, then re-run --login.")
            elif site.looks_signed_out(page):
                print("Connected, but Meijer shows the signed-out page.")
                print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
            elif listed:
                print("Success: connected to your signed-in Meijer session.")
                print("Keep that browser window OPEN, then run the diagnostics or pilot.")
            else:
                print("Connected, but your Meijer orders did not load, so this cannot say")
                print("whether you are signed in. Look at the browser window. If Meijer")
                print("asks you to prove you are a person, to sign in, or for a code,")
                print("answer it there yourself, keep the window OPEN, then re-run --login.")
            self.close()
            return
        print("Opening Meijer.com in a dedicated supervised browser profile.")
        print("Sign in manually (username, password, any verification codes).")
        print("This tool never touches your credentials.\n")
        page = self.page()
        page.goto(site.URLS["home"], wait_until="domcontentloaded", timeout=60000)
        # Under the panel there is no console to press Enter at, and this
        # used to read end-of-file and stop the run before it could check
        # anything, with a message about .bat files (#48). Nothing is
        # checked in that case because there is nothing to check yet, and
        # the browser is deliberately left open.
        if not browser_launcher.pause_for_sign_in():
            return
        listed, challenge = self._look_at_orders(page)
        if challenge:
            print(f"!! {challenge}")
            print("Resolve it yourself in the browser window, then run --login again.")
        elif site.looks_signed_out(page):
            print("It still looks like you are signed out; the orders page bounced to login.")
            print("Sign in in the browser, then run:  python meijer_receipts.py --login")
        elif listed:
            print("Signed-in session detected.")
        else:
            print("Your Meijer orders did not load, so this cannot say whether you")
            print("are signed in. Look at the browser window, answer anything Meijer")
            print("asks there yourself, then run --login again.")
        self.close()

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False) -> dict:
        """Discovery pass: the orders page, then ?page=2 and on
        until a page adds no order the earlier pages did not have."""
        page = self.page()
        n_new = 0
        floor = self.args.start_date or self.config.get("default_start_date")

        cards = []
        seen_texts = set()
        for page_no in range(1, 60):
            if page_no == 1:
                found = self._read_both_tabs(page)
            else:
                # What a page past the last one answers has not been seen,
                # so a later page is read as it always was. Signing in again
                # at a console leaves the page on the first page, which would
                # be read as this one, hold nothing new, and end the history
                # here. So this page is opened again for as long as the
                # check had to ask.
                site.goto_orders(page, page_no)
                while self.check_session(page):
                    site.goto_orders(page, page_no)
                found = site.collect_cards(page)
            fresh = [c for c in found if c.text not in seen_texts]
            log.info("Orders page %d: %d row(s), %d new", page_no, len(found), len(fresh))
            if not fresh:
                break
            for c in fresh:
                seen_texts.add(c.text)
            cards.extend(fresh)
        seen_keys = set()
        for card in cards:
            purchase = site.card_to_purchase(card)
            if not purchase:
                continue
            seen_keys.add(purchase.key)
            if floor and purchase.purchase_date and purchase.purchase_date < floor:
                continue  # before the cutoff: never record or download
            key = purchase.key
            if self.discovery.get(key) is None:
                rec = purchase.to_dict()
                rec["state"] = State.DISCOVERED.value
                self.discovery.update(key, rec, save=False)
                n_new += 1
            else:
                self.discovery.update(key, {
                    "details_url": purchase.details_url,
                    "receipt_url": purchase.receipt_url,
                    "total": purchase.total or self.discovery.get(key).get("total", ""),
                    "status": purchase.status or self.discovery.get(key).get("status", ""),
                    "store_info": purchase.store_info
                    or self.discovery.get(key).get("store_info", ""),
                }, save=False)
        dropped = self._drop_undated_leftovers(seen_keys)
        if dropped:
            log.info("Dropped %d undated purchase(s) an earlier version recorded "
                     "and this page no longer shows", dropped)
        self._listed_now = frozenset(seen_keys)
        again = self._listed_again(seen_keys)
        if again:
            print(f"\n{again} purchase(s) Meijer had stopped listing are on its list "
                  "again, so this run tries them again.")
        self.discovery.save()

        all_recs = list(self.discovery.data.values())
        self.stats["online_discovered"] = len(all_recs)

        if not quiet:
            print(f"\nDiscovery complete. Purchases known: {len(all_recs)}")
            by_year = {}
            for r in all_recs:
                y = (r.get("purchase_date") or "?")[:4]
                by_year[y] = by_year.get(y, 0) + 1
            summary = ", ".join(f"{y}: {c}" for y, c in sorted(by_year.items(), reverse=True))
            print(f"  ({summary or 'none'})")
            dates = sorted(r.get("purchase_date") for r in all_recs if r.get("purchase_date"))
            if dates:
                print(f"  Date range: {dates[0]} .. {dates[-1]}")
        return {"new": n_new}

    def _drop_undated_leftovers(self, seen_keys) -> int:
        """Forget purchases an earlier version recorded with no date that
        this page no longer shows.

        0.33.0 read every in-store row without its date, and filed each as
        an online order under a key built from that dateless text. The rows
        now read properly and are recorded again under their real keys, so
        the old ninety-six sat beside the new ninety-six, and Pilot spent
        half its tries on purchases that do not exist (#42).

        Only a discovery that found rows does this, so a page that failed
        to load forgets nothing. A purchase with a date, one seen in this
        run, and anything ever downloaded are always kept, and the file is
        backed up before anything is dropped."""
        if not seen_keys:
            return 0
        stale = []
        for key, rec in self.discovery.data.items():
            if not isinstance(rec, dict) or rec.get("purchase_date") or key in seen_keys:
                continue
            done = self.progress.get(key) or {}
            if (done.get("downloaded_ok") or done.get("pdf_path") or done.get("pdf_filename")
                    or rec.get("pdf_path") or rec.get("pdf_filename")):
                continue
            stale.append(key)
        if stale:
            self.discovery.save(backup=True)
            for key in stale:
                del self.discovery.data[key]
        return len(stale)

    def _listed_again(self, seen_keys) -> int:
        """Put back every purchase written down as no longer listed that
        this discovery found on Meijer's list, so that it is tried as any
        other is. How many there were.

        Finding it on the list is the one thing that says Meijer lists it
        again. Until then later runs skip it (_already_done)."""
        again = 0
        for key in sorted(seen_keys):
            rec = self.progress.get(key)
            if not isinstance(rec, dict) or rec.get("state") != State.NO_LONGER_LISTED.value:
                continue
            self.progress.update(key, {"state": State.DISCOVERED.value}, save=False)
            if self.discovery.get(key) is not None:
                self.discovery.update(key, {"state": State.DISCOVERED.value}, save=False)
            again += 1
        if again:
            self.progress.save()
        return again

    # -- selection ----------------------------------------------------------

    def _select_purchases(self, ptype: Optional[str] = None,
                          limit: Optional[int] = None,
                          newest_first: bool = True) -> List[Purchase]:
        args = self.args
        records = list(self.discovery.data.values())
        purchases = [Purchase.from_dict(r) for r in records
                     if isinstance(r, dict) and r.get("order_number")]
        if ptype:
            purchases = [p for p in purchases if p.purchase_type == ptype]
        if args.order_number:
            purchases = [p for p in purchases if p.order_number == args.order_number]
        if args.year:
            purchases = [p for p in purchases if p.purchase_date.startswith(str(args.year))]
        # Hard floor: never process orders before the configured start date
        # (You already has 2024-and-earlier Meijer receipts).
        floor = args.start_date or self.config.get("default_start_date")
        if floor:
            purchases = [p for p in purchases
                         if p.purchase_date and p.purchase_date >= floor]
        if args.start_date:
            purchases = [p for p in purchases if p.purchase_date and p.purchase_date >= args.start_date]
        if args.end_date:
            purchases = [p for p in purchases if p.purchase_date and p.purchase_date <= args.end_date]
        purchases.sort(key=lambda p: p.purchase_date or "0000", reverse=newest_first)
        limit = limit if limit is not None else args.max_purchases
        if limit:
            purchases = purchases[:limit]
        return purchases

    def _already_done(self, purchase: Purchase) -> bool:
        """Skip purchases already handled. A receipt that was successfully
        downloaded once is done FOR GOOD - it is not re-downloaded even if you
        later delete the PDF (e.g. after importing it into paperless-ngx). Use
        --redownload to override and fetch everything in scope again."""
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(purchase.key)
        if not rec:
            return False
        if rec.get("downloaded_ok"):
            return True
        state = rec.get("state")
        # terminal / already-completed (incl. records made before the
        # downloaded_ok marker existed): done, do not re-download.
        #
        # Not "no receipt available". Every Meijer receipt row has one, so
        # that state only ever meant this app failed to press it, and 0.34.2
        # wrote it for ten purchases it had looked for on the wrong tab.
        # Treated as final it would have hidden those receipts for good.
        # Nothing was saved for them, so trying again fetches nothing twice.
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.CANCELED.value):
            return True
        # Meijer no longer lists it, so its tab has no row for it to press,
        # and looking for it took two loads of the orders page every run. A
        # discovery that finds it on the list again puts it back
        # (_listed_again).
        if state == State.NO_LONGER_LISTED.value:
            return True
        # A copy put aside for review counts as done while it is still in
        # Manual Review, and deleting it is how a person asks for the receipt
        # again (#42). Trying it again on its own every run added a copy a run,
        # and replacing the earlier copy could replace another purchase's
        # (reviews of 0.41.0).
        if state == State.NEEDS_MANUAL_REVIEW.value:
            pdf_path = rec.get("pdf_path", "")
            return bool(pdf_path and Path(pdf_path).exists()
                        and receipt_pdf.validate_pdf(
                            Path(pdf_path), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing core ----------------------------------------------------

    def process_purchases(self, purchases: List[Purchase], dry_run: bool = False):
        page = self.page()
        for i, purchase in enumerate(purchases, 1):
            self._place = (i, len(purchases))
            print(f"\n[{i}/{len(purchases)}] {purchase.purchase_type} "
                  f"{purchase.purchase_date or '(date unknown)'} "
                  f"#{purchase.order_number}")
            if self._already_done(purchase):
                rec = self.progress.get(purchase.key) or {}
                if (rec.get("state") == State.NO_LONGER_LISTED.value
                        and not rec.get("downloaded_ok")):
                    # Not done, and never said to be. There is nothing on the
                    # list to fetch it from.
                    print("  Meijer no longer lists it, so it is skipped. A run whose "
                          "discovery finds it listed again tries it again.")
                    self.stats["no_longer_listed"] = self.stats.get("no_longer_listed", 0) + 1
                    continue
                if (rec.get("state") == State.NEEDS_MANUAL_REVIEW.value
                        and not rec.get("downloaded_ok")):
                    # A copy put aside counts as done while it is in Manual
                    # Review. It never passed its check, and this line used
                    # to say it had, to a tester asking why it was skipped (#42).
                    print("  Put aside in Manual Review by an earlier run, so it is skipped. "
                          "Delete it there to have it fetched again.")
                else:
                    print("  Already completed and PDF verified - skipping.")
                self.stats["skipped_completed"] += 1
                continue
            # Which document the run is on, so a failure file says how far
            # it got and whether it ever reached a second one.
            try:
                self.journal.op("next_item" if i > 1 else "open_item",
                                "take a document", ordinal=i)
            except Exception:
                pass
            try:
                self.process_one(page, purchase, dry_run=dry_run)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress is saved; run --resume to continue.")
                raise
            except Exception as e:
                log.exception("Unhandled failure on %s", purchase.key)
                self._record_state(purchase, State.FAILED, notes=f"Unhandled error: {e}")
                self.stats["failed"] += 1
            self._delay()

    def process_one(self, page, purchase: Purchase, dry_run: bool = False):
        # The order row already gave the date, total and description.
        # There is no details page to open, the receipt is the document.
        if not (page.url or "").startswith(site.ORDERS_URL):
            site.goto_orders(page)
        self.check_session(page)
        self._record_state(purchase, State.DETAILS_EXTRACTED)
        if purchase.purchase_date:
            self.stats["dates_processed"].append(purchase.purchase_date)

        # ---- classify (local, deterministic) ----
        cls = classification.classify_items(purchase.items, self.rules)
        purchase.summary = cls.summary
        purchase.confidence = cls.confidence
        review_needed = cls.confidence == classification.LOW
        notes_extra = f"Items: {'; '.join(i.name for i in purchase.items[:12])}" \
            if review_needed and purchase.items else ""
        print(f"  {len(purchase.items)} item(s); summary: {cls.summary} "
              f"[{cls.confidence}] ({cls.notes})")

        # ---- canceled orders: record, no receipt expected ----
        if re.search(r"cancell?ed", purchase.status or "", re.I):
            self._record_state(purchase, State.CANCELED,
                               notes="Order canceled; no receipt downloaded")
            self._write_csv_rows(purchase, receipt_status="Canceled",
                                 processing_status=State.CANCELED.value,
                                 notes_extra=notes_extra)
            self.stats["canceled"] += 1
            print("  Canceled order - recorded, no receipt.")
            return

        if dry_run:
            filename = build_pdf_filename(purchase.purchase_date, purchase.summary, record=purchase)
            print(f"  DRY RUN - would save: {filename}")
            return

        # ---- locate + save receipt ----
        saved = self._save_receipt(page, purchase)
        if not saved:
            return  # state already recorded inside

        # ---- CSVs + progress ----
        receipt_status = "Downloaded"
        if (self.progress.get(purchase.key) or {}).get(UNLISTED_ROWS):
            self._forget_unlisted_rows(purchase)
        self._write_csv_rows(purchase, receipt_status=receipt_status,
                             processing_status="Review Needed" if review_needed else "Completed",
                             notes_extra=notes_extra)
        final_state = State.NEEDS_MANUAL_REVIEW if review_needed else State.COMPLETED
        self._record_state(purchase, final_state,
                           notes=("Low classification confidence" if review_needed else ""))
        if review_needed:
            self.stats["manual_review"] += 1
        self.journal.checkpoint('a document is saved')
        self.stats["receipts_downloaded"] += 1
        print(f"  Saved: {purchase.pdf_filename}")

    # -- receipt saving -----------------------------------------------------

    def _save_receipt(self, page, purchase: Purchase) -> bool:
        """Save the order's receipt as a verified PDF.

        The row's receipt link is fetched from inside the signed-in page.
        When the answer is a PDF it is saved as it is. When it is a page,
        that page is opened, cut down to the receipt block and rendered
        with printToPDF. Nothing is clicked, the link's own address is
        followed, and the native print dialog is never involved.
        """
        if site.looks_signed_out(page):
            print("  Meijer is asking you to verify your sign-in.")
            print("  Complete it in the browser window (password, code or passkey).")
            self.check_session(page)
            if site.looks_signed_out(page):
                self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                   notes="Could not pass re-authentication")
                self.stats["manual_review"] += 1
                return False

        url = purchase.receipt_url or ""
        # An in-store receipt's row has a PDF icon and no link at all, so
        # the row itself is asked first when there is nothing to fetch (#42).
        if not url or not site.is_receipt_address(url):
            folder = self.paths.folder_for(purchase.purchase_type, "Receipt")
            filename = build_pdf_filename(purchase.purchase_date, purchase.summary, "Receipt", record=purchase)
            out_path = unique_path(folder, filename, self.config["max_path_length"],
                                   distinguisher=purchase.order_number)
            trace: list = []
            body, listed, found = self._press_its_row(page, purchase, trace)
            if body:
                purchase.document_type = "Receipt"
                self._record_state(purchase, State.RECEIPT_LOCATED)
                out_path.write_bytes(body)
                log.info("Capture path: the row's own receipt control")
                # This path has no page to print again, so the one retry is a
                # second press of the same control. Until 0.41.0 it said it
                # was retrying and never did (#42).
                if self._finish_pdf(page, purchase, out_path, source_page=None,
                                    again=lambda: site.press_row_receipt(page, purchase, trace)):
                    return True
                if purchase.pdf_path:
                    trace.append({"note": "the receipt was put aside",
                                  "reason": _reason_words(getattr(self, "_last_reason", "")),
                                  "pdf": site.pdf_facts(Path(purchase.pdf_path))})
                self._write_attempt(page, purchase, trace, PUT_ASIDE)
                return False
            if not listed:
                self._write_attempt(page, purchase, trace, LIST_DID_NOT_LOAD)
                return self._list_did_not_load(purchase)
            # The list showed and the row gave nothing. This used to say of
            # every such purchase that its row carried no receipt or details
            # link, which was never what happened, and to write it into both
            # CSVs on every run that looked for it again (#42).
            return self._not_pressed(page, purchase, trace, found)

        purchase.document_type = "Receipt"
        folder = self.paths.folder_for(purchase.purchase_type, purchase.document_type)
        filename = build_pdf_filename(purchase.purchase_date, purchase.summary, purchase.document_type, record=purchase)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=purchase.order_number)
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1
        self._record_state(purchase, State.RECEIPT_LOCATED)

        try:
            data = site.fetch_receipt_bytes(page, url)
            if data:
                log.info("Capture path: receipt link answered with a PDF")
                out_path.write_bytes(data)
                return self._finish_pdf(page, purchase, out_path, source_page=None)
            log.info("Capture path: receipt page printed to PDF")
            site.goto_receipt_page(page, url)
            # Signing in again at a console leaves the page on the order
            # list, which has amounts and the word order on it, so the list
            # would be printed and filed as this receipt. The receipt is
            # opened again for as long as the check had to ask.
            while self.check_session(page):
                site.goto_receipt_page(page, url)
            site.scroll_full_page(page)
            # The page has to be this order's receipt before anything is
            # taken from it. The orders page shows the order's date and
            # total, which the check on the saved file would find, and a
            # page that is not the receipt says nothing about whether there
            # is one, so it is not recorded as having none, which is final.
            why = site.not_this_purchase(page, url)
            if why:
                return self._refuse_page(purchase, why)
            if not site.receipt_is_present(page):
                self._record_state(purchase, State.NO_RECEIPT_AVAILABLE,
                                   notes="Receipt page did not show a receipt")
                self._write_csv_rows(purchase, receipt_status="No printable receipt available",
                                     processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                     notes_extra="Receipt page did not render")
                self.stats["no_receipt"] += 1
                self.write_failure('find the receipt', 'there was no receipt to save')
                self.stats["manual_review"] += 1
                print("  Receipt page did not render - marked for manual review.")
                return False
            purchase = site.extract_details(page, purchase)
            self._capture_document(page, purchase, out_path)
            return self._finish_pdf(page, purchase, out_path, source_page=page)
        except Exception as e:
            log.exception("PDF generation failed for %s", purchase.key)
            self._record_state(purchase, State.FAILED, notes=f"PDF generation failed: {e}")
            self.stats["failed"] += 1
            return False

    def _press_its_row(self, page, purchase: Purchase, trace: list):
        """The receipt from the purchase's own row, as (its bytes or None,
        whether its list showed on either look, what the last look that
        showed it found).

        The orders page is opened on the purchase's tab and its rows are
        waited for before the row is pressed. When that gives nothing the
        page is opened once more, after a pause, and the row looked for
        again. His Run All met a page holding only the list's heading after
        most of the list had been saved, looked once, and wrote the purchase
        down as a row with no receipt (#42).

        What a look found is what the press found ("outcome"), and for a row
        that is not on the page, whether the purchase has dropped off
        Meijer's list ("dropped") and the oldest date the list shows
        ("oldest"). It has dropped off only when every look that showed the
        list found so."""
        listed = False
        found: dict = {}
        judged = []
        for look in range(2):
            if look:
                self._delay(2)
            site.goto_orders(page)
            # The page just opened is the one the row is read from, so it is
            # the one checked. Only the page the previous purchase left
            # behind used to be.
            while self.check_session(page):
                site.goto_orders(page)
            shown = site.show_list_for(page, purchase.purchase_type)
            trace.append({"note": "the purchase's tab", "opened": bool(shown.get("opened")),
                          "rows": int(shown.get("rows") or 0)})
            if not shown.get("rows"):
                continue
            listed = True
            self._lists_missed = 0
            pressed: dict = {}
            body = site.press_row_receipt(page, purchase, trace, facts=pressed)
            if not body and pressed.get("outcome") == site.NOT_ON_THE_PAGE:
                body = self._press_once_settled(page, purchase, trace, pressed)
            if body:
                return body, True, {}
            found = {"outcome": pressed.get("outcome") or site.NO_PDF}
            if found["outcome"] == site.NOT_ON_THE_PAGE:
                found.update(self._dropped_off(page, purchase, pressed, shown, trace))
            judged.append(bool(found.get("dropped")))
        if found:
            found["dropped"] = all(judged)
        return None, listed, found

    def _press_once_settled(self, page, purchase: Purchase, trace: list, pressed: dict):
        """The receipt from a row the press did not find, once the list has
        stopped changing. Its bytes or None, and `pressed` then says what the
        last press found and whether the list was seen whole ("final").

        A row is not called missing until the count of the tab's rows has
        stayed the same for a while (site.settle_rows), counted on from the
        press's own looks. A list read while it was still filling left out
        the rows it had not drawn yet, and a purchase among them looked like
        one Meijer no longer lists. Once the count has stopped, the list is
        scrolled to its end (site.scroll_to_end), since a list can draw more
        of itself as it is scrolled. Whenever the count changed, the row is
        looked for once more, and a list that drew more as it was scrolled
        was never seen whole, however it ends."""
        kind = purchase.purchase_type
        settled = site.settle_rows(page, kind, seen=(pressed.get("rows"), pressed.get("since")))
        if settled["changed"]:
            pressed.clear()
            body = site.press_row_receipt(page, purchase, trace, facts=pressed)
            if body or pressed.get("outcome") != site.NOT_ON_THE_PAGE:
                return body
            settled = site.settle_rows(page, kind, seen=(pressed.get("rows"), pressed.get("since")))
        scrolled = {"changed": False}
        if settled["settled"] and not settled["changed"]:
            scrolled = site.scroll_to_end(page, kind)
            if scrolled["changed"]:
                pressed.clear()
                body = site.press_row_receipt(page, purchase, trace, facts=pressed)
                if body or pressed.get("outcome") != site.NOT_ON_THE_PAGE:
                    return body
        whole = bool(settled["settled"] and not settled["changed"] and not scrolled["changed"])
        pressed["final"] = whole
        trace.append({"note": "the rows once they settled", "rows": int(settled["rows"]),
                      "settled": whole, "more_after_scrolling": bool(scrolled["changed"])})
        return None

    def _dropped_off(self, page, purchase: Purchase, pressed: dict, shown: dict,
                     trace: list) -> dict:
        """Whether a purchase whose row is not on its tab has dropped off
        Meijer's list, as {"dropped", "oldest"}, the date of the oldest row
        the list shows.

        Meijer appears to list about two years of store receipts. A tester's
        three oldest had dropped off, and each was looked for twice on every
        run and written down as a row with no receipt (#42). A list that
        shows only part of what Meijer holds looks the same, though, behind
        a Load more button or a pager, under a filter it remembers, or cut
        short while Meijer slows requests, and a purchase is said to have
        dropped off only when every one of these holds (review).

        It is a store receipt. Its tab was opened on this look, and the list
        was seen whole, its rows stopped changing and drew no more when
        scrolled to its end. No control shows that would show more of it or
        a narrower part of it, and a control that could not be read counts.
        Every row of its kind shows a date, the oldest of them is at least
        WHOLE_LIST_MONTHS old, and the purchase is older still. This run's
        own discovery read the In-Store rows, so Resume never decides it,
        and did not find this purchase among them. Anything else stays a
        failure the next run looks for again, an online order among them,
        since the Online tab may go on over later pages, which discovery
        reads and a row is never looked for on."""
        kind = purchase.purchase_type
        now = site.listed_rows(page, kind)
        oldest = now["oldest"]
        older = bool(purchase.purchase_date and oldest and purchase.purchase_date < oldest)
        back = bool(oldest and oldest <= _months_before(
            _today(), site.WHOLE_LIST_MONTHS).isoformat())
        more = site.more_controls(page)
        opened = bool(shown.get("opened"))
        read = IN_STORE in self._kinds_read
        listed = purchase.key in self._listed_now
        trace.append({"note": "the oldest row the list shows", "rows": int(now["rows"]),
                      "earlier_than_every_row": older, "listed_by_discovery": listed,
                      "tab_opened": opened, "controls_read": more is not None,
                      "more_controls": int(more or 0), "back_twenty_months": back,
                      "discovery_read_the_tab": read})
        dropped = (kind == IN_STORE and opened and bool(pressed.get("final")) and more == 0
                   and back and read and older and not listed)
        return {"dropped": dropped, "oldest": oldest}

    # What is said of a purchase whose list showed and whose row gave no
    # receipt, by what the press found.
    _NOT_PRESSED = {
        site.NOT_ON_THE_PAGE: "Its row is not on Meijer's {tab} tab, so nothing was pressed.",
        site.MORE_THAN_ONE_ROW: "More than one row on Meijer's {tab} tab fits this purchase, "
                                "so none was pressed.",
        site.NO_RECEIPT_CONTROL: "Its row on Meijer's {tab} tab has nothing that reads as its "
                                 "receipt, so nothing was pressed.",
        site.NO_PDF: "Pressing the receipt link on its row brought no PDF.",
    }

    def _not_pressed(self, page, purchase: Purchase, trace: list, found: dict) -> bool:
        """A purchase whose list showed and whose row gave no receipt.

        One that has dropped off Meijer's list is written down as no longer
        listed (_no_longer_listed). Any other is a failure, said as what the
        press found, and the next run looks for it again. A failure goes
        into neither CSV, since it would go in again on every run that looked
        for it. Neither is counted for manual review, where there is nothing
        to look at."""
        if found.get("dropped"):
            self._write_attempt(page, purchase, trace, DROPPED_OFF, say=False)
            return self._no_longer_listed(purchase, found.get("oldest") or "")
        outcome = found.get("outcome") or site.NO_PDF
        tab = site.TAB_LABELS.get(purchase.purchase_type, purchase.purchase_type)
        said = self._NOT_PRESSED.get(outcome, self._NOT_PRESSED[site.NO_PDF]).format(tab=tab)
        self._record_state(purchase, State.FAILED, notes=said)
        self.stats["failed"] += 1
        print(f"  {said} The next run looks for it again.")
        self._write_attempt(page, purchase, trace, outcome)
        self.write_failure("find the receipt", outcome)
        return False

    def _no_longer_listed(self, purchase: Purchase, oldest: str) -> bool:
        """Write down a purchase Meijer no longer lists, and say so.

        Nothing failed and nothing was put aside, so no failure file is
        written and nothing counts for review. It goes into both CSVs once,
        so a spend summary built from the Order History still counts it,
        as it counted such a purchase before, and never again, whatever
        later runs find. Later runs skip it (_already_done) until a
        discovery finds it on the list again (_listed_again), and if its
        receipt is then saved, these rows give way to the saved receipt's
        (_forget_unlisted_rows)."""
        tab = site.TAB_LABELS.get(purchase.purchase_type, purchase.purchase_type)
        written = (self.progress.get(purchase.key) or {}).get(UNLISTED_ROWS)
        self._record_state(purchase, State.NO_LONGER_LISTED,
                           notes=f"Meijer's {tab} tab no longer lists it. Its oldest row "
                                 f"is from {oldest}.", extra={UNLISTED_ROWS: True})
        if not written:
            self._write_csv_rows(purchase, receipt_status="No longer listed",
                                 processing_status=State.NO_LONGER_LISTED.value)
        self.stats["no_longer_listed"] = self.stats.get("no_longer_listed", 0) + 1
        print(f"  Meijer no longer lists this purchase. Its {tab} tab goes back to {oldest}, "
              "and this purchase is older, so there is no row to press. Later runs skip it "
              "unless Meijer lists it again.")
        return False

    def _forget_unlisted_rows(self, purchase: Purchase) -> None:
        """Take out of both CSVs the rows written for a purchase while
        Meijer no longer listed it, before the rows of its saved receipt go
        in, so that it stays one purchase there. Only rows of this purchase
        that say it was no longer listed are taken out, and each file is
        backed up before it is rewritten."""
        for book in (self.order_csv, self.index_csv):
            rows = book.read_all()
            kept = [r for r in rows if not (
                r.get("Purchase Type") == purchase.purchase_type
                and r.get("Order or Receipt Number") == purchase.order_number
                and r.get("Processing Status") == State.NO_LONGER_LISTED.value)]
            if len(kept) != len(rows):
                book.rewrite(kept)
        self.progress.update(purchase.key, {UNLISTED_ROWS: False})

    def _list_did_not_load(self, purchase: Purchase) -> bool:
        """A purchase whose tab showed no rows on either look.

        Its row was never seen, so it is not written down as a row without a
        receipt, and the next run looks for it again. One of them never ends
        the run. Three in a row do, since Meijer is then not answering, and
        asking again for every purchase left would only ask it more often."""
        self._lists_missed += 1
        self._record_state(purchase, State.FAILED,
                           notes=f"The {purchase.purchase_type} list did not load")
        self.stats["failed"] += 1
        self.write_failure("open the purchase list", "the list did not load")
        print(f"  The {purchase.purchase_type} list did not load, so this receipt was not "
              "looked for. The next run looks for it again.")
        if self._lists_missed >= self.LISTS_MISSED_TO_STOP:
            self.progress.save(backup=True)
            print(f"\n!! The {purchase.purchase_type} list did not load for "
                  f"{self._lists_missed} purchases in a row.")
            print("Meijer may be slowing requests down, so nothing more is asked of it now.")
            print("Wait a while, then press Resume to carry on from where this stopped.")
            raise SystemExit(0)
        return False

    def _refuse_page(self, purchase: Purchase, why: str) -> bool:
        """Leave a page that is not this order's receipt unprinted, as Best
        Buy does. A receipt filed under another order's name is worse than
        none, because nobody looks for it. Nothing is saved and the order
        is asked for again on the next run. `why` is fixed words from
        paperpull_core.page_check, never the page's."""
        said = why[:1].upper() + why[1:]
        self._record_state(purchase, State.NEEDS_MANUAL_REVIEW, notes=said)
        self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        self.stats["manual_review"] += 1
        self.write_failure("check the receipt", why)
        print(f"  {said}, so nothing was saved.")
        return False

    def _capture_document(self, target_page, purchase: Purchase,
                          out_path: Path, content_kind: str = "") -> None:
        """Render the Meijer order-details receipt to PDF.

        Meijer ships NO print stylesheet, so printing the page as-is captures the
        whole site (nav, promo banners, footer) across three cluttered pages.
        site.isolate_receipt hides everything except the purchase-summary
        block first - a live-DOM display change only, discarded on the next
        navigation - which leaves a clean one-page receipt for CDP
        Page.printToPDF.
        """
        # Strip the site chrome so only the receipt is printed.
        site.isolate_receipt(target_page)
        try:
            log.info("Capture path: isolated order-details printToPDF")
            receipt_pdf.print_page_to_pdf(target_page, out_path)
            return
        except Exception as e:
            log.warning("Live printToPDF failed (%s); trying fallbacks", e)
        # Fallback: a print iframe still in the DOM.
        frame = site.find_printing_frame(target_page, wait_ms=2000)
        if frame is not None:
            try:
                log.info("Capture path: live print iframe")
                receipt_pdf.print_frame_to_pdf(target_page, frame, out_path)
                return
            except Exception as e:
                log.warning("Print-iframe capture failed (%s); falling back", e)
        # Last resort: the HTML snapshot captured at print() time.
        snapshot = receipt_pdf.get_print_snapshot(target_page)
        if snapshot:
            log.info("Capture path: print-call HTML snapshot (%d chars)", len(snapshot))
            receipt_pdf.print_html_to_pdf(target_page, snapshot, out_path)
            return
        log.info("Capture path: plain page print")
        receipt_pdf.print_page_to_pdf(target_page, out_path)

    def _write_attempt(self, page, purchase: Purchase, trace: list, outcome: str,
                       say: bool = True) -> None:
        """What the press saw, to Diagnostics/download-attempt.json, for the
        tester to attach. Built only from what press_row_receipt and
        pdf_facts put in the trace, which never carry a receipt's words.

        Every attempt of the run is kept, in the order they came, each with
        its place in the run and what it came to, in words of this app's
        own. The file used to hold only the last, so a Run All that missed
        three purchases left a record of one (#42)."""
        if self._attempts is None:
            self._attempts = []
        place, of = self._place
        self._attempts.append({
            "place": place, "of": of, "outcome": Fixed(outcome),
            "timestamp": Fixed(now_iso()), "date": purchase.purchase_date,
            "landed_on": site.mask_href(page.url or ""), "responses": trace[:60]})
        attempt = self.paths.diagnostics / "download-attempt.json"
        write_shaped(attempt, {"attempts": self._attempts}, words_for('Meijer', site))
        if say:
            print(f"  What the page answered is in {attempt}, attach it to the issue.")

    def _in_review(self, path) -> bool:
        try:
            return Path(path).resolve().parent == self.paths.manual_review.resolve()
        except OSError:
            return False

    def _put_aside(self, out_path: Path) -> Path:
        """Move a receipt that failed its check into Manual Review, under a
        name of its own. A file already there is left where it is and never
        matched to itself (review of 0.41.0)."""
        if self._in_review(out_path):
            return out_path
        quarantine = unique_path(self.paths.manual_review, out_path.name,
                                 self.config["max_path_length"])
        try:
            out_path.replace(quarantine)
        except OSError:
            quarantine = out_path
        return quarantine

    def _second_capture(self, out_path: Path, tokens, first, take):
        """Take a receipt that failed its check once more, with `take(path)`,
        into a file beside the first under a name that is not a PDF. It takes
        the first one's place only if it passes, and the check's result is
        returned, `first` when it did not. A second print used to replace the
        first even when it failed too, a page that had moved on to "Your
        session has ended" in place of the receipt (review of 0.41.0)."""
        second = out_path.with_name(out_path.name + ".second")
        try:
            take(second)
            retried = receipt_pdf.validate_pdf(second, self.config["min_pdf_bytes"], tokens)
            if retried.ok:
                second.replace(out_path)
                return retried
        except Exception as e:
            log.warning("Retry failed: %s", e)
        finally:
            try:
                if second.exists():
                    second.unlink()
            except OSError:
                pass
        return first

    def _finish_pdf(self, page, purchase: Purchase, out_path: Path,
                    popup=None, source_page=None, again=None) -> bool:
        """Check a saved receipt, and put it aside for review if it fails.
        A receipt that fails is taken once more first, by printing
        `source_page` again, or by `again`, which takes it the way it was
        first taken and gives its bytes. A second capture that also fails
        never replaces the first."""
        purchase.pdf_path = str(out_path)
        purchase.pdf_filename = out_path.name
        self._record_state(purchase, State.PDF_SAVED)

        # A till receipt prints no number and names no item this check
        # could know, so the date and total its row showed count together
        # as well (#42), or the purchase's own when the list kept no record
        # of it.
        tokens = receipt_pdf.expected_tokens_for(
            purchase, listed=self.discovery.get(purchase.key) or purchase)
        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
        if not result.ok:
            self.stats["validation_failures"] += 1
            if again is not None:
                log.warning("Validation failed (%s); retrying once", result.reason)
                body = None
                try:
                    body = again()
                except Exception as e:
                    log.warning("Retry failed: %s", e)
                if body:
                    result = self._second_capture(out_path, tokens, result,
                                                  lambda path: path.write_bytes(body))
            elif source_page is not None:
                log.warning("Validation failed (%s); retrying once", result.reason)
                result = self._second_capture(
                    out_path, tokens, result,
                    lambda path: receipt_pdf.print_page_to_pdf(source_page, path))
            else:
                log.warning("Validation failed (%s)", result.reason)
        if not result.ok:
            # Quarantine the questionable file; never mark Completed.
            self._last_reason = result.reason
            quarantine = self._put_aside(out_path)
            purchase.pdf_path = str(quarantine)
            purchase.pdf_filename = quarantine.name
            self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                               notes=f"PDF validation failed: {result.reason}")
            self._write_csv_rows(purchase, receipt_status="Validation Failed",
                                 processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                 notes_extra=f"Validation: {result.reason}")
            self.stats["manual_review"] += 1
            print(f"  !! Validation failed ({_reason_words(result.reason)}); moved to Manual Review.")
            return False

        purchase.receipt_count = 1
        # Sticky marker: a valid PDF was produced, so this purchase is done for
        # good and will not be re-downloaded even if the file is later deleted.
        self._record_state(purchase, State.PDF_VERIFIED, extra={
            "pdf_size": result.size_bytes, "pdf_pages": result.page_count,
            "downloaded_ok": True})
        self.stats["new_files"].append(str(out_path))
        return True


    # -- records ------------------------------------------------------------

    def _record_state(self, purchase: Purchase, state: State,
                      notes: str = "", extra: Optional[dict] = None):
        purchase.state = state.value
        if notes:
            purchase.notes = (purchase.notes + "; " if purchase.notes else "") + notes
        rec = purchase.to_dict()
        if extra:
            rec.update(extra)
        self.progress.update(purchase.key, rec)  # atomic save on every update
        self.discovery.update(purchase.key, {"state": state.value})

    def _write_csv_rows(self, purchase: Purchase, receipt_status: str,
                        processing_status: str, notes_extra: str = ""):
        notes = "; ".join(x for x in (purchase.notes, notes_extra) if x)
        items = purchase.items or [Item(name="")]
        self.order_csv.append_rows([{
            "Account Holder": self.config.get("owner", ""),
            "Purchase Date": purchase.purchase_date,
            "Purchase Type": purchase.purchase_type,
            "Order or Receipt Number": purchase.order_number,
            "Order Status": purchase.status,
            "Item Name": it.name,
            "Quantity": it.quantity,
            "Unit Price": it.unit_price,
            "Line Item Total": it.line_total,
            "Order Total": purchase.total,
            "Fulfillment Method": it.fulfillment or purchase.fulfillment,
            "Return Status": it.return_status,
            "Purchase Summary": purchase.summary,
            "PDF Filename": purchase.pdf_filename,
            "Purchase Details URL": purchase.details_url,
            "Receipt URL": purchase.receipt_url,
            "Processing Status": processing_status,
            "Notes": notes,
        } for it in items])

        if purchase.pdf_filename or receipt_status != "Downloaded":
            prog = self.progress.get(purchase.key) or {}
            self.index_csv.append_rows([{
                "Account Holder": self.config.get("owner", ""),
                "Purchase Date": purchase.purchase_date,
                "Purchase Type": purchase.purchase_type,
                "Order or Receipt Number": purchase.order_number,
                "Order Total": purchase.total,
                "Purchase Summary": purchase.summary,
                "PDF Filename": purchase.pdf_filename,
                "PDF Full Path": purchase.pdf_path,
                "Document Type": purchase.document_type,
                "Receipt Status": receipt_status,
                "Receipt Count": purchase.receipt_count,
                "Classification Confidence": purchase.confidence,
                "Receipt URL": purchase.receipt_url,
                "PDF File Size": prog.get("pdf_size", ""),
                "PDF Page Count": prog.get("pdf_pages", ""),
                "Downloaded At": now_iso() if purchase.pdf_filename else "",
                "Verified At": now_iso() if prog.get("pdf_pages") else "",
                "Processing Status": processing_status,
                "Notes": notes,
            }])

    # -- modes --------------------------------------------------------------

    def cmd_pilot(self):
        self.stats["mode"] = "pilot"
        print("PILOT MODE - limited supervised test run.")
        self.cmd_discover(types=[ONLINE, IN_STORE], quiet=False)
        selected: List[Purchase] = self._select_purchases(
            ONLINE, limit=self.config["pilot_online"])
        selected += self._select_purchases(
            IN_STORE, limit=self.config.get("pilot_instore", 5))
        if not selected:
            print("\nNo purchases discovered to pilot. Run --diagnose to inspect pages.")
            return
        print(f"\nProcessing {len(selected)} pilot purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)
        self._pilot_report(selected)

    def _pilot_report(self, selected: List[Purchase]):
        print("\n" + "=" * 70)
        print("PILOT RESULTS - please inspect these files before approving a full run")
        print("=" * 70)
        problems = []
        for p in selected:
            rec = self.progress.get(p.key) or {}
            state = rec.get("state", "?")
            fn = rec.get("pdf_filename", "")
            print(f"\n  {p.purchase_type}  {rec.get('purchase_date', p.purchase_date)}  "
                  f"#{rec.get('order_number', p.order_number)}")
            print(f"    State:      {state}")
            print(f"    Summary:    {rec.get('summary','')} "
                  f"[confidence: {rec.get('confidence','')}]")
            print(f"    PDF:        {fn or '(none)'}")
            if fn:
                path = Path(rec.get("pdf_path", ""))
                exists = path.exists()
                size, pages = rec.get("pdf_size"), rec.get("pdf_pages")
                # Only a receipt that passed its check has its size and pages
                # written down, so one put aside in Manual Review read "? bytes,
                # ? pages" here while it was on disk (#42). It is measured.
                if exists and (size in (None, "") or pages in (None, "")):
                    facts = site.pdf_facts(path)
                    size = facts.get("bytes") if size in (None, "") else size
                    pages = facts.get("pages") if pages in (None, "") else pages
                print(f"    PDF exists: {exists}  "
                      f"({'?' if size in (None, '') else size} bytes, "
                      f"{'?' if pages in (None, '') else pages} pages)")
                if not exists:
                    problems.append(f"{p.key}: PDF missing")
            if state in (State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value,
                         State.NO_RECEIPT_AVAILABLE.value):
                problems.append(f"{p.key}: {state} - {rec.get('notes','')}")
        print("\n" + "-" * 70)
        if problems:
            print("Needs attention:")
            for pr in problems:
                print(f"  ! {pr}")
        else:
            print("No problems detected in the pilot.")
        print("\nPilot finished. Inspect the PDFs and CSVs in:")
        print(f"  {self.paths.root}")
        print("Nothing further will run until you explicitly start a full command,")
        print("e.g.:  python meijer_receipts.py --all")

    def cmd_run(self, types: List[str], mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Meijer purchase history")
            print(f"({', '.join(types)}). Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover(types=types, quiet=False)
        selected: List[Purchase] = []
        for t in types:
            selected += self._select_purchases(t)
        print(f"\nProcessing {len(selected)} purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)

    def cmd_resume(self):
        self.stats["mode"] = "resume"
        pend = [Purchase.from_dict(r) for r in self.discovery.data.values()
                if isinstance(r, dict) and r.get("order_number")]
        pend = [p for p in pend if not self._already_done(p)]
        pend.sort(key=lambda p: p.purchase_date or "0000", reverse=True)
        if self.args.max_purchases:
            pend = pend[:self.args.max_purchases]
        if not pend:
            print("Nothing to resume - all discovered purchases are complete.")
            return
        print(f"Resuming: {len(pend)} incomplete purchase(s).")
        self.process_purchases(pend, dry_run=self.args.dry_run)


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
            print("Receipt index is empty - nothing to verify.")
            return
        bad = 0
        seen_keys = {}
        for row in rows:
            path = row.get("PDF Full Path", "")
            key = f"{row.get('Purchase Type')}:{row.get('Order or Receipt Number')}"
            seen_keys[key] = seen_keys.get(key, 0) + 1
            if not path:
                continue
            result = receipt_pdf.validate_pdf(Path(path), self.config["min_pdf_bytes"])
            mark = "OK " if result.ok else "BAD"
            if not result.ok:
                bad += 1
                print(f"  {mark} {row.get('PDF Filename','')}: {result.reason}")
            row["Verified At"] = now_iso() if result.ok else row.get("Verified At", "")
        dups = {k: c for k, c in seen_keys.items() if c > 1}
        self.index_csv.rewrite(rows)
        print(f"\nVerified {len(rows)} index rows; {bad} problem(s).")
        if dups:
            print("Note: multiple index rows for these purchases (may be legitimate "
                  "multi-document orders):")
            for k, c in dups.items():
                print(f"  {k}: {c} rows")

    def _yours_to_rename(self, row) -> bool:
        """Whether a row of the index names a file this review may rename,
        one inside this app's own output folder.

        A row written for a purchase with no receipt has an empty path, which
        reads as the folder the app runs in, and that folder exists. A new
        summary typed for such a row had the app rename its own folder, and
        on Windows stopped with a traceback partway through, its earlier
        renames on disk and in progress.json and the CSVs left as they were
        (review)."""
        text = (row.get("PDF Full Path") or "").strip()
        if not text:
            return False
        try:
            path = Path(text).resolve()
            root = self.paths.root.resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        return root in path.parents and path.is_file()

    def cmd_review_names(self):
        rows = self.index_csv.read_all()
        # A row somebody already renamed is left out, even one renamed
        # before its confidence was marked High as well (#47). So is a row
        # that names no file of this app's own, which nothing here renames.
        review = [r for r in rows
                  if (r.get("Classification Confidence") == "Low"
                      or "Review" in (r.get("Processing Status") or ""))
                  and "renamed via --review-names" not in (r.get("Notes") or "")
                  and self._yours_to_rename(r)]
        if not review:
            print("No receipts need name review.")
            return
        print(f"{len(review)} receipt(s) need review. Enter a new summary, "
              "press Enter to keep, or 'q' to stop.\n")
        order_rows = self.order_csv.read_all()
        changed = False
        try:
            for r in review:
                key = f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}"
                prog = self.progress.get(key) or {}
                items = [i.get("name", "") for i in prog.get("items", [])][:10]
                print(f"  {r.get('Purchase Date')}  #{r.get('Order or Receipt Number')}"
                      f"  [{r.get('Classification Confidence')}]")
                print(f"    Current file: {r.get('PDF Filename')}")
                if items:
                    print(f"    Items: {'; '.join(items)}")
                new = ask("    New summary (blank=keep, q=quit): ").strip()
                if new.lower() == "q":
                    break
                if not new:
                    print()
                    continue
                new_summary = title_case(new)
                old_path = Path(r["PDF Full Path"].strip())
                date = r.get("Purchase Date") or old_path.name[:10]
                doc_type = r.get("Document Type") or "Receipt"
                new_name = build_pdf_filename(date, new_summary, doc_type, record=prog)
                new_path = unique_path(old_path.parent, new_name,
                                       self.config["max_path_length"])
                try:
                    old_path.rename(new_path)  # unique_path guarantees no overwrite
                except OSError as e:
                    print(f"    It could not be renamed ({type(e).__name__}), so it keeps "
                          "its name.\n")
                    continue
                old_filename = r.get("PDF Filename")
                r["PDF Filename"] = new_path.name
                r["PDF Full Path"] = str(new_path)
                r["Purchase Summary"] = new_summary
                r["Processing Status"] = "Completed"
                r["Classification Confidence"] = "High"
                r["Notes"] = (r.get("Notes", "") + "; renamed via --review-names").strip("; ")
                for orow in order_rows:
                    if (orow.get("Order or Receipt Number") == r.get("Order or Receipt Number")
                            and orow.get("PDF Filename") == old_filename):
                        orow["PDF Filename"] = new_path.name
                        orow["Purchase Summary"] = new_summary
                        orow["Processing Status"] = "Completed"
                self.progress.update(key, {  # key (purchase identifier) unchanged
                    "summary": new_summary, "pdf_filename": new_path.name,
                    "pdf_path": str(new_path), "confidence": "High",
                    "state": State.COMPLETED.value})
                changed = True
                print(f"    Renamed -> {new_path.name}\n")
        finally:
            # Written however the review ends, a quit, a console that went
            # away or a rename that failed, so the CSVs name the files as they
            # now are on disk and in progress.json.
            if changed:
                self.index_csv.rewrite(rows)
                self.order_csv.rewrite(order_rows)
                print("CSV files and progress.json updated.")

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
            provider='Meijer', text=text, extra=extra)
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
            provider='Meijer')

    def cmd_diagnose(self):
        """The orders page and what its first receipt link gives,
        written to Diagnostics/diagnose-meijer.json with every number of
        two digits or more, every email and every @handle masked. This is
        the file a tester attaches to the issue. No screenshot is taken."""
        self.stats["mode"] = "diagnose"
        words = words_for('Meijer', site)
        page = self.page()
        site.set_private_words([self.config.get("owner", "")])
        info = {"timestamp": now_iso(), "app": "meijer", "history": {}, "receipt": {}, "json_answers": []}
        sniffer = site.JsonSniffer(page)
        try:
            site.goto_orders(page)
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            # Both tabs, since a person who only shops in the store has an
            # empty first tab and everything behind the second (#42).
            info["tabs"] = {}
            for name, pattern in (("In-Store Receipts", site.TAB_IN_STORE_RE),
                                  ("Online Orders", site.TAB_ONLINE_RE)):
                opened = site.open_tab(page, pattern)
                survey = site.survey_history_page(page) if opened else {}
                info["tabs"][name] = {"opened": opened, "rows": survey.get("rows"),
                                      "lines": (survey.get("lines") or [])[:40],
                                      "links": (survey.get("links") or [])[:15],
                                      "parsed": survey.get("parsed"),
                                      "outline": (survey.get("outline") or [])[:60]}
                if opened:
                    for c in site.collect_cards(page)[:1]:
                        p0 = site.card_to_purchase(c)
                        if p0:
                            found = site.row_controls(page, p0)
                            info["tabs"][name]["row_controls"] = [
                                {**x, "text": site.mask_text(x["text"]), "label": site.mask_text(x["label"]),
                                 "href": site.mask_href(x["href"])} for x in (found[0] if found else [])][:10]
            site.open_tab(page, site.TAB_IN_STORE_RE)
            info["history"] = site.survey_history_page(page)
            cards = site.collect_cards(page)
            links = []
            for c in cards[:3]:
                links = site.receipt_links(c)
                if links:
                    break
            if links:
                print("\nFollowing the newest receipt link ...")
                info["receipt"] = site.survey_receipt(page, links[0]["href"])
            else:
                info["receipt"] = {"note": Fixed("no receipt link found on the first rows")}
        except Exception as e:
            info["error"] = site.mask_text(str(e))
        info["json_answers"] = sniffer.stop()
        out = self.paths.diagnostics / "diagnose-meijer.json"
        write_shaped(out, info, words)
        print(f"  Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        h = info.get("history") or {}
        print(f"  Orders page: state={shape_tree(h.get('state') or 'has rows', words)} "
              f"rows={shape_tree(h.get('rows'), words)} links={len(h.get('links') or [])} "
              f"json answers={len(info['json_answers'])}")
        r = info.get("receipt") or {}
        print(f"  Receipt link: {shape_tree(r.get('kind') or r.get('note'), words)}")
        print("  Nothing in the file identifies you. Attach it to the Meijer issue.")


    # -- run summary --------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a receipt, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Meijer',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Meijer Receipts - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Online orders known:       {s['online_discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Receipts downloaded:       {s['receipts_downloaded']}",
            f"Skipped (already done):    {s['skipped_completed']}",
            f"Canceled purchases:        {s['canceled']}",
            f"No printable receipt:      {s['no_receipt']}",
            f"No longer listed:          {s.get('no_longer_listed', 0)}",
            f"Needs manual review:       {s['manual_review']}",
            f"Failed:                    {s['failed']}",
            f"Duplicate filenames (#'d): {s['duplicate_filenames']}",
            f"PDF validation failures:   {s['validation_failures']}",
            f"Earliest date processed:   {dates[0] if dates else '-'}",
            f"Latest date processed:     {dates[-1] if dates else '-'}",
            "",
        ]
        atomic_write_text(self.paths.run_summary, "\n".join(lines))
        # A plain list of exactly the files downloaded THIS run (all new, since
        # already-downloaded items are skipped). Handy for knowing what to
        # import into paperless-ngx, and safe to ignore/delete afterward.
        atomic_write_text(
            self.paths.root / "new-this-run.txt",
            f"# {len(new_files)} file(s) downloaded on this run "
            f"({s['ended']}):\n" + "\n".join(sorted(new_files)) + "\n")
        if new_files:
            print(f"\n{len(new_files)} NEW file(s) downloaded this run "
                  f"(listed in new-this-run.txt).")
        report_run_result(s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Local supervised Meijer receipt downloader")
    modes = [
        ("login", "open browser for manual Meijer sign-in"),
        ("discover", "discovery pass only; writes discovery.json"),
        ("pilot", "pilot: newest few orders"),
        ("all", "process every purchase (asks for confirmation)"),
        ("resume", "resume incomplete purchases"),
        ("verify", "re-validate every indexed PDF"),
        ("rename", "rename downloaded files to this app's current naming"),
        ("review-names", "interactively fix low-confidence names"),
        ("diagnose", "inspect one order, write diagnostics"),
        ("record", "record your own path to a receipt, so this app can be repaired"),
    ]
    for name, help_text in modes:
        ap.add_argument(f"--{name}", action="store_true", help=help_text)
    ap.add_argument("--apply", action="store_true",
                    help="with --rename, actually rename (default is a preview)")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and plan filenames but save no PDFs/CSVs")
    ap.add_argument("--year", type=int)
    ap.add_argument("--start-date")
    ap.add_argument("--end-date")
    ap.add_argument("--max-purchases", type=int)
    ap.add_argument("--order-number")
    ap.add_argument("--yes", action="store_true", help="skip the --all confirmation prompt")
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
            app.cmd_run([ONLINE, IN_STORE], "all")
        elif args.resume:
            app.cmd_resume()
        elif args.verify:
            app.cmd_verify()
        elif args.rename:
            app.cmd_rename()
        elif getattr(args, "review_names"):
            app.cmd_review_names()
        elif args.record:
            app.cmd_record()
        elif args.diagnose:
            app.cmd_diagnose()
            app.write_survey()
        elif args.dry_run:
            app.cmd_run([ONLINE, IN_STORE], "dry-run")
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

