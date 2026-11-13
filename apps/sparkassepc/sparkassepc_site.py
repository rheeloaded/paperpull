"""Read the Sparkasse Pforzheim Calw Postfach and its direct PDFs."""
from __future__ import annotations

from hashlib import sha256
import logging
import time
from datetime import datetime
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


from paperpull_core import failure
from paperpull_core import intake, redirects, tabs
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows, join

log = logging.getLogger("sparkassepc_docs.site")

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

# The signed-in Postfach contains a hidden password field in the portal's
# sign-in UI. The recorder and the session check count the same visible fields.
PASSWORD_FIELD = "input[type='password']:visible"

# Authentication and sign-out pages are never a document list.
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
        if page.locator(PASSWORD_FIELD).count() > 0:
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
        out["password_fields"] = page.locator(PASSWORD_FIELD).count()
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


def _folder(page, folder):
    """Open the exact folder linked by the Postfach navigation."""
    if not is_safe_url(page.url) or looks_signed_out(page):
        raise SessionExpired("Sign in to Sparkasse Pforzheim Calw again.")
    if urlsplit(page.url).path == FOLDERS[folder] and page.locator("form.postfach").count():
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
    page.wait_for_url(lambda url: is_safe_url(url) and urlsplit(url).path == FOLDERS[folder],
                      timeout=10000)
    page.locator("form.postfach").wait_for(timeout=8000)


def goto_documents(page):
    try:
        url = page.url or "about:blank"
        if not (url == "about:blank" and tabs.is_own(page)) and looks_signed_out(page):
            return False
        if urlsplit(url).path not in FOLDERS.values():
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=15000)
        return not looks_signed_out(page) and page.locator("form.postfach").count() == 1
    except Exception:
        return False


def ensure_statements(page):
    return goto_documents(page)


def answers_its_list(page):
    return bool(_read_page(page))


_LIST_JS = r"""
() => {
  const form = document.querySelector("form.postfach");
  if (!form) return null;
  const pager = form.querySelector(".bpager");
  const active = pager?.querySelector(".active input");
  const next = pager?.querySelector(".next input:enabled");
  const period = form.querySelector(".select-time select");
  const search = form.querySelector("input.mkp-input-with-icon");
  const rows = [...form.querySelectorAll("tr.postbox-message-row")].map((row, index) => {
    const link = row.querySelector("a.postbox-message-direct-download");
    const title = link?.getAttribute("title") || link?.textContent.trim();
    const identity = row.querySelector('input[type="checkbox"]')?.value;
    return {index, title, identity, date: row.cells[3]?.textContent.trim(),
            downloadable: Boolean(link), unread: row.classList.contains("tablerowmarked")};
  });
  return {rows, number: Number(active?.value || 1), next: Number(next?.value || 0),
          filtered: Boolean(search?.value.trim() || (period &&
              period.selectedOptions[0]?.text.trim() !== "Gesamtzeitraum")),
          failed: Boolean(form.querySelector(".failure-msg, .error-msg"))};
}
"""


def _read_page(page):
    if not is_safe_url(page.url) or looks_signed_out(page):
        raise SessionExpired("Sign in to Sparkasse Pforzheim Calw again.")
    if urlsplit(page.url).path not in FOLDERS.values():
        raise ListStopped("The browser left the Postfach.")
    result = page.evaluate(_LIST_JS)
    if not result or result.get("failed") or not isinstance(result.get("rows"), list):
        raise ListStopped("The Postfach list is missing.")
    if result["filtered"]:
        raise ListStopped("Clear the Postfach search and select Gesamtzeitraum before running.")
    return result


_PAGE_FORM = r"""
(target) => {
  const form = document.querySelector("form.postfach");
  const pager = form?.querySelector(".bpager .pagerbuttons");
  const controls = [...(pager?.querySelectorAll('input[type="submit"]:enabled') || [])];
  const selected = controls.filter(input => input.value === String(target));
  if (selected.length !== 1 || selected[0].form !== form ||
      form.querySelector('input[type="checkbox"]:checked') ||
      form.method !== "post" || form.enctype !== "application/x-www-form-urlencoded")
    return null;
  return {action: form.action, body: new URLSearchParams(new FormData(form, selected[0])).toString()};
}
"""


def _turn(page, target):
    """Submit only the observed numeric pager action of the Postfach form."""
    path = urlsplit(page.url).path
    if path not in FOLDERS.values() or not is_safe_url(page.url) or not is_safe_control(str(target)):
        raise ListStopped("The Postfach page control is outside the mailbox.")
    form = page.evaluate(_PAGE_FORM, target)
    if not form:
        raise ListStopped("The Postfach page control is missing or ambiguous. Clear any selections.")
    parts = urlsplit(form["action"])
    if not is_safe_url(form["action"]) or parts.path != path or parts.fragment:
        raise ListStopped("The Postfach paging address changed.")
    endpoint = urlunsplit(parts._replace(path=path.removesuffix(".html") + ".ajstep.html"))
    destination = BASE + path.removesuffix(".html") + ".ajstep.html"
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "X-Requested-With": "XMLHttpRequest"}
    answer = page.request.post(endpoint, data=form["body"], max_redirects=0,
                               timeout=12000, headers=headers)
    try:
        answer = redirects.follow_listing(page.request, answer, destination, is_safe_url,
                                          timeout=12000, headers=headers)
        if not answer.ok or answer.url != destination:
            raise ListStopped("The Postfach did not return the requested page.")
    finally:
        answer.dispose()
    page.goto(BASE + path, wait_until="domcontentloaded", timeout=15000)
    result = _read_page(page)
    if result["number"] != target:
        raise ListStopped("The Postfach did not reach the requested page.")
    return result


def _rewind(page, result):
    while result["number"] > 1:
        # Use the numbered first page when the pager currently offers it.
        first = page.locator('form.postfach .bpager .pagerbuttons input[type="submit"][value="1"]:enabled:visible')
        result = _turn(page, 1 if first.count() == 1 else result["number"] - 1)
    return result


_cache = None
_summary = {}


def _collect(page):
    global _summary
    rows = []
    skipped = 0
    for folder in FOLDERS:
        _folder(page, folder)
        result = _rewind(page, _read_page(page))
        while True:
            number = result["number"]
            if number < 1 or number > 500:
                raise ListStopped("The Postfach reached the page limit.")
            for row in result["rows"]:
                if not row["downloadable"]:
                    skipped += 1
                    continue
                row.update(folder=folder, number=number)
                rows.append(_normalize(row))
            target = result["next"]
            if not target:
                break
            if target != number + 1:
                raise ListStopped("The Postfach page sequence changed.")
            result = _turn(page, target)
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
            _cache = (page, _collect(page))
        except (SessionExpired, ListStopped):
            raise
        except Exception:
            raise ListStopped("The Postfach listing did not finish.") from None
    wanted = set((config or {}).get("document_types") or storage_categories())
    return [dict(row) for row in _cache[1] if row["category"] in wanted]


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
    identity = sha256(token.encode("utf-8")).hexdigest()
    return {"title": title, "date": date, "account": "Konto " + tail if tail else "",
            "category": classify("", title), "item_id": identity, "client_id": "",
            "href": BASE + FOLDERS[row["folder"]], "folder": row["folder"],
            "number": row["number"], "index": row["index"]}


def _take_pdf(page, row):
    _folder(page, row["folder"])
    listed = _read_page(page)
    target = row["number"]
    if target < listed["number"]:
        listed = _rewind(page, listed)
    while listed["number"] != target:
        listed = _turn(page, listed["number"] + 1)
    page.bring_to_front()
    page.wait_for_load_state("load", timeout=15000)
    i = row["index"]
    if i >= len(listed["rows"]):
        raise ListStopped("The document moved since the Postfach was listed.")
    current = listed["rows"][i]
    if not current["downloadable"]:
        raise ListStopped("The listed document no longer has its download link.")
    current.update(folder=row["folder"], number=target)
    matching = _normalize(current)
    if any(matching[k] != row[k] for k in ("item_id", "title", "date", "account", "category")):
        raise ListStopped("The document moved since the Postfach was listed.")
    link = page.locator("form.postfach tr.postbox-message-row").nth(i).locator(
        "a.postbox-message-direct-download:visible")
    if link.count() != 1 or not is_safe_control(link.get_attribute("title")):
        raise NoFile("The direct download control changed.")
    href = join(page.url, link.get_attribute("href") or "")
    if not is_safe_url(href) or urlsplit(href).path != FOLDERS[row["folder"]]:
        raise NoFile("The direct download link is outside the Postfach.")

    # The portal prepares a download, then navigates to its PDF service.
    # Hold that request with a 204 so the tab stays in the Postfach.
    downloads = []
    route_pattern = "**/services/download.service/**"

    def hold_pdf(route):
        if is_safe_url(route.request.url) and _pdf_path(route.request.url) and route.request.method == "GET":
            downloads.append(route.request.url)
        route.fulfill(status=204)

    page.route(route_pattern, hold_pdf)
    try:
        link.click(timeout=8000, no_wait_after=True)
        deadline = time.monotonic() + 15
        while not downloads and time.monotonic() < deadline:
            page.wait_for_timeout(150)
    finally:
        page.unroute(route_pattern, hold_pdf)
    if len(downloads) != 1:
        raise NoFile("The direct download did not give exactly one PDF.")
    after = _read_page(page)
    if (after["number"] != target or i >= len(after["rows"]) or
            after["rows"][i]["unread"] != current["unread"] or
            after["rows"][i]["identity"] != current["identity"] or
            after["rows"][i]["title"] != current["title"]):
        raise ListStopped("The Postfach row changed during the download.")
    response = page.request.get(downloads[0], max_redirects=0, timeout=30000)
    if not response.ok:
        response.dispose()
        raise NoFile("The Postfach PDF service did not give the file.")
    try:
        return intake.body(response)
    finally:
        response.dispose()


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
    return row.get("category") or classify(row.get("kind"), row.get("title"))


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
        data = _take_pdf(page, row)
        why = "" if data.startswith(b"%PDF-") else "not a PDF (%d bytes)" % len(data)
    except (SessionExpired, ListStopped):
        raise
    except Exception as e:
        # By its type and kind, since what an answer or an error says can
        # carry the bank's words.
        why = "%s, %s" % (type(e).__name__, failure.error_kind(e))
    if why:
        log.warning("no PDF for one %s of %s: %s", category, date, why)
        # A sign-in page served in place of the PDF, or a redirect to one,
        # says nothing this app can tell from a file the bank will not give.
        # The list is the proof, so it is read again here, and an answer as
        # signed out (SessionExpired) or a list that stops (ListStopped) ends
        # the run with nothing recorded against this document. Only a list
        # that still answers makes this one document's failure.
        listed_rows(page, config, fresh=True)
        return ""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return row["item_id"]
