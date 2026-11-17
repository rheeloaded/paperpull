"""A receipt is set aside only on a run that saved one of its kind before it
(#225).

A tester's Kroger receipt pages stopped showing the receipt for every one of
their 244 purchases, most likely a change at Kroger. Each run counted a day
for each of them, and a third separate day would have set every one aside
as No Receipt Available, for good, and written it into both CSVs. PaperPull
Server has no Download again, so a purchase set aside there is never asked
for again. A provider whose receipt pages show nothing for every purchase
has broken pages. It says nothing about whether the purchases have
receipts.

So a purchase is set aside only on a run that saved a receipt of its kind
(online or in-store) before it, with no receipt page of that kind showing
nothing in between. Otherwise it is tried again next run and keeps its
days, never more than three of them. A provider that shows no receipt at
all then costs time, never the purchases.

These drive each app's own method that hands such a purchase to the core,
in one app object for each run, and save another purchase's receipt
through the app's own _finish_pdf, as a run does. Every name, number and
date is invented.
"""
import ast
import importlib.util
from pathlib import Path

import pytest

from paperpull_core import not_shown
from paperpull_core.models import IN_STORE, Purchase, State

# The census beside this file, for its stand-in run of each receipt app.
_CENSUS = Path(__file__).with_name("test_every_receipt_app_asks_again_for_a_receipt_not_shown.py")
_spec = importlib.util.spec_from_file_location("not_shown_census_of_saves", _CENSUS)
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)

TRYING, TRYING_IDS = census.TRYING, census.TRYING_IDS

SET_ASIDE = "on 3 of 3 separate days. It is set aside for review and not asked for again."
NOT_SET_ASIDE = "It is not set aside, because"
NONE_SAVED = "no %s receipt was saved before it in this run, and it is tried again next run."
SHOWED_NOTHING_SINCE = ("an %s receipt page showed nothing after the last %s receipt this run "
                        "saved, and it is tried again next run.")


def run(mod, out: Path, day: int, redownload: bool = False):
    """A new run of the app, started on that day."""
    return census.app_in(mod, out, redownload=redownload, day=day)


def miss(inst, method: str, p: Purchase = None, rec: dict = None):
    """The run looks for the purchase's receipt and its page shows nothing."""
    census.look_in(inst, method, p or census.purchase(), rec)
    return inst


def record(inst, p: Purchase = None) -> dict:
    return inst.progress.get((p or census.purchase()).key) or {}


def alone(mod, out: Path, method: str, days, p: Purchase = None):
    """A run on each of these days that looked for the purchase and found
    nothing, and saved nothing."""
    inst = None
    for day in days:
        inst = miss(run(mod, out, day), method, p)
    return inst


def said(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


def kind(p: Purchase) -> str:
    return p.purchase_type.lower()


def in_store(number: str = census.ORDER) -> Purchase:
    p = census.purchase()
    p.purchase_type, p.order_number = IN_STORE, number
    return p


def assert_tried_again(inst, p: Purchase = None, days: int = 3):
    rec = record(inst, p)
    shown = (rec.get("state"), rec.get(not_shown.DAYS_KEY))
    assert rec.get("state") == State.FAILED.value, shown
    assert len(rec.get(not_shown.DAYS_KEY) or []) == days, shown


def assert_set_aside(inst, p: Purchase = None):
    rec = record(inst, p)
    shown = (rec.get("state"), rec.get(not_shown.DAYS_KEY))
    assert rec.get("state") == State.NO_RECEIPT_AVAILABLE.value, shown
    assert not_shown.set_aside(rec), shown


# -- a run that saved nothing of the kind -----------------------------------------------


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_receipt_whose_page_shows_nothing_with_nothing_saved_is_never_set_aside(
        app, method, tmp_path, monkeypatch, capsys):
    """Kroger's pages showed nothing for every purchase, so no run saved
    anything. The third day finds nothing again, and the purchase is
    tried again next run, keeps its three days and is written nowhere."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    p = census.purchase()
    alone(mod, tmp_path, method, (1, 2))
    capsys.readouterr()

    inst = alone(mod, tmp_path, method, (3,))
    out = said(capsys)
    assert_tried_again(inst)
    assert "set aside for review" not in out, out
    assert "on 3 separate days. " + NOT_SET_ASIDE in out, out
    assert NONE_SAVED % kind(p) in out, out
    assert (inst.stats["failed"], inst.stats["no_receipt"], inst.stats["manual_review"]) == (1, 0, 0)
    assert not census.written_down(inst), "nothing is written down for a purchase not set aside"
    assert not census.done_already(mod, tmp_path, p), "the next run asks for it again"


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_never_more_than_three_days_are_kept(app, method, tmp_path, monkeypatch, capsys):
    """Ten days of a page that shows nothing, with nothing saved. The record
    keeps the three most recent days, never a growing list, and no run says
    a purchase showed nothing on 4 of 3 days."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    for day in range(1, 11):
        inst = alone(mod, tmp_path, method, (day,))
        out = said(capsys)
        days = record(inst).get(not_shown.DAYS_KEY) or []
        assert len(days) == min(day, not_shown.DAYS), (day, days)
        assert days[-1] == inst.stats["started"][:10], days
        assert record(inst)["state"] == State.FAILED.value, (day, record(inst)["state"])
        for more in range(not_shown.DAYS + 1, 12):
            assert "on %d of 3" % more not in out and "on %d separate" % more not in out, out
        if day > not_shown.DAYS:
            assert "on more than 3 separate days. " + NOT_SET_ASIDE in out, out
    assert sorted(days) == days, "the three most recent, in order"


# -- a run that saved one first ---------------------------------------------------------


@pytest.mark.parametrize("kept", [True, False], ids=["kept", "put aside"])
@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_save_before_it_on_its_third_day_sets_it_aside(app, method, kept, tmp_path,
                                                          monkeypatch, capsys):
    """The run saved another purchase's receipt, a copy kept or one put
    aside for review, whose record had no days of its own. The purchase
    whose page then showed nothing on its third day is set aside, and
    written down once."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    alone(mod, tmp_path, method, (1, 2))
    inst = run(mod, tmp_path, 3)
    other = census.save_another(inst, kept=kept)
    assert not_shown.DAYS_KEY not in record(inst, other), record(inst, other)
    capsys.readouterr()

    miss(inst, method)
    out = said(capsys)
    assert_set_aside(inst)
    assert SET_ASIDE in out, out
    assert inst.stats["no_receipt"] == 1 and inst.stats["manual_review"] >= 1
    rows = census.written_down(inst)
    assert rows >= 2, "a row in each CSV"
    assert census.done_already(mod, tmp_path, census.purchase())

    # A later run with nothing saved does not write it down again.
    inst = alone(mod, tmp_path, method, (4,))
    assert census.written_down(inst) == rows


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_page_that_showed_nothing_after_the_save_keeps_it_from_being_set_aside(
        app, method, tmp_path, monkeypatch, capsys):
    """Saved, then another purchase's page showed nothing, then this one's
    showed nothing on its third day. The save is no longer the run's last
    word on whether the provider shows receipts, so it is tried again."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    p, q = census.purchase(), census.another("ORDER-0003")
    alone(mod, tmp_path, method, (1, 2))
    inst = run(mod, tmp_path, 3)
    census.save_another(inst)
    miss(inst, method, q)
    capsys.readouterr()

    miss(inst, method, p)
    out = said(capsys)
    assert_tried_again(inst, p)
    assert_tried_again(inst, q, days=1)
    assert SHOWED_NOTHING_SINCE % (kind(p), kind(p)) in out, out
    assert not census.written_down(inst)


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_each_save_lets_the_next_page_that_shows_nothing_be_set_aside(app, method, tmp_path,
                                                                      monkeypatch, capsys):
    """Save, nothing on a third day, save, nothing on a third day. Both are
    set aside."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    p, q = census.purchase(), census.another("ORDER-0003")
    for day in (1, 2):
        inst = run(mod, tmp_path, day)
        miss(inst, method, p)
        miss(inst, method, q)
    inst = run(mod, tmp_path, 3)
    census.save_another(inst, "ORDER-0002")
    miss(inst, method, p)
    census.save_another(inst, "ORDER-0004")
    miss(inst, method, q)
    out = said(capsys)
    assert_set_aside(inst, p)
    assert_set_aside(inst, q)
    assert out.count(SET_ASIDE) == 2, out


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_save_in_another_run_does_not_count(app, method, tmp_path, monkeypatch, capsys):
    """Two runs of the app in one process. The first saved a receipt, the
    second did not, and the second's page shows nothing on the third day.
    Then the first's does, after its save."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    alone(mod, tmp_path, method, (1, 2))
    first, second = run(mod, tmp_path, 3), run(mod, tmp_path, 3)
    census.save_another(first)
    miss(second, method)
    assert_tried_again(second)
    miss(first, method)
    assert_set_aside(first)


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_only_a_save_lets_it_be_set_aside(app, method, tmp_path, monkeypatch, capsys):
    """What a run records for another purchase short of a save, a failure,
    a copy for review it did not save, a receipt located or its details
    read, or a canceled order, says nothing about whether this provider
    shows receipts now."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    for state in (State.FAILED, State.NEEDS_MANUAL_REVIEW, State.RECEIPT_LOCATED,
                  State.DETAILS_EXTRACTED, State.CANCELED):
        out = tmp_path / state.name
        alone(mod, out, method, (1, 2))
        inst = run(mod, out, 3)
        inst._record_state(census.another(), state)
        miss(inst, method)
        assert_tried_again(inst)
        capsys.readouterr()


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_one_kept_from_being_set_aside_is_set_aside_on_the_next_run_that_saves_first(
        app, method, tmp_path, monkeypatch, capsys):
    """Its third day had nothing saved before it, so it kept its three
    days. The next day's run saved a receipt first, and the purchase whose
    page showed nothing again is set aside at once."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    inst = alone(mod, tmp_path, method, (1, 2, 3))
    assert_tried_again(inst)
    capsys.readouterr()

    inst = run(mod, tmp_path, 4)
    census.save_another(inst)
    miss(inst, method)
    assert SET_ASIDE in said(capsys)
    assert_set_aside(inst)


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_download_again_of_a_receipt_set_aside_keeps_it_set_aside(app, method, tmp_path,
                                                                  monkeypatch, capsys):
    """Set aside on its third day. A Download again on a later day saved
    nothing before it and its page shows nothing again. It stays set aside,
    with no new rows and no more than three days."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    alone(mod, tmp_path, method, (1, 2))
    inst = run(mod, tmp_path, 3)
    census.save_another(inst)
    miss(inst, method)
    assert_set_aside(inst)
    rows = census.written_down(inst)

    for day in (4, 5):
        inst = miss(run(mod, tmp_path, day, redownload=True), method)
        assert_set_aside(inst)
        days = record(inst)[not_shown.DAYS_KEY]
        assert len(days) == not_shown.DAYS, days
        assert census.written_down(inst) == rows
        assert census.done_already(mod, tmp_path, census.purchase())


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_page_that_showed_nothing_for_a_receipt_saved_before_counts_too(
        app, method, tmp_path, monkeypatch, capsys):
    """A Download again saved a receipt, then met a page that showed
    nothing for a receipt saved before, whose copy is kept. That page showed
    nothing as much as any other, so the next purchase whose page shows
    nothing on its third day is not set aside. A save after it is."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    saved_before = census.another("ORDER-0003")
    alone(mod, tmp_path, method, (1, 2))
    inst = run(mod, tmp_path, 3, redownload=True)
    census.save_another(inst)
    miss(inst, method, saved_before, rec={"state": State.COMPLETED.value, "downloaded_ok": True})
    out = said(capsys)
    assert "The receipt saved before is kept." in out, out

    miss(inst, method)
    assert_tried_again(inst)
    census.save_another(inst, "ORDER-0004")
    miss(inst, method)
    assert_set_aside(inst)


IN_STORE_APPS = [(d, m) for d, m in TRYING
                 if "IN_STORE" in census.entry_of(d).read_text(encoding="utf-8-sig")]


@pytest.mark.parametrize("app, method", IN_STORE_APPS,
                         ids=["%s.%s" % (d.name, m) for d, m in IN_STORE_APPS])
def test_a_save_counts_only_for_its_own_kind(app, method, tmp_path, monkeypatch, capsys):
    """An online order saved says nothing of the store receipts, which come
    from pages of their own (Costco's warehouse receipts, Kroger's and Best
    Buy's store receipts). An in-store receipt whose page shows nothing on
    its third day after an online save is tried again. After an in-store
    save it is set aside."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    p = in_store()
    alone(mod, tmp_path, method, (1, 2), p)
    inst = run(mod, tmp_path, 3)
    census.save_another(inst)
    capsys.readouterr()
    miss(inst, method, p)
    out = said(capsys)
    assert_tried_again(inst, p)
    assert NONE_SAVED % kind(p) in out, out

    census.save_another(inst, "ORDER-0004", purchase_type=IN_STORE)
    miss(inst, method, p)
    assert_set_aside(inst, p)


# -- records older versions left --------------------------------------------------------


@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_a_receipt_set_aside_by_an_earlier_version_stays_set_aside(app, tmp_path):
    """0.66.0 to 0.68.0 set receipts aside after three days with nothing
    saved. Those records stay as they are, and are skipped with their
    words."""
    mod = census.load(app)
    rec = {"state": State.NO_RECEIPT_AVAILABLE.value,
           "notes": "Kroger could not load this receipt on 3 separate days, so it is not "
                    "asked for again",
           not_shown.DAYS_KEY: ["2031-01-02", "2031-01-03", "2031-01-04"]}
    assert census.done(mod, tmp_path, rec), app.name
    assert "did not show on 3 separate days" in not_shown.skipped(rec, "done")


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_failed_record_from_an_earlier_version_counts_on(app, method, tmp_path, monkeypatch,
                                                          capsys):
    """A purchase 0.68.0 recorded as failed on one or two days counts on
    from them."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    failed = {"state": State.FAILED.value,
              "notes": "Receipt page did not render, tried again next run"}

    one = tmp_path / "one"
    miss(run(mod, one, 3), method, rec=dict(failed, not_shown_days=["2031-01-02"]))
    assert "on 2 of 3 separate days. It is tried again next run." in said(capsys)

    two = tmp_path / "two"
    inst = run(mod, two, 3)
    census.save_another(inst)
    miss(inst, method, rec=dict(failed, not_shown_days=["2031-01-02", "2031-01-03"]))
    assert SET_ASIDE in said(capsys)
    assert_set_aside(inst)


# -- by the code ------------------------------------------------------------------------


SAVED_WORDS = ("PDF_SAVED", "PDF_VERIFIED", State.PDF_SAVED.value, State.PDF_VERIFIED.value)


def _call_to(node, attr: str, owner: str = None) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr):
        return False
    return owner is None or ast.unparse(node.func.value).split(".")[-1] == owner


@pytest.mark.parametrize("app", census.TRYING_APPS, ids=[d.name for d in census.TRYING_APPS])
def test_every_save_goes_through_the_core(app):
    """A save lets a purchase be set aside only by way of let_go_on_save, so
    an app whose saves skip it would never set one aside, and one that
    writes a saved state some other way would set one aside on nothing.
    In each app that sets receipts aside, _record_state calls it at its top
    level, before a Download again keeps the record saved before
    (saved_copy.holds) and before the record is written, and nothing else
    in the app writes a saved state into its history."""
    source = census.entry_of(app).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    cls = census._app_class(app)
    writes = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == "_record_state")
    top = [s.value for s in writes.body if isinstance(s, ast.Expr)]
    let_go = [c for c in top if _call_to(c, "let_go_on_save", "not_shown")]
    assert len(let_go) == 1, "%s's _record_state does not call let_go_on_save at its top" % app.name
    later = [n.lineno for n in ast.walk(writes)
             if _call_to(n, "holds", "saved_copy") or _call_to(n, "update", "progress")]
    assert later and all(let_go[0].lineno < line for line in later), app.name

    inside = {id(n) for n in ast.walk(writes)}
    faults = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if any(_call_to(node, attr, "progress") for attr in ("update", "set", "put")) or (
                isinstance(node, (ast.Assign, ast.AugAssign)) and "progress" in ast.unparse(node)):
            said_there = ast.unparse(node)
            if any(word in said_there for word in SAVED_WORDS):
                faults.append("line %d: %s" % (node.lineno, said_there[:80]))
    assert not faults, (app.name, faults)


@pytest.mark.parametrize("app, method", TRYING, ids=TRYING_IDS)
def test_a_receipt_recorded_as_having_none_for_another_reason_lets_its_days_go(
        app, method, tmp_path, monkeypatch, capsys):
    """Three days of pages that showed nothing, with nothing saved before
    them, leave a purchase tried again with its three days. When a later
    run records it as having no receipt for what the provider showed (a
    Target order with only an invoice, a GitHub payment with no receipt
    link), that is final for its own reason, and the days go with it. Kept,
    they read as a purchase set aside for pages that showed nothing, and
    every later run said its receipt did not show on 3 separate days
    (review of #225)."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    p = census.purchase()
    inst = alone(mod, tmp_path, method, (1, 2, 3))
    assert_tried_again(inst)
    capsys.readouterr()

    inst = run(mod, tmp_path, 4)
    inst._record_state(census.purchase(), State.NO_RECEIPT_AVAILABLE,
                       notes="No printable receipt available")
    rec = record(inst, p)
    assert rec.get("state") == State.NO_RECEIPT_AVAILABLE.value, rec.get("state")
    assert not (rec.get(not_shown.DAYS_KEY) or []), rec.get(not_shown.DAYS_KEY)
    assert not not_shown.set_aside(rec), app.name
    assert not_shown.skipped(rec, "  its own words") == "  its own words"
