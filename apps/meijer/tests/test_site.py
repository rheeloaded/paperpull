"""The Meijer site layer, against the shape an orders page is likely to
have. Every row here is made up. Nothing in them is a real order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

ROW_WITH_LINKS = site.RawCard(
    text="Pickup\nSep 13, 2026\nOrder #12345678\n14 items\n$86.42\nView order details\nView receipt",
    links=[
        {"text": "View order details", "href": "/shopping/orders/12345678.html", "label": "", "download": False},
        {"text": "View receipt", "href": "/shopping/orders/12345678/receipt.pdf", "label": "", "download": True},
        {"text": "Reorder", "href": "/shopping/reorder/12345678", "label": "", "download": False},
    ])
ROW_WITHOUT_LINKS = site.RawCard(text="In-store\n2026-08-13\nStore 123\n$23.10", links=[])
ROW_NO_AMOUNT = site.RawCard(text="Date\nOrder\nTotal", links=[])


def test_an_order_row_becomes_a_purchase_with_the_pdf_link_first_and_reorder_never():
    p = site.card_to_purchase(ROW_WITH_LINKS)
    assert p.purchase_type == ONLINE
    assert p.purchase_date == "2026-09-13"
    assert p.total == "$86.42"
    assert p.order_number == "12345678"
    assert p.receipt_url.endswith("/receipt.pdf"), "the download link comes before the details link"
    links = site.receipt_links(ROW_WITH_LINKS)
    assert [ln["text"] for ln in links] == ["View receipt", "View order details"]
    assert all(ln["href"].startswith("https://www.meijer.com/") for ln in links)


def test_a_row_without_links_still_gets_a_stable_key():
    p = site.card_to_purchase(ROW_WITHOUT_LINKS)
    assert p.purchase_date == "2026-08-13" and p.total == "$23.10"
    assert p.order_number.startswith("p") and len(p.order_number) == 13
    assert p.order_number == site.card_to_purchase(ROW_WITHOUT_LINKS).order_number
    assert p.receipt_url == ""


def test_a_header_row_without_an_amount_is_not_an_order():
    assert site.card_to_purchase(ROW_NO_AMOUNT) is None


def test_dates_in_the_forms_the_site_is_likely_to_print():
    assert site.parse_date("Sep 13, 2026") == "2026-09-13"
    assert site.parse_date("13 Sep 2026") == "2026-09-13"
    assert site.parse_date("2026-09-13T00:00:00Z") == "2026-09-13"
    assert site.parse_date("09/13/2026") == "2026-09-13"
    assert site.parse_date("no date here") is None


def test_nothing_that_shops_refunds_clips_or_refills_is_safe():
    for t in ("Add to cart", "Add all to cart", "Reorder", "Buy again", "Start your order", "Cancel order",
              "Request a refund", "Clip coupon", "Redeem rewards", "Refill prescription", "Pay now",
              "Edit order", "Rate this order", "Contact us", "Sign out", "Update address", "Add a tip"):
        assert not site.is_safe_control(t), t
    for t in ("View receipt", "View order details", "Order details", "Order history", "My orders", "Load more", "Next"):
        assert site.is_safe_control(t), t


def test_only_meijer_hosts_and_every_candidate_passes():
    assert site.is_safe_url("https://www.meijer.com/shopping/orders.html")
    assert site.is_safe_url("https://accounts.meijer.com/x")
    assert not site.is_safe_url("https://meijer.com.evil.test/x")
    assert not site.is_safe_url("http://www.meijer.com/")
    assert not site.is_safe_url("https://user@meijer.com/")
    assert all(site.is_safe_url(u) for u in site.ORDER_CANDIDATES)


class _Page:
    url = "https://www.meijer.com/shopping/orders.html"

    def __init__(self, text, has_main=True):
        self._t = text
        self._m = has_main

    def title(self):
        return "Orders"

    def locator(self, sel):
        page = self

        class _L:
            def count(self_):
                return 1 if (page._m or sel == "body") else 0

            @property
            def first(self_):
                return self_

            def inner_text(self_, timeout=0):
                return page._t
        return _L()


def test_the_empty_page_and_a_receipt_page_are_recognized():
    assert site.history_state(_Page("Orders\nYou don't have any orders yet.")) == "empty"
    assert site.history_state(_Page("Orders\nNo orders to show")) == "empty"
    assert site.history_state(_Page("Orders\nPickup Sep 13, 2026 $86.42")) == ""
    assert site.receipt_is_present(_Page("Receipt\nMilk $3.29\nBananas $1.18\nSubtotal $4.47\nTotal $4.47"))
    assert not site.receipt_is_present(_Page("Account\nSettings"))


def test_receipt_lines_give_items_without_the_totals():
    p = site.extract_details(_Page("Receipt\nMeijer 2% Milk $3.29\nBananas $1.18\nSubtotal $4.47\nTax $0.00\nTotal $4.47"),
                             Purchase(purchase_type=ONLINE, order_number="x"))
    assert [i.name for i in p.items] == ["Meijer 2% Milk", "Bananas"]


def test_the_diagnose_file_masks_numbers_emails_and_handles_and_keeps_json_shapes():
    assert site.mask_text("Store 123, card 4242, pat@example.com, Sep 13, 2026") == "Store ###, card ####, <email>, Sep ##, ####"
    assert site.mask_href("/shopping/orders/12345678/receipt.pdf?x=1") == "/shopping/orders/<id>/receipt.pdf?..."
    assert site.json_shape({"orders": [{"id": 1, "total": 2.5, "items": [{"upc": "1"}]}], "page": 1}) == \
        {"orders": ["list of 1", {"id": "int", "total": "float", "items": ["list of 1", {"upc": "str"}]}], "page": "int"}


# -- round two, the two tabs the tester's page has (#42) ---------------------

def test_an_in_store_row_is_filed_as_in_store():
    """His page has an Online Orders tab, which is empty, and an In-Store
    Receipts tab holding everything. A row that says In-Store is one."""
    row = site.RawCard(text="In-Store: 09/19/2026\n1600 N. Port Washington Road\n$31.23 \u2022 15 items", links=[])
    p = site.card_to_purchase(row)
    assert p.purchase_type == IN_STORE
    assert p.purchase_date == "2026-09-19" and p.total == "$31.23"
    online = site.card_to_purchase(site.RawCard(text="Pickup\nSep 13, 2026\nOrder #123\n$86.42", links=[]))
    assert online.purchase_type == ONLINE


def test_both_tabs_are_read_and_named_as_the_page_names_them():
    for t in ("In-Store Receipts", "In-store receipts", "Instore Receipts"):
        assert site.TAB_IN_STORE_RE.match(t), t
    for t in ("Online Orders", "online order"):
        assert site.TAB_ONLINE_RE.match(t), t
    assert not site.TAB_IN_STORE_RE.match("Add Paper Receipt")
    import inspect
    src = inspect.getsource(site.collect_both_tabs)
    assert "TAB_IN_STORE_RE" in src and "TAB_ONLINE_RE" in src


def test_a_pdf_icon_with_no_text_is_still_the_receipt_control():
    js = site._ROW_CONTROLS_JS
    assert "aria-label" in js and "cursor" in js and "pdf|receipt|download" in js
    assert "out.sort" in js, "the PDF icon is tried before anything else in the row"


# -- round three, from the tester's recording (#42) ---------------------------

def test_the_receipt_control_is_a_link_that_says_what_it_is():
    """His recording pressed a link reading "view receipt pdf", twice, and
    each press opened a tab. Round two was built for a PDF icon carrying
    no text at all."""
    for name in ("view receipt pdf", "View Receipt PDF", "View receipt"):
        assert site.RECEIPT_LINK_RE.match(name), name
    for name in ("Add Paper Receipt", "Reorder", "View order details"):
        assert not site.RECEIPT_LINK_RE.match(name), name


def test_a_controls_own_words_decide_whether_it_looks_like_the_receipt():
    js = site._ROW_CONTROLS_JS
    assert "c.innerText" in js.split("looksPdf")[1][:400], \
        "the control's own text is part of the test, not just its label and class"


def test_the_empty_message_is_only_believed_after_both_tabs_were_read():
    """The online tab is the one the page opens on, and it says "You
    haven't placed any orders yet" to somebody whose receipts are all
    behind the other tab. He was told his account has no orders, twice."""
    import inspect
    from pathlib import Path
    src = (Path(site.__file__).parent / "meijer_receipts.py").read_text(encoding="utf-8")
    block = src.split("for page_no in range(1, 60):")[1][:900]
    collect_at = block.index("collect_both_tabs")
    empty_at = block.index('history_state(page) == "empty"')
    assert collect_at < empty_at, "the tabs are read before the page is believed"
    assert "not found and" in block, "and the message needs both tabs to be empty"
    assert inspect.getsource(site.collect_both_tabs)
