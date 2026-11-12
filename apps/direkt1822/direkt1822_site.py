"""1822direkt Postbox lists and direct PDFs through its own browser API.

Mapped from the user's structural capture and the public Angular client.
Only benutzerInfo, Postbox list endpoints and direct PDF downloads are used.
No controls, transactions or account settings are activated. Conversation
reads require open_conversations=true because the bank marks them read.
Tokens are prepared inside the signed-in page and never returned to Python.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.run_reporting import after_sign_in
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("direkt1822_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("www.1822direkt-banking.de",)

BASE = "https://www.1822direkt-banking.de"
URLS = {
    "home": BASE + "/ng-banking/",
    "documents": BASE + "/ng-banking/banking/postbox",
    # login.bat opens this, the sign-in address the request names (#174).
    "login": BASE + "/ng-banking/login/eingabe",
}

class SessionExpired(RuntimeError):
    """The API requires the account holder to sign in again."""


class ListStopped(RuntimeError):
    """The Postbox list could not be read whole."""


class NotToldApart(RuntimeError):
    """Documents alike cannot be uniquely matched."""


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
    r"hinterleg|freischalt|\bbeauftrag|\bper\s+post\b|\bpapier|duplikat|\bkopie|"
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
    return bool(SAFE_DOC_CONTROL_RE.search(name))


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

# Authentication routes are never treated as a document list.
LOGIN_URL_MARKERS = ["/login", "/logout", "/anmeldung", "/abmeldung"]

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
                      else "(not on www.1822direkt-banking.de)")
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
        # Those the page draws, which is what looks_signed_out counts (#174).
        out["visible_password_fields"] = page.locator("input[type='password']").count()
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
    return report


_API_JS = Path(__file__).with_name("direkt1822_api.js").read_text(encoding="utf-8")
_cache = None
_summary = {}


def _execute(page, operation, **values):
    if not is_safe_url(page.url or ""):
        raise SessionExpired("Open the signed-in 1822direkt tab.")
    try:
        result = page.evaluate(_API_JS, {"op": operation, **values})
    except Exception:
        raise ListStopped("the in-page document request did not finish") from None
    if not isinstance(result, dict):
        raise ListStopped("the document API answered in an unexpected shape")
    if result.get("expired"):
        raise SessionExpired("Sign in to 1822direkt again.")
    if not result.get("ok"):
        raise ListStopped(result.get("error") or "the document API did not answer")
    return result


def goto_documents(page):
    """Reuse the banking tab; the list API, not its URL, proves sign-in.

    Reopening the SPA's deep link can take it through an OAuth callback.
    Reading from the existing tab avoids both that race and discarding the
    session the person just opened. A tab of the run's own may navigate.
    """
    if is_safe_url(page.url or ""):
        # A login just completed by the account holder can still be moving
        # through the authentication route when the CLI attaches.
        for attempt in range(11):
            if not looks_signed_out(page):
                return True
            if attempt < 10:
                page.wait_for_timeout(500)
        return False
    try:
        if (page.url or "").split("?", 1)[0].rstrip("/") != URLS["documents"]:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        return not looks_signed_out(page)
    except Exception:
        return False


def ensure_statements(page):
    return goto_documents(page)


def answers_its_list(page):
    listed_rows(page, fresh=True)
    return True


def classify(kind, title=""):
    categories = {
        "MEGA": "Statement", "MEKA": "Credit Card Statement",
        "EWOM": "Securities Document", "EWJA": "Securities Document",
        "JSTB": "Tax Document", "ADV": "Other Document", "INFO_ADV": "Other Document",
        "ETC": "Message", "INFO": "Message", "MITT": "Message", "BRIEF": "Message",
        "MITT_BRIEF": "Message", "IPAI": "Message",
    }
    if kind in categories:
        return categories[kind]
    text = str(kind or "") + " " + str(title or "")
    for category, pattern in (
        ("Tax Document", r"steuer|tax|freistellung|verlustbescheinigung"),
        ("Credit Card Statement", r"kreditkarte|credit.?card"),
        ("Securities Document", r"depot|wertpapier|dividend|fonds"),
        ("Statement", r"kontoausz|statement|tagesgeld|festgeld|rechnungsabschluss"),
        ("Contract Information", r"vertrag|bedingung|vereinbarung|contract"),
        ("Message", r"mitteilung|nachricht|information|message"),
    ):
        if re.search(pattern, text, re.I):
            return category
    return "Other Document"


def filed_category(row):
    return row.get("category") or classify(row.get("kind"), row.get("title"))


def parse_date(value):
    value = str(value or "").strip()
    for fmt, length in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(value[:length], fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _normalise(row):
    date = parse_date(row.get("date"))
    if not date or not row.get("title") or not row.get("item_id"):
        raise ListStopped("a listed document has no readable date, title or identity")
    account = re.sub(r"\W", "", str(row.get("account") or ""))[-4:]
    return {"title": re.sub(r"\s+", " ", row["title"]).strip(), "date": date,
            "account": "Konto " + account if account else "",
            "category": filed_category(row), "item_id": row["item_id"],
            "client_id": "", "href": URLS["documents"]}


def listed_rows(page, config=None, fresh=False):
    global _cache, _summary
    try:
        present = page.evaluate("Boolean(window.__paperpull1822PostboxV1?.items)")
    except Exception:
        present = False
    if (fresh or not _cache or _cache[0] is not page or not present
            or time.monotonic() - _cache[1] > 120
            or _cache[3] != (bool((config or {}).get("include_trash", True)), bool((config or {}).get("open_conversations", False)))):
        result = _execute(page, "collect", include_trash=(config or {}).get("include_trash", True),
                          open_conversations=(config or {}).get("open_conversations", False))
        raw = result.get("rows")
        if not isinstance(raw, list):
            raise ListStopped("the document list could not be read")
        rows = [_normalise(row) for row in raw]
        if len({r["item_id"] for r in rows}) != len(rows):
            raise ListStopped("the document list repeats an identity")
        _summary = result.get("summary") or {}
        _cache = (page, time.monotonic(), rows, (bool((config or {}).get("include_trash", True)), bool((config or {}).get("open_conversations", False))))
    wanted = set((config or {}).get("document_types") or storage_categories())
    return [dict(row) for row in _cache[2] if row["category"] in wanted]


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
    """DKB's identity matching, without falling back to an unlisted id."""
    rows = listed_rows(page, config)
    numbers = number_rows(rows)
    alike = [i for i, row in enumerate(rows) if
             (row["title"], row["date"], row["account"], filed_category(row)) ==
             (title, date, account, category)]
    mine = [i for i in alike if numbers[i][0] == occurrence]
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
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins, config=config)
    result = _execute(page, "download", id=row["item_id"])
    try:
        data = base64.b64decode(result["data"], validate=True)
    except (ValueError, KeyError):
        return ""
    if not data.startswith(b"%PDF-"):
        return ""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return row["item_id"]
