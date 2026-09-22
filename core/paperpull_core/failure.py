"""What the page looked like at the moment something failed.

A survey walks the page through the app's own code, so how much it can
see depends on how correct the app already is. On a provider that does
not work yet it says "found nothing" and stops, which is the same thing
the failing run said. That is why a new provider takes eight rounds.

This is the other half. It reads the page directly, asks it only the
questions the app's own selectors raise, and writes what it finds
without anybody having to know to ask for it.

THE SELECTOR CENSUS

Every app already declares the selectors it depends on, in a dictionary
called FALLBACK. For each one this reports how many nodes matched, how
many of those were on screen, and what the first few are. That table is
where the answers live.

    matched 0                   the page has not drawn yet, or the
                                selector is wrong
    matched 1, visible 0        the thing found is not the thing on
                                screen. A framework leaving a hidden
                                copy of a dialog in the markup is the
                                classic, and it cost a day.
    every selector visible 0    something hid the page and did not put
                                it back
    invalid                     the selector is written in Playwright's
                                dialect, which the browser does not
                                speak. Silent until now.

Two selectors that should agree and do not is the last one, and it needs
a person, but the two counts are side by side in the file.

WHAT IS IN IT AND WHAT IS NOT

Everything goes through paperpull_core.redact, the same as a survey or a
recording. Element text is counted rather than quoted, except for the
one block the app was trying to save, which is the thing a maintainer
most needs and is quoted with every number of two digits or more
removed.

No screenshot. A picture cannot be read or edited by the person sending
it, and the whole point is that they can.

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

from .redact import redact

# Playwright understands these on top of CSS and the browser does not, so
# a selector carrying one is a syntax error the moment it reaches
# querySelectorAll. Checked here without running anything, because the
# answer does not need a page.
PLAYWRIGHT_ONLY = (":has-text(", ":has(", ":text(", ":text-is(",
                   ":visible", ":nth-match(", ">>", ":light(", ":right-of(",
                   ":left-of(", ":above(", ":below(", ":near(")

# How much of the page to describe. A census of four hundred nodes is a
# file nobody reads.
_MAX_NODES = 5
_MAX_SELECTORS = 40
_MAX_TEXT = 4000
_MAX_LOG_LINES = 40


# Playwright also accepts a selector that names its engine up front,
# text=Save or xpath=//a. Those are a prefix rather than a fragment, and
# a plain CSS attribute selector like [role=dialog] must not be mistaken
# for one, which is why this is anchored.
PLAYWRIGHT_ENGINES = ("text=", "xpath=", "css=", "id=", "role=",
                      "data-testid=", "data-test-id=", "internal:", "//")


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


# Runs in the page. Plain CSS only, for the reason above.
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
      class: (el.className || '').toString().split(/\s+/).filter(Boolean).slice(0, 4).join(' ').slice(0, 80),
      id: (el.id || '').slice(0, 60),
      role: el.getAttribute('role') || '',
      testid: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '',
      box: [Math.round(r.width), Math.round(r.height)],
      display: s.display,
      visibility: s.visibility,
      text_len: (el.innerText || '').length,
      on_screen: onScreen(el)
    };
  };
  const out = [];
  for (const [name, sel] of selectors) {
    const entry = {name: name, selector: sel};
    let found;
    try {
      found = document.querySelectorAll(sel);
    } catch (e) {
      entry.error = String(e.message || e).slice(0, 200);
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
  // The biggest thing a person can actually see. When everything is
  // hidden this comes back null, which is itself the answer.
  let big = null, most = -1;
  for (const el of document.querySelectorAll('body *')) {
    if (!onScreen(el)) continue;
    const n = (el.innerText || '').length;
    if (n > most) { most = n; big = el; }
  }
  return {
    title: (document.title || '').slice(0, 120),
    ready: document.readyState,
    html_overflow: cs(h).overflow,
    body_overflow: cs(b).overflow,
    body_scroll_height: b ? b.scrollHeight : 0,
    body_text_len: b ? (b.innerText || '').length : 0,
    counts: {
      buttons: document.querySelectorAll('button, [role=button]').length,
      links: document.querySelectorAll('a[href]').length,
      dialogs: document.querySelectorAll('[role=dialog], [aria-modal=true]').length,
      iframes: document.querySelectorAll('iframe').length,
      inputs: document.querySelectorAll('input, select, textarea').length,
      passwords: document.querySelectorAll("input[type=password]").length
    },
    largest_visible: big ? {
      tag: big.tagName.toLowerCase(),
      class: (big.className || '').toString().slice(0, 80),
      text_len: (big.innerText || '').length
    } : null,
    anything_visible: big !== null
  };
}
"""

# Installed once, so a console error that happened before the failure is
# still there to report. The page keeps them on itself.
_COLLECT_ERRORS_JS = r"""
() => {
  if (window.__ppErrors) return "already";
  window.__ppErrors = [];
  const keep = (what) => {
    try {
      if (window.__ppErrors.length < 40) window.__ppErrors.push(String(what).slice(0, 300));
    } catch (e) {}
  };
  window.addEventListener('error', (e) => keep(e.message));
  window.addEventListener('unhandledrejection', (e) => keep('unhandled rejection: ' + (e.reason && e.reason.message || e.reason)));
  return "installed";
}
"""


def watch_errors(page) -> None:
    """Start keeping the page's own errors, for whenever this goes wrong.

    Called once when a run opens its page. Costs nothing if it fails."""
    try:
        page.evaluate(_COLLECT_ERRORS_JS)
    except Exception:
        pass


def census(page, selectors: Optional[dict]) -> list:
    """What the page says about each selector this app depends on."""
    if not isinstance(selectors, dict) or not selectors:
        return []
    pairs, statics = [], {}
    for name, sel in list(selectors.items())[:_MAX_SELECTORS]:
        sel = str(sel or "")
        bad = playwright_only(sel)
        if bad:
            # No need to ask the page. This one can never work there.
            statics[name] = {
                "name": name, "selector": sel[:200],
                "error": "written in Playwright's dialect (%s), which the "
                         "browser does not accept. Valid for page.locator, "
                         "a syntax error inside the page." % bad}
            continue
        pairs.append([name, sel])
    out = list(statics.values())
    if pairs:
        try:
            got = page.evaluate(_CENSUS_JS, pairs) or []
        except Exception as e:
            out.append({"name": "(census)", "error": str(e)[:200]})
            got = []
        for entry in got:
            if isinstance(entry, dict):
                entry["selector"] = str(entry.get("selector") or "")[:200]
                entry["nodes"] = (entry.get("nodes") or [])[:_MAX_NODES]
                out.append(entry)
    return out


def page_state(page) -> dict:
    """The page itself, without going through the app's own navigation."""
    state = {}
    try:
        state["url"] = redact(page.url or "")[:200]
    except Exception:
        state["url"] = ""
    try:
        got = page.evaluate(_PAGE_STATE_JS)
        if isinstance(got, dict):
            state.update(got)
    except Exception as e:
        state["error"] = str(e)[:200]
    try:
        errs = page.evaluate("() => (window.__ppErrors || []).slice(0, 20)")
        if errs:
            state["page_errors"] = [redact(str(e))[:200] for e in errs][:20]
    except Exception:
        pass
    return state


def quote(text: str) -> list:
    """The block the app was trying to save, with the numbers taken out.

    Quoted rather than counted, because what a receipt's lines look like
    is the one thing a maintainer cannot guess and cannot get any other
    way. Every run of two digits or more goes, as does an email and the
    account holder's name."""
    text = redact(str(text or ""))[:_MAX_TEXT]
    text = re.sub(r"\d{2,}", lambda m: "#" * len(m.group(0)), text)
    return [ln.strip() for ln in text.splitlines() if ln.strip()][:120]


def postmortem(page, node_selector: str = "", saved_bytes: int = 0,
               expected_bytes: int = 0) -> dict:
    """Why a rendered document came out wrong.

    "989 bytes" tells a maintainer nothing. "the block it kept measured
    nought by nought while the page behind it was locked" is two bugs at
    once."""
    out = {"saved_bytes": saved_bytes, "expected_at_least": expected_bytes}
    if node_selector:
        try:
            out["kept"] = page.evaluate(
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
                          class: (best.className || '').toString().slice(0, 80),
                          box: [Math.round(r.width), Math.round(r.height)],
                          scroll_height: best.scrollHeight,
                          display: s.display, position: s.position,
                          text_len: (best.innerText || '').length};
                }""", node_selector)
        except Exception as e:
            out["kept"] = {"error": str(e)[:200]}
    return out


def write_failure(diagnostics_dir, command: str, step: str, reason: str,
                  page=None, selectors=None, provider: str = "",
                  version: str = "", text: str = "", extra=None,
                  log_lines=None, say=print) -> Optional[str]:
    """One file, written where the run already writes everything else.

    Returns the path, or None if even this could not be done, which is
    not a reason to fail a run that was failing anyway."""
    from pathlib import Path
    try:
        report = {
            "kind": "paperpull-failure",
            "provider": provider,
            "version": version,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "command": str(command)[:40],
            "step": str(step)[:80],
            "reason": redact(str(reason))[:400],
        }
        if page is not None:
            report["page"] = page_state(page)
            report["selectors"] = census(page, selectors)
        if text:
            report["what_it_was_reading"] = quote(text)
        if isinstance(extra, dict):
            report["extra"] = extra
        if log_lines:
            report["log_tail"] = [redact(str(ln))[:300]
                                  for ln in list(log_lines)[-_MAX_LOG_LINES:]]
        report["note"] = (
            "Written automatically because a step failed. It holds no "
            "keystroke, no cookie and no password, and every number of "
            "two digits or more is masked. Read it through before "
            "attaching it anywhere.")

        out = Path(diagnostics_dir) / ("failure-%s-%s.json" % (
            re.sub(r"[^a-z0-9]+", "-", str(command).lower())[:20] or "run",
            time.strftime("%Y%m%d-%H%M%S")))
        out.parent.mkdir(parents=True, exist_ok=True)
        from .storage import atomic_write_text
        atomic_write_text(out, json.dumps(report, indent=2, default=str))
    except Exception:
        return None
    try:
        say("  Wrote %s" % out)
        say("  That file says what the page looked like when this failed.")
        say("  Read it through, then attach it to the provider's issue.")
    except Exception:
        pass
    return str(out)


def summarize(report: dict) -> list:
    """What a reader should notice first, in sentences.

    The census is the evidence and this is the reading of it. Kept here
    rather than in the maintainer's tool so the person who ran it sees
    the same conclusion."""
    said = []
    if not isinstance(report, dict):
        return said
    entries = [e for e in (report.get("selectors") or []) if isinstance(e, dict)]
    page = report.get("page") or {}

    broken = [e for e in entries if e.get("error")]
    for e in broken:
        said.append("%s cannot work as written. %s"
                    % (e.get("name"), e.get("error")))

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
            said.append("%s matched %d node(s) and none of them were on "
                        "screen. A framework that leaves a hidden copy of a "
                        "dialog in the markup looks exactly like this."
                        % (e.get("name"), e["matched"]))
        elif e.get("matched") == 0:
            said.append("%s matched nothing. Either the page had not drawn "
                        "yet or the selector is wrong." % e.get("name"))

    if page.get("counts", {}).get("passwords"):
        said.append("There is a password field on the page, so the session "
                    "probably ended.")
    if page.get("body_overflow") == "hidden" or page.get("html_overflow") == "hidden":
        said.append("Scrolling is locked on the page, which is what an open "
                    "dialog does, and what makes a rendered document come "
                    "out as one blank screen.")
    pm = (report.get("extra") or {}).get("postmortem") or {}
    kept = pm.get("kept") or {}
    if kept.get("box") == [0, 0]:
        said.append("The block it kept measured nought by nought, so it "
                    "rendered nothing.")
    return said[:20]
