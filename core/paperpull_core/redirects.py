"""Asking an address with the browser's cookies, one redirect at a time.

Playwright's own request client, page.request and page.context.request,
asks from outside the page. It sends every cookie the attached browser
holds for the host it asks, and the attached browser is the person's own
profile, so that can be any site they use. Left to itself it follows twenty
redirects and checks none of them. Measured on 2026-10-05 in Chromium 153
attached over CDP, with Playwright 1.62 and 1.63 alike. A provider at
localhost answered a document's address with a 302 to 127.0.0.1, and the
client asked 127.0.0.1 with the cookie the browser held for it and handed
back that host's PDF, which capture.fetch_pdf then kept. With
max_redirects=0 it handed back the 302 itself, Location and all, and asked
nothing more.

So no call into that client follows a redirect by itself. An address the
browser already got its document from is asked again with max_redirects=0,
since it answered once without one. A provider's link asked for the first
time may well be sent on, to the document on another of the provider's
hosts, say, so it is asked here. Every hop is asked with max_redirects=0,
and a redirect's Location is checked with the app's own guard before it is
asked. One the guard refuses is never asked, and the redirect itself is the
answer, which is not ok and holds no document, so every caller already
treats it as nothing.

core/tests/test_no_request_follows_a_redirect_off_the_allowlist.py finds
every call into that client and holds each one to max_redirects=0, and
only this module reads where a redirect points.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

log = logging.getLogger("paperpull.redirects")

# The answers that send a client on to another address.
REDIRECTS = (301, 302, 303, 307, 308)

# Playwright's own limit, so an app that never set one follows as many
# redirects on its provider's hosts as it always did. M&T, Amazon, FedEx
# and Stripe kept caps of three or five of their own, and still do.
HOPS = 20


class TooManyRedirects(Exception):
    """More redirects than the caller allows, every one of them to an
    address the guard allowed. Playwright raises "Max redirect count
    exceeded" for the same thing, and M&T reads it as a session that has
    ended, since that is what bounces its document requests."""


def get(client, url: str, is_safe_url, *, hops: int = HOPS, params=None, **kwargs):
    """What `url` answers when `client` asks it with the session's cookies,
    following a redirect only to an address `is_safe_url` allows.

    `client` is Playwright's page.request or page.context.request, and
    `is_safe_url` the app's own guard. Every hop is asked with
    max_redirects=0. A redirect's Location is read against the address that
    sent it and asked only when the guard allows it, and the guard is asked
    about the first address too. A redirect the guard
    refuses, or one that says nowhere, is handed back as the answer. More
    than `hops` redirects raise TooManyRedirects. `params` go with the first
    ask only, since a Location is a whole address, and anything else in
    `kwargs`, a timeout say, goes with every ask. A max_redirects among them
    is refused by Python itself, since every ask names its own."""
    if not is_safe_url(url):
        raise ValueError("refusing to ask an address off the app's own hosts")
    first = {"params": params} if params else {}
    for _ in range(hops + 1):
        resp = client.get(url, max_redirects=0, **first, **kwargs)
        first = {}
        if resp.status not in REDIRECTS:
            return resp
        where = (resp.headers.get("location") or "").strip()
        if not where:
            return resp
        # Read against the address asked, which with max_redirects=0 is the
        # answer's own, `params` and all.
        onward = urljoin(resp.url or url, where)
        if not is_safe_url(onward):
            log.info("a redirect led off the app's own hosts and was not followed")
            return resp
        _let_go(resp)
        url = onward
    raise TooManyRedirects("more than %d redirects" % hops)


def _let_go(resp) -> None:
    """Free a redirect's answer once its Location has been read."""
    try:
        resp.dispose()
    except Exception:
        pass
