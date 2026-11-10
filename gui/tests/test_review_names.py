"""Review Names in the panel, on the desktop and on PaperPull Server.

Every receipt app asks for a better name for each receipt it was unsure of,
and it asks in a console, which the panel does not have and the server has
none of at all. So the panel asks in two steps. POST /api/review-names has
the app write the receipts it would ask about to a file of the panel's own,
and renames nothing. POST /api/review-names/apply hands the app what the
person typed, in a file of that run's own that is gone once the run ends,
and streams the run as any other run is streamed. The rules about which
receipt may be renamed stay the app's own (core renaming.review_names, held
to them for all fourteen receipt apps by
core/tests/test_every_app_reviews_names_from_the_panel.py).

These run a stand-in receipt app as a real process, the panel's way, which
writes down the command line, the environment it was handed and what it
read. On the server it is the image's copy that runs, never one in /data.
Every name and number is invented.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]

# The stand-in. It answers the list step with one receipt and the answers
# step by reading what it was handed, as the real review does, and writes
# down what it saw in seen.json in the folder it runs in.
SHOP = """\
import json, os, sys
from pathlib import Path
listing = os.environ.get("PAPERPULL_REVIEW_LIST")
answers = os.environ.get("PAPERPULL_REVIEW_ANSWERS")
seen = {"argv": sys.argv[1:], "ran": str(Path(__file__).resolve()),
        "console": sys.stdin.isatty(), "listing": bool(listing)}
if listing:
    Path(listing).write_text(json.dumps({"receipts": [
        {"id": "C:/out/2026-05-14 Unsure Receipt.pdf", "number": "ORDER-0001",
         "date": "2026-05-14", "confidence": "Low", "status": "Review Needed",
         "file": "2026-05-14 Unsure Receipt.pdf", "summary": "Unsure",
         "items": ["Invented Hose"]}]}), encoding="utf-8")
    print("1 row marked for review has no receipt PDF in this app's folders "
          "to rename, so it is left out.")
    print("1 receipt needs review.")
if answers:
    seen["answers_at"] = answers
    seen["answers"] = json.loads(Path(answers).read_text(encoding="utf-8"))
    print("Renaming 1 receipt given a new name.")
    print("    Renamed -> 2026-05-14 Garden Hose Receipt.pdf")
Path("seen.json").write_text(json.dumps(seen), encoding="utf-8")
"""


class Asked:
    """A request as a POST handler reads it."""

    def __init__(self, body, kind="application/json"):
        self.headers = {"content-type": kind} if kind else {}
        self.body = body

    async def json(self):
        return self.body


def listed(body, kind="application/json"):
    """(status, answer) for one POST /api/review-names."""
    async def go():
        try:
            return 200, await app_module.api_review_names(Asked(body, kind))
        except fastapi.HTTPException as e:
            return e.status_code, str(e.detail)
    return asyncio.run(go())


def applied(body, kind="application/json"):
    """(status, everything streamed) for one POST /api/review-names/apply."""
    async def go():
        try:
            response = await app_module.api_review_names_apply(Asked(body, kind))
        except fastapi.HTTPException as e:
            return e.status_code, str(e.detail)
        return 200, "".join([part async for part in response.body_iterator])
    return asyncio.run(go())


def answer(summary="garden hose", **more):
    return dict({"id": "C:/out/2026-05-14 Unsure Receipt.pdf", "number": "ORDER-0001",
                 "summary": summary}, **more)


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """A receipt app and a document app on the desktop, set up, with two
    people on the receipt app."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    for name in (app_module.REVIEW_LIST_ENV, app_module.REVIEW_ANSWERS_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "setup_needed", lambda meta: "")
    receipts = tmp_path / "Shop Receipts"
    receipts.mkdir()
    (receipts / "shop_receipts.py").write_text(SHOP, encoding="utf-8")
    docs = tmp_path / "Bank Docs"
    docs.mkdir()
    (docs / "bank_docs.py").write_text(SHOP, encoding="utf-8")
    apps = {}
    for folder, script in ((receipts, "shop_receipts.py"), (docs, "bank_docs.py")):
        apps[folder.name] = {
            "name": folder.name, "dir": str(folder), "script": script,
            "script_name": script, "template_dir": None, "python": sys.executable,
            "login_flag": "--login", "accounts": ["primary", "robin"],
            "has_venv": True, "needs_setup": False, "runnable": True,
            "reviews_names": app_module._reviews_names(folder / script)}
    monkeypatch.setattr(app_module, "discover_apps", lambda: apps)
    monkeypatch.setattr(app_module, "_RUNS", {})
    return receipts


def seen(folder: Path) -> dict:
    return json.loads((folder / "seen.json").read_text(encoding="utf-8"))


# -- what the panel and the apps agree on ----------------------------------------------

def test_the_panel_and_the_apps_name_the_same_two_handovers():
    sys.path.insert(0, str(REPO / "core"))
    try:
        from paperpull_core import renaming
    finally:
        sys.path.remove(str(REPO / "core"))
    assert app_module.REVIEW_LIST_ENV == renaming.REVIEW_LIST_ENV
    assert app_module.REVIEW_ANSWERS_ENV == renaming.REVIEW_ANSWERS_ENV


def test_review_names_is_kept_out_of_the_table_every_app_is_sent():
    """Every action is sent to all the apps (core/tests/test_panel_and_apps_
    agree.py), and only a receipt app knows --review-names."""
    assert "review_names" not in app_module.ACTIONS
    assert not any("--review-names" in a["flags"] for a in app_module.ACTIONS.values())


def test_only_a_receipt_app_has_it():
    assert app_module._reviews_names(Path("x/target_receipts.py"))
    assert not app_module._reviews_names(Path("x/ally_docs.py"))
    assert not app_module._reviews_names(None)
    entries = sorted(REPO.glob("apps/*/*_receipts.py"))
    assert len(entries) >= 14
    for entry in entries:
        assert "--review-names" in entry.read_text(encoding="utf-8") or \
            '"review-names"' in entry.read_text(encoding="utf-8"), entry


def test_a_run_cannot_ask_for_it(shop):
    """Only /api/review-names/apply starts it, since only that hands it the
    new names. Asked as a run, it is an action the panel does not have."""
    async def post():
        try:
            await app_module.api_run_body(Asked({"app": "Shop Receipts",
                                                 "action": "review_names"}))
        except fastapi.HTTPException as e:
            return e.status_code
    assert asyncio.run(post()) == 400
    with pytest.raises(fastapi.HTTPException) as refused:
        app_module.api_run(app="Shop Receipts", action="review_names")
    assert refused.value.status_code == 400


# -- the list ---------------------------------------------------------------------------

def test_the_list_is_the_apps_own_and_its_file_is_gone_after(shop, tmp_path):
    status, got = listed({"app": "Shop Receipts"})
    assert status == 200, got
    assert [r["number"] for r in got["receipts"]] == ["ORDER-0001"]
    assert any("left out" in line for line in got["said"])
    what = seen(shop)
    assert what["argv"] == ["--review-names"]
    assert what["listing"] is True
    assert what["console"] is False, "the app is never given a console to ask in"


def test_a_second_person_lists_their_own(shop):
    status, _ = listed({"app": "Shop Receipts", "account": "robin"})
    assert status == 200
    assert seen(shop)["argv"] == ["--review-names", "--config", "config.robin.json"]


@pytest.mark.parametrize("body,code", [
    ({"app": "Bank Docs"}, 400),
    ({"app": "Nobody"}, 404),
    ({"app": "Shop Receipts", "account": "stranger"}, 400),
    ({"app": "Shop Receipts", "action": "all"}, 400),
    ({"app": 7}, 400),
    ({}, 400),
    (["Shop Receipts"], 400),
])
def test_a_list_asked_wrongly_is_refused(shop, body, code):
    status, _ = listed(body)
    assert status == code
    assert not (shop / "seen.json").exists()


def test_an_app_that_lists_nothing_is_said(shop):
    (shop / "shop_receipts.py").write_text("print('Something went wrong here.')\n",
                                           encoding="utf-8")
    status, detail = listed({"app": "Shop Receipts"})
    assert status == 500
    assert "Something went wrong here." in detail


def test_an_app_that_crashes_while_listing_says_why(shop):
    (shop / "shop_receipts.py").write_text(
        "raise RuntimeError('an invented failure')\n", encoding="utf-8")
    status, detail = listed({"app": "Shop Receipts"})
    assert status == 500
    assert "an invented failure" in detail


def test_no_list_while_that_account_runs_or_a_history_is_imported(shop):
    """Listing starts the app, which may write its own records (Target
    mends an order's list of invoices), so it waits as a run would."""
    app_module._RUNS[("Shop Receipts", "primary")] = {"action": "all", "started": ""}
    status, detail = listed({"app": "Shop Receipts"})
    assert status == 409 and "running" in detail
    assert not (shop / "seen.json").exists()
    app_module._RUNS.clear()
    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        status, detail = listed({"app": "Shop Receipts"})
    finally:
        app_module._IMPORTING.release()
    assert status == 409 and "imported" in detail
    assert not (shop / "seen.json").exists()


def test_a_list_counts_as_a_run_while_it_lists(shop, monkeypatch):
    held = []
    real = app_module._review_list

    def noting(app, account):
        held.append(((app, account) in app_module._RUNS, app in app_module._RUNNING))
        return real(app, account)
    monkeypatch.setattr(app_module, "_review_list", noting)
    status, _ = listed({"app": "Shop Receipts"})
    assert status == 200
    assert held == [(True, True)]
    assert not app_module._RUNS and "Shop Receipts" not in app_module._RUNNING


@pytest.mark.parametrize("ask", [lambda b: listed(b, kind="text/plain"),
                                 lambda b: applied(dict(b, answers=[answer()]), kind="")])
def test_a_body_that_is_not_json_is_refused(shop, ask):
    status, _ = ask({"app": "Shop Receipts"})
    assert status == 415
    assert not (shop / "seen.json").exists()


# -- the new names ----------------------------------------------------------------------

def test_the_new_names_reach_the_app_in_a_file_gone_when_the_run_ends(shop):
    status, out = applied({"app": "Shop Receipts", "answers": [
        answer(), answer(summary="  ", id="C:/out/2026-05-14 Other Receipt.pdf",
                         number="ORDER-0002")]})
    assert status == 200, out
    assert "event: done\ndata: 0" in out
    assert "Renamed -> 2026-05-14 Garden Hose Receipt.pdf" in out
    what = seen(shop)
    assert what["argv"] == ["--review-names"]
    assert what["console"] is False
    assert what["answers"] == {"answers": [answer()]}, "a blank one keeps its name"
    handed = Path(what["answers_at"])
    assert not handed.exists() and not handed.parent.exists()
    assert not app_module._RUNS


def test_a_second_persons_names_go_to_their_own_config(shop):
    status, out = applied({"app": "Shop Receipts", "account": "robin", "answers": [answer()]})
    assert status == 200, out
    assert seen(shop)["argv"] == ["--review-names", "--config", "config.robin.json"]


def test_names_are_not_handed_over_while_that_account_runs(shop):
    app_module._RUNS[("Shop Receipts", "primary")] = {"action": "all", "started": ""}
    status, out = applied({"app": "Shop Receipts", "answers": [answer()]})
    assert status == 200
    assert "already running" in out
    assert not (shop / "seen.json").exists()


@pytest.mark.parametrize("body", [
    {"app": "Shop Receipts", "answers": "garden hose"},
    {"app": "Shop Receipts", "answers": [answer(extra="x")]},
    {"app": "Shop Receipts", "answers": [{"id": "a", "summary": "b"}]},
    {"app": "Shop Receipts", "answers": [answer(summary=7)]},
    {"app": "Shop Receipts", "answers": [answer(summary="x" * 1001)]},
    {"app": "Shop Receipts", "answers": [answer()] * 2001},
    {"app": "Shop Receipts", "answers": [answer()], "redownload": True},
    {"app": "Bank Docs", "answers": [answer()]},
])
def test_names_asked_wrongly_are_refused(shop, body):
    status, out = applied(body)
    assert status == 400 or "event: done\ndata: 0" not in out
    assert not (shop / "seen.json").exists()
    assert not (shop.parent / "Bank Docs" / "seen.json").exists()


# -- the page -----------------------------------------------------------------------------

def test_the_page_offers_it_to_a_receipt_provider_only_and_posts_the_names():
    script = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    page = (REPO / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "META.apps[r.app].reviews_names" in script
    assert "'/api/review-names'" in script and "'/api/review-names/apply'" in script
    assert 'id="dlg-review"' in page and 'data-do="rv-go"' in page
    # Not hidden on the server, the way Restore deleted files is.
    menu = script[script.index("function openMenu"):script.index("function", script.index(
        "function openMenu") + 10)]
    review = menu[menu.index("'review'") - 200:menu.index("'review'")]
    assert "SERVER" not in review


# -- PaperPull Server ---------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path, monkeypatch):
    """An image-like tree with the receipt app's trusted copy, and a /data
    install holding a changed copy that must never run."""
    opt = tmp_path / "opt" / "paperpull"
    gui = opt / "gui"
    gui.mkdir(parents=True)
    tmpl = opt / "templates" / "apps" / "shop"
    tmpl.mkdir(parents=True)
    (tmpl / "shop_receipts.py").write_text(SHOP + "\n# --open-browser\n", encoding="utf-8")
    data = tmp_path / "data"
    install = data / "Shop Receipts"
    install.mkdir(parents=True)
    (install / "shop_receipts.py").write_text(
        "raise SystemExit('the /data copy must never run')\n", encoding="utf-8")
    (install / "config.json").write_text('{"output_dir": "."}\n', encoding="utf-8")
    monkeypatch.setattr(app_module, "HERE", gui)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_RUNS", {})
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    for name in ("PAPERPULL_DATA_DIR", "PYTHONPATH", app_module.REVIEW_LIST_ENV,
                 app_module.REVIEW_ANSWERS_ENV):
        monkeypatch.delenv(name, raising=False)
    return install, tmpl


def test_on_the_server_the_images_copy_lists_and_renames(server):
    install, tmpl = server
    meta = app_module.discover_apps()["Shop Receipts"]
    assert meta["reviews_names"] is True
    cmd = app_module._review_cmd(meta, "primary")
    assert cmd[:2] == [sys.executable, "-P"]
    assert cmd[2] == str(tmpl / "shop_receipts.py")

    status, got = listed({"app": "Shop Receipts"})
    assert status == 200, got
    assert Path(seen(install)["ran"]) == (tmpl / "shop_receipts.py").resolve()

    status, out = applied({"app": "Shop Receipts", "answers": [answer()]})
    assert status == 200, out
    assert "event: done\ndata: 0" in out
    what = seen(install)
    assert Path(what["ran"]) == (tmpl / "shop_receipts.py").resolve()
    assert what["answers"] == {"answers": [answer()]}
    handed = Path(what["answers_at"])
    assert not handed.parent.exists()
    assert not str(handed).startswith(str(install.parent)), "nothing is handed through /data"


def test_on_the_server_an_install_that_maps_to_nothing_is_not_listed(server):
    install, tmpl = server
    (install / "other_receipts.py").write_text("", encoding="utf-8")
    status, detail = listed({"app": "Shop Receipts"})
    assert status == 409
    assert not (install / "seen.json").exists()
