"""The settings page's Documents folder (#102).

One account's documents_dir, written into that account's config with a copy
of the config kept first. A folder that is not a full path, a browser
profile or inside or around one, one holding a provider's own folder, and
one inside the folder another account keeps its download history in are refused,
and on PaperPull Server so is one outside the data folder. The page says
how many documents saved before are still in the account's own folder, and
Move runs the app's own Rename with the core's move mark set.

Above it, one folder for every provider, kept in the panel's settings. Each
account that has no folder of its own gets one inside it, "<install>" or
"<install> - <account>", written into its config, and one given a folder of
its own, its own folder included, keeps it when the root changes.

The endpoints are called directly, the way the rest of this suite does.
Every folder is a throwaway one under tmp_path, and every name is invented.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
pytest.importorskip("fastapi")
from fastapi import HTTPException            # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from paperpull_core import renaming  # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def install(root: Path, name: str, accounts=("primary",)) -> Path:
    """A provider's folder with a config for each account, each with a
    profile and an output folder of its own beside it."""
    d = root / name
    d.mkdir(parents=True)
    for account in accounts:
        cfg_name = "config.json" if account == "primary" else "config.%s.json" % account
        out = "." if account == "primary" else "../%s - %s" % (name, account)
        (d / out).mkdir(parents=True, exist_ok=True)
        (d / cfg_name).write_text(json.dumps({
            "output_dir": out, "profile_dir": "%s-profile" % account}), encoding="utf-8")
    return d


@pytest.fixture
def apps(tmp_path, monkeypatch):
    root = tmp_path / "PaperPull"
    found = {"Chase Statements": install(root, "Chase Statements", ("primary", "spouse")),
             "Target Receipts": install(root, "Target Receipts")}
    metas = {name: {"name": name, "dir": str(d), "accounts": app_module._accounts(d)}
             for name, d in found.items()}
    monkeypatch.setattr(app_module, "discover_apps", lambda: metas)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_settings_path",
                        lambda: tmp_path / "panel" / "settings.json")
    return found


def save(body):
    return asyncio.run(app_module.api_documents_save(_Req(body)))


def config(d: Path, name="config.json") -> dict:
    return json.loads((d / name).read_text(encoding="utf-8"))


def test_an_account_with_no_documents_folder_keeps_everything_together(apps):
    d = app_module.api_documents("Chase Statements")
    assert d["documents_dir"] == "" and d["left"] == 0
    assert Path(d["output_dir"]) == apps["Chase Statements"].resolve()


def test_a_documents_folder_is_written_into_that_accounts_config_alone(apps, tmp_path):
    docs = tmp_path / "Watched"
    d = save({"app": "Chase Statements", "account": "spouse", "folder": str(docs)})
    assert d["written"] and d["documents_dir"] == str(docs)
    chase = apps["Chase Statements"]
    assert config(chase, "config.spouse.json")["documents_dir"] == str(docs)
    assert "documents_dir" not in config(chase)
    kept = list((chase / "Backups").glob("documents-*/config.spouse.json"))
    assert len(kept) == 1 and "documents_dir" not in json.loads(kept[0].read_text("utf-8"))
    assert save({"app": "Chase Statements", "account": "spouse",
                 "folder": str(docs)})["written"] is False, "nothing to change"
    d = save({"app": "Chase Statements", "account": "spouse", "folder": ""})
    assert d["written"] and "documents_dir" not in config(chase, "config.spouse.json")


def test_the_accounts_own_folder_clears_the_setting(apps):
    chase = apps["Chase Statements"]
    save({"app": "Chase Statements", "folder": str(chase.parent / "Elsewhere")})
    save({"app": "Chase Statements", "folder": str(chase)})
    assert "documents_dir" not in config(chase)


@pytest.mark.parametrize("where,says", [
    ("relative", "full path"),
    ("profile", "browser profile"),
    ("inside profile", "browser profile"),
    # The folder of every install holds its profiles too.
    ("holds an install", "browser profile"),
    ("another account", "keeps its download history in"),
    ("another provider", "keeps its download history in"),
])
def test_a_folder_that_cannot_hold_documents_is_refused(apps, where, says):
    chase = apps["Chase Statements"]
    folder = {"relative": "Watched",
              "profile": str(chase / "primary-profile"),
              "inside profile": str(chase / "spouse-profile" / "Default"),
              "holds an install": str(chase.parent),
              "another account": str(chase.parent / "Chase Statements - spouse" / "Docs"),
              "another provider": str(apps["Target Receipts"] / "Docs")}[where]
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": folder})
    assert e.value.status_code == 400 and says in e.value.detail, e.value.detail
    assert "documents_dir" not in config(chase)


def test_a_folder_holding_a_providers_own_folder_is_refused(apps, tmp_path):
    """Its settings and records are there, whatever its profile is. Here it
    is a provider's folder with no config, and so no profile, yet."""
    holder = tmp_path / "Holder"
    (holder / "Target Receipts").mkdir(parents=True)
    app_module.discover_apps()["Target Receipts"]["dir"] = str(holder / "Target Receipts")
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": str(holder)})
    assert "Target Receipts's own folder" in e.value.detail, e.value.detail


def test_a_folder_inside_the_accounts_own_folder_may_hold_its_documents(apps):
    chase = apps["Chase Statements"]
    assert save({"app": "Chase Statements", "folder": str(chase / "Documents")})["written"]


def test_on_the_server_a_folder_outside_the_data_folder_is_refused(apps, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.server_mode, "enabled", lambda: True)
    monkeypatch.setattr(app_module.server_mode, "data_root",
                        lambda: apps["Chase Statements"].parent)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": str(tmp_path / "elsewhere")})
    assert "data folder" in e.value.detail
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": str(tmp_path / "profiles" / "x")})
    inside = apps["Chase Statements"].parent / "Documents"
    assert save({"app": "Chase Statements", "folder": str(inside)})["written"]


def test_the_page_counts_the_documents_the_move_would_take(apps, tmp_path):
    """Saved and checked documents in a folder of their kind in the
    account's own folder, or in a documents folder it used before, each
    once while it is there, never one in Manual Review, one whose check
    failed, or one already in the documents folder, a folder inside the
    account's own folder included."""
    chase = apps["Chase Statements"]
    statements = chase / "Statements" / "Testco"
    statements.mkdir(parents=True)
    (statements / "a.pdf").write_bytes(b"%PDF- a")
    (chase / "Statements" / "b.pdf").write_bytes(b"%PDF- b")
    (chase / "Statements" / "failed.pdf").write_bytes(b"%PDF- failed")
    (chase / "Manual Review").mkdir()
    (chase / "Manual Review" / "c.pdf").write_bytes(b"%PDF- c")
    earlier = tmp_path / "Earlier Watched" / "Statements"
    earlier.mkdir(parents=True)
    (earlier / "d.pdf").write_bytes(b"%PDF- d")
    (chase / "documents-folders.json").write_text(
        json.dumps([str(tmp_path / "Earlier Watched")]), encoding="utf-8")
    docs = chase / "Documents"
    (docs / "Statements").mkdir(parents=True)
    (docs / "Statements" / "e.pdf").write_bytes(b"%PDF- e")
    done = {"downloaded_ok": True}
    records = {"a": dict(done, pdf_path="Statements/Testco/a.pdf"),
               "a again": dict(done, pdf_path=str(statements / "a.pdf")),
               "b": {"state": "Completed", "pdf_path": str(chase / "Statements" / "b.pdf")},
               "failed": {"downloaded_ok": False, "state": "Needs Manual Review",
                          "pdf_path": "Statements/failed.pdf"},
               "c": dict(done, pdf_path="Manual Review/c.pdf"),
               "d": dict(done, pdf_path=str(earlier / "d.pdf")),
               "e": dict(done, pdf_path=str(docs / "Statements" / "e.pdf")),
               "gone": dict(done, pdf_path="Statements/gone.pdf"),
               "elsewhere": dict(done, pdf_path=str(tmp_path / "x.pdf"))}
    (chase / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    assert app_module.api_documents("Chase Statements")["left"] == 1, (
        "with no folder set, the one in the folder used before comes back")
    d = save({"app": "Chase Statements", "folder": str(docs)})
    assert d["left"] == 3
    assert app_module.api_documents("Chase Statements")["left"] == 3
    # The Move takes what an index row names, so a record with no row is
    # not counted once there is an index.
    (chase / "Chase Document Index.csv").write_text(
        "PDF Filename,PDF Full Path\na.pdf,Statements/Testco/a.pdf\nd.pdf,%s\n"
        % (earlier / "d.pdf"), encoding="utf-8")
    assert app_module.api_documents("Chase Statements")["left"] == 2


def test_a_file_left_behind_keeps_the_move_on_offer(apps, tmp_path):
    """A workbook held open in a spreadsheet stays behind when its PDF moves.
    It is one document left, so the page goes on offering the Move, and a file
    the Move does not take is not counted."""
    chase = apps["Chase Statements"]
    docs = tmp_path / "Documents"
    (docs / "Tax Documents").mkdir(parents=True)
    moved = docs / "Tax Documents" / "form.pdf"
    moved.write_bytes(b"%PDF- form")
    (chase / "Tax Documents").mkdir()
    sheet = chase / "Tax Documents" / "form (2 of 3).xls"
    sheet.write_bytes(b"a workbook")
    other = chase / "Tax Documents" / "form (3 of 3).txt"
    other.write_bytes(b"something else")
    (chase / "progress.json").write_text(json.dumps({"form": {
        "downloaded_ok": True, "pdf_path": str(moved),
        "invoices": [{"file": str(moved), "kept": True}, {"file": str(sheet), "kept": True},
                     {"file": str(other), "kept": True}]}}), encoding="utf-8")
    assert save({"app": "Chase Statements", "folder": str(docs)})["left"] == 1


def test_the_panel_counts_what_the_move_takes():
    assert app_module.DOCUMENT_ENDINGS == renaming.VALID_DOC_EXTS


def test_an_unknown_account_is_refused(apps):
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "account": "nobody", "folder": ""})
    assert e.value.status_code == 404


@pytest.fixture()
def started(tmp_path, monkeypatch):
    """Every command the panel starts with the environment it is given,
    kept rather than run."""
    import io
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV, raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_settings_path",
                        lambda: tmp_path / "panel" / "settings.json")
    venv = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    meta = {"name": "Shop Docs", "dir": str(tmp_path), "script": "shop_docs.py",
            "python": "py", "login_flag": "--login", "accounts": ["primary"]}
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"Shop Docs": meta})
    runs = []

    class Process:
        def __init__(self, cmd, **kwargs):
            runs.append((list(cmd), dict(kwargs.get("env") or {})))
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("a line from the app\n")

        def wait(self, **kwargs):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(app_module.subprocess, "Popen", Process)
    return runs


def ran(action):
    async def go():
        response = app_module.api_run(app="Shop Docs", action=action)
        return "".join([part async for part in response.body_iterator])
    return asyncio.run(go())


@pytest.mark.parametrize("action,moves", [("move_documents", True),
                                          ("move_documents_apply", True),
                                          ("rename", False), ("rename_apply", False)])
def test_only_the_move_runs_the_apps_rename_with_the_mark(started, action, moves):
    out = ran(action)
    assert "event: done\ndata: 0" in out, out
    [(cmd, env)] = started
    assert cmd == ["py", "shop_docs.py", *app_module.ACTIONS[action]["flags"]]
    assert (env.get(renaming.MOVE_DOCUMENTS_ENV) == "1") is moves


def test_a_folder_around_an_accounts_own_folder_is_refused(apps, tmp_path):
    """A provider whose folder is kept elsewhere, as the default
    Downloads/<provider> is. Around it, its records and Manual Review would
    sit in the watched folder, the account's own or another's."""
    target = apps["Target Receipts"]
    out = tmp_path / "Somewhere" / "Target Out"
    out.mkdir(parents=True)
    (target / "config.json").write_text(json.dumps({
        "output_dir": str(out), "profile_dir": str(target / "primary-profile")}),
        encoding="utf-8")
    for app_name in ("Target Receipts", "Chase Statements"):
        with pytest.raises(HTTPException) as e:
            save({"app": app_name, "folder": str(tmp_path / "Somewhere")})
        assert "keeps its download history and Manual Review in" in e.value.detail, e.value.detail


@pytest.fixture()
def downloading(started, tmp_path):
    """The started stand-in, with a download run that lists what it saved
    in new-this-run.txt as every app does, and an account whose documents
    folder is set."""
    (tmp_path / "config.json").write_text(json.dumps({
        "output_dir": ".", "documents_dir": str(tmp_path.parent / "Watched")}),
        encoding="utf-8")
    listed = tmp_path / "new-this-run.txt"

    def lists(names):
        listed.write_text("# saved this run\n" + "".join(n + "\n" for n in names),
                          encoding="utf-8")
    return lists


def test_after_a_download_run_what_it_saved_moves_to_the_documents_folder(
        started, downloading, tmp_path):
    real = app_module.subprocess.Popen

    def first_lists(cmd, **kwargs):
        if "--pilot" in cmd:
            downloading([str(tmp_path / "Statements" / "a.pdf")])
        return real(cmd, **kwargs)

    app_module.subprocess.Popen = first_lists
    try:
        out = ran("pilot")
    finally:
        app_module.subprocess.Popen = real
    assert "event: done\ndata: 0" in out, out
    (pilot, pilot_env), (move, move_env) = started
    assert "--pilot" in pilot and renaming.MOVE_DOCUMENTS_ENV not in pilot_env
    assert move == ["py", "shop_docs.py", "--rename", "--apply"]
    assert move_env[renaming.MOVE_DOCUMENTS_ENV] == "new"


def finishing():
    """What /api/finishing names, asked from inside the panel's event loop or
    outside it. The route awaits nothing, so it answers on its first step."""
    step = app_module.api_finishing()
    try:
        step.send(None)
    except StopIteration as done:
        return done.value["finishing"]
    step.close()
    raise AssertionError("api_finishing awaited something")


def test_a_download_runs_move_is_named_as_finishing_while_it_goes(started, downloading, tmp_path):
    """The move after a download run is the same Move as Settings' own, so
    a quit of PaperPull.app waits for it (gui/mac_host.py), and it is named
    no longer once it has ended."""
    real = app_module.subprocess.Popen
    seen = []

    def watch(cmd, **kwargs):
        if "--pilot" in cmd:
            seen.append(("pilot", finishing()))
            downloading([str(tmp_path / "Statements" / "a.pdf")])
        else:
            seen.append(("move", finishing()))
        return real(cmd, **kwargs)

    app_module.subprocess.Popen = watch
    try:
        out = ran("pilot")
    finally:
        app_module.subprocess.Popen = real
    assert "event: done\ndata: 0" in out, out
    assert seen == [("pilot", []), ("move", ["move_documents_apply"])]
    assert finishing() == []


def test_what_a_run_saved_is_what_the_page_lists_after_its_move(started, downloading, tmp_path):
    """The move is the app's own Rename, and every app's Rename wrote a run
    summary of its own, new-this-run.txt with nothing in it. The panel read
    the list after the move, so a Citi run that saved 23 requested
    statements said Nothing new (#103). The list is read once, as the run
    ends and before the move, and the page and the run log get that one,
    whatever a step after the run writes."""
    real = app_module.subprocess.Popen

    def lists(cmd, **kwargs):
        if "--pilot" in cmd:
            downloading([str(tmp_path / "Statements" / "a.pdf"),
                         str(tmp_path / "Statements" / "b.pdf")])
        if "--rename" in cmd:
            downloading([])
        return real(cmd, **kwargs)

    app_module.subprocess.Popen = lists
    try:
        out = ran("pilot")
    finally:
        app_module.subprocess.Popen = real
    assert "event: done\ndata: 0" in out, out
    (pilot, _), (move, _) = started
    assert "--pilot" in pilot and move == ["py", "shop_docs.py", "--rename", "--apply"]
    [said] = [part for part in out.split("\n\n") if part.startswith("event: saved\n")]
    assert json.loads(said.split("data: ", 1)[1]) == ["a.pdf", "b.pdf"]
    assert app_module._read_run_log(tmp_path)[0]["saved"] == ["a.pdf", "b.pdf"]


@pytest.mark.parametrize("why", ["no documents folder", "nothing saved", "an old list"])
def test_no_move_follows_a_run_with_nothing_of_its_own_to_move(started, downloading, tmp_path,
                                                               why):
    if why == "no documents folder":
        (tmp_path / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    if why == "an old list":
        downloading([str(tmp_path / "Statements" / "a.pdf")])
        import os
        os.utime(tmp_path / "new-this-run.txt", (1000000000, 1000000000))
    real = app_module.subprocess.Popen

    def lists(cmd, **kwargs):
        if "--pilot" in cmd and why != "an old list":
            downloading([] if why == "nothing saved" else [str(tmp_path / "a.pdf")])
        return real(cmd, **kwargs)

    app_module.subprocess.Popen = lists
    try:
        ran("pilot")
    finally:
        app_module.subprocess.Popen = real
    assert len(started) == 1, started


@pytest.mark.parametrize("inside", ["Manual Review", "Backups", ".chase-downloads",
                                    # In any letter case, as a run tells them
                                    # (core storage._in_a_kept_folder).
                                    "manual review", "BACKUPS"])
def test_a_folder_inside_the_accounts_manual_review_or_records_is_refused(apps, inside):
    chase = apps["Chase Statements"]
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": str(chase / inside / "Docs")})
    assert "failed their check" in e.value.detail, e.value.detail


@pytest.fixture()
def slow(tmp_path, monkeypatch):
    """A run that is still going when its page closes, and whether it was
    stopped."""
    import io
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_settings_path",
                        lambda: tmp_path / "panel" / "settings.json")
    venv = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    meta = {"name": "Shop Docs", "dir": str(tmp_path), "script": "shop_docs.py",
            "python": "py", "login_flag": "--login", "accounts": ["primary"]}
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"Shop Docs": meta})
    seen = {"stopped": False, "ended": False}

    class Process:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("moving one\nmoving two\n")

        def poll(self):
            return 0 if (seen["stopped"] or seen["ended"]) else None

        def wait(self, **kwargs):
            seen["ended"] = True
            return 0

        def terminate(self):
            seen["stopped"] = True

        kill = terminate

    monkeypatch.setattr(app_module.subprocess, "Popen", Process)
    return seen


def closed_after_its_first_line(action):
    """The page closes once the run's first line of output has come."""
    async def go():
        response = app_module.api_run(app="Shop Docs", action=action)
        body = response.body_iterator
        while "moving one" not in await body.__anext__():
            pass
        await body.aclose()
    asyncio.run(go())


def test_a_move_or_rename_applying_finishes_when_its_page_closes(slow):
    """It moves every file and then writes the ledgers, so stopped partway
    it would leave files the index no longer names. It goes on to its end,
    and the account stays claimed until it has."""
    import time
    closed_after_its_first_line("move_documents_apply")
    for _ in range(200):
        if ("Shop Docs", "primary") not in app_module._RUNS:
            break
        time.sleep(0.01)
    assert not slow["stopped"] and slow["ended"]
    assert ("Shop Docs", "primary") not in app_module._RUNS


def test_any_other_run_is_stopped_when_its_page_closes(slow):
    closed_after_its_first_line("pilot")
    assert slow["stopped"]
    assert ("Shop Docs", "primary") not in app_module._RUNS


@pytest.fixture()
def held_open(slow, monkeypatch):
    """The slow stand-in, with output that goes on until the test lets the
    run end by setting the event this returns."""
    import io
    import threading
    go = threading.Event()

    class Output(io.StringIO):
        def __init__(self):
            super().__init__("moving one\n")

        def readline(self, *args):
            line = super().readline()
            if not line:
                go.wait(10)
            return line

        def __iter__(self):
            line = self.readline()
            while line:
                yield line
                line = self.readline()

    class Process:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = Output()

        def poll(self):
            return 0 if go.is_set() else None

        def wait(self, **kwargs):
            go.wait(10)
            return 0

        def terminate(self):
            go.set()

        kill = terminate

    monkeypatch.setattr(app_module.subprocess, "Popen", Process)
    yield go
    go.set()


def test_a_rename_applying_is_named_as_finishing_until_it_has_finished(held_open):
    """PaperPull.app asks /api/finishing before a quit stops the panel and
    every run it started, and waits while it names anything. So a Rename
    whose page closed is named there for as long as it goes on by itself,
    and nothing is named once it has ended and been noted."""
    import time
    assert finishing() == []
    closed_after_its_first_line("rename_apply")
    assert ("Shop Docs", "primary") in app_module._RUNS, "it goes on after its page closed"
    assert finishing() == ["rename_apply"]
    held_open.set()
    for _ in range(500):
        if ("Shop Docs", "primary") not in app_module._RUNS:
            break
        time.sleep(0.01)
    assert finishing() == []


def test_the_move_is_the_apps_own_rename_with_the_cores_mark():
    for action, flags in (("move_documents", ["--rename"]),
                          ("move_documents_apply", ["--rename", "--apply"])):
        assert app_module.ACTIONS[action]["flags"] == flags
        assert app_module.ACTIONS[action]["env"] == {renaming.MOVE_DOCUMENTS_ENV: "1"}
    assert all("env" not in spec for name, spec in app_module.ACTIONS.items()
               if not name.startswith("move_documents"))


# -- one documents folder for every provider ----------------------------------

def save_root(folder, all: bool = False):
    return asyncio.run(app_module.api_documents_root_save(_Req({"folder": folder, "all": all})))


def test_one_folder_gives_every_account_a_folder_of_its_own_inside_it(apps, tmp_path):
    docs = tmp_path / "Drive" / "PaperPull"
    d = save_root(str(docs))
    assert d["written"] and d["documents_root"] == str(docs) and d["configs"] == 3
    chase, target = apps["Chase Statements"], apps["Target Receipts"]
    assert config(chase)["documents_dir"] == str(docs / "Chase Statements")
    assert config(chase, "config.spouse.json")["documents_dir"] == \
        str(docs / "Chase Statements - spouse")
    assert config(target)["documents_dir"] == str(docs / "Target Receipts")
    got = app_module.api_documents("Chase Statements", "spouse")
    assert got["follows"] and got["documents_root"] == str(docs)
    assert got["in_root"] == got["documents_dir"]
    kept = list((chase / "Backups").glob("documents-*/config.spouse.json"))
    assert len(kept) == 1 and "documents_dir" not in json.loads(kept[0].read_text("utf-8"))
    assert save_root(str(docs))["written"] is False, "nothing to change"
    moved = tmp_path / "Other Drive"
    assert save_root(str(moved))["configs"] == 3
    assert config(target)["documents_dir"] == str(moved / "Target Receipts")
    assert save_root("")["configs"] == 3
    for folder, name in ((chase, "config.json"), (chase, "config.spouse.json"),
                         (target, "config.json")):
        assert "documents_dir" not in config(folder, name)


def test_a_folder_set_for_one_account_stays_when_the_root_changes(apps, tmp_path):
    chase, target = apps["Chase Statements"], apps["Target Receipts"]
    own = tmp_path / "Spouse Watched"
    save({"app": "Chase Statements", "account": "spouse", "folder": str(own)})
    docs = tmp_path / "Drive"
    assert save_root(str(docs))["configs"] == 2
    assert config(chase, "config.spouse.json")["documents_dir"] == str(own)
    assert not app_module.api_documents("Chase Statements", "spouse")["follows"]
    # Its own folder, chosen while the root is set, is kept as that.
    save({"app": "Target Receipts", "folder": ""})
    assert config(target)["documents_dir"] == ""
    assert not app_module.api_documents("Target Receipts")["follows"]
    save_root(str(tmp_path / "Elsewhere"))
    assert config(target)["documents_dir"] == ""
    assert config(chase, "config.spouse.json")["documents_dir"] == str(own)
    assert config(chase)["documents_dir"] == str(tmp_path / "Elsewhere" / "Chase Statements")
    # And it can follow the root again.
    d = save({"app": "Target Receipts", "follow": True})
    assert d["written"] and d["follows"]
    assert config(target)["documents_dir"] == str(tmp_path / "Elsewhere" / "Target Receipts")


def test_saving_with_all_gives_every_account_the_folder_even_with_own_folder(apps, tmp_path):
    chase = apps["Chase Statements"]
    own = tmp_path / "Spouse Watched"
    save({"app": "Chase Statements", "account": "spouse", "folder": str(own)})
    docs = tmp_path / "Drive"
    d = save_root(str(docs))
    assert d["configs"] == 2 and d["following"] == 2 and d["unfollowed"] == 1
    d_all = save_root(str(docs), all=True)
    assert d_all["configs"] == 1 and d_all["following"] == 3 and d_all["unfollowed"] == 0
    assert config(chase, "config.spouse.json")["documents_dir"] == \
        str(docs / "Chase Statements - spouse")


def test_an_account_added_later_gets_its_folder_before_it_runs(apps, tmp_path):
    docs = tmp_path / "Drive"
    save_root(str(docs))
    target = apps["Target Receipts"]
    (target / "config.kid.json").write_text(json.dumps({
        "output_dir": "../Target Receipts - kid", "profile_dir": "kid-profile"}),
        encoding="utf-8")
    metas = app_module.discover_apps()
    metas["Target Receipts"]["accounts"] = app_module._accounts(target)
    assert app_module._sync_documents(metas, str(docs), only=("Target Receipts", "kid")) == 1
    assert config(target, "config.kid.json")["documents_dir"] == \
        str(docs / "Target Receipts - kid")


@pytest.mark.parametrize("where,says", [
    ("relative", "full path"),
    ("profile", "browser profile"),
    ("the PaperPull folder", "browser profile"),
    ("inside a provider", "keeps its download history in"),
    ("inside Manual Review", "keeps its download history in"),
])
def test_a_root_that_cannot_hold_documents_is_refused(apps, where, says):
    chase = apps["Chase Statements"]
    folder = {"relative": "Watched",
              "profile": str(chase / "primary-profile"),
              "the PaperPull folder": str(chase.parent),
              "inside a provider": str(apps["Target Receipts"] / "Docs"),
              "inside Manual Review": str(chase / "Manual Review" / "Docs")}[where]
    with pytest.raises(HTTPException) as e:
        save_root(folder)
    assert e.value.status_code == 400 and says in e.value.detail, e.value.detail
    assert "documents_dir" not in config(chase)
    assert app_module.api_documents("Chase Statements")["documents_root"] == ""


# -- the review of #120 -------------------------------------------------------
#
# A run fills in a person's folder in the one documents folder only when
# their config names no documents folder at all, only for a run that
# starts, and says so in its output. Apply to every account names each
# folder it would replace before it is pressed, and applies the folder
# saved, the one that list was made for. A config that cannot be written
# keeps no copy and is named. Each folder in it is one folder's name, never
# shared by two providers or people, and on PaperPull Server it stays in
# the data folder, a link left in its place included.

def _drive(tmp_path: Path) -> Path:
    """A documents folder beside the started stand-in's install."""
    return tmp_path.parent / (tmp_path.name + " Drive")


def test_a_run_gives_a_person_added_since_their_folder_and_says_so(started, tmp_path):
    drive = _drive(tmp_path)
    (tmp_path / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    app_module._write_settings({"documents_root": str(drive)})
    out = ran("pilot")
    assert "event: done\ndata: 0" in out, out
    assert config(tmp_path)["documents_dir"] == str(drive / "Shop Docs")
    assert str(drive / "Shop Docs") in out, out
    assert len(list((tmp_path / "Backups").glob("documents-*/config.json"))) == 1
    out = ran("pilot")
    assert str(drive / "Shop Docs") not in out, "said once, when it was written"


@pytest.mark.parametrize("why", ["an unknown action", "already running", "an import"])
def test_a_run_that_is_refused_writes_no_config(started, tmp_path, why):
    (tmp_path / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    app_module._write_settings({"documents_root": str(_drive(tmp_path))})
    if why == "an unknown action":
        with pytest.raises(HTTPException):
            ran("nothing such")
    elif why == "already running":
        app_module._RUNS[("Shop Docs", "primary")] = {"action": "pilot", "started": ""}
        try:
            assert "already running" in ran("pilot")
        finally:
            app_module._RUNS.pop(("Shop Docs", "primary"), None)
    else:
        app_module._IMPORTING.acquire()
        try:
            assert "being imported" in ran("pilot")
        finally:
            app_module._IMPORTING.release()
    assert "documents_dir" not in config(tmp_path)
    assert not (tmp_path / "Backups").exists()
    assert started == []


@pytest.mark.parametrize("own", ["a folder set for it", "its own folder"])
def test_a_run_never_changes_a_folder_set_for_one_account(started, tmp_path, own):
    value = str(tmp_path.parent / (tmp_path.name + " Watched")) if own != "its own folder" else ""
    (tmp_path / "config.json").write_text(json.dumps({"output_dir": ".", "documents_dir": value}),
                                          encoding="utf-8")
    app_module._write_settings({"documents_root": str(_drive(tmp_path))})
    assert "event: done\ndata: 0" in ran("pilot")
    assert config(tmp_path)["documents_dir"] == value
    assert not (tmp_path / "Backups").exists()


def test_a_config_that_cannot_be_written_keeps_no_copy_and_is_named(apps, tmp_path, monkeypatch):
    def refuse(path, text):
        raise PermissionError("read-only")
    monkeypatch.setattr(app_module, "_replace_text", refuse)
    d = save_root(str(tmp_path / "Drive"))
    assert d["configs"] == 0
    assert d["missed"] == ["Chase Statements", "Chase Statements, spouse", "Target Receipts"]
    for _ in range(3):
        assert app_module._sync_documents(app_module.discover_apps(), d["documents_root"]) == 0
    for folder in apps.values():
        assert not (folder / "Backups").exists(), list((folder / "Backups").rglob("*"))


def test_using_it_for_every_provider_names_each_folder_it_replaces_first(apps, tmp_path):
    chase, target = apps["Chase Statements"], apps["Target Receipts"]
    own = tmp_path / "Spouse Watched"
    save({"app": "Chase Statements", "account": "spouse", "folder": str(own)})
    docs = tmp_path / "Drive"
    assert save_root(str(docs))["own"] == [
        {"who": "Chase Statements, spouse", "folder": str(own)}]
    save({"app": "Target Receipts", "folder": ""})
    got = app_module.api_documents("Chase Statements")
    assert got["own"] == [{"who": "Chase Statements, spouse", "folder": str(own)},
                          {"who": "Target Receipts", "folder": ""}]
    assert got["unfollowed"] == 2
    # Only for the folder saved, whose list the page showed.
    with pytest.raises(HTTPException) as e:
        save_root(str(tmp_path / "Elsewhere"), all=True)
    assert e.value.status_code == 409, e.value.detail
    assert config(chase, "config.spouse.json")["documents_dir"] == str(own)
    assert app_module._documents_root() == str(docs)
    d = save_root(str(docs), all=True)
    assert d["configs"] == 2 and d["own"] == [] and d["unfollowed"] == 0
    assert config(target)["documents_dir"] == str(docs / "Target Receipts")
    kept = list((chase / "Backups").glob("documents-*/config.spouse.json"))
    assert str(own) in [json.loads(k.read_text("utf-8")).get("documents_dir") for k in kept]


def test_two_that_would_share_a_folder_in_it_are_refused(apps, tmp_path):
    """A second install named as the first one's second person is, its
    folder kept elsewhere."""
    other = install(tmp_path / "Elsewhere", "Chase Statements - spouse")
    metas = app_module.discover_apps()
    metas["Chase Statements - spouse"] = {"name": "Chase Statements - spouse",
                                          "dir": str(other), "accounts": ["primary"]}
    with pytest.raises(HTTPException) as e:
        save_root(str(tmp_path / "Drive"))
    assert "Chase Statements, spouse" in e.value.detail and \
        "Chase Statements - spouse" in e.value.detail, e.value.detail
    assert app_module._documents_root() == ""
    assert all("documents_dir" not in config(d) for d in (apps["Chase Statements"], other))


def test_a_name_that_is_not_one_folder_in_it_is_refused(apps, tmp_path):
    """No config file's name holds a separator, so this is a guard. The
    folder is always one folder inside the documents folder."""
    metas = app_module.discover_apps()
    metas["Target Receipts"]["accounts"] = ["primary", os.path.join("..", "..", "out")]
    with pytest.raises(HTTPException) as e:
        save_root(str(tmp_path / "Drive"))
    assert "one folder" in e.value.detail, e.value.detail


def _link(link: Path, to: Path) -> None:
    to.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(to, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(to), str(link))
    except (ImportError, OSError):
        pytest.skip("no link can be made here")


def test_on_the_server_the_folder_and_each_folder_in_it_stay_in_the_data_folder(
        apps, tmp_path, monkeypatch):
    data = apps["Chase Statements"].parent
    monkeypatch.setattr(app_module.server_mode, "enabled", lambda: True)
    monkeypatch.setattr(app_module.server_mode, "data_root", lambda: data)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    with pytest.raises(HTTPException) as e:
        save_root(str(tmp_path / "Drive"))
    assert "data folder" in e.value.detail
    # A link left in the data folder where one provider's folder would be.
    left = data / "Documents" / "Target Receipts"
    left.parent.mkdir()
    _link(left, tmp_path / "Outside")
    with pytest.raises(HTTPException) as e:
        save_root(str(data / "Documents"))
    assert "Target Receipts" in e.value.detail and "data folder" in e.value.detail, e.value.detail
    assert app_module._documents_root() == ""
    if left.is_symlink():
        left.unlink()
    else:
        os.rmdir(left)
    d = save_root(str(data / "Documents"))
    assert d["configs"] == 3, d
    assert config(apps["Target Receipts"])["documents_dir"] == str(left)


# -- the fresh review of the merged branch ------------------------------------
#
# One person's own folder is never the folder for every provider itself,
# nor another's folder in it, and following it is judged as the save is. A
# read-only config keeps no copy on Windows either, and on PaperPull Server
# nothing is taken away. A config that is no JSON object stops nothing
# else. Two writes of one config in one second keep two copies, and the
# folder is not saved while a history file is being imported.

@pytest.mark.parametrize("where", ["the folder itself", "another's folder", "inside another's"])
def test_a_folder_of_their_own_is_never_another_ones_in_it(apps, tmp_path, where):
    docs = tmp_path / "Drive"
    save_root(str(docs))
    folder = {"the folder itself": docs,
              "another's folder": docs / "Target Receipts",
              "inside another's": docs / "target receipts" / "Chase"}[where]
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "folder": str(folder)})
    assert e.value.status_code == 400, e.value.detail
    assert config(apps["Chase Statements"])["documents_dir"] == str(docs / "Chase Statements")
    # Its own folder in it, the one the field is filled in with, still saves.
    assert save({"app": "Chase Statements", "account": "spouse",
                 "folder": str(docs / "Chase Statements - spouse")})["follows"]


def test_following_the_folder_is_judged_as_saving_it_is(apps, tmp_path):
    docs = tmp_path / "Drive"
    save({"app": "Chase Statements", "account": "spouse", "folder": ""})
    save_root(str(docs))
    save({"app": "Chase Statements", "account": "spouse", "folder": ""})
    other = install(tmp_path / "Elsewhere", "Chase Statements - spouse")
    app_module.discover_apps()["Chase Statements - spouse"] = {
        "name": "Chase Statements - spouse", "dir": str(other), "accounts": ["primary"]}
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "account": "spouse", "follow": True})
    assert "same folder" in e.value.detail, e.value.detail
    assert config(apps["Chase Statements"], "config.spouse.json")["documents_dir"] == ""


def test_a_folder_set_before_that_another_would_get_in_it_is_refused(apps, tmp_path):
    docs = tmp_path / "Drive"
    save({"app": "Chase Statements", "account": "spouse", "folder": str(docs / "Target Receipts")})
    with pytest.raises(HTTPException) as e:
        save_root(str(docs))
    assert "Target Receipts" in e.value.detail and "Chase Statements, spouse" in e.value.detail
    assert app_module._documents_root() == ""


def test_a_read_only_config_keeps_no_copy(apps, tmp_path, monkeypatch):
    """A copy made with copy2 is read-only too, and Windows will not delete
    one until that is taken off. The write itself is refused here, since
    POSIX replaces a read-only file in a folder it may write."""
    import stat
    cfg = apps["Target Receipts"] / "config.json"
    os.chmod(cfg, stat.S_IREAD)
    try:
        monkeypatch.setattr(app_module, "_replace_text",
                            lambda path, text: (_ for _ in ()).throw(PermissionError("read-only")))
        assert "Target Receipts" in save_root(str(tmp_path / "Drive"))["missed"]
        assert not (apps["Target Receipts"] / "Backups").exists()
    finally:
        os.chmod(cfg, stat.S_IREAD | stat.S_IWRITE)


def test_on_the_server_nothing_is_taken_away_when_a_write_fails(apps, tmp_path, monkeypatch):
    data = apps["Chase Statements"].parent
    monkeypatch.setattr(app_module.server_mode, "enabled", lambda: True)
    monkeypatch.setattr(app_module.server_mode, "data_root", lambda: data)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))

    def refuse(path, text):
        raise PermissionError("read-only")
    monkeypatch.setattr(app_module, "_replace_text", refuse)
    save_root(str(data / "Documents"))
    assert list((apps["Target Receipts"] / "Backups").glob("documents-*/config.json"))


@pytest.mark.parametrize("held", ["[1]", "5", '"text"'])
def test_a_config_that_is_no_object_stops_nothing_else(apps, tmp_path, held):
    """In another install, as one left in the shared folder could be."""
    (apps["Target Receipts"] / "config.kid.json").write_text(held, encoding="utf-8")
    metas = app_module.discover_apps()
    metas["Target Receipts"]["accounts"] = app_module._accounts(apps["Target Receipts"])
    docs = tmp_path / "Drive"
    assert save_root(str(docs))["configs"] == 3
    assert app_module.api_documents("Chase Statements")["documents_root"] == str(docs)
    assert app_module._documents_before_run(metas, "Chase Statements", "primary") == []


def test_two_writes_of_one_config_in_one_second_keep_two_copies(apps):
    cfg = apps["Target Receipts"] / "config.json"
    assert app_module._write_config(cfg, "documents_dir", "A", "20260101-000000", why="documents")
    assert app_module._write_config(cfg, "documents_dir", "B", "20260101-000000", why="documents")
    kept = sorted(json.loads(p.read_text("utf-8")).get("documents_dir", "")
                  for p in (apps["Target Receipts"] / "Backups").glob("documents-*/config.json"))
    assert kept == ["", "A"]


def test_the_folder_is_not_saved_while_a_history_file_is_imported(apps, tmp_path):
    app_module._IMPORTING.acquire()
    try:
        with pytest.raises(HTTPException) as e:
            save_root(str(tmp_path / "Drive"))
    finally:
        app_module._IMPORTING.release()
    assert e.value.status_code == 409
    assert app_module._documents_root() == ""


# -- the release reviews of 0.57.0 and 0.57.1 ---------------------------------
#
# A folder of one person's own never holds the folder for every provider,
# saved in either order, since every follower's documents would then be in
# it. The panel fills in a person's folder in it only before a download run,
# so a Move goes where the page said it would. Two writes of one config at
# once keep the first one's copy of the config as it was.

@pytest.mark.parametrize("where", ["just around it", "further up"])
def test_a_folder_of_their_own_never_holds_the_folder_for_every_provider(
        apps, tmp_path, where):
    docs = tmp_path / "Drive" / "Docs" / "PaperPull"
    save_root(str(docs))
    folder = docs.parent if where == "just around it" else tmp_path / "Drive"
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "account": "spouse", "folder": str(folder)})
    assert e.value.status_code == 400 and "holds the Documents folder" in e.value.detail, \
        e.value.detail
    assert config(apps["Chase Statements"], "config.spouse.json")["documents_dir"] == \
        str(docs / "Chase Statements - spouse")


@pytest.mark.parametrize("root", ["the folder itself", "inside it", "deep inside it"])
@pytest.mark.parametrize("others", ["following", "each with a folder of their own"])
def test_the_folder_for_every_provider_is_never_in_a_folder_of_their_own(
        apps, tmp_path, root, others):
    own = tmp_path / "Drive" / "Docs"
    save({"app": "Chase Statements", "account": "spouse", "folder": str(own)})
    if others != "following":
        save({"app": "Chase Statements", "folder": str(tmp_path / "Chase Watched")})
        save({"app": "Target Receipts", "folder": str(tmp_path / "Target Watched")})
    folder = {"the folder itself": own, "inside it": own / "PaperPull",
              "deep inside it": own / "Sync" / "PaperPull"}[root]
    with pytest.raises(HTTPException) as e:
        save_root(str(folder))
    assert e.value.status_code == 400, e.value.detail
    assert "Chase Statements, spouse" in e.value.detail and str(own) in e.value.detail, \
        e.value.detail
    assert app_module._documents_root() == ""
    # A folder for every provider that no folder of their own holds saves.
    assert save_root(str(tmp_path / "Elsewhere"))["documents_root"]


def test_use_it_for_every_provider_replaces_a_folder_holding_it(apps, tmp_path):
    """The folder for every provider saved inside one person's own folder by
    an earlier version. Apply to every account gives that person a folder
    inside it too, so theirs no longer holds it."""
    own = tmp_path / "Drive" / "Docs"
    chase = apps["Chase Statements"]
    save({"app": "Chase Statements", "account": "spouse", "folder": str(own)})
    app_module._write_settings({"documents_root": str(own / "PaperPull")})
    d = save_root(str(own / "PaperPull"), all=True)
    assert d["own"] == [] and d["following"] == 3, d
    assert config(chase, "config.spouse.json")["documents_dir"] == \
        str(own / "PaperPull" / "Chase Statements - spouse")


def test_a_run_gives_no_folder_inside_a_folder_of_their_own(apps, tmp_path):
    """The folder for every provider saved inside one person's own folder by
    an earlier version. A person added since gets no folder in it."""
    own = tmp_path / "Drive" / "Docs"
    chase, target = apps["Chase Statements"], apps["Target Receipts"]
    (chase / "config.spouse.json").write_text(json.dumps({
        "output_dir": "../Chase Statements - spouse", "profile_dir": "spouse-profile",
        "documents_dir": str(own)}), encoding="utf-8")
    app_module._write_settings({"documents_root": str(own / "PaperPull")})
    said = app_module._documents_before_run(app_module.discover_apps(), "Target Receipts",
                                            "primary")
    assert said and said[0].startswith("Documents stay where they were.") and \
        "Chase Statements, spouse" in said[0], said
    assert "documents_dir" not in config(target)
    assert not (target / "Backups").exists()
    # The page says so, rather than promise the folder from their next
    # download.
    got = app_module.api_documents("Target Receipts")
    assert got["follows"] and "Chase Statements, spouse" in got["in_root_refused"], got
    assert app_module.api_documents("Chase Statements", "spouse")["in_root_refused"] == "", \
        "one whose config names a folder is not refused anything"
    # Nor does following it, for anyone but that person.
    with pytest.raises(HTTPException) as e:
        save({"app": "Chase Statements", "follow": True})
    assert "Chase Statements, spouse" in e.value.detail, e.value.detail
    assert save({"app": "Chase Statements", "account": "spouse", "follow": True})["follows"]


@pytest.mark.parametrize("action", [a for a in app_module.ACTIONS
                                    if a not in app_module.DOWNLOAD_ACTIONS])
def test_only_a_download_run_fills_in_the_folder(started, tmp_path, action):
    """A Move, a Rename or any run that downloads nothing goes where the
    config says, which is where the page says. One that moved documents out
    before and was set back to its own folder, which left no setting, is
    told Move brings them back to its own folder, and so it does."""
    (tmp_path / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    app_module._write_settings({"documents_root": str(_drive(tmp_path))})
    out = ran(action)
    assert "event: done\ndata: 0" in out, out
    assert "documents_dir" not in config(tmp_path)
    assert not (tmp_path / "Backups").exists()
    assert str(_drive(tmp_path)) not in out, out


@pytest.mark.parametrize("action", app_module.DOWNLOAD_ACTIONS)
def test_each_download_run_fills_in_the_folder(started, tmp_path, action):
    (tmp_path / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    app_module._write_settings({"documents_root": str(_drive(tmp_path))})
    assert "event: done\ndata: 0" in ran(action)
    assert config(tmp_path)["documents_dir"] == str(_drive(tmp_path) / "Shop Docs")


def test_two_writes_of_one_config_at_once_keep_the_config_as_it_was(apps, monkeypatch):
    """Two writes in one second, the second starting while the first copies
    the config, as a run starting in one tab and a save in another can. The
    second waited for no one and took the first one's Backups folder. Each
    wrote a config read before the other's change, and the copy of the
    config as it was was written over, or taken away with the folder once
    the two tripped over one temporary file and one write failed."""
    import threading
    cfg = apps["Target Receipts"] / "config.json"
    before = config(apps["Target Receipts"])
    copying, second_copies = threading.Event(), threading.Event()
    real_copy = app_module._copy_file

    def copy(src, dst):
        if not copying.is_set():
            copying.set()
            # Held until the second write copies too, which it does at once
            # with nothing to wait for, or for a second if it waits its turn.
            second_copies.wait(1)
        else:
            second_copies.set()
        real_copy(src, dst)
    monkeypatch.setattr(app_module, "_copy_file", copy)
    stamp = "20260101-000000"
    first = threading.Thread(target=app_module._write_config,
                             args=(cfg, "documents_dir", "A", stamp), kwargs={"why": "documents"})
    first.start()
    assert copying.wait(5)
    app_module._write_config(cfg, "filename_pattern", "{date}", stamp, why="documents")
    first.join(5)
    kept = [json.loads(p.read_text("utf-8"))
            for p in (apps["Target Receipts"] / "Backups").glob("documents-*/config.json")]
    assert before in kept, kept
    assert len(kept) == 2
    now = config(apps["Target Receipts"])
    assert now["documents_dir"] == "A" and now["filename_pattern"] == "{date}", now


# -- the fresh review of minors-0571 ------------------------------------------
#
# The fill is asked again of the config as it is written, so a folder of
# their own saved in another tab meanwhile is kept, and every writer of an
# account's config in the panel holds the one lock.

def test_a_folder_saved_in_another_tab_meanwhile_is_kept(apps, tmp_path, monkeypatch):
    """The fill had decided to write before the save landed, and wrote over
    it, so the page said the person's own folder and the run used the folder
    for every provider."""
    docs, mine = tmp_path / "Drive", tmp_path / "Mine"
    app_module._write_settings({"documents_root": str(docs)})
    real = app_module._in_root_problem

    def meanwhile(*args):
        save({"app": "Target Receipts", "folder": str(mine)})
        return real(*args)
    monkeypatch.setattr(app_module, "_in_root_problem", meanwhile)
    missed = []
    assert app_module._sync_documents(app_module.discover_apps(), str(docs),
                                      only=("Target Receipts", "primary"), missed=missed) == 0
    assert config(apps["Target Receipts"])["documents_dir"] == str(mine)
    assert missed == [], "a choice kept is not a config that could not be written"


def test_every_writer_of_a_config_holds_the_one_lock(apps, tmp_path, monkeypatch):
    from types import SimpleNamespace
    target = apps["Target Receipts"]
    cfg = target / "config.json"
    (target / "config.example.json").write_text(json.dumps({"output_dir": ".", "new": 1}),
                                                encoding="utf-8")
    held = []
    for name in ("_write_text", "_replace_text"):
        real = getattr(app_module, name)

        def wrote(path, text, real=real):
            held.append(app_module._CONFIG_WRITES.locked())
            real(path, text)
        monkeypatch.setattr(app_module, name, wrote)
    app_module._set_profile(cfg, "kept-profile")
    app_module._set_owner(cfg, "Dana Example")
    assert app_module.ensure_settings(target, "t") == ["new"]
    migrate = SimpleNamespace(settings_to_apply=lambda install, cfg, settings,
                              check_pattern=None: {"browser": "bundled"})
    app_module._apply_settings(migrate, cfg, target, {"browser": "bundled"})
    assert app_module._write_config(cfg, "documents_dir", str(tmp_path / "W"), "t", why="documents")
    now = config(target)
    assert (now["profile_dir"], now["owner"], now["new"], now["browser"]) == \
        ("kept-profile", "Dana Example", 1, "bundled")
    assert held == [True] * 5, held
    assert not app_module._CONFIG_WRITES.locked()


def test_a_folder_spelled_in_other_letter_case_is_judged_as_the_disk_holds_it(tmp_path):
    """On a Mac resolve() keeps the spelling given, so "target receipts" was
    never inside "Target Receipts" there, though the two are one folder. A
    Mac's and Windows' names are told apart without case, and elsewhere as
    the disk holds them, as Linux's tells "target receipts" apart."""
    (tmp_path / "Target Receipts").mkdir()
    # Windows tells names apart without case, as the panel does
    # (app._in_root_name). A Mac does as its disk does, which is most often
    # without case and can be with it. Elsewhere names are as spelled.
    one_folder = sys.platform == "win32" or (
        sys.platform == "darwin" and (tmp_path / "target receipts").exists())
    inside = tmp_path / "target receipts" / "Chase"
    assert app_module._within(inside, tmp_path / "Target Receipts") is one_folder
    assert app_module._within(tmp_path / "target receipts", tmp_path / "Target Receipts") is one_folder
    assert app_module._within(tmp_path / "Target Receipts" / "Chase", tmp_path / "Target Receipts")
    assert not app_module._within(tmp_path / "Target Receiptsx" / "Chase", tmp_path / "Target Receipts")
    assert not app_module._within(tmp_path / "Target Receipts", tmp_path / "Target Receipts" / "Chase")


def _tells_case_apart(folder: Path) -> bool:
    """Whether a folder tells letter case apart, as a Mac's disk can be
    formatted to and Linux's do."""
    probe = folder / "Probe"
    probe.mkdir()
    try:
        return not (folder / "probe").exists()
    finally:
        probe.rmdir()


def _made_to_tell_case_apart(folder: Path) -> bool:
    """_tells_case_apart, made so on Windows where it can be (fsutil, a
    folder at a time, and the folders made in it after)."""
    if _tells_case_apart(folder) or sys.platform != "win32":
        return _tells_case_apart(folder)
    import subprocess
    try:
        subprocess.run(["fsutil.exe", "file", "setCaseSensitiveInfo", str(folder), "enable"],
                       capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return _tells_case_apart(folder)


def test_a_disk_without_case_holds_two_spellings_as_one_folder(tmp_path):
    """On a Mac a step of a path spelled as another account's folder is in
    other letter case is that folder when the disk finds it so. A folder
    not made yet is judged by the folder it would be made in."""
    if _tells_case_apart(tmp_path):
        pytest.skip("this disk tells letter case apart")
    (tmp_path / "Drive" / "Target Receipts").mkdir(parents=True)
    drive = tmp_path / "Drive"
    assert app_module._one_folder(drive / "target receipts", drive / "Target Receipts")
    assert app_module._one_folder(tmp_path / "drive" / "TARGET RECEIPTS", drive / "Target Receipts")
    # Neither made yet, in a folder whose names are found in either case.
    assert app_module._one_folder(drive / "gap receipts", drive / "Gap Receipts")
    # A folder holding nothing cannot say, and the two are taken as one.
    (tmp_path / "Empty").mkdir()
    assert app_module._one_folder(tmp_path / "Empty" / "a b", tmp_path / "Empty" / "A B")


def test_a_disk_that_tells_case_apart_holds_two_spellings_as_two_folders(tmp_path):
    """A Mac's disk formatted to tell case apart has "target receipts" and
    "Target Receipts" as two folders, and the panel lets one account have
    the one beside another's, as it does on Linux."""
    folder = tmp_path / "cs"
    folder.mkdir()
    if not _made_to_tell_case_apart(folder):
        pytest.skip("no folder here can be made to tell letter case apart")
    (folder / "Target Receipts").mkdir()
    # Not made in the other spelling, which a disk without case would find.
    assert not app_module._one_folder(folder / "target receipts", folder / "Target Receipts")
    assert not app_module._one_folder(folder / "target receipts" / "Chase",
                                      folder / "Target Receipts" / "Chase")
    # Made in both spellings, two folders.
    (folder / "target receipts").mkdir()
    assert not app_module._one_folder(folder / "target receipts", folder / "Target Receipts")
    # Neither made, in a folder that tells the names already in it apart.
    assert not app_module._one_folder(folder / "gap receipts", folder / "Gap Receipts")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows paths compare without case before any disk is asked")
def test_on_a_mac_a_folder_in_other_letter_case_is_judged_by_the_disk(tmp_path, monkeypatch):
    """_within on a Mac, wherever the suite runs on a POSIX disk."""
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    (tmp_path / "Target Receipts").mkdir()
    one = (tmp_path / "target receipts").exists()
    assert app_module._within(tmp_path / "target receipts" / "Chase", tmp_path / "Target Receipts") is one
    assert app_module._within(tmp_path / "TARGET RECEIPTS", tmp_path / "Target Receipts") is one
    assert not app_module._within(tmp_path / "target receiptsx", tmp_path / "Target Receipts")
