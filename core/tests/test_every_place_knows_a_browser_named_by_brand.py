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
                           "close_signin_browser")
NEED_NOT = {
    "core/paperpull_core/browser.py::_launch": "opens the one folder it is handed",
    "core/paperpull_core/storage.py::load_config": "sets the default profile_dir",
    "core/paperpull_core/storage.py::hold_to_the_server":
        "puts profile_dir on the profiles volume, where a brand keeps the base folder",
    "core/paperpull_core/testkit.py::receipt_app": "a test app's config",
    "gui/app.py::_set_profile": "writes the setting",
    "gui/app.py::_removal_summary":
        'matches "browser-profile" anywhere in a name, which every brand folder holds',
    "gui/app.py::_skip_template_part":
        'matches "browser-profile" anywhere in a name, which every brand folder holds',
    "server/smoke.py::set_up_provider": "the smoke test's own config",
    "tools/add_account.py::make_config": "names a new account's base folder",
    "tools/upgrade.py::inspect": "only warns that no sign-in has been made yet",
}
SHIPPED = ("core/paperpull_core", "gui", "server", "tools", ".")
HANDED_TO_THE_CORE = ("open_signin_browser(", "launch_own_browser(")
APP_NEED_NOT = {"apps/target/target_receipts.py::cmd_login": "only prints the folder"}


def _names_a_profile(src: str) -> bool:
    return any(mark in src for mark in ('"profile_dir"', "'profile_dir'", "browser-profile"))


def profile_readers(source: str, where: str):
    """(function, whether it knows the brand folders) for each function in
    source that names profile_dir or a browser-profile folder."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.get_source_segment(source, node) or ""
            if _names_a_profile(src):
                yield "%s::%s" % (where, node.name), any(k in src for k in KNOWS_THE_BRAND_FOLDERS)


def forgetful(source: str, where: str) -> list:
    return [name for name, knows in profile_readers(source, where)
            if not knows and name not in NEED_NOT]


def _shipped_sources():
    for base in SHIPPED:
        for path in sorted((ROOT / base).glob("*.py")):
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
                node = next(n for n in ast.walk(ast.parse(source))
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn
                            and _names_a_profile(ast.get_source_segment(source, n) or ""))
                src = ast.get_source_segment(source, node)
                assert any(call in src for call in HANDED_TO_THE_CORE), name
