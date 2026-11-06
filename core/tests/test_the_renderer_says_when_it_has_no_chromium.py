"""The receipt renderer says so in plain words when PaperPull's own Chromium
is not on this computer (#131).

Sign-in and almost every app use the Edge or Chrome already on the computer,
so most installs never download Playwright's Chromium. The renderer, which
prints a page in a headless browser of its own, is the one step that always
needs it. It met Playwright's "Executable doesn't exist ... run `playwright
install`", and that went into the purchase's notes as it stood, naming a
command the packaged app does not have and not saying that nothing of the
person's was wrong.

No browser is started here. A stand-in for Playwright's chromium fails the
way Playwright does, so what is read is what the person would be told.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser, receipt_pdf  # noqa: E402

# Playwright 1.64's words for a Chromium that is not on disk
PLAYWRIGHT_MISSING = (
    "BrowserType.launch: Executable doesn't exist at "
    "/Users/x/Library/Caches/ms-playwright/chromium_headless_shell-1248/"
    "chrome-headless-shell-mac-arm64/chrome-headless-shell\n"
    "╔════════════════════════════════════════════════════════════╗\n"
    "║ Looks like Playwright was just installed or updated.       ║\n"
    "║ Please run the following command to download new browsers: ║\n"
    "║     playwright install                                     ║\n"
    "╚════════════════════════════════════════════════════════════╝")


class _Chromium:
    """Fails as asked, and has no build of its own to find on disk."""

    def __init__(self, error):
        self.error = error
        self.executable_path = ""
        self.launched = 0

    def launch(self, **_kw):
        self.launched += 1
        raise self.error


class _Playwright:
    def __init__(self, error):
        self.chromium = _Chromium(error)


def _render(tmp_path, error):
    return receipt_pdf.render_url_headless(
        _Playwright(error), {}, "https://shop.example/receipt", tmp_path / "out.pdf",
        is_safe_url=lambda u: str(u).startswith("https://shop.example/"),
        hosts=("shop.example",))


@pytest.fixture(autouse=True)
def _no_server(monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(browser, "server_refusal", lambda: "")


def test_playwrights_words_for_a_missing_chromium_are_recognised():
    assert browser.is_missing_chromium(Exception(PLAYWRIGHT_MISSING))
    assert browser.is_missing_chromium(RuntimeError("Executable doesn't exist at /x"))
    for other in ("Timeout 30000ms exceeded", "net::ERR_CONNECTION_REFUSED", "", None):
        assert not browser.is_missing_chromium(Exception(other))


def test_the_renderer_with_no_chromium_says_what_is_missing_and_how_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "browser_install_command",
                        lambda: ["/Applications/PaperPull.app/Contents/Resources/python/bin/python3",
                                 "-m", "playwright", "install", "chromium"])
    with pytest.raises(browser.NoOwnChromium) as e:
        _render(tmp_path, Exception(PLAYWRIGHT_MISSING))
    said = str(e.value)
    assert "PaperPull's own copy of Chromium" in said
    assert "Nothing is wrong with your account" in said
    assert "/Applications/PaperPull.app/Contents/Resources/python/bin/python3 -m playwright install chromium" in said
    # Playwright's own words, and the command that means nothing in a package
    assert "Looks like Playwright was just installed" not in said
    assert "Executable doesn't exist" not in said
    assert "╔" not in said
    # The words are one line, since they go into a purchase's notes
    assert "\n" not in said
    # and the original error is not chained to it as a second thing to read
    assert e.value.__cause__ is None and e.value.__suppress_context__
    assert not (tmp_path / "out.pdf").exists()


def test_a_command_with_spaces_in_its_path_is_quoted_so_it_can_be_pasted(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(browser, "browser_install_command",
                        lambda: ["/Users/a b/PaperPull.app/python3", "-m", "playwright",
                                 "install", "chromium"])
    said = browser.missing_chromium_words()
    assert "'/Users/a b/PaperPull.app/python3' -m playwright install chromium" in said
    assert "open Terminal" in said
    assert "run this line" in said


def test_windows_is_told_to_open_a_command_prompt_and_quoted_its_way(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(browser, "browser_install_command",
                        lambda: [r"C:\Users\a b\PaperPull\python\python.exe", "-m", "playwright",
                                 "install", "chromium"])
    said = browser.missing_chromium_words()
    assert "open Command Prompt" in said
    assert r'"C:\Users\a b\PaperPull\python\python.exe" -m playwright install chromium' in said


def test_a_build_that_cannot_download_it_says_so_and_where_to_ask(monkeypatch):
    monkeypatch.setattr(browser, "browser_install_command", lambda: None)
    said = browser.missing_chromium_words()
    assert "cannot download it for you" in said
    assert "github.com/rheeloaded/paperpull/issues" in said
    assert "run this line" not in said


@pytest.mark.parametrize("python", [
    r"C:\Program Files\WindowsApps\Publisher.PaperPull_0.60.2.0_x64__abc123\python\python.exe",
    r"D:\WindowsApps\Publisher.PaperPull_0.60.2.0_x64__abc123\python\python.exe",
    r"c:\program files\windowsapps\Publisher.PaperPull_0.60.2.0_x64__abc123\python\python.exe",
])
def test_the_store_edition_is_not_given_a_line_it_cannot_run(monkeypatch, python):
    """The Store package leaves the terminal command out, and a program in
    its folder that it does not declare will not start from Command Prompt."""
    monkeypatch.delattr(browser.sys, "frozen", raising=False)
    monkeypatch.setattr(browser.sys, "executable", python)
    assert browser.browser_install_command() is None
    said = browser.missing_chromium_words()
    assert "cannot download it for you" in said
    assert "playwright" not in said
    assert "run this line" not in said


@pytest.mark.parametrize("python", [
    r"C:\Users\a\AppData\Local\Microsoft\WindowsApps"
    r"\PythonSoftwareFoundation.Python.3.12_abc123\python.exe",
    r"C:\Users\a\AppData\Local\Microsoft\WindowsApps\python.exe",
    r"C:\dev\WindowsApps\paperpull\gui\.venv\Scripts\python.exe",
])
def test_a_python_that_is_in_no_store_package_keeps_its_line(monkeypatch, python):
    """Windows keeps its app aliases in a folder of the same name, and a
    checkout on the Store's own Python does run from there. Somebody may
    also keep a checkout in a folder called that. Neither is a package."""
    monkeypatch.delattr(browser.sys, "frozen", raising=False)
    monkeypatch.setattr(browser.sys, "executable", python)
    assert browser.browser_install_command() == [python, "-m", "playwright", "install", "chromium"]


def test_the_server_is_told_nothing_of_terminals_or_a_browser_of_its_own(tmp_path, monkeypatch):
    """The container's Chrome is its own and a download there would not
    last, so a command to paste and the Chrome or Edge you already have fit
    nobody there."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setattr(browser, "browser_install_command",
                        lambda: ["/opt/python", "-m", "playwright", "install", "chromium"])
    with pytest.raises(browser.NoOwnChromium) as e:
        _render(tmp_path, Exception(PLAYWRIGHT_MISSING))
    said = str(e.value)
    assert "PaperPull Server" in said
    assert "Nothing is wrong with your account" in said
    assert "was not saved" in said
    assert "github.com/rheeloaded/paperpull/issues" in said
    for not_there in ("Chrome or", "Edge", "Terminal", "Command Prompt", "a terminal",
                      "playwright install", "download", "\n"):
        assert not_there not in said, not_there


def test_the_mac_apps_line_keeps_bytecode_out_of_its_signed_bundle(monkeypatch):
    """A line pasted into Terminal has neither setting the app's own scripts
    export, and a signed bundle that grows files reads as damaged."""
    python = "/Applications/PaperPull.app/Contents/Resources/python/bin/python3"
    monkeypatch.delattr(browser.sys, "frozen", raising=False)
    monkeypatch.setattr(browser.sys, "executable", python)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert browser.browser_install_command() == \
        [python, "-B", "-s", "-m", "playwright", "install", "chromium"]
    assert python + " -B -s -m playwright install chromium" in browser.missing_chromium_words()


@pytest.mark.parametrize("python", [
    "/usr/local/bin/python3",
    "/Applications/Xcode.app/Contents/Developer/usr/bin/python3",
])
def test_a_checkout_on_a_mac_keeps_a_playwright_in_its_own_site_folder(monkeypatch, python):
    """-s would hide a Playwright kept in the person's own site folder, so
    only the app's Python takes it, not one that happens to sit in a bundle."""
    monkeypatch.delattr(browser.sys, "frozen", raising=False)
    monkeypatch.setattr(browser.sys, "executable", python)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert browser.browser_install_command() == \
        [python, "-m", "playwright", "install", "chromium"]


def test_any_other_failure_to_launch_is_passed_on_as_it_was(tmp_path):
    boom = RuntimeError("the machine is out of memory")
    with pytest.raises(RuntimeError) as e:
        _render(tmp_path, boom)
    assert e.value is boom


def test_a_refused_address_still_launches_nothing(tmp_path):
    pw = _Playwright(Exception(PLAYWRIGHT_MISSING))
    with pytest.raises(ValueError):
        receipt_pdf.render_url_headless(
            pw, {}, "https://evil.example/receipt", tmp_path / "out.pdf",
            is_safe_url=lambda u: str(u).startswith("https://shop.example/"),
            hosts=("shop.example",))
    assert pw.chromium.launched == 0
