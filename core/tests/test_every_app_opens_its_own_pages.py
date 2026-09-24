"""An order page is opened at an address on the provider's own host, always.

The receipt apps store the address of each purchase and open it again on
later runs. Target read that address off an anchor on the orders page, took
anything that started with "http", and wrote it down. Target, Walmart and
Gap then all overwrite it with `page.url` once the page has loaded, so
wherever the browser ended up is what the next run opens.

Target and Walmart had a working URL guard the entire time and nothing
called it. eBay already did this correctly, and reading how is what the
others now do: prefer the stored address, check it, fall back to rebuilding
one from the order number.

So the question here is not which of those two shapes an app chose. It is
what came out: whatever address reaches the browser has to be one this app's
own guard accepts, whatever the stored record happened to say.
"""
import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]


def openers(app: Path) -> list:
    """Functions that send the browser to an address they were handed.

    Found by reading what they do rather than by their name. Looking for
    "def goto_details" would work today and stop working the moment an app
    calls it something else, which is exactly how Walmart's pagination
    escaped a fix and the test written beside it.
    """
    source = (app / ("%s_site.py" % app.name)).read_text(
        encoding="utf-8", errors="ignore")
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Handed the stored record itself. An opener given an order id or a
        # route builds its address from a fixed base and there is nothing to
        # poison, so including it would only make this pass without asking.
        taken = [a.arg for a in node.args.args]
        if not any(a in ("purchase", "doc", "record") for a in taken):
            continue
        # what each local in this function was built out of, one step back,
        # because most of these read `url = purchase.details_url` first and
        # then navigate to `url`
        built_from = {}
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign) and len(inner.targets) == 1 \
                    and isinstance(inner.targets[0], ast.Name):
                built_from.setdefault(inner.targets[0].id, set()).update(
                    n.id for n in ast.walk(inner.value) if isinstance(n, ast.Name))

        for inner in ast.walk(node):
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "goto" and inner.args):
                continue
            roots = {n.id for n in ast.walk(inner.args[0])
                     if isinstance(n, ast.Name)}
            roots |= {r for name in list(roots) for r in built_from.get(name, ())}
            if roots & set(taken) - {"page"}:
                found.append(node.name)
                break
    return sorted(set(found))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists()
              and openers(d))

POISONED = [
    "https://evil.test/orders/900000000000001",
    "https://www.target.com.evil.test/orders/900000000000001",
    "https://www.target.com@evil.test/orders/900000000000001",
    "http://evil.test/orders/900000000000001",
    "javascript:alert(1)",
    "",
]


def site_of(app_dir: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app_dir))
    try:
        return importlib.import_module("%s_site" % app_dir.name)
    finally:
        sys.path.pop(0)


def purchase_at(url: str):
    from paperpull_core.models import ONLINE, Purchase
    return Purchase(purchase_type=ONLINE, purchase_date="2026-01-15",
                    order_number="900000000000001", details_url=url)


def openers_of(site):
    return [n for n in openers(Path(site.__file__).parent)
            if getattr(site, n, None) is not None]


def opened_by(site, url: str):
    """The address goto_details actually hands the browser, or None when it
    refused to hand it one at all."""
    page = MagicMock()
    for name in openers_of(site):
        try:
            getattr(site, name)(page, purchase_at(url))
        except Exception:
            pass
    if not page.goto.called:
        return None
    args, kwargs = page.goto.call_args
    return args[0] if args else kwargs.get("url")


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
@pytest.mark.parametrize("url", POISONED, ids=lambda u: u or "empty")
def test_a_poisoned_record_never_reaches_the_browser(app, url):
    site = site_of(app)
    opened = opened_by(site, url)
    assert opened is None or site.is_safe_url(opened), \
        "%s opened %r from a stored record saying %r" % (app.name, opened, url)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_an_ordinary_record_still_opens_the_order_page(app):
    """The other half. A guard that refuses everything breaks the app, and an
    app that quietly opens nothing is worse than one that raises."""
    site = site_of(app)
    host = sorted(site.ALLOWED_HOSTS)[0]
    opened = opened_by(site, "https://www.%s/orders/900000000000001" % host)
    assert opened, "%s no longer opens an order page at all" % app.name
    assert site.is_safe_url(opened)


# -- and the address never gets written down in the first place ---------------

TARGET = REPO / "apps" / "target"


@pytest.mark.skipif(not TARGET.exists(), reason="the Target app is not here")
def test_target_does_not_record_an_order_link_that_leads_off_target():
    """Where it came from. The orders page hands over an anchor, and this is
    the moment it either becomes a stored purchase or does not."""
    site = site_of(TARGET)
    card = site.RawCard(href="https://evil.test/orders/900000000000001",
                        text="Order #900000000000001  Jan 15, 2026  $42.00")
    assert site.card_to_purchase(card, site.ONLINE) is None


@pytest.mark.skipif(not TARGET.exists(), reason="the Target app is not here")
def test_target_still_records_an_ordinary_order_link():
    site = site_of(TARGET)
    for href in ("/orders/900000000000001",
                 "https://www.target.com/orders/900000000000001"):
        card = site.RawCard(href=href,
                            text="Order #900000000000001  Jan 15, 2026  $42.00")
        got = site.card_to_purchase(card, site.ONLINE)
        assert got is not None, href
        assert site.is_safe_url(got.details_url)
