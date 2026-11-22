"""An order list drawn without the order cards the app knows (#207).

A tester's amazon.de list drew each order as a plain block, with no card
class, no orderID= link the old selector finds and no order number its
text gives the reader, so Discover stopped at "the order list did not
appear" with the list on screen. Each order's header still carries its own
invoice menu (Rechnung), Amazon's popover trigger whose data-a-popover
names /your-orders/invoice/popover?orderId=<id>, beside an order-details
link. The ship-to name is a popover trigger of the same shape, so the
orders here are read only from the address a trigger's data names, never
from its place or its words, in every store the app knows.

The pages are drawn in Playwright's own Chromium with set_content, and the
module's readers are called on them. Every order number, name and amount
is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_site as site
from paperpull_core import browser as browser_launcher

A = "302-0000000-0000101"
B = "302-0000000-0000102"
DECOY = "302-0000000-0000999"
ADDR = "302-0000000-0000555"
DIG = "D01-0000000-0000104"


@pytest.fixture(autouse=True)
def back_to_dot_com():
    yield
    site.set_marketplace(None)


@pytest.fixture(scope="module")
def browser():
    sync = pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    with sync.sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=found[0][1], headless=True,
                               args=["--host-resolver-rules=MAP * ~NOTFOUND"])
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    p = browser.new_page()
    yield p
    p.close()


def popover(url, **more) -> str:
    data = dict(more)
    data["url"] = url
    return json.dumps(data)


def menu(order_id=None, url=None, label="Rechnung") -> str:
    """An order's invoice menu, as Amazon draws its popover trigger."""
    url = url or "/your-orders/invoice/popover?orderId=%s&relatedRequestId=X" % order_id
    return ("<span class='a-declarative' data-action='a-popover' data-a-popover='%s'>"
            "<a href='javascript:void(0)' class='a-popover-trigger'>%s<i class='a-icon'></i></a>"
            "</span>" % (popover(url, position="triggerBottom").replace("'", "&#39;"), label))


def ship_to(data=None, name="Dana Example") -> str:
    """The ship-to name, a popover trigger of the same shape whose card
    holds the address."""
    data = data if data is not None else json.dumps({"position": "triggerBottom",
                                                     "closeButton": "false"})
    return ("<span class='a-declarative' data-action='a-popover' data-a-popover='%s'>"
            "<a href='javascript:void(0)' class='a-popover-trigger'>%s<i class='a-icon'></i></a>"
            "</span><div class='a-popover-preload'>1 Example Street</div>"
            % (data.replace("'", "&#39;"), name))


def details(order_id, param="orderID", path="/gp/your-account/order-details") -> str:
    return "<a href='%s?%s=%s&ref=ppx'>Bestelldetails anzeigen</a>" % (path, param, order_id)


def order(order_id, when, total, header=None, items=1) -> str:
    """One order's block the way the tester's list draws it, four data
    attributes and no class the app knows. Its number is not in its text."""
    header = header if header is not None else (
        ship_to() + details(order_id) + "<i class='a-icon a-icon-text-separator'></i>"
        + menu(order_id))
    goods = "".join("<div><a href='/dp/B00000000%d'>Invented Product %d</a></div>" % (i, i)
                    for i in range(items))
    return ("<div class='x1' data-a='1' data-b='2' data-c='3' data-d='4'>"
            "<div class='h'><div><div>Bestellung aufgegeben</div><div>%s</div></div>"
            "<div><div>Summe</div><div>%s</div></div>"
            "<ul><li>%s</li></ul></div>%s</div>" % (when, total, header, goods))


def orders_page(blocks, count=2, before="", after="") -> str:
    return ("<!doctype html><html><head><title>Meine Bestellungen</title></head><body>"
            "<header><nav>Konto</nav></header>"
            "<section><div class='y'>"
            "<div><form action='/your-orders/orders'><label class='time-filter__label' "
            "for='t'><b>%d Bestellungen</b> aufgegeben in</label>"
            "<select id='t'><option>2026</option></select></form></div>"
            "%s<div id='orders'>%s</div>%s"
            "</div></section></body></html>" % (count, before, "".join(blocks), after))


TWO = orders_page([order(A, "3. März 2026", "23,41 €"), order(B, "1. Februar 2026", "58,20 €")])


def read(page, html):
    page.set_content(html)
    return [(c.order_id, c.text) for c in site.collect_cards(page)]


# -- the tester's layout -----------------------------------------------------------

def test_the_testers_layout_is_a_list_and_each_order_is_read_with_its_own_date(page):
    site.set_marketplace("amazon.de")
    found = read(page, TWO)
    assert [oid for oid, _ in found] == [A, B]
    assert site.orders_listed(page, 0)
    a, b = (site.card_to_purchase(site.RawCard(href="", text=t, order_id=o), "Online")
            for o, t in found)
    assert (a.purchase_date, a.total) == ("2026-03-03", "€23.41")
    assert (b.purchase_date, b.total) == ("2026-02-01", "€58.20")
    assert "58,20" not in found[0][1] and "23,41" not in found[1][1]


def test_a_list_with_only_the_invoice_menus_is_read(page):
    site.set_marketplace("amazon.de")
    blocks = [order(o, d, t, header=ship_to() + menu(o))
              for o, d, t in ((A, "3. März 2026", "1,00 €"), (B, "1. März 2026", "2,00 €"))]
    assert [o for o, _ in read(page, orders_page(blocks))] == [A, B]


@pytest.mark.parametrize("param", ["orderID", "orderId", "orderid"])
@pytest.mark.parametrize("path", ["/gp/your-account/order-details", "/your-orders/order-details",
                                  "/gp/your-account/order-details/ref=ppx_yo_dt"])
def test_a_list_with_only_the_details_links_is_read_whatever_the_case(page, param, path):
    site.set_marketplace("amazon.de")
    blocks = [order(o, "3. März 2026", "1,00 €", header=details(o, param, path)) for o in (A, B)]
    assert [o for o, _ in read(page, orders_page(blocks))] == [A, B]


def test_the_testers_page_with_nothing_that_names_an_order_still_did_not_appear(page):
    """The page as the failure file counts it, the count, product links and
    pre-drawn popovers, and nothing naming an order. Still not a list."""
    site.set_marketplace("amazon.de")
    blocks = [order(o, "3. März 2026", "1,00 €", header=ship_to(), items=3) for o in (A, B)]
    page.set_content(orders_page(blocks, count=16))
    assert not site.orders_listed(page, 0)
    assert site.collect_cards(page) == []


def test_ship_to_cards_carrying_an_id_shaped_value_are_not_a_list(page):
    site.set_marketplace("amazon.de")
    data = popover("/your-orders/address/popover?orderId=%s" % ADDR)
    blocks = [order(A, "3. März 2026", "1,00 €", header=ship_to(data))]
    page.set_content(orders_page(blocks, count=16))
    assert not site.orders_listed(page, 0)
    assert site.collect_cards(page) == []


# -- only the invoice menu names an order -------------------------------------------

@pytest.mark.parametrize("data", [
    popover("/your-orders/address/popover?orderId=%s" % ADDR),
    json.dumps({"addressId": ADDR}),
    popover("/your-orders/returns/popover?orderId=%s" % ADDR),
    popover("/your-orders/tracking/popover?orderId=%s" % ADDR),
])
def test_the_ship_to_card_or_another_popover_never_names_an_order(page, data):
    """The ship-to trigger comes first in the header and the invoice menu
    second. Whatever the ship-to data holds, only the invoice menu's order
    is read, and its block keeps its own date and total."""
    site.set_marketplace("amazon.de")
    header = ship_to(data) + menu(A)
    found = read(page, orders_page([order(A, "3. März 2026", "23,41 €", header=header)], 1))
    assert [o for o, _ in found] == [A]
    assert "3. März 2026" in found[0][1] and "23,41" in found[0][1]


@pytest.mark.parametrize("url", [
    "/your-orders/invoice/popover",                                       # no id
    "/your-orders/invoice/popover?orderId=",                              # empty
    "/your-orders/invoice/popover?orderId=abc",
    "/your-orders/invoice/popover?parentOrderId=%s" % B,
    "/your-orders/invoice/popover?xorderId=%s" % B,
    "/your-orders/invoice/popover?orderIdx=%s" % B,
    "/your-orders/invoice/popover?ref=%s" % B,
    "/your-orders/invoice/popover?returnTo=%%2Fx%%3ForderId%%3D%s" % B,
    "/your-orders/invoice/popover?orderId=%s&orderId=%s" % (B, DECOY),   # two orders
    "/your-orders/invoice/popoverX?orderId=%s" % B,
    "/your-orders/invoice/popover/extra?orderId=%s" % B,
    "/x?next=/your-orders/invoice/popover?orderId=%s" % B,
    "https://www.amazon.fr/your-orders/invoice/popover?orderId=%s" % B,   # another store
    "https://evil.example/your-orders/invoice/popover?orderId=%s" % B,
    "//evil.example/your-orders/invoice/popover?orderId=%s" % B,
    "https://www.amazon.de.evil.example/your-orders/invoice/popover?orderId=%s" % B,
    "https://www.amazon.de@evil.example/your-orders/invoice/popover?orderId=%s" % B,
    "http://www.amazon.de/your-orders/invoice/popover?orderId=%s" % B,
    "https:\\\\evil.example\\your-orders/invoice/popover?orderId=%s" % B,
])
def test_a_menu_that_does_not_name_one_order_of_this_store_names_none(page, url):
    site.set_marketplace("amazon.de")
    blocks = [order(A, "3. März 2026", "1,00 €"),
              order(B, "1. März 2026", "2,00 €", header=menu(url=url))]
    assert [o for o, _ in read(page, orders_page(blocks))] == [A]


@pytest.mark.parametrize("raw", [
    '{"url":"/your-orders/invoice/popover?orderId=%s"' % B,     # no closing brace
    "{url:'/your-orders/invoice/popover?orderId=%s'}" % B,      # bare keys
    '{&quot;url&quot;:&quot;/your-orders/invoice/popover?orderId=%s&quot;}' % B,
    '["/your-orders/invoice/popover?orderId=%s"]' % B,
    '{"url": 7}',
    "",
])
def test_data_that_does_not_read_cleanly_names_no_order(raw):
    site.set_marketplace("amazon.de")
    assert site.invoice_menu_order_id(raw) is None


def test_escaped_slashes_in_the_data_are_read():
    site.set_marketplace("amazon.de")
    raw = '{"url":"\\/your-orders\\/invoice\\/popover?orderId=%s"}' % B
    assert site.invoice_menu_order_id(raw) == B


def test_the_store_own_host_and_a_language_prefix_are_read():
    site.set_marketplace("amazon.de")
    assert site.invoice_menu_order_id(
        popover("https://www.amazon.de/your-orders/invoice/popover?orderId=%s" % A)) == A
    assert site.invoice_menu_order_id(
        popover("/-/en/your-orders/invoice/popover?orderId=%s" % A)) == A
    assert site.invoice_menu_order_id(
        popover("/your-orders/invoice/popover?orderId=%s" % DIG)) == DIG


def test_a_product_link_with_an_order_id_is_not_an_order():
    site.set_marketplace("amazon.de")
    assert site.details_link_order_id("/dp/B000000009?ref=x&orderID=%s" % DECOY) is None
    assert site.details_link_order_id("/gp/your-account/order-details?orderID=%s" % A) == A


def test_two_orders_in_one_block_are_each_kept_without_the_blocks_date(page):
    """One block naming two orders cannot say which date is whose, so each is
    kept with what names it alone and neither takes the block's date."""
    site.set_marketplace("amazon.de")
    header = menu(A) + menu(B)
    found = read(page, orders_page([order(A, "3. März 2026", "9,99 €", header=header)]))
    assert [o for o, _ in found] == [A, B]
    assert all("März" not in t and "9,99" not in t for _, t in found)


def test_one_order_named_twice_in_its_block_is_one_order(page):
    site.set_marketplace("amazon.de")
    header = details(A) + menu(A) + menu(A)
    found = read(page, orders_page([order(A, "3. März 2026", "9,99 €", header=header)], 1))
    assert [o for o, _ in found] == [A]
    assert "3. März 2026" in found[0][1]


def test_a_menu_beside_the_period_menu_does_not_take_the_page_as_its_block(page):
    """A single order's block stops below anything holding the page's own
    controls, so the period menu's words are never read as its date."""
    site.set_marketplace("amazon.de")
    found = read(page, orders_page([order(A, "3. März 2026", "9,99 €")], 1))
    assert [o for o, _ in found] == [A]
    assert "aufgegeben in" not in found[0][1] and "Konto" not in found[0][1]


def test_a_list_drawn_with_cards_is_read_exactly_as_before(page):
    """The amazon.com layout, its order number in its text. The cards decide,
    a trigger inside a card adds nothing."""
    card = ("<div class='order-card js-order-card'><div>Order placed</div>"
            "<div>January 2, 2026</div><div>Total</div><div>$23.41</div>"
            "<div>Order # %s</div>%s</div>")
    html = orders_page([card % (A, menu(A)), card % (B, menu(DECOY))])
    found = read(page, html)
    assert [o for o, _ in found] == [A, B]
    assert found[0][1].startswith("Order placed")


# -- every store --------------------------------------------------------------------

STORES = sorted(site.MARKETPLACES)


def test_every_store_is_checked():
    assert len(STORES) == len(site.MARKETPLACES) >= 14


@pytest.mark.parametrize("store", STORES)
def test_every_store_reads_only_the_invoice_menu_of_its_own_host(page, store):
    site.set_marketplace(store)
    others = [s for s in STORES if s != store]
    header = (ship_to(popover("/your-orders/address/popover?orderId=%s" % ADDR))
              + menu(url="https://www.%s/your-orders/invoice/popover?orderId=%s" % (store, A)))
    blocks = [order(A, "January 2, 2026", "23.41", header=header)]
    for i, other in enumerate(others):
        oid = "302-0000000-%07d" % (200 + i)
        blocks.append(order(oid, "January 3, 2026", "1.00", header=menu(
            url="https://www.%s/your-orders/invoice/popover?orderId=%s" % (other, oid))))
    found = read(page, orders_page(blocks))
    assert [o for o, _ in found] == [A]
    assert "January 2, 2026" in found[0][1]


@pytest.mark.parametrize("store", STORES)
def test_every_store_reads_an_order_drawn_without_a_card_as_one_drawn_with_one(page, store):
    """The date and total read from the block are those the card path reads
    from the same words inside a card."""
    site.set_marketplace(store)
    money = ("%s23.41" % site.CURRENCY if site.CURRENCY in ("$", "£")
             else "23,41 %s" % site.CURRENCY)
    found = read(page, orders_page([order(A, "January 2, 2026", money)], 1))
    assert [o for o, _ in found] == [A]
    words = found[0][1]
    as_block = site.card_to_purchase(site.RawCard(href="", text=words, order_id=A), "Online")
    page.set_content("<div class='order-card'>%s Order # %s</div>"
                     % (words.replace("\n", "<br>"), A))
    (old,) = site.collect_cards(page)
    as_card = site.card_to_purchase(old, "Online")
    assert as_block.purchase_date == as_card.purchase_date == "2026-01-02"
    assert as_block.total == as_card.total and as_block.total


# -- Unicode hyphens ----------------------------------------------------------------

DASHES = "‐‑‒–—―−﹣－"


@pytest.mark.parametrize("dash", list(DASHES))
def test_an_order_number_printed_with_a_unicode_hyphen_is_read_in_ascii(dash):
    assert site.order_ids_in("Bestellnr. " + A.replace("-", dash)) == [A]
    assert site.order_ids_in(DIG.replace("-", dash)) == [DIG]


def test_mixed_hyphens_are_read():
    assert site.order_ids_in("302-0000000–0000101") == [A]


@pytest.mark.parametrize("text", [
    "302­0000000­0000101",          # soft hyphen
    "302⁃0000000⁃0000101",          # hyphen bullet
    "302﹘0000000﹘0000101",          # small em dash
    "302⸺0000000⸺0000101",          # two-em dash
    "302ー0000000ー0000101",          # katakana long mark
    "302 – 0000000 – 0000101",
    "302–0000000",
    "302-00000000-0000101",
    "2025–2026",
    "３０２-０００００００-００００１０１",
])
def test_lookalikes_are_not_order_numbers(text):
    assert site.order_ids_in(text) == []


def test_the_order_number_argument_is_kept_in_ascii():
    import amazon_receipts as app_mod
    args = app_mod.build_parser().parse_args(["--order-number", A.replace("-", "‑")])
    assert args.order_number != A   # parsed as typed, main() makes it ASCII
    assert site.order_id_of(args.order_number) == A


def test_the_text_fallback_takes_each_orders_words_from_where_it_is_printed(page):
    site.set_marketplace("amazon.de")
    filler = "<p>" + ("x " * 500) + "</p>"
    html = ("<body><div>Bestellung aufgegeben 3. März 2026 Summe 1,00 € Nr. %s</div>%s"
            "<div>Bestellung aufgegeben 1. Februar 2026 Summe 2,00 € Nr. %s</div></body>"
            % (A.replace("-", "–"), filler, B.replace("-", "–")))
    found = read(page, html)
    assert [o for o, _ in found] == [A, B]
    assert "3. März 2026" in found[0][1]
    assert "1. Februar 2026" in found[1][1] and "3. März 2026" not in found[1][1]


def test_an_order_page_with_a_unicode_hyphen_is_not_a_robot_check(page):
    page.set_content("<body><p>Robot check vacuum, invented product</p>"
                     "<p>Bestellnr. %s</p></body>" % A.replace("-", "‑"))
    assert site.detect_security_challenge(page) is None


def test_the_summary_check_reads_order_numbers_with_unicode_hyphens(page):
    site.set_marketplace("amazon.com")

    class AtAddress:
        """The page's text from the browser, its address as Amazon's."""
        def __init__(self, real, url):
            self._real, self.url = real, url

        def __getattr__(self, name):
            return getattr(self._real, name)

    url = site.print_invoice_url(A)
    page.set_content("<body><h1>Order %s</h1><p>Grand Total: $1.00</p></body>"
                     % A.replace("-", "‑"))
    assert site.not_this_purchase(AtAddress(page, url), A) == ""
    page.set_content("<body><h1>Order %s</h1><p>Order %s</p><p>Grand Total: $1.00</p></body>"
                     % (A, B.replace("-", "–")))
    assert site.not_this_purchase(AtAddress(page, url), A) != ""


class _Moving:
    """A page whose first look finds two invoice menus in one list and whose
    second finds the place of one of them holding something else."""

    def __init__(self, second):
        self.second = second
        self.looks = 0

    def evaluate(self, js, arg=None):
        self.looks += 1
        if self.looks == 1:
            return [{"kind": "menu", "chain": [5, 4], "alike": [True, False], "top": 1,
                     "raw": popover("/your-orders/invoice/popover?orderId=%s" % A)},
                    {"kind": "menu", "chain": [9, 8], "alike": [True, False], "top": 1,
                     "raw": popover("/your-orders/invoice/popover?orderId=%s" % B)}]
        return self.second


def test_a_page_that_moved_between_the_two_looks_gives_no_order():
    site.set_marketplace("amazon.de")
    a, b = ["Rechnung", "3. März 2026"], ["Rechnung", "1. März 2026"]
    assert site.invoice_menu_orders(_Moving([a, b])) == [
        (A, "3. März 2026"), (B, "1. März 2026")]
    assert site.invoice_menu_orders(_Moving([a, None])) == []
    assert site.invoice_menu_orders(_Moving([a, ["Rechnung", None]])) == []
    assert site.invoice_menu_orders(_Moving([a])) == []


BANNER = ("<div class='banner'><div>Lieferung am 9. Mai 2026</div><div>Summe 77,77 €</div>%s</div>")


def test_a_banner_outside_the_list_names_no_order_and_takes_no_date(page):
    """An order named in a block outside the list of orders, a banner about a
    delivery, adds no order and lends no order its words."""
    site.set_marketplace("amazon.de")
    for named in (menu(DECOY), details(DECOY), menu(A), details(A)):
        found = read(page, orders_page([order(A, "3. März 2026", "23,41 €"),
                                        order(B, "1. Februar 2026", "58,20 €")],
                                       before=BANNER % named))
        assert [o for o, _ in found] == [A, B], named
        assert "3. März 2026" in found[0][1] and "Mai" not in found[0][1], named


def test_details_links_are_not_read_where_invoice_menus_name_the_orders(page):
    site.set_marketplace("amazon.de")
    found = read(page, orders_page([order(A, "3. März 2026", "23,41 €")], 1,
                                   after=BANNER % details(DECOY)))
    assert [o for o, _ in found] == [A]


def test_a_year_whose_count_is_nought_reads_nothing_from_a_menu(page):
    """Amazon's own count says the year holds no orders. Whatever names an
    order on that page is not in the list, so the year stays empty and the
    walk back through the years still ends there."""
    site.set_marketplace("amazon.de")
    html = orders_page([], count=0, before=BANNER % (menu(DECOY) + details(DECOY)))
    page.set_content(html)
    assert site.orders_listed(page, 0)
    assert site.collect_cards(page) == []


def test_an_unnamed_order_beside_the_only_named_one_lends_it_nothing(page):
    """A digital order whose link the reader does not take, listed first,
    and a retail order named by its menu. The retail order keeps its own
    date and total, and the digital one is still read from the text where
    its number is printed."""
    site.set_marketplace("amazon.de")
    digital = order(DIG, "7. April 2026", "4,99 €",
                    header="<a href='/gp/digital/your-account/order-summary.html?orderID=%s'>"
                           "Bestellnr. %s</a>" % (DIG, DIG))
    found = read(page, orders_page([digital, order(A, "3. März 2026", "23,41 €")]))
    assert [o for o, _ in found] == [A, DIG]
    a = site.card_to_purchase(site.RawCard(href="", text=found[0][1], order_id=A), "Online")
    assert (a.purchase_date, a.total) == ("2026-03-03", "€23.41")


def test_an_order_number_in_the_text_is_still_read_beside_the_menus(page):
    """On amazon.com with no card class, the text names a digital order and
    the menu names a retail one. Both are read, as the text alone was."""
    site.set_marketplace("amazon.com")
    digital = ("<div class='x1' data-a='1' data-b='2' data-c='3' data-d='4'><div>Order placed</div>"
               "<div>April 7, 2026</div><div>Total</div><div>$4.99</div><div>Order # %s</div></div>"
               % DIG)
    found = read(page, orders_page([digital, order(A, "March 3, 2026", "$23.41")]))
    assert sorted(o for o, _ in found) == sorted([A, DIG])


def test_an_order_named_only_by_its_details_link_is_read_in_the_list(page):
    """A canceled order has no invoice menu, only its order-details link. It
    sits in the list beside orders that have one, so it is read."""
    site.set_marketplace("amazon.de")
    canceled = order(B, "1. Februar 2026", "0,00 €", header=ship_to() + details(B))
    found = read(page, orders_page([order(A, "3. März 2026", "23,41 €"), canceled,
                                    order(DIG, "1. Januar 2026", "4,99 €")]))
    assert [o for o, _ in found] == [A, B, DIG]
    assert "1. Februar 2026" in found[1][1]


def test_a_buy_again_form_in_each_order_does_not_let_a_banner_in(page):
    """Each order's item row holds a Buy it again form of its own. The
    orders are still one list, so a banner's menu names no order and each
    order keeps its own date."""
    site.set_marketplace("amazon.de")
    form = "<form action='/gp/buyagain'><input type='submit' value='Erneut kaufen'></form>"
    # Each order's block with the form put in just before it closes.
    blocks = [order(A, "3. März 2026", "23,41 €")[:-len("</div>")] + form + "</div>",
              order(B, "1. Februar 2026", "58,20 €")[:-len("</div>")] + form + "</div>"]
    found = read(page, orders_page(blocks, before=BANNER % menu(DECOY)))
    assert [o for o, _ in found] == [A, B]
    dates = [site.parse_date(t) for _, t in found]
    assert dates == ["2026-03-03", "2026-02-01"]


def test_a_page_that_showed_fewer_orders_than_its_count_says_so(page):
    """Three orders counted on the page and two named. The third is not made
    up, and the page says it showed fewer than its count."""
    site.set_marketplace("amazon.de")
    unnamed = order(DECOY, "2. Januar 2026", "1,00 €", header=ship_to())
    html = orders_page([order(A, "3. März 2026", "1,00 €"), unnamed,
                        order(B, "1. März 2026", "2,00 €")], count=3)
    assert [o for o, _ in read(page, html)] == [A, B]
    assert site.fewer_than_counted(page, 0, 2)
    assert not site.fewer_than_counted(page, 0, 3)
    # The last page of a year counts only what is left after the pages before.
    page.set_content(orders_page([order(A, "3. März 2026", "1,00 €")], count=11))
    assert not site.fewer_than_counted(page, 10, 1)
    assert site.fewer_than_counted(page, 0, 1)


def test_a_page_that_prints_its_order_numbers_is_never_called_short(page):
    """A page whose text prints the numbers reads as it always did."""
    site.set_marketplace("amazon.de")
    page.set_content(orders_page(["<div>Bestellnr. %s</div>" % A], count=5))
    assert not site.fewer_than_counted(page, 0, 1)
    page.set_content("<div class='order-card'>x</div>" + orders_page([], count=5))
    assert not site.fewer_than_counted(page, 0, 1)
