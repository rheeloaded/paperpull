"""Download again, which the panel offers as Restore deleted files.

Every app takes --redownload, which makes it fetch every document in scope
again, the ones it already downloaded included, and save each beside the
file already there. The panel adds it to a Pilot or a Run All only, only
with a year or dates chosen, and only when the request carries the answer
to the dialog that asks for it. Both arrive as JSON true in a POST body,
never as text, and what reaches the app is that one flag. Nothing else a
body holds can reach a command line, and without the request the flag
never appears.

Most of this asks the run endpoints directly, with a stand-in for the app's
process that keeps the command it was handed. The page part reads the
page's script, and the last part serves the real panel on a free local
port, as test_server_mode.py does, and runs a real app script that writes
down the arguments it was started with.
"""
import asyncio
import io
import json
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")

FLAG = "--redownload"
# The two scopes a run that downloads again may have, a year or both ends of
# a range. One date alone is open at its other end.
SCOPES = [({"year": "2025"}, ["--year", "2025"]),
          ({"start": "2025-01-01", "end": "2025-06-30"},
           ["--start-date", "2025-01-01", "--end-date", "2025-06-30"])]
ONE_END = [{"start": "1990-01-01"}, {"end": "2026-10-06"},
           {"start": "2025-01-01", "end": ""}, {"start": "", "end": "2025-06-30"}]
OTHER_ACTIONS = sorted(set(app_module.ACTIONS) - {"pilot", "all"})


def test_the_panel_says_which_flag_and_which_actions():
    """What the rest of this file, and the census of every app's parser in
    core/tests, hold the panel to."""
    assert app_module.REDOWNLOAD_FLAG == FLAG
    assert app_module.REDOWNLOAD_ACTIONS == ("pilot", "all")
    assert len(OTHER_ACTIONS) == len(app_module.ACTIONS) - 2 >= 7


# -- the run endpoints, asked directly ----------------------------------------------

class Asked:
    """A request as the POST handler reads it, a content type and a body."""

    def __init__(self, body, kind="application/json"):
        self.headers = {"content-type": kind} if kind else {}
        self.body = body

    async def json(self):
        if isinstance(self.body, bytes):
            return json.loads(self.body)
        return self.body


@pytest.fixture()
def started(tmp_path, monkeypatch):
    """Every command the panel starts, kept rather than run. The app is set
    up, so nothing but the request decides what is started."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    venv = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    meta = {"name": "Shop Docs", "dir": str(tmp_path), "script": "shop_docs.py",
            "python": "py", "login_flag": "--login", "accounts": ["primary", "robin"]}
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"Shop Docs": meta})
    commands = []

    class Process:
        def __init__(self, cmd, **kwargs):
            commands.append(list(cmd))
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("a line from the app\n")

        def wait(self, **kwargs):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(app_module.subprocess, "Popen", Process)
    return commands


def post(body, kind="application/json"):
    """(status, what came back) for one POST /api/run, run to its end."""
    async def go():
        try:
            response = await app_module.api_run_body(Asked(body, kind))
        except fastapi.HTTPException as e:
            return e.status_code, str(e.detail)
        return 200, "".join([part async for part in response.body_iterator])
    return asyncio.run(go())


def get(**query):
    """(status, what came back) for one GET /api/run, run to its end."""
    async def go():
        try:
            response = app_module.api_run(**query)
        except fastapi.HTTPException as e:
            return e.status_code, str(e.detail)
        return 200, "".join([part async for part in response.body_iterator])
    return asyncio.run(go())


def again(action="all", scope=None, **more):
    body = {"app": "Shop Docs", "action": action, "redownload": True, "confirmed": True}
    body.update({"year": "2025"} if scope is None else scope)
    body.update(more)
    return body


@pytest.mark.parametrize("action", ["pilot", "all"])
@pytest.mark.parametrize("scope,flags", SCOPES)
def test_a_confirmed_scoped_pilot_or_run_all_gets_the_one_flag(started, action, scope, flags):
    status, out = post(again(action, scope))
    assert status == 200, out
    assert started == [["py", "shop_docs.py", *app_module.ACTIONS[action]["flags"], *flags, FLAG]]
    assert "event: done\ndata: 0" in out


def test_a_second_account_keeps_its_own_config(started):
    status, _ = post(again("pilot", account="robin"))
    assert status == 200
    assert started == [["py", "shop_docs.py", "--pilot", "--year", "2025", FLAG,
                        "--config", "config.robin.json"]]


@pytest.mark.parametrize("action", sorted(app_module.ACTIONS))
@pytest.mark.parametrize("box", ["absent", False])
def test_without_the_box_the_flag_never_appears(started, action, box):
    body = {"app": "Shop Docs", "action": action, "year": "2025", "confirmed": True}
    if box != "absent":
        body["redownload"] = box
    assert post(body)[0] == 200
    assert get(app="Shop Docs", action=action, year="2025")[0] == 200
    assert len(started) == 2
    for cmd in started:
        assert FLAG not in cmd, cmd


@pytest.mark.parametrize("key", ["redownload", "confirmed"])
@pytest.mark.parametrize("value", ["true", "True", "1", "yes", FLAG, 1, 0, None, [], {}, [True]])
def test_a_value_that_is_not_true_or_false_is_refused(started, key, value):
    status, said = post(again(**{key: value}))
    assert status == 400 and "true or false" in said, said
    assert started == []


@pytest.mark.parametrize("key", ["redownload", "confirmed"])
@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_such_a_value_is_refused_without_the_box_too(started, key, value):
    """Not just ignored when nothing else asks to download again."""
    body = {"app": "Shop Docs", "action": "all", "year": "2025", key: value}
    status, said = post(body)
    assert status == 400 and "true or false" in said, said
    assert started == []


@pytest.mark.parametrize("extra", [
    {"flags": [FLAG]}, {"args": FLAG}, {"redownload_flag": FLAG}, {"argv": ["--all"]},
    {"config": "config.robin.json"}, {"REDOWNLOAD": True}, {"": ""}, {"yes": True}])
def test_a_field_the_page_never_sends_is_refused(started, extra):
    status, said = post(again(**extra))
    assert status == 400 and "holds only" in said, said
    assert started == []


@pytest.mark.parametrize("field,value", [("app", 1), ("action", ["all"]), ("account", None),
                                         ("year", 2025), ("start", {"a": 1}), ("end", True)])
def test_a_text_field_of_another_kind_is_refused(started, field, value):
    """By the check of its kind, not by a later check that happens to
    refuse it too, as an unknown account or action would be."""
    status, said = post(again(**{field: value}))
    assert (status, said) == (400, "%s is text" % field)
    assert started == []


@pytest.mark.parametrize("body", [[again()], "redownload", 1, None, True])
def test_a_body_that_is_not_an_object_is_refused(started, body):
    assert post(body)[0] == 400
    assert started == []


def test_a_body_that_is_not_json_is_refused(started):
    assert post(b'{"app": "Shop Docs", "action": "all",')[0] == 400
    assert post(json.dumps(again()).encode(), kind="text/plain")[0] == 415
    assert post(again(), kind="")[0] == 415
    assert started == []


@pytest.mark.parametrize("action", OTHER_ACTIONS)
def test_any_other_action_is_refused(started, action):
    status, said = post(again(action))
    assert status == 400 and "Pilot and Run All" in said, said
    assert started == []


@pytest.mark.parametrize("action", ["pilot", "all"])
@pytest.mark.parametrize("scope", [{}, {"year": "", "start": "", "end": ""}, {"year": "  "}])
def test_no_scope_is_refused(started, action, scope):
    status, said = post(again(action, scope))
    assert status == 400 and "a year, or both a From and a To date" in said, said
    assert started == []


@pytest.mark.parametrize("action", ["pilot", "all"])
@pytest.mark.parametrize("scope", ONE_END)
def test_one_end_of_a_range_is_refused(started, action, scope):
    """From 1990 alone, or To today alone, is a whole history."""
    status, said = post(again(action, scope))
    assert status == 400 and "a year, or both a From and a To date" in said, said
    assert started == []
    # Without the box the same scope is an ordinary run, as it always was.
    body = dict(again(action, scope), redownload=False)
    assert post(body)[0] == 200 and len(started) == 1 and FLAG not in started[0]


def test_the_apps_are_found_off_the_event_loop(started, monkeypatch):
    """Finding the apps reads every install's folder. The POST handler is a
    coroutine, so done there it would hold up every other request, and the
    GET handler, a plain function, is already run in the threadpool."""
    seen = []
    found = app_module.discover_apps
    monkeypatch.setattr(app_module, "discover_apps",
                        lambda: seen.append(threading.current_thread()) or found())
    assert post(again("all"))[0] == 200
    assert seen and seen[0] is not threading.main_thread(), seen


@pytest.mark.parametrize("action", ["pilot", "all"])
@pytest.mark.parametrize("confirmation", ["absent", False])
def test_no_confirmation_is_refused(started, action, confirmation):
    body = again(action)
    if confirmation == "absent":
        del body["confirmed"]
    else:
        body["confirmed"] = confirmation
    status, said = post(body)
    assert status == 400 and "question" in said, said
    assert started == []


@pytest.mark.parametrize("query", [{"redownload": "1"}, {"redownload": "true"},
                                   {"redownload": ""}, {"confirmed": "true"},
                                   {"redownload": "1", "confirmed": "1"}])
def test_an_address_that_asks_for_it_is_refused(started, query):
    """A GET carries text, so it never downloads again, and it says so
    rather than run an ordinary run that skips everything."""
    status, said = get(app="Shop Docs", action="all", year="2025", **query)
    assert status == 400 and "POST body" in said, said
    assert started == []


def test_paperpull_server_does_not_offer_it(started, monkeypatch):
    """A run there hands every file it saves to the plug-ins, and the
    Paperless one would copy each document into Paperless a second time."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    status, said = post(again("all"))
    assert status == 404 and "PaperPull Server" in said, said
    assert started == []
    assert post({"app": "Shop Docs", "action": "all", "year": "2025"})[0] == 200
    assert started and FLAG not in started[0]


# -- the command builder, the last word on the command line ------------------------

META = {"python": "py", "script": "x_docs.py", "login_flag": "--login",
        "accounts": ["primary", "robin"], "dir": "."}


@pytest.mark.parametrize("action", OTHER_ACTIONS)
def test_the_builder_will_not_put_it_on_another_action(action):
    with pytest.raises(ValueError):
        app_module._build_cmd(META, "primary", action, ["--year", "2025"], True)


@pytest.mark.parametrize("value", ["true", 1, None, [FLAG]])
def test_the_builder_takes_true_or_false_only(value):
    with pytest.raises(ValueError):
        app_module._build_cmd(META, "primary", "all", ["--year", "2025"], value)


def test_the_builder_adds_the_flag_once_after_the_scope():
    assert app_module._build_cmd(META, "robin", "all", ["--year", "2025"], True) == \
        ["py", "x_docs.py", "--all", "--yes", "--year", "2025", FLAG,
         "--config", "config.robin.json"]
    assert app_module._build_cmd(META, "primary", "all", ["--year", "2025"]) == \
        ["py", "x_docs.py", "--all", "--yes", "--year", "2025"]


# -- the page ----------------------------------------------------------------------

def page() -> str:
    html = app_module.index()
    return html.body.decode("utf-8") if hasattr(html, "body") else str(html)


def function(name: str) -> str:
    """One function of the page's script, from its name to the brace that
    closes its body."""
    body = page()
    start = re.search(r"\n(?:async )?function %s\(" % name, body).start()
    depth, i = 0, body.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(body[i], 0)
        if depth == 0:
            return body[start:i + 1]
        i += 1


def _dialog(body: str) -> str:
    start = body.index('<dialog id="dlg-restore"')
    return " ".join(body[start:body.index("</dialog>", start)].split())


def test_it_is_a_dialog_of_its_own_never_a_box_on_the_everyday_path():
    """Download again was a box beside the dates that changed what the next
    Pilot or Run All did, so a run could download again by surprise. It is
    Restore deleted files now, a dialog of its own, and Get new documents
    never downloads again."""
    body = page()
    assert 'id="again"' not in body and "<dialog id=\"dlg-restore\"" in body
    script = body[body.index("<script>"):]
    # Asked for in one place, the dialog's own button, and sent in one.
    assert script.count("redownload: true") == 2
    go = function("rsGo")
    assert "if (!startRun(DLG_ROW, how, {scope: s, redownload: true})) {" in go
    # The dialog closes only once the run started, so a refusal is said in it.
    assert go.index("startRun(") < go.index("$('dlg-restore').close();")
    assert "const again = opts.redownload === true;" in function("startRun")


def test_it_starts_fresh_each_time_and_is_never_remembered():
    body = page()
    script = body[body.index("<script>"):]
    keys = set(re.findall(r"store\.(?:get|set)\('([^']+)'", script))
    assert keys == {"scope", "theme"}, keys
    opened = function("openRestore")
    for reset in ("el.checked = el.value === 'year'", "el.checked = el.value === 'all'",
                  "$('rs-start').value = ''", "$('rs-end').value = ''", "showModal()"):
        assert reset in opened, reset
    # The everyday path's dates never reach it, it has its own.
    scope = function("rsScope")
    assert "rs-year" in scope and "scopeValues" not in scope and "scopeSaved" not in scope
    # Brought back from the back and forward cache, the page starts again.
    assert "addEventListener('pageshow', e => { if (e.persisted) location.reload(); })" in script


def test_a_year_or_both_ends_are_needed_on_the_page_first():
    go = function("rsGo")
    check = go.index("if (!againScoped(s))")
    assert check < go.index("startRun(") and check < go.index(".close()")
    assert "Choose a year, or both a From and a To date." in go
    assert "s.start > s.end" in go
    assert "return Boolean(s.year || (s.start && s.end));" in function("againScoped")
    # And the run itself refuses it again, whoever asks.
    assert ("if (again && (SERVER || !againScoped(s) || "
            "!(META.redownload_actions || []).includes(action))) return false;") in function("startRun")


def test_it_is_sent_only_in_a_post_body_with_the_agreement():
    run = function("startRun")
    assert run.count("redownload: true") == 1 and run.count("confirmed: true") == 1
    assert "again ? postRun(Object.assign({ app, account, action, redownload: true, confirmed: true }" in \
        " ".join(run.split())
    assert "/api/run?" in run and "redownload" not in run[run.index("new EventSource("):]


def test_the_dialog_says_what_happens():
    dialog = _dialog(page())
    for words in ("PaperPull remembers every document it saved, so it never downloads one twice",
                  "Restore fetches the missing ones again, for the dates you pick",
                  "the ones already downloaded included, and fetches again each one whose file is gone",
                  "Nothing is overwritten.", "A file you still have stays as it is",
                  "the app may save a second copy beside it, under a name of its own",
                  "The provider is asked again for each document fetched",
                  "For this run only.", "Continue never restores",
                  "A year, or both a From and a To date, is needed"):
        assert words in dialog, words
    # True of every app, Target's invoices still on file included, so it
    # promises no new copy of every document.
    assert "new copy" not in dialog and "Each new" not in dialog
    assert 'value="all" checked' in dialog and 'value="pilot" checked' not in dialog


def test_a_restore_that_ends_early_says_continue_will_not_download_again():
    """Continue never downloads again, so it would skip the rest of the range
    and then call the run finished with no issues."""
    body = " ".join(page().split())
    left = re.search(r"const AGAIN_LEFT = (.*?);", body).group(1)
    for words in ("Continue will not download again",
                  "restoring the same dates again ' + 'fetches again what this run already restored",
                  "so choose the dates that are left"):
        assert words in left, words
    outcome = " ".join(function("runOutcome").split())
    # Every way a run can end without finishing says it, and offers Continue
    # only to a run that downloads and was not a restore.
    assert "const next = RUN.again ? AGAIN_LEFT :" in outcome
    assert "const downloads = ['pilot', 'all', 'resume'].includes(RUN.action) && !RUN.again;" in outcome
    assert outcome.count("+ next + '.'") + outcome.count("say: next + '.'") >= 4
    assert outcome.count("resume: downloads") == 5 and "resume: !RUN.again" not in outcome
    assert "say: RUN.again ? AGAIN_LEFT + '.'" in outcome
    assert "if (RUN.again && !RUN.outcome.clean && RUN.sink)" in function("finishRun")
    # A row whose last run was a restore that stopped offers the rest of the
    # restore, never Continue, and a round of Get new for all leaves it out.
    # Where Restore is not offered, the server and the sample, the row opens
    # the account rather than show a button that would do nothing.
    present = " ".join(function("present").split())
    assert ("const restore = SERVER || inSample() ? {label: 'Open', nav: true} : "
            "{label: 'Restore the rest', dialog: 'restore', primary: true};") in present
    assert "act: again ? restore : {label: 'Continue', run: 'resume', primary: true}" in present
    assert "!(r.last_run && r.last_run.redownload)" in function("queueTargets")
    account = " ".join(function("renderAccount").split())
    assert "const again = r.state === 'stopped' && Boolean(r.last_run && r.last_run.redownload);" in account
    assert "const stoppedHere = continues(r) && !again;" in account
    assert "(again && !SERVER && !inSample() ?" in account


def test_a_refusal_is_shown_rather_than_a_lost_connection():
    assert "es.refused" in function("startRun")
    assert "d.detail" in function("postRun")
    assert ("if (RUN.refused) return {tone: 'bad', title: 'This run did not start', say: RUN.refused"
            in " ".join(function("runOutcome").split()))


def test_the_server_page_does_not_offer_it():
    assert "if (!SERVER) html += menuItem('restore'" in function("openMenu")
    assert "if (SERVER || inSample()) return;" in function("openRestore")


def test_the_safe_to_rerun_note_names_the_way_back():
    text = " ".join(function("renderAccount").split())
    assert "nothing is ever downloaded twice, even if you deleted the PDFs" in text
    assert "To get deleted files back, use Restore deleted files under More." in text


def test_the_page_and_the_server_name_the_same_actions():
    """The page reads which actions take the box from /api/apps."""
    assert '"redownload_actions": list(REDOWNLOAD_ACTIONS)' in \
        Path(app_module.__file__).read_text(encoding="utf-8")


# -- the real panel, over HTTP, with a real app -------------------------------------

RECORDER = '''
import json, sys
from pathlib import Path
with open(Path(__file__).resolve().parent / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
print('PAPERPULL_RUN_RESULT {"new_files": 0, "failed": 0}')
'''


@pytest.fixture(scope="module")
def base():
    """The panel, served on a free local port for the whole module."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Asked until it says so, for up to thirty seconds, since a machine
    # running a whole suite can be slow to start anything.
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """An apps root of its own holding one app, a script that writes down
    the arguments it was started with. Every setting is under tmp_path."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    # Run with this Python, the way the packaged build runs every app.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    folder = tmp_path / "apps" / "Shop Docs"
    folder.mkdir(parents=True)
    (folder / "shop_docs.py").write_text(RECORDER, encoding="utf-8")
    return folder


def ask(url, method="GET", body=None, kind="application/json", headers=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None and kind:
        req.add_header("Content-Type", kind)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def arguments(folder):
    listed = folder / "argv.jsonl"
    if not listed.exists():
        return []
    return [json.loads(line) for line in listed.read_text(encoding="utf-8").splitlines()]


def test_the_app_is_started_with_the_flag_once(base, shop):
    status, out = ask(base + "/api/run", "POST", again("all", {"start": "2024-01-01", "end": "2024-12-31"}))
    assert status == 200 and "event: done\ndata: 0" in out, out
    assert arguments(shop) == [["--all", "--yes", "--start-date", "2024-01-01",
                                "--end-date", "2024-12-31", FLAG]]


def test_over_http_the_box_is_all_that_adds_it(base, shop):
    assert ask(base + "/api/run", "POST", {"app": "Shop Docs", "action": "pilot",
                                           "year": "2024"})[0] == 200
    assert ask(base + "/api/run?app=Shop%20Docs&action=pilot&year=2024")[0] == 200
    assert arguments(shop) == [["--pilot", "--year", "2024"], ["--pilot", "--year", "2024"]]


def test_over_http_nothing_starts_on_a_refusal(base, shop):
    refused = [
        ask(base + "/api/run", "POST", again("all", {})),
        ask(base + "/api/run", "POST", again("resume")),
        ask(base + "/api/run", "POST", again("all", confirmed=False)),
        ask(base + "/api/run", "POST", again("all", redownload="true")),
        ask(base + "/api/run", "POST", again("all", flags=[FLAG])),
        ask(base + "/api/run", "POST", json.dumps(again("all")).encode(), kind="text/plain"),
        ask(base + "/api/run?app=Shop%20Docs&action=all&year=2024&redownload=1"),
        # Another site's page, which the panel refuses whatever it asks.
        ask(base + "/api/run", "POST", again("all"), headers={"Sec-Fetch-Site": "cross-site"}),
        ask(base + "/api/run", "POST", again("all"), headers={"Origin": "https://example.com"}),
    ]
    assert [status for status, _ in refused] == [400, 400, 400, 400, 400, 415, 400, 403, 403], refused
    assert arguments(shop) == []
