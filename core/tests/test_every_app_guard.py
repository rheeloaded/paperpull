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
