"""A second person's account, in one app or every app.

The tool used to be a file copied into every app with a hard-coded list of
install paths that was stale in every copy. Now it is one file that finds
the installs the way the launcher does. What matters is that the second
account never shares a folder, a profile or a port with the first, and that
the first account's files are not touched.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
add_account = pytest.importorskip("add_account")
paperpull = add_account.paperpull


def _install(root: Path, name: str, entry: str, config=None):
    d = root / name
    d.mkdir(parents=True)
    (d / entry).write_text("", encoding="utf-8")
    (d / "storage.py").write_text('provider = "%s"\n' % name.split()[0], encoding="utf-8")
    if config is not None:
        (d / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return d


def _config(root, name):
    return {"output_dir": str(root / name / "output"), "profile_dir": "browser-profile",
            "cdp_url": "http://127.0.0.1:9223", "owner": "Pat"}


def test_the_second_account_shares_nothing_with_the_first(tmp_path):
    chase = _install(tmp_path, "Chase Statements", "chase_docs.py", _config(tmp_path, "Chase Statements"))
    before = (chase / "config.json").read_text(encoding="utf-8")
    dest = add_account.make_config(chase, "spouse", owner="Jane Doe")
    assert dest == chase / "config.spouse.json"
    cfg = json.loads(dest.read_text(encoding="utf-8"))
    assert cfg["output_dir"].endswith("output - spouse")
    assert cfg["profile_dir"] == str(Path(cfg["output_dir"]) / "browser-profile")
    assert cfg["cdp_url"] == "http://127.0.0.1:9233"
    assert cfg["owner"] == "Jane Doe"
    assert Path(cfg["output_dir"]).is_dir()
    assert (chase / "config.json").read_text(encoding="utf-8") == before


def test_every_app_under_the_root_gets_one_and_an_unset_up_app_is_skipped(tmp_path, capsys):
    _install(tmp_path, "Chase Statements", "chase_docs.py", _config(tmp_path, "Chase Statements"))
    _install(tmp_path, "Ally Statements", "ally_docs.py")           # no config.json yet
    _install(tmp_path, "Amazon Receipts", "amazon_receipts.py", _config(tmp_path, "Amazon Receipts"))
    (tmp_path / "Not An App").mkdir()
    assert add_account.main(["spouse", "--root", str(tmp_path)]) == 0
    made = sorted(p.parent.name for p in tmp_path.glob("*/config.spouse.json"))
    assert made == ["Amazon Receipts", "Chase Statements"]
    out = capsys.readouterr().out
    assert "skip (no config.json, run setup first): Ally Statements" in out
    assert "Done: 2 config(s)." in out


def test_one_app_by_slug_and_the_label_is_a_safe_filename(tmp_path):
    _install(tmp_path, "Chase Statements", "chase_docs.py", _config(tmp_path, "Chase Statements"))
    _install(tmp_path, "Amazon Receipts", "amazon_receipts.py", _config(tmp_path, "Amazon Receipts"))
    assert add_account.main(["Jane & Co", "--app", "chase", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "Chase Statements" / "config.janeco.json").is_file()
    assert not list((tmp_path / "Amazon Receipts").glob("config.*.json"))


def test_the_launcher_command_reaches_the_tool_and_names_it_when_missing(tmp_path, capsys):
    _install(tmp_path, "Chase Statements", "chase_docs.py", _config(tmp_path, "Chase Statements"))
    assert paperpull.main(["--root", str(tmp_path), "chase", "add-account", "spouse",
                           "--port-offset", "20"]) == 0
    cfg = json.loads((tmp_path / "Chase Statements" / "config.spouse.json").read_text(encoding="utf-8"))
    assert cfg["cdp_url"] == "http://127.0.0.1:9243"
    with pytest.raises(SystemExit) as e:
        paperpull.main(["--root", str(tmp_path), "chase", "add-account"])
    assert "add-account spouse" in str(e.value)
    with pytest.raises(SystemExit) as e:
        paperpull.main(["--root", str(tmp_path), "chase", "pilot", "--account", "nobody"])
    assert "python paperpull.py chase add-account nobody" in str(e.value)


def test_an_install_that_holds_its_own_downloads_gets_a_sibling_folder(tmp_path):
    """A packaged install keeps its downloads in the install folder itself
    (output_dir "."). The old rule turned that into a folder called " - spouse"
    inside the install. The second account's folder is a sibling of the
    install, named for it, and the path is relative so the install can move."""
    home = tmp_path / "PaperPull"
    amazon = _install(home, "Amazon Receipts", "amazon_receipts.py",
                      {"output_dir": ".", "profile_dir": "./browser-profile", "cdp_url": "http://127.0.0.1:9223"})
    dest = add_account.make_config(amazon, "spouse")
    cfg = json.loads(dest.read_text(encoding="utf-8"))
    assert cfg["output_dir"] == str(Path("..") / "Amazon Receipts - spouse")
    assert cfg["profile_dir"] == str(Path("..") / "Amazon Receipts - spouse" / "browser-profile")
    assert (home / "Amazon Receipts - spouse").is_dir()
    assert not (amazon / " - spouse").exists()
    assert cfg["cdp_url"] == "http://127.0.0.1:9233"
