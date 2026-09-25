"""Round four (#42), from his 0.34.2 Pilot.

Discover found ninety-six in-store receipts and Pilot saved none. Each
receipt was looked for after reloading the orders page, which opens on
Online Orders, and nothing ever switched to In-Store Receipts, so every
row was looked for on a tab that said he had no orders. His failure file
shows exactly that page: a heading, the empty-state picture, and the two
tab links as the only "receipt links" on it.

Pilot also spent half its tries on ninety-six purchases that do not
exist, dateless copies an earlier version recorded, and marked all ten
"no receipt available", which this app treated as final.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.models import IN_STORE, ONLINE
from paperpull_core.storage import JsonStore


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def row(date, amount, store="1600 N. Port Washington Road"):
    return ('<li class="order-card"><div class="date">In-Store: %s</div><div>%s</div>'
            '<div class="totals"><span>$%s</span>&nbsp;&nbsp;6 items</div>'
            '<a href="javascript:void(0)">view receipt pdf</a></li>' % (date, store, amount))


# The page as he has it: two tabs, opening on the empty online one.
TABS = """<body><main><h1>Orders and Receipts</h1>
<div role="tablist">
  <a role="tab" data-testid="t1" href="#" onclick="show('online');return false">Online Orders</a>
  <a role="tab" data-testid="t2" href="#" onclick="show('store');return false">In-Store Receipts</a>
</div>
<div id="online"><p>You haven't placed any orders yet</p></div>
<div id="store" style="display:none"><ul>%s</ul></div>
<script>
function show(which) {
  document.getElementById('online').style.display = which === 'online' ? '' : 'none';
  const s = document.getElementById('store');
  s.style.display = which === 'store' ? '' : 'none';
}
</script></main></body>"""


def purchase_from(page_html, page, date):
    page.set_content(page_html)
    site.show_tab_for(page, IN_STORE)
    cards = site.collect_cards(page)
    return next(p for p in map(site.card_to_purchase, cards) if p.purchase_date == date)


def test_an_in_store_receipt_is_looked_for_on_its_own_tab(page):
    page.set_content(TABS % row("09/19/2026", "31.23"))
    assert site.row_controls(page, SimpleNamespace(
        total="$31.23", purchase_date="2026-09-19",
        items=[SimpleNamespace(name="1600 N. Port Washington Road")])) is None, \
        "on the online tab the row is not there, which is what his Pilot hit"
    assert site.show_tab_for(page, IN_STORE)
    found = site.row_controls(page, SimpleNamespace(
        total="$31.23", purchase_date="2026-09-19",
        items=[SimpleNamespace(name="1600 N. Port Washington Road")]))
    assert found, "the row is found once its tab is showing"
    assert any(site.RECEIPT_LINK_RE.match(c["text"]) for c in found[0])


def test_an_online_order_asks_for_the_online_tab(page):
    page.set_content(TABS % row("09/19/2026", "31.23"))
    site.show_tab_for(page, IN_STORE)
    assert site.show_tab_for(page, ONLINE)
    assert page.locator("#online").is_visible()


def test_two_receipts_alike_but_for_the_date_are_not_mistaken(page):
    html = TABS % (row("09/19/2026", "31.23") + row("09/12/2026", "31.23"))
    p = purchase_from(html, page, "2026-09-12")
    cands, _els = site.row_controls(page, p)
    outline = page.evaluate_handle(
        site._ROW_CONTROLS_JS, [p.items[0].name, p.total, site.row_dates(p.purchase_date)]
    ).get_property("outline").json_value()
    assert "09/12/2026" in outline and "09/19/2026" not in outline


def test_a_date_is_matched_however_the_row_prints_it():
    assert "09/05/2026" in site.row_dates("2026-09-05")
    assert "9/5/2026" in site.row_dates("2026-09-05")
    assert site.row_dates("") == []


def test_the_receipt_step_opens_the_purchases_tab_before_pressing():
    src = (Path(site.__file__).parent / "meijer_receipts.py").read_text(encoding="utf-8")
    block = src.split("def _save_receipt")[1]
    assert block.index("show_tab_for") < block.index("press_row_receipt")


# -- what an earlier version left behind ---------------------------------------

def _app(tmp_path, discovery, progress=None):
    import meijer_receipts as mr
    d = JsonStore(tmp_path / "discovery.json", tmp_path / "Backups")
    d.data, d._loaded = dict(discovery), True
    d.save()
    p = JsonStore(tmp_path / "progress.json", tmp_path / "Backups")
    p.data, p._loaded = dict(progress or {}), True
    fake = SimpleNamespace(discovery=d, progress=p,
                           args=SimpleNamespace(redownload=False),
                           config={"min_pdf_bytes": 3000})
    return mr, fake


def test_dateless_leftovers_the_page_no_longer_shows_are_dropped(tmp_path):
    mr, app = _app(tmp_path, {
        "Online:pold1": {"order_number": "pold1", "purchase_date": ""},
        "Online:pold2": {"order_number": "pold2", "purchase_date": ""},
        "In-Store:pnew": {"order_number": "pnew", "purchase_date": "2026-09-19"},
    })
    assert mr.App._drop_undated_leftovers(app, {"In-Store:pnew"}) == 2
    assert list(app.discovery.data) == ["In-Store:pnew"]
    assert list((tmp_path / "Backups").glob("*")), "the file was backed up first"


def test_nothing_is_dropped_when_the_page_showed_nothing(tmp_path):
    mr, app = _app(tmp_path, {"Online:pold1": {"order_number": "pold1", "purchase_date": ""}})
    assert mr.App._drop_undated_leftovers(app, set()) == 0
    assert "Online:pold1" in app.discovery.data


def test_anything_ever_downloaded_is_kept_even_undated(tmp_path):
    mr, app = _app(tmp_path,
                   {"Online:pold1": {"order_number": "pold1", "purchase_date": ""}},
                   {"Online:pold1": {"downloaded_ok": True, "pdf_filename": "x.pdf"}})
    assert mr.App._drop_undated_leftovers(app, {"In-Store:pnew"}) == 0
    assert "Online:pold1" in app.discovery.data


def test_no_receipt_available_is_tried_again(tmp_path):
    """Every Meijer row has a receipt, so that state only meant the app
    missed it, and it was written for ten real purchases in 0.34.2."""
    mr, app = _app(tmp_path, {}, {"In-Store:pnew": {"state": "No Receipt Available"}})
    p = SimpleNamespace(key="In-Store:pnew")
    assert mr.App._already_done(app, p) is False


def test_a_downloaded_receipt_is_still_never_fetched_twice(tmp_path):
    mr, app = _app(tmp_path, {}, {"In-Store:pnew": {"downloaded_ok": True}})
    assert mr.App._already_done(app, SimpleNamespace(key="In-Store:pnew")) is True
