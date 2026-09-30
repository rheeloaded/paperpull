"""A revealed document whose description names money (#37).

RECORDED, from the member's Run All of 2026-09-29. One Payment Receipt,
dated 2025-03-11, had no file address in the list, so the app pressed its
row's View Documents, saw "Payment Receipt - ..." appear, and refused to
press it. The guard read the whole name, the description included, and the
list's own title for such a receipt is "Payment Receipt - Billing/Payments",
where "Payments" is a word the guard refuses on a control.

The type before the dash still faces the whole guard and has to be the type
the list gives. The description faces the words that act, and the whole
guard as well, less the few nouns a document is known to be named by, and
only in their own shape. A first repair asked the description about verbs
alone, and a review before release found fifty ways of acting it let
through. A second found nouns let off wherever they sat carrying a verb in.
All are tested here.

Every date, name and vehicle here is invented.
"""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site
import test_row_documents_in_a_browser as shaped

# What the tester's documents are named, or may be. These are documents.
DOCUMENTS = [
    "Payment Receipt - Billing/Payments",
    "Payment Receipt - Payments",
    "Payment Receipt - Autopay",
    "Payment Receipt - Card ending 4321",
    "Payment Receipt - Wire",
    "Payment Receipt - Payment Receipt",
    "Renewal Notice - 2017 Invented Limited",
    "Renewal Notice - 2021 Invented Coupe Limited Edition",
    "Renewal Notice - 2019 Invented F-150 Limited",
    "Renewal Notice - 2020 Invented Pilot Limited AWD",
    "Renewal Notice - 2022 Invented Sedan Limited Hybrid",
    "Payment Receipt - Debit card ending in 4321",
    "Billing Statement - Bill for 2025",
    "Renewal Notice - Auto",
    "Declarations Page - Homeowners",
]


@pytest.mark.parametrize("name", DOCUMENTS)
def test_a_money_word_in_a_description_names_the_document(name):
    assert site.is_revealed_document(name), name


# "<a type the list gives> - <a description that acts>". Every one acts, and
# every one was refused before this round. The review found the first repair
# pressing most of them.
ACTING = [
    "Payment Receipt - Pay Now",
    "Payment Receipt - Pay your bill",
    "Payment Receipt - Make a payment",
    "Payment Receipt - Set up autopay",
    "Payment Receipt - Enroll in paperless",
    "Payment Receipt - Stop payment",
    "Payment Receipt - Turn off autopay",
    "Payment Receipt - Save changes",
    "Payment Receipt - Switch to autopay",
    "Payment Receipt - Start autopay",
    "Payment Receipt - Autopay: turn it on",
    "Payment Receipt - Opt-in to autopay",
    "Payment Receipt - Quick pay",
    "Payment Receipt - Click to pay",
    "Payment Receipt - One-time payment",
    "Payment Receipt - Complete payment",
    "Payment Receipt - Continue to payment",
    "Payment Receipt - Card ending 4321, pay",
    "Payment Receipt - Use this card",
    "Payment Receipt - Save card for next time",
    "Payment Receipt - Go paperless",
    "Payment Receipt - Switch to paperless",
    "Renewal Notice - Opt out of paperless",
    "Renewal Notice - Opt-out of paperless",
    "Renewal Notice - Cancel policy",
    "Renewal Notice - Change coverage",
    "Renewal Notice - Renew now",
    "Renewal Notice - 2017 Invented Roadster, pay now",
    "Renewal Notice - File claim",
    "Renewal Notice - Start a claim",
    "Declarations Page - File a claim",
    "Declarations Page - New claim",
    "Declarations Page - Upgrade coverage",
    "Declarations Page - Increase coverage",
    "Declarations Page - Raise liability limits",
    "Declarations Page - Rental car coverage",
    "Renewal Notice - 2017 Invented Camry - Remove vehicle",
    "Renewal Notice - 2017 Invented Camry: Cancel coverage",
    "Renewal Notice - Policy 123 - Cancel",
    "Renewal Notice - *Cancel policy",
    "Renewal Notice - [Remove vehicle]",
    "Declarations Page - New address",
    "ID Card - Order replacement",
    "ID Card - Get roadside help",
    "Renewal Notice - Get a quote",
    "Auto ID Card - Replace",
    "Pay Now - Payment Receipt",
    "Payments - Billing",
    "Make a payment - Auto",
    # A known noun with a verb glued on, found by a second review. A noun is
    # let off only as the whole description, and Limited only in a vehicle's
    # name, since Limited Tort is a coverage election.
    "Payment Receipt - Use this card ending 4321",
    "Payment Receipt - Save this card ending 4321",
    "Payment Receipt - Charge card ending 4321",
    "Payment Receipt - Switch to card ending 4321",
    "Payment Receipt - Make default card ending 4321",
    "Payment Receipt - Continue to Billing/Payments",
    "Payment Receipt - Complete Billing/Payments",
    "Renewal Notice - Switch to Limited Tort",
    "Renewal Notice - Choose Limited Tort",
    "Renewal Notice - 2017 Invented Camry Limited, switch to Limited Tort",
    # A vehicle's shape carrying an election, found by a third review.
    "Renewal Notice - 2017 Invented Camry - Switch to Limited Tort",
    "Renewal Notice - 2017 Invented Camry Limited - Switch to Limited Tort",
    "Renewal Notice - 2017 Invented Camry / Choose Limited Tort",
    "Renewal Notice - 2025 Switch to Limited Tort",
]


@pytest.mark.parametrize("name", ACTING)
def test_a_description_that_acts_is_refused(name):
    assert not site.is_revealed_document(name), name


@pytest.mark.parametrize("aria", ["Go - Switch to autopay", "Receipt - payment setup",
                                  "Payment Receipt - File claim", "Make a payment",
                                  "Payment Receipt - Use this card ending 4321",
                                  "Payment Receipt - Continue to Billing/Payments"])
def test_a_screen_reader_name_that_acts_is_refused(aria):
    assert site._guard_refuses_name(aria), aria


def test_a_screen_reader_name_is_read_by_the_same_rule():
    assert not site._guard_refuses_name("Payment Receipt - Billing/Payments")
    assert site._guard_refuses_name("Payment Receipt - Pay Now")
    assert not site._guard_refuses_name("Open the payment receipt")
    want = site._type_key("Payment Receipt - Billing/Payments")
    assert site._guard_refuses_name("Make a - payment", want), "its type is nobody's"


# -- the trace carries fixed words only ------------------------------------------

def test_the_trace_gives_the_guards_own_word_and_nothing_of_the_page():
    assert site._label_mask("Payment Receipt - Billing/Payments") == "Payment Receipt - ..."
    assert site._label_mask("Payment Receipt - Pay Now") == \
        "Payment Receipt - ..., refused by the guard for pay"
    assert site._label_mask("Renewal Notice - Cancel Jane Q Invented policy") == \
        "Renewal Notice - ..., refused by the guard for cancel"
    assert site._label_mask("Payment Receipt - Go paperless") == \
        "Payment Receipt - ..., refused by the guard for paperless"
    assert site._refusing_word("Renewal Notice - 2017 Invented Roadster, pay now") == "pay now"
    assert site._refusing_word("not shaped like a document") == "another word"


def _allowed_masks():
    types = set(site._KNOWN_TYPES.values()) | {"another type"}
    words = set(site._GUARD_WORDS) | {"another word"}
    out = {"%s - ..." % t for t in types}
    out |= {"%s - ..., refused by the guard for %s" % (t, w) for t in types for w in words}
    return out


PERSONAL = ["Jane", "Q", "Invented", "4321", "Maple", "Camry", "Roadster", "Grand", "Tourer",
            "Kelvin", "ſend", "Pay​now", "PAY", "pаy", "LOCK"]


def test_a_refused_documents_mask_holds_fixed_words_only():
    """download-attempt.json is posted publicly. Whatever a revealed document
    says, its mask is one of a list made here from fixed words."""
    rng = random.Random(930)
    allowed = _allowed_masks()
    guard_words = sorted(site._GUARD_WORDS)
    types = list(site._KNOWN_TYPES.values()) + ["Quilted Rider", "Payment", "Autopay Receipt"]
    for _ in range(4000):
        desc = " ".join(rng.choice(guard_words + PERSONAL) for _ in range(rng.randint(1, 6)))
        name = "%s - %s" % (rng.choice(types), desc)
        mask = site._label_mask(name)
        assert mask in allowed or mask == "another control", (name, mask)


# -- in a browser, the app's own fake Document Center ----------------------------

def _press(rows, when, title, tmp_path, center=None):
    html = center or (lambda: shaped.PAGE % shaped._row_html(rows=rows))
    driver, browser, pg = shaped._drive(html)
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        ok = site.download_bill(pg, None, when, out, title=title, trace=trace)
        return ok, out, trace
    finally:
        browser.close()
        driver.stop()


def _clicked(trace):
    return [t["control"] for t in trace if t.get("note") == "clicked"]


def test_his_payment_receipt_is_pressed_and_saved(tmp_path):
    rows = [("03/11/2025", "Payment Receipt - Billing/Payments")]
    ok, out, trace = _press(rows, "2025-03-11", "Payment Receipt - Billing/Payments", tmp_path)
    assert ok, trace
    assert out.read_bytes().startswith(b"%PDF-")
    assert _clicked(trace) == ["View Documents0", "Payment Receipt - ..."], _clicked(trace)
    assert "Billing/Payments" not in json.dumps(trace)


def test_a_vehicle_named_limited_is_saved(tmp_path):
    rows = [("03/14/2026", "Renewal Notice - 2017 Invented Limited")]
    ok, out, trace = _press(rows, "2026-03-14", "Renewal Notice - Auto", tmp_path)
    assert ok and out.read_bytes().startswith(b"%PDF-"), trace
    assert "Limited" not in json.dumps(trace) and "Invented" not in json.dumps(trace)


@pytest.mark.parametrize("revealed,title", [
    ("Payment Receipt - Pay Now", "Payment Receipt - Billing/Payments"),
    ("Payment Receipt - Switch to autopay", "Payment Receipt - Billing/Payments"),
    ("Renewal Notice - 2017 Invented Camry - Remove vehicle", "Renewal Notice - Auto"),
    ("Payment Receipt - Use this card ending 4321", "Payment Receipt - Billing/Payments"),
    ("Payment Receipt - Continue to Billing/Payments", "Payment Receipt - Billing/Payments"),
])
def test_a_row_that_reveals_a_control_that_acts_has_it_left_alone(revealed, title, tmp_path):
    """The one control of the wanted type in the opened row acts. It is
    never pressed, and the trace says the guard refused it."""
    ok, out, trace = _press([("03/11/2025", revealed)], "2025-03-11", title, tmp_path)
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    assert not ok and not out.exists()
    [row] = [t for t in trace if t.get("note") == "the row's documents"]
    assert all(", refused by the guard for " in a for a in row["appeared"]
               if not a.startswith("View Documents")), row


def _row_with(doc_html, when="03/11/2025", n=0):
    return ("<div role='row'><span class='when'>%s</span> <span>Sent by mail. Available online "
            "until %s</span><button class='view' aria-expanded='false' onclick='toggle(this)'>"
            "View Documents%d</button><div class='docs' hidden>%s</div></div>"
            % (when, when[:6] + "2028", n, doc_html))


def test_a_screen_reader_name_from_labelledby_is_asked_too(tmp_path):
    """The name a screen reader gives the control comes from aria-labelledby
    here, and it says the control pays. The guard read aria-label alone, so
    the words of the element it points at were never asked (review)."""
    doc = ("<span id='pay' hidden>Make a payment now</span>"
           "<a href='#' aria-labelledby='pay' onclick=\"openDoc('x');return false\">"
           "Payment Receipt - Payment Receipt</a>")
    ok, out, trace = _press(None, "2025-03-11", "Payment Receipt - Billing/Payments", tmp_path,
                            center=lambda: shaped.PAGE % _row_with(doc))
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    assert not ok and not out.exists()


def test_a_title_that_pays_keeps_the_press_away_too(tmp_path):
    doc = ("<a href='#' title='Pay now' onclick=\"openDoc('x');return false\">"
           "Payment Receipt - Payment Receipt</a>")
    ok, out, trace = _press(None, "2025-03-11", "Payment Receipt - Billing/Payments", tmp_path,
                            center=lambda: shaped.PAGE % _row_with(doc))
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    assert not ok and not out.exists()


@pytest.mark.parametrize("aria", ["Make a - payment", "Stop - Payment",
                                  "Payment Receipt - Card ending 4321, update payment method"])
def test_a_screen_reader_label_that_acts_keeps_the_press_away(aria, tmp_path):
    """The control's words are the receipt's, its screen-reader label says it
    acts. 0.41.0 asked the whole guard about the label and refused all three,
    and so does this round."""
    doc = ("<a href='#' aria-label='%s' onclick=\"openDoc('x');return false\">"
           "Payment Receipt - Payment Receipt</a>" % aria)
    ok, out, trace = _press(None, "2025-03-11", "Payment Receipt - Billing/Payments", tmp_path,
                            center=lambda: shaped.PAGE % _row_with(doc))
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    assert not ok and not out.exists()
