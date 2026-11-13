"""One document Stripe refuses on its own fails alone.

A 401, a 403 or a redirect off stripe.com for one document's file was read
as a sign-out, so the run stopped at that document. A document Stripe will
not give is refused on every run, so every run stopped there and Continue
stopped at it again, the loop of #124. Now the lists are read again when
one document is refused, the same way Discover reads them. A session that
ended is refused the lists too, and that stops the run. Lists that still
read leave the document failed alone, nothing saved, and the next run
tries it again. The document is asked for once.
"""
import base64
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import urlparse

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import stripe_site as site  # noqa: E402
import stripe_docs as docs  # noqa: E402
from paperpull_core import testkit  # noqa: E402

ACCT = "https://dashboard.stripe.com/acct_TEST123"
INV_API = "https://dashboard.stripe.com" + site.INVOICES_API
TAX_API = "https://dashboard.stripe.com" + site.TAX_API
PDF = testkit.text_pdf(["Stripe made-up fee invoice"])

# Three fee invoices, by id, the end of their period and their own link.
ROWS = [{"id": "inv_3", "invoiceNumber": "INV-3", "periodEndExclusive": 1927670400,
         "link": "https://files.stripe.com/f3"},
        {"id": "inv_2", "invoiceNumber": "INV-2", "periodEndExclusive": 1924992000,
         "link": "https://files.stripe.com/f2"},
        {"id": "inv_1", "invoiceNumber": "INV-1", "periodEndExclusive": 1922313600,
         "link": "https://files.stripe.com/f1"}]

# What one document's file can be answered with that read as a sign-out,
# from inside the page or, where the page may not ask that host, through
# the browser's own session.
REFUSALS = {
    "401": {"how": 401},
    "403": {"how": 403},
    "redirect off stripe.com": {"how": "off"},
    "401 through the session": {"how": 401, "blocked": True},
    "403 through the session": {"how": 403, "blocked": True},
}


class Req:
    def all_headers(self):
        return {"stripe-version": "v", "x-stripe-csrf-token": "t"}


class Resp:
    def __init__(self, url, body=None, status=200, headers=None):
        self.url, self._body, self.status = url, body, status
        self.headers = headers or {}
        self.request = Req()

    def json(self):
        return self._body


class Session:
    """The browser's own session, page.context.request."""

    def __init__(self, page):
        self.page = page

    def get(self, url, **_):
        self.page.asked.append(url)
        if url in self.page.refused:
            self.page.refuse_now()
            return Resp(url, status=self.page.how, headers={"content-type": "text/html"})
        return Resp(url, headers={"content-type": "application/pdf"})


class Context:
    def __init__(self, page):
        self.request = Session(page)


class Page:
    """A signed-in Dashboard tab. Opening a list page makes it receive the
    list. Each document's file is answered from inside the page, refused
    with `how` for the links in `refused`. A link `blocked` to a page
    script is asked through the session instead. A session that ends at
    the refusal (`signs_out`) answers the lists with a 401 from then on."""

    def __init__(self, refused=(), how=401, blocked=False, signs_out=False):
        self.url = ACCT + "/dashboard"
        self.refused, self.how, self.blocked, self.signs_out = set(refused), how, blocked, signs_out
        self.list_status = 200
        self.rows = ROWS
        self.listeners, self.asked, self.lists_read = [], [], 0
        self.context = Context(self)

    def refuse_now(self):
        if self.signs_out:
            self.list_status = 401

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        self.url = url
        path = "/" + urlparse(url).path.split("/", 2)[2]
        if path == site.INVOICES_PATH:
            self.lists_read += 1
            if self.rows is None:
                return
            resp = Resp(INV_API, {"data": self.rows, "has_more": False}, status=self.list_status)
        elif path == site.TAX_PATH:
            resp = Resp(TAX_API, {"object": "list", "data": [], "has_more": False}, status=self.list_status)
        else:
            return
        for fn in list(self.listeners):
            fn(resp)

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class Nothing:
            def count(self):
                return 0
        return Nothing()

    def evaluate(self, _js, args):
        url, _headers = args
        if url in self.refused and self.blocked:
            raise RuntimeError("TypeError: Failed to fetch")
        self.asked.append(url)
        if url in self.refused:
            self.refuse_now()
            if self.how == "off":
                return {"status": 200, "ct": "text/html", "url": "https://sign-in.example.test/x"}
            return {"status": self.how, "ct": "text/html", "url": url}
        return {"status": 200, "ct": "application/pdf", "url": url, "b64": base64.b64encode(PDF).decode()}


@pytest.fixture(autouse=True)
def fresh_cache():
    site._cache.update(at=0.0, docs=[])
    yield
    site._cache.update(at=0.0, docs=[])


def take(page, out, n="2"):
    return site.download_bill(page, None, "2030-12-31", out, href="https://files.stripe.com/f" + n,
                              document_id="inv_" + n)


@pytest.mark.parametrize("way", list(REFUSALS))
@pytest.mark.parametrize("kept", [False, True])
def test_a_document_refused_while_the_lists_still_read_fails_alone(tmp_path, way, kept):
    page = Page(refused={"https://files.stripe.com/f2"}, **REFUSALS[way])
    if kept:
        site.collect_download_docs(page)
    out = tmp_path / "i.pdf"
    assert take(page, out) is False
    assert not out.exists()
    # The lists are read once more after the refusal, and the document is
    # asked for once, never a second time.
    assert page.lists_read == 2
    assert page.asked == ["https://files.stripe.com/f2"]


@pytest.mark.parametrize("way", list(REFUSALS))
def test_a_document_refused_and_the_lists_refused_after_it_is_a_sign_out(tmp_path, way):
    page = Page(refused={"https://files.stripe.com/f2"}, signs_out=True, **REFUSALS[way])
    out = tmp_path / "i.pdf"
    with pytest.raises(site.SessionExpired):
        take(page, out)
    assert not out.exists()
    assert page.asked == ["https://files.stripe.com/f2"]


@pytest.mark.parametrize("rows", [[], None])
def test_lists_read_empty_after_a_refusal_are_no_lists(tmp_path, rows):
    """Lists that show nothing, or never came, after this document was
    listed are not lists that still read."""
    page = Page(refused={"https://files.stripe.com/f2"}, how=403)
    site.collect_download_docs(page)
    page.rows = rows
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path / "i.pdf")
    assert page.asked == ["https://files.stripe.com/f2"]


def test_a_document_given_reads_no_list_again(tmp_path):
    page = Page()
    site.collect_download_docs(page)
    out = tmp_path / "i.pdf"
    assert take(page, out)
    assert page.lists_read == 1


def make_app(tmp):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args(["--resume", "--config", str(cfg)]))


def run_with(tmp_path, page):
    """A Run All's downloads over the three listed invoices, with what it
    printed."""
    app = make_app(tmp_path)
    for r in site.collect_download_docs(page):
        app._record_rawdoc(r, site.BILLING_URL)
    app.discovery.save()
    app.check_session = lambda p: None
    app._on_its_site = lambda: page
    app._dl_dir = None   # set where the app opens its page, which this skips
    app._delay = lambda *a, **k: None
    seen = io.StringIO()
    ended = None
    try:
        with redirect_stdout(seen):
            app.process(app._select())
    except SystemExit as e:
        ended = e
    return app, ended, seen.getvalue()


def test_one_document_refused_while_the_lists_read_fails_alone_and_the_rest_are_saved(tmp_path):
    """The refused document stopped the run before, so the ones after it
    were never asked for, and every later run stopped at it again."""
    page = Page(refused={"https://files.stripe.com/f2"}, how=403)
    app, ended, said = run_with(tmp_path, page)
    assert ended is None, said
    states = {v["document_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"inv_3": "Completed", "inv_2": "Failed", "inv_1": "Completed"}
    assert (app.stats["failed"], len(app.stats["new_files"])) == (1, 2)
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert "session has expired" not in said
    assert page.asked.count("https://files.stripe.com/f2") == 1


def test_one_document_refused_and_the_lists_after_it_stop_the_run(tmp_path):
    page = Page(refused={"https://files.stripe.com/f3"}, how=401, signs_out=True)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, SystemExit)
    assert "session has expired" in said
    assert "Nothing was saved" not in said
    assert page.asked == ["https://files.stripe.com/f3"]
