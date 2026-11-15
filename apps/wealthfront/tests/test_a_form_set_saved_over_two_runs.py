"""A tax form whose dialog lists several files is done once every file has come.

A 1099's dialog can list a workbook or a corrected copy beside its PDF, and
each is saved beside the first as "(2 of 3)" and so on (#142). A file of the
set that did not come was written in the log and passed over, and the form
was marked done for good with the notes counting files that were never
saved, so the next run never asked for it. A run that did ask through the
same code would have saved the first file a second time, as "(2)", since
its name is taken by then.

The real app, its real progress file and index and the real Rename run here,
with the browser stood in. A link answers with its file, or with nothing
when the test leaves it out, and each file is known by its bytes. Every
value is invented.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import test_companion_tax_files as companion  # noqa: E402  its app, form and stand-ins
import wealthfront_docs as app_mod  # noqa: E402
from paperpull_core import renaming, storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402

PDF_START = companion.PDF_START
FOLDER = ("Wealthfront", "Investing", "2031")
FIRST = "2031-12-31 Tax Document.pdf"


@pytest.fixture(autouse=True)
def reset_patterns():
    yield
    storage.set_filename_owner("")
    storage.set_filename_patterns({})


def link(n: int) -> str:
    """A file of the form's set, as its dialog gives it."""
    return "/documents/inv-0001/2031/FORM_1099_PDF?idx=%d" % (n - 1)


FILES = {link(1): ("1099.pdf", PDF_START + b"the form"),
         link(2): ("gain_loss.xls", b"invented,columns\n1,2\n"),
         link(3): ("corrected.pdf", PDF_START + b"a corrected form"),
         link(4): ("lots.csv", b"invented,lots\n3,4\n")}


class _Count:
    def count(self):
        return 1


class _Expect:
    def __init__(self, tab):
        self.tab = tab

    def __enter__(self):
        self.tab.entered += 1
        return self

    def __exit__(self, *exc):
        if exc[0] is None and self.tab.last not in self.tab.arrives:
            raise TimeoutError('Timeout 45000ms exceeded while waiting for event "download"')
        if exc[0] is None and isinstance(self.tab.arrives[self.tab.last], BaseException):
            raise self.tab.arrives[self.tab.last]
        return False

    @property
    def value(self):
        suggested, body = self.tab.arrives[self.tab.last]
        return SimpleNamespace(suggested_filename=suggested, body=body)


class FormTab:
    """The browser's tab. A link answers with its file when `arrives` has
    one for it, and with nothing otherwise."""

    def __init__(self, arrives):
        self.arrives, self.last, self.asked, self.entered = dict(arrives), "", [], 0

    def locator(self, *_a, **_k):
        return _Count()

    def expect_download(self, timeout=0):
        return _Expect(self)

    def goto(self, url, **_k):
        self.last = url[len(app_mod.site.BASE):] if url.startswith(app_mod.site.BASE) else url
        self.asked.append(self.last)
        raise Exception("Download is starting")


def a_run(tmp_path, monkeypatch, links, arrives, pattern=companion.PATTERN, **settings):
    """One run of the app over the form, a process of its own on the same
    output folder, taking the form as discovery lists it."""
    app = companion.make_app(tmp_path, pattern)
    for name, value in settings.items():
        setattr(app.args, name, value)
    companion.stand_in(monkeypatch, app)
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links", lambda page, a, t: list(links))
    monkeypatch.setattr(app_mod.site, "select_tax_year", lambda page, year: None)
    monkeypatch.setattr(app_mod.site, "find_row_download", lambda *a: None)
    tab = FormTab(arrives)
    doc = companion.a_form()
    if not app._already_done(doc):
        app.download_one(tab, doc, storage.build_pdf_filename(doc.date, doc.summary, "",
                                                              record=doc))
    return app, tab, doc


def everything_but(*left_out, of=4):
    return {u: f for u, f in FILES.items() if u not in left_out and int(u[-1]) < of}


def folder(app) -> Path:
    return app.paths.tax_documents.joinpath(*FOLDER)


def saved(app) -> dict:
    """Each file in the form's folder by its name, with its bytes."""
    return {p.name: p.read_bytes() for p in folder(app).iterdir()} if folder(app).is_dir() else {}


def stored(app, doc) -> dict:
    return json.loads(app.paths.progress_json.read_text(encoding="utf-8"))[doc.key]


THREE = [link(1), link(2), link(3)]


def test_a_file_of_the_set_that_did_not_come_leaves_the_form_to_be_asked_again(
        tmp_path, monkeypatch):
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    assert not app._already_done(doc), "file 2 of the form set never came, and the form is done for good"
    rec = stored(app, doc)
    assert rec["downloaded_ok"] is False and rec["state"] == State.FAILED.value
    assert [(Path(e["file"]).name, e["link"], e["part"]) for e in rec["invoices"]] == [
        (FIRST, link(1), "1 of 3"), ("2031-12-31 Tax Document (3 of 3).pdf", link(3), "3 of 3")]
    assert "file 2 of 3" in rec["notes"] and "tried again next run" in rec["notes"]
    assert app.stats["failed"] == 1 and app.stats["tax_documents"] == 0
    assert sorted(Path(p).name for p in app.stats["new_files"]) == sorted(
        [FIRST, "2031-12-31 Tax Document (3 of 3).pdf"])
    assert not [r for r in app.index_csv.read_all() if r["Processing Status"] == "Completed"]


def test_the_next_run_asks_only_for_the_file_that_did_not_come(tmp_path, monkeypatch):
    a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but())
    assert tab.entered == 1 and tab.asked == [link(2)]
    assert saved(app) == {FIRST: FILES[link(1)][1],
                          "2031-12-31 Tax Document (2 of 3).xls": FILES[link(2)][1],
                          "2031-12-31 Tax Document (3 of 3).pdf": FILES[link(3)][1]}
    rec = stored(app, doc)
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"] is True
    assert [Path(e["file"]).read_bytes() for e in rec["invoices"]] == [
        FILES[u][1] for u in THREE], "the list is in the form's order"
    assert rec["notes"] == "form set has 3 files"
    rows = app.index_csv.read_all()
    assert [(r["PDF Filename"], r["Processing Status"]) for r in rows] == [(FIRST, "Completed")]
    assert [Path(p).name for p in app.stats["new_files"]] == ["2031-12-31 Tax Document (2 of 3).xls"]
    assert app.stats["tax_documents"] == 1 and app.stats["failed"] == 0
    assert app._already_done(doc)


def test_a_file_set_aside_is_not_asked_for_again(tmp_path, monkeypatch):
    """Of four, the second came as a script and was held in Manual Review,
    and the third did not come. Only the third is asked for next."""
    four = [link(1), link(2), link(3), link(4)]
    script = {link(2): ("run.command", b"#!/bin/sh\necho invented\n")}
    first, _tab, _doc = a_run(tmp_path, monkeypatch, four,
                              dict(everything_but(link(3), of=5), **script))
    assert first.stats["manual_review"] == 1
    app, tab, doc = a_run(tmp_path, monkeypatch, four, dict(everything_but(of=5), **script))
    assert tab.asked == [link(3)]
    held = [p.name for p in app.paths.manual_review.rglob("*") if p.is_file()]
    assert held == ["2031-12-31 Tax Document (2 of 4) command.held"]
    rec = stored(app, doc)
    assert rec["state"] == State.COMPLETED.value
    assert rec["notes"] == "form set has 4 files; " + companion.SET_ASIDE
    assert rec["notes"].count("kept in Manual Review") == 1
    assert [Path(e["file"]).name for e in rec["invoices"]] == [
        FIRST, "2031-12-31 Tax Document (3 of 4).pdf", "2031-12-31 Tax Document (4 of 4).csv"]


def test_a_run_stopped_between_two_files_does_not_save_the_first_again(tmp_path, monkeypatch):
    """Stopped while the second file was coming. The next run fetches the
    rest, and the first is not saved a second time as "(2)"."""
    with pytest.raises(KeyboardInterrupt):
        a_run(tmp_path, monkeypatch, THREE, dict(everything_but(), **{link(2): KeyboardInterrupt()}))
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but())
    assert not any(" (2)" in name for name in saved(app)), sorted(saved(app))
    assert tab.asked == [link(2), link(3)]
    assert saved(app) == {FIRST: FILES[link(1)][1],
                          "2031-12-31 Tax Document (2 of 3).xls": FILES[link(2)][1],
                          "2031-12-31 Tax Document (3 of 3).pdf": FILES[link(3)][1]}
    assert stored(app, doc)["downloaded_ok"] is True


def test_the_first_file_deleted_between_runs_is_not_fetched_again(tmp_path, monkeypatch):
    first, _tab, _doc = a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    (folder(first) / FIRST).unlink()
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but())
    assert tab.asked == [link(2)]
    assert set(saved(app)) == {"2031-12-31 Tax Document (2 of 3).xls",
                               "2031-12-31 Tax Document (3 of 3).pdf"}
    assert stored(app, doc)["downloaded_ok"] is True


def test_a_dialog_that_lists_one_more_keeps_the_files_saved(tmp_path, monkeypatch):
    first, _tab, _doc = a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    before = saved(first)
    four = [link(1), link(2), link(3), link(4)]
    app, tab, doc = a_run(tmp_path, monkeypatch, four, everything_but(of=5))
    assert tab.asked == [link(2), link(4)]
    files = saved(app)
    assert {n: files[n] for n in before} == before, "the files saved keep their names"
    assert len(set(files.values())) == len(files) == 4
    rec = stored(app, doc)
    listed = [e["file"] for e in rec["invoices"]]
    assert len(listed) == len(set(listed)) == 4
    assert rec["notes"] == "form set has 4 files"


def test_a_file_fetched_later_goes_beside_the_first_under_a_new_pattern(tmp_path, monkeypatch):
    """The naming pattern changed between the runs. The file fetched later
    goes where the first is, named from it, and a Rename then takes all
    three together."""
    first, _tab, _doc = a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but(),
                          pattern=companion.ANOTHER)
    assert tab.asked == [link(2)]
    assert saved(app)["2031-12-31 Tax Document (2 of 3).xls"] == FILES[link(2)][1]
    code, said = companion.rename(app)
    assert code == 0 and "Renamed 3 file(s)" in said, said
    where = "out/Tax Documents/Wealthfront/2031/2031-12-31 Renamed Tax Document"
    assert companion.files(tmp_path) == {FILES[link(1)][1]: where + ".pdf",
                                         FILES[link(2)][1]: where + " (2 of 3).xls",
                                         FILES[link(3)][1]: where + " (3 of 3).pdf"}
    code, said = companion.rename(app)
    assert code == 0 and companion.DONE in said, said


def test_a_move_after_takes_every_file_of_the_form(tmp_path, monkeypatch):
    a_run(tmp_path, monkeypatch, THREE, everything_but(link(2)))
    app, _tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but())
    app = companion.make_app(tmp_path, documents=True)
    before = companion.files(tmp_path)
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")
    code, said = companion.rename(app)
    assert code == 0 and "Moved 3 file(s)" in said, said
    assert companion.files(tmp_path) == {body: "Watched/" + path[len("out/"):]
                                         for body, path in before.items()}
    assert companion.bodies_listed(stored(app, doc)) == [FILES[u][1] for u in THREE]


def test_the_first_file_that_never_comes_saves_nothing_as_before(tmp_path, monkeypatch):
    app, tab, doc = a_run(tmp_path, monkeypatch, THREE, everything_but(link(1)))
    rec = stored(app, doc)
    assert rec["state"] == State.FAILED.value and "Download did not start" in rec["notes"] \
        or "No safe download control" in rec["notes"], rec["notes"]
    assert tab.asked == [link(1)]
    assert not (app.paths.tax_documents / "Wealthfront").exists()


def test_a_first_file_that_fails_its_check_asks_for_no_other(tmp_path, monkeypatch):
    app = companion.make_app(tmp_path)
    companion.stand_in(monkeypatch, app)
    monkeypatch.setattr(app_mod.receipt_pdf, "validate_pdf",
                        lambda path, min_bytes: SimpleNamespace(ok=False, reason="invented",
                                                                size_bytes=1, page_count=0))
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links", lambda page, a, t: list(THREE))
    monkeypatch.setattr(app_mod.site, "select_tax_year", lambda page, year: None)
    tab = FormTab(everything_but())
    doc = companion.a_form()
    app.download_one(tab, doc, storage.build_pdf_filename(doc.date, doc.summary, "", record=doc))
    rec = stored(app, doc)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and tab.asked == [link(1)]
    assert not rec.get("invoices")
