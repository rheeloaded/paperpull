"""What the panel accepts from a page that is not its own.

It listens on 127.0.0.1, which keeps other machines out and does nothing
about the browser already running on this one. A website somebody visits
can ask a local address for something, and /api/run is a GET that starts a
download, so the question is what arrives with that request.

Origin and Referer answer it when they are sent, and a page can arrange
for neither to be: an <img> carries no Origin, and `no-referrer` strips
the rest. Sec-Fetch-Site cannot be arranged away by the page, so that is
the one relied on.

That fails against a page that points a name of its own at 127.0.0.1,
which the browser takes for the panel's own origin, so Sec-Fetch-Site
says same-origin. The Host header is what tells that page apart, since it
names the address the request was made to. Every request here carries
one, as curl and every browser send it, unless a test says otherwise.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")
import server_mode  # noqa: E402

HOST = "127.0.0.1:8799"


class Req:
    def __init__(self, **headers):
        self.headers = {k.replace("_", "-"): v for k, v in headers.items() if v is not None}


def allowed(**headers) -> bool:
    headers.setdefault("host", HOST)
    try:
        app_module._same_origin_only(Req(**headers))
        return True
    except fastapi.HTTPException:
        return False


@pytest.fixture(autouse=True)
def on_the_desktop(monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.delenv("PAPERPULL_HOSTS", raising=False)


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
    break every local script anyone has written against this. Both send a
    Host header, the one header nothing leaves out."""
    assert allowed()
    assert allowed(host="localhost:8765")


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


# -- a page that points a name of its own at this computer ---------------------

def test_the_request_the_review_sent_is_refused():
    """A page at rebind.example, whose name now leads to 127.0.0.1, is the
    same origin as the requests it makes, so the browser says same-origin.
    The 2026-10-06 review sent exactly this, and it was answered."""
    assert not allowed(host="rebind.example:8765", sec_fetch_site="same-origin", origin="null")


def test_a_get_from_such_a_page_with_no_referrer_is_refused():
    """A GET carries no Origin, and a page under no-referrer sends no
    Referer, so only the Host header still names that site. /api/run is a
    GET that starts a download."""
    assert not allowed(host="rebind.example:8765", sec_fetch_site="same-origin")


def test_such_a_page_is_refused_with_its_own_origin_too():
    assert not allowed(host="rebind.example:8765", sec_fetch_site="same-origin",
                       origin="http://rebind.example:8765")


def test_an_address_on_the_network_is_refused_on_the_desktop():
    """The desktop panel listens on 127.0.0.1 alone and has no password, so
    a request naming this computer by its network address or its name
    reached it some other way than the panel was started."""
    assert not allowed(host="192.168.1.20:8765")
    assert not allowed(host="my-computer:8765")


def test_a_request_with_no_host_is_refused():
    """Every browser and curl send one. A request without it names no
    address of the panel's."""
    assert not allowed(host=None)


def test_a_host_that_is_not_a_plain_address_is_refused():
    for host in ("127.0.0.1:8765@evil.example", "evil.example/127.0.0.1", "127.0.0.1:port",
                 "127.0.0.1 evil.example", "localhost.", ""):
        assert not allowed(host=host), host


def test_the_panel_by_its_other_names_is_its_own_page():
    assert allowed(host="localhost:8799", sec_fetch_site="same-origin",
                   origin="http://localhost:8799")
    assert allowed(host="LOCALHOST:8799", origin="http://localhost:8799")
    assert allowed(host="[::1]:8799", sec_fetch_site="same-origin", origin="http://[::1]:8799")
    assert allowed(host="127.0.0.1", origin="http://127.0.0.1")


# -- an Origin that names no address -------------------------------------------

def test_an_origin_of_null_is_refused():
    """A browser sends null for a page that keeps its address to itself, a
    sandboxed frame, or a form sent under no-referrer. It parsed to an
    empty host, and the empty host passed for this computer."""
    assert not allowed(sec_fetch_site="same-origin", origin="null")
    assert not allowed(origin="null")
    assert not allowed(origin="NULL")


def test_an_empty_origin_is_refused():
    assert not allowed(sec_fetch_site="same-origin", origin="")
    assert not allowed(origin="  ")


def test_a_referer_that_names_no_address_is_refused():
    assert not allowed(sec_fetch_site="same-origin", referer="null")


# -- another page of this computer ---------------------------------------------

def test_another_port_of_this_computer_is_refused():
    """A browser too old to send Sec-Fetch-Site still sends Origin. Any
    page on this computer used to pass, since only the name was compared,
    so a local web server's page could drive the panel."""
    assert not allowed(origin="http://127.0.0.1:3000")
    assert not allowed(referer="http://127.0.0.1:3000/page")


def test_this_computer_by_its_other_name_is_another_origin():
    assert not allowed(origin="http://localhost:8799")
    assert not allowed(host="localhost:8799", origin="http://127.0.0.1:8799")


# -- PaperPull Server ----------------------------------------------------------

def test_on_the_server_an_empty_origin_is_refused_too(monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    own = {"host": "nas.local:8765", "sec-fetch-site": "same-origin"}
    assert server_mode.same_origin(dict(own, origin="http://nas.local:8765"))
    assert not server_mode.same_origin(dict(own, origin=""))
    assert not server_mode.same_origin(dict(own, origin="null"))
    assert not allowed(host="nas.local:8765", sec_fetch_site="same-origin", origin="")
    assert allowed(host="nas.local:8765", sec_fetch_site="same-origin",
                   origin="http://nas.local:8765")


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
