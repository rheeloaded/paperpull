"""Deciding whether an address belongs to the provider at all.

Every app refuses to open a URL that is not its provider's. That check was
written forty-eight times and drifted into ten different answers to the one
question. Twenty-nine apps matched subdomains and never looked at the port.
Five looked at the port. Six insisted on an exact host, so a provider that
moved a page to a new subdomain would break them. Some stripped a trailing
dot from the host, some did not, so `chase.com.` was refused in one app and
allowed in another.

None of that was reachable as an attack, because every version still ended
at the app's own allowlist. It was simply ten answers to one question, and
the next provider added an eleventh. A fix to any of them fixed one.

So the logic lives here and the hosts stay with the app, which is the part
that really is per-provider. An app that must not follow subdomains says so
with `subdomains=False` rather than by writing its own parser.

    from paperpull_core.urls import is_safe_url
    is_safe_url(url, ALLOWED_HOSTS)                    # and its subdomains
    is_safe_url(url, ALLOWED_HOSTS, subdomains=False)  # these hosts exactly
    host_matches(host_of(url), DOMAINS)                # a host, any scheme
    join(page.url, href)                               # a link, as a browser reads it

Python and a browser do not read every address alike. A browser takes a
backslash for a slash, skips any run of slashes before a host, and drops
tabs and newlines, and urllib does the first two differently. An address
where that matters is never the provider's here (`_head`, `join`). So an
app compares a host with host_matches, never `host.endswith("." + domain)`
of its own, and resolves a link with join, never urljoin
(core/tests/test_every_host_check_goes_through_urls.py).

Everything here fails closed. An address this cannot make sense of is not
safe, and an empty allowlist matches nothing.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Iterable
from urllib.parse import urljoin, urlsplit

# The only shape of host ever compared. Labels of letters, digits, hyphens
# and underscores, joined by dots. Python and a browser end the host of an
# address in different places when it holds a backslash. urlsplit reads
# `https://evil.example\.chase.com/x` as the host `evil.example\.chase.com`,
# which ends in `.chase.com`, while Chromium and Playwright's own request
# client read the backslash as a slash and ask evil.example. So a host of
# any other shape matches nothing, whatever it ends in. That fails closed,
# since no provider's host needs anything else.
_NAME = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*")

# What a browser takes off both ends of an address, and what it drops
# from anywhere in it, before reading it at all.
_ENDS = "".join(chr(c) for c in range(0x21))
_DROPPED = re.compile(r"[\t\n\r]")

# A link a browser reads as naming a host of its own that urljoin reads as
# a path on the page's host. A run of three or more slashes, alone or after
# a scheme (`///evil.example/x`, `https:///evil.example/x`), or a scheme a
# browser gives a host to, written without its two slashes, when the page
# is on another scheme (`http:evil.example` from an https page).
_SLASHES = re.compile(r"(?:[a-z][a-z0-9+.-]*:)?/{3,}", re.I)
_SPECIAL = re.compile(r"(https?|wss?|ftp|file):(?!//)", re.I)


def _head(url: str) -> str:
    """An address as a browser starts to read it, up to its query or
    fragment, which is where a backslash stops mattering."""
    url = _DROPPED.sub("", url or "").strip(_ENDS)
    return re.split(r"[?#]", url, maxsplit=1)[0]


def _host(name: str) -> str:
    """An allowlisted host in the one form comparisons happen in, however
    untidily it was written. A trailing dot is the DNS root and names the
    same host, so `chase.com.` and `chase.com` must not be two different
    answers."""
    return (name or "").strip().lower().rstrip(".")


def _tested(host: str) -> str:
    """A host being asked about, lowercased and with one trailing dot off,
    and nothing else taken away, so that a space or a second dot a browser
    would keep makes it no plain name at all."""
    host = (host or "").lower()
    return host[:-1] if host.endswith(".") else host


def host_of(url: str) -> str:
    """The host of an address, in the form comparisons happen in, or "" when
    it has none, cannot be read, holds a backslash before its query
    (`https://evil.example\\@chase.com/` is evil.example to a browser and
    chase.com to urlsplit), or is anything but a plain name."""
    if "\\" in _head(url):
        return ""
    try:
        host = _tested(urlsplit(url or "").hostname or "")
    except ValueError:
        return ""
    return host if _NAME.fullmatch(host) else ""


def host_matches(host: str, allowed_hosts: Iterable[str], *, subdomains: bool = True) -> bool:
    """True when this host is one of these, or, with subdomains left on, a
    host under one of them, by label and never by string prefix. A host
    that is not a plain name matches nothing, whatever it ends in.

    Every check of a host by its ending asks this rather than writing its
    own (core/tests/test_every_host_check_goes_through_urls.py)."""
    host = _tested(host)
    if not host or not _NAME.fullmatch(host):
        return False
    for allowed in allowed_hosts:
        a = _host(allowed)
        if not a:
            continue
        if host == a or (subdomains and host.endswith("." + a)):
            return True
    return False


def join(base: str, href: str) -> str:
    """A link resolved against the page it is on, the way urljoin does, or
    "" when a browser could resolve it to another place. That is a link
    with a backslash before its query, a run of three or more slashes
    before a host, or a scheme with no slashes on a page of another scheme.
    Checking urljoin's answer and then pressing the link itself would check
    one address and go to another."""
    head = _head(href)
    if "\\" in head or _SLASHES.match(head):
        return ""
    special = _SPECIAL.match(head)
    if special:
        try:
            scheme = urlsplit(base or "").scheme
        except ValueError:
            return ""
        if special.group(1).lower() != scheme.lower():
            return ""
    try:
        return urljoin(base or "", _DROPPED.sub("", href or "").strip(_ENDS))
    except ValueError:
        return ""


def is_safe_url(url: str, allowed_hosts: Iterable[str], *, subdomains: bool = True) -> bool:
    """True only for an https URL on one of these hosts.

    Refused: any other scheme, a missing host, a user or password in the
    URL (`https://provider.com@evil.example`), any port other than 443, a
    backslash before the query (`https://chase.com/\\evil.example/`), a
    host that is not a plain name (`https://evil.example\\.chase.com/`), and
    any host that is not in the allowlist. With subdomains left on, a host
    under an allowed one is allowed too, by label and never by string
    prefix, so `notchase.com` cannot pass for `chase.com`.
    """
    if "\\" in _head(url):
        return False
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    if parts.username or parts.password:
        return False
    try:
        # Reading .port parses it, and an out-of-range one raises rather
        # than answering. An address we cannot read the port of is refused.
        port = parts.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    return host_matches(parts.hostname or "", allowed_hosts, subdomains=subdomains)


# A host's label as a refusal line names it, letters, digits and hyphens.
_PLAIN_LABEL = re.compile(r"[a-z0-9-]{1,63}")
# A label that reads like an account's number or a token, a run of six
# digits, as paperpull_core.redact reads an id, or ten letters and digits
# mixed, which leaves as its shape.
_ID_IN_LABEL = re.compile(r"\d{6,}|(?=[a-z0-9]{10})(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{10,}")


def _label_said(label: str, keep: bool = True) -> str:
    """One label of a host as a refusal line says it. A plain label is kept,
    and any other leaves as its shape, every letter as a and every digit as
    9 (paperpull_core.words), so a page's words or an id in a host leave
    nothing of themselves but their length. A host with any label that is
    not plain is no host name but words, and each of its labels leaves as
    its shape (keep False)."""
    if keep and _PLAIN_LABEL.fullmatch(label) and not _ID_IN_LABEL.search(label):
        return label
    return "".join("9" if ch.isdigit() else "a" if ch.isalpha() else "-" if ch == "-" else "_"
                   for ch in label[:63])


def where_it_leads(url: str) -> str:
    """Where an address leads, for the line that says one was refused, its
    scheme, host and any port, and never its path, query or fragment, which
    can carry an account's ids, nor a user or password in it. A label of the
    host that is not a plain name, or that carries an id or a token, leaves
    as its shape. Nothing is asked of the address, it is only read. A
    refusal that said nothing of where left nothing to tell a guard working
    from a page gone wrong."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return "an address that could not be read"
    scheme = (parts.scheme or "").lower()
    if not scheme:
        return "an address with no scheme"
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        host, port = parts.hostname, None
    if not host:
        return "an address with no host (%s:)" % scheme[:20]
    if ":" in host:
        try:
            # Its zone, after %, is any text at all, and is left out.
            said = "[%s]" % ipaddress.IPv6Address(host.split("%", 1)[0]).compressed
        except ValueError:
            said = _label_said(host, keep=False)
    else:
        labels = _host(host).split(".")[:10]
        keep = all(_PLAIN_LABEL.fullmatch(label) for label in labels)
        said = ".".join(_label_said(label, keep) for label in labels)
    return "%s://%s%s" % (scheme[:20], said[:120], ":%d" % port if port else "")
