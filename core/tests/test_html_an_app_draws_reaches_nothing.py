"""HTML an app draws to a PDF itself runs nothing and reaches nothing.

Anthem drew a secure message's body, which it does not write, in a page of
the signed-in browser context with JavaScript on, and its block covered
http and https alone. A script in a body could open a WebSocket, or a popup
whose requests carried the session (a private report of 2026-11-10). It
draws through receipt_pdf.inert_pdf_bytes now, active content stripped,
JavaScript off, and every request aborted, in a fresh context where it is
attached to a browser and in a page of its own where it runs on a
persistent profile.

Playwright's own headless Chromium, never a browser of the person's. A raw
socket on this computer stands in for anywhere a page could reach, and it
counts every connection made to it, whatever it carries, since an aborted
request is still an event and only a connection is reaching something.
"""
import base64
import socket
import threading

import pytest

from paperpull_core import receipt_pdf

sync_api = pytest.importorskip("playwright.sync_api")

# A one-pixel PNG, as Anthem's ID card puts each side in an img tag.
PIXEL = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2d4a5"
    "9f0000000049454e44ae426082")).decode("ascii")


class Listener:
    """A socket on 127.0.0.1 that counts each connection made to it."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.accepted += 1
            conn.close()

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.port

    def close(self):
        self.sock.close()


@pytest.fixture(scope="module")
def chromium():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch(headless=True)
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        yield b
        b.close()


@pytest.fixture()
def listener():
    got = Listener()
    yield got
    got.close()


@pytest.fixture()
def signed_in(chromium, listener):
    """A context standing in for the signed-in one, holding a cookie for
    the place a page could reach."""
    ctx = chromium.new_context()
    ctx.add_cookies([{"name": "session", "value": "s3cret-invented", "url": listener.base}])
    page = ctx.new_page()
    yield page
    ctx.close()


def text_of(data: bytes, tmp_path) -> str:
    out = tmp_path / "drawn.pdf"
    out.write_bytes(data)
    return receipt_pdf.pdf_text(out)


def settle(page, ms=1200):
    """Long enough for anything a script or a resource set going to have
    reached the socket."""
    page.wait_for_timeout(ms)


def test_a_script_in_the_html_never_runs(signed_in, tmp_path):
    data = receipt_pdf.inert_pdf_bytes(
        signed_in, "<p>Hello</p><script>document.body.insertAdjacentText("
                   "'beforeend','SCRIPT-RAN-4821')</script>"
                   "<img src=x onerror=\"document.body.append('HANDLER-RAN-4821')\">")
    text = text_of(data, tmp_path)
    assert "Hello" in text
    assert "SCRIPT-RAN" not in text and "HANDLER-RAN" not in text


@pytest.mark.parametrize("body", [
    "<script>new WebSocket('ws://127.0.0.1:{port}/ws')</script>",
    "<script>window.open('{base}/pop')</script>",
    "<script>fetch('{base}/f', {{credentials: 'include'}})</script>",
    "<script>navigator.sendBeacon('{base}/b', 'x')</script>",
    "<script>new EventSource('{base}/e')</script>",
    "<svg onload=\"new WebSocket('ws://127.0.0.1:{port}/ws')\"></svg>",
], ids=["websocket", "popup", "fetch", "beacon", "eventsource", "svg-handler"])
def test_a_script_never_reaches_anything(signed_in, listener, body):
    receipt_pdf.inert_pdf_bytes(signed_in, "<p>a letter</p>" + body.format(
        port=listener.port, base=listener.base))
    settle(signed_in)
    assert listener.accepted == 0


RESOURCES = [
    '<img src="{b}/i.png">', '<img srcset="{b}/s.png 2x">',
    '<picture><source srcset="{b}/p.png"><img alt=""></picture>',
    '<link rel=stylesheet href="{b}/s.css">', '<link rel=prefetch href="{b}/pf">',
    '<link rel=preload as=image href="{b}/pl.png">',
    '<style>@import url("{b}/imp.css");</style>',
    '<style>body{{background:url("{b}/bg.png")}}</style>',
    '<style>@font-face{{font-family:x;src:url("{b}/f.woff")}} p{{font-family:x}}</style>',
    '<table background="{b}/tb.png"><tr><td>x</td></tr></table>',
    '<svg><image href="{b}/svg.png" width=10 height=10 /></svg>',
    '<video poster="{b}/poster.png"></video>', '<input type=image src="{b}/in.png">',
    '<meta http-equiv="refresh" content="0;url={b}/refresh">',
    '<iframe src="{b}/frame"></iframe>', '<object data="{b}/obj"></object>',
    '<embed src="{b}/emb">', '<form action="{b}/form"><button>go</button></form>',
    '<a href="{b}/a" ping="{b}/ping">a link</a>', '<audio src="{b}/a.mp3"></audio>',
]


def test_nothing_the_html_names_is_fetched_and_its_text_still_draws(signed_in, listener,
                                                                     tmp_path):
    html = "<body background='%s/body.png'><p>The letter text</p>%s</body>" % (
        listener.base, "".join(r.format(b=listener.base) for r in RESOURCES))
    data = receipt_pdf.inert_pdf_bytes(signed_in, html)
    settle(signed_in)
    assert listener.accepted == 0
    assert "The letter text" in text_of(data, tmp_path)


def test_it_is_drawn_apart_from_the_signed_in_session_and_leaves_nothing_open(
        chromium, signed_in, monkeypatch):
    made = []
    real = type(chromium).new_context

    def noted(self, **kwargs):
        made.append(kwargs)
        ctx = real(self, **kwargs)
        made.append(ctx)
        return ctx
    monkeypatch.setattr(type(chromium), "new_context", noted)
    contexts, pages = len(chromium.contexts), len(signed_in.context.pages)
    receipt_pdf.inert_pdf_bytes(signed_in, "<p>x</p>")
    assert made and made[0].get("java_script_enabled") is False
    assert made[1] is not signed_in.context
    assert len(chromium.contexts) == contexts
    assert len(signed_in.context.pages) == pages


def test_nothing_is_drawn_when_the_block_cannot_be_put_in_place(signed_in, listener,
                                                                monkeypatch):
    """Fail closed. A drawing without its block would be the old risk."""
    drawn = []
    page_class = type(signed_in)
    monkeypatch.setattr(page_class, "set_content",
                        lambda self, *a, **k: drawn.append(1))

    def refuse(self, *a, **k):
        raise RuntimeError("route unavailable")
    monkeypatch.setattr(type(signed_in.context), "route", refuse)
    monkeypatch.setattr(page_class, "route", refuse)
    with pytest.raises(RuntimeError):
        receipt_pdf.inert_pdf_bytes(signed_in, "<script>new WebSocket('ws://127.0.0.1:%d')"
                                               "</script>" % listener.port)
    assert drawn == []


def test_on_a_persistent_profile_it_is_drawn_apart_too(chromium, listener, tmp_path):
    """Anthem runs on a profile of its own when no browser is attached.
    Playwright 1.64.1, the one PaperPull ships, gives that context a
    browser that opens a fresh context beside it, measured 2026-11-14."""
    ctx = chromium.browser_type.launch_persistent_context(str(tmp_path / "profile"),
                                                          headless=True)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        pages = len(ctx.pages)
        data = receipt_pdf.inert_pdf_bytes(
            page, "<p>Kept text</p><script>document.body.append('SCRIPT-RAN-4821');"
                  "new WebSocket('ws://127.0.0.1:%d/ws')</script>"
                  "<img src='%s/i.png'>" % (listener.port, listener.base))
        settle(page)
        assert listener.accepted == 0
        assert len(ctx.pages) == pages
        text = text_of(data, tmp_path)
        assert "Kept text" in text and "SCRIPT-RAN" not in text
    finally:
        ctx.close()


class _NoBrowser:
    """A context that has no browser to open another context in, as a
    persistent one had in older Playwrights."""

    browser = None

    def __init__(self, ctx):
        self._ctx = ctx

    def __getattr__(self, name):
        return getattr(self._ctx, name)


def test_where_no_other_context_can_be_opened_it_is_drawn_in_a_page_with_script_off(
        signed_in, listener, tmp_path):
    page = type("Page", (), {"context": _NoBrowser(signed_in.context)})()
    pages = len(signed_in.context.pages)
    data = receipt_pdf.inert_pdf_bytes(
        page, "<p>Kept text</p><script>document.body.append('SCRIPT-RAN-4821');"
              "new WebSocket('ws://127.0.0.1:%d/ws')</script>"
              "<img src='%s/i.png'><iframe src='%s/f'></iframe>"
              % (listener.port, listener.base, listener.base))
    settle(signed_in)
    assert listener.accepted == 0
    assert len(signed_in.context.pages) == pages
    text = text_of(data, tmp_path)
    assert "Kept text" in text and "SCRIPT-RAN" not in text


def test_images_given_in_the_html_itself_still_draw(signed_in, tmp_path):
    """Anthem's ID card puts each side in the page as a data: image, which
    no request fetches, one side to a page."""
    pypdf = pytest.importorskip("pypdf")
    sides = "".join('<div style="page-break-after:always"><div>%s</div>'
                    '<img src="data:image/png;base64,%s" width=40 height=25></div>'
                    % (side, PIXEL) for side in ("Front", "Back"))
    data = receipt_pdf.inert_pdf_bytes(signed_in, "<html><body>%s</body></html>" % sides)
    out = tmp_path / "card.pdf"
    out.write_bytes(data)
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2
    for page in reader.pages:
        xobjects = page["/Resources"].get("/XObject") or {}
        assert any(x.get_object().get("/Subtype") == "/Image" for x in xobjects.values())


def test_every_kind_of_character_comes_through(signed_in, tmp_path):
    words = "Café, résumé, “quotes”, € 12, 日本語"
    data = receipt_pdf.inert_pdf_bytes(
        signed_in, "<html><head><meta charset='utf-8'></head><body><p>%s</p></body></html>"
        % words)
    text = text_of(data, tmp_path)
    for word in ("Café", "résumé", "“quotes”", "€"):
        assert word in text, (word, text)
