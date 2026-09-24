"""default_start_date means the same thing in all forty-eight apps.

It is the setting that says "I already have everything before this date".
Without it a second archive of twelve years walks all twelve on every run,
and forty-five apps honor it. Target, Walmart and Wealthfront read
--start-date and ignored the config, in code otherwise identical to the
apps beside them, so setting it did nothing and nothing said so.

No template mentioned it either, and none mentioned `browser`, the setting
that decides whether this drives a browser you already have or downloads
its own four hundred megabytes. Both are read by nearly every app and were
discoverable only by reading the source. They are in every template now,
and the last test here is what keeps them there.

These call each app's own filter rather than reading its source, because
the question is what an app does with the setting, not whether the words
appear in the file.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]

FLOOR = "2025-01-01"
BEFORE, AFTER = "2024-03-01", "2026-03-01"


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def app_with(mod, floor):
    """The downloader, without running its __init__, which would want a
    browser and an output folder. Only the filter is under test."""
    inst = object.__new__(mod.App)
    inst.args = SimpleNamespace(year=None, type=None, start_date=None,
                                end_date=None, order_number=None,
                                max_purchases=None, max_docs=None,
                                redownload=False)
    inst.config = {"document_types": ["Statement", "Tax Document",
                                      "Insurance Document", "Other"],
                   "default_start_date": floor}
    inst.rules = getattr(mod, "DEFAULT_RULES", {})
    return inst


def in_scope(mod, inst, date):
    """Whether an item with this date survives the app's own filter."""
    if hasattr(mod.App, "_in_scope"):
        return bool(inst._in_scope(
            mod.Document(category="Statement", date=date, title="Statement")))
    from paperpull_core.models import ONLINE, Purchase
    inst.discovery = SimpleNamespace(data={
        "k": Purchase(purchase_type=ONLINE, purchase_date=date,
                      order_number="900000000000001").to_dict()})
    return bool(inst._select_purchases())


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_skips_what_the_floor_says_it_already_has(app):
    mod = load(app)
    inst = app_with(mod, FLOOR)
    assert not in_scope(mod, inst, BEFORE), (
        "%s walks %s although default_start_date is %s" % (app.name, BEFORE, FLOOR))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_still_takes_what_is_above_the_floor(app):
    """A floor that refuses everything is worse than no floor."""
    mod = load(app)
    inst = app_with(mod, FLOOR)
    assert in_scope(mod, inst, AFTER), \
        "%s skips %s although the floor is %s" % (app.name, AFTER, FLOOR)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_floor_means_no_floor(app):
    """Absent and empty both have to mean the whole archive."""
    mod = load(app)
    for floor in (None, ""):
        inst = app_with(mod, floor)
        assert in_scope(mod, inst, BEFORE), \
            "%s skips %s with the floor set to %r" % (app.name, BEFORE, floor)


# -- and the settings are in the file people are told to copy ------------------

def settings_read(app: Path) -> set:
    """Every config key this app looks up by name."""
    found = set()
    for path in sorted(app.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) \
                    and "config" in ast.unparse(node.func.value):
                found.add(node.args[0].value)
            elif isinstance(node, ast.Subscript) \
                    and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str) \
                    and "config" in ast.unparse(node.value):
                found.add(node.slice.value)
    return found


def defaults_in_spec(app: Path) -> set:
    """Keys the app's AppSpec fills in, which the template may then skip."""
    spec = app / "storage.py"
    if not spec.exists():
        return set()
    try:
        tree = ast.parse(spec.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "config_defaults" \
                and isinstance(node.value, ast.Dict):
            out |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return out


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_setting_this_app_reads_is_in_the_template(app):
    """config.example.json is the only list of settings anybody ever sees. A
    setting missing from it is a setting nobody can find."""
    template = app / "config.example.json"
    if not template.exists():
        pytest.skip("no template")
    documented = set(json.loads(template.read_text(encoding="utf-8")))
    missing = sorted(settings_read(app) - documented - defaults_in_spec(app))
    assert not missing, (
        "%s reads settings its own template never shows: %s"
        % (app.name, " ".join(missing)))
