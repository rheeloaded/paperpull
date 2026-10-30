"""Login says when another config beside this one names its port.

A sign-in on a port a browser already holds joins that browser (#90), so two
configs on one port sign in to one browser, one profile. A second person is
given their app's port plus 10, moved past only the ports in use then, so an
app set up after them can come with that same port, and a config copied by
hand can name any port. Login now says which other install and account name
the port and which cdp_url to change to what, and goes on with the sign-in,
since a wrong refusal is worse than the clash. An install's own example and
a config with no port are never a clash. Every folder is under tmp_path and
every provider, label and port is made up.
"""
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import browser, storage

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
add_account = pytest.importorskip("add_account")
paperpull = add_account.paperpull

SIGN_IN = "https://bank.example/sign-in"


def install(root: Path, folder: str, script: str, example=None, **configs) -> Path:
    """An install with its entry script, its example when it has a port, and
    each config given, config.json as primary and the rest by label."""
    d = root / folder
    d.mkdir(parents=True)
    (d / script).write_text("", encoding="utf-8")
    if example is not None:
        (d / "config.example.json").write_text(
            json.dumps({"output_dir": ".", "cdp_url": example}), encoding="utf-8")
    for account, cfg in configs.items():
        name = "config.json" if account == "primary" else "config.%s.json" % account
        (d / name).write_text(json.dumps(dict({"output_dir": str(d / account)}, **cfg)),
                              encoding="utf-8")
    return d


def at(port: int) -> dict:
    return {"cdp_url": "http://127.0.0.1:%d" % port}


@pytest.fixture(autouse=True)
def shipped(tmp_path, monkeypatch):
    """The providers this copy ships, a folder of its own with none in it
    until a test puts some there, so no test reads the repo's own."""
    from paperpull_core import ports
    folder = tmp_path / "templates"
    folder.mkdir()
    monkeypatch.setattr(ports, "shipped_folders", lambda: [folder])
    return folder


@pytest.fixture()
def launches(monkeypatch, capsys):
    """A sign-in that launches a browser of its own, as on a free port, and
    what had been said when it did."""
    said = []

    def launch(*a, **kw):
        said.append(capsys.readouterr().out)
        return "Chromium"
    monkeypatch.setattr(browser, "browser_candidates", lambda **kw: [("Chromium", "/x/chrome")])
    monkeypatch.setattr(browser, "_try_each", launch)
    return said


def sign_in(config: Path, port) -> str:
    storage.load_config(config)
    return browser.open_signin_browser(config.parent / "browser-profile", str(port), SIGN_IN)


@pytest.fixture()
def pair(tmp_path):
    """Grocer's second person on 9262, then Card set up on its example's
    9262, and Store on 9263, the next port up."""
    root = tmp_path / "PaperPull"
    grocer = install(root, "Grocer Receipts", "grocer_receipts.py", "http://127.0.0.1:9252",
                     primary=at(9252), spouse=at(9262))
    card = install(root, "Card Statements", "card_docs.py", "http://127.0.0.1:9262",
                   primary=at(9262))
    install(root, "Store Receipts", "store_receipts.py", "http://127.0.0.1:9263",
            primary=at(9263))
    return grocer, card


def test_login_names_the_other_install_and_account_and_the_cdp_url_to_change(pair, launches):
    grocer, card = pair
    assert sign_in(card / "config.json", 9262) == "Chromium"
    said = launches[0]
    assert "!! Another config beside this one names port 9262 too." in said
    assert 'the "spouse" account of Grocer Receipts (config.spouse.json)' in said
    # The second person's config strayed onto Card's own port, so it is the
    # one to move, past Store's 9263 to the first free port.
    assert "give the config below a port of its own by changing its cdp_url" in said
    assert "     %s\n       http://127.0.0.1:9264\n" % (grocer / "config.spouse.json") in said
    assert "(this config)" not in said
    assert "the sign-in goes on" in said


def test_the_second_person_is_told_to_change_their_own(pair, launches):
    grocer, card = pair
    assert sign_in(grocer / "config.spouse.json", 9262) == "Chromium"
    said = launches[0]
    assert "the first account of Card Statements (config.json)" in said
    assert "     %s (this config)\n       http://127.0.0.1:9264\n" % (
        grocer / "config.spouse.json") in said


def test_a_sign_in_on_a_port_no_other_config_names_says_nothing(pair, launches):
    grocer, _ = pair
    assert sign_in(grocer / "config.json", 9252) == "Chromium"
    assert "!!" not in launches[0]


def test_an_install_s_own_example_and_a_config_with_no_port_are_no_clash(tmp_path, launches):
    """Chase's config is on its example's 9236. Beside it are an app not set
    up yet whose example names 9236 too, a config that names no cdp_url, one
    whose cdp_url names no port, one whose cdp_url is not text, and two on
    the loopback address of IPv6 whose ports are not 9236 or each other's."""
    root = tmp_path / "PaperPull"
    chase = install(root, "Chase Statements", "chase_docs.py", "http://127.0.0.1:9236",
                    primary=at(9236))
    install(root, "Bank Statements", "bank_docs.py", "http://127.0.0.1:9236")
    install(root, "Shop Receipts", "shop_receipts.py", None, primary={},
            spouse={"cdp_url": "http://localhost"}, other={"cdp_url": 9236},
            six={"cdp_url": "http://[::1]:9240"}, seven={"cdp_url": "http://[::1]:9241"},
            eight={"cdp_url": "http://[::1]"}, nine={"cdp_url": "ws://[::1]/devtools"})
    assert sign_in(chase / "config.json", 9236) == "Chromium"
    assert "!!" not in launches[0]
    from paperpull_core import ports
    assert ports.findings(ports.installs_in(root)) == {}
    # The colons of an IPv6 address are not a port, which a search for a
    # colon and digits took ::1 for.
    assert ports.port_of("http://[::1]:9240") == 9240
    assert ports.port_of("http://[::1]") is None
    assert ports.port_of("localhost:9236") == 9236


def test_two_people_of_one_install_on_one_port_are_said(tmp_path, launches):
    """config.json copied by hand to config.spouse.json, port and all."""
    root = tmp_path / "PaperPull"
    chase = install(root, "Chase Statements", "chase_docs.py", "http://127.0.0.1:9236",
                    primary=at(9236), spouse=at(9236))
    assert sign_in(chase / "config.json", 9236) == "Chromium"
    said = launches[0]
    assert 'the "spouse" account of Chase Statements (config.spouse.json)' in said
    assert "     %s\n       http://127.0.0.1:9237\n" % (chase / "config.spouse.json") in said


def test_a_second_person_given_a_later_app_s_port_is_said(tmp_path, launches):
    """The clash as add_account makes it. E-ZPass's second person is given
    9274 plus 10, Interactive Brokers' port, before Interactive Brokers is
    set up, and a config copied from its example then names 9284 too."""
    root = tmp_path / "PaperPull"
    ezpass = install(root, "E-ZPass Statements", "ezpassva_docs.py", "http://127.0.0.1:9274",
                     primary=at(9274))
    add_account.make_config(ezpass, "spouse", owner="Jane Doe")
    ibkr = install(root, "Interactive Brokers Statements", "ibkr_docs.py",
                   "http://127.0.0.1:9284", primary=at(9284))
    assert sign_in(ibkr / "config.json", 9284) == "Chromium"
    said = launches[0]
    assert 'the "spouse" account of E-ZPass Statements (config.spouse.json)' in said
    assert "     %s\n       http://127.0.0.1:9285\n" % (ezpass / "config.spouse.json") in said


def test_a_moved_config_is_never_told_a_port_a_shipped_provider_comes_with(pair, shipped,
                                                                          launches):
    """9264 and 9265 belong to providers this copy ships and nobody here has
    set up yet. Told one of them, the person would meet the same clash the
    day that provider is set up."""
    install(shipped, "deli", "deli_receipts.py", "http://127.0.0.1:9264")
    install(shipped, "fuel", "fuel_docs.py", "http://127.0.0.1:9265")
    grocer, card = pair
    assert sign_in(card / "config.json", 9262) == "Chromium"
    assert "     %s\n       http://127.0.0.1:9266\n" % (grocer / "config.spouse.json") \
        in launches[0]


def test_the_shipped_providers_are_read_once_until_one_is_added(pair, shipped, monkeypatch):
    """The panel asks on every page it loads, and reading every shipped
    example each time made its rows late. They are read once, and again
    only when a provider is added to the folder."""
    from paperpull_core import ports
    install(shipped, "deli", "deli_receipts.py", "http://127.0.0.1:9264")
    _, card = pair
    real, read = ports._url_in, []

    def counted(path):
        read.append(path.parent.name)
        return real(path)
    monkeypatch.setattr(ports, "_url_in", counted)
    installs = ports.installs_in(card.parent)
    first = ports.findings(installs, [shipped])
    second = ports.findings(installs, [shipped])
    assert read.count("deli") == 1
    assert first[ports.key_of(card / "config.json")].moves[0][1] == "http://127.0.0.1:9265"
    assert second == first
    install(shipped, "fuel", "fuel_docs.py", "http://127.0.0.1:9265")
    third = ports.findings(installs, [shipped])
    assert read.count("fuel") == 1
    assert third[ports.key_of(card / "config.json")].moves[0][1] == "http://127.0.0.1:9266"


def test_a_config_moved_off_its_own_example_is_told_that_port_again(tmp_path, launches):
    """Plan's example moved to 9296 once Bank had taken 9298, the port Plan
    shipped on, and a Plan set up before then still names 9298. Plan's own
    9296 is free, and is the port a new Plan install takes."""
    root = tmp_path / "PaperPull"
    plan = install(root, "Plan Statements", "plan_docs.py", "http://127.0.0.1:9296",
                   primary=at(9298))
    bank = install(root, "Bank Statements", "bank_docs.py", "http://127.0.0.1:9298",
                   primary=at(9298))
    assert sign_in(bank / "config.json", 9298) == "Chromium"
    assert "     %s\n       http://127.0.0.1:9296\n" % (plan / "config.json") in launches[0]


def test_a_tie_is_told_the_same_way_from_both_sides(tmp_path, launches):
    """Two apps that both shipped on 9298, each set up on its example. Each
    side was told to move itself, to two different ports. Now the first by
    its path keeps the port, and both sides say Beta moves."""
    root = tmp_path / "PaperPull"
    alpha = install(root, "Alpha Statements", "alpha_docs.py", "http://127.0.0.1:9298",
                    primary=at(9298))
    beta = install(root, "Beta Statements", "beta_docs.py", "http://127.0.0.1:9298",
                   primary=at(9298))
    assert sign_in(alpha / "config.json", 9298) == "Chromium"
    assert sign_in(beta / "config.json", 9298) == "Chromium"
    from_alpha, from_beta = launches
    assert "     %s\n       http://127.0.0.1:9299\n" % (beta / "config.json") in from_alpha
    assert "     %s (this config)\n       http://127.0.0.1:9299\n" % (beta / "config.json") \
        in from_beta
    assert str(alpha / "config.json") not in from_alpha.split("comes with.")[1]


def test_three_on_one_port_are_each_told_where_to_go(pair, launches):
    """Card keeps 9262. Grocer's second person and Store's are both on it,
    and both have to move, each to a port of its own."""
    grocer, card = pair
    store = card.parent / "Store Receipts"
    (store / "config.kid.json").write_text(json.dumps(at(9262)), encoding="utf-8")
    assert sign_in(card / "config.json", 9262) == "Chromium"
    said = launches[0]
    assert "!! 2 other configs beside this one name port 9262 too." in said
    assert "give each config below a port of its own" in said
    assert "     %s\n       http://127.0.0.1:9264\n" % (grocer / "config.spouse.json") in said
    assert "     %s\n       http://127.0.0.1:9265\n" % (store / "config.kid.json") in said


def test_three_pairs_are_each_told_a_port_of_their_own(tmp_path, launches):
    """Three second people share a port each with an app set up after them,
    and the same port is the first free one for all three. Told it all
    three, the three would end on one port."""
    root = tmp_path / "PaperPull"
    told = {}
    for folder, script, own, second, later, later_script in (
            ("Grocer Receipts", "grocer_receipts.py", 9252, 9262, "Card Statements", "card_docs.py"),
            ("Pharmacy Receipts", "pharmacy_receipts.py", 9253, 9263, "Phone Bills", "phone_docs.py"),
            ("Fuel Receipts", "fuel_receipts.py", 9254, 9264, "Water Bills", "water_docs.py")):
        first = install(root, folder, script, "http://localhost:%d" % own,
                        primary={"cdp_url": "http://localhost:%d" % own},
                        partner={"cdp_url": "http://localhost:%d" % second})
        install(root, later, later_script, "http://localhost:%d" % second,
                primary={"cdp_url": "http://localhost:%d" % second})
        told[second] = first / "config.partner.json"
    for port, want in zip(sorted(told), (9265, 9266, 9267)):
        assert sign_in(told[port], port) == "Chromium"
        assert "     %s (this config)\n       http://localhost:%d\n" % (told[port], want) \
            in launches[-1]


def test_it_is_said_before_a_browser_already_on_the_port_is_joined(pair, monkeypatch, capsys):
    """The case that mixes two profiles. The other person's browser holds
    the port, and the sign-in opens its page there as before."""
    _, card = pair
    monkeypatch.setattr(browser, "debug_port_holder", lambda port, timeout=1.5: "Chrome/141")
    monkeypatch.setattr(browser, "_open_tab_in", lambda port, url: True)
    assert sign_in(card / "config.json", 9262) == browser.ALREADY_ON_PORT
    said = capsys.readouterr().out
    assert said.index("names port 9262 too") < said.index("already listening on port 9262")


def test_nothing_it_cannot_read_stops_a_sign_in(pair, launches, monkeypatch):
    grocer, card = pair
    (grocer / "config.broken.json").write_text("{not json", encoding="utf-8")
    (grocer / "config.list.json").write_text("[9262]", encoding="utf-8")
    (grocer / "config.folder.json").mkdir()
    # Far larger than any config, so never read, though it names 9262 too.
    (grocer / "config.huge.json").write_text(
        json.dumps(dict(at(9262), padding="x" * (2 << 20))), encoding="utf-8")
    assert sign_in(card / "config.json", 9262) == "Chromium"
    assert "!! Another config beside this one names port 9262 too." in launches[0]
    assert "config.spouse.json" in launches[0] and "config.huge.json" not in launches[0]

    from paperpull_core import ports

    def broken(*a, **kw):
        raise OSError("the folder went away")
    monkeypatch.setattr(ports, "shared_at", broken)
    assert sign_in(card / "config.json", 9262) == "Chromium"


def test_one_file_it_cannot_resolve_silences_nothing_else(pair, launches, monkeypatch):
    """A link that leads to itself cannot be resolved. It is taken as
    written, and what is said of the other configs is still said."""
    grocer, card = pair
    (grocer / "config.strange.json").write_text(json.dumps(at(9262)), encoding="utf-8")
    real = Path.resolve

    def resolve(self, strict=False):
        if self.name == "config.strange.json":
            raise RuntimeError("Symlink loop from %r" % str(self))
        return real(self, strict)
    monkeypatch.setattr(Path, "resolve", resolve)
    assert sign_in(card / "config.json", 9262) == "Chromium"
    said = launches[0]
    assert "2 other configs beside this one name port 9262 too." in said
    assert 'the "spouse" account of Grocer Receipts (config.spouse.json)' in said
    assert 'the "strange" account of Grocer Receipts (config.strange.json)' in said


def test_a_sign_in_with_no_config_read_says_nothing(pair, launches):
    """A sign-in from a test or a tool that read no config. A config read
    by an earlier run in this process is forgotten when the next app binds."""
    _, card = pair
    storage.load_config(card / "config.json")
    storage.bind(storage.spec())
    assert browser.open_signin_browser(card / "p", "9262", SIGN_IN) == "Chromium"
    assert "!!" not in launches[0]


def test_installs_are_found_as_the_launcher_finds_them(tmp_path):
    from paperpull_core import ports
    root = tmp_path / "PaperPull"
    install(root, "b Receipts", "b_receipts.py")
    install(root, "A Docs", "a_docs.py")
    install(root, "Tests Only", "test_x_docs.py")
    install(root, "Hidden", ".x_docs.py")
    install(root, "Not An App", "notes.py")
    (root / "loose_docs.py").write_text("", encoding="utf-8")
    assert ports.installs_in(root) == paperpull.list_apps(root)
    assert [d.name for d in ports.installs_in(root)] == ["A Docs", "b Receipts"]


def test_the_providers_this_copy_ships_are_found(monkeypatch):
    """In a checkout, the repo's own apps. The suite runs on a checkout, so
    the package's and the server's places are not here to find."""
    from paperpull_core import ports
    monkeypatch.undo()
    found = [p.resolve() for p in ports.shipped_folders()]
    assert (REPO / "apps").resolve() in found
    assert len(ports.installs_in(REPO / "apps")) >= 78


def test_every_app_signs_in_through_the_core_with_the_config_it_read():
    """Login is said in the core, so it reaches every app only if every
    app's sign-in goes through open_signin_browser and its config through
    the core's load_config, which remembers the file."""
    apps = paperpull.list_apps(REPO / "apps")
    missing = []
    for app in apps:
        src = paperpull.entry_script(app).read_text(encoding="utf-8")
        shim = (app / "storage.py").read_text(encoding="utf-8")
        if ("browser_launcher.open_signin_browser(" not in src or "load_config(" not in src
                or "from paperpull_core import browser as browser_launcher" not in src
                or "load_config" not in shim or "_core.bind(SPEC)" not in shim):
            missing.append(app.name)
    assert not missing, missing
    assert len(apps) >= 78, len(apps)
