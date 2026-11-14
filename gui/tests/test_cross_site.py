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

A link opened from an email, a chat or a PDF carries no Origin and no
Referer either, and its Host is the panel's own. Sec-Fetch-Site says none
for it, as it does for an address typed into the bar, since the browser
opened the address by itself. Only a page is opened that way, never the
API, so the API refuses none.
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


def test_a_link_opened_from_outside_the_browser_is_refused():
    """A Sec-Fetch-Site of none is the browser opening an address by
    itself, for a link opened from an email, a chat or a PDF as for an
    address typed into the bar. It used to be allowed, and /api/run is a
    GET that starts a run, so such a link started that run. The panel's
    own page asks for the API by script, which the browser marks
    same-origin."""
    assert not allowed(sec_fetch_site="none")
    assert not allowed(sec_fetch_site="NONE")
    assert not allowed(host="localhost:8799", sec_fetch_site="none")


def test_the_refusal_of_such_a_link_says_what_asks_here():
    """The one refusal a person meets by doing something ordinary, opening
    an address of the API by hand, so it says why."""
    with pytest.raises(fastapi.HTTPException) as refused:
        app_module._same_origin_only(Req(host=HOST, sec_fetch_site="none"))
    assert refused.value.status_code == 403
    assert "own page" in refused.value.detail and "link" in refused.value.detail
    with pytest.raises(fastapi.HTTPException) as refused:
        app_module._same_origin_only(Req(host=HOST, sec_fetch_site="cross-site"))
    assert refused.value.detail == "cross-origin request refused"


def test_a_tool_that_sends_no_headers_at_all_is_allowed():
    """curl, and browsers old enough not to know the header, on the desktop.
    A header being absent is not the same as it saying cross-site there,
    since every current browser sends it to 127.0.0.1, and refusing would
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


def test_on_the_server_a_link_opened_from_outside_the_browser_is_refused_too(monkeypatch):
    """A browser opening an address by itself sends the server's session
    cookie, SameSite=Strict and all, so the sign-in gate lets such a link
    through. The server's sign-in, sign-out and Browser Screen connection
    ask the same question as the API, and none of them is a page."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    assert not server_mode.same_origin({"host": "nas.local:8765", "sec-fetch-site": "none"})
    assert server_mode.same_origin({"host": "nas.local:8765", "sec-fetch-site": "same-origin"})
    assert not allowed(host="nas.local:8765", sec_fetch_site="none")


def test_on_the_server_a_request_that_names_nothing_is_refused(monkeypatch):
    """PaperPull Server reached over plain HTTP by a name on the home
    network gets no Sec-Fetch-Site from any browser, so a link opened from
    an email or a chat arrives with the session's cookie and nothing else,
    and so does an image another program's page on the same NAS asks for
    under no-referrer. Both passed, and a link to /api/run started a run (a
    private report of 2026-11-10, measured in Chromium 2026-11-14)."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    for host in ("nas.local:8765", "192.168.1.20:8765", "127.0.0.1:8765"):
        assert not server_mode.same_origin({"host": host}), host
        assert not allowed(host=host), host
        assert not allowed(host=host, referer="  "), host
    with pytest.raises(fastapi.HTTPException) as refused:
        app_module._same_origin_only(Req(host="nas.local:8765"))
    assert refused.value.status_code == 403 and "link" in refused.value.detail


def test_on_the_server_the_panels_own_page_over_plain_http_still_names_itself(monkeypatch):
    """Its fetch, EventSource and frames carry a Referer of its own address,
    since nothing in the panel sets a Referrer-Policy, and a POST an Origin
    as well. Any one of the three is enough, and each still has to name the
    panel."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    assert allowed(host="nas.local:8765", referer="http://nas.local:8765/")
    assert allowed(host="nas.local:8765", origin="http://nas.local:8765")
    assert allowed(host="nas.local:8765", sec_fetch_site="same-origin")
    assert not allowed(host="nas.local:8765", referer="http://nas.local:5000/")
    assert not allowed(host="nas.local:8765", origin="http://nas.local:5000")


def test_the_page_says_nothing_of_how_its_own_requests_are_sent():
    """The fix rests on the panel's own requests carrying a Referer, so a
    Referrer-Policy anywhere in the panel, or a request of its own sent with
    no referrer, would refuse them over plain HTTP."""
    import re
    gui = Path(app_module.__file__).resolve().parent
    for path in sorted((gui / "static").iterdir()):
        text = path.read_text(encoding="utf-8").lower()
        for word in ("referrer-policy", "referrerpolicy", "referrer:", "no-referrer", "noreferrer"):
            assert word not in text, (path.name, word)
    for path in (gui / "app.py", gui / "server_mode.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"""["']referrer-policy["']""", text, re.I), path.name
        # The pages the server writes itself, sign-in and the screen's frame.
        assert not re.search(r"""(referrerpolicy|rel=["'][^"']*noreferrer)""", text, re.I), path.name


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


# -- every combination, against the rule written out -------------------------------------
#
# Hand-picked cases miss combinations, Sec-Fetch-Site absent with a good
# Origin and a bad Referer for one. The rule: the Host is the panel's,
# Sec-Fetch-Site is absent or same-origin, any Origin or Referer sent names
# the panel's own address, and on PaperPull Server at least one of the three
# is sent at all.

SITES = [None, "", "none", "same-origin", "same-site", "cross-site"]
ORIGINS = [None, "own", "other port", "other host", "null", ""]
REFERERS = [None, "own", "own with a path", "other port", "other host"]


def _value(kind, host):
    name = host.split(":")[0]
    return {"own": "http://%s" % host, "own with a path": "http://%s/x?y=1#z" % host,
            "other port": "http://%s:5000" % name, "other host": "http://evil.example",
            "null": "null", "": ""}.get(kind, kind)


def _by_the_rule(edition, site, origin, referer):
    if site not in (None, "", "same-origin"):
        return False
    if origin is not None and origin != "own":
        return False
    if referer is not None and referer not in ("own", "own with a path"):
        return False
    return not (edition == "server" and not site and origin is None and referer is None)


@pytest.mark.parametrize("edition", ["desktop", "server"])
def test_every_combination_of_the_three_headers_follows_the_rule(edition, monkeypatch):
    if edition == "server":
        monkeypatch.setenv("PAPERPULL_SERVER", "1")
    host = "nas.local:8765" if edition == "server" else HOST
    wrong = []
    for site in SITES:
        for origin in ORIGINS:
            for referer in REFERERS:
                got = allowed(host=host, sec_fetch_site=site,
                              origin=None if origin is None else _value(origin, host),
                              referer=None if referer is None else _value(referer, host))
                if got != _by_the_rule(edition, site, origin, referer):
                    wrong.append((site, origin, referer, got))
    assert not wrong, wrong
