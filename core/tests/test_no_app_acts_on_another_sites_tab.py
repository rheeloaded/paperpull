"""No app reads, clicks or hands over a tab of another site.

A run attaches to the person's own browser, with whatever tabs they have
open. Most document apps took a tab on the provider's site when one was
open and otherwise the first open tab of any site at all, and Resume goes
straight to the documents. With the tab the person signed in with closed,
AAFMAA clicked a link named "1" on whatever page that was, American Express
and Navy Federal clicked links named like their own menus, Ally and Chase
pressed a documents control there and then loaded their own addresses into
that tab, as TSP did, and every document was marked for manual review or
the session was said to have expired. Golden 1 did the same through a
helper of its own, and Target always took the first tab.

So two questions are put to every app, and both are answered by running
its own code against a browser of this test's own, never by reading names.

  * The app's tab picker, any method that hands back a tab, is given a
    browser whose only tab is on another site. It must never hand that tab
    over. A tab of the run's own is what a run without one of the person's
    on the site works in.
  * An app that does use the person's tab on the provider's site, as most
    document apps do, has that tab moved to another site, the way a person
    might move it during a run, and its loop over the items it saves is
    given one item. Nothing may be read or clicked in that tab while it is
    on the other site. Loading it somewhere by address is not counted, the
    way the receipt apps open each purchase by its own address.

The browser here is a stand-in. Every app reaches it through its own
browser() and connect_over_cdp, exactly as it attaches at home, and a tab
records what was done to it and where it was at the time. The first read or
click in a tab of the run's own ends the run there, since all that is asked
is which tab the app turned to, and the same in the person's tab while it is
off the site, since that is the failure.
"""
import ast
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
ELSEWHERE = "https://www.elsewhere.example/inbox"


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))


# -- the stand-in browser -----------------------------------------------------

class Enough(BaseException):
    """Ends a run at the first read or click this test needs to see. Not an
    Exception, so no app's own `except Exception` can take it for a failure
    it should note and carry on from."""


# What may be done with a tab without reading what is on it or acting in it.
QUIET = {"url", "is_closed", "on", "once", "remove_listener", "goto",
         "wait_for_timeout", "set_default_timeout", "set_default_navigation_timeout",
         "context"}


class Tab:
    """A tab. Its address changes when it is sent somewhere by address, and
    everything else done to it is noted with where it was at the time."""

    def __init__(self, url, context, on_its_host, own=False):
        object.__setattr__(self, "_state", {
            "url": url, "closed": False, "context": context,
            "on_its_host": on_its_host, "own": own, "armed": False,
            "acts": [], "loads": []})

    @property
    def url(self):
        return self._state["url"]

    @url.setter
    def url(self, value):
        self._state["url"] = value

    @property
    def context(self):
        return self._state["context"]

    def is_closed(self):
        return self._state["closed"]

    def goto(self, url, **_kw):
        self._state["loads"].append(url)
        self._state["url"] = url
        return MagicMock(status=200, ok=True)

    def wait_for_timeout(self, *_a, **_kw):
        return None

    def on(self, *_a, **_kw):
        return None

    once = remove_listener = on

    def set_default_timeout(self, *_a, **_kw):
        return None

    set_default_navigation_timeout = set_default_timeout

    def close(self, *_a, **_kw):
        self._noted("close")
        self._state["closed"] = True

    def on_the_site(self):
        try:
            return bool(self._state["on_its_host"](self._state["url"] or ""))
        except Exception:
            return False

    def _noted(self, name):
        st = self._state
        st["acts"].append((name, st["url"], self.on_the_site()))
        # In a tab of the run's own, the first read or click is the answer.
        # In the person's tab it is the failure when the tab is off the site,
        # and once the item is under way any of it ends the run, since only
        # where the tab was matters.
        if st["own"] or st["armed"] or not self.on_the_site():
            raise Enough(name)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self._noted(name)
        return MagicMock(name="tab.%s" % name)

    def __setattr__(self, name, value):
        if name == "url":
            self._state["url"] = value
        else:
            object.__setattr__(self, name, value)


class Context:
    """The signed-in context a run attaches to. A tab it opens is a tab of
    the run's own."""

    def __init__(self, on_its_host):
        self.pages = []
        self.on_its_host = on_its_host
        self.opened = []

    def new_page(self):
        tab = Tab("about:blank", self, self.on_its_host, own=True)
        self.pages.append(tab)
        self.opened.append(tab)
        return tab

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name="context.%s" % name)


class _Browser:
    def __init__(self, context):
        self.contexts = [context]

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name="browser.%s" % name)


class _Playwright:
    def __init__(self, context):
        self._context = context
        self.chromium = SimpleNamespace(
            connect_over_cdp=lambda url, **kw: _Browser(self._context),
            launch_persistent_context=lambda *a, **kw: pytest.fail(
                "the run launched a browser of its own instead of attaching"))

    def start(self):
        return self

    def stop(self):
        return None


# -- each app, built as it is at home --------------------------------------------

def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        mod = importlib.import_module(entry_of(app).stem)
        site = sys.modules.get("%s_site" % app.name)
        storage = sys.modules.get("storage")
        return mod, site, storage
    finally:
        sys.path.pop(0)


def built(app: Path, tmp_path, monkeypatch):
    """The app, constructed by its own parser and __init__ from a config that
    attaches over CDP, with a stand-in browser behind that attach."""
    mod, site, storage = load(app)
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    args = mod.build_parser().parse_args(["--config", str(cfg)])
    inst = mod.App(args)
    context = Context(site.is_safe_url)
    import playwright.sync_api as sync_api
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: _Playwright(context))
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return mod, site, storage, inst, context


# -- what hands back a tab, found by what it does ---------------------------------

def _tabby(node, attrs, providers) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == "pages":
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "new_page":
                return True
            if isinstance(n.func.value, ast.Name) and n.func.value.id == "self" \
                    and n.func.attr in providers:
                return True
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id == "self" and n.attr in attrs:
            return True
    return False


def tab_pickers(mod):
    """The run's methods that hand back a tab and need nothing to be told,
    whatever returns, or keeps and returns, a value made from a context's
    open tabs, a new tab, or another such method. With them, the attributes
    the run keeps a tab in."""
    tree = ast.parse(inspect.getsource(mod))
    methods = {fn.name: fn for cls in tree.body if isinstance(cls, ast.ClassDef)
               and cls.name == "App" for fn in cls.body
               if isinstance(fn, ast.FunctionDef)}
    attrs, providers, grew = set(), set(), True
    while grew:
        grew = False
        for name, fn in methods.items():
            local = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and _tabby(n.value, attrs, providers):
                    for t in n.targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                                and t.value.id == "self" and t.attr not in attrs:
                            attrs.add(t.attr)
                            grew = True
                        elif isinstance(t, ast.Name):
                            local.add(t.id)
            if name in providers:
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Return) and n.value is not None and (
                        _tabby(n.value, attrs, providers)
                        or (isinstance(n.value, ast.Name) and n.value.id in local)):
                    providers.add(name)
                    grew = True
                    break
    out = []
    for name in sorted(providers):
        fn = methods[name]
        if len(fn.args.args) - len(fn.args.defaults) <= 1:
            out.append(name)
    return out, attrs


def own_addresses(site) -> list:
    """Addresses on the provider's own hosts, the ones its site module names
    and the front page of each host it allows, so a person's tab can be put
    on its site even when the module builds its addresses as it goes."""
    named = []
    for value in vars(site).values():
        values = value.values() if isinstance(value, dict) else [value]
        named += [v for v in values if isinstance(v, str) and v.startswith("https://")]
    for host in sorted(getattr(site, "ALLOWED_HOSTS", ()) or ()):
        named += ["https://%s/" % host, "https://www.%s/" % host]
    found = []
    for v in named:
        if v in found:
            continue
        try:
            if site.is_safe_url(v):
                found.append(v)
        except Exception:
            continue
    return found


def forget_tabs(inst, attrs):
    """The run let go of every tab it was keeping, as a new run starts."""
    for attr in attrs:
        if attr in vars(inst):
            setattr(inst, attr, None)


def picked(inst, name, context, tabs, attrs):
    """What the picker hands back from a browser holding these tabs."""
    context.pages[:] = list(tabs)
    forget_tabs(inst, attrs)
    try:
        return getattr(inst, name)()
    except Enough:
        return context.opened[-1] if context.opened else None


def theirs_for(inst, name, site, context, attrs):
    """A tab of the person's on the provider's own site that this picker
    takes, or None when it takes none of theirs, as the receipt apps that
    always open a tab of their own do."""
    for address in own_addresses(site):
        tab = Tab(address, context, site.is_safe_url)
        if picked(inst, name, context, [tab], attrs) is tab:
            return tab
    return None


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_tab_picker_hands_over_a_tab_of_another_site(app, tmp_path, monkeypatch):
    mod, site, _storage, inst, context = built(app, tmp_path, monkeypatch)
    names, attrs = tab_pickers(mod)
    assert names, "%s has no method that hands back a tab, so nothing was asked" % app.name
    for name in names:
        elsewhere = Tab(ELSEWHERE, context, site.is_safe_url)
        got = picked(inst, name, context, [elsewhere], attrs)
        assert got is not elsewhere, (
            "%s.%s() handed over a tab of another site (%s) when no tab of the "
            "person's was on the provider's site" % (app.name, name, ELSEWHERE))
        assert not elsewhere._state["acts"] and not elsewhere._state["loads"], (
            "%s.%s() did %s to a tab of another site" % (
                app.name, name, elsewhere._state["acts"] or elsewhere._state["loads"]))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_the_persons_tab_on_the_site_is_still_the_one_used(app, tmp_path, monkeypatch):
    """The other half. A picker that never takes the person's tab passes the
    test above by breaking every provider that keeps its session in that
    tab. One that took it before still takes it, beside a tab of another
    site."""
    mod, site, _storage, inst, context = built(app, tmp_path, monkeypatch)
    names, attrs = tab_pickers(mod)
    for name in names:
        theirs = theirs_for(inst, name, site, context, attrs)
        if theirs is None:
            continue
        elsewhere = Tab(ELSEWHERE, context, site.is_safe_url)
        assert picked(inst, name, context, [elsewhere, theirs], attrs) is theirs, (
            "%s.%s() no longer takes the person's tab on the provider's site" % (
                app.name, name))


# -- the loop over the items a run saves ---------------------------------------------

def _records_progress(methods, fn, seen) -> bool:
    if fn.name in seen:
        return False
    seen.add(fn.name)
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "update" and isinstance(n.func.value, ast.Attribute) \
                and n.func.value.attr == "progress":
            return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self" \
                and n.func.attr in methods \
                and _records_progress(methods, methods[n.func.attr], seen):
            return True
    return False


def item_loop(mod):
    """The method holding the loop that takes one item at a time, hands it to
    another method, and records how it went."""
    tree = ast.parse(inspect.getsource(mod))
    methods = {fn.name: fn for cls in tree.body if isinstance(cls, ast.ClassDef)
               and cls.name == "App" for fn in cls.body
               if isinstance(fn, ast.FunctionDef)}
    for name, fn in methods.items():
        for loop in ast.walk(fn):
            if not isinstance(loop, ast.For):
                continue
            bound = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
            for c in (c for s in loop.body for c in ast.walk(s) if isinstance(c, ast.Call)):
                f = c.func
                if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                        and f.value.id == "self" and f.attr in methods
                        and f.attr != name):
                    continue
                handed = {n.id for a in c.args for n in ast.walk(a) if isinstance(n, ast.Name)}
                if handed & bound and _records_progress(methods, methods[f.attr], set()):
                    return name
    return None


def an_item(mod, storage, address):
    """One item of the kind the app saves, invented, dated well inside any
    window, with its own address on the provider's site."""
    if hasattr(mod, "Document"):
        params = inspect.signature(mod.Document).parameters
        wanted = {"title": "Statement", "category": "Statement",
                  "summary": "Statement", "date": "2026-06-15",
                  "document_id": "900000000000001", "account": "Checking",
                  "href": address, "source_url": address}
        return mod.Document(**{k: v for k, v in wanted.items() if k in params})
    from paperpull_core.models import Purchase
    kinds = list(getattr(getattr(storage, "SPEC", None), "routes", {}) or ["Online"])
    return Purchase(purchase_type=kinds[0], purchase_date="2026-06-15",
                    order_number="900000000000001", details_url=address,
                    total="$10.00")


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_nothing_is_read_or_clicked_in_the_persons_tab_once_it_is_off_the_site(
        app, tmp_path, monkeypatch, capsys):
    mod, site, storage, inst, context = built(app, tmp_path, monkeypatch)
    names, attrs = tab_pickers(mod)
    theirs = None
    for name in names:
        theirs = theirs_for(inst, name, site, context, attrs)
        if theirs is not None:
            break
    if theirs is None:
        pytest.skip("%s never works in a tab of the person's, only in its own" % app.name)
    loop = item_loop(mod)
    assert loop, "%s has no loop over the items it saves" % app.name

    # The run took the person's tab on the site, and then it was moved.
    item = an_item(mod, storage, theirs.url)
    context.pages[:] = [theirs]
    forget_tabs(inst, attrs)
    assert getattr(inst, name)() is theirs
    theirs.url = ELSEWHERE
    theirs._state["acts"].clear()
    theirs._state["loads"].clear()
    theirs._state["armed"] = True

    stopped = False
    try:
        getattr(inst, loop)([item])
    except SystemExit:
        stopped = True
    except Enough:
        pass
    out = capsys.readouterr().out

    off_site = [(act, where) for act, where, on in theirs._state["acts"] if not on]
    assert not off_site, (
        "%s read or clicked the person's tab while it was on another site, %s"
        % (app.name, off_site))
    own_acted = any(t._state["acts"] for t in context.opened)
    assert stopped or own_acted or theirs._state["loads"], (
        "%s neither stopped nor turned to a tab, so the item never reached a tab "
        "and this proves nothing\n%s" % (app.name, out))
