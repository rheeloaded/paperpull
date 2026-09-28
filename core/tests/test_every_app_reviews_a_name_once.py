"""A name a person has fixed is not asked about again (#47).

review_names asks about each receipt whose name the app was unsure of, the
rows of the index marked Low or Review. Renaming one set its status to
Completed and left its confidence Low, so the next review asked about every
receipt already renamed, in all thirteen receipt apps, while the tester
expected only the ones he had kept as they were. These run each app's own
review_names twice over an index held in memory, with the typing stood in
for.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d)
              and "def cmd_review_names" in entry_of(d).read_text(encoding="utf-8"))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


class _Csv:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]

    def read_all(self):
        return [dict(r) for r in self.rows]

    def rewrite(self, rows):
        self.rows = [dict(r) for r in rows]


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def update(self, key, record, save=True):
        self.data.setdefault(key, {}).update(record)


def _row(folder: Path, number: str, name: str) -> dict:
    pdf = folder / name
    pdf.write_bytes(b"%PDF-1.4\n% invented\n%%EOF\n")
    return {"Purchase Date": "2026-05-14", "Purchase Type": "Online",
            "Order or Receipt Number": number, "PDF Filename": name,
            "PDF Full Path": str(pdf), "Document Type": "Receipt",
            "Classification Confidence": "Low", "Processing Status": "Review Needed",
            "Notes": ""}


def test_every_receipt_app_is_covered():
    assert len(APPS) >= 13, [a.name for a in APPS]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_renamed_receipt_is_not_asked_about_again(app, tmp_path, monkeypatch, capsys):
    mod = load(app)
    inst = object.__new__(mod.App)
    inst.index_csv = _Csv([_row(tmp_path, "ORDER-0001", "2026-05-14 Unsure Receipt.pdf"),
                           _row(tmp_path, "ORDER-0002", "2026-05-14 Other Receipt.pdf")])
    inst.order_csv = _Csv([])
    inst.progress = _Store()
    inst.config = {"max_path_length": 240}

    answers = iter(["Garden Hose", ""])          # rename the first, keep the second
    monkeypatch.setattr(mod, "ask", lambda prompt: next(answers))
    inst.cmd_review_names()
    renamed = [r for r in inst.index_csv.rows if r["Order or Receipt Number"] == "ORDER-0001"][0]
    assert "Garden Hose" in renamed["PDF Filename"]

    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "")
    inst.cmd_review_names()
    assert len(asked) == 1, "only the receipt kept as it was is asked about again"
    assert "ORDER-0002" in capsys.readouterr().out.split("need review")[-1]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_receipt_renamed_before_the_fix_is_not_asked_about_either(app, tmp_path, monkeypatch):
    """The tester's archive, renamed on 0.39.0, still says Low beside each
    name he fixed. The note every rename leaves is what tells them apart."""
    mod = load(app)
    inst = object.__new__(mod.App)
    old = _row(tmp_path, "ORDER-0003", "2026-05-14 Gas Station Receipt.pdf")
    old.update({"Processing Status": "Completed", "Notes": "renamed via --review-names"})
    inst.index_csv = _Csv([old])
    inst.order_csv = _Csv([])
    inst.progress = _Store()
    inst.config = {"max_path_length": 240}
    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "")
    inst.cmd_review_names()
    assert asked == []
