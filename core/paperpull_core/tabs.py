"""The tab a run works in is on the provider's own site or one of the run's
own, and never a tab of another site.

A run attaches to the browser login.bat left open, the person's own, with
whatever tabs they have in it. Most document apps took a tab on the
provider's site when one was open and otherwise the first open tab of any
site at all, and Resume goes straight to the documents, so nothing opened
the provider's page first. With the tab the person signed in with closed,
AAFMAA clicked a link named "1" on whatever page that tab showed and read
its rows, American Express and Navy Federal clicked links named like their
own menus there, and Ally and Chase pressed a documents control on it and
then loaded their own addresses into it, as TSP did. Every document was
then marked for manual review, or the run said the session had expired,
and each app had read the other site's page for a sign-in or a check first.
Golden 1 did the same through a helper of its own, and Target always took
the browser's first tab.

So every app answers two questions the same way, here.

  * Which tab. The person's tab on the provider's own site when one is open,
    and otherwise a new tab of the run's own (new_tab), never one of another
    site.
  * Whether the tab is still on the site before each document (on_its_site).
    A tab of the person's that has left the site is theirs and is let go of,
    never loaded or read. A provider that keeps its session in the tab the
    person signed in with cannot be reached from a new tab, so the run stops
    at that document and says so, leaving it and the rest for the next run.
    Any other provider's documents page is opened in a tab of the run's own,
    the way discovery opens it.
"""
from __future__ import annotations

import weakref

# The tabs this run opened. Only these may be loaded somewhere new when they
# are not on the provider's site. Weak, so a closed tab is not kept alive.
_OWN = weakref.WeakSet()


def new_tab(context):
    """A new tab in the signed-in context, known from then on as one this
    run opened rather than one of the person's."""
    tab = context.new_page()
    try:
        _OWN.add(tab)
    except TypeError:
        pass
    return tab


def is_own(tab) -> bool:
    """Whether this run opened the tab (new_tab)."""
    try:
        return tab in _OWN
    except TypeError:
        return False


def on_site(tab, on_its_host) -> bool:
    """Whether the tab is open and on the provider's own site, by the same
    test of an address the app picks the person's tab with. Never True for a
    closed tab or one whose address cannot be read."""
    try:
        if tab is None or tab.is_closed():
            return False
        return bool(on_its_host(tab.url or ""))
    except Exception:
        return False


def on_its_site(app, on_its_host, provider: str, open_documents=None, ready=None):
    """The tab the next document is taken in, on the provider's own site.

    `app` is the run. Its page() hands over the tab it works in and its
    _work_page holds it. `on_its_host` says whether an address is the
    provider's own, and `provider` is the name the run says it by.

    The tab page() hands over is used while it is on the site. A tab of the
    person's that is not, moved somewhere else during the run, is theirs, so
    it is let go of and page() is asked again, for another of theirs on the
    site or a new tab of the run's own.

    `open_documents(tab)` opens the provider's documents page in a tab by
    its address, the way discovery does, and is given for a provider whose
    session is a cookie, which a new tab shares. `ready(tab)` is given when
    the documents need one page of the site, or something done there, and
    says the tab has it, and a tab on the site without it is sent there
    first. Without `open_documents` the provider keeps its session in the
    tab the person signed in with, which a tab of the run's own never has,
    even once something has loaded the site in it, so the run stops here
    and says so. It also stops when the page would not open on the site.
    Either way nothing is asked of the provider for this document, which is
    left as it was for the next run."""
    page = app.page()
    if not on_site(page, on_its_host) and not is_own(page):
        app._work_page = None
        page = app.page()
    there = on_site(page, on_its_host)
    if open_documents is None:
        if there and not is_own(page):
            return page
        _close_if_blank(page)
        stop(app, [
            "The %s tab you signed in with is not open." % provider,
            "%s keeps your session in that tab, and a new tab would not be "
            "signed in, so nothing was asked of %s." % (provider, provider),
            "Open %s with login.bat, sign in, keep the window open, and run "
            "this again." % provider,
        ])
    if there and (ready is None or ready(page)):
        return page
    open_documents(page)
    if on_site(page, on_its_host) and (ready is None or ready(page)):
        return page
    _close_if_blank(page)
    stop(app, [
        "Your %s documents page did not open, so nothing was asked of %s "
        "for this document." % (provider, provider),
        "Open %s with login.bat, sign in, keep the window open, and run "
        "this again." % provider,
    ])


def stop(app, lines) -> None:
    """Say why the run stops and stop it, as a stop. Leaving on SystemExit
    with the exception in flight is what the core reports as a run that
    stopped, never one that finished clean."""
    try:
        app.progress.save(backup=True)
    except Exception:
        pass
    print()
    for i, line in enumerate(lines):
        print(("!! " if i == 0 else "   ") + line)
    raise SystemExit(0)


def _close_if_blank(tab) -> None:
    """A tab this run opened that never left its blank page is closed rather
    than left behind, unless it is the browser's only tab, since closing that
    could close the window the person was told to keep open."""
    try:
        if not is_own(tab) or tab.is_closed() or (tab.url or "about:blank") != "about:blank":
            return
        if len([t for t in tab.context.pages if not t.is_closed()]) > 1:
            tab.close()
    except Exception:
        pass
