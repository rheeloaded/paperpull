"""What the page looked like at the moment something failed.

A survey walks the page through the app's own code, so how much it can
see depends on how correct the app already is. On a provider that does
not work yet it says "found nothing" and stops, which is the same thing
the failing run said. That is why a new provider takes eight rounds.

This is the other half. It reads the page directly, asks it only the
questions the app's own selectors raise, and writes what it finds
without anybody having to know to ask for it.

SAFE BY CONSTRUCTION, NOT BY SCRUBBING

The first version of this file collected what looked useful and ran it
through redaction. A canary page carrying a distinctive fake secret in
every channel a browser offers proved that wrong. Eleven of twenty one
came out. A name through the page title. A street and a card tail
through the receipt's own text, because they are words and the masking
knew about digits. An element id and a class, straight out.

So nothing here is scrubbed. **Only these kinds of thing may leave.**

    an enum          a tag name from a fixed list, a CSS display value
    a boolean        was it on screen, was the page locked
    a bounded count  how many nodes matched, how many lines parsed
    a duration       how long a wait took
    a name we wrote  the key of an entry in the app's own FALLBACK table

Everything else the browser can give is denied. No page text, no title,
no attribute value, no id, no class except the handful of framework
words below, no URL, no console message, no log line. A field that is
not on the list does not reach the file, so a provider added tomorrow
cannot widen it by accident.

The one exception is proved rather than assumed. A class is the single
most diagnostic thing a framework leaks, and `div.modal.fade` was the
answer to a bug that cost a day. So the class is reduced to whichever
of a fixed vocabulary of layout words it contains, and the rest of it
is thrown away.

Held by test_failure_canary.py, which rebuilds that page and asserts
that none of its secrets comes out.

NOTHING HERE MAY RAISE

It runs when something has already gone wrong, and a diagnostic that
fails in the middle of a failure costs the round it was meant to save.
Every call is wrapped.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

# Playwright understands these on top of CSS and the browser does not, so
# a selector carrying one is a syntax error the moment it reaches
# querySelectorAll. Checked here without running anything, because the
# answer does not need a page.
PLAYWRIGHT_ONLY = (":has-text(", ":has(", ":text(", ":text-is(",
                   ":visible", ":nth-match(", ">>", ":light(", ":right-of(",
                   ":left-of(", ":above(", ":below(", ":near(")

# Playwright also accepts a selector that names its engine up front,
# text=Save or xpath=//a. Those are a prefix rather than a fragment, and
# a plain CSS attribute selector like [role=dialog] must not be mistaken
# for one, which is why this is anchored.
PLAYWRIGHT_ENGINES = ("text=", "xpath=", "css=", "id=", "role=",
                      "data-testid=", "data-test-id=", "internal:", "//")

# A tag name outside this list becomes "other". A custom element can be
# named after anything, including a company or a person.
SAFE_TAGS = frozenset("""
a abbr article aside b body button canvas caption col colgroup dd details
dialog div dl dt em fieldset figure footer form h1 h2 h3 h4 h5 h6 header
hr i iframe img input label legend li main nav ol optgroup option output
p picture pre section select small span strong sub summary sup svg table
tbody td textarea tfoot th thead time tr u ul video
""".split())

# The only words that may come out of a class attribute. Layout and state
# vocabulary that a framework writes and a person never does. A class of
# "customer-4821-panel" reduces to nothing at all.
SIGNAL_CLASSES = frozenset("""
modal dialog popup popover drawer sheet overlay backdrop scrim lightbox
fade show shown hide hidden visible invisible open opened close closed
collapse collapsed expand expanded active inactive disabled enabled
selected current loading spinner skeleton placeholder
sticky fixed absolute relative
container wrapper content inner outer header footer sidebar main
row column grid list item card panel table cell
tab tabs tabpanel menu dropdown accordion
print printable noprint screen-only print-only
""".split())

# What went wrong, as a word rather than as whatever the exception said.
# A message can carry a URL, an element's text, or an account number.
ERROR_KINDS = (
    ("timeout", ("timeout", "timed out", "exceeded")),
    ("navigation", ("navigation", "net::", "err_", "navigating")),
    ("detached", ("detached", "execution context", "destroyed", "closed")),
    ("selector", ("not a valid selector", "failed to execute 'queryselector",
                  "syntaxerror")),
    ("not_found", ("no element", "not found", "waiting for selector",
                   "resolved to 0")),
    ("blocked", ("intercepts pointer events", "not visible", "not enabled",
                 "not stable")),
)

_MAX_NODES = 5
_MAX_SELECTORS = 40
_MAX_COUNT = 100000


def error_kind(err) -> str:
    """One word for what went wrong. Never the message itself."""
    text = ""
    try:
        text = ("%s %s" % (type(err).__name__, err)).lower()
    except Exception:
        return "unknown"
    for kind, words in ERROR_KINDS:
        if any(w in text for w in words):
            return kind
    return "unknown"


def playwright_only(selector: str) -> str:
    """The Playwright-only part of this selector, or "". """
    selector = (selector or "").strip()
    for engine in PLAYWRIGHT_ENGINES:
        if selector.startswith(engine):
            return engine
    for bad in PLAYWRIGHT_ONLY:
        if bad in selector:
            return bad
    return ""


def _count(value) -> int:
    """A count, bounded, or zero. Never a length that encodes a secret."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, _MAX_COUNT))


def _tag(value) -> str:
    v = str(value or "").lower().strip()
    return v if v in SAFE_TAGS else "other"


def _classes(value) -> list:
    """Whichever layout words this class carries, and nothing else.

    Whole tokens. Splitting on hyphens as well would let a class of
    "customer-4821-panel" report itself as a panel, which leaks nothing
    because the word comes from the vocabulary below, and is still a
    sentence about an element that said no such thing."""
    words = str(value or "").lower().split()
    return sorted({w for w in words if w in SIGNAL_CLASSES})[:6]


def _enum(value, allowed, fallback="other") -> str:
    v = str(value or "").lower().strip()
    return v if v in allowed else fallback


_DISPLAY = frozenset("""block inline inline-block flex inline-flex grid
inline-grid none contents table table-cell table-row list-item flow-root""".split())
_VISIBILITY = frozenset(("visible", "hidden", "collapse"))
_POSITION = frozenset(("static", "relative", "absolute", "fixed", "sticky"))
_OVERFLOW = frozenset(("visible", "hidden", "scroll", "auto", "clip"))


def _node(raw) -> dict:
    """One element, as shape and state only."""
    if not isinstance(raw, dict):
        return {}
    box = raw.get("box")
    box = [_count(box[0]), _count(box[1])] if isinstance(box, list) and len(box) == 2 else [0, 0]
    return {
        "tag": _tag(raw.get("tag")),
        "signal_classes": _classes(raw.get("class")),
        "has_id": bool(raw.get("has_id")),
        "has_testid": bool(raw.get("has_testid")),
        "role": _enum(raw.get("role"), _ROLES, "" if not raw.get("role") else "other"),
        "box": box,
        "display": _enum(raw.get("display"), _DISPLAY),
        "visibility": _enum(raw.get("visibility"), _VISIBILITY),
        "position": _enum(raw.get("position"), _POSITION),
        "text_len": _count(raw.get("text_len")),
        "on_screen": bool(raw.get("on_screen")),
    }


# An ARIA role is from a fixed vocabulary, so it is a word we could have
# written ourselves. Anything outside it becomes "other".
_ROLES = frozenset("""
alert alertdialog application article banner button cell checkbox columnheader
combobox complementary contentinfo definition dialog directory document feed
figure form grid gridcell group heading img link list listbox listitem log
main marquee math menu menubar menuitem menuitemcheckbox menuitemradio
navigation none note option presentation progressbar radio radiogroup region
row rowgroup rowheader scrollbar search searchbox separator slider spinbutton
status switch tab table tablist tabpanel term textbox timer toolbar tooltip
tree treegrid treeitem
""".split())


# Runs in the page. Plain CSS only, for the reason above. It returns
# more than leaves this module, and everything it returns is filtered
# above before it reaches the file.
_CENSUS_JS = r"""
(selectors) => {
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const describe = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(),
      class: (el.className || '').toString().slice(0, 200),
      has_id: !!el.id,
      has_testid: !!(el.getAttribute('data-testid') || el.getAttribute('data-test-id')),
      role: el.getAttribute('role') || '',
      box: [Math.round(r.width), Math.round(r.height)],
      display: s.display, visibility: s.visibility, position: s.position,
      text_len: (el.innerText || '').length,
      on_screen: onScreen(el)
    };
  };
  const out = [];
  for (const [name, sel] of selectors) {
    const entry = {name: name};
    let found;
    try {
      found = document.querySelectorAll(sel);
    } catch (e) {
      entry.evaluation = 'invalid_css_selector';
      out.push(entry);
      continue;
    }
    entry.matched = found.length;
    entry.visible = 0;
    entry.nodes = [];
    let i = 0;
    for (const el of found) {
      if (onScreen(el)) entry.visible += 1;
      if (i < 5) entry.nodes.push(describe(el));
      i += 1;
    }
    out.push(entry);
  }
  return out;
}
"""

_PAGE_STATE_JS = r"""
() => {
  const cs = (el) => el ? getComputedStyle(el) : {};
  const h = document.documentElement, b = document.body;
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  let big = null, most = -1, visible = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (!onScreen(el)) continue;
    visible += 1;
    const n = (el.innerText || '').length;
    if (n > most) { most = n; big = el; }
  }
  return {
    ready: document.readyState,
    html_overflow: cs(h).overflow,
    body_overflow: cs(b).overflow,
    body_scroll_height: b ? b.scrollHeight : 0,
    body_text_len: b ? (b.innerText || '').length : 0,
    visible_elements: visible,
    counts: {
      buttons: document.querySelectorAll('button, [role=button]').length,
      links: document.querySelectorAll('a[href]').length,
      dialogs: document.querySelectorAll('[role=dialog], [aria-modal=true]').length,
      iframes: document.querySelectorAll('iframe').length,
      inputs: document.querySelectorAll('input, select, textarea').length,
      passwords: document.querySelectorAll("input[type=password]").length
    },
    largest_visible: big ? {tag: big.tagName.toLowerCase(),
                            class: (big.className || '').toString().slice(0, 200),
                            text_len: (big.innerText || '').length} : null
  };
}
"""

_COUNT_ERRORS_JS = r"""
() => {
  if (window.__ppErrorCount !== undefined) return "already";
  window.__ppErrorCount = 0;
  window.__ppRejectCount = 0;
  window.addEventListener('error', () => { window.__ppErrorCount += 1; });
  window.addEventListener('unhandledrejection', () => { window.__ppRejectCount += 1; });
  return "installed";
}
"""


def watch_errors(page) -> None:
    """Count the page's own errors, for whenever this goes wrong.

    Counted and never read. An exception's message is written by the
    site and can carry anything that was on the page."""
    try:
        page.evaluate(_COUNT_ERRORS_JS)
    except Exception:
        pass


def census(page, selectors: Optional[dict]) -> list:
    """What the page says about each selector this app depends on.

    The name of each entry is the key the app wrote in its own FALLBACK
    table, so it is a word from the source and not from the account.
    The selector string itself is source-written too, and is kept
    because an engine mismatch is invisible without it."""
    if not isinstance(selectors, dict) or not selectors:
        return []
    pairs, out = [], []
    for name, sel in list(selectors.items())[:_MAX_SELECTORS]:
        name, sel = str(name)[:40], str(sel or "")
        bad = playwright_only(sel)
        if bad:
            out.append({"name": name, "declared_engine": "playwright",
                        "evaluation": "playwright_only_syntax",
                        "syntax": bad,
                        "note": "valid for page.locator, a syntax error "
                                "inside the page"})
            continue
        pairs.append([name, sel])
    if pairs:
        try:
            got = page.evaluate(_CENSUS_JS, pairs) or []
        except Exception as e:
            out.append({"name": "(census)", "evaluation": error_kind(e)})
            got = []
        for raw in got:
            if not isinstance(raw, dict):
                continue
            entry = {"name": str(raw.get("name"))[:40],
                     "declared_engine": "css"}
            if raw.get("evaluation"):
                entry["evaluation"] = str(raw["evaluation"])[:40]
            else:
                entry["matched"] = _count(raw.get("matched"))
                entry["visible"] = _count(raw.get("visible"))
                entry["nodes"] = [_node(n) for n in (raw.get("nodes") or [])][:_MAX_NODES]
            out.append(entry)
    return out


def page_state(page) -> dict:
    """The page itself, as counts and enums."""
    state = {}
    try:
        raw = page.evaluate(_PAGE_STATE_JS)
    except Exception as e:
        return {"evaluation": error_kind(e)}
    if not isinstance(raw, dict):
        return {}
    state["ready"] = _enum(raw.get("ready"),
                           ("loading", "interactive", "complete"))
    state["html_overflow"] = _enum(raw.get("html_overflow"), _OVERFLOW)
    state["body_overflow"] = _enum(raw.get("body_overflow"), _OVERFLOW)
    state["body_scroll_height"] = _count(raw.get("body_scroll_height"))
    state["body_text_len"] = _count(raw.get("body_text_len"))
    state["visible_elements"] = _count(raw.get("visible_elements"))
    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    state["counts"] = {k: _count(v) for k, v in list(counts.items())[:12]}
    big = raw.get("largest_visible")
    state["largest_visible"] = _node(dict(big, on_screen=True)) if isinstance(big, dict) else None
    state["anything_visible"] = state["largest_visible"] is not None
    for key, js in (("page_errors", "__ppErrorCount"),
                    ("page_rejections", "__ppRejectCount")):
        try:
            state[key] = _count(page.evaluate("() => window.%s || 0" % js))
        except Exception:
            pass
    return state


def postmortem(page, node_selector: str = "", saved_bytes: int = 0,
               expected_bytes: int = 0) -> dict:
    """Why a rendered document came out wrong.

    "989 bytes" tells a maintainer nothing. "the block it kept measured
    nought by nought while the page behind it was locked" is two bugs at
    once."""
    out = {"saved_bytes": _count(saved_bytes),
           "expected_at_least": _count(expected_bytes)}
    if not node_selector or playwright_only(node_selector):
        return out
    try:
        raw = page.evaluate(
            "(sel) => {" + """
              let best = null, most = -1;
              for (const el of document.querySelectorAll(sel)) {
                const n = (el.innerText || '').length;
                if (n > most) { most = n; best = el; }
              }
              if (!best) return null;
              const r = best.getBoundingClientRect();
              const s = getComputedStyle(best);
              return {tag: best.tagName.toLowerCase(),
                      class: (best.className || '').toString().slice(0, 200),
                      box: [Math.round(r.width), Math.round(r.height)],
                      scroll_height: best.scrollHeight,
                      display: s.display, visibility: s.visibility,
                      position: s.position,
                      text_len: (best.innerText || '').length,
                      on_screen: true};
            }""", node_selector)
    except Exception as e:
        out["evaluation"] = error_kind(e)
        return out
    if isinstance(raw, dict):
        kept = _node(raw)
        kept["scroll_height"] = _count(raw.get("scroll_height"))
        out["kept"] = kept
    else:
        out["kept"] = None
    return out


def parser_counts(candidates: int = 0, accepted: int = 0,
                  rejected: Optional[dict] = None) -> dict:
    """Why the lines on a document did not become items.

    A count of what was thrown away and why says the same thing quoting
    the lines would, and says it without any of them. A parser that
    insisted on a currency sign against a till that prints none reads as
    twelve candidates, nothing accepted, twelve with no currency sign."""
    out = {"candidates": _count(candidates), "accepted": _count(accepted)}
    if isinstance(rejected, dict):
        out["rejected"] = {
            re.sub(r"[^a-z0-9 ]+", " ", str(k).lower()).strip()[:40]: _count(v)
            for k, v in list(rejected.items())[:12]}
    return out


# The words an app may use to say what it was doing. A step is lowercase
# prose written in the source, "open the receipt", and this keeps it that
# way. A capital is what tells it from a sentence off a page, which is
# why the value is matched before it is lowered and not after.
_STEP_RE = re.compile(r"^[a-z][a-z ]{2,60}$")


def _step(value) -> str:
    v = re.sub(r"\s+", " ", str(value or "")).strip()
    return v if _STEP_RE.match(v) else "unnamed step"


def write_failure(diagnostics_dir, command: str, step: str, reason: str = "",
                  page=None, selectors=None, provider: str = "",
                  version: str = "", error=None, extra=None, journal=None,
                  requests=None, say=print, **ignored) -> Optional[str]:
    """One file, written where the run already writes everything else.

    `step` and `reason` are written by the app, in its own source, and
    must never be built from anything the page said. An exception goes
    in `error` and becomes one word.

    Returns the path, or None if even this could not be done, which is
    not a reason to fail a run that was failing anyway."""
    from pathlib import Path
    try:
        report = {
            "kind": "paperpull-failure",
            "schema": 2,
            "provider": str(provider)[:40],
            "version": str(version)[:20],
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "command": re.sub(r"[^a-z-]+", "", str(command).lower())[:20] or "run",
            "step": _step(step),
            "reason": _step(reason) if reason else "",
        }
        if error is not None:
            report["error"] = error_kind(error)
        if page is not None:
            report["page"] = page_state(page)
            report["selectors"] = census(page, selectors)
        if isinstance(extra, dict):
            report["extra"] = _only_safe(extra)
        if requests is not None:
            # The eleven apps that drive an API declare no selectors, so
            # the census above has nothing to say about them. This is
            # their half of it.
            try:
                report["requests"] = requests.report()
            except Exception:
                pass
        if journal is not None:
            # The census says what the page looked like when the run
            # gave up. This says what it looked like on the way there,
            # which is the only thing that can speak for a layer the run
            # never reached.
            try:
                report["journal"] = journal.report()
            except Exception:
                pass
        report["note"] = (
            "Written automatically because a step failed. It holds counts "
            "and states and no text from the page, so there is nothing in "
            "it from your account. Read it through before attaching it.")

        out = Path(diagnostics_dir) / ("failure-%s-%s.json" % (
            report["command"], time.strftime("%Y%m%d-%H%M%S")))
        out.parent.mkdir(parents=True, exist_ok=True)
        from .storage import atomic_write_text
        atomic_write_text(out, json.dumps(report, indent=2))
    except Exception:
        return None
    try:
        say("")
        say("  This run wrote a file about what went wrong:")
        say("    %s" % out)
        say("  It holds counts and states and no text from your account, so")
        say("  there is nothing in it from your statements or receipts.")
    except Exception:
        pass
    return str(out)


def _only_safe(value, depth: int = 0):
    """Numbers, booleans and words we wrote. Nothing else gets through.

    An app that starts handing this a page's text does not widen the
    file, it loses the field."""
    if depth > 4:
        return None
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return _count(value)
    if isinstance(value, float):
        return round(float(value), 3)
    if isinstance(value, str):
        # Only a word an app could have written in its own source.
        return value[:60] if _STEP_RE.match(value.lower().strip()) else None
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:20]:
            key = re.sub(r"[^a-z0-9_]+", "_", str(k).lower())[:40]
            # Kept as null rather than dropped, so a reader can see that
            # a field was offered and refused instead of wondering where
            # it went.
            out[key] = _only_safe(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_only_safe(v, depth + 1) for v in list(value)[:20]]
    return None


def summarize(report: dict) -> list:
    """What a reader should notice first, in sentences."""
    said = []
    if not isinstance(report, dict):
        return said
    entries = [e for e in (report.get("selectors") or []) if isinstance(e, dict)]
    page = report.get("page") or {}

    for e in entries:
        if e.get("evaluation") == "playwright_only_syntax":
            said.append("%s is written in Playwright's dialect (%s). That is "
                        "valid for page.locator and a syntax error inside the "
                        "page, so it matches nothing there and says nothing "
                        "about it." % (e.get("name"), e.get("syntax")))
        elif e.get("evaluation") == "invalid_css_selector":
            said.append("%s is not a selector the browser accepts."
                        % e.get("name"))

    checked = [e for e in entries if "matched" in e]
    if checked and all(e.get("visible") == 0 for e in checked):
        if page.get("anything_visible") is False:
            said.append("Nothing on the page was visible at all, so "
                        "something hid it and did not put it back. On a run "
                        "that saves more than one document, look at what the "
                        "one before it left behind.")
        else:
            said.append("Every selector this app uses matched nothing that "
                        "was on screen.")
    for e in checked:
        if e.get("matched") and not e.get("visible"):
            words, roles = set(), set()
            for n in e.get("nodes") or []:
                words.update(n.get("signal_classes") or [])
                if n.get("role"):
                    roles.add(n["role"])
            # Only when the thing found looks like a dialog. An input of
            # type hidden matching nothing visible is an input of type
            # hidden, and saying otherwise every time is how a file stops
            # being read.
            dialogish = ({"modal", "dialog", "popup", "popover", "drawer",
                          "overlay", "lightbox"} & words) or ("dialog" in roles)
            if dialogish:
                said.append("%s matched %d node(s) and none of them were on "
                            "screen, and what it found is a %s. A framework "
                            "that leaves a hidden copy of a dialog in the "
                            "markup looks exactly like this."
                            % (e.get("name"), e["matched"],
                               ".".join(sorted(words)[:4]) or "dialog"))
            else:
                said.append("%s matched %d node(s) and none of them were on "
                            "screen." % (e.get("name"), e["matched"]))
        elif e.get("matched") == 0:
            said.append("%s matched nothing. Either the page had not drawn "
                        "yet or the selector is wrong." % e.get("name"))

    if (page.get("counts") or {}).get("passwords"):
        said.append("There is a password field on the page, so the session "
                    "probably ended.")
    if "hidden" in (page.get("body_overflow"), page.get("html_overflow")):
        said.append("Scrolling is locked on the page, which is what an open "
                    "dialog does, and what makes a rendered document come "
                    "out as one blank screen.")

    extra = report.get("extra") or {}
    kept = (extra.get("postmortem") or {}).get("kept") or {}
    if kept.get("box") == [0, 0]:
        said.append("The block it kept measured nought by nought, so it "
                    "rendered nothing.")
    from .api_census import summarize as _requests_said
    said.extend(_requests_said(report.get("requests") or {}))

    from .journal import summarize as _journal_said
    said.extend(_journal_said(report.get("journal") or {}))

    parser = extra.get("parser") or {}
    if parser.get("candidates") and not parser.get("accepted"):
        why = parser.get("rejected") or {}
        top = max(why, key=why.get) if why else ""
        said.append("%d line(s) looked like items and none were accepted%s."
                    % (parser["candidates"],
                       ", all of them for %s" % top.replace("_", " ") if top else ""))
    return said[:20]
