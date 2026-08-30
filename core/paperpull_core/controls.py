"""Deciding whether a control on the page may be touched at all.

Every app here is read-only, and the hard part of that promise is not the
downloading, it is the small number of places where the app has to interact
with the page to reach a document. A year picker has to be set. An accordion
has to be opened. Those are the moments where a mistake stops being a bug and
becomes something that touched the user's money.

This module exists because that judgement was written three times, in three
apps, and the third copy was the only one that got it right. The Ally and
Chase apps refused a control if it belonged to a money-movement widget, which
is the obvious danger. Neither considered that a control might belong to a
SIGN-IN form, so when a wrong URL guess landed one of them on a public page,
the account-picker lookup happily matched a login dropdown and set a value on
it. Nothing was submitted and no credential was touched, but selecting inside
a login form is not reading, and reading is all these tools do.

An app declares its own provider vocabulary and passes it in. Everything that
is true of every provider lives here, so the next app inherits the lesson
instead of rediscovering it.

TWO RULES WORTH KEEPING IN MIND WHEN EDITING THIS
-------------------------------------------------
1. It fails CLOSED. An identity that could not be read is unsafe, not safe.
   The reason is that an unreadable identity is exactly what a detached or
   mid-navigation element looks like.
2. It must not get so broad that it refuses the pickers an app genuinely
   needs. A guard that refuses the year picker does not announce itself. It
   makes discovery return nothing, and an empty run looks like an empty
   account. Both directions are tested.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Optional, Pattern

log = logging.getLogger("paperpull_core.controls")

# Anything belonging to a widget that moves money. The account-shaped names
# matter as much as the verbs: Ally's dashboard carries a transfer widget
# whose <select id="fromAccount"> is structurally identical to a statements
# picker, and only its identity tells them apart.
MONEY_CONTROL_RE = re.compile(
    r"(from|to|source|destination|target)\s*_?-?account|"
    r"transfer|payment|pay\b|bill|deposit|withdraw|zelle|wire|remit|"
    r"send\s*money|move\s*money|recipient|payee|amount|frequency|schedule",
    re.I)

# Anything belonging to a sign-in or registration form. Refused outright, and
# not because it moves money, because it does not.
AUTH_CONTROL_RE = re.compile(
    r"log[\s_-]?(in|on)|sign[\s_-]?(in|on|up)|signin|logon|"
    r"authenticat|credential|register|enroll(ment)?\b|"
    r"username|user[\s_-]?id|password|passcode|remember\s*me", re.I)

# Every name a control answers to. The enclosing form and the heading of the
# card it sits in are the parts that matter: an element's own id is often
# meaningless ("select-2"), while the form around it says "login-form".
IDENTITY_JS = r"""el => {
  const attrs = ['id','name','aria-label','placeholder','data-testid',
                 'data-track-name','data-cy','title'];
  const bits = attrs.map(a => el.getAttribute(a) || '');
  const form = el.closest('form');
  if (form) bits.push(form.id || '', form.getAttribute('name') || '',
                      form.getAttribute('aria-label') || '',
                      form.className || '');
  const sect = el.closest("section, [role='region'], [class*='card'], [class*='Card'], " +
                          "[class*='widget'], [class*='Widget'], [class*='module'], " +
                          "[class*='login'], [class*='signin']");
  if (sect) {
    bits.push(sect.getAttribute('aria-label') || '', sect.className || '');
    const h = sect.querySelector('h1,h2,h3,h4,legend');
    if (h) bits.push((h.innerText || '').slice(0, 60));
  }
  const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  if (lbl) bits.push((lbl.innerText || '').slice(0, 60));
  return bits.filter(Boolean).join(' | ');
}"""


def control_identity(loc) -> str:
    """Every name this control answers to, or an empty string if it could not
    be read. An empty string is treated as unsafe by the checks below."""
    try:
        return loc.evaluate(IDENTITY_JS) or ""
    except Exception:
        return ""


def is_forbidden_context(identity: str,
                         forbidden_re: Optional[Pattern] = None,
                         extra_res: Iterable[Pattern] = (),
                         options: Iterable[str] = ()) -> bool:
    """True when a control must not be read OR written, for any reason.

    `forbidden_re` is the app's own provider vocabulary, and `extra_res` is for
    anything more it wants to add, such as a product picker whose OPTIONS name
    accounts rather than documents. `options` are the visible option labels,
    checked against the same patterns, because a picker sometimes only reveals
    what it is through what it offers.
    """
    if not identity:
        return True
    if MONEY_CONTROL_RE.search(identity) or AUTH_CONTROL_RE.search(identity):
        return True
    if forbidden_re is not None and forbidden_re.search(identity):
        return True
    for rx in extra_res:
        if rx.search(identity):
            return True
    for opt in options:
        for rx in (*extra_res,):
            if rx.search(opt or ""):
                return True
    return False


def safe_selects(page, forbidden_re: Optional[Pattern] = None,
                 signed_out=None, extra_res: Iterable[Pattern] = (),
                 limit: int = 12):
    """Yield (locator, identity) for the <select> elements safe to touch.

    `signed_out` is the app's own check. If it says this is not an application
    page, nothing here is touched at all, whatever the individual controls
    call themselves. A wrong URL guess is an ordinary thing to happen on a
    first probe. Treating whatever it lands on as though it were the app is
    what turns that into a safety problem.
    """
    try:
        if signed_out is not None and signed_out(page):
            log.info("refusing every control: this is not a signed-in page")
            return
    except Exception:
        return
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        if is_forbidden_context(identity, forbidden_re, extra_res):
            log.info("refusing dropdown: %s", identity[:120])
            continue
        yield s, identity


def describe_selects(page, forbidden_re: Optional[Pattern] = None,
                     extra_res: Iterable[Pattern] = (),
                     limit: int = 12) -> List[dict]:
    """Every <select> with its identity and the guard's verdict.

    Diagnostic only. It reads and never sets anything. If a real document
    picker is ever refused, this is where you will see why.
    """
    out: List[dict] = []
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return out
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        out.append({
            "identity": identity[:200],
            "refused": is_forbidden_context(identity, forbidden_re, extra_res),
        })
    return out


# Control labels that COMMIT something, as opposed to naming a document.
# Deliberately verb-led. A review found each app matching only bare verb stems,
# so "Save Changes", "Document Removal" and "Loss Mitigation Application"
# walked through every one of them.
#
# Equally deliberately this holds no money NOUNS. "Pay Statement", "Detailed
# Bill PDF" and "Trade Confirmation" are documents, and an earlier attempt that
# included those words refused real downloads in five apps.
#
# The word boundaries are load-bearing. Without the \b on "edit" this also
# matches "credit", and "Credit Card Statement" must stay downloadable.
SETTINGS_CONTROL_RE = re.compile(
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing|al)\b|\bdelet(e|es|ed|ing|ion)\b|"
    r"^\s*save\s*$|\bsave\s+(changes?|settings?|preferences?|profile)\b|"
    r"\bsettings?\b|\bpreferences?\b|\bmanage\b|"
    r"\bset\s+up\b|\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|"
    r"\bturn\s+(on|off)\b|\bopt\s*(in|out)\b|"
    r"\bconsent\b|\bauthoriz(e|es|ed|ing|ation)\b|"
    r"\bcertif(y|ies|ied|ication)\b|\bbeneficiar(y|ies)\b|"
    r"\bwithholding\b|\bautopay\b|\bauto-pay\b|"
    r"\bappl(y|ies|ied|ication)\b|\bplace\s+order\b|\brebalance\b|"
    r"\breallocate\b|\bliquidat(e|es|ed|ing|ion)\b|"
    r"\bbuy\b|\bsell\b|\bschedule\s+(a\s+)?(payment|transfer)\b",
    re.I)
