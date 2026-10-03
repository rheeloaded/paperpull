"""A revealed document whose description is State Farm's own (#37).

RECORDED, from the member's Run All on 0.41.1 of 2026-10-01. The Payment
Receipt of 2025-03-11 has no file address in the list, so its row's View
Documents was pressed and "Payment Receipt - ..." appeared, and the guard
refused it again, for "payment". 0.41.1 let a money noun through only as
the whole description, Billing/Payments, Payments, a card ending in its last
four, and his description says payment some other way. What it says is not
known, since the trace never carries the page's words.

The list the page fetches names every document, its type, its category and
its description, and the page names a revealed document "<type> -
<description>" (the fake Document Center here draws its rows the same way).
A description that is word for word what the list calls this document, read
from the list answer of the very load its row is found on, is not asked
about nouns now. It still faces the words that act and the words that sign
in, the type still faces the whole guard, and its names for a screen reader
are asked too. A description the list does not give is read as before.

When one is refused, the trace now tells its words from a fixed list of
ordinary ones, so a refusal says what shape the description has without
anything of the page leaving.

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


def _plain(text):
    """As the app compares words with the list's, case and spacing aside."""
    return " ".join(text.split()).casefold()


# A receipt's description that says payment in a shape the nouns refuse.
SAID = "Payment received, thank you for your payment"
OWN = (_plain(SAID), _plain("Billing/Payments"))


# -- what the list calls the document ---------------------------------------------

def _answer(*entries):
    return {"data": {"attributes": list(entries)}}


def _entry(doc_id, description, category="Billing/Payments", url=""):
    return {"documentId": doc_id, "description": description, "category": category,
            "type": "Payment Receipt", "filePathUrl": url, "creationDate": "03/11/2025"}


def test_the_lists_words_are_read_by_the_documents_id():
    answers = [_answer(_entry("invented-1", "Payment Receipt"), _entry("invented-2", SAID))]
    assert site._own_words(answers, "invented-2") == tuple(sorted(OWN))


def test_the_lists_words_are_read_by_the_file_address_when_that_is_what_discovery_kept():
    address = "/DocumentCenterProxyV1/document/invented/file"
    answers = [_answer(_entry("invented-2", SAID, url=address))]
    assert site._own_words(answers, address) == tuple(sorted(OWN))


@pytest.mark.parametrize("answers,hint", [
    ([_answer(_entry("invented-2", SAID))], ""),
    ([_answer(_entry("invented-2", SAID))], "invented-9"),
    ([_answer(_entry("invented-2", SAID, url="/a/1"), _entry("invented-2", "Another", url="/a/2"))],
     "invented-2"),
    ([{"data": None}, "not an answer", {"data": {"attributes": "nothing"}}], "invented-2"),
    ([], "invented-2"),
])
def test_no_words_when_no_single_document_carries_the_hint(answers, hint):
    assert site._own_words(answers, hint) == ()


def test_two_documents_sharing_an_id_give_no_words():
    """His sixteen entries have no file address, so two that shared an id
    would pool their words, another's "Switch to autopay" with his receipt's
    (review)."""
    answers = [_answer(_entry("invented-2", SAID), _entry("invented-2", "Switch to autopay"))]
    assert site._own_words(answers, "invented-2") == ()


def test_a_file_address_with_no_slash_is_matched_as_it_was_kept():
    answers = [_answer(_entry("invented-2", SAID, url="invented-file-2"))]
    assert site._own_words(answers, "invented-file-2") == tuple(sorted(OWN))


def test_one_document_in_two_answers_is_still_one():
    answers = [_answer(_entry("invented-2", SAID)), _answer(_entry("invented-2", SAID))]
    assert site._own_words(answers, "invented-2") == tuple(sorted(OWN))


# -- the rule ------------------------------------------------------------------------

# Descriptions a money noun used to keep away from the press. With the list's
# own words they are pressed, without them they are refused as before.
SAID_BY_THE_LIST = [
    SAID,
    "Payment Confirmation",
    "One-time payment",
    "Online Payment - Card ending 4321",
    "SFPP Payment",
    "Billing & Payments",
]


@pytest.mark.parametrize("description", SAID_BY_THE_LIST)
def test_a_description_the_list_gives_names_the_document(description):
    name = "Payment Receipt - " + description
    assert not site.is_revealed_document(name), "refused without the list's words"
    assert site.is_revealed_document(name, (_plain(description),)), name
    assert site._label_mask(name, (_plain(description),)) == "Payment Receipt - ..."


def test_a_whole_name_the_list_gives_names_the_document_too():
    name = "Payment Receipt - " + SAID
    assert site.is_revealed_document(name, (_plain(name),))


@pytest.mark.parametrize("description", [
    "Pay now", "Make a payment", "Pay your bill", "Set up autopay", "Sign in to pay",
    "Log in", "Cancel policy", "Switch to autopay now, enroll",
    # The whole guard still reads the list's words, less the money words a
    # receipt is described by. Each of these passed the first build with the
    # list's words and is refused on main (review).
    "Switch to autopay", "Start autopay", "Go paperless", "Get a quote", "Upgrade coverage",
    "Coverage change", "Billing settings", "Payment settings", "Cancellation request"])
def test_a_description_that_acts_is_refused_even_when_the_list_gives_it(description):
    name = "Payment Receipt - " + description
    assert not site.is_revealed_document(name, (_plain(description),)), name


def test_a_ligature_does_not_carry_a_word_that_acts_past_the_rules():
    """"Confirm" written with the fi ligature compares equal to the list's
    "confirm", and the rules read the same compatibility form (review)."""
    name = "Payment Receipt - Conﬁrm payment"
    assert not site.is_revealed_document(name, (_plain("Confirm payment"),))
    assert not site.is_revealed_document(name, (_plain("Conﬁrm payment"),))


def test_the_lists_words_never_refuse_what_main_would_press():
    for name in ("Payment Receipt - Autopay", "Payment Receipt - Payment Receipt",
                 "Renewal Notice - 2019 Invented Sedan Limited"):
        description = name.split(" - ", 1)[1]
        assert site.is_revealed_document(name)
        assert site.is_revealed_document(name, (_plain(description),)), name


def test_the_type_still_faces_the_whole_guard():
    own = (_plain("Payment Receipt"),)
    assert not site.is_revealed_document("Pay Now - Payment Receipt", own)
    assert not site.is_revealed_document("Make a payment - Payment Receipt", own)


def test_a_description_close_to_the_lists_is_not_the_lists():
    own = (_plain(SAID),)
    assert not site.is_revealed_document("Payment Receipt - Payment received", own)
    assert not site.is_revealed_document("Payment Receipt - " + SAID + ", pay now", own)


def test_a_name_read_cut_short_matches_the_start_of_the_lists_words():
    """The page's controls are listed cut at sixty characters, and his
    receipt may be named past that. The start is enough while the name is
    cut, and the whole name read off the node is held to all of it."""
    name = "Payment Receipt - " + SAID
    cut = name[:site._CUT_AT]
    assert len(name) > site._CUT_AT
    assert site.is_revealed_document(cut, OWN, cut=True)
    assert not site.is_revealed_document(cut, OWN), "a whole name is held to all of it"
    assert site.is_revealed_document(name, OWN)
    assert not site.is_revealed_document("Payment Receipt - Payment received", OWN, cut=True),         "a name shorter than the cut was read whole"
    assert site._description_mask(cut, cut=True) == "payment received , thank you for your * ..."


def test_a_name_cut_on_a_space_still_counts_as_cut():
    """The core tidies a name and then cuts it at sixty, so a cut that falls
    on a space leaves a trailing space that tidying again takes off, and the
    name looked whole at fifty-nine (review)."""
    said = "Payment received, thank you for your kind payment"
    name = "Payment Receipt - " + said
    cut = name[:site._CUT_AT]
    assert cut.endswith(" ") and len(cut.strip()) == site._CUT_AT - 1
    own = (_plain(said),)
    assert site.is_revealed_document(cut, own, cut=True)
    assert site._label_mask(cut, own, cut=True) == "Payment Receipt - ..."
    assert not site._refused_document(cut, own, cut=True)


def test_a_screen_reader_name_that_acts_is_refused_with_the_lists_words():
    want = site._type_key("Payment Receipt - Billing/Payments")
    assert site._guard_refuses_name("Make a payment", want, OWN)
    assert site._guard_refuses_name("Payment Receipt - Pay now", want, OWN)
    assert not site._guard_refuses_name("Payment Receipt - " + SAID, want, OWN)


# -- the trace tells a refused description by fixed words -------------------------

def test_a_refused_description_is_told_by_fixed_words():
    assert site._description_mask("Payment Receipt - " + SAID) == \
        "payment received , thank you for your payment"
    assert site._description_mask("Payment Receipt - Payment for Jane Q Invented 2017 Camry") == \
        "payment for * * * # *"
    assert site._description_mask("Payment Receipt - Paid by card ending ****4321") == \
        "paid by card ending ? ? ? ? #"
    assert site._description_mask("not shaped like a document") == ""


PERSONAL = ["Jane", "Q", "Invented", "4321", "Maple", "Camry", "Roadster", "Grand", "Tourer",
            "Kelvin", "ſend", "Pay​now", "pаy", "Señor", "Zoë", "١٢٣", "policy#99A"]


def test_a_refused_descriptions_words_never_carry_anything_else():
    """download-attempt.json is posted publicly. Whatever a description says,
    its told words are the fixed list's, a placeholder or a listed mark."""
    rng = random.Random(1002)
    vocab = sorted(site._DESCRIPTION_WORDS)
    allowed = set(site._DESCRIPTION_WORDS) | set(site._DESCRIPTION_MARKS) | {"*", "#", "?", "..."}
    for _ in range(4000):
        words = [rng.choice(vocab + PERSONAL) for _ in range(rng.randint(1, 20))]
        told = site._description_mask("Payment Receipt - " + " ".join(words))
        assert set(told.split()) <= allowed, (words, told)
        for p in PERSONAL:
            assert p.lower() not in told.split(), (p, told)


def test_no_personal_word_is_in_the_fixed_list():
    for p in PERSONAL + ["jane", "camry", "honda", "toyota", "ford", "january", "march",
                         "bill", "visa", "mastercard", "amex", "discover", "checking",
                         "savings", "declined", "returned", "reversed"]:
        assert p.lower() not in site._DESCRIPTION_WORDS, p


# -- in a browser, the fake Document Center fills its rows from the list ---------

Y = shaped.THIS_YEAR


def _answers(description, doc_id="invented-311"):
    this = [shaped._listed("01/02/%d" % Y, "Renewal Notice", "Auto", "2017 Invented Roadster",
                           "invented-1")]
    last = [shaped._listed("03/11/%d" % (Y - 1), "Payment Receipt", "Billing/Payments",
                           description, doc_id)]
    return {"": this, str(Y): this, str(Y - 1): last}


def _drawn_as(words):
    """A Document Center that fills itself from the list but names each
    document with `words` after its type, whatever the list says."""
    fill = shaped._FILLED_BY_THE_LIST.replace(
        "e.type + ' - ' + e.description", "e.type + ' - ' + %s" % json.dumps(words))
    assert fill != shaped._FILLED_BY_THE_LIST
    return shaped._anew([], fill=fill)


def _run(tmp_path, description, hint="invented-311", drawn=None):
    asked = []
    page = (lambda: _drawn_as(drawn)) if drawn is not None else shaped._fills_itself
    driver, browser, pg = shaped._drive(page, [shaped._list_by_year(asked, _answers(description))])
    try:
        pg.wait_for_selector("button.view")
        out = tmp_path / "doc.pdf"
        trace = []
        ok = site.download_bill(pg, None, "%d-03-11" % (Y - 1), out,
                                title="Payment Receipt - Billing/Payments", trace=trace, hint=hint)
        return ok, out, trace
    finally:
        browser.close()
        driver.stop()


def _row_note(trace):
    [row] = [t for t in trace if t.get("note") == "the row's documents"]
    return row


def _clicked(trace):
    return [t["control"] for t in trace if t.get("note") == "clicked"]


def _documents(row):
    """What appeared in the row, less its own View Documents button."""
    return [a for a in row["appeared"] if not a.startswith("View Documents")]


def test_his_receipt_described_as_the_list_describes_it_is_pressed_and_saved(tmp_path):
    ok, out, trace = _run(tmp_path, SAID)
    assert ok, trace
    assert out.read_bytes() == ("%%PDF-1.4 the document of 03/11/%d" % (Y - 1)).encode()
    assert _clicked(trace) == ["View Documents0", "Payment Receipt - ..."], _clicked(trace)
    row = _row_note(trace)
    # His receipt's name runs past sixty characters, so the page's controls
    # list only its start, and its whole name was matched before the press.
    assert row["named_as_the_list_names_it"] == "its first sixty characters", row
    assert row["refused_words"] == [], row
    assert "thank" not in json.dumps(trace)


def test_a_short_name_described_as_the_list_describes_it_says_so(tmp_path):
    ok, out, trace = _run(tmp_path, "Payment received, thank you")
    assert ok, trace
    assert _row_note(trace)["named_as_the_list_names_it"] == "yes"


def test_without_a_hint_the_receipt_is_refused_and_the_trace_tells_its_words(tmp_path):
    """A record discovered before the list gave ids carries no hint, so
    there is nothing to read the list's words by, and the nouns refuse it as
    0.41.1 did. The trace now says which words, from the fixed list."""
    ok, out, trace = _run(tmp_path, "Payment from Jane Q Invented", hint="")
    assert not ok and not out.exists()
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    row = _row_note(trace)
    assert row["named_as_the_list_names_it"] == "the list gave no words for it", row
    assert row["refused_words"] == ["payment from * * *"], row
    text = json.dumps(trace)
    assert "Jane" not in text and "Invented" not in text


def test_a_page_that_names_the_document_otherwise_is_refused_as_before(tmp_path):
    ok, out, trace = _run(tmp_path, "Payment Receipt", drawn="Payment received, thank you")
    assert not ok and not out.exists()
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    row = _row_note(trace)
    assert row["named_as_the_list_names_it"] == "no", row
    assert _documents(row) == ["Payment Receipt - ..., refused by the guard for payment"], row
    assert row["refused_words"] == ["payment received , thank you"], row


def test_a_long_name_that_parts_from_the_lists_words_past_the_cut_is_not_pressed(tmp_path):
    """Its first sixty characters are the start of the list's words, and its
    whole name, read off the node before the press, is not the list's."""
    ok, out, trace = _run(tmp_path, SAID, drawn=SAID + " in full")
    assert not ok and not out.exists()
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    assert _row_note(trace)["named_as_the_list_names_it"] == "its first sixty characters"
    [why] = [t["why"] for t in trace if t.get("note") == "no revealed document was pressed"]
    assert why == "the guard refuses the document's whole name", why


def test_a_description_that_acts_is_refused_though_the_list_gives_it(tmp_path):
    ok, out, trace = _run(tmp_path, "Pay now")
    assert not ok and not out.exists()
    assert _clicked(trace) == ["View Documents0"], _clicked(trace)
    row = _row_note(trace)
    assert row["named_as_the_list_names_it"] == "yes", row
    assert _documents(row) == ["Payment Receipt - ..., refused by the guard for pay"], row
