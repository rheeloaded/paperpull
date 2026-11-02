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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
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
    assert cfg["cdp_url"] == "http://127.0.0.1:9400"
    assert cfg["owner"] == "Jane Doe"
    assert Path(cfg["output_dir"]).is_dir()
    assert (chase / "config.json").read_text(encoding="utf-8") == before


def _port(app_dir, name="spouse"):
    return add_account._port_of(json.loads(
        (app_dir / ("config.%s.json" % name)).read_text(encoding="utf-8"))["cdp_url"])


def test_a_second_account_never_takes_another_apps_port(tmp_path):
    """E-ZPass's 9274 plus 10 was Interactive Brokers' 9284, so the second
    account's browser and IBKR's attached to each other. A second person is
    now given a port from 9400 up, where no app's port is."""
    ezpass = _install(tmp_path, "E-ZPass Statements", "ezpassva_docs.py",
                      dict(_config(tmp_path, "E-ZPass Statements"), cdp_url="http://127.0.0.1:9274"))
    _install(tmp_path, "Interactive Brokers Statements", "ibkr_docs.py",
             dict(_config(tmp_path, "Interactive Brokers Statements"), cdp_url="http://127.0.0.1:9284"))
    assert add_account.main(["spouse", "--app", "E-ZPass Statements", "--root", str(tmp_path)]) == 0
    assert _port(ezpass) == 9400


def test_a_person_is_never_given_the_port_of_an_app_set_up_later(tmp_path):
    """The clash the old rule made. E-ZPass's second person was given 9284
    while Interactive Brokers was not set up, and IBKR set up afterwards
    came with 9284 too. A person's port is now one no app comes with."""
    ezpass = _install(tmp_path, "E-ZPass Statements", "ezpassva_docs.py",
                      dict(_config(tmp_path, "E-ZPass Statements"), cdp_url="http://127.0.0.1:9274"))
    add_account.make_config(ezpass, "spouse", owner="Jane Doe")
    examples = [add_account._port_of(json.loads(p.read_text(encoding="utf-8")).get("cdp_url"))
                for p in (REPO / "apps").glob("*/config.example.json")]
    assert _port(ezpass) not in examples


def test_the_panels_add_a_person_reads_the_apps_beside_it(tmp_path):
    """The panel calls make_config for one app with no set of ports of its
    own, and the people beside it are still read, so a second person takes
    the next port of the range, not one a person beside it has."""
    ezpass = _install(tmp_path, "E-ZPass Statements", "ezpassva_docs.py",
                      dict(_config(tmp_path, "E-ZPass Statements"), cdp_url="http://127.0.0.1:9274"))
    ibkr = _install(tmp_path, "Interactive Brokers Statements", "ibkr_docs.py",
                    dict(_config(tmp_path, "Interactive Brokers Statements"),
                         cdp_url="http://127.0.0.1:9284"))
    (ibkr / "config.kid.json").write_text(json.dumps({"cdp_url": "http://127.0.0.1:9400"}),
                                          encoding="utf-8")
    add_account.make_config(ezpass, "spouse", owner="Jane Doe")
    assert _port(ezpass) == 9401


def test_the_old_rule_is_kept_for_who_asks_for_it(tmp_path):
    """--port-offset still gives the app's own port plus that many, moved
    past every port in use, for anyone who keeps their ports that way."""
    ezpass = _install(tmp_path, "E-ZPass Statements", "ezpassva_docs.py",
                      dict(_config(tmp_path, "E-ZPass Statements"), cdp_url="http://127.0.0.1:9274"))
    _install(tmp_path, "Interactive Brokers Statements", "ibkr_docs.py",
             dict(_config(tmp_path, "Interactive Brokers Statements"), cdp_url="http://127.0.0.1:9284"))
    add_account.make_config(ezpass, "spouse", port_offset=10)
    assert _port(ezpass) == 9285


def test_no_app_comes_with_a_port_in_the_peoples_range():
    """When the apps' own ports reach 9400, a second person's port could be
    the port of an app set up after them again. This fails first, so the
    range moves before that can happen."""
    high = {}
    for example in (REPO / "apps").glob("*/config.example.json"):
        port = add_account._port_of(json.loads(example.read_text(encoding="utf-8")).get("cdp_url"))
        if port and port >= add_account.PEOPLE_PORTS:
            high[example.parent.name] = port
    assert not high, high
    from paperpull_core import ports
    assert ports.PEOPLE_PORTS == add_account.PEOPLE_PORTS


def test_two_apps_given_accounts_in_one_run_take_two_ports(tmp_path):
    """One app's second account is also never another's, nor the port an
    account made earlier in the same run took."""
    first = _install(tmp_path, "Alpha Statements", "alpha_docs.py",
                     dict(_config(tmp_path, "Alpha Statements"), cdp_url="http://127.0.0.1:9300"))
    second = _install(tmp_path, "Beta Statements", "beta_docs.py",
                      dict(_config(tmp_path, "Beta Statements"), cdp_url="http://127.0.0.1:9310"))
    (second / "config.example.json").write_text(json.dumps({"cdp_url": "http://127.0.0.1:9320"}),
                                                encoding="utf-8")
    assert add_account.main(["spouse", "--root", str(tmp_path)]) == 0
    ports = {_port(first), _port(second)}
    assert ports.isdisjoint({9300, 9310, 9320}) and len(ports) == 2, ports


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
    assert cfg["cdp_url"] == "http://127.0.0.1:9400"
