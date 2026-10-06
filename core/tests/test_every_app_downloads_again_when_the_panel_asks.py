"""Every app downloads again when the panel asks it to.

The panel's Download again box adds --redownload to a Pilot or a Run All,
always with a year or dates. An app takes it only if its parser accepts the
flag beside everything else the panel sends, and honors it only if the check
that skips a document it downloaded before lets that document through while
the flag is set. A parser without the flag answers the panel with a usage
message and exit code 2. A check that ignores it skips every document again,
and the run finishes clean having brought nothing back.

Each app is found by what its command line does, never by a file name. The
module whose `if __name__ == "__main__"` block runs a function that parses
the command line and starts Pilot and Run All from what it parsed is the
app's entry. The parser is the one that function parses with, and the app
is the class it builds from the parsed arguments. What the panel sends is
read out of gui/app.py with ast, as test_panel_and_apps_agree.py reads it,
so this suite needs none of the panel's dependencies. The panel's own tests
(gui/tests/test_download_again.py) hold its command builder to the same
flags in the same order.

The check is found the same way. A method of the app that a loop asks about
one document, before counting it in skipped_completed and moving on, is
asked about a record downloaded for good, by the app built from the panel's
own command line with --redownload and without it. A place that decides
inline has to sit under a test of the flag, or be named below with why.
"""
import ast
import functools
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = REPO / "apps"
PANEL = REPO / "gui" / "app.py"

FOLDERS = sorted(d for d in APPS.iterdir()
                 if d.is_dir() and not d.name.startswith((".", "_")))

# The scopes a run that downloads again may carry, as the flags each becomes
# (gui/app.py, _scope_flags and _redownload_ok). It always carries a year or
# both ends of a range, never one date alone.
SCOPES = (["--year", "2025"],
          ["--start-date", "2025-01-01", "--end-date", "2025-06-30"])

# Places that count a document as already saved for a reason of their own,
# not the memory --redownload sets aside, each with why.
OWN_REASON = {
    ("robinhood", "_settle_tax_form"):
        "A tax form listed without a date that prints the year of a form already "
        "saved is that same form listed twice, so its copy is not kept. The dated "
        "listing is the one fetched again, and a run scoped to a year or dates, the "
        "only kind the panel downloads again, never takes an undated listing.",
}

KEY = "census:2025-03-31:a document downloaded before"


@functools.lru_cache(maxsize=1)
def panel() -> dict:
    """ACTIONS, REDOWNLOAD_FLAG and REDOWNLOAD_ACTIONS, from the panel's source."""
    wanted = {"ACTIONS", "REDOWNLOAD_FLAG", "REDOWNLOAD_ACTIONS"}
    out = {}
    for node in ast.parse(PANEL.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    out[target.id] = ast.literal_eval(node.value)
    assert set(out) == wanted, "the panel no longer declares %s" % sorted(wanted - set(out))
    return out


def dest(flag: str) -> str:
    """The name argparse keeps a flag's value under."""
    return flag.lstrip("-").replace("-", "_")


def flag() -> str:
    return panel()["REDOWNLOAD_FLAG"]


def panel_argv(action: str, scope, again: bool = True, config=None) -> list:
    """The arguments the panel starts an app with, after the script."""
    argv = list(panel()["ACTIONS"][action]["flags"]) + list(scope)
    if again:
        argv.append(flag())
    if config:
        argv += ["--config", str(config)]
    return argv


# -- finding the command line by what it does ------------------------------------

def _run_as_script(tree):
    """The module function its `if __name__ == "__main__"` block calls."""
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in node.test.comparators)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id in functions:
                    return functions[sub.func.id]
    return None


def _parsed(main):
    """(the name main keeps the parsed arguments in, the module function it
    builds the parser with), from `args = build().parse_args(argv)` or from
    `parser = build()` and then `args = parser.parse_args(argv)`."""
    built = {}
    for sub in ast.walk(main):
        if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call) \
                and isinstance(sub.value.func, ast.Name):
            for target in sub.targets:
                if isinstance(target, ast.Name):
                    built[target.id] = sub.value.func.id
    for sub in ast.walk(main):
        if not (isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call)
                and isinstance(sub.value.func, ast.Attribute)
                and sub.value.func.attr == "parse_args"):
            continue
        holder = sub.value.func.value
        if isinstance(holder, ast.Call) and isinstance(holder.func, ast.Name):
            builder = holder.func.id
        elif isinstance(holder, ast.Name) and holder.id in built:
            builder = built[holder.id]
        else:
            continue
        names = [t.id for t in sub.targets if isinstance(t, ast.Name)]
        if names:
            return names[0], builder
    return None, None


def _reads(main, name: str) -> set:
    """What main reads off the parsed arguments."""
    return {n.attr for n in ast.walk(main) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == name}


def _built_from(main, tree, args: str):
    """The module class main builds from the parsed arguments."""
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    for sub in ast.walk(main):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id in classes
                and any(isinstance(a, ast.Name) and a.id == args for a in sub.args)):
            return sub.func.id
    return None


@functools.lru_cache(maxsize=None)
def entries(folder: Path) -> tuple:
    """Every module of an app that starts Pilot and Run All from its command
    line, as (module path, parser function, app class)."""
    starts = {dest(panel()["ACTIONS"][a]["flags"][0]) for a in panel()["REDOWNLOAD_ACTIONS"]}
    found = []
    for py in sorted(folder.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        main = _run_as_script(tree)
        if main is None:
            continue
        args, builder = _parsed(main)
        if args is None or not starts <= _reads(main, args):
            continue
        found.append((py, builder, _built_from(main, tree, args)))
    return tuple(found)


def load(folder: Path, module: Path):
    """The module, imported fresh, with no other app's modules standing in
    for its own. Every app has a storage.py and a site module."""
    for name, mod in list(sys.modules.items()):
        where = getattr(mod, "__file__", None) or ""
        if where and os.path.normcase(os.path.abspath(where)).startswith(
                os.path.normcase(str(APPS))):
            del sys.modules[name]
    sys.path.insert(0, str(folder))
    try:
        return importlib.import_module(module.stem)
    finally:
        sys.path.pop(0)


# -- finding what counts a document as done ----------------------------------------

def _counts_done_here(body) -> bool:
    """A statement of this block itself, not of a decision inside it, adds
    to self.stats["skipped_completed"]."""
    for stmt in body:
        if isinstance(stmt, ast.If):
            continue
        for sub in ast.walk(stmt):
            if (isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Subscript)
                    and isinstance(sub.target.slice, ast.Constant)
                    and sub.target.slice.value == "skipped_completed"):
                return True
    return False


def _asks_self(node) -> bool:
    """self.something(item), a question about one document."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
            and len(node.args) == 1 and not node.keywords)


def _tests_the_flag(node) -> bool:
    name = dest(flag())
    return any((isinstance(n, ast.Attribute) and n.attr == name)
               or (isinstance(n, ast.Constant) and n.value == name) for n in ast.walk(node))


def skip_sites(cls: ast.ClassDef) -> list:
    """(method, decider, under a test of the flag) for every place in the
    class that counts a document as already done. The decider is the method
    the place's test asks about the document, directly or through a name
    the answer was kept in, or None where the test decides inline."""
    out = []
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        parents, kept = {}, {}
        for node in ast.walk(fn):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
            if isinstance(node, ast.Assign) and _asks_self(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        kept[target.id] = node.value.func.attr
        for node in ast.walk(fn):
            if not (isinstance(node, ast.If) and _counts_done_here(node.body)):
                continue
            test = node.test
            if _asks_self(test):
                decider = test.func.attr
            elif isinstance(test, ast.Name):
                decider = kept.get(test.id)
            else:
                decider = None
            guarded, up = _tests_the_flag(test), parents.get(node)
            while up is not None and not guarded:
                guarded = isinstance(up, ast.If) and _tests_the_flag(up.test)
                up = parents.get(up)
            out.append((fn.name, decider, guarded))
    return out


class Item:
    """A document or a purchase as far as a done check reads one, its key,
    and nothing for anything else."""

    def __init__(self, key: str):
        self.key = key

    def __getattr__(self, name):
        return ""


def built(folder: Path, mod, parser_fn: str, cls: str, argv: list, tmp_path: Path):
    """The app, built the way main builds it, from the panel's arguments and
    a config whose every folder is under tmp_path."""
    example = folder / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    args = getattr(mod, parser_fn)().parse_args(argv + ["--config", str(cfg)])
    return getattr(mod, cls)(args)


# -- the census ---------------------------------------------------------------------

@pytest.mark.parametrize("folder", FOLDERS, ids=lambda d: d.name)
def test_every_app_has_one_command_line_that_runs_pilot_and_run_all(folder):
    found = entries(folder)
    assert len(found) == 1, "%s has %d modules that run Pilot and Run All from a command line" \
        % (folder.name, len(found))
    module, parser_fn, cls = found[0]
    assert parser_fn and cls, "main's parser in %s, or the app it builds, was not found" % module.name


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda d: d.name)
def test_its_parser_takes_the_flag_beside_everything_the_panel_sends(folder):
    module, parser_fn, _cls = entries(folder)[0]
    mod = load(folder, module)
    for action in panel()["REDOWNLOAD_ACTIONS"]:
        for scope in SCOPES:
            for config in (None, "config.robin.json"):
                argv = panel_argv(action, scope, config=config)
                try:
                    args = getattr(mod, parser_fn)().parse_args(argv)
                except SystemExit:
                    pytest.fail("%s refuses the panel's %s" % (folder.name, " ".join(argv)))
                assert getattr(args, dest(flag())) is True, argv
                for given in panel()["ACTIONS"][action]["flags"]:
                    assert getattr(args, dest(given)) is True, (given, argv)
                pairs = dict(zip(scope[::2], scope[1::2]))
                for name, value in pairs.items():
                    assert str(getattr(args, dest(name))) == value, (name, argv)
                for name in {"--year", "--start-date", "--end-date"} - set(pairs):
                    assert not getattr(args, dest(name)), (name, argv)
                if config:
                    assert args.config == config, argv
                plain = getattr(mod, parser_fn)().parse_args(panel_argv(action, scope, again=False))
                assert getattr(plain, dest(flag())) is False, argv


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda d: d.name)
def test_a_document_downloaded_before_is_done_unless_the_panel_asks_again(folder, tmp_path):
    module, parser_fn, cls = entries(folder)[0]
    mod = load(folder, module)
    tree = ast.parse(module.read_text(encoding="utf-8"))
    app_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    sites = skip_sites(app_class)
    deciders = sorted({decider for _fn, decider, _g in sites if decider})
    assert deciders, "no loop in %s asks a method whether a document is done" % folder.name

    for name in deciders:
        answers = {}
        for again in (False, True):
            home = tmp_path / ("again" if again else "plain") / name
            inst = built(folder, mod, parser_fn, cls,
                         panel_argv("all", SCOPES[0], again=again), home)
            inst.progress.update(KEY, {"downloaded_ok": True, "state": "Completed",
                                       "pdf_path": "", "pdf_filename": ""})
            answers[again] = getattr(inst, name)(Item(KEY))
        assert answers[False], "%s.%s does not count a document downloaded before as done" \
            % (folder.name, name)
        assert not answers[True], "%s.%s skips it even with %s" % (folder.name, name, flag())

    for fn, decider, guarded in sites:
        if decider or guarded:
            continue
        assert (folder.name, fn) in OWN_REASON, (
            "%s.%s counts a document as done with no test of %s around it"
            % (folder.name, fn, flag()))


def test_every_place_named_with_a_reason_is_still_there():
    for (app, fn) in OWN_REASON:
        module = entries(APPS / app)[0]
        tree = ast.parse(module[0].read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == module[2])
        assert any(site[0] == fn and site[1] is None and not site[2]
                   for site in skip_sites(cls)), "%s.%s is gone or changed" % (app, fn)


def test_the_census_is_not_empty():
    """Found by behavior, a census that finds nothing passes on nothing."""
    assert len(FOLDERS) >= 61
    assert sum(1 for folder in FOLDERS if len(entries(folder)) == 1) == len(FOLDERS)
    assert flag() == "--redownload"
    assert set(panel()["REDOWNLOAD_ACTIONS"]) == {"pilot", "all"}
