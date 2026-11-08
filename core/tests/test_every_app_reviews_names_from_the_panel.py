"""Review Names asked by the control panel, which has no console.

Every receipt app asks in a console for a better name for each receipt it
was unsure of. The panel, and PaperPull Server, which has no console at
all, ask in two steps instead. The first has the app write the receipts it
would ask about to a file and rename nothing. The second hands it the new
summaries a person typed, and only the receipts given one are renamed, by
the rules a console review follows.

A new name is known by the file it was shown for and that purchase's order
number. One for a file no longer waiting for review, or for another
purchase, does nothing and is said, so a list that went stale while the
dialog was open never renames the wrong receipt.

These run each app's own cmd_review_names over an output folder on disk,
with the console standing in as something that fails the test when asked.
Every name, number and answer is invented.
"""
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import renaming

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_reviews_a_name_once as census  # noqa: E402

APPS = census.APPS
IDS = [a.name for a in APPS]
FIRST = "2026-05-14 Unsure Receipt.pdf"
SECOND = "2026-05-14 Other Receipt.pdf"


@pytest.fixture(autouse=True)
def default_names():
    """Files named the default way, whatever a test before this one chose."""
    from paperpull_core import storage
    storage.set_filename_owner("")
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


@pytest.fixture(autouse=True)
def no_panel(monkeypatch):
    """Neither step asked unless a test asks it."""
    monkeypatch.delenv(renaming.REVIEW_LIST_ENV, raising=False)
    monkeypatch.delenv(renaming.REVIEW_ANSWERS_ENV, raising=False)


def nobody_types(mod, monkeypatch):
    def ask(prompt):
        raise AssertionError("the panel's review asked a console: %r" % prompt)
    monkeypatch.setattr(mod, "ask", ask)


def two_unsure(app, tmp_path, monkeypatch):
    """The app over an output folder holding two receipts it was unsure
    how to name, as its own run left them, with items on the first."""
    mod = census.load(app)
    nobody_types(mod, monkeypatch)
    inst = census.runnable(mod, tmp_path / "out")
    filed = inst.paths.folder_for("Online")
    first = census.receipt(filed, FIRST)
    second = census.receipt(filed, SECOND)
    census.as_a_run_left_it(inst, "ORDER-0001", first, saved=True, confidence="Low")
    census.as_a_run_left_it(inst, "ORDER-0002", second, saved=True, confidence="Low")
    inst.progress.update("Online:ORDER-0001", {"items": [{"name": "Invented Hose"},
                                                         {"name": "Invented Nozzle"}]})
    return mod, inst, first, second


def listed(inst, tmp_path, monkeypatch) -> list:
    where = tmp_path / "panel" / "review.json"
    where.parent.mkdir(exist_ok=True)
    monkeypatch.setenv(renaming.REVIEW_LIST_ENV, str(where))
    inst.cmd_review_names()
    monkeypatch.delenv(renaming.REVIEW_LIST_ENV)
    assert not list(where.parent.glob("*.part")), "the list is moved into place whole"
    return json.loads(where.read_text(encoding="utf-8"))["receipts"]


def answered(inst, tmp_path, monkeypatch, answers):
    where = tmp_path / "answers.json"
    where.write_text(json.dumps({"answers": answers}), encoding="utf-8")
    monkeypatch.setenv(renaming.REVIEW_ANSWERS_ENV, str(where))
    try:
        inst.cmd_review_names()
    finally:
        monkeypatch.delenv(renaming.REVIEW_ANSWERS_ENV)


def files(inst) -> list:
    return sorted(p.name for p in inst.paths.folder_for("Online").glob("*.pdf"))


def rows_for(inst, number) -> list:
    return [r for r in inst.index_csv.read_all() if r["Order or Receipt Number"] == number]


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_the_list_is_what_a_console_review_would_ask_and_renames_nothing(
        app, tmp_path, monkeypatch, capsys):
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    before = census.everything_under(tmp_path / "out")
    receipts = listed(inst, tmp_path, monkeypatch)
    assert census.everything_under(tmp_path / "out") == before, "listing changes nothing"
    assert [(r["id"], r["number"], r["file"]) for r in receipts] == [
        (str(first), "ORDER-0001", FIRST), (str(second), "ORDER-0002", SECOND)]
    assert receipts[0]["items"] == ["Invented Hose", "Invented Nozzle"]
    assert receipts[0]["date"] == "2026-05-14"
    assert "2 receipts need review." in capsys.readouterr().out


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_an_empty_list_is_written_too(app, tmp_path, monkeypatch, capsys):
    mod = census.load(app)
    nobody_types(mod, monkeypatch)
    inst = census.runnable(mod, tmp_path / "out")
    assert listed(inst, tmp_path, monkeypatch) == []
    assert "No receipts need name review." in capsys.readouterr().out


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_only_the_receipt_given_a_name_is_renamed(app, tmp_path, monkeypatch, capsys):
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    receipts = listed(inst, tmp_path, monkeypatch)
    answered(inst, tmp_path, monkeypatch, [
        {"id": receipts[0]["id"], "number": receipts[0]["number"], "summary": "garden hose"},
        {"id": receipts[1]["id"], "number": receipts[1]["number"], "summary": "   "}])
    names = files(inst)
    assert SECOND in names and FIRST not in names
    renamed = [n for n in names if n != SECOND]
    assert len(renamed) == 1 and "Garden Hose" in renamed[0], names
    row = rows_for(inst, "ORDER-0001")[0]
    assert row["PDF Filename"] == renamed[0]
    assert row["Classification Confidence"] == "High"
    assert renaming.REVIEWED in row["Notes"]
    assert row["Processing Status"] == "Completed"
    record = inst.progress.get("Online:ORDER-0001")
    assert Path(record["pdf_path"]).name == renamed[0]
    assert rows_for(inst, "ORDER-0002")[0]["PDF Filename"] == SECOND
    out = capsys.readouterr().out
    assert "Renaming 1 receipt given a new name." in out
    assert "New summary: garden hose" in out
    # The next list holds only the receipt kept as it was.
    assert [r["number"] for r in listed(inst, tmp_path, monkeypatch)] == ["ORDER-0002"]


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_name_for_another_purchase_or_a_file_gone_from_the_list_does_nothing(
        app, tmp_path, monkeypatch, capsys):
    """The list went stale while the dialog was open. A name given for the
    first file under the second's number, and one for a file no longer
    waiting, leave every file and every ledger as they were."""
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    gone = census.receipt(inst.paths.folder_for("Online"), "2026-05-14 Gone Receipt.pdf")
    before = census.everything_under(tmp_path / "out")
    answered(inst, tmp_path, monkeypatch, [
        {"id": str(first), "number": "ORDER-0002", "summary": "Wrong Purchase"},
        {"id": str(gone), "number": "ORDER-0003", "summary": "Not Waiting"}])
    assert census.everything_under(tmp_path / "out") == before
    out = capsys.readouterr().out
    assert "2 new names were for receipts no longer waiting for review" in out
    assert "nothing was renamed" in out


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_of_two_names_for_one_file_the_one_for_its_own_purchase_is_taken(
        app, tmp_path, monkeypatch, capsys):
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    answered(inst, tmp_path, monkeypatch, [
        {"id": str(first), "number": "ORDER-0002", "summary": "Wrong Purchase"},
        {"id": str(first), "number": "ORDER-0001", "summary": "Right Purchase"}])
    names = files(inst)
    assert any("Right Purchase" in n for n in names), names
    assert not any("Wrong Purchase" in n for n in names), names
    assert "1 new name was for a receipt no longer waiting" in capsys.readouterr().out


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_words_that_keep_a_name_from_the_panel_keep_it(app, tmp_path, monkeypatch, capsys):
    """The panel's empty box once read "Keep this name", and typed into
    four boxes on a real Target archive it renamed four receipts "... Keep
    This Name Invoice.pdf". Words that ask to keep a name keep it, as a
    blank box does, and both receipts stay waiting for a name."""
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    rows = inst.index_csv.read_all()
    answered(inst, tmp_path, monkeypatch, [
        {"id": str(first), "number": "ORDER-0001", "summary": "Keep this name"},
        {"id": str(second), "number": "ORDER-0002", "summary": " same. "}])
    assert files(inst) == sorted([FIRST, SECOND])
    assert inst.index_csv.read_all() == rows
    assert "No receipt was given a new name, so nothing was renamed." in capsys.readouterr().out
    assert [r["number"] for r in listed(inst, tmp_path, monkeypatch)] == ["ORDER-0001", "ORDER-0002"]


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_words_that_keep_a_name_in_a_console_keep_it(app, tmp_path, monkeypatch, capsys):
    """The same words typed at the console's question keep the name, and the
    receipt after them is still asked about and renamed."""
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    typed = iter(["keep this name", "Invented Lamp"])
    monkeypatch.setattr(mod, "ask", lambda prompt: next(typed))
    inst.cmd_review_names()
    names = files(inst)
    assert FIRST in names and SECOND not in names, names
    assert any("Invented Lamp" in n for n in names), names
    assert "That keeps its name." in capsys.readouterr().out
    assert rows_for(inst, "ORDER-0001")[0]["PDF Filename"] == FIRST


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_q_from_the_panel_is_a_name_and_never_a_stop(app, tmp_path, monkeypatch):
    """In a console q stops the review. Typed in the panel it is a summary
    like any other, and the receipt after it is renamed as well."""
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    answered(inst, tmp_path, monkeypatch, [
        {"id": str(first), "number": "ORDER-0001", "summary": "q"},
        {"id": str(second), "number": "ORDER-0002", "summary": "Invented Lamp"}])
    names = files(inst)
    assert FIRST not in names and SECOND not in names, names
    assert any("Invented Lamp" in n for n in names), names


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_answers_that_cannot_be_read_rename_nothing(app, tmp_path, monkeypatch, capsys):
    mod, inst, first, second = two_unsure(app, tmp_path, monkeypatch)
    before = census.everything_under(tmp_path / "out")
    where = tmp_path / "answers.json"
    for text in ("{not json", json.dumps({"answers": "Garden Hose"}), json.dumps([1, 2])):
        where.write_text(text, encoding="utf-8")
        monkeypatch.setenv(renaming.REVIEW_ANSWERS_ENV, str(where))
        with pytest.raises(SystemExit) as stopped:
            inst.cmd_review_names()
        assert stopped.value.code == 1
        assert census.everything_under(tmp_path / "out") == before
    monkeypatch.setenv(renaming.REVIEW_ANSWERS_ENV, str(tmp_path / "missing.json"))
    with pytest.raises(SystemExit):
        inst.cmd_review_names()
    assert census.everything_under(tmp_path / "out") == before
    assert "could not be read" in capsys.readouterr().out


def test_a_summary_from_the_panel_is_one_line_and_cut_to_size(tmp_path):
    where = tmp_path / "answers.json"
    long = "Lamp " * 60
    where.write_text(json.dumps({"answers": [
        {"id": "a", "number": " 1 ", "summary": "Garden\nHose\t\x00Reel"},
        {"id": "b", "number": "2", "summary": long},
        {"id": "c", "number": "3", "summary": " \n "},
        {"id": "", "number": "4", "summary": "No File"},
        {"id": "e", "number": 5, "summary": "Not Text"},
        "not an answer"]}), encoding="utf-8")
    got = renaming._panel_answers(str(where))
    assert got[("a", "1")] == "Garden Hose Reel"
    assert len(got[("b", "2")]) <= renaming.SUMMARY_MAX
    assert set(got) == {("a", "1"), ("b", "2")}
