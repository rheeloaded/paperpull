"""SimpliSafe monitoring history and invoice tests with invented data."""
import ast
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simplisafe_site as site


FIRST = "0" * 31 + "1"
SECOND = "0" * 31 + "2"
DATE = "2032-03-05"
APP = Path(__file__).resolve().parents[1]

# Five invented invoices, newest first, two of them on one day.
FIVE = [
    ("a" * 31 + "1", "07/05/32"),
    ("a" * 31 + "2", "06/05/32"),
    ("a" * 31 + "3", "06/05/32"),
    ("a" * 31 + "4", "04/05/32"),
    ("a" * 31 + "5", "03/05/32"),
]


def view(*ids, label="1 – 2 of 2"):
    return {"range": label, "rows": [{"id": key, "date": "03/05/32"} for key in ids]}


def test_row_dates_and_same_day_invoice_ids_remain_distinct():
    shown = site._parse_view(view(FIRST, SECOND))
    assert shown.total == len(shown.bills) == 2
    assert {bill.record.date_text for bill in shown.bills.values()} == {DATE}
    assert FIRST not in repr([bill.record for bill in shown.bills.values()])
    with pytest.raises(site.ListStopped):
        site._parse_view(view(FIRST, FIRST))


@pytest.mark.parametrize("label,ids", [
    ("1 – 3 of 2", (FIRST, SECOND)),      # a range past its count
    ("2 – 1 of 5", ()),                    # a range turned around
    ("1 – 2 of 5", (FIRST,)),              # fewer rows than the range names
    ("1 – 1 of 5", (FIRST, SECOND)),       # more rows than the range names
    ("0 of 0", (FIRST,)),                  # rows under an empty count
    ("37", (FIRST,)),                      # a count with no range
    ("1 to 2 of 2", (FIRST, SECOND)),
    ("", (FIRST,)),
])
def test_a_page_that_disagrees_with_its_own_range_stops_the_list(label, ids):
    with pytest.raises(site.ListStopped):
        site._parse_view(view(*ids, label=label))


def test_an_empty_history_reads_as_empty_and_a_plain_dash_is_read():
    assert site._parse_view(view(label="0 of 0")).total == 0
    assert site._parse_view(view(FIRST, SECOND, label="1 - 2 of 2")).total == 2


def test_the_app_never_routes_changes_or_answers_a_request():
    """Read-only. The history is read from what the page draws, never by
    rewriting, replaying or answering one of SimpliSafe's own requests."""
    banned = {"route", "unroute", "fetch", "fulfill", "continue_", "fallback", "abort",
              "set_extra_http_headers", "expect_request", "request"}
    for path in (APP / "simplisafe_site.py", APP / "simplisafe_docs.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not used & banned, (path.name, sorted(used & banned))


def test_every_press_goes_through_the_guards():
    """No raw Playwright click, tap, dispatch or check anywhere in the app."""
    tree = ast.parse((APP / "simplisafe_site.py").read_text(encoding="utf-8"))
    raw = {"click", "dblclick", "tap", "dispatch_event", "check", "press", "set_checked"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in raw:
            owner = node.func.value
            assert isinstance(owner, ast.Name) and owner.id == "pressing", ast.dump(node)


# A page like Manage Account → Monitoring Payments, with Angular Material's
# paginator. window.lag holds a page's rows back after its range changes,
# window.stuck never draws them, and window.presses counts the paginator's
# presses.
PAGE = r"""
<ss-monitoring-payments>
  <table><thead><tr><th>Date</th><th>Invoice</th></tr></thead><tbody></tbody></table>
  <table hidden><thead><tr><th>Invoice Summary</th></tr></thead></table>
  <mat-paginator class="mat-mdc-paginator">
    <div class="mat-mdc-paginator-range-label"></div>
    <button type="button" class="mat-mdc-paginator-navigation-previous" aria-label="Previous page">&lt;</button>
    <button type="button" class="mat-mdc-paginator-navigation-next" aria-label="Next page">&gt;</button>
  </mat-paginator>
</ss-monitoring-payments>
<button id="incidental">Pay balance</button>
<script>
const all = INVOICES;
const size = SIZE;
let at = 0;
window.presses = 0;
const body = document.querySelector('tbody');
const label = document.querySelector('.mat-mdc-paginator-range-label');
const prev = document.querySelector('.mat-mdc-paginator-navigation-previous');
const next = document.querySelector('.mat-mdc-paginator-navigation-next');
function rows() {
  body.innerHTML = '';
  for (const [id, date] of all.slice(at * size, at * size + size)) {
    const row = body.insertRow();
    row.insertCell().textContent = date;
    const link = document.createElement('a');
    link.textContent = id;
    link.onclick = () => openInvoice(id, date);
    row.insertCell().append(link);
  }
}
function range() {
  const first = all.length ? at * size + 1 : 0;
  const last = Math.min(all.length, at * size + size);
  label.textContent = all.length ? first + ' – ' + last + ' of ' + all.length : '0 of 0';
  prev.disabled = at === 0;
  next.disabled = last >= all.length;
}
function turn(way) {
  window.presses += 1;
  at += way;
  range();
  if (window.stuck) return;
  if (window.lag) setTimeout(rows, window.lag); else rows();
}
prev.onclick = () => turn(-1);
next.onclick = () => turn(1);
function openInvoice(id, date) {
  const dialog = document.createElement('mat-dialog-container');
  const shownId = window.forceInvoice || id;
  const [m, d, y] = date.split('/');
  const shownDate = window.forceDate || (m + '/' + d + '/20' + y);
  dialog.innerHTML = '<ss-payment-details-display><div class="invoice-container">'
    + '<h2>Invoice: SS' + shownId + '</h2><h3>Date:</h3><p>' + shownDate + '</p>'
    + '<table><thead><tr><th>Description</th><th>Total</th></tr></thead>'
    + '<tbody><tr><td>Example monitoring</td><td>$1.00</td></tr></tbody></table></div>'
    + '</ss-payment-details-display><button class="close" type="button">Close</button>';
  dialog.querySelector('button').onclick = () => dialog.remove();
  document.body.append(dialog);
}
rows();
range();
</script>
"""


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(site, "_TURN_PAUSE_MS", 0)
    monkeypatch.setattr(site, "_TURN_WAIT_S", 3.0)


def open_history(browser, invoices, size, requests=None):
    html = PAGE.replace("INVOICES", json.dumps(invoices)).replace("SIZE", str(size))
    tab = browser.new_page()

    def answer(route):
        if requests is not None:
            requests.append(route.request.url)
        if route.request.url == site.BASE + "/":
            route.fulfill(body=html, content_type="text/html; charset=utf-8")
        else:
            route.abort()

    tab.route("**/*", answer)
    tab.goto(site.DOCUMENTS_URL)
    return tab


@pytest.fixture
def page(browser):
    return open_history(browser, [(FIRST, "03/05/32"), (SECOND, "03/05/32")], 10)


def test_both_visible_bills_render_and_match(page, tmp_path):
    records = site.collect_download_docs(page)
    assert len(records) == 2
    assert page.evaluate("window.presses") == 0
    for index, doc in enumerate(records):
        path = tmp_path / f"{index}.pdf"
        assert site.download_bill(page, doc.date_text, path, document_id=doc.document_id)
        assert path.read_bytes().startswith(b"%PDF-")
        assert not page.locator(site._DIALOG).count()
    assert page.evaluate("window.presses") == 0


@pytest.mark.parametrize("wrong_value", [
    ("forceInvoice", SECOND), ("forceDate", "03/06/2032"), ("forceDate", "Unavailable"),
])
def test_wrong_view_is_closed_and_never_saved(page, tmp_path, wrong_value):
    first = site.collect_download_docs(page)[0]
    page.evaluate("([name,value]) => window[name]=value", list(wrong_value))
    path = tmp_path / "bill.pdf"
    assert not site.download_bill(page, first.date_text, path, document_id=first.document_id)
    assert not path.exists()
    assert not page.locator(site._DIALOG).count()


def test_rejects_invoice_control_that_navigates_to_another_host(page, tmp_path):
    first = site.collect_download_docs(page)[0]
    page.locator("ss-monitoring-payments a").first.evaluate("el=>el.href='https://example.test/'")
    with pytest.raises(site.ListStopped, match="view control"):
        site.download_bill(page, first.date_text, tmp_path / "bill.pdf", document_id=first.document_id)
    assert not page.locator(site._DIALOG).count()


def test_discovery_leaves_an_existing_account_dialog_open(page):
    page.evaluate("""() => {
        const dialog = document.createElement('mat-dialog-container');
        dialog.textContent = 'Example account dialog';
        document.body.append(dialog);
    }""")
    with pytest.raises(site.ListStopped, match="Close the open SimpliSafe dialog"):
        site.collect_download_docs(page)
    assert page.locator(site._DIALOG).count() == 1


def test_a_long_history_is_read_through_the_pages_own_next_button(browser):
    requests = []
    tab = open_history(browser, FIVE, 2, requests)
    records = site.collect_download_docs(tab)
    assert sorted(r.date_text for r in records) == sorted(site._date(d) for _, d in FIVE)
    assert len({r.document_id for r in records}) == 5
    assert tab.evaluate("window.presses") == 2
    # Only the page itself was asked for, nothing of the app's making.
    assert requests == [site.BASE + "/"]


def test_rows_drawn_after_the_range_are_waited_for(browser):
    tab = open_history(browser, FIVE, 2)
    tab.evaluate("window.lag = 700")
    assert len(site.collect_download_docs(tab)) == 5


def test_a_range_that_moves_without_its_rows_stops_the_list(browser):
    tab = open_history(browser, FIVE, 2)
    tab.evaluate("window.stuck = true")
    with pytest.raises(site.ListStopped, match="next page"):
        site.collect_download_docs(tab)
    assert tab.evaluate("window.presses") == 1


def test_a_history_shown_from_a_later_page_is_read_from_its_first(browser):
    tab = open_history(browser, FIVE, 2)
    tab.locator(site._MONITORING + " button.mat-mdc-paginator-navigation-next").click()
    tab.locator(site._MONITORING + " button.mat-mdc-paginator-navigation-next").click()
    assert len(site.collect_download_docs(tab)) == 5


@pytest.mark.parametrize("repeated,said", [
    # On the page right after, it reads as rows that never changed.
    (FIVE[:3] + [FIVE[0]] + FIVE[4:], "next page"),
    # On a later page, as a repeat.
    (FIVE[:4] + [FIVE[0]], "same invoice"),
])
def test_a_page_that_repeats_an_earlier_invoice_stops_the_list(browser, repeated, said):
    tab = open_history(browser, repeated, 2)
    with pytest.raises(site.ListStopped, match=said):
        site.collect_download_docs(tab)


@pytest.mark.parametrize("change", [
    "el => el.setAttribute('aria-label', 'Pay now')",
    "el => el.setAttribute('aria-label', 'Next page of results')",
    "el => el.remove()",
    "el => { const div = document.createElement('div'); div.className = el.className;"
    " div.setAttribute('aria-label', 'Next page'); div.setAttribute('role', 'button');"
    " div.onclick = () => { window.presses += 1; }; el.replaceWith(div); }",
    "el => { const form = document.createElement('form'); el.replaceWith(form); form.append(el); }",
    "el => el.setAttribute('type', 'submit')",
    "el => el.disabled = true",
])
def test_a_changed_next_button_is_never_pressed(browser, change):
    tab = open_history(browser, FIVE, 2)
    tab.locator("button.mat-mdc-paginator-navigation-next").evaluate(change)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(tab)
    assert tab.evaluate("window.presses") == 0


def test_bills_on_any_page_are_saved_in_any_order(browser, tmp_path):
    tab = open_history(browser, FIVE, 2)
    records = {r.document_id: r for r in site.collect_download_docs(tab)}
    by_id = {site.Bill(key, site._date(date)).key: key for key, date in FIVE}
    for wanted in (FIVE[4][0], FIVE[0][0], FIVE[3][0], FIVE[1][0]):
        key = next(k for k, v in by_id.items() if v == wanted)
        path = tmp_path / f"{wanted}.pdf"
        assert site.download_bill(tab, records[key].date_text, path, document_id=key)
        assert site._pdf_matches(path.read_bytes(), site.Bill(wanted, records[key].date_text))
        assert not tab.locator(site._DIALOG).count()


def test_an_empty_history_lists_nothing_and_presses_nothing(browser):
    tab = open_history(browser, [], 10)
    assert site.collect_download_docs(tab) == []
    assert tab.evaluate("window.presses") == 0


def test_rows_that_move_under_a_range_that_stays_stop_the_list(browser):
    tab = open_history(browser, FIVE, 2)
    tab.evaluate("""() => {
        const next = document.querySelector('.mat-mdc-paginator-navigation-next');
        next.addEventListener('click', () => setTimeout(() => {
            document.querySelector('.mat-mdc-paginator-range-label').textContent = '1 – 2 of 5';
        }, 0));
    }""")
    with pytest.raises(site.ListStopped, match="next page"):
        site.collect_download_docs(tab)


def test_a_sign_in_form_while_paging_is_a_signed_out_session(browser):
    tab = open_history(browser, FIVE, 2)
    tab.evaluate("""() => {
        const next = document.querySelector('.mat-mdc-paginator-navigation-next');
        next.addEventListener('click', () => {
            const field = document.createElement('input');
            field.type = 'password';
            document.body.append(field);
        });
    }""")
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(tab)


def test_an_invoice_count_that_changes_while_paging_stops_the_list(browser):
    tab = open_history(browser, FIVE, 2)
    tab.evaluate("""() => {
        const next = document.querySelector('.mat-mdc-paginator-navigation-next');
        next.addEventListener('click', () => setTimeout(() => {
            const label = document.querySelector('.mat-mdc-paginator-range-label');
            label.textContent = label.textContent.replace(/of 5$/, 'of 6');
        }, 0));
    }""")
    with pytest.raises(site.ListStopped, match="count changed"):
        site.collect_download_docs(tab)
