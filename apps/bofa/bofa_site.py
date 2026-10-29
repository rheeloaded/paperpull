"""Bank of America's site. When the site changes, repair this file only.

STATUS, built 2026-10-25 from two recordings by the tester on #121, one trip
to a checking statement and one to a credit card statement. Its first run
on an account (2026-10-26) listed 388 statements of five accounts and saved
none, for want of the Statements heading below, so NOT YET PROVEN on an
account. Every part below that a recording could not show is found
on the page at run time, and anything that does not fit what the
recordings showed stops the run rather than being guessed at.

HOW THE STATEMENTS PAGE WORKS, as the recordings showed it

  Statements & Documents is a page on secure.bankofamerica.com whose path
  ends in "stmts-docs", or for a second tester (#121, 2026-10-28) the
  same page at /statements-documents/home/. It fills its list from one
  call of its own.

    list   POST https://secure.bankofamerica.com/<three words>/statements/v1/<word>Documents
           body {<account key>, docCategoryId, year, lang}
           ->  {documentList: [{docId, docTypeId, docDisplayName, docCategory,
                                docCategoryId, date, dateString,
                                accountDisplayName, <account key>, ...}],
                accountList: [{accountDisplayName, productCode, <account key>,
                               selected, ...}],
                documentCategoryList: [{docCategoryName, docCategoryId}],
                yearList: ["2026", ...], status, errorInfo}

  One account, one category and one year per call. Checking, savings and
  cards are all in accountList, so one page lists every account's
  statements. A statement's row has a "Download PDF for <month> Statement
  for <account>" link whose address opens the PDF in a new tab, and the
  file is named eStmt_<date>.pdf.

  The recordings write every word off the page as its shape, so the three
  words of the list's address, the account key's name and the PDF link's
  address are not in them. So the app learns them from the page itself.
  It reloads the statements page the person left open, keeps the list call
  the page makes (its address, the body's names and the headers it sent),
  and reads the PDF links the page draws. A link's address is learned as a
  form, the address with each of its row's own values in it marked, and is
  taken only when every link the page drew comes out of the same form, from
  the rows of every list the page answered while it was heard. Each other
  statement's PDF is asked for at its own row's address in that form, from
  inside the page with the page's own session.

  The page draws its list under a heading of each category, and a reload
  leaves the Statements heading shut, with no row and so no link drawn
  under it (the first real run on #121, 2026-10-26). Both recordings
  pressed that heading first, and the page asked its list again and drew
  the rows. So when a statement is to be downloaded and no Download PDF
  link shows after the reload, the one button whose whole name is
  Statements and which says it is shut is pressed, once. The list it asks
  for is waited for, and the links are matched to the newest answer's rows
  first, the ones they were drawn from. Login and Discover only list, and
  press nothing.

  The second real run (2026-10-27) met a Download PDF link whose address
  was "#" or nothing, with no statement's id in it or in a data- field, so
  a script of the page's own opens the PDF. When every link the page drew
  is like that, one of them is pressed, once a run, and the call it makes
  for its PDF is heard, at the browser context so a tab it opens is heard
  too. That call has to be one GET or one POST of JSON or a form, on the
  bank's site, naming no change, and hold exactly one listed statement's
  docId, and it is learned as a form the way a link's address is. The PDF
  the press brings is never kept. A download it starts is cancelled and
  deleted and a tab it opens closed. The form is asked once more for the
  statement pressed, from inside the page, and kept only when that answers
  with a PDF. Each statement's PDF is then asked with its own row's call.

  IDENTITY is the account, the date and the title, with the docId as a
  hint (paperpull_core.keys.told_apart numbers two of one day and one
  account name). A PDF is filed only when its text names its own row
  better than any it could be taken for (paperpull_core.identity), and a
  file the bank names for another day than its row is never filed.

SAFETY. A bank, with checking, savings, credit cards, Zelle, transfers
and bill pay.
  Strictly READ-ONLY. Two presses, each through paperpull_core.pressing,
  which stops the run when anything is over the control. The Statements
  heading of the statements page, when it is shut, the page shows no
  Download PDF link and a statement is to be downloaded (or Diagnose
  surveys the page), through is_statements_heading (the guard below plus
  its whole name). And one statement's Download PDF link, once a run, when
  a statement is to be downloaded and every link's address is a script,
  through is_pdf_link (the guard below on its words beside the bank's own
  names for the statements and accounts it listed), a link and not a
  button, read again right before the press. Diagnose never presses a
  link. Nothing else is clicked, typed, selected, submitted or confirmed.
  The page is reloaded to hear its list call, at the start of a run and
  again when what was heard is FRESH_SECONDS old, a tab the link's press
  took to its PDF is taken back, and lists and PDFs are asked for from
  inside the signed-in page, every address on bankofamerica.com. The guards
  below are also what Record and Diagnose mark each control against.
"""
from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import quote, urlsplit

from paperpull_core import intake, pressing
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE, control_labels
from paperpull_core.characters import whole_json
from paperpull_core.dates import checked as _checked_date, full_year
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("bofa_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("bankofamerica.com",)
# Where online banking and its statements live.
SECURE_HOST = "secure.bankofamerica.com"

BASE = "https://www.bankofamerica.com"
URLS = {
    "home": BASE + "/",
    # login.bat opens this. The person signs in from Bank of America's own
    # home page, the address the request names (#121).
    "login": BASE + "/",
}

# The statements page, by the part of its path the recordings kept, or by
# the whole path of the address a second tester's window showed for the
# same page (#121). Only that path, so a page below it, which the tab is
# taken back from after a press, is never taken for the statements page.
STATEMENTS_PAGE_RE = re.compile(r"stmts-docs|^/statements-documents/home/?$", re.I)
# The list call, by the shape both recordings showed, letter for letter.
# Words of eight, fifteen and four letters, then statements/v1/ and a word
# of six letters before Documents.
LIST_PATH_RE = re.compile(r"^/[A-Za-z]{8}/[A-Za-z]{15}/[A-Za-z]{4}/statements/v1/[A-Za-z]{6}Documents$")
# A call that names a change is never taken for the list, whatever its shape.
CHANGING_PATH_RE = re.compile(r"delete|remove|update|save|edit|change|create|send|order|request",
                              re.I)
# The body's names besides the account key, as both recordings showed them.
BODY_NAMES = ("docCategoryId", "year", "lang")
# A statement's PDF link, by the words of its name.
DOWNLOAD_LINK_RE = re.compile(r"^\s*Download PDF for\b", re.I)
# The heading the Statements list is drawn under, by its whole name, as
# both recordings pressed it.
STATEMENTS_HEADING = "Statements"
# How long the rows under it may take to draw once it is opened.
OPEN_WAIT_MS = 15000
# How long a press of a Download PDF link may take to bring its PDF, and
# how long after it comes another call is still listened for.
PRESS_WAIT_MS = 20000
SETTLE_MS = 1000
# The statements category, by its name in documentCategoryList.
STATEMENTS_CATEGORY_RE = re.compile(r"^\s*statements?\s*$", re.I)
# A docId shorter than this could sit inside an address by chance.
MIN_ID = 6
# Headers the page sent that the browser sets on its own, never sent again.
_BROWSER_HEADERS = re.compile(r"^(:.*|cookie|host|content-length|connection|origin|referer|"
                              r"user-agent|accept-encoding|accept-language|priority|"
                              r"sec-.*|upgrade-insecure-requests|dnt)$", re.I)
# Headers that say what a call sends and takes back. A PDF call keeps its
# own when its other headers are taken fresh from the list call.
_WHAT_IS_SENT = re.compile(r"^(content-.*|accept)$", re.I)
# Bank of America's bot protection is not known, so the list is asked for
# at a person's pace, account by account and year by year.
PACE_MS = 1200
# How long a learned list call is trusted before the page is heard again.
FRESH_SECONDS = 300

# Diagnose writes this down, so a survey file says it came from this build.
NOT_MAPPED = ""


class SessionExpired(RuntimeError):
    """Bank of America answered with a sign-in or a refusal instead."""


class NotThere(RuntimeError):
    """The tab is not on the statements page, so nothing was asked."""


class NotLearned(RuntimeError):
    """What the statements page does did not fit what the recordings
    showed, so nothing was guessed. The message is fixed words only, and
    `facts` what the page drew, as counts and fixed words, and `reason` the
    same in the failure file's own words, since its reason keeps no capital
    letter and no word off the word list."""

    def __init__(self, message: str, facts: Optional[dict] = None, reason: str = ""):
        super().__init__(message)
        self.facts = dict(facts or {})
        self.reason = reason


class ListCut(RuntimeError):
    """The list could not be read whole, so the run stops before it could
    call anything missing from it absent. The message is fixed words and
    counts only."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


def _on_secure(url: str) -> bool:
    try:
        return is_safe_url(url) and (urlsplit(url).hostname or "").lower() == SECURE_HOST
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a bank. Never move money, never pay, never
# open, close, lock or replace anything, never order or request anything
# that may carry a fee, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|\bpays\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"\bdeposit|withdraw|send\s+money|request\s+money|move\s+money|\bsend\b|"
    r"cash\s+advance|balance\s+transfer|\bredeem|\brewards?\b|\bdeals?\b|"
    r"keep\s+the\s+change|\boffers?\b|"
    # Opening an account or a card, never its statements.
    r"\bapply\b|open\s+(a|an|another|new|my)\b[\w\s]{0,24}\b(accounts?|cards?|cds?|ira)\b"
    r"(?!\s+(statements?|documents?))|"
    r"open\s+\w{0,12}\s*(accounts?|cards?)\b(?!\s+(statements?|documents?))|"
    r"\bopen\s+(now|merrill)\b|"
    r"get\s+(a\s+|an\s+|the\s+|your\s+)?(new\s+)?(card|account|loan|quote)\b|"
    r"close\s+(my\s+|an?\s+|this\s+)?account|"
    # A paper copy of a statement can carry a fee at a bank, so ordering,
    # requesting or getting a copy is never pressed.
    r"\bstop\b|\border\b|\brequest|\bcop(y|ies)\b|\bpaper\b|"
    r"\bloan\b|\bborrow|refinanc|"
    # Word boundaries on both sides of every stem. A card is a document
    # here, so "Credit card statement" must pass, and "edit" sits inside
    # "Credit".
    r"\breplac(e|es|ed|ing|ement)\b|\bactivat|\block\b|\bunlock|\bpin\b|"
    r"travel\s+(notice|notification|plans?)|credit\s+limit|"
    r"overdraft|balance\s+connect|\balerts?\b|\bbudget|\bgoals?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bmodif(y|ies|ied|ying)\b|\bmanage\b|"
    r"\bset\s+up\b|\bdelet|\bremov(e|es|ed|ing|al)\b|\bcancel|dispute|"
    r"report\s+(a\s+)?(lost|stolen|fraud)|\bfraud\b|"
    r"password|passcode|username|online\s+id|\bprofile\b|settings|preferences|"
    r"contact\s+info|\baddress\b|\bemail\b|\bphone\b|"
    r"\bconfirm|\bsubmit|\bagree\b|\baccept\b|authoriz|\bchat\b|contact\s+us|\berica\b|"
    r"beneficiar|nickname|\btrade\b|\bbuy\b|\bsell\b|"
    r"log\s*out|logout|log\s*off|sign\s*out|sign\s*off)", re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statements?\b|documents?\b|"
    r"\bletters?\b|\bnotices?\b|1099|1098|5498|tax\s+(forms?|documents?|statements?)|"
    r"\bsummar(y|ies)\b|year.?end|"
    r"\bhistory\b|see\s+(more|all|older)|show\s+(more|all|older))", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_statements_heading(name: str) -> bool:
    """The Statements heading of the statements page, by its whole name,
    and only when the guard above lets it through too."""
    name = re.sub(r"\s+", " ", name or "").strip()
    return name == STATEMENTS_HEADING and is_safe_control(name)


def _beside_names(name: str, names=()) -> str:
    """A control's words with the bank's own names for the statements and
    accounts it listed taken out, each standing whole, longest first."""
    rest = re.sub(r"\s+", " ", name or "").strip()
    for n in sorted({re.sub(r"\s+", " ", str(x or "")).strip() for x in names or ()},
                    key=len, reverse=True):
        if len(n) >= 3:
            rest = _whole(n).sub(" ", rest)
    return re.sub(r"\s+", " ", rest).strip()


def is_pdf_link(name: str, names=()) -> bool:
    """A statement's Download PDF link, by its words. The bank's own names
    for the statements and accounts it listed, `names`, are taken out first,
    since a card called Cash Rewards is named so and is not a control that
    redeems anything, and what is left has to start with Download PDF for
    and pass the guard above whole. With no names, the whole name does."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if len(name) > 300 or not DOWNLOAD_LINK_RE.match(name):
        return False
    rest = _beside_names(name, names)
    return bool(DOWNLOAD_LINK_RE.match(rest)) and is_safe_control(rest)


# The only controls a run presses, each through its own guard.
PRESS_GUARDS = (is_statements_heading, is_pdf_link)


def _words():
    """This app's own words for paperpull_core.words, for saying what
    covered a control."""
    import sys
    from paperpull_core.words import words_for
    return words_for("Bank of America", sys.modules[__name__])


SECURITY_CHALLENGE_MARKERS = [
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "authorization code", "authenticator",
    "confirm your identity", "verify your identity", "help us verify",
    "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "you have been logged off",
]

# Lowercased address fragments of a sign-in page. One only, the path the
# sign-in form has been on, not checked against an account yet. "/signin"
# is left out on purpose, since a signed-in overview may sit under a path
# like /myaccounts/signin/, and calling that signed out would refuse Record
# on the very page a person lands on. The password field below notices any
# sign-in form this misses.
LOGIN_URL_MARKERS = ["/login/sign-in/"]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic", "http error 429"]


def looks_signed_out(page) -> bool:
    """True where the page is the sign-in page by its address, shows a
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


def open_home(page) -> bool:
    """Bank of America's home page, where a person signs in, opened in a
    tab this run opened itself. Never in a tab of the person's, which is
    left where they put it. True when the tab ended on the site."""
    if not is_safe_url(URLS["home"]):
        return False
    try:
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log.info("home page failed: %s", type(e).__name__)
    try:
        return is_safe_url(page.url or "")
    except Exception:
        return False


def is_statements_address(url: str) -> bool:
    """Whether an address is Statements & Documents', by the address alone,
    so a tab can be told by it without reading the tab."""
    try:
        return _on_secure(url) and bool(STATEMENTS_PAGE_RE.search(urlsplit(url).path or ""))
    except ValueError:
        return False


def on_statements_page(page) -> bool:
    """The tab is on Statements & Documents and shows no sign-in form."""
    try:
        url = page.url or ""
    except Exception:
        return False
    if not is_statements_address(url):
        return False
    return not looks_signed_out(page)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def parse_date(text) -> str:
    """A YYYY-MM-DD date out of what the list gives, or "". Each of the
    ways a list writes a day is read, and a day that cannot exist is
    refused."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)", s)
    if m:
        return _checked_date("%s-%s-%s" % m.groups(), "")
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$", s)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(year) if len(year) == 4 else full_year(int(year))
        return _checked_date("%04d-%02d-%02d" % (y, month, day), "")
    m = re.match(r"^([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})$", s)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return _checked_date("%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(1)[:3].lower()],
                                               int(m.group(2))), "")
    return ""


def row_date(row: dict) -> str:
    """The statement's day, from date and dateString. Where both say a day
    and they disagree, which is which cannot be told, so neither is taken."""
    a = parse_date(row.get("date"))
    b = parse_date(row.get("dateString"))
    if a and b and a != b:
        return ""
    return a or b


def date_in_file_name(disposition: str) -> str:
    """The day in the file name the bank gave a PDF, eStmt_<date>.pdf, or ""."""
    m = re.search(r"filename\*?=[^;]*?(\d{4}-\d{2}-\d{2})", disposition or "", re.I)
    return _checked_date(m.group(1), "") if m else ""


# ---------------------------------------------------------------------------
# Hearing the page's own list call
# ---------------------------------------------------------------------------
_learned = {"at": 0.0, "call": None}


class Call:
    """The list call as the page made it, kept in memory for this run only
    and never written anywhere. `account_key` is the name the body and the
    lists give an account by."""

    def __init__(self, url, headers, body, account_key, answer, template, links, link_host="",
                 facts=None):
        self.url = url
        self.headers = headers
        self.body = body
        self.account_key = account_key
        self.answer = answer
        self.template = template
        self.links = links
        self.link_host = link_host       # the host the page's own PDF links were on
        # What the page drew and answered while it was heard, as counts and
        # fixed words (link_facts), for Diagnose and a failure file.
        self.facts = dict(facts or {})
        # Whether the PDF form was looked for, the Statements heading opened
        # when it was shut, which a run that only lists does not do.
        self.form_tried = False
        # The call one Download PDF link's press made for its PDF, as a
        # form (PdfCall), when the links hide their address.
        self.pdf = None
        # What the page's own answer said of itself, which every other
        # answer has to say too (_post_list).
        self.status = answer.get("status")

    @property
    def accounts(self) -> list:
        k = self.account_key
        return [a for a in (self.answer.get("accountList") or [])
                if isinstance(a, dict) and isinstance(a.get(k), str) and a.get(k)]

    @property
    def statements_category(self) -> str:
        return statements_category_of(self.answer)

    @property
    def years(self) -> list:
        return [y for y in (str(v).strip() for v in self.answer.get("yearList") or [])
                if re.fullmatch(r"\d{4}", y)]


def statements_category_of(answer: dict) -> str:
    """The Statements category's id in a list answer, or ""."""
    for c in answer.get("documentCategoryList") or []:
        if (isinstance(c, dict) and STATEMENTS_CATEGORY_RE.match(str(c.get("docCategoryName") or ""))
                and str(c.get("docCategoryId") or "")):
            return str(c["docCategoryId"])
    return ""


def _is_list_call(request) -> bool:
    try:
        if (request.method or "").upper() != "POST":
            return False
        u = urlsplit(request.url or "")
    except Exception:
        return False
    try:
        sends = str((request.headers or {}).get("content-type") or "")
    except Exception:
        sends = ""
    return (u.scheme == "https" and (u.hostname or "").lower() == SECURE_HOST
            and bool(LIST_PATH_RE.match(u.path or "")) and not u.query
            and not CHANGING_PATH_RE.search(u.path or "")
            # The body is sent again as JSON, so it has to have been JSON.
            and "json" in sends.lower())


def _is_list_answer(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("documentList"), list)
            and isinstance(body.get("accountList"), list))


def account_key_of(body: dict, answer: dict) -> str:
    """The name the body gives the account by, the one name in it besides
    BODY_NAMES, and only when the account the page has selected carries
    the same value under that name. "" when that cannot be told."""
    if not isinstance(body, dict):
        return ""
    others = [k for k in body if k not in BODY_NAMES]
    if len(others) != 1:
        return ""
    k = others[0]
    value = body.get(k)
    if not isinstance(value, str) or not value:
        return ""
    selected = [a for a in answer.get("accountList") or []
                if isinstance(a, dict) and a.get("selected") is True]
    if len(selected) != 1 or selected[0].get(k) != value:
        return ""
    return k


# Each "Download PDF for ..." link, its address as the browser reads it, the
# address as the page wrote it, and the values of its data- fields, which
# only link_facts reads, to count the links whose statement's id is there.
_LINKS_JS = r"""() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
  name: ((a.getAttribute('aria-label') || a.innerText || '').replace(/\s+/g, ' ').trim()).slice(0, 300),
  href: String(a.href || '').slice(0, 2000),
  raw: String(a.getAttribute('href') || '').slice(0, 2000),
  data: Array.from(a.attributes).filter(x => x.name.indexOf('data-') === 0)
    .map(x => String(x.value || '').slice(0, 300)).slice(0, 12)
})).filter(x => /^\s*Download PDF for\b/i.test(x.name)).slice(0, 200)"""


def drawn_links(page) -> list:
    """Each "Download PDF for ..." link the page drew, wherever its address
    goes, as {name, href, raw, data}. Read, never pressed."""
    try:
        # The page's own links, at most two hundred of them, read in the
        # page. No answer's body is read here.
        got = page.evaluate(_LINKS_JS)
    except Exception as e:
        log.info("the PDF links could not be read: %s", type(e).__name__)
        return []
    return [x for x in got or [] if isinstance(x, dict)
            and DOWNLOAD_LINK_RE.match(str(x.get("name") or ""))]


def download_links(page) -> list:
    """The address of each "Download PDF for ..." link the page drew, on
    bankofamerica.com only. Read, never pressed."""
    return [str(x.get("href") or "") for x in drawn_links(page)
            if is_safe_url(str(x.get("href") or ""))]


def link_facts(drawn: list, rows: list) -> dict:
    """What the page's Download PDF links were, as counts and never an
    address or a value, under names the word list that writes a survey
    keeps whole. How many there were, where their addresses go, how many
    hold a listed statement's id whole, and how many hold one only in a
    data- field, which is where a page keeps what a script of its own opens
    the PDF with."""
    ids = {r["docId"] for r in rows if isinstance(r, dict) and isinstance(r.get("docId"), str)
           and len(r["docId"]) >= MIN_ID}

    def holds(text) -> bool:
        text = str(text or "")
        return any(_whole(i).search(text) or _whole(quote(i, safe="")).search(text) for i in ids)

    out = {"pdf_links": len(drawn), "links_to_other_pages": 0, "links_to_no_page": 0,
           "links_to_this_page": 0, "links_elsewhere": 0, "links_with_an_id": 0,
           "links_with_an_id_elsewhere": 0}
    for x in drawn:
        href = str(x.get("href") or "")
        raw = str(x.get("raw") if x.get("raw") is not None else href).strip()
        if raw.lower().startswith("javascript:"):
            out["links_to_no_page"] += 1
        elif not raw or raw.startswith("#"):
            out["links_to_this_page"] += 1
        elif is_safe_url(href):
            out["links_to_other_pages"] += 1
        else:
            out["links_elsewhere"] += 1
        if holds(href):
            out["links_with_an_id"] += 1
        elif any(holds(v) for v in x.get("data") or []):
            out["links_with_an_id_elsewhere"] += 1
    return out


def _headings(page, expanded: bool):
    """The buttons whose whole name is Statements and which say they are
    open, or shut, as a Playwright locator. A button that says neither,
    with no aria-expanded at all, is in neither."""
    return page.get_by_role("button", name=STATEMENTS_HEADING, exact=True, expanded=expanded)


def _opens_a_list(el) -> bool:
    """A heading names the list it opens, in aria-controls."""
    try:
        return bool((el.get_attribute("aria-controls") or "").strip())
    except Exception:
        return False


def _submits_a_form(el) -> bool:
    """A button inside a form submits it when pressed, unless it is typed
    a plain button, and a press here only ever opens a list. One that
    cannot be read is taken for one that submits."""
    try:
        return bool(el.evaluate("e => !!e.form && (e.type || '').toLowerCase() !== 'button'"))
    except Exception:
        return True


def _any_refuses(labels) -> bool:
    """A label any of the blocklists refuses, which is_safe_control asks
    of a control's name."""
    return any(FORBIDDEN_CONTROL_RE.search(x) or SETTINGS_CONTROL_RE.search(x)
               or AUTH_CONTROL_RE.search(x) for x in labels)


def _open_ones(page) -> int:
    """How many Statements headings say they are open and name a list."""
    loc = _headings(page, True)
    n = loc.count()
    return sum(1 for i in range(min(n, 6)) if _opens_a_list(loc.nth(i).element_handle(timeout=5000)))


def open_statements(page) -> str:
    """Open the Statements heading when it is shut, with one press, and say
    how it stood, in words the failure file keeps. "already expanded" or
    "opened", or, with nothing pressed, "not found", "several" or
    "refused". Raises NotThere when the tab has left the statements page,
    and pressing.Stop when something is over the heading."""
    try:
        if _open_ones(page):
            return "already expanded"
        shut = _headings(page, False)
        n = shut.count()
    except Exception as e:
        log.info("the Statements heading could not be read: %s", type(e).__name__)
        return "not found"
    if n == 0:
        return "not found"
    if n > 1:
        # Which one holds the list cannot be told, so none is pressed.
        return "several"
    try:
        el = shut.first.element_handle(timeout=5000)
        labels = control_labels(el)
    except Exception as e:
        log.info("the Statements heading could not be read: %s", type(e).__name__)
        return "not found"
    # Its words, each label it carries, and the list it says it opens.
    if (el is None or not _opens_a_list(el) or not labels
            or not any(is_statements_heading(x) for x in labels) or _any_refuses(labels)
            or _submits_a_form(el)):
        return "refused"
    # Read once more right before the press. A heading the page has opened
    # meanwhile would be shut by it, and a tab gone from the page is not
    # pressed in at all.
    try:
        still_shut = (el.get_attribute("aria-expanded") or "").strip().lower() == "false"
    except Exception:
        still_shut = False
    if not still_shut:
        return "already expanded"
    if not on_statements_page(page):
        raise NotThere("the tab left Statements & Documents")
    pressing.click(page, el, css="button[aria-controls]", what="the Statements heading",
                   words=_words(), step="expand the statements heading")
    return "opened"


def _expanded_now(page) -> bool:
    """Whether a Statements heading says it is open, read after the press."""
    try:
        return _open_ones(page) > 0
    except Exception:
        return False


def _marker(name: str, quoted: bool) -> str:
    return "\x00%s%s\x00" % ("q:" if quoted else "", name)


# What a value written into an address as it is may hold. Anything else
# would change what the address asks for, so it is written escaped or not
# at all.
_PLAIN = re.compile(r"^[A-Za-z0-9._~-]+$")


def _whole(value: str) -> re.Pattern:
    """A value in an address standing whole, never the start or the end of
    a longer run of letters and digits, so DOC0099 is not found in DOC00992."""
    return re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value))


def _marked(text: str, row: dict) -> Tuple[str, set]:
    """`text` with each of the row's own values in it marked by the name of
    its field, and the names marked. Longest values first, so one value
    inside another is never taken for it."""
    fields = sorted(((k, v) for k, v in row.items() if isinstance(v, str) and len(v) >= MIN_ID),
                    key=lambda kv: -len(kv[1]))
    out = text
    used = set()
    for name, value in fields:
        enc = quote(value, safe="")
        if _PLAIN.match(value) and _whole(value).search(out):
            out = _whole(value).sub(lambda m: _marker(name, False), out)
            used.add(name)
        elif enc != value and _whole(enc).search(out):
            out = _whole(enc).sub(lambda m: _marker(name, True), out)
            used.add(name)
    return out, used


def template_of(href: str, row: dict) -> Optional[str]:
    """The address of a row's link as a form, each of the row's own values
    in it marked by the name of its field, or None when the row's docId is
    not in it whole."""
    doc_id = row.get("docId")
    if not isinstance(doc_id, str) or len(doc_id) < MIN_ID:
        return None
    out, used = _marked(href, row)
    return out if "docId" in used else None


def fill(template: str, row: dict) -> Optional[str]:
    """A row's own address in the form, or None when the row lacks a field
    the form needs, or holds a value that would change what the address
    asks for where the form writes it as it is."""
    def put(m):
        quoted, name = bool(m.group(1)), m.group(2)
        value = row.get(name)
        if not isinstance(value, str) or not value:
            raise KeyError(name)
        if quoted:
            return quote(value, safe="")
        if not _PLAIN.match(value):
            raise KeyError(name)
        return value

    try:
        return re.sub(r"\x00(q:)?([^\x00]+)\x00", put, template)
    except KeyError:
        return None


def forms_of(rows: list, links: list) -> Tuple[set, int]:
    """Every form the links come out of, each learned from a link and the
    first row, in the order given, whose docId it holds and whose form
    fills back to it, and how many links gave one."""
    forms = set()
    matched = 0
    for href in links:
        for row in rows:
            if not isinstance(row, dict):
                continue
            t = template_of(href, row)
            if t is not None and fill(t, row) == href:
                forms.add(t)
                matched += 1
                break
    return forms, matched


def learn_template(rows: list, links: list) -> Tuple[Optional[str], int]:
    """The one form every link the page drew comes out of, and how many
    links it was learned from. None when no link holds a row's docId, when
    two links come out of different forms, or when a link matches no row."""
    forms, matched = forms_of(rows, links)
    if len(forms) != 1 or matched != len(links):
        return None, matched
    return forms.pop(), matched


# ---------------------------------------------------------------------------
# A Download PDF link whose address is a script
# ---------------------------------------------------------------------------
# What a link a script of the page's own opens has for an address. Nothing,
# a place on the page itself, or the script.
def _opens_by_script(raw) -> bool:
    raw = str(raw or "").strip()
    return not raw or raw.startswith("#") or raw.lower().startswith("javascript:")


def _all_by_script(facts: dict) -> bool:
    """Every Download PDF link the page drew opens its PDF by a script and
    none shows a listed statement's id in its address."""
    n = facts.get("pdf_links") or 0
    return bool(n) and not facts.get("links_with_an_id") and (
        (facts.get("links_to_this_page") or 0) + (facts.get("links_to_no_page") or 0) == n)


class PdfCall:
    """The call a press of one Download PDF link made for its PDF, its
    address and body as forms (template_of, the row's own values marked),
    kept in memory for this run only and never written anywhere."""

    def __init__(self, method, url, body, headers, host):
        self.method = method         # "GET" or "POST"
        self.url = url
        self.body = body             # "" when the call sent none
        self.headers = headers
        self.host = host

    def filled(self, row: dict) -> Optional[Tuple[str, str]]:
        """A row's own address and body in the form, or None when the row
        lacks a field the form needs or holds a value it cannot write."""
        url = fill(self.url, row)
        body = fill(self.body, row) if self.body else ""
        if url is None or body is None:
            return None
        return url, body


# Kept for the run, so a later reload is not a reason to press again, and a
# press whose call was not learned, or that something failed after, is not
# made twice. The list call is heard again on a reload, and the headers both
# calls send are taken from it.
_pdf_learned = {"pdf": None, "pressed": False, "facts": None}


def _names_of(rows: list, accounts: list) -> list:
    """The bank's own names for the statements and accounts it listed."""
    out = []
    for r in list(rows or ()) + list(accounts or ()):
        if isinstance(r, dict):
            out.extend(str(r.get(k) or "") for k in ("docDisplayName", "accountDisplayName"))
    return [n for n in out if n.strip()]


def _a_link_to_press(el, names) -> bool:
    """A link of the page's own, not a button or a field, whose address is
    a script, with a label that is a statement's Download PDF link and no
    label any blocklist refuses beside the bank's own names. One that
    cannot be read is not pressed."""
    try:
        if str(el.evaluate("e => e.tagName") or "").upper() != "A":
            return False
        if not _opens_by_script(el.get_attribute("href")):
            return False
        labels = control_labels(el)
    except Exception:
        return False
    return (bool(labels) and any(is_pdf_link(x, names) for x in labels)
            and not _any_refuses([_beside_names(x, names) for x in labels]))


def pdf_link_to_press(page, drawn: list, names) -> Tuple[Optional[object], str]:
    """The one Download PDF link to press, as an element, and how it stood,
    "chosen", or with nothing to press, "refused" (no link this app
    presses), "several" (each it would press shares its name with another
    link) or "not found". The first link in the page's order that fits."""
    took = [x for x in drawn if _opens_by_script(x.get("raw")) and is_pdf_link(x.get("name"), names)]
    if not took:
        return None, "refused"
    several = False
    for x in took:
        try:
            loc = page.get_by_role("link", name=x["name"], exact=True)
            n = loc.count()
            if n > 1:
                # Which of them Playwright would press cannot be told.
                several = True
                continue
            el = loc.first.element_handle(timeout=5000) if n == 1 else None
        except Exception as e:
            log.info("a Download PDF link could not be read: %s", type(e).__name__)
            continue
        if el is not None and _a_link_to_press(el, names):
            return el, "chosen"
    return None, "several" if several else "not found"


def _download_address(d) -> str:
    try:
        return str(d.url or "")
    except Exception:
        return ""


def _press_and_hear(page, el, names) -> dict:
    """Press one Download PDF link and hear what it asks the bank for. The
    PDF it brings is never kept. A download it starts is cancelled and its
    file deleted, and a tab it opens is closed. Raises NotThere when the
    tab left the statements page before the press, and pressing.Stop when
    something is over the link."""
    heard = {"calls": [], "pdf": [], "downloads": [], "tabs": []}

    def on_request(req):
        try:
            if is_safe_url(req.url or "") and len(heard["calls"]) < 200:
                heard["calls"].append(req)
        except Exception:
            pass

    def on_response(r):
        try:
            if not is_safe_url(r.url or ""):
                return
            h = r.headers or {}
            kind = str(h.get("content-type") or "").lower()
            said = str(h.get("content-disposition") or "").lower()
            if "pdf" in kind or ".pdf" in said:
                heard["pdf"].append(r.request)
        except Exception:
            pass

    def on_download(d):
        try:
            heard["downloads"].append(d)
        except Exception:
            pass

    def on_tab_download(d):
        # A tab that opened meanwhile can be the person's own, so only a
        # download from the bank's site is the press's.
        try:
            if _on_the_site(_download_address(d)):
                heard["downloads"].append(d)
        except Exception:
            pass

    def on_page(p):
        try:
            heard["tabs"].append(p)
            p.on("download", on_tab_download)
        except Exception:
            pass

    def on_moved(frame):
        try:
            if frame == page.main_frame:
                heard["moved"] = True
        except Exception:
            pass

    # At the context, so a call made for a tab the press opens is heard from
    # its first answer on.
    try:
        ctx = page.context
    except Exception:
        ctx = None
    hooks = ([(ctx, "request", on_request), (ctx, "response", on_response), (ctx, "page", on_page)]
             if ctx is not None else [(page, "request", on_request), (page, "response", on_response)])
    hooks += [(page, "download", on_download), (page, "framenavigated", on_moved)]
    for source, event, fn in hooks:
        source.on(event, fn)
    try:
        # Read once more right before the press, as the heading is.
        if not on_statements_page(page):
            raise NotThere("the tab left Statements & Documents")
        if not _a_link_to_press(el, names):
            heard["refused_late"] = True
            return heard
        # Pressed for this run from here on, whatever happens after, so it is
        # never pressed twice in one run.
        _pdf_learned["pressed"] = True
        pressing.click(page, el, css=pressing.LINKS, what="a statement's Download PDF link",
                       words=_words(), step="download a statement")
        waited = 0
        while waited < PRESS_WAIT_MS and not heard["pdf"] and not any(
                is_safe_url(_download_address(d)) for d in heard["downloads"]):
            page.wait_for_timeout(250)
            waited += 250
        if any(_moves_the_tab(page, r) for r in heard["pdf"]):
            # The statements tab itself went to the PDF, which it shows only
            # once it has moved, a moment after the answer, unless the PDF
            # is downloaded instead. Waited for, so the tab is taken back
            # to the statements page before anything is asked from it.
            waited = 0
            while waited < PRESS_WAIT_MS and not heard.get("moved") and not heard["downloads"]:
                page.wait_for_timeout(250)
                waited += 250
        if heard["pdf"] or heard["downloads"]:
            # A press that makes two calls for its PDF is not one this app
            # can ask again, so the second is listened for too.
            page.wait_for_timeout(SETTLE_MS)
    finally:
        for source, event, fn in hooks:
            try:
                source.remove_listener(event, fn)
            except Exception:
                pass
        for d in heard["downloads"]:
            # Cancelled and deleted, waited for no longer than the core
            # waits for a download.
            intake.discard(d, page)
        for p in heard["tabs"]:
            if _opened_by_the_press(p, page, heard):
                try:
                    p.close()
                except Exception:
                    pass
    return heard


def _moves_the_tab(page, req) -> bool:
    """Whether a call is the statements tab's own going to a new address."""
    try:
        return bool(req.is_navigation_request()) and req.frame == page.main_frame
    except Exception:
        return False


def _on_the_site(url: str) -> bool:
    """An address on the bank's site, or a blob a page of the site made."""
    url = str(url or "")
    return is_safe_url(url) or (url.startswith("blob:") and is_safe_url(url[5:]))


def _opened_by_the_press(tab, page, heard) -> bool:
    """A tab that opened while the press was heard, from the statements
    page, or one at the very address of a PDF the press brought, never the
    statements tab. Any other tab, a blank one or one on the bank's site,
    can be the person's own, opened meanwhile, and is left."""
    if tab is page:
        return False
    try:
        if tab.opener() is page:
            return True
    except Exception:
        pass
    url = _url_of(tab)
    brought = ({_url_of(r) for r in heard.get("pdf", ())}
               | {_download_address(d) for d in heard.get("downloads", ())})
    return _on_the_site(url) and url in brought


def _sends(req) -> Tuple[dict, str]:
    """The headers a call sent that the browser does not set on its own,
    and its body as text, "" for none, as Playwright holds them already.
    Never all_headers(), which waits for the browser's own copy, and for a
    call of a tab the press opened and that is closed now, waits forever."""
    try:
        headers = dict(req.headers or {})
    except Exception:
        headers = {}
    try:
        body = req.post_data or ""
    except Exception:
        body = None
    return ({k: v for k, v in (headers or {}).items() if not _BROWSER_HEADERS.match(k)},
            body if isinstance(body, str) else None)


def _kind_of(method: str, headers: dict, body) -> str:
    """What a call is, in the failure file's own words. A GET with no body,
    a POST of JSON or of a form, or anything else, "other"."""
    if body is None:
        return "other"
    sent = next((str(v) for k, v in headers.items() if k.lower() == "content-type"), "").lower()
    if method == "GET":
        return "get" if not body else "other"
    if method == "POST" and body:
        if "json" in sent:
            return "json"
        if "x-www-form-urlencoded" in sent:
            return "form"
    return "other"


def pdf_call_of(heard: dict, rows: list) -> Tuple[Optional[PdfCall], Optional[dict], dict]:
    """The one call the press made for its PDF, as a form, the row it was
    for, and what was heard, as counts and fixed words. A download the
    press started at an address of the site is that call too. None when
    the press made no such call, or several, or one that is not a GET or a
    POST of JSON or a form, that names a change, or that holds no listed
    statement's id, or more than one statement's."""
    facts = {"urls_read_after_the_link_was_pressed": len(heard["calls"]),
             "pdf_files_read": len(heard["pdf"]), "downloads": len(heard["downloads"]),
             "tabs_opened": len(heard["tabs"])}
    calls = list(heard["pdf"])
    for d in heard["downloads"]:
        url = _download_address(d)
        if url.startswith("blob:"):
            facts["downloads_in_the_page"] = facts.get("downloads_in_the_page", 0) + 1
        elif is_safe_url(url):
            calls.extend([r for r in heard["calls"] if _url_of(r) == url][-1:])
    found = {}
    for req in calls:
        try:
            method = (req.method or "").upper()
        except Exception:
            method = ""
        headers, body = _sends(req)
        found.setdefault((method, _url_of(req), body), (method, _url_of(req), body, headers))
    facts["pdf_urls"] = len(found)
    if len(found) != 1:
        return None, None, facts
    method, url, body, headers = next(iter(found.values()))
    kind = facts["pdf_url_kind"] = _kind_of(method, headers, body)
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if (kind == "other" or parts is None or parts.scheme != "https" or not is_safe_url(url)
            or CHANGING_PATH_RE.search(parts.path or "")):
        facts["pdf_url_refused"] = True
        return None, None, facts
    ids = {r["docId"] for r in rows if isinstance(r, dict) and isinstance(r.get("docId"), str)
           and len(r["docId"]) >= MIN_ID}
    held = [i for i in sorted(ids) if any(_whole(i).search(t) or _whole(quote(i, safe="")).search(t)
                                          for t in (url, body))]
    facts["statements_in_the_pdf_url"] = len(held)
    if len(held) != 1:
        return None, None, facts
    row = next(r for r in rows if isinstance(r, dict) and r.get("docId") == held[0])
    url_form, in_url = _marked(url, row)
    body_form, in_body = _marked(body, row)
    if ("docId" not in (in_url | in_body) or fill(url_form, row) != url
            or (body and fill(body_form, row) != body)):
        facts["statements_in_the_pdf_url"] = 0
        return None, None, facts
    return PdfCall(method, url_form, body_form, headers, (parts.hostname or "").lower()), row, facts


def _url_of(req) -> str:
    try:
        return str(req.url or "")
    except Exception:
        return ""


def learn_pdf_call(page, drawn: list, rows: list, call: Call) -> Tuple[Optional[PdfCall], dict]:
    """The call a statement's PDF is asked with, learned from one press of
    a Download PDF link the page drew, when every link's address is a
    script. It is asked once more, for the statement pressed, from inside
    the page, and kept only when that answers with a PDF. Learned once a
    run. Raises NotThere, SessionExpired, and pressing.Stop."""
    kept = _pdf_learned.get("pdf")
    if kept is not None:
        # A form or a GET is still sent as one and still takes a PDF, so only
        # the session's own headers are taken from the list call.
        fresh = {k.lower(): v for k, v in call.headers.items() if not _WHAT_IS_SENT.match(k)}
        kept.headers = {k: fresh.get(k.lower(), v) for k, v in kept.headers.items()}
        return kept, {"pdf_link": "kept"}
    if _pdf_learned.get("pressed"):
        # Pressed already this run, and what it brought was not learned.
        return None, dict(_pdf_learned.get("facts") or {"pdf_link": "pressed"})
    names = _names_of(rows, call.accounts)
    el, how = pdf_link_to_press(page, drawn, names)
    if el is None:
        return None, {"pdf_link": how}
    heard = _press_and_hear(page, el, names)
    if heard.get("refused_late"):
        return None, {"pdf_link": "refused"}
    pdf, row, facts = pdf_call_of(heard, rows)
    facts["pdf_link"] = "pressed"
    if not on_statements_page(page):
        # The press opened the PDF in the person's own tab. It is taken
        # back to the statements page the lists are asked from.
        facts["back_to_the_page"] = True
        try:
            page.go_back(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.info("the statements page could not be gone back to: %s", type(e).__name__)
        if not on_statements_page(page):
            raise NotThere("a Download PDF link took the tab off Statements & Documents")
    if pdf is not None:
        try:
            r = _ask_pdf(page, pdf, row)
        except SessionExpired:
            # The list answered a moment ago, so a refusal of this one call
            # says it cannot be asked from the page, not that the session
            # ended, and signing in again would press the link again for
            # the same answer.
            r = None
        facts["pdf_url_read_again"] = bool(r and r.get("status") == 200 and r.get("b64")
                                           and intake.decode(r["b64"])[:5] == b"%PDF-")
        if not facts["pdf_url_read_again"]:
            pdf = None
    if pdf is not None:
        _pdf_learned["pdf"] = pdf
    _pdf_learned["facts"] = dict(facts)
    return pdf, facts


def _wait_for_links(page, tries: int) -> list:
    """The page's Download PDF links, once it has drawn any, read every
    half second for `tries` times. The page draws its rows after its
    answer comes."""
    drawn = []
    for _ in range(tries):
        drawn = drawn_links(page)
        if drawn:
            break
        page.wait_for_timeout(500)
    return drawn


def _wait_after_the_press(page, got: dict, heard: list, before: int) -> list:
    """The Download PDF links drawn under the heading just opened, read
    once the list the press asked for has been heard too, or once
    OPEN_WAIT_MS is over, whichever comes first. The rows are drawn from
    that answer, so links read before it is heard could match no row."""
    drawn = []
    for _ in range(OPEN_WAIT_MS // 500):
        if got.get("refused_later"):
            break
        drawn = drawn_links(page)
        if drawn and len(heard) > before:
            break
        page.wait_for_timeout(500)
    return drawn


def learn(page, wait_ms: int = 25000, form: bool = True, press_link: bool = True) -> Call:
    """Reload the statements page and keep the list call it makes, and the
    form of its PDF links, opening the Statements heading first when the
    page drew none. When every link's address is a script, one link is
    pressed to learn the call its PDF comes by instead (learn_pdf_call),
    unless `press_link` is False, as for Diagnose. With `form` False, for a
    run that only lists (Login, Discover), the links the page drew are read
    once and nothing is pressed. Raises NotThere, SessionExpired or
    NotLearned, and pressing.Stop when the heading or the link has
    something over it."""
    if not on_statements_page(page):
        raise NotThere("the tab is not on Statements & Documents")
    got = {}
    # Every list the page answers while it is heard, the reload's and the
    # one opening the heading asks for, whose rows are the ones it draws.
    heard = []

    def on_response(r):
        try:
            req = r.request
            if not _is_list_call(req):
                return
            body = whole_json(intake.json_of(r))
        except Exception:
            return
        if "answer" in got:
            if r.status in (401, 403):
                got["refused_later"] = r.status
            elif r.status == 200 and _is_list_answer(body):
                heard.append(body)
            return
        got["status"] = r.status
        if not _is_list_answer(body):
            return
        try:
            sent = whole_json(req.post_data_json)
        except Exception:
            sent = None
        try:
            headers = req.all_headers()
        except Exception:
            headers = dict(req.headers or {})
        got["url"] = req.url
        got["body"] = sent if isinstance(sent, dict) else None
        got["headers"] = {k: v for k, v in (headers or {}).items() if not _BROWSER_HEADERS.match(k)}
        got["answer"] = body
        heard.append(body)

    page.on("response", on_response)
    try:
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("the statements page would not reload: %s", type(e).__name__)
        waited = 0
        while "answer" not in got and waited < wait_ms:
            page.wait_for_timeout(500)
            waited += 500
        if got.get("status") in (401, 403) or looks_signed_out(page):
            raise SessionExpired("Bank of America showed a sign-in page")
        if "answer" not in got:
            raise NotLearned("the statements page made no list call this app knows")
        if not got.get("body"):
            raise NotLearned("the list call's body was not one this app can read")
        key = account_key_of(got["body"], got["answer"])
        if not key:
            raise NotLearned("the list call names its account in a way this app cannot tell")
        if any(not (isinstance(a, dict) and isinstance(a.get(key), str) and a.get(key))
               for a in got["answer"].get("accountList") or []):
            # An account it could not ask for would be missing from a list
            # taken as whole.
            raise NotLearned("an account in the list has no key this app can read")
        if got["answer"].get("errorInfo"):
            raise NotLearned("the page's own list answered with an error")
        if not statements_category_of(got["answer"]):
            raise NotLearned("the list names no Statements category")
        heading = "not pressed"
        pressed = {}
        # The page draws its rows after its answer comes.
        drawn = _wait_for_links(page, 16 if form else 1)
        if not drawn and form:
            # A reload leaves the Statements heading shut, and nothing is
            # drawn under a shut heading.
            before = len(heard)
            heading = open_statements(page)
            if heading == "opened":
                drawn = _wait_after_the_press(page, got, heard, before)
                if got.get("refused_later"):
                    raise SessionExpired("Bank of America answered %s" % got["refused_later"])
                pressed = {"list_read_after_the_heading": len(heard) > before,
                           "heading_expanded_after": _expanded_now(page)}
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    # The newest answer first, the one whose rows the page drew last, so a
    # statement both answers list is matched to the row it was drawn from.
    rows = [r for answer in reversed(heard) for r in answer.get("documentList") or []
            if isinstance(r, dict)]
    links = [str(x.get("href") or "") for x in drawn if is_safe_url(str(x.get("href") or ""))]
    forms, matched = forms_of(rows, links)
    # Every link comes out of the one form, or none is taken.
    template = next(iter(forms)) if len(forms) == 1 and matched == len(links) else None
    hosts = {(urlsplit(h).hostname or "").lower() for h in links}
    facts = dict(link_facts(drawn, rows), statements_heading=heading,
                 times_the_list_was_read=len(heard), rows_read=len(rows), forms=len(forms),
                 links_with_no_row=len(links) - matched, **pressed)
    call = Call(got["url"], got["headers"], got["body"], key, got["answer"], template, len(links),
                link_host=hosts.pop() if len(hosts) == 1 else "", facts=facts)
    if call.template is not None and not call.link_host:
        call.template = None
    if form and call.template is None and _all_by_script(facts):
        if press_link:
            call.pdf, pressed_facts = learn_pdf_call(page, drawn, rows, call)
            call.facts.update(pressed_facts)
        else:
            call.facts["pdf_link"] = "not pressed"
    # Asked once a run that downloads needs it, unless this one found it.
    call.form_tried = form or call.template is not None
    _learned.update(at=time.monotonic(), call=call)
    return call


def not_learned_why(facts: dict) -> Tuple[str, str]:
    """Why no PDF form was learned, from what the page drew, as a sentence
    for the run to say and a reason in the failure file's own words."""
    heading = facts.get("statements_heading")
    if not facts.get("pdf_links"):
        if heading in ("opened", "already expanded"):
            return ("the statements page drew no Download PDF link, even with its "
                    "Statements heading open", "no pdf link with the heading expanded")
        return ("the statements page drew no Download PDF link, and its Statements "
                "heading could not be opened (%s)" % (heading or "not pressed"),
                "no pdf link on the page")
    link = facts.get("pdf_link")
    if link in ("refused", "several", "not found"):
        return ("the statements page's Download PDF links do not show the address of "
                "their statement, and none of them is a link this app presses (%s)" % link,
                "the pdf link was not pressed")
    if link == "pressed":
        if not facts.get("pdf_urls"):
            return ("pressing a Download PDF link brought no PDF this app could hear",
                    "no pdf url after the link was pressed")
        if facts["pdf_urls"] > 1:
            return ("pressing a Download PDF link brought a PDF from more than one call",
                    "several pdf urls after the link was pressed")
        if facts.get("pdf_url_refused"):
            return ("the call a Download PDF link makes for its PDF is not one this app "
                    "asks again", "the pdf url is refused")
        if not facts.get("statements_in_the_pdf_url"):
            return ("the call a Download PDF link makes for its PDF names no listed "
                    "statement", "no statement id in the pdf url")
        if facts["statements_in_the_pdf_url"] > 1:
            return ("the call a Download PDF link makes for its PDF names more than one "
                    "listed statement", "several statements in the pdf url")
        return ("the call a Download PDF link makes for its PDF did not answer with a "
                "PDF when asked again", "no pdf when the pdf url was read again")
    if not facts.get("forms"):
        if heading == "opened" and not facts.get("list_read_after_the_heading"):
            return ("the statements page drew Download PDF links for a list this app "
                    "did not hear it ask for", "the list was not read after the heading")
        return ("the statements page's Download PDF links do not show the address of "
                "their statement", "no statement id in the pdf links")
    if facts["forms"] > 1:
        return ("the statements page's Download PDF links do not all come out of one form",
                "the pdf links are of several forms")
    if facts.get("links_with_no_row"):
        return ("a Download PDF link on the statements page matches no statement it listed",
                "pdf links with no row")
    return ("the statements page's Download PDF links are not all on one host of the bank",
            "the pdf links are elsewhere")


def learned(page, form: bool = False) -> Call:
    """The list call heard in this run, heard again when it is old, or when
    `form` is asked for and the call was heard without it."""
    call = _learned.get("call")
    if (call is None or time.monotonic() - _learned["at"] > FRESH_SECONDS
            or (form and not call.form_tried)):
        call = learn(page, form=form)
    return call


def forget() -> None:
    _learned.update(at=0.0, call=None)
    _pdf_learned.update(pdf=None, pressed=False, facts=None)


# ---------------------------------------------------------------------------
# Asking from inside the page
# ---------------------------------------------------------------------------
_LIST_JS = r"""async ([url, headers, body]) => {
  const t = new URL(url, location.href);
  if (t.protocol !== 'https:' || t.hostname !== 'secure.bankofamerica.com') {
    throw new Error('Refusing an off-host request');
  }
  const h = Object.assign({}, headers || {});
  h['Content-Type'] = h['Content-Type'] || h['content-type'] || 'application/json';
  delete h['content-type'];
  const r = await fetch(t.href, {method: 'POST', credentials: 'include', headers: h,
                                 body: JSON.stringify(body), redirect: 'error'});
  const raw = await ppRead(r);
  let j = null;
  try { j = JSON.parse(new TextDecoder().decode(raw)); } catch (e) {}
  return {status: r.status, url: r.url, json: j};
}"""

_PDF_JS = r"""async (url) => {
  const t = new URL(url, location.href);
  const host = t.hostname;
  if (t.protocol !== 'https:' || !(host === 'bankofamerica.com' || host.endsWith('.bankofamerica.com'))) {
    throw new Error('Refusing an off-host request');
  }
  const r = await fetch(t.href, {credentials: 'include', redirect: 'follow'});
  const end = new URL(r.url || t.href);
  if (end.protocol !== 'https:' || !(end.hostname === 'bankofamerica.com' ||
                                     end.hostname.endsWith('.bankofamerica.com'))) {
    // Followed off the site. Its body is never read.
    return {status: r.status, url: r.url, ct: '', cd: '', b64: ''};
  }
  const bytes = await ppRead(r);
  let bin = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return {status: r.status, url: r.url, ct: r.headers.get('content-type') || '',
          cd: r.headers.get('content-disposition') || '', b64: btoa(bin)};
}"""


# A statement's PDF asked with the call a Download PDF link's press made,
# its method, the headers it sent and its body as it sent it.
_PDF_CALL_JS = r"""async ([url, method, headers, body]) => {
  const ours = u => u.protocol === 'https:' &&
    (u.hostname === 'bankofamerica.com' || u.hostname.endsWith('.bankofamerica.com'));
  const t = new URL(url, location.href);
  if (!ours(t) || (method !== 'GET' && method !== 'POST')) {
    throw new Error('Refusing an off-host request');
  }
  const init = {method: method, credentials: 'include', redirect: 'follow',
                headers: Object.assign({}, headers || {})};
  if (method === 'POST') { init.body = body; }
  const r = await fetch(t.href, init);
  const end = new URL(r.url || t.href);
  if (!ours(end)) {
    // Followed off the site. Its body is never read.
    return {status: r.status, url: r.url, ct: '', cd: '', b64: ''};
  }
  const bytes = await ppRead(r);
  let bin = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return {status: r.status, url: r.url, ct: r.headers.get('content-type') || '',
          cd: r.headers.get('content-disposition') || '', b64: btoa(bin)};
}"""


def _ask_pdf(page, pdf: PdfCall, row: dict) -> Optional[dict]:
    """A row's PDF asked from inside the page with the learned call, as
    {status, url, ct, cd, b64}. Raises NotLearned when the row's own call
    would not come out on the host the press's call went to, ListCut when
    the page could not ask, and SessionExpired on a sign-in answer."""
    filled = pdf.filled(row)
    if filled is None:
        raise NotLearned("a statement's address did not come out where the page's own call is")
    url, body = filled
    if not is_safe_url(url) or (urlsplit(url).hostname or "").lower() != pdf.host:
        raise NotLearned("a statement's address did not come out where the page's own call is")
    try:
        r = intake.evaluate(page, _PDF_CALL_JS, [url, pdf.method, pdf.headers, body])
    except Exception as e:
        raise ListCut("a statement could not be asked for in the page (%s)" % type(e).__name__)
    status = r.get("status") if isinstance(r, dict) else None
    if status in (401, 403) or not is_safe_url((r or {}).get("url") or ""):
        raise SessionExpired("Bank of America answered %s" % status)
    return r


def _post_list(page, call: Call, body: dict) -> dict:
    if not _on_secure(call.url):
        raise ValueError("refusing a list call off secure.bankofamerica.com")
    if not on_statements_page(page):
        raise NotThere("the tab is not on Statements & Documents")
    try:
        r = intake.evaluate(page, _LIST_JS, [call.url, call.headers, body])
    except Exception as e:
        # A redirect to a sign-in, a page gone mid-run or an answer over
        # its limit. Which cannot be told, and the list is not whole.
        raise ListCut("a list call failed in the page (%s)" % type(e).__name__)
    status = r.get("status") if isinstance(r, dict) else None
    if status in (401, 403):
        raise SessionExpired("Bank of America answered %s" % status)
    if status != 200 or not _is_list_answer(r.get("json")):
        raise ListCut("a list call answered %s" % (status if isinstance(status, int) else "nothing"))
    answer = whole_json(r["json"])
    # An answer that says something else of itself than the page's own did,
    # or carries an error, may have left statements out.
    if answer.get("status") != call.status or answer.get("errorInfo"):
        raise ListCut("a list call answered with an error")
    return answer


def statement_row(row, account: dict, key: str, category_id: str, year: str = "") -> Optional[dict]:
    """One statement of the list, or None for a row of another category or
    another account. Raises ValueError for a statement row it cannot read,
    so the list is never taken as whole without it. `year` is the year the
    list was asked for, which is where its download looks for it again."""
    if not isinstance(row, dict):
        raise ValueError("a row that is not a record")
    if not str(row.get("docCategoryId") or ""):
        raise ValueError("a row that names no category")
    if str(row.get("docCategoryId")) != category_id:
        return None
    if key in row and row.get(key) != account.get(key):
        # A statement of another account in this account's answer, or the
        # account written another way. Neither is taken as this one's.
        raise ValueError("a statement under another account's key")
    doc_id = row.get("docId")
    if not isinstance(doc_id, str) or len(doc_id) < MIN_ID:
        raise ValueError("a statement with no id")
    date = row_date(row)
    if not date:
        raise ValueError("a statement with no day this app can read")
    title = re.sub(r"\s+", " ", str(row.get("docDisplayName") or "")).strip() or "Statement"
    name = re.sub(r"\s+", " ", str(row.get("accountDisplayName") or account.get("accountDisplayName") or "")).strip()
    return {"title": title, "date": date, "account": name, "category": "Statement",
            "document_id": doc_id, "account_ref": account[key], "year": year or date[:4]}


def _body_for(call: Call, account: dict, year: str) -> dict:
    body = dict(call.body)
    body[call.account_key] = account[call.account_key]
    body["docCategoryId"] = call.statements_category
    body["year"] = year
    return body


def list_account_year(page, call: Call, account: dict, year: str) -> Tuple[List[dict], list]:
    """One account's statements of one year, read whole or ListCut, and the
    years that answer names, which can be the account's own."""
    answer = _post_list(page, call, _body_for(call, account, year))
    rows, unread = [], 0
    for row in answer.get("documentList") or []:
        try:
            got = statement_row(row, account, call.account_key, call.statements_category, year)
        except ValueError:
            unread += 1
            continue
        if got is not None:
            rows.append(got)
    if unread:
        raise ListCut("%d statement(s) in a list could not be read" % unread)
    years = [y for y in (str(v).strip() for v in answer.get("yearList") or [])
             if re.fullmatch(r"\d{4}", y)]
    return rows, years


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every account's statements, year by year. `keep` is the run's scope
    predicate over year labels. The years asked for an account are the
    page's own and every year an answer for that account names. Raises
    NotThere, SessionExpired, NotLearned or ListCut, and never answers with
    part of a list. Nothing is pressed, since a list needs no PDF link."""
    call = learn(page, form=False)
    if not call.accounts:
        raise NotLearned("the list names no account")
    if not call.years:
        raise NotLearned("the list names no year")
    rows: List[dict] = []
    first = True
    for account in call.accounts:
        asked, waiting = set(), list(call.years)
        while waiting:
            year = waiting.pop(0)
            if year in asked:
                continue
            asked.add(year)
            if keep is not None and not keep(year):
                continue
            if not first:
                page.wait_for_timeout(PACE_MS)
            first = False
            got, years = list_account_year(page, call, account, year)
            rows.extend(got)
            waiting.extend(y for y in years if y not in asked and y not in waiting)
    rows.sort(key=lambda r: (r["account"], r["account_ref"], r["date"], r["title"], r["document_id"]))
    return rows


# ---------------------------------------------------------------------------
# One statement's PDF
# ---------------------------------------------------------------------------
def fresh_row(page, call: Call, account_ref: str, year: str, document_id: str) -> Optional[dict]:
    """The statement's row as the list gives it now, by its docId, held to
    what a row of the list is held to (statement_row), or None."""
    for account in call.accounts:
        if account.get(call.account_key) != account_ref:
            continue
        answer = _post_list(page, call, _body_for(call, account, year))
        for row in answer.get("documentList") or []:
            if isinstance(row, dict) and row.get("docId") == document_id:
                try:
                    ok = statement_row(row, account, call.account_key,
                                       call.statements_category, year)
                except ValueError:
                    return None
                return row if ok is not None else None
    return None


def document_bytes(page, *, account_ref: str, date: str, document_id: str,
                   year: str = "") -> Tuple[Optional[bytes], str]:
    """One statement's PDF, asked for at its own row's address in the form
    the page's links came out of, and the day in the file name the bank
    gave it ("" when it gave none). (None, "") when its row is no longer
    listed. Raises NotThere, SessionExpired or NotLearned."""
    call = learned(page, form=True)
    if call.template is None and call.pdf is None:
        why, reason = not_learned_why(call.facts)
        raise NotLearned(why, call.facts, reason)
    if not (account_ref and document_id and date):
        return None, ""
    row = fresh_row(page, call, account_ref, year or date[:4], document_id)
    if row is None or row_date(row) != date:
        return None, ""
    if call.template is None:
        r = _ask_pdf(page, call.pdf, row)
        if r.get("status") != 200 or not r.get("b64"):
            return b"", ""
        return intake.decode(r["b64"]), date_in_file_name(r.get("cd") or "")
    url = fill(call.template, row)
    if not url or not is_safe_url(url) or (urlsplit(url).hostname or "").lower() != call.link_host:
        raise NotLearned("a statement's address did not come out where the page's own links are")
    try:
        r = intake.evaluate(page, _PDF_JS, url)
    except Exception as e:
        # A page gone mid-run, an answer over its limit, or a fetch the
        # browser refused. The run stops rather than fail every statement.
        raise ListCut("a statement could not be asked for in the page (%s)" % type(e).__name__)
    status = r.get("status") if isinstance(r, dict) else None
    if status in (401, 403) or not is_safe_url(r.get("url") or ""):
        raise SessionExpired("Bank of America answered %s" % status)
    if status != 200 or not r.get("b64"):
        return b"", ""
    return intake.decode(r["b64"]), date_in_file_name(r.get("cd") or "")


# ---------------------------------------------------------------------------
# Diagnose survey. Read-only and on the page the person left open. Nothing
# is followed or downloaded, the one press is the Statements heading when it
# is shut, no screenshot is taken, and every word goes through the redactor
# and then the word list that writes the file.
# ---------------------------------------------------------------------------
def _page_summary(page) -> dict:
    out = {"url": "", "title": ""}
    try:
        url = page.url or ""
        out["on_site"] = is_safe_url(url)
        # The path only. A query string or a fragment can carry a session
        # or an account's id.
        out["url"] = (redact(re.split(r"[?#]", url, maxsplit=1)[0]) if out["on_site"]
                      else "(not on bankofamerica.com)")
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


def learned_summary(call: Call) -> dict:
    """What was learned of the list call, as names and counts, never a
    value. Field names are the bank's own words and go through the word
    list that writes the file."""
    rows = [r for r in call.answer.get("documentList") or [] if isinstance(r, dict)]
    fields = sorted({k for r in rows for k in r})
    form_fields = sorted(set(re.findall(r"\x00(?:q:)?([^\x00]+)\x00", call.template or "")))
    return {"accounts": len(call.accounts), "years": len(call.years),
            "categories": len(call.answer.get("documentCategoryList") or []),
            "statements_category": bool(call.statements_category),
            "rows_on_the_page": len(rows), "row_fields": fields,
            "body_names": sorted(call.body), "headers_kept": len(call.headers),
            "pdf_form_learned": call.template is not None,
            "pdf_form_fields": form_fields, "pdf_url_kept": call.pdf is not None,
            **call.facts}


def survey(page, dwell_ms: int = 2000) -> dict:
    """What the page the person left open looks like, and on the statements
    page what its list call answers, downloading nothing. The page is
    reloaded once to hear the call, and its Statements heading opened when
    it is shut, the one press a run makes too."""
    report = {"pages": [], "responses": [], "mapped": True}
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:
        pass
    report["pages"].append(_page_summary(page))
    if on_statements_page(page):
        try:
            report["list"] = learned_summary(learn(page, press_link=False))
        except (NotThere, NotLearned, SessionExpired) as e:
            # Which way it stopped, by the name of the stop, and what the
            # page drew, as counts.
            report["list"] = dict(getattr(e, "facts", None) or {}, stopped=type(e).__name__)
    else:
        report["list"] = {"stopped": "NotThere"}
    return report
