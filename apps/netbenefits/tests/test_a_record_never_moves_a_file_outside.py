"""A held statement's record never moves a file outside the account's folders.

A statement held until its plan is known is judged again at the end of a
run (_judge_held), filed when it names its plan and set aside in Manual
Review when it cannot. Its record names the file, and a history file
imported from somewhere else can name any file on this computer, which was
then moved (a private report of 2026-11-10). Only a document the account
holds, in a folder it files in once links and ".." are followed, is judged
now. Every name and file here is invented.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import netbenefits_site as site  # noqa: E402
import netbenefits_docs as docs  # noqa: E402

PLAN = {"digest": "d1", "name": "Example 401(k) Plan"}


def judged(tmp_path, monkeypatch, named):
    folder = tmp_path / "acct"
    review = folder / "Manual Review"
    review.mkdir(parents=True, exist_ok=True)
    rec = {"held": True, "plan": "d1", "pdf_path": named, "state": "Needs Manual Review",
           "downloaded_ok": False, "date": "2026-03-31", "title": "Quarterly Statement",
           "category": "Statement", "notes": docs.HELD}
    recorded = []
    app = SimpleNamespace(
        _plans_by_digest={"d1": PLAN}, progress=SimpleNamespace(data={"k": rec}),
        paths=SimpleNamespace(manual_review=review, filing_folders=lambda: [review]),
        config={"max_path_length": 240}, stats={"manual_review": 0, "failed": 0},
        _place_from_saved=lambda plans: None,
        # Read, and found to name no plan, so it would be set aside.
        _names_its_plan=lambda text, doc, plans: ([], "names no plan"),
        _record=lambda doc, state, notes="": recorded.append((doc.pdf_path, state)),
        _write_row=lambda *a, **k: None, write_failure=lambda *a, **k: None)
    app._set_aside = lambda doc, path: docs.App._set_aside(app, doc, path)
    monkeypatch.setattr(site, "employer_of", lambda plan: "Example Employer")
    monkeypatch.setattr(docs.receipt_pdf, "pdf_text", lambda path: "a statement's text")
    docs.App._judge_held(app)
    return review, recorded


def test_a_file_outside_the_accounts_folders_stays_where_it_is(tmp_path, monkeypatch):
    decoy = tmp_path / "outside" / "decoy.pdf"
    decoy.parent.mkdir()
    decoy.write_bytes(b"%PDF-1.4 not the account's")
    review, recorded = judged(tmp_path, monkeypatch, str(decoy))
    assert decoy.read_bytes() == b"%PDF-1.4 not the account's"
    assert list(review.iterdir()) == [] and recorded == []


def test_a_held_statement_in_manual_review_is_still_judged(tmp_path, monkeypatch):
    held = tmp_path / "acct" / "Manual Review" / "2026-03-31 Quarterly Statement.pdf"
    held.parent.mkdir(parents=True)
    held.write_bytes(b"%PDF-1.4 held")
    review, recorded = judged(tmp_path, monkeypatch, str(held))
    # Set aside where it already is, and recorded as the wrong document.
    assert held.exists() and len(recorded) == 1
