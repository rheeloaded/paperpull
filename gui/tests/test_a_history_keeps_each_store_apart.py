"""Moving to another computer keeps each store's history in an account of
that store.

Places were matched by provider and person alone, so with Amazon's
amazon.com and amazon.de both set up, the amazon.de history went into the
amazon.com account, and the second store was never set up on the new
computer (a review of 2026-11-15). The panel's own handlers are called as
the page calls them. Every value is invented.
"""
import asyncio
import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

EXAMPLE = {"owner": "", "output_dir": ".", "profile_dir": "./browser-profile",
           "cdp_url": "http://127.0.0.1:9299", "site": "mart.com"}
SPEC = ('SPEC = AppSpec(\n    provider="Mart",\n    countries=("US", "DE"),\n'
        '    stores={"mart.com": "US", "mart.de": "DE"},\n    store_setting="site",\n'
        '    kind=RECEIPT,\n)\n')


@pytest.fixture
def panel(tmp_path, monkeypatch):
    settings = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: settings)
    for name in ("APPS_ROOT", "PAPERPULL_SERVER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    root = tmp_path / "templates" / "apps"
    d = root / "mart"
    d.mkdir(parents=True)
    (d / "mart_docs.py").write_text("# the app\n", encoding="utf-8")
    (d / "storage.py").write_text(SPEC, encoding="utf-8")
    (d / "config.example.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: root)
    monkeypatch.setattr(app_module, "_provider_notes", lambda: {})
    for name, value in (("_SAMPLE", None), ("_RUNNING", set()), ("_STATUS_MOD", None)):
        monkeypatch.setattr(app_module, name, value)
    return settings


def _done(prefix: str, n: int) -> dict:
    return {"%s:%d" % (prefix, i): {"state": "Completed", "downloaded_ok": True,
                                    "pdf_path": "", "summary": "Order"} for i in range(n)}


def _records(folder: Path) -> dict:
    return json.loads((folder / "progress.json").read_text(encoding="utf-8"))


def _site(folder: Path) -> str:
    return json.loads((folder / "config.json").read_text(encoding="utf-8"))["site"]


class Upload:
    def __init__(self, data: bytes, root: str = ""):
        self._raw = json.dumps({"file": base64.b64encode(data).decode("ascii"),
                                "root": root}).encode()
        self.headers = {"content-length": str(len(self._raw))}

    async def stream(self):
        yield self._raw


def old_computer(tmp_path) -> Path:
    old = tmp_path / "old"
    assert app_module.create_install(old, "mart") == "created"
    assert app_module.create_install(old, "mart", store="mart.de") == "created"
    (old / "Mart Receipts" / "progress.json").write_text(json.dumps(_done("com", 3)), encoding="utf-8")
    (old / "Mart Receipts (mart.de)" / "progress.json").write_text(json.dumps(_done("de", 2)),
                                                                  encoding="utf-8")
    app_module._write_settings({"apps_root": str(old)})
    return old


def exported() -> bytes:
    return app_module.api_history_export().body


def manifest(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json"))


def bring(data: bytes, root: Path) -> dict:
    return asyncio.run(app_module.api_history_import(Upload(data, str(root))))


def test_an_export_says_each_places_store(panel, tmp_path):
    old_computer(tmp_path)
    stores = sorted((a["install"], a.get("store")) for a in manifest(exported())["apps"])
    assert stores == [("Mart Receipts", "mart.com"), ("Mart Receipts (mart.de)", "mart.de")]


def test_a_new_computer_gets_each_store_with_its_own_history(panel, tmp_path):
    old_computer(tmp_path)
    data = exported()
    new = tmp_path / "new"
    bring(data, new)
    assert _site(new / "Mart Receipts") == "mart.com"
    assert _site(new / "Mart Receipts (mart.de)") == "mart.de"
    assert set(_records(new / "Mart Receipts")) == set(_done("com", 3))
    assert set(_records(new / "Mart Receipts (mart.de)")) == set(_done("de", 2))


def test_a_computer_with_both_stores_adds_each_history_to_its_own(panel, tmp_path):
    old_computer(tmp_path)
    data = exported()
    new = tmp_path / "new"
    app_module.create_install(new, "mart", store="mart.de")
    app_module.create_install(new, "mart")
    bring(data, new)
    assert set(_records(new / "Mart Receipts")) == set(_done("com", 3))
    assert set(_records(new / "Mart Receipts (mart.de)")) == set(_done("de", 2))


def without(data: bytes, *keys) -> bytes:
    """The file as an older version wrote it, each entry without keys."""
    m = manifest(data)
    for a in m["apps"]:
        for key in keys:
            a.pop(key, None)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as out:
        for name in src.namelist():
            out.writestr(name, json.dumps(m) if name == "manifest.json" else src.read(name))
    return buf.getvalue()


def test_a_file_from_before_stores_were_named_keeps_them_apart_by_its_settings(panel, tmp_path):
    """A file 0.67.0 wrote names no store of its own, and carries the
    install's site setting, which says the same."""
    old_computer(tmp_path)
    new = tmp_path / "new"
    bring(without(exported(), "store"), new)
    assert set(_records(new / "Mart Receipts")) == set(_done("com", 3))
    assert set(_records(new / "Mart Receipts (mart.de)")) == set(_done("de", 2))


def test_a_file_that_names_no_store_at_all_goes_to_the_default_store(panel, tmp_path):
    """A --minimal file of 0.67.0 carries no settings either, so its history
    is the default store's, as the app reads a config naming none. It went
    to the first place by name, here the one set to mart.de by hand (a
    review of 2026-11-15)."""
    old = tmp_path / "old"
    app_module.create_install(old, "mart")
    (old / "Mart Receipts" / "progress.json").write_text(json.dumps(_done("com", 3)), encoding="utf-8")
    app_module._write_settings({"apps_root": str(old)})
    data = without(exported(), "store", "settings")
    new = tmp_path / "new"
    app_module.create_install(new, "mart")
    cfg = json.loads((new / "Mart Receipts" / "config.json").read_text(encoding="utf-8"))
    cfg["site"] = "mart.de"
    (new / "Mart Receipts" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert app_module.create_install(new, "mart", store="mart.com") == "created"
    bring(data, new)
    assert set(_records(new / "Mart Receipts (mart.com)")) == set(_done("com", 3))
    assert not (new / "Mart Receipts" / "progress.json").exists() or not _records(new / "Mart Receipts")


def test_a_person_joins_an_install_whose_store_could_not_be_read(panel, tmp_path):
    """A first person's config naming a store the provider does not have
    left the second person refused, where 0.67.0 added them (a review of
    2026-11-15)."""
    old = tmp_path / "old"
    app_module.create_install(old, "mart")
    app_module._write_settings({"apps_root": str(old)})

    class Req:
        async def json(self):
            return {"app": "Mart Receipts", "label": "pat", "owner": "Pat Example"}
    asyncio.run(app_module.api_account(Req()))
    (old / "Mart Receipts - pat" / "progress.json").write_text(json.dumps(_done("pat", 2)),
                                                               encoding="utf-8")
    data = exported()
    new = tmp_path / "new"
    app_module.create_install(new, "mart")
    cfg = json.loads((new / "Mart Receipts" / "config.json").read_text(encoding="utf-8"))
    cfg["site"] = "mart.example"
    (new / "Mart Receipts" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    bring(data, new)
    assert (new / "Mart Receipts" / "config.pat.json").is_file()
    assert set(_records(new / "Mart Receipts - pat")) == set(_done("pat", 2))
