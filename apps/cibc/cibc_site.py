"""CIBC's site, as far as this first shell knows it.

When the site changes, repair this file only.

STATUS, NOT BUILT (#204). This is the shell a tester signs in with and
Records in. It opens CIBC Online Banking's sign-on page in a browser profile
of its own, the person signs in there themselves, and Record and Diagnose
watch the tab they leave open. Which page lists statements, how a checking
or savings account, a credit card and a line of credit are told apart, and
how a statement's PDF arrives are not known, and nothing here guesses at
them. Discover and every download raise NotBuilt, which says to Record one
trip to a document, since a recording is what the real app is written from
(docs/testing-a-provider.md).

What this shell does know is how to tell a sign-in page, by its address or a
password field. The sign-in address the request names, www.cibconline.cibc.com,
hands over to CIBC Online Banking's own page, which draws the sign-on form at
#/signon. It knows no shape of a signed-in page, so it never says a session
is signed in. That waits for the recording.

SAFETY. A bank, with Interac e-Transfers, bill payments, transfers, checks
deposited by photo, money sent abroad, credit cards, lines of credit, loans
and investments.
  Strictly READ-ONLY, and in this shell nothing is pressed at all. No
  function here clicks, types, selects, submits a form or confirms a
  dialog. The one navigation is opening the sign-on page, in a tab this run
  opened itself, when no tab of the person's is on CIBC Online Banking. The
  guard below is what Record marks each control a person pressed against,
  and what the real build will hold every press to. Every host but
  cibconline.cibc.com and its subdomains is refused, cibc.com's public site
  among them.
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

log = logging.getLogger("cibc_docs.site")

# Every host this app will read from. Anything else is refused. The sign-on
# page and the banking pages are both on www.cibconline.cibc.com, a
# subdomain, so it is in. The public site, www.cibc.com, is not needed for a
# sign-in and is left out.
ALLOWED_HOSTS = ("cibconline.cibc.com",)

BASE = "https://www.cibconline.cibc.com"
URLS = {
    "home": BASE + "/",
    # login.bat opens this, the sign-in address the request names (#204).
    # It hands over to the banking page, which draws the sign-on form.
    "login": BASE + "/",
}

# Diagnose writes this down, so a survey file says it came from a shell.
NOT_MAPPED = ("CIBC is not built yet. This first build only opens "
              "the site for a sign-in, and Record and Diagnose.")


def not_built_words() -> str:
    """What Discover, Pilot, Run All and every download say instead of
    guessing, in the words of where the run is. Plain words, no address,
    nothing from a page."""
    return (
        "CIBC is not built yet, so this run lists and downloads "
        "nothing. This first build opens the site for you to sign in, and "
        f"nothing more. To help build it, sign in, then {after_sign_in(record=True)}, "
        "and click your way to one document the way you always do, then stop "
        "the recording. The recording.json it writes in this provider's "
        "Diagnostics folder is what the real app is built from. Read it "
        "through, then attach it to issue #204 on GitHub. Every run but the "
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
    """CIBC answered with a sign-in page instead of a document.
    Nothing in this shell raises it yet. The engine stops a run on it."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a Canadian bank, whose pages may be in English
# or French. Never move money, never pay, never send an Interac e-Transfer,
# never deposit a check, never buy or sell, never borrow, take a cash
# advance or raise a limit, never open, close, lock or replace anything,
# never order or ask for a copy, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # Money moving, English. "Transfer" with no boundary before it, so
    # "e-Transfer" is refused too.
    r"(transfer|\binterac\b|\bwire\b|\bpay\b|\bpays\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"\bpayees?\b|\brecipients?\b|\bdeposit|withdraw|\bsend\b|request\s+money|move\s+money|"
    r"\bremit|foreign\s+(currency|exchange)|\bconvert|\bstop\b|"
    # Trading and investing, English
    r"\bbuy\b|\bsell\b|\btrade\b|\btrading\b|\binvest\s+now\b|"
    # Credit, English. A line of credit is one of the documents here, so
    # "Line of credit statement" passes, while borrowing, a cash advance, a
    # limit and an installment plan never do.
    r"cash\s+advance|credit\s+limit|limit\s+increase|"
    r"increase\s+(my\s+|your\s+|the\s+)?(limit|credit)|\bborrow|"
    r"\binstall?ments?\b|pay\s+over\s+time|\bpace\s+it\b|\bredeem|\brewards?\b|\bpoints\b|"
    r"\boffers?\b|\bdeals?\b|\bupgrade|\bapply\b|\bapplication|"
    # Opening anything but a document, English. "Open", "View" alone are a
    # document's own button, and beside an account's word they need a
    # statement or a document after it.
    r"\bopen\b[\w\s-]{0,30}?\b(accounts?|cards?|lines?\s+of\s+credit|loans?|overdraft|"
    r"savings|investments?|gics?|tfsa|rrsp|resp|rrif|fhsa)\b"
    r"(?!\s+(accounts?\s+)?(statements?|documents?))|"
    r"\bget\s+(a\s+|an\s+|the\s+|your\s+)?(new\s+)?(card|account|loan|line\s+of\s+credit|"
    r"mortgage|quote)\b|"
    r"\bclose\s+(my\s+|the\s+|this\s+|an?\s+)?(account|card|line)|"
    # Ordering, requesting, signing and uploading, and how statements
    # arrive, English. A paper statement or a copy can carry a fee, and a
    # switch to or from eStatements changes how they arrive.
    r"\border\b|\brequest|\bupload|\bsign\b|\be-?sign|\bpaper\b|\bpaperless|\bcop(y|ies)\b|"
    r"\bduplicate|\breprint|\bswitch\s+to\b|delivery\s+(preference|option)|"
    # Cards, the account and the person's own data, English
    r"\block\b|\bunlock|\bfreeze|\bunfreeze|\breplac|\bactivat|\bpin\b|\blost\b|\bstolen\b|"
    r"\bfraud\b|\bdispute|travel\s+(notice|notification|plans?)|\balerts?\b|"
    r"\bnotifications?\b|\benrol|\bregister|\bnickname|\bbeneficiar|\bauthori[sz]|"
    r"\bpassword|\bpasscode|\busername|\bprofile\b|\bsettings?\b|\bpreferences?\b|"
    r"\baddress\b|\be-?mail\b|\bphone\b|contact\s+(info|information|details)|\bchat\b|"
    # Word boundaries on both sides of the verb stems, so "Credit" stays
    # allowed.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bmodif|"
    r"\bset\s+up\b|\bdelet|\bremov(e|es|ed|ing|al)\b|\bcancel|\bsubmit|\bconfirm\b|"
    r"\baccept\b|\bagree\b|\bmark\s+as\s+read\b|\barchive\b|"
    r"log\s*out|logout|log\s*off|sign\s*out|sign\s*off|"
    # Money moving, trading and credit, French
    r"virement|\bvirer\b|transf[ée]r|\bpa(yer|yez|iements?)\b|\bfactures?\b|\bd[ée]poser|"
    r"\bretrait|\bretirer|\benvoy|\bdemand|\bacheter|\bachat|\bvendre|\bvente\b|"
    r"\bn[ée]goci|avance\s+de\s+fonds|limite\s+de\s+cr[ée]dit|\bemprunt|"
    r"\bversements?\b|\br[ée]compens|\boffres?\b|"
    # Paying a balance, switching to or enrolling in eStatements, managing
    # them, adding a payee and depositing, French, as the English above.
    r"\br[ée]gl(er|ez)\b|\br[éè]glements?\b|\brembours|\bacquitt|"
    r"\bpasser\s+aux?\b|\badh[ée]r|\bopt(er|ez)\b|\babonn|\brecevoir|\bg[ée]r(er|ez)\b|"
    r"\bajout(er|ez)\b|b[ée]n[ée]ficiaire|\bd[ée]p[oô]ts?\b|"
    # Opening and closing, ordering, signing, cards and the person's own
    # data, French. "Ouvrir" alone is a document's own button.
    r"\bouvrir\s+(un|une|mon|ma|votre)\s+(autre\s+)?(nouve\w+\s+)?"
    r"(comptes?|cartes?|marges?|pr[eê]ts?|placements?|cpg|celi|reer|reee|ferr|celiapp)\b|"
    r"\bfermer|\bcommand|\bt[ée]l[ée]vers|\bsign(er|ez|ature)|\bpapier|\bcopies?\b|"
    r"\bverrouill|d[ée]verrouill|\bbloquer|d[ée]bloquer|\bremplac|\bactiver|"
    r"\bperdue?s?\b|\bvol[ée]e?s?\b|\bfraude|\bcontest|\balertes?\b|avis\s+de\s+voyage|"
    r"\binscri|mot\s+de\s+passe|\bprofil\b|\bparam[èe]tres|\bpr[ée]f[ée]rences|"
    r"\badresse\b|\bcourriel|\bt[ée]l[ée]phone|\bmodifi|\bchanger|\bsupprim|\bannul|"
    r"\bsoumettre|\bconfirmer|\baccepter|d[ée]connex|fermeture\s+de\s+session|\bquitter)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    # "Open", "View", "Ouvrir", "Afficher" and "Voir" alone are a
    # document's own button. Beside any other word they need a document's
    # word too, since "Open a TFSA" opens an account.
    r"(download|\bpdf\b|^\s*view\s*$|^\s*open\s*$|"
    r"statements?\b|documents?\b|\btax\b|\bt[45]\w{0,4}\b|"
    r"(show|load|see|view)\s+(more|all|older)|"
    r"t[ée]l[ée]charg|relev[ée]s?\b|feuillets?\b|\bimp[oô]ts?\b|"
    r"^\s*(ouvrir|afficher|voir)\s*$|(afficher|voir|charger)\s+plus)", re.I)


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
    # English
    "one-time code", "one time code", "one-time verification code", "enter the code",
    "verification code", "we sent a code", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "you have been signed off",
    "too many attempts",
    # French
    "code à usage unique", "code de vérification", "entrez le code",
    "votre session a expiré", "session expirée", "trop de tentatives",
]

# Lowercased address fragments of a sign-in page. The sign-on form is drawn
# at #/signon on the banking page the request's address hands over to. The
# address and the banking page with no route yet are a loading page that
# moves on by itself, and are left alone. The password field below notices
# any sign-in form this misses.
LOGIN_URL_MARKERS = ["#/signon"]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic", "http error 429",
                      "trop de demandes", "réessayer plus tard", "réessayez plus tard"]


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
    """CIBC Online Banking's sign-on page, opened in a tab this run opened
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
                      else "(not on cibconline.cibc.com)")
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
