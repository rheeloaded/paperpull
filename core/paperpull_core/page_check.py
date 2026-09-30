"""Whether the page in front of an app is the purchase it is about to save.

A receipt app opens a purchase's page and prints it. The check on the saved
file asks whether the file names the purchase, and since 2026-09-29 the
provider's own name no longer counts. A page can still name the purchase
without being its receipt. GitHub's payment history shows each payment's
own date, amount and id, so the history printed for one payment names that
payment, and was kept as its receipt. The order list of any shop does the
same, and so does another purchase's page once its facts have been read
into this purchase by mistake, which is what extract_details does on a
wrong page.

So the page is checked BEFORE it is printed, the way Best Buy reads the
number on its details page and refuses a page that names another. Two
things are asked, each app answering from what its provider shows.

    its address   the page is still at this purchase's own address, which
                  names the purchase in its path or in the one query
                  parameter the provider keys it on. A sign-in page names
                  it only in its return address, and that never counts.
    its number    the number the page prints for its purchase is this
                  purchase's, and no other purchase's number is printed.
                  A list prints several, another purchase's page prints
                  its own.

An app compares against the number the purchase was LISTED under, never
one read from the page, since a wrong page read first writes its own facts
into the purchase and would then agree with itself.

A refusal is not a failure to be quiet about. Nothing is saved under the
purchase's name, the purchase is left for the next run, and the run
reports it as a wrong document, which is the loud outcome. The reasons are
fixed words, because they reach the record, the console and a failure
file a tester may attach to a public issue.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, unquote, urlsplit

# Why a page is not this purchase's, in fixed words.
NOT_ITS_ADDRESS = "the page is not at this purchase's address"
NAMES_ANOTHER = "the page names a different purchase"
NAMES_NONE = "the page names no purchase"
IS_THE_LIST = "the page is the order list"

_NOT_ALNUM = re.compile(r"[^0-9A-Za-z]")


def plain(number) -> str:
    """A purchase number with only its letters and digits, upper case, so
    Walmart's "1000000-00000003" and the "100000000000003" it is keyed on
    are one number, and Gap's ids compare whatever their case."""
    return _NOT_ALNUM.sub("", str(number or "")).upper()


def address_names(url: str, number: str, query: Optional[str] = None) -> bool:
    """True when the address names this purchase.

    Its path has to hold the number as a segment of its own, or, given
    `query`, the query parameter of that name (in any case) has to be it.
    No other part of the address counts. A sign-in page carries the page
    it came from in its query, the purchase's own address included, and a
    number found there says nothing about the page."""
    own = plain(number)
    if not own:
        return False
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    for segment in parts.path.split("/"):
        if plain(unquote(segment)) == own:
            return True
    if query:
        for name, value in parse_qsl(parts.query, keep_blank_values=True):
            if name.lower() == query.lower() and plain(value) == own:
                return True
    return False


def same_address(here: str, there: str) -> bool:
    """True when `here` is the address `there`, as a provider might still
    write it. The scheme, the case of the host, a trailing slash and query
    parameters added along the way are allowed to differ. The host, the
    path and every query parameter `there` has are not, and neither is its
    fragment when it has one, since a page that routes by its fragment
    names its purchase there."""
    try:
        a, b = urlsplit(here or ""), urlsplit(there or "")
    except ValueError:
        return False
    if not b.netloc or (a.hostname or "").lower() != (b.hostname or "").lower():
        return False
    if a.port != b.port:
        return False
    if a.path.rstrip("/") != b.path.rstrip("/"):
        return False
    have = parse_qsl(a.query, keep_blank_values=True)
    if any(pair not in have for pair in parse_qsl(b.query, keep_blank_values=True)):
        return False
    return not b.fragment or a.fragment == b.fragment


def names_only(shown: Iterable[str], number: str) -> str:
    """"" when the page's numbers are all this purchase's and there is at
    least one, else the reason it is not this purchase's page."""
    own = plain(number)
    seen = {plain(s) for s in shown if plain(s)}
    if not seen:
        return NAMES_NONE
    if seen != {own}:
        return NAMES_ANOTHER
    return ""


_MEDIA_NOW = "() => matchMedia('print').matches ? 'print' : 'screen'"


def page_text(page, media: str = "screen", timeout_ms: int = 8000) -> str:
    """The page's text as `media` lays it out, "screen" or "print".

    Which one matters. Walmart's receipt is print-only, so its number is on
    the printed page and may not be on the screen, and a site can hide its
    heading from print. It also cannot be left to chance, because printing
    a page leaves the tab in print media for the rest of the run, so an
    app's second purchase is read in print when its first was read on
    screen. The page is laid out as asked, read, and put back the way it
    was. "" when the page cannot be read at all."""
    try:
        before = page.evaluate(_MEDIA_NOW)
    except Exception:
        before = None
    changed = False
    try:
        if before != media:
            page.emulate_media(media=media)
            changed = True
        return page.locator("body").inner_text(timeout=timeout_ms) or ""
    except Exception:
        return ""
    finally:
        if changed:
            try:
                page.emulate_media(media="print" if before == "print" else "null")
            except Exception:
                pass
