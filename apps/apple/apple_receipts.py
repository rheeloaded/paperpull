"""Apple purchase receipts downloader (local, supervised).

Two stores, each with its own folder. App Store is subscriptions such as
Apple One and iCloud+, in-app purchases and paid apps, for the whole
family, from Report a Problem. Apple Store is hardware orders, each
order's invoice.

Usage

    python apple_receipts.py --login
    python apple_receipts.py --discover
    python apple_receipts.py --pilot            (newest few of each kind)
    python apple_receipts.py --all
    python apple_receipts.py --app-store        (App Store purchases only)
    python apple_receipts.py --apple-store      (Apple Store orders only)
    python apple_receipts.py --resume
    python apple_receipts.py --verify
    python apple_receipts.py --review-names
    python apple_receipts.py --diagnose
    python apple_receipts.py --dry-run

Filters are --year YYYY, --start-date YYYY-MM-DD, --end-date YYYY-MM-DD,
--max-purchases N and --order-number N.

Everything runs locally. No receipt data leaves this machine.
Authentication is always manual (--login opens a browser and waits for you).
"""
from __future__ import annotations

from paperpull_core import delivery
from paperpull_core import failure
from paperpull_core import listing
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
import apple_site as site
from paperpull_core.models import Item, Purchase, State
from paperpull_core.words import shape_tree, words_for, write_shaped

from storage import (APP_STORE, APPLE_STORE, PURCHASE_TYPES, CsvFile, JsonStore,
                     ORDER_HISTORY_COLUMNS, Paths, RECEIPT_INDEX_COLUMNS,
                     atomic_write_text, build_pdf_filename, load_config, now_iso,
                     unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("apple_receipts")

# How much of each store Diagnose reads. Enough to count, and quick.
DIAGNOSE_BATCHES = 20
DIAGNOSE_DETAILS = 5

# A store order in one of these states is settled, so discovery does not
# open its details page again.
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
    """One of the two stores asked to be signed in again partway through."""

    def __init__(self, side: str, page=None):
        super().__init__(side)
        self.side = side
        self.page = page


class _AppleRefused(Exception):
    """Report a Problem answered, still signed in, and gave no receipt, or
    was not asked, `asked` False, because Apple had just refused the
    purchases before this one (#55)."""

    def __init__(self, asked: bool = True):
        super().__init__("refused" if asked else "not asked")
        self.asked = asked


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
        self._store_page = None
        self._cdp_mode = False
        # Tabs this run opened, which are the only ones it may close, and
        # the ones left on a sign-in page for the person to use.
        self._opened = []
        self._left_open = set()
        # The stores that asked for a sign-in during this run.
        self._stopped_sides = set()
        # The stores whose list did not come whole, the family list or the
        # purchase search refused, not answered, or answered without the list.
        # What came is used, and the run stops at its end (see
        # _stop_if_unfinished).
        self._cut_short_sides = set()
        self._survey = {}
        self.stats = {
            "mode": "", "started": now_iso(), "ended": "",
            "app_store_discovered": 0, "apple_store_discovered": 0,
            "receipts_downloaded": 0,
            "skipped_completed": 0, "canceled": 0, "no_receipt": 0,
            "not_invoiced": 0, "free_skipped": 0, "pending_skipped": 0,
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
        """Whether a receipt that does not carry its own order number is
        destroyed rather than filed. On unless the config turns it off."""
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
            # The print-suppression hook at context level, so the invoice
            # tab and the tab a receipt is drawn in carry it too, and a
            # window.print() never opens the native dialog.
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
        """The Report a Problem tab every App Store call is made from.

        In CDP mode the tab somebody signed in with is used when there is
        one, because it already holds the session token the page's own
        script keeps in sessionStorage, which a new tab has to wait for. It
        is only read from, and it is never closed. Failing that a new tab
        is opened in the same, signed-in context."""
        ctx = self.browser()
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        found = []
        if self._cdp_mode:
            found = [p for p in ctx.pages if not p.is_closed() and site.on_report_page(p)]
        if found:
            self._work_page = found[0]
        elif self._cdp_mode:
            self._work_page = ctx.new_page()
            self._opened.append(self._work_page)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not found:
            # Only on a tab this run made. The person's own is left as it is.
            try:
                self._work_page.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
            except Exception:
                pass
        self.requests
        return self._work_page

    def store_page(self):
        """The tab the Apple Store's list and details pages are read in, a
        new one in the same context, so the Report a Problem tab keeps its
        page and its session."""
        ctx = self.browser()
        if self._store_page is not None and not self._store_page.is_closed():
            return self._store_page
        self._store_page = ctx.new_page()
        self._opened.append(self._store_page)
        return self._store_page

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
        self._store_page = None
        self._pw = None

    # -- session safety -----------------------------------------------------

    def _signed_out(self, side: str, page=None) -> None:
        """One store asked to be signed in again. That store stops for this
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
        if side == APP_STORE:
            print("!! Report a Problem asked you to sign in again.")
            print("   Sign in at reportaproblem.apple.com in the browser window and keep")
            print("   the window open, then run this again. The App Store side stopped here.")
        else:
            print("!! The Apple Store asked you to sign in.")
            print("   Sign in to the Apple Store in that window. It is a separate sign-in")
            print("   from Report a Problem. Keep the window open, then run this again.")

    def _challenged(self, tab) -> None:
        """The Apple Store put a check in front of its pages. The store side
        stops, and the tab stays open for the person to deal with it."""
        self._stopped_sides.add(APPLE_STORE)
        self._left_open.add(id(tab))
        print("\n!! The Apple Store is showing a check in that window. Deal with it")
        print("   yourself, this tool will not, then run this again.")

    def _stop_if_unfinished(self) -> None:
        """A run where a store stopped for a sign-in, or where a store's list
        did not come whole, did not finish, and it must not read as a clean
        one. It leaves the way every app's run leaves on a sign-out, which
        the panel reports as stopped."""
        if self._cut_short_sides:
            said = " and ".join("your App Store purchases" if side == APP_STORE
                                else "your Apple Store orders"
                                for side in PURCHASE_TYPES if side in self._cut_short_sides)
            print("\nNot all of %s came, so this run stops here rather than finish." % said)
            print("Run it again later to read the rest.")
        if self._stopped_sides:
            print("\nSign in where it asked, then press Resume or run this again.")
        if self._stopped_sides or self._cut_short_sides:
            raise SystemExit(0)

    # -- commands -----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session, so nothing is duplicated in the launcher scripts. You
        sign in, and the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9280")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile {profile}")
        print("Sign in to Report a Problem in the tab that opened. That is the App Store side.")
        print("The Apple Store is a separate sign-in. Open")
        print(f"  {site.STORE_LIST_URL}")
        print("in a second tab and sign in there too, if you want your Apple Store orders.")
        print("Keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode. The browser is launched by login.bat, not here. This
            # only checks the connection and whether each store is signed in.
            print("Checking the connection to your signed-in Apple browser...\n")
            self._say_sign_in_state()
            self.close()
            return
        print("Opening Report a Problem in a dedicated supervised browser profile.")
        print("Sign in manually, with any verification code Apple sends.")
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
        """Whether each store answers as signed in. Reads only."""
        page = self.page()
        family = {"kind": site.SIGNED_OUT, "members": []}
        if site.open_report_page(page):
            family = site.read_family(page)
        if family["kind"] == site.ANSWERED:
            print("Report a Problem is signed in, with %d family member(s)."
                  % len(family["members"]))
        else:
            self._left_open.add(id(page))
            print("Report a Problem is not signed in. Sign in at reportaproblem.apple.com")
            print("in the browser window, keep it open, then check again.")
        tab = self.store_page()
        state = site.goto_store_list(tab)
        if state == site.READY:
            print("The Apple Store is signed in.")
        else:
            self._left_open.add(id(tab))
            print("The Apple Store is not signed in (%s). Sign in to it in the tab" % state)
            print("that just opened. It is a separate sign-in from Report a Problem.")

    def _floor(self) -> str:
        """The date before which nothing is recorded or downloaded."""
        return self.args.start_date or self.config.get("default_start_date") or ""

    def _walk_limit(self) -> str:
        """How far back the App Store search has to read, which is the floor
        or the start of --year, whichever is later."""
        floor = self._floor()
        year = getattr(self.args, "year", None)
        if year:
            start = "%04d-01-01" % int(year)
            return max(floor, start) if floor else start
        return floor

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False,
                     finish: bool = True) -> dict:
        """Discovery pass, both stores unless told one.

        The App Store side asks Report a Problem's own purchase search from
        inside the signed-in page, for the whole family, a batch at a time,
        and keeps the purchases where money was spent. The Apple Store side
        reads the order list's embedded data and then each order's details
        page, one at a time. Nothing is clicked on either.

        A store whose list did not come whole keeps what came, and Pilot, Run
        All and Resume go on with it and with the other store, but the rest
        is missing, so the run stops at its end rather than finish, as it
        does when a store asks for a sign-in. With finish=False the caller
        does that once it has used them."""
        # A Discover that stops on the way, however it stops, is noted as one
        # that stopped, so Resume reads the list again (paperpull_core.listing).
        listing.started(self)
        types = list(types or PURCHASE_TYPES)
        n_new = {APP_STORE: 0, APPLE_STORE: 0}
        if APP_STORE in types:
            n_new[APP_STORE] = self._discover_app_store()
        if APPLE_STORE in types:
            n_new[APPLE_STORE] = self._discover_apple_store()
        self.discovery.save()
        unfinished = bool(self._stopped_sides or self._cut_short_sides)
        narrowed = bool(getattr(self.args, "year", None) or self.args.start_date)
        # Only both stores read to their end let Resume carry on without
        # reading them again. A store that asked for a sign-in or was cut
        # short leaves the listing noted as one that stopped, and so does a
        # run that read one store, or one year or stretch of the purchases,
        # since the rest was not read.
        if not unfinished and not narrowed and set(PURCHASE_TYPES) <= set(types):
            listing.read_whole(self)

        all_recs = [r for r in self.discovery.data.values() if isinstance(r, dict)]
        self.stats["app_store_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == APP_STORE)
        self.stats["apple_store_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == APPLE_STORE)

        if not quiet:
            said = ("Discovery did not read all of your purchases and orders." if unfinished
                    else "Discovery complete.")
            print(f"\n{said} Purchases known {len(all_recs)} "
                  f"({self.stats['app_store_discovered']} App Store, "
                  f"{self.stats['apple_store_discovered']} Apple Store)")
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

    def _discover_app_store(self) -> int:
        """Report a Problem's purchases, the paid ones, for every member."""
        page = self.page()
        floor, limit = self._floor(), self._walk_limit()
        self.journal.op("open_list", "read the app store purchases")
        ready = site.open_report_page(page)
        # The family's members, or the one account signed in when it has no
        # Family Sharing, whose family list answers empty (#55).
        family = site.read_searchers(page)
        if family["kind"] == site.SIGNED_OUT or (family["kind"] == site.FAILED and not ready):
            self._signed_out(APP_STORE, page)
            return 0
        if not ready and family["kind"] == site.ANSWERED:
            # GUESS. Every call the page made carried its session token,
            # RECORDED, and a tab it has just loaded is assumed to be given
            # one. This one was not, and the family list answered anyway, so
            # the search is tried, and a refusal says to sign in again.
            log.warning("Report a Problem answered without the page's session token")
        if family["kind"] != site.ANSWERED:
            # No purchase of this store can be searched for, which is not a
            # store with nothing in it.
            self._cut_short_sides.add(APP_STORE)
            how = ("an answer without the list" if family["kind"] == site.NO_LIST
                   else family["status"] or "no answer")
            print("\n!! Report a Problem did not answer with the family list (%s)." % how)
            print("   This run stops at its end rather than finish. Run it again later.")
            self.write_failure("read the family list", "the family list was not answered")
            return 0
        members = family["members"]
        if not members:
            # The search refuses a call that names nobody, and neither the
            # family list nor the page's own account said who is signed in.
            # Both answered, so asking again gets the same, and the run is
            # not stopped for it.
            print("\n!! Report a Problem named no family member and no account, and its")
            print("   purchase search needs one. Run Diagnose and send the survey.")
            self.write_failure("read the family list", "neither the family nor the account named anyone")
            return 0
        self.journal.op("read_rows", "search the purchases", members=len(members))
        walk = site.walk_purchases(page, [m.dsid for m in members], limit_date=limit,
                                   single=family.get("single", False))
        self.journal.result("searched the purchases", batches=walk["batches"],
                            purchases=len(walk["purchases"]))
        n_new, dropped, owner = 0, 0, self.config.get("owner", "")
        kept = {}
        for raw in walk["purchases"]:
            if site.is_pending(raw):
                # Not charged yet. It is found again once it has been.
                self.stats["pending_skipped"] += 1
                continue
            if not site.is_paid(raw):
                self.stats["free_skipped"] += 1
                continue
            made = site.app_store_purchase(raw, members, owner)
            if not made:
                continue
            if made[0].order_number in kept:
                # One receipt covers one weborder, so a second purchase under
                # the same one adds its lines rather than replacing the first's.
                site.merge_purchase(kept[made[0].order_number], made)
                continue
            kept[made[0].order_number] = made
        paid = len(kept)
        for purchase, extras in kept.values():
            if floor and purchase.purchase_date and purchase.purchase_date < floor:
                dropped += 1
                continue  # before the cutoff, never record or download
            n_new += self._remember(purchase, extras)
        who = (f"{len(members)} family member(s)" if family.get("source") != "account"
               else "one account, no Family Sharing" if family.get("single")
               else "the account signed in")
        print(f"\nApp Store, {who}, {len(walk['purchases'])} "
              f"purchase(s) read in {walk['batches']} batch(es). {paid} paid, "
              f"{self.stats['free_skipped']} free skipped, "
              f"{self.stats['pending_skipped']} pending skipped.")
        if dropped:
            print(f"  {dropped} fell outside the scope you set.")
        if walk["stop"] == site.SIGNED_OUT:
            self._signed_out(APP_STORE, page)
        elif walk["stop"] in (site.REFUSED, site.FAILED, site.NO_LIST):
            # Read as a search with nothing more in it, this let the run
            # finish clean with the older purchases missed. What came is
            # used, and the run stops at its end.
            self._cut_short_sides.add(APP_STORE)
            how = ("an answer without the purchases" if walk["stop"] == site.NO_LIST
                   else walk["status"] or "no answer")
            if walk["batches"] > 1:
                print("\n!! Report a Problem stopped answering the purchase search partway")
                print("   (%s). What was read is kept and used, and this run stops at its" % how)
                print("   end rather than finish. Run it again later to read the rest.")
            else:
                print("\n!! Report a Problem did not answer when this asked for your purchases")
                print("   (%s). This run stops at its end rather than finish. Run it again" % how)
                print("   later.")
            self.write_failure("search the purchases", "a search was not answered",
                               postmortem={"side": "app store", "batches": walk["batches"],
                                           "stop": walk["stop"], "status": walk["status"]})
        elif walk["stop"] == site.BATCH_CAP:
            print("  The search was stopped after %d batches. Set default_start_date or"
                  % walk["batches"])
            print("  pass --start-date to read a shorter stretch at a time.")
        return n_new

    def _discover_apple_store(self) -> int:
        """The Apple Store's orders, from the list and each details page."""
        floor = self._floor()
        tab = self.store_page()
        self.journal.op("open_list", "read the apple store orders")
        state = site.goto_store_list(tab)
        if state == site.SIGNED_OUT:
            self._signed_out(APPLE_STORE, tab)
            return 0
        if state == site.CHALLENGE:
            self._challenged(tab)
            return 0
        if state != site.READY:
            # What the list of an account with no Apple Store orders carries
            # was never seen, so a list without its data is not taken for a
            # list that did not come, which would stop every run of such an
            # account.
            print("\n!! The Apple Store order list did not carry its orders.")
            self.write_failure("read the store orders", "the order list carried no data")
            return 0
        listed = site.parse_order_list(site.read_init_data(tab))
        if listed["more"]:
            # GUESS. The list says when older orders exist, and it carries a
            # "more" action, but paging was never seen, because the account
            # this was built on has three orders and no more. So nothing is
            # guessed at, and it is said out loud instead.
            self.stats["older_store_orders"] = 1
            print("\n  Apple says older Apple Store orders exist. This app does not page")
            print("  the order list yet, so those older orders were not read.")
        n_new, opened, dropped, unread = 0, 0, 0, 0
        for order in listed["orders"]:
            known = self.discovery.get("%s:%s" % (APPLE_STORE, order["order_number"])) or {}
            if known.get("state") in SETTLED:
                continue  # settled already, its details page is not opened again
            if opened:
                # One at a time, the way a person reads them.
                tab.wait_for_timeout(site.STORE_PAUSE_MS)
            opened += 1
            self.journal.op("open_item", "read an order details page", ordinal=opened)
            got_state, detail = site.read_order_detail(tab, order["detail_url"])
            if got_state == site.SIGNED_OUT:
                self._signed_out(APPLE_STORE, tab)
                break
            if got_state == site.CHALLENGE:
                # The next page would only meet the same check.
                self._challenged(tab)
                break
            purchase = site.store_purchase(order, detail) if detail else None
            if purchase is None:
                unread += 1
                continue
            if floor and purchase.purchase_date and purchase.purchase_date < floor:
                dropped += 1
                continue
            n_new += self._remember(purchase)
        print(f"\nApple Store, {len(listed['orders'])} order(s) listed, "
              f"{opened} details page(s) read.")
        if dropped:
            print(f"  {dropped} fell outside the scope you set.")
        if unread:
            # One order's own page, which may come the same way every time,
            # so the run is not stopped for it.
            print(f"  {unread} details page(s) did not carry the order. They are read again next run.")
            self.write_failure("read an order details page", "a details page carried no order")
        return n_new

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

    def _report_tab(self):
        """The Report a Problem tab, on Report a Problem, which every App
        Store call is made from, or None when it asked for a sign-in, which
        is said and stops the App Store side.

        A call from a tab anywhere else is refused before it is sent. A run
        that read no list first, Resume after a Discover that read both to
        their end, had only the new blank tab page() opens when no tab is on
        Report a Problem, and every receipt it asked for failed, run after
        run. So a tab that is not on it is opened there first, the way
        discovery opens it. A page that never comes to hold its session
        token is still used while Report a Problem answers its family list,
        as discovery does."""
        page = self.page()
        if site.on_report_page(page):
            return page
        if self._cdp_mode and page not in self._opened:
            # A tab of the person's that has left Report a Problem is theirs,
            # and it is let go of where they took it, never loaded back, the
            # rule core's tabs module gives every app. Another tab of theirs
            # on Report a Problem is taken, or one of the run's own is opened
            # there below.
            self._work_page = None
            page = self.page()
            if site.on_report_page(page):
                return page
        ready = site.open_report_page(page)
        if not ready and not site.session_alive(page):
            self._signed_out(APP_STORE, page)
            return None
        if not ready:
            log.warning("Report a Problem answered without the page's session token")
        return page

    def process_purchases(self, purchases: List[Purchase], dry_run: bool = False):
        # The line past which Apple refuses an account's receipts is learned
        # anew in each run, from that run's answers (#55).
        self.__dict__.pop("_age_line", None)
        page = self.page() if any(p.purchase_type != APPLE_STORE for p in purchases) else None
        for i, purchase in enumerate(purchases, 1):
            print(f"\n[{i}/{len(purchases)}] {purchase.purchase_type} "
                  f"{purchase.purchase_date or '(date unknown)'} "
                  f"#{purchase.order_number}")
            if self._already_done(purchase):
                print("  Already completed and PDF verified, skipping.")
                self.stats["skipped_completed"] += 1
                continue
            if purchase.purchase_type in self._stopped_sides:
                # That store asked for a sign-in earlier in the run, and
                # nothing is asked of Apple for this one, so there is nothing
                # to pace. The first full run spent ten minutes waiting
                # between purchases it skipped.
                print("  Skipped, this store asked for a sign-in earlier in the run.")
                continue
            # Which document the run is on, so a failure file says how far
            # it got and whether it ever reached a second one.
            try:
                self.journal.op("next_item" if i > 1 else "open_item",
                                "take a document", ordinal=i)
            except Exception:
                pass
            not_asked = self.stats.get("not_asked", 0)
            try:
                self.process_one(page, purchase, dry_run=dry_run)
            except KeyboardInterrupt:
                print("\nInterrupted. Progress is saved, run --resume to continue.")
                raise
            except Exception as e:
                log.exception("Unhandled failure on %s", purchase.key)
                self._record_state(purchase, State.FAILED, notes=f"Unhandled error, {e}")
                self.stats["failed"] += 1
            # Nothing was asked of Apple for a purchase past the line (#55),
            # so there is nothing to pace.
            if self.stats.get("not_asked", 0) == not_asked:
                self._delay()

    def process_one(self, page, purchase: Purchase, dry_run: bool = False):
        if purchase.purchase_type in self._stopped_sides:
            print("  Skipped, this store asked for a sign-in earlier in the run.")
            return
        rec = self.discovery.get(purchase.key) or {}
        if purchase.purchase_date:
            self.stats["dates_processed"].append(purchase.purchase_date)

        # ---- name it (local, deterministic) ----
        if purchase.purchase_type == APPLE_STORE:
            # A store order is named for its main product, from this app's
            # own rules, iPhone, MacBook Air, Magic Keyboard.
            cls = classification.classify_items(purchase.items, self.rules)
            purchase.summary, purchase.confidence, why = cls.summary, cls.confidence, cls.notes
        else:
            # Apple has already said what was bought, so an App Store
            # receipt is named for the app or service, not guessed at.
            purchase.summary, purchase.confidence = site.app_store_summary(rec.get("lines") or [])
            why = "named by Apple"
        review_needed = purchase.confidence == classification.LOW
        notes_extra = f"Items {'; '.join(i.name for i in purchase.items[:12])}" \
            if review_needed and purchase.items else ""
        print(f"  {len(purchase.items)} item(s), named {purchase.summary} "
              f"[{purchase.confidence}] ({why})")

        # ---- a canceled store order, recorded with no receipt ----
        if purchase.purchase_type == APPLE_STORE and site.is_canceled(purchase):
            self._record_state(purchase, State.CANCELED,
                               notes="Order canceled, Apple issued no invoice")
            self._write_csv_rows(purchase, receipt_status="Canceled",
                                 processing_status=State.CANCELED.value,
                                 notes_extra=notes_extra)
            self.stats["canceled"] += 1
            print("  Canceled order, recorded with no receipt.")
            return

        # ---- a store order Apple has not invoiced yet ----
        if purchase.purchase_type == APPLE_STORE and not purchase.receipt_url:
            # Apple invoices an item once it ships or is ready for pickup.
            # Not a terminal state, so the next run looks at it again.
            self._record_state(purchase, State.DISCOVERED,
                               notes="Not invoiced yet. Revisited on the next run.")
            self.stats["not_invoiced"] += 1
            print("  Apple has not invoiced this order yet. It is looked at again next run.")
            return

        if dry_run:
            filename = build_pdf_filename(purchase.purchase_date, purchase.summary, record=purchase)
            print(f"  DRY RUN, would save {filename}")
            return

        # ---- Report a Problem's own page, opened when its tab is not on it ----
        if purchase.purchase_type == APP_STORE:
            page = self._report_tab()
            if page is None:
                return  # it asked for a sign-in, said already, and this one is asked for next run

        # ---- locate + save receipt ----
        saved = self._save_receipt(page, purchase, rec)
        if not saved:
            return  # state already recorded inside

        # ---- CSVs + progress ----
        is_record = purchase.document_type == site.RECORD_TYPE
        self._write_csv_rows(purchase,
                             receipt_status=("Purchase record, Apple refused the receipt"
                                             if is_record else "Downloaded"),
                             processing_status="Review Needed" if review_needed else "Completed",
                             notes_extra=notes_extra)
        final_state = State.NEEDS_MANUAL_REVIEW if review_needed else State.COMPLETED
        notes = "; ".join(n for n in (
            "Low classification confidence" if review_needed else "",
            "A purchase record, Apple refused its receipt" if is_record else "") if n)
        self._record_state(purchase, final_state, notes=notes)
        if review_needed:
            self.stats["manual_review"] += 1
        self.journal.checkpoint('a document is saved')
        if is_record:
            print(f"  Saved {purchase.pdf_filename}, a record from Apple's purchase history, "
                  f"since Apple did not give the receipt on {site.REFUSED_RUNS_FOR_RECORD} "
                  f"separate runs")
        else:
            self.stats["receipts_downloaded"] += 1
            print(f"  Saved {purchase.pdf_filename}")

    # -- receipt saving -----------------------------------------------------

    def _save_receipt(self, page, purchase: Purchase, rec: dict) -> bool:
        """Save one receipt as a verified PDF.

        An App Store purchase's receipt is Apple's own emailed receipt,
        asked for from inside Report a Problem and drawn in a blank tab. An
        Apple Store order's is its invoice page. Either is printed through
        delivery.render, to a staging file that is read back and moved into
        place only when it carries this purchase's own order number."""
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
            got = self._capture_document(page, purchase, out_path, rec)
        except _SignedOut as e:
            # Not a terminal state, so the next run asks for it again.
            self._record_state(purchase, State.DISCOVERED,
                               notes="Signed out before the receipt was read, revisited next run")
            self._signed_out(e.side, e.page)
            return False
        except _AppleRefused as e:
            return self._apple_refused(page, purchase, rec, asked=e.asked)
        except Exception as e:
            log.exception("PDF generation failed for %s", purchase.key)
            self._record_state(purchase, State.FAILED,
                               notes=f"PDF generation failed, {e}")
            self.stats["failed"] += 1
            self.write_failure("save the receipt", "capturing the receipt raised")
            return False

        if got is None:
            # Apple answered without a receipt, or the invoice page never
            # showed this order. Failed rather than finished, so the next run
            # tries it again.
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
            # Nothing checked reached the folder, so nothing is finished, and
            # nothing is printed again outside the check.
            self._record_state(purchase, State.FAILED,
                               notes="the receipt did not render, %s" % got.outcome)
            self.stats["failed"] += 1
            self.write_failure("save the receipt", "the receipt did not render")
            self.journal.result("could not save the document")
            return False
        purchase.receipt_count = 1
        ok = self._finish_pdf(page, purchase, out_path, reprint=False)
        self.journal.result("saved the document" if ok
                            else "could not save the document",
                            bytes_written=out_path.stat().st_size
                            if out_path.exists() else 0)
        return ok

    def _capture_document(self, page, purchase: Purchase, out_path: Path, rec: dict):
        """A Delivery, or None when no receipt came back to print. Raises
        _SignedOut when a store asked for a sign-in."""
        if purchase.purchase_type == APPLE_STORE:
            return self._capture_store_invoice(purchase, out_path)
        return self._capture_app_store_receipt(page, purchase, out_path, rec)

    def _capture_app_store_receipt(self, page, purchase: Purchase, out_path: Path, rec: dict):
        """Apple's receipt, as the page's own View Receipt asks for it, with
        the purchaser's dsid in the header, then drawn with set_content in a
        blank tab of the same browser and printed by the core. Asked once,
        and not at all past the line this run has learned for the account
        (#55)."""
        if self._past_the_line(purchase) and not self._would_make_a_record(purchase):
            self.stats["not_asked"] = self.stats.get("not_asked", 0) + 1
            raise _AppleRefused(asked=False)
        got = self._ask_for_receipt(page, purchase.order_number, str(rec.get("dsid") or ""))
        if got["kind"] == site.SIGNED_OUT:
            raise _SignedOut(APP_STORE, page)
        if got["kind"] != site.ANSWERED or not got["html"]:
            log.warning("The receipt was answered %s (%s)", got["kind"], got["status"] or "no answer")
            # Apple answered and gave no receipt. No answer at all is not
            # counted, and neither is an order this app would not ask for.
            if got["status"] and got["kind"] in (site.REFUSED, site.ANSWERED):
                self._note_answer(purchase, "refused")
                raise _AppleRefused()
            self._note_answer(purchase, "other")
            return None
        self._note_answer(purchase, "given")
        html = got["html"]
        self.journal.checkpoint("the receipt is in hand")
        def draw(staged):
            receipt_pdf.print_html_to_pdf(page, html, staged)
            site.drop_blank_last_pages(staged)

        return delivery.render(
            page,
            draw,
            out_path,
            expect=site.identity_for(purchase),
            journal=self.journal,
            strict=self._strict())

    def _ask_for_receipt(self, page, weborder: str, dsid: str) -> dict:
        """The receipt call, with the request census stepped aside for it.

        The census goes into a failure file, which a tester may post in
        public, and it masks an id in an address only when the id has a
        shape it knows. A paid App Store order id does not have one, so the
        census does not watch this one call, and the journal writes down its
        status as a number instead."""
        census = self._requests
        if census is not None:
            census.stop()
        try:
            got = site.fetch_invoice(page, weborder, dsid)
        finally:
            if census is not None:
                census.start()
        self.journal.result("asked for the receipt", status=int(got.get("status") or 0))
        return got

    def _capture_store_invoice(self, purchase: Purchase, out_path: Path):
        """The order's invoice page in a new tab, its Print button hidden for
        the PDF, printed by the core, and the tab closed. Nothing is pressed."""
        tab = site.open_invoice(self.browser(), purchase.receipt_url)
        self._opened.append(tab)
        keep = False
        try:
            if site.looks_signed_out(tab):
                keep = True
                raise _SignedOut(APPLE_STORE, tab)
            if not site.wait_for_invoice(tab, purchase.order_number):
                # A sign-in page can arrive after the invoice address has
                # loaded, and that is a sign-in, not a missing receipt.
                if site.looks_signed_out(tab):
                    keep = True
                    raise _SignedOut(APPLE_STORE, tab)
                return None
            site.hide_print_controls(tab)

            def draw(staged):
                receipt_pdf.print_page_to_pdf(tab, staged)
                site.drop_blank_last_pages(staged)

            return delivery.render(
                tab,
                draw,
                out_path,
                expect=site.identity_for(purchase),
                journal=self.journal,
                strict=self._strict())
        finally:
            if not keep:
                try:
                    tab.close()
                except Exception:
                    pass

    def _refused(self, purchase: Purchase, got) -> bool:
        """A receipt was printed, read back, and is not this purchase.

        Nothing is quarantined because nothing was kept. The file was
        destroyed at the staging path, which is the point of checking
        before writing rather than after."""
        why = "the receipt that printed is not this purchase"
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

    # -- a receipt Apple will not give -------------------------------------

    def _run_key(self) -> str:
        """This run, by the time it started, which is also the time in its
        log file's name, so that a refusal is counted once per run however
        often it is met, and each one can be traced to its run's log."""
        if not getattr(self, "_run_id", ""):
            self._run_id = str(self.stats.get("started") or "") or now_iso()
        return self._run_id

    def _apple_refused(self, page, purchase: Purchase, rec: dict, asked: bool = True) -> bool:
        """Report a Problem answered, signed in, and gave no receipt, or was
        not asked, past the line this run learned for the account. The
        purchase is looked at again on later runs, and once it has been
        refused on REFUSED_RUNS_FOR_RECORD separate runs, asked or not, a
        record made from Apple's own purchase history is saved in its place.
        The runs it was not asked on are kept apart, so the record can say
        so."""
        prog = self.progress.get(purchase.key) or {}
        runs = [r for r in (prog.get("refused_runs") or []) if isinstance(r, str) and r]
        quiet = [r for r in (prog.get("not_asked_runs") or []) if isinstance(r, str) and r]
        if self._run_key() not in runs:
            runs.append(self._run_key())
        if not asked and self._run_key() not in quiet:
            quiet.append(self._run_key())
        needed = site.REFUSED_RUNS_FOR_RECORD
        if len(runs) >= needed:
            return self._save_purchase_record(page, purchase, rec, runs, quiet)
        self._record_state(purchase, State.FAILED,
                           notes=("Apple refused its receipt" if asked else
                                  "Not asked, Apple had refused this account's newer purchases "
                                  "before it in this run"),
                           extra={"refused_runs": runs, "not_asked_runs": quiet})
        self.stats["failed"] += 1
        if not asked:
            print(f"  Not asked. In this run Apple refused {site.REFUSAL_STREAK} of this "
                  f"account's newer purchases in a row, each older than any receipt it had given "
                  f"the account, so this counts as refused, on {len(runs)} of {needed} separate "
                  f"runs. It is asked on the run that would make its record.")
            return False
        self.stats["no_receipt"] += 1
        self.write_failure("fetch the receipt", "Apple refused the receipt")
        self.journal.result("could not save the document")
        print(f"  Apple would not give this receipt, on {len(runs)} of {needed} separate runs. "
              f"It is asked again next run, and after {needed} a record is made from "
              f"Apple's purchase history instead.")
        return False

    # -- the line past which Apple refuses an account's receipts (#55) -----
    #
    # Report a Problem refuses an account's oldest receipts, and where that
    # starts differs by account (site.REFUSAL_STREAK). Every refused purchase
    # used to be asked on every run, a few seconds each, until its third
    # refusal made a record of it. Purchases go newest first, so once Apple
    # has refused REFUSAL_STREAK of an account's purchases in a row, each
    # older than any receipt it has given that account, the rest are past the
    # line and are not asked this run. Each counts as refused on it, so a
    # record still waits for three separate runs, and the run that would make
    # a purchase's record asks it, so every record rests on Apple's own
    # refusal. The newest purchase of each older year is still asked, and a
    # receipt Apple gives there takes the line away, so a line in the wrong
    # place does not hold for the run, and the next run starts from the older
    # receipt. --redownload asks every purchase, as it always has.

    def _line_state(self) -> dict:
        return self.__dict__.setdefault(
            "_age_line", {"given": {}, "streak": {}, "line": {}, "year": {}})

    def _apple_account(self, purchase: Purchase) -> str:
        """Whose purchase this is, the dsid it was searched under."""
        return str((self.discovery.get(purchase.key) or {}).get("dsid") or "")

    def _oldest_given(self, account: str) -> str:
        """The date of the oldest App Store receipt Apple has given this
        account, from every record kept and this run, or "" for none."""
        given = self._line_state()["given"]
        if account not in given:
            dates = []
            for key, prog in (getattr(self.progress, "data", None) or {}).items():
                if not isinstance(prog, dict) or not prog.get("downloaded_ok"):
                    continue
                if prog.get("purchase_type") != APP_STORE or \
                        prog.get("document_type") == site.RECORD_TYPE:
                    continue
                # A receipt whose account is not known counts for every
                # account, since leaving it out would make a line easier to
                # learn (review).
                if str((self.discovery.get(key) or {}).get("dsid") or "") not in (account, ""):
                    continue
                if prog.get("purchase_date"):
                    dates.append(str(prog["purchase_date"]))
            given[account] = min(dates) if dates else ""
        return given[account]

    def _note_answer(self, purchase: Purchase, what: str) -> None:
        """What Apple answered for an App Store receipt, "given", "refused" or
        "other", kept per account. A refusal older than any receipt Apple
        has given the account adds to its count in a row, anything else
        ends it, and a receipt given past the line takes the line away."""
        st = self._line_state()
        account, when = self._apple_account(purchase), purchase.purchase_date or ""
        if what != "refused":
            st["streak"][account] = 0
            if what == "given":
                oldest = self._oldest_given(account)
                if when and (not oldest or when < oldest):
                    st["given"][account] = when
                if st["line"].pop(account, None):
                    print("  Apple gave this receipt, older than the ones it refused, so "
                          "older purchases are asked again.")
            return
        oldest = self._oldest_given(account)
        if not (when and oldest and when < oldest):
            st["streak"][account] = 0
            return
        st["streak"][account] = st["streak"].get(account, 0) + 1
        if st["streak"][account] >= site.REFUSAL_STREAK and account not in st["line"]:
            st["line"][account] = when
            print(f"  Apple has refused the last {site.REFUSAL_STREAK} of this account's "
                  f"purchases, each older than any receipt it has given it. Older ones are not "
                  f"asked this run, but for the newest of each year, and each counts as refused.")
        # A year's purchases past the line go unasked only once Apple has
        # refused one of them. One that got no answer leaves its year to be
        # asked (review).
        line = st["line"].get(account)
        if line and when <= line:
            st["year"][account] = when[:4]

    def _past_the_line(self, purchase: Purchase) -> bool:
        """Whether this App Store purchase is past the line this run has
        learned for its account, and so is not asked. A year's purchases
        are asked until Apple refuses one of them, and --redownload asks
        every purchase."""
        if purchase.purchase_type != APP_STORE or not purchase.purchase_date:
            return False
        if getattr(self.args, "redownload", False):
            return False
        st = self._line_state()
        account = self._apple_account(purchase)
        line = st["line"].get(account)
        if not line or purchase.purchase_date > line:
            return False
        return purchase.purchase_date[:4] == st["year"].get(account)

    def _would_make_a_record(self, purchase: Purchase) -> bool:
        """Whether a refusal on this run would make the purchase's record. It
        is asked then, so no record is made without Apple refusing the
        receipt itself (review)."""
        prog = self.progress.get(purchase.key) or {}
        runs = {r for r in (prog.get("refused_runs") or []) if isinstance(r, str) and r}
        runs.add(self._run_key())
        return len(runs) >= site.REFUSED_RUNS_FOR_RECORD

    def _save_purchase_record(self, page, purchase: Purchase, rec: dict, runs: list,
                              quiet: tuple = ()) -> bool:
        """The record of a purchase whose receipt Apple refused on enough
        separate runs, printed like a receipt through delivery.render and
        checked for its own order ID, and filed as a Purchase Record so it is
        never taken for Apple's receipt."""
        purchase.document_type = site.RECORD_TYPE
        folder = self.paths.folder_for(purchase.purchase_type, purchase.document_type)
        filename = build_pdf_filename(purchase.purchase_date, purchase.summary,
                                      purchase.document_type, record=purchase)
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=purchase.order_number)
        self.progress.update(purchase.key, {"refused_runs": runs, "not_asked_runs": list(quiet)})
        page_html = site.purchase_record_html(purchase, rec.get("lines") or [],
                                              str(rec.get("purchaser") or ""), len(runs),
                                              made_on=datetime.now().date().isoformat(),
                                              not_asked=len(quiet))

        def draw(staged):
            receipt_pdf.print_html_to_pdf(page, page_html, staged)
            site.drop_blank_last_pages(staged)

        try:
            got = delivery.render(page, draw, out_path, expect=site.identity_for(purchase),
                                  journal=self.journal, strict=self._strict())
        except Exception as e:
            log.exception("The purchase record failed for %s", purchase.key)
            got = None
            why = f"the purchase record did not render, {e}"
        else:
            why = "the purchase record did not render, %s" % got.outcome
        if got is not None and got.outcome == delivery.WRONG:
            return self._refused(purchase, got)
        if got is None or got.outcome != delivery.SAVED:
            self._record_state(purchase, State.FAILED, notes=why)
            self.stats["failed"] += 1
            self.write_failure("save the purchase record", "the record did not render")
            self.journal.result("could not save the document")
            return False
        ok = self._finish_pdf(page, purchase, out_path, reprint=False)
        # A record is not a receipt, and the index says how many receipts
        # a purchase has.
        purchase.receipt_count = 0
        if ok:
            self.stats["purchase_records"] = self.stats.get("purchase_records", 0) + 1
        self.journal.result("saved the document" if ok else "could not save the document",
                            bytes_written=out_path.stat().st_size if out_path.exists() else 0)
        return ok

    def _finish_pdf(self, page, purchase: Purchase, out_path: Path,
                    popup=None, source_page=None, reprint: bool = True) -> bool:
        """Validate what was saved, and file it or quarantine it.

        reprint is off for a receipt that came through delivery.render. A
        reprint there goes straight to the final path, unchecked, over a
        receipt that had been checked, so a file that fails validation is
        quarantined as it is instead."""
        purchase.pdf_path = str(out_path)
        purchase.pdf_filename = out_path.name
        self._record_state(purchase, State.PDF_SAVED)

        tokens = receipt_pdf.expected_tokens_for(purchase)
        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
        if not result.ok and reprint:
            log.warning("Validation failed (%s), retrying once", result.reason)
            self.stats["validation_failures"] += 1
            try:
                retry_page = source_page or page
                receipt_pdf.print_page_to_pdf(retry_page, out_path)
                result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
            except Exception as e:
                log.warning("Retry failed, %s", e)
        if not result.ok:
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
        # The purchaser, the dsid a receipt is asked for with, and the line
        # items as Apple named them, which the Purchase has no fields for.
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
        # Some of each kind, since a receipt Report a Problem hands over and
        # an invoice page on the store are two different captures, and a
        # pilot of one proves nothing about the other.
        selected: List[Purchase] = (
            self._select_purchases(APP_STORE, limit=self.config.get("pilot_app_store", 3))
            + self._select_purchases(APPLE_STORE, limit=self.config.get("pilot_apple_store", 2)))
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
            if rec.get("purchaser"):
                print(f"    Bought by   {rec.get('purchaser')}")
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
        print("e.g.  python apple_receipts.py --all")

    def cmd_run(self, types: Optional[List[str]], mode_name: str):
        self.stats["mode"] = mode_name
        types = list(types or PURCHASE_TYPES)
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Apple purchase history")
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
        # store asked for a sign-in or its list did not come whole, that is
        # some of them, and Resume finished clean on those with the rest
        # never looked for. So both lists are read first, and a store that
        # does not come this time either still leaves the purchases already
        # found to download, and the run stops at its end.
        # On an install that has never listed anything, Resume says so and
        # stops (paperpull_core.listing).
        if listing.read_again_first(self):
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
        renaming.review_names(self, ask, words=renaming.PLAIN_WORDS)

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
        # journal when nothing had written to it yet.
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
            provider='Apple', text=text, extra=extra)
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
        and carrying each store's counts from Diagnose as numbers, yes or
        no, and words this app wrote. It is the one to send."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Apple',
            extra=self._survey_extra() or None)

    def _survey_extra(self) -> dict:
        """Diagnose's counts for the survey, nothing but numbers, yes or no,
        and the fixed words the site module answers with."""
        out = {}
        for side in ("app_store", "apple_store"):
            found = (self._survey or {}).get(side) or {}
            out[side] = {k: v for k, v in found.items()
                         if isinstance(v, (bool, int)) or k in ("stop", "state")}
        return out

    def cmd_diagnose(self):
        """Both stores as this browser sees them, in counts, written to
        Diagnostics/diagnose-apple.json beside the survey that is safe to
        send. Downloads nothing and presses nothing, and no screenshot is
        taken."""
        self.stats["mode"] = "diagnose"
        words = words_for('Apple', site)
        info = {"timestamp": now_iso(), "app": "apple"}
        try:
            info["app_store"] = self._survey_app_store()
        except Exception as e:
            info["app_store"] = {"error": type(e).__name__}
        try:
            info["apple_store"] = self._survey_apple_store()
        except Exception as e:
            info["apple_store"] = {"error": type(e).__name__}
        self._survey = info
        out = self.paths.diagnostics / "diagnose-apple.json"
        write_shaped(out, info, words)
        print(f"  Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        a = info.get("app_store") or {}
        print("  App Store, signed in %s, %s member(s), %s purchase(s) read, %s paid, "
              "%s free, %s pending"
              % tuple(shape_tree(v, words) for v in (
                  "yes" if a.get("signed_in") else "no", a.get("members", 0),
                  a.get("purchases", 0), a.get("paid", 0), a.get("free", 0),
                  a.get("pending", 0))))
        s = info.get("apple_store") or {}
        print("  Apple Store, signed in %s, %s order(s) listed, %s with an invoice, "
              "%s canceled"
              % tuple(shape_tree(v, words) for v in (
                  "yes" if s.get("signed_in") else "no", s.get("orders", 0),
                  s.get("with_invoice", 0), s.get("canceled", 0))))

    def _survey_app_store(self) -> dict:
        """Report a Problem in counts. Reads only."""
        page = self.page()
        out = {"signed_in": False, "session_token": False, "family_status": 0,
               "members": 0, "organizer_found": False, "batches": 0,
               "stop": "", "reached_end": False, "purchases": 0, "paid": 0,
               "free": 0, "pending": 0, "paid_by_others": 0}
        out["session_token"] = site.open_report_page(page, wait_ms=20000)
        family = site.read_searchers(page)
        out["family_status"] = family["status"]
        out["signed_in"] = family["kind"] == site.ANSWERED
        members = family["members"]
        out["members"] = len(members)
        out["organizer_found"] = any(m.organizer for m in members)
        # Whether the family list named the members or, with no Family
        # Sharing, the page's own account did (#55).
        out["searched_by"] = family.get("source") or "family"
        out["single_account"] = bool(family.get("single"))
        if out["signed_in"] and members:
            walk = site.walk_purchases(page, [m.dsid for m in members],
                                       max_batches=DIAGNOSE_BATCHES,
                                       single=bool(family.get("single")))
            out["batches"], out["stop"] = walk["batches"], walk["stop"]
            out["reached_end"] = walk["stop"] == site.END
            out.update(site.purchase_counts(walk["purchases"], members))
            first = walk["purchases"][0] if walk["purchases"] else {}
            # Apple's own field names, the same for every account, for a
            # repair. Only in the detailed file.
            out["purchase_fields"] = sorted(k for k in first if isinstance(k, str))[:40]
            lines = [p for p in first.get("plis") or [] if isinstance(p, dict)]
            out["line_fields"] = sorted(k for k in (lines[0] if lines else {})
                                        if isinstance(k, str))[:40]
        return out

    def _survey_apple_store(self) -> dict:
        """The Apple Store in counts, the list and a few details pages. Reads only."""
        tab = self.store_page()
        state = site.goto_store_list(tab)
        out = {"signed_in": state == site.READY, "state": state, "orders": 0,
               "more_orders": False, "details_read": 0, "with_invoice": 0,
               "canceled": 0, "not_invoiced": 0}
        if state != site.READY:
            self._left_open.add(id(tab))
            return out
        listed = site.parse_order_list(site.read_init_data(tab))
        out["orders"], out["more_orders"] = len(listed["orders"]), listed["more"]
        for n, order in enumerate(listed["orders"][:DIAGNOSE_DETAILS]):
            if n:
                tab.wait_for_timeout(site.STORE_PAUSE_MS)
            _state, detail = site.read_order_detail(tab, order["detail_url"])
            purchase = site.store_purchase(order, detail) if detail else None
            if purchase is None:
                continue
            out["details_read"] += 1
            if site.is_canceled(purchase):
                out["canceled"] += 1
            elif purchase.receipt_url:
                out["with_invoice"] += 1
            else:
                out["not_invoiced"] += 1
        return out

    # -- run summary --------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a receipt, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Apple',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Apple Receipts, run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"App Store purchases known: {s.get('app_store_discovered', 0)}",
            f"Apple Store orders known:  {s.get('apple_store_discovered', 0)}",
            f"NEW files this run:        {len(new_files)}",
            f"Receipts downloaded:       {s.get('receipts_downloaded', 0)}",
            f"Purchase records made:     {s.get('purchase_records', 0)}",
            f"Skipped (already done):    {s.get('skipped_completed', 0)}",
            f"Free downloads skipped:    {s.get('free_skipped', 0)}",
            f"Pending purchases skipped: {s.get('pending_skipped', 0)}",
            f"Canceled orders:           {s.get('canceled', 0)}",
            f"Not invoiced yet:          {s.get('not_invoiced', 0)}",
            f"No receipt returned:       {s.get('no_receipt', 0)}",
            f"Older, not asked:          {s.get('not_asked', 0)}",
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
    ap = argparse.ArgumentParser(description="Local supervised Apple receipt downloader")
    modes = [
        ("login", "open browser for manual Apple sign-in"),
        ("discover", "discovery pass only, writes discovery.json"),
        ("pilot", "pilot, the newest few of each kind"),
        ("all", "process every purchase (asks for confirmation)"),
        ("app-store", "process App Store purchases only"),
        ("apple-store", "process Apple Store orders only"),
        ("resume", "resume incomplete purchases"),
        ("verify", "re-validate every indexed PDF"),
        ("rename", "rename downloaded files to this app's current naming"),
        ("review-names", "interactively fix low-confidence names"),
        ("diagnose", "survey both stores in counts, write diagnostics"),
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
        elif getattr(args, "app_store", False):
            app.cmd_run(["App Store"], "app-store")
        elif getattr(args, "apple_store", False):
            app.cmd_run(["Apple Store"], "apple-store")
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
