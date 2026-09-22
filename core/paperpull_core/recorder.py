"""What the person did, so an app can be written to do the same.

A survey describes a page. It is a good description and it is still a
guess, because it cannot know which control the account holder would
click, or in what order, or what the site does in between. AT&T took
seven rounds of guessing. This records the answer instead.

The tester signs in themselves, presses Record, clicks their way to a
statement once, and presses Stop. What comes out is a list of steps and
the requests each step caused. The maintainer reads it and writes the
site layer. One round.

    from paperpull_core.recorder import Recorder

    rec = Recorder(page, is_safe_url=site.is_safe_url,
                   looks_signed_out=site.looks_signed_out,
                   owner=config.get("owner", ""))
    rec.start()
    input("Click through to a statement, then press Enter... ")
    report = rec.stop()

WHAT IS RECORDED

    a click            on a control, named the way a person reads it
    a selection        a dropdown, and which option was chosen
    a checkbox         and whether it ended up checked
    a navigation       when the address changed
    a new tab          and whether it was still on the provider's site
    a download         that a step set off
    the requests       each step caused, as names and shapes

WHAT IS NOT, AND CANNOT BE

No keystrokes. Not filtered afterwards, not masked, not collected at
all. There is no keydown or input listener in this module, so a
password, a card number or a search term has nothing to be captured by.
A typed field that changes is recorded as having been typed into, and
its value is the word [REDACTED], which is a constant in this file and
never the field's contents.

No cookies, no headers, no storage. This module never calls cookies(),
storage_state() or anything that reads them, so a recording cannot carry
a session even by accident.

No page text beyond a control's own label, and everything that does come
out goes through paperpull_core.redact first.

WHERE IT REFUSES TO RUN

Before the account holder is signed in. start() checks the page is on
the provider's own host, that the app does not think it is signed out,
and that there is no password field on it. A recorder that can be
switched on at a sign-in screen is a keylogger with good intentions, so
this one cannot be.

HOW A CONTROL IS NAMED

Role and accessible name first, "the link called Bill and payment
history", because that is what survives a site's next deploy. Then a
test id, an aria-label, a stable id, a name attribute, then the visible
text. Never a class, never a position among siblings. A control that
answers to none of those is recorded as unresolved, which tells the
maintainer this provider needs a different approach.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .redact import redact, safe_query, shape_of

# The only thing a typed value is ever recorded as.
REDACTED = "[REDACTED]"

# Two clicks on the same control this close together are one click.
_REPEAT_MS = 400

# A click on one of these that did not resolve to a role is the mouse
# landing on the page rather than on a control. A heading, a paragraph,
# a cell. If such an element carries a role or a test id the walk-up in
# the page finds it and the locator is not "text", so this never drops a
# real control that happens to be a div.
_NOT_A_CONTROL = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "div",
                  "li", "td", "th", "tr", "section", "article", "main",
                  "header", "footer", "label", "strong", "em", "small"}

_MAX_STEPS = 400
_MAX_REQUESTS = 300


# ---------------------------------------------------------------------------
# What runs in the page
# ---------------------------------------------------------------------------
# Capture-phase listeners for click, change and submit, and nothing else.
# It names the control it fired on and posts that back. It reads no page
# text beyond the control's own label, and no input value ever leaves it.
_CAPTURE_JS = r"""
(bindingName) => {
  if (window.__ppRecorderInstalled) return "already";
  window.__ppRecorderInstalled = true;
  const post = window[bindingName];

  const HASHY = /(?:[0-9]{6,})|(?:^|[-_])[a-f0-9]{8,}(?:$|[-_])|(?:ng-|css-|sc-|jsx-|emotion-)/i;
  const stable = (v) => !!v && v.length < 80 && !HASHY.test(v);

  const roleOf = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit.trim().split(/\s+/)[0];
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : null;
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "summary") return "button";
    if (tag === "input") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (t === "submit" || t === "button" || t === "reset") return "button";
      return "textbox";
    }
    return null;
  };

  // The accessible name, the way a screen reader would say it.
  const nameOf = (el) => {
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) return label.trim();
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const parts = by.split(/\s+/)
        .map((id) => (el.ownerDocument.getElementById(id) || {}).textContent || "")
        .join(" ").trim();
      if (parts) return parts;
    }
    if (el.tagName.toLowerCase() === "input" && el.labels && el.labels.length)
      return (el.labels[0].textContent || "").trim();
    const alt = el.getAttribute("alt");
    if (alt && alt.trim()) return alt.trim();
    const title = el.getAttribute("title");
    if (title && title.trim()) return title.trim();
    const text = (el.innerText || el.textContent || "").trim();
    if (text) return text.replace(/\s+/g, " ");
    const val = el.getAttribute("value");
    // A button's own caption, never a text field's contents.
    const t = (el.getAttribute("type") || "").toLowerCase();
    if (val && (t === "submit" || t === "button" || t === "reset")) return val.trim();
    return "";
  };

  // In preference order. Never a class, never a position among siblings.
  const locate = (el) => {
    const role = roleOf(el);
    const name = nameOf(el).slice(0, 80);
    if (role && name) return { how: "role", role: role, name: name };
    const testid = el.getAttribute("data-testid") || el.getAttribute("data-test-id")
                || el.getAttribute("data-qa") || el.getAttribute("data-cy");
    if (stable(testid)) return { how: "testid", value: testid };
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) return { how: "label", value: label.trim().slice(0, 80) };
    if (stable(el.id)) return { how: "id", value: el.id };
    const nm = el.getAttribute("name");
    if (stable(nm)) return { how: "name", value: nm };
    if (name) return { how: "text", value: name };
    return { how: "unresolved", tag: el.tagName.toLowerCase() };
  };

  // Up from the event target to the thing a person would say they clicked.
  const control = (start) => {
    let el = start;
    for (let i = 0; el && i < 6; i++) {
      if (el.nodeType === 1 && (roleOf(el) || el.getAttribute("data-testid")))
        return el;
      el = el.parentElement;
    }
    return start && start.nodeType === 1 ? start : null;
  };

  const send = (record) => { try { post(record); } catch (e) {} };

  document.addEventListener("click", (ev) => {
    const el = control(ev.target);
    if (!el) return;
    const tag = el.tagName.toLowerCase();
    if (tag === "html" || tag === "body") return;   // a click on nothing
    send({ action: "click", locator: locate(el), tag: tag,
           label: nameOf(el).slice(0, 120), at: Date.now() });
  }, true);

  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (!el || el.nodeType !== 1) return;
    const tag = el.tagName.toLowerCase();
    const loc = locate(el);
    const label = nameOf(el).slice(0, 120);
    if (tag === "select") {
      const opt = el.options && el.options[el.selectedIndex];
      // The option's visible label. A statement picker's options are
      // dates and years, which is the signal, and it is redacted in
      // Python on the way out like everything else.
      send({ action: "select", locator: loc, label: label,
             option: opt ? (opt.textContent || "").trim().slice(0, 60) : "",
             at: Date.now() });
      return;
    }
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox" || type === "radio") {
      send({ action: "check", locator: loc, label: label,
             checked: !!el.checked, at: Date.now() });
      return;
    }
    // A typed field. That it was typed into is the fact worth keeping.
    // What was typed is never read.
    send({ action: "fill", locator: loc, label: label, at: Date.now() });
  }, true);

  document.addEventListener("submit", (ev) => {
    const el = ev.target;
    send({ action: "submit", locator: el ? locate(el) : { how: "unresolved" },
           at: Date.now() });
  }, true);

  return "installed";
}
"""


class Recorder:
    """One recording, on one page, of one person's path to a document."""

    def __init__(self, page, *,
                 is_safe_url: Callable[[str], bool],
                 looks_signed_out: Optional[Callable] = None,
                 is_safe_control: Optional[Callable[[str], bool]] = None,
                 provider: str = ""):
        self.page = page
        self._is_safe_url = is_safe_url
        self._looks_signed_out = looks_signed_out
        self._is_safe_control = is_safe_control
        self.provider = provider
        self.steps: list = []
        self.requests: list = []
        self.dropped = {"repeat": 0, "unresolved": 0, "off_host_request": 0}
        self._binding = "__ppRecorderPost"
        self._started = False
        self._stopped = False

    # -- gating ------------------------------------------------------------

    def refusal(self) -> Optional[str]:
        """Why this page may not be recorded, or None. Public so an app can
        say it before offering the button."""
        try:
            url = self.page.url or ""
        except Exception:
            return "the page could not be read"
        if not self._is_safe_url(url):
            return ("this is not a page on the provider's own site, so nothing "
                    "here would be recorded")
        if self._looks_signed_out is not None:
            try:
                if self._looks_signed_out(self.page):
                    return "sign in first, then start recording"
            except Exception:
                pass
        try:
            if self.page.locator("input[type='password']").count() > 0:
                return ("there is a password field on this page, so recording "
                        "will not start here. Finish signing in first.")
        except Exception:
            pass
        return None

    # -- running -----------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        why = self.refusal()
        if why:
            raise RuntimeError(why)
        self.page.expose_binding(self._binding, self._on_event)
        self._install()
        self.page.on("framenavigated", self._on_navigated)
        self.page.on("response", self._on_response)
        self.page.on("download", self._on_download)
        try:
            self.page.context.on("page", self._on_new_tab)
        except Exception:
            pass
        self._started = True

    def _install(self) -> None:
        """The capture script, put back after every navigation because a new
        document does not keep it. It is idempotent."""
        try:
            self.page.evaluate(_CAPTURE_JS, self._binding)
        except Exception:
            pass

    def stop(self) -> dict:
        if self._stopped:
            return self.report()
        for event, handler in (("framenavigated", self._on_navigated),
                               ("response", self._on_response),
                               ("download", self._on_download)):
            try:
                self.page.remove_listener(event, handler)
            except Exception:
                pass
        try:
            self.page.context.remove_listener("page", self._on_new_tab)
        except Exception:
            pass
        # The page keeps its listeners until it navigates, so they are told
        # to stop posting. Nothing is left running in the user's browser.
        try:
            self.page.evaluate("() => { window.__ppRecorderPost = () => {}; }")
        except Exception:
            pass
        self._stopped = True
        return self.report()

    # -- what comes back from the page ------------------------------------

    def _on_event(self, source, record) -> None:
        if not isinstance(record, dict) or len(self.steps) >= _MAX_STEPS:
            return
        action = str(record.get("action") or "")
        if action not in ("click", "select", "check", "fill", "submit"):
            return
        loc = record.get("locator") or {}
        label = str(record.get("label") or "")

        # A click that landed on nothing nameable, or on a heading or a
        # paragraph, is the mouse wandering rather than a step.
        if action == "click" and loc.get("how") in ("unresolved", "text"):
            if not label.strip() or str(record.get("tag") or "") in _NOT_A_CONTROL:
                self.dropped["unresolved"] += 1
                return

        step = {
            "i": len(self.steps),
            "action": action,
            "locator": self._clean_locator(loc),
            "label": redact(label)[:120],
            "at": record.get("at"),
        }
        if action == "select":
            step["option"] = redact(str(record.get("option") or ""))[:60]
        if action == "check":
            step["checked"] = bool(record.get("checked"))
        if action == "fill":
            # Never the value. There is no value here to redact.
            step["value"] = REDACTED
        if self._is_safe_control is not None and label.strip():
            try:
                step["guard_allows"] = bool(self._is_safe_control(label))
            except Exception:
                pass
        if self._is_repeat(step):
            self.dropped["repeat"] += 1
            return
        # A checkbox or a dropdown fires a click and then a change, and
        # the change is the one that says what happened. The click before
        # it on the same control is the same act, not a second one.
        self._absorb_click_before(step)
        step["effect"] = {"navigated": False, "new_tab": False,
                          "download": False, "requests": 0}
        self.steps.append(step)

    def _absorb_click_before(self, step: dict) -> None:
        if step["action"] not in ("select", "check") or not self.steps:
            return
        last = self.steps[-1]
        if last["action"] != "click" or last["locator"] != step["locator"]:
            return
        try:
            close = abs(int(step.get("at") or 0) - int(last.get("at") or 0)) < _REPEAT_MS
        except (TypeError, ValueError):
            close = False
        if close:
            self.steps.pop()
            self.dropped["repeat"] += 1
            step["i"] = len(self.steps)

    def _clean_locator(self, loc: dict) -> dict:
        out = {"how": str(loc.get("how") or "unresolved")}
        for key in ("role", "name", "value", "tag"):
            if loc.get(key):
                out[key] = redact(str(loc[key]))[:80]
        return out

    def _is_repeat(self, step: dict) -> bool:
        if not self.steps:
            return False
        last = self.steps[-1]
        if last["action"] != step["action"] or last["locator"] != step["locator"]:
            return False
        try:
            return abs(int(step.get("at") or 0) - int(last.get("at") or 0)) < _REPEAT_MS
        except (TypeError, ValueError):
            return False

    # -- what the page did in response ------------------------------------

    def _current(self) -> Optional[dict]:
        return self.steps[-1] if self.steps else None

    def _on_navigated(self, frame) -> None:
        try:
            if frame != self.page.main_frame:
                return
        except Exception:
            return
        step = self._current()
        if step is not None:
            step["effect"]["navigated"] = True
            step["effect"]["landed_on"] = redact(frame.url or "")[:160]
        self._install()

    def _on_new_tab(self, page) -> None:
        step = self._current()
        if step is None:
            return
        step["effect"]["new_tab"] = True
        try:
            step["effect"]["new_tab_off_host"] = not self._is_safe_url(page.url or "")
        except Exception:
            pass

    def _on_download(self, download) -> None:
        step = self._current()
        if step is None:
            return
        step["effect"]["download"] = True
        try:
            step["effect"]["download_name"] = redact(
                download.suggested_filename or "")[:80]
        except Exception:
            pass

    def _on_response(self, response) -> None:
        """The JSON and PDF a step set off, as names and shapes. A request
        to anywhere but the provider is counted and not described."""
        if len(self.requests) >= _MAX_REQUESTS:
            return
        try:
            url = response.url or ""
            if not self._is_safe_url(url):
                self.dropped["off_host_request"] += 1
                return
            kind = (response.headers.get("content-type") or "").lower()
            if "json" not in kind and "pdf" not in kind:
                return
            step = self._current()
            entry = {
                "step": step["i"] if step else None,
                "url": redact(url)[:200],
                "status": response.status,
                "type": kind[:40],
            }
            query = safe_query(url)
            if query:
                entry["query"] = query[:240]
            try:
                entry["method"] = response.request.method
                body = response.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            if "json" in kind:
                try:
                    entry["shape"] = shape_of(response.json())
                except Exception:
                    entry["shape"] = "unreadable"
            self.requests.append(entry)
            if step is not None:
                step["effect"]["requests"] += 1
        except Exception:
            pass

    # -- the file ----------------------------------------------------------

    def report(self) -> dict:
        """Everything worth keeping, and nothing else. Safe to attach to a
        public issue, which is what it is for."""
        return {
            "kind": "paperpull-recording",
            "provider": self.provider,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "steps": self.steps,
            "requests": self.requests,
            "dropped": self.dropped,
            "note": ("Typed values are never captured, only that a field was "
                     "typed into. No cookies, headers or storage are read. "
                     "Read this through before attaching it anywhere."),
        }

    def summary(self) -> str:
        """One line for the console and the panel."""
        kinds: dict = {}
        for s in self.steps:
            kinds[s["action"]] = kinds.get(s["action"], 0) + 1
        parts = ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items()))
        return "%d step(s)%s, %d provider request(s)" % (
            len(self.steps), " (" + parts + ")" if parts else "", len(self.requests))
