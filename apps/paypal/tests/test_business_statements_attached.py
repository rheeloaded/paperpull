"""A business account's statements through the app's own attach, in a real
browser that keeps its downloads the way the person's does.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP from its
own main, exactly as at home. No router stands between the page and its
answers, since a router cancels every download it answers, so the invented
account (business_pages) is served by a server on this machine over HTTPS,
with a certificate made for this run that only this browser is told to
trust. The browser finds www.paypal.com on this machine and every other name
fails to resolve, and Playwright's own request client is made to fail, so
nothing reaches PayPal. The browser's own download folder is a folder of
the test's, so nothing lands in the real Downloads, and it has to stay
empty.

Each ready statement's press hands it over the way the tester's did, a
hidden link with a download mark that the page clicks, its address a blob
the page built in one run and an address of PayPal's own in the other, and
each has to arrive by the browser's own download, under the app's name for
it and never the link's.
"""
import base64
import datetime
import hashlib
import json
import ssl
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import paypal_docs
import business_pages as B
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

# The account the server answers for now. Each test sets its own.
SITE = {"now": B.Business()}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, body: bytes, kind=None, status=200, headers=()):
        self.send_response(status)
        if kind:
            self.send_header("Content-Type", kind)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        now = SITE["now"]
        path = urlsplit(self.path).path
        if path == B.STATEMENTS_PATH:
            # A business account's statements address sends it to its settings.
            self._send(b"", "text/html", 302, [("Location", B.SETTINGS)])
        elif path == B.SETTINGS:
            self._send(B.SETTINGS_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == B.REPORTS and now.reports_page:
            self._send(now.page_html().encode("utf-8"), "text/html; charset=utf-8")
        elif path.startswith(B.FILES) and now.file(path) is not None:
            self._send(now.file(path), "application/pdf", 200, [(
                "Content-Disposition", 'attachment; filename="%s"' % B.SAVED_NAME)])
        else:
            self._send(b"not here", "text/plain", 404)

    def do_POST(self):
        now = SITE["now"]
        parts = urlsplit(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if parts.path == B.LIST and now.list_answers:
            # The page marks its own list request. One without the mark would
            # be the app asking for the list itself, which it never does.
            now.unmarked += self.headers.get("x-csrf-token") != "invented-token"
            self._send(now.list_answer(body.decode("utf-8", "replace")).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif parts.path == B.PRESSED:
            now.pressed.append(parse_qs(parts.query).get("row", [""])[0])
            self._send(b"", None, 204)
        elif parts.path == B.FLAG:
            now.flags.append(parse_qs(parts.query).get("what", [""])[0])
            self._send(b"", None, 204)
        else:
            self._send(b"not here", "text/plain", 404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def certificate(tmp_path_factory):
    """A certificate for www.paypal.com made for this run, its files and the
    hash of its key, which is all the browser is told to trust."""
    crypto = pytest.importorskip("cryptography")  # noqa: F841  pypdf[crypto] brings it
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder = tmp_path_factory.mktemp("certificate")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "www.paypal.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("www.paypal.com")]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    spki = base64.b64encode(hashlib.sha256(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest())
    return folder / "cert.pem", folder / "key.pem", spki.decode()


@pytest.fixture(scope="module")
def server(certificate):
    cert, key, _spki = certificate
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert), str(key))
    # The handshake happens in each request's own thread, so a connection
    # the browser opens and never uses cannot hold up the rest.
    httpd.socket = tls.wrap_socket(httpd.socket, server_side=True,
                                   do_handshake_on_connect=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    """Playwright's own Chromium, found the way the app finds it in its
    bundled mode, so it is never the person's everyday browser."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def saved_by_the_browser(tmp_path_factory):
    """The browser's own download folder, the test's rather than the real
    Downloads."""
    return tmp_path_factory.mktemp("browser-downloads")


@pytest.fixture(scope="module")
def attached(browser_exe, server, certificate, saved_by_the_browser, tmp_path_factory):
    """The browser's debugging address, for cdp_url, handed over once a tab
    has drawn a page (testkit.drawn_browser). That tab is on a page of the
    helper's own, so no tab of the person's is open on PayPal."""
    _cert, _key, spki = certificate

    def profile():
        folder = tmp_path_factory.mktemp("attached-profile")
        (folder / "Default").mkdir()
        (folder / "Default" / "Preferences").write_text(json.dumps({"download": {
            "default_directory": str(saved_by_the_browser), "prompt_for_download": False}}),
            encoding="utf-8")
        return folder

    args = ("--host-resolver-rules=MAP www.paypal.com 127.0.0.1:%d, MAP * ~NOTFOUND , "
            "EXCLUDE 127.0.0.1" % server, "--ignore-certificate-errors-spki-list=" + spki)
    try:
        with testkit.drawn_browser(browser_exe, profile, args=args) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def _tabs(cdp_url):
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read()) if t.get("type") == "page"]


@pytest.fixture(autouse=True)
def no_tab_left_on_paypal(attached):
    """Each run starts with no tab on PayPal and leaves none, so one run's
    tab is never the next run's."""
    def close_them():
        for tab in _tabs(attached):
            if urlsplit(tab.get("url") or "").hostname == "www.paypal.com":
                urllib.request.urlopen("%s/json/close/%s" % (attached, tab["id"]),
                                       timeout=10).read()
    close_them()
    yield
    close_them()


@pytest.fixture(autouse=True)
def nothing_asked_outside_the_browser(monkeypatch):
    """Playwright's own request client does not use the browser's resolver
    and would reach the real www.paypal.com, so any use of it fails."""
    from playwright.sync_api import APIRequestContext

    def refused(*_a, **_k):
        raise AssertionError("Playwright's own request client was used")
    for name in ("get", "post", "fetch", "head", "put", "patch", "delete"):
        monkeypatch.setattr(APIRequestContext, name, refused)


@pytest.mark.parametrize("variant", ["blob", "direct"])
def test_each_ready_statement_arrives_by_the_browsers_own_download(
        attached, saved_by_the_browser, tmp_path, capsys, variant):
    now = SITE["now"] = B.Business(variant)
    now.unmarked = 0
    cfg = B.config(tmp_path, cdp_url=attached, profile_dir=str(tmp_path / "profile"))
    try:
        paypal_docs.main(["--all", "--yes", "--config", str(cfg)])
        stopped = None
    except SystemExit as e:
        stopped = e.code
    out = capsys.readouterr().out
    said, result = " ".join(out.split()), B.result_of(out)
    assert B.statements(tmp_path) == B.FILED, said
    assert said.count("the document arrived by download") == 2, said
    assert sorted(now.pressed) == sorted([B.ACCOUNT_ID + "1", B.ACCOUNT_ID + "4"])
    assert now.flags == [], "a control that makes a report or a CSV was pressed"
    assert now.lists >= 1 and now.unmarked == 0, "the list was asked for by the app"
    assert stopped is None and result["new_files"] == 2 and not result["stopped"]
    written = B.everything_written(tmp_path / "out")
    for canary in B.CANARIES:
        assert canary not in written, "%s reached a file this run wrote" % canary
    assert list(saved_by_the_browser.iterdir()) == [], "the browser kept a copy of its own"
