"""What the app did, and what the page did about it.

The failure file says what the page looked like when a run gave up. It
cannot say anything about the state a run never reached, and that is
what makes a new provider expensive. Costco's bugs were stacked, so the
sixth was invisible until the fifth was fixed, and each layer cost a
round.

This is the layer above. A bounded record of every step the app took and
the state the page was in before and after, kept as it goes, so one
failure carries the evidence for several defects at once.

WHAT AN ENTRY IS

Three kinds, and nothing else.

    an operation    the app was about to do something it named
    a choice        it found N candidates and took the nth of them
    a checkpoint    the page's state at a transition, before and after

A choice is the one that matters most and is the cheapest to get wrong.
Counting one collection and acting on the nth of another is a bug that
reads, from outside, exactly like a page that did not load. Recording
which collection each count came from puts the two numbers side by side
where a person can see they disagree.

WHAT A CHECKPOINT MAY SAY

The same rules as the failure file, because it ends up in the same file.
Counts, booleans, enums, durations, and words the app wrote in its own
source. No text, no attribute, no URL.

A route change is the exception worth explaining. Whether an address
changed, and in which part, is the difference between a page that
reloaded and one that did not, and that was a bug on its own. So the
journal keeps the last address to compare against and never writes it
down. What comes out is one of "same", "hash", "query", "path", "host".

NOTHING HERE MAY RAISE

It runs during an ordinary run, including a run that is going fine. A
journal that throws turns a working provider into a broken one, so every
call is wrapped and every failure to record is silent.
"""
from __future__ import annotations

import time
from typing import Optional

from .failure import _count, _enum, _only_safe, _step, error_kind

# A run that saves two hundred documents does not need two hundred
# thousand entries, and a file nobody can open helps nobody. The oldest
# go first, because the question is almost always what happened last.
MAX_ENTRIES = 300

# What a step was for, from a fixed list, so a phase cannot become a
# sentence off a page.
PHASES = frozenset("""
start sign_in open_list switch_tab choose_range read_rows
open_item render_item finish_item close_item next_item
parse download verify done
""".split())

# How an address changed between two checkpoints. The whole point of
# keeping the address is to be able to say this and not write it down.
ROUTE_CHANGES = ("same", "hash", "query", "path", "host", "unknown")

_WATCH_JS = r"""
(selectors) => {
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const out = {};
  for (const [name, sel] of selectors) {
    try {
      const found = document.querySelectorAll(sel);
      let visible = 0;
      for (const el of found) if (onScreen(el)) visible += 1;
      out[name] = [found.length, visible];
    } catch (e) {
      out[name] = null;
    }
  }
  const b = document.body;
  out['__page'] = [
    getComputedStyle(document.documentElement).overflow,
    b ? getComputedStyle(b).overflow : '',
    b ? b.scrollHeight : 0,
    document.readyState
  ];
  return out;
}
"""

_OVERFLOW = frozenset(("visible", "hidden", "scroll", "auto", "clip"))
_READY = frozenset(("loading", "interactive", "complete"))


def _route_change(before: str, after: str) -> str:
    """How an address changed, without either of them coming out."""
    if not before or not after:
        return "unknown"
    if before == after:
        return "same"
    from urllib.parse import urlsplit
    try:
        a, b = urlsplit(before), urlsplit(after)
    except ValueError:
        return "unknown"
    if a.hostname != b.hostname:
        return "host"
    if a.path != b.path:
        return "path"
    if a.query != b.query:
        return "query"
    if a.fragment != b.fragment:
        return "hash"
    return "same"


class Journal:
    """A bounded record of what a run did, kept as it goes.

    `watch` names the entries of the app's own FALLBACK table worth
    counting at every checkpoint, usually the list and the thing a
    document opens into."""

    def __init__(self, page=None, selectors: Optional[dict] = None,
                 watch=(), limit: int = MAX_ENTRIES):
        self.entries: list = []
        self.dropped = 0
        self.limit = max(10, int(limit))
        self._page = page
        self._started = time.time()
        self._last_url = ""
        self._pairs = []
        if isinstance(selectors, dict):
            from .failure import playwright_only
            for name in watch:
                sel = selectors.get(name)
                if sel and not playwright_only(str(sel)):
                    self._pairs.append([str(name)[:40], str(sel)])

    # -- writing -----------------------------------------------------------

    def _add(self, entry: dict) -> None:
        entry["at_ms"] = _count((time.time() - self._started) * 1000)
        entry["i"] = len(self.entries) + self.dropped
        self.entries.append(entry)
        while len(self.entries) > self.limit:
            self.entries.pop(0)
            self.dropped += 1

    def op(self, phase: str, operation: str, ordinal=None, **facts) -> None:
        """The app is about to do something it named.

        `operation` is a word from the source, "open the receipt". Facts
        are counts and words from the source, and anything else is
        dropped rather than written."""
        try:
            entry = {"kind": "op",
                     "phase": _enum(phase, PHASES, "other"),
                     "operation": _step(operation)}
            if ordinal is not None:
                entry["ordinal"] = _count(ordinal)
            if facts:
                entry["facts"] = _only_safe(facts)
            self._add(entry)
        except Exception:
            pass

    def chose(self, selector_id: str, collection: str, candidates: int,
              ordinal: int, precondition: str = "") -> None:
        """It found N candidates in a named collection and took the nth.

        The collection is the part that matters. Counting the rows and
        then acting on the nth button is a bug that reads from outside
        exactly like a page that did not load, and two entries naming
        different collections with different counts is that bug on the
        page in front of you."""
        try:
            self._add({
                "kind": "chose",
                "selector_id": _step(selector_id) if " " in str(selector_id)
                else str(selector_id)[:40],
                "collection": _step(collection),
                "candidates": _count(candidates),
                "ordinal": _count(ordinal),
                "precondition": _enum(precondition,
                                      ("visible", "attached", "enabled",
                                       "none"), "none"),
            })
        except Exception:
            pass

    def result(self, outcome: str, error=None, **facts) -> None:
        """How the last thing turned out, as a word from the source."""
        try:
            entry = {"kind": "result", "outcome": _step(outcome)}
            if error is not None:
                entry["error"] = error_kind(error)
            if facts:
                entry["facts"] = _only_safe(facts)
            self._add(entry)
        except Exception:
            pass

    def checkpoint(self, name: str, page=None) -> dict:
        """The page's state at a transition.

        One round trip. Counts for each watched selector, whether the
        page is locked, and how the address changed since the last one."""
        entry = {"kind": "checkpoint", "name": _step(name)}
        page = page or self._page
        try:
            raw = page.evaluate(_WATCH_JS, self._pairs) if page else {}
        except Exception as e:
            entry["evaluation"] = error_kind(e)
            self._add(entry)
            return entry
        if isinstance(raw, dict):
            counts = {}
            for key, value in raw.items():
                if key == "__page":
                    continue
                if isinstance(value, list) and len(value) == 2:
                    counts[str(key)[:40]] = {"matched": _count(value[0]),
                                             "visible": _count(value[1])}
                else:
                    counts[str(key)[:40]] = None
            entry["watching"] = counts
            page_bits = raw.get("__page")
            if isinstance(page_bits, list) and len(page_bits) == 4:
                entry["html_overflow"] = _enum(page_bits[0], _OVERFLOW)
                entry["body_overflow"] = _enum(page_bits[1], _OVERFLOW)
                entry["body_scroll_height"] = _count(page_bits[2])
                entry["ready"] = _enum(page_bits[3], _READY)
        try:
            url = page.url or "" if page else ""
        except Exception:
            url = ""
        entry["route_change"] = _route_change(self._last_url, url)
        self._last_url = url
        self._add(entry)
        return entry

    # -- reading -----------------------------------------------------------

    def report(self) -> dict:
        """The journal as it goes into a failure file."""
        return {"entries": list(self.entries), "dropped_oldest": self.dropped,
                "limit": self.limit}


def summarize(journal: dict) -> list:
    """What a reader should notice, in sentences.

    Read from the journal alone, because the point of keeping one is to
    say something about the layers a run got past before it stopped."""
    said = []
    if not isinstance(journal, dict):
        return said
    entries = [e for e in (journal.get("entries") or []) if isinstance(e, dict)]
    if not entries:
        # No journal is not a finding. An app that does not keep one
        # should not have sentences written about it.
        return said

    # Two collections counted differently, which is the bug that reads
    # like a page that did not load.
    chosen = [e for e in entries if e.get("kind") == "chose"]
    by_selector: dict = {}
    for e in chosen:
        by_selector.setdefault(e.get("selector_id"), set()).add(
            (e.get("collection"), e.get("candidates")))
    for selector, seen in by_selector.items():
        collections = {c for c, _ in seen}
        if len(collections) > 1:
            counts = ", ".join("%s had %s" % (c, n) for c, n in sorted(seen))
            said.append("%s was chosen from more than one collection in the "
                        "same run (%s). Counting one and acting on another is "
                        "a bug that looks from outside like a page that did "
                        "not load." % (selector, counts))
    for e in chosen:
        if e.get("candidates") and e.get("ordinal", 0) >= e["candidates"]:
            said.append("%s took item %d of %d, which is past the end."
                        % (e.get("selector_id"), e["ordinal"], e["candidates"]))

    checks = [e for e in entries if e.get("kind") == "checkpoint"]
    for e in checks:
        if e.get("route_change") == "hash":
            said.append("At \"%s\" only the part after the # changed, so the "
                        "browser loaded nothing. A page that has to be fresh "
                        "has to be asked for." % e.get("name"))
    # A list that was there and then was not.
    for before, after in zip(checks, checks[1:]):
        for name, was in (before.get("watching") or {}).items():
            now = (after.get("watching") or {}).get(name)
            if not isinstance(was, dict) or not isinstance(now, dict):
                continue
            if was.get("visible") and not now.get("visible") and now.get("matched"):
                said.append("Between \"%s\" and \"%s\" the %s stopped being "
                            "visible while still being there. Something hid "
                            "it and did not put it back."
                            % (before.get("name"), after.get("name"), name))
    for e in checks:
        if e.get("body_overflow") == "hidden" or e.get("html_overflow") == "hidden":
            said.append("At \"%s\" scrolling was locked, which is what an "
                        "open dialog does and what makes a rendered document "
                        "come out as one blank screen." % e.get("name"))
            break

    if not any(e.get("phase") == "next_item" for e in entries
               if e.get("kind") == "op"):
        said.append("No second document was attempted, so nothing here says "
                    "whether this provider works more than once.")
    return said[:20]
