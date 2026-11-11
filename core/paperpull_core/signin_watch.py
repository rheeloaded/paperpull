"""Whether the person has finished signing in, from their window's address.

Pressing Open sign-in window used to leave the person to come back to the
panel and press Get new. The panel now watches the sign-in window and starts
the run itself once the person has got past the sign-in pages.

WHAT IS LOOKED AT

The address and the title of each tab, as the browser's own debugging port
on this computer lists them (/json/list). Nothing more. No page is opened,
read or touched, no password field is looked for, and nothing goes to the
provider's site. Neither the address nor the title is written anywhere or
sent to the page, which hears only the answer.

Every app can say whether it is looking at a sign-in page, in its own
looks_signed_out, but that asks the page for a password field, which is
reading the page, and each app has its own copy. What they all share, in
data, is one list of the addresses sign-in pages have (LOGIN_URL_MARKERS)
and one list of the provider's own addresses (URLS). So those two lists are
what is used here, and one rule serves every provider.

THE RULE

A tab is signed in when it is on the provider's own site, it is not on a
sign-in page, and it is somewhere only signing in gets a person: at one of
the provider's own addresses for an account, or anywhere else after having
been on a sign-in page. It has to stay there for a few looks, since a
sign-in passes through several addresses on its way.

A sign-in page, for this purpose, is one the provider's own list names,
one whose address or title has the words of a sign-in or of a second step
in it (a code, a verification, a security check), or the address the
window opened at. Being wrong in that direction costs nothing but the
press of Get new that was always there, so the words are many.

A provider this cannot be worked out for has no plan (plan_for), and its
sign-in goes on as it always did. The rule cannot see a sign-in that
changes nothing in the address, such as a form that replaces itself on one
page, and the wait then ends by itself after a while.

A WRONG ANSWER

Wrong "signed in" is meant to be rare and is harmless. The run starts, its
own check of the page finds nobody signed in, and it stops as it always
has, with the page saying to sign in. It is one run. Only a person pressing
Open sign-in window ever starts another wait.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from .characters import whole_json
from .run_reporting import MARK_ENV, marked

# The line a run under the panel prints once the window is open. It carries
# the run's mark as a result line does (gui/run_result.sign_in_plan).
PLAN_PREFIX = "PAPERPULL_SIGN_IN_PLAN "

# How many looks in a row a tab has to stay at one address. The panel looks
# every two seconds or so.
SETTLED_LOOKS = 3

# What a tab is, on the provider's site.
SIGNING_IN, STARTED_HERE, AN_ACCOUNT_PAGE, SOMEWHERE_ELSE = (
    "signing in", "where the window opened", "an account page", "somewhere else on the site")

# The words of a sign-in or of a second step, in an address. Those of a
# provider's own list come on top of these.
_ADDRESS_WORDS = re.compile(
    r"(?<![a-z0-9])(?:mfa|2fa|otp|sso|saml|oauth2?|captcha)(?![a-z0-9])"
    r"|log[-_]?(?:in|on|out|off)|sign[-_]?(?:in|on|out|up)"
    r"|two[-_]?(?:factor|step)|2[-_]?step|multi[-_]?factor"
    r"|verif(?:y|ication)|authenticat|challenge|passcode|security[-_]?code"
    r"|one[-_]?time|step[-_]?up|forgot|reset[-_]?password|password|recover"
    r"|enroll|register|checkpoint|interstitial|trust(?:ed)?[-_]?device"
    r"|session[-_]?(?:expired|timeout|ended?)|timed?[-_]?out")

# The same in a page's title, which a person reads, so in the words they read.
_TITLE_WORDS = re.compile(
    r"sign[- ]?(?:in|on)|log[- ]?(?:in|on)|signed out|logged out"
    r"|verif(?:y|ication)|two[- ]?(?:step|factor)|2[- ]?step|multi[- ]?factor"
    r"|security (?:code|check)|one[- ]?time|passcode|authenticat|confirm your identity"
    r"|confirm it.s you|verify it.s you|challenge|captcha|forgot|reset your password|create (?:an )?account"
    r"|enroll|session (?:has )?expired|timed out|access denied|just a moment|attention required"
    r"|are you (?:a robot|human)|pardon our interruption")


def _parts(url):
    """(host, path, fragment) of an address, in lower case, the path with no
    trailing slash, or None for one that is not a web page."""
    try:
        s = urlsplit(url or "")
        if s.scheme not in ("http", "https") or not s.hostname:
            return None
        return s.hostname.lower(), s.path.rstrip("/").lower(), s.fragment.lower()
    except ValueError:
        return None


def _same_page(a, b) -> bool:
    """One page, whatever the query of either says. A fragment counts, since
    a page that routes by its fragment says where it is there."""
    pa, pb = _parts(a), _parts(b)
    return pa is not None and pa == pb


def _site(host: str) -> str:
    """The last two parts of a host, a provider's own site."""
    return ".".join(host.split(".")[-2:])


def _is_sign_in_address(url: str, markers: Iterable[str]) -> bool:
    low = (url or "").lower()
    return any(m and m.lower() in low for m in markers) or bool(_ADDRESS_WORDS.search(low))


def plan_for(start: str, urls: dict, markers: Iterable[str]) -> Optional[dict]:
    """What to watch for one provider, or None when this rule cannot tell.

    start is the address the window opened at, urls the app's URLS and
    markers its LOGIN_URL_MARKERS. Whether a provider can be told is
    answered from those alone: its window opened on a page that is a
    sign-in page by its address, or it names an account page of its own
    somewhere other than where the window opened."""
    if _parts(start) is None or not isinstance(urls, dict):
        return None
    markers = [str(m).lower() for m in markers if isinstance(m, str) and m]
    others = {k: v for k, v in urls.items()
              if k not in ("login", "home") and isinstance(v, str) and _parts(v)}
    hosts_of_others = {_parts(v)[0] for v in others.values()}
    start_host = _parts(start)[0]
    inside = [v for v in others.values() if not _is_sign_in_address(v, markers)]
    home = urls.get("home")
    if isinstance(home, str) and _parts(home) and (_parts(home)[1] or _parts(home)[0] in hosts_of_others) \
            and not _is_sign_in_address(home, markers):
        inside.append(home)
    # Other hosts the account pages are on, which show nothing of a sign-in
    # themselves. The host the window opened at and any host a sign-in page
    # is on are for paths alone, and so is a www. host, the public site's.
    login = urls.get("login")
    login_host = _parts(login)[0] if isinstance(login, str) and _parts(login) else None
    hosts = sorted(h for h in {_parts(v)[0] for v in inside} - {start_host, login_host} if not h.startswith("www."))
    # A root page says nothing, since every site has one.
    deep = [v for v in inside if _parts(v)[1] or _parts(v)[2]]
    dedicated = _is_sign_in_address(start, markers)
    if not (dedicated or hosts or deep):
        return None
    return {"start": start, "markers": markers, "inside": sorted(set(inside)), "hosts": hosts,
            "dedicated": dedicated, "start_is_inside": any(_same_page(start, v) for v in deep)}


def _place(url: str, title: str, plan: dict) -> Optional[str]:
    """Where a tab is, or None when it says nothing about this sign-in:
    another site, or a page still loading with no title yet."""
    parts = _parts(url)
    if parts is None:
        return None
    host, path, fragment = parts
    sites = {_site(_parts(plan["start"])[0])} | {_site(_parts(v)[0]) for v in plan["inside"]}
    if _site(host) not in sites:
        return None
    if _is_sign_in_address(url, plan["markers"]) or _TITLE_WORDS.search((title or "").lower()):
        return SIGNING_IN
    if not (title or "").strip():
        return None
    if _same_page(url, plan["start"]):
        return STARTED_HERE
    if host in plan["hosts"]:
        return AN_ACCOUNT_PAGE
    for v in plan["inside"]:
        h, p, f = _parts(v)
        if h == host and ((p and (path == p or path.startswith(p + "/")))
                          or (f and path == p and (fragment == f or fragment.startswith(f + "/")))):
            return AN_ACCOUNT_PAGE
    return SOMEWHERE_ELSE


class Watch:
    """One wait for one sign-in. look() is given the tabs each time, and
    says True once the person has got past the sign-in pages."""

    def __init__(self, plan: dict):
        self.plan = plan
        # A window that opened on a sign-in page has already been on one.
        self.saw_sign_in = bool(plan.get("dedicated"))
        self._last = None
        self._held = 0

    def look(self, tabs: Iterable[dict]) -> bool:
        good, signing_in = None, False
        for tab in tabs:
            url, title = str(tab.get("url") or ""), str(tab.get("title") or "")
            place = _place(url, title, self.plan)
            if place == SIGNING_IN:
                signing_in = True
                if not _same_page(url, self.plan["start"]):
                    self.saw_sign_in = True
            elif good is None and (place == AN_ACCOUNT_PAGE or (self.saw_sign_in and (
                    place == SOMEWHERE_ELSE or (place == STARTED_HERE and self.plan.get("start_is_inside"))))):
                good = url
        # A tab on an account page beside one still signing in is most often
        # a tab left over from before, and says nothing.
        if signing_in or good is None:
            self._last, self._held = None, 0
            return False
        here = _parts(good)
        if here != self._last:
            self._last, self._held = here, 0
        self._held += 1
        return self._held >= SETTLED_LOOKS


def read_tabs(port) -> Optional[List[dict]]:
    """The address and title of each page the browser on this debugging port
    has open, or None when no browser answers there. On this computer only."""
    import urllib.request
    from .browser import open_local
    try:
        with open_local(urllib.request.Request("http://127.0.0.1:%d/json/list" % int(port)), timeout=3) as r:
            pages = whole_json(json.load(r))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(pages, list):
        return None
    return [{"url": str(p.get("url") or ""), "title": str(p.get("title") or "")}
            for p in pages if isinstance(p, dict) and p.get("type") == "page"]


def _this_runs_site():
    """The app's own *_site module, the one this run imported, or None."""
    found = [m for name, m in list(sys.modules.items())
             if name.endswith("_site") and isinstance(getattr(m, "URLS", None), dict)]
    return found[0] if len(found) == 1 else None


def announce(start: str) -> None:
    """Under the panel, print what to watch for this sign-in on a line of
    its own that only the panel reads. A run from a terminal prints nothing,
    and nothing that goes wrong here is the reason a sign-in does not open."""
    mark = os.environ.get(MARK_ENV, "")
    if not mark:
        return
    try:
        site = _this_runs_site()
        if site is None:
            return
        # A first shell of a provider, whose site says it is not mapped yet,
        # downloads nothing, so no run follows its sign-in. A Get new started
        # here would only stop and leave the account offering Continue. The
        # step after its sign-in is a recording, which the person starts.
        if getattr(site, "NOT_MAPPED", ""):
            return
        plan = plan_for(start, site.URLS, getattr(site, "LOGIN_URL_MARKERS", ()) or ())
        if plan is not None:
            print(marked(PLAN_PREFIX, plan), flush=True)
    except Exception:
        return
