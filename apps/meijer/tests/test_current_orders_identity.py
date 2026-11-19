"""The current orders page (#236) ties each purchase to its own row and its
own button, by the date and time the row prints.

The page lists each purchase as "In-Store: September 13, 2026, 11:41 am"
over its store and amount, with a button whose name for a screen reader is
"Download receipt from September 13, 2026, 11:41 am". Two purchases on one
day differ only by their time, and a button names a purchase of its own.

The orders page is served here on www.meijer.com and every other request
is refused, so nothing leaves this machine. Every date, time, store and
amount is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.words import words_for, write_shaped

ORDERS = "https://www.meijer.com/shopping/orders"
WHEN = "September 13, 2026, 11:41 am"

# A PDF the page hands over as a download when its button is pressed.
SAVE = r"""<script>
function saveReceipt() {
  const pdf = '%PDF-1.4\n% invented receipt\n' + 'x'.repeat(300) + '\n%%EOF\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
  a.download = 'receipt.pdf';
  document.body.appendChild(a);
  a.click();
}
</script>"""


def button(when, who, words="&#8595;"):
    return (f'<button type="button" aria-label="Download receipt from {when}" '
            f'onclick="window.pressed.push(\'{who}\')">{words}</button>')


def row(when, ctl, store="4400 Invented Avenue", amount="$31.23"):
    return (f'<li class="order-card"><div class="date">In-Store: {when}</div><div>{store}</div>'
            f'<div class="totals"><span>{amount}</span>&nbsp;&nbsp;2 items</div>{ctl}</li>')


def page_of(*rows):
    return ('<!doctype html><html><body><main><h1>Orders</h1><div role="tablist">'
            '<button role="tab">Online</button><button role="tab">In-Store</button></div>'
            '<ul>' + "".join(rows) + '</ul><script>window.pressed = [];</script></main></body></html>')


@pytest.fixture
def browse(monkeypatch):
    """A page served as Meijer's orders page, given its html."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "ROW_LOOKS", 1)
    opened = []

    def open_page(html):
        ctx = browser.new_context(accept_downloads=True)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route(ORDERS, lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        pg = ctx.new_page()
        pg.goto(ORDERS)
        opened.append(ctx)
        return pg

    yield open_page
    for ctx in opened:
        ctx.close()
    browser.close()
    driver.stop()


def purchases(pg):
    return [site.card_to_purchase(c) for c in site.collect_cards(pg)]


def press(pg, purchase):
    facts, trace = {}, []
    body = site.press_row_receipt(pg, purchase, trace, facts)
    return body, facts.get("outcome"), pg.evaluate("window.pressed"), trace


# -- the date line is not the purchase's name ------------------------------

def test_the_date_and_time_line_is_never_the_purchase_name():
    """The line "In-Store: September 13, 2026, 11:41 am" is 39 characters,
    longer than the 24 a date line was allowed, so it became the purchase's
    name, its summary and its file name, and every September row matched the
    first twelve characters of it."""
    card = site.RawCard(text=f"In-Store: {WHEN}\n4400 Invented Avenue\n$31.23  2 items")
    assert site.card_to_purchase(card).items[0].name == "4400 Invented Avenue"


@pytest.mark.parametrize("text,name,key", [
    # Control. The layout Meijer showed before, its name and archive key as
    # 92f3aba4 gives them, so nothing already saved is saved again.
    ("In-Store: 09/19/2026\n1600 Invented Road\n$31.23  6 items", "1600 Invented Road", "In-Store:pdd68c0110267"),
    ("Jun 9, 2026 Order 4417 $31.50\nInvented Market Order", "Jun 9, 2026 Order 4417 $31.50", "Online:p7b62875dd23b"),
])
def test_a_row_of_the_layout_before_keeps_its_name_and_key(text, name, key):
    p = site.card_to_purchase(site.RawCard(text=text))
    assert (p.items[0].name, p.key) == (name, key)


# -- each purchase presses its own row --------------------------------------

@pytest.mark.parametrize("mine,twin", [
    ("September 13, 2026, 4:02 pm", WHEN),
    # "1:41 am" sits inside "11:41 am".
    ("September 13, 2026, 1:41 am", WHEN),
    ("September 13, 2026, 12:05 am", "September 13, 2026, 12:05 pm"),
])
def test_two_purchases_of_one_day_each_press_their_own_row(browse, mine, twin):
    pg = browse(page_of(row(twin, button(twin, "twin")), row(mine, button(mine, "mine"))))
    ps = purchases(pg)
    assert len({p.key for p in ps}) == 2
    _body, outcome, pressed, _trace = press(pg, ps[1])
    assert pressed == ["mine"], outcome
    _body, outcome, pressed, _trace = press(pg, ps[0])
    assert pressed == ["mine", "twin"], outcome


def test_a_time_with_other_spaces_is_still_its_row(browse):
    """Chromium's own dates put a narrow no-break space before "am"."""
    odd = "September&nbsp;13, 2026, 11:41&#8239;am"
    pg = browse(page_of(row("September 13, 2026, 4:02 pm", button("September 13, 2026, 4:02 pm", "twin")),
                        row(odd, button(WHEN, "mine"))))
    _body, outcome, pressed, _trace = press(pg, purchases(pg)[1])
    assert pressed == ["mine"], outcome


def test_a_purchase_whose_row_is_gone_never_takes_its_twins_button(browse):
    """The 11:41 purchase was listed when it was found. Its row is gone now,
    and the one row left is its twin of the same day, store and amount."""
    gone = site.card_to_purchase(site.RawCard(
        text=f"In-Store: {WHEN}\n4400 Invented Avenue\n$31.23  2 items"))
    twin = "September 13, 2026, 4:02 pm"
    pg = browse(page_of(row(twin, button(twin, "twin"))))
    _body, outcome, pressed, _trace = press(pg, gone)
    assert pressed == []
    assert outcome == site.NOT_ON_THE_PAGE


def test_identical_rows_are_refused(browse):
    pg = browse(page_of(row(WHEN, button(WHEN, "a")), row(WHEN, button(WHEN, "b"))))
    _body, outcome, pressed, _trace = press(pg, purchases(pg)[0])
    assert (outcome, pressed) == (site.MORE_THAN_ONE_ROW, [])


# -- the button's own words -------------------------------------------------

def test_a_button_that_shows_its_whole_label_is_pressed(browse):
    """Its words were cut at 40 characters, "Download receipt from September
    13, 2026", and that no longer read as a receipt control."""
    ctl = ('<button type="button" onclick="window.pressed.push(\'mine\')">'
           f'Download receipt from {WHEN}</button>')
    pg = browse(page_of(row(WHEN, ctl)))
    _body, outcome, pressed, _trace = press(pg, purchases(pg)[0])
    assert pressed == ["mine"], outcome


@pytest.mark.parametrize("named", [
    "September 12, 2026, 6:15 pm",   # another day
    "September 13, 2026, 4:02 pm",   # the same day, another time
])
def test_a_button_naming_another_purchase_is_never_pressed(browse, named):
    pg = browse(page_of(row(WHEN, button(named, "other"))))
    _body, outcome, pressed, _trace = press(pg, purchases(pg)[0])
    assert (outcome, pressed) == (site.NO_RECEIPT_CONTROL, [])


@pytest.mark.parametrize("label", [
    f"Download receipt from {WHEN} EDT",
    "Download receipt from Sept 13, 2026, 11:41 am",
    "Download receipt from September 13, 2026",
    "Download receipt from",
    f"Email receipt from {WHEN}",
    f"Share receipt from {WHEN}",
    f"Delete receipt from {WHEN}",
    f"Download receipt from {WHEN} and email it",
])
def test_words_not_seen_on_the_page_are_refused(label):
    """Only the words the page was seen to use are a receipt control. Any
    other is refused rather than guessed at, and so is one that sends,
    shares or deletes."""
    assert not site.is_receipt_control({"text": "", "label": label})


# -- what the file a tester attaches says -----------------------------------

def test_the_attempt_never_names_the_purchases_date(browse, tmp_path):
    """The trace named the control by its own words, and a button that
    shows "Download receipt from September 13, 2026, 11:41 am" put the
    month and the time of the purchase into a file a tester attaches."""
    ctl = ('<button type="button" onclick="window.pressed.push(\'mine\');saveReceipt()">'
           f'Download receipt from {WHEN}</button>')
    pg = browse(page_of(row(WHEN, ctl)).replace("</main>", SAVE + "</main>"))
    body, outcome, pressed, trace = press(pg, purchases(pg)[0])
    assert body and body[:5] == b"%PDF-", outcome
    out = tmp_path / "download-attempt.json"
    write_shaped(out, {"responses": trace}, words_for("Meijer", site))
    said = out.read_text(encoding="utf-8")
    assert "the receipt came from the row's control" in said
    for words in ("September", "Invented", "11:41"):
        assert words not in said, said
    assert json.loads(said)


def test_the_diagnose_file_names_a_dated_control_in_fixed_words():
    """Diagnose wrote the first row's controls with only their digits
    masked, and at 160 characters a button's name kept its month and its am
    or pm (review)."""
    assert site.control_words(f"Download receipt from {WHEN}") == \
        "the receipt control, which names its date"
    assert site.control_words("view receipt pdf") == "view receipt pdf"
    import inspect
    import meijer_receipts
    src = inspect.getsource(meijer_receipts.App.cmd_diagnose)
    assert '"text": site.control_words(x["text"])' in src
    assert '"label": site.control_words(x["label"])' in src


def test_a_row_past_the_collectors_cap_is_still_pressed(browse):
    """The collector reads at most ROWS_CAP rows, and a purchase's own row
    was looked for among those only, so one further down the list was never
    found (review)."""
    mine = row(WHEN, button(WHEN, "mine"))
    pg = browse(page_of(mine))
    purchase = purchases(pg)[0]
    filler = [row(f"January {1 + i % 28}, {2020 + i // 28}, 9:05 am", button("x", "filler"),
                  amount=f"${10 + i}.00") for i in range(site.ROWS_CAP + 4)]
    pg = browse(page_of(*filler, mine))
    _body, outcome, pressed, _trace = press(pg, purchase)
    assert pressed == ["mine"], outcome
