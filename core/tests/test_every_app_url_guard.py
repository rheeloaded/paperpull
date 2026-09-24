"""Every app's URL guard, checked in one place and by behavior.

The check was written forty-eight times and drifted into ten answers. Six
apps insisted on an exact host, twenty-nine ignored the port, and five
raised ValueError instead of refusing a URL whose port did not parse. None
of it was reachable as an attack, but ten answers to one question is nine
too many, and a fix to one fixed one.

The parsing lives in paperpull_core.urls now. These run the same battery
against every app, so a provider added next year cannot bring an eleventh
version with it. They ask what the guard ANSWERS rather than how it is
written, because an app is free to add rules of its own on top (UKG also
refuses a path that says EDIT, ADD or DELETE) and must still get the
common cases right.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(".")
              and (d / ("%s_site.py" % d.name)).exists())


@pytest.fixture(params=[d.name for d in APPS])
def guard(request):
    """(is_safe_url, a host the app allows) for one app."""
    slug = request.param
    sys.path.insert(0, str(REPO / "apps" / slug))
    try:
        mod = importlib.import_module("%s_site" % slug)
    finally:
        sys.path.pop(0)
    fn = getattr(mod, "is_safe_url", None)
    if fn is None:
        pytest.skip("%s has no URL guard" % slug)
    hosts = sorted(getattr(mod, "ALLOWED_HOSTS", []) or [])
    if not hosts:
        # UKG's tenant is configured rather than compiled in.
        base = getattr(mod, "BASE", "") or ""
        if not base:
            mod.BASE = "https://tenant.ultipro.com"
        from urllib.parse import urlparse
        hosts = [urlparse(mod.BASE).hostname or ""]
    return slug, fn, hosts[0], [h.lower().rstrip(".") for h in hosts]


def _ok(fn, url):
    """The guard's answer, with a crash counted as its own kind of wrong."""
    try:
        return fn(url)
    except Exception as e:      # noqa: BLE001 - a guard may not raise
        return "raised %s" % type(e).__name__


# -- what every guard must refuse ----------------------------------------------

def test_plain_http_is_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "http://%s/" % host) is False


def test_another_host_is_refused(guard):
    _slug, fn, _host, _all = guard
    assert _ok(fn, "https://evil.example/x") is False


def test_a_lookalike_host_is_refused(guard):
    """The reason hosts are matched by label and never by string prefix.

    The second probe glues a label onto the front of an allowed host with
    no dot. For most apps that is a different domain and must be refused.
    Where the app also allows the parent (PG&E allows both m.pge.com and
    pge.com) the result really is one of its own subdomains, so the probe
    is built from a host that has no allowed parent."""
    _slug, fn, host, allowed = guard
    assert _ok(fn, "https://%s.evil.example/x" % host) is False

    def under_an_allowed_parent(h):
        return any(h.endswith("." + a) for a in allowed)

    for h in [host] + allowed:
        if not under_an_allowed_parent("not" + h):
            assert _ok(fn, "https://not%s/x" % h) is False
            return
    pytest.skip("every host here has an allowed parent, so no such probe exists")


def test_credentials_hiding_the_real_host_are_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s@evil.example/x" % host) is False


def test_another_port_is_refused(guard):
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s:8443/x" % host) is False


def test_a_port_that_does_not_parse_is_refused_and_does_not_raise(guard):
    """Five apps raised ValueError here, which reached the user as a
    traceback rather than as a refusal."""
    _slug, fn, host, _all = guard
    assert _ok(fn, "https://%s:99999/x" % host) is False


def test_a_scheme_that_is_not_the_web_is_refused(guard):
    _slug, fn, _host, _all = guard
    for url in ("file:///c:/secrets.txt", "javascript:alert(1)", "data:text/html,x"):
        assert _ok(fn, url) is False, url


def test_nothing_at_all_is_refused(guard):
    _slug, fn, _host, _all = guard
    for url in ("", None, "   ", "not a url"):
        assert _ok(fn, url) is False, repr(url)


# -- and what it must still allow ----------------------------------------------

def test_the_provider_s_own_host_is_allowed(guard):
    """A guard that refuses everything is safe and useless."""
    slug, fn, host, _all = guard
    if slug == "ukg":
        pytest.skip("its paths carry the verb, so a bare host is not enough")
    assert _ok(fn, "https://%s/" % host) is True


# -- and that something actually asks it ---------------------------------------

def _calls_outside_its_own_definition(app_dir: Path) -> list:
    """Every place this app asks the guard, not counting the guard's one line
    of delegation to the core."""
    import ast
    found = []
    for path in sorted(app_dir.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        own = [(n.lineno, n.end_lineno) for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "is_safe_url"]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name not in ("is_safe_url", "_host_allows"):
                continue
            if any(a <= node.lineno <= b for a, b in own):
                continue
            found.append("%s:%d" % (path.name, node.lineno))
    return found


APP_DIRS = sorted(d for d in (Path(__file__).resolve().parents[2] / "apps").iterdir()
                  if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())


@pytest.mark.parametrize("app", APP_DIRS, ids=lambda d: d.name)
def test_this_app_actually_asks_its_guard_somewhere(app):
    """A guard nothing calls is decoration, and it passes every check above.

    Four apps had one. Target and Walmart each opened an order page at an
    address that came off the page or out of a stored record, Wealthfront
    followed a document link the same way, and Gap had simply never needed
    to ask. All four answered this battery correctly the whole time, because
    nothing here was asking whether anybody consulted the answer.

    The same question was asked once about is_safe_control, after six apps
    turned out to have a control guard nothing called. It was never asked
    about this one.
    """
    calls = _calls_outside_its_own_definition(app)
    assert calls, (
        "%s defines is_safe_url and nothing ever calls it, so every URL this "
        "app opens is unchecked" % app.name)
