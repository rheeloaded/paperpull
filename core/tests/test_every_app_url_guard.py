"""Every app's URL guard, checked in one place and by behavior.

The check was written forty-eight times and drifted into ten answers. Six
apps insisted on an exact host, twenty-nine ignored the port, and five
raised ValueError instead of refusing a URL whose port did not parse. None
of it was reachable as an attack, but ten answers to one question is nine
too many, and a fix to one fixed one.

The parsing lives in paperpull_core.urls now. These run the same battery
against every app, so a provider added next year cannot bring an eleventh
version with it. They ask what the guard ANSWERS rather than how it is
written, because an app is free to add rules of its own on top (UKG also
refuses a path that says EDIT, ADD or DELETE) and must still get the
common cases right.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(".")
              and (d / ("%s_site.py" % d.name)).exists())


@pytest.fixture(params=[d.name for d in APPS])
def guard(request):
    """(is_safe_url, a host the app allows) for one app."""
    slug = request.param
    sys.path.insert(0, str(REPO / "apps" / slug))
    try:
        mod = importlib.import_module("%s_site" % slug)
    finally:
        sys.path.pop(0)
    fn = getattr(mod, "is_safe_url", None)
    if fn is None:
        pytest.skip("%s has no URL guard" % slug)
    hosts = sorted(getattr(mod, "ALLOWED_HOSTS", []) or [])
    if not hosts:
        # UKG's tenant is configured rather than compiled in.
        base = getattr(mod, "BASE", "") or ""
        if not base:
            mod.BASE = "https://tenant.ultipro.com"
        from urllib.parse import urlparse
        hosts = [urlparse(mod.BASE).hostname or ""]
    return slug, fn, hosts[0], [h.lower().rstrip(".") for h in hosts]


def _ok(fn, url):
    """The guard's answer, with a crash counted as its own kind of wrong."""
    try:
        return fn(url)
    except Exception as e:      # noqa: BLE001 - a guard may not raise
        return "raised %s" % type(e).__name__


# -- what every guard must refuse ----------------------------------------------

def test_plain_http_is_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "http://%s/" % host) is False


def test_another_host_is_refused(guard):
    _slug, fn, _host, _all = guard
    assert _ok(fn, "https://evil.example/x") is False


def test_a_lookalike_host_is_refused(guard):
    """The reason hosts are matched by label and never by string prefix.

    The second probe glues a label onto the front of an allowed host with
    no dot. For most apps that is a different domain and must be refused.
    Where the app also allows the parent (PG&E allows both m.pge.com and
    pge.com) the result really is one of its own subdomains, so the probe
    is built from a host that has no allowed parent."""
    _slug, fn, host, allowed = guard
    assert _ok(fn, "https://%s.evil.example/x" % host) is False

    def under_an_allowed_parent(h):
        return any(h.endswith("." + a) for a in allowed)

    for h in [host] + allowed:
        if not under_an_allowed_parent("not" + h):
            assert _ok(fn, "https://not%s/x" % h) is False
            return
    pytest.skip("every host here has an allowed parent, so no such probe exists")


def test_credentials_hiding_the_real_host_are_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s@evil.example/x" % host) is False


def test_another_port_is_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s:8443/x" % host) is False


def test_a_port_that_does_not_parse_is_refused_and_does_not_raise(guard):
    """Five apps raised ValueError here, which reached the user as a
    traceback rather than as a refusal."""
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s:99999/x" % host) is False


def test_a_scheme_that_is_not_the_web_is_refused(guard):
    _slug, fn, _host, _all = guard
    for url in ("file:///c:/secrets.txt", "javascript:alert(1)", "data:text/html,x"):
        assert _ok(fn, url) is False, url


def test_nothing_at_all_is_refused(guard):
    _slug, fn, _host, _all = guard
    for url in ("", None, "   ", "not a url"):
        assert _ok(fn, url) is False, repr(url)


# -- and what it must still allow ----------------------------------------------

def test_the_provider_s_own_host_is_allowed(guard):
    """A guard that refuses everything is safe and useless."""
    slug, fn, host, _all = guard
    if slug == "ukg":
        pytest.skip("its paths carry the verb, so a bare host is not enough")
    assert _ok(fn, "https://%s/" % host) is True
