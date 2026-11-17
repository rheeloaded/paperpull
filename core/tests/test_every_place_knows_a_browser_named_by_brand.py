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
