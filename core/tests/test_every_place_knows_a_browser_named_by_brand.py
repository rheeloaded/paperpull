"""Every place the "browser" setting or a profile folder is known by, held
to the eight values and the brand folders of #222.

The setting takes auto, installed, bundled, edge, chrome, brave, vivaldi or
opera. Every app hands it to the core as it is, every example config holds
one of them, and the pages that tell a person what to type list the code's
own eight. A brand opens on a folder beside the usual one, with the ending
a fallback to that brand already had, and every place that knows a profile
folder by its name knows those folders too. The panel's own two are held in
gui/tests/test_a_brand_profile_is_never_a_documents_folder.py.
"""
import ast
import fnmatch
import json
import re
from pathlib import Path

import pytest

from paperpull_core import browser, shared_folder

ROOT = Path(__file__).resolve().parents[2]
EIGHT = ("auto", "installed", "bundled", "edge", "chrome", "brave", "vivaldi", "opera")
ENDINGS = ("-microsoftedge", "-googlechrome", "-brave", "-vivaldi", "-opera")


def _apps():
    return sorted(p for p in (ROOT / "apps").iterdir() if (p / "config.example.json").is_file())


def test_the_code_takes_exactly_the_eight():
    assert tuple(browser.BROWSER_VALUES) == EIGHT


def test_every_example_config_names_one_of_the_eight():
    apps = _apps()
    assert len(apps) >= 90
    for app in apps:
        cfg = json.loads((app / "config.example.json").read_text(encoding="utf-8"))
        assert cfg.get("browser") in EIGHT, app.name


def _sign_in_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "open_signin_browser":
                yield node


def test_every_app_hands_the_setting_over_as_it_is():
    """So the core is the one place a value is read, and a brand, or a
    value that is none of the eight, reaches it from every app."""
    want = ast.dump(ast.parse('self.config.get("browser", "auto")', mode="eval").body)
    seen = 0
    # Each app's own files, never its tests or a virtual environment.
    for path in sorted((ROOT / "apps").glob("*/*.py")):
        for call in _sign_in_calls(path):
            seen += 1
            modes = [k.value for k in call.keywords if k.arg == "mode"]
            assert len(modes) == 1 and ast.dump(modes[0]) == want, "%s:%d" % (path, call.lineno)
    assert seen >= 90


def _words(text: str) -> set:
    return set(re.findall(r"[a-z]+", text.lower()))


def test_the_settings_comment_lists_the_eight():
    text = (ROOT / "core" / "paperpull_core" / "storage.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if 'cfg.setdefault("browser"' in line)
    start = at
    while lines[start - 1].strip().startswith("#"):
        start -= 1
    comment = "\n".join(lines[start:at])
    assert set(EIGHT) <= _words(comment), comment


def test_the_guide_for_a_new_provider_lists_the_eight():
    text = (ROOT / "docs" / "adding-a-provider.md").read_text(encoding="utf-8")
    para = next(p for p in text.split("\n- ") if '"browser"' in p)
    for word in EIGHT:
        assert '"%s"' % word in para or "`%s`" % word in para, word


def _readme_section() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"^### Can I choose the browser it signs in with\?\n(.*?)(?=^#)", text, re.S | re.M)
    assert m, "README has no section on the browser setting"
    return m.group(1)


def test_the_readme_lists_the_eight_and_how_to_pick_chrome():
    section = _readme_section()
    for word in EIGHT:
        assert "`%s`" % word in section or '"%s"' % word in section, word
    assert '"browser": "chrome"' in section
    assert "sign-in" in section or "sign in" in section


@pytest.mark.parametrize("ending", ENDINGS)
def test_a_brand_folder_is_never_walked_for_links(ending):
    """A profile copied from a desktop holds links of its own, and a run
    writes nothing in one (shared_folder._walked)."""
    assert not shared_folder._walked("chase-browser-profile" + ending)
    assert not shared_folder._walked("browser-profile" + ending)
    assert shared_folder._walked("Statements" + ending)


def test_a_brand_folder_is_kept_out_of_git():
    """The repo's own .gitignore keeps every profile folder out, so none is
    ever tracked, and server/build.py, which reads only tracked paths, never
    meets one. Its whole-part "browser-profile" stays as it is."""
    lines = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "**/*browser-profile*/" in lines
    for ending in ENDINGS:
        assert fnmatch.fnmatchcase("chase-browser-profile" + ending, "*browser-profile*")


@pytest.mark.parametrize("word,ending", zip(("edge", "chrome", "brave", "vivaldi", "opera"), ENDINGS))
def test_every_brand_folder_is_one_the_core_knows(word, ending, tmp_path):
    """profile_folders, which the panel asks, names each brand's folder."""
    base = browser.profile_folder(tmp_path / "browser-profile")
    assert base.with_name(base.name + ending) in browser.profile_folders(tmp_path / "browser-profile")


# -- every function that knows a profile folder by name or by profile_dir ----
#
# Each one either knows the folders beside it, through the core's own list
# of them, or is named here with why it need not. A new one that does
# neither fails, so a check such as "is documents_dir the profile" cannot
# again forget the folder a brand or a fallback opens on.

KNOWS_THE_BRAND_FOLDERS = ("profile_folders", "_with_brand_folders", "PROFILE_ENDS",
                           "_FALLBACK_ENDS", "_names_profile", "brand_profile",
                           "close_signin_browser",
                           # tools/upgrade.py's own call of profile_folders, kept
                           # for a copy of the tool that runs without the core
                           "_profile_folders")
NEED_NOT = {
    "core/paperpull_core/storage.py::load_config": "sets the default profile_dir",
    "core/paperpull_core/storage.py::hold_to_the_server":
        "puts profile_dir on the profiles volume, where a brand keeps the base folder",
    "core/paperpull_core/testkit.py::receipt_app": "a test app's config",
    "gui/app.py::_set_profile": "writes the setting",
    "gui/app.py::_removal_summary":
        'matches "browser-profile" anywhere in a name, which every brand folder holds',
    "gui/app.py::_skip_template_part":
        'matches "browser-profile" anywhere in a name, which every brand folder holds',
    "tools/add_account.py::make_config": "names a new account's base folder",
    "server/build.py::left_out":
        "reads tracked paths only, and .gitignore keeps every profile folder untracked",
}
# Each folder is looked through to its last level, the root alone only at
# its own, and never into tests, a virtual environment or a cache.
SHIPPED = ("core/paperpull_core", "gui", "server", "tools")
NOT_SHIPPED = {"tests", ".venv", "venv", "__pycache__", "node_modules"}
HANDED_TO_THE_CORE = ("open_signin_browser(", "launch_own_browser(")
APP_NEED_NOT = {"apps/target/target_receipts.py::cmd_login": "only prints the folder"}
MODULE = "<module>"
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _docstrings(tree) -> set:
    """The ids of the docstring nodes in tree, which say things and do
    nothing."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module,) + DEFS) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _only_constants(node) -> bool:
    return all(isinstance(n, (ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Load)) for n in ast.walk(node))


def _profile_constants(tree) -> set:
    """Module-level names given a text that holds browser-profile."""
    out = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            texts = [n.value for n in ast.walk(stmt.value)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            if any("browser-profile" in t for t in texts):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                out |= {t.id for t in targets if isinstance(t, ast.Name)}
    return out


def _units(tree):
    """(name, nodes) for each function, and for the code at module level,
    a class's own lines included. A module-level constant is data, so it is
    left out there and followed where it is used instead."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, list(ast.walk(node))
    top, stack = [], list(tree.body)
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, ast.ClassDef):
            stack.extend(stmt.body)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None \
                and _only_constants(stmt.value):
            continue
        else:
            top.extend(ast.walk(stmt))
    yield MODULE, top


def profile_readers(source: str, where: str):
    """(place, whether it knows the brand folders) for each function, and
    the module level, that names profile_dir or a browser-profile folder in
    its code, by a text, an attribute or a constant holding the name.
    Knowing is a real name or attribute of the core's list, never a word in
    a comment, a docstring or a text."""
    tree = ast.parse(source)
    skip, constants = _docstrings(tree), _profile_constants(tree)
    for name, nodes in _units(tree):
        names = knows = False
        for n in nodes:
            if id(n) in skip:
                continue
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                names = names or n.value == "profile_dir" or "browser-profile" in n.value
            elif isinstance(n, ast.Attribute):
                names = names or n.attr == "profile_dir"
                knows = knows or n.attr in KNOWS_THE_BRAND_FOLDERS
            elif isinstance(n, ast.Name):
                names = names or n.id in constants
                knows = knows or n.id in KNOWS_THE_BRAND_FOLDERS
            elif isinstance(n, ast.alias):
                knows = knows or n.name in KNOWS_THE_BRAND_FOLDERS
        if names:
            yield "%s::%s" % (where, name), knows


def forgetful(source: str, where: str) -> list:
    return [name for name, knows in profile_readers(source, where)
            if not knows and name not in NEED_NOT]


def _shipped_sources():
    paths = list(ROOT.glob("*.py"))
    for base in SHIPPED:
        paths += [p for p in (ROOT / base).rglob("*.py")
                  if not NOT_SHIPPED & set(p.relative_to(ROOT).parts)]
    for path in sorted(paths):
        yield path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix()


def test_every_place_that_knows_a_profile_folder_knows_the_brand_folders():
    found, wrong = set(), []
    for source, where in _shipped_sources():
        for name, _knows in profile_readers(source, where):
            found.add(name)
        wrong += forgetful(source, where)
    assert wrong == []
    for must in ("core/paperpull_core/storage.py::set_documents_dir",
                 "gui/app.py::_documents_in_use", "gui/app.py::_profiles_known",
                 "gui/app.py::_not_for_documents", "core/paperpull_core/shared_folder.py::_walked"):
        assert must in found, must
    assert "tools/upgrade.py::inspect" in found and "tools/upgrade.py::inspect" not in NEED_NOT
    assert set(NEED_NOT) <= found, set(NEED_NOT) - found


def test_the_census_finds_a_new_place_that_forgets_them():
    sample = '''
def documents_problem(cfg, docs):
    profile = cfg.get("profile_dir")
    return docs == profile


def is_profile(name):
    return name.endswith("browser-profile")


def knows(cfg, docs):
    from paperpull_core import browser
    return docs in browser.profile_folders(cfg["profile_dir"])
'''
    assert forgetful(sample, "gui/sample.py") == ["gui/sample.py::documents_problem",
                                                  "gui/sample.py::is_profile"]


FOUR_WAYS_TO_SLIP_PAST = {
    "a mention in a comment or a docstring is not knowing": '''
def documents_problem(cfg, docs):
    """Unlike browser.profile_folders, this looks at one folder."""
    # unlike profile_folders and _with_brand_folders
    print("PROFILE_ENDS are not looked at")
    return docs == cfg["profile_dir"]
''',
    "a constant holding the name, used later": '''
BASE = "browser-profile"


def is_profile(name):
    return name.endswith(BASE)
''',
    "an attribute named profile_dir": '''
class Account:
    def holds(self, docs):
        return docs == self.profile_dir
''',
    "a check at module level": '''
import sys

if sys.argv[1].endswith("browser-profile"):
    raise SystemExit("that is a profile")
''',
}


@pytest.mark.parametrize("why", sorted(FOUR_WAYS_TO_SLIP_PAST))
def test_the_census_is_not_passed_by_code_that_breaks_its_rule(why):
    assert forgetful(FOUR_WAYS_TO_SLIP_PAST[why], "gui/sample.py") != [], why


def test_the_census_takes_a_real_call_of_the_core_list():
    sample = '''
BASE = "browser-profile"


def holds(self, docs):
    from paperpull_core import browser
    return docs in browser.profile_folders(self.profile_dir)
'''
    assert forgetful(sample, "gui/sample.py") == []


def test_the_census_looks_in_every_folder_below_the_shipped_ones():
    where = {w for _source, w in _shipped_sources()}
    assert "tools/pytest_plugins/core_part.py" in where
    assert any(w.startswith("server/plugins/paperless/") for w in where)
    assert not any("/tests/" in w or "/.venv/" in w for w in where)


def test_every_app_hands_its_profile_folder_to_the_core():
    """An app names profile_dir only to hand it to the core's sign-in or to
    a browser of its own, so it never decides by name what a profile is."""
    for app in _apps():
        for path in sorted(app.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name, _knows in profile_readers(source, path.relative_to(ROOT).as_posix()):
                if name in APP_NEED_NOT:
                    continue
                fn = name.split("::")[1]
                assert fn != MODULE, name
                srcs = [ast.get_source_segment(source, n) or "" for n in ast.walk(ast.parse(source))
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn]
                assert any(call in src for src in srcs for call in HANDED_TO_THE_CORE), name
