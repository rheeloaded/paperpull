"""Scalable Capital's site, as far as this first shell knows it.

When the site changes, repair this file only.

STATUS, NOT BUILT (#170). This is the shell a tester signs in with and
Records in. It opens Scalable Capital's sign-in page in a browser profile of
its own, the person signs in there themselves, and Record and Diagnose watch
the tab they leave open. Which page lists documents, how a child's
sub-account is reached from the same sign-in, and how a document's PDF
arrives are not known, and nothing here guesses at them. Discover and every
download raise NotBuilt, which says to Record one trip to a document, since a
recording is what the real app is written from (docs/testing-a-provider.md).

What this shell does know is how to tell a sign-in page, by its address or a
password field. The sign-in address the request names, /secure-login on
de.scalable.capital, hands over to secure.scalable.capital, where the form
is. It knows no shape of a signed-in page, so it never says a session is
signed in. That waits for the recording.

SAFETY. A broker, with buying and selling, savings plans, deposits and
withdrawals, a cash account and a paid subscription.
  Strictly READ-ONLY, and in this shell nothing is pressed at all. No
  function here clicks, types, selects, submits a form or confirms a
  dialog. The one navigation is opening the sign-in page, in a tab this run
  opened itself, when no tab of the person's is on Scalable Capital's site.
  The guard below is what Record marks each control a person pressed
  against, and what the real build will hold every press to. Every host but
  scalable.capital and its subdomains is refused.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.run_reporting import after_sign_in
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("scalable_docs.site")

# Every host this app will read from. Anything else is refused. The sign-in
# form is on secure.scalable.capital, a subdomain, so it is in.
ALLOWED_HOSTS = ("scalable.capital",)

BASE = "https://de.scalable.capital"
URLS = {
    "home": BASE + "/",
    # login.bat opens this, the sign-in address the request names (#170).
    "login": BASE + "/secure-login",
}

# Diagnose writes this down, so a survey file says it came from a shell.
NOT_MAPPED = ("Scalable Capital is not built yet. This first build only opens "
              "the site for a sign-in, and Record and Diagnose.")


def not_built_words() -> str:
    """What Discover, Pilot, Run All and every download say instead of
    guessing, in the words of where the run is. Plain words, no address,
    nothing from a page."""
    return (
        "Scalable Capital is not built yet, so this run lists and downloads "
        "nothing. This first build opens the site for you to sign in, and "
        f"nothing more. To help build it, sign in, then {after_sign_in(record=True)}, "
        "and click your way to one document the way you always do, then stop "
        "the recording. The recording.json it writes in this provider's "
        "Diagnostics folder is what the real app is built from. Read it "
        "through, then attach it to issue #170 on GitHub. Every run but the "
        "sign-in, Record and the support report stops until it is built.")


# The words as a terminal reads them, for anything that wants them without
# asking where the run is.
NOT_BUILT = not_built_words()


class NotBuilt(RuntimeError):
    """Asked for a list or a document this first build cannot read."""

    def __init__(self, what: str = ""):
        super().__init__(not_built_words())
        self.what = what


class SessionExpired(RuntimeError):
    """Scalable Capital answered with a sign-in page instead of a document.
    Nothing in this shell raises it yet. The engine stops a run on it."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a German broker, whose pages may be in German
# or English. Never buy, sell or place an order, never start, change or
# pause a savings plan, never move money in or out, never take out a loan,
# never sign up for or change a subscription, never open an account for
# anyone, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # Money moving, German. "Übertrag" is a depot moved to another bank.
    r"((ue|ü)berweis|(ue|ü)bertrag|\bechtzeit|dauerauftr|lastschrift|\bumbuch|"
    r"\bsenden\b|\bzahl(en|ung)\b|\bbezahl|geld\s+(senden|anfordern)|\bauszahl|"
    r"\beinzahl|\babheb|\bempf(ae|ä)nger|\bzur(ue|ü)ckbuch|widersprech|widerspruch|"
    # Trading, German. Kaufen and Verkaufen are what a trade button says.
    # "Kauf" alone is in the name of every Wertpapierabrechnung, so only a
    # label that is nothing but that word is refused.
    r"\bkaufen\b|\bverkaufen\b|^\s*(ver)?kauf\s*$|\border\b|\bhandel|\bzeichn|"
    r"\blimit|\bstop\b|\bkurs\s*alarm|\bpreis\s*alarm|\bsparplan\s+"
    r"(anlegen|einrichten|erstellen|(ae|ä)ndern|pausieren|aussetzen|l(oe|ö)schen)|"
    # A loan of any kind, Wertpapierkredit included, while "Kreditkarte"
    # passes.
    r"kredit\b|\bhebel|\bderivat|"
    # The subscription, which costs money.
    r"\bupgrade|\bdowngrade|\babo\b|\babonn|\bmitgliedschaft|\btarif|\bprime\b|"
    # Accounts, children's included, and the person's own data, German.
    r"\ber(oe|ö)ffn|\bbeantrag|\bantrag\b|\bk(ue|ü)ndig|\bsperr|entsperr|\bpin\b|"
    r"\bfreigeb|\bfreigabe|\bbest(ae|ä)tig|\bzustimm|\bakzeptier|"
    r"\b(ae|ä)nder|\bbearbeit|\bl(oe|ö)sch|\bentfern|\barchivier|\beinricht|"
    r"\baktivier|deaktivier|\babschlie(ss|ß)|\bhinzuf(ue|ü)g|\banlegen\b|\beinladen|"
    r"als\s+gelesen|gelesen\s+markier|\bfreistellungsauftrag\s+(erteilen|anlegen|(ae|ä)ndern)|"
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
    r"\btrade\b|savings\s+plan|\bsubscri|\binvite|"
    r"\badd\s+(a\s+)?(child|account|depot|portfolio)|"
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
    r"postfach|mailbox|\binbox\b|dokument|document|kontoauszug|ausz(ue|ü)ge|"
    r"abrechnung|depotauszug|steuer|\btax\b|ertr(ae|ä)gnis|verlustbescheinigung|"
    r"kosteninformation|mitteilung|statement|\bconfirmations?\b|\barchiv\b|"
    r"mehr\s+(anzeigen|laden)|show\s+more|load\s+more)", re.I)


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
    "bestätigungscode", "sicherheitscode", "code eingeben", "gib den code ein",
    "geben sie den code ein", "zu viele versuche", "sitzung ist abgelaufen",
    "sitzung abgelaufen", "du wurdest abgemeldet", "sie wurden abgemeldet",
    # English
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out",
]

# Lowercased address fragments of a sign-in page. The sign-in address the
# request names, and the host it hands over to, where the form asks for the
# e-mail address first and the password on a page of its own after it. The
# password field below notices any sign-in form these miss.
LOGIN_URL_MARKERS = ["/secure-login", "//secure.scalable.capital/"]

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
    if not url or any(m in url for m in LOGIN_URL_MARKERS):
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


def open_sign_in(page) -> bool:
    """Scalable Capital's sign-in page, opened in a tab this run opened
    itself. Never in a tab of the person's, which is left where they put it.
    True when the tab ended on the site."""
    if not is_safe_url(URLS["login"]):
        return False
    try:
        page.goto(URLS["login"], wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log.info("sign-in page failed: %s", e)
    try:
        return is_safe_url(page.url or "")
    except Exception:
        return False


# -- what this first build cannot do yet ---------------------------------------

def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every document the accounts list. Not built, so this refuses rather
    than read a page it does not know."""
    raise NotBuilt("the list of documents")


def download_document(page, *args, **kwargs) -> bool:
    """Save one document. Not built, so this refuses rather than press or
    fetch anything."""
    raise NotBuilt("a document's PDF")


# ---------------------------------------------------------------------------
# Diagnose survey. Read-only and on the page the person left open. Nothing
# is followed, pressed or downloaded, no screenshot is taken, and every word
# goes through the redactor and then the word list that writes the file.
# ---------------------------------------------------------------------------
def _page_summary(page) -> dict:
    out = {"url": "", "title": ""}
    try:
        url = page.url or ""
        out["on_site"] = is_safe_url(url)
        # The path only. A query string or a fragment can carry a session
        # or an account's id.
        out["url"] = (redact(re.split(r"[?#]", url, maxsplit=1)[0]) if out["on_site"]
                      else "(not on scalable.capital)")
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
    report = {"pages": [], "responses": [], "mapped": False}
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:
        pass
    report["pages"].append(_page_summary(page))
    return report
