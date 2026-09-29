"""Round five (#42), from his 0.40.0 Pilot.

Four of five receipts were saved. The one of 2026-09-19 came from the row's
own control, failed the check that it mentions Meijer or the purchase, and
was put aside in Manual Review. The log said it was retrying, and on that
path nothing was retried. His second Pilot then skipped it, because a copy
put aside counted as done whenever it passed the check without its words.
He opened that receipt by hand and it was a normal one. Every amount, store
and word below is invented."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import meijer_receipts as mr
import meijer_site as site
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, Purchase, State


def _text_pdf(lines) -> bytes:
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
    return bytes(out) + b" " * 4000


RECEIPT = _text_pdf(["MEIJER STORE 000", "09/19/26 14:02", "SUBTOTAL 21.10",
                     "TAX 1.27", "TOTAL 22.37", "THANK YOU"])
SOMETHING_ELSE = _text_pdf(["ZEBRAFISH QUARTERLY", "Page 1 of 1", "09/19/26",
                            "Terms and conditions apply"])


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield


def _purchase():
    return Purchase(purchase_type=IN_STORE, purchase_date="2026-09-19",
                    order_number="pexample0919", total="$22.37",
                    summary="Mixed Purchases", confidence="Low")


def _app(tmp_path, progress=None):
    app = object.__new__(mr.App)
    app.args = SimpleNamespace(redownload=False)
    app.config = {"min_pdf_bytes": 3000, "max_path_length": 240, "owner": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.progress.data, app.progress._loaded = dict(progress or {}), True
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.discovery.data, app.discovery._loaded = {}, True
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.stats = {"validation_failures": 0, "manual_review": 0, "new_files": [],
                 "receipts_downloaded": 0, "no_receipt": 0, "failed": 0,
                 "duplicate_filenames": 0}
    app.write_failure = lambda *a, **k: None
    return app


def _pressing(monkeypatch, *bodies):
    """The row's control, answering with each of `bodies` in turn."""
    presses = []

    def press(page, purchase, trace=None):
        presses.append(purchase.purchase_date)
        return bodies[min(len(presses), len(bodies)) - 1]
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "goto_orders", lambda page, page_no=1: None)
    monkeypatch.setattr(site, "show_tab_for", lambda page, t: True)
    monkeypatch.setattr(site, "press_row_receipt", press)
    return presses


PAGE = SimpleNamespace(url="https://www.meijer.com/shopping/order-history.html")


def _pdfs(folder: Path):
    return sorted(p.name for p in folder.glob("*.pdf"))


# -- the done check ---------------------------------------------------------------

def test_a_receipt_put_aside_for_its_words_is_tried_again(tmp_path):
    aside = tmp_path / "Manual Review" / "2026-09-19 Meijer Mixed Purchases Receipt.pdf"
    aside.parent.mkdir(parents=True, exist_ok=True)
    aside.write_bytes(SOMETHING_ELSE)
    p = _purchase()
    app = _app(tmp_path, {p.key: {"state": State.NEEDS_MANUAL_REVIEW.value,
                                  "pdf_path": str(aside),
                                  "notes": "PDF validation failed: Extractable text does not mention Meijer/order details"}})
    assert app._already_done(p) is False


def test_a_receipt_saved_under_a_low_confidence_name_is_still_done(tmp_path):
    """The other four of his Pilot, saved and valid, then marked for review
    because the row names no items. They are never fetched twice."""
    p = _purchase()
    app = _app(tmp_path, {p.key: {"state": State.NEEDS_MANUAL_REVIEW.value,
                                  "downloaded_ok": True, "pdf_path": "gone.pdf",
                                  "notes": "Low classification confidence"}})
    assert app._already_done(p) is True


def test_a_copy_put_aside_that_passes_its_check_is_done(tmp_path):
    aside = tmp_path / "Manual Review" / "x.pdf"
    aside.parent.mkdir(parents=True, exist_ok=True)
    aside.write_bytes(RECEIPT)
    p = _purchase()
    app = _app(tmp_path, {p.key: {"state": State.NEEDS_MANUAL_REVIEW.value,
                                  "pdf_path": str(aside)}})
    assert app._already_done(p) is True


# -- the retry it announced --------------------------------------------------------

def test_the_row_receipt_is_pressed_once_more_before_it_is_put_aside(tmp_path, monkeypatch):
    presses = _pressing(monkeypatch, SOMETHING_ELSE, RECEIPT)
    app = _app(tmp_path)
    p = _purchase()
    assert app._save_receipt(PAGE, p) is True
    assert len(presses) == 2
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    assert _pdfs(folder) == ["2026-09-19 Meijer Mixed Purchases Receipt.pdf"]
    assert (folder / _pdfs(folder)[0]).read_bytes() == RECEIPT
    assert _pdfs(app.paths.manual_review) == []
    assert app.progress.get(p.key)["downloaded_ok"] is True


def test_a_receipt_failing_every_run_is_kept_once_in_manual_review(tmp_path, monkeypatch):
    presses = _pressing(monkeypatch, SOMETHING_ELSE)
    app = _app(tmp_path)
    assert app._save_receipt(PAGE, _purchase()) is False
    assert len(presses) == 2, "pressed, then pressed once more"
    # the next run tries it again, since it is not done, and fails the same way
    p = _purchase()
    assert app._already_done(p) is False
    assert app._save_receipt(PAGE, p) is False
    assert len(_pdfs(app.paths.manual_review)) == 1
    assert _pdfs(app.paths.folder_for(IN_STORE, "Receipt")) == []
    rec = app.progress.get(p.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert Path(rec["pdf_path"]).exists()


def test_a_different_file_put_aside_the_next_run_is_kept_beside_the_first(tmp_path, monkeypatch):
    """Two different wrong files are two pieces of evidence, both kept."""
    other = _text_pdf(["ZEBRAFISH ANNUAL", "Page 1 of 2"])
    _pressing(monkeypatch, SOMETHING_ELSE)
    app = _app(tmp_path)
    app._save_receipt(PAGE, _purchase())
    _pressing(monkeypatch, other)
    app._save_receipt(PAGE, _purchase())
    assert len(_pdfs(app.paths.manual_review)) == 2


# -- the file to attach --------------------------------------------------------------

def test_the_file_to_attach_says_what_was_put_aside_and_never_its_words(tmp_path, monkeypatch, capsys):
    _pressing(monkeypatch, SOMETHING_ELSE)
    app = _app(tmp_path)
    app._save_receipt(PAGE, _purchase())
    out = capsys.readouterr().out
    attempt = app.paths.diagnostics / "download-attempt.json"
    assert str(attempt) in out
    text = attempt.read_text(encoding="utf-8")
    info = json.loads(text)
    aside = [t for t in info["responses"] if t.get("note") == "the receipt was put aside"]
    assert len(aside) == 1
    assert "does not mention" in aside[0]["reason"]
    facts = aside[0]["pdf"]
    assert facts["pages"] == 1 and facts["prints_a_date"] is True
    assert facts["prints_an_amount"] is False and facts["words"] == []
    assert "zebrafish" not in text.lower() and "terms" not in text.lower()


def test_pdf_facts_names_only_words_from_its_own_list(tmp_path):
    f = tmp_path / "r.pdf"
    f.write_bytes(RECEIPT)
    facts = site.pdf_facts(f)
    assert facts["words"] == ["meijer", "subtotal", "total", "tax", "store", "thank"]
    assert facts["prints_an_amount"] is True
    assert set(facts) == {"bytes", "pages", "text_characters", "prints_a_date",
                          "prints_an_amount", "words"}
