"""ING's account tabs (#169) read by the real page scripts in a real browser.

A made-up Postbox, laid out as MelleD's recordings show it: one box above
the list whose children are all links, one per account, each to the list's
own page with an opaque query value, the selected one a link too. Every
name, subject and date here is invented, and no request leaves the machine.
"""
import io
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ing_site as site
from paperpull_core import redact

pw_api = pytest.importorskip("playwright.sync_api")

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

ACCOUNTS = ["Alex Muster", "Mia Muster", "Leo Muster"]
DOCS = {0: [("Kontoauszug", "Kontoauszug 01/2026", "31.01.2026")],
        1: [("Kontoauszug", "Kontoauszug 02/2026", "28.02.2026"),
            ("Steuerbescheinigung", "Jahressteuerbescheinigung 2025", "15.02.2026")],
        2: []}


def pdf_of(name: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Subject": "document %s" % name})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


class Site:
    """What the made-up Postbox shows. `mark` is how the selected tab is
    marked, `bar` how the tab bar is built."""

    def __init__(self):
        self.mark = "class"
        self.bar = "links"
        self.requests = []

    def tab(self, i, selected, version):
        label = ACCOUNTS[i]
        href = "/app/postbox/postbox?x=t%d-%d" % (version, i)
        if self.mark == "class":
            return '<a class="pill%s" href="%s">%s</a>' % (
                " pill--active" if selected else "", href, label)
        if self.mark == "aria-selected":
            return '<a class="pill" aria-selected="%s" href="%s">%s</a>' % (
                "true" if selected else "false", href, label)
        if self.mark == "aria-current":
            return '<a class="pill"%s href="%s">%s</a>' % (
                ' aria-current="page"' if selected else "", href, label)
        if self.mark == "superset":
            return '<a class="pill%s" href="%s">%s</a>' % (
                " filled" if selected else "", href, label)
        return '<a class="pill" href="%s">%s</a>' % (href, label)

    def page(self, account, version):
        tabs = "".join(self.tab(i, i == account, version) for i in range(len(ACCOUNTS)))
        if self.bar == "links":
            bar = '<div class="box" id="b1"><div class="pills">%s</div></div>' % tabs
        elif self.bar == "two":
            bar = ('<div class="box"><div class="pills">%s</div></div>'
                   '<div class="box"><div class="pills">%s</div></div>') % (tabs, tabs)
        elif self.bar == "with-a-button":
            bar = '<div class="box"><div class="pills">%s<button>+</button></div></div>' % tabs
        else:
            bar = ""
        rows = "".join(
            '<div class="ibbr-table-row"><div class="postbox-grid-left"><span>%s</span></div>'
            '<div class="postbox-grid-description">%s</div>'
            '<div class="postbox-grid-right">%s</div>'
            '<a href="/app/postbox/postbox?x=d%d-%d-%d">Download</a></div>'
            % (kind, subject, date, version, account, n)
            for n, (kind, subject, date) in enumerate(DOCS[account]))
        notice = "" if rows else "Zu Ihrer Suche können keine Dokumente angezeigt werden"
        return ('<html><body><nav><a href="/app/obligo">Meine Konten</a>'
                '<a href="/app/postbox/postbox_archiv">Archiv</a></nav><main>%s'
                '<div class="ibbr-table-wrapper-postbox">%s%s</div></main>'
                '<script>window.clicked = false; document.addEventListener("click",'
                ' () => { window.clicked = true; }, true);</script></body></html>'
                % (bar, rows, notice))


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setattr(redact, "_PRIVATE_WORDS", [])
    made = Site()
    state = {"version": 0}
    with pw_api.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=ARGS)
        context = browser.new_context()

        def answer(route):
            url = urlsplit(route.request.url)
            made.requests.append((route.request.method, route.request.url))
            x = (parse_qs(url.query).get("x") or [""])[0]
            if url.path == "/app/postbox/postbox" and x.startswith("d"):
                _version, account, n = (int(v) for v in x[1:].split("-"))
                route.fulfill(content_type="application/pdf",
                              body=pdf_of("acct%ddoc%d" % (account, n)))
            elif url.path == "/app/postbox/postbox":
                account = int(x.split("-")[1]) if x.startswith("t") else 0
                state["version"] += 1
                route.fulfill(content_type="text/html", body=made.page(account, state["version"]))
            else:
                route.fulfill(status=404, content_type="text/plain", body="not found")

        context.route("**/*", answer)
        page = context.new_page()
        page.goto(site.URLS["documents"])
        made.tab_page = page
        site.remember_home("")
        site._listing.clear()
        try:
            yield made
        finally:
            site.remember_home("")
            site._listing.clear()
            context.close()
            browser.close()


def listing(bank):
    return site._all_rows(bank.tab_page, {"read_archive": False}, fresh=True)


@pytest.mark.parametrize("mark", ["class", "aria-selected", "aria-current", "superset"])
def test_each_accounts_rows_are_read_behind_its_own_tab(bank, mark):
    bank.mark = mark
    rows = listing(bank)
    by_tab = {}
    for r in rows:
        by_tab.setdefault(r["tab"], []).append(r["title"])
    assert by_tab == {"": ["Kontoauszug 01/2026"],
                      "Mia Muster": ["Kontoauszug 02/2026",
                                     "Jahressteuerbescheinigung 2025"]}
    assert {r["account_folder"] for r in rows} == {"", "Mia Muster"}
    assert site.accounts_read() == [1, 2, 0]
    assert bank.tab_page.evaluate("window.clicked") is False
    assert all(method == "GET" for method, _url in bank.requests)


def test_a_childs_document_is_fetched_from_its_own_tab(bank, tmp_path):
    rows = listing(bank)
    mia = [r for r in rows if r["tab"] == "Mia Muster" and r["title"] == "Kontoauszug 02/2026"]
    assert len(mia) == 1
    out = tmp_path / "doc.pdf"

    def numbered(listed):
        seen, numbers = {}, []
        for r in listed:
            k = (r["title"], r["date"], r["account"], r["tab"], site.filed_category(r))
            numbers.append((seen.get(k, 0), True))
            seen[k] = seen.get(k, 0) + 1
        return numbers

    saved = site.download_document(bank.tab_page, "Kontoauszug 02/2026", "2026-02-28", out,
                                   category=site.ACCOUNT, number_rows=numbered,
                                   config={"read_archive": False}, tab="Mia Muster")
    assert saved and b"document acct1doc0" in out.read_bytes()
    assert bank.tab_page.evaluate("window.clicked") is False


def test_tabs_whose_selected_one_cannot_be_told_stop_the_listing(bank):
    bank.mark = "none"
    with pytest.raises(site.ListStopped, match="selected cannot be told"):
        listing(bank)


def test_two_tab_bars_stop_the_listing(bank):
    bank.bar = "two"
    with pytest.raises(site.ListStopped, match="more than one row of account tabs"):
        listing(bank)


def test_a_postbox_with_no_tab_bar_reads_as_it_always_did(bank):
    bank.bar = "none"
    rows = listing(bank)
    assert [(r["title"], r["tab"], r["account_folder"]) for r in rows] == \
        [("Kontoauszug 01/2026", "", "")]
    assert site.accounts_read() == [1]


def test_a_box_of_tabs_with_another_control_is_not_read_as_tabs_and_is_counted(bank):
    bank.bar = "with-a-button"
    rows = listing(bank)
    assert {r["tab"] for r in rows} == {""}
    census = site.postbox_census(bank.tab_page)
    assert census["account_tab_bars"] == 0 and census["account_tab_boxes_not_read"] == 1


def test_diagnose_counts_the_tabs_by_number_only(bank):
    census = site.postbox_census(bank.tab_page)
    assert census["account_tab_bars"] == 1 and census["account_tabs"] == 3
    assert census["account_tabs_marked"] == 1 and census["account_tab_selected_told"] is True
    assert not any(name.split()[0] in str(census) for name in ACCOUNTS)
