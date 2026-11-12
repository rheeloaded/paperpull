"""PaperPull Server's pages say what the server does, and keep saying it.

SERVER.md, PRIVACY-SERVER.md and SECURITY-SERVER.md make promises about the
image, and a page that drifts from the code is worse than none. These tests
tie the promises that can be checked to the files that keep them.
"""
import ast
import json
import re
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
import smoke  # noqa: E402
PAGES = ("SERVER.md", "PRIVACY-SERVER.md", "SECURITY-SERVER.md")


def prose(text: str) -> str:
    """A page without its code, fenced or inline."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


@pytest.mark.parametrize("page", PAGES)
def test_the_pages_keep_the_house_punctuation(page):
    text = (REPO / page).read_text(encoding="utf-8")
    assert "—" not in text, "an em dash"
    lines = [line for line in prose(text).splitlines() if ";" in line]
    assert not lines, lines


@pytest.mark.parametrize("page", PAGES)
def test_every_command_they_name_is_in_the_image(page):
    text = (REPO / page).read_text(encoding="utf-8")
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    for name in re.findall(r"/opt/paperpull/server/([\w.]+\.py)", text):
        assert (SERVER / name).is_file(), name
        assert "server/%s" % name in dockerfile, "%s is not copied into the image" % name


def test_the_files_the_setup_names_are_there():
    text = (REPO / "SERVER.md").read_text(encoding="utf-8")
    for rel in re.findall(r"`(server/[\w./-]+)`", text):
        assert (REPO / rel).exists(), rel


def test_a_rented_server_is_warned_about():
    """Bryan's call, a disclaimer and not a block, for the bot checks a
    data center's addresses draw."""
    text = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    assert "Not on a rented server" in text and "data-center addresses" in text
    assert "Robot or human?" in text


def test_what_the_privacy_page_says_is_off_is_off():
    policies = json.loads((SERVER / "chrome-policies.json").read_text(encoding="utf-8"))
    text = " ".join((REPO / "PRIVACY-SERVER.md").read_text(encoding="utf-8").split())
    assert ("Usage statistics, sync, signing in to the browser, search suggestions, "
            "spell checking and translation are switched off by policy") in text
    assert policies["MetricsReportingEnabled"] is False
    assert policies["SyncDisabled"] is True
    assert policies["BrowserSignin"] == 0
    assert policies["SearchSuggestEnabled"] is False
    assert policies["SpellCheckServiceEnabled"] is False
    assert policies["TranslateEnabled"] is False


def panel_setting(name: str):
    """A number set at the top of gui/server_mode.py. Read rather than
    imported, because the Python that runs this suite may not have FastAPI,
    and a check that skips itself there would never be seen to fail."""
    tree = ast.parse((REPO / "gui" / "server_mode.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), "server_mode.py", "eval"), {"__builtins__": {}})
    raise AssertionError("%s is not set in gui/server_mode.py" % name)


def test_what_the_security_page_says_about_waiting_matches_the_panel():
    text = " ".join((REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8").split())
    assert "After five wrong passwords" in text and panel_setting("FREE_TRIES") == 5
    assert "up to a quarter of an hour" in text and panel_setting("LONGEST_WAIT") == 15 * 60
    assert "after eight hours in which the panel's own page asked nothing of it" in text
    assert panel_setting("IDLE_SECONDS") == 8 * 3600
    assert "after 14 days at most" in text and panel_setting("SESSION_SECONDS") == 14 * 86400
    assert "only within 15 minutes of someone being seen at it" in text
    assert "After that it closes, says why" in text
    assert panel_setting("SCREEN_IDLE_SECONDS") == 15 * 60
    setup = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    assert "more than 15 minutes after typing the password or last using the window" in setup
    assert "signs you out after eight hours without use" in setup


def test_the_names_the_https_setup_takes_are_separated_as_caddy_reads_them():
    """Caddy refuses to start on names joined by a comma alone, so the pages
    and the file say spaces, which the panel takes as well."""
    setup = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    https = (SERVER / "compose.https.yaml").read_text(encoding="utf-8")
    assert "more than one separated by spaces" in setup
    assert "# Any names you open PaperPull by as well, separated by spaces" in https
    names = re.search(r'^x-names: &names "([^"]*)"$', https, re.M).group(1)
    assert not re.search(r",\S", names), names


def test_the_https_setup_names_what_compose_https_yaml_holds():
    """The command that copies Caddy's authority out names its container and
    its file, and the volume the pages warn about is the one that holds it."""
    setup = (REPO / "SERVER.md").read_text(encoding="utf-8")
    https = (SERVER / "compose.https.yaml").read_text(encoding="utf-8")
    assert "docker cp paperpull-proxy:%s paperpull-root.crt" % smoke.ROOT_CERT in setup
    assert "container_name: paperpull-proxy" in https and "- proxy-data:/data" in https
    security = (REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8")
    assert "docker volume rm paperpull_proxy-data" in security
    assert "docker volume rm paperpull_profiles" in security
    assert "`proxy-data` volume" in setup and "`proxy-data` volume" in security


@pytest.mark.parametrize("page", ["SECURITY.md", "SECURITY-SERVER.md"])
def test_both_security_pages_say_what_to_do_when_something_may_be_exposed(page):
    text = (REPO / page).read_text(encoding="utf-8")
    assert "## If something may have been exposed" in text
    assert "**How security fixes are announced.**" in text
    assert "under Security in [CHANGELOG.md](CHANGELOG.md)" in " ".join(text.split())
    assert "## Reporting" in text


def test_what_the_security_page_says_about_the_password_matches_the_panel():
    text = " ".join((REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8").split())
    assert "(n=2^14, r=8, p=5)" in text and panel_setting("SCRYPT") == {"n": 2 ** 14, "r": 8, "p": 5}
    assert "two at a time at most" in text and panel_setting("HASHES_AT_ONCE") == 2
    assert "longer than 8 KiB" in text and panel_setting("FORM_LIMIT") == 8 * 1024
    assert "`__Host-paperpull_session`" in text
    assert panel_setting("SECURE_SESSION_COOKIE") == "__Host-paperpull_session"


def test_what_the_security_page_says_about_the_ukg_address_matches_the_app():
    """The page names the domains a UKG address may be on, and UKG's AppSpec
    is what a run is held to."""
    text = " ".join((REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8").split())
    tree = ast.parse((REPO / "apps" / "ukg" / "storage.py").read_text(encoding="utf-8"))
    declared = [ast.literal_eval(kw.value) for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AppSpec"
                for kw in node.keywords if kw.arg == "url_settings"]
    assert declared == [{"base_url": ("ultipro.com", "saashr.com")}]
    assert "UKG's own domains, `ultipro.com` or `saashr.com`" in text


def test_the_names_the_setup_says_the_panel_answers_to_are_the_panels():
    """A name the page promises and the panel refuses locks a person out of
    their own server, and one the panel takes that the page leaves out is a
    name nobody checked."""
    text = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    said = text[text.index("The panel answers to the server's address"):]
    said = said[:said.index("separated by commas")]
    assert set(re.findall(r"`(\.[a-z.]+)`", said)) == set(panel_setting("LOCAL_SUFFIXES"))
    assert "one without a dot such as `nas`" in said and "`PAPERPULL_HOSTS`" in said
    compose = (SERVER / "compose.yaml").read_text(encoding="utf-8")
    assert '# PAPERPULL_HOSTS: "' in compose


def test_the_hosts_only_setting_the_pages_name_is_the_one_the_panel_reads():
    """A setting the guide names and the panel never reads, or a value it
    tells a person to write that the panel takes for no, leaves a server
    answering names its owner believes it refuses."""
    code = (REPO / "gui" / "server_mode.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PAPERPULL_HOSTS_ONLY")' in code
    assert "1" in panel_setting("HOSTS_ONLY_ON")
    server_page = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    assert "set `PAPERPULL_HOSTS_ONLY` to `1`" in server_page
    security_page = " ".join((REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8").split())
    assert "`PAPERPULL_HOSTS_ONLY` set to `1`" in security_page
    for compose in ("compose.yaml", "compose.https.yaml"):
        assert '# PAPERPULL_HOSTS_ONLY: "1"' in (SERVER / compose).read_text(encoding="utf-8"), compose


@pytest.mark.parametrize("page, server_page", [
    ("PRIVACY.md", "PRIVACY-SERVER.md"),
    ("SECURITY.md", "SECURITY-SERVER.md"),
    ("README.md", "SERVER.md"),
])
def test_the_desktop_pages_point_to_the_servers(page, server_page):
    assert "(%s)" % server_page in (REPO / page).read_text(encoding="utf-8")


def test_the_places_the_sandbox_check_points_to_are_there():
    """The container's log, the panel, the self-test and a sign-in all say
    why Chrome has no sandbox on a host that cannot give it one, and name
    where SERVER.md says what to do (#110). A name that is not there leaves
    the person at the black screen they started from."""
    from paperpull_core import host_sandbox
    text = (REPO / "SERVER.md").read_text(encoding="utf-8")
    assert "\n### On Synology\n" in text
    assert host_sandbox.SECTION == '"On Synology" in SERVER.md'
    assert "- **Chrome does not start.**" in text
    assert host_sandbox.PROFILE_SECTION == '"Chrome does not start" in SERVER.md'
    assert "Synology should work the same way" not in text
    flat = " ".join(text.split())
    assert "starts with `[sandbox]`" in flat and "self-test's `sandbox` line" in flat


def test_the_update_steps_the_panel_gives_are_the_pages():
    """The server's update check gives the steps of "Updating" in SERVER.md
    with the new version filled in, and the anchor it links to is that
    heading's. Either drifting from the other sends somebody to the wrong
    command."""
    text = (REPO / "SERVER.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    js = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    steps = js[js.index("function updServerSteps(v)"):]
    steps = steps[:steps.index("\n}\n")]
    assert "\n## Updating, backing up and removing\n" in text
    assert "SERVER.md#updating-backing-up-and-removing" in steps
    for command in ("docker compose pull", "docker compose up -d", "-f compose.https.yaml"):
        assert "`%s`" % command in flat and "<code>%s</code>" % command in steps, command
    assert "the panel gives these same steps" in flat
    image = re.search(r"^\s+image: (ghcr\.io/[\w/-]+):\d+\.\d+\.\d+$",
                      (SERVER / "compose.yaml").read_text(encoding="utf-8"), re.M).group(1)
    assert "const SERVER_IMAGE = '%s';" % image in js
