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
    a print            when a step made the page ask to print
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

No page text beyond a control's own label, and nothing the page says
leaves as it was unless it is a word on the fixed list in
paperpull_core.words. Any other word is written as its shape, every
letter as a and every digit as 9, the name of a file it downloaded, an
address, a test id and a key in an answer included. Redaction was the
rule here, and it masks runs of digits, so an account's id made mostly
of letters in a downloaded file's name went out as it was.

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

import re
import time
from typing import Callable, Optional

from .api_census import kind_of as _kind_of
from .browser import can_ask
from .failure import SAFE_TAGS as _SAFE_TAGS
from .failure import _count
from .words import (Fixed, shape, shape_name, shape_query, shape_tree,
                    shape_url, words_for)

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

# How the capture script can say it found a control, in its order of
# preference. Anything else the page sends is "unresolved".
_HOWS = ("role", "testid", "label", "id", "name", "text", "unresolved")

# The methods a request can carry. A page can send any word as a method,
# and one that is not here is written "other".
_METHODS = frozenset(("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"))

_MAX_STEPS = 400
_MAX_REQUESTS = 300

# Reading a response body is a round trip to the browser, and it happens
# while the person is still clicking. A transaction list can be megabytes,
# and its shape is the same as a small one's, so anything over this is
# recorded as having been too large to read rather than fetched.
_MAX_BODY_BYTES = 2_000_000

# ---------------------------------------------------------------------------
# The shape of the page around a step
# ---------------------------------------------------------------------------
# What a maintainer writes a selector from is structure. Which element the
# control sits in, what its neighbors are, whether the list beside it is
# twelve rows of the same shape, whether any of it is inside a shadow root.
# None of that needs a word off the page, so none is taken.
#
# Every field of a node is one of these. A tag from the list, "custom"
# for an element a site defined, "other" for anything else. A role from
# the ARIA list. Attribute names from the list below and never a value,
# with every other attribute counted rather than named, because a site
# chooses its own attribute names and one could carry a customer number.
# Counts and booleans for the rest. Nothing is removed from a copy of the
# page. Each node is built from these lists, in the page and again here,
# and here is the one that counts, because any script on the provider's
# page can call the binding and send whatever it likes.
STRUCTURE_TAGS = frozenset(_SAFE_TAGS | set("""
html head title meta link script style address blockquote br code form
frame frameset main menu meter nav noscript object progress q s search
slot source template track wbr
""".split()) | {"custom", "other"})

STRUCTURE_ROLES = frozenset("""
alert alertdialog application article banner button cell checkbox
columnheader combobox complementary contentinfo definition dialog
directory document feed figure form grid gridcell group heading img link
list listbox listitem log main marquee math menu menubar menuitem
menuitemcheckbox menuitemradio navigation none note option presentation
progressbar radio radiogroup region row rowgroup rowheader scrollbar
search searchbox separator slider spinbutton status switch tab table
tablist tabpanel term textbox timer toolbar tooltip tree treegrid
treeitem other
""".split())

STRUCTURE_ATTRS = frozenset("""
id class href src alt title name type value role for action method target
rel tabindex disabled hidden checked selected readonly required
placeholder lang style colspan rowspan scope download open multiple
data-testid data-test-id data-test data-qa data-cy data-automation-id
aria-label aria-labelledby aria-describedby aria-controls aria-expanded
aria-selected aria-hidden aria-current aria-disabled aria-haspopup
aria-modal aria-live aria-pressed aria-checked aria-owns aria-sort
""".split())

# How much one step carries. A page of a thousand rows is summarized as
# the rows beside the control and a count of the rest, which is the part a
# selector is written from.
_SHAPE_MAX_NODES = 300
_SHAPE_MAX_SIBLINGS = 25
_SHAPE_MAX_DEPTH = 80
_SHAPE_TARGET_DEPTH = 3
# Steps that carry one. A recording is fourteen steps as a rule, and one
# that runs to hundreds does not need a picture of every page.
_SHAPE_MAX_STEPS = 80


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

  // An id a build generates, which changes with every deploy. The framework
  // prefixes count only at the start. Anywhere in the value they took
  // "billing-nav" for Angular's ng- and "desc-field" for styled-components'
  // sc-, and a site's own test id was thrown over for its words (#45).
  const HASHY = /(?:[0-9]{6,})|(?:^|[-_])[a-f0-9]{8,}(?:$|[-_])|^(?:ng-|css-|sc-|jsx-|emotion-)/i;
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
      // Inside a shadow root the label is in that root, not the document.
      const root = (el.getRootNode && el.getRootNode().getElementById) ? el.getRootNode() : el.ownerDocument;
      const parts = by.split(/\s+/)
        .map((id) => (root.getElementById(id) || {}).textContent || "")
        .join(" ").trim();
      if (parts) return parts;
    }
    const tag = el.tagName.toLowerCase();
    const typed = (tag === "input" || tag === "textarea" || tag === "select");
    if (typed && el.labels && el.labels.length)
      return (el.labels[0].textContent || "").trim();
    const alt = el.getAttribute("alt");
    if (alt && alt.trim()) return alt.trim();
    const title = el.getAttribute("title");
    if (title && title.trim()) return title.trim();
    // Not for a field. A textarea's text content is whatever was in it,
    // which on a server-rendered page is the account holder's own words,
    // and a field is named by its label or it is not named at all.
    const text = typed ? "" : (el.innerText || el.textContent || "").trim();
    if (text) return text.replace(/\s+/g, " ");
    const val = el.getAttribute("value");
    // A button's own caption, never a text field's contents. The value
    // attribute, not the property, so what somebody typed is not in it
    // even for the kinds of field that are allowed through here.
    const kind = (el.getAttribute("type") || "").toLowerCase();
    if (val && (kind === "submit" || kind === "button" || kind === "reset"))
      return val.trim();
    return "";
  };

  // The attributes a site's own tests find its controls by. A control can
  // carry one of these and nothing else, no role and no link. American
  // Family marks its controls with data-cy alone, and a click on the words
  // inside one was taken for the mouse wandering and thrown away, so his
  // recording of the billing tab kept one click of seven (#45).
  const TEST_IDS = ["data-testid", "data-test-id", "data-test", "data-qa",
                    "data-cy", "data-automation-id"];
  const testIdOf = (el) => {
    for (const a of TEST_IDS) {
      const v = el.getAttribute(a);
      if (v) return v;
    }
    return null;
  };

  // The roles of a control a person presses or types in. Anything else with
  // a role, a row, a list item, a region, holds other things, and its name
  // is every word inside it.
  const CONTROL_ROLES = new Set(["button", "link", "menuitem", "menuitemcheckbox",
    "menuitemradio", "tab", "checkbox", "radio", "option", "combobox", "textbox",
    "searchbox", "switch", "slider", "spinbutton", "treeitem"]);

  // Whether an element may be named by its own words. A control may, and so
  // may an element nothing marks. A container may not, one a site marks with
  // a test id or one whose role is not a control, since its words can be a
  // whole section of an account page, names, a policy number, an address
  // (review of 0.41.0). It is found by its test id or its role instead.
  const speaks = (el) => {
    const role = roleOf(el);
    if (role) return CONTROL_ROLES.has(role);
    return !testIdOf(el);
  };

  // In preference order. Never a class, never a position among siblings.
  const locate = (el) => {
    const role = roleOf(el);
    const talk = speaks(el);
    const name = talk ? nameOf(el).slice(0, 80) : "";
    if (role && name) return { how: "role", role: role, name: name };
    const testid = testIdOf(el);
    if (stable(testid)) return { how: "testid", value: testid };
    // A container's aria-label is its words too. A section marked with a
    // test id a build generates fell through to "Auto policy for" and the
    // policyholder's name (second review of 0.41.0).
    const label = talk ? el.getAttribute("aria-label") : "";
    if (label && label.trim()) return { how: "label", value: label.trim().slice(0, 80) };
    if (stable(el.id)) return { how: "id", value: el.id };
    const nm = el.getAttribute("name");
    if (stable(nm)) return { how: "name", value: nm };
    if (name) return { how: "text", value: name };
    if (role) return { how: "role", role: role };   // a container, by its role and never its words
    return { how: "unresolved", tag: el.tagName.toLowerCase() };
  };

  // One step up, out of a shadow root when there is no parent inside it.
  const up = (el) => el.parentElement ||
    (el.getRootNode && el.getRootNode() !== document ? el.getRootNode().host : null) || null;

  // Up from what was really clicked to the thing a person would say they
  // clicked, across shadow roots.
  const control = (start) => {
    let el = start;
    for (let i = 0; el && i < 6; i++) {
      if (el.nodeType === 1 && (roleOf(el) || testIdOf(el)))
        return el;
      el = up(el);
    }
    return start && start.nodeType === 1 ? start : null;
  };

  // What was really clicked. The event's target is retargeted to the
  // outermost component when the click lands inside a shadow root, and
  // that component has no role and no text of its own, so every click on
  // a page built from components was thrown away as unnameable. His
  // recording of American Family's billing tab is six clicks long and
  // kept none of them (#45).
  const clicked = (ev) => {
    const path = ev.composedPath ? ev.composedPath() : [];
    let el = path.length ? path[0] : ev.target;
    if (el && el.nodeType !== 1) el = el.parentElement || (el.parentNode && el.parentNode.host) || ev.target;
    return el;
  };
  const inFrame = () => { try { return window !== window.top; } catch (e) { return true; } };

  // The shape of the page from the body down to the control, the
  // control's neighbors at every level, and a little of what is inside
  // it. Every field comes off a list or is a count or a yes or no. The
  // only look at text is whether a node has any, and only the yes or no
  // leaves this function.
  const SHAPE_TAGS = new Set(__SHAPE_TAGS__);
  const SHAPE_ROLES = new Set(__SHAPE_ROLES__);
  const SHAPE_ATTRS = new Set(__SHAPE_ATTRS__);
  const shapeOf = (ev, target) => {
    try {
      let budget = __SHAPE_MAX_NODES__, truncated = false;
      const down = (ev.composedPath ? ev.composedPath() : [])
        .filter((n) => n && n.nodeType === 1).reverse();
      const start = down.findIndex((n) => n.tagName.toLowerCase() === "body");
      if (start < 0 || down.indexOf(target) < 0) return null;
      // A slot's children are its fallback. What a person sees in it,
      // and what a click inside a web component lands on, is what was
      // assigned to it, and walking the fallback lost the path there.
      const kids = (el) => {
        if (el.tagName.toLowerCase() === "slot" && el.assignedElements) {
          const given = el.assignedElements({ flatten: true });
          if (given.length) return given;
        }
        return Array.from(el.shadowRoot ? el.shadowRoot.children : el.children);
      };
      let reached = false;
      const describe = (el) => {
        budget--;
        const tag = el.tagName.toLowerCase();
        const node = { tag: SHAPE_TAGS.has(tag) ? tag
                            : (tag.indexOf("-") > 0 ? "custom" : "other") };
        const role = (el.getAttribute("role") || "").trim().split(/\s+/)[0]
          .toLowerCase();
        if (role) node.role = SHAPE_ROLES.has(role) ? role : "other";
        const attrs = [];
        let dataOther = 0, other = 0;
        for (const a of el.getAttributeNames()) {
          if (SHAPE_ATTRS.has(a)) attrs.push(a);
          else if (a.startsWith("data-")) dataOther++;
          else other++;
        }
        node.attrs = attrs.sort();
        if (dataOther) node.data_other = dataOther;
        if (other) node.other_attrs = other;
        node.child_count = kids(el).length;
        if (el.shadowRoot) node.shadow = true;
        const box = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        node.visible = box.width >= 1 && box.height >= 1
          && style.display !== "none" && style.visibility !== "hidden";
        node.text = Array.from(el.childNodes).some(
          (c) => c.nodeType === 3 && /\S/.test(c.data || ""));
        return node;
      };
      const inside = (el, depth) => {
        const node = describe(el);
        const list = kids(el);
        const children = [];
        if (depth > 0) {
          for (const c of list.slice(0, __SHAPE_MAX_SIBLINGS__)) {
            if (budget <= 0) { truncated = true; break; }
            children.push(inside(c, depth - 1));
          }
        }
        if (children.length) node.children = children;
        if (list.length > children.length) node.more = list.length - children.length;
        return node;
      };
      const walk = (i) => {
        const el = down[i];
        if (el === target) {
          const node = inside(el, __SHAPE_TARGET_DEPTH__);
          node.target = true;
          reached = true;
          return node;
        }
        const node = describe(el);
        const list = kids(el);
        let next = -1;
        for (let j = i + 1; j < down.length && next < 0; j++)
          if (list.indexOf(down[j]) >= 0) next = j;
        const children = [];
        let shown = 0;
        for (const c of list) {
          if (next >= 0 && c === down[next]) {
            if (next - start > __SHAPE_MAX_DEPTH__) { truncated = true; continue; }
            children.push(walk(next));
            continue;
          }
          if (budget <= 0) { truncated = true; continue; }
          if (shown >= __SHAPE_MAX_SIBLINGS__) continue;
          shown++;
          children.push(describe(c));
        }
        if (children.length) node.children = children;
        if (list.length > children.length) node.more = list.length - children.length;
        return node;
      };
      const root = walk(start);
      // A shape that never reached the control says so, rather than
      // reading as a whole page with nothing pressed in it.
      return { root: root, nodes: __SHAPE_MAX_NODES__ - budget,
               truncated: truncated || !reached };
    } catch (e) {
      return null;
    }
  };

  const send = (record) => { try { post(record); } catch (e) {} };

  // A download run replaces window.print so it can keep the HTML the
  // print view would have rendered, and it does that for every page in
  // the browser. During a recording that means the person presses the
  // site's Print button and nothing at all happens, which reads as a
  // broken tool and steers them away from the one control that matters
  // most on a receipt. So the real one goes back for the duration, and
  // the fact that the page asked to print is kept, because for a receipt
  // that is the single most useful thing a maintainer can be told.
  try {
    const realPrint = window.__paperpullOriginalPrint || window.print;
    window.print = function () {
      send({ action: "print", at: Date.now() });
      try { return realPrint.apply(window, arguments); } catch (e) {}
    };
  } catch (e) {}

  document.addEventListener("click", (ev) => {
    const el = control(clicked(ev));
    if (!el) return;
    const tag = el.tagName.toLowerCase();
    if (tag === "html" || tag === "body") return;   // a click on nothing
    send({ action: "click", locator: locate(el), tag: tag,
           label: speaks(el) ? nameOf(el).slice(0, 120) : "", at: Date.now(),
           marked: !!testIdOf(el),
           in_shadow: !!(el.getRootNode && el.getRootNode() !== document),
           in_frame: inFrame(),
           structure: shapeOf(ev, el) });
  }, true);

  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (!el || el.nodeType !== 1) return;
    const tag = el.tagName.toLowerCase();
    const loc = locate(el);
    const label = nameOf(el).slice(0, 120);
    const structure = shapeOf(ev, el);
    if (tag === "select") {
      const opt = el.options && el.options[el.selectedIndex];
      // The option's visible label. A statement picker's options are
      // dates and years, which is the signal, and it is redacted in
      // Python on the way out like everything else.
      send({ action: "select", locator: loc, label: label,
             option: opt ? (opt.textContent || "").trim().slice(0, 60) : "",
             at: Date.now(), structure: structure });
      return;
    }
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox" || type === "radio") {
      send({ action: "check", locator: loc, label: label,
             checked: !!el.checked, at: Date.now(), structure: structure });
      return;
    }
    // A typed field. That it was typed into is the fact worth keeping.
    // What was typed is never read.
    send({ action: "fill", locator: loc, label: label, at: Date.now(),
           structure: structure });
  }, true);

  document.addEventListener("submit", (ev) => {
    const el = ev.target;
    send({ action: "submit", locator: el ? locate(el) : { how: "unresolved" },
           at: Date.now(), structure: el ? shapeOf(ev, el) : null });
  }, true);

  return "installed";
}
"""


def _fill_capture_js(js: str) -> str:
    """The lists the page builds a shape from are the ones Python checks it
    against, written in once, so the two cannot drift apart."""
    import json as _json
    for key, value in (
            ("__SHAPE_TAGS__", _json.dumps(sorted(STRUCTURE_TAGS))),
            ("__SHAPE_ROLES__", _json.dumps(sorted(STRUCTURE_ROLES))),
            ("__SHAPE_ATTRS__", _json.dumps(sorted(STRUCTURE_ATTRS))),
            ("__SHAPE_MAX_NODES__", str(_SHAPE_MAX_NODES)),
            ("__SHAPE_MAX_SIBLINGS__", str(_SHAPE_MAX_SIBLINGS)),
            ("__SHAPE_MAX_DEPTH__", str(_SHAPE_MAX_DEPTH)),
            ("__SHAPE_TARGET_DEPTH__", str(_SHAPE_TARGET_DEPTH))):
        js = js.replace(key, value)
    return js


_CAPTURE_JS = _fill_capture_js(_CAPTURE_JS)

# The most nodes a shape may hold on the way out. The page keeps to
# _SHAPE_MAX_NODES but always finishes the path down to the control, so
# the ceiling here leaves room for that path. It exists for a page that
# ignores the rules, not for one that follows them.
_SHAPE_CEILING = _SHAPE_MAX_NODES + _SHAPE_MAX_DEPTH + 60


def _timestamp(value) -> Optional[int]:
    """A step's time in milliseconds, or None.

    Copied as the page sent it, any script on the page could write a card
    number into the file through it, since the binding is on window. A
    number in range is a time, and anything else is nothing."""
    if isinstance(value, bool):
        return None
    try:
        n = int(value) if isinstance(value, (int, float)) else None
    except (OverflowError, ValueError):
        return None
    return n if n is not None and 0 <= n < 10 ** 14 else None


def clean_structure(raw) -> Optional[dict]:
    """A step's shape, rebuilt from the lists and nothing else.

    What the page sent is read for its fields and never copied. A tag not
    on the list is "other", a role not on the list is "other", an
    attribute name not on the list is not there, a count is a bounded
    count, and a yes or no is True only when it is exactly True. A string
    the page invented has nowhere to go."""
    if not isinstance(raw, dict) or not isinstance(raw.get("root"), dict):
        return None
    budget = [_SHAPE_CEILING]
    cut = [raw.get("truncated") is True]

    def node(r, depth):
        if not isinstance(r, dict):
            return None
        if budget[0] <= 0 or depth > _SHAPE_MAX_DEPTH + _SHAPE_TARGET_DEPTH:
            cut[0] = True
            return None
        budget[0] -= 1
        tag = r.get("tag")
        out = {"tag": tag if isinstance(tag, str) and tag in STRUCTURE_TAGS
               else "other"}
        role = r.get("role")
        if role is not None:
            out["role"] = (role if isinstance(role, str)
                           and role in STRUCTURE_ROLES else "other")
        attrs = r.get("attrs")
        out["attrs"] = sorted({a for a in attrs if isinstance(a, str)
                               and a in STRUCTURE_ATTRS}) \
            if isinstance(attrs, list) else []
        for key in ("data_other", "other_attrs", "child_count", "more"):
            if key in r:
                out[key] = _count(r[key])
        out["visible"] = r.get("visible") is True
        for key in ("text", "target", "shadow"):
            if r.get(key) is True:
                out[key] = True
        kids = r.get("children")
        if isinstance(kids, list):
            if len(kids) > _SHAPE_MAX_SIBLINGS + 1:
                cut[0] = True
            children = [c for c in (node(k, depth + 1)
                                    for k in kids[:_SHAPE_MAX_SIBLINGS + 1])
                        if c is not None]
            if children:
                out["children"] = children
        return out

    root = node(raw["root"], 0)
    if root is None:
        return None

    def has_target(n):
        return n.get("target") or any(has_target(c)
                                       for c in n.get("children") or ())
    # A shape with no control in it lost the path somewhere, and says so
    # whatever the page claimed.
    return {"root": root, "nodes": _SHAPE_CEILING - budget[0],
            "truncated": cut[0] or not has_target(root)}


class Recorder:
    """One recording, on one page, of one person's path to a document."""

    def __init__(self, page, *,
                 is_safe_url: Callable[[str], bool],
                 looks_signed_out: Optional[Callable] = None,
                 is_safe_control: Optional[Callable[[str], bool]] = None,
                 provider: str = "", words=None):
        self.page = page
        self._is_safe_url = is_safe_url
        self._looks_signed_out = looks_signed_out
        self._is_safe_control = is_safe_control
        self.provider = provider
        # The app's own words on top of the fixed list, its name and its
        # site module's, so "PayPal" in an address reads as itself.
        self.words = frozenset(words) if words is not None else words_for(provider)
        self.steps: list = []
        self.requests: list = []
        self.dropped = {"repeat": 0, "unresolved": 0, "off_host_request": 0,
                        "malformed": 0}
        self._binding = "__ppRecorderPost"
        # Every tab being recorded, the one this started on and any the
        # provider opened from it.
        self._watched: list = []
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
                    return ("you are not signed in yet. Sign in, open the "
                        "page with your documents on it, and start again")
            except Exception:
                pass
        try:
            if self.page.locator("input[type='password']").count() > 0:
                return ("there is a password field on this page, so recording "
                        "will not start here. Finish signing in first.")
        except Exception:
            # This is the backstop, and a backstop that cannot run is not one.
            # The check above it swallows its own failure on purpose, because a
            # provider's looks_signed_out being unwell should not take the
            # feature away. Nothing is left under this one, so it refuses.
            return ("the page could not be checked for a sign-in form just "
                    "now, so recording will not start. Try again in a moment.")
        return None

    # -- running -----------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        why = self.refusal()
        if why:
            raise RuntimeError(why)
        self.page.expose_binding(self._binding, self._on_event)
        self._arm()
        self._install()
        self.page.on("framenavigated", self._on_navigated)
        self.page.on("response", self._on_response)
        self.page.on("download", self._on_download)
        self._watched.append(self.page)
        try:
            self.page.context.on("page", self._on_new_tab)
        except Exception:
            pass
        self._started = True

    def _arm(self) -> None:
        """The capture script on every document this page loads from here
        on, put there by the browser itself before any page script runs.

        Re-installing it by hand when a navigation is noticed was not
        enough and could not be. A click that navigates replaces the
        document and takes its listeners with it, and the notice that it
        happened arrives, if at all, after the next page is already in
        front of the person. Costco's first click navigated and the
        recording went silent for the next sixty-six seconds. Proved in a
        browser against three pages that link to each other before this
        was written."""
        import json as _json
        try:
            self.page.add_init_script(
                "(%s)(%s);" % (_CAPTURE_JS.strip(), _json.dumps(self._binding)))
        except Exception:
            pass

    def _install(self) -> None:
        """The same script on the document that is already here, which an
        init script alone would not reach. It is idempotent."""
        try:
            self.page.evaluate(_CAPTURE_JS, self._binding)
        except Exception:
            pass

    def stop(self) -> dict:
        if self._stopped:
            return self.report()
        for watched in list(self._watched):
            for event, handler in (("framenavigated", self._on_navigated),
                                   ("response", self._on_response),
                                   ("download", self._on_download)):
                try:
                    watched.remove_listener(event, handler)
                except Exception:
                    pass
            # Its capture script is told to stop posting too, or a tab the
            # provider opened keeps talking to a recording that has ended.
            try:
                watched.evaluate("() => { window.__ppRecorderPost = () => {}; }")
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
        """Whatever the page sent. The binding is on `window`, so any
        script on the provider's page can call it, not only the listener
        installed above. Nothing here trusts a type or a length. An
        exception raised in this handler would surface in the page and
        lose the step, so the whole thing is guarded."""
        if self._stopped:
            # An init script cannot be taken off a page once it is on, so
            # a navigation after Stop arms the new document too. Stop has
            # to mean stop on this side as well.
            return
        try:
            # Which tab it came from, so a step can say whether it was on
            # the provider's own site. The binding hands this over, which
            # is surer than anything the payload could claim.
            where = ""
            opened = False
            try:
                src_page = source.get("page") if isinstance(source, dict) else None
                where = (src_page.url or "") if src_page is not None else ""
                opened = src_page is not None and src_page is not self.page
            except Exception:
                where = ""
            self._record_event(record, where, opened)
        except Exception:
            self.dropped["malformed"] = self.dropped.get("malformed", 0) + 1

    def _record_event(self, record, page_url: str = "", opened: bool = False) -> None:
        if not isinstance(record, dict) or len(self.steps) >= _MAX_STEPS:
            return
        action = str(record.get("action") or "")
        if action == "print":
            # Not a step. Nobody clicks "print", they click a control and
            # the page prints, so it belongs to that control.
            step = self._current()
            if step is not None:
                step["effect"]["printed"] = True
            else:
                self.dropped["print_without_step"] = \
                    self.dropped.get("print_without_step", 0) + 1
            return
        if action not in ("click", "select", "check", "fill", "submit"):
            return
        loc = record.get("locator")
        loc = loc if isinstance(loc, dict) else {}
        label = str(record.get("label") or "")

        # A click that landed on nothing nameable, or on a heading or a
        # paragraph, is the mouse wandering rather than a step. Not one on
        # an element the site marks with a test id, which is a control on a
        # site that marks its controls that way and no other (#45).
        if action == "click" and loc.get("how") in ("unresolved", "text"):
            tag = record.get("tag")
            tag = tag if isinstance(tag, str) else ""
            marked = record.get("marked") is True
            if not label.strip() or (tag in _NOT_A_CONTROL and not marked):
                self.dropped["unresolved"] += 1
                self._count_unresolved(record, tag, opened)
                return

        step = {
            "i": len(self.steps),
            "action": action,
            "locator": self._clean_locator(loc),
            "label": shape(label, self.words)[:120],
            "at": _timestamp(record.get("at")),
        }
        if action == "select":
            step["option"] = shape(str(record.get("option") or ""), self.words)[:60]
        if action == "select" and not step["option"]:
            step["option"] = ""
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
        # Which site this happened on. A tab the provider opened is
        # recorded whatever host it lands on, because two providers here
        # keep their documents on a vendor, and a reader should be able
        # to see which steps were theirs and which were not (#35, #45).
        try:
            if page_url and not self._is_safe_url(page_url):
                step["on_the_providers_own_site"] = False
        except Exception:
            pass
        # Where on the page it was, when that is anywhere unusual. Counts
        # and yes or no only.
        where = {k: True for k, v in (("in_shadow", record.get("in_shadow")),
                                      ("in_frame", record.get("in_frame")),
                                      ("in_opened_tab", opened)) if v is True}
        if where:
            step["where"] = where
        if self._is_repeat(step):
            self.dropped["repeat"] += 1
            return
        # The shape of the page around the step, for writing a selector
        # from. Guarded on its own, so a shape that will not clean up
        # costs the shape and never the step.
        try:
            if sum(1 for s in self.steps if "structure" in s) < _SHAPE_MAX_STEPS:
                built = clean_structure(record.get("structure"))
                if built is not None:
                    step["structure"] = built
            elif record.get("structure") is not None:
                self.dropped["structure"] = self.dropped.get("structure", 0) + 1
        except Exception:
            pass
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
        """Rebuilt from the lists, because what the page sent is not
        necessarily what the listener above would send. How it was found
        and its role and tag are words of ours or "other", and its name or
        value is shaped like any other words off the page, a test id or an
        id included, since a site builds those from what it shows."""
        how = loc.get("how")
        out = {"how": how if isinstance(how, str) and how in _HOWS else "unresolved"}
        role = loc.get("role")
        if role not in (None, "", [], {}):
            role = str(role).strip().lower()
            out["role"] = role if role in STRUCTURE_ROLES else "other"
        for key in ("name", "value"):
            value = loc.get(key)
            if value not in (None, "", [], {}):
                out[key] = shape(str(value), self.words)[:80]
        tag = loc.get("tag")
        if tag not in (None, "", [], {}):
            tag = str(tag).strip().lower()
            out["tag"] = tag if tag in STRUCTURE_TAGS else (
                "custom" if "-" in tag else "other")
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

    def _count_unresolved(self, record, tag: str, opened: bool) -> None:
        """What a click that could not be named landed on, as counts.

        Six of one tester's clicks were thrown away and the file said only
        that there were six (#45). The kind of element comes off the same
        list a page's shape does, anything else is "custom" or "other", and
        the rest are yes or no, so nothing here is text from the page."""
        kind = tag if tag in STRUCTURE_TAGS else ("custom" if "-" in tag else "other")
        by = self.dropped.setdefault("unresolved_on", {})
        by[kind] = by.get(kind, 0) + 1
        where = self.dropped.setdefault("unresolved_where", {})
        for key, hit in (("in_shadow", record.get("in_shadow") is True),
                         ("in_frame", record.get("in_frame") is True),
                         ("in_opened_tab", opened)):
            if hit:
                where[key] = where.get(key, 0) + 1

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
            step["effect"]["landed_on"] = shape_url(frame.url or "", self.words)[:200]
        self._install()

    def _on_new_tab(self, page) -> None:
        step = self._current()
        on_host = True
        try:
            on_host = self._is_safe_url(page.url or "")
        except Exception:
            pass
        if step is not None:
            step["effect"]["new_tab"] = True
            step["effect"]["new_tab_off_host"] = not on_host
        self._watch(page)

    def _watch(self, page) -> None:
        """Record what happens in a tab the provider opened, as well as in
        the one it was opened from.

        A recording used to note that a tab had opened and then hear
        nothing more, because every listener and the binding the capture
        script calls were on the first tab alone. A tester pressed Billing
        & Payments, that opened a tab, and his recording is one step long
        (#45). Everything a provider does after that point was invisible,
        which on a site that opens a tab is everything worth recording.

        A tab the provider opened is recorded whatever host it lands on,
        and each step says whether it was on the provider's own site.

        Refusing an off-host tab was tried first and it does not work,
        for two reasons. It refused the wrong thing: two providers here
        keep their documents on a vendor, so the tab that matters is the
        one that is not theirs, and refusing it left one tester's
        recording a single step long. And it refused inconsistently,
        because a tab opens as about:blank and navigates afterwards, so
        whether the check saw its real address was a race. One tester's
        off-host tab was recorded and another's was not, on the same
        build.

        Nothing typed is captured anywhere, on any tab, so what this
        gathers on a vendor's page is the same as anywhere else: the
        controls pressed, named the way a person reads them. Recording
        still refuses to START outside the provider's own site, and still
        refuses a page with a password field on it."""
        if page is None or page in self._watched:
            return
        self._watched.append(page)
        import json as _json
        try:
            page.expose_binding(self._binding, self._on_event)
        except Exception:
            pass                      # already exposed, which is fine
        try:
            page.add_init_script(
                "(%s)(%s);" % (_CAPTURE_JS.strip(), _json.dumps(self._binding)))
        except Exception:
            pass
        try:
            page.evaluate(_CAPTURE_JS, self._binding)
        except Exception:
            pass
        for event, handler in (("framenavigated", self._on_navigated),
                               ("response", self._on_response),
                               ("download", self._on_download)):
            try:
                page.on(event, handler)
            except Exception:
                pass

    def _on_download(self, download) -> None:
        """That a step set off a download, and the shape of the file's name.

        The name was kept through redaction, which masks runs of digits,
        and a provider can name a statement after the account it belongs
        to, an id of letters and digits that went out as it was. Its kind
        is the useful part, and where its dates sit, so the shape keeps
        those and nothing else."""
        step = self._current()
        if step is None:
            return
        step["effect"]["download"] = True
        try:
            step["effect"]["download_name"] = shape_name(
                download.suggested_filename or "", self.words)
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
                "url": shape_url(url, self.words, query=False)[:200],
                "status": _count(response.status),
                "type": _kind_of(kind),
            }
            query = shape_query(url, self.words)
            if query:
                entry["query"] = query[:240]
            try:
                method = str(response.request.method or "").upper()
                entry["method"] = method if method in _METHODS else "other"
                body = response.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(
                            shape(str(k), self.words)[:40] for k in parsed)[:30]
            except Exception:
                pass
            if "json" in kind:
                size = 0
                try:
                    size = int(response.headers.get("content-length") or 0)
                except (TypeError, ValueError):
                    size = 0
                if size > _MAX_BODY_BYTES:
                    entry["shape"] = "not read, too large"
                else:
                    try:
                        entry["shape"] = self._json_shape(response.json())
                    except Exception:
                        entry["shape"] = "unreadable"
            self.requests.append(entry)
            if step is not None:
                step["effect"]["requests"] += 1
        except Exception:
            pass

    def _json_shape(self, obj, depth: int = 0):
        """The shape of a JSON answer, never its values. Keys are the
        signal, a balance is not. A key is shaped like any other word,
        because an object keyed by account number is a thing that
        exists."""
        if depth > 3:
            return "..."
        if isinstance(obj, dict):
            out = {}
            for k, v in list(obj.items())[:25]:
                key = shape(str(k), self.words)[:40]
                while key in out:
                    key += "+"
                out[key] = self._json_shape(v, depth + 1)
            return out
        if isinstance(obj, list):
            # Fixed, since the count is ours to say and would otherwise
            # leave as its shape like any other digits.
            return [Fixed("list of %d" % len(obj)),
                    self._json_shape(obj[0], depth + 1) if obj else None]
        return {bool: "bool", int: "int", float: "float", str: "str",
                type(None): "NoneType"}.get(type(obj), "other")

    # -- the file ----------------------------------------------------------

    def report(self) -> dict:
        """Everything worth keeping, and nothing else. Safe to attach to a
        public issue, which is what it is for.

        Every field above is already built from the lists, and the whole of
        it goes through the same rule once more on the way out, so a field
        added later cannot carry a page's words by forgetting to. A step's
        time leaves as whole seconds since the first step, a duration,
        rather than the clock."""
        first = next((s["at"] for s in self.steps
                      if isinstance(s.get("at"), int)), None)
        steps = []
        for s in self.steps:
            out = {k: v for k, v in s.items() if k != "at"}
            if first is not None and isinstance(s.get("at"), int):
                out["seconds_in"] = max(0, (s["at"] - first) // 1000)
            steps.append(out)
        return shape_tree({
            "kind": "paperpull-recording",
            "provider": self.provider,
            "recorded_at": Fixed(time.strftime("%Y-%m-%dT%H:%M:%S")),
            "steps": steps,
            "requests": self.requests,
            "dropped": self.dropped,
            "note": Fixed(
                "Typed values are never captured, only that a field was "
                "typed into. No cookies, headers or storage are read. "
                "A word off the page is kept only when it is on PaperPull's "
                "fixed list of words, and any other is written as its shape, "
                "a for a letter and 9 for a digit, in control names, file "
                "names, addresses and keys alike. A step's structure is the "
                "page's shape around the control, element kinds, attribute "
                "names and counts, and never any text or attribute value. "
                "Read this through before attaching it anywhere."),
        }, self.words)

    def summary(self) -> str:
        """One line for the console and the panel."""
        kinds: dict = {}
        for s in self.steps:
            kinds[s["action"]] = kinds.get(s["action"], 0) + 1
        parts = ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items()))
        return "%d step(s)%s, %d provider request(s)" % (
            len(self.steps), " (" + parts + ")" if parts else "", len(self.requests))


# ---------------------------------------------------------------------------
# Reading the file back, before it goes anywhere
# ---------------------------------------------------------------------------

# A number this long is left alone by redaction on purpose, because a year,
# a page count and a dollar figure are all four digits and masking them
# would make a recording useless. An account number can be four digits too.
_SHORT_NUMBER = re.compile(r"(?<!\d)\d{4,5}(?!\d)")

# 1900 through 2099. A statement list is nothing but years, so flagging
# those would bury the one number worth looking at.
_A_YEAR = re.compile(r"^(19|20)\d\d$")

# The report's own fields. Nothing personal has ever been in them and
# every one of them is a number or a fixed sentence.
_OURS = ("kind", "note", "provider", "recorded_at", "dropped")

# Two or three capitalised words in a row, which is what a person's name
# looks like when it is sitting on a profile button. Most hits are the
# name of a control, so this is a prompt to look rather than a finding.
_NAME_SHAPED = re.compile(r"\b[A-Z][a-z]{1,14} [A-Z][a-z]{1,14}(?: [A-Z][a-z]{1,14})?\b")

# Words that make a name-shaped pair almost certainly a control, not a
# person. Sites label things "Bill History" and "Account Summary" all day.
_CONTROL_WORDS = {
    "account", "accounts", "bill", "billing", "bills", "card", "cards",
    "center", "check", "close", "current", "detail", "details", "document",
    "documents", "download", "estimate", "file", "files", "form", "forms",
    "go", "history", "home", "invoice", "invoices", "loan", "log", "logout",
    "menu", "more", "my", "next", "open", "order", "orders", "page", "pay",
    "payment", "payments", "pdf", "period", "plan", "policy", "previous",
    "print", "profile", "receipt", "receipts", "records", "report", "return",
    "save", "search", "select", "settings", "show", "sign", "statement",
    "statements", "summary", "tax", "the", "transaction", "transactions",
    "view", "year",
}

_EMAIL_OR_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_STREET = re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+"
                     r"(st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|"
                     r"blvd|boulevard|way|pl|place|ter|terrace)\b", re.I)


def _strings(obj, path="", found=None, depth=0) -> list:
    """Every string in the report, with where it came from.

    The recorder never nests deeper than a handful, but this reads a file
    a person has had in a text editor, so the depth is capped rather than
    trusted. Running out of stack while checking a file for private data
    would fail in the one direction that matters."""
    found = [] if found is None else found
    if depth > 12:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            _strings(v, "%s.%s" % (path, k) if path else str(k), found, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _strings(v, "%s[%d]" % (path, i), found, depth + 1)
    elif isinstance(obj, str) and obj:
        found.append((path, obj))
    return found


def _name_shaped(text: str, ours=frozenset()) -> list:
    out = []
    # A name also comes joined into an id, "holder-Invented-Person", since a
    # click inside a marked container is kept by its test id or its id, and
    # a site can build those from what it shows (review of 0.41.0).
    # Both ways, since read with its dashes as spaces "Bill-To-John Smith"
    # is "Bill To John", and "John Smith" was no longer seen (review of
    # 0.41.0).
    for source in (text, re.sub(r"[-_]+", " ", text)):
        for hit in _NAME_SHAPED.findall(source):
            words = [w.lower() for w in hit.split()]
            if hit in out or any(w in _CONTROL_WORDS for w in words):
                continue
            # The app's own name, "American Family", is not a person. A
            # pair of words that are both on the list still is worth a
            # look, since a name made of ordinary words, June Price, is
            # the one kind the list lets through.
            if all(w in ours for w in words):
                continue
            out.append(hit)
    return out


def concerns(report: dict) -> list:
    """What a person should look at, worst first. Each is a sentence, not a
    verdict. This does not edit the file and does not claim the file is
    clean, because no check can.

    One finding is one sentence however many places it appears. An account
    number in forty rows is one thing to fix, and forty lines saying so is
    a wall of text that gets skipped.

    A recording written since the fixed word list cannot hold any of these,
    since a word off the list leaves as its shape and every digit as a 9.
    This reads a file a person has had in a text editor, and one written
    before, so it looks anyway."""
    found: dict = {}
    ours = words_for(str(report.get("provider") or "")) \
        if isinstance(report, dict) else frozenset()

    def add(key, where, text):
        said.add(key[0])
        if key in found:
            found[key][1] += 1
        else:
            found[key] = [where, 1, text]

    for where, text in _strings(report, ""):
        if where.split(".")[0].split("[")[0] in _OURS:
            continue
        said = set()
        if _EMAIL_OR_MAIL.search(text):
            add(("email", text), where,
                "%s holds something shaped like an email address. A recording "
                "writes those as <email>, so this one arrived by a route that "
                "does not. Delete it and tell the maintainer where it was.")
        if _STREET.search(text):
            add(("street", text), where,
                "%s holds something shaped like a street address. Delete it.")
        for hit in _SHORT_NUMBER.findall(text):
            if _A_YEAR.match(hit) or set(hit) == {"9"}:
                continue
            add(("number", hit), where,
                "%s holds the number " + hit + ". A recording writes every "
                "digit as a 9, so this one was written some other way. If it "
                "is part of an account number, replace it with x's.")
        for hit in _name_shaped(text, ours):
            add(("name", hit), where,
                '%s reads "' + hit + '". If that is a person\'s name rather '
                "than the name of a button, replace it.")
        # Only when nothing above named the thing. An email is caught by
        # the line above and by this one, and the line above says more.
        if not said and shape(text, ours) != text:
            add(("unlisted", text), where,
                "%s holds a word that is not on the fixed list, which means it "
                "was written without going through it, or before there was "
                "one. Tell the maintainer.")

    out = []
    for where, times, text in found.values():
        place = where if times == 1 else "%s (and %d other place%s)" % (
            where, times - 1, "" if times == 2 else "s")
        out.append(text % place)
    return out


# ---------------------------------------------------------------------------
# One whole recording, from the app's point of view
# ---------------------------------------------------------------------------

def _host_of(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return urlsplit(url or "").hostname or ""
    except ValueError:
        return ""


_CONSENT = """\
RECORDING - what this does and does not capture

  It records   the controls you click, by the name you read on them, the
               option you pick in a dropdown, a box you tick, and the
               addresses and shapes of the provider's own answers.
  It keeps     a word off the page only when it is on PaperPull's fixed
               list of words. Any other word, a name, an address, an
               account number, is written as its shape, a for a letter
               and 9 for a digit.
  It does not  record anything you type. Not the text, not a password,
               not a code. There is no keystroke listener in it at all.
  It does not  read cookies, headers or anything that holds your session.

Nothing is downloaded. Click your way to a statement the way you normally
would, once, then stop. Read the file it writes before sending it.
"""


def page_to_watch(page, is_safe_url):
    """The tab the account holder is looking at.

    An app that attaches to a running browser hands out a FRESH page in
    the signed-in context. That is right for a download run, which
    navigates it wherever it needs to go, and it is wrong for a
    recording, which has nowhere to navigate to and has to watch what
    the person is already doing. Handed a blank page, every recording
    refused with "this is not a page on the provider's own site", which
    is a true sentence about the wrong tab.

    So look past the given page at the others in the same context and
    take the provider's own, the most recently opened one when there is
    more than one, because that is the tab somebody just went to. If
    none of them is on the provider, keep the page we were given so the
    refusal describes the situation honestly."""
    try:
        if is_safe_url(page.url or ""):
            return page
        others = [p for p in page.context.pages if p is not page]
    except Exception:
        return page
    best = None
    for other in others:
        try:
            closed = getattr(other, "is_closed", None)
            if callable(closed) and closed():
                continue
            if is_safe_url(other.url or ""):
                best = other
        except Exception:
            continue
    return best or page


def _wait_for_stop(page, stop_file, say) -> None:
    """Enter at a console, or the panel's Stop button, whichever comes.

    The waiting is done with the browser's own timer rather than
    time.sleep, and Enter is read on a thread rather than here. Both for
    the same reason. Playwright's sync API dispatches what the page
    sends only while this thread is inside a Playwright call, so a
    thread parked in sleep() or input() is a thread that hears nothing.
    Navigations went unnoticed, so the capture was never put back, and
    responses were read long after their bodies were gone. Costco
    recorded two clicks and then sixty-six seconds of silence.

    The panel runs an app with its input closed, so there is nobody to
    press Enter and the sentinel file is the only way to say when to
    stop. can_ask() decides which, and the prompt is only printed when
    somebody could answer it. input() on a closed stdin raises
    ValueError rather than EOFError, which a live run found, so both are
    caught."""
    import threading
    say("")
    done = threading.Event()
    no_console = threading.Event()
    console = can_ask()
    if console:

        def read_enter():
            try:
                input()
            except (EOFError, OSError, ValueError, RuntimeError):
                # can_ask() said there was a console and there is not.
                no_console.set()
                return
            done.set()

        threading.Thread(target=read_enter, daemon=True).start()
        # Long enough for an input() on a closed stdin to raise, which it
        # does at once, so the person gets one instruction and it is the
        # one that will work.
        if no_console.wait(0.25):
            console = False
    say("Recording. Click through to a document, then press Enter here."
        if console else
        "Recording. Press Stop in the control panel when you are done.")
    while not done.is_set() and not stop_file.exists():
        try:
            page.wait_for_timeout(400)
        except Exception:
            # The page is gone, or this is not a real one. Either way
            # there is nothing left to hear.
            time.sleep(0.4)


def record_session(page, site, diagnostics_dir, provider: str = "",
                   owner: str = "", say=print) -> Optional[str]:
    """Start a recording on `page`, wait for the person, write the file.

    `site` is the app's own site module, for the two host checks and its
    control guard. Returns the path written, or None if it refused."""
    from .redact import set_private_words
    from .words import write_shaped
    from pathlib import Path

    set_private_words([owner] if owner else [])
    words = words_for(provider, site)
    watching = page_to_watch(page, site.is_safe_url)
    if watching is not page:
        page = watching
        try:
            page.bring_to_front()
        except Exception:
            pass
        say("Watching the tab you already have open at %s."
            % (_host_of(page.url or "") or "this provider"))
    rec = Recorder(page,
                   is_safe_url=site.is_safe_url,
                   looks_signed_out=getattr(site, "looks_signed_out", None),
                   is_safe_control=getattr(site, "is_safe_control", None),
                   provider=provider, words=words)
    why = rec.refusal()
    if why:
        say("Not recording, because %s." % why)
        return None

    say(_CONSENT)
    if not owner:
        # A name leaves as its shape because it is not on the word list. A
        # name that is also a word on it, Bill or May, is told apart only
        # by being the owner's, so say so rather than imply a cover that is
        # not there.
        say("No account holder name is set in this app's config. A name is"
            " written as its shape anyway, unless it is also an ordinary"
            " word, like Bill or May. Look for one when you read the file.")
        say("")
    rec.start()
    stop_file = Path(diagnostics_dir) / ".stop-recording"
    try:
        stop_file.unlink()
    except OSError:
        pass
    try:
        _wait_for_stop(page, stop_file, say)
    except KeyboardInterrupt:
        say("\nStopped.")
    finally:
        report = rec.stop()
        try:
            stop_file.unlink()
        except OSError:
            pass

    out = Path(diagnostics_dir) / "recording.json"
    write_shaped(out, report, words)
    say("")
    say("Wrote %s" % out)
    say("  %s" % rec.summary())
    if not report["steps"]:
        say("  Nothing was recorded. If you clicked, the page may have been")
        say("  replaced between starting and clicking. Try again.")

    # The file has already been built from the word list. This is the
    # second pair of eyes over the result, and it runs here rather than
    # only in the maintainer's tool because the person deciding whether to
    # attach the file is standing in front of this console, not that one.
    try:
        worry = concerns(report)
    except Exception:
        # The file is already on disk and is the thing that matters. A
        # check that fails is not a reason to lose it.
        worry = ["the check over this file could not be run, so read it"
                 " through with particular care"]
    say("")
    if worry:
        say("Before this file goes anywhere, look at %d thing%s in it."
            % (len(worry), "" if len(worry) == 1 else "s"))
        for line in worry[:20]:
            say("  - %s" % line)
        if len(worry) > 20:
            say("  - and %d more of the same kind." % (len(worry) - 20))
        say("")
    say("Read that file through for anything you would not want public,")
    say("then attach it to the provider's issue on GitHub.")
    return str(out)
