"""Every app's guards, checked in one place.

A repo-wide review found the guards had each drifted their own way. Six apps
defined a guard and never called it, one called it with a hardcoded string so
it always passed, seventeen had no host check at all, and every single one let
settings controls through because only bare verb stems were matched.

Testing this per app let that happen, because each app's tests only ever knew
about that app. These run across all of them at once, so a new provider cannot
quietly ship without the same protection.
"""
import functools
import importlib
import re
import subprocess
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
    # A dismiss press once took any of these for a Close (review of 0.45.0).
    "Close Account", "Close my account", "Sign Out", "Log out", "Logout",
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


# Labels an app's guard may take, one of which every guard does.
_ACCEPTED = ["Download statement", "Download PDF", "View statement", "View PDF", "Download",
             "View Receipt", "Download Bill", "Download 1098-E", "View order details",
             "Purchase history",
             "Download document with subject Repayment Notice",
             "View Printable Statement"]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_control_with_one_label_the_guard_refuses_is_refused_whatever_its_others_say(app):
    """pressing.press_once hands the guard every label a control carries,
    its text, aria-label and title, joined by " | ". Nelnet took the part
    of a label after " with subject " off as the document's own title, so
    everything after it, the labels joined on included, went unread, and
    "Download document with subject Notice | Make a payment" passed (review
    of 0.45.0). A label the guard refuses alone is refused beside one it
    takes, on either side."""
    site = _site(app)
    check = getattr(site, "is_safe_control", None)
    if check is None:
        return
    accepted = [label for label in _ACCEPTED if check(label)]
    assert accepted, "%s takes none of %s, so this asks nothing of it" % (app.name, _ACCEPTED)
    joined = ["%s | %s" % pair for ok in accepted for d in DANGEROUS for pair in ((ok, d), (d, ok))]
    clickable = [label for label in joined if check(label)]
    assert not clickable, "%s would click: %s" % (app.name, clickable[:6])


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


def _profile_files(app):
    """The files of a signed-in profile, under each name this app's profile
    folder can have."""
    configured = _configured_profile_dir(app)
    names = {"%s-browser-profile" % app.name}
    if configured:
        names.add(configured.strip("./").strip("/"))
    return ["apps/%s/%s/%s" % (app.name, name, leaf) for name in sorted(names)
            for leaf in ("Default/Cookies", "Local State",
                         "Default/Network/Cookies", "Default/Login Data")]


@functools.lru_cache(maxsize=1)
def _gitignored() -> frozenset:
    """Which of every app's profile files git ignores, asked of one git.
    A git for each file, 460 of them, took 41 seconds of the core suite on
    Windows. git names each ignored path as it was given, and only those."""
    asked = [rel for app in APPS for rel in _profile_files(app)]
    r = subprocess.run(["git", "check-ignore", "-z", "--stdin"], cwd=REPO,
                       input="".join(rel + "\0" for rel in asked).encode("utf-8"),
                       capture_output=True)
    # 1 is git's answer when it ignores none of them, anything else an error.
    assert r.returncode in (0, 1), r.stderr.decode("utf-8", "replace")
    return frozenset(r.stdout.decode("utf-8").split("\0")) - {""}


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
    for rel in _profile_files(app):
        assert rel in _gitignored(), (
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


# -- a guard an app defines is a guard its run asks ---------------------------

# Best Buy and M&T each defined is_safe_control() and never called it. Best
# Buy pressed its year menu with no guard at all and M&T its year headings
# after the blocklist alone, and SECURITY.md's audit for 0.54.0 found it by
# reading every app. The reachability test above passed both, because it
# only looks at the calls there are. Here every guard an app defines must be
# asked on a path a run takes, from a command a run starts with (every
# cmd_ but cmd_diagnose, main, and what a module names outside its
# functions, an AppSpec say) through the functions each calls. A function
# nothing calls is no path, and a use in a survey, a page summary or the
# Diagnose command does not count, nor one in a function only they reach.

# The functions that report on a page rather than fetch from it, each by its
# whole name as the apps have it, so a run's own function that happens to
# say "survey", Best Buy's hide_survey, Wells Fargo's _survey or a new
# survey_years, is never taken for one. A run reaches only cmd_diagnose
# (main's own call) and _page_summary (a failure file's) among them.
_REPORT_FN = re.compile(
    r"^(?:cmd_diagnose|_page_summary|_link_summary|_control_survey|survey|"
    r"survey_history_page|survey_receipt_page|_survey_vendor_button)$")
# Names that hold a control to a list of labels. FORBIDDEN_CONTROL_RE alone
# is a blocklist, which lets anything it does not name through, so it is not
# one of them, and is_safe_url guards where a fetch goes, not a press.
_ALLOWLIST_NAMES = {"is_safe_control", "SAFE_DOC_CONTROL_RE", "SAFE_DOC_CONTROL_RES"}

# Apps that define a guard and click nothing during a run, SECURITY.md's
# third list. Amazon defines no guard, so it is not here, and Gap only its
# document allowlist.
CLICK_NOTHING = {
    "affirm", "anthem", "apple", "citi", "ezpassva", "fedex", "fidelity", "gap", "github",
    "homedepot", "invest529", "irs", "kroger", "lowes", "myecp", "mypay", "netbenefits",
    "optum", "paylocity", "sdge", "stripe", "tsp", "tualatin", "uber", "ukg", "ups",
}
# Apps that press only controls they find by a selector or by words written
# in the app, and keep is_safe_control() for Diagnose, SECURITY.md's second
# list. Target and Walmart define no guard. This list may only shrink, which
# test_the_diagnose_only_list_only_shrinks holds it to.
GUARD_FOR_DIAGNOSE_ONLY = {
    "amex", "capitalone", "navyfederal", "robinhood", "schwab", "usaa", "verizon",
    "wealthfront",
}
# The list as it stood when the census came in, for 0.55.0. Never added to.
_DIAGNOSE_ONLY_WHEN_THE_CENSUS_CAME = frozenset({
    "amex", "capitalone", "navyfederal", "robinhood", "schwab", "usaa", "verizon",
    "wealthfront",
})


def _locals(fn) -> set:
    """The names a function binds itself, its arguments and what it
    assigns, so a variable named like a function is not taken for a call."""
    import ast
    args = fn.args
    out = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    out |= {a.arg for a in (args.vararg, args.kwarg) if a}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
    return out


def _functions(source: str, stems=()):
    """{name: the names its body refers to} for every function in `source`,
    nested ones under their own name as well as inside the one around them.

    A name counts when it is no name the function binds itself, and an
    attribute only on self, cls or app, or on a module of the app's own,
    `stems`, as imported here, so re.search is no call to a function named
    search."""
    import ast
    tree = ast.parse(source)
    own = {"self", "cls", "app"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            own.update(a.asname or a.name for a in node.names if a.name in stems)
    out = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seen = out.setdefault(fn.name, set())
            bound = _locals(fn)
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                        and node.id not in bound:
                    seen.add(node.id)
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                        and node.value.id in own:
                    seen.add(node.attr)
    return out


def _press_guards(site_source: str) -> set:
    """The guards a site module defines. is_safe_control, every member of
    PRESS_GUARDS, the document allowlist itself, and every is_ function that
    asks one of those or the blocklist, directly or through a helper, such
    as Bilt's is_view_statements or Venmo's is_show_more."""
    import ast
    tree = ast.parse(site_source)
    fns = _functions(site_source)
    guards = {n for n in _ALLOWLIST_NAMES if n in fns or re.search(r"^%s\s*=" % n, site_source, re.M)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PRESS_GUARDS" for t in node.targets):
            guards.update(e.id for e in ast.walk(node.value) if isinstance(e, ast.Name))
    refusing = {"FORBIDDEN_CONTROL_RE"} | guards
    while True:
        more = {name for name, refs in fns.items() if refs & refusing} - refusing
        if not more:
            break
        refusing |= more
    guards.update(name for name in refusing
                  if name.startswith("is_") and name != "is_safe_url" and name in fns)
    return guards


def _modules(app) -> dict:
    return {py.stem: py.read_text(encoding="utf-8-sig")
            for py in sorted(app.glob("*.py")) if "test" not in py.name}


def _refs(modules: dict) -> dict:
    """{function: the names its body refers to}, over every module."""
    refs = {}
    for fns in modules.values():
        for name, seen in fns.items():
            refs.setdefault(name, set()).update(seen)
    return refs


def _by_hand(modules: dict):
    """({stem: {function: names}}, the reporting functions and every one
    only they call). Everything else counts as a run's, a function nothing
    calls included, which is the careful side for a census of presses."""
    modules = {stem: _functions(source, set(modules)) for stem, source in modules.items()}
    refs = _refs(modules)
    callers = {}
    for name, seen in refs.items():
        for other in seen - {name}:
            callers.setdefault(other, set()).add(name)
    by_hand = {name for name in refs if _REPORT_FN.match(name)}
    while True:
        more = {name for name in refs if name not in by_hand and callers.get(name)
                and callers[name] <= by_hand}
        if not more:
            break
        by_hand |= more
    return modules, by_hand


def _outside_functions(source: str, stems=()) -> set:
    """The names a module refers to outside its functions, an AppSpec's
    hooks or a table of commands, say, an attribute only on a module of the
    app's own."""
    import ast
    tree = ast.parse(source)
    own = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            own.update(a.asname or a.name for a in node.names if a.name in stems)
    out = set()
    todo = list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in own:
            out.add(node.attr)
        todo.extend(ast.iter_child_nodes(node))
    return out


def run_reaches(sources: dict) -> set:
    """The functions a run can reach, from every cmd_ but cmd_diagnose,
    main, and what the modules name outside their functions, through the
    functions each calls, never into a reporting one. A function nothing
    reaches, dead code, is not among them, which is the careful side for a
    census of guards."""
    stems = set(sources)
    modules = {stem: _functions(source, stems) for stem, source in sources.items()}
    refs = _refs(modules)
    roots = {name for name in refs if name.startswith("cmd_") or name == "main"}
    for source in sources.values():
        roots |= _outside_functions(source, stems) & set(refs)
    todo = [name for name in roots if not _REPORT_FN.match(name)]
    reached = set()
    while todo:
        name = todo.pop()
        if name in reached:
            continue
        reached.add(name)
        todo.extend(n for n in refs.get(name, ()) if n in refs and n not in reached
                    and not _REPORT_FN.match(n))
    return reached


def guards_asked_in_a_run(app) -> list:
    """["module:function", ...] for each function of `app` that asks one of
    its site module's guards on a path a run takes. Empty for an app that
    defines no guard."""
    sources = _modules(app)
    guards = _press_guards(sources["%s_site" % app.name])
    if not guards:
        return []
    reached = run_reaches(sources)
    modules = {stem: _functions(source, set(sources)) for stem, source in sources.items()}
    return sorted("%s:%s" % (stem, name) for stem, fns in modules.items()
                  for name, seen in fns.items()
                  if name in reached and name not in guards and seen & guards)


def _defines_a_guard(app) -> bool:
    return bool(_press_guards((app / ("%s_site.py" % app.name)).read_text(encoding="utf-8-sig")))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_guard_an_app_defines_is_asked_in_its_run(app):
    if not _defines_a_guard(app):
        return
    asked = guards_asked_in_a_run(app)
    if app.name in CLICK_NOTHING or app.name in GUARD_FOR_DIAGNOSE_ONLY:
        assert not asked, (
            "%s asks a guard in a run now (%s), so take it off its list here and move it "
            "to the right list in SECURITY.md" % (app.name, ", ".join(asked[:4])))
        return
    assert asked, (
        "%s defines a guard and asks it only in a survey or Diagnose, if at all, so "
        "whatever its run presses is held to no allowlist" % app.name)


# Playwright's presses, the core's, and a press run inside the page.
_PRESS_CALLS = {"click", "dblclick", "tap", "check", "set_checked", "select_option",
                "dispatch_event", "press", "press_once"}


def presses_in_a_run(app) -> list:
    """["function:what", ...] for each press `app` makes outside a survey or
    Diagnose."""
    import ast
    sources = _modules(app)
    _, by_hand = _by_hand(sources)
    out = set()
    for source in sources.values():
        for fn in ast.walk(ast.parse(source)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name in by_hand:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in _PRESS_CALLS):
                    out.add("%s:%s" % (fn.name, node.func.attr))
                elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                      and ".click()" in node.value):
                    out.add("%s:click in the page" % fn.name)
    return sorted(out)


@pytest.mark.parametrize("app", sorted(CLICK_NOTHING | {"amazon"}))
def test_an_app_said_to_click_nothing_presses_nothing_in_its_run(app):
    """The third list is what lets an app go without a guard in its run,
    so an app on it that starts to press something has to leave it."""
    found = presses_in_a_run(REPO / "apps" / app)
    assert not found, "%s presses in a run: %s" % (app, found[:6])


def test_the_press_census_sees_a_press(tmp_path):
    """A press in a run is seen, one made inside the page too, and one in a
    survey is not. If this stops firing, the test above is decoration."""
    app = tmp_path / "shop"
    app.mkdir()
    (app / "shop_site.py").write_text('''
def survey(page):
    page.locator("a").first.click()

def pick_year(page, year):
    page.locator("#menu").click()

def show_all(page):
    page.evaluate("() => document.querySelector('#more').click()")
''', encoding="utf-8")
    assert presses_in_a_run(app) == ["pick_year:click", "show_all:click in the page"]


def test_the_diagnose_only_list_only_shrinks():
    """An app off it presses through a guard. One put on it would be let
    off asking a guard it defines, which is the hole the census closed."""
    assert GUARD_FOR_DIAGNOSE_ONLY <= _DIAGNOSE_ONLY_WHEN_THE_CENSUS_CAME


def test_every_app_on_the_lists_here_is_an_app_with_a_guard():
    """A name that is no app, or an app without a guard, would hold nothing."""
    with_guard = {a.name for a in APPS if _defines_a_guard(a)}
    assert not (CLICK_NOTHING | GUARD_FOR_DIAGNOSE_ONLY) - with_guard
    assert not CLICK_NOTHING & GUARD_FOR_DIAGNOSE_ONLY


def test_the_run_guard_census_catches_a_guard_asked_only_by_hand(tmp_path):
    """The shape Best Buy and M&T had, a guard defined, asked by a survey
    and by Diagnose, and a run that presses without it. If this stops
    firing, the census above is decoration."""
    app = tmp_path / "shop"
    app.mkdir()
    (app / "shop_site.py").write_text('''
import re
FORBIDDEN_CONTROL_RE = re.compile("pay")
SAFE_DOC_CONTROL_RE = re.compile("year")

def is_safe_control(name):
    return not FORBIDDEN_CONTROL_RE.search(name) and bool(SAFE_DOC_CONTROL_RE.search(name))

def _verdicts(labels):
    return [is_safe_control(l) for l in labels]

def survey(page):
    return _verdicts(["a", "b"])

def pick_year(page, year):
    page.locator("#menu").click()
''', encoding="utf-8")
    (app / "shop_docs.py").write_text('''
import shop_site as site

def cmd_diagnose(page):
    return site.is_safe_control("x")

def cmd_run(page):
    site.pick_year(page, "2025")
''', encoding="utf-8")
    assert guards_asked_in_a_run(app) == []

    # A function nothing calls asking the guard is dead code, no run.
    site = (app / "shop_site.py").read_text(encoding="utf-8")
    (app / "shop_site.py").write_text(site + '''
def pick_year_carefully(page, year):
    if is_safe_control(page.locator("#menu").inner_text()):
        page.locator("#menu").click()
''', encoding="utf-8")
    assert guards_asked_in_a_run(app) == []

    # A run's own function whose name says survey is still the run's.
    (app / "shop_site.py").write_text(site + '''
def hide_survey(page):
    if is_safe_control(page.locator("#menu").inner_text()):
        page.locator("#menu").click()
''', encoding="utf-8")
    docs = (app / "shop_docs.py").read_text(encoding="utf-8")
    (app / "shop_docs.py").write_text(docs.replace(
        'site.pick_year(page, "2025")', 'site.hide_survey(page)'), encoding="utf-8")
    assert guards_asked_in_a_run(app) == ["shop_site:hide_survey"]
    (app / "shop_docs.py").write_text(docs, encoding="utf-8")
    (app / "shop_site.py").write_text(site, encoding="utf-8")

    # The same press, asked of the guard first, is a run that asks it.
    site = (app / "shop_site.py").read_text(encoding="utf-8")
    (app / "shop_site.py").write_text(site.replace(
        '    page.locator("#menu").click()',
        '    if is_safe_control(page.locator("#menu").inner_text()):\n'
        '        page.locator("#menu").click()'), encoding="utf-8")
    assert guards_asked_in_a_run(app) == ["shop_site:pick_year"]

    # A guard of its own for the one control counts the same way.
    (app / "shop_site.py").write_text(site.replace(
        '    page.locator("#menu").click()',
        '    if is_year_menu(page.locator("#menu").inner_text()):\n'
        '        page.locator("#menu").click()') + '''
def _refused(name):
    return bool(FORBIDDEN_CONTROL_RE.search(name))

def is_year_menu(name):
    return not _refused(name) and name == "Past 3 Years"
''', encoding="utf-8")
    assert guards_asked_in_a_run(app) == ["shop_site:pick_year"]


def test_the_census_ties_a_call_to_what_it_calls_not_to_a_name(tmp_path):
    """Found by review. re.search reached a dead function named search, a
    variable named survey reached the function survey, and a run's own
    function named survey_years was excused as a report."""
    app = tmp_path / "shop"
    app.mkdir()
    (app / "shop_site.py").write_text('''
import re
FORBIDDEN_CONTROL_RE = re.compile("pay")
SAFE_DOC_CONTROL_RE = re.compile("year")

def is_safe_control(name):
    return not FORBIDDEN_CONTROL_RE.search(name) and bool(SAFE_DOC_CONTROL_RE.search(name))

def search(page):
    if is_safe_control(page.locator("#menu").inner_text()):
        page.locator("#menu").click()

def survey(page):
    return [is_safe_control("x")]

def survey_years(page):
    page.locator("#year").click()

def pick_year(page, year):
    survey = page.locator("#menu").inner_text()
    return survey
''', encoding="utf-8")
    (app / "shop_docs.py").write_text('''
import re
import shop_site as site

def cmd_run(page):
    if re.search("x", "y"):
        pass
    site.pick_year(page, "2025")
    site.survey_years(page)
''', encoding="utf-8")
    assert guards_asked_in_a_run(app) == []
    assert "survey_years:click" in presses_in_a_run(app)


# -- a real browser saves its own downloads ----------------------------------

REAL_BROWSER_APPS = [d for d in APPS if any(
    "prefer_real=True" in p.read_text(encoding="utf-8") for p in d.glob("*_docs.py"))]


@pytest.mark.parametrize("app", REAL_BROWSER_APPS, ids=lambda d: d.name)
def test_an_app_that_clicks_in_a_real_browser_watches_a_download_folder(app):
    """A real Edge or Chrome attached over CDP saves a download itself, into
    its own Downloads folder, and Playwright's download event never fires.
    Nine scaffolds waited for that event. AT&T's tester clicked Download
    PDF five times and the app saw nothing each time. An app that clicks a
    download control in a real browser has to point the browser at a
    folder and watch it, or read the PDF some other way."""
    site = (app / ("%s_site.py" % app.name)).read_text(encoding="utf-8")
    if "expect_download" not in site:
        return
    docs = (app / ("%s_docs.py" % app.name)).read_text(encoding="utf-8")
    # set_download_dir and fetch_as_b64 both live in paperpull_core.capture
    # now, so an app satisfies this by calling either, whether it still
    # names the CDP call itself or reaches it through the core.
    watches = ("setDownloadBehavior" in site or "setDownloadBehavior" in docs
               or "set_download_dir" in site or "set_download_dir" in docs)
    reads_another_way = "fetch_as_b64" in site.lower()
    assert watches or reads_another_way, \
        "%s waits for a download event a real browser never sends" % app.name


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_app_notices_throttling(app):
    """Paylocity and UKG, the two payroll apps, watched for a passcode
    prompt and not for a site that had stopped answering. A payroll system
    is the worst place to keep asking after it has said no, and the other
    forty-six already knew to stop."""
    site = (app / ("%s_site.py" % app.name)).read_text(encoding="utf-8")
    if "detect_security_challenge" not in site:
        return
    assert "RATE_LIMIT_MARKERS" in site, \
        "%s cannot tell it is being throttled" % app.name
