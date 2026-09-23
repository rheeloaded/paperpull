"""What the panel accepts from a page that is not its own.

It listens on 127.0.0.1, which keeps other machines out and does nothing
about the browser already running on this one. A website somebody visits
can ask a local address for something, and /api/run is a GET that starts a
download, so the question is what arrives with that request.

Origin and Referer answer it when they are sent, and a page can arrange
for neither to be: an <img> carries no Origin, and `no-referrer` strips
the rest. Sec-Fetch-Site cannot be arranged away by the page, so that is
the one relied on.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


class Req:
    def __init__(self, **headers):
        self.headers = {k.replace("_", "-"): v for k, v in headers.items()}


def allowed(**headers) -> bool:
    try:
        app_module._same_origin_only(Req(**headers))
        return True
    except fastapi.HTTPException:
        return False


# -- what the panel's own page looks like --------------------------------------

def test_the_panels_own_page_is_allowed():
    assert allowed(sec_fetch_site="same-origin", origin="http://127.0.0.1:8799")
    assert allowed(sec_fetch_site="same-origin", referer="http://127.0.0.1:8799/")
    assert allowed(sec_fetch_site="same-origin")


def test_an_address_typed_into_the_bar_is_allowed():
    """Sec-Fetch-Site: none is a navigation the person started."""
    assert allowed(sec_fetch_site="none")


def test_a_tool_that_sends_no_headers_at_all_is_allowed():
    """curl, and browsers old enough not to know the header. A header being
    absent is not the same as it saying cross-site, and refusing here would
    break every local script anyone has written against this."""
    assert allowed()


# -- what somebody else's page looks like --------------------------------------

def test_another_site_is_refused_by_its_origin():
    assert not allowed(origin="https://evil.example")


def test_another_site_is_refused_by_its_referer():
    assert not allowed(referer="https://evil.example/page")


def test_an_image_tag_with_no_referrer_is_refused():
    """The one that used to get through. An <img> sends no Origin, and a
    page declaring no-referrer sends no Referer, so both checks abstained
    and a GET that starts a download was answered."""
    assert not allowed(sec_fetch_site="cross-site")


def test_a_sibling_site_is_refused_too():
    assert not allowed(sec_fetch_site="same-site")


def test_a_cross_site_request_is_refused_even_claiming_a_local_origin():
    """A page cannot set Sec-Fetch-Site, and it cannot set Origin either,
    but if either could be forged the other still has to agree."""
    assert not allowed(sec_fetch_site="cross-site", origin="http://127.0.0.1:8799")
    assert not allowed(sec_fetch_site="same-origin", origin="https://evil.example")


# -- the endpoints this actually guards ----------------------------------------

def test_every_api_endpoint_carries_the_guard():
    """A new endpoint that forgets it is the way this comes back."""
    import re
    src = (Path(app_module.__file__)).read_text(encoding="utf-8")
    missing = []
    for m in re.finditer(r'@app\.(get|post)\("(/api/[^"]*)"([^)]*)\)', src):
        if "_same_origin_only" not in m.group(3):
            missing.append(m.group(2))
    assert not missing, "these answer anybody: %s" % missing
