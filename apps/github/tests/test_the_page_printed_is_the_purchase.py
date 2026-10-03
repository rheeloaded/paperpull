"""The page GitHub prints for a payment has to be that payment's receipt.

A receipt link that answers with a page rather than a PDF is opened and
printed. GitHub's payment history shows each payment's own date, amount
and id, so the history, printed in a payment's place, named the payment
and passed the check on the saved file, and was kept as its receipt.

So the page is checked before anything is taken from it, the way Best Buy
reads the number on its details page. Nothing in the history's words
tells it from a receipt, so what decides is where the page is. It has to
be the address the payment's row linked to, and that address must not be
the history's own.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches GitHub. Every payment,
id and amount is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import github_receipts as app_mod
import github_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

HISTORY = "/account/billing/history"
RECEIPT = "/account/receipt/"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history, a table with the tester's columns, newest first. Each row
# links to its receipt, which here is a page of its own.
PAYMENTS = [("30000001", "Jun 1, 2026", "PAYXQ7K1", "$10.00"),
            ("30000002", "May 1, 2026", "PAYXQ7K2", "$4.00")]


def history_page(rows):
    body = "".join(
        "<tr><td>%s</td><td>%s</td><td>Visa ending in 4242</td><td>%s</td><td>Paid</td>"
        '<td><a href="%s" aria-label="View receipt">Receipt</a></td></tr>'
        % (when, pid_shown, amount, link) for link, when, pid_shown, amount in rows)
    return ("<!doctype html><html><head><title>Payment history</title></head><body>"
            "<h1>Payment history</h1>"
            '<turbo-frame id="settings-frame"><table><thead><tr><th>Date</th><th>ID</th>'
            "<th>Payment Method</th><th>Amount</th><th>Status</th><th>Receipt</th></tr>"
            "</thead><tbody>%s</tbody></table></turbo-frame></body></html>" % body)


def receipt_page(pid):
    for p, when, shown, amount in PAYMENTS:
        if p == pid:
            return ("<!doctype html><html><head><title>Receipt</title></head><body>"
                    "<main><div class='receipt'><h1>GitHub receipt</h1>"
                    "<p>Paid on %s</p><p>Payment %s</p><p>GitHub Pro %s</p>"
                    "<p>Total %s</p><p>Thank you for your payment to GitHub, Inc.</p>"
                    "</div></main></body></html>" % (when, shown, amount, amount))
    return None


class FakeGitHub:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}          # payment id -> where its receipt link sends the browser
        self.row_links = {}      # payment id -> the link its row carries instead
        self.seen = []

    def rows(self):
        return [(self.row_links.get(p, RECEIPT + p), when, shown, amount)
                for p, when, shown, amount in PAYMENTS]


SITE = FakeGitHub()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(self.path)
        pid = path[len(RECEIPT):] if path.startswith(RECEIPT) else ""
        if path == HISTORY:
            self._answer(history_page(SITE.rows()))
        elif pid in SITE.moved:
            self.send_response(302)
            self.send_header("Location", SITE.moved[pid])
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        elif pid and receipt_page(pid):
            self._answer(receipt_page(pid))
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
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
def attached(browser_exe, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation, which is how Target's copy of
    this test failed on CI (run 37123796050). The app works in a tab it
    opens for itself, so the tab that drew can stay where it is."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_github(server, monkeypatch):
    """Every address the app opens points at the made-up site. A receipt
    link is read against GitHub's own host, and only an address on it is
    followed. Here that host is this machine."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + HISTORY)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def pilot(tmp_path, cdp_url):
    assert app_mod.main(["--pilot", "--config", str(config_for(tmp_path, cdp_url))]) == 0


def progress(tmp_path):
    return json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def saved(tmp_path):
    """Every PDF the run left anywhere under its folder."""
    return sorted((tmp_path / "out").rglob("*.pdf"))


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def assert_refused(rec, out):
    assert not rec.get("downloaded_ok"), "kept as the receipt: %r" % rec
    assert rec["state"] == "Needs Manual Review", rec
    assert "nothing was saved" in out, out
    assert "refused because they were not the one asked for" in out, out


def test_every_receipt_is_printed_from_its_own_page(attached, tmp_path, capsys):
    """What worked before still works, and nothing right is refused."""
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert sorted(records) == sorted("Online:" + p[0] for p in PAYMENTS), records
    for pid, _when, shown, _amount in PAYMENTS:
        rec = records["Online:" + pid]
        assert rec.get("downloaded_ok") is True, rec
        assert "Payment " + shown in pdf_text(rec["pdf_path"])
    assert "nothing was saved" not in out, out


def test_the_history_is_not_printed_as_a_receipt(attached, tmp_path, capsys):
    """The receipt link sends the browser back to the payment history,
    which names the payment's date, amount and id."""
    SITE.moved["30000001"] = HISTORY
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:30000001"], out)
    assert "is not at this purchase's address" in out, out
    assert all("Visa ending in" not in pdf_text(p) for p in saved(tmp_path)), \
        "the history was saved as a receipt"
    assert records["Online:30000002"].get("downloaded_ok") is True


def test_a_row_whose_link_is_the_history_is_not_printed(attached, tmp_path, capsys):
    """A row's link can itself be the history. What it opens is the list,
    whatever the link was called."""
    SITE.row_links["30000001"] = HISTORY + "?page=1"
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert "is the order list" in out, out
    assert all("Visa ending in" not in pdf_text(p) for p in saved(tmp_path)), \
        "the history was saved as a receipt"
    linked = [rec for rec in progress(tmp_path).values()
              if urlsplit(rec.get("receipt_url") or "").path == HISTORY]
    assert len(linked) == 1 and not linked[0].get("downloaded_ok"), linked


def test_a_refused_payment_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with the link opening the
    receipt again, saves it."""
    SITE.moved["30000001"] = HISTORY
    pilot(tmp_path, attached)
    assert not progress(tmp_path)["Online:30000001"].get("downloaded_ok")

    SITE.moved.clear()
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:30000001"]
    assert rec.get("downloaded_ok") is True, rec
    assert "Payment PAYXQ7K1" in pdf_text(rec["pdf_path"])
