"""A page that cannot say where it is is not a signed-in page.

looks_signed_out is what stops a run scraping the sign-in page and filing
whatever it finds, and it is also the question safe_selects asks before
deciding whether any control on the page may be touched at all. Its
docstring is explicit: if the app says this is not an application page,
nothing is touched, whatever the individual controls call themselves.

So the answer that matters is not the easy one. It is what comes back when
the page will not answer, and five apps answered False. Not "I cannot
tell", but "signed in, carry on", on a page nothing could read.

The other forty-three let it raise, which safe_selects treats as a refusal,
so False was both the odd answer and the only unsafe one.

The password field check still swallows its own failure in all forty-eight,
and should. A locator can fail on a page that is merely mid-navigation, and
answering "signed out" to that would stop runs that were about to work. A
page that cannot be asked for its own URL is not mid-anything.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())


class Dead:
    """A page whose context has gone. Every question raises."""

    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")

    def __getattr__(self, name):
        def gone(*_a, **_k):
            raise RuntimeError("Target page, context or browser has been closed")
        return gone


class SignIn:
    """A sign-in page, answering the two ways an app can notice one."""

    def __init__(self, url):
        self.url = url

    def locator(self, selector):
        return self

    def count(self):
        return 1 if "password" in str(getattr(self, "_sel", "password")) else 1


class Quiet:
    """A page that is somewhere ordinary and has no password field."""

    def __init__(self, url):
        self.url = url

    def locator(self, selector):
        return self

    def count(self):
        return 0


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def answer(site, page):
    """True, False, or "raised". A raise is a refusal downstream."""
    try:
        return bool(site.looks_signed_out(page))
    except Exception:
        return "raised"


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_page_that_cannot_be_asked_is_never_called_signed_in(app):
    site = site_of(app)
    if getattr(site, "looks_signed_out", None) is None:
        pytest.skip("this app has no sign-in check")
    got = answer(site, Dead())
    assert got is not False, (
        "%s says it is signed in on a page whose context has gone, which is "
        "the answer safe_selects reads before touching any control" % app.name)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_sign_in_page_is_still_noticed(app):
    """The other half, and the thing this function is actually for."""
    site = site_of(app)
    if getattr(site, "looks_signed_out", None) is None:
        pytest.skip("this app has no sign-in check")
    markers = getattr(site, "LOGIN_URL_MARKERS", [])
    assert markers, "%s recognizes no sign-in address at all" % app.name
    host = sorted(getattr(site, "ALLOWED_HOSTS", ["x.test"]))[0]
    for marker in markers[:4]:
        url = "https://%s%s" % (host, marker if marker.startswith("/")
                                else "/" + marker)
        assert answer(site, SignIn(url)) is True, \
            "%s does not notice %s as a sign-in page" % (app.name, url)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_an_ordinary_page_is_not_called_signed_out(app):
    """A check that says signed out everywhere stops every run on the first
    thing it looks at."""
    site = site_of(app)
    if getattr(site, "looks_signed_out", None) is None:
        pytest.skip("this app has no sign-in check")
    host = sorted(getattr(site, "ALLOWED_HOSTS", ["x.test"]))[0]
    assert answer(site, Quiet("https://%s/documents" % host)) is False, \
        "%s calls an ordinary documents page signed out" % app.name
