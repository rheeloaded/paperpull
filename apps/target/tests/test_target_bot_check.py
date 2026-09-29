"""Target's own bot check, in a real browser (#48).

A tester's Discover on 0.39.1 met a "Quick verification" window on
/orders, asking him to press and hold a button to confirm he is not a bot.
None of the words this app knew for a check was on it, so the run kept
pressing Load more and then reloaded the orders page for the in-store half,
which throws away an answer he had just given. In Pilot or Run All the same
page has no receipt control, and a purchase it hid would have been marked
No Receipt Available, which is never asked for again.

The check is his to answer. The app never presses it, and stops when it
comes. Every page here is made up and nothing leaves this machine.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts
import target_site as site
from paperpull_core.models import ONLINE, Item, Purchase, State

APP_DIR = Path(__file__).resolve().parents[1]

# The check the way his was, its words in the page and its button in a
# frame of its own.
CHECK = ("<h1>Quick verification</h1><p>Press &amp; hold to confirm you're not a bot.</p>"
         "<iframe srcdoc=\"<button>Press &amp; Hold</button>\"></iframe>")

ORDERS = """<!doctype html><html><body><main id="m">
<div id="cards"></div><button id="more">Load more</button></main><script>
window.presses = 0;
function card(i) {
  const a = document.createElement('a');
  a.setAttribute('data-test', 'order-details-link');
  a.href = '/orders/10' + i;
  a.textContent = 'Order ' + i;
  return a;
}
for (let i = 0; i < 3; i++) document.getElementById('cards').appendChild(card(i));
document.getElementById('more').addEventListener('click', () => {
  window.presses++;
  const list = document.getElementById('cards');
  for (let i = 0; i < 3; i++) list.appendChild(card(list.children.length));
  // The second press brings Target's check over the page.
  if (window.presses === 2) {
    const over = document.createElement('div');
    over.innerHTML = CHECK_JSON;
    document.body.appendChild(over);
  }
});
</script></body></html>"""


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


def test_the_check_is_known_by_its_words_even_inside_its_own_frame(page):
    page.set_content("<main>%s</main>" % CHECK)
    assert site.detect_security_challenge(page)
    page.set_content("<main><iframe srcdoc=\"<p>Press &amp; Hold</p>\"></iframe></main>")
    assert site.detect_security_challenge(page), "the words only in the frame"
    page.set_content("<main><h1>Orders</h1><a data-test='order-details-link' href='/orders/1'>"
                     "Order 1</a></main>")
    assert site.detect_security_challenge(page) is None


def test_the_paging_stops_when_the_check_comes(page):
    page.set_content(ORDERS.replace("CHECK_JSON", json.dumps(CHECK)))
    site.load_all_cards(page, ONLINE, delay_ms=50, max_rounds=40)
    assert page.evaluate("window.presses") == 2, "nothing is pressed once the check is showing"


def _app(tmp_path, monkeypatch, answer):
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Tester", "output_dir": str(tmp_path / "out"),
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(target_receipts.browser_launcher, "ask_or_none", lambda prompt: answer)
    return target_receipts.App(target_receipts.build_parser().parse_args(["--config", str(path)]))


def _purchase():
    return Purchase(purchase_type=ONLINE, purchase_date="2026-09-01", order_number="102000111",
                    total="$12.34", status="Delivered", store_info="Target",
                    details_url="https://www.target.com/orders/102000111",
                    items=[Item(name="Invented thing", quantity="1", line_total="$12.34")])


def test_a_purchase_the_check_hid_is_never_marked_as_having_no_receipt(page, tmp_path, monkeypatch):
    """Under the panel nobody can answer, so the run stops, and the
    purchase is left to be asked for again."""
    app = _app(tmp_path, monkeypatch, None)
    page.set_content("<main>%s</main>" % CHECK)
    purchase = _purchase()
    with pytest.raises(SystemExit):
        app._handle_no_receipt(page, purchase)
    rec = app.progress.get(purchase.key) or {}
    assert rec.get("state") != State.NO_RECEIPT_AVAILABLE.value, rec


def test_at_a_console_too_the_check_stops_the_run_and_leaves_the_purchase(page, tmp_path, monkeypatch):
    """Until 0.41.0 a console run waited here for the answer, with the app
    still attached, and the check refused the hold (#48)."""
    app = _app(tmp_path, monkeypatch, "")
    page.set_content("<main>%s</main>" % CHECK)
    purchase = _purchase()
    with pytest.raises(SystemExit):
        app._handle_no_receipt(page, purchase)
    rec = app.progress.get(purchase.key) or {}
    assert rec.get("state") != State.NO_RECEIPT_AVAILABLE.value, rec


# -- 0.41.0, the check is answered with the app gone (#48) ------------------------

def test_the_check_is_answered_with_the_app_gone(page, tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch, "")
    happened = []
    monkeypatch.setattr(target_receipts.browser_launcher, "ask_or_none",
                        lambda prompt: happened.append("asked") or "")
    real_close = app.close
    monkeypatch.setattr(app, "close", lambda: happened.append("let go") or real_close())
    page.set_content("<main>%s</main>" % CHECK)
    with pytest.raises(SystemExit) as stop:
        app.check_session(page)
    assert stop.value.code == 0, "a clean stop, reported as stopped"
    assert happened == ["let go"], "nobody is asked while the app is attached"
    out = capsys.readouterr().out
    assert "reload the page first" in out and "press Resume" in out


def test_what_was_read_is_kept_when_the_check_stops_the_run(page, tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "")
    purchase = _purchase()
    app.discovery.update(purchase.key, purchase.to_dict(), save=False)
    page.set_content("<main>%s</main>" % CHECK)
    with pytest.raises(SystemExit):
        app.check_session(page)
    on_disk = json.loads(app.paths.discovery_json.read_text(encoding="utf-8"))
    assert purchase.key in on_disk


def test_a_sign_out_still_waits_at_a_console(page, tmp_path, monkeypatch):
    """A sign-in is not a bot check, and the app stays attached for it, so
    the orders page can be opened again once it is answered."""
    app = _app(tmp_path, monkeypatch, "")
    asked = []
    monkeypatch.setattr(target_receipts.browser_launcher, "ask_or_none",
                        lambda prompt: asked.append(prompt) or "")
    monkeypatch.setattr(site, "looks_signed_out", lambda p: True)
    monkeypatch.setattr(site, "goto_orders", lambda p: None)
    page.set_content("<main><h1>Sign in</h1></main>")
    app.check_session(page)
    assert len(asked) == 1


# -- from the review of this change --------------------------------------------

def _cards(n):
    return "".join("<a data-test='order-details-link' href='/orders/%d'>Order %d, an invented thing "
                   "bought for the house and delivered</a>" % (i, i) for i in range(n))


def test_a_check_drawn_at_the_end_of_a_long_list_is_seen(page):
    """The check comes partway through paging, so it lands at the end of a
    body longer than the five thousand characters read from its start."""
    page.set_content("<main>%s</main><div>Quick verification. Press &amp; hold.</div>" % _cards(120))
    assert len(page.locator("body").inner_text()) > 5000
    assert site.detect_security_challenge(page)


def test_a_check_in_the_newest_of_many_frames_is_seen(page):
    frames = "".join("<iframe srcdoc='<p>ad %d</p>' width='120' height='60'></iframe>" % i for i in range(7))
    page.set_content("<main>%s%s<iframe srcdoc=\"<button>Press &amp; Hold</button>\"></iframe></main>"
                     % (_cards(3), frames))
    assert site.detect_security_challenge(page)


@pytest.mark.parametrize("frame", [
    "<p>This site is protected by reCAPTCHA and the Google Privacy Policy</p>",
    "<p>Something went wrong. Please try again later.</p>",
], ids=["a reCAPTCHA badge", "a frame's own try again later"])
def test_an_ordinary_frame_is_not_taken_for_a_check(page, frame):
    """A page's own frames can carry words that read as a check, and one of
    those taken for one would stop every run."""
    page.set_content("<main>%s<iframe srcdoc=\"%s\" width='256' height='60'></iframe></main>"
                     % (_cards(3), frame))
    assert site.detect_security_challenge(page) is None


def test_an_item_whose_name_starts_like_a_bot_is_not_a_check(page):
    page.set_content("<main><a data-test='order-details-link' href='/orders/1'>"
                     "Order 1, not a bottle opener but a corkscrew</a></main>")
    assert site.detect_security_challenge(page) is None
