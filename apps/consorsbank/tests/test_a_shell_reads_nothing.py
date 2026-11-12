"""This first build of Consorsbank reads nothing and presses nothing.

Discover, Pilot, Run All and Resume say it is not built yet, to Record
instead, and stop as a run that stopped, never as a clean run that found
nothing. Discover attaches to the browser as every app's does and asks it
for no tab, and Resume, with nothing listed, never reaches it. Login names a
sign-in page or a check and otherwise says it cannot tell, and never says a
session is signed in. Diagnose reads the page the person left open and
follows, presses and fetches nothing. The sign-in window says to record one
trip, in the panel's words under the panel.

No browser is started. The page is a stand-in that writes down everything
asked of it, and every address and title in it is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import consorsbank_docs as app_mod
import consorsbank_site as site
from paperpull_core import run_reporting
from paperpull_core.recorder import Recorder
from paperpull_core.run_reporting import PREFIX

# What a page can be asked that does something rather than read.
PRESSES = {"click", "dblclick", "tap", "check", "uncheck", "set_checked", "fill", "type",
           "press", "select_option", "dispatch_event", "set_input_files", "evaluate",
           "expose_binding", "route", "request"}


class Asked(list):
    def did(self, name):
        return [a for a in self if a[0] == name]


class Locator:
    def __init__(self, page, selector, n=0, text=""):
        self.page, self.selector, self.n, self.text = page, selector, n, text

    def __getattr__(self, name):
        if name in PRESSES:
            def press(*a, **k):
                self.page.asked.append((name, self.selector))
            return press
        raise AttributeError(name)

    def count(self):
        self.page.asked.append(("count", self.selector))
        return self.n

    def nth(self, i):
        return Locator(self.page, self.selector, 1, self.text)

    def inner_text(self, timeout=None):
        return self.text

    def all_inner_texts(self):
        return [self.text] if self.text else []

    def get_attribute(self, name):
        return ""


class Page:
    """A stand-in for a tab. `password` is how many password fields it
    shows, `hidden` how many it holds and never draws, as the sign-in window
    Consorsbank keeps in every page, and `text` what its body says."""

    def __init__(self, url, password=0, text="Overview", title="Banking", hidden=0):
        self.url, self.password, self.text, self._title = url, password, text, title
        self.hidden = hidden
        self.asked = Asked()

    def __getattr__(self, name):
        if name in PRESSES:
            def press(*a, **k):
                self.asked.append((name, a))
            return press
        raise AttributeError(name)

    def is_closed(self):
        return False

    def title(self):
        return self._title

    def locator(self, selector):
        if "password" in selector:
            # Playwright's :visible keeps the fields the page draws.
            return Locator(self, selector,
                           self.password + (0 if ":visible" in selector else self.hidden))
        if selector == "body":
            return Locator(self, selector, 1, self.text)
        return Locator(self, selector, 1, "Postbox")

    def get_by_role(self, role, **k):
        return Locator(self, role, 2, "PDF herunterladen" if role == "link" else "Kaufen")

    def goto(self, url, **k):
        self.asked.append(("goto", url))
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def on(self, *a):
        self.asked.append(("on", a))


def _config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "document_types": ["Statement", "Securities Document", "Tax Document"],
        "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5,
    }), encoding="utf-8")
    return cfg


@pytest.fixture
def no_browser(monkeypatch):
    """Discover attaches to the browser as every app's does, and asks it for
    no tab. The attach is counted, and asking for a tab fails the test."""
    attached = []

    def attach(self):
        attached.append(self)

    def no_tab(self):
        raise AssertionError("a tab was asked for")
    monkeypatch.setattr(app_mod.App, "browser", attach)
    monkeypatch.setattr(app_mod.App, "page", no_tab)
    return attached


@pytest.fixture
def in_a_terminal(monkeypatch):
    monkeypatch.delenv(run_reporting.MARK_ENV, raising=False)


@pytest.mark.parametrize("command", ["--discover", "--pilot", "--all", "--resume", "--dry-run"])
def test_a_run_says_it_is_not_built_and_stops(command, tmp_path, capsys, no_browser, in_a_terminal):
    cfg = _config(tmp_path)
    with pytest.raises(SystemExit) as stop:
        app_mod.main([command, "--config", str(cfg)])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    said = " ".join(out.split())
    if command == "--resume":
        # Resume reads no list, and none was ever read, which the core says
        # in its own words, pointing at Pilot.
        assert "have been listed yet" in said and "Pilot" in said
        assert not no_browser
    else:
        assert "Consorsbank is not built yet" in said
        assert "then run record," in said and "issue #178" in said
        assert len(no_browser) == 1
    result = [line for line in out.splitlines() if line.startswith(PREFIX)]
    assert result, out
    payload = result[-1][len(PREFIX):]
    # The panel's mark comes first when the panel started the run.
    got = json.loads(payload if payload.startswith("{") else payload.split(" ", 1)[1])
    assert got["stopped"] == 1 and got["new_files"] == 0, got
    out_dir = tmp_path / "out"
    assert not list(out_dir.rglob("*.pdf"))
    discovery = out_dir / "discovery.json"
    assert not discovery.exists() or json.loads(discovery.read_text(encoding="utf-8")) in ({}, [])


def test_under_the_panel_a_run_names_the_panels_record_button(tmp_path, capsys, no_browser,
                                                               monkeypatch):
    monkeypatch.setenv(run_reporting.MARK_ENV, "0" * 32)
    with pytest.raises(SystemExit):
        app_mod.main(["--pilot", "--config", str(_config(tmp_path))])
    said = " ".join(capsys.readouterr().out.split())
    assert "then press Record steps (More, then Get help), and click" in said
    assert "run record" not in said


@pytest.mark.parametrize("command", ["--discover", "--pilot"])
def test_a_listing_is_never_noted_whole(command, tmp_path, capsys, no_browser):
    cfg = _config(tmp_path)
    with pytest.raises(SystemExit):
        app_mod.main([command, "--config", str(cfg)])
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note["complete"] is False


def test_with_no_browser_open_discover_says_to_sign_in_first(tmp_path, capsys, monkeypatch,
                                                            in_a_terminal):
    """The attach fails the way it does at home with no browser on the port,
    and the run stops there, before the list is asked for."""
    class NoBrowser:
        class chromium:
            @staticmethod
            def connect_over_cdp(url):
                raise RuntimeError("connect ECONNREFUSED")

        def stop(self):
            pass

    class Starter:
        def start(self):
            return NoBrowser()
    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: Starter())
    monkeypatch.setattr(site, "collect_documents",
                        lambda *a, **k: pytest.fail("the list was asked for"))
    with pytest.raises(SystemExit) as stop:
        app_mod.main(["--discover", "--config", str(_config(tmp_path))])
    assert stop.value.code == run_reporting.NOT_SIGNED_IN
    assert "Run login.bat first" in capsys.readouterr().err
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note["complete"] is False


def test_the_site_refuses_a_list_and_a_document():
    page = Page("https://www.consorsbank.de/a")
    with pytest.raises(site.NotBuilt):
        site.collect_documents(page)
    with pytest.raises(site.NotBuilt):
        site.download_document(page, "Kontoauszug", "2026-03-31", Path("x.pdf"))
    assert not page.asked


def test_a_document_already_listed_stops_the_run_and_nothing_is_pressed(tmp_path, capsys, monkeypatch):
    cfg = _config(tmp_path)
    args = app_mod.build_parser().parse_args(["--pilot", "--config", str(cfg)])
    app = app_mod.App(args)
    page = Page("https://www.consorsbank.de/a")
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    doc = app_mod.Document(title="Finanzreport", category="Statement", summary="Finanzreport",
                           date="2026-03-31", account="Girokonto 1111")
    with pytest.raises(SystemExit) as stop:
        app.process([doc])
    assert stop.value.code == 0
    assert "Consorsbank is not built yet" in " ".join(capsys.readouterr().out.split())
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] == "goto"], page.asked
    assert not list((tmp_path / "out").rglob("*.pdf"))


def _login(tmp_path, monkeypatch, page, own):
    cfg = _config(tmp_path)
    args = app_mod.build_parser().parse_args(["--login", "--config", str(cfg)])
    app = app_mod.App(args)
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    monkeypatch.setattr(app_mod.tabs, "is_own", lambda tab: own)
    app.cmd_login()


@pytest.mark.parametrize("page", [
    Page("https://www.consorsbank.de/a"),
    Page("https://www.consorsbank.de/home", text="Willkommen"),
])
def test_login_never_says_a_session_is_signed_in(page, tmp_path, capsys, monkeypatch):
    _login(tmp_path, monkeypatch, page, own=False)
    said = " ".join(capsys.readouterr().out.split()).lower()
    assert "cannot tell whether you are signed in" in said
    assert "success" not in said and "you are signed in" not in said.replace(
        "whether you are signed in", "")
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] == "goto"], page.asked


@pytest.mark.parametrize("page", [
    Page("https://www.consorsbank.de/a", password=1),
    Page("https://www.consorsbank.de/home?showEVLoginForm=true"),
])
def test_login_names_a_sign_in_page(page, tmp_path, capsys, monkeypatch):
    _login(tmp_path, monkeypatch, page, own=False)
    assert "shows a sign-in page" in " ".join(capsys.readouterr().out.split())
    assert not page.asked.did("goto")


def test_login_opens_the_sign_in_page_only_in_a_tab_it_opened(tmp_path, capsys, monkeypatch):
    page = Page("about:blank")
    _login(tmp_path, monkeypatch, page, own=True)
    assert page.asked.did("goto") == [
        ("goto", "https://www.consorsbank.de/home?showEVLoginForm=true")]


def test_login_never_moves_a_tab_of_the_persons(tmp_path, capsys, monkeypatch):
    page = Page("https://www.elsewhere.test/")
    _login(tmp_path, monkeypatch, page, own=False)
    assert not page.asked.did("goto")
    assert "no tab is on consorsbank.de" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("text", ["Bitte TAN eingeben",
                                  "Enter the code we sent you"])
def test_login_names_a_check(text, tmp_path, capsys, monkeypatch):
    page = Page("https://www.consorsbank.de/a", text=text)
    _login(tmp_path, monkeypatch, page, own=False)
    assert "Security challenge detected" in capsys.readouterr().out


def test_an_ordinary_page_that_names_security_is_no_check():
    """A settings menu may name the second factor. Only a prompt counts."""
    page = Page("https://www.consorsbank.de/a",
                text="Einstellungen Sicherheit Zwei-Faktor-Authentifizierung Postbox")
    assert site.detect_security_challenge(page) is None


def test_a_password_field_or_an_unreadable_page_is_signed_out():
    assert site.looks_signed_out(Page("https://www.consorsbank.de/a", password=1))
    assert not site.looks_signed_out(Page("https://www.consorsbank.de/a"))

    class Broken(Page):
        def locator(self, selector):
            raise RuntimeError("gone")
    assert site.looks_signed_out(Broken("https://www.consorsbank.de/a"))
    assert site.looks_signed_out(Page(""))

    class Gone(Page):
        @property
        def url(self):
            raise RuntimeError("Target page, context or browser has been closed")

        @url.setter
        def url(self, value):
            pass
    assert site.looks_signed_out(Gone(""))


def test_the_sign_in_address_is_signed_out_and_the_bank_is_not():
    """The sign-in address the request names, which draws the form over
    the home page, in any case. The home page without it and a page of
    the bank's own are left alone."""
    assert site.looks_signed_out(Page("https://www.consorsbank.de/home?showEVLoginForm=true"))
    assert site.looks_signed_out(Page("https://www.consorsbank.de/home?a=1&showevloginform=TRUE"))
    assert not site.looks_signed_out(Page("https://www.consorsbank.de/home"))
    assert not site.looks_signed_out(Page("https://www.consorsbank.de/web/a"))


def test_record_will_not_start_on_the_sign_in_address_before_its_form_is_drawn():
    """The core's recorder asks this app's checks, and a form not drawn yet
    has no password field for its own backstop to see."""
    rec = Recorder(Page("https://www.consorsbank.de/home?showEVLoginForm=true"),
                   is_safe_url=site.is_safe_url, looks_signed_out=site.looks_signed_out,
                   is_safe_control=site.is_safe_control, provider="Consorsbank")
    assert "not signed in yet" in rec.refusal()
    signed_in = Recorder(Page("https://www.consorsbank.de/web/a"),
                         is_safe_url=site.is_safe_url, looks_signed_out=site.looks_signed_out,
                         is_safe_control=site.is_safe_control, provider="Consorsbank")
    assert signed_in.refusal() is None


def test_the_sign_in_window_every_page_keeps_is_no_sign_in_page():
    """Consorsbank keeps its sign-in window in every page, the bank's own
    included, and draws it only when asked. A tester signed in on the bank
    was told to sign in on each page, and Record never started (#178)."""
    bank = Page("https://www.consorsbank.de/web/a", hidden=1)
    assert not site.looks_signed_out(bank)
    rec = Recorder(bank, is_safe_url=site.is_safe_url, looks_signed_out=site.looks_signed_out,
                   is_safe_control=site.is_safe_control, provider="Consorsbank",
                   password_field=site.PASSWORD_FIELD)
    assert rec.refusal() is None
    # The sign-in address is one whatever the page draws, and a field the
    # page shows still is.
    assert site.looks_signed_out(Page("https://www.consorsbank.de/home?showEVLoginForm=true",
                                      hidden=1))
    assert site.looks_signed_out(Page("https://www.consorsbank.de/web/a", password=1, hidden=1))


def _app(tmp_path, *argv):
    args = app_mod.build_parser().parse_args([*argv, "--config", str(_config(tmp_path))])
    return app_mod.App(args)


def test_the_sign_in_window_opens_the_request_address_and_says_to_record(tmp_path, capsys,
                                                                         monkeypatch):
    opened = []

    def open_signin_browser(profile, port, url, prefer_real=False, mode="auto"):
        opened.append((port, url, prefer_real))
        return "Google Chrome"
    monkeypatch.setattr(app_mod.browser_launcher, "open_signin_browser", open_signin_browser)
    monkeypatch.setenv(run_reporting.MARK_ENV, "0" * 32)
    app = _app(tmp_path, "--open-browser")
    app.config["cdp_url"] = "http://127.0.0.1:9310"
    app.cmd_open_browser()
    assert opened == [("9310", "https://www.consorsbank.de/home?showEVLoginForm=true", True)]
    said = " ".join(capsys.readouterr().out.split())
    assert "press Record steps (More, then Get help), and click your way to one document" in said
    assert "pilot" not in said.lower() and "newest few" not in said


def test_a_sign_in_window_that_never_opened_says_so_to_the_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod.browser_launcher, "open_signin_browser",
                        lambda *a, **k: None)
    with pytest.raises(SystemExit) as stop:
        _app(tmp_path, "--open-browser").cmd_open_browser()
    assert stop.value.code == run_reporting.NOTHING_OPENED


def test_a_recording_that_saved_nothing_says_so_to_the_panel(tmp_path, monkeypatch):
    import paperpull_core.recorder as recorder
    monkeypatch.setattr(recorder, "record_session", lambda *a, **k: None)
    app = _app(tmp_path, "--record")
    monkeypatch.setattr(app_mod.App, "page", lambda self: Page("https://www.consorsbank.de/a"))
    with pytest.raises(SystemExit) as stop:
        app.cmd_record()
    assert stop.value.code == run_reporting.NOTHING_RECORDED


def test_diagnose_never_writes_the_account_holders_name(tmp_path, capsys, monkeypatch):
    """"Bill" is an ordinary word on the fixed list, so only the owner's
    name being private keeps it out."""
    cfg = _config(tmp_path)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["owner"] = "Bill Grant"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--diagnose", "--config", str(cfg)])
    app = app_mod.App(args)
    page = Page("https://www.consorsbank.de/a", title="Bill Grant - Banking")
    monkeypatch.setattr(app_mod.App, "page", lambda self: page)
    monkeypatch.setattr(site, "survey", lambda p, dwell_ms=0: {"pages": [site._page_summary(p)]})
    app.cmd_diagnose()
    written = (tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8")
    assert "Bill" not in written and "Grant" not in written
    assert json.loads(written)["on_site"] is True
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] == "goto"], page.asked


def test_the_survey_reads_the_open_page_and_does_nothing_on_it():
    page = Page("https://www.consorsbank.de/a/b?accountId=12345#top", hidden=1)
    report = site.survey(page, dwell_ms=0)
    # The field in the page and the one it shows apart, which a tester's
    # survey could not tell (#178).
    assert report["pages"][0]["password_fields"] == 1
    assert report["pages"][0]["visible_password_fields"] == 0
    assert not [a for a in page.asked if a[0] in PRESSES or a[0] in ("goto", "on")], page.asked
    summary = report["pages"][0]
    assert summary["on_site"] is True
    assert "account" not in summary["url"] and "12345" not in summary["url"]
    # The fragment too, which the redactor leaves and a page may route by.
    assert summary["url"] == "https://www.consorsbank.de/a/b"
    assert {c["safe"] for c in summary["controls"]} == {True, False}
    assert report["mapped"] is False


def test_the_survey_reads_nothing_off_a_page_of_another_site():
    page = Page("https://www.elsewhere.test/private", title="Someone's page")
    summary = site.survey(page, dwell_ms=0)["pages"][0]
    assert summary["on_site"] is False
    assert summary["title"] == "" and "controls" not in summary
    assert "elsewhere" not in summary["url"]
