"""Bank of America statement downloader (local, supervised, #121).

Usage:
    python bofa_docs.py --open-browser  open a sign-in window of its own
    python bofa_docs.py --login         check the statements list answers
    python bofa_docs.py --discover      list every account's statements
    python bofa_docs.py --pilot         download the 5 newest, then stop
    python bofa_docs.py --all           download everything in scope
    python bofa_docs.py --resume        continue an interrupted run
    python bofa_docs.py --verify        re-validate every saved PDF
    python bofa_docs.py --diagnose      survey the open page (no downloads)
    python bofa_docs.py --record        record your own path to a statement

Filters: --year YYYY  --start-date YYYY-MM-DD  --end-date YYYY-MM-DD
         --max-docs N

Statements of checking, savings and credit card accounts, from Statements &
Documents. Built from a tester's two recordings, and confirmed on that
tester's checking and credit card statements, not yet on savings. Sign in,
open Statements & Documents in that window, and leave it open.

READ-ONLY: the two presses are the statements page's Statements heading, when
the page leaves it shut and a statement is to be downloaded or Diagnose
looks at the page, and again after a long run reloads it, to open its list
the way a person would, and one Download PDF link, when every link's
address is a script, to learn how the page asks for a PDF. Login and
Discover press nothing. It
reloads the statements page to hear its list, at the start and every five
minutes of a long run, and asks for lists and PDFs from inside the
signed-in page the way the page itself does. It never pays,
transfers money, sends money, or changes any account setting. Everything
stays on this machine. Nothing is sent to any external service.

See the STATUS block in bofa_site.py for what is known.
"""
from __future__ import annotations

from paperpull_core import failure
from paperpull_core import listing
from paperpull_core import pressing
from paperpull_core import renaming
from paperpull_core import saved_copy
from paperpull_core import tabs
from paperpull_core.journal import Journal
from paperpull_core.api_census import Requests
from paperpull_core.run_reporting import NEW_LIST_NOTE, lists_what_it_saved, report_run_result

import argparse
import logging
import random
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from paperpull_core import delivery, doc_types, identity, receipt_pdf, scope
from paperpull_core import browser as browser_launcher
import bofa_site as site
from paperpull_core.models import State
from paperpull_core.keys import account_component as _account_component
from paperpull_core.keys import told_apart as _told_apart
from paperpull_core.words import shape_tree, words_for, write_shaped
from storage import (CsvFile, DOCUMENT_INDEX_COLUMNS, JsonStore, Paths,
                     atomic_write_text, build_pdf_filename, load_config,
                     now_iso, sanitize_component, unique_path)

from storage import ensure_owner, PROJECT_DIR, set_filename_owner
log = logging.getLogger("bofa_docs")

DONE_STATES = {State.COMPLETED.value, State.NO_RECEIPT_AVAILABLE.value}


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nNo interactive console available to answer a required prompt.")
        print("Run this from a real console window (use the .bat files).")
        raise SystemExit(3)


class Document:
    """One Bank of America document."""

    def __init__(self, title="", category="", summary="", date="", period="",
                 href="", row_index=-1, confidence="", account="",
                 date_text="", document_id="", occurrence=0, account_ref="",
                 year="", **kw):
        self.title = title
        self.account = account
        self.category = category
        self.summary = summary
        self.date = date
        self.period = period
        self.date_text = date_text  # the row's raw date string, for re-matching
        self.document_id = document_id  # the list's docId, a hint, looked up again
        self.occurrence = occurrence    # nth document with this title, date and account
        # The bank's own key for the account, which the list is asked by.
        # Kept in this install's own records, never in a file that leaves.
        self.account_ref = account_ref
        self.year = year                # the year the list was asked for

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
        """Category, date, title and account name, never the docId, which
        is looked up fresh at download time. A bank sign-in holds checking,
        savings and cards, whose statements can share a day, so the account
        is what tells one from another. Two accounts of one product can carry
        one name, and their statements of one day are numbered by
        paperpull_core.keys.told_apart, the docId first."""
        acct = _account_component(sanitize_component(self.account or ""))
        base = f"{self.category}:{self.date}:{sanitize_component(self.title)[:60]}:{acct}"
        return base if not self.occurrence else f"{base}#{self.occurrence}"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(**d)


def listed_key(d: dict) -> str:
    """The key of the statement a listed row names, before it is
    numbered, from the row as _record_document reads it. A history moved
    to another computer carries no discovery.json, and told_apart finds
    each saved number by this key then."""
    return Document(title=re.sub(r"\s+", " ", (d.get("title") or "")).strip() or "Statement",
                    category=d.get("category") or doc_types.STATEMENT,
                    date=(d.get("date") or "").strip(),
                    account=re.sub(r"\s+", " ", (d.get("account") or "")).strip()).key


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
            # Reuse the person's own tab on Bank of America's site, the page
            # they left open for this. With none open, a tab of this run's
            # own is opened, never a tab of another site (tabs.new_tab).
            # Matched on the parsed host, never a substring, since
            # "provider.com" in an address also matches
            # "provider.com.phish.example".
            live = [p for p in ctx.pages if not p.is_closed()]
            mine = [p for p in live if site.is_safe_url(p.url or "")]
            # Of those, the one on Statements & Documents, told by its
            # address alone. The first tab on the site used to be taken,
            # so with two open a run could work in the wrong one. With
            # several on Statements & Documents, which one is meant cannot
            # be told, so none is taken and nothing is asked of any.
            listing = [p for p in mine if site.is_statements_address(p.url or "")]
            if len(listing) > 1:
                raise pressing.Stop(
                    "get the statements tab", "several tabs are on the statements page",
                    ["More than one Bank of America tab is on Statements & Documents, "
                     "and which one you mean cannot be told, so nothing was asked of any.",
                     "Close the others, leave one tab on Statements & Documents, and run "
                     "this again."],
                    {"tabs_on_the_statements_page": len(listing)})
            if listing:
                self._work_page = listing[0]
            else:
                self._work_page = mine[0] if mine else tabs.new_tab(ctx)
        else:
            self._work_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.requests
        return self._work_page

    def close(self):
        try:
            if self._cdp_mode:
                pass  # never close the user's own signed-in tab
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
            print("\n!! Bank of America appears to have signed you out.")
            print("Please sign in again in the open browser window.")
            if browser_launcher.ask_or_none(
                    "Press Enter after you are signed in... ") is None:
                print("Then press Resume here to carry on from where this stopped.")
                raise SystemExit(0)

    def stop_with(self, step: str, e: Exception) -> None:
        """Say why the statements could not be read, write the failure file
        when the page did something this app does not know, and stop the
        run as one that stopped, never as a clean run that found nothing."""
        self.progress.save(backup=True)
        if isinstance(e, site.NotThere):
            lines = ["The Bank of America tab is not on Statements & Documents, so "
                     "nothing was asked of it. In that window, open Statements & "
                     "Documents (it is linked from an account's page), leave it "
                     "there, and run this again."]
        elif isinstance(e, site.SessionExpired):
            self.stats["session_expired"] = 1
            lines = ["Bank of America answered with a sign-in instead of your "
                     "statements, so the session has ended. Sign in again in the "
                     "open window, open Statements & Documents, and run this again."]
        else:
            # The page did something the recordings did not show. Nothing
            # was guessed at, and the failure file says what, in counts.
            self.write_failure(step, getattr(e, "reason", "") or str(e),
                               postmortem=getattr(e, "facts", None) or None)
            lines = ["The statements page did not answer the way this app knows, "
                     "because %s. Nothing was guessed at and nothing was saved "
                     "for it. The failure file above says what the page did, as "
                     "counts. Attach it to a new issue on GitHub." % e]
        print()
        for text in lines:
            for line in textwrap.wrap(text, width=72):
                print(line)
        raise SystemExit(0)

    def list_changed(self, e: Exception) -> None:
        """Stop the run because the statements list, read again for a
        statement, did not answer the way this app knows (ListUnread).
        Nothing is recorded against the statement. A Resume reads
        no list of its own, so it would read the same list for its first
        statement and stop again (#124), and the run leaves as one whose
        list did not end whole, which only a run that lists carries on from
        (listing.read_again_stopped)."""
        self.write_failure("download a statement", getattr(e, "reason", "") or str(e),
                           postmortem=getattr(e, "facts", None) or None)
        text = ("Bank of America's statements list did not answer the way this app "
                "knows when it was read again for a statement, because %s. Nothing was "
                "guessed at and nothing was saved for it. The failure file above says "
                "what the page did, as counts. Attach it to a new issue on GitHub." % e)
        print()
        for i, line in enumerate(textwrap.wrap(text, width=69)):
            print(("!! " if i == 0 else "   ") + line)
        listing.read_again_stopped(self)

    # -- commands ----------------------------------------------------------

    def cmd_open_browser(self):
        """Open a sign-in window on THIS config's own port and profile.

        A second account opens its own browser, on its own port, with its own
        saved session - so nothing is duplicated in the launcher scripts. You
        sign in; the tool attaches afterwards.
        """
        port = browser_launcher.port_from_cdp_url(self.config.get("cdp_url", ""), "9299")
        profile = self.config["profile_dir"]
        url = site.URLS.get("login") or site.URLS["home"]
        name = browser_launcher.open_signin_browser(profile, port, url,
            # A bank's sign-in is the likeliest place to turn a bare
            # Chromium away, so the person's own Edge or Chrome is tried
            # first, in a profile of its own.
            prefer_real=True,
            mode=self.config.get("browser", "auto"))
        if not name:
            return
        print(f"Opened a sign-in browser on port {port} ({name}).")
        print(f"Profile: {profile}")
        print("Sign in, open Statements & Documents, keep the window OPEN, then")
        print("run the pilot.")

    def _look_at_the_list(self, page):
        """How many accounts the statements list answered with, or why it
        did not. Only a list that answered says a session is signed in, and
        a list needs no PDF link, so nothing is pressed."""
        try:
            return len(site.learn(page, form=False).accounts), None
        except (site.NotThere, site.NotLearned, site.SessionExpired) as e:
            return 0, e

    def cmd_login(self):
        """Says a session is signed in only when the statements list answered
        with an account. Otherwise names a check, a sign-in form, a tab off
        the site or off the statements page, and claims nothing."""
        print("Checking the connection to your Bank of America browser...\n")
        page = self.page()
        if not site.is_safe_url(page.url or "") and tabs.is_own(page):
            # No tab of the person's was on the site, so the one this run
            # opened is sent to the home page, where they sign in.
            site.open_home(page)
        challenge = site.detect_security_challenge(page)
        listed, why = (0, None)
        if not challenge and site.on_statements_page(page):
            listed, why = self._look_at_the_list(page)
        if challenge:
            print(f"!! {challenge}\nResolve it in the browser, then re-run Login.")
        elif listed:
            print(f"Success: the statements list answered, with {listed} account(s).")
            print("Keep that window OPEN on Statements & Documents, then run the pilot.")
        elif not site.is_safe_url(page.url or ""):
            print("Connected, but no tab is on bankofamerica.com. Open it in that")
            print("window and sign in yourself, then run Login again.")
        elif site.looks_signed_out(page):
            print("Connected, and the tab shows a sign-in form. Sign in there")
            print("yourself, answer any code it sends, and keep the window OPEN.")
        elif why is not None:
            print("Connected, but the statements list did not answer, so this cannot")
            print("say whether you are signed in (%s)." % why)
            print("Look at the window, answer anything it asks, and run Login again.")
        else:
            print("Connected, but the tab is not on Statements & Documents, so this")
            print("cannot say whether you are signed in. Open Statements & Documents")
            print("in that window (it is linked from an account's page), then run")
            print("Login again.")
        self.close()

    def _in_scope(self, doc: Document) -> bool:
        a = self.args
        if not doc_types.wanted(doc.category, self.config):
            return False
        if a.type and doc.category.lower() != a.type.lower():
            return False
        if a.year and not (doc.date or "").startswith(str(a.year)):
            return False
        floor = a.start_date or self.config.get("default_start_date")
        if floor and (not doc.date or doc.date < floor):
            return False
        if a.end_date and (not doc.date or doc.date > a.end_date):
            return False
        return True

    def _record_document(self, d: dict, sure: bool = True) -> int:
        """Record one listed statement {title, date, account, document_id,
        account_ref, year, occurrence}. Returns 1 if new. A row that cannot
        be told apart from one saved keeps no id (keys.told_apart), so it is
        never downloaded in its place."""
        title = re.sub(r"\s+", " ", (d.get("title") or "")).strip() or "Statement"
        if doc_types.should_skip(title, self.rules):
            self.stats["skipped_out_of_scope"] += 1
            return 0
        # The list says which category a row is, so the rules only word it.
        category = d.get("category") or doc_types.STATEMENT
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
        summary = "Statement - %s" % account if account else "Statement"
        occurrence = int(d.get("occurrence", 0) or 0)
        if occurrence:
            summary = "%s (%d)" % (summary, occurrence + 1)
        doc = Document(title=title, category=category, summary=summary, date=date,
                       confidence=doc_types.HIGH, account=account,
                       document_id=(d.get("document_id") or "") if sure else "",
                       account_ref=d.get("account_ref") or "",
                       year=d.get("year") or "", occurrence=occurrence)
        existing = self.discovery.get(doc.key)
        if existing is None:
            rec = doc.to_dict()
            rec["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, rec, save=False)
            return 1
        if sure and doc.document_id and (existing.get("document_id") != doc.document_id
                                         or existing.get("account_ref") != doc.account_ref):
            self.discovery.update(doc.key, {"document_id": doc.document_id,
                                            "account_ref": doc.account_ref,
                                            "year": doc.year}, save=False)
        return 0

    def cmd_discover(self, quiet: bool = False) -> int:
        # A listing that stops on the way, however it stops, is noted as one
        # that stopped, for Resume (paperpull_core.listing).
        listing.started(self)
        page = self.page()
        if not site.on_statements_page(page):
            self.check_session(page)
        # The statements page is reloaded to hear its own list call,
        # and every account's statements are asked for the same way, year
        # by year. Nothing is pressed, since a list needs no PDF link. A
        # list that does not fit what the recordings showed stops the run
        # (bofa_site.NotLearned, ListCut).
        try:
            raw = site.collect_documents(page, keep=scope.period_filter(self.args, self.config),
                                         config=self.config)
        except (site.NotThere, site.SessionExpired, site.NotLearned, site.ListCut) as e:
            self.stop_with("read the statements list", e)
        log.info("Bank of America: %d statement(s) across every account", len(raw))
        n_new = 0
        # Two accounts of one product carry one name, so two of their
        # statements can share a title, a day and an account name. A number
        # given stays with the statement it was given to, found by its docId
        # first, and a row that cannot be told apart from one saved is not
        # taken for it (paperpull_core.keys.told_apart). Numbered by the
        # whole key, the category with it, as every app's census asks.
        alike = ("category", "title", "date", "account")
        for d, (occ, sure) in zip(raw, _told_apart(raw, self.discovery.data, fields=alike,
                                                   saved=self.progress.data,
                                                   key_of=listed_key)):
            d["occurrence"] = occ
            n_new += self._record_document(d, sure)
        self.discovery.save()
        # The whole list is in, and only now may a Resume that carries on
        # from it call the run finished (paperpull_core.listing).
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)

        if not quiet:
            docs = [Document.from_dict(v) for v in self.discovery.data.values()]
            print(f"\nDiscovery complete. Statements known: {len(docs)}")
            accounts = self.stats.get("accounts") or {}
            if accounts:
                print(f"  Accounts with statements ({len(accounts)}):")
                for name, n in sorted(accounts.items(), key=lambda kv: -kv[1]):
                    print(f"    {n:4}  {name or '(no name)'}")
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
        """The tab the next document is taken in, on Bank of America's own
        site and never a tab of another site. The statements page's address
        carries the account it shows, so no page is opened by its address,
        and with no tab of the person's on the site the run stops and says
        so (tabs.on_its_site). A tab on the site but off Statements &
        Documents stops at the first ask (bofa_site.NotThere)."""
        return tabs.on_its_site(self, site.is_safe_url, "Bank of America", None)

    def _identity(self, doc: Document):
        """What the statement should name, its day and its account."""
        return identity.Identity(date=doc.date, label=doc.account, kind=doc.title)

    def _rivals(self, doc: Document) -> tuple:
        """The statements this one could be taken for, in two groups, since
        each differs from it by another fact. Every other statement of the
        same day differs by its account, and its own account's statements
        either side of it differ by their day. Asked together, the day the
        first share and the account the second share would both stop
        counting, and nothing would be left to tell them apart by."""
        records = [Document.from_dict(v) for v in self.discovery.data.values()
                   if isinstance(v, dict)]
        same_day = [self._identity(r) for r in records
                    if r.date == doc.date and r.key != doc.key]
        mine = sorted((r for r in records if r.account == doc.account
                       and r.account_ref == doc.account_ref), key=lambda r: (r.date, r.key))
        keys = [r.key for r in mine]
        near = []
        if doc.key in keys:
            i = keys.index(doc.key)
            near = [self._identity(mine[j]) for j in (i - 1, i + 1)
                    if 0 <= j < len(mine) and mine[j].date != doc.date]
        return same_day, near

    def _to_review(self, doc: Document, path: Path, note: str, wrong: bool = False) -> None:
        """Keep a statement for a person in Manual Review, never filed."""
        quarantine = unique_path(self.paths.manual_review, path.name,
                                 self.config["max_path_length"])
        try:
            path.replace(quarantine)
        except OSError:
            quarantine = path
        doc.pdf_path, doc.pdf_filename = str(quarantine), quarantine.name
        self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=note)
        self._write_row(doc, "Kept for review", "Needs Manual Review")
        self.stats["manual_review"] += 1
        if wrong:
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
            self.write_failure("check the saved statement", note)
        print("  %s. It is in Manual Review, not filed." % note)

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
            except site.ListUnread as e:
                # The list, read again for this statement, did not answer the
                # way this app knows, and every statement after it reads it
                # the same way.
                self.list_changed(e)
            except (site.NotThere, site.NotLearned, site.ListCut) as e:
                # Every statement would say the same, so the run stops here.
                self.stop_with("download a statement", e)
            except site.SessionExpired:
                # Already explained by download_one. Stop rather than grind
                # through the rest producing empty "manual review" entries.
                print("Stopped. Everything downloaded so far is saved.")
                # Left with the stop in flight, which is what the core
                # reports as a run that stopped. A return here finished
                # the run clean, with documents still to download.
                raise SystemExit(0)
            except Exception as e:
                log.exception("Failed on %s", doc.key)
                self._record(doc, State.FAILED, notes=str(e))
                self.stats["failed"] += 1
            self._delay()

    def download_one(self, page, doc: Document, filename: str):
        """Ask for one statement's PDF from inside the page, at its own row's
        address, check it is that statement, and file it. Only a statement
        whose text names its own day and account better than any statement
        it could be taken for is filed. Anything else is kept in Manual
        Review, and a file the bank names for another day is never filed."""
        self.check_session(page)
        folder = self.paths.folder_for(doc.category)
        # The last of the document id, used only if the name is taken.
        out_path = unique_path(folder, filename, self.config["max_path_length"],
                               distinguisher=(doc.document_id or "")[-6:])
        if out_path.name != filename:
            self.stats["duplicate_filenames"] += 1
        if not (doc.document_id and doc.account_ref):
            # Not told apart from one saved (keys.told_apart), so nothing is
            # asked for in its place.
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Not told apart from another statement of its day")
            self._write_row(doc, "Not asked for", "Needs Manual Review")
            self.stats["manual_review"] += 1
            print("  It could not be told apart from another statement of its")
            print("  day, so nothing was asked for. It is marked for manual review.")
            return
        try:
            data, named_day = site.document_bytes(
                page, account_ref=doc.account_ref, date=doc.date,
                document_id=doc.document_id, year=doc.year)
        except site.SessionExpired:
            print("\n  !! Bank of America answered with a sign-in page instead of a document.")
            print("     Your session has expired. Sign in again in the open")
            print("     browser, open Statements & Documents, then run Resume.")
            self.stats["session_expired"] = 1
            raise
        if data is None:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="No longer listed under its id")
            self._write_row(doc, "No longer listed", "Needs Manual Review")
            self.stats["manual_review"] += 1
            print("  The list no longer shows this statement under its id, so")
            print("  nothing was asked for. A Discover first lists it again.")
            return
        strict = bool(self.config.get("refuse_wrong_documents", False))
        if named_day and named_day != doc.date:
            why = "the bank named the file for another day than its statement"
            if not strict:
                # Kept for a person to look at, never filed. The list's day
                # and the file's may be two days the bank keeps for one
                # statement, which only a person can tell.
                review = unique_path(self.paths.manual_review, filename,
                                     self.config["max_path_length"])
                kept = delivery.place(data, review, journal=self.journal, strict=False)
                if kept.ok:
                    doc.pdf_path, doc.pdf_filename = str(review), review.name
            self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
            self._write_row(doc, "Wrong document", "Needs Manual Review")
            self.write_failure("check the saved statement", why)
            self.stats["manual_review"] += 1
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
            print("  Not filed, because %s.%s" % (
                why, "" if strict else " It is in Manual Review."))
            return
        # Staged, checked against this statement and every other account's
        # of its day, and only then put in place (paperpull_core.delivery).
        # Then checked by its day against its own account's either side
        # (_rivals).
        expect = self._identity(doc)
        same_day, near = self._rivals(doc)
        got = delivery.place(data, out_path, expect=expect, rivals=same_day,
                             journal=self.journal, strict=strict)
        print("  %s" % got.say())
        if got.outcome == delivery.WRONG:
            why = "the statement that came back is not the one it was listed as"
            self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
            self._write_row(doc, "Wrong document", "Needs Manual Review")
            self.write_failure("check the saved statement", why)
            self.stats["manual_review"] += 1
            self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
            print("  Nothing was saved for it. The file was destroyed rather")
            print("  than filed under this statement's name.")
            return
        saved = got.ok
        if saved:
            verdict = got.verdict.outcome if got.verdict is not None else identity.UNCHECKED
            if verdict == identity.VERIFIED:
                # Always, so the day is checked even when the first check
                # told it apart by its account alone. With nothing either
                # side this is the plain check of its day (identity.verify).
                verdict = identity.distinguish(out_path, expect, near).outcome
                if verdict == identity.REFUSED and strict:
                    # As delivery does with a wrong statement when this is
                    # set, it is not kept at all.
                    try:
                        out_path.unlink()
                    except OSError as e:
                        log.info("could not remove the refused statement: %s", type(e).__name__)
                    why = "the statement that came back is another month's"
                    self._record(doc, State.NEEDS_MANUAL_REVIEW, notes=why)
                    self._write_row(doc, "Wrong document", "Needs Manual Review")
                    self.write_failure("check the saved statement", why)
                    self.stats["manual_review"] += 1
                    self.stats["wrong_document"] = self.stats.get("wrong_document", 0) + 1
                    print("  Nothing was saved for it, because %s." % why)
                    return
            if verdict == identity.REFUSED:
                self._to_review(doc, out_path, "The statement names another statement's "
                                "day or account better than its own", wrong=True)
                return
            if verdict != identity.VERIFIED:
                self._to_review(doc, out_path, "The statement's day and account could not "
                                "be checked in its text")
                return
        if not saved:
            self._record(doc, State.NEEDS_MANUAL_REVIEW,
                         notes="Could not capture the document PDF")
            self._write_row(doc, "Capture failed", "Needs Manual Review")
            self.write_failure('capture the document', 'the document would not render')
            self.stats["manual_review"] += 1
            print("  Could not capture this document - marked for manual review.")
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
        # --max-docs takes fewer, so a first try can be one statement.
        limit = self.config.get("pilot_count", 5)
        if self.args.max_docs:
            limit = min(limit, self.args.max_docs)
        docs = self._select(limit=limit)
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
        self.stats["mode"] = mode_name
        if mode_name == "all" and not self.args.yes:
            print("This downloads ALL available Bank of America statements.")
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
        # as a run that stopped (paperpull_core.listing).
        docs = [d for d in self._select() if not self._already_done(d)]
        listing.resume(self, docs, lambda left: self.process(left, dry_run=self.args.dry_run))

    def cmd_rename(self):
        """Rename what is already downloaded, without downloading it again.
        Nothing is asked of the provider here (#43, #49). A preview unless
        --apply is given."""
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
        it only sees what arrives after it starts listening."""
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
        differently because of this."""
        if self._journal is None:
            self._journal = Journal(getattr(self, "_work_page", None),
                                    getattr(site, "FALLBACK", None))
        return self._journal

    def write_failure(self, step: str, reason: str, text: str = "",
                      postmortem: dict = None, extra: dict = None) -> None:
        """What the page looked like when this went wrong, to a file.

        Written without anybody having to know to ask for it. One per run,
        taken while the page is still sitting on the thing that broke.
        `extra` holds only our own words, counts and yes or no, such as a
        press's stop's facts."""
        if self.stats.get("failure_files"):
            return
        extra = dict(extra or {})
        if postmortem:
            extra["postmortem"] = postmortem
        extra = extra or None
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
            provider='Bank of America', text=text, extra=extra)
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
        print("  Read it through, then attach it to a new issue on GitHub.")
        print("  It is the one thing that saves a round of guessing.")

    def write_survey(self, stopped=None) -> None:
        """The survey Diagnose is safe to send, on the same list of what may
        leave that the failure file uses, saying why Diagnose stopped when a
        press stopped it."""
        failure.write_survey(
            self.paths.diagnostics,
            page=getattr(self, "_work_page", None),
            selectors=getattr(site, "FALLBACK", None),
            journal=self._journal,
            requests=self._requests,
            provider='Bank of America',
            stopped=stopped or getattr(self, "_diagnose_stopped", None))

    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = words_for('Bank of America', site)
        page = self.page()
        info = {"timestamp": now_iso()}
        stopped = None
        try:
            info["on_site"] = site.is_safe_url(page.url or "")
            info["signed_out"] = site.looks_signed_out(page)
            # The account holder's name is never written, even where its
            # parts are ordinary words on the fixed list.
            site.set_private_words([self.config.get("owner", "")])
            info["challenge"] = site.detect_security_challenge(page)
            info["mapped"] = not getattr(site, "NOT_MAPPED", "")
            # The page the person left open, and on the statements page what
            # its own list call answers, as names and counts. Nothing is
            # followed or downloaded, and the one press is the Statements
            # heading when it is shut (bofa_site.survey).
            info["survey"] = site.survey(page)
            # No screenshot. A bank's pages show balances, and a PNG of one
            # would sit in Diagnostics where it is easy to attach to a bug
            # report by accident.
        except pressing.Stop as stop:
            # Something over the Statements heading ends the look there, and
            # the file still says what was seen and why it stopped.
            stopped = stop
            info["stopped"] = {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
        except Exception as e:
            info["error"] = type(e).__name__
        self._diagnose_stopped = stopped
        out = self.paths.diagnostics / "diagnose-documents.json"
        write_shaped(out, info, words)
        if stopped is not None:
            # The stop's own words, as a run says them.
            pressing.say(stopped)
        print(f"Wrote {out}")
        print("  That is the detailed file, for repairing this provider. Any word")
        print("  in it that is not on PaperPull's fixed list is written as its")
        print("  shape, a for a letter and 9 for a digit, so it can be attached")
        print("  too. Read it through first.")
        sv = info.get("survey") or {}
        pages = sv.get("pages", [])
        print(f"Pages surveyed: {len(pages)}   "
              f"on bankofamerica.com: {sum(1 for p in pages if p.get('on_site'))}")
        learned = sv.get("list") or {}
        if "stopped" in learned:
            print(f"Statements list: not read ({shape_tree(learned.get('stopped', ''), words)})")
        else:
            print(f"Statements list: {shape_tree(learned.get('accounts', '?'), words)} account(s), "
                  f"{shape_tree(learned.get('years', '?'), words)} year(s), "
                  f"PDF links {'understood' if learned.get('pdf_form_learned') is True else 'NOT understood'}")

    def cmd_record(self):
        """Record the path a person takes to a document, so this app can be
        written to take the same one. Downloads nothing, and captures no
        keystroke. The whole thing is in the core."""
        self.stats["mode"] = "record"
        from paperpull_core.recorder import record_session
        record_session(self.page(), site, self.paths.diagnostics,
                       provider='Bank of America',
                       owner=self.config.get("owner", ""))

    # -- summary -----------------------------------------------------------

    def write_run_summary(self):
        s = self.stats
        s["ended"] = now_iso()
        dates = sorted(d for d in s["dates"] if d)
        new_files = s.get("new_files", [])
        atomic_write_text(self.paths.run_summary, "\n".join([
            "Bank of America Documents - run summary",
            "=" * 40,
            f"Run start:                 {s['started']}",
            f"Run end:                   {s['ended']}",
            f"Mode:                      {s['mode'] or '(none)'}",
            f"Documents known:           {s['discovered']}",
            f"NEW files this run:        {len(new_files)}",
            f"Statements downloaded:     {s['statements']}",
            f"Tax documents downloaded:  {s['tax_documents']}",
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
        description="Local supervised Bank of America statement downloader (read-only)")
    for name, help_text in [
            ("login", "check that the statements list answers"),
            ("discover", "list every account's statements; writes discovery.json"),
            ("pilot", "download the 5 newest in-scope statements, then stop"),
            ("all", "download everything in scope (asks for confirmation)"),
            ("resume", "continue an interrupted run"),
            ("verify", "re-validate every saved PDF"),
            ("rename", "rename downloaded files to this app's current naming"),
            ("diagnose", "survey the open page and its statements list (no downloads)"),
            ("record", "record your own path to a statement, so this app can be repaired (downloads nothing)"),
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
    ap.add_argument("--type", help="Statement or 'Tax Document'")
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
        # Something over the Statements heading, or a press that did not go
        # through, stops the run here, with the reason said and the failure
        # file written.
        pressing.stop_run(app, stop)
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
            # them, and only the panel is told how it ended (#103).
            report_run_result(app.stats)
        elif app.stats["mode"] not in ("", "diagnose", "record"):
            app.write_run_summary()
        app.close()
    # A run that saved nothing must not look like a clean run.
    if app.stats.get("session_expired"):
        return 2
    if app.stats.get("failed") or app.stats.get("manual_review"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
