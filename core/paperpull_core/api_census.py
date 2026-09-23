"""Which of the provider's own calls happened, and what came back.

Eleven of the forty eight apps drive a JSON API rather than a page. They
declare no selectors, so the selector census has nothing to say about
them and a failure file from one of them carries a page state and little
else. This is their half.

It listens rather than asking. Every response the page receives goes
past a Playwright listener, so it works whatever way an app makes its
call, an in-page fetch, a navigation, or a request the site's own
JavaScript made, and no app has to change how it calls anything.

WHAT COMES OUT

    the path       with anything id-shaped in it masked
    the method     GET, POST
    the status     404 is a different problem from 200 with nothing in it
    the kind       json, html, pdf
    the query      the names of the parameters, never their values
    the shape      the keys of a JSON answer, and the type of each value

THE SHAPE IS THE POINT, AND IT IS THE RISK

A maintainer repairing one of these apps needs the field names, because
an API that renamed `documents` to `items` looks from outside exactly
like an account with nothing in it. Those names are the provider's
schema, the same for every customer, so they carry nothing about whose
account it is.

Except when they do. An object keyed by account number is a thing that
exists, and there the keys *are* values. So a key that looks like an
identifier is masked the same way a path segment is, and no value is
ever kept, only the name of its type.

WHAT NEVER COMES OUT

No body, no header, no cookie, no query value, no host other than
whether it was the provider's. A response from anywhere but the
provider is counted and not described, because an advertiser's URL on a
bank's page is still a record of what somebody was doing.
"""
from __future__ import annotations

import re

from .failure import _count, _enum

# A path segment or a key that identifies somebody rather than something.
# A long run of digits, a hex blob, a uuid. Masked, because a path like
# /accounts/12345678/documents is structure and an account number in one
# breath, and the structure is the only half worth having.
_IDENTIFYING = re.compile(
    r"^(?:\d{4,}"                             # 12345678
    r"|[0-9a-f]{8,}"                          # a hex blob or a hash
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\d[A-Za-z0-9_-]{6,})$", re.I)

# What a body is, as a word.
_KINDS = (("json", ("json",)), ("pdf", ("pdf",)), ("html", ("html",)),
          ("xml", ("xml",)), ("text", ("text/plain",)),
          ("image", ("image/",)), ("stream", ("octet-stream",)))

_METHODS = frozenset(("get", "post", "put", "patch", "delete", "head",
                      "options"))

MAX_SEEN = 24          # entries kept, newest wins
MAX_BODIES = 30        # bodies read in one run, because each is a round trip
MAX_BODY_BYTES = 2_000_000
MAX_KEYS = 30
MAX_DEPTH = 4


def mask_token(token: str) -> str:
    """One path segment or key, kept or masked."""
    token = str(token or "")
    if len(token) > 60:
        return "#"
    return "#" if _IDENTIFYING.match(token) else token


def path_shape(url: str) -> str:
    """The path, with the parts that name a person taken out."""
    from urllib.parse import urlsplit
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return ""
    parts = [mask_token(p) for p in path.split("/") if p]
    return "/" + "/".join(parts[:12])


def query_keys(url: str) -> list:
    """The names of the parameters, never their values.

    A repair needs to know a call takes a year and a page. What year
    this person asked for is theirs."""
    from urllib.parse import parse_qsl, urlsplit
    try:
        pairs = parse_qsl(urlsplit(url or "").query, keep_blank_values=True)
    except ValueError:
        return []
    return sorted({mask_token(k)[:40] for k, _ in pairs})[:20]


def kind_of(content_type: str) -> str:
    ct = (content_type or "").lower()
    for word, needles in _KINDS:
        if any(n in ct for n in needles):
            return word
    return "other"


def shape_of(value, depth: int = 0):
    """The keys of a JSON answer and the type of each value.

    Never a value. A list becomes its length and the shape of its first
    entry, because a hundred documents have the same shape as one and
    the count is the part worth knowing."""
    if depth > MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:MAX_KEYS]:
            out[mask_token(k)[:40]] = shape_of(v, depth + 1)
        if len(value) > MAX_KEYS:
            out["..."] = "%d more key(s)" % (len(value) - MAX_KEYS)
        return out
    if isinstance(value, list):
        return ["%d item(s)" % len(value),
                shape_of(value[0], depth + 1) if value else None]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        # Its length is a fact about the answer's shape. Its content is
        # a fact about the account.
        return "string"
    return type(value).__name__


class Requests:
    """Every call the provider answered, as shapes and counts.

        seen = Requests(page, site.is_safe_url)
        seen.start()
        ...
        report["requests"] = seen.report()

    Nothing here may raise. It runs through an ordinary working run."""

    def __init__(self, page, is_safe_url=None, limit: int = MAX_SEEN):
        self.page = page
        self.limit = max(4, int(limit))
        self.seen: list = []
        self.counts = {"provider": 0, "elsewhere": 0, "bodies_read": 0,
                       "too_large": 0, "unreadable": 0}
        self._is_safe = is_safe_url or (lambda u: True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            self.page.on("response", self._on_response)
            self._started = True
        except Exception:
            pass

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception:
            pass
        self._started = False

    def _on_response(self, response) -> None:
        """Guarded whole. An exception here surfaces inside Playwright's
        event loop and would take a working run down with it."""
        try:
            self._record(response)
        except Exception:
            self.counts["unreadable"] = self.counts.get("unreadable", 0) + 1

    def _record(self, response) -> None:
        url = response.url or ""
        try:
            safe = bool(self._is_safe(url))
        except Exception:
            safe = False
        if not safe:
            # Counted, never described. An advertiser's address on a
            # bank's page is still a record of what somebody was doing.
            self.counts["elsewhere"] += 1
            return
        self.counts["provider"] += 1

        headers = {}
        try:
            headers = response.headers or {}
        except Exception:
            pass
        kind = kind_of(headers.get("content-type", ""))
        entry = {
            "path": path_shape(url)[:200],
            "status": _count(response.status),
            "kind": kind,
        }
        try:
            entry["method"] = _enum(response.request.method, _METHODS, "other")
        except Exception:
            entry["method"] = "other"
        keys = query_keys(url)
        if keys:
            entry["query_keys"] = keys
        try:
            size = int(headers.get("content-length") or 0)
        except (TypeError, ValueError):
            size = 0
        if size:
            entry["bytes"] = _count(size)

        if kind == "json" and self.counts["bodies_read"] < MAX_BODIES:
            if size > MAX_BODY_BYTES:
                self.counts["too_large"] += 1
                entry["shape"] = "not read, %d bytes" % _count(size)
            else:
                # A round trip to the browser, which is why it is capped.
                try:
                    entry["shape"] = shape_of(response.json())
                    self.counts["bodies_read"] += 1
                except Exception:
                    self.counts["unreadable"] += 1
                    entry["shape"] = "unreadable"

        self.seen.append(entry)
        while len(self.seen) > self.limit:
            self.seen.pop(0)

    def report(self) -> dict:
        return {"seen": list(self.seen), "counts": dict(self.counts),
                "limit": self.limit}


def summarize(report: dict) -> list:
    """What a reader should notice, in sentences."""
    said = []
    if not isinstance(report, dict):
        return said
    seen = [e for e in (report.get("seen") or []) if isinstance(e, dict)]
    counts = report.get("counts")
    if not isinstance(counts, dict):
        # Nobody watched, which is not the same as having watched and
        # seen nothing, and only one of those is worth a sentence.
        return said

    if not counts.get("provider"):
        if counts.get("elsewhere"):
            said.append("The page made %d request(s) and not one of them went "
                        "to the provider, so either the app never asked or it "
                        "asked somewhere this app does not recognise as the "
                        "provider's own." % _count(counts["elsewhere"]))
        else:
            said.append("The page made no requests at all while this ran.")
        return said

    bad = [e for e in seen if 400 <= (e.get("status") or 0) < 600]
    for e in bad[:4]:
        said.append("%s %s answered %d." % (e.get("method", "").upper(),
                                            e.get("path"), e["status"]))
        if e["status"] in (401, 403):
            said[-1] += " The session is probably over, or that call needs a header the app is not sending."
        elif e["status"] == 404:
            said[-1] += " The address has moved, or the thing asked for is not there."
        elif e["status"] == 429:
            said[-1] += " Too many requests, so slow the run down."

    empty = [e for e in seen
             if e.get("kind") == "json" and e.get("status") == 200
             and _looks_empty(e.get("shape"))]
    for e in empty[:3]:
        said.append("%s answered 200 with an empty list in it, which is an "
                    "account with nothing in it or a filter that excluded "
                    "everything, and those are different problems."
                    % e.get("path"))

    if not any(e.get("kind") == "json" for e in seen):
        said.append("Nothing the provider sent back was JSON, so this app's "
                    "API may have moved or the page is rendering on the "
                    "server now.")
    return said[:20]


def _looks_empty(shape) -> bool:
    """A shape whose every list is empty, anywhere in it."""
    if isinstance(shape, list) and shape:
        if str(shape[0]).startswith("0 item"):
            return True
        return any(_looks_empty(s) for s in shape[1:])
    if isinstance(shape, dict):
        return any(_looks_empty(v) for v in shape.values())
    return False
