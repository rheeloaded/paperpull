"""The audit a file naming template is designed from.

A pattern can only use what an app knows when it names a file, so this
tool is what the settings page's field list and its fill rates rest on.
It has to see every app, and it must never print a value from anybody's
records, only field names and counts.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

naming_fields = pytest.importorskip("naming_fields")


def test_every_app_has_a_record_the_tool_can_read():
    apps = [p for p in (REPO / "apps").iterdir()
            if p.is_dir() and naming_fields.entry_of(p)]
    assert len(apps) >= 49
    for app in apps:
        keys = naming_fields.record_keys(naming_fields.entry_of(app))
        assert keys & {"date", "purchase_date"}, app.name


def test_an_archive_is_measured_in_counts_and_never_values(tmp_path, capsys):
    install = tmp_path / "Chase Statements"
    install.mkdir()
    (install / "chase_docs.py").write_text("", encoding="utf-8")
    (install / "progress.json").write_text(json.dumps({
        "a": {"date": "2026-01-31", "account": "Sapphire CANARYACCOUNT 4111",
              "summary": "CANARYSUMMARY Statement", "category": "Statement"},
        "b": {"date": "2026-02-28", "account": "", "summary": "Statement",
              "category": "Statement"}}), encoding="utf-8")
    naming_fields.main(["--installs", str(tmp_path)])
    out = capsys.readouterr().out
    assert "CANARY" not in out and "4111" not in out
    row = next(line for line in out.splitlines() if line.startswith("chase "))
    assert "50%" in row, "one of two records fills account"
