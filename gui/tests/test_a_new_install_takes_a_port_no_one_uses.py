"""A provider installed from the panel never takes a debugging port that an
install or a second person beside it already uses.

An app's example config names a port no other app's example names, and
that was taken to make it free. But a second person's account is given its
app's port plus 10, moved past only the ports the installs there use at
that moment, so it can hold the port of an app installed afterwards.
E-ZPass's 9274 plus 10 is Interactive Brokers' 9284 while IBKR is not
installed, and Chase Business's 9290 plus 10 is 9300, the port the next
new app was given. The new install's config.json was its example, so it
and the second person attached to one browser, and each signed in to the
other's profile.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


@pytest.fixture(autouse=True)
def desktop(monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)


def _port(config: Path) -> int:
    url = json.loads(config.read_text(encoding="utf-8-sig"))["cdp_url"]
    return int(re.search(r":(\d+)", url).group(1))


def _install(root: Path, slug: str) -> Path:
    assert app_module.create_install(root, slug) == "created"
    return root / next(p["folder"] for p in app_module.list_providers() if p["slug"] == slug)


def test_an_app_installed_after_a_second_person_takes_a_port_of_its_own(tmp_path):
    root = tmp_path / "installs"
    root.mkdir()
    ezpass = _install(root, "ezpassva")
    spouse = app_module._make_account(ezpass, "spouse", "Jane Doe")
    assert _port(spouse) == 9284                    # Interactive Brokers', not installed yet

    ibkr = _install(root, "ibkr")
    assert _port(ibkr / "config.json") == 9285
    assert _port(spouse) == 9284                    # the person added first keeps theirs
    assert _port(ezpass / "config.json") == 9274
    # Only the port moved. The rest is the example's, as before.
    want = json.loads((ibkr / "config.example.json").read_text(encoding="utf-8-sig"))
    got = json.loads((ibkr / "config.json").read_text(encoding="utf-8-sig"))
    assert {k: v for k, v in got.items() if k != "cdp_url"} == \
           {k: v for k, v in want.items() if k != "cdp_url"}
    assert got["cdp_url"] == want["cdp_url"].replace(":9284", ":9285")

    costco = _install(root, "costco")
    assert _port(costco / "config.json") == 9268    # a port no one uses is kept


def test_the_port_it_moves_to_is_past_every_port_in_use(tmp_path):
    root = tmp_path / "installs"
    root.mkdir()
    ezpass = _install(root, "ezpassva")
    app_module._make_account(ezpass, "spouse", "Jane Doe")      # 9284
    optum = _install(root, "optum")                             # 9285, its own
    assert _port(optum / "config.json") == 9285

    ibkr = _install(root, "ibkr")
    assert _port(ibkr / "config.json") == 9286
    used = [_port(c) for d in root.iterdir() if d.is_dir()
            for c in d.glob("config*.json") if c.name != "config.example.json"]
    assert len(used) == len(set(used)), used


def test_a_port_an_update_adds_moves_off_one_in_use(tmp_path):
    """Target had no port before 0.34.0. An install from then has none in
    its config.json, so a person added beside it could take 9269, and the
    update that brought Target's port copied 9269 in from the example."""
    root = tmp_path / "installs"
    root.mkdir()
    target = _install(root, "target")
    cfg = json.loads((target / "config.json").read_text(encoding="utf-8-sig"))
    del cfg["cdp_url"]
    (target / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    other = root / "Someone Else Statements"
    other.mkdir()
    (other / "someone_docs.py").write_text("", encoding="utf-8")
    (other / "config.spouse.json").write_text(
        json.dumps({"cdp_url": "http://127.0.0.1:9269"}), encoding="utf-8")

    assert "cdp_url" in app_module.ensure_settings(target)
    assert _port(target / "config.json") == 9270


def test_every_provider_installed_beside_a_person_on_its_port_moves_off_it(tmp_path):
    """Every template, since the port is read from each one's own example,
    and a cdp_url written another way would keep the port it shares."""
    providers = app_module.list_providers()
    assert len(providers) >= 70, len(providers)
    shared = []
    for i, p in enumerate(providers):
        example = app_module._templates_root() / p["slug"] / "config.example.json"
        cfg = json.loads(example.read_text(encoding="utf-8-sig"))
        if not re.search(r":(\d+)", cfg.get("cdp_url") or ""):
            continue
        port = _port(example)
        root = tmp_path / str(i)
        other = root / "Someone Else Statements"
        other.mkdir(parents=True)
        (other / "someone_docs.py").write_text("", encoding="utf-8")
        (other / "config.spouse.json").write_text(
            json.dumps({"cdp_url": "http://127.0.0.1:%d" % port}), encoding="utf-8")
        install = _install(root, p["slug"])
        if _port(install / "config.json") == port:
            shared.append("%s on %d" % (p["slug"], port))
    assert not shared, shared
