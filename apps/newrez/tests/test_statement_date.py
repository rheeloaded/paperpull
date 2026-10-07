"""A statement is named for the date it prints, and keeps the key it has.

His Pilot on 0.37.0 saved three statements and he noticed each file was
named for the last day of its month while the statement inside is dated
early in the month (#38). The statements list dates a row by its month and
year and nothing finer, so the last day of the month was the only day the
app had. The statement prints its own date, and nothing says every
account's falls on the same day, so it is read off each statement.

The key a document is remembered by must not move, or every statement
already saved looks new and is fetched again beside the copy on disk. So
the record keeps the month's date and only the file and its ledger row take
the printed one. A statement saved before this is brought into line by
Rename, from the file already on disk.

The same date says when a file is not the statement its row asked for.
One dated in the month of another statement on the list, with no date of
its own month near the label, is what a download the capture before gave
up on looks like when it lands during the next capture. It is not saved
under this row's name. A statement's own due date is in the next month,
which is on the list too, so a due date read first must not refuse it.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402  binds this provider's AppSpec
import newrez_docs  # noqa: E402
import newrez_site as site  # noqa: E402
from paperpull_core import storage as core_storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402

# Invented, in the shape a mortgage statement prints its header.
AUGUST = ["Newrez Mortgage Statement", "Statement Date: 08/06/2026",
          "Payment Due Date: 09/01/2026", "Amount Due $1,234.56"]


def _text_pdf(path: Path, lines) -> None:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b" " * 4000)


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def _app(tmp_path, monkeypatch, lines=None, apply=False):
    app = object.__new__(newrez_docs.App)
    app.args = SimpleNamespace(apply=apply, redownload=False)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "owner": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.document_index_csv,
                                    storage.DOCUMENT_INDEX_COLUMNS)
    app._dl_dir = tmp_path / "dl"
    app.stats = {"mode": "", "manual_review": 0, "new_files": [], "dates": [],
                 "statements": 0, "tax_documents": 0, "insurance_documents": 0,
                 "other": 0, "validation_failures": 0, "duplicate_filenames": 0,
                 "failed": 0}
    app.check_session = lambda page: None
    app.write_failure = lambda *a, **k: None
    monkeypatch.setattr(newrez_docs.site, "goto_documents", lambda page: True)

    def fake_download(page, dl_dir, iso, out_path, title="", trace=None):
        _text_pdf(Path(out_path), lines or [])
        return True
    monkeypatch.setattr(newrez_docs.site, "download_bill", fake_download)
    return app


class _Page:
    url = "https://servicing.newrez.com/servicing/1234567/statements/monthly"


def _statement(month_end="2026-08-31", human="August 31, 2026"):
    return newrez_docs.Document(title="Mortgage Statement - %s" % human,
                                category="Statement", summary="Account Statement",
                                date=month_end)


def _names(folder: Path):
    return sorted(p.name for p in folder.glob("*.pdf"))


# -- reading the date -------------------------------------------------------

def test_the_date_beside_statement_date_is_read_only_inside_the_rows_month():
    text = "\n".join(AUGUST)
    assert site.printed_statement_date(text, "2026-08-31") == "2026-08-06"
    # Not the same day for everyone, whatever day it prints is the one
    assert site.printed_statement_date("STATEMENT DATE 08/17/26", "2026-08-31") == "2026-08-17"
    assert site.printed_statement_date("Statement Date: August 5, 2026", "2026-08-31") == "2026-08-05"
    # the first date after the label, whatever form a later one takes
    assert site.printed_statement_date(
        "Statement Date: 08/06/2026 Due Sep 1, 2026", "2026-08-31") == "2026-08-06"
    # a date in another month is not this row's, so nothing is read
    assert site.printed_statement_date(text, "2026-09-30") == ""
    # the due date comes first after the label, and it is next month's
    assert site.printed_statement_date(
        "Statement Date Payment Due Date\n09/01/2026 08/06/2026", "2026-08-31") == ""
    # no label, or a label with no date after it
    assert site.printed_statement_date("Payment Due Date: 08/01/2026", "2026-08-31") == ""
    assert site.printed_statement_date("Statement Date: see below", "2026-08-31") == ""
    assert site.printed_statement_date("", "2026-08-31") == ""
    assert site.printed_statement_date(text, "") == ""


# -- a statement downloaded from now on ------------------------------------

def test_a_statement_is_named_for_its_printed_date_and_keeps_its_key(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, AUGUST)
    doc = _statement()
    key = doc.key
    app.download_one(_Page(), doc, "2026-08-31 Newrez Account Statement.pdf")

    folder = app.paths.folder_for("Statement")
    assert _names(folder) == ["2026-08-06 Newrez Account Statement.pdf"]
    rec = app.progress.get(key)
    assert rec["state"] == State.COMPLETED.value
    assert rec["date"] == "2026-08-31", "the key's date must not move"
    assert rec["statement_date"] == "2026-08-06"
    assert rec["pdf_filename"] == "2026-08-06 Newrez Account Statement.pdf"
    assert Path(rec["pdf_path"]).exists()
    row = app.index_csv.read_all()[-1]
    assert row["Document Date"] == "2026-08-06"
    assert row["PDF Filename"] == "2026-08-06 Newrez Account Statement.pdf"
    # the next discovery reads the same row and knows it is done
    assert app._already_done(_statement())


def test_a_statement_without_a_date_in_its_month_keeps_the_months_name(tmp_path, monkeypatch):
    """July is not on this list, so a July date is not another row's. The
    file is kept under the month's name, and the note says to check it."""
    app = _app(tmp_path, monkeypatch, ["Statement Date: 07/06/2026"])
    doc = _statement()
    app.download_one(_Page(), doc, "2026-08-31 Newrez Account Statement.pdf")
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-31 Newrez Account Statement.pdf"]
    rec = app.progress.get(doc.key)
    assert rec["statement_date"] == "" and rec["state"] == State.COMPLETED.value
    row = app.index_csv.read_all()[-1]
    assert row["Document Date"] == "2026-08-31"
    assert "not in the month its row names" in row["Notes"]


def test_a_label_row_over_a_value_row_is_read():
    """A header printed as labels over values puts the date well past the
    label. Forty characters did not reach it."""
    text = ("Statement Date                Payment Due Date              Amount Due\n"
            "08/06/2026 09/01/2026 $1,234.56")
    assert text.index("08/06") - len("Statement Date") > 40
    assert site.printed_statement_date(text, "2026-08-31") == "2026-08-06"


def test_what_the_date_inside_says_about_the_row():
    others = {"2026-07", "2026-09"}
    assert site.statement_verdict("Statement Date: 08/06/2026", "2026-08-31", others) == "this month"
    # in the month of another statement on the list, with nothing of this month's near
    assert site.statement_verdict("Statement Date: 09/04/2026", "2026-08-31", others) == "another row"
    assert site.statement_verdict("STATEMENT DATE\n09/04/26", "2026-08-31", others) == "another row"
    assert site.statement_verdict("Statement Date: 09/04/2026\nPayment Due Date: 10/01/2026",
                                  "2026-08-31", others) == "another row"
    # the same layout as a row of labels over a row of values, which is
    # how September's statement looks when it lands in August's capture
    assert site.statement_verdict("Statement Date Payment Due Date\n09/04/2026 10/01/2026",
                                  "2026-08-31", others) == "another row"
    # a month the list does not show is not another row's
    assert site.statement_verdict("Statement Date: 09/04/2026", "2026-08-31", set()) == "another month"
    # this statement's own due date, read first, never refuses it
    assert site.statement_verdict("Statement Date:\nAccount Number 1234567\nPayment Due Date 09/01/2026",
                                  "2026-08-31", others) == "another month"
    # values in an order the labels do not follow, this month's date among them
    assert site.statement_verdict("Statement Date Payment Due Date\n09/01/2026 08/06/2026",
                                  "2026-08-31", others) == "unclear"
    assert site.statement_verdict("Payment Due Date\nStatement Date\n09/01/2026\n08/03/2026",
                                  "2026-08-31", others) == "unclear"
    # an earlier mention of the last statement, then this one's own date
    assert site.statement_verdict("since your last statement date 07/06/2026.\nStatement Date: 08/06/2026",
                                  "2026-08-31", others) == "unclear"
    assert site.statement_verdict("", "2026-08-31", others) == "no date"
    assert site.statement_verdict("Statement Date: see below", "2026-08-31", others) == "no date"
    assert site.statement_verdict("Statement Date: 08/06/2026", "", others) == "no date"


def _listed(app, *docs):
    """Statements discovery found on the list."""
    for doc in docs:
        rec = doc.to_dict()
        rec["state"] = State.DISCOVERED.value
        app.discovery.update(doc.key, rec)


@pytest.mark.parametrize("lines", [
    AUGUST,
    # a row of labels over a row of values
    ["Newrez Mortgage Statement", "Statement Date Payment Due Date", "08/06/2026 09/01/2026"],
], ids=["label beside its date", "labels over values"])
def test_a_statement_dated_in_another_rows_month_is_not_saved_under_this_name(tmp_path, monkeypatch,
                                                                               lines):
    """The capture before gave up on August and its download landed while
    July was being captured. The file is August's, so it is not saved as
    July's, and July stays undone so the next run asks for it again."""
    app = _app(tmp_path, monkeypatch, lines)
    failures = []
    app.write_failure = lambda step, reason, **k: failures.append((step, reason, k))
    july = _statement("2026-07-31", "July 31, 2026")
    _listed(app, july, _statement(), _statement("2026-09-30", "September 30, 2026"))
    app.download_one(_Page(), july, "2026-07-31 Newrez Account Statement.pdf")

    assert _names(app.paths.folder_for("Statement")) == []
    assert _names(app.paths.manual_review) == ["2026-07-31 Newrez Account Statement.pdf"]
    rec = app.progress.get(july.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert rec["pdf_path"] == "" and not rec.get("downloaded_ok")
    assert rec["date"] == "2026-07-31", "the key's date must not move"
    assert not app._already_done(_statement("2026-07-31", "July 31, 2026"))
    row = app.index_csv.read_all()[-1]
    assert row["Processing Status"] == "Needs Manual Review"
    assert "another statement on the list" in row["Notes"]
    assert Path(row["PDF Full Path"]).parent == app.paths.manual_review
    [(step, reason, kw)] = failures
    assert (step, reason) == ("check the saved statement", "the statement is dated in another month")
    assert kw["capture"]["statement_check"] == "another row"
    assert app.stats["manual_review"] == 1 and app.stats["statements"] == 0


def test_a_statement_whose_dates_disagree_keeps_its_name_with_a_note(tmp_path, monkeypatch):
    """A mention of the last statement's date ahead of this one's own. It
    is not refused, since one label names this month, and it is not
    renamed, since the first does not."""
    app = _app(tmp_path, monkeypatch, ["since your last statement date 07/06/2026.",
                                       "Statement Date: 08/06/2026"])
    doc = _statement()
    _listed(app, _statement("2026-07-31", "July 31, 2026"), doc)
    app.download_one(_Page(), doc, "2026-08-31 Newrez Account Statement.pdf")
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-31 Newrez Account Statement.pdf"]
    assert app.progress.get(doc.key)["state"] == State.COMPLETED.value
    assert "disagree about the month" in app.index_csv.read_all()[-1]["Notes"]


@pytest.mark.parametrize("lines", [
    # this statement's own due date is the first date after the label
    ["Statement Date:", "Account Number 1234567", "Payment Due Date 09/01/2026"],
    # the values come out in an order the labels do not follow
    ["Statement Date Payment Due Date", "09/01/2026 08/06/2026"],
    # the labels come out in the other order, each over its own value
    ["Payment Due Date", "Statement Date", "09/01/2026", "08/03/2026"],
], ids=["due date read first", "values out of order", "labels out of order"])
def test_this_statements_own_due_date_read_first_never_refuses_it(tmp_path, monkeypatch, lines):
    """A statement's own due date is in the next month, which is on the
    list. Read first, it looked like the next month's statement, and every
    statement but the newest would have gone to Manual Review on every
    run. It is kept, under the month's name, with a note."""
    app = _app(tmp_path, monkeypatch, lines)
    doc = _statement()
    _listed(app, _statement("2026-07-31", "July 31, 2026"), doc,
            _statement("2026-09-30", "September 30, 2026"))
    app.download_one(_Page(), doc, "2026-08-31 Newrez Account Statement.pdf")
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-31 Newrez Account Statement.pdf"]
    assert _names(app.paths.manual_review) == []
    assert app.progress.get(doc.key)["state"] == State.COMPLETED.value
    assert "Open it to check" in app.index_csv.read_all()[-1]["Notes"]


def test_a_1098_that_lands_in_a_statements_capture_is_not_kept_as_that_statement(tmp_path,
                                                                                 monkeypatch):
    """A 1098 prints no Statement Date, so one whose download arrived late,
    during a statement's capture, read as "no date" and was kept as that
    statement. A statement always prints its date, a 1098 notice in it or
    not."""
    others = {"2025-12"}
    assert site.statement_verdict("Form 1098 Mortgage Interest Statement", "2026-01-31", others) \
        == "a tax form"
    assert site.statement_verdict("Statement Date: 01/03/2026\nYour Form 1098 is on its way",
                                  "2026-01-31", others) == "this month"
    app = _app(tmp_path, monkeypatch, ["Form 1098 Mortgage Interest Statement", "Tax year 2025"])
    failures = []
    app.write_failure = lambda step, reason, **k: failures.append((step, reason, k))
    doc = _statement("2026-01-31", "January 31, 2026")
    app.download_one(_Page(), doc, "2026-01-31 Newrez Account Statement.pdf")
    assert _names(app.paths.folder_for("Statement")) == []
    assert _names(app.paths.manual_review) == ["2026-01-31 Newrez Account Statement.pdf"]
    rec = app.progress.get(doc.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and not rec.get("downloaded_ok")
    assert "Form 1098 and not a statement" in app.index_csv.read_all()[-1]["Notes"]
    [(step, reason, kw)] = failures
    assert reason == "the statement is a tax form"
    assert kw["capture"]["statement_check"] == "a tax form"


def test_a_1098_is_never_renamed(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, ["Form 1098", "Statement Date: 12/06/2025"])
    doc = newrez_docs.Document(title="Tax Document - December 31, 2025",
                               category="Tax Document", summary="Tax Document",
                               date="2025-12-31")
    app.download_one(_Page(), doc, "2025-12-31 Newrez Tax Document.pdf")
    assert _names(app.paths.folder_for("Tax Document")) == ["2025-12-31 Newrez Tax Document.pdf"]


# -- a statement saved before this, brought into line by Rename --------------

def _saved_before(app, doc, lines):
    """A statement saved by an earlier build, named for its month's last day."""
    folder = app.paths.folder_for(doc.category)
    name = "%s Newrez %s.pdf" % (doc.date, doc.summary)
    path = folder / name
    _text_pdf(path, lines)
    doc.pdf_path, doc.pdf_filename = str(path), name
    doc.state = State.COMPLETED.value
    doc.downloaded_ok = True
    app.progress.update(doc.key, doc.to_dict())
    app.discovery.update(doc.key, {k: v for k, v in doc.to_dict().items()
                                   if k not in ("pdf_path", "pdf_filename")})
    app.index_csv.append_rows([{
        "Document Date": doc.date, "Category": doc.category,
        "Document Summary": doc.summary, "Document Title": doc.title,
        "PDF Filename": name, "PDF Full Path": str(path),
        "Processing Status": "Completed"}])
    return path


def test_rename_brings_a_statement_saved_before_this_to_its_printed_date(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    august = _statement()
    tax = newrez_docs.Document(title="Tax Document - December 31, 2025",
                               category="Tax Document", summary="Tax Document",
                               date="2025-12-31")
    old = _saved_before(app, august, AUGUST)
    _saved_before(app, tax, ["Form 1098", "Statement Date: 12/06/2025"])
    keys = set(app.progress.data)

    # a preview changes nothing, on disk or in the ledger
    app.cmd_rename()
    assert "2026-08-06 Newrez Account Statement.pdf" in capsys.readouterr().out
    assert old.exists()
    assert app.index_csv.read_all()[0]["Document Date"] == "2026-08-31"

    app.args.apply = True
    app.cmd_rename()
    folder = app.paths.folder_for("Statement")
    assert _names(folder) == ["2026-08-06 Newrez Account Statement.pdf"]
    assert _names(app.paths.folder_for("Tax Document")) == ["2025-12-31 Newrez Tax Document.pdf"]
    row = app.index_csv.read_all()[0]
    assert row["Document Date"] == "2026-08-06"
    assert row["PDF Filename"] == "2026-08-06 Newrez Account Statement.pdf"
    assert set(app.progress.data) == keys, "a rename never moves a key"
    rec = app.progress.get(august.key)
    assert rec["date"] == "2026-08-31"
    assert rec["pdf_filename"] == "2026-08-06 Newrez Account Statement.pdf"
    assert app._already_done(_statement())

    # and a second time there is nothing left to do
    capsys.readouterr()
    app.cmd_rename()
    assert "already named" in capsys.readouterr().out


def test_rename_names_a_saved_statement_that_may_be_another_months(tmp_path, monkeypatch, capsys):
    """A July file saved by an earlier build holds a statement dated in
    August, which is also on the list. Rename says so and leaves it be."""
    app = _app(tmp_path, monkeypatch)
    july = _statement("2026-07-31", "July 31, 2026")
    old = _saved_before(app, july, AUGUST)
    _listed(app, _statement())
    app.cmd_rename()
    out = capsys.readouterr().out
    assert "!! 2026-07-31 Newrez Account Statement.pdf" in out
    assert "may be that one" in out
    app.args.apply = True
    app.cmd_rename()
    assert old.exists()
    assert _names(app.paths.folder_for("Statement")) == ["2026-07-31 Newrez Account Statement.pdf"]


def test_rename_under_a_naming_pattern_still_finds_the_record(tmp_path, monkeypatch):
    """The rename matches a ledger row to its record by date and title.
    The row now carries the printed date and the record the month's, so
    without a copy dated as the row is, a pattern naming the kind lost it
    and the file was offered a name with nothing where the kind was."""
    app = _app(tmp_path, monkeypatch, apply=True)
    _saved_before(app, _statement(), AUGUST)
    core_storage.set_filename_patterns({"filename_pattern": "{date:yyyy-mm-dd} {provider} {kind}"})
    app.cmd_rename()
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-06 Newrez Statement.pdf"]
    app.cmd_rename()
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-06 Newrez Statement.pdf"]


def test_rename_leaves_alone_a_row_naming_a_statement_it_does_not_hold(tmp_path, monkeypatch):
    """An index copied from another folder names the statements there. The
    one this app holds is brought to its printed date, and the row naming
    the copy elsewhere, of the same title, date and file name, is left as it
    is. Its file is not read for a date and its row takes nothing of the
    rename."""
    app = _app(tmp_path / "out", monkeypatch, apply=True)
    august = _statement()
    held = _saved_before(app, august, AUGUST)
    outside = tmp_path / "elsewhere" / held.name
    _text_pdf(outside, AUGUST)
    copied = {"Document Date": august.date, "Category": august.category,
              "Document Summary": august.summary, "Document Title": august.title,
              "PDF Filename": outside.name, "PDF Full Path": str(outside),
              "Processing Status": "Completed"}
    app.index_csv.append_rows([copied])
    app.cmd_rename()
    assert _names(app.paths.folder_for("Statement")) == ["2026-08-06 Newrez Account Statement.pdf"]
    rows = app.index_csv.read_all()
    assert rows[0]["Document Date"] == "2026-08-06"
    assert {k: rows[1][k] for k in copied} == copied
    assert outside.is_file()
