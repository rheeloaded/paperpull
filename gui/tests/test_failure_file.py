"""Offering the tester the file a failed run wrote.

The file writes itself and the run prints where it went, which is not the
same as anybody finding it. These pin down that the panel offers the
right one, never the wrong one, and never a path the page chose.

The endpoints are called directly, the way the rest of this suite does.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
pytest.importorskip("fastapi")
from fastapi import HTTPException            # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def install(tmp_path, monkeypatch):
    """One install that looks like the real thing, with its own output
    folder, because Diagnostics follows output_dir rather than the app."""
    app_dir = tmp_path / "apps" / "Costco Receipts"
    out = tmp_path / "out" / "Costco Receipts"
    (app_dir).mkdir(parents=True)
    (app_dir / "costco_receipts.py").write_text("", encoding="utf-8")
    (app_dir / "config.json").write_text(
        json.dumps({"output_dir": str(out)}), encoding="utf-8")
    (out / "Diagnostics").mkdir(parents=True)
    monkeypatch.setattr(app_module, "discover_apps",
                        lambda: {"costco": {"dir": str(app_dir)}})
    return out / "Diagnostics"


def wrote(diagnostics: Path, name: str, age_seconds: float = 0):
    p = diagnostics / name
    p.write_text("{}", encoding="utf-8")
    if age_seconds:
        old = time.time() - age_seconds
        import os
        os.utime(p, (old, old))
    return p


def reveal(body):
    return asyncio.run(app_module.api_failure_reveal(_Req(body)))


# -- finding the right one ----------------------------------------------------

def test_nothing_written_is_nothing_offered(install):
    assert app_module.api_failure_latest("costco") == {"found": False}


def test_a_file_from_the_run_that_just_failed_is_offered(install):
    wrote(install, "failure-pilot-20260922-174903.json")
    answer = app_module.api_failure_latest("costco")
    assert answer["found"] is True
    assert answer["name"] == "failure-pilot-20260922-174903.json"


def test_the_newest_wins_when_a_run_failed_twice(install):
    wrote(install, "failure-pilot-20260922-090000.json")
    wrote(install, "failure-pilot-20260922-174903.json")
    assert app_module.api_failure_latest("costco")["name"].endswith(
        "174903.json")


def test_yesterdays_failure_is_not_offered_as_this_ones(install):
    """The one that would have somebody attach the wrong failure to the
    right issue, and never know."""
    wrote(install, "failure-pilot-20260921-090000.json", age_seconds=90_000)
    assert app_module.api_failure_latest("costco") == {"found": False}


def test_a_recent_one_is_still_found_behind_an_old_one(install):
    wrote(install, "failure-pilot-20260921-090000.json", age_seconds=90_000)
    wrote(install, "failure-sweep-20260922-174903.json")
    assert app_module.api_failure_latest("costco")["name"].startswith(
        "failure-sweep")


def test_a_diagnose_file_is_not_a_failure_file(install):
    wrote(install, "diagnose-costco.json")
    wrote(install, "recording.json")
    assert app_module.api_failure_latest("costco") == {"found": False}


def test_a_missing_diagnostics_folder_is_not_an_error(tmp_path, monkeypatch):
    app_dir = tmp_path / "App"
    app_dir.mkdir()
    monkeypatch.setattr(app_module, "discover_apps",
                        lambda: {"x": {"dir": str(app_dir)}})
    assert app_module.api_failure_latest("x") == {"found": False}


# -- what the page may name ---------------------------------------------------

def test_an_app_nobody_installed_is_refused(install):
    with pytest.raises(HTTPException) as e:
        app_module.api_failure_latest("not-installed")
    assert e.value.status_code == 404


def test_revealing_takes_the_app_name_and_never_a_path(install, monkeypatch):
    """The page says which provider. Where the file is, is decided here."""
    opened = []
    monkeypatch.setattr(app_module.subprocess, "Popen",
                        lambda cmd, *a, **k: opened.append(cmd))
    target = wrote(install, "failure-pilot-20260922-174903.json")
    assert reveal({"app": "costco"}) == {"ok": True}
    assert str(target) in " ".join(opened[0])


def test_revealing_a_path_the_page_made_up_is_ignored(install, monkeypatch):
    opened = []
    monkeypatch.setattr(app_module.subprocess, "Popen",
                        lambda cmd, *a, **k: opened.append(cmd))
    target = wrote(install, "failure-pilot-20260922-174903.json")
    reveal({"app": "costco", "path": "C:\\Windows\\System32\\config\\SAM"})
    joined = " ".join(opened[0])
    assert str(target) in joined
    assert "SAM" not in joined


def test_revealing_with_nothing_to_reveal_says_so(install):
    with pytest.raises(HTTPException) as e:
        reveal({"app": "costco"})
    assert e.value.status_code == 404


def test_revealing_for_an_unknown_app_is_refused(install):
    with pytest.raises(HTTPException) as e:
        reveal({"app": "../../elsewhere"})
    assert e.value.status_code == 404


def test_a_file_manager_that_will_not_start_is_reported_not_raised(
        install, monkeypatch):
    def boom(*a, **k):
        raise OSError("no explorer")

    monkeypatch.setattr(app_module.subprocess, "Popen", boom)
    wrote(install, "failure-pilot-20260922-174903.json")
    with pytest.raises(HTTPException) as e:
        reveal({"app": "costco"})
    assert e.value.status_code == 500


# -- and the page itself says what it is for ----------------------------------

def test_the_page_tells_the_tester_what_to_do_with_it():
    page = app_module.HTML
    assert "Show the file to attach" in page
    assert "no text from your account" in page
    assert "checkFailure(app)" in page
