"""Waiting for a page to be ready, when nobody knows which wait it needs.

Two of the eight bugs that cost Costco a round each were the wrong kind
of wait. The rows had not been drawn when they were read, because a tab
switch asks an API and redraws without navigating, so there is no load
to wait on and the network goes quiet before the rows are on screen. And
a hash-only change of address loads nothing, so a wait for a page load
waited on something that was never going to happen.

The maintainer writing a provider blind cannot know which wait a page
wants. This lets him write down his best few guesses in order, tries
each in turn against one budget, and says which one worked. The journal
carries the answer back, and the next round hard-codes it.

    from paperpull_core.ready import (ready, network_idle, has,
                                      count_reaches, count_settles)

    got = ready(page,
                [network_idle(), count_reaches("tr.order"),
                 count_settles("tr.order")],
                invariant=has("tr.order"),
                budget_ms=20000, journal=self._journal, name="order rows")
    if not got.ready:
        ...

ADDITIVE ONLY

Every strategy here only waits. None clicks, reloads, navigates, goes
back or restores anything, so trying one and then the next leaves the
page exactly as the first found it plus however long it took. That is
the whole reason this is safe to run against somebody's bank, and it is
why a strategy can only be built by this module. Handing ready() a
function of your own is a TypeError, because a function of your own is
where a reload would get in.

THE INVARIANT DECIDES

A strategy that returned without raising has not succeeded. The page is
ready when the invariant says so, and it is asked first, before any
strategy, so a page that is already ready costs one question and no
wait. That keeps a working run as fast as it was.

ONE BUDGET

The budget is for the whole call, not for each strategy. An app that
failed in ten seconds must not start failing in ninety because it listed
nine guesses. A strategy that could hang, a change of address that never
comes, can be given a smaller share with within_ms so it cannot starve
the ones after it.

NOTHING HERE MAY RAISE

Once the arguments are right, a failure inside a wait, a page that
closed, an invariant that threw, is recorded and the next strategy is
tried. The caller gets an answer, never an exception.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Every name a strategy can have. The journal writes these and nothing
# else, so a name cannot become a sentence off a page.
STRATEGIES = frozenset((
    "already", "late", "dom_loaded", "loaded", "network_idle", "url_changed",
    "count_reached", "count_settled",
))

# How an attempt turned out, from a fixed list for the same reason.
OUTCOMES = frozenset((
    "satisfied",        # the strategy finished and the invariant held
    "not_satisfied",    # the strategy finished and the invariant did not
    "timed_out",        # the strategy's own condition never came
    "no_budget",        # the budget ran out before it was tried
    "invalid_selector", # a selector the browser cannot parse
    "error",            # the wait itself failed, a closed page for one
))

# How often the polling strategies look. Short enough that a count which
# arrives is noticed within a frame or two, long enough to cost nothing.
POLL_MS = 100

_COUNT_JS = "(sel) => document.querySelectorAll(sel).length"


@dataclass
class Attempt:
    strategy: str
    outcome: str
    ms: int

    def as_dict(self) -> dict:
        return {"strategy": self.strategy, "outcome": self.outcome,
                "ms": self.ms}


@dataclass
class Readiness:
    """What happened. ready is the only field a caller has to read."""
    ready: bool
    winner: str = ""
    elapsed_ms: int = 0
    attempts: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ready


class Strategy:
    """One way of waiting. Built only by the functions below."""

    __slots__ = ("name", "_wait", "_within_ms")

    def __init__(self, name: str, wait: Callable, within_ms=None,
                 _token=None):
        if _token is not _BUILDER:
            raise TypeError(
                "A strategy is built by paperpull_core.ready, so that "
                "nothing which undoes page state can be tried as one")
        self.name = name
        self._wait = wait
        self._within_ms = within_ms

    def __repr__(self) -> str:
        return "Strategy(%s)" % self.name


_BUILDER = object()


def _strategy(name: str, wait: Callable, within_ms) -> Strategy:
    if within_ms is not None:
        within_ms = max(0, int(within_ms))
    return Strategy(name, wait, within_ms, _token=_BUILDER)


# -- the strategies -----------------------------------------------------------
#
# Each wait takes the page, how long it may take, and what the page's
# address was when ready() began, and returns True when its own condition
# came, False when it did not. None of them may change the page.

def _check_selector(selector: str) -> Optional[str]:
    """Why a selector cannot be counted, or None.

    Playwright's dialect is a SyntaxError inside the page, which has been
    shipped twice, so it is caught here before anything is asked."""
    from .failure import playwright_only
    if not selector or not isinstance(selector, str):
        return "empty"
    if playwright_only(selector):
        return "playwright dialect"
    return None


class _InvalidSelector(Exception):
    pass


def _count(page, selector: str) -> int:
    return int(page.evaluate(_COUNT_JS, selector) or 0)


def load(state: str = "load", within_ms=None) -> Strategy:
    """The document finished loading, to "domcontentloaded" or "load"."""
    if state not in ("load", "domcontentloaded"):
        raise ValueError("load() takes 'load' or 'domcontentloaded'")
    name = "loaded" if state == "load" else "dom_loaded"

    def wait(page, ms, _start_url):
        page.wait_for_load_state(state, timeout=max(1, ms))
        return True
    return _strategy(name, wait, within_ms)


def network_idle(within_ms=None) -> Strategy:
    """No request in flight for half a second.

    Right for a page that fetches and then draws. Wrong for one that
    draws on a timer after the fetch, which is what the invariant is for.
    """
    def wait(page, ms, _start_url):
        page.wait_for_load_state("networkidle", timeout=max(1, ms))
        return True
    return _strategy("network_idle", wait, within_ms)


def url_changes(within_ms=None) -> Strategy:
    """The address differs from what it was when ready() began.

    A change of the part after # counts. That kind of change loads
    nothing, so a wait for a load never sees it, and that was a round.
    Read from page.url on a poll rather than from navigation events,
    because a single page app that rewrites its address with the history
    API fires no navigation a listener could rely on.

    An address that changed before ready() was called is not a change to
    this, since it compares with where the page was when waiting began.
    That case is the invariant's to catch, which is one more reason the
    invariant says what the new page looks like and not only that the
    address moved."""
    def wait(page, ms, start_url):
        deadline = time.monotonic() + ms / 1000
        while True:
            if (page.url or "") != start_url:
                return True
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            page.wait_for_timeout(min(POLL_MS, max(1, int(left * 1000))))
    return _strategy("url_changed", wait, within_ms)


def count_reaches(selector: str, at_least: int = 1,
                  within_ms=None) -> Strategy:
    """At least this many elements match a CSS selector."""
    problem = _check_selector(selector)
    need = max(1, int(at_least))

    def wait(page, ms, _start_url):
        if problem:
            raise _InvalidSelector(problem)
        deadline = time.monotonic() + ms / 1000
        while True:
            if _count(page, selector) >= need:
                return True
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            page.wait_for_timeout(min(POLL_MS, max(1, int(left * 1000))))
    return _strategy("count_reached", wait, within_ms)


def count_settles(selector: str, quiet_ms: int = 750, at_least: int = 1,
                  within_ms=None) -> Strategy:
    """The number of matches stopped changing for quiet_ms.

    For a list that draws in pieces, where the first row arriving says
    nothing about whether the fortieth has. It will not call a count of
    zero settled unless at_least is 0, because an empty list that has not
    started drawing is perfectly still, and settling on it was the bug."""
    problem = _check_selector(selector)
    need = max(0, int(at_least))
    quiet = max(POLL_MS, int(quiet_ms))

    def wait(page, ms, _start_url):
        if problem:
            raise _InvalidSelector(problem)
        deadline = time.monotonic() + ms / 1000
        last, since = None, time.monotonic()
        while True:
            n = _count(page, selector)
            now = time.monotonic()
            if n != last:
                last, since = n, now
            elif n >= need and (now - since) * 1000 >= quiet:
                return True
            left = deadline - now
            if left <= 0:
                return False
            page.wait_for_timeout(min(POLL_MS, max(1, int(left * 1000))))
    return _strategy("count_settled", wait, within_ms)


# -- invariants ---------------------------------------------------------------

def has(selector: str, at_least: int = 1) -> Callable:
    """An invariant, at least this many elements match."""
    problem = _check_selector(selector)
    if problem:
        raise ValueError("invariant selector is %s" % problem)
    need = max(1, int(at_least))
    return lambda page: _count(page, selector) >= need


# -- the call -----------------------------------------------------------------

def _ms_since(t0: float) -> int:
    return max(0, int((time.monotonic() - t0) * 1000))


def _holds(invariant, page) -> Optional[bool]:
    """The invariant's answer, or None when asking it failed."""
    try:
        return bool(invariant(page))
    except Exception as e:
        log.debug("ready: invariant raised %s", type(e).__name__)
        return None


def ready(page, strategies, invariant, budget_ms: int, journal=None,
          name: str = "") -> Readiness:
    """Try each strategy in order until the invariant holds.

    Returns a Readiness saying whether it did, which strategy got it
    there, and how long each one took. "already" wins when the page was
    ready before anything waited, and "late" when it came right only
    after every strategy had finished without getting it there. Nothing
    raises once the arguments are right."""
    strategies = list(strategies or ())
    for s in strategies:
        if not isinstance(s, Strategy):
            raise TypeError(
                "ready() takes strategies built by paperpull_core.ready, "
                "got %r" % type(s).__name__)
    if not callable(invariant):
        raise TypeError("ready() needs an invariant. A strategy that did "
                        "not raise has not proved the page is ready.")
    budget = max(0, int(budget_ms))

    t0 = time.monotonic()
    result = Readiness(False)
    try:
        start_url = page.url or ""
    except Exception:
        start_url = ""

    if _holds(invariant, page):
        result.ready, result.winner = True, "already"
        result.attempts.append(Attempt("already", "satisfied", _ms_since(t0)))
    else:
        for s in strategies:
            left = budget - _ms_since(t0)
            if left <= 0:
                result.attempts.append(Attempt(s.name, "no_budget", 0))
                continue
            share = left if s._within_ms is None else min(left, s._within_ms)
            began = time.monotonic()
            try:
                came = s._wait(page, share, start_url)
                outcome = "" if came else "timed_out"
            except _InvalidSelector:
                outcome = "invalid_selector"
            except Exception as e:
                outcome = ("timed_out" if "timeout" in type(e).__name__.lower()
                           else "error")
            if not outcome:
                held = _holds(invariant, page)
                outcome = "satisfied" if held else "not_satisfied"
            result.attempts.append(Attempt(s.name, outcome, _ms_since(began)))
            if outcome == "satisfied":
                result.ready, result.winner = True, s.name
                break
        else:
            # Every strategy has had its turn. The invariant is asked one
            # last time, because a page can come right while a strategy
            # that was going to fail was still waiting, and saying it is
            # not ready when it is would throw a working run away. It is
            # called late, not credited to a strategy that did not get it
            # there, and not called already, which would say no wait was
            # needed.
            if strategies and _holds(invariant, page):
                result.ready, result.winner = True, "late"

    result.elapsed_ms = _ms_since(t0)
    if journal is not None:
        try:
            journal.waited(name or "unnamed wait", result)
        except Exception:
            pass
    _say(name, result)
    return result


# Which (name, answer) pairs this process has already printed.
_told: set = set()


def _say(name: str, result: Readiness) -> None:
    """One line in the run's output, the first time a wait gets an answer.

    A Pilot that works writes no file, and the run that worked is the one
    whose wait the next round should keep. Testers paste a Pilot's output
    into the issue already, so the answer goes there. Built from the same
    words the journal allows, and printed once per wait and answer, so a
    run of two hundred receipts says it once and not two hundred times.
    "already" is not news and is not printed."""
    try:
        from .failure import _step
        label = _step(name or "unnamed wait")
        winner = result.winner if result.winner in STRATEGIES else "nothing"
        if result.ready and winner == "already":
            return
        key = (label, winner, bool(result.ready))
        if key in _told:
            return
        _told.add(key)
        tried = ", ".join(a.strategy for a in result.attempts
                          if a.strategy in STRATEGIES) or "nothing"
        if result.ready:
            log.info("Waited for %s, ready after %s in %d ms (tried %s)",
                     label, winner, result.elapsed_ms, tried)
        else:
            log.info("Waited for %s, never ready in %d ms (tried %s)",
                     label, result.elapsed_ms, tried)
    except Exception:
        pass
