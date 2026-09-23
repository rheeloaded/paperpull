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

Everything here fails closed. An address this cannot make sense of is not
safe, and an empty allowlist matches nothing.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit


def _host(name: str) -> str:
    """A host in the one form comparisons happen in. A trailing dot is the
    DNS root and names the same host, so `chase.com.` and `chase.com` must
    not be two different answers."""
    return (name or "").strip().lower().rstrip(".")


def is_safe_url(url: str, allowed_hosts: Iterable[str], *, subdomains: bool = True) -> bool:
    """True only for an https URL on one of these hosts.

    Refused: any other scheme, a missing host, a user or password in the
    URL (`https://provider.com@evil.example`), any port other than 443, and
    any host that is not in the allowlist. With subdomains left on, a host
    under an allowed one is allowed too, by label and never by string
    prefix, so `notchase.com` cannot pass for `chase.com`.
    """
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
    host = _host(parts.hostname or "")
    if not host:
        return False
    for allowed in allowed_hosts:
        a = _host(allowed)
        if not a:
            continue
        if host == a or (subdomains and host.endswith("." + a)):
            return True
    return False
