"""The File names page (#50).

It reads an app's records to preview with and writes a pattern into
config. These pin down that it previews what a run would build, writes
only where it was asked, keeps a copy of what it replaced, refuses a
pattern that cannot be used, and writes nothing in the sample.

The endpoints are called directly, the way the rest of this suite does.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
pytest.importorskip("fastapi")
from fastapi import HTTPException            # noqa: E402

naming = app_module._naming()
if naming is None:
    pytest.skip("the core is not beside the panel", allow_module_level=True)


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def make_install(root: Path, folder: str, provider: str, kind: str,
                 records=None, config=None, extra_configs=None):
    d = root / "apps" / folder
    out = root / "out" / folder
    d.mkdir(parents=True)
    out.mkdir(parents=True)
    script = provider.lower() + ("_receipts.py" if kind == "RECEIPT" else "_docs.py")
    (d / script).write_text("", encoding="utf-8")
    (d / "storage.py").write_text(
        "SPEC = AppSpec(provider=%r, kind=%s)\n" % (provider, kind), encoding="utf-8")
    cfg = {"output_dir": str(out)}
    cfg.update(config or {})
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (d / "config.example.json").write_text("{}", encoding="utf-8")
    for name, extra in (extra_configs or {}).items():
        (d / name).write_text(json.dumps(extra), encoding="utf-8")
    if records is not None:
        (out / "progress.json").write_text(
            json.dumps({str(i): r for i, r in enumerate(records)}), encoding="utf-8")
    return d


RECEIPTS = [
    {"purchase_date": "2026-01-05", "summary": "Paper towels", "order_number": "111",
     "total": "12.00", "pdf_filename": "2026-01-05 Target Paper Towels Receipt.pdf"},
    {"purchase_date": "2026-03-09", "summary": "Coffee", "order_number": "333",
     "pdf_filename": "2026-03-09 Target Coffee Receipt.pdf"},
    {"purchase_date": "2026-02-01", "summary": "Soap", "order_number": "222",
     "pdf_filename": "2026-02-01 Target Soap Receipt.pdf"},
    {"purchase_date": "2025-12-01", "summary": "Old", "order_number": "000",
     "pdf_filename": "2025-12-01 Target Old Receipt.pdf"},
    {"purchase_date": "2026-04-01", "summary": "Never saved", "order_number": "444"},
]


@pytest.fixture
def apps(tmp_path, monkeypatch):
    target = make_install(tmp_path, "Target Receipts", "Target", "RECEIPT",
                          records=RECEIPTS, config={"owner": "Sam"},
                          extra_configs={"config.partner.json": {"owner": "Alex"}})
    walmart = make_install(tmp_path, "Walmart Receipts", "Walmart", "RECEIPT")
    chase = make_install(tmp_path, "Chase Statements", "Chase", "DOCUMENT",
                         records=[{"date": "2026-02-28", "summary": "Checking",
                                   "category": "Statement", "account": "x1234",
                                   "pdf_filename": "2026-02-28 Chase Checking.pdf"}])
    found = {"target": target, "walmart": walmart, "chase": chase}
    monkeypatch.setattr(app_module, "discover_apps",
                        lambda: {k: {"dir": str(v)} for k, v in found.items()})
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    return found


def cfg(d: Path, name="config.json"):
    return json.loads((d / name).read_text(encoding="utf-8"))


def preview(body):
    return asyncio.run(app_module.api_naming_preview(_Req(body)))


def save(body):
    return asyncio.run(app_module.api_naming_save(_Req(body)))


# -- reading -------------------------------------------------------------------

def test_the_page_knows_the_app_its_kind_and_what_it_fills(apps):
    d = app_module.api_naming("target")
    assert d["available"] is True
    assert d["kind"] == "receipts"
    assert d["provider"] == "Target"
    assert d["shared"] == "" and d["own"] == ""
    assert d["fill"]["records"] == 5
    assert d["fill"]["filled"]["number"] == 5
    assert d["fill"]["filled"]["total"] == 1
    assert d["fill"]["filled"]["store"] == 0


def test_a_statements_app_is_a_statements_app(apps):
    assert app_module.api_naming("chase")["kind"] == "statements"


def test_an_app_with_no_records_yet_still_opens(apps):
    d = app_module.api_naming("walmart")
    assert d["fill"]["records"] == 0


def test_an_unknown_app_is_refused(apps):
    with pytest.raises(HTTPException) as e:
        app_module.api_naming("nobody")
    assert e.value.status_code == 404


def test_the_fill_rates_are_counts_and_never_a_value(apps):
    text = json.dumps(app_module.api_naming("target")["fill"])
    for r in RECEIPTS:
        for v in r.values():
            assert v not in text or v.isdigit()


def test_records_are_found_under_a_relative_output_dir(tmp_path, monkeypatch):
    d = make_install(tmp_path, "Gap Receipts", "Gap", "RECEIPT",
                     config={"output_dir": "archive"})
    (d / "archive").mkdir()
    (d / "archive" / "progress.json").write_text(
        json.dumps({"a": RECEIPTS[0]}), encoding="utf-8")
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"gap": {"dir": str(d)}})
    assert app_module.api_naming("gap")["fill"]["records"] == 1


# -- previewing ----------------------------------------------------------------

def test_the_preview_is_the_three_newest_saved_files(apps):
    names = preview({"app": "target", "pattern": ""})["names"]
    assert [n["current"] for n in names] == [
        "2026-03-09 Target Coffee Receipt.pdf",
        "2026-02-01 Target Soap Receipt.pdf",
        "2026-01-05 Target Paper Towels Receipt.pdf"]
    assert all(n["new"] == n["current"] for n in names)


def test_the_preview_is_what_a_run_would_build(apps):
    names = preview({"app": "target",
                     "pattern": "{date:yyyymmdd} - {provider}[ -- {number}]"})["names"]
    assert names[0]["new"] == "20260309 - Target -- 333.pdf"


def test_the_preview_uses_the_configured_owner(apps):
    names = preview({"app": "target", "pattern": "{owner} {date}"})["names"]
    assert names[0]["new"] == "Sam 2026-03-09.pdf"


def test_a_statement_previews_its_category_as_its_kind(apps):
    names = preview({"app": "chase", "pattern": "{date} {provider} {account} {kind}"})["names"]
    assert names[0]["new"] == "2026-02-28 Chase x1234 Statement.pdf"


def test_a_broken_pattern_says_what_is_wrong_and_changes_nothing(apps):
    d = preview({"app": "target", "pattern": "{date} {nosuchfield}"})
    assert d["problem"] and "nosuchfield" in d["problem"]
    assert all(n["new"] == n["current"] for n in d["names"])


# -- saving --------------------------------------------------------------------

def test_shared_goes_into_every_install_of_that_kind_and_every_account(apps):
    r = save({"app": "target", "scope": "shared", "pattern": "{date} {provider}"})
    assert r["key"] == "filename_pattern_receipts"
    assert r["installs"] == 2
    assert r["written"] == 3
    for d, name in ((apps["target"], "config.json"),
                    (apps["target"], "config.partner.json"),
                    (apps["walmart"], "config.json")):
        assert cfg(d, name)["filename_pattern_receipts"] == "{date} {provider}"
    assert "filename_pattern_receipts" not in cfg(apps["chase"])
    assert "filename_pattern_statements" not in cfg(apps["chase"])


def test_the_example_config_is_never_written(apps):
    save({"app": "target", "scope": "shared", "pattern": "{date} {provider}"})
    assert cfg(apps["target"], "config.example.json") == {}


def test_own_goes_into_this_app_only(apps):
    r = save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    assert r["key"] == "filename_pattern"
    assert cfg(apps["target"])["filename_pattern"] == "{date} {number}"
    assert "filename_pattern" not in cfg(apps["walmart"])


def test_the_rest_of_the_config_survives(apps):
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    c = cfg(apps["target"])
    assert c["owner"] == "Sam" and c["output_dir"].endswith("Target Receipts")


def test_a_copy_of_what_was_replaced_is_kept(apps):
    before = (apps["target"] / "config.json").read_text(encoding="utf-8")
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    backups = list((apps["target"] / "Backups").glob("naming-*/config.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == before


def test_saving_the_same_pattern_twice_writes_nothing_the_second_time(apps):
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    assert save({"app": "target", "scope": "own", "pattern": "{date} {number}"})["written"] == 0


def test_an_empty_pattern_or_the_default_clears_the_key(apps):
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    save({"app": "target", "scope": "own", "pattern": naming.DEFAULT_RECEIPTS})
    assert "filename_pattern" not in cfg(apps["target"])
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    save({"app": "target", "scope": "own", "pattern": ""})
    assert "filename_pattern" not in cfg(apps["target"])


def test_a_pattern_that_cannot_be_used_is_refused_and_nothing_written(apps):
    before = (apps["target"] / "config.json").read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        save({"app": "target", "scope": "own", "pattern": "{date} {nosuchfield}"})
    assert e.value.status_code == 400
    assert (apps["target"] / "config.json").read_text(encoding="utf-8") == before


def test_an_unknown_scope_is_refused(apps):
    with pytest.raises(HTTPException) as e:
        save({"app": "target", "scope": "everything", "pattern": "{date}"})
    assert e.value.status_code == 400


def test_a_saved_pattern_is_what_the_page_reads_back(apps):
    save({"app": "target", "scope": "shared", "pattern": "{date} {provider}"})
    save({"app": "target", "scope": "own", "pattern": "{date} {number}"})
    d = app_module.api_naming("target")
    assert d["shared"] == "{date} {provider}" and d["own"] == "{date} {number}"


def test_what_the_page_writes_is_what_a_run_reads(apps, monkeypatch):
    """The keys the page writes are the keys a run looks up, for both
    kinds, and an app's own still wins over the shared one."""
    from types import SimpleNamespace
    from paperpull_core import storage
    from paperpull_core.spec import DOCUMENT, RECEIPT
    for name in ("_SPEC", "spec", "_FILENAME_PATTERN", "_PATTERN_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    monkeypatch.setattr(storage, "_SPEC", object())

    def run_reads(d, kind):
        monkeypatch.setattr(storage, "spec", lambda: SimpleNamespace(kind=kind))
        return storage.set_filename_patterns(cfg(d))

    save({"app": "target", "scope": "shared", "pattern": "{date} R"})
    save({"app": "chase", "scope": "shared", "pattern": "{date} S"})
    assert run_reads(apps["target"], RECEIPT) == "{date} R"
    assert run_reads(apps["walmart"], RECEIPT) == "{date} R"
    assert run_reads(apps["chase"], DOCUMENT) == "{date} S"
    save({"app": "walmart", "scope": "own", "pattern": "{date} W"})
    assert run_reads(apps["walmart"], RECEIPT) == "{date} W"
    assert run_reads(apps["target"], RECEIPT) == "{date} R"


# -- guards --------------------------------------------------------------------

def _deps(path, method):
    for route in app_module.app.routes:
        if getattr(route, "path", None) == path and method in route.methods:
            return {d.call for d in route.dependant.dependencies}
    raise AssertionError("no route " + path)


def test_every_naming_route_refuses_another_site():
    for path, method in (("/api/naming", "GET"), ("/api/naming/preview", "POST"),
                         ("/api/naming/save", "POST")):
        assert app_module._same_origin_only in _deps(path, method)


def test_saving_is_refused_in_the_sample():
    assert app_module._not_in_sample in _deps("/api/naming/save", "POST")
