"""Every app's guards, checked in one place.

A repo-wide review found the guards had each drifted their own way. Six apps
defined a guard and never called it, one called it with a hardcoded string so
it always passed, seventeen had no host check at all, and every single one let
settings controls through because only bare verb stems were matched.

Testing this per app let that happen, because each app's tests only ever knew
about that app. These run across all of them at once, so a new provider cannot
quietly ship without the same protection.
"""
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if (d / ("%s_site.py" % d.name)).exists())

# Controls that COMMIT something. None of these may ever be clickable.
DANGEROUS = [
    "Save Changes", "Save Settings", "Update Settings", "Change Address",
    "Edit Preferences", "Document Removal", "Loss Mitigation Application",
    "Manage AutoPay", "Turn off", "Opt Out", "Update Beneficiary",
    "Place Order", "Rebalance", "Liquidate", "Buy", "Sell",
]

# Shapes a URL guard must refuse. `{h}` is the app's own allowed host.
HOSTILE_URLS = [
    "https://evil.test/statement.pdf",
    "https://evil.test/x?doc=statement",
    "http://{h}/statement.pdf",
    "https://{h}.evil.test/statement.pdf",
    "https://{h}@evil.test/statement.pdf",
    "//evil.test/statement.pdf",
    "javascript:alert(1)",
    "",
]


def _site(app_dir):
    for name in [m for m in sys.modules if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app_dir))
    try:
        return importlib.import_module("%s_site" % app_dir.name)
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_app_will_click_a_control_that_commits_something(app):
    site = _site(app)
    check = getattr(site, "is_safe_control", None)
    if check is None:
        # Receipt apps guard with the blocklist inline instead, because they
        # must still click pagination ("Load more"), which a document-word
        # allowlist would refuse.
        blocked = [l for l in DANGEROUS if not site.FORBIDDEN_CONTROL_RE.search(l)]
        assert not blocked, "%s would click: %s" % (app.name, blocked)
        return
    clickable = [l for l in DANGEROUS if check(l)]
    assert not clickable, "%s would click: %s" % (app.name, clickable)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_app_has_a_url_guard_that_refuses_other_hosts(app):
    site = _site(app)
    is_safe_url = getattr(site, "is_safe_url", None)
    assert is_safe_url is not None, "%s has no URL guard" % app.name
    hosts = sorted(getattr(site, "ALLOWED_HOSTS", []))
    h = hosts[0] if hosts else None
    if h:
        assert is_safe_url("https://%s/a/b.pdf" % h), \
            "%s refuses its own host" % app.name
    for shape in HOSTILE_URLS:
        url = shape.format(h=h) if h else shape
        assert not is_safe_url(url), "%s accepts %r" % (app.name, url)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_guard_that_exists_is_actually_reachable(app):
    """One app called its guard with a hardcoded string, so it always returned
    True and gated nothing. A guard nobody calls with real input is decoration.
    """
    src = (app / ("%s_site.py" % app.name)).read_text(encoding="utf-8")
    if "def is_safe_control" not in src:
        return
    calls = [ln.strip() for ln in src.splitlines()
             if "is_safe_control(" in ln
             and "def " not in ln
             and not ln.strip().startswith("#")]  # comments may quote the old bug
    for call in calls:
        assert 'is_safe_control("' not in call.replace(" ", ""), \
            "%s calls its guard with a literal, so it gates nothing: %s" % (
                app.name, call)


# -- a failed capture must not leave a convincing empty file ----------------

SAVE_AS_APPS = [d for d in APPS
                if "save_as" in (d / ("%s_site.py" % d.name)).read_text(encoding="utf-8")]


@pytest.mark.parametrize("app", SAVE_AS_APPS, ids=lambda d: d.name)
def test_a_failed_capture_removes_the_file_it_could_not_fill(app):
    """Playwright's save_as creates the target before the bytes arrive, so a
    capture that fails leaves a ZERO BYTE file carrying a perfectly convincing
    statement name. Five of those sat in a real Statements folder looking like
    downloads until they were opened, and the run had already reported them as
    needing review rather than as absent."""
    src = (app / ("%s_docs.py" % app.name)).read_text(encoding="utf-8")
    assert "st_size == 0" in src, (
        "%s uses save_as but never removes an unfilled file" % app.name)
    assert "out_path.unlink()" in src


def test_the_cleanup_actually_removes_an_empty_file(tmp_path):
    """The condition itself, exercised rather than asserted."""
    f = tmp_path / "2026-01-01 Statement.pdf"
    for content, should_go in ((b"", True), (b"<html>nope", True), (b"%PDF-1.7 ok", False)):
        f.write_bytes(content)
        if f.exists() and (f.stat().st_size == 0 or f.read_bytes()[:5] != b"%PDF-"):
            f.unlink()
        assert f.exists() != should_go
        if f.exists():
            f.unlink()


# -- a signed-in browser profile must never be committable ------------------

def _configured_profile_dir(app):
    """The profile folder this app's own config names, not a guessed one. An
    app that picks a different name still has to be covered."""
    cfg = app / "config.example.json"
    if not cfg.exists():
        return None
    import json
    try:
        return (json.loads(cfg.read_text(encoding="utf-8")) or {}).get("profile_dir")
    except ValueError:
        return None


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_browser_profile_could_never_be_committed(app):
    """A browser profile holds live session cookies for whatever the user
    signed into, which here means banks, an insurer, a payroll system and a
    government pay system. The repo is public.

    Three lines in .gitignore are the only thing standing between that and a
    public commit, and nothing checked they still covered every app. A new
    provider's author has no reason to know the convention exists, so the
    build checks it instead of trusting them to.
    """
    import subprocess
    configured = _configured_profile_dir(app)
    names = {"%s-browser-profile" % app.name}
    if configured:
        names.add(configured.strip("./").strip("/"))

    for name in names:
        for leaf in ("Default/Cookies", "Local State",
                     "Default/Network/Cookies", "Default/Login Data"):
            rel = "apps/%s/%s/%s" % (app.name, name, leaf)
            r = subprocess.run(["git", "check-ignore", "-q", rel],
                               cwd=REPO, capture_output=True)
            assert r.returncode == 0, (
                "%s is NOT gitignored, so a signed-in profile could be "
                "committed to a public repo" % rel)


# -- the big download is offered, not assumed -------------------------------

def test_no_setup_script_downloads_a_browser():
    """The bundled Chromium is 416 MB against roughly 60 MB for everything
    else, and almost nobody needs it, because any Chromium-based browser can be
    driven the same way. Downloading it during setup made every install pay for
    something most people already have, and made setup fail on a bad connection
    at the worst possible moment."""
    offenders = []
    for pattern in ("setup-all.bat", "setup-all.command",
                    "apps/*/setup.bat", "apps/*/setup.command",
                    "tools/make_unix_launchers.py"):
        for f in sorted(REPO.glob(pattern)):
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if "playwright install" in line and not line.lstrip().startswith(
                        ("#", "rem ", "REM ", "::")):
                    offenders.append("%s:%d" % (f.relative_to(REPO), i))
    assert not offenders, "setup still downloads a browser: " + ", ".join(offenders)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_lets_the_user_choose_which_browser(app):
    """The choice is a config setting, so somebody on a managed machine can
    keep this away from their own browser and somebody on a slow connection can
    refuse the download. An app that ignores it silently overrides them."""
    import ast
    calls = 0
    for py in sorted(app.glob("*.py")):
        if "test" in py.name:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name != "open_signin_browser":
                continue
            calls += 1
            assert "mode" in {k.arg for k in node.keywords}, (
                "%s:%d ignores the browser setting" % (py.name, node.lineno))
    if calls == 0:
        # target drives Playwright's own Chromium directly rather than
        # attaching to a browser the user launched, so it has no choice to
        # offer. It must still ask before a 400 MB download.
        src = "\n".join(p.read_text(encoding="utf-8-sig")
                        for p in app.glob("*.py") if "test" not in p.name)
        assert "fetch_bundled_chromium" in src, (
            "%s neither offers the browser choice nor asks before downloading"
            % app.name)


# -- a click on "any link in the row" is a click on Pay ----------------------

# A guard the app defines and calls somewhere is not the same as a guard that
# stands between a data-chosen element and the click. One provider arrived
# with a working is_safe_control, called it only in its diagnose dump, and
# fetched each bill by clicking the first link or button in the row when the
# labeled one was not found. A bill row also holds Pay. The reachability
# test above passed it, because the guard was called with real text.
#
# What is caught here is the shape of that mistake, read from the source.
# A function that clicks something, and reaches for elements by a selector
# that names no control in particular (a bare tag, a bare role, a wildcard),
# must also consult a guard. A selector that names its target ("#getmybill",
# "button[aria-label*='View']", a role with a name) chose the control itself,
# and is left alone.

# is_safe_url is deliberately not on this list. It guards where a fetch goes,
# not what a click lands on, and the function that got through called it.
_GUARD_NAMES = re.compile(
    r"\b(is_safe_(?!url\b)\w+|is_\w*_control|pick_document_control|is_page_picker|"
    r"is_page_option|\w*_CONTROL_RE|FORBIDDEN\w*)\b")
# Selector entries that could land on any control at all.
_BARE_SELECTORS = {"a", "button", "*", "[role='button']", '[role="button"]',
                   "input", "a[href]", "[type='submit']", '[type="submit"]'}
_SELECTOR_METHODS = {"locator", "query_selector", "query_selector_all"}
# Roles that commit something when clicked. An unnamed get_by_role on one of
# these is "every button on the page".
_ACTING_ROLES = {"button", "link", "menuitem", "checkbox", "radio", "switch"}


def unguarded_broad_clicks(source: str):
    """Functions that click, reach for controls by a selector that names none,
    and never consult a guard. Returns [(function, selector), ...]."""
    import ast
    tree = ast.parse(source)
    out = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        body = ast.get_source_segment(source, fn) or ""
        if ".click(" not in body or _GUARD_NAMES.search(body):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            method = node.func.attr
            first = node.args[0].value if (node.args and isinstance(node.args[0], ast.Constant)
                                           and isinstance(node.args[0].value, str)) else None
            if method in _SELECTOR_METHODS and first is not None:
                parts = [p.strip() for p in first.split(",")]
                if any(p in _BARE_SELECTORS for p in parts):
                    out.append((fn.name, first))
            elif (method == "get_by_role" and first in _ACTING_ROLES
                  and not any(k.arg == "name" for k in node.keywords)):
                out.append((fn.name, "get_by_role(%r) with no name" % first))
    return out


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_function_clicks_whatever_a_bare_selector_finds(app):
    for py in sorted(app.glob("*.py")):
        if "test" in py.name:
            continue
        found = unguarded_broad_clicks(py.read_text(encoding="utf-8-sig"))
        assert not found, (
            "%s/%s clicks what a bare selector finds without a guard: %s"
            % (app.name, py.name, found))


def test_the_bare_selector_check_catches_the_shape_that_got_through():
    """The PG&E fetch as it arrived, reduced to its shape. If this ever stops
    firing, the check above is decoration."""
    arrived = '''
def download_bill(page, doc, out_path):
    rows = page.query_selector_all("table tbody tr, [role='row']")
    link = rows[doc["row_index"]].query_selector(
        "a:has-text('View Bill PDF'), button:has-text('View Bill PDF'), a, button")
    href = link.get_attribute("href") or ""
    if href and is_safe_url(href):
        return page.request.get(href)
    link.click(force=True)
'''
    assert unguarded_broad_clicks(arrived) == [
        ("download_bill",
         "a:has-text('View Bill PDF'), button:has-text('View Bill PDF'), a, button")]

    # The same function with the guard in the path is left alone.
    fixed = arrived.replace("link.click(force=True)",
                            "if is_safe_control(link.inner_text()):\n        link.click()")
    assert unguarded_broad_clicks(fixed) == []

    # A selector that names its control is not broad.
    named = '''
def open_history(page):
    page.locator("#getmybill").click()
    page.get_by_role("button", name=re.compile("continue session", re.I)).click()
    page.locator("button[aria-label*='View']").first.click()
'''
    assert unguarded_broad_clicks(named) == []

    # Every button on the page, unnamed, is broad.
    every = '''
def press_something(page):
    page.get_by_role("button").first.click()
'''
    assert unguarded_broad_clicks(every) == [
        ("press_something", "get_by_role('button') with no name")]
