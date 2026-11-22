"""A My Documents title never names a file or reaches the run's output.

Kaiser's My Documents rows carry the site's own titles, and on a health
account a title can hold a name, a clinic or a condition. Only the
classifier's fixed words name a file and are printed. Every value here is
made up."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_docs as connector

CANARY = "Letter for CANARY-PATIENT-4417 about CANARY-DIAGNOSIS-90210"


def app(tmp_path, monkeypatch, *flags):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic",
        "output_dir": str(tmp_path / "archive"),
        "profile_dir": str(tmp_path / "profile"),
        "min_pdf_bytes": 200,
    }))
    monkeypatch.setattr(connector.App, "_setup_logging", lambda self: None)
    return connector.App(connector.build_parser().parse_args(["--config", str(config), *flags]))


def row(title, document_id):
    return SimpleNamespace(title=title, date_text="2031-04-06", account="",
                           document_id=document_id)


def test_an_unrecognized_title_is_filed_under_a_fixed_word(tmp_path, monkeypatch, capsys):
    kaiser = app(tmp_path, monkeypatch, "--pilot", "--dry-run")
    assert kaiser._record_rawdoc(row(CANARY, "a" * 64), "https://example.invalid/") == 1
    assert kaiser._record_rawdoc(row("Membership Notice CANARY-MRN-7731", "b" * 64),
                                 "https://example.invalid/") == 1
    docs = kaiser._select()
    assert {doc.summary for doc in docs} == {"Document"}
    kaiser.process(docs, dry_run=True)
    kaiser._pilot_report(docs)
    said = capsys.readouterr().out
    assert "CANARY" not in said, said
    assert "Document.pdf" in said


def test_a_recognized_title_keeps_its_fixed_summary(tmp_path, monkeypatch):
    kaiser = app(tmp_path, monkeypatch, "--pilot", "--dry-run")
    kaiser._record_rawdoc(row("Form 1095-B for CANARY-PATIENT-4417", "c" * 64),
                          "https://example.invalid/")
    (doc,) = kaiser._select()
    assert doc.summary == "Tax Form 1095"
    assert "CANARY" not in connector.build_pdf_filename(doc.date, doc.summary, "", record=doc)


def test_a_row_shown_only_in_the_viewer_is_left_not_taken():
    """Scope. A My Documents row with no Download PDF link that is not
    Premium Bills opens only in Kaiser's viewer, a letter or a record the
    site does not offer as a file, so it is left and the list still reads."""
    import kaiser_site as site
    page = site._parse_page({"range": None, "previous": None, "next": None, "rows": [
        ["getdoc_1", "Apr 6, 2031", "Premium Bills", False],
        ["getdoc_2", "Apr 5, 2031", "Visit Summary CANARY-DIAGNOSIS-90210", False],
        ["getdoc_3", "Apr 4, 2031", "Membership Notice", True],
    ]})
    assert [site.offered(row) for row in page.rows] == [True, False, True]
