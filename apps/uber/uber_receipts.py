"""Uber receipts downloader (local, supervised).

Two kinds of purchase, each with its own folder. Rides are every trip on
riders.uber.com, and Uber Eats is every food or grocery order on
ubereats.com, which is a separate sign-in. Each receipt is Uber's own PDF,
the one its Download PDF gives, and only purchases where money was spent
are kept.

Usage

    python uber_receipts.py --login
    python uber_receipts.py --discover
    python uber_receipts.py --pilot            (newest few of each kind)
    python uber_receipts.py --all
    python uber_receipts.py --rides            (rides only)
    python uber_receipts.py --eats             (Uber Eats orders only)
    python uber_receipts.py --resume
    python uber_receipts.py --verify
    python uber_receipts.py --review-names
    python uber_receipts.py --diagnose
    python uber_receipts.py --dry-run

Filters are --year YYYY, --start-date YYYY-MM-DD, --end-date YYYY-MM-DD,
--max-purchases N and --order-number N.

Everything runs locally. No receipt data leaves this machine.
Authentication is always manual (--login opens a browser and waits for you).
"""
from __future__ import annotations

from paperpull_core import delivery
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
import uber_site as site
from paperpull_core.models import Item, Purchase, State
from paperpull_core.words import shape_tree, words_for, write_shaped

from storage import (EATS, PURCHASE_TYPES, RIDES, CsvFile, JsonStore,
                     ORDER_HISTORY_COLUMNS, Paths, RECEIPT_INDEX_COLUMNS,
                     atomic_write_text, build_pdf_filename, load_config, now_iso,
                     title_case, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("uber_receipts")

# How much of each side Diagnose reads. Enough to count, and quick.
DIAGNOSE_PAGES = 5
DIAGNOSE_DETAILS = 3

# A purchase in one of these states is settled, so discovery does not ask
# Uber about it again.
SETTLED = (State.COMPLETED.value, State.PDF_VERIFIED.value,
           State.CANCELED.value, State.NO_RECEIPT_AVAILABLE.value)

def ask(prompt: str) -> str:
    """input() that stops cleanly (progress already saved by callers) when
    no interactive console is attached, instead of corrupting the run."""
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this command from a real console window (use the .bat files).")
        raise SystemExit(3)


class _SignedOut(Exception):
    """One of the two sides asked to be signed in again partway through."""

    def __init__(self, side: str, page=None):
        super().__init__(side)
        self.side = side
        self.page = page


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class App:
    _journal = None
    _requests = None

    def __init__(self, args):
        self.args = args
        # --config lets one copy of the code serve several people or accounts.
        # Each config points at its own output_dir, profile_dir and port, so
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
        self._eats_page = None
        self._cdp_mode = False
        # Tabs this run opened, which are the only ones it may close, and
        # the ones left on a sign-in page for the person to use.
        self._opened = []
        self._left_open = set()
        # The sides that asked for a sign-in during this run.
        self._stopped_sides = set()
        # The sides whose list did not come whole, refused or not answered
        # partway, or with trips whose details Uber did not answer. What came
        # is used, and the run stops at its end (see _stop_if_unfinished).
        self._cut_short_sides = set()
        self._survey = {}
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "rides_discovered": 0, "eats_discovered": 0,
            "receipts_downloaded": 0,
            "skipped_completed": 0, "no_receipt": 0, "unpaid_skipped": 0,
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

    def _strict(self) -> bool:
        """Whether a receipt that is not this purchase's is destroyed rather
        than filed. On unless the config turns it off."""
        return bool(self.config.get("refuse_wrong_documents", True))

    def browser(self):
        """Return the supervised browser context.

        The default mode is CDP-attach. The user runs `login.bat`, which
        opens their own Edge or Chrome and lets them sign in as a human,
        handling any verification themselves. This tool then connects to
        that already-open browser over the DevTools protocol and reads the
        pages the user is authorized to see, so the sign-in and any
        two-factor step stay entirely with the user and the session is
        never scripted. No stealth or evasion is used anywhere. Set
        "cdp_url" to "" in config.json to fall back to launching a
        dedicated browser with its own persistent profile instead.
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
                raise SystemExit("Connected browser has no context, open a tab and retry.")
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

    def _tab(self, on_site, current):
        """A tab on one side. In CDP mode the tab somebody signed in with is
        used when there is one. It is only read from, and it is never
        closed. Failing that a new tab is opened in the same, signed-in
        context."""
        ctx = self.browser()
        if current is not None and not current.is_closed():
            return current
        found = []
        if self._cdp_mode:
            found = [p for p in ctx.pages if not p.is_closed() and on_site(p)]
        if found:
            return found[0]
        if self._cdp_mode:
            tab = ctx.new_page()
            self._opened.append(tab)
            return tab
        # A dedicated browser opens with one blank tab, which the first
        # side takes.
        blank = [p for p in ctx.pages if not p.is_closed()
                 and p is not self._work_page and p is not self._eats_page]
        return blank[0] if blank else ctx.new_page()

    def page(self):
        """The riders.uber.com tab every ride call is made from."""
        self._work_page = self._tab(site.on_riders_page, self._work_page)
        self.requests
        return self._work_page

    def eats_page(self):
        """The Uber Eats tab every Eats call is made from, a tab of its own,
        so each site keeps its page and its session."""
        self._eats_page = self._tab(site.on_eats_page, self._eats_page)
        return self._eats_page

    def close(self):
        # In CDP mode the browser belongs to the user. Only the tabs this run
        # opened are closed, never one somebody signed in with, and never one
        # left on a sign-in page for the person to use.
        try:
            if self._cdp_mode:
                for tab in self._opened:
                    if id(tab) in self._left_open:
                        continue
                    try:
                        if not tab.is_closed():
                            tab.close()
                    except Exception:
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
        self._context = None
        self._browser = None
        self._work_page = None
        self._eats_page = None
        self._pw = None

    # -- session safety -----------------------------------------------------

    def _signed_out(self, side: str, page=None) -> None:
        """One side asked to be signed in again. That side stops for this
        run, what was already read is kept, and its tab stays open so the
        person can sign in there. Nothing is asked again in a loop."""
        self._stopped_sides.add(side)
        if page is not None:
            self._left_open.add(id(page))
        try:
            self.progress.save(backup=True)
        except Exception:
            pass
        print()
        if side == RIDES:
            print("!! Uber asked you to sign in again for your trips.")
            print("   Sign in at riders.uber.com in the browser window and keep the")
            print("   window open, then run this again. The rides side stopped here.")
        else:
            print("!! Uber Eats asked you to sign in.")
            print("   Sign in at ubereats.com in that window. It is a separate sign-in")
            print("   from your trips. Keep the window open, then run this again.")

    def _challenged(self, side: str, tab) -> None:
        """Uber put a check in front of its pages. That side stops, and the
        tab stays open for the person to deal with it."""
        self._stopped_sides.add(side)
        self._left_open.add(id(tab))
        print("\n!! Uber is showing a check in that window. Deal with it yourself,")
        print("   this tool will not, then run this again.")

    def _stop_if_unfinished(self) -> None:
        """A run where a side stopped for a sign-in, or where a side's list
        did not come whole, did not finish, and it must not read as a clean
        one. It leaves the way every app's run leaves on a sign-out, which
        the panel reports as stopped."""
        if self._cut_short_sides:
            said = " and ".join("your trips" if side == RIDES else "your Uber Eats orders"
                                for side in PURCHASE_TYPES if side in self._cut_short_sides)
            print("\nNot all of %s came, so this run stops here rather than finish." % said)
            print("Run it again later to read the rest.")
        if self._stopped_sides:
            print("\nSign in where it asked, then press Resume or run this again.")
        if self._stopped_sides or self._cut_short_sides:
            raise SystemExit(0)

    def _unfinished_mark(self) -> Path:
        """Present while a Discover is under way and after one that did not
        read both lists to their end, so Resume knows to read them first, as
        Target's and Kroger's do. A side that asked for a sign-in or was cut
        short leaves it, and so does a run that read one side, or one year or
        stretch of a list, since the rest was not read."""
        return self.paths.discovery_json.with_name(".discovery-unfinished")

    def _open(self, side: str):
        """The side's tab, opened on its list page. The tab, or None when
        the side asked for a sign-in or showed a check, which is said."""
        tab = self.page() if side == RIDES else self.eats_page()
        opener = site.open_trips_page if side == RIDES else site.open_eats_page
        state = opener(tab)
        if state == site.SIGNED_OUT:
            self._signed_out(side, tab)
            return None
        if state == site.CHALLENGE:
            self._challenged(side, tab)
            return None
        return tab

    # -- commands -----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session, so nothing is duplicated in the launcher scripts. You
        sign in, and the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9281")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile {profile}")
        print("Sign in to Uber in the tab that opened. That is the rides side.")
        print("Uber Eats is a separate sign-in. Open")
        print(f"  {site.EATS_ORDERS_URL}")
        print("in a second tab and sign in there too, if you want your Uber Eats orders.")
        print("Keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode. The browser is launched by login.bat, not here. This
            # only checks the connection and whether each side is signed in.
            print("Checking the connection to your signed-in Uber browser...\n")
            self._say_sign_in_state()
            self.close()
            return
        print("Opening Uber in a dedicated supervised browser profile.")
        print("Sign in manually, with any code Uber sends.")
        print("This tool never touches your credentials.\n")
        page = self.page()
        page.goto(site.URLS["home"], wait_until="domcontentloaded", timeout=60000)
        # Under the panel there is no console to press Enter at, and the
        # browser is deliberately left open for the person to sign in (#48).
        if not browser_launcher.pause_for_sign_in():
            return
        self._say_sign_in_state()
        self.close()

    def _say_sign_in_state(self) -> None:
        """Whether each side answers as signed in. Reads only."""
        page = self.page()
        state = site.open_trips_page(page)
        answered = False
        if state == site.READY:
            got = site.gql(page, "Activities", {"includePast": True, "includeUpcoming": False,
                                                "limit": 1, "orderTypes": ["RIDES", "TRAVEL"],
                                                "profileType": "PERSONAL"})
            answered = site.gql_kind(got) == site.ANSWERED
        if answered:
            print("Your Uber trips are signed in.")
        else:
            self._left_open.add(id(page))
            print("Your Uber trips are not signed in. Sign in at riders.uber.com in the")
            print("browser window, keep it open, then check again.")
        tab = self.eats_page()
        state = site.open_eats_page(tab)
        if state == site.READY:
            print("Uber Eats is signed in.")
        else:
            self._left_open.add(id(tab))
            print("Uber Eats is not signed in (%s). Sign in to it in the tab" % state)
            print("that just opened. It is a separate sign-in from your trips.")

    def _floor(self) -> str:
        """The date before which nothing is recorded or downloaded."""
        return self.args.start_date or self.config.get("default_start_date") or ""

    def _walk_limit(self) -> str:
        """How far back a list has to be read, which is the floor or the
        start of --year, whichever is later."""
        floor = self._floor()
        year = getattr(self.args, "year", None)
        if year:
            start = "%04d-01-01" % int(year)
            return max(floor, start) if floor else start
        return floor

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False,
                     finish: bool = True) -> dict:
        """Discovery pass, both sides unless told one.

        Each side asks Uber's own list from inside its signed-in page, the
        way the page asks, and keeps the purchases where money was spent. A
        ride's day comes from the trip itself, one trip at a time, since the
        list writes no year. Nothing is clicked on either.

        A side whose list did not come whole keeps what came, and Pilot, Run
        All and Resume go on with it and with the other side, but the rest
        is missing, so the run stops at its end rather than finish, as it
        does when a side asks for a sign-in. With finish=False the caller
        does that once it has used them."""
        types = list(types or PURCHASE_TYPES)
        try:
            self._unfinished_mark().write_text(now_iso(), encoding="utf-8")
        except OSError:
            pass
        n_new = {RIDES: 0, EATS: 0}
        if RIDES in types:
            n_new[RIDES] = self._discover_rides()
        if EATS in types:
            n_new[EATS] = self._discover_eats()
        self.discovery.save()
        unfinished = bool(self._stopped_sides or self._cut_short_sides)
        narrowed = bool(getattr(self.args, "year", None) or self.args.start_date)
        if not unfinished and not narrowed and set(PURCHASE_TYPES) <= set(types):
            try:
                self._unfinished_mark().unlink()
            except OSError:
                pass

        all_recs = [r for r in self.discovery.data.values() if isinstance(r, dict)]
        self.stats["rides_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == RIDES)
        self.stats["eats_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == EATS)

        if not quiet:
            said = ("Discovery did not read all of your trips and orders." if unfinished
                    else "Discovery complete.")
            print(f"\n{said} Purchases known {len(all_recs)} "
                  f"({self.stats['rides_discovered']} rides, "
                  f"{self.stats['eats_discovered']} Uber Eats)")
            by_year = {}
            for r in all_recs:
                y = (r.get("purchase_date") or "?")[:4]
                by_year[y] = by_year.get(y, 0) + 1
            summary = ", ".join(f"{y} {c}" for y, c in sorted(by_year.items(), reverse=True))
            print(f"  ({summary or 'none'})")
            dates = sorted(r.get("purchase_date") for r in all_recs if r.get("purchase_date"))
            if dates:
                print(f"  Date range {dates[0]} to {dates[-1]}")
        if finish:
            self._stop_if_unfinished()
        return n_new

    def _discover_rides(self) -> int:
        """Every trip where money was spent, from the trip list, each placed
        on its day by the trip itself."""
        floor, limit = self._floor(), self._walk_limit()
        # The tab first, so the journal is made watching the page it reports.
        page = self._open(RIDES)
        if page is None:
            return 0
        self.journal.op("open_list", "read the trips")
        self.journal.op("read_rows", "read the trip list")
        walk = site.walk_rides(page, limit_date=limit)
        self.journal.result("read the trip list", pages=walk["pages"],
                            trips=len(walk["rides"]))
        n_new, dropped, unplaced, unpaid, asked, unread = 0, 0, 0, 0, 0, 0
        unanswered = 0
        # After a sign-out no trip's details would be answered, and a trip
        # must never be recorded from its subtitle alone for that reason.
        rows = [] if walk["stop"] == site.SIGNED_OUT else walk["rides"]
        for row in rows:
            if not site.ride_is_paid(row):
                # A trip canceled before anything was charged. Uber keeps no
                # receipt for it, RECORDED.
                unpaid += 1
                continue
            key = "%s:%s" % (RIDES, row.get("uuid"))
            known = self.discovery.get(key) or {}
            if known.get("state") in SETTLED:
                continue  # settled already, the trip is not asked about again
            if asked:
                page.wait_for_timeout(site.LIST_PAUSE_MS)
            asked += 1
            got = site.read_trip(page, row["uuid"])
            if got["kind"] == site.SIGNED_OUT:
                self._signed_out(RIDES, page)
                break
            if got["kind"] != site.ANSWERED:
                # Asked again next run. Only a trip whose details answered
                # without a start is placed by its subtitle. No answer, a
                # 429 or a server error is Uber not answering, and the run
                # does not finish clean on it. Any other answer without the
                # trip is the trip's own, and asking again may change
                # nothing, so it does not stop every run.
                status = got.get("status") or 0
                if got["kind"] == site.FAILED or status == 429 or status >= 500:
                    unanswered += 1
                else:
                    unread += 1
                continue
            purchase = site.ride_purchase(row, got["trip"])
            if purchase is None:
                unplaced += 1
                continue
            if floor and purchase.purchase_date < floor:
                dropped += 1
                continue  # before the cutoff, never record or download
            n_new += self._remember(purchase, site.ride_extras(row, got["trip"]))
        self.stats["unpaid_skipped"] += unpaid
        print(f"\nRides, {len(walk['rides'])} trip(s) read in {walk['pages']} call(s). "
              f"{len(walk['rides']) - unpaid} paid, {unpaid} with nothing charged skipped.")
        if dropped:
            print(f"  {dropped} fell outside the scope you set.")
        if unanswered:
            # Trips missed, which a run that finished clean left unsaid.
            self._cut_short_sides.add(RIDES)
            print(f"  {unanswered} trip(s) did not answer with their details. They are read again next run,")
            print("  and this run stops at its end rather than finish.")
            self.write_failure("read a trip", "a trip's details were not answered")
        if unread:
            print(f"  {unread} trip(s) were answered without their details. They are read again next run.")
            self.write_failure("read a trip", "a trip's details came without the trip")
        if unplaced:
            print(f"  {unplaced} trip(s) could not be placed on a day. They are read again next run.")
            self.write_failure("read a trip", "a trip could not be placed on a day")
        self._say_walk_stop(RIDES, walk, page)
        return n_new

    def _discover_eats(self) -> int:
        """Every Uber Eats order where money was spent."""
        floor, limit = self._floor(), self._walk_limit()
        page = self._open(EATS)
        if page is None:
            return 0
        self.journal.op("open_list", "read the uber eats orders")
        walk = site.walk_eats(page, limit_date=limit)
        n_new, dropped, unpaid, unplaced = 0, 0, 0, 0
        for order in walk["orders"]:
            if not site.eats_is_paid(order):
                unpaid += 1
                continue
            purchase = site.eats_purchase(order)
            if purchase is None:
                unplaced += 1
                continue
            if floor and purchase.purchase_date < floor:
                dropped += 1
                continue
            n_new += self._remember(purchase, site.eats_extras(order))
        self.stats["unpaid_skipped"] += unpaid
        print(f"\nUber Eats, {len(walk['orders'])} order(s) read in {walk['pages']} call(s). "
              f"{len(walk['orders']) - unpaid} paid, {unpaid} with nothing charged skipped.")
        if dropped:
            print(f"  {dropped} fell outside the scope you set.")
        if unplaced:
            print(f"  {unplaced} order(s) carried no date. They are read again next run.")
            self.write_failure("read the orders", "an order carried no date")
        self._say_walk_stop(EATS, walk, page)
        return n_new

    def _say_walk_stop(self, side: str, walk: dict, page) -> None:
        if walk["stop"] == site.SIGNED_OUT:
            self._signed_out(side, page)
        elif walk["stop"] in (site.REFUSED, site.FAILED, site.NO_LIST):
            # Read as a list with nothing more in it, this let the run finish
            # clean with the rest of the side missed. What came is used, and
            # the run stops at its end.
            self._cut_short_sides.add(side)
            what = "trip" if side == RIDES else "order"
            how = ("an answer with errors and no %ss" % what if walk["stop"] == site.NO_LIST
                   else walk["status"] or "no answer")
            if walk["pages"] > 1:
                print("\n!! Uber stopped answering the %s list partway (%s)." % (what, how))
                print("   What was read is kept and used, and this run stops at its end")
                print("   rather than finish. Run it again later to read the rest.")
            else:
                print("\n!! Uber did not answer when this asked for the %s list (%s)." % (what, how))
                print("   This run stops at its end rather than finish. Run it again later.")
            self.write_failure("read the list", "a list call was not answered",
                               postmortem={"side": side.lower(), "calls": walk["pages"],
                                           "stop": walk["stop"], "status": walk["status"]})
        elif walk["stop"] == site.PAGE_CAP:
            print("  The list was stopped after %d calls. Set default_start_date or" % walk["pages"])
            print("  pass --start-date to read a shorter stretch at a time.")

    def _remember(self, purchase: Purchase, extras: Optional[dict] = None) -> int:
        """Record a discovered purchase, or refresh what is known of one.
        Returns 1 for a purchase not seen before."""
        key = purchase.key
        known = self.discovery.get(key)
        if known is None:
            rec = purchase.to_dict()
            rec.update(extras or {})
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(key, rec, save=False)
            return 1
        patch = {
            "details_url": purchase.details_url,
            "receipt_url": purchase.receipt_url or known.get("receipt_url", ""),
            "total": purchase.total or known.get("total", ""),
            "status": purchase.status or known.get("status", ""),
            "purchase_date": purchase.purchase_date or known.get("purchase_date", ""),
        }
        if purchase.items:
            patch["items"] = [i.to_dict() for i in purchase.items]
        patch.update({k: v for k, v in (extras or {}).items() if v})
        self.discovery.update(key, patch, save=False)
        return 0

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
        # A hard floor. Nothing before the configured start date is processed.
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
        downloaded once is done FOR GOOD. It is not downloaded again even if
        you later delete the PDF, after importing it into paperless-ngx say.
        Use --redownload to override and fetch everything in scope again."""
        if getattr(self.args, "redownload", False):
            return False
        rec = self.progress.get(purchase.key)
        if not rec:
            return False
        if rec.get("downloaded_ok"):
            return True
        state = rec.get("state")
        # Terminal or already completed, including records made before the
        # downloaded_ok marker existed. Done, and not downloaded again.
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        # A review copy counts only if its PDF is still present and valid,
        # and a quarantined or failed one is tried again.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            pdf_path = rec.get("pdf_path", "")
            return bool(pdf_path and Path(pdf_path).exists()
                        and receipt_pdf.validate_pdf(
                            Path(pdf_path), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing core ----------------------------------------------------

    def _on_its_site(self, side: str, tab):
        """The side's tab, on the side's own site, which every call for a
        receipt is made from, or None when the side asked for a sign-in or
        showed a check, which is said and stops the side.

        A call from a tab anywhere else is refused before it is sent. A run
        that read no list first, Resume after a Discover that read both to
        their end, had only the new blank tab _tab opens when no tab is on
        the site, and every receipt it asked for failed, run after run. So
        a tab that is not on the site is opened on the side's list page
        first, the way discovery opens it."""
        on_site = site.on_riders_page if side == RIDES else site.on_eats_page
        if on_site(tab):
            return tab
        if self._cdp_mode and tab is not None and tab not in self._opened:
            # A tab of the person's that has left the site is theirs, and it
            # is let go of where they took it, never loaded back onto Uber,
            # the rule core's tabs module gives every app. Another tab of
            # theirs on the site is taken, or one of the run's own is opened
            # on the list page below.
            if side == RIDES:
                self._work_page = None
            else:
                self._eats_page = None
            fresh = self.page() if side == RIDES else self.eats_page()
            if on_site(fresh):
                return fresh
        return self._open(side)

    def process_purchases(self, purchases: List[Purchase], dry_run: bool = False):
        for i, purchase in enumerate(purchases, 1):
            print(f"\n[{i}/{len(purchases)}] {purchase.purchase_type} "
                  f"{purchase.purchase_date or '(date unknown)'} "
                  f"#{purchase.order_number}")
            if self._already_done(purchase):
                print("  Already completed and PDF verified, skipping.")
                self.stats["skipped_completed"] += 1
                continue
            if purchase.purchase_type in self._stopped_sides:
                # That side asked for a sign-in earlier in the run, and
                # nothing is asked of Uber for this one, so there is nothing
                # to pace.
                print("  Skipped, this side asked for a sign-in earlier in the run.")
                continue
            try:
                # The tab first, so the journal is made watching a page.
                page = self.page() if purchase.purchase_type == RIDES else self.eats_page()
                # Which document the run is on, so a failure file says how
                # far it got and whether it ever reached a second one.
                try:
                    self.journal.op("next_item" if i > 1 else "open_item",
                                    "take a document", ordinal=i)
                except Exception:
                    pass
                self.process_one(page, purchase, dry_run=dry_run)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress is saved, run --resume to continue.")
                raise
            except Exception as e:
                log.exception("Unhandled failure on %s", purchase.key)
                self._record_state(purchase, State.FAILED, notes=f"Unhandled error, {e}")
                self.stats["failed"] += 1
            self._delay()

    def process_one(self, page, purchase: Purchase, dry_run: bool = False):
        if purchase.purchase_type in self._stopped_sides:
            print("  Skipped, this side asked for a sign-in earlier in the run.")
            return
        rec = self.discovery.get(purchase.key) or {}
        if purchase.purchase_date:
            self.stats["dates_processed"].append(purchase.purchase_date)

        # ---- name it (local, deterministic) ----
        # Uber has already said what each purchase was, where a ride went
        # and which store an order came from, so nothing is guessed at.
        purchase.summary = rec.get("summary_hint") or (
            "Ride" if purchase.purchase_type == RIDES else "Eats Order")
        purchase.confidence = classification.HIGH
        print(f"  {len(purchase.items)} item(s), named {purchase.summary} "
              f"[{purchase.confidence}] (named by Uber)")

        if dry_run:
            filename = build_pdf_filename(purchase.purchase_date, purchase.summary, record=purchase)
            print(f"  DRY RUN, would save {filename}")
            return

        # ---- the side's own page, opened when its tab is not on it ----
        page = self._on_its_site(purchase.purchase_type, page)
        if page is None:
            return  # the side stopped and said why, and this one is asked for next run

        # ---- locate + save receipt ----
        saved = self._save_receipt(page, purchase, rec)
        if not saved:
            return  # state already recorded inside

        # ---- CSVs + progress ----
        self._write_csv_rows(purchase, receipt_status="Downloaded",
                             processing_status="Completed")
        self._record_state(purchase, State.COMPLETED)
        self.journal.checkpoint('a document is saved')
        self.stats["receipts_downloaded"] += 1
        print(f"  Saved {purchase.pdf_filename}")

    # -- receipt saving -----------------------------------------------------

    def _save_receipt(self, page, purchase: Purchase, rec: dict) -> bool:
        """Save one receipt as a verified PDF.

        The receipt is Uber's own PDF, asked for from inside the signed-in
        page the way its Download PDF link asks, and placed through
        delivery.place, to a staging file that is read back and moved into
        place only when it is this purchase's receipt."""
        purchase.document_type = "Receipt"
        folder = self.paths.folder_for(purchase.purchase_type,
                                       purchase.document_type)
        filename = build_pdf_filename(purchase.purchase_date, purchase.summary,
                                      purchase.document_type, record=purchase)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=purchase.order_number)
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1

        self._record_state(purchase, State.RECEIPT_LOCATED)
        try:
            got = self._capture_document(page, purchase, out_path)
        except _SignedOut as e:
            # Not a terminal state, so the next run asks for it again.
            self._record_state(purchase, State.DISCOVERED,
                               notes="Signed out before the receipt was read, revisited next run")
            self._signed_out(e.side, e.page)
            return False
        except Exception as e:
            log.exception("Saving the receipt failed for %s", purchase.key)
            self._record_state(purchase, State.FAILED,
                               notes=f"Saving the receipt failed, {e}")
            self.stats["failed"] += 1
            self.write_failure("save the receipt", "capturing the receipt raised")
            return False

        if got is None:
            # Uber answered without a receipt, or the PDF never came. Failed
            # rather than finished, so the next run tries it again.
            self._record_state(purchase, State.FAILED, notes="No receipt came back")
            self.stats["no_receipt"] += 1
            self.stats["failed"] += 1
            self.write_failure("fetch the receipt", "no receipt came back")
            self.journal.result("could not save the document")
            print("  No receipt came back for this purchase. It is tried again next run.")
            return False
        if got.outcome == delivery.WRONG:
            return self._refused(purchase, got)
        if got.outcome != delivery.SAVED:
            # Nothing checked reached the folder, so nothing is finished.
            self._record_state(purchase, State.FAILED,
                               notes="the receipt was not saved, %s" % got.outcome)
            self.stats["failed"] += 1
            self.write_failure("save the receipt", "the receipt was not saved")
            self.journal.result("could not save the document")
            return False
        purchase.receipt_count = 1
        ok = self._finish_pdf(purchase, out_path)
        self.journal.result("saved the document" if ok
                            else "could not save the document",
                            bytes_written=out_path.stat().st_size
                            if out_path.exists() else 0)
        return ok

    def _capture_document(self, page, purchase: Purchase, out_path: Path):
        """A Delivery, or None when no receipt came back. Raises _SignedOut
        when a side asked for a sign-in.

        The receipt call first, as the page's receipt window makes it, for
        the newest receipt's time and the Receipt ID it prints, then the PDF
        that time names, each asked once."""
        side = purchase.purchase_type
        uuid = purchase.order_number
        if side == RIDES:
            info = site.read_ride_receipt(page, uuid)
        else:
            info = site.read_eats_receipt(page, uuid)
        self.journal.result("asked for the receipt", status=int(info.get("status") or 0))
        if info["kind"] == site.SIGNED_OUT:
            raise _SignedOut(side, page)
        if info["kind"] != site.ANSWERED or not info["pdf"]:
            log.warning("The receipt was answered %s (%s), pdf offered %s",
                        info["kind"], info["status"] or "no answer", info["pdf"])
            return None
        path = (site.ride_pdf_path(uuid, info["stamp"]) if side == RIDES
                else site.eats_pdf_path(uuid, info["stamp"]))
        pdf = self._fetch_pdf(page, path, side)
        if pdf["kind"] == site.SIGNED_OUT:
            raise _SignedOut(side, page)
        if pdf["kind"] != site.ANSWERED or not pdf["data"]:
            log.warning("The receipt PDF was answered %s (%s)", pdf["kind"],
                        pdf["status"] or "no answer")
            return None
        self.journal.checkpoint("the receipt is in hand")
        # A ride receipt prints the trip's own uuid as its Receipt ID,
        # RECORDED, and an Eats one prints the id the receipt call named, or,
        # before December 2025, none.
        receipt_id = info["receipt_id"] or (uuid if side == RIDES else "")
        # An older Eats receipt, with no ID, is held to its own date and
        # total and never counted against its neighbors, which refused a
        # correct one in a review (see site.identity_for).
        expect = site.identity_for(purchase, receipt_id)
        return delivery.place(pdf["data"], out_path, expect=expect,
                              journal=self.journal, strict=self._strict())

    def _fetch_pdf(self, page, path: str, side: str) -> dict:
        """The PDF, with the request census stepped aside for it.

        The census goes into a failure file, which a tester may post in
        public, and a receipt's address carries the purchase's own id and
        time. The census masks an id it knows the shape of, and this one
        call is left out of it all the same."""
        census = self._requests
        if census is not None and getattr(census, "page", None) is not page:
            census = None
        if census is not None:
            census.stop()
        try:
            got = site.fetch_pdf(page, path, side)
        finally:
            if census is not None:
                census.start()
        self.journal.result("asked for the pdf", status=int(got.get("status") or 0))
        return got

    def _refused(self, purchase: Purchase, got) -> bool:
        """A receipt came back, was read, and is not this purchase.

        Nothing is quarantined because nothing was kept. The file was
        destroyed at the staging path, which is the point of checking
        before writing rather than after."""
        why = "the receipt that came back is not this purchase"
        self._record_state(purchase, State.NEEDS_MANUAL_REVIEW, notes=why)
        self._write_csv_rows(purchase, receipt_status="Wrong document",
                             processing_status=State.NEEDS_MANUAL_REVIEW.value,
                             notes_extra=why)
        self.stats["manual_review"] += 1
        self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        print("  !! %s" % got.say())
        print("     Nothing was saved for it. The file was destroyed rather")
        print("     than filed under this purchase's name.")
        self.write_failure("save the receipt", why)
        self.journal.result("refused the document",
                            delivery_outcome=got.outcome,
                            mechanism=got.mechanism)
        return False

    def _finish_pdf(self, purchase: Purchase, out_path: Path) -> bool:
        """Validate what was saved, and file it or quarantine it. Uber's PDF
        is its own, so there is nothing to print again, and one that fails
        validation is quarantined as it is."""
        purchase.pdf_path = str(out_path)
        purchase.pdf_filename = out_path.name
        self._record_state(purchase, State.PDF_SAVED)

        tokens = receipt_pdf.expected_tokens_for(purchase) + site.receipt_tokens(purchase)
        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
        if not result.ok:
            self.stats["validation_failures"] += 1
            # Quarantine the questionable file, never mark it Completed.
            quarantine = unique_path(self.paths.manual_review, out_path.name,
                                     self.config["max_path_length"])
            try:
                out_path.replace(quarantine)
            except OSError:
                quarantine = out_path
            purchase.pdf_path = str(quarantine)
            purchase.pdf_filename = quarantine.name
            self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                               notes=f"PDF validation failed, {result.reason}")
            self._write_csv_rows(purchase, receipt_status="Validation Failed",
                                 processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                 notes_extra=f"Validation {result.reason}")
            self.stats["manual_review"] += 1
            print(f"  !! Validation failed ({result.reason}), moved to Manual Review.")
            return False

        purchase.receipt_count = 1
        # A sticky marker. A valid PDF was produced, so this purchase is done
        # for good and is not downloaded again even if the file is deleted.
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
        # What the Purchase has no fields for, the vehicle and the list's own
        # words for the trip.
        found = self.discovery.get(purchase.key) or {}
        for name in site.EXTRA_KEYS:
            if name in found:
                rec[name] = found[name]
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
        print("PILOT MODE, a limited supervised test run.")
        self.cmd_discover(types=list(PURCHASE_TYPES), quiet=False, finish=False)
        # Some of each kind, since a ride's receipt and an Eats receipt come
        # from two different sites, and a pilot of one proves nothing about
        # the other.
        selected: List[Purchase] = (
            self._select_purchases(RIDES, limit=self.config.get("pilot_rides", 3))
            + self._select_purchases(EATS, limit=self.config.get("pilot_eats", 3)))
        if not selected:
            print("\nNo purchases discovered to pilot. Run --diagnose to inspect pages.")
            self._stop_if_unfinished()
            return
        print(f"\nProcessing {len(selected)} pilot purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)
        self._pilot_report(selected)
        self._stop_if_unfinished()

    def _pilot_report(self, selected: List[Purchase]):
        print("\n" + "=" * 70)
        print("PILOT RESULTS, please inspect these files before approving a full run")
        print("=" * 70)
        problems = []
        for p in selected:
            rec = self.progress.get(p.key) or {}
            state = rec.get("state", "?")
            fn = rec.get("pdf_filename", "")
            print(f"\n  {p.purchase_type}  {rec.get('purchase_date', p.purchase_date)}  "
                  f"#{rec.get('order_number', p.order_number)}")
            print(f"    State       {state}")
            print(f"    Summary     {rec.get('summary','')} "
                  f"[confidence {rec.get('confidence','')}]")
            print(f"    PDF         {fn or '(none)'}")
            if fn:
                path = Path(rec.get("pdf_path", ""))
                exists = path.exists()
                print(f"    PDF exists  {exists}  "
                      f"({rec.get('pdf_size','?')} bytes, {rec.get('pdf_pages','?')} pages)")
                if not exists:
                    problems.append(f"{p.key}, PDF missing")
            if state in (State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value,
                         State.NO_RECEIPT_AVAILABLE.value):
                problems.append(f"{p.key}, {state}, {rec.get('notes','')}")
        print("\n" + "-" * 70)
        if problems:
            print("Needs attention")
            for pr in problems:
                print(f"  ! {pr}")
        else:
            print("No problems detected in the pilot.")
        print("\nPilot finished. Inspect the PDFs and CSVs in")
        print(f"  {self.paths.root}")
        print("Nothing further will run until you explicitly start a full command,")
        print("e.g.  python uber_receipts.py --all")

    def cmd_run(self, types: Optional[List[str]], mode_name: str):
        self.stats["mode"] = mode_name
        types = list(types or PURCHASE_TYPES)
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Uber receipt history")
            print(f"({', '.join(types)}). Type YES to continue.")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't, --pilot)")
                return
        self.cmd_discover(types=types, quiet=False, finish=False)
        selected: List[Purchase] = []
        for t in types:
            selected += self._select_purchases(t)
        print(f"\nProcessing {len(selected)} purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)
        self._stop_if_unfinished()

    def cmd_resume(self):
        self.stats["mode"] = "resume"
        # Resume works from the purchases a Discover found. After one where a
        # side asked for a sign-in or its list did not come whole, that is
        # some of them, and Resume finished clean on those with the rest
        # never looked for. So both lists are read first, and a side that
        # does not come this time either still leaves the purchases already
        # found to download, and the run stops at its end.
        if self._unfinished_mark().exists():
            print("The last Discover did not read both of your lists to their end, "
                  "so it runs again first.")
            self.cmd_discover(quiet=True, finish=False)
        pend = [Purchase.from_dict(r) for r in self.discovery.data.values()
                if isinstance(r, dict) and r.get("order_number")]
        pend = [p for p in pend if not self._already_done(p)]
        pend.sort(key=lambda p: p.purchase_date or "0000", reverse=True)
        if self.args.max_purchases:
            pend = pend[:self.args.max_purchases]
        if not pend:
            print("Nothing to resume, all discovered purchases are complete.")
            self._stop_if_unfinished()
            return
        print(f"Resuming {len(pend)} incomplete purchase(s).")
        self.process_purchases(pend, dry_run=self.args.dry_run)
        self._stop_if_unfinished()

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
            print("Receipt index is empty, nothing to verify.")
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
                print(f"  {mark} {row.get('PDF Filename','')}, {result.reason}")
            row["Verified At"] = now_iso() if result.ok else row.get("Verified At", "")
        dups = {k: c for k, c in seen_keys.items() if c > 1}
        self.index_csv.rewrite(rows)
        print(f"\nVerified {len(rows)} index rows, {bad} problem(s).")
        if dups:
            print("Note, multiple index rows for these purchases (may be legitimate "
                  "multi-document orders)")
            for k, c in dups.items():
                print(f"  {k}, {c} rows")

    def cmd_review_names(self):
        rows = self.index_csv.read_all()
        # A row somebody already renamed is left out, even one renamed
        # before its confidence was marked High as well (#47).
        review = [r for r in rows
                  if (r.get("Classification Confidence") == "Low"
                      or "Review" in (r.get("Processing Status") or ""))
                  and "renamed via --review-names" not in (r.get("Notes") or "")]
        if not review:
            print("No receipts need name review.")
            return
        print(f"{len(review)} receipt(s) need review. Enter a new summary, "
              "press Enter to keep, or 'q' to stop.\n")
        order_rows = self.order_csv.read_all()
        changed = False
        for r in review:
            key = f"{r.get('Purchase Type')}:{r.get('Order or Receipt Number')}"
            prog = self.progress.get(key) or {}
            items = [i.get("name", "") for i in prog.get("items", [])][:10]
            print(f"  {r.get('Purchase Date')}  #{r.get('Order or Receipt Number')}"
                  f"  [{r.get('Classification Confidence')}]")
            print(f"    Current file  {r.get('PDF Filename')}")
            if items:
                print(f"    Items  {'; '.join(items)}")
            new = ask("    New summary (blank=keep, q=quit) ").strip()
            if new.lower() == "q":
                break
            if not new:
                print()
                continue
            new_summary = title_case(new)
            old_path = Path(r.get("PDF Full Path") or "")
            date = r.get("Purchase Date") or (old_path.name[:10] if old_path.name else "")
            doc_type = r.get("Document Type") or "Receipt"
            new_name = build_pdf_filename(date, new_summary, doc_type, record=prog)
            if old_path.exists():
                new_path = unique_path(old_path.parent, new_name,
                                       self.config["max_path_length"])
                old_path.rename(new_path)  # unique_path guarantees no overwrite
            else:
                new_path = old_path.parent / new_name if old_path.name else Path(new_name)
                print("    (warning, original PDF not found on disk, records updated only)")
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
            print(f"    Renamed to {new_path.name}\n")
        if changed:
            self.index_csv.rewrite(rows)
            self.order_csv.rewrite(order_rows)
            print("CSV files and progress.json updated.")

    def _diag_page(self):
        """The tab the journal, the census and a failure file look at, the
        trips tab, or the Uber Eats tab on a run that opened only that."""
        return getattr(self, "_work_page", None) or getattr(self, "_eats_page", None)

    @property
    def requests(self):
        """Which of the provider's own calls happened, and what came back.

        Made on first use like the journal, and started at once, because
        it only sees what arrives after it starts listening. An app that
        drives an API rather than a page has no selectors for the census
        to count, and this is what it has instead."""
        if self._requests is None:
            self._requests = Requests(self._diag_page(),
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
            self._journal = Journal(self._diag_page(),
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
        # journal when nothing had written to it yet.
        try:
            if self._diag_page() is not None:
                self.journal.checkpoint("when the run gave up")
        except Exception:
            pass
        path = failure.write_failure(
            self.paths.diagnostics,
            command=self.stats.get("mode") or "run",
            step=step, reason=reason,
            page=self._diag_page(),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Uber', text=text, extra=extra)
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
            print("  What it noticed")
            for line in said[:6]:
                print("    - %s" % line)
        print("  Read it through, then attach it to this provider's issue on")
        print("  GitHub. It is the one thing that saves a round of guessing.")

    def write_survey(self) -> None:
        """The survey Diagnose is safe to send.

        Built on the same list of what may leave that the failure file uses,
        and carrying each side's counts from Diagnose as numbers, yes or
        no, and words this app wrote. It is the one to send."""
        failure.write_survey(
            self.paths.diagnostics,
            page=self._diag_page(),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Uber',
            extra=self._survey_extra() or None)

    def _survey_extra(self) -> dict:
        """Diagnose's counts for the survey, nothing but numbers, yes or no,
        and the fixed words the site module answers with."""
        out = {}
        for side in ("rides", "eats"):
            found = (self._survey or {}).get(side) or {}
            out[side] = {k: v for k, v in found.items()
                         if isinstance(v, (bool, int)) or k in ("stop", "state")}
        return out

    def cmd_diagnose(self):
        """Both sides as this browser sees them, in counts, written to
        Diagnostics/diagnose-uber.json beside the survey that is safe to
        send. Downloads nothing and presses nothing, and no screenshot is
        taken."""
        self.stats["mode"] = "diagnose"
        words = words_for('Uber', site)
        info = {"timestamp": now_iso(), "app": "uber"}
        try:
            info["rides"] = self._survey_rides()
        except Exception as e:
            info["rides"] = {"error": type(e).__name__}
        try:
            info["eats"] = self._survey_eats()
        except Exception as e:
            info["eats"] = {"error": type(e).__name__}
        self._survey = info
        out = self.paths.diagnostics / "diagnose-uber.json"
        write_shaped(out, info, words)
        print(f"  Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        r = info.get("rides") or {}
        print("  Rides, signed in %s, %s trip(s) read, %s paid, %s with a receipt of %s asked"
              % tuple(shape_tree(v, words) for v in (
                  "yes" if r.get("signed_in") else "no", r.get("trips", 0), r.get("paid", 0),
                  r.get("with_pdf", 0), r.get("receipts_asked", 0))))
        e = info.get("eats") or {}
        print("  Uber Eats, signed in %s, %s order(s) read, %s paid, %s with a receipt of %s asked"
              % tuple(shape_tree(v, words) for v in (
                  "yes" if e.get("signed_in") else "no", e.get("orders", 0), e.get("paid", 0),
                  e.get("with_pdf", 0), e.get("receipts_asked", 0))))

    def _survey_rides(self) -> dict:
        """The trips in counts, the list and a few receipts. Reads only."""
        page = self.page()
        state = site.open_trips_page(page)
        out = {"signed_in": False, "state": state, "pages": 0, "stop": "",
               "reached_end": False, "trips": 0, "paid": 0, "canceled": 0,
               "receipts_asked": 0, "with_pdf": 0, "with_receipt_id": 0}
        if state != site.READY:
            self._left_open.add(id(page))
            return out
        walk = site.walk_rides(page, max_pages=DIAGNOSE_PAGES)
        out["signed_in"] = walk["stop"] != site.SIGNED_OUT and walk["pages"] > 0
        out["pages"], out["stop"] = walk["pages"], walk["stop"]
        out["reached_end"] = walk["stop"] == site.END
        rows = walk["rides"]
        out["trips"] = len(rows)
        paid = [r for r in rows if site.ride_is_paid(r)]
        out["paid"] = len(paid)
        out["canceled"] = sum(1 for r in rows if site.ride_is_canceled(r))
        for n, row in enumerate(paid[:DIAGNOSE_DETAILS]):
            page.wait_for_timeout(site.LIST_PAUSE_MS)
            got = site.read_ride_receipt(page, row["uuid"])
            out["receipts_asked"] += 1
            out["with_pdf"] += 1 if got["pdf"] else 0
            out["with_receipt_id"] += 1 if got["receipt_id"] else 0
        # Uber's own field names, the same for every account, for a repair.
        # Only in the detailed file.
        out["trip_fields"] = sorted(k for k in (rows[0] if rows else {})
                                    if isinstance(k, str) and not k.startswith("_"))[:40]
        return out

    def _survey_eats(self) -> dict:
        """The Uber Eats orders in counts, the list and a few receipts."""
        tab = self.eats_page()
        state = site.open_eats_page(tab)
        out = {"signed_in": False, "state": state, "pages": 0, "stop": "",
               "reached_end": False, "orders": 0, "paid": 0, "canceled": 0,
               "receipts_asked": 0, "with_pdf": 0, "with_receipt_id": 0}
        if state != site.READY:
            self._left_open.add(id(tab))
            return out
        walk = site.walk_eats(tab, max_pages=DIAGNOSE_PAGES)
        out["signed_in"] = walk["stop"] != site.SIGNED_OUT and walk["pages"] > 0
        out["pages"], out["stop"] = walk["pages"], walk["stop"]
        out["reached_end"] = walk["stop"] == site.END
        orders = walk["orders"]
        out["orders"] = len(orders)
        paid = [o for o in orders if site.eats_is_paid(o)]
        out["paid"] = len(paid)
        out["canceled"] = sum(1 for o in orders if site.eats_is_canceled(o))
        for order in paid[:DIAGNOSE_DETAILS]:
            tab.wait_for_timeout(site.LIST_PAUSE_MS)
            got = site.read_eats_receipt(tab, site.order_uuid(order))
            out["receipts_asked"] += 1
            out["with_pdf"] += 1 if got["pdf"] else 0
            out["with_receipt_id"] += 1 if got["receipt_id"] else 0
        first = orders[0] if orders else {}
        out["order_fields"] = sorted(k for k in first if isinstance(k, str))[:40]
        return out

    # -- run summary --------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a receipt, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Uber',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Uber Receipts, run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Rides known:               {s.get('rides_discovered', 0)}",
            f"Uber Eats orders known:    {s.get('eats_discovered', 0)}",
            f"NEW files this run:        {len(new_files)}",
            f"Receipts downloaded:       {s.get('receipts_downloaded', 0)}",
            f"Skipped (already done):    {s.get('skipped_completed', 0)}",
            f"Nothing charged, skipped:  {s.get('unpaid_skipped', 0)}",
            f"No receipt returned:       {s.get('no_receipt', 0)}",
            f"Needs manual review:       {s.get('manual_review', 0)}",
            f"Failed:                    {s.get('failed', 0)}",
            f"Duplicate filenames (#'d): {s.get('duplicate_filenames', 0)}",
            f"PDF validation failures:   {s.get('validation_failures', 0)}",
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
    ap = argparse.ArgumentParser(description="Local supervised Uber receipt downloader")
    modes = [
        ("login", "open browser for manual Uber sign-in"),
        ("discover", "discovery pass only, writes discovery.json"),
        ("pilot", "pilot, the newest few of each kind"),
        ("all", "process every purchase (asks for confirmation)"),
        ("rides", "process rides only"),
        ("eats", "process Uber Eats orders only"),
        ("resume", "resume incomplete purchases"),
        ("verify", "re-validate every indexed PDF"),
        ("rename", "rename downloaded files to this app's current naming"),
        ("review-names", "interactively fix low-confidence names"),
        ("diagnose", "survey both sides in counts, write diagnostics"),
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
            print(f"Bad date '{d}', use YYYY-MM-DD")
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
            app.cmd_run(None, "all")
        elif getattr(args, "rides", False):
            app.cmd_run([RIDES], "rides")
        elif getattr(args, "eats", False):
            app.cmd_run([EATS], "eats")
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
            app.cmd_run(None, "dry-run")
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
