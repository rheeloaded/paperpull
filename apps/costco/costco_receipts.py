"""Costco purchase-history & receipt downloader (local, supervised).

Usage:
    python costco_receipts.py --login
    python costco_receipts.py --discover
    python costco_receipts.py --pilot            (newest few of each kind)
    python costco_receipts.py --all
    python costco_receipts.py --online           (pickup, delivery and ship orders only)
    python costco_receipts.py --instore          (warehouse, gas and pharmacy only)
    python costco_receipts.py --resume
    python costco_receipts.py --verify
    python costco_receipts.py --review-names
    python costco_receipts.py --diagnose [--order-number N]
    python costco_receipts.py --dry-run

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-purchases N  --order-number N

Everything runs locally. No receipt data leaves this machine.
Authentication is always manual (--login opens a browser and waits for you).
"""
from __future__ import annotations

from paperpull_core import delivery
from paperpull_core import identity
from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import not_shown
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.restore import restoring
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

from paperpull_core import classification, receipt_pdf
from paperpull_core import browser as browser_launcher
import costco_site as site
from paperpull_core.models import (IN_STORE, ONLINE, Item, Purchase, State)
from paperpull_core.words import Fixed, shape_tree, words_for, write_shaped
from storage import (CsvFile, JsonStore, ORDER_HISTORY_COLUMNS, Paths,
                     RECEIPT_INDEX_COLUMNS, atomic_write_text, build_pdf_filename, load_config, now_iso, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("costco_receipts")


# A key a record did not have before Rename settled its store, so a
# preview can take it away again.
_MISSING = object()


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
    # Set when discovery passed over a tab or a quarter it could not choose,
    # so the run goes on with what it read and stops at its end rather than
    # finish (_stop_if_cut_short).
    _list_cut_short = False

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
            "online_discovered": 0, "instore_discovered": 0,
            "receipts_downloaded": 0,
            "skipped_completed": 0, "canceled": 0, "no_receipt": 0,
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
        never scripted. Plain Chromium is enough for Costco - it does not block
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
                raise not_signed_in(cdp_url, e)
            if not self._browser.contexts:
                raise SystemExit("Connected browser has no context; open a tab and retry.")
            self._context = self._browser.contexts[0]
            self._cdp_mode = True
            # Install the print-suppression hook at context level so any popup
            # window Costco opens to print also has window.print() intercepted
            # (prevents the modal native print dialog from freezing the browser).
            try:
                self._context.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
            except Exception:
                pass
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
        failure.watch_errors(self._work_page)
        self.requests
        site.set_journal(self.journal)
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
            print("\n!! Costco appears to have signed you out.")
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
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9268")
        profile = self.config["profile_dir"]
        url = site.URLS.get("orders") or site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            raise SystemExit(NOTHING_OPENED)
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print(f"Sign in, keep the window OPEN, then {after_sign_in()}.")

    def _look_at_orders(self, page):
        """Open Orders & Purchases and say what is there, as (listed,
        challenge).

        Only its tabs show a signed-in session, and they are drawn whether
        or not there is anything under them. When they do not come the page
        is looked at again for a little while, because a bot check can leave
        the page blank and a moment later turn it into the check, and one
        look at the blank page finds nothing to name. That one look is how
        --login said Success on a page with no history on it."""
        if site.goto_orders(page):
            return True, site.detect_security_challenge(page)
        challenge = site.challenge_after_a_moment(page)
        return site.orders_listed(page), challenge

    def _open_orders(self, page) -> None:
        """Open Orders & Purchases and go on only once it is there.

        Discovery used to go on from a page the tabs never came to, find no
        purchases on it and finish as though there were none, so a run read
        as clean with its new purchases missed."""
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
            print("\n!! Your Costco orders and purchases did not load, so this cannot")
            print("find any of them. Look at the browser window. If Costco is asking")
            print("you to prove you are a person, or asking you to sign in, answer it")
            print("there yourself. I will NOT attempt to bypass it.")
            self.write_failure("open Orders & Purchases", "its tabs did not appear")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page shows your purchases (or Ctrl+C to quit)... ") is None:
                print("Once it shows your purchases, run this again.")
                raise SystemExit(0)
        self.check_session(page)

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode: the browser is launched by login.bat (not here). This
            # just verifies we can connect and that you are signed in.
            print("Checking the connection to your signed-in Costco browser...\n")
            page = self.page()
            listed, challenge = self._look_at_orders(page)
            if challenge:
                print(f"!! {challenge}")
                print("Resolve it yourself in the browser window, then re-run --login.")
            elif site.looks_signed_out(page):
                print("Connected, but Costco shows the signed-out page.")
                print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
            elif listed:
                print("Success: connected to your signed-in Costco session.")
                print("Keep that browser window OPEN, then run the diagnostics or pilot.")
            else:
                print("Connected, but your Costco orders and purchases did not load, so")
                print("this cannot say whether you are signed in. Look at the browser")
                print("window. If Costco asks you to prove you are a person, or asks you")
                print("to sign in, answer it there yourself, keep the window OPEN, then")
                print("re-run --login.")
            self.close()
            return
        print("Opening Costco.com in a dedicated supervised browser profile.")
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
            print("Sign in in the browser, then run:  python costco_receipts.py --login")
        elif listed:
            print("Signed-in session detected.")
        else:
            print("Your Costco orders and purchases did not load, so this cannot say")
            print("whether you are signed in. Look at the browser window, answer")
            print("anything Costco asks there yourself, then run --login again.")
        self.close()

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False,
                     finish: bool = True) -> dict:
        """Discovery pass: the purchase-history API, called from inside the
        signed-in page the way the page itself calls it, every page of it
        until the API says it is the last. Nothing clicked.

        A list read only in part (a tab or a quarter passed over) keeps the
        purchases it found, and Pilot, Run All and Resume go on with them,
        but the run stops at its end rather than finish. With finish=False
        the caller does that once it has used them."""
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, so Resume reads the list again (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        n_new = 0
        floor = self.args.start_date or self.config.get("default_start_date")

        self._open_orders(page)
        state = site.history_state(page)
        if state == "no-membership":
            print("\nCostco is asking for a membership number before it will show")
            print("warehouse receipts. Link it under Account, then run this again.")
        hist = site.fetch_history(page)
        records = hist.get("records") or []
        log.info("Purchase list: %d record(s) read from the page", len(records))
        if not records and state != "empty":
            print("\nNo purchases were found on the page.")
            print("This app was built without a Costco account, so where the")
            print("purchases sit on the page is a guess, and this is what a wrong")
            print("guess looks like. Run `record`, click your way to one receipt,")
            print("and send the file. That turns the guess into the answer.")
            log.warning("Nothing read from the page. Built without an account, "
                        "so run `record` and share the file.")
        if hist.get("passed_over"):
            # A tab that would not open or a quarter the picker offered that
            # would not take is a part of the list missing. The run goes on
            # with what it read and stops at its end rather than finish
            # (_stop_if_cut_short), and Resume reads the list again.
            self._list_cut_short = True
            log.info("Purchase list: the %s could not be chosen",
                     " and the ".join(hist["passed_over"]))
            print("\n!! Costco's purchase list was not read whole, since a tab or a quarter on")
            print("it could not be chosen. What was read is kept, and this run stops at its")
            print("end rather than finish. The next run reads the list again.")
            self.write_failure("read the purchase list", "some of the list could not be chosen")
        purchases = [pp for pp in (site.record_to_purchase(r) for r in records) if pp]
        for purchase in purchases:
            if types and purchase.purchase_type not in types:
                continue
            if floor and purchase.purchase_date and purchase.purchase_date < floor:
                continue  # before the cutoff: never record or download
            key = purchase.key
            store = self._listed_store(purchase)
            if self.discovery.get(key) is None:
                rec = purchase.to_dict()
                rec["state"] = State.DISCOVERED.value
                rec["store_info"], rec["store_read"] = store, bool(store)
                self.discovery.update(key, rec, save=False)
                n_new += 1
            else:
                self.discovery.update(key, {
                    "details_url": purchase.details_url,
                    "receipt_url": purchase.receipt_url,
                    "total": purchase.total or self.discovery.get(key).get("total", ""),
                    "status": purchase.status or self.discovery.get(key).get("status", ""),
                    # The list says In-Warehouse for every warehouse
                    # receipt, gas included, so a store read off the
                    # receipt is kept over it (#60).
                    "store_info": store,
                    "store_read": bool(store),
                    "notes": purchase.notes,
                }, save=False)
        self.discovery.save()
        # The whole list is in, and only now may a Resume carry on from it
        # without reading it again (paperpull_core.listing). A list read in
        # part is not, and the listing stays one that stopped.
        if not self._list_cut_short:
            listing.read_whole(self)

        all_recs = list(self.discovery.data.values())
        self.stats["online_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == ONLINE)
        self.stats["instore_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == IN_STORE)

        if not quiet:
            print("\nDiscovery %s. Purchases known: %d"
                  % ("read part of the purchase list" if self._list_cut_short else "complete",
                     len(all_recs)))
            by_year = {}
            for r in all_recs:
                y = (r.get("purchase_date") or "?")[:4]
                by_year[y] = by_year.get(y, 0) + 1
            summary = ", ".join(f"{y}: {c}" for y, c in sorted(by_year.items(), reverse=True))
            print(f"  ({summary or 'none'})")
            dates = sorted(r.get("purchase_date") for r in all_recs if r.get("purchase_date"))
            if dates:
                print(f"  Date range: {dates[0]} .. {dates[-1]}")
        if finish:
            self._stop_if_cut_short()
        return {"new": n_new}

    def _stop_if_cut_short(self) -> None:
        """A run that did not read the whole purchase list did not finish,
        and must not read as a clean one. Once it has used what came, it
        leaves on SystemExit the way a run leaves on a sign-out, which the
        panel reports as stopped after Pilot, Run All and Resume."""
        if self._list_cut_short:
            print("\nNot all of Costco's purchase list was read, so this run stops here rather")
            print("than finish. Run it again later to read the rest.")
            raise SystemExit(0)

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
        # (You already has 2024-and-earlier Costco receipts).
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
        # An older version recorded this final when the receipt page did not
        # show the receipt, which says nothing about whether there is one,
        # so it is asked for again (#70).
        if not_shown.asked_again(rec):
            return False
        # terminal / already-completed (incl. records made before the
        # downloaded_ok marker existed): done, do not re-download.
        if state in (State.COMPLETED.value, State.PDF_VERIFIED.value,
                     State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value):
            return True
        # a review copy counts only if its PDF is still present and valid;
        # a quarantined / failed one should be retried.
        if state == State.NEEDS_MANUAL_REVIEW.value:
            pdf_path = rec.get("pdf_path", "")
            return bool(pdf_path and Path(pdf_path).exists()
                        and receipt_pdf.validate_pdf(
                            Path(pdf_path), self.config["min_pdf_bytes"]).ok)
        return False

    # -- processing core ----------------------------------------------------

    def process_purchases(self, purchases: List[Purchase], dry_run: bool = False):
        page = self.page()
        # Every row, so a capture can be checked against the ones it
        # could have come back with instead. Two warehouse visits to the
        # same store on one day for the same amount are one row to this
        # app, which warehouse_key says out loud, and the rows either
        # side are what an index off by one lands on.
        self._rows = [site.identity_for(p) for p in purchases]
        for i, purchase in enumerate(purchases, 1):
            self._row_index = i - 1
            print(f"\n[{i}/{len(purchases)}] {purchase.purchase_type} "
                  f"{purchase.purchase_date or '(date unknown)'} "
                  f"#{purchase.order_number}")
            if self._already_done(purchase):
                print(not_shown.skipped(self.progress.get(purchase.key),
                                        "  Already completed and PDF verified - skipping."))
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
        # Before anything is recorded, even a page that fails to load, since
        # every record writes the purchase's store (#60, as Kroger does).
        self._forget_unread_store(purchase)
        n = self.stats.get("receipts_downloaded", 0)
        self.journal.op("next_item" if n else "open_item",
                        "take the next document", ordinal=n)
        self.journal.checkpoint("before opening a document")
        # ---- an order still pending has no receipt yet ----
        if "Pending order" in (purchase.notes or "") or (purchase.status or "").lower() == "pending":
            # Not a terminal state, so the next run looks at it again.
            self._record_state(purchase, State.DISCOVERED,
                               notes="Pending order, no receipt yet. Revisited on the next run.")
            self.stats["pending"] = self.stats.get("pending", 0) + 1
            print("  Order still pending - no receipt yet, will be revisited next run.")
            return

        # ---- open the receipt page (retry once, per spec 22) ----
        for attempt in (1, 2):
            try:
                site.goto_receipt(page, purchase)
                # Signing in again at a console leaves the page on the order
                # list, and the list was read as this purchase. So the
                # receipt is opened again for as long as the check had to
                # ask.
                while self.check_session(page):
                    site.goto_receipt(page, purchase)
                break
            except Exception as e:
                log.warning("Receipt page failed (attempt %d): %s", attempt, e)
                if attempt == 2:
                    self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                       notes="Receipt page failed to load twice")
                    self.stats["manual_review"] += 1
                    # The failure file reads the page as it stands, and the
                    # error's own words stay in the log, which is never posted.
                    self.write_failure("open the receipt", "it would not open twice")
                    return
                time.sleep(5)
                site.goto_orders(page)

        # ---- extract ----
        purchase = site.extract_details(page, purchase)
        # What the purchase had before this dialog was read, for a refusal
        # to put back, since a dialog the check refuses is not this
        # purchase's and neither is the store read off it.
        self._store_before = (purchase.key, purchase.store_info)
        if purchase.purchase_type == IN_STORE:
            # The heading names the part of Costco, Warehouse or Gas
            # Station and the like, which no row on the list does (#60).
            purchase.store_info = site.receipt_store(page) or purchase.store_info
        self._record_state(purchase, State.DETAILS_EXTRACTED)
        self._note_store(purchase)
        if purchase.purchase_date:
            self.stats["dates_processed"].append(purchase.purchase_date)

        # ---- classify (local, deterministic) ----
        cls = classification.classify_items(purchase.items, self.rules)
        # Unless Costco has already said what this purchase is. A fuel
        # stop has no item to classify, so it was being filed as Mixed
        # Purchases while its own PDF says Gas Station Receipt (#47).
        # Every row on the Warehouse tab is typed as a warehouse visit,
        # gas included, so the row cannot say it and the receipt's own
        # heading is what does.
        # Only the dialog on screen names a warehouse receipt, never a
        # store kept from an earlier read (review of #60). An online order
        # has no dialog, and the list's word for it can name it, Travel or
        # Photo.
        told = (site.receipt_kind(page) if purchase.purchase_type == IN_STORE
                else site.summary_from_kind(purchase.store_info))
        purchase.summary = told or cls.summary
        purchase.confidence = classification.HIGH if told else cls.confidence
        review_needed = (not told) and cls.confidence == classification.LOW
        notes_extra = f"Items: {'; '.join(i.name for i in purchase.items[:12])}" \
            if review_needed and purchase.items else ""
        print(f"  {len(purchase.items)} item(s); summary: {purchase.summary} "
              f"[{purchase.confidence}] "
              f"({'Costco names this kind itself' if told else cls.notes})")

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
        self._write_csv_rows(purchase, receipt_status=receipt_status,
                             processing_status="Review Needed" if review_needed else "Completed",
                             notes_extra=notes_extra)
        final_state = State.NEEDS_MANUAL_REVIEW if review_needed else State.COMPLETED
        self._record_state(purchase, final_state,
                           notes=("Low classification confidence" if review_needed else ""))
        # Once a copy of its own is saved, a Download again of a receipt
        # saved before tells the list its store too, which it could not
        # while the old record was held (review of #60).
        self._note_store(purchase)
        if review_needed:
            self.stats["manual_review"] += 1
            # Saved under a name it was unsure of, which Review Names
            # puts right, not set aside in Manual Review.
            self.stats["name_review"] = self.stats.get("name_review", 0) + 1
        self.journal.checkpoint('a document is saved')
        self.stats["receipts_downloaded"] += 1
        print(f"  Saved: {purchase.pdf_filename}")

    # -- receipt saving -----------------------------------------------------

    def _save_receipt(self, page, purchase: Purchase) -> bool:
        """Save the Costco receipt page as a verified PDF receipt.

        GUESS, like most of this app. Costco is assumed to render a receipt
        on a page of its own, which process_one has already navigated to.
        _capture_document strips the site chrome and CDP printToPDF renders
        it directly. No buttons are clicked, the page's own Print button
        included, and the native print dialog is never involved.
        """
        if site.looks_signed_out(page):
            print("  Costco is asking you to verify your sign-in.")
            print("  Complete it in the browser window (password/OTP).")
            self.check_session(page)
            site.goto_receipt(page, purchase)
            if site.looks_signed_out(page):
                self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                   notes="Could not pass re-authentication")
                self.stats["manual_review"] += 1
                return False

        # Make sure this purchase's receipt is the one on screen. A
        # warehouse receipt is a dialog with no address of its own, so
        # there is no URL to check it against and the only question that
        # can be asked is whether a receipt is up at all.
        if not site.on_receipt_page(page):
            site.goto_receipt(page, purchase)
        site.scroll_full_page(page)

        # A page that did not show the receipt says nothing about whether the
        # purchase has one, so the next run asks for it again (#70).
        if not site.receipt_is_present(page):
            why = "Costco could not load this receipt" if site.receipt_failed(page) \
                else "Receipt page did not render"
            not_shown.tried_again(self, purchase, why)
            self.write_failure("render the receipt",
                               "the receipt did not render")
            return False

        self.journal.checkpoint("the receipt is on screen")
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
        purchase.receipt_url = page.url
        try:
            with restoring(page, journal=self.journal):
                got = self._capture_document(page, purchase, out_path)
            if got.outcome == delivery.WRONG:
                return self._refused(purchase, got)
            if got.outcome != delivery.SAVED:
                # Nothing checked reached the folder, so nothing is
                # finished. _finish_pdf used to run anyway, find no file,
                # and reprint the page straight to the final path outside
                # both the isolation and the check, and the case where
                # the checked render fails is the one where a stale
                # receipt is still on screen.
                self._record_state(purchase, State.FAILED,
                                   notes="the receipt did not render: %s"
                                   % got.outcome)
                self._write_csv_rows(purchase,
                                     receipt_status="Capture failed",
                                     processing_status=State.FAILED.value)
                self.stats["failed"] += 1
                self.write_failure("save the receipt",
                                   "the receipt did not render")
                self.journal.result("could not save the document")
                return False
            ok = self._finish_pdf(page, purchase, out_path, source_page=page,
                                  reprint=False)
            self.journal.result("saved the document" if ok
                                else "could not save the document",
                                bytes_written=out_path.stat().st_size
                                if out_path.exists() else 0)
            return ok
        except Exception as e:
            log.exception("PDF generation failed for %s", purchase.key)
            self._record_state(purchase, State.FAILED,
                               notes=f"PDF generation failed: {e}")
            self.stats["failed"] += 1
            return False

    def _capture_document(self, target_page, purchase: Purchase,
                          out_path: Path, content_kind: str = ""):
        """Render the receipt on screen to PDF.

        A warehouse receipt is a dialog sitting on top of the whole site,
        so printing the page as-is captures the nav, the banners and a
        gray backdrop around a letterbox of receipt.
        site.isolate_receipt hides everything except the purchase-summary
        block first, which leaves a clean one-page receipt for CDP
        Page.printToPDF.

        All of it inside `restoring`, which puts every style back
        afterwards whatever happens, including when the render raises.
        This app does not navigate between warehouse receipts, so the
        hiding is not thrown away by a page load the way it is
        elsewhere, and the second receipt of a run was being looked for
        on a page where nothing could be clicked. From outside that is
        a page that did not load, and it cost two live runs to find.

        The render goes through `delivery.render`, so the receipt is
        printed to a staging file beside the destination, read back, and
        moved into place only if it is the purchase that was asked for.
        A warehouse receipt is checked on its date and total, because
        Costco gives one no number and the key this app invents for it
        appears on no receipt ever printed. See site.identity_for.

        It is checked against the other purchases of its day, or with none
        against the purchases either side on other days, and in the first
        case again once saved against those either side (_rivals). One the
        second check refuses is treated as one the render refused.
        """
        expect = site.identity_for(purchase)
        strict = bool(self.config.get("refuse_wrong_documents", False))
        same_day, near = self._rivals()
        got = delivery.render(
            target_page,
            lambda staged: self._render(target_page, staged),
            out_path,
            expect=expect,
            rivals=same_day or near,
            journal=self.journal,
            strict=strict)
        if got.ok and same_day and near:
            # So its day is checked even when the render told it apart from
            # the others of its day by its total alone. With nothing either
            # side no other purchase's day could be found in it, and its own
            # day not found destroys nothing, as it never did beside another
            # purchase of its day.
            again = identity.distinguish(out_path, expect, near)
            self.journal.op("verify", "check the receipt again", outcome=again.outcome,
                            checked=len(again.checked), matched=len(again.matched))
            if again.outcome == identity.REFUSED and strict:
                try:
                    out_path.unlink()
                except OSError as e:
                    # Kept where it was saved, as it is with refusing off,
                    # rather than said to be destroyed while it is there.
                    log.info("could not remove the refused receipt: %s", type(e).__name__)
                else:
                    return delivery.Delivery(delivery.WRONG, got.mechanism, again,
                                             got.armed, got.bytes_len)
        return got

    def _rivals(self) -> tuple:
        """The purchases this one could be taken for, in two groups, since
        each differs from it by another fact. The others of its day differ
        by their total, and the rows either side on other days
        (identity.rivals_for) differ by their day and usually their total.
        One of those with this one's total, a gas fill paid ahead for the
        same amount, would share it, and asked together, the day the first
        share and the total the second shares would both stop counting, and
        nothing would be left to tell them apart by."""
        rows = list(getattr(self, "_rows", ()) or ())
        i = getattr(self, "_row_index", -1)
        if not 0 <= i < len(rows):
            return (), ()
        day = rows[i].date
        same_day = [r for n, r in enumerate(rows) if n != i and day and r.date == day]
        near = [r for r in identity.rivals_for(rows, i) if not day or r.date != day]
        return same_day, near

    def _refused(self, purchase: Purchase, got) -> bool:
        """A receipt was printed, read back, and is not this purchase.

        Nothing is quarantined because nothing was kept. The file was
        destroyed at the staging path, which is the point of checking
        before writing rather than after.

        This is reported apart from an ordinary failure on purpose. A
        run that saved nothing is a run that did not work. A run that
        produced a document belonging to a different purchase is a run
        whose other documents are now also in doubt."""
        why = "the receipt that printed is not this purchase"
        key, before = getattr(self, "_store_before", (None, ""))
        if key == purchase.key:
            purchase.store_info = before
        self._record_state(purchase, State.NEEDS_MANUAL_REVIEW, notes=why)
        self._note_store(purchase)
        self._write_csv_rows(purchase, receipt_status="Wrong document",
                             processing_status=State.NEEDS_MANUAL_REVIEW.value,
                             notes_extra=why)
        self.stats["manual_review"] += 1
        self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
        print("  !! %s" % got.say())
        print("     Nothing was saved for it. The file was destroyed rather")
        print("     than filed under this purchase's name.")
        self.write_failure("save the receipt", why)
        # Named as the delivery's outcome. Passed as outcome= it collided
        # with the journal's own first argument, raised, and the refusal
        # was counted as an ordinary failure in _save_receipt's except.
        self.journal.result("refused the document",
                            delivery_outcome=got.outcome,
                            mechanism=got.mechanism)
        return False

    def _render(self, target_page, out_path: Path) -> None:
        """The capture itself. Always called with the page remembered."""
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

    def _finish_pdf(self, page, purchase: Purchase, out_path: Path,
                    popup=None, source_page=None, reprint: bool = True) -> bool:
        """Validate what was saved, and file it or quarantine it.

        reprint is off for a receipt that came through delivery.render. A
        reprint there goes straight to the final path, unisolated and
        unchecked, over a receipt that had been checked, so a file that
        fails validation is quarantined as it is instead."""
        purchase.pdf_path = str(out_path)
        purchase.pdf_filename = out_path.name
        self._record_state(purchase, State.PDF_SAVED)

        # A gas receipt prints no number and has no item, so the date and
        # total the list showed count together as well, or the purchase's
        # own when the list kept no record of it.
        tokens = receipt_pdf.expected_tokens_for(
            purchase, listed=self.discovery.get(purchase.key) or purchase)
        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
        if not result.ok and reprint:
            log.warning("Validation failed (%s); retrying once", result.reason)
            self.stats["validation_failures"] += 1
            try:
                retry_page = source_page or page
                receipt_pdf.print_page_to_pdf(retry_page, out_path)
                result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
            except Exception as e:
                log.warning("Retry failed: %s", e)
        if not result.ok:
            # Quarantine the questionable file; never mark Completed.
            quarantine = unique_path(self.paths.manual_review, out_path.name,
                                     self.config["max_path_length"])
            try:
                out_path.replace(quarantine)
            except OSError:
                quarantine = out_path
            purchase.pdf_path = str(quarantine)
            purchase.pdf_filename = quarantine.name
            self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                               notes=f"PDF validation failed: {result.reason}")
            self._write_csv_rows(purchase, receipt_status="Validation Failed",
                                 processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                 notes_extra=f"Validation: {result.reason}")
            self.stats["manual_review"] += 1
            print(f"  !! Validation failed ({result.reason}); moved to Manual Review.")
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
        # Every write says whether its store was read, so a later write,
        # PDF_VERIFIED or COMPLETED after a held DETAILS_EXTRACTED, never
        # leaves a store read off a receipt unmarked (review of #60).
        rec["store_read"] = self._store_is_read(purchase)
        if extra:
            rec.update(extra)
        not_shown.let_go_on_save(self, purchase, state, rec)
        # A receipt saved before keeps its record while a Download again
        # saves no copy of its own (paperpull_core.saved_copy).
        if saved_copy.holds(self, purchase.key, rec):
            return
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
        self.cmd_discover(types=[ONLINE, IN_STORE], quiet=False, finish=False)
        selected: List[Purchase] = self._select_purchases(
            ONLINE, limit=self.config["pilot_online"])
        selected += self._select_purchases(
            IN_STORE, limit=self.config["pilot_instore"])
        if not selected:
            print("\nNo purchases discovered to pilot. Run --diagnose to inspect pages.")
            self._stop_if_cut_short()
            return
        print(f"\nProcessing {len(selected)} pilot purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)
        self._pilot_report(selected)
        self._stop_if_cut_short()

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
                print(f"    PDF exists: {exists}  "
                      f"({rec.get('pdf_size','?')} bytes, {rec.get('pdf_pages','?')} pages)")
                if not exists:
                    problems.append(f"{p.key}: PDF missing")
            # A Download again that saved nothing kept the saved copy's
            # record as it was, so it is said here (paperpull_core.saved_copy).
            if saved_copy.tried(self, p.key):
                problems.append(f"{p.key}: {saved_copy.tried(self, p.key)}")
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
        print("e.g.:  python costco_receipts.py --all")

    def cmd_run(self, types: List[str], mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Costco purchase history")
            print(f"({', '.join(types)}). Type YES to continue:")
            if ask("> ").strip().upper() != "YES":
                print("Aborted. (Run the pilot first if you haven't: --pilot)")
                return
        self.cmd_discover(types=types, quiet=False, finish=False)
        selected: List[Purchase] = []
        for t in types:
            selected += self._select_purchases(t)
        print(f"\nProcessing {len(selected)} purchase(s)...")
        self.process_purchases(selected, dry_run=self.args.dry_run)
        self._stop_if_cut_short()

    def cmd_resume(self):
        self.stats["mode"] = "resume"
        # Resume works from the purchases a Discover found. After one that
        # stopped before the list was read whole, that is some of them or none,
        # and Resume finished clean with the rest never looked for. So the list
        # is read before anything else, and a listing that stops again stops
        # the run (paperpull_core.listing). A list read again only in part
        # still goes on with what it found, and the run stops at its end.
        if listing.read_again_first(self):
            self.cmd_discover(quiet=True, finish=False)
        # Only the purchases inside the run's scope, chosen as Pilot and Run
        # All choose them, so a Resume with a year chosen takes that year
        # alone. The limit waits until the done ones are left out.
        pend = self._select_purchases(None, limit=0)
        pend = [p for p in pend if not self._already_done(p)]
        pend.sort(key=lambda p: p.purchase_date or "0000", reverse=True)
        if self.args.max_purchases:
            pend = pend[:self.args.max_purchases]
        if not pend:
            # A scoped Resume knows only that its own part is done.
            print("Nothing to resume - everything in scope is complete."
                  if listing.scoped(self) else
                  "Nothing to resume - all discovered purchases are complete.")
            self._stop_if_cut_short()
            return
        print(f"Resuming: {len(pend)} incomplete purchase(s).")
        self.process_purchases(pend, dry_run=self.args.dry_run)
        self._stop_if_cut_short()


    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.

        A naming scheme improves and the files on disk keep the old one.
        Nothing about them needs fetching, only their names are wrong, so
        nothing is asked of the provider here (#43, #49). A preview
        unless --apply is given."""
        self.stats["mode"] = "rename"
        apply = bool(getattr(self.args, "apply", False))
        # A preview changes nothing. The stores settled here name the files
        # in the preview and are put back after it however it ends, cut short
        # or failing included, since the run saves both stores on its way
        # out (#60, as Kroger does for its banner).
        changed: list = []
        try:
            read = self._settle_stores(changed)
            if read:
                print(f"Read the part of Costco from {read} receipt(s) already saved, "
                      "off the PDF itself.")
            renaming.run_for(self, apply_changes=apply)
        finally:
            if not apply:
                self._put_back(changed)

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

    def cmd_review_names(self):
        # The store read off the receipt, never the list's In-Warehouse.
        renaming.review_names(self, ask, record_for=lambda key, prog: dict(
            prog, store_info=self._store_kept(key)))

    # -- the part of Costco a receipt came from (#60) --------------------------

    def _store_kept(self, key: str) -> str:
        """The store a purchase has, or empty. For an online order, the
        list's own word for it, Online or Delivery and the like. For a
        warehouse receipt, only a store read off the receipt's heading,
        marked store_read. The list's In-Warehouse is on every warehouse
        receipt, gas included, and was written there before 0.50.0, so it
        names nothing. A store that is not text, which a hand edit or a
        damaged file can leave, names nothing either."""
        for store in (self.progress, self.discovery):
            rec = store.get(key) or {}
            info = rec.get("store_info")
            if not isinstance(info, str) or not info.strip():
                continue
            if rec.get("purchase_type") == ONLINE or rec.get("store_read"):
                return info.strip()
        return ""

    def _store_is_read(self, purchase: Purchase) -> bool:
        """Whether a purchase's store is one to keep. An online order's
        list word, or a store only a warehouse receipt's heading can give,
        never the list's In-Warehouse."""
        info = purchase.store_info
        if not isinstance(info, str) or not info.strip():
            return False
        return purchase.purchase_type == ONLINE or info.strip() in site.WAREHOUSE_STORES

    def _listed_store(self, purchase: Purchase) -> str:
        """The store a row read off the list gives its purchase. The list
        names an online order's kind, and never the part of a warehouse a
        receipt came from, so a warehouse receipt keeps the one read off
        it, or none."""
        if purchase.purchase_type == ONLINE:
            info = purchase.store_info
            return info.strip() if isinstance(info, str) else ""
        return self._store_kept(purchase.key)

    def _forget_unread_store(self, purchase: Purchase) -> None:
        """Before a receipt is read, drop a store that was never read off
        one. Resume works from the purchase list without reading it again,
        and a list from before 0.50.0 carries In-Warehouse there."""
        purchase.store_info = self._listed_store(purchase)

    def _note_store(self, purchase: Purchase) -> None:
        """The purchase list says the same as the record, since Rename reads
        the list over the record. A receipt saved before keeps the store its
        record has while a Download again saves no copy of its own
        (paperpull_core.saved_copy)."""
        if saved_copy.holding(self, purchase.key):
            return
        if self.discovery.get(purchase.key) is not None:
            self.discovery.update(purchase.key, {
                "store_info": purchase.store_info,
                "store_read": bool(purchase.store_info)}, save=False)

    def _settle_stores(self, changed: list) -> int:
        """Give every purchase the store its receipt names, or none, in the
        record and the purchase list alike, before Rename builds names from
        them (#60).

        A store already read is kept, and the list is made to agree, since
        Rename reads the list over the record. A warehouse receipt saved
        before 0.50.0 has its store read off its own PDF, whose heading is
        the dialog's, with nothing asked of Costco. In memory only, each
        change noted in `changed`, so a preview can put it back. Returns how
        many stores were read off a PDF."""
        n = 0
        folders = self.paths.filing_folders()
        for key in set(self.progress.data) | set(self.discovery.data):
            recs = [r for r in (self.progress.data.get(key), self.discovery.data.get(key))
                    if isinstance(r, dict)]
            store = self._store_kept(key)
            prog = self.progress.data.get(key)
            if not store and isinstance(prog, dict) and prog.get("purchase_type") == IN_STORE:
                where = prog.get("pdf_path")
                # Only a receipt the app holds is read, as Rename renames
                # only those (renaming.held_document).
                if renaming.held_document(where, folders) is not None:
                    store = site.store_from_receipt(receipt_pdf.pdf_text(Path(where)))
                    n += bool(store)
            for rec in recs:
                if (rec.get("store_info") or "") != store:
                    changed.append((rec, "store_info", rec.get("store_info", _MISSING)))
                    rec["store_info"] = store
                if bool(rec.get("store_read")) != bool(store):
                    changed.append((rec, "store_read", rec.get("store_read", _MISSING)))
                    rec["store_read"] = bool(store)
        return n

    def _put_back(self, changed: list) -> None:
        """Undo _settle_stores exactly, for a preview, a key that was not
        there taken away again."""
        for rec, key, old in reversed(changed):
            if old is _MISSING:
                rec.pop(key, None)
            else:
                rec[key] = old

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
            provider='Costco', text=text, extra=extra)
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
        # The receipt Diagnose opened, as its layout in words from a fixed
        # list, so a receipt this app cannot read yet can be repaired
        # from a file that is safe to post (#47).
        shape = getattr(self, "_receipt_shape", None)
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Costco',
            extra={"receipt": shape} if shape else None)

    def cmd_diagnose(self):
        """The purchase history and one receipt page, as this browser sees
        them, written to Diagnostics/diagnose-costco.json with every number
        of two digits or more and every email masked. This is the file a
        tester attaches to the issue. No screenshot is taken."""
        self.stats["mode"] = "diagnose"
        words = words_for('Costco', site)
        page = self.page()
        site.set_private_words([self.config.get("owner", "")])
        info = {"timestamp": now_iso(), "app": "costco", "history": {}, "receipt": {}}
        try:
            site.goto_orders(page)
            info["signed_out"] = site.looks_signed_out(page)
            info["challenge"] = site.detect_security_challenge(page)
            info["history"] = site.survey_history_page(page)
            recs = site.fetch_history(page, max_pages=1).get("records") or []
            purchases = [pp for pp in (site.record_to_purchase(r) for r in recs) if pp]
            if self.args.order_number:
                purchases = [pp for pp in purchases if pp.order_number == self.args.order_number]
            finished = [pp for pp in purchases if "Pending" not in (pp.notes or "")]
            if finished:
                pp = finished[0]
                print("\nOpening the newest receipt page ...")
                site.goto_receipt(page, pp)
                sv = site.survey_receipt_page(page)
                items = site.extract_items(page)
                self._receipt_shape = site.receipt_shape(site.receipt_text(page), items)
                info["receipt"] = {"url": sv.url, "title": sv.title, "rendered": sv.rendered,
                                   "failed": sv.failed, "lines": sv.lines, "outline": sv.outline,
                                   "controls": sv.controls,
                                   "items_read": [site.mask_text(i.name)[:60] for i in items][:20],
                                   "shape": self._receipt_shape}
            else:
                info["receipt"] = {"note": Fixed("no finished purchase to open")}
        except Exception as e:
            info["error"] = site.mask_text(str(e))
        out = self.paths.diagnostics / "diagnose-costco.json"
        write_shaped(out, info, words)
        print(f"  Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        h = info.get("history") or {}
        print(f"  History: state={shape_tree(h.get('state') or 'has purchases', words)} "
              f"api={shape_tree(h.get('api'), words)}")
        r = info.get("receipt") or {}
        print(f"  Receipt page: rendered={shape_tree(r.get('rendered'), words)} "
              f"failed={shape_tree(r.get('failed'), words)} lines={len(r.get('lines') or [])}")
        # It used to end by saying to attach this file, which carries the
        # page's own words, straight after saying it stays here. The
        # survey written next is the one to send.
        print("  Do not attach this one. The survey written next is the file to send.")


    # -- run summary --------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a receipt, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        if record_session(self.page(), site, self.paths.diagnostics,
                          provider='Costco',
                          owner=self.config.get("owner", "")) is None:
            raise SystemExit(NOTHING_RECORDED)

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Costco Receipts - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Online orders known:       {s['online_discovered']}",
            f"In-warehouse purchases known:  {s['instore_discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Receipts downloaded:       {s['receipts_downloaded']}",
            f"Skipped (already done):    {s['skipped_completed']}",
            f"Canceled purchases:        {s['canceled']}",
            f"No printable receipt:      {s['no_receipt']}",
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Local supervised Costco receipt downloader")
    modes = [
        ("login", "open browser for manual Costco sign-in"),
        ("discover", "discovery pass only; writes discovery.json"),
        ("pilot", "pilot: newest few online orders and warehouse purchases"),
        ("online", "process all pickup, delivery and ship orders"),
        ("instore", "process all warehouse, gas and pharmacy purchases"),
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
            app.stats["mode"] = "discover"
            app.cmd_discover()
        elif args.pilot:
            app.cmd_pilot()
        elif args.all:
            app.cmd_run([ONLINE, IN_STORE], "all")
        elif args.online:
            app.cmd_run([ONLINE], "online")
        elif args.instore:
            app.cmd_run([IN_STORE], "instore")
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
        app.progress.save(leaving=True)
        app.discovery.save(leaving=True)
        # A run that only looked at the page writes no summary. The
        # summary rewrites new-this-run.txt, and for a mode that
        # downloads nothing that means replacing the real list from
        # the last download run with an empty one.
        if app.stats["mode"] in ("discover", "rename"):
            # Discover and Rename download nothing, so the run summary
            # and new-this-run.txt stay as the last download run wrote
            # them, and only the panel is told how it ended. The panel
            # moves what a run saved into a documents folder with a
            # Rename, and its empty list made that run read as one that
            # saved nothing (#103).
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

