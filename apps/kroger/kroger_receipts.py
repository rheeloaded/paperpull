"""Kroger purchase-history & receipt downloader (local, supervised).

Usage:
    python kroger_receipts.py --login
    python kroger_receipts.py --discover
    python kroger_receipts.py --pilot            (newest few of each kind)
    python kroger_receipts.py --all
    python kroger_receipts.py --online           (pickup, delivery and ship orders only)
    python kroger_receipts.py --instore          (in-store and fuel purchases only)
    python kroger_receipts.py --resume
    python kroger_receipts.py --verify
    python kroger_receipts.py --review-names
    python kroger_receipts.py --diagnose [--order-number N]
    python kroger_receipts.py --dry-run

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
import kroger_site as site
from paperpull_core.models import (IN_STORE, ONLINE, Item, Purchase, State)
from paperpull_core.words import Fixed, words_for, write_shaped
from storage import (CsvFile, JsonStore, ORDER_HISTORY_COLUMNS, Paths,
                     RECEIPT_INDEX_COLUMNS, atomic_write_text, build_pdf_filename, load_config, now_iso, title_case,
                     unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
# A key a record did not have, so a preview can put a record back exactly.
_MISSING = object()

log = logging.getLogger("kroger_receipts")


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
        # Set when the history API stopped before its last page, so the run
        # stops at its end rather than finish (see _stop_if_cut_short).
        self._history_cut_short = False
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
        never scripted. Plain Chromium is enough for Kroger - it does not block
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
            # window Kroger opens to print also has window.print() intercepted
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
            print("\n!! Kroger appears to have signed you out.")
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
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9263")
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
        """Open the purchase history and say what is there, as (listed,
        challenge).

        Only the history shows a signed-in session, a purchase on it or its
        own words that there is nothing to show. When it does not come the
        page is looked at again for a little while, because a bot check can
        leave the page blank and a moment later turn it into the check, and
        one look at the blank page finds nothing to name. That one look is
        how --login said Success on a page with no history on it."""
        if site.goto_orders(page):
            return True, site.detect_security_challenge(page)
        challenge = site.challenge_after_a_moment(page)
        return site.orders_listed(page), challenge

    def _open_orders(self, page) -> None:
        """Open the purchase history and go on only once it is there.

        Discovery used to go on from a history that never came and ask the
        purchase history API from that page, and when nothing came back it
        finished as though there were no purchases, so a run read as clean
        with its new receipts missed."""
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
            print("\n!! Your Kroger purchase history did not load, so this cannot find")
            print("any of your purchases. Look at the browser window. If Kroger is")
            print("asking you to prove you are a person, to sign in, or for a code,")
            print("answer it there yourself. I will NOT attempt to bypass it.")
            self.write_failure("open the purchase history",
                               "the purchase history did not appear")
            if browser_launcher.ask_or_none(
                    "Press Enter once the page shows your purchases (or Ctrl+C to quit)... ") is None:
                print("Once it shows your purchases, run this again.")
                raise SystemExit(0)
        self.check_session(page)

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode: the browser is launched by login.bat (not here). This
            # just verifies we can connect and that you are signed in.
            print("Checking the connection to your signed-in Kroger browser...\n")
            page = self.page()
            listed, challenge = self._look_at_orders(page)
            if challenge:
                print(f"!! {challenge}")
                print("Resolve it yourself in the browser window, then re-run --login.")
            elif site.looks_signed_out(page):
                print("Connected, but Kroger shows the signed-out page.")
                print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
            elif listed:
                print("Success: connected to your signed-in Kroger session.")
                print("Keep that browser window OPEN, then run the diagnostics or pilot.")
            else:
                print("Connected, but your Kroger purchase history did not load, so this")
                print("cannot say whether you are signed in. Look at the browser window.")
                print("If Kroger asks you to prove you are a person, to sign in, or for a")
                print("code, answer it there yourself, keep the window OPEN, then")
                print("re-run --login.")
            self.close()
            return
        print("Opening Kroger.com in a dedicated supervised browser profile.")
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
            print("Sign in in the browser, then run:  python kroger_receipts.py --login")
        elif listed:
            print("Signed-in session detected.")
        else:
            print("Your Kroger purchase history did not load, so this cannot say")
            print("whether you are signed in. Look at the browser window, answer")
            print("anything Kroger asks there yourself, then run --login again.")
        self.close()

    def _unfinished_mark(self) -> Path:
        """Present while a Discover is under way and after one that did not
        read the whole purchase history, so Resume knows to read it first,
        as Target's does. Only the history's last page takes it away."""
        return self.paths.discovery_json.with_name(".discovery-unfinished")

    @staticmethod
    def _history_facts(hist: dict) -> dict:
        """How far the history API got, for a failure file, since nobody has
        seen how a long history ends. Counts, and the word for why it
        stopped."""
        return {"pages": hist.get("pages", 0), "last": bool(hist.get("last")),
                "stop": hist.get("stop") or "", "status": hist.get("status", 0)}

    def _read_history(self, page, need_it: bool = True):
        """The purchase history from its API, asked from inside the open
        history the way the page asks, and the page's own word on it, as
        (hist, state).

        The page drawing is not the API answering. Kroger sits behind Akamai
        Bot Manager, and a call made from a page that drew can still be
        refused. Discovery read a first page that never came as a history
        with nothing new in it and finished clean, so Pilot and Run All went
        on as though there were nothing to download. Now the run stops here
        the way it stops on a history that never drew, claiming nothing, and
        at a console it asks and then reads the history again. Resume, which
        does not need it (need_it=False), says so and goes on with the
        purchases already found, as it did before it read the history.

        An account with no loyalty card is the one exception. Kroger says
        why it has no history, and what the API answers for such an account
        has never been seen, so those words stand whatever it answers."""
        while True:
            self._open_orders(page)
            state = site.history_state(page)
            if state == "no-loyalty":
                print("\nKroger says this account has no loyalty card on it, so it has no")
                print("purchase history to show. Add your card under Account, then run again.")
            hist = site.fetch_history(page)
            if hist.get("pages") or state == "no-loyalty":
                return hist, state
            self.progress.save(backup=True)
            print("\n!! Your purchase history did not come when this asked Kroger for it")
            print(f"({site.why_it_stopped(hist)}), so this cannot say which purchases are new.")
            print("Look at the browser window. If Kroger is asking you to prove you are a")
            print("person, to sign in, or for a code, answer it there yourself. I will NOT")
            print("attempt to bypass it.")
            self.write_failure("read the purchase history",
                               "the purchase history api gave no page",
                               postmortem=self._history_facts(hist))
            if not need_it:
                print("This goes on with the purchases already found, and stops at its end.")
                return hist, state
            if browser_launcher.ask_or_none(
                    "Press Enter to ask Kroger for your purchases again (or Ctrl+C to quit)... ") is None:
                print("Run this again in a while.")
                raise SystemExit(0)

    def _stop_if_cut_short(self) -> None:
        """A run that did not read the whole purchase history did not finish,
        and must not read as a clean one. Once it has used what came, it
        leaves on SystemExit the way a run leaves on a sign-out, which the
        panel reports as stopped after Pilot, Run All and Resume."""
        if self._history_cut_short:
            print("\nNot all of your purchase history came, so this run stops here rather")
            print("than finish. Run it again later to read the rest.")
            raise SystemExit(0)

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False,
                     finish: bool = True, need_history: bool = True) -> dict:
        """Discovery pass: the purchase-history API, called from inside the
        signed-in page the way the page itself calls it, every page of it
        until the API says it is the last. Nothing clicked.

        Only that last page, or an empty one, shows the history was read
        whole. When the API stops short of it after giving some pages, the
        purchases on them are real and are kept, and Pilot, Run All and
        Resume go on with them, but older ones are missing, so the run stops
        at its end rather than finish. With finish=False the caller does
        that once it has used them. need_history=False is Resume's, which
        goes on with the purchases already found even when no page comes."""
        try:
            self._unfinished_mark().write_text(now_iso(), encoding="utf-8")
        except OSError:
            pass
        page = self.page()
        n_new = 0
        floor = self.args.start_date or self.config.get("default_start_date")

        hist, state = self._read_history(page, need_it=need_history)
        records = hist.get("records") or []
        log.info("Purchase history API: %d record(s) over %d page(s), last page %s",
                 len(records), hist.get("pages", 0), hist.get("last"))
        if not records and state != "empty":
            log.warning("No purchases came back from the history API. If you are signed in "
                        "and do have purchases, run --diagnose and share the file.")
        purchases = [pp for pp in (site.record_to_purchase(r) for r in records) if pp]
        for purchase in purchases:
            if types and purchase.purchase_type not in types:
                continue
            if floor and purchase.purchase_date and purchase.purchase_date < floor:
                continue  # before the cutoff: never record or download
            key = purchase.key
            if self.discovery.get(key) is None:
                rec = purchase.to_dict()
                rec["state"] = State.DISCOVERED.value
                self.discovery.update(key, rec, save=False)
                n_new += 1
            else:
                kept = self._store_kept(key)
                self.discovery.update(key, {
                    "details_url": purchase.details_url,
                    "receipt_url": purchase.receipt_url,
                    "total": purchase.total or self.discovery.get(key).get("total", ""),
                    "status": purchase.status or self.discovery.get(key).get("status", ""),
                    # The store is read off the receipt page, never the
                    # list, so the list's empty one keeps a store already
                    # read, and anything else, the purchase type written
                    # here before 0.41.0, is cleared (#41).
                    "store_info": kept,
                    "store_read": bool(kept),
                    "fulfillment": purchase.fulfillment,
                    "notes": purchase.notes,
                }, save=False)
        self.discovery.save()

        if hist.get("last"):
            try:
                self._unfinished_mark().unlink()
            except OSError:
                pass
        elif hist.get("pages"):
            self._history_cut_short = True
            print(f"\n!! Only {hist.get('pages', 0)} page(s) of your purchase history came "
                  f"({site.why_it_stopped(hist)}),")
            print("so older purchases may be missing. What came is kept, and this run stops at")
            print("its end rather than finish. Run it again later to read the rest.")
            self.write_failure("read the purchase history",
                               "the purchase history api stopped partway",
                               postmortem=self._history_facts(hist))
        elif state != "no-loyalty":
            # Resume, going on with the purchases found before (_read_history).
            self._history_cut_short = True

        all_recs = list(self.discovery.data.values())
        self.stats["online_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == ONLINE)
        self.stats["instore_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == IN_STORE)

        if not quiet:
            if self._history_cut_short:
                print(f"\nDiscovery read part of your purchase history. Purchases known: {len(all_recs)}")
            else:
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
        if finish:
            self._stop_if_cut_short()
        return {"new": n_new}

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
        # (You already has 2024-and-earlier Kroger receipts).
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
        for i, purchase in enumerate(purchases, 1):
            print(f"\n[{i}/{len(purchases)}] {purchase.purchase_type} "
                  f"{purchase.purchase_date or '(date unknown)'} "
                  f"#{purchase.order_number}")
            if self._already_done(purchase):
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
        # Before anything is recorded, even a page that fails to load, since
        # every record writes the purchase's store (second review of 0.41.0).
        self._forget_unread_store(purchase)

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
                    self.write_failure("open the document",
                                       "it would not open twice")
                    return
                time.sleep(5)
                site.goto_orders(page)

        # ---- extract ----
        purchase = site.extract_details(page, purchase)
        self._record_state(purchase, State.DETAILS_EXTRACTED,
                           extra={"store_read": bool(purchase.store_info)})
        self._note_store(purchase)
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
        """Save the Kroger order-details page as a verified PDF receipt.

        Kroger renders the receipt on its own page, /mypurchases/image/<key>.
        process_one already navigated there, so it is on screen.
        _capture_document strips the site chrome and CDP printToPDF renders
        it directly. No buttons are clicked, the page's own Print button
        included, and the native print dialog is never involved.
        """
        if site.looks_signed_out(page):
            print("  Kroger is asking you to verify your sign-in.")
            print("  Complete it in the browser window (password/OTP).")
            self.check_session(page)
            site.goto_receipt(page, purchase)
            if site.looks_signed_out(page):
                self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                   notes="Could not pass re-authentication")
                self.stats["manual_review"] += 1
                return False

        # Make sure we are on this purchase's receipt page.
        if not site.on_receipt_page(page) or purchase.order_number not in (page.url or ""):
            site.goto_receipt(page, purchase)
        site.scroll_full_page(page)

        if not site.receipt_is_present(page):
            why = "Kroger could not load this receipt" if site.receipt_failed(page) \
                else "Receipt page did not render"
            self._record_state(purchase, State.NO_RECEIPT_AVAILABLE, notes=why)
            self._write_csv_rows(purchase,
                                 receipt_status="No printable receipt available",
                                 processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                 notes_extra=why)
            self.stats["no_receipt"] += 1
            self.stats["manual_review"] += 1
            print(f"  {why} - marked for manual review.")
            return False

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
            self._capture_document(page, purchase, out_path)
            ok = self._finish_pdf(page, purchase, out_path, source_page=page)
            return ok
        except Exception as e:
            log.exception("PDF generation failed for %s", purchase.key)
            self._record_state(purchase, State.FAILED,
                               notes=f"PDF generation failed: {e}")
            self.stats["failed"] += 1
            return False

    def _capture_document(self, target_page, purchase: Purchase,
                          out_path: Path, content_kind: str = "") -> None:
        """Render the Kroger order-details receipt to PDF.

        Kroger ships NO print stylesheet, so printing the page as-is captures the
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

    def _finish_pdf(self, page, purchase: Purchase, out_path: Path,
                    popup=None, source_page=None) -> bool:
        purchase.pdf_path = str(out_path)
        purchase.pdf_filename = out_path.name
        self._record_state(purchase, State.PDF_SAVED)

        # The receipt's key is not what it prints as its order number, and
        # a receipt without Item Details names no item, so the date and
        # total the purchase list gave count together as well, or the
        # purchase's own when the list kept no record of it.
        tokens = receipt_pdf.expected_tokens_for(
            purchase, listed=self.discovery.get(purchase.key) or purchase)
        result = receipt_pdf.validate_pdf(out_path, self.config["min_pdf_bytes"], tokens)
        if not result.ok:
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
        print("e.g.:  python kroger_receipts.py --all")

    def cmd_run(self, types: List[str], mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Kroger purchase history")
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
        # stopped before the history came, or when only part of it came,
        # that is none or some of them, and Resume finished clean on those
        # with the rest never looked for. So the history is read first, and
        # when it does not come this time either, Resume still goes on with
        # the purchases it has and stops at its end.
        if self._unfinished_mark().exists():
            print("The last Discover did not read your whole purchase history, so it runs again first.")
            self.cmd_discover(quiet=True, finish=False, need_history=False)
        pend = [Purchase.from_dict(r) for r in self.discovery.data.values()
                if isinstance(r, dict) and r.get("order_number")]
        pend = [p for p in pend if not self._already_done(p)]
        pend.sort(key=lambda p: p.purchase_date or "0000", reverse=True)
        if self.args.max_purchases:
            pend = pend[:self.args.max_purchases]
        if not pend:
            print("Nothing to resume - all discovered purchases are complete.")
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
        # out. The order history is only cleaned with --apply (#41).
        changed: list = []
        try:
            read = self._settle_stores(changed)
            if read:
                print(f"Read the store from {read} receipt(s) already saved, off the PDF itself.")
            self._clean_order_history(apply)
            renaming.run_for(self, apply_changes=apply)
        finally:
            if not apply:
                self._put_back(changed)

    # The two Order Summary lines runs before 0.41.0 wrote into the order
    # history as items, one of each per receipt (#41). Only these exact
    # names, which no product carries.
    _SUMMARY_ROWS = {"original item total", "order total"}

    def _is_summary_row(self, row: dict) -> bool:
        return (row.get("Item Name") or "").strip().lower() in self._SUMMARY_ROWS

    def _clean_order_history(self, apply: bool) -> None:
        """Take the Order Summary lines that earlier runs read as items out
        of the order history, which the Purchases workbook is rebuilt from,
        with --apply, the file backed up first. A purchase with no other row,
        one whose real items 0.40 refused, a gift card alone for instance,
        keeps one row with its item left blank, the shape a purchase with no
        items read is written in, so it never drops out of the workbook
        (review of 0.41.0)."""
        try:
            rows = self.order_csv.read_all()
        except (OSError, UnicodeDecodeError, ValueError) as e:
            print(f"The order history could not be read to clean it ({type(e).__name__}).")
            return
        others = {r.get("Order or Receipt Number") for r in rows if not self._is_summary_row(r)}
        blanked: set = set()
        out, taken = [], 0
        for r in rows:
            if not self._is_summary_row(r):
                out.append(r)
                continue
            taken += 1
            number = r.get("Order or Receipt Number")
            if number not in others and number not in blanked:
                blanked.add(number)
                out.append(dict(r, **{"Item Name": "", "Quantity": "", "Unit Price": "",
                                      "Line Item Total": ""}))
        if not taken:
            return
        if apply:
            self.order_csv.rewrite(out)
            print(f"Took {taken} Order Summary line(s) out of the order history, where "
                  "earlier runs wrote them as items.")
        else:
            print(f"{taken} Order Summary line(s) that earlier runs wrote as items would "
                  "be taken out of the order history.")

    def _store_kept(self, key: str) -> str:
        """The store read off this purchase's receipt, or empty. Only a store
        marked store_read, which 0.41.0 on writes when it reads one, is kept.
        Anything else in store_info was written before 0.41.0, the purchase
        type, "In-Store", "Fuel Center" or a type title-cased, or Kroger when
        there was no type, and is never kept (#41, review of 0.41.0)."""
        for store in (self.progress, self.discovery):
            rec = store.get(key) or {}
            if rec.get("store_read") and (rec.get("store_info") or "").strip():
                return str(rec["store_info"]).strip()
        return ""

    def _forget_unread_store(self, purchase: Purchase) -> None:
        """Before a receipt is read, drop a store that was never read off one.
        Resume works from the purchase list without refreshing it, and a list
        from before 0.41.0 carries the purchase type there (review)."""
        purchase.store_info = self._store_kept(purchase.key)

    def _note_store(self, purchase: Purchase) -> None:
        """The purchase list says the same as the record, since Rename reads
        the list over the record (review)."""
        if self.discovery.get(purchase.key) is not None:
            self.discovery.update(purchase.key, {
                "store_info": purchase.store_info,
                "store_read": bool(purchase.store_info)}, save=False)

    def _settle_stores(self, changed: list) -> int:
        """Give every purchase the store its receipt names, or none, in the
        record and the purchase list alike, before Rename builds names from
        them (#41, review of 0.41.0).

        A store read off a receipt is kept, and the list is made to agree,
        since Rename reads the list over the record. Anything else was
        written before 0.41.0 and is dropped, unless the saved PDF names the
        store, which is then read off it with nothing asked of Kroger. In
        memory only, each change noted in `changed`, so a preview can put it
        back. Returns how many stores were read off a PDF."""
        n = 0
        for key in set(self.progress.data) | set(self.discovery.data):
            recs = [r for r in (self.progress.data.get(key), self.discovery.data.get(key))
                    if isinstance(r, dict)]
            store = self._store_kept(key)
            if not store:
                prog = self.progress.data.get(key)
                where = (prog or {}).get("pdf_path") if isinstance(prog, dict) else ""
                if where and Path(where).exists():
                    store = site.banner_from_lines(receipt_pdf.pdf_text(Path(where)).splitlines())
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
            old_path = Path(r.get("PDF Full Path") or "")
            date = r.get("Purchase Date") or (old_path.name[:10] if old_path.name else "")
            doc_type = r.get("Document Type") or "Receipt"
            # The store read off the receipt, never a label 0.40 wrote where
            # the store goes (second review of 0.41.0).
            new_name = build_pdf_filename(date, new_summary, doc_type,
                                          record=dict(prog, store_info=self._store_kept(key)))
            if old_path.exists():
                new_path = unique_path(old_path.parent, new_name,
                                       self.config["max_path_length"])
                old_path.rename(new_path)  # unique_path guarantees no overwrite
            else:
                new_path = old_path.parent / new_name if old_path.name else Path(new_name)
                print("    (warning: original PDF not found on disk; records updated only)")
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
            provider='Kroger', text=text, extra=extra)
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
            provider='Kroger')

    def cmd_diagnose(self):
        """The purchase history and one receipt page, as this browser sees
        them, written to Diagnostics/diagnose-kroger.json with every number
        of two digits or more and every email masked. This is the file a
        tester attaches to the issue. No screenshot is taken."""
        self.stats["mode"] = "diagnose"
        page = self.page()
        site.set_private_words([self.config.get("owner", "")])
        info = {"timestamp": now_iso(), "app": "kroger", "history": {}, "receipt": {}}
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
                info["receipt"] = {"url": sv.url, "title": sv.title, "rendered": sv.rendered,
                                   "failed": sv.failed, "lines": sv.lines, "outline": sv.outline,
                                   "controls": sv.controls,
                                   "items_read": [site.mask_text(i.name)[:60] for i in site.extract_items(page)][:20]}
            else:
                info["receipt"] = {"note": Fixed("no finished purchase to open")}
        except Exception as e:
            info["error"] = site.mask_text(str(e))
        out = self.paths.diagnostics / "diagnose-kroger.json"
        write_shaped(out, info, words_for('Kroger', site))
        print(f"  Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        h = info.get("history") or {}
        print(f"  History: state={h.get('state') or 'has purchases'} api={h.get('api')}")
        r = info.get("receipt") or {}
        print(f"  Receipt page: rendered={r.get('rendered')} failed={r.get('failed')} lines={len(r.get('lines') or [])}")
        print("  Nothing in the file identifies you. Attach it to the GitHub issue.")


    # -- run summary --------------------------------------------------------

    def cmd_record(self):
        """Record the path a person takes to a receipt, so this app can be
        written or repaired to take the same one. Downloads nothing, and
        captures no keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Kroger',
                       owner=self.config.get("owner", ""))

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Kroger Receipts - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Online orders known:       {s['online_discovered']}",
            f"In-store purchases known:  {s['instore_discovered']}",
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
    ap = argparse.ArgumentParser(description="Local supervised Kroger receipt downloader")
    modes = [
        ("login", "open browser for manual Kroger sign-in"),
        ("discover", "discovery pass only; writes discovery.json"),
        ("pilot", "pilot: newest few online orders and in-store purchases"),
        ("online", "process all pickup, delivery and ship orders"),
        ("instore", "process all in-store and fuel purchases"),
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

