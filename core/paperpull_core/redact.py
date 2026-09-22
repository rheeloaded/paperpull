"""What must never reach a diagnostic file.

A tester runs `diagnose`, reads the file it writes, and attaches it to a
public GitHub issue because this project told them to. Everything that
file says about their account passes through here first.

This used to live in each app's `*_site.py`, copied by hand as providers
were added, and it drifted. Seventeen apps carried it in three different
versions. Eleven had the current one. Five masked long digit runs and
nothing else, so a URL kept its query string, an amount stayed on screen
and the account holder's own name went through untouched. One had a
version of its own. A fix to any copy left the other sixteen alone, and
the point of this module is that there is now one copy to fix.

    from paperpull_core.redact import redact, set_private_words

    set_private_words([config.get("owner", "")])
    safe = redact(page.url)

What it removes, in order.

    a URL's query string      where a site keeps session and account state
    an email address          it identifies the person as surely as a name
    a greeting                "Welcome back, ALEX" names the person
    an id-shaped path segment "/accounts/d11-Kz9Rc8vQ/"
    an amount                 a balance or a payment, of no use in a survey
    a masked tail             "....1234", the last of an account number
    the owner's own name      given by the orchestrator, every part of it
    a long digit run          an account, a phone, a claim, a policy

None of this is a guarantee against a provider that prints something
unusual, which is why every app tells the tester to read the file before
they attach it. It is the floor, not the ceiling.
"""
from __future__ import annotations

import re

# An account, a phone, a claim or a policy number. Six is low enough to
# catch them and high enough to leave a year, a dollar amount or a count.
_ID_RE = re.compile(r"\d{6,}")

# An address identifies the person as surely as their name. Three of the
# newest apps already masked this in a redaction of their own, and the
# other nineteen did not, which is the drift this module exists to end.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# A URL's query string, where a site keeps session and account state.
_QUERY_RE = re.compile(r"(https?://[^\s\"'?#]+)\?[^\s\"'#]*")

# A path segment shaped like an id or a key, "/accounts/d11-Kz9Rc.../",
# ten or more characters with a letter and a digit in it.
_PATH_TOKEN_RE = re.compile(
    r"(?<=/)(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{10,}(?=[/?#]|$)")

# "Welcome, ALEX", "Hi Jane", "Good evening, Sam": a greeting names the
# person, and a survey has no use for the name.
_GREETING_RE = re.compile(
    r"\b((?:welcome(?:\s+back)?|hello|hi|hey|good\s+(?:morning|afternoon|evening)),?)"
    r"\s+(?!back\b)[A-Za-z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*)?", re.I)

# An amount is a balance or a payment, and a survey has no use for either.
_MONEY_RE = re.compile(r"[$€£]\s?-?\d[\d,]*(?:\.\d{2})?")

# A number after dots or stars is the tail of an account.
_MASKED_TAIL_RE = re.compile(r"([.*•xX]{2,}\s*)\d{2,}")

# The account holder's own name, given by the orchestrator from the
# config, so a heading or a profile button that shows it never reaches
# the file. A tester found his in one (#35).
_PRIVATE_WORDS: list = []

# Titles and suffixes are not names, and redacting them would turn every
# "Jr" and "II" on the page into [name].
_NOT_A_NAME = {"mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii"}


def set_private_words(words) -> None:
    """Words that must never reach a diagnostic file, the account holder's
    name in every part of two letters or more.

    Called once by the orchestrator before it surveys anything. Passing an
    empty list or None clears it, which is what an app with no owner set
    does, and the rest of the redaction still applies."""
    _PRIVATE_WORDS.clear()
    for w in words or []:
        for part in re.split(r"[\s,]+", str(w or "")):
            if len(part) >= 2 and part.lower() not in _NOT_A_NAME:
                _PRIVATE_WORDS.append(part)


def private_words() -> list:
    """What set_private_words is currently holding. For tests and for an
    app that wants to say in its own output how many it is guarding."""
    return list(_PRIVATE_WORDS)


def redact(text: str) -> str:
    """One string on its way into a diagnostic file."""
    text = _QUERY_RE.sub(lambda m: m.group(1) + "?...", text or "")
    text = _EMAIL_RE.sub("<email>", text)
    text = _GREETING_RE.sub(lambda m: m.group(1) + " [name]", text)
    text = _PATH_TOKEN_RE.sub("...", text)
    text = _MONEY_RE.sub("$x.xx", text)
    text = _MASKED_TAIL_RE.sub(lambda m: m.group(1) + "####", text)
    for word in _PRIVATE_WORDS:
        text = re.sub(re.escape(word), "[name]", text, flags=re.I)
    return _ID_RE.sub(lambda m: "#" * len(m.group(0)), text)

# ---------------------------------------------------------------------------
# Values, for the parts of a diagnostic file that describe a request
# ---------------------------------------------------------------------------
# A survey and a recording both want to say what a provider's API was
# asked and what came back, without carrying any of the answer. These say
# it as names and shapes. Seventeen apps had their own copy of the first
# of these and eleven had the other two.

_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def plain_word(v: str) -> bool:
    '''"STATEMENT", "LAST_90_DAYS", not an id, a token or a number.'''
    return bool(_WORD_VALUE_RE.match(v or "")) and sum(ch.isdigit() for ch in v) <= 3


def safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import urlsplit, parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url or "").query, keep_blank_values=True)
    except ValueError:
        return ""
    return "&".join("%s=%s" % (k[:30], v if plain_word(v) else "...")
                    for k, v in pairs[:20])


def shape_of(obj, depth: int = 0):
    """The shape of a JSON body, never its values. Keys are the signal, a
    balance is not."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: shape_of(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return ["list of %d" % len(obj), shape_of(obj[0], depth + 1) if obj else None]
    return type(obj).__name__
