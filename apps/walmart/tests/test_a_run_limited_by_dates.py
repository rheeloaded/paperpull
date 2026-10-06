"""A run limited to some dates, among online orders whose cards show none (#63).

--year, --start-date, --end-date and the default_start_date setting kept a
purchase only when the date on its card was inside them, and dropped one
whose card showed no date without a word. Walmart's online order cards show
none, so a run limited to a year took no online order at all, and the
setting, once set, took none ever again.

Now such a purchase stays in, its order page is read for its date as it
always was, and only then is it placed. One outside the dates is not saved
and not recorded, so a later run that includes its date takes it, and it is
counted as outside the dates, never as a failure. One whose order page
shows no date either is left for manual review. A pilot's limit counts only
what the run takes, never one it opened only to learn its date, and the
date the page gave is kept, so the next run places the purchase unopened.

Every page is invented and served to Playwright's own Chromium from inside
the test. Every other request is refused, so nothing reaches Walmart or any
other site. Every order number, item and amount is invented.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

HOST = "https://orders.example.invalid"

# Online orders in the order Walmart's list shows them, each with the date
# its own page gives and its one item. None of their cards shows a date.
ORDERS = [
    ("100000000000021", "Jun 3, 2026", "Invented Garden Trowel, Steel"),
    ("100000000000022", "May 20, 2025", "Invented Desk Lamp, Black"),
    ("100000000000023", None, "Invented Shower Curtain, Gray"),
    ("100000000000024", "Feb 2, 2026", "Invented Paper Towels, 12 Rolls"),
    ("100000000000025", "Jan 5, 2026", "Invented Dish Rack, Bamboo"),
]
INSIDE_2026, OUTSIDE, NO_DATE_AT_ALL, ALSO_2026, PAST_THE_LIMIT = (o[0] for o in ORDERS)

# An order's page as Walmart lays it out, on screen with its item tile and
# on paper as an invoice. The page of the order with no date has no date
# anywhere on it.
PAGE = """<!doctype html><html><head><title>Order details</title><style>
@media print { .screen-layout { display: none } }
@media screen { .print-invoice { display: none } }
</style></head><body>
<div class="screen-layout">
  %(heading)s
  <p>Order# %(printed)s</p>
  <p>Delivered</p>
  <div data-testid="itemtile-stack"><span data-testid="productName">%(item)s</span><div>Qty 1</div><span data-testid="line-price">$18.40</span></div>
  <p>Subtotal $18.40</p><p>Tax $1.29</p><p>Total $19.69</p>
</div>
<div class="print-invoice">
  <h2>Invoice</h2>
  %(heading)s
  <p>Order# %(printed)s</p>
  <p>%(item)s Qty 1 $18.40</p>
  <p>Subtotal (1 item) $18.40</p><p>Tax $1.29</p><p>Total $19.69</p>
</div>
</body></html>"""

# Five orders from 2026 ahead of two from 2025, none dated on its card, for
# how many pages a run opens only to learn a date.
NEWER = ["1000000000000%d" % n for n in range(41, 46)]
OLDER = ["100000000000046", "100000000000047"]
LATER_FIRST = ([(n, "Mar %d, 2026" % (i + 1), "Invented Storage Bin No. %d" % i)
                for i, n in enumerate(NEWER)]
               + [(OLDER[0], "Apr 4, 2025", "Invented Wall Clock, Round"),
                  (OLDER[1], "Mar 3, 2025", "Invented Bath Mat, Blue")])

# Its card showed a later day, and an earlier run that could not open its
# page recorded that day. Its page says when it was ordered.
CARD_LATER = "100000000000051"
CARD_LATER_ORDER = [(CARD_LATER, "Dec 30, 2025", "Invented Space Heater, Small")]

PAGES = {number: PAGE % {"heading": "<h1>%s order</h1>" % date if date else "",
                         "printed": number[:7] + "-" + number[7:], "item": item}
         for number, date, item in ORDERS + LATER_FIRST + CARD_LATER_ORDER}


# -- which purchases a run limited to some dates starts from ----------------------------

def selecting(purchases, progress=None, **asked):
    """The app's own selection, with nothing else of the app around it."""
    inst = object.__new__(app_mod.App)
    inst.args = SimpleNamespace(year=asked.get("year"), start_date=asked.get("start_date"),
                                end_date=asked.get("end_date"), order_number=None,
                                max_purchases=None)
    inst.config = {"default_start_date": asked.get("setting", "")}
    inst.discovery = SimpleNamespace(data={p.key: p.to_dict() for p in purchases})
    if progress is not None:
        inst.progress = SimpleNamespace(get=lambda key: progress.get(key))
    return [p.order_number for p in inst._select_purchases(ONLINE)]


@pytest.mark.parametrize("asked", [{"year": 2026}, {"start_date": "2026-01-01"},
                                   {"end_date": "2026-12-31"},
                                   {"setting": "2026-01-01"}],
                         ids=["year", "start date", "end date", "setting"])
def test_a_card_with_no_date_stays_in_a_run_limited_by_dates(asked):
    undated = Purchase(purchase_type=ONLINE, order_number=INSIDE_2026)
    inside = Purchase(purchase_type=ONLINE, order_number=ALSO_2026, purchase_date="2026-02-02")
    outside = Purchase(purchase_type=ONLINE, order_number=OUTSIDE,
                       purchase_date="2025-05-20" if "end_date" not in asked else "2027-01-04")

    kept = selecting([undated, inside, outside], **asked)

    assert INSIDE_2026 in kept, "the order with no date on its card was dropped"
    assert ALSO_2026 in kept and OUTSIDE not in kept, kept


def test_the_date_its_order_page_gave_is_the_one_a_run_goes_by():
    """The card dated this order two days after it was placed, and a run
    has since read the order's page. A run limited to dates goes by the
    page's date, which is the one its file is named with."""
    carded = Purchase(purchase_type=ONLINE, order_number=OUTSIDE, purchase_date="2025-07-06")
    read = {carded.key: {"purchase_date": "2025-07-04"}}

    assert selecting([carded], progress=read, end_date="2025-07-05") == [OUTSIDE]


# -- in a real browser ------------------------------------------------------------------

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--disable-extensions", "--disable-sync", "--no-first-run",
            "--host-resolver-rules=MAP * ~NOTFOUND"])
        try:
            yield b
        finally:
            b.close()


@pytest.fixture()
def site_pages(browser):
    """A page on which every invented order's own page opens, and the list
    of the orders whose pages were opened, in order. Every other request is
    refused."""
    opened = []
    context = browser.new_context()

    def answer(route):
        address = route.request.url.split("?")[0]
        number = address.rsplit("/", 1)[-1]
        if address == "%s/orders/%s" % (HOST, number) and number in PAGES:
            opened.append(number)
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=PAGES[number])
        else:
            route.abort()

    context.route("**/*", answer)
    page = context.new_page()
    yield SimpleNamespace(context=context, page=page, opened=opened)
    context.close()


@pytest.fixture(autouse=True)
def the_invented_site(monkeypatch):
    """Order pages open on the invented host, the list is already known
    rather than read again, and the scroll before a print is kept short."""
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(HOST + "/"))
    real = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=50: real(page, rounds, delay_ms))
    monkeypatch.setattr(app_mod.App, "cmd_discover", lambda self, types=None, quiet=False: {})


def discovered(tmp_path, orders=ORDERS, card_text="Delivered\n$19.69"):
    """The orders as discovery records them from their cards, by default
    cards with no date."""
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    records = {}
    for number, _date, _item in orders:
        card = site.RawCard(href="", text=card_text, order_id=number, kind=ONLINE)
        purchase = site.card_to_purchase(card, ONLINE, base_url=HOST)
        records[purchase.key] = dict(purchase.to_dict(), state="Discovered")
    (out / "discovery.json").write_text(json.dumps(records), encoding="utf-8")
    return records


def run(tmp_path, site_pages, *flags, setting="", pilot=True):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0,
        "pilot_online": 2, "default_start_date": setting}), encoding="utf-8")
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), *flags]))
    app._context, app._work_page = site_pages.context, site_pages.page
    if pilot:
        app.cmd_pilot(online=True, instore=False)
    else:
        app.cmd_run([ONLINE], "online")
    return app


def records(tmp_path, name):
    path = tmp_path / "out" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def key(number):
    return "Online:" + number


def printed(capsys):
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("flags, setting", [(("--year", "2026"), ""), ((), "2026-01-01")],
                         ids=["year", "default_start_date"])
def test_a_pilot_limited_by_dates_opens_the_orders_with_no_date_and_places_them(
        tmp_path, site_pages, capsys, flags, setting):
    discovered(tmp_path)
    app = run(tmp_path, site_pages, *flags, setting=setting)
    out = printed(capsys)
    progress, found = records(tmp_path, "progress.json"), records(tmp_path, "discovery.json")

    # Two taken, the pilot's limit, counting neither the order outside the
    # dates nor the one with no date, and the fifth never opened.
    assert site_pages.opened == [INSIDE_2026, OUTSIDE, NO_DATE_AT_ALL, ALSO_2026], \
        site_pages.opened
    for number, date in ((INSIDE_2026, "2026-06-03"), (ALSO_2026, "2026-02-02")):
        assert progress[key(number)]["downloaded_ok"] is True, progress.get(key(number))
        assert progress[key(number)]["purchase_date"] == date
    assert len(list((tmp_path / "out" / "Invoices").glob("*.pdf"))) == 2
    assert "this run's limit of 2 was reached, so 1 purchase not looked at is left" in out, out

    # Outside the dates. Not saved, not recorded, still as discovered, and
    # its date kept.
    assert key(OUTSIDE) not in progress, progress.get(key(OUTSIDE))
    assert found[key(OUTSIDE)]["state"] == "Discovered", found[key(OUTSIDE)]
    assert found[key(OUTSIDE)]["purchase_date"] == "2025-05-20", found[key(OUTSIDE)]
    assert "dates it 2025-05-20, outside the dates asked for" in out, out
    assert "1 purchase(s) turned out to be outside the dates asked for" in out, out
    assert app.stats["outside_dates"] == 1 and app.stats["failed"] == 0, app.stats
    assert "! " + key(OUTSIDE) not in out, "outside the dates is not a problem"

    # No date on its page either. Left for manual review, nothing saved.
    rec = progress[key(NO_DATE_AT_ALL)]
    assert rec["state"] == "Needs Manual Review" and not rec.get("pdf_path"), rec
    assert "No date on its order page" in rec["notes"], rec
    assert "! %s: Needs Manual Review - No date on its order page" % key(NO_DATE_AT_ALL) in out
    assert not list((tmp_path / "out" / "Manual Review").iterdir())

    # The dates the pages gave are kept, and the order never opened is as it was.
    assert found[key(INSIDE_2026)]["purchase_date"] == "2026-06-03"
    assert found[key(ALSO_2026)]["purchase_date"] == "2026-02-02"
    assert found[key(PAST_THE_LIMIT)]["purchase_date"] == ""
    assert found[key(PAST_THE_LIMIT)]["state"] == "Discovered"


def test_the_next_run_places_it_unopened_and_a_wider_one_takes_it(tmp_path, site_pages,
                                                                   capsys):
    discovered(tmp_path)
    app = run(tmp_path, site_pages, "--year", "2026")
    assert OUTSIDE in site_pages.opened, site_pages.opened
    app.write_run_summary()
    summary = (tmp_path / "out" / "run-summary.txt").read_text(encoding="utf-8")
    assert "Outside the dates asked:   1" in summary, summary
    assert "Failed:                    0" in summary, summary

    # A full run over the same dates, with no limit to stop it early. The
    # order outside them is known to be, so its page is not opened again,
    # and the one the pilot never reached is taken.
    site_pages.opened.clear()
    run(tmp_path, site_pages, "--year", "2026", pilot=False)
    assert OUTSIDE not in site_pages.opened, site_pages.opened
    assert PAST_THE_LIMIT in site_pages.opened, site_pages.opened
    capsys.readouterr()

    # A run that includes its year takes it. It had stayed as discovered.
    site_pages.opened.clear()
    run(tmp_path, site_pages, "--year", "2025", pilot=False)
    progress = records(tmp_path, "progress.json")
    assert site_pages.opened[0] == OUTSIDE, site_pages.opened
    assert progress[key(OUTSIDE)]["downloaded_ok"] is True, progress[key(OUTSIDE)]
    assert progress[key(OUTSIDE)]["purchase_date"] == "2025-05-20"


def test_without_dates_a_pilot_takes_what_it_always_took(tmp_path, site_pages, capsys):
    """What worked before still works. Nothing is placed by date, the first
    ones on the list are taken up to the limit, and an order whose page
    shows no date is saved as it always was."""
    discovered(tmp_path)
    run(tmp_path, site_pages)
    progress = records(tmp_path, "progress.json")

    assert site_pages.opened == [INSIDE_2026, OUTSIDE], site_pages.opened
    assert all(progress[key(n)]["downloaded_ok"] is True for n in (INSIDE_2026, OUTSIDE))
    assert "outside the dates" not in printed(capsys)


def test_a_store_purchase_is_left_as_it_was():
    """Store purchases have a date on their card, and a run limited to
    dates places them by it before opening anything, as it always did."""
    store = Purchase(purchase_type=IN_STORE, order_number="10000000000000000031",
                     purchase_date="2025-11-02")
    inst = object.__new__(app_mod.App)
    inst.args = SimpleNamespace(year=2026, start_date=None, end_date=None,
                                order_number=None, max_purchases=None)
    inst.config = {"default_start_date": ""}
    inst.discovery = SimpleNamespace(data={store.key: store.to_dict()})
    assert inst._select_purchases(IN_STORE) == []


# -- from the review of the change above ---------------------------------------------

def test_a_run_opens_only_so_many_pages_to_learn_dates(tmp_path, site_pages, capsys,
                                                      monkeypatch):
    """A pilot for 2025, its limit two, behind five 2026 orders with no
    date on their cards. It opened every one of them to take two. Now it
    stops after so many pages opened for nothing, says how many it left,
    and the next run carries on from the dates it learned."""
    monkeypatch.setattr(app_mod, "DATES_LEARNED_PER_RUN", 3, raising=False)
    discovered(tmp_path, LATER_FIRST)
    app = run(tmp_path, site_pages, "--year", "2025")
    out = printed(capsys)

    assert site_pages.opened == NEWER[:3], site_pages.opened
    assert "4 order(s) with no date yet were not opened" in out, out
    app.write_run_summary()
    summary = (tmp_path / "out" / "run-summary.txt").read_text(encoding="utf-8")
    assert "Undated, left for later:   4" in summary, summary

    site_pages.opened.clear()
    run(tmp_path, site_pages, "--year", "2025")
    assert site_pages.opened == NEWER[3:] + OLDER, site_pages.opened
    progress = records(tmp_path, "progress.json")
    assert all(progress[key(n)]["downloaded_ok"] is True for n in OLDER), progress


def test_a_date_learned_over_an_earlier_record_is_the_one_used(tmp_path, site_pages):
    """The run for 2026 opened it, found it ordered in 2025 and left it, and
    the earlier run's record still said 2026, which the selection reads
    first, so the run for 2025 left it out too."""
    found = discovered(tmp_path, CARD_LATER_ORDER, card_text="Delivered on Jan 3, 2026\n$19.69")
    assert found[key(CARD_LATER)]["purchase_date"] == "2026-01-03"
    earlier = Purchase(purchase_type=ONLINE, order_number=CARD_LATER,
                       purchase_date="2026-01-03", state="Needs Manual Review",
                       notes="Details page failed to load twice")
    (tmp_path / "out" / "progress.json").write_text(
        json.dumps({earlier.key: earlier.to_dict()}), encoding="utf-8")

    run(tmp_path, site_pages, "--year", "2026", pilot=False)
    rec = records(tmp_path, "progress.json")[key(CARD_LATER)]
    assert site_pages.opened == [CARD_LATER], site_pages.opened
    assert rec["purchase_date"] == "2025-12-30", rec
    assert rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok"), rec

    run(tmp_path, site_pages, "--year", "2025", pilot=False)
    rec = records(tmp_path, "progress.json")[key(CARD_LATER)]
    assert rec.get("downloaded_ok") is True, rec


def test_an_order_whose_page_showed_no_date_is_not_opened_again(tmp_path, site_pages, capsys):
    discovered(tmp_path, [ORDERS[2]])
    run(tmp_path, site_pages, "--year", "2026", pilot=False)
    assert site_pages.opened == [NO_DATE_AT_ALL], site_pages.opened
    capsys.readouterr()

    site_pages.opened.clear()
    run(tmp_path, site_pages, "--year", "2026", pilot=False)
    assert site_pages.opened == [], site_pages.opened
    assert "1 order(s) were not opened, since their order page showed no date" in printed(capsys)

    # A run without dates takes it, as it always did.
    run(tmp_path, site_pages, pilot=False)
    assert records(tmp_path, "progress.json")[key(NO_DATE_AT_ALL)]["downloaded_ok"] is True
