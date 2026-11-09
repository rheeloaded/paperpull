"""A statement list read without an account or a year its dropdowns offer
is never noted whole.

Discover's statements page lists every statement as a link, and when those
links read nothing the page's text is read instead, under each account and
year its dropdowns offer. An account or a year whose choice did not take
was passed over, and the list noted as read whole, so Resume carried on
from it and called the run finished with an account or a year never read.

Now that reading names what it passed over, and Discover keeps what it
read, writes a failure file, leaves the listing as one that stopped, and
Pilot, Run All and Discover stop at their end rather than finish. An option
that is turned off or that the guard refuses is never chosen, and is no
part of the list passed over. Driven in a real browser against a made-up
page. Every account, year and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import discovercard_docs as app_mod
import discovercard_site as site
from paperpull_core import listing

ACCOUNTS = ("Example Card ending 0001", "Other Card ending 0002")

PAGE = """<!doctype html><html><body>
<label>Account <select id="acct" aria-label="Account">
  <option>Example Card ending 0001</option>
  <option>Other Card ending 0002</option>
  %s
</select></label>
<label>Year <select id="year" aria-label="Statement year">
  <option>2031</option><option>2030</option>%s
</select></label>
<ul id="rows"></ul>
<script>(() => {
const draw = () => {
  const a = document.getElementById('acct').value.slice(-4);
  const y = document.getElementById('year').value;
  document.getElementById('rows').innerHTML =
    '<li>Mar 15, ' + y + ' Statement ' + a + ' <a href="#">Download</a></li>';
};
document.getElementById('acct').onchange = draw;
document.getElementById('year').onchange = draw;
draw();
})();</script></body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    shortened = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: shortened(min(ms, 200))
    pg.set_content(PAGE % ("", ""))
    yield pg
    browser.close()
    driver.stop()


def choosing(monkeypatch, refuse=()):
    """_select_option, with the labels in `refuse` not taking, and every
    label asked for kept."""
    chosen = []
    real = site._select_option

    def choose(pg, sel, label):
        chosen.append(label)
        return False if label in refuse else real(pg, sel, label)
    monkeypatch.setattr(site, "_select_option", choose)
    return chosen


# -- the page's text reading names what it passed over ----------------------------

def test_a_reading_of_every_part_passes_over_nothing(page, monkeypatch):
    chosen = choosing(monkeypatch)
    got = site.discovercard_collect(page)
    assert set(ACCOUNTS) | {"2031", "2030"} <= set(chosen)
    assert {r["date"][:4] for r in got} == {"2031", "2030"}
    assert got.passed_over == ()


def test_an_account_that_could_not_be_chosen_is_passed_over(page, monkeypatch):
    choosing(monkeypatch, refuse=(ACCOUNTS[1],))
    assert site.discovercard_collect(page).passed_over == ("account picker",)


def test_a_year_that_could_not_be_chosen_is_passed_over(page, monkeypatch):
    choosing(monkeypatch, refuse=("2030",))
    got = site.discovercard_collect(page)
    assert {r["date"][:4] for r in got} == {"2031"}
    assert got.passed_over == ("year picker",)


def test_a_turned_off_or_refused_option_is_never_chosen_or_passed_over(page, monkeypatch):
    """A turned off year waited out its time and was passed over, and an
    account the guard refuses is never chosen."""
    page.set_content(PAGE % ("<option>Transfer funds ending 0003</option>",
                             "<option disabled>2029</option>"))
    chosen = choosing(monkeypatch)
    got = site.discovercard_collect(page)
    assert "2029" not in chosen and not any("Transfer" in c for c in chosen), chosen
    assert set(ACCOUNTS) | {"2031", "2030"} <= set(chosen)
    assert got.passed_over == ()


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch, page):
    pressed = []

    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_on_its_site", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, _name: pressed.append(doc.date))
        return app

    # The links read nothing, so the page's text is read.
    monkeypatch.setattr(site, "ensure_statements", lambda pg: True)
    monkeypatch.setattr(site, "discovercard_collect_via_api", lambda pg: [])
    build.pressed = pressed
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(make_app):
    app = make_app("--all")
    app.cmd_run("all")
    assert {d[:4] for d in make_app.pressed} == {"2031", "2030"}
    assert listing.last(app) == listing.COMPLETE


def test_a_list_passed_over_in_part_is_not_noted_whole(make_app, monkeypatch, tmp_path, capsys):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    choosing(monkeypatch, refuse=("2030",))
    app = make_app("--all")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert make_app.pressed and {d[:4] for d in make_app.pressed} == {"2031"}
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Discover's statement list was not read whole" in out
    assert "Not all of Discover's statement list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the statement list",
                                                  "some of the list could not be chosen")

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(make_app, monkeypatch):
    choosing(monkeypatch, refuse=("2030",))
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert make_app().discovery.data


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(make_app, monkeypatch):
    choosing(monkeypatch, refuse=("2030",))
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert make_app.pressed
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(
        make_app, monkeypatch, capsys):
    """No account could be chosen, so nothing was read and there is nothing
    to pilot."""
    choosing(monkeypatch, refuse=ACCOUNTS)
    app = make_app("--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Discover's statement list was read, so this run stops here" in out
    assert make_app.pressed == []
