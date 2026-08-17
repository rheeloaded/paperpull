"""Gap purchase-history & receipt downloader (local, supervised).

Usage:
    python gap_receipts.py --login
    python gap_receipts.py --discover
    python gap_receipts.py --pilot            (newest few of each kind)
    python gap_receipts.py --all
    python gap_receipts.py --online           (online orders only)
    python gap_receipts.py --instore          (in-store purchases only)
    python gap_receipts.py --resume
    python gap_receipts.py --verify
    python gap_receipts.py --review-names
    python gap_receipts.py --diagnose [--order-number N]
    python gap_receipts.py --dry-run

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-purchases N  --order-number N

Everything runs locally. No receipt data leaves this machine.
Authentication is always manual (--login opens a browser and waits for you).
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

from paperpull_core import classification, receipt_pdf
from paperpull_core import browser as browser_launcher
import gap_site as site
from paperpull_core.models import (DONE_STATES, IN_STORE, ONLINE, Item, Purchase, State)
from storage import (CsvFile, JsonStore, ORDER_HISTORY_COLUMNS, Paths,
                     RECEIPT_INDEX_COLUMNS, atomic_write_text, backup_file,
                     build_pdf_filename, load_config, now_iso, title_case,
                     unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("gap_receipts")


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
        never scripted. Plain Chromium is enough for Gap - it does not block
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
            # window Gap opens to print also has window.print() intercepted
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
        shares the user's session AND receives our init script — existing
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

    def check_session(self, page) -> None:
        """Raise/pause on sign-out or security challenges."""
        challenge = site.detect_security_challenge(page)
        if challenge:
            self.progress.save(backup=True)
            print(f"\n!! {challenge}")
            print("Processing stopped. Please resolve the challenge yourself in the")
            print("browser window. I will NOT attempt to bypass it.")
            ask("Press Enter once the page looks normal again (or Ctrl+C to quit)... ")
        if site.looks_signed_out(page):
            self.progress.save(backup=True)
            print("\n!! Gap appears to have signed you out.")
            print("Please sign in manually in the open browser window.")
            ask("Press Enter after you are signed in again... ")
            site.goto_orders(page)

    # -- commands -----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9233")
        profile = self.config["profile_dir"]
        url = site.URLS.get("orders") or site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url, prefer_real=False)
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, keep the window OPEN, then run the pilot.")

    def cmd_login(self):
        if self.config.get("cdp_url"):
            # CDP mode: the browser is launched by login.bat (not here). This
            # just verifies we can connect and that you are signed in.
            print("Checking the connection to your signed-in Gap browser...\n")
            page = self.page()
            site.goto_orders(page)
            challenge = site.detect_security_challenge(page)
            if challenge:
                print(f"!! {challenge}")
                print("Resolve it yourself in the browser window, then re-run --login.")
            elif site.looks_signed_out(page):
                print("Connected, but Gap shows the signed-out page.")
                print("Sign in in the open browser window (keep it OPEN), then re-run --login.")
            else:
                print("Success: connected to your signed-in Gap session.")
                print("Keep that browser window OPEN, then run the diagnostics or pilot.")
            self.close()
            return
        print("Opening Gap.com in a dedicated supervised browser profile.")
        print("Sign in manually (username, password, any verification codes).")
        print("This tool never touches your credentials.\n")
        page = self.page()
        page.goto(site.URLS["home"], wait_until="domcontentloaded", timeout=60000)
        ask("Press Enter here AFTER you have finished signing in... ")
        site.goto_orders(page)
        if site.looks_signed_out(page):
            print("It still looks like you are signed out; the orders page bounced to login.")
            print("Sign in in the browser, then run:  python gap_receipts.py --login")
        else:
            print("Signed-in session detected.")
        self.close()

    # NOTE: unlike the year-paginated merchants, Gap needs no year loop.
    # Its order history has no year filter and no startIndex pagination - one
    # scrolled page holds everything the account still exposes (about the last
    # 13 months) - so discovery is a single pass. --year / --start-date /
    # --end-date still apply, as filters at selection time.

    def cmd_discover(self, types: Optional[List[str]] = None, quiet: bool = False) -> dict:
        """Discovery pass: load the order-history page, scroll until Gap stops
        appending orders, and record every order card found."""
        page = self.page()
        n_new = 0
        floor = self.args.start_date or self.config.get("default_start_date")

        # Gap has no year pages and no startIndex pagination: goto_orders loads
        # the order-history page and scrolls until Gap stops appending orders,
        # so one pass sees the entire available history.
        site.goto_orders(page)
        self.check_session(page)
        cards = site.collect_cards(page)
        log.info("Purchase history: %d card(s) (%d in-store)",
                 len(cards), sum(1 for c in cards if c.in_store))
        if not cards:
            log.warning("No purchase cards found. If you are signed in and do "
                        "have purchases, run --diagnose to inspect the page.")
        for card in cards:
            purchase = site.card_to_purchase(card)
            if not purchase:
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
                self.discovery.update(key, {
                    "details_url": purchase.details_url,
                    "receipt_url": purchase.receipt_url,
                    "total": purchase.total or self.discovery.get(key).get("total", ""),
                    "status": purchase.status or self.discovery.get(key).get("status", ""),
                    "store_info": purchase.store_info
                    or self.discovery.get(key).get("store_info", ""),
                }, save=False)
        self.discovery.save()

        all_recs = list(self.discovery.data.values())
        self.stats["online_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == ONLINE)
        self.stats["instore_discovered"] = sum(
            1 for r in all_recs if r.get("purchase_type") == IN_STORE)

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
        return {ONLINE: n_new}

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
        # (You already has 2024-and-earlier Gap receipts).
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
        # ---- open details (retry once, per spec 22) ----
        for attempt in (1, 2):
            try:
                site.goto_details(page, purchase)
                self.check_session(page)
                break
            except Exception as e:
                log.warning("Details page failed (attempt %d): %s", attempt, e)
                if attempt == 2:
                    self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                       notes="Details page failed to load twice")
                    self.stats["manual_review"] += 1
                    return
                time.sleep(5)
                site.goto_orders(page)

        # ---- extract ----
        purchase = site.extract_details(page, purchase)
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
            filename = build_pdf_filename(purchase.purchase_date, purchase.summary)
            print(f"  DRY RUN - would save: {filename}")
            return

        # ---- locate + save receipt ----
        saved = self._save_receipt(page, purchase)
        if not saved:
            return  # state already recorded inside

        # ---- CSVs + progress ----
        status = State.NEEDS_MANUAL_REVIEW.value if review_needed else State.COMPLETED.value
        receipt_status = "Downloaded"
        self._write_csv_rows(purchase, receipt_status=receipt_status,
                             processing_status="Review Needed" if review_needed else "Completed",
                             notes_extra=notes_extra)
        final_state = State.NEEDS_MANUAL_REVIEW if review_needed else State.COMPLETED
        self._record_state(purchase, final_state,
                           notes=("Low classification confidence" if review_needed else ""))
        if review_needed:
            self.stats["manual_review"] += 1
        self.stats["receipts_downloaded"] += 1
        print(f"  Saved: {purchase.pdf_filename}")

    # -- receipt saving -----------------------------------------------------

    def _save_receipt(self, page, purchase: Purchase) -> bool:
        """Save the Gap order-details page as a verified PDF receipt.

        Gap has no separate printable invoice: the hydrated order-details page
        IS the receipt. process_one already navigated there to extract the
        details, so it is on screen; _capture_document strips the site chrome
        and CDP printToPDF renders it directly. No buttons are clicked and the
        native print dialog is never involved.
        """
        if site.looks_signed_out(page):
            print("  Gap is asking you to verify your sign-in.")
            print("  Complete it in the browser window (password/OTP).")
            self.check_session(page)
            site.goto_details(page, purchase)
            if site.looks_signed_out(page):
                self._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                                   notes="Could not pass re-authentication")
                self.stats["manual_review"] += 1
                return False

        # Make sure we are on this order's details page (the receipt).
        if "order-details" not in (page.url or ""):
            site.goto_details(page, purchase)
        site.scroll_full_page(page)

        if not site.receipt_is_present(page):
            self._record_state(purchase, State.NO_RECEIPT_AVAILABLE,
                               notes="Order-details receipt did not render")
            self._write_csv_rows(purchase,
                                 receipt_status="No printable receipt available",
                                 processing_status=State.NEEDS_MANUAL_REVIEW.value,
                                 notes_extra="Order-details page did not hydrate")
            self.stats["no_receipt"] += 1
            self.stats["manual_review"] += 1
            print("  Order-details receipt did not render - marked for manual review.")
            return False

        purchase.document_type = "Receipt"
        folder = self.paths.folder_for(purchase.purchase_type,
                                       purchase.document_type)
        filename = build_pdf_filename(purchase.purchase_date, purchase.summary,
                                      purchase.document_type)
        out_path = unique_path(folder, filename, self.config["max_path_length"])
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
        """Render the Gap order-details receipt to PDF.

        Gap ships NO print stylesheet, so printing the page as-is captures the
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

        tokens = receipt_pdf.expected_tokens_for(purchase)
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
        self.cmd_discover(types=[ONLINE, IN_STORE], quiet=False)
        selected: List[Purchase] = self._select_purchases(
            ONLINE, limit=self.config["pilot_online"])
        selected += self._select_purchases(
            IN_STORE, limit=self.config["pilot_instore"])
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
        print("e.g.:  python gap_receipts.py --all")

    def cmd_run(self, types: List[str], mode_name: str):
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This will download your FULL available Gap purchase history")
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
        review = [r for r in rows if r.get("Classification Confidence") == "Low"
                  or "Review" in (r.get("Processing Status") or "")]
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
            new_name = build_pdf_filename(date, new_summary, doc_type)
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

    def cmd_diagnose(self):
        """Inspect one purchase per type and record local diagnostics."""
        self.stats["mode"] = "diagnose"
        import json as _json
        page = self.page()
        if not self.discovery.data:
            self.cmd_discover(quiet=True)
        for ptype in (ONLINE, IN_STORE):
            candidates = self._select_purchases(ptype, limit=1)
            if self.args.order_number:
                candidates = [p for p in
                              self._select_purchases(None, limit=None)
                              if p.order_number == self.args.order_number]
            if not candidates:
                print(f"No {ptype} purchase available to diagnose.")
                continue
            p = candidates[0]
            print(f"\nDiagnosing {ptype} purchase #{p.order_number} ...")
            info = {"purchase": p.key, "timestamp": now_iso()}
            try:
                site.goto_details(page, p)
                info["url"] = page.url
                info["title"] = page.title()
                info["signed_out"] = site.looks_signed_out(page)
                info["challenge"] = site.detect_security_challenge(page)
                buttons = []
                for role in ("button", "link", "tab"):
                    try:
                        loc = page.get_by_role(role)
                        for i in range(min(loc.count(), 80)):
                            t = (loc.nth(i).inner_text(timeout=800) or "").strip()
                            if t and len(t) < 80:
                                buttons.append({"role": role, "name": t})
                    except Exception:
                        continue
                info["controls"] = buttons
                info["receipt_section_found"] = site.open_receipt_section(page)
                controls = site.find_print_receipt_controls(page)
                info["print_receipt_controls"] = len(controls)
                info["invoice_controls"] = len(site.find_invoice_controls(page))
                info["iframe_receipt"] = site.find_receipt_iframe(page) is not None
                info["items_extracted"] = [i.name for i in site.extract_items(page)][:20]
                shot = self.paths.diagnostics / f"diagnose-{ptype}-{p.order_number}.png"
                page.screenshot(path=str(shot), full_page=True)
                info["screenshot"] = str(shot)
            except Exception as e:
                info["error"] = str(e)
            out = self.paths.diagnostics / f"diagnose-{ptype}-{p.order_number}.json"
            atomic_write_text(out, _json.dumps(info, indent=2))
            print(f"  Wrote {out}")
            print(f"  Print-receipt controls found: {info.get('print_receipt_controls', '?')}; "
                  f"receipt section: {info.get('receipt_section_found', '?')}")

    # -- run summary --------------------------------------------------------

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates_processed"] if d)
        new_files = s.get("new_files", [])
        lines = [
            "Gap Receipts - run summary",
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
        if new_files:
            atomic_write_text(
                self.paths.root / "new-this-run.txt",
                f"# {len(new_files)} file(s) downloaded on this run "
                f"({s['ended']}):\n" + "\n".join(sorted(new_files)) + "\n")
            print(f"\n{len(new_files)} NEW file(s) downloaded this run "
                  f"(listed in new-this-run.txt).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Local supervised Gap receipt downloader")
    modes = [
        ("login", "open browser for manual Gap sign-in"),
        ("discover", "discovery pass only; writes discovery.json"),
        ("pilot", "pilot: newest few online orders and in-store purchases"),
        ("all", "process every purchase (asks for confirmation)"),
        ("online", "process all Online orders"),
        ("instore", "process all In-store purchases"),
        ("resume", "resume incomplete purchases"),
        ("verify", "re-validate every indexed PDF"),
        ("review-names", "interactively fix low-confidence names"),
        ("diagnose", "inspect one order, write diagnostics"),
    ]
    for name, help_text in modes:
        ap.add_argument(f"--{name}", action="store_true", help=help_text)
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
        elif getattr(args, "review_names"):
            app.cmd_review_names()
        elif args.diagnose:
            app.cmd_diagnose()
        elif args.dry_run:
            app.cmd_run([ONLINE, IN_STORE], "dry-run")
        else:
            build_parser().print_help()
            return 0
    except KeyboardInterrupt:
        print("\nStopped by user. Progress saved.")
    finally:
        app.progress.save()
        app.discovery.save()
        if app.stats["mode"]:
            app.write_run_summary()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

