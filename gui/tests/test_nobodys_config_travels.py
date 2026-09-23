"""A config belongs to whoever set that folder up, and never travels.

An install is made by copying a template, and every panel run brings an
install's code back up to the shipped version by copying from the same
place. config.json was named in the skip list. A second person's account
is config.<label>.json, which no list knew about.

In a checkout used as the template root, one of those sitting on disk
would have been copied into every install as though it were part of the
app, handing somebody an account they never asked for, pointing at another
person's folders and carrying their name.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")


def template(tmp_path: Path) -> Path:
    """A provider template with one person's settings left lying in it."""
    src = tmp_path / "templates" / "chase"
    src.mkdir(parents=True)
    (src / "chase_docs.py").write_text("the app\n", encoding="utf-8")
    (src / "chase_site.py").write_text("the selectors\n", encoding="utf-8")
    (src / "config.example.json").write_text('{"owner": ""}', encoding="utf-8")
    (src / "config.json").write_text(json.dumps({"owner": "Dana"}), encoding="utf-8")
    (src / "config.esther.json").write_text(json.dumps({"owner": "Esther"}), encoding="utf-8")
    (src / "progress.json").write_text('{"a": 1}', encoding="utf-8")
    return src


def test_a_second_persons_account_is_not_part_of_the_app(tmp_path):
    src = template(tmp_path)
    shipped = sorted(str(rel) for rel, _item in app_module._template_files(src))
    assert "config.esther.json" not in shipped
    assert "config.json" not in shipped
    assert "progress.json" not in shipped


def test_the_example_is_the_one_config_that_does_ship(tmp_path):
    src = template(tmp_path)
    shipped = sorted(str(rel) for rel, _item in app_module._template_files(src))
    assert "config.example.json" in shipped
    assert "chase_docs.py" in shipped and "chase_site.py" in shipped


def test_the_rule_itself():
    own = app_module._is_someones_own
    for name in ("config.json", "config.esther.json", "config.Esther.JSON",
                 "config.second-person.json", "config.2.json"):
        assert own(name), name
    for name in ("config.example.json", "CONFIG.EXAMPLE.JSON",
                 "chase_site.py", "document_rules.json", "requirements.txt"):
        assert not own(name), name


def test_bringing_an_install_up_to_date_leaves_its_accounts_alone(tmp_path):
    """The refresh runs on every panel load, so this is the path that would
    have done it quietly and often."""
    src = template(tmp_path)
    dst = tmp_path / "Chase Statements"
    dst.mkdir()
    (dst / "chase_docs.py").write_text("the OLD app\n", encoding="utf-8")
    mine = json.dumps({"owner": "Whoever lives here", "output_dir": "D:/mine"})
    (dst / "config.json").write_text(mine, encoding="utf-8")

    replaced = app_module.refresh_install_code(dst, src)

    assert "chase_docs.py" in replaced, "the code should have been brought up to date"
    assert (dst / "chase_docs.py").read_text(encoding="utf-8") == "the app\n"
    assert (dst / "config.json").read_text(encoding="utf-8") == mine, \
        "somebody's own settings were overwritten"
    assert not (dst / "config.esther.json").exists(), \
        "an account from somewhere else was planted here"


def test_the_packager_ships_no_config_but_the_example():
    import importlib.util
    repo = Path(app_module.__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "bw", repo / "packaging" / "build_windows.py")
    bw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bw)
    assert bw.wanted("apps/chase/config.example.json")
    for p in ("apps/chase/config.json", "apps/chase/config.esther.json",
              "apps/chase/progress.json", "apps/chase/discovery.json"):
        assert not bw.wanted(p), p
