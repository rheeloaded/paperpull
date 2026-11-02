"""A statement list read without an account whose Statement History would
not open is never noted whole.

Each account on the vendor's page is a panel, opened through its heading,
with a Statement History that brings its list into one dialog. A panel
whose Statement History press raised was passed over, and the list was
noted as read whole. Resume then carried on from it and called the run
finished with that account never read.

Now the read counts those panels, and Discover keeps what it read, writes a
failure file, sets nothing aside for not being on a list read in part,
leaves the listing as one that stopped, and Pilot, Run All and Discover
stop at their end rather than finish. Only a Statement History that showed,
could be pressed and read as one counts. An account with no statements
shows no list or a link turned off, two accounts billed on the same days
show the list before, a heading the guard refuses is never pressed, and a
hidden copy of a Statement History never shows, and a page that works can
do each of those, so each is read as it always was. A first version
counted every raise, and a review found a hidden copy stopping every run.
The download path asks the same panels, and it finds nothing for an
account whose history would not open, as before.

Driven in a real browser against the made-up vendor page of
test_one_dialog_for_every_account. Every account, date and number is
invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_docs as app_mod
import golden1_site as site
from paperpull_core import doc_types, listing
from paperpull_core.models import State
from paperpull_core.words import shape, words_for

import test_one_dialog_for_every_account as dialog

MEMBER = [site.parse_date(d) for d in dialog.MEMBER]
SECOND = "account ending 4321"
SHUT = "a panel's statement history did not show"
FAILED_LINE = ("Account 2 history did not show. Its Statement History showed and the press "
               "on it failed.")


def press_will_not_take(html, *panels):
    """The page with each of these panels' Statement History shown under a
    cover that takes every press, so the press waits out its time."""
    pairs = []
    for i in panels or (1,):
        link = dialog.HISTORY_LINK % i
        pairs.append((link, '<span style="position:relative">%s<span style="position:absolute;'
                            'inset:-4px;z-index:9"></span></span>' % link))
    return dialog._swap(html, pairs)


def heading_opens_nothing(html):
    """The second panel's heading drawn so a press on it opens nothing, its
    Statement History left hidden."""
    return dialog._swap(html, [
        ("h.addEventListener('click', () => {",
         "h.addEventListener('click', () => {\n    if (h.dataset.dead) return;"),
        (dialog.SECOND_SHUT, dialog.SECOND_SHUT.replace('<h2 ', '<h2 data-dead="1" ', 1))])


def a_hidden_copy(html):
    """A copy of a Statement History the page never shows, as a phone
    layout's would be (review)."""
    return dialog._swap(html, [("</form>", '</form><div style="display:none">'
                                           '<a href="#">Statement History</a></div>')])


def a_link_turned_off(html):
    return dialog._swap(html, [(dialog.HISTORY_LINK % 1, '<button type="button" class="hist" '
                                'data-panel="1" disabled>Statement History</button>')])


def no_statements_on_the_second(html):
    """The second account's history opens on an empty list."""
    return dialog._swap(html, [(json.dumps(dialog.CARD), "[]")])


def guarded_heading(html):
    """The second panel's heading names money moving, so it is never
    pressed."""
    return dialog._swap(html, [("PLATINUM REWARDS XXXXXXXXXXXX4321",
                                "PLATINUM REWARDS Transfer XXXXXXXXXXXX4321")])


def the_list_before(html):
    return dialog._vendor_html(show_at_once=True, held=[1, 1, 1])


# Each page a working vendor can draw where the second account's history
# does not show, the wait for a list it needs, and what its trace says.
WORKING = {
    "no list": (no_statements_on_the_second, 2400, site.NO_LIST),
    "the list before": (the_list_before, 3000, site.BEFORE),
    "a heading the guard refuses": (guarded_heading, None, ""),
    "a heading that opens nothing": (heading_opens_nothing, None, ""),
    "a link turned off": (a_link_turned_off, None, ""),
}


@pytest.fixture
def vendor(monkeypatch):
    """Draws the vendor's page a test hands it, and closes the browser
    after."""
    opened = []

    def draw(html, wait_ms=None):
        if wait_ms is not None:
            monkeypatch.setattr(site, "HISTORY_WAIT_MS", wait_ms)
        driver, browser, pg = dialog._drive(monkeypatch, html)
        opened.append((driver, browser))
        return pg
    yield draw
    for driver, browser in opened:
        browser.close()
        driver.stop()


def _read(pg):
    trace: list = []
    docs = site.collect_download_docs(pg, trace=trace)
    shut = [(t["panel"], t["list"]) for t in trace if t.get("note") == SHUT]
    return docs, trace, shut


# -- the read counts what it passed over ------------------------------------------

def test_a_whole_read_passes_over_nothing(vendor):
    docs, trace, shut = _read(vendor(dialog._vendor_html()))
    assert len(docs) == 41 and docs.passed_over == 0, trace
    assert shut == []


def test_a_history_whose_press_failed_is_passed_over(vendor):
    docs, trace, shut = _read(vendor(press_will_not_take(dialog._vendor_html())))
    assert [d.date_text for d in docs if d.account == ""] == MEMBER, trace
    assert [d for d in docs if d.account] == []
    assert docs.passed_over == 1
    assert shut == [(1, site.PRESS_FAILED)], trace
    assert FAILED_LINE in site.discovery_lines(trace)


@pytest.mark.parametrize("way", sorted(WORKING))
def test_a_history_a_working_page_can_leave_unshown_is_no_part_passed_over(vendor, way):
    page, wait_ms, how = WORKING[way]
    docs, trace, shut = _read(vendor(page(dialog._vendor_html()), wait_ms))
    assert [d.date_text for d in docs if d.account == ""] == MEMBER, trace
    assert docs.passed_over == 0
    assert shut == [(1, how)], trace


def test_a_hidden_copy_of_a_statement_history_is_no_part_passed_over(vendor):
    """It is a panel of its own, whose link never shows. Every account is
    read as before."""
    docs, trace, shut = _read(vendor(a_hidden_copy(dialog._vendor_html())))
    assert len(docs) == 41 and docs.passed_over == 0, trace
    assert shut == [(2, "")], trace


def test_the_phrases_a_history_is_said_by_come_through_the_word_list():
    words = words_for("Golden 1", site)
    for phrase in (site.DRAWN, site.DRAWN_SAME, site.SHOWN, site.BEFORE, site.NO_LIST,
                   site.PRESS_FAILED):
        assert shape(phrase, words) == phrase


def test_the_download_finds_nothing_in_a_history_whose_press_failed(vendor, tmp_path):
    """As before. Nothing is pressed, and the statement is not saved."""
    pg = vendor(press_will_not_take(dialog._vendor_html()))
    trace: list = []
    out = tmp_path / "second.pdf"
    assert not site.download_bill(pg, tmp_path / "dl", "2025-08-20", out,
                                  title="Account Statement - August 20, 2025", trace=trace,
                                  account=SECOND)
    assert not out.exists() and pg.evaluate("window.__pressed") == []
    assert [(t["panel"], t["list"]) for t in trace if t.get("note") == SHUT] == \
        [(1, site.PRESS_FAILED)], trace
    assert any(t.get("note") == "no control on this page carries that date" for t in trace)


# -- Discover ---------------------------------------------------------------------

@pytest.fixture
def make_app(tmp_path, monkeypatch, vendor):
    pressed = []
    state = {}

    def build(*argv, html=None, wait_ms=None):
        if html is not None:
            state["page"] = vendor(html, wait_ms)
        pg = state["page"]
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement", "Tax Document"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: pg)
        monkeypatch.setattr(app, "_on_its_site", lambda: pg)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        monkeypatch.setattr(app, "download_one",
                            lambda _page, doc, *_a, **_kw: pressed.append((doc.account, doc.date)))
        return app

    build.pressed = pressed
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def no_failure(tmp_path):
    return not list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_list_read_whole_is_noted_whole(make_app, tmp_path):
    app = make_app("--all", html=dialog._vendor_html())
    app.cmd_run("all")
    assert len(make_app.pressed) == 41
    assert listing.last(app) == listing.COMPLETE
    assert no_failure(tmp_path)


def test_a_list_with_a_history_whose_press_failed_is_not_noted_whole(make_app, tmp_path, capsys):
    """Run All takes what the list read, and stops at its end rather than
    finish, with a failure file. The listing is left as one that stopped,
    so a Resume after it stops too."""
    app = make_app("--all", html=press_will_not_take(dialog._vendor_html()))
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert sorted(make_app.pressed) == sorted(("", d) for d in MEMBER)
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Golden 1's statement list was not read whole" in out
    assert "Discovery read part of the statement list." in out
    assert FAILED_LINE in out
    assert "Not all of Golden 1's statement list was read, so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the statement list",
                                                  "some of the list could not be opened")
    assert report["extra"]["panels_passed_over"] == 1

    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_discover_of_a_list_passed_over_stops_once_it_has_saved_the_list(make_app):
    app = make_app("--discover", html=press_will_not_take(dialog._vendor_html()))
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert sorted(r["date"] for r in make_app().discovery.data.values()) == sorted(MEMBER)


def test_a_pilot_of_a_list_passed_over_stops_at_its_end(make_app):
    app = make_app("--pilot", html=press_will_not_take(dialog._vendor_html()))
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert sorted(make_app.pressed) == sorted(("", d) for d in MEMBER)
    assert listing.last(app) == listing.STOPPED


def test_a_pilot_with_nothing_to_take_from_a_list_passed_over_still_stops(make_app, capsys):
    """No history's press took, so nothing was read and there is nothing to
    pilot."""
    app = make_app("--pilot", html=press_will_not_take(dialog._vendor_html(), 0, 1))
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    out = said(capsys)
    assert "No documents in scope to pilot" in out
    assert "Not all of Golden 1's statement list was read, so this run stops here" in out
    assert make_app.pressed == []


@pytest.mark.parametrize("way", ["no list", "the list before", "a heading that opens nothing"])
def test_a_run_whose_history_a_working_page_can_leave_unshown_finishes(make_app, tmp_path, way):
    page, wait_ms, _how = WORKING[way]
    app = make_app("--all", html=page(dialog._vendor_html()), wait_ms=wait_ms)
    app.cmd_run("all")
    assert sorted(make_app.pressed) == sorted(("", d) for d in MEMBER)
    assert listing.last(app) == listing.COMPLETE
    assert no_failure(tmp_path)


def test_a_run_with_a_hidden_copy_of_a_statement_history_finishes(make_app, tmp_path):
    app = make_app("--all", html=a_hidden_copy(dialog._vendor_html()))
    app.cmd_run("all")
    assert len(make_app.pressed) == 41
    assert listing.last(app) == listing.COMPLETE
    assert no_failure(tmp_path)


# -- what an earlier run listed ---------------------------------------------------

def _listed_before(app, iso):
    """A statement of the second account an earlier run listed and never
    saved."""
    title = "Account Statement - %s" % site._human_date(iso)
    category, summary, confidence = doc_types.classify_document(title, app.rules)
    doc = app_mod.Document(title=title, category=category, summary=summary, date=iso,
                           confidence=confidence, account=SECOND)
    rec = doc.to_dict()
    rec["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, rec)
    return doc.key


def test_a_list_read_in_part_sets_nothing_aside(make_app):
    """The second account was not read, so a statement of its that an
    earlier run listed is kept for the run that reads it."""
    app = make_app("--discover", html=press_will_not_take(dialog._vendor_html()))
    key = _listed_before(app, "2025-08-21")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert make_app().discovery.get(key) is not None


def test_a_whole_list_still_sets_aside_what_it_no_longer_names(make_app):
    app = make_app("--discover", html=dialog._vendor_html())
    key = _listed_before(app, "2025-08-21")
    app.cmd_discover()
    assert make_app().discovery.get(key) is None
