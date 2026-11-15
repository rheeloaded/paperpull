"""The provider list says each provider's country, and a provider with a
store per country is set up on the store chosen.

Amazon reads one of fourteen stores, named by "marketplace" in its
config.json, which the panel never asked for, so somebody in Germany who
set Amazon up got amazon.com (Bryan, 2026-11-15). Every value is invented.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

STORES = '{"mart.com": "US", "mart.de": "DE", "mart.co.uk": "GB"}'
TEMPLATES = {
    "bank": ('provider="Bank",\n    countries=("DE",),\n    kind=DOCUMENT,', {}),
    "pay": ('provider="Pay",\n    countries=("US",),\n    may_work_elsewhere=True,\n    kind=DOCUMENT,', {}),
    "mart": ('provider="Mart",\n    countries=("US", "DE", "GB"),\n    stores=%s,\n'
             '    store_setting="site",\n    kind=RECEIPT,' % STORES, {"site": "mart.com"}),
}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    p = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: p)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    return p


@pytest.fixture
def templates(tmp_path, monkeypatch):
    root = tmp_path / "templates" / "apps"
    for n, (slug, (spec, extra)) in enumerate(TEMPLATES.items()):
        d = root / slug
        d.mkdir(parents=True)
        (d / ("%s_docs.py" % slug)).write_text("# entry\n", encoding="utf-8")
        (d / "storage.py").write_text("SPEC = AppSpec(\n    %s\n)\n" % spec, encoding="utf-8")
        (d / "config.example.json").write_text(json.dumps(dict(
            {"cdp_url": "http://127.0.0.1:%d" % (9291 + n), "output_dir": "."}, **extra)),
            encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: root)
    monkeypatch.setattr(app_module, "_provider_notes", lambda: {})
    return root


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _create(body):
    return asyncio.run(app_module.api_create(_Req(body)))


def offered(slug):
    return next(p for p in app_module.list_providers() if p["slug"] == slug)


def config(folder: Path) -> dict:
    return json.loads((folder / "config.json").read_text(encoding="utf-8"))


# -- what the list says ------------------------------------------------------

def test_a_provider_of_one_country_says_it(templates):
    bank = offered("bank")
    assert bank["countries"] == ["DE"] and bank["country_label"] == "Germany"
    assert bank["stores"] == [] and not bank["may_work_elsewhere"]


def test_a_service_of_one_site_worldwide_says_it_may_work_elsewhere(templates):
    pay = offered("pay")
    assert pay["country_label"] == "United States, may work elsewhere" and pay["may_work_elsewhere"]


def test_a_store_provider_lists_its_stores_and_its_default(templates):
    mart = offered("mart")
    assert mart["country_label"] == "3 countries"
    assert mart["country_names"] == ["United States", "Germany", "United Kingdom"]
    assert [s["name"] for s in mart["stores"]] == [
        "mart.com (United States)", "mart.de (Germany)", "mart.co.uk (United Kingdom)"]
    assert mart["store_default"] == "mart.com" and mart["store_setting"] == "site"


def test_the_real_templates_say_amazon_and_the_german_banks():
    """PaperPull's own templates, as the packaged panel lists them."""
    root = app_module._templates_root()
    if root is None or not (root / "amazon").is_dir():
        pytest.skip("no templates beside this panel")
    amazon, dkb, chase = offered("amazon"), offered("dkb"), offered("chase")
    assert amazon["country_label"] == "14 countries" and amazon["store_default"] == "amazon.com"
    assert {s["site"] for s in amazon["stores"]} >= {"amazon.de", "amazon.co.uk", "amazon.com.mx"}
    assert dkb["country_label"] == "Germany" and chase["country_label"] == "United States"


# -- setting a store provider up ---------------------------------------------

def test_the_store_chosen_is_written_and_names_the_folder(templates, settings, tmp_path):
    home = tmp_path / "home"
    got = _create({"root": str(home), "providers": ["mart"], "stores": {"mart": "mart.de"}})
    assert got["created"] == ["mart"]
    folder = home / "Mart Receipts (mart.de)"
    assert config(folder)["site"] == "mart.de"
    assert not (home / "Mart Receipts").exists()


def test_with_no_store_sent_it_is_set_up_as_it_always_was(templates, settings, tmp_path):
    """An older page, or one with no store question, sets it up on its
    default store in the folder an install has always had."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart"]})
    assert config(home / "Mart Receipts")["site"] == "mart.com"


def test_the_default_store_keeps_the_folder_it_always_had(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart"], "stores": {"mart": "mart.com"}})
    assert config(home / "Mart Receipts")["site"] == "mart.com"


def test_a_store_it_does_not_have_is_refused(templates, settings, tmp_path):
    home = tmp_path / "home"
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(home), "providers": ["mart"], "stores": {"mart": "evil.example"}})
    assert e.value.status_code == 400 and "no store" in e.value.detail
    assert not any(home.glob("Mart*"))


def test_stores_that_are_not_an_object_are_refused(templates, settings, tmp_path):
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(tmp_path / "home"), "providers": ["mart"], "stores": ["mart.de"]})
    assert e.value.status_code == 400


def test_a_provider_with_no_stores_takes_no_store(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["bank"], "stores": {"bank": "mart.de"}})
    assert "site" not in config(home / "Bank Statements")


def test_a_second_store_is_an_install_of_its_own_on_its_own_port(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart"]})
    first = (home / "Mart Receipts" / "config.json").read_bytes()
    _create({"root": str(home), "providers": ["mart"], "stores": {"mart": "mart.co.uk"}})
    assert (home / "Mart Receipts" / "config.json").read_bytes() == first
    a, b = config(home / "Mart Receipts"), config(home / "Mart Receipts (mart.co.uk)")
    assert b["site"] == "mart.co.uk" and a["cdp_url"] != b["cdp_url"]


def test_a_store_that_could_not_be_saved_is_said(templates, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_set_setting", lambda *a: False)
    with pytest.raises(fastapi.HTTPException) as e:
        _create({"root": str(tmp_path / "home"), "providers": ["mart"], "stores": {"mart": "mart.de"}})
    assert e.value.status_code == 500 and '"site": "mart.de"' in e.value.detail


# -- what is already set up --------------------------------------------------

def providers_now():
    return {p["slug"]: p for p in app_module.api_providers()["providers"]}


def test_a_store_provider_is_offered_until_every_store_is_set_up(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart", "bank"]})
    got = providers_now()
    assert got["bank"]["installed"] is True
    assert got["mart"]["installed"] is False and got["mart"]["stores_set_up"] == ["mart.com"]
    for store in ("mart.de", "mart.co.uk"):
        _create({"root": str(home), "providers": ["mart"], "stores": {"mart": store}})
    got = providers_now()
    assert got["mart"]["installed"] is True
    assert got["mart"]["stores_set_up"] == ["mart.co.uk", "mart.com", "mart.de"]


def test_a_store_set_by_hand_counts_as_that_store(templates, settings, tmp_path):
    """A folder of the old name whose config was pointed at another store by
    hand, as Amazon's README says to."""
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart"]})
    cfg = config(home / "Mart Receipts")
    cfg["site"] = "mart.de"
    (home / "Mart Receipts" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert providers_now()["mart"]["stores_set_up"] == ["mart.de"]


def test_an_account_row_says_its_store(templates, settings, tmp_path):
    home = tmp_path / "home"
    _create({"root": str(home), "providers": ["mart", "bank"], "stores": {"mart": "mart.de"}})
    rows = {r["app"]: r for r in app_module.account_rows()}
    assert rows["Mart Receipts (mart.de)"]["store"] == "mart.de"
    assert rows["Bank Statements"]["store"] == ""
