"""The home page's "may have something new" leaves out a gap a whole run
could not fill, and keeps an account that is due (#149).

Two accounts each stayed in the summary after every Get new for all, since
their only flag was a gap years back that the provider no longer offers.
These run the page's own script in Playwright's own headless Chromium,
against the real panel served on a free local port. Every setting and
folder is under a temp folder, nothing is run, and no browser of the
person's is started.
"""
import json
import socket
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")


def _records(newest_days_ago, hole=None, count=8, every=30):
    out = {}
    newest = date.today() - timedelta(days=newest_days_ago)
    for i in range(count):
        if i == hole:
            continue
        d = (newest - timedelta(days=every * i)).isoformat()
        out["doc-%d" % i] = {"downloaded_ok": True, "state": "Completed", "date": d,
                             "pdf_filename": "Statements/%s Statement.pdf" % d, "updated_at": d}
    return out


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def base():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


def _install(apps, name, provider, records):
    folder = apps / name
    folder.mkdir(parents=True)
    script = name.split()[0].lower() + "_docs.py"
    (folder / script).write_text("print('not run')\n", encoding="utf-8")
    (folder / "storage.py").write_text(
        'SPEC = AppSpec(\n    provider="%s",\n    kind="DOCUMENT",\n)\n' % provider, encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    (folder / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    return folder


def _clean_all(gaps_left):
    return {"action": "all", "account": "primary", "started": "2026-11-06T16:00:00",
            "ended": "2026-11-06T16:01:00", "exit_code": 0, "closed": False,
            "result": {"manual_review": 0, "failed": 0, "validation_failures": 0,
                       "new_files": 0, "stopped": 0},
            "scope": [], "redownload": False, "saved": [], "gaps_left": gaps_left}


@pytest.fixture()
def apps(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    root = tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", str(root))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    # Current by its newest document, with a gap 90 days back in the middle.
    gapped = _install(root, "Gapbank Statements", "Gapbank", _records(5, hole=3))
    # Due: its newest document is past its usual monthly interval.
    _install(root, "Duebank Statements", "Duebank", _records(45))
    return root, gapped


def _summary(tab):
    tab.wait_for_function("() => ROWS && ROWS.length === 2")
    card = tab.locator(".summary")
    return card.inner_text() if card.count() else ""


def test_a_gap_a_whole_run_left_drops_out_and_a_due_account_stays(browser, base, apps):
    root, gapped = apps
    keys = app_module._gaps_left(gapped)
    assert keys, "the made-up history has a gap"
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        before = _summary(tab)
        assert "Gapbank" in before and "Duebank" in before and "2 accounts" in before

        (gapped / app_module.RUN_LOG).write_text(json.dumps([_clean_all(keys)]), encoding="utf-8")
        tab.reload()
        after = _summary(tab)
        assert "Duebank" in after and "Gapbank" not in after, after
        assert "1 account " in after or after.startswith("1 account"), after
        # The row itself still says Possible gap and offers to look.
        tab.wait_for_selector("text=Possible gap")
    finally:
        context.close()


def test_a_gap_the_run_did_not_see_still_counts(browser, base, apps):
    root, gapped = apps
    (gapped / app_module.RUN_LOG).write_text(json.dumps([_clean_all([])]), encoding="utf-8")
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        assert "Gapbank" in _summary(tab)
    finally:
        context.close()
