"""A brand-new user, who has nothing to point at.

The first version of the panel asked "where are your downloaders?", which is a
question somebody who has never used this cannot answer. These pin down the
path that replaced it: choose a folder, tick providers, and have the installs
made from the shipped templates.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    p = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: p)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    return p


@pytest.fixture
def templates(tmp_path, monkeypatch):
    """Two fake provider templates, with the junk a repo checkout leaves
    beside the code, so the copy filter is actually exercised."""
    root = tmp_path / "templates" / "apps"
    for slug, provider, kind in (("bank", "Bank", "DOCUMENT"),
                                 ("shop", "Shop", "RECEIPT")):
        d = root / slug
        d.mkdir(parents=True)
        (d / ("%s_docs.py" % slug)).write_text("# entry\n", encoding="utf-8")
        (d / ("%s_site.py" % slug)).write_text("# site\n", encoding="utf-8")
        (d / "storage.py").write_text(
            'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind),
            encoding="utf-8")
        (d / "config.example.json").write_text(
            json.dumps({"cdp_url": "http://127.0.0.1:9299", "output_dir": "."}),
            encoding="utf-8")
        # things that must never be copied into a new install
        (d / ".venv" / "Scripts").mkdir(parents=True)
        (d / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
        (d / "tests").mkdir()
        (d / "tests" / "test_x.py").write_text("", encoding="utf-8")
        (d / "progress.json").write_text("{}", encoding="utf-8")
        (d / "config.json").write_text('{"owner": "Someone Real"}', encoding="utf-8")
        (d / ("%s-browser-profile" % slug)).mkdir()
        (d / ("%s-browser-profile" % slug) / "Cookies").write_bytes(b"secret")
    monkeypatch.setattr(app_module, "_templates_root", lambda: root)
    monkeypatch.setattr(app_module, "_provider_notes",
                        lambda: {"bank": {"documents": "Statements", "category": "Bank"}})
    return root


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _create(body):
    return asyncio.run(app_module.api_create(_Req(body)))


# -- what is offered ---------------------------------------------------------

def test_providers_are_listed_with_what_they_download(templates, settings):
    got = {p["slug"]: p for p in app_module.list_providers()}
    assert set(got) == {"bank", "shop"}
    assert got["bank"]["provider"] == "Bank"
    assert got["bank"]["documents"] == "Statements"
    assert got["shop"]["kind"] == "RECEIPT"


def test_install_folders_follow_the_existing_naming_convention(templates, settings):
    """"Chase Statements", "Amazon Receipts". A folder made here should sit
    naturally beside one made by hand."""
    got = {p["slug"]: p["folder"] for p in app_module.list_providers()}
    assert got == {"bank": "Bank Statements", "shop": "Shop Receipts"}


def test_a_suggested_folder_is_offered_so_nothing_has_to_be_typed(templates, settings):
    d = app_module.api_providers()
    assert d["templates"] is True
    assert d["suggested_root"].endswith("PaperPull")


def test_already_installed_providers_are_marked(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    marks = {p["slug"]: p["installed"] for p in app_module.api_providers()["providers"]}
    assert marks == {"bank": True, "shop": False}


# -- creating an install -----------------------------------------------------

def test_setup_creates_the_folder_and_an_install_per_provider(templates, settings, tmp_path):
    home = tmp_path / "does-not-exist-yet" / "PaperPull"
    got = _create({"root": str(home), "providers": ["bank", "shop"]})
    assert sorted(got["created"]) == ["bank", "shop"]
    assert (home / "Bank Statements" / "bank_docs.py").is_file()
    assert (home / "Shop Receipts" / "shop_docs.py").is_file()
    assert app_module.apps_root() == home.resolve(), "the folder was not remembered"


def test_the_example_config_becomes_the_real_one(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    cfg = json.loads((home / "Bank Statements" / "config.json").read_text(encoding="utf-8"))
    assert cfg["cdp_url"] == "http://127.0.0.1:9299"


def test_nothing_personal_from_the_template_is_copied(templates, settings, tmp_path):
    """A template in a repo checkout can have a venv, tests, a real config, a
    signed-in profile and a download history sitting beside the code. None of
    that belongs in a stranger's fresh install."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    d = home / "Bank Statements"
    assert not (d / ".venv").exists()
    assert not (d / "tests").exists()
    assert not (d / "progress.json").exists()
    assert not (d / "bank-browser-profile").exists()
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert "Someone Real" not in json.dumps(cfg), "the template's real config leaked"


def test_an_existing_install_is_never_overwritten(templates, settings, tmp_path):
    """The folder may hold years of history."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    marker = home / "Bank Statements" / "progress.json"
    marker.write_text('{"id:1": {"downloaded_ok": true}}', encoding="utf-8")
    got = _create({"root": str(home), "providers": ["bank"]})
    assert got["existed"] == ["bank"] and got["created"] == []
    assert "id:1" in marker.read_text(encoding="utf-8")


# -- refusals ----------------------------------------------------------------

def test_an_unknown_provider_is_refused(templates, settings, tmp_path):
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(tmp_path / "h"), "providers": ["../../etc"]})
    assert e.value.status_code == 400


def test_no_providers_is_refused(templates, settings, tmp_path):
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(tmp_path / "h"), "providers": []})
    assert e.value.status_code == 400


def test_a_relative_folder_is_refused(templates, settings):
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": "Documents/PaperPull", "providers": ["bank"]})
    assert e.value.status_code == 400


def test_the_page_cannot_override_the_environment(templates, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(tmp_path / "h"), "providers": ["bank"]})
    assert e.value.status_code == 409


def test_no_templates_means_an_honest_empty_list(settings, monkeypatch):
    """A checkout with APPS_ROOT pointed elsewhere has nothing to make
    installs from, and should say so rather than offer an empty picker."""
    monkeypatch.setattr(app_module, "_templates_root", lambda: None)
    d = app_module.api_providers()
    assert d["templates"] is False
    assert d["providers"] == []


# -- removing a provider -----------------------------------------------------

def _remove(body):
    return asyncio.run(app_module.api_remove(_Req(body)))


def test_removing_moves_the_folder_aside_and_deletes_nothing(templates, settings, tmp_path):
    """The one action in the panel that could destroy something, so it does
    not. PDFs not yet filed elsewhere, the history and the signed-in profile
    all survive, in a Removed folder the person can delete deliberately."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    inst = home / "Bank Statements"
    (inst / "Statements").mkdir()
    (inst / "Statements" / "2026-01-31 Statement.pdf").write_bytes(b"%PDF-1.7 x")
    (inst / "progress.json").write_text('{"id:1": {"downloaded_ok": true}}', encoding="utf-8")
    (inst / "bank-browser-profile").mkdir()
    (inst / "bank-browser-profile" / "Cookies").write_bytes(b"session")

    got = _remove({"app": "Bank Statements"})

    assert not inst.exists(), "still listed under the root"
    moved = Path(got["moved_to"])
    assert moved.parent == home / "Removed"
    assert (moved / "Statements" / "2026-01-31 Statement.pdf").read_bytes() == b"%PDF-1.7 x"
    assert "id:1" in (moved / "progress.json").read_text(encoding="utf-8")
    assert (moved / "bank-browser-profile" / "Cookies").read_bytes() == b"session"
    assert got["pdfs"] == 1 and got["history"] == 1 and got["profile"] is True


def test_a_removed_provider_no_longer_appears_and_can_be_added_again(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    _remove({"app": "Bank Statements"})
    assert app_module._looks_like_installs(home) == 0
    marks = {p["slug"]: p["installed"] for p in app_module.api_providers()["providers"]}
    assert marks["bank"] is False, "still shown as installed after removal"
    got = _create({"root": str(home), "providers": ["bank"]})
    assert got["created"] == ["bank"], "could not be set up again after removal"


def test_removing_twice_keeps_both_copies(templates, settings, tmp_path):
    """Remove, set up again, remove again. The second copy must not overwrite
    the first in Removed, because the first may hold history the second does
    not."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    first = Path(_remove({"app": "Bank Statements"})["moved_to"])
    _create({"root": str(home), "providers": ["bank"]})
    second = Path(_remove({"app": "Bank Statements"})["moved_to"])
    assert first.exists() and second.exists() and first != second


def test_a_running_provider_cannot_be_removed(templates, settings, tmp_path):
    """Pulling the folder out from under a live download would be worse than
    any of the things removal is careful about."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    app_module._RUNNING.add("Bank Statements")
    try:
        with pytest.raises(fastapi.HTTPException) as e:
            _remove({"app": "Bank Statements"})
        assert e.value.status_code == 409
        assert (home / "Bank Statements").exists()
    finally:
        app_module._RUNNING.discard("Bank Statements")


def test_only_a_discovered_app_can_be_removed(templates, settings, tmp_path):
    """The name must be one the panel found itself, so nothing outside the
    root can ever be named, however it is spelled."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"]})
    (tmp_path / "elsewhere").mkdir()
    for name in ("../elsewhere", "..\elsewhere", "elsewhere", "Removed", ""):
        with pytest.raises(fastapi.HTTPException) as e:
            _remove({"app": name})
        assert e.value.status_code == 404, name
    assert (tmp_path / "elsewhere").exists()
    assert (home / "Bank Statements").exists()
