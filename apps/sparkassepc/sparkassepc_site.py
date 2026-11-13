"""Read the Sparkasse Pforzheim Calw Postfach and its direct PDFs.

The Postfach is read in the person's own tab, folder by folder and page by
page, as the bank's pages show it. A page is turned by pressing the page's
own numbered pager button, the press a person makes, and it is read only
once the page shows that page number. This app never sends a form of its
own.

A document's PDF comes from pressing the direct download link in its own
row, the row found by its identity. That press starts the bank's own
prepare step, and the navigation it then starts toward the bank's PDF
service is held in the browser, so the tab stays in the Postfach. That one
address is then asked for once from inside the tab. Whether the bank marks
a document read when its PDF is taken has not been checked. Nothing else
is pressed.
"""
from __future__ import annotations

from hashlib import sha256
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlsplit


from paperpull_core import failure
from paperpull_core import intake, pressing
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows, join
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("sparkassepc_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Sparkasse Pforzheim Calw", sys.modules[__name__])

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("www.sparkasse-pforzheim-calw.de",)

BASE = "https://www.sparkasse-pforzheim-calw.de"
POSTFACH = "/de/home/onlinebanking/e_postfach/"
FOLDERS = {
    "Posteingang": POSTFACH + "Posteingang.html",
    "Gesendet": POSTFACH + "gesendete-nachrichten.html",
    "Papierkorb": POSTFACH + "papierkorb.html",
}
URLS = {
    "home": BASE + "/de/home/onlinebanking/finanzuebersicht.html",
    "login": BASE + "/de/home/login-online-banking.html",
    "documents": BASE + FOLDERS["Posteingang"],
}

# The Postfach's own parts, as the contributor's account showed them.
ROW_CSS = "form.postfach tr.postbox-message-row"
LINK_CSS = "a.postbox-message-direct-download"
PAGER_CSS = 'form.postfach .bpager .pagerbuttons input[type="submit"]'
# Where the direct download's navigation goes, held in the browser.
PDF_ROUTE = "**/services/download.service/**"

# How many rows a Postfach page holds was not measured. A page with no pager
# that holds this many rows or more stops the listing, since a pager that
# went missing would otherwise read as the last page. A page of this run's
# that had a next page says how many a page holds, and is used once seen.
FULL_PAGE = 10

# The steps a press stops at, for the failure file (paperpull_core.pressing).
TURN_STEP = "turn a postfach page"
TAKE_STEP = "take a document"


class SessionExpired(RuntimeError):
    """The document API needs the user to sign in again."""


class ListStopped(RuntimeError):
    """A list could not be read whole. A run that reads the list again while
    it downloads stops once with the list unread
    (listing.read_again_stopped), since every document after it reads the
    same list."""


class NoFile(RuntimeError):
    """The bank lists a document and gives no PDF for it, an HTTP error for
    that one file, no download ticket, or an answer that is not a PDF. Only
    that document fails, and the run goes on to the next, as DKB's does. It
    was ListStopped, which ended every run at the first such document, and
    since runs go newest first nothing older was ever saved."""


class NotToldApart(RuntimeError):
    """A fresh list cannot uniquely identify a document."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a German bank and broker, whose pages may be
# in German or English. Never move money, never pay, never buy, sell or
# place an order, never start, change or pause a savings plan, never open,
# close, lock or replace anything, never take out credit, never change a
# setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # Money moving, German. "Übertrag" is a depot moved to another bank.
    r"((ue|ü)berweis|(ue|ü)bertrag|\bechtzeit|dauerauftr|lastschrift|\bumbuch|"
    r"\bsenden\b|\bzahl(en|ung)\b|\bbezahl|geld\s+(senden|anfordern)|\bauszahl|"
    r"\beinzahl|\babheb|\bvorlage|\bempf(ae|ä)nger|\bzur(ue|ü)ckbuch|"
    r"widersprech|widerspruch|"
    # Trading, German. Kaufen and Verkaufen are what a trade button says.
    # "Kauf" alone is in the name of every Wertpapierabrechnung, so only a
    # label that is nothing but that word is refused.
    r"\bkaufen\b|\bverkaufen\b|^\s*(ver)?kauf\s*$|\border\b|\bhandel|\bzeichn|"
    r"\blimit|\bstop\b|\bkurs\s*alarm|\bpreis\s*alarm|\bsparplan\s+"
    r"(anlegen|einrichten|erstellen|(ae|ä)ndern|pausieren|aussetzen|l(oe|ö)schen)|"
    # Credit of any kind, Ratenkredit, Wertpapierkredit and a Kreditrahmen
    # included, while "Kreditkarte" passes.
    r"kredit\b|\bdispo|rahmen\b|\bhebel|\bderivat|\bupgrade|"
    # Cards, accounts and the person's own data, German.
    r"\ber(oe|ö)ffn|\bbeantrag|\bantrag\b|\bk(ue|ü)ndig|\bsperr|entsperr|\bpin\b|"
    r"\bfreigeb|\bfreigabe|\bbest(ae|ä)tig|\bzustimm|\bakzeptier|"
    r"\b(ae|ä)nder|\bbearbeit|\bl(oe|ö)sch|\bentfern|\barchivier|\beinricht|"
    r"\baktivier|deaktivier|\babschlie(ss|ß)|\bhinzuf(ue|ü)g|\banlegen\b|"
    r"als\s+gelesen|gelesen\s+markier|\bfreistellungsauftrag\s+(erteilen|anlegen|(ae|ä)ndern)|"
    r"\bkontowecker|\bbenachrichtigung|"
    r"\babmeld|\bpasswort|\bkennwort|\bger(ae|ä)t|\badresse\b|\be-?mail\b|"
    r"\btelefon|\bhandynummer|pers(oe|ö)nliche\s+daten|\beinstellung|"
    # Ordering, requesting, signing, uploading and entering data, German.
    # A loss certificate asked for closes the year's loss pot, and a paper
    # copy or a duplicate can carry a fee. "Papier" at a word's start only,
    # since every Wertpapierabrechnung holds it.
    r"anforder|bestell|unterschreib|unterzeichn|\bsignier|hochlad|aktualisier|"
    r"hinterleg|freischalt|\bbeauftrag|\bper\s+post\b|\bpapier(?!korb\b)|duplikat|\bkopie|"
    r"zweitschrift|\b\w*(konto|depot)\s+(er)?(oe|ö)ffnen|"
    # Opening anything but a document, requesting, signing, uploading,
    # paper and copies, credit and cards, English.
    r"\bopen\b[\w\s-]{0,30}?\b(accounts?|depots?|portfolios?|cards?|overdraft|"
    r"positions?|loans?|savings|investments?)\b(?!\s+(statements?|documents?))|"
    r"\brequest|\bupload|\bsign\b|\be-?sign|\bpaper\b|\bcop(y|ies)\b|\bduplicate|"
    r"\block\b|\bunlock|\breplac|\bactivat|overdraft|credit\s+(line|limit|increase)|"
    r"\bloans?\b|\bborrow|\bmargin\b|"
    r"\bclose\s+(my\s+|the\s+|this\s+|an?\s+)?(account|depot|portfolio|card)|"
    # Money moving and trading, English
    r"transfer\b|\bwire\b|\bpay\b|payment|\bdeposit|withdraw|\bbuy\b|\bsell\b|"
    r"\btrade\b|savings\s+plan|\bstanding\s+order|direct\s+debit|"
    # Word boundaries on both sides of the verb stems, so "Credit" and
    # "Exchange" stay allowed.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bdelet|\bremov(e|es|ed|ing|al)\b|\bsubmit|\bconfirm\b|\baccept\b|"
    r"\bmark\s+as\s+read\b|\barchive\b|log\s*out|logout|sign\s*out)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    # "Open", "Öffnen", "View" and "Anzeigen" alone are a document's own
    # button. Beside any other word they need a document's word too, since
    # "Kinderdepot öffnen" and "Open a child account" open an account.
    r"(herunterladen|download|\bpdf\b|^\s*anzeigen\s*$|^\s*(oe|ö)ffnen\s*$|"
    r"^\s*view\s*$|^\s*open\s*$|"
    r"postbox|postfach|mailbox|\binbox\b|dokument|document|kontoauszug|ausz(ue|ü)ge|"
    r"abrechnung|depotauszug|finanzreport|steuer|\btax\b|ertr(ae|ä)gnis|"
    r"verlustbescheinigung|kosteninformation|mitteilung|statement|"
    r"\bconfirmations?\b|\barchiv\b|mehr\s+(anzeigen|laden)|show\s+more|load\s+more)", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name) or re.fullmatch(r"[1-9]\d{0,2}|Posteingang|Gesendet|Papierkorb", name, re.I))


# The phrases of a prompt, never a bare product or menu name, which an
# ordinary signed-in page can show too.
SECURITY_CHALLENGE_MARKERS = [
    # German
    "tan eingeben", "geben sie die tan ein", "bestätigungscode", "sicherheitscode",
    "code eingeben", "geben sie den code ein", "zu viele versuche",
    "sitzung ist abgelaufen", "sitzung abgelaufen", "sie wurden abgemeldet",
    "aus sicherheitsgründen abgemeldet",
    # English
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out",
]

# Authentication and OAuth callback pages are never a document list.
LOGIN_URL_MARKERS = ["/login", "/logout", "?logout"]

RATE_LIMIT_MARKERS = ["zu viele anfragen", "später erneut", "too many requests",
                      "rate limit", "try again later", "temporarily unavailable",
                      "unusual traffic", "http error 429"]


def looks_signed_out(page) -> bool:
    """True where the page is a sign-in page by its address, shows a
    password field, or cannot say where it is."""
    try:
        url = (page.url or "").lower()
    except Exception:
        # A page that cannot say where it is is treated as signed out, the
        # safe answer.
        return True
    if not is_safe_url(url) or any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        return True
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the code, CAPTCHA or throttling prompt on screen, or None.
    Visible text only, and never a reason to think a session is signed in
    when it finds nothing."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def _page_summary(page) -> dict:
    out = {"url": "", "title": ""}
    try:
        url = page.url or ""
        out["on_site"] = is_safe_url(url)
        # The path only. A query string or a fragment can carry a session
        # or an account's id.
        out["url"] = (redact(re.split(r"[?#]", url, maxsplit=1)[0]) if out["on_site"]
                      else "(not on www.sparkasse-pforzheim-calw.de)")
    except Exception:
        out["on_site"] = False
    if not out["on_site"]:
        # Nothing is read off a page of another site.
        return out
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 80)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                controls.append({"role": role, "text": redact(text)[:60],
                                 "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    try:
        out["password_fields"] = page.locator("input[type='password']").count()
    except Exception:
        pass
    return out


def survey(page, dwell_ms: int = 2000) -> dict:
    """What the page the person left open looks like, without following,
    pressing or downloading anything."""
    report = {"pages": [], "responses": [], "mapped": True}
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:
        pass
    report["pages"].append(_page_summary(page))
    report["listing_counts"] = dict(_summary)
    return report


def _folder(page, folder, fresh=False):
    """Open the exact folder linked by the Postfach navigation. A tab
    already showing it is left there, unless the list is to be read
    `fresh`, since a page the tab drew a while ago shows the folder as it
    was then."""
    if not is_safe_url(page.url) or looks_signed_out(page):
        raise SessionExpired("Sign in to Sparkasse Pforzheim Calw again.")
    if (not fresh and urlsplit(page.url).path == FOLDERS[folder]
            and page.locator("form.postfach").count()):
        return
    slug = FOLDERS[folder].rsplit("/", 1)[-1].removesuffix(".html")
    links = page.locator(f'a.nbf-guided-tour-navigation_{slug}[href^="{FOLDERS[folder]}?"]:visible')
    if not links.count():
        raise ListStopped("The Postfach folder link is missing.")
    link = links.first
    label = re.sub(r"\s*\d+\s*$", "", link.inner_text(timeout=5000).strip())
    if label.casefold() != folder.casefold() or not is_safe_control(label):
        raise ListStopped("The Postfach folder link has changed.")
    href = join(page.url, link.get_attribute("href") or "")
    if not is_safe_url(href) or urlsplit(href).path != FOLDERS[folder]:
        raise ListStopped("The Postfach folder address changed.")
    page.goto(href, wait_until="domcontentloaded", timeout=15000)
    # A sign-in page in its place is a session that ended, never a list
    # that stopped.
    if looks_signed_out(page):
        raise SessionExpired("Sign in to Sparkasse Pforzheim Calw again.")
    if urlsplit(page.url).path != FOLDERS[folder]:
        raise ListStopped("The Postfach folder did not open.")
    page.locator("form.postfach").wait_for(timeout=8000)


def goto_documents(page):
    """The Postfach in this tab, and whether it shows signed in.

    A tab off the site, a blank tab of the run's own say, is sent to the
    Postfach by its address first, as renaultbank_site.py does. The bank
    keeps its session in a cookie that tab shares, so it is judged only
    once it is there. A tab of the person's off the site is never handed
    here (the app's page() and paperpull_core.tabs)."""
    try:
        if not is_safe_url(page.url or ""):
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        if looks_signed_out(page):
            return False
        if urlsplit(page.url).path not in FOLDERS.values():
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=15000)
        return (is_safe_url(page.url) and not looks_signed_out(page)
                and page.locator("form.postfach").count() == 1)
    except Exception:
        return False


def ensure_statements(page):
    return goto_documents(page)


def answers_its_list(page):
    """Whether the Postfach answers with its list now. The folder the tab
    shows is asked for afresh by its address, since a page the tab drew
    before says nothing of the session now. A sign-in page in its place
    raises SessionExpired and a list that will not read ListStopped."""
    path = urlsplit(page.url or "").path
    folder = next((name for name, known in FOLDERS.items() if known == path), "Posteingang")
    return bool(_list_answers(page, folder))


_LIST_JS = r"""
() => {
  const form = document.querySelector("form.postfach");
  if (!form) return null;
  const pager = form.querySelector(".bpager");
  const value = (input) => input ? input.getAttribute("value") : null;
  const actives = pager ? [...pager.querySelectorAll(".active input")] : [];
  const nexts = pager ? [...pager.querySelectorAll(".next input:enabled")] : [];
  const offered = pager ? [...pager.querySelectorAll('.pagerbuttons input[type="submit"]:enabled')]
    .map(value) : [];
  const period = form.querySelector(".select-time select");
  const search = form.querySelector("input.mkp-input-with-icon");
  const rows = [...form.querySelectorAll("tr.postbox-message-row")].map((row, index) => {
    const links = row.querySelectorAll("a.postbox-message-direct-download");
    const link = links[0];
    const box = row.querySelector('input[type="checkbox"]');
    return {index, links: links.length,
            title: link ? (link.getAttribute("title") || link.textContent || "").trim() : "",
            identity: box ? box.getAttribute("value") : null,
            date: row.cells[3] ? row.cells[3].textContent.trim() : "",
            unread: row.classList.contains("tablerowmarked")};
  });
  return {rows, pager: Boolean(pager), actives: actives.length, active: value(actives[0]),
          nexts: nexts.length, next: value(nexts[0]), offered,
          filtered: Boolean(search?.value.trim() || (period &&
              period.selectedOptions[0]?.text.trim() !== "Gesamtzeitraum")),
          failed: Boolean(form.querySelector(".failure-msg, .error-msg"))};
}
"""

_NUMBER = re.compile(r"[1-9]\d{0,2}")

# How long a page is given to show what a press or an address asked for.
SETTLE_SECONDS = 20


def _row_fault(row):
    """Why a row as the list read it is not the shape this app reads, or
    "". A row with no direct download is kept and counted, never read as
    nothing there. A row with more than one, a downloadable row with no
    identity, and any row whose unread mark is not read stop the listing."""
    if not isinstance(row, dict) or not isinstance(row.get("links"), int):
        return "A Postfach row cannot be read."
    if row["links"] > 1:
        return "A Postfach row offers more than one direct download."
    if not isinstance(row.get("unread"), bool):
        return "A Postfach row's unread mark cannot be read."
    token = row.get("identity")
    if row["links"] == 1 and (not isinstance(token, str) or not token or len(token) > 2048):
        return "A listed PDF has no document identity."
    return ""


# What _look answers besides a page.
SIGNED_OUT, STOPPED = "signed out", "stopped"


def _look(page):
    """The Postfach page the tab shows as ("page", what it lists), or why it
    cannot be read, (SIGNED_OUT, words) or (STOPPED, words). It raises none
    of this module's stops, so a look taken again and again while a page
    changes (_settled) never has to catch one.

    What it lists is its rows, its page number and the page after it as the
    pager says them, and the numbers the pager offers to press. A pager that
    shows no page number this can read stops the listing, and so does one
    that offers a page after this one while saying there is no next page,
    or one beside no rows at all, since a renamed arrow or row would
    otherwise read as the last page or an empty folder. A page with no
    pager reads as page 1 with no page after it, which only a short page
    may be (_collect). A short folder with no rows and no pager reads as
    empty, which only the bank's own empty notice could tell from rows
    renamed, and none has been recorded."""
    if not is_safe_url(page.url) or looks_signed_out(page):
        return SIGNED_OUT, "Sign in to Sparkasse Pforzheim Calw again."
    if urlsplit(page.url).path not in FOLDERS.values():
        return STOPPED, "The browser left the Postfach."
    result = page.evaluate(_LIST_JS)
    if not isinstance(result, dict) or result.get("failed") or not isinstance(result.get("rows"), list):
        return STOPPED, "The Postfach list is missing."
    if result.get("filtered"):
        return STOPPED, "Clear the Postfach search and select Gesamtzeitraum before running."
    rows = []
    for row in result["rows"]:
        fault = _row_fault(row)
        if fault:
            return STOPPED, fault
        rows.append(dict(row, downloadable=row["links"] == 1))
    if not result.get("pager"):
        return "page", {"rows": rows, "pager": False, "number": 1, "next": 0, "offered": set()}
    if not rows:
        return STOPPED, "The Postfach shows a pager and no rows, so the rows have changed."
    active = result.get("active")
    if result.get("actives") != 1 or not isinstance(active, str) or not _NUMBER.fullmatch(active):
        return STOPPED, "The Postfach's active page number cannot be read."
    following = result.get("next")
    if result.get("nexts") not in (0, 1) or (result.get("nexts") and not (
            isinstance(following, str) and _NUMBER.fullmatch(following))):
        return STOPPED, "The Postfach's next page number cannot be read."
    offered = {int(v) for v in result.get("offered") or ()
               if isinstance(v, str) and _NUMBER.fullmatch(v)}
    if not result.get("nexts") and any(n > int(active) for n in offered):
        return STOPPED, "The Postfach offers a later page and no next page, so the pager has changed."
    return "page", {"rows": rows, "pager": True, "number": int(active),
                    "next": int(following) if result.get("nexts") else 0, "offered": offered}


def _settled(page, target=None):
    """The page once it reads, and reads the same twice running, with the
    page number `target` when one is given. A page still changing, between
    a press and the bank's answer, is looked at again until it holds still.
    When it never does within SETTLE_SECONDS, the last reason it would not
    read stops it, SessionExpired for a sign-in page and ListStopped for
    anything else."""
    deadline = time.monotonic() + SETTLE_SECONDS
    last, kind, why = None, STOPPED, "The Postfach did not reach the requested page."
    while True:
        try:
            seen, found = _look(page)
        except Exception:
            # A page between two documents cannot be read for a moment.
            seen, found = STOPPED, "The Postfach page did not finish loading."
        now = None
        if seen != "page":
            kind, why = seen, found
        elif target is None or (found["pager"] and found["number"] == target):
            now = found
        else:
            kind, why = STOPPED, "The Postfach did not reach the requested page."
        if now is not None and last is not None and _same(now, last):
            return now
        last = now
        if time.monotonic() >= deadline:
            if kind == SIGNED_OUT:
                raise SessionExpired(why)
            raise ListStopped(why)
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass


def _same(one, other):
    return ((one["number"], one["next"], one["pager"]) == (other["number"], other["next"], other["pager"])
            and [r.get("identity") for r in one["rows"]] == [r.get("identity") for r in other["rows"]])


_PAGER_JS = r"""
(target) => {
  const form = document.querySelector("form.postfach");
  if (!form) return {why: "no form"};
  const found = [...form.querySelectorAll('.bpager .pagerbuttons input[type="submit"]:enabled')]
    .filter(input => input.getAttribute("value") === String(target));
  if (found.length !== 1) return {why: "not one button"};
  const button = found[0];
  if (button.form !== form) return {why: "another form"};
  if (["formaction", "formmethod", "formtarget", "formenctype"].some(name => button.hasAttribute(name)))
    return {why: "a target of its own"};
  const window_ = form.getAttribute("target");
  if (window_ && window_ !== "_self") return {why: "another window"};
  if (form.querySelector('input[type="checkbox"]:checked')) return {why: "rows selected"};
  return {why: "", action: new URL(form.getAttribute("action") || location.href, location.href).href};
}
"""


def _pause(config=None):
    """The config's own pause between two page turns, as between documents."""
    config = config or {}
    try:
        low = max(0.0, float(config.get("delay_min_seconds", 2.5)))
        high = max(low, float(config.get("delay_max_seconds", 5.0)))
    except (TypeError, ValueError):
        low, high = 2.5, 5.0
    if high > 0:
        time.sleep(random.uniform(low, high))


def _turn(page, target, config=None):
    """Press the Postfach's own numbered pager button for `target`, the press
    a person makes, and answer the page once it shows that page number.

    The button is the one enabled submit button of the Postfach form's pager
    whose value is that number, and digits are all a pager button may say
    (is_safe_control). Its form has to send to the folder's own address and
    stay in this tab, with no row ticked, since a ticked row would go with
    the press. The pause comes first and all of this is read after it, right
    before the press, so a row ticked during the pause is seen. Nothing else
    of the form is touched, and the page itself sends what its press sends."""
    path = urlsplit(page.url).path
    if path not in FOLDERS.values() or not is_safe_url(page.url) or not is_safe_control(str(target)):
        raise ListStopped("The Postfach page control is outside the mailbox.")
    _pause(config)
    found = page.evaluate(_PAGER_JS, target)
    if not isinstance(found, dict) or found.get("why") != "":
        raise ListStopped("The Postfach page control is missing or ambiguous. "
                          "Clear any selected rows in the Postfach.")
    action = str(found.get("action") or "")
    parts = urlsplit(action)
    if not is_safe_url(action) or parts.path != path or parts.fragment:
        raise ListStopped("The Postfach paging address changed.")
    button = page.locator('%s[value="%d"]:enabled' % (PAGER_CSS, target))
    if button.count() != 1:
        raise ListStopped("The Postfach page control is missing or ambiguous.")
    pressing.click(page, button, css=pressing.BUTTONS, words=_words(), step=TURN_STEP,
                   what="the Postfach's page %d button" % target)
    return _settled(page, target)


def _goto_page(page, listed, target, config=None):
    """Turn the folder to page `target` from the page it shows, by the
    pager's own numbered buttons, the one for `target` when the pager
    offers it and otherwise the nearest one toward it. A folder already on
    that page is not turned at all."""
    for _ in range(500):
        if listed["number"] == target:
            return listed
        if not listed["pager"]:
            raise ListStopped("The Postfach pager is missing.")
        number, offered = listed["number"], listed["offered"]
        if target in offered:
            step = target
        elif target > number:
            step = max((n for n in offered if number < n < target), default=0)
        else:
            step = min((n for n in offered if target < n < number), default=0)
        if not step:
            raise ListStopped("The Postfach pager does not offer the page.")
        listed = _turn(page, step, config)
    raise ListStopped("The Postfach reached the page limit.")


_cache = None
_summary = {}


def _collect(page, config=None):
    """Every downloadable row of every folder, read page by page from page 1.

    A part of the list that is missing stops it, never reads as nothing
    there. That is a pager missing from a full page, a page number that
    cannot be read or that skips, and a row shape with no direct download
    link anywhere while rows are listed. A folder of one short page with no
    pager is listed as it is."""
    global _summary
    rows = []
    listed = skipped = 0
    full = 0
    for folder in FOLDERS:
        _folder(page, folder, fresh=True)
        result = _goto_page(page, _settled(page), 1, config)
        expected = 1
        while True:
            number = result["number"]
            if number != expected or number > 500:
                raise ListStopped("The Postfach page sequence changed.")
            if not result["pager"] and len(result["rows"]) >= (full or FULL_PAGE):
                raise ListStopped("The Postfach shows a full page with no pager.")
            for row in result["rows"]:
                listed += 1
                if not row["downloadable"]:
                    skipped += 1
                    continue
                rows.append(_normalize(dict(row, folder=folder, number=number)))
            target = result["next"]
            if not target:
                break
            if target != number + 1:
                raise ListStopped("The Postfach page sequence changed.")
            full = max(full, len(result["rows"]))
            result = _turn(page, target, config)
            expected = target
    if listed and not rows:
        raise ListStopped("No Postfach row offers a direct download, so the rows have changed.")
    unique = {}
    for row in rows:
        key = row["item_id"]
        if key in unique and any(row[k] != unique[key][k] for k in ("title", "date", "account", "category")):
            raise ListStopped("Two different documents share an identity.")
        unique.setdefault(key, row)
    _summary = {"no_direct_download": skipped}
    return list(unique.values())


def listed_rows(page, config=None, fresh=False):
    global _cache
    if fresh or not _cache or _cache[0] is not page:
        try:
            page.bring_to_front()
            _cache = (page, _collect(page, config))
        except (SessionExpired, ListStopped):
            raise
        except Exception:
            raise ListStopped("The Postfach listing did not finish.") from None
    wanted = set((config or {}).get("document_types") or storage_categories())
    return [dict(row) for row in _cache[1] if filed_category(row) in wanted]


def _digest(token):
    return sha256(str(token).encode("utf-8")).hexdigest()


def _normalize(row):
    title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
    date = parse_date(row.get("date"))
    if not title or not date:
        raise ListStopped("A listed PDF has no subject or readable date.")
    account = re.search(r"\bKonto\s+(\d{5,})\b", title, re.I)
    tail = account.group(1)[-4:] if account else ""
    if account:
        title = title[:account.start(1)] + tail + title[account.end(1):]
    # The row's checkbox identifies the document across page reloads.
    # Keep a digest in the archive, never a value that can be submitted.
    token = row.get("identity")
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise ListStopped("A listed PDF has no document identity.")
    return {"title": title, "date": date, "account": "Konto " + tail if tail else "",
            "category": classify("", title), "item_id": _digest(token), "client_id": "",
            "href": BASE + FOLDERS[row["folder"]], "folder": row["folder"],
            "number": row["number"], "index": row["index"]}


def _css_string(text):
    """`text` as a quoted CSS string, every quote and backslash escaped."""
    out = []
    for ch in text:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append("\\%x " % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _take_pdf(page, row, config=None):
    """The PDF of one listed row, from pressing that row's own direct
    download link.

    The folder is turned to the row's page from where it stands, and the
    row is found there by its identity and has to be the document listed.
    The press is held to the control itself, never to the subject it shows,
    which is the document's own words. It is the one direct download link
    of that row, by its class, and its address is the folder's own. The
    navigation it starts toward the PDF service is held in the browser, and
    that one address is then asked for once."""
    _folder(page, row["folder"])
    listed = _goto_page(page, _settled(page), row["number"], config)
    page.bring_to_front()
    page.wait_for_load_state("load", timeout=15000)
    mine = [r for r in listed["rows"] if r["downloadable"] and _digest(r["identity"]) == row["item_id"]]
    if len(mine) != 1:
        raise ListStopped("The document moved since the Postfach was listed.")
    current = mine[0]
    matching = _normalize(dict(current, folder=row["folder"], number=row["number"]))
    if any(matching[k] != row[k] for k in ("item_id", "title", "date", "account", "category")):
        raise ListStopped("The document moved since the Postfach was listed.")
    own = page.locator(ROW_CSS).filter(
        has=page.locator('input[type="checkbox"][value=%s]' % _css_string(current["identity"])))
    if own.count() != 1:
        raise ListStopped("The document moved since the Postfach was listed.")
    link = own.locator(LINK_CSS)
    if link.count() != 1:
        raise NoFile("The row's direct download link is not one link.")
    href = join(page.url, link.get_attribute("href") or "")
    if not href or not is_safe_url(href) or urlsplit(href).path != FOLDERS[row["folder"]]:
        raise NoFile("The direct download link is outside the Postfach.")

    # Every request toward the PDF service is held, and only a plain GET of
    # a PDF's own address is noted. Aborted, never answered with an empty
    # page, since a navigation answered with nothing leaves Playwright
    # waiting for it to finish.
    held = []

    def hold(route):
        request = route.request
        if request.method == "GET" and is_safe_url(request.url) and _pdf_path(request.url):
            held.append(request.url)
        route.abort("aborted")

    page.route(PDF_ROUTE, hold)
    try:
        _press_link(page, link, row["date"])
        deadline = time.monotonic() + 15
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(150)
        page.wait_for_timeout(300)
    finally:
        page.unroute(PDF_ROUTE, hold)
    if len(held) != 1:
        raise NoFile("The direct download did not give exactly one PDF.")
    _note_unread(page, current)
    try:
        result = intake.evaluate(page, _FETCH_JS, held[0])
    except intake.TooLarge:
        raise
    except Exception:
        raise NoFile("The Postfach PDF request did not finish.") from None
    if not isinstance(result, dict) or not result.get("ok"):
        raise NoFile("The Postfach PDF service did not give the file.")
    return intake.decode(result.get("data"), validate=True)


def _press_link(page, link, date):
    """Press one row's own direct download link. A link the bank shows
    turned off was not pressed, so this one document is left (NoFile),
    recorded as failed and tried again on the next run, and the run goes
    on. A link something covers still stops the run."""
    try:
        pressing.click(page, link, css=LINK_CSS, words=_words(), step=TAKE_STEP,
                       what="the direct download link of the document of %s" % date)
    except pressing.TurnedOff:
        raise NoFile("The row's direct download link is turned off.") from None


# The PDF the held navigation was going to, asked for once from inside the
# tab, the way its own navigation would have asked, with no redirect
# followed. Only the bank's PDF service on its own host is asked, and only
# PDF bytes leave the page, never what the bank said.
_FETCH_JS = r"""
async (url) => {
  const origin = "https://www.sparkasse-pforzheim-calw.de";
  const target = new URL(url, origin);
  if (location.origin !== origin || target.origin !== origin || target.search || target.hash ||
      target.username || target.password ||
      !/^\/services\/download\.service\/sk-pforzheim-calw\/[A-Za-z0-9_-]+\/[^/]+\.pdf$/i.test(target.pathname))
    return {ok: false, error: "refused request outside the PDF service"};
  const timer = new AbortController();
  const limit = setTimeout(() => timer.abort(), 30000);
  try {
    const response = await fetch(target.href, {method: "GET", credentials: "same-origin",
      mode: "same-origin", redirect: "error", signal: timer.signal});
    if (!response.ok) return {ok: false, error: "PDF service returned HTTP " + response.status};
    const bytes = await ppRead(response);
    let binary = "";
    for (let n = 0; n < bytes.length; n += 32768) binary += String.fromCharCode(...bytes.subarray(n, n + 32768));
    return {ok: true, data: btoa(binary)};
  } catch (error) {
    if (ppRefused(error)) throw error;
    return {ok: false, error: "PDF request failed"};
  } finally { clearTimeout(limit); }
}
"""


def _note_unread(page, before):
    """Whether the row's unread mark changed with its download, to the log
    alone. Nobody has measured whether the bank marks a document read when
    its PDF is taken, and a change never stops the run."""
    try:
        seen, found = _look(page)
    except Exception:
        return
    if seen != "page":
        return
    after = [r for r in found["rows"] if r.get("identity") == before["identity"]]
    if len(after) == 1 and after[0]["unread"] != before["unread"]:
        log.info("a Postfach row's unread mark changed with its download")


def _list_answers(page, folder):
    """The folder's list, asked for afresh by its address, which proves the
    session still holds after a document gave no PDF. A sign-in page in its
    place raises SessionExpired, and a list that will not read ListStopped.
    The bank keeps the folder on the page it was turned to, so only that page
    is read. Reading every page again here would press through the whole
    Postfach for each such document."""
    if not is_safe_url(page.url or ""):
        raise SessionExpired("Open the signed-in Sparkasse Pforzheim Calw tab.")
    page.goto(BASE + FOLDERS[folder], wait_until="domcontentloaded", timeout=15000)
    return _settled(page)


def _pdf_path(url):
    parts = urlsplit(url)
    return (not parts.query and not parts.fragment and bool(re.fullmatch(
        r"/services/download\.service/sk-pforzheim-calw/[A-Za-z0-9_-]+/[^/]+\.pdf",
        parts.path, re.I)))


def classify(kind, title=""):
    text = str(kind or "") + " " + str(title or "")
    for category, pattern in (
        ("Tax Document", r"steuer|tax|freistellung|verlustbescheinigung|ertr[aä]gnis"),
        ("Credit Card Statement", r"kreditkarte|credit.?card|\bvisa\b"),
        ("Securities Document", r"depot|wertpapier|dividend|fonds|securit"),
        ("Statement", r"kontoausz|statement|tagesgeld|festgeld|zinsabrechnung|rechnungsabschluss"),
        ("Contract Information", r"vertrag|bedingung|vereinbarung|kontoer[öo]ffnung|contract"),
        ("Message", r"mitteilung|nachricht|information|message"),
    ):
        if re.search(pattern, text, re.I):
            return category
    return "Other Document"


def filed_category(row):
    """The category a listed row's document is recorded under. The row's
    own, except that one of no known kind whose subject says it is a
    statement is recorded as one (sparkassepc_docs._record_statement_doc),
    as DKB's filed_category reads it. Discover numbers the rows by it and a
    download finds its row by it, so the two read a row as the record holds
    it."""
    category = row.get("category") or classify(row.get("kind"), row.get("title"))
    title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip() or "Statement"
    if category == "Other Document" and re.search(r"statement|kontoauszug", title, re.I):
        return "Statement"
    return category


def parse_date(value):
    value = str(value or "").strip()
    for fmt, pattern in (("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}(?!\d)"),
                         ("%d.%m.%Y", r"^\d{2}\.\d{2}\.\d{4}(?!\d)"),
                         ("%Y%m%d", r"^\d{8}(?!\d)")):
        match = re.match(pattern, value)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def storage_categories():
    return ["Statement", "Credit Card Statement", "Securities Document", "Tax Document",
            "Contract Information", "Message", "Other Document"]


def collect_documents(page, keep=None, config=None):
    rows = listed_rows(page, config, fresh=True)
    return sorted((r for r in rows if keep is None or keep(r["date"][:4])),
                  key=lambda row: row["date"], reverse=True)


def undated():
    # An unreadable date stops this provider's whole listing.
    return 0


def resolve_item(page, title, date, account, occurrence=0, item_id="", *,
                 category, number_rows, twins=1, config=None):
    """DKB's identity matching, without falling back to an unlisted id,
    since the current page must still show the same document."""
    rows = listed_rows(page, config)
    numbers = number_rows(rows)
    alike = [i for i, row in enumerate(rows) if
             (row["title"], row["date"], row["account"], filed_category(row)) ==
             (title, date, account, category)]
    mine = [i for i in alike if numbers[i][0] == occurrence]
    if not mine:
        if item_id and any(row["item_id"] == item_id for row in rows):
            raise NotToldApart("Its stored id is now another document's.")
        raise NotToldApart("The list no longer shows this document.")
    if len(mine) != 1:
        raise NotToldApart("The list does not uniquely identify this document.")
    index = mine[0]
    row = rows[index]
    if not numbers[index][1] or (row["item_id"] != item_id and len(alike) != twins):
        raise NotToldApart("Documents alike cannot be safely matched.")
    return row


def download_document(page, title, date, out_path, occurrence=0, item_hint="",
                      client_hint="", account="", *, category, number_rows,
                      twins=1, config=None):
    """Save one document, and answer the id its bytes came from, or "" when
    the bank gave no PDF for it, which fails that document alone. Which row
    is its own is resolve_item's to say. A signed-out answer raises
    SessionExpired and a list that cannot be read again ListStopped, since
    both hold for every document after it."""
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins, config=config)
    try:
        data = _take_pdf(page, row, config)
        why = "" if data.startswith(b"%PDF-") else "not a PDF (%d bytes)" % len(data)
    except (SessionExpired, ListStopped):
        raise
    except Exception as e:
        # By its type and kind, since what an answer or an error says can
        # carry the bank's words. A stop at a press is no Exception and
        # goes on to the run (paperpull_core.pressing).
        why = "%s, %s" % (type(e).__name__, failure.error_kind(e))
    if why:
        log.warning("no PDF for one %s of %s: %s", category, date, why)
        # A sign-in page served in place of the PDF, or a redirect to one,
        # says nothing this app can tell from a file the bank will not give.
        # The list is the proof, so the folder's list is asked for again
        # here, and an answer as signed out (SessionExpired) or a list that
        # stops (ListStopped) ends the run with nothing recorded against this
        # document. Only a list that still answers makes this one document's
        # failure.
        _list_answers(page, row["folder"])
        return ""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return row["item_id"]
