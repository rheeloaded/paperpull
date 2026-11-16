"""The headless receipt renderer prints only the provider's own page.

It checked the first address against the app's guard and then let the page
go anywhere. A redirect from the provider's address was followed to any
host, with every cookie of the person's browser in the context, and what
arrived there was printed and filed as the receipt. Now every request its
browser holds before sending, each redirect hop among them, is let through
only when the app's guard accepts it, the browser finds an address for no
host but the ones the app names, the page is checked again before and
after it is printed, and the context is given only the cookies of the
provider's own hosts.

These run a real browser against made-up servers. The provider's is at
127.0.0.1, another host at localhost, and the provider's static host at
127.0.0.1 on a port of its own. Every value here is made up.
"""
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paperpull_core import receipt_pdf
from paperpull_core.urls import is_safe_url as host_allows


class Site:
    """A made-up site that notes every request it is sent, its address
    given under `host`."""

    def __init__(self, host, pages):
        self.seen = []
        self.cookies = []
        self.pages = pages
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _answer(self):
                site.seen.append(self.path)
                site.cookies.append(self.headers.get("Cookie") or "")
                code, kind, body, extra = site.pages(self.path.split("?")[0]) or (
                    404, "text/plain", "none", {})
                body = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for name, value in extra.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_OPTIONS = _answer

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = "http://%s:%d" % (host, self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


RECEIPT = "Receipt 4417 total 12.34"


@pytest.fixture
def sites():
    """(provider, elsewhere, assets), each a fresh site for one test."""
    made = {}

    def elsewhere_pages(path):
        # What would be printed if the renderer ever got here.
        return 200, "text/html", "<title>Order 4417</title><h1>%s</h1>" % RECEIPT, {}

    def asset_pages(path):
        if path == "/asset.js":
            return 200, "text/javascript", (
                "document.addEventListener('DOMContentLoaded', () => "
                "document.getElementById('asset').textContent = 'Drawn by its asset host');"), {}
        if path == "/style.css":
            return 200, "text/css", "h1 { color: rgb(10, 20, 30); }", {}
        return elsewhere_pages(path)

    def provider_pages(path):
        b, c = made["elsewhere"].address, made["assets"].address
        ws = b.replace("http://", "ws://")
        if path == "/receipt":
            return 200, "text/html", """<html><head><title>Order 4417</title>
<link rel="stylesheet" href="%(c)s/style.css">
<script src="/own.js"></script><script src="%(c)s/asset.js"></script>
</head><body><h1>%(receipt)s</h1><p id="own"></p><p id="asset"></p>
<img src="%(b)s/pixel.png"><img src="/hop.png"><iframe src="%(b)s/frame"></iframe>
<script>
fetch("%(b)s/fetch").catch(() => {});
navigator.sendBeacon("%(b)s/beacon", "x");
try { window.open("%(b)s/popup"); } catch (e) {}
try { new Worker("/worker.js"); } catch (e) {}
try { new WebSocket("%(ws)s/socket"); } catch (e) {}
try { new WebSocketStream("%(ws)s/socket-stream"); } catch (e) {}
try { new EventSource("%(b)s/events"); } catch (e) {}
try {
  const own = "try { new WebSocket('%(ws)s/worker-socket'); } catch (e) {}";
  new Worker(URL.createObjectURL(new Blob([own], {type: "text/javascript"})));
} catch (e) {}
try { navigator.serviceWorker.register("/sw.js").catch(() => {}); } catch (e) {}
</script>
<script type="speculationrules">{"prefetch": [{"source": "list", "urls": ["%(b)s/prefetch"]}]}</script>
</body></html>""" % {"b": b, "c": c, "ws": ws, "receipt": RECEIPT}, {}
        if path == "/own.js":
            return 200, "text/javascript", (
                "document.addEventListener('DOMContentLoaded', () => "
                "document.getElementById('own').textContent = 'Drawn by its own script');"), {}
        if path == "/sockets":
            return 200, "text/html", """<title>Order 4417</title><h1>%s</h1><script>
for (const make of [() => new WebSocket("%s/socket"), () => new WebSocketStream("%s/stream")]) {
  try { make(); } catch (e) {}
}
</script>""" % (RECEIPT, ws, ws), {}
        if path == "/sw.js":
            return 200, "text/javascript", "self.addEventListener('install', () => {});", {}
        if path == "/worker.js":
            return 200, "text/javascript", "fetch('%s/from-worker').catch(() => {});" % b, {}
        if path == "/hop.png":
            return 302, "text/plain", "", {"Location": b + "/hop.png"}
        if path == "/go":
            return 302, "text/plain", "", {"Location": b + "/receipt"}
        if path == "/chain":
            return 302, "text/plain", "", {"Location": "/go"}
        if path == "/to-assets":
            return 302, "text/plain", "", {"Location": c + "/receipt"}
        if path == "/leaves":
            return 200, "text/html", """<title>Order 4417</title><h1>%s</h1><script>
window.addEventListener("load", () => setTimeout(() => { location.href = "%s/receipt"; }, 0));
</script>""" % (RECEIPT, b), {}
        return None

    made["provider"] = Site("127.0.0.1", provider_pages)
    made["elsewhere"] = Site("localhost", elsewhere_pages)
    made["assets"] = Site("127.0.0.1", asset_pages)
    yield made["provider"], made["elsewhere"], made["assets"]
    for site in made.values():
        site.close()


@pytest.fixture(scope="module")
def pw():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            p.chromium.executable_path
        except Exception:
            pytest.skip("no Playwright Chromium here")
        yield p


def guards(provider, assets):
    """The app's guard and its static hosts' guard, for these sites."""
    def is_safe_url(url):
        return str(url).startswith(provider.address + "/")

    def is_asset_url(url):
        return str(url).startswith(assets.address + "/")
    return is_safe_url, is_asset_url


SESSION = {"cookies": [
    {"name": "own", "value": "1", "domain": "127.0.0.1", "path": "/", "expires": -1,
     "httpOnly": False, "secure": False, "sameSite": "Lax"},
    {"name": "other", "value": "2", "domain": "localhost", "path": "/", "expires": -1,
     "httpOnly": False, "secure": False, "sameSite": "Lax"},
], "origins": []}


# The one host the browser may find an address for. The rules hold an
# address in bare numbers too, so 127.0.0.1 is named, and "localhost" is not.
HOSTS = ("127.0.0.1",)


def render(pw, provider, assets, path, out):
    is_safe_url, is_asset_url = guards(provider, assets)
    receipt_pdf.render_url_headless(pw, SESSION, provider.address + path, out, wait_ms=300,
                                    is_safe_url=is_safe_url, is_asset_url=is_asset_url,
                                    hosts=HOSTS)


@pytest.fixture
def contexts(monkeypatch):
    """What each browser context of the render was made with, read at
    Playwright's own door."""
    from playwright.sync_api import Browser
    made = []
    real = Browser.new_context

    def new_context(self, **kwargs):
        made.append(kwargs)
        return real(self, **kwargs)
    monkeypatch.setattr(Browser, "new_context", new_context)
    return made


def closed_port() -> int:
    """A port of 127.0.0.1 that was free a moment ago, so nothing answers."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pdf_text(path) -> str:
    from pypdf import PdfReader
    return " ".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def test_the_providers_own_page_still_prints(pw, sites, tmp_path, contexts):
    """Drawn whole, its own scripts and its static host's included, while
    everything it asks of another host is refused before it is sent, and
    what it could send without a request the browser pauses (sockets, a
    worker's socket, a prefetch its speculation rules ask for) finds no
    address for that host."""
    provider, elsewhere, assets = sites
    out = tmp_path / "receipt.pdf"
    render(pw, provider, assets, "/receipt", out)
    assert out.read_bytes()[:5] == b"%PDF-"
    text = " ".join(pdf_text(out).split())
    assert RECEIPT in text
    assert "Drawn by its own script" in text and "Drawn by its asset host" in text
    assert elsewhere.seen == []
    assert sorted(set(assets.seen)) == ["/asset.js", "/style.css"]
    assert provider.seen[0] == "/receipt" and "/hop.png" in provider.seen
    # No worker script, the service worker's included, was ever fetched.
    assert "/worker.js" not in provider.seen and "/sw.js" not in provider.seen
    # The browser was given the provider's cookie and nothing of the other
    # host's, and the page went with it.
    assert len(contexts) == 1
    given = contexts[0]["storage_state"]
    assert [c["name"] for c in given["cookies"]] == ["own"]
    assert contexts[0]["service_workers"] == "block"
    assert contexts[0]["accept_downloads"] is False
    assert provider.cookies[0] == "own=1"


def test_the_page_opens_no_socket_even_to_a_host_with_an_address(pw, sites, tmp_path):
    """A socket never pauses as a request, so the policy cannot refuse it.
    Here the other host is left an address, so only the page having no
    sockets at all keeps them from it."""
    provider, elsewhere, assets = sites
    is_safe_url, is_asset_url = guards(provider, assets)
    out = tmp_path / "receipt.pdf"
    receipt_pdf.render_url_headless(pw, SESSION, provider.address + "/sockets", out,
                                    wait_ms=300, is_safe_url=is_safe_url,
                                    is_asset_url=is_asset_url, hosts=HOSTS + ("localhost",))
    assert RECEIPT in " ".join(pdf_text(out).split())
    assert elsewhere.seen == []


def test_a_page_that_left_with_no_request_prints_nothing(pw, sites, tmp_path, monkeypatch):
    """A tab sent to about:blank asks no host, so no request was refused,
    and only the page's own address says it is no longer the provider's.
    The page leaves at the renderer's own wait after it opened, through
    the page's script, so no clock decides when."""
    from playwright.sync_api import Page
    provider, elsewhere, assets = sites
    real = Page.wait_for_timeout
    left = []

    def wait(self, timeout):
        self.evaluate("location.href = 'about:blank'")
        self.wait_for_url("about:blank")
        left.append(self.url)
        return real(self, timeout)
    monkeypatch.setattr(Page, "wait_for_timeout", wait)
    out = tmp_path / "receipt.pdf"
    with pytest.raises(ValueError, match="about:blank"):
        render(pw, provider, assets, "/receipt", out)
    assert left == ["about:blank"]
    assert not out.exists()


def test_behind_a_proxy_the_fallback_says_why_it_did_not_run(pw, sites, tmp_path, monkeypatch):
    """The browser is given no address for a proxy that is not one of the
    provider's hosts, so behind one the page never opens, and the failure
    says so rather than naming a connection error."""
    from paperpull_core import browser
    provider, elsewhere, assets = sites
    real = browser.sandboxed_launch
    proxy = "http://localhost:%d" % closed_port()

    def behind_a_proxy(chromium, **kwargs):
        # Loopback is sent through the proxy too, as it is for a page that
        # is not on this computer.
        return real(chromium, proxy={"server": proxy, "bypass": "<-loopback>"}, **kwargs)
    monkeypatch.setattr(browser, "sandboxed_launch", behind_a_proxy)
    out = tmp_path / "receipt.pdf"
    with pytest.raises(RuntimeError) as e:
        render(pw, provider, assets, "/receipt", out)
    assert str(e.value) == receipt_pdf.PROXY_REFUSED
    assert "ERR_PROXY_CONNECTION_FAILED" in str(e.value.__cause__)
    assert not out.exists()
    assert provider.seen == [] and elsewhere.seen == []


def test_a_page_the_browser_could_not_open_keeps_its_own_words(pw, tmp_path):
    """A refused connection is not a page that left the provider, and its
    failure is passed on as Playwright said it."""
    address = "http://127.0.0.1:%d" % closed_port()
    with pytest.raises(Exception) as e:
        receipt_pdf.render_url_headless(
            pw, {}, address + "/receipt", tmp_path / "out.pdf", wait_ms=0,
            is_safe_url=lambda u: str(u).startswith(address + "/"), hosts=HOSTS)
    assert not isinstance(e.value, ValueError), e.value
    assert "ERR_CONNECTION_REFUSED" in str(e.value)
    assert not (tmp_path / "out.pdf").exists()


@pytest.mark.parametrize("path", ["/go", "/chain"])
def test_a_redirect_to_another_host_never_reaches_it_and_prints_nothing(pw, sites, tmp_path,
                                                                         path):
    provider, elsewhere, assets = sites
    out = tmp_path / "receipt.pdf"
    with pytest.raises(ValueError, match="localhost"):
        render(pw, provider, assets, path, out)
    assert not out.exists()
    assert elsewhere.seen == []
    assert "/go" in provider.seen


def test_a_page_that_leaves_for_another_host_after_it_loads_prints_nothing(pw, sites, tmp_path):
    provider, elsewhere, assets = sites
    out = tmp_path / "receipt.pdf"
    with pytest.raises(ValueError):
        render(pw, provider, assets, "/leaves", out)
    assert not out.exists()
    assert elsewhere.seen == []
    assert provider.seen == ["/leaves"]


def test_the_static_host_never_serves_the_page(pw, sites, tmp_path):
    provider, elsewhere, assets = sites
    out = tmp_path / "receipt.pdf"
    with pytest.raises(ValueError):
        render(pw, provider, assets, "/to-assets", out)
    assert not out.exists()
    assert assets.seen == [] and elsewhere.seen == []


# -- what is decided, without a browser ----------------------------------------

class Printed:
    """A stand-in tab whose print writes a file."""

    def __init__(self, out, leaves=False):
        self.out = out
        self.leaves = leaves
        self.left = False
        self.media = None

    def emulate_media(self, media):
        self.media = media

    def pdf(self, path=None, **_kwargs):
        """As Playwright's page.pdf, which writes path when given one and
        answers the PDF's bytes either way."""
        assert self.media == "print"
        if path is not None:
            Path(path).write_bytes(b"%PDF-1.4 a receipt")
        self.left = self.leaves
        return b"%PDF-1.4 a receipt"


def test_a_page_that_leaves_while_it_prints_leaves_no_pdf(tmp_path):
    out = tmp_path / "receipt.pdf"
    tab = Printed(out, leaves=True)

    def still_the_providers():
        if tab.left:
            raise ValueError("refusing to print, the page was sent on to localhost")
    with pytest.raises(ValueError, match="localhost"):
        receipt_pdf._print_checked(tab, out, still_the_providers)
    assert not out.exists()


def test_a_page_that_stays_is_printed_and_kept(tmp_path):
    out = tmp_path / "receipt.pdf"
    receipt_pdf._print_checked(Printed(out), out, lambda: None)
    assert out.read_bytes().startswith(b"%PDF-")


def test_a_page_already_gone_is_never_printed(tmp_path):
    out = tmp_path / "receipt.pdf"
    tab = Printed(out)

    def gone():
        raise ValueError("refusing to print a page that is not the provider's")
    with pytest.raises(ValueError):
        receipt_pdf._print_checked(tab, out, gone)
    assert tab.media is None and not out.exists()


def test_the_browser_finds_an_address_only_for_the_hosts_it_is_given():
    assert receipt_pdf._resolver_rules(["target.com", "*.target.com", "Target.Scene7.com."]) == (
        "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE target.com , EXCLUDE *.target.com"
        " , EXCLUDE target.scene7.com")
    from paperpull_core import browser
    assert not browser.turns_sandbox_off(receipt_pdf._resolver_rules(["target.com"]))

def target_guard(url):
    return host_allows(url, {"target.com"})


def target_assets(url):
    return host_allows(url, {"assets.targetimg1.com", "target.scene7.com"}, subdomains=False)


@pytest.mark.parametrize("url,kind,allowed", [
    ("https://www.target.com/orders/1", "Document", True),
    ("https://gsp.target.com/login", "Document", True),
    ("https://evil.example/receipt", "Document", False),
    ("https://www.target.com.evil.example/", "Document", False),
    ("http://www.target.com/orders/1", "Document", False),
    ("https://assets.targetimg1.com/page.html", "Document", False),
    ("https://assets.targetimg1.com/app.js", "Script", True),
    ("https://assets.targetimg1.com/app.css", "Stylesheet", True),
    ("https://assets.targetimg1.com/font.woff2", "Font", True),
    ("https://target.scene7.com/is/image/x", "Image", True),
    ("https://assets.targetimg1.com/data.json", "XHR", False),
    ("https://x.assets.targetimg1.com/app.js", "Script", False),
    ("https://redsky.target.com/v1/orders", "XHR", True),
    ("https://api.target.com/v1", "Fetch", True),
    ("https://www.target.com/beacon", "Ping", False),
    ("https://www.target.com/events", "EventSource", False),
    ("https://www.target.com/worker.js", "Other", False),
    ("https://www.target.com/manifest.json", "Manifest", False),
    ("https://securepubads.g.doubleclick.net/tag.js", "Script", False),
    ("https://client.px-cloud.net/main.js", "Script", False),
    ("data:image/png;base64,AA==", "Image", True),
    ("data:text/html,<h1>x</h1>", "Document", False),
    ("blob:https://www.target.com/1", "Image", True),
])
def test_what_the_renderer_lets_through(url, kind, allowed):
    assert receipt_pdf._allowed(url, kind, target_guard, target_assets) is allowed


def test_without_static_hosts_only_the_providers_own_answer():
    assert not receipt_pdf._allowed("https://assets.targetimg1.com/app.js", "Script",
                                    target_guard, None)
    assert receipt_pdf._allowed("https://www.target.com/app.js", "Script", target_guard, None)


def test_only_the_providers_cookies_and_storage_are_given_to_the_renderer():
    state = {"cookies": [
        {"name": "a", "domain": ".target.com"},
        {"name": "b", "domain": "www.target.com"},
        {"name": "c", "domain": "target.com"},
        {"name": "d", "domain": ".google.com"},
        {"name": "e", "domain": "target.com.evil.example"},
        {"name": "f", "domain": ""},
        {"name": "g", "domain": "evil.example/x.target.com"},
        {"name": "h", "domain": "assets.targetimg1.com"},
        {"name": "i"},
        "not a cookie",
    ], "origins": [
        {"origin": "https://www.target.com", "localStorage": [{"name": "k", "value": "v"}]},
        {"origin": "https://mail.example", "localStorage": [{"name": "k", "value": "v"}]},
        {"origin": "http://www.target.com", "localStorage": []},
    ]}
    given = receipt_pdf._state_for(state, "https://www.target.com/orders/1", target_guard)
    assert [c["name"] for c in given["cookies"]] == ["a", "b", "c"]
    assert [o["origin"] for o in given["origins"]] == ["https://www.target.com"]


def test_a_session_that_is_not_one_gives_nothing():
    for state in (None, {}, "state.json", {"cookies": None, "origins": None}):
        assert receipt_pdf._state_for(state, "https://www.target.com/", target_guard) == {
            "cookies": [], "origins": []}


def test_a_guard_that_raises_has_not_said_yes():
    def broken(url):
        raise RuntimeError("guard broke")
    assert receipt_pdf._state_for({"cookies": [{"name": "a", "domain": "target.com"}]},
                                  "https://www.target.com/", broken)["cookies"] == []
