"""A Wells Fargo run of the accounts its setting names, and no other (#221).

A tester's sign-in holds business and personal accounts in one picker. They
asked for a Pilot, and every other run, that reads ONE chosen account and
never another account's list. So config.json takes "only_accounts", a list
of masked last fours. Empty, or missing, is every account, as before. Set,
the picker is read before anything is expanded, scrolled or surveyed, only
the chosen entries are pressed, and each is proven shown, strictly, before
its list is read, after, and once more just before its PDF is fetched or
pressed. A setting that names an account the picker does not hold, or that
is not a last four, stops the run before anything is read.

Two gaps on main were found while planning it and are closed for every
run. There was no check of the account the picker shows between finding a
document's control and pressing it or fetching its link, and the check
that was made took a picker showing no account's words as showing the
right one.

Everything here is invented. The page is the made-up Statements &
Documents page of test_statements_and_documents_page.py, with a log of the
entries pressed, a "Show older statements" button per account, and a way
for the page to move the picker by itself.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import wellsfargo_docs as app_mod  # noqa: E402
import wellsfargo_site as site  # noqa: E402
from paperpull_core import listing, pressing  # noqa: E402
from paperpull_core.testkit import receipt_app, text_pdf  # noqa: E402

import test_statements_and_documents_page as base  # noqa: E402
from test_statements_and_documents_page import browser, quick  # noqa: F401,E402

# The real expand and scroll, kept before the autouse fixture stands in.
REAL_EXPAND = site.expand_all
REAL_SCROLL = site.scroll_full_page

EDOCS = base.EDOCS
A = "Business Checking A ...1111"
B = "Business Checking B ...2222"
P = "Personal Checking ...3333"

# The made-up page, with what these tests watch added to it.
PAGE = (base.EDOCS_PAGE
        .replace("window.pressed = []; window.headPresses = 0; window.lists = 0;",
                 "window.pressed = []; window.headPresses = 0; window.lists = 0;"
                 " window.optionPresses = []; window.olderPresses = []; const olderOpen = {};")
        .replace("const i = +li.dataset.i, a = CFG.accounts[i];",
                 "const i = +li.dataset.i, a = CFG.accounts[i]; window.optionPresses.push(a.id);")
        .replace("current = i; render(); return;",
                 "current = i; render();"
                 " if (CFG.moveAfter && (a.id in CFG.moveAfter)) window.moveTo(CFG.moveAfter[a.id]);"
                 " return;")
        .replace("if (CFG.expanded) {", r"""
// The page moves the picker by itself, to account `m`, or with m < 0 to
// show no account's words. "inplace" keeps the list's own elements and
// gives them the other account's documents, as a page drawing its list
// again over the same elements does.
window.moveTo = (m, how) => {
  const shown = document.getElementById('shown');
  if (m < 0) { shown.textContent = ''; return; }
  current = m;
  if (how !== 'inplace') { render(); return; }
  const acct = CFG.accounts[m]; shown.textContent = acct.label;
  [...document.querySelectorAll('#docs a[role=link]')].forEach((a, k) => {
    const d = acct.docs[k] || acct.docs[0];
    a.dataset.doc = acct.id + ':' + d; a.textContent = 'Statement ' + d + ' (123K, PDF)'; });
};
const drawList = render;
render = function () {
  drawList();
  if (!CFG.older) return;
  const acct = CFG.accounts[current];
  if (olderOpen[acct.id]) return;
  const b = document.createElement('button'); b.type = 'button';
  b.textContent = 'Show older statements';
  b.addEventListener('click', () => {
    window.olderPresses.push(acct.id); olderOpen[acct.id] = true; b.remove();
    if (CFG.moveOnOlder && CFG.moveOnOlder[acct.id] !== undefined)
      window.moveTo(CFG.moveOnOlder[acct.id]);
  });
  document.getElementById('docs').appendChild(b);
};
if (CFG.expanded) {"""))


class Site(base.Site):
    def __init__(self, accounts, older=False, move_after=None, move_on_older=None, **kw):
        super().__init__(accounts, **kw)
        self.cfg.update({"older": older, "moveAfter": move_after or {},
                         "moveOnOlder": move_on_older or {}})

    def handle(self, route):
        parts = base.urlsplit(route.request.url)
        if route.request.method == "GET" and parts.path == "/edocs/documents":
            return route.fulfill(content_type="text/html",
                                 body=PAGE.replace("__CFG__", json.dumps(self.cfg)))
        return super().handle(route)


def _three(**kw):
    """The tester's case, A shown by default."""
    return Site([base._account(A, ["09/30/26", "07/31/26"]),
                 base._account(B, ["09/30/26", "08/31/26"]),
                 base._account(P, ["09/15/26"])], **kw)


@pytest.fixture
def open_site(browser):  # noqa: F811
    contexts = []

    def opener(fake, url=EDOCS):
        ctx = browser.new_context()
        contexts.append(ctx)
        ctx.route("**/*", fake.handle)
        pg = ctx.new_page()
        pg.goto(url)
        fake.navigations.clear()
        return pg
    yield opener
    for ctx in contexts:
        ctx.close()


def _shown(pg) -> str:
    try:
        return pg.evaluate("document.getElementById('shown').textContent")
    except Exception:
        return "?"


@pytest.fixture
def spies(monkeypatch):
    """The account the picker showed at each expand, scroll and survey."""
    seen = {"expand": [], "scroll": [], "survey": []}
    survey = site._survey

    def expand(pg):
        seen["expand"].append(_shown(pg))

    def scroll(pg, *a, **k):
        seen["scroll"].append(_shown(pg))

    def look(pg):
        seen["survey"].append(_shown(pg))
        return survey(pg)
    monkeypatch.setattr(site, "expand_all", expand)
    monkeypatch.setattr(site, "scroll_full_page", scroll)
    monkeypatch.setattr(site, "_survey", look)
    return seen


def _account_posts(fake):
    return [p for p in fake.posts if "/account/" in p]


def _listed(docs):
    return sorted((d.account, d.date_text) for d in docs)


# -- the setting -----------------------------------------------------------------

@pytest.mark.parametrize("value", [["2222"], ["...2222"], ["*2222"], ["****2222"], ["x2222"],
                                   [" ...2222 "], ["X2222"], ["***2222"], ["\u20262222"],
                                   ["2222", "...2222"]])
def test_a_last_four_is_read_in_each_form_it_is_written(value):
    assert app_mod.read_only_accounts(value) == ["2222"]


@pytest.mark.parametrize("value", [None, []])
def test_no_setting_is_every_account(value):
    assert app_mod.read_only_accounts(value) == []


BAD = [["22"], ["98765"], ["Zebra Account"], ["Zebra Account ...2222"], [2222], [2222.0],
       [True], [None], [["2222"]], [{"tail": "2222"}], "2222", 2222, {"2222": True}, True,
       [""], ["   "], ["2222", ""], ["\uff12\uff12\uff12\uff12"], ["\u0662\u0662\u0662\u0662"],
       ["2222\n"], ["22 22"], ["-2222"], ["2222x"], ["1e3"]]


@pytest.mark.parametrize("value", BAD, ids=[repr(v) for v in BAD])
def test_a_setting_that_is_not_a_list_of_last_fours_stops(value):
    with pytest.raises(pressing.Stop) as stop:
        app_mod.read_only_accounts(value)
    said = " ".join(stop.value.lines) + " " + json.dumps(stop.value.facts)
    assert "only_accounts" in said
    for word in ("98765", "Zebra", "2222"):
        assert word not in said


def _config(tmp_path, **settings):
    example = json.loads((Path(app_mod.__file__).parent / "config.example.json")
                         .read_text(encoding="utf-8"))
    example.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                    "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                    "delay_min_seconds": 0, "delay_max_seconds": 0, **settings})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(example), encoding="utf-8")
    return cfg


@pytest.mark.parametrize("command", [["--discover"], ["--pilot"], ["--all", "--yes"],
                                     ["--resume"], ["--diagnose"]])
@pytest.mark.parametrize("value", [["98765"], ["Zebra Account"], "2222"])
def test_a_malformed_setting_stops_before_the_browser_is_asked_anything(
        tmp_path, monkeypatch, capsys, command, value):
    cfg = _config(tmp_path, only_accounts=value)

    def touched(self, *a, **k):
        raise AssertionError("the browser was asked for")
    monkeypatch.setattr(app_mod.App, "page", touched)
    monkeypatch.setattr(app_mod.App, "browser", touched)
    with pytest.raises(SystemExit):
        app_mod.main(["--config", str(cfg)] + command)
    out = capsys.readouterr()
    said = out.out + out.err
    assert "only_accounts" in said
    written = "".join(p.read_text(encoding="utf-8", errors="replace")
                      for p in (tmp_path / "out").rglob("*") if p.is_file()
                      and p.suffix in (".json", ".log", ".txt"))
    for word in ("98765", "Zebra"):
        assert word not in said and word not in written
    # No listing was begun, and nothing was recorded.
    assert not (tmp_path / "out" / "last-listing.json").exists()
    for name in ("discovery.json", "progress.json"):
        held = tmp_path / "out" / name
        assert not held.exists() or json.loads(held.read_text(encoding="utf-8") or "{}") == {}


def test_a_good_setting_reads_as_the_template_ships_it():
    example = json.loads((Path(app_mod.__file__).parent / "config.example.json")
                         .read_text(encoding="utf-8"))
    assert example["only_accounts"] == []


# -- choosing reads only the chosen account ------------------------------------------

def test_choosing_b_reads_b_alone_and_never_touches_a(open_site, spies):
    """The tester's case. A is the account the page shows by default."""
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=["2222"])
    assert _listed(docs) == [(B, "2026-08-31"), (B, "2026-09-30")]
    assert fake.posts == ["/edocs/documents/statement/list",
                          "/edocs/documents/statement/list/account/a2222/period/default"]
    assert pg.evaluate("window.optionPresses") == ["a2222"]
    assert spies["survey"] == [B]
    assert set(spies["expand"]) == {B} and set(spies["scroll"]) == {B}


def test_nothing_of_the_default_account_is_expanded(open_site, monkeypatch):
    """The real expand, with a Show older button in each account's list."""
    monkeypatch.setattr(site, "expand_all", REAL_EXPAND)
    fake = _three(older=True)
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=["2222"])
    assert _listed(docs) == [(B, "2026-08-31"), (B, "2026-09-30")]
    assert pg.evaluate("window.olderPresses") == ["a2222"]


def test_two_chosen_are_read_in_picker_order(open_site, spies):
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=["3333", "2222"])
    assert [d.account for d in docs] == [B, B, P]
    assert pg.evaluate("window.optionPresses") == ["a2222", "a3333"]
    assert spies["survey"] == [B, P]


def test_the_default_account_chosen_presses_no_entry(open_site, spies):
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=["1111"])
    assert _listed(docs) == [(A, "2026-07-31"), (A, "2026-09-30")]
    assert pg.evaluate("window.optionPresses") == []
    assert spies["survey"] == [A]


def _stops_before_any_list(fake, pg, spies, only):
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg, only=only)
    assert _account_posts(fake) == []
    assert pg.evaluate("window.optionPresses") == []
    assert spies["expand"] == spies["scroll"] == spies["survey"] == []
    said = " ".join(stop.value.lines) + json.dumps(stop.value.facts)
    for word in ("1111", "2222", "3333", "4444", "5555", "Business", "Personal", "Payroll"):
        assert word not in said, word
    return stop.value


def test_an_account_the_picker_does_not_hold_stops_before_any_list(open_site, spies):
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    stop = _stops_before_any_list(fake, pg, spies, ["4444"])
    assert stop.reason == "the setting names an account the picker does not hold"


def test_a_last_four_two_entries_share_stops_before_any_list(open_site, spies):
    fake = Site([base._account(A, ["09/30/26"]),
                 base._account(B, ["09/30/26"], "b1"),
                 base._account("Personal Checking ...2222", ["09/30/26"], "b2")])
    pg = open_site(fake)
    assert site.goto_documents(pg)
    _stops_before_any_list(fake, pg, spies, ["2222"])


def test_a_nickname_holding_the_digits_is_never_chosen(open_site, spies):
    fake = Site([base._account(A, ["09/30/26"]),
                 base._account("Payroll 2222 ...5555", ["08/31/26"]),
                 base._account(B, ["07/31/26"])])
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=["2222"])
    assert _listed(docs) == [(B, "2026-07-31")]
    assert pg.evaluate("window.optionPresses") == ["a2222"]


@pytest.mark.parametrize("accounts", [[], [base._account(B, ["09/30/26"])]],
                         ids=["no picker", "a picker of one"])
def test_the_setting_on_a_sign_in_of_one_account_stops_with_a_sentence(open_site, spies,
                                                                         accounts):
    fake = Site(accounts or [base._account(B, ["09/30/26"])])
    pg = open_site(fake)
    assert site.goto_documents(pg)
    if not accounts:
        # A page whose section holds no picker at all.
        pg.evaluate("document.getElementById('box').remove()")
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg, only=["2222"])
    assert stop.value.reason == "the setting is set and the page shows one account"
    assert "leave only_accounts empty" in " ".join(stop.value.lines)
    assert "could not be read" in " ".join(stop.value.lines)
    assert spies["survey"] == []


def test_the_key_of_a_chosen_document_is_the_one_every_account_gives_it(open_site):
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    every = site.collect_download_docs(pg)
    pg2 = open_site(_three())
    assert site.goto_documents(pg2)
    chosen = site.collect_download_docs(pg2, only=["2222"])

    def keyed(docs):
        return {app_mod.Document(category="Statement", date=d.date_text, title=d.title,
                                 account=d.account).key: (d.title, d.account) for d in docs}
    assert keyed(chosen).items() <= keyed(every).items()
    assert len(keyed(chosen)) == 2


def test_with_the_setting_empty_every_account_is_read_as_before(open_site, spies):
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    docs = site.collect_download_docs(pg, only=[])
    assert _listed(docs) == sorted([(A, "2026-09-30"), (A, "2026-07-31"), (B, "2026-09-30"),
                                    (B, "2026-08-31"), (P, "2026-09-15")])
    # A is shown already, so only B and P are pressed, as on main.
    assert pg.evaluate("window.optionPresses") == ["a2222", "a3333"]


# -- the picker moves while a chosen list is read ------------------------------------

@pytest.mark.parametrize("move", [0, -1], ids=["to A", "to no words"])
def test_a_picker_that_moves_after_the_answer_stops_with_nothing_read(open_site, spies, move):
    fake = _three(move_after={"a2222": move})
    pg = open_site(fake)
    assert site.goto_documents(pg)
    with pytest.raises(pressing.Stop):
        site.collect_download_docs(pg, only=["2222"])
    assert spies["survey"] == []
    assert spies["expand"] == []


@pytest.mark.parametrize("move", [0, -1], ids=["to A", "to no words"])
def test_a_picker_that_moves_while_older_statements_open_stops_before_the_survey(
        open_site, monkeypatch, move):
    monkeypatch.setattr(site, "expand_all", REAL_EXPAND)
    looked = []
    monkeypatch.setattr(site, "_survey", lambda pg: looked.append(1) or site._Survey())
    fake = _three(older=True, move_on_older={"a2222": move})
    pg = open_site(fake)
    assert site.goto_documents(pg)
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg, only=["2222"])
    assert stop.value.reason == "the picker moved to another account"
    assert looked == []


@pytest.mark.parametrize("move", [0, -1], ids=["to A", "to no words"])
def test_a_picker_that_moves_during_the_survey_keeps_nothing_of_that_look(
        open_site, monkeypatch, move):
    survey = site._survey

    def look_then_move(pg):
        got = survey(pg)
        pg.evaluate("(m) => window.moveTo(m)", move)
        return got
    monkeypatch.setattr(site, "_survey", look_then_move)
    fake = _three()
    pg = open_site(fake)
    assert site.goto_documents(pg)
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg, only=["2222"])
    assert stop.value.reason == "the picker moved to another account"


def test_a_picker_showing_no_words_after_an_answer_stops_every_run(open_site):
    """The second gap, on a run with the setting empty. Main took a picker
    that named nobody as one showing the account just chosen."""
    fake = _three(move_after={"a3333": -1})
    pg = open_site(fake)
    assert site.goto_documents(pg)
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg)
    assert stop.value.reason == "the picker moved to another account"


def test_still_shows_takes_only_the_label_itself():
    class Box:
        def __init__(self, words, expanded="false"):
            self.words, self.expanded = words, expanded

        def get_attribute(self, name):
            return self.expanded if name == "aria-expanded" else None

        def evaluate(self, *_a, **_k):
            return self.words
    labels = [A, B, P]
    assert site._still_shows(None, Box("Account " + B), labels, B)
    assert not site._still_shows(None, Box("Account " + A), labels, B)
    assert not site._still_shows(None, Box("Account"), labels, B)
    assert not site._still_shows(None, Box("Account " + B, "true"), labels, B)
    assert site._still_shows(None, None, [], B)


# -- the download ---------------------------------------------------------------

def _catch(monkeypatch):
    """Stands in for the catch, pressing the control as the real one does
    and saving a PDF that names what the press landed on."""
    calls = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        calls.append(_shown(pg))
        before = len(pg.evaluate("window.pressed"))
        el.click(timeout=3000)
        landed = pg.evaluate("window.pressed")[before:]
        Path(out_path).write_bytes(text_pdf(["pressed " + ",".join(landed)]))
        return bool(landed)
    monkeypatch.setattr(site, "_catch_pdf", fake)
    return calls


def _move_after_control(monkeypatch, pg_move, how="inplace"):
    found = site._control_for

    def then_move(pg, *a, **k):
        got = found(pg, *a, **k)
        pg.evaluate("([m, how]) => window.moveTo(m, how)", [pg_move, how])
        return got
    monkeypatch.setattr(site, "_control_for", then_move)


@pytest.mark.parametrize("only", [(), ("2222",)], ids=["every account", "only_accounts"])
@pytest.mark.parametrize("move", [0, -1], ids=["to A", "to no words"])
def test_a_picker_that_moves_before_the_press_presses_nothing(open_site, monkeypatch, tmp_path,
                                                             only, move):
    calls = _catch(monkeypatch)
    _move_after_control(monkeypatch, move)
    if move < 0:
        # No words, and A's list drawn over the same elements.
        found = site._control_for

        def then_a(pg, *a, **k):
            got = found(pg, *a, **k)
            pg.evaluate("() => { window.moveTo(0, 'inplace'); window.moveTo(-1); }")
            return got
        monkeypatch.setattr(site, "_control_for", then_a)
    fake = _three()
    pg = open_site(fake)
    trace: list = []
    with pytest.raises(pressing.Stop) as stop:
        site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                           title="Account Statement - 2026-09-30", trace=trace, account=B,
                           only=only)
    assert stop.value.reason == "the picker moved to another account"
    assert pg.evaluate("window.pressed") == []
    assert calls == []
    assert not (tmp_path / "out.pdf").exists()
    assert trace[-1]["why"] == "the picker moved to another account"


class _Linked:
    """A control whose row carries a link to its PDF."""

    def __init__(self, el):
        self.el = el

    def get_attribute(self, name):
        if name == "href":
            return "/edocs/documents/download/d1.pdf?_x=T0K3N"
        return self.el.get_attribute(name)

    def click(self, **kw):
        return self.el.click(**kw)


@pytest.mark.parametrize("move", [0, -1], ids=["to A", "to no words"])
def test_a_picker_that_moves_before_a_link_is_fetched_fetches_nothing(open_site, monkeypatch,
                                                                     tmp_path, move):
    found = site._control_for
    fetched = []

    def linked_then_move(pg, *a, **k):
        el, label = found(pg, *a, **k)
        pg.evaluate("(m) => window.moveTo(m, 'inplace')", move)
        return _Linked(el), label
    monkeypatch.setattr(site, "_control_for", linked_then_move)
    monkeypatch.setattr(site, "_fetch_pdf", lambda *a, **k: fetched.append(1) or b"%PDF-1.4")
    calls = _catch(monkeypatch)
    pg = open_site(_three())
    with pytest.raises(pressing.Stop):
        site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                           title="Account Statement - 2026-09-30", trace=[], account=B)
    assert fetched == [] and calls == []
    assert not (tmp_path / "out.pdf").exists()


def test_a_picker_that_moves_after_a_failed_fetch_is_not_pressed(open_site, monkeypatch, tmp_path):
    found = site._control_for
    fetched = []

    def linked(pg, *a, **k):
        el, label = found(pg, *a, **k)
        return _Linked(el), label

    def fetch_then_move(pg, *a, **k):
        fetched.append(1)
        pg.evaluate("() => window.moveTo(0, 'inplace')")
        return None
    monkeypatch.setattr(site, "_control_for", linked)
    monkeypatch.setattr(site, "_fetch_pdf", fetch_then_move)
    calls = _catch(monkeypatch)
    pg = open_site(_three())
    with pytest.raises(pressing.Stop):
        site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                           title="Account Statement - 2026-09-30", trace=[], account=B)
    assert fetched == [1] and calls == []
    assert pg.evaluate("window.pressed") == []


def test_a_steady_picker_still_downloads_the_chosen_document(open_site, monkeypatch, tmp_path):
    calls = _catch(monkeypatch)
    pg = open_site(_three())
    assert site.download_bill(pg, tmp_path, "2026-08-31", tmp_path / "out.pdf",
                              title="Account Statement - 2026-08-31", trace=[], account=B,
                              only=("2222",)) is True
    assert pg.evaluate("window.pressed") == ["a2222:08/31/26"]
    assert calls == [B]


def test_a_document_of_an_account_not_chosen_is_refused_before_the_page(open_site, monkeypatch,
                                                                       tmp_path):
    calls = _catch(monkeypatch)
    went = []
    monkeypatch.setattr(site, "goto_documents", lambda pg: went.append(1) or True)
    pg = open_site(_three())
    trace: list = []
    assert site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                              title="Account Statement - 2026-09-30", trace=trace, account=A,
                              only=("2222",)) is False
    assert went == [] and calls == []
    assert trace[-1]["why"] == "the document's account is not one the setting chose"


@pytest.mark.parametrize("accounts", [[base._account(A, ["09/30/26"])]], ids=["one account"])
def test_a_page_of_one_account_still_downloads_as_before(open_site, monkeypatch, tmp_path,
                                                        accounts):
    _catch(monkeypatch)
    pg = open_site(Site(accounts))
    assert site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                              title="Account Statement - 2026-09-30", trace=[], account="") is True
    assert pg.evaluate("window.pressed") == ["a1111:09/30/26"]


# -- a run of the app ---------------------------------------------------------------

TITLE = "Account Statement - " + site._human_date("2026-09-30")


def _record(account, date, state="Discovered", **more):
    title = "Account Statement - " + site._human_date(date)
    doc = app_mod.Document(title=title, category="Statement", date=date, account=account,
                           summary=("Statement - " + account) if account else "Statement")
    rec = doc.to_dict()
    rec.update({"state": state, "discovered_at": "2026-10-01T00:00:00"}, **more)
    return doc.key, rec


@pytest.fixture
def run(open_site, monkeypatch, tmp_path):
    def make(fake=None, **config):
        config.setdefault("min_pdf_bytes", 10)
        pg = open_site(fake or _three())
        app = receipt_app(app_mod, tmp_path, **config)
        app._context, app._work_page, app._dl_dir = pg.context, pg, tmp_path / "downloads"
        app._on_its_site = lambda: pg
        app.page = lambda: pg
        return app, pg
    _catch(monkeypatch)
    return make


def _seed(app):
    """A's and P's records of every state, B's done September statement and
    a record of no account from before #27, sharing B's September title."""
    seeded = dict([
        _record(A, "2026-09-30", "Completed", downloaded_ok=True),
        _record(A, "2026-07-31", "Failed"),
        _record(P, "2026-09-15", "Discovered"),
        _record(B, "2026-09-30", "Completed", downloaded_ok=True),
        _record("", "2026-09-30", "Discovered"),
    ])
    for key, rec in seeded.items():
        app.discovery.update(key, dict(rec), save=False)
        if rec["state"] != "Discovered":
            app.progress.update(key, dict(rec), save=False)
    app.discovery.save()
    app.progress.save()
    return seeded


def _not_b(store):
    return {k: v for k, v in store.data.items() if not k.endswith(":2222")}


def test_a_filtered_discover_keeps_every_other_record_as_it_was(run):
    app, pg = run(only_accounts=["2222"])
    _seed(app)
    disc, prog = json.dumps(_not_b(app.discovery), sort_keys=True), \
        json.dumps(_not_b(app.progress), sort_keys=True)
    app.cmd_discover(quiet=True)
    assert json.dumps(_not_b(app.discovery), sort_keys=True) == disc
    assert json.dumps(_not_b(app.progress), sort_keys=True) == prog
    b = sorted(k for k in app.discovery.data if k.endswith(":2222"))
    assert len(b) == 2
    assert pg.evaluate("window.optionPresses") == ["a2222"]
    assert listing.last(app) == listing.COMPLETE


def test_a_filtered_pilot_downloads_only_the_one_asked_for(run):
    app, pg = run(only_accounts=["2222"], pilot_count=1)
    _seed(app)
    app.args.start_date = app.args.end_date = "2026-08-31"
    app.cmd_pilot()
    assert pg.evaluate("window.pressed") == ["a2222:08/31/26"]
    saved = sorted(app.paths.root.rglob("*.pdf"))
    assert len(saved) == 1 and "2222" in saved[0].name
    done = [k for k, v in app.progress.data.items() if v.get("state") == "Completed"
            and v.get("date") == "2026-08-31"]
    assert done and all(k.endswith(":2222") for k in done)


def test_a_filtered_run_all_takes_no_other_accounts_document(run):
    app, pg = run(only_accounts=["2222"])
    seeded = _seed(app)
    app.args.yes = True
    app.cmd_run("all")
    assert pg.evaluate("window.pressed") == ["a2222:08/31/26"]
    for key, rec in seeded.items():
        if not key.endswith(":2222"):
            assert app.discovery.data[key]["state"] == rec["state"]


def test_a_filtered_resume_takes_only_the_chosen_accounts_documents(run, monkeypatch):
    app, pg = run(only_accounts=["2222"])
    for key, rec in (_record(A, "2026-08-31"), _record(B, "2026-08-31"),
                     _record(P, "2026-08-15")):
        app.discovery.update(key, rec, save=False)
    app.discovery.save()
    listing.started(app)
    listing.read_whole(app)
    asked = []
    monkeypatch.setattr(site, "download_bill",
                        lambda *a, **k: asked.append(k.get("account")) or False)
    try:
        app.cmd_resume()
    except SystemExit:
        pass
    assert asked == [B]


def test_a_picker_that_moves_before_the_press_leaves_the_record_failed_and_stops(
        run, monkeypatch):
    app, pg = run(only_accounts=["2222"])
    key, rec = _record(B, "2026-09-30")
    app.discovery.update(key, rec)
    _move_after_control(monkeypatch, 0)
    with pytest.raises(pressing.Stop):
        app.process([app_mod.Document.from_dict(rec)])
    assert app.progress.data[key]["state"] == "Failed"
    assert not app._already_done(app_mod.Document.from_dict(rec))
    assert pg.evaluate("window.pressed") == []


def test_a_filtered_diagnose_reads_b_alone_and_writes_counts(run, monkeypatch, spies):
    app, pg = run(only_accounts=["2222"])
    followed = []
    monkeypatch.setattr(site, "survey", lambda pg, **k: followed.append(k) or {})
    app.cmd_diagnose()
    assert pg.evaluate("window.optionPresses") == ["a2222"]
    assert A not in spies["expand"] + spies["scroll"] + spies["survey"]
    assert followed == [{"max_follow": 0}]
    found = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(
        encoding="utf-8"))
    assert found["only_accounts"] == {"only_accounts": True, "picker_entries": 3, "chosen": 1}
    assert len(found["documents_recognized"]) == 2


def test_an_unfiltered_diagnose_reads_every_account_as_before(run, monkeypatch, spies):
    app, pg = run()
    monkeypatch.setattr(site, "survey", lambda pg, **k: {})
    app.cmd_diagnose()
    assert pg.evaluate("window.optionPresses") == ["a2222", "a3333"]
    found = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(
        encoding="utf-8"))
    assert found["only_accounts"] == {"only_accounts": False, "picker_entries": 3,
                                      "chosen": 3}


# -- after the review of the first build ----------------------------------------------

def test_a_moved_picker_says_what_it_showed_and_never_which_account(open_site):
    for move, showed in ((0, "another account"), (-1, "no account")):
        pg = open_site(_three(move_after={"a2222": move} if move < 0 else {}))
        assert site.goto_documents(pg)
        if move == 0:
            # Chosen, then moved by the page itself during the survey.
            survey = site._survey

            def look_then_move(p, survey=survey):
                got = survey(p)
                p.evaluate("() => window.moveTo(0)")
                return got
            site_survey, site._survey = site._survey, look_then_move
        try:
            with pytest.raises(pressing.Stop) as stop:
                site.collect_download_docs(pg, only=["2222"])
        finally:
            if move == 0:
                site._survey = site_survey
        assert stop.value.facts == {"picker_showed": showed}


def test_the_account_is_proven_before_its_list_is_expanded_at_download(open_site, monkeypatch,
                                                                       tmp_path):
    """A picker showing no account once its entry was chosen. Nothing in
    the list is pressed, Show older included."""
    monkeypatch.setattr(site, "expand_all", REAL_EXPAND)
    calls = _catch(monkeypatch)
    pg = open_site(_three(older=True, move_after={"a2222": -1}))
    with pytest.raises(pressing.Stop):
        site.download_bill(pg, tmp_path, "2026-09-30", tmp_path / "out.pdf",
                           title="Account Statement - 2026-09-30", trace=[], account=B)
    assert pg.evaluate("window.olderPresses") == []
    assert calls == [] and pg.evaluate("window.pressed") == []


def test_a_run_leaves_the_record_of_an_account_not_chosen_alone(run):
    app, pg = run(only_accounts=["2222"])
    key, rec = _record(A, "2026-09-30", "Failed")
    app.discovery.update(key, dict(rec))
    app.progress.update(key, dict(rec))
    before = json.dumps(app.progress.data, sort_keys=True)
    app.download_one(pg, app_mod.Document.from_dict(rec), "a.pdf")
    assert json.dumps(app.progress.data, sort_keys=True) == before
    assert pg.evaluate("window.pressed") == []
    assert not list(app.paths.diagnostics.glob("failure-*.json"))


CLOSED = """<!doctype html><meta charset="utf-8"><span id="lbl">Account</span>
<div role="combobox" id="box" aria-expanded="false" aria-labelledby="lbl" style="%s">
  <span>%s</span>
  <ul role="listbox" style="position:absolute;clip:rect(0 0 0 0);width:1px;height:1px;overflow:hidden">
    <li role="option">Business Checking A ...1111</li>
    <li role="option">Business Checking B ...2222<span>Selected</span></li>
    <li role="option">Personal Checking ...3333</li></ul></div>"""


@pytest.mark.parametrize("style, words, shown", [
    ("", B, B),
    ("text-transform:uppercase", B, B),
    ("", "Business   Checking B\n...2222", B),
    ("", "Business Checking B", None),
    ("", "", None),
    ("", A + " " + B, None),
], ids=["as drawn", "in capitals", "spaced", "nickname alone", "nothing", "two accounts"])
def test_the_closed_picker_names_its_account_however_it_is_drawn(browser, style, words,  # noqa: F811
                                                                 shown):
    """Shapes a real closed picker could take. Its entries kept inside it,
    clipped rather than hidden, are never read as what it shows."""
    pg = browser.new_page()
    try:
        pg.set_content(CLOSED % (style, words))
        assert site._shown_account(pg, pg.locator("#box"), [A, B, P]) == shown
    finally:
        pg.close()


def test_a_filtered_diagnose_writes_no_account_word_in_either_file(run, monkeypatch):
    app, pg = run(only_accounts=["2222"])
    monkeypatch.setattr(site, "survey", lambda pg, **k: {})
    app.cmd_diagnose()
    app.write_survey()
    written = " ".join(p.read_text(encoding="utf-8") for p in app.paths.diagnostics.glob("*.json"))
    assert len(list(app.paths.diagnostics.glob("*.json"))) >= 2
    for word in ("1111", "2222", "3333", "Business", "Personal", "Checking"):
        assert word not in written, word
    assert '"chosen": 1' in written and '"picker_entries": 3' in written


def test_the_selection_holds_only_the_chosen_accounts_documents(run):
    """What Pilot, Run All and Continue take, before any download is tried."""
    app, pg = run(only_accounts=["2222"])
    _seed(app)
    picked = app._select()
    assert [d.account for d in picked] == [B]
    assert all(app_mod.site.account_tail(d.account) == "2222" for d in picked)
