"""The name on an account can be set, for anyone on it, after the welcome.

The welcome asked once, for every provider at the same time, and the only
other way to change it was to edit a settings file. The endpoint is called
directly, the way the rest of this suite does, and the dialog is run by the
page's own script in Playwright's own headless Chromium. Every folder is a
throwaway one under tmp_path, and every name is invented.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import server_mode  # noqa: E402
pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

APP = "Chase Statements"


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def chase(tmp_path, monkeypatch):
    d = tmp_path / "PaperPull" / APP
    d.mkdir(parents=True)
    for name in ("config.json", "config.spouse.json"):
        (d / name).write_text(json.dumps({"output_dir": ".", "owner": "Pat Example", "keep": 1}), encoding="utf-8")
    metas = {APP: {"name": APP, "dir": str(d), "accounts": app_module._accounts(d)}}
    monkeypatch.setattr(app_module, "discover_apps", lambda: metas)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    app_module._RUNS.clear()
    yield d
    app_module._RUNS.clear()


def save(**body):
    return asyncio.run(app_module.api_account_owner(_Req(body)))


def config(d, name="config.json"):
    return json.loads((d / name).read_text(encoding="utf-8"))


def refused(status, **body):
    with pytest.raises(HTTPException) as e:
        save(**body)
    assert e.value.status_code == status
    return e.value.detail


def test_the_first_persons_name_is_written_in_their_own_config(chase):
    got = save(app=APP, account="primary", owner="  Sam Example ")
    assert got == {"app": APP, "account": "primary", "owner": "Sam Example", "written": True}
    assert config(chase)["owner"] == "Sam Example" and config(chase)["keep"] == 1
    assert config(chase, "config.spouse.json")["owner"] == "Pat Example"


def test_another_persons_name_is_written_in_their_config_alone(chase):
    save(app=APP, account="spouse", owner="Alex Example")
    assert config(chase, "config.spouse.json")["owner"] == "Alex Example"
    assert config(chase)["owner"] == "Pat Example"


def test_a_copy_is_kept_in_backups_first(chase):
    save(app=APP, account="primary", owner="Sam Example")
    kept = list((chase / "Backups").glob("owner-*/config.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text(encoding="utf-8"))["owner"] == "Pat Example"


def test_the_name_stops_at_eighty_characters(chase):
    save(app=APP, account="primary", owner="n" * 200)
    assert config(chase)["owner"] == "n" * 80


def test_a_blank_name_clears_it(chase):
    assert save(app=APP, account="primary", owner="   ")["owner"] == ""
    assert config(chase)["owner"] == ""


def test_the_same_name_writes_nothing(chase):
    assert save(app=APP, account="primary", owner="Pat Example")["written"] is False
    assert not (chase / "Backups").exists()


def test_refused_while_that_account_runs(chase):
    app_module._RUNS[(APP, "primary")] = {"action": "all"}
    assert "finish first" in refused(409, app=APP, account="primary", owner="Sam")
    assert config(chase)["owner"] == "Pat Example"
    save(app=APP, account="spouse", owner="Alex"), "another person's run is another account"


def test_a_run_that_started_since_it_was_asked_stops_the_write(chase, monkeypatch):
    real = app_module._write_config

    def run_starts_now(*a, **kw):
        app_module._RUNS[(APP, "primary")] = {"action": "all"}
        return real(*a, **kw)
    monkeypatch.setattr(app_module, "_write_config", run_starts_now)
    assert "finish first" in refused(409, app=APP, account="primary", owner="Sam")
    assert config(chase)["owner"] == "Pat Example"


def test_an_account_the_panel_did_not_find_is_refused(chase):
    refused(404, app=APP, account="../other", owner="Sam")
    refused(404, app="Nobody", account="primary", owner="Sam")


def test_a_missing_config_is_said(chase):
    (chase / "config.json").unlink()
    assert "Open sign-in window" in refused(404, app=APP, account="primary", owner="Sam")


def test_a_config_that_is_not_an_object_is_left_alone(chase):
    (chase / "config.json").write_text("[1]", encoding="utf-8")
    refused(409, app=APP, account="primary", owner="Sam")
    assert (chase / "config.json").read_text(encoding="utf-8") == "[1]"


def test_a_link_in_the_shared_folder_is_never_written_through(chase, monkeypatch):
    monkeypatch.setattr(server_mode, "own_file", lambda _p: False)
    assert "link in the shared folder" in refused(409, app=APP, account="primary", owner="Sam")
    assert config(chase)["owner"] == "Pat Example"


def test_the_sample_is_refused():
    route = next(r for r in app_module.app.routes if getattr(r, "path", "") == "/api/account/owner")
    assert app_module._not_in_sample in [d.call for d in route.dependant.dependencies]


# -- the dialog ----------------------------------------------------------------------

@pytest.fixture()
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        tab = chromium.new_page()
        tab.asked = []

        def answer(route):
            if route.request.url == "http://panel.test/":
                route.fulfill(status=200, content_type="text/html", body=html)
            elif route.request.url.endswith("/api/account/owner"):
                body = route.request.post_data_json
                tab.asked.append(body)
                if body["owner"] == "Busy":
                    route.fulfill(status=409, content_type="application/json",
                                  body=json.dumps({"detail": "Wait for the run on Chase to finish first."}))
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(
                        {"app": body["app"], "account": body["account"], "owner": body["owner"], "written": True}))
            elif route.request.url.endswith("/api/accounts"):
                route.fulfill(status=200, content_type="application/json", body='{"accounts": []}')
            else:
                route.abort()
        tab.route("**/*", answer)
        tab.goto("http://panel.test/")
        yield tab
        chromium.close()


ROW = "{app: 'Chase Statements', account: 'primary', provider: 'Chase', owner: 'Pat Example', kind: 'statements'}"


def test_the_dialog_opens_on_the_name_saved_now_and_saves_for_that_account(page):
    page.evaluate("openOwner(%s)" % ROW)
    assert page.is_visible("#dlg-owner") and page.input_value("#on-owner") == "Pat Example"
    page.fill("#on-owner", "Sam Example")
    page.click("[data-do=on-go]")
    page.wait_for_function("() => !$('dlg-owner').open")
    assert page.asked == [{"app": APP, "account": "primary", "owner": "Sam Example"}]
    assert page.inner_text("#noticetext") == "The name on Chase is now Sam Example."


def test_a_refusal_is_said_in_the_dialog(page):
    page.evaluate("openOwner(%s)" % ROW)
    page.fill("#on-owner", "Busy")
    page.click("[data-do=on-go]")
    page.wait_for_selector("#on-err:not([hidden])")
    assert "finish first" in page.inner_text("#on-err")
    assert page.evaluate("$('dlg-owner').open")


def test_the_field_stops_at_eighty(page):
    assert page.get_attribute("#on-owner", "maxlength") == "80"
