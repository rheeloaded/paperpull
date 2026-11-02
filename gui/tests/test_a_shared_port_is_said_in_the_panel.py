"""The control panel says when two accounts beside each other name one port.

A sign-in on a port a browser already holds joins that browser (#90), so two
configs on one port sign in to one browser, one profile, and a run of either
reads whichever account it is signed in to. A second person is given their
app's port plus 10, moved past only the ports in use then, so an app set up
after them can come with that same port. The account's row and page now
name the other install and account and the cdp_url to change to what, the
same as Login says. Nothing is stopped for it, since a wrong refusal is
worse than the clash, and an install's own example or a config with no port
is never a clash. The page tests run the panel's own script in Playwright's
own headless Chromium against the real panel on a free local port. Every
folder is under tmp_path and every provider, label and port is made up.
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
responses = pytest.importorskip("starlette.responses")


def install(root: Path, folder: str, script: str, provider: str, example=None, **configs) -> Path:
    d = root / folder
    d.mkdir(parents=True)
    (d / script).write_text("", encoding="utf-8")
    (d / "storage.py").write_text('SPEC = AppSpec(\n    provider="%s",\n    kind=DOCUMENT,\n)\n'
                                  % provider, encoding="utf-8")
    if example is not None:
        (d / "config.example.json").write_text(
            json.dumps({"output_dir": ".", "cdp_url": example}), encoding="utf-8")
    for account, cfg in configs.items():
        name = "config.json" if account == "primary" else "config.%s.json" % account
        out = "." if account == "primary" else str(d.parent / ("%s - %s" % (folder, account)))
        (d / name).write_text(json.dumps(dict({"output_dir": out}, **cfg)), encoding="utf-8")
    return d


def at(port: int) -> dict:
    return {"cdp_url": "http://127.0.0.1:%d" % port}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "PaperPull"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    # The providers this copy ships, a folder of its own with none in it,
    # so no test reads the repo's own.
    shipped = tmp_path / "templates"
    shipped.mkdir()
    monkeypatch.setattr(app_module, "_templates_root", lambda: shipped)
    monkeypatch.setattr(app_module._ports(), "shipped_folders", lambda: [])
    app_module._RUNS.clear()
    (tmp_path / "PaperPull").mkdir()
    return tmp_path / "PaperPull"


@pytest.fixture()
def pair(root):
    """Grocer's second person on 9262, then Card set up on its example's
    9262, and Store on 9263, the next port up."""
    grocer = install(root, "Grocer Receipts", "grocer_receipts.py", "Grocer",
                     "http://127.0.0.1:9252", primary=at(9252), spouse=at(9262))
    card = install(root, "Card Statements", "card_docs.py", "Card", "http://127.0.0.1:9262",
                   primary=at(9262))
    install(root, "Store Receipts", "store_receipts.py", "Store", "http://127.0.0.1:9263",
            primary=at(9263))
    return grocer, card


def rows() -> dict:
    return {(r["app"], r["account"]): r for r in app_module.account_rows()}


def test_each_account_on_a_shared_port_names_the_other_and_the_cdp_url_to_change(pair):
    got = rows()
    card = got[("Card Statements", "primary")]["shared_port"]
    assert card["port"] == 9262
    assert card["say"] == (
        'The "spouse" account of Grocer Receipts names debugging port 9262 too. A sign-in '
        "joins the browser already on its port, so these accounts sign in to one browser, "
        "and a run of any of them reads whichever account that browser is signed in to. "
        "To keep them apart, change cdp_url in config.spouse.json in the Grocer Receipts "
        "folder to http://127.0.0.1:9264, a port no other account here names and no "
        "provider PaperPull ships comes with. Nothing is stopped for this.")
    assert card["short"] == ('Shares debugging port 9262 with the "spouse" account of '
                             "Grocer Receipts. Open it to see the setting to change.")
    spouse = got[("Grocer Receipts", "spouse")]["shared_port"]
    assert spouse["say"].startswith("The first account of Card Statements names "
                                    "debugging port 9262 too.")
    assert ("change cdp_url in this account's config, config.spouse.json in the Grocer "
            "Receipts folder, to http://127.0.0.1:9264, a port") in spouse["say"]
    assert got[("Grocer Receipts", "primary")]["shared_port"] is None
    assert got[("Store Receipts", "primary")]["shared_port"] is None


def test_the_panel_and_login_tell_a_person_the_same_thing(pair, capsys, monkeypatch):
    """The panel and Login ask the same core module with the same shipped
    providers, one of which comes with 9264, so both send the same config
    past it to the same address."""
    grocer, card = pair
    shipped = app_module._templates_root()
    install(shipped, "deli", "deli_receipts.py", "Deli", "http://127.0.0.1:9264")
    mod = app_module._ports()
    monkeypatch.setattr(mod, "shipped_folders", lambda: [shipped])
    mod.say_at_sign_in(card / "config.json", "9262")
    login = capsys.readouterr().out
    panel = rows()[("Card Statements", "primary")]["shared_port"]["say"]
    assert "     %s\n       http://127.0.0.1:9265\n" % (grocer / "config.spouse.json") in login
    assert ("change cdp_url in config.spouse.json in the Grocer Receipts folder to "
            "http://127.0.0.1:9265, a port") in panel


def test_an_install_s_own_example_and_a_config_with_no_port_are_no_clash(root):
    install(root, "Chase Statements", "chase_docs.py", "Chase", "http://127.0.0.1:9236",
            primary=at(9236))
    install(root, "Bank Statements", "bank_docs.py", "Bank", "http://127.0.0.1:9236")
    install(root, "Shop Receipts", "shop_receipts.py", "Shop", None, primary={},
            spouse={"cdp_url": "http://localhost"})
    got = rows()
    assert got and all(r["shared_port"] is None for r in got.values()), got


def test_both_rows_of_a_tie_say_the_same_one_moves(root):
    """Two apps that both shipped on 9298, each set up on its example."""
    install(root, "Alpha Statements", "alpha_docs.py", "Alpha", "http://127.0.0.1:9298",
            primary=at(9298))
    install(root, "Beta Statements", "beta_docs.py", "Beta", "http://127.0.0.1:9298",
            primary=at(9298))
    got = rows()
    alpha = got[("Alpha Statements", "primary")]["shared_port"]["say"]
    beta = got[("Beta Statements", "primary")]["shared_port"]["say"]
    assert ("change cdp_url in config.json in the Beta Statements folder to "
            "http://127.0.0.1:9299, a port") in alpha
    assert ("change cdp_url in this account's config, config.json in the Beta Statements "
            "folder, to http://127.0.0.1:9299, a port") in beta


def test_a_stray_character_in_an_address_keeps_every_row(pair):
    """A cdp_url holding half of a character and a line break, written by
    hand or left in the shared folder on the server. The page's rows are
    sent as UTF-8, which cannot hold the half, and the home page said only
    that it could not read the accounts. The half is made whole as the
    config is read, and the line break is written as its escape."""
    grocer, _ = pair
    (grocer / "config.spouse.json").write_text(
        '{"output_dir": ".", "cdp_url": "http://127.0.0.1:9262/a\\nb\\ud800"}', encoding="utf-8")
    got = app_module.account_rows()
    body = responses.JSONResponse({"accounts": got}).body
    said = json.loads(body)["accounts"]
    card = next(r for r in said if r["app"] == "Card Statements")["shared_port"]["say"]
    assert "http://127.0.0.1:9264/a\\nb�" in card


def test_a_port_it_cannot_read_takes_no_row_down(pair, monkeypatch):
    class Broken:
        def installs_in(self, root):
            raise OSError("the folder went away")

        def shipped_folders(self):
            return []
    monkeypatch.setattr(app_module, "_ports", lambda: Broken())
    got = rows()
    assert len(got) == 4
    assert all(r["shared_port"] is None for r in got.values())
    assert all(r["state"] != "nostatus" for r in got.values())


def test_a_note_it_cannot_make_takes_no_row_down(pair, monkeypatch):
    real = app_module._ports()

    class Strange:
        installs_in = staticmethod(real.installs_in)
        findings = staticmethod(real.findings)
        shipped_folders = staticmethod(lambda: [])

        @staticmethod
        def key_of(config):
            raise RuntimeError("a link that leads to itself")
    monkeypatch.setattr(app_module, "_ports", lambda: Strange())
    got = rows()
    assert len(got) == 4
    assert all(r["shared_port"] is None for r in got.values())
    assert all(r["state"] != "nostatus" for r in got.values())


# -- in a browser --------------------------------------------------------------

sync_api = pytest.importorskip("playwright.sync_api")


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


@pytest.fixture()
def tab(browser):
    context = browser.new_context()
    yield context.new_page()
    context.close()


def test_the_account_page_says_it_above_a_sign_in_it_still_offers(pair, base, tab):
    tab.goto(base + "/#/a/Card%20Statements/primary")
    tab.wait_for_selector("#view-account [data-do=run][data-action=login]")
    said = tab.inner_text("#view-account .callout.warn")
    assert 'The "spouse" account of Grocer Receipts names debugging port 9262 too.' in said
    assert "http://127.0.0.1:9264" in said
    assert tab.is_enabled("#view-account [data-do=run][data-action=login]")


def test_the_home_row_says_it_and_a_row_on_its_own_port_does_not(pair, base, tab):
    tab.goto(base + "/#/")
    tab.wait_for_selector("#view-home .acct")

    def row(provider):
        return tab.locator("#view-home .acct").filter(
            has=tab.locator(".who a", has_text=provider))
    assert ("Shares debugging port 9262 with the \"spouse\" account of Grocer Receipts."
            in row("Card").inner_text())
    assert "Shares debugging port" not in row("Store").inner_text()
