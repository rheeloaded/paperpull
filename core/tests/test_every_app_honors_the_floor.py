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
import textwrap
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
    """Every config key this app looks up by name, a constant subscript or
    .get on the config dict itself (see is_the_config)."""
    found = set()
    for path in sorted(app.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        found |= keys_read(tree)
    return found


SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def is_the_config(node, aliases=frozenset()) -> bool:
    """Whether this expression is the config dict itself.

    That is the name config, an attribute chain ending in .config (such as
    self.config, app.config or self.app.config), a local alias of one of
    those, or any of these `or` a fallback such as {}. A call is never the
    config, even one handed the config, since what it answers is its own.
    ING's `_read_area(page, source, config, again=True)["rows"]` is a row
    list, and the text of that call holding the word config made it a
    setting named rows."""
    if isinstance(node, ast.Name):
        return node.id == "config" or node.id in aliases
    if isinstance(node, ast.Attribute):
        if node.attr != "config":
            return False
        base = node.value
        while isinstance(base, ast.Attribute):
            base = base.value
        return isinstance(base, ast.Name)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return is_the_config(node.values[0], aliases)
    return False


def own_nodes(scope):
    """The nodes of one scope. A function, lambda or class inside it is
    yielded, but its body is left to its own scope."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, SCOPES):
            todo.extend(ast.iter_child_nodes(node))


def local_aliases(scope, own, inherited) -> set:
    """The names that hold nothing but the config dict in this scope.

    A name counts when every binding of it here assigns it the config (or
    an alias of it), so a name later handed something else, a parameter,
    a loop target or an import never does. An alias of the enclosing
    function still counts here unless this scope binds that name."""
    stores, plain, other = {}, {}, set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        other |= {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs
                  + [args.vararg, args.kwarg] if a is not None}
    for node in own:
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            stores[node.id] = stores.get(node.id, 0) + 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) \
                and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    plain.setdefault(target.id, []).append(node.value)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            other |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            other |= set(node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            other.add(node.name)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) \
                and node.name:
            other.add(node.name)
    aliases = {n for n in inherited if n not in stores and n not in other}
    grew = True
    while grew:
        grew = False
        for name, values in plain.items():
            if name not in aliases and name not in other \
                    and stores.get(name) == len(values) \
                    and all(is_the_config(v, aliases) for v in values):
                aliases.add(name)
                grew = True
    return aliases


def keys_read(scope, inherited=frozenset()) -> set:
    """The keys read off the config dict in this scope and the scopes inside
    it."""
    own = list(own_nodes(scope))
    aliases = local_aliases(scope, own, inherited)
    found = set()
    for node in own:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) \
                and is_the_config(node.func.value, aliases):
            found.add(node.args[0].value)
        elif isinstance(node, ast.Subscript) \
                and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str) \
                and is_the_config(node.value, aliases):
            found.add(node.slice.value)
        elif isinstance(node, SCOPES):
            found |= keys_read(node, aliases)
    return found


# What settings_read takes for a setting, on a sample of each shape. Each
# FOUND sample reads the one setting s. Each NOT_SETTINGS sample reads rows
# off something that is not the config dict. The first two are the false
# match ING met, a row list a helper answered, read as a setting named rows
# because the helper was handed the config.

FOUND = {
    "self.config subscripted": """
        def f(self):
            return self.config["s"]
        """,
    "self.config asked with get": """
        def f(self):
            return self.config.get("s")
        """,
    "a parameter named config": """
        def f(page, config):
            return config.get("s", True)
        """,
    "config subscripted": """
        def f(page, config):
            return config["s"]
        """,
    "another object's config": """
        def f(app):
            return app.config.get("s")
        """,
    "a longer attribute chain": """
        def f(self):
            return self.app.config["s"]
        """,
    "the config or an empty dict": """
        def f(config=None):
            return (config or {}).get("s")
        """,
    "a local alias": """
        def f(self):
            cfg = self.config
            return cfg.get("s")
        """,
    "a local alias of the config or an empty dict": """
        def f(config=None):
            cfg = config or {}
            return cfg["s"]
        """,
    "an annotated alias": """
        def f(self):
            cfg: dict = self.config
            return cfg.get("s")
        """,
    "an alias made in a condition": """
        def f(self):
            if (cfg := self.config):
                return cfg["s"]
        """,
    "an alias of an alias": """
        def f(self):
            cfg = self.config
            same = cfg
            return same["s"]
        """,
    "an alias read inside a function it holds": """
        def f(self):
            cfg = self.config

            def inner():
                return cfg["s"]
            return inner()
        """,
}

NOT_SETTINGS = {
    "a call handed the config, subscripted": """
        def f(page, source, config):
            return _read_area(page, source, config, again=True)["rows"]
        """,
    "a call handed the config, asked with get": """
        def f(self):
            return fetch(self.config).get("rows")
        """,
    "the config of what a call answers": """
        def f(self):
            return connect(self).config["rows"]
        """,
    "a key inside a setting's value": """
        def f(self):
            return self.config["s"]["rows"], self.config.get("s", {}).get("rows")
        """,
    "another dict whose name holds config": """
        def f():
            default_config = {"rows": 3}
            return default_config["rows"]
        """,
    "a name that held the config, then something else": """
        def f(self):
            cfg = self.config
            cfg = fetch(cfg)
            return cfg["rows"]
        """,
    "a name that held the config, then a loop's items": """
        def f(self):
            cfg = self.config
            for cfg in fetch(cfg):
                return cfg["rows"]
        """,
    "a parameter that hides an outer alias": """
        def f(self):
            cfg = self.config

            def inner(cfg):
                return cfg["rows"]
            return inner([])
        """,
}


def read_from_sample(tmp_path, source) -> set:
    (tmp_path / "sample_site.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return settings_read(tmp_path)


@pytest.mark.parametrize("source", list(FOUND.values()), ids=list(FOUND))
def test_each_way_of_reading_the_config_is_found(tmp_path, source):
    assert read_from_sample(tmp_path, source) == {"s"}


@pytest.mark.parametrize("source", list(NOT_SETTINGS.values()), ids=list(NOT_SETTINGS))
def test_what_is_read_off_something_else_is_not_a_setting(tmp_path, source):
    """A call handed the config answers something of its own, and a key of a
    setting's value or of another dict is no setting either."""
    assert "rows" not in read_from_sample(tmp_path, source)


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
