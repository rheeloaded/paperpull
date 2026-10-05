"""The tab a run works in, and the check before each document (tabs.py).

Each rule is held here with a stand-in for a tab, which notes everything
done to it. The apps' own browser tests and the census in
test_no_app_acts_on_another_sites_tab.py hold the same rules in real
browsers and across every app.
"""
from urllib.parse import urlsplit

import pytest

from paperpull_core import tabs

SITE_HOST = "documents.provider.test"
ON_SITE = "https://%s/statements" % SITE_HOST
ELSEWHERE = "https://www.elsewhere.test/inbox"


def on_its_host(url):
    return urlsplit(url or "").hostname == SITE_HOST


class Tab:
    def __init__(self, url, context):
        self.url = url
        self.context = context
        self.closed = False
        self.done = []

    def is_closed(self):
        return self.closed

    def close(self):
        self.done.append("close")
        self.closed = True

    def goto(self, url, **_kw):
        self.done.append(("goto", url))
        self.url = url


class Context:
    def __init__(self):
        self.pages = []

    def new_page(self):
        tab = Tab("about:blank", self)
        self.pages.append(tab)
        return tab


class Run:
    """A run as tabs.on_its_site sees it, a page() that picks the person's
    tab on the site or opens one of its own, a _work_page, and progress."""

    def __init__(self, context):
        self.context = context
        self._work_page = None
        self.saved = []
        self.progress = self

    def save(self, backup=False):
        self.saved.append(backup)

    def page(self):
        if self._work_page is not None and not self._work_page.is_closed():
            return self._work_page
        theirs = [t for t in self.context.pages if tabs.on_site(t, on_its_host)]
        self._work_page = theirs[0] if theirs else tabs.new_tab(self.context)
        return self._work_page


def a_run(*urls):
    context = Context()
    for url in urls:
        context.pages.append(Tab(url, context))
    return Run(context), context


def test_a_tab_on_the_site_is_used_as_it_is():
    run, context = a_run(ELSEWHERE, ON_SITE)
    theirs = context.pages[1]
    assert tabs.on_its_site(run, on_its_host, "Provider") is theirs
    assert not theirs.done and not context.pages[0].done


def test_a_new_tab_is_the_runs_own_and_one_of_the_persons_is_not():
    run, context = a_run(ON_SITE)
    assert not tabs.is_own(context.pages[0])
    assert tabs.is_own(tabs.new_tab(context))


def test_with_no_tab_on_the_site_a_tab_session_provider_stops_and_says_so(capsys):
    run, context = a_run(ELSEWHERE)
    elsewhere = context.pages[0]
    with pytest.raises(SystemExit) as stopped:
        tabs.on_its_site(run, on_its_host, "Provider")
    out = capsys.readouterr().out
    assert stopped.value.code == 0
    assert "!! The Provider tab you signed in with is not open." in out
    assert "login.bat" in out
    assert not elsewhere.done, "the other site's tab was never touched"
    assert run.saved == [True], "progress is saved before the stop"
    own = [t for t in context.pages if tabs.is_own(t)]
    assert own and own[0].closed, "the blank tab the run opened is not left behind"


def test_the_runs_only_tab_is_not_closed_at_the_stop(capsys):
    """Closing the browser's only tab could close the window the person was
    told to keep open."""
    run, context = a_run()
    with pytest.raises(SystemExit):
        tabs.on_its_site(run, on_its_host, "Provider")
    assert len(context.pages) == 1 and not context.pages[0].closed


def test_with_no_tab_on_the_site_a_cookie_provider_opens_its_page_in_its_own_tab():
    run, context = a_run(ELSEWHERE)
    elsewhere = context.pages[0]
    opened = []

    def open_documents(tab):
        opened.append(tab)
        tab.goto(ON_SITE)

    got = tabs.on_its_site(run, on_its_host, "Provider", open_documents)
    assert tabs.is_own(got) and opened == [got] and got.url == ON_SITE
    assert not elsewhere.done


def test_the_persons_tab_that_left_the_site_is_let_go_and_never_touched(capsys):
    """Moved somewhere else during the run, it is theirs. Another tab is
    found or opened, and that one is used."""
    run, context = a_run(ON_SITE)
    theirs = run.page()
    theirs.url = ELSEWHERE

    def open_documents(tab):
        tab.goto(ON_SITE)

    got = tabs.on_its_site(run, on_its_host, "Provider", open_documents)
    assert got is not theirs and tabs.is_own(got)
    assert not theirs.done, "their tab was neither loaded nor closed"


def test_a_tab_of_the_runs_own_off_the_site_is_opened_on_it_again():
    run, context = a_run()
    own = run.page()
    own.url = ELSEWHERE
    got = tabs.on_its_site(run, on_its_host, "Provider", lambda tab: tab.goto(ON_SITE))
    assert got is own and own.url == ON_SITE


def test_a_page_that_does_not_open_on_the_site_stops_the_run(capsys):
    run, context = a_run(ELSEWHERE)
    with pytest.raises(SystemExit) as stopped:
        tabs.on_its_site(run, on_its_host, "Provider", lambda tab: None)
    assert stopped.value.code == 0
    assert "documents page did not open" in capsys.readouterr().out
    own = [t for t in context.pages if tabs.is_own(t)]
    assert own and own[0].closed, "the blank tab the run opened is not left behind"
    assert not context.pages[0].done, "the other site's tab was never touched"


def test_a_tab_of_the_runs_own_is_never_taken_for_the_signed_in_tab(capsys):
    """A provider that keeps its session in the tab the person signed in
    with is never worked in a tab of the run's own, even once something,
    discovery for one, has loaded the site in it, since that tab never
    signed in."""
    run, context = a_run(ELSEWHERE)
    own = run.page()
    assert tabs.is_own(own)
    own.url = ON_SITE
    with pytest.raises(SystemExit):
        tabs.on_its_site(run, on_its_host, "Provider")
    assert "The Provider tab you signed in with is not open." in capsys.readouterr().out
    assert not own.closed, "a tab the run opened that is not blank is left for the person"


def test_a_tab_on_the_site_but_not_on_the_page_the_documents_come_from_is_sent_there():
    run, context = a_run("https://%s/home" % SITE_HOST)
    theirs = context.pages[0]

    def ready(tab):
        return urlsplit(tab.url).path == "/statements"

    got = tabs.on_its_site(run, on_its_host, "Provider", lambda tab: tab.goto(ON_SITE),
                           ready=ready)
    assert got is theirs and theirs.done == [("goto", ON_SITE)]


def test_a_tab_on_the_page_the_documents_come_from_is_not_loaded_again():
    run, context = a_run(ON_SITE)
    theirs = context.pages[0]
    got = tabs.on_its_site(run, on_its_host, "Provider", lambda tab: tab.goto(ON_SITE),
                           ready=lambda tab: urlsplit(tab.url).path == "/statements")
    assert got is theirs and not theirs.done


@pytest.mark.parametrize("url", ["", "about:blank", "not a url", None])
def test_an_address_that_cannot_be_read_is_not_on_the_site(url):
    context = Context()
    tab = Tab(url, context)
    assert not tabs.on_site(tab, on_its_host)
    tab.url = ON_SITE
    tab.closed = True
    assert not tabs.on_site(tab, on_its_host), "a closed tab is on no site"
