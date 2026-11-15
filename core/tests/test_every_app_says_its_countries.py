"""Every app says which countries it is for, and every list says it alike.

Amazon is one app for fourteen stores, and Amazon Visa here is a German
card where the US one is Chase's, so a list with no country in it reads
wrong to someone somewhere (Bryan, 2026-11-15). Each app names its
countries once in its AppSpec. The panel and the website read them from
storage.py without running it, and PROVIDERS.md and the README carry them
in a Country column, so each of those is held to the imported spec here.
"""
import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from paperpull_core import countries
from paperpull_core import storage as core_storage

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(p.parent for p in (REPO / "apps").glob("*/storage.py"))
IDS = [a.name for a in APPS]
ROW = re.compile(r"^\| \[`([a-z0-9_]+)`\]\([^)]*\) \|(.*)\|\s*$")


@pytest.fixture
def loaded(monkeypatch):
    """Each app's storage module under a name of its own, the core's
    bindings put back after, as the naming census loads them."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))

    def load(app: Path):
        found = importlib.util.spec_from_file_location("_countries_of_%s" % app.name,
                                                       app / "storage.py")
        module = importlib.util.module_from_spec(found)
        found.loader.exec_module(module)
        return module.SPEC
    return load


def test_there_are_apps_to_look_at():
    assert len(APPS) > 90


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_app_names_its_countries(app, loaded):
    spec = loaded(app)
    assert spec.countries, "%s's AppSpec has no countries" % app.name
    assert all(c in countries.NAMES for c in spec.countries)


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_the_lists_read_what_the_app_declares(app, loaded):
    """The panel and the website read storage.py's source. A value written
    some other way than a plain literal would be lost to them."""
    spec = loaded(app)
    read = countries.declared((app / "storage.py").read_text(encoding="utf-8"))
    assert read == {"countries": tuple(spec.countries),
                    "may_work_elsewhere": spec.may_work_elsewhere,
                    "stores": dict(spec.stores), "store_setting": spec.store_setting}


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_store_app_starts_on_one_of_its_stores(app, loaded):
    spec = loaded(app)
    if not spec.stores:
        pytest.skip("one site for every account")
    example = json.loads((app / "config.example.json").read_text(encoding="utf-8"))
    assert example.get(spec.store_setting) in spec.stores
    assert set(spec.stores.values()) == set(spec.countries)


def _assigned(path: Path, name: str):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("%s has no %s" % (path.name, name))


def test_amazons_stores_are_the_marketplaces_it_reads(loaded):
    """The store the panel offers is the one amazon_site.set_marketplace
    takes, which refuses any other, so the two lists are one."""
    spec = loaded(REPO / "apps" / "amazon")
    marketplaces = _assigned(REPO / "apps" / "amazon" / "amazon_site.py", "MARKETPLACES")
    assert set(spec.stores) == set(marketplaces)
    assert spec.store_setting == "marketplace"
    assert len(spec.countries) == len(spec.stores) == 14


def _country_cells(path: Path) -> dict:
    """Each row's Country cell, the column after Provider."""
    out, header = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| App |"):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            continue
        m = ROW.match(line)
        if m and header:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out[m.group(1)] = cells[header.index("Country")] if "Country" in header else None
    return out


@pytest.mark.parametrize("doc", ["PROVIDERS.md", "README.md"])
def test_the_tables_say_each_apps_countries(doc, loaded):
    cells = _country_cells(REPO / doc)
    assert cells, "%s has no provider table" % doc
    wrong = []
    for app in APPS:
        if app.name not in cells:
            continue
        spec = loaded(app)
        want = countries.label(spec.countries, spec.may_work_elsewhere)
        if cells[app.name] != want:
            wrong.append("%s says %r, its AppSpec %r" % (app.name, cells[app.name], want))
    assert not wrong, "\n".join(wrong)
    assert set(cells) == set(IDS), "%s leaves out %s" % (doc, sorted(set(IDS) - set(cells)))
