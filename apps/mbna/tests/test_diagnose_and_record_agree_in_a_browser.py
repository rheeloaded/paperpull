"""Diagnose and Record agree on an MBNA page that holds a password field out of sight.

This app counts every password field in the page as a sign-in page, a hidden
one too. That is the rule for every app that
core/tests/test_every_app_counts_every_password_field.py does not name with
a measured reason, since a field kept out of sight may be the next step of a
sign-in, and nothing has shown a signed-in MBNA page holding one. So a page
holding a hidden password field is a sign-in page to both commands that read
the page. Diagnose writes signed_out and reads as a report that read
nothing, and Record will not start, for the same reason and in the same
words as on a drawn field. A page with no password field is read and
recorded by both.

The fields are hidden in the ways Playwright's :visible leaves out, and each
case measures that in the page, so a field the browser draws after all
cannot pass for a hidden one. The page is on the bank's own address and not
its sign-in route, so nothing else makes it a sign-in page.

A simulated page in Playwright's own Chromium, never the Edge or Chrome on
this computer, with every name resolved to nowhere so nothing reaches the
bank. The page is invented and holds nothing of anyone's.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import mbna_docs as app_mod
import mbna_site as site
from paperpull_core import recorder, words
from paperpull_core.run_reporting import NOTHING_RECORDED

pw_api = pytest.importorskip("playwright.sync_api")

PROVIDER = "MBNA"
URL = "https://service.mbna.ca/waw/mbna/accounts/summary"

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

PAGE = """<!doctype html>
<title>Accounts</title>
<h1>Accounts</h1>
<a href="/documents">Statements and documents</a>
%s
"""

# A component whose shadow root gives its light DOM no slot, the shape
# Consorsbank keeps its sign-in window in (#178).
_UNSLOTTED = """<sign-in-window><form><input type="password" name="pin"></form></sign-in-window>
<script>
customElements.define('sign-in-window', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<div></div>'; }
});
</script>"""

HIDDEN = {
    "display none": '<input type="password" name="pin" style="display:none">',
    "in a parent not displayed": '<div style="display:none"><input type="password" name="pin"></div>',
    "visibility hidden": '<input type="password" name="pin" style="visibility:hidden">',
    "the hidden attribute": '<input type="password" name="pin" hidden>',
    "in a dialog not open": '<dialog><form><input type="password" name="pin"></form></dialog>',
    "in a component that never slots it": _UNSLOTTED,
    "with no size": '<input type="password" name="pin" style="width:0;height:0;padding:0;border:0">',
}

DRAWN = {
    "drawn": '<input type="password" name="pin">',
    "drawn after a hidden one": ('<input type="password" name="a" style="display:none">'
                                 '<input type="password" name="b">'),
}

NONE = {
    "no password field": "",
    "only fields that are not password fields": (
        '<input type="text" name="password"><template><input type="password"></template>'),
}


def _config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "document_types": ["Statement"], "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5,
    }), encoding="utf-8")
    return cfg


def _app(tmp_path, flag):
    return app_mod.App(app_mod.build_parser().parse_args([flag, "--config", str(_config(tmp_path))]))


@pytest.fixture(scope="module")
def browser():
    with pw_api.sync_playwright() as driver:
        try:
            launched = driver.chromium.launch(headless=True, args=ARGS)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def open_page(browser):
    contexts = []

    def open_(field):
        context = browser.new_context()
        contexts.append(context)
        context.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body=PAGE % field))
        page = context.new_page()
        page.goto(URL)
        # On the bank, and not its sign-in address, so the field is the one
        # thing that could make it a sign-in page.
        assert page.url == URL and site.is_safe_url(page.url)
        assert not any(m in page.url.lower() for m in site.LOGIN_URL_MARKERS)
        return page

    yield open_
    for context in contexts:
        context.close()


def _fields(page):
    """(every password field, the drawn ones), measured in the page."""
    return (page.locator(recorder.PASSWORD_FIELD).count(),
            page.locator(recorder.DRAWN_PASSWORD_FIELD).count())


def _diagnose(page, tmp_path, monkeypatch):
    app = _app(tmp_path, "--diagnose")
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    survey = site.survey
    monkeypatch.setattr(site, "survey", lambda p, dwell_ms=2000: survey(p, dwell_ms=0))
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert "error" not in info, info
    assert info["on_site"] is True
    return info, words.read_nothing_in(app.paths.diagnostics)


def _record(page, tmp_path, monkeypatch, capsys):
    """What Record said, and whether it wrote a recording. Started, it
    stops at once with nothing clicked."""
    app = _app(tmp_path, "--record")
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(recorder, "_wait_for_stop", lambda *a, **k: None)
    capsys.readouterr()
    with pytest.raises(SystemExit) as stopped:
        app.cmd_record()
    # Refused or started with nothing clicked, the same code, so the words
    # and the file are what tell the two apart.
    assert stopped.value.code == NOTHING_RECORDED
    return capsys.readouterr().out, (app.paths.diagnostics / "recording.json").exists()


def _signed_out_to_both(page, tmp_path, monkeypatch, capsys):
    info, read_nothing = _diagnose(page, tmp_path, monkeypatch)
    said, recorded = _record(page, tmp_path, monkeypatch, capsys)
    refused = "Not recording, because" in said
    assert info["signed_out"] is refused, (info["signed_out"], said)
    return info, read_nothing, said, recorded


@pytest.mark.parametrize("how", sorted(HIDDEN))
def test_a_hidden_password_field_is_a_sign_in_page_to_diagnose_and_record(
        how, open_page, tmp_path, monkeypatch, capsys):
    page = open_page(HIDDEN[how])
    assert _fields(page) == (1, 0), how
    info, read_nothing, said, recorded = _signed_out_to_both(page, tmp_path, monkeypatch, capsys)
    assert info["signed_out"] is True
    assert read_nothing
    # The app's own check refused it, not only the recorder's count of
    # every field behind it.
    assert "Not recording, because you are not signed in yet" in said
    assert not recorded


@pytest.mark.parametrize("how", sorted(DRAWN))
def test_a_drawn_password_field_is_a_sign_in_page_to_diagnose_and_record(
        how, open_page, tmp_path, monkeypatch, capsys):
    page = open_page(DRAWN[how])
    assert _fields(page)[1] == 1, how
    info, read_nothing, said, recorded = _signed_out_to_both(page, tmp_path, monkeypatch, capsys)
    assert info["signed_out"] is True
    assert read_nothing
    assert "Not recording, because you are not signed in yet" in said
    assert not recorded


@pytest.mark.parametrize("how", sorted(NONE))
def test_a_page_with_no_password_field_is_read_and_recorded(
        how, open_page, tmp_path, monkeypatch, capsys):
    page = open_page(NONE[how])
    assert _fields(page) == (0, 0), how
    info, read_nothing, said, recorded = _signed_out_to_both(page, tmp_path, monkeypatch, capsys)
    assert info["signed_out"] is False
    assert not read_nothing
    assert "Not recording" not in said
    assert "RECORDING - what this does" in said
    assert recorded


@pytest.mark.parametrize("how", sorted(HIDDEN))
def test_the_recorders_own_count_takes_a_hidden_field_too(how, open_page):
    """The backstop behind the app's check, on its own, so a check that
    lost its count of hidden fields could not hide behind it."""
    field = getattr(site, "PASSWORD_FIELD", recorder.PASSWORD_FIELD)
    assert field == recorder.PASSWORD_FIELD
    page = open_page(HIDDEN[how])
    rec = recorder.Recorder(page, is_safe_url=site.is_safe_url, looks_signed_out=None,
                            is_safe_control=site.is_safe_control, provider=PROVIDER,
                            password_field=field)
    assert "there is a password field on this page" in (rec.refusal() or "")
