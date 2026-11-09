"""The Accounts list reads at a glance, run by the page itself.

One filled button on the page, for the step that matters, rows that have
never run folded away once something has, a search box once the list is
long, and the More menu giving focus back to its button when Escape closes
it. These run the page's own script, in Playwright's own headless Chromium,
against the real panel served on a free local port, over an apps root of
ten small apps under a temp folder. No browser of the person's is started
and no app runs.
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")

APP = "print('never run in these tests')\n"
NAMES = ["Shop Docs %d" % n for n in range(1, 11)]


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


def _apps(tmp_path, monkeypatch, stopped: bool):
    """Ten apps, none ever run, or the first stopped partway when asked."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    for name in NAMES:
        folder = tmp_path / "apps" / name
        folder.mkdir(parents=True)
        (folder / "shop_docs.py").write_text(APP, encoding="utf-8")
    if stopped:
        folder = tmp_path / "apps" / NAMES[0]
        root = app_module._account_root({"dir": str(folder)}, "primary")
        root.mkdir(parents=True, exist_ok=True)
        (root / app_module.RUN_LOG).write_text(json.dumps([
            {"action": "all", "exit_code": 0, "ended": "2026-10-28T09:00:00",
             "result": {"stopped": 1}}]), encoding="utf-8")


def _open(browser, base):
    context = browser.new_context()
    tab = context.new_page()
    tab.goto(base + "/#/")
    tab.wait_for_selector("#view-home .acct")
    return context, tab


@pytest.fixture()
def one_stopped(browser, base, tmp_path, monkeypatch):
    _apps(tmp_path, monkeypatch, stopped=True)
    context, tab = _open(browser, base)
    yield tab
    context.close()


@pytest.fixture()
def all_new(browser, base, tmp_path, monkeypatch):
    _apps(tmp_path, monkeypatch, stopped=False)
    context, tab = _open(browser, base)
    yield tab
    context.close()


def shown(tab) -> int:
    return tab.evaluate("[...document.querySelectorAll('#view-home .acct')]"
                        ".filter(a => a.checkVisibility()).length")


def test_rows_never_run_fold_away_once_one_has_run(one_stopped):
    tab = one_stopped
    more = tab.locator("#view-home details.group-more")
    assert more.count() == 1
    assert more.evaluate("d => d.open") is False
    assert "Not started (9)" in more.locator("summary").inner_text()
    assert shown(tab) == 1
    more.locator("summary").click()
    assert shown(tab) == 10


def test_a_fresh_list_shows_every_row_never_run(all_new):
    assert all_new.locator("#view-home details.group-more").count() == 0
    assert shown(all_new) == 10


def test_a_row_never_run_does_not_repeat_the_same_sentence(all_new):
    assert all_new.locator("#view-home .acct .say").count() == 0
    assert all_new.locator("#view-home .acct .sub").count() == 10


def test_only_the_summary_carries_a_filled_button(one_stopped):
    tab = one_stopped
    assert tab.locator("#view-home .acct .btn-p").count() == 0
    assert tab.locator("#view-home .acct .btn-s.starts").count() >= 1
    assert tab.locator("#view-home .summary .btn-p").count() == 1


def test_search_narrows_the_list_and_says_when_nothing_matches(one_stopped):
    tab = one_stopped
    tab.locator("#view-home details.group-more summary").click()
    find = tab.locator("#h-find")
    find.fill("docs 7")
    assert shown(tab) == 1
    assert tab.locator("#view-home .acct:visible .who a").inner_text() == "Shop Docs 7"
    find.fill("nothing like this")
    assert shown(tab) == 0
    assert tab.locator("#h-nomatch").is_visible()
    tab.locator("#h-nomatch [data-do=find-clear]").click()
    assert find.input_value() == ""
    assert shown(tab) == 10


def test_a_search_opens_the_folded_rows_it_finds(one_stopped):
    tab = one_stopped
    tab.locator("#h-find").fill("docs 4")
    assert shown(tab) == 1


def test_a_short_list_has_no_search(browser, base, tmp_path, monkeypatch):
    _apps(tmp_path, monkeypatch, stopped=False)
    for name in NAMES[3:]:
        for f in (tmp_path / "apps" / name).iterdir():
            f.unlink()
        (tmp_path / "apps" / name).rmdir()
    context, tab = _open(browser, base)
    try:
        assert not tab.locator("#h-find").is_visible()
    finally:
        context.close()


def test_escape_gives_focus_back_to_the_menu_button(one_stopped):
    tab = one_stopped
    button = tab.locator("#view-home .acct [data-do=menu]").first
    button.focus()
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".menu")
    assert tab.evaluate("document.activeElement.classList.contains('mi')")
    tab.keyboard.press("Escape")
    assert tab.locator(".menu").count() == 0
    assert tab.evaluate("document.activeElement.dataset.do") == "menu"
    assert button.get_attribute("aria-expanded") == "false"


def test_overdue_reads_as_a_new_one_likely_not_a_failure(one_stopped):
    cls = one_stopped.evaluate(
        "present(Object.assign({}, ROWS[0], {state: 'overdue', age_days: 60, cadence_days: 30,"
        " running: null, needs_setup: false, runnable: true})).chip.cls")
    assert cls == "due"


def test_a_first_run_going_now_is_never_folded_away(browser, base, tmp_path, monkeypatch):
    """A provider never run before whose first run is going, here or in
    another tab, stays in sight with its progress, while the rest fold."""
    _apps(tmp_path, monkeypatch, stopped=True)
    app_module._RUNS[(NAMES[1], "primary")] = {"action": "all", "started": "2026-11-07T10:00:00"}
    context, tab = _open(browser, base)
    try:
        row = tab.locator("#view-home .acct[data-key^='%s']" % NAMES[1])
        assert row.evaluate("a => a.checkVisibility()")
        assert row.evaluate("a => !a.closest('#h-more')")
        assert "Running in another tab" in row.inner_text()
        assert "Not started (8)" in tab.locator("#h-more summary").inner_text()
    finally:
        app_module._RUNS.clear()
        context.close()


def test_a_row_that_needs_setting_up_is_never_folded_away(browser, base, tmp_path, monkeypatch):
    """A provider never run that cannot run until the person runs setup-all
    is what needs them, so it stands in sight with what to do, while the
    rest fold."""
    _apps(tmp_path, monkeypatch, stopped=True)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: False)
    monkeypatch.setattr(app_module, "_runs_apps", lambda: False)
    monkeypatch.setattr(app_module, "_venv_python",
                        lambda d: None if Path(d).name == NAMES[2] else Path(d) / ".venv" / "bin" / "python")
    context, tab = _open(browser, base)
    try:
        row = tab.locator("#view-home .acct[data-key^='%s']" % NAMES[2])
        assert row.evaluate("a => a.checkVisibility()")
        assert row.evaluate("a => !a.closest('#h-more')")
        assert "Needs setup" in row.inner_text() and "Run setup-all" in row.inner_text()
        assert "Not started (8)" in tab.locator("#h-more summary").inner_text()
    finally:
        context.close()


def test_a_first_run_started_in_this_tab_is_never_folded_away(one_stopped):
    """The rows were read before the run started here, so none of them says
    it is running. The run's own row still stands in sight with its
    progress."""
    tab = one_stopped
    got = tab.evaluate("""name => {
        Object.assign(RUN, {state: 'running', app: name, account: 'primary', provider: name, action: 'all',
                            lines: [], found: null, total: 0, step: 0, connected: false});
        renderHome();
        const row = document.querySelector('#view-home .acct[data-key^="' + name + '"]');
        const out = {shown: row.checkVisibility(), folded: Boolean(row.closest('#h-more')), text: row.innerText,
                     more: $('h-more').querySelector('summary').innerText};
        RUN.state = 'idle';
        renderHome();
        return out;
    }""", NAMES[3])
    assert got["shown"] and not got["folded"]
    assert "Running now" in got["text"]
    assert "Not started (8)" in got["more"]


def test_settings_names_each_folder_of_its_own_as_accounts_does(one_stopped):
    """The folders Use it for every provider would replace are named by
    provider and person, as Accounts and the picker beside them name them,
    never by the provider's folder."""
    said = one_stopped.evaluate("""async () => {
        ROWS = [{app: 'Bank Statements', account: 'second', provider: 'Bank', owner: 'Pat Doe'}];
        $('dcpick').innerHTML = '<option value="Bank Statements\\nsecond" selected>Bank, Pat Doe</option>';
        window.fetch = async () => ({json: async () => ({documents_root: 'D:\\\\Docs', output_dir: 'C:\\\\PaperPull\\\\x',
            own: [{who: 'Bank Statements, second', folder: 'E:\\\\Mine'}]})});
        await dcLoad();
        return $('drownlist').textContent;
    }""")
    assert said == "Bank, Pat Doe keeps E:\\Mine"
