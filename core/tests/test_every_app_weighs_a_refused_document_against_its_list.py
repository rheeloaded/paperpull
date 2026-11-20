"""One document a site refuses on its own never stops every run.

Ziply Fiber read a 401, a 403, a redirect or a page where one bill's PDF
should be as a sign-out, and stopped the run there. A site that refuses one
bill answers every run the same way, so every run stopped at that bill and
Continue stopped there again, the loop of #124. Cetera and Verizon Mobile
had the same shape and were mended first. When one document is refused,
they read the list again with the call that proves a session. A session
that has ended is refused the list too, and that stops the run as signed
out. A list that still reads leaves the refusal that document's own, so it
fails alone and the run goes on.

So every document app is asked the same question. Where a site function
only the download reaches reads a document's own answer as refused and
raises a stop of the run, is that stop weighed against the list before it
can reach the run? The census finds the readings by what the code does. A
refusal is a test that reads a status of 401 or 403, a redirect, or a page
where the file should start (a "<"), in the test itself or in a site
helper it calls, two calls down at most. A stop of the run is a class of
the site module that the loop around download_one names, or one built on
it. The download path is every site function download_one reaches that
neither Discover, the session check nor Login reaches.

From each such raise the census follows the stop up through the site
functions and App methods that call it. It must meet a handler that keeps
it from going on (a bare raise, a raise of the name it caught, or a new one
of its class passes it on). That handler has to read the list again, or go
on to the next pass of a loop that does, NW Natural's way, by calling a
function Discover reaches that can raise the same stop. A refusal that
reaches download_one's loop is one document stopping every run. A handler
that keeps it without reading the list leaves a real sign-out failing
every document after it, the major of the #128 review.

The list read again has three answers, and they are kept apart. A list
refused too is a sign-out. A list that does not answer (a 500, a timeout,
a network error), answers with something else, or holds nothing proves
neither a session nor its end, so the run stops with the list unread,
nothing recorded against the document, and a run that lists first takes
it again. A list that reads leaves the document failed alone. An
independent review of the first mending found the middle one read both
wrong ways, a 500 as one document's failure (Affirm) and an empty list as
a sign-out (Affirm, FedEx, myPay, Stripe, UPS). So the read that weighs a
refusal goes through paperpull_core.refused.list_again, which keeps the
three apart, told to raise a list stop for a list that does not answer,
one the run stops on with the list unread (the list stop census holds
how). The read is found in the handler or the loop it goes on in, or in a
site function or App method they call, two calls down at most. Every list
reader called there goes through list_again, a check of the page before
the list included, since a page that cannot be read raises there too.
list_again is told the refusal's own sign-out, and each stop it passes on
is a stop of the run, so neither a class as wide as Exception nor one the
loop records as a document's failure lets a 500 through as it is.

Coverage is kept by handler, not by app. MENDED names every handler that
weighs a refusal, by the function it is in and the one that reads the
refusal, so a second kind of document an app takes its own way is named
on its own, and a handler found and not named fails. Two handlers in one
function for the same fetch are one entry, and each is still read. A refusal
the reading follows to no handler at all, a fetch handed to the method
that takes it as a function (Anthem's member documents and ID cards, which
_save_collected takes), is named in UNFOLLOWED with that method, which is
read by hand for the same list_again.

LEFT names the apps that still have the shape, each by the function that
reads the refusal, until each is looked at. A name that no longer has it
fails, so the list only shrinks. Seventeen were named on 2026-11-12 and
sixteen were mended the next day. M&T alone is left, since its list is the
one the person opened in their own tab, which nothing can read again
without wiping it, and none of its requests proves a session. Weighing a
refused statement there needs a recording of a request M&T answers with a
list first.

What this cannot see. The receipt apps, whose purchase loops name no
sign-out and meet one inside process_one (Apple's stopped sides), so what
stops a run there needs a reading of its own. A refusal told by what the tab
shows rather than by the answer (looks_signed_out after a press), a helper
more than two calls down, a stop raised by a name, and a handler kept in a
name. A list read again that is called but whose answer is thrown away is
not seen either, which each app's own tests hold, and nor is whether the
reader itself raises the sign-out only for a refusal it was shown, which
each app's own tests hold too.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What a refusal is read by, in a test or in a site helper it calls.
REFUSED_STATUSES = (401, 403, "401", "403")

# The apps that read one document's refusal as a sign-out of the whole run,
# by the site function where it is read, not yet mended. Each was seen on
# 2026-11-12. Ziply Fiber was mended that day and sixteen more on
# 2026-11-13. M&T's statement list is read from the person's own tab, and
# no request it makes proves a session, so there is nothing to read again.
LEFT = {
    "mtb": "download_statement",
}

# Every handler that weighs a refusal against the list, by app and the
# function the handler is in, with the function that reads the refusal. An
# app with more than one kind of document is named once for each handler,
# so a kind left as it was shows here. A handler found and not named
# fails, and so does one named and not found. Affirm reads its loan list
# right where it reads the refusal, so no stop is left there to keep, and
# it is read on its own below.
MENDED = {
    ("amexbanking", "download_one"): "amexbanking_download",
    ("anthem", "download_document"): "_fetch_eob",
    ("bilt", "download_statement"): "_take",
    ("bofa", "document_bytes"): "_ask_link",
    ("cetera", "download_bill"): "_fetch",
    ("fedex", "download_bill"): "_fetch_file",
    ("firsthorizon", "download_statement"): "_catch_statement",
    ("ing", "download_document"): "_fetch",
    ("irs", "download_bill"): "_fetch",
    ("mercury", "download_bill"): "_fetch_pdf",
    ("mypay", "download_document"): "_fetch",
    ("nwnatural", "download_bill"): "_fetch",
    ("portlandgeneral", "download_bill"): "_fetch",
    ("sdge", "download_bill"): "_fetch",
    ("simmons", "download_document"): "_fetch_asked",
    ("stripe", "download_bill"): "_fetch_file",
    ("tualatin", "download_bill"): "_fetch",
    ("ups", "download_bill"): "_post",
    ("verizonmobile", "download_bill"): "_fetch",
    ("ziply", "download_bill"): "_fetch",
}

# Refusals the reading follows to no handler, since the fetch is handed to
# the method that takes it as a function, by app and the site function that
# reads the refusal, with that method. Each method is read by hand below.
# Anthem's member documents and ID cards are fetched through a lambda that
# _save_collected calls.
UNFOLLOWED = {
    ("anthem", "_b64_pdf"): "_save_collected",
    ("anthem", "download_id_card"): "_save_collected",
}

# The list stops not named ListStopped, which the list stop census names in
# its LIST_STOPS.
OTHER_LIST_STOPS = {("bofa", "ListUnread")}


def entry_of(app: Path):
    found = sorted(app.glob("*_docs.py"))
    return found[0] if found else None


def site_of(app: Path):
    found = sorted(app.glob("*_site.py"))
    return found[0] if found else None


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def methods_in(tree) -> dict:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return {n.name: n for n in node.body if isinstance(n, ast.FunctionDef)}
    return {}


def own_nodes(fn):
    """The nodes of fn, functions and classes defined inside it left out,
    since they are not run where they are written."""
    todo = list(ast.iter_child_nodes(fn))
    while todo:
        n = todo.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield n
        todo.extend(ast.iter_child_nodes(n))


def calls(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            yield n


def attr_of(node, owner: str):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == owner:
        return node.attr
    return None


def parents_in(fn) -> dict:
    out = {}
    for n in ast.walk(fn):
        for child in ast.iter_child_nodes(n):
            out[child] = n
    return out


def is_list_again(call) -> bool:
    f = call.func
    return (isinstance(f, ast.Name) and f.id == "list_again") or attr_of(f, "refused") == "list_again"


def keyword(call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def argument(call, at: int, name: str):
    return call.args[at] if len(call.args) > at else keyword(call, name)


def elements(node) -> list:
    if node is None:
        return []
    return list(node.elts) if isinstance(node, (ast.Tuple, ast.List)) else [node]


def calls_outside_list_again(node):
    """The calls in node, a refused.list_again call itself included but
    nothing inside it."""
    todo = [node]
    while todo:
        n = todo.pop()
        if isinstance(n, ast.Call):
            yield n
            if is_list_again(n):
                continue
        todo.extend(ast.iter_child_nodes(n))


def label_of(node):
    """The class a handler names or a raise raises, by its last name."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class Reading:
    """One app's docs and site modules, read for what a refusal of one
    document becomes."""

    def __init__(self, app: Path, docs=None, site=None):
        self.name = app.name
        self.docs = docs if docs is not None else parse(entry_of(app))
        self.site = site if site is not None else parse(site_of(app))
        self.methods = methods_in(self.docs)
        self.funcs = {n.name: n for n in self.site.body if isinstance(n, ast.FunctionDef)}
        bases = {n.name: [label_of(b) for b in n.bases]
                 for n in self.site.body if isinstance(n, ast.ClassDef)}
        self.classes = set(bases)

        def ancestors(name):
            out, todo = set(), [name]
            while todo:
                n = todo.pop()
                if n not in out:
                    out.add(n)
                    todo.extend(b for b in bases.get(n, []) if b)
            return out
        self.ancestors = ancestors
        self.stops = self._stops()
        down = self.reached(["download_one"])
        other = self.reached(["cmd_discover", "check_session", "cmd_login"])
        self.down = down
        self.listers = self.closure(self.site_calls(self.reached(["cmd_discover"])))
        self.path = self.closure(self.site_calls(down)) - self.closure(self.site_calls(other))

    # what the App does
    def reached(self, start) -> set:
        seen, todo = set(), list(start)
        while todo:
            name = todo.pop()
            if name in seen or name not in self.methods:
                continue
            seen.add(name)
            todo.extend(attr_of(c.func, "self") for c in calls(self.methods[name]))
        return seen

    def site_calls(self, names) -> set:
        return {attr_of(c.func, "site") for m in names for c in calls(self.methods[m])} & set(self.funcs)

    def closure(self, start) -> set:
        seen, todo = set(), list(start)
        while todo:
            name = todo.pop()
            if name in seen or name not in self.funcs:
                continue
            seen.add(name)
            todo.extend(c.func.id for c in calls(self.funcs[name]) if isinstance(c.func, ast.Name))
        return seen

    def _stops(self) -> set:
        """The site classes the loop around download_one names, with the
        classes built on them. The loop stops the run on each (the list
        stop census holds that)."""
        named = set()
        for fn in self.methods.values():
            for node in own_nodes(fn):
                if not isinstance(node, ast.Try) or not any(
                        attr_of(c.func, "self") == "download_one" for s in node.body for c in calls(s)):
                    continue
                for h in node.handlers:
                    for t in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]):
                        if attr_of(t, "site") in self.classes:
                            named.add(attr_of(t, "site"))
        return {c for c in self.classes if self.ancestors(c) & named}

    # what a refusal is
    def reads_a_refusal(self, node, depth=0) -> bool:
        for n in ast.walk(node):
            if isinstance(n, ast.Constant):
                v = n.value
                if v in REFUSED_STATUSES and not isinstance(v, bool):
                    return True
                if isinstance(v, (str, bytes)) and v[:1] in ("<", b"<"):
                    return True
                if isinstance(v, str) and "redirect" in v.lower():
                    return True
            if isinstance(n, ast.Attribute) and "redirect" in n.attr.lower():
                return True
            if isinstance(n, ast.Name) and "redirect" in n.id.lower():
                return True
        if depth < 2:
            for c in calls(node):
                if isinstance(c.func, ast.Name) and c.func.id in self.funcs \
                        and self.reads_a_refusal(self.funcs[c.func.id], depth + 1):
                    return True
        return False

    def refusals(self) -> list:
        """Each raise of a stop in the download path under a test that reads
        a refusal, as (function, the raise, its class)."""
        out = []
        for name in sorted(self.path):
            fn = self.funcs[name]
            up = parents_in(fn)
            for node in own_nodes(fn):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                cls = label_of(node.exc)
                if cls not in self.stops:
                    continue
                p = up.get(node)
                while p is not None and p is not fn:
                    if (isinstance(p, (ast.If, ast.While)) and self.reads_a_refusal(p.test)) or (
                            isinstance(p, ast.ExceptHandler) and p.type is not None
                            and self.reads_a_refusal(p.type)):
                        out.append((name, node, cls))
                        break
                    p = up.get(p)
        return out

    # where a refusal goes
    def frame(self, where: str, name: str):
        return (self.funcs if where == "site" else self.methods)[name]

    def callers(self, where: str, name: str) -> list:
        """The calls of this function in the download path, as (where,
        function, the call)."""
        out = []
        for g in sorted(self.path):
            out += [("site", g, c) for c in calls(self.funcs[g])
                    if where == "site" and isinstance(c.func, ast.Name) and c.func.id == name]
        for m in sorted(self.down):
            out += [("docs", m, c) for c in calls(self.methods[m])
                    if attr_of(c.func, "site" if where == "site" else "self") == name]
        return out

    def catches(self, handler, cls: str) -> bool:
        if handler.type is None:
            return True
        names = {label_of(t) for t in (handler.type.elts if isinstance(handler.type, ast.Tuple)
                                       else [handler.type])}
        return bool(names & ({"Exception", "BaseException"} | self.ancestors(cls)))

    def passes_on(self, handler, cls: str) -> bool:
        """Whether a handler raises the refusal again, by a bare raise, by
        the name it caught, or as a new one of its class."""
        for n in own_nodes(handler):
            if isinstance(n, ast.Raise):
                if n.exc is None or (isinstance(n.exc, ast.Name) and n.exc.id == handler.name):
                    return True
                raised = label_of(n.exc)
                if raised in self.classes and (cls in self.ancestors(raised)
                                               or raised in self.ancestors(cls)):
                    return True
        return False

    def caught_at(self, where: str, name: str, node, cls: str):
        """The handler around `node` in this function that catches `cls`,
        and the try it belongs to, or (None, None)."""
        fn = self.frame(where, name)
        up = parents_in(fn)
        child, p = node, up.get(node)
        while p is not None and p is not fn:
            if isinstance(p, ast.Try) and child in p.body:
                for h in p.handlers:
                    if self.catches(h, cls):
                        return h, p
            child, p = p, up.get(p)
        return None, None

    def follow(self, where: str, name: str, node, cls: str, seen=frozenset()) -> list:
        """Where a refusal raised at `node` ends, as a list of ("run",
        function) for a way it reaches the loop around download_one, and
        ("handler", where, function, handler, try) for each handler that
        keeps it."""
        if (where, name, id(node)) in seen:
            return []
        seen = seen | {(where, name, id(node))}
        handler, attempt = self.caught_at(where, name, node, cls)
        if handler is not None and not self.passes_on(handler, cls):
            return [("handler", where, name, handler, attempt)]
        if handler is not None:
            return self.follow(where, name, attempt, cls, seen)
        if where == "docs" and name == "download_one":
            return [("run", name)]
        out = []
        for cwhere, cname, call in self.callers(where, name):
            out += self.follow(cwhere, cname, call, cls, seen)
        return out

    def readers(self, cls: str) -> set:
        """The site functions Discover reaches that can raise `cls`."""
        return {f for f in self.listers
                if any(isinstance(n, ast.Raise) and n.exc is not None
                       and cls in self.ancestors(label_of(n.exc) or "")
                       for g in self.closure([f]) for n in own_nodes(self.funcs[g]))}

    def places(self, where: str, name: str, handler, attempt) -> list:
        """The handler, and the loop its try sits in when the handler goes
        on to its next pass, one with no return or break of its own."""
        fn = self.frame(where, name)
        up = parents_in(fn)
        places = [handler]
        p = up.get(attempt)
        goes_on = not any(isinstance(n, (ast.Return, ast.Break)) for n in own_nodes(handler))
        while goes_on and p is not None and p is not fn:
            if isinstance(p, (ast.For, ast.While)):
                places.append(p)
                break
            p = up.get(p)
        return places

    def reads(self, call, readers: set) -> bool:
        """Whether a call is of a list reader, directly, by a site helper
        that calls one itself, or by an App method that reaches one."""
        f = call.func.id if isinstance(call.func, ast.Name) else attr_of(call.func, "site")
        if f in readers:
            return True
        if f in self.funcs and any(isinstance(c.func, ast.Name) and c.func.id in readers
                                   for c in calls(self.funcs[f])):
            return True
        m = attr_of(call.func, "self")
        return bool(m in self.methods and self.site_calls(self.reached([m])) & readers)

    def reads_the_list(self, where: str, name: str, handler, attempt, cls: str) -> bool:
        """Whether the handler, or the loop its try sits in, calls a
        function Discover reaches that can raise the same stop, so a session
        that ended shows there. The loop counts only for a handler that
        goes on to its next pass, one with no return or break of its own."""
        readers = self.readers(cls)
        return any(self.reads(c, readers)
                   for place in self.places(where, name, handler, attempt) for c in calls(place))

    def asked_again(self, where: str, name: str, handler, attempt, cls: str):
        """How the list is read again, in the handler or the loop it goes on
        in, and in the site functions and App methods they call, two calls
        down at most. Returns each refused.list_again call that reads the
        list, as (the sign-out it is told, the class it raises for a list
        that does not answer, the stops it passes on), and each list reader
        called outside one, by name."""
        readers = self.readers(cls)
        todo = [(place, 0) for place in self.places(where, name, handler, attempt)]
        seen, asked, raw = set(), [], []
        while todo:
            node, depth = todo.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for c in calls_outside_list_again(node):
                if is_list_again(c):
                    read = c.args[0] if c.args else keyword(c, "read")
                    if read is not None and any(self.reads(r, readers) for r in calls(read)):
                        asked.append((label_of(argument(c, 1, "signed_out")),
                                      label_of(argument(c, 2, "unread")),
                                      [label_of(s) for s in elements(argument(c, 3, "stops"))]))
                    continue
                f = c.func.id if isinstance(c.func, ast.Name) else attr_of(c.func, "site")
                m = attr_of(c.func, "self")
                if f in readers:
                    raw.append(f)
                elif depth < 2 and f in self.funcs:
                    todo.append((self.funcs[f], depth + 1))
                elif depth < 2 and m in self.methods:
                    todo.append((self.methods[m], depth + 1))
        return asked, raw

    def a_stop(self, cls) -> bool:
        """Whether a class is a stop of the run, one of the site module's
        that the loop around download_one names, or Discover does, so the
        list stop census follows it through the download."""
        if cls not in self.classes:
            return False
        caught = {attr_of(t, "site") for m in self.reached(["cmd_discover"])
                  for n in own_nodes(self.methods[m]) if isinstance(n, ast.ExceptHandler) and n.type
                  for t in (n.type.elts if isinstance(n.type, ast.Tuple) else [n.type])}
        return cls in self.stops or bool(self.ancestors(cls) & caught)

    def a_list_stop(self, cls) -> bool:
        """Whether a class is one the run stops on with the list unread. It
        is a list stop (ListStopped, a class built on it, or one the list
        stop census names), and a stop of the run (a_stop)."""
        if cls not in self.classes:
            return False
        if "ListStopped" not in self.ancestors(cls) and (self.name, cls) not in OTHER_LIST_STOPS:
            return False
        return self.a_stop(cls)

    def unweighed(self) -> list:
        """Each handler that keeps a refusal and reads the list, where the
        list is read outside refused.list_again, or list_again is told
        another sign-out than the refusal's, a class that is no list stop
        for a list that does not answer, or a stop to pass on that is no
        stop of the run, as (function, what is wrong)."""
        out = []
        for name, node, cls in self.refusals():
            for end in self.follow("site", name, node, cls):
                if end[0] != "handler" or not self.reads_the_list(*end[1:], cls):
                    continue
                asked, raw = self.asked_again(*end[1:], cls)
                if not asked:
                    out.append((end[2], "reads the list again outside refused.list_again"))
                for f in raw:
                    out.append((end[2], "reads %s outside refused.list_again" % f))
                for signed_out, unread, stops in asked:
                    if signed_out != cls:
                        out.append((end[2], "tells list_again the sign-out is %s, not %s"
                                    % (signed_out, cls)))
                    if not self.a_list_stop(unread):
                        out.append((end[2], "reads an unread list as %s, which is no list stop" % unread))
                    for s in stops:
                        if not self.a_stop(s):
                            out.append((end[2], "passes %s on, which is no stop of the run" % s))
        return sorted(set(out))

    def unfollowed(self) -> list:
        """Each refusal in a site function an App method reaches, Discover,
        the session check and Login apart, that the reading follows to no
        handler and no loop, as (function, line). A fetch handed to the
        method that takes it as a function is one."""
        wide = Reading.__new__(Reading)
        wide.__dict__.update(self.__dict__)
        other = self.reached(["cmd_discover", "check_session", "cmd_login"])
        wide.down = set(self.methods) - other
        wide.path = self.closure(self.site_calls(wide.down)) - self.closure(self.site_calls(other))
        return sorted({(name, node.lineno) for name, node, cls in wide.refusals()
                       if not wide.follow("site", name, node, cls)})

    def wrong(self) -> list:
        """Each refusal that reaches the run, or is kept by a handler that
        never reads the list, as (function, line, what is wrong)."""
        out = []
        for name, node, cls in self.refusals():
            for end in self.follow("site", name, node, cls):
                if end[0] == "run":
                    out.append((name, node.lineno, "reaches the run"))
                elif not self.reads_the_list(*end[1:], cls):
                    out.append((name, node.lineno, "is kept in %s, which never reads the list" % end[2]))
        return sorted(set(out))

    def weighed(self) -> list:
        """Each handler that keeps a refusal and reads the list, as
        (function, the function it was read in)."""
        out = []
        for name, node, cls in self.refusals():
            for end in self.follow("site", name, node, cls):
                if end[0] == "handler" and self.reads_the_list(*end[1:], cls):
                    out.append((end[2], name))
        return sorted(set(out))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and site_of(d)
              and {"download_one", "cmd_discover"} <= set(methods_in(parse(entry_of(d)))))
IDS = [d.name for d in APPS]


@pytest.fixture(scope="module")
def read():
    return {d.name: Reading(d) for d in APPS}


def test_there_are_apps_to_read():
    assert len(APPS) >= 70, IDS


@pytest.mark.parametrize("app", IDS)
def test_one_refused_document_never_stops_the_run_without_the_list(read, app):
    found = read[app].wrong()
    if app in LEFT:
        found = [f for f in found if f[0] != LEFT[app]]
    assert not found, found


def test_each_app_left_still_has_the_shape(read):
    """Once one is mended it leaves LEFT, so the census holds it from then
    on."""
    mended = sorted(app for app, fn in LEFT.items()
                    if not any(f[0] == fn for f in read[app].wrong()))
    assert not mended, mended


@pytest.mark.parametrize("app,handler", sorted(MENDED))
def test_the_handlers_that_weigh_a_refusal_are_read(read, app, handler):
    """Not vacuous. Each handler mended is seen keeping a refusal of one
    document and reading the list again."""
    assert (handler, MENDED[app, handler]) in read[app].weighed()
    assert read[app].refusals(), app
    assert "SessionExpired" in read[app].stops, app


def test_every_handler_that_weighs_a_refusal_is_named(read):
    """Coverage is kept by handler, not by app, so a second kind of
    document an app takes its own way is named on its own."""
    found = {(app, handler): fetch for app in IDS for handler, fetch in read[app].weighed()}
    assert found == MENDED


@pytest.mark.parametrize("app", IDS)
def test_a_list_read_again_tells_an_unread_list_from_a_sign_out(read, app):
    """The list read again after a refusal goes through
    refused.list_again, told to raise a list stop for a list that does not
    answer. A 500, a timeout or a list that holds nothing then stops the
    run with the list unread, neither a sign-out nor one document's
    failure."""
    assert read[app].unweighed() == []


def test_affirm_reads_its_list_where_it_reads_a_refusal(read):
    """Affirm's agreement refused reads the loan list in the same place, so
    no stop is raised there for a handler to keep. Its read goes through
    refused.list_again all the same."""
    affirm = read["affirm"]
    assert affirm.wrong() == [] and affirm.refusals() == []
    assert "download_document" in affirm.path
    fn = affirm.funcs["download_document"]
    asked = [c for c in calls(fn) if is_list_again(c)]
    assert asked and all(any(affirm.reads(r, affirm.readers("SessionExpired")) for r in calls(c.args[0]))
                         for c in asked)
    assert all(affirm.a_list_stop(label_of(c.args[2])) for c in asked)


@pytest.mark.parametrize("app", IDS)
def test_every_refusal_is_followed_or_named(read, app):
    """A refusal the reading follows to no handler is named, with the
    method that weighs it, so a fetch handed on as a function is looked at
    by hand rather than passed over."""
    named = sorted(fn for (a, fn) in UNFOLLOWED if a == app)
    assert sorted({fn for fn, _line in read[app].unfollowed()}) == named


@pytest.mark.parametrize("app,fetch", sorted(UNFOLLOWED))
def test_a_fetch_handed_on_is_weighed_by_the_method_that_takes_it(read, app, fetch):
    """The method calls the fetch it is handed inside a try whose
    SessionExpired handler reads the list again through refused.list_again,
    told the refusal's sign-out and a list stop, and a list that does not
    answer ends the method's pass there, by a return or a raise, rather
    than going on with that document counted as its own failure.

    Anthem's member documents and ID cards end their pass as their own
    list does when it will not open (_listing_incomplete), counted as
    failed with nothing recorded against the document, and the run goes on
    to the next kind. They do not leave on ListNotRead, since every run
    lists them afresh, Resume too, so Continue never stops at the same
    document, and that stop would note the EOB list as one that stopped."""
    method = read[app].methods[UNFOLLOWED[app, fetch]]
    handlers = [h for t in own_nodes(method) if isinstance(t, ast.Try) for h in t.handlers
                if h.type is not None and label_of(h.type) == "SessionExpired"]
    asked = [c for h in handlers for c in calls(h) if is_list_again(c)]
    assert asked, UNFOLLOWED[app, fetch]
    for c in asked:
        assert label_of(argument(c, 1, "signed_out")) == "SessionExpired"
        unread = label_of(argument(c, 2, "unread"))
        assert read[app].a_list_stop(unread), unread
        up = parents_in(method)
        p = up.get(c)
        while p is not None and not (isinstance(p, ast.Try) and any(c in calls(s) for s in p.body)):
            p = up.get(p)
        assert p is not None, "list_again is not inside a try"
        ends = [h for h in p.handlers if h.type is not None
                and unread in {label_of(t) for t in elements(h.type)}]
        assert ends, "nothing catches %s where the list is read again" % unread
        assert all(any(isinstance(n, (ast.Return, ast.Raise)) for n in own_nodes(h)) for h in ends)


def test_the_other_list_stops_are_the_list_stop_censuss():
    path = Path(__file__).with_name("test_every_app_stops_when_its_list_stops_while_it_downloads.py")
    named = next(ast.literal_eval(n.value) for n in parse(path).body
                 if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "LIST_STOPS" for t in n.targets))
    assert OTHER_LIST_STOPS <= set(named)


# -- the rule, on samples --------------------------------------------------------------

DOCS = '''
class App:
    def cmd_discover(self):
        try:
            site.collect_download_docs(page)
        except site.ListStopped:
            raise SystemExit(1)

    def process(self, docs):
        for doc in docs:
            try:
                self.download_one(page, doc)
            except site.SessionExpired:
                self.session_ended()
            except Exception:
                self._record(doc, "failed")

    def download_one(self, page, doc):
        if not site.download_bill(page, doc.date):
            self._record(doc, "failed")
'''

SITE = '''
class SessionExpired(Exception):
    pass


class ListStopped(Exception):
    pass


_RUN = {}


def _read(page):
    got = page.evaluate("list")
    if got.get("status") in (401, 403):
        raise SessionExpired("the list was refused")
    if not got.get("bills"):
        raise ListStopped("no bills")
    _RUN["bills"] = got["bills"]
    return got["bills"]


def collect_download_docs(page):
    return _read(page)


def _fetch(page, bill):
    got = page.evaluate("pdf")
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the bill was refused")
    return got.get("status") == 200


def download_bill(page, day):
    bills = _RUN.get("bills") or _read(page)
    found = [b for b in bills if b == day]
    if len(found) == 1:
        return _fetch(page, found[0])
    return False
'''


def sample(tmp_path, site=SITE, docs=DOCS):
    return Reading(tmp_path, docs=ast.parse(docs), site=ast.parse(site))


def said(app: Reading) -> list:
    """What is wrong, by function, without the line."""
    return [(fn, why) for fn, _line, why in app.wrong()]


OLD = SITE
WEIGHED = SITE.replace('''        return _fetch(page, found[0])
    return False''', '''        try:
            return _fetch(page, found[0])
        except SessionExpired:
            _read(page)
            return False
    return False''')


def test_the_old_way_is_found(tmp_path):
    assert said(sample(tmp_path, OLD)) == [("_fetch", "reaches the run")]


def test_a_refusal_weighed_against_the_list_passes(tmp_path):
    app = sample(tmp_path, WEIGHED)
    assert app.wrong() == [] and app.weighed() == [("download_bill", "_fetch")]


def test_a_refusal_kept_without_reading_the_list_is_found(tmp_path):
    """A sign-out then fails every document after it, one by one."""
    site = WEIGHED.replace("            _read(page)\n            return False", "            return False")
    assert said(sample(tmp_path, site)) == [
        ("_fetch", "is kept in download_bill, which never reads the list")]


@pytest.mark.parametrize("passed_on", ["raise", "raise SessionExpired('refused')"])
def test_a_refusal_passed_on_after_the_list_reads_is_found(tmp_path, passed_on):
    """Portland General's shape. A refusal right after a fresh list is
    passed on, so the list reading fine changes nothing."""
    site = WEIGHED.replace("            _read(page)\n            return False",
                           "            _read(page)\n            %s" % passed_on)
    assert said(sample(tmp_path, site)) == [("_fetch", "reaches the run")]


def test_a_refusal_kept_by_except_exception_is_followed(tmp_path):
    site = WEIGHED.replace("        except SessionExpired:", "        except Exception:")
    assert sample(tmp_path, site).wrong() == []
    site = site.replace("            _read(page)\n            return False", "            return False")
    assert said(sample(tmp_path, site)) == [
        ("_fetch", "is kept in download_bill, which never reads the list")]


def test_a_list_read_in_the_loop_around_the_try_counts(tmp_path):
    """NW Natural's shape. The list is read at the top of the next pass,
    or right before the bill when there was none kept."""
    site = SITE.replace('''def download_bill(page, day):
    bills = _RUN.get("bills") or _read(page)
    found = [b for b in bills if b == day]
    if len(found) == 1:
        return _fetch(page, found[0])
    return False''', '''def download_bill(page, day):
    for fresh in ((False, True) if _RUN else (True,)):
        if fresh:
            _read(page)
        found = [b for b in _RUN["bills"] if b == day]
        try:
            if _fetch(page, found[0]):
                return True
        except SessionExpired:
            pass
    return False''')
    app = sample(tmp_path, site)
    assert app.wrong() == [] and app.weighed() == [("download_bill", "_fetch")]
    assert said(sample(tmp_path, site.replace("            _read(page)\n", "            pass\n"))) == [
        ("_fetch", "is kept in download_bill, which never reads the list")]
    # A handler that leaves the loop never reaches the list read on its
    # next pass.
    for leaves in ("return False", "break"):
        assert said(sample(tmp_path, site.replace("        except SessionExpired:\n            pass",
                                                  "        except SessionExpired:\n            " + leaves))) == [
            ("_fetch", "is kept in download_bill, which never reads the list")], leaves


@pytest.mark.parametrize("test", [
    'got.get("redirected")', 'got.get("status") == 403', 'body.lstrip()[:1] == b"<"',
    "_signed_out(got)"])
def test_each_way_of_reading_a_refusal_is_read(tmp_path, test):
    site = OLD.replace('    if got.get("redirected") or got.get("status") in (401, 403):\n'
                       '        raise SessionExpired("the bill was refused")',
                       "    body = b''\n    if %s:\n        raise SessionExpired('refused')" % test) + '''

def _signed_out(got):
    return got.get("status") in (401, 403)
'''
    assert [w[2] for w in sample(tmp_path, site).wrong()] == ["reaches the run"]


def test_a_stop_the_loop_does_not_name_is_not_a_stop_of_the_run(tmp_path):
    """The loop records anything else as that document's failure, so that
    document fails alone."""
    docs = DOCS.replace("            except site.SessionExpired:\n                self.session_ended()\n", "")
    assert sample(tmp_path, OLD, docs).wrong() == []


def test_a_refusal_of_the_list_itself_is_not_a_documents(tmp_path):
    """_read is Discover's as well, so a refusal there is the list's and
    stops the run, as it should."""
    app = sample(tmp_path, OLD)
    assert "_read" not in app.path and "_fetch" in app.path
    assert [r[0] for r in app.refusals()] == ["_fetch"]


# -- the list read again, on samples ---------------------------------------------------
ASKED = WEIGHED.replace("            _read(page)\n            return False",
                        "            refused.list_again(lambda: _read(page), SessionExpired, ListStopped)\n"
                        "            return False")


def test_a_list_read_again_through_list_again_passes(tmp_path):
    app = sample(tmp_path, ASKED)
    assert app.wrong() == [] and app.unweighed() == []
    assert app.weighed() == [("download_bill", "_fetch")]


def test_a_list_read_again_on_its_own_is_found(tmp_path):
    """A 500 or a timeout there reaches the loop as one document's failure,
    and the run goes on with no session shown."""
    assert sample(tmp_path, WEIGHED).unweighed() == [
        ("download_bill", "reads _read outside refused.list_again"),
        ("download_bill", "reads the list again outside refused.list_again")]


def test_a_list_again_that_reads_no_list_is_not_counted(tmp_path):
    """The list read on its own, and what it gave handed to list_again,
    leaves the read's 500 outside it."""
    site = ASKED.replace("            refused.list_again(lambda: _read(page), SessionExpired, ListStopped)",
                         "            _read(page)\n"
                         "            refused.list_again(lambda: _RUN['bills'], SessionExpired, ListStopped)")
    assert sample(tmp_path, site).unweighed() == [
        ("download_bill", "reads _read outside refused.list_again"),
        ("download_bill", "reads the list again outside refused.list_again")]


def test_a_list_read_outside_list_again_beside_one_inside_is_found(tmp_path):
    """First Horizon's shape. A check of the page before the list is read
    again through list_again, made on its own, lets a page that cannot be
    read reach the loop as one document's failure."""
    site = ASKED.replace("            refused.list_again(lambda: _read(page), SessionExpired, ListStopped)",
                         "            collect_download_docs(page)\n"
                         "            refused.list_again(lambda: _read(page), SessionExpired, ListStopped)")
    assert sample(tmp_path, site).unweighed() == [
        ("download_bill", "reads collect_download_docs outside refused.list_again")]


def test_a_read_through_a_helper_inside_list_again_passes(tmp_path):
    site = ASKED.replace("lambda: _read(page)", "lambda: _again(page)") + """

def _again(page):
    collect_download_docs(page)
    return _read(page)
"""
    app = sample(tmp_path, site)
    assert app.wrong() == [] and app.unweighed() == []


@pytest.mark.parametrize("signed_out", ["Exception", "ListStopped"])
def test_a_sign_out_told_as_anything_but_the_refusals_is_found(tmp_path, signed_out):
    """list_again(read, Exception, ...) would pass every failure on as it
    is, the 500 and the timeout among them."""
    site = ASKED.replace("lambda: _read(page), SessionExpired, ListStopped",
                         "lambda: _read(page), %s, ListStopped" % signed_out)
    assert sample(tmp_path, site).unweighed() == [
        ("download_bill", "tells list_again the sign-out is %s, not SessionExpired" % signed_out)]


@pytest.mark.parametrize("stop", ["Exception", "RuntimeError", "NotAStop"])
def test_a_stop_passed_on_that_is_no_stop_of_the_run_is_found(tmp_path, stop):
    """Passed on as it is, it reaches the loop as one document's failure."""
    site = ASKED.replace("lambda: _read(page), SessionExpired, ListStopped",
                         "lambda: _read(page), SessionExpired, ListStopped, stops=(%s,)" % stop) + """

class NotAStop(Exception):
    pass
"""
    assert sample(tmp_path, site).unweighed() == [
        ("download_bill", "passes %s on, which is no stop of the run" % stop)]


def test_an_unread_list_told_as_a_sign_out_is_found(tmp_path):
    site = ASKED.replace("SessionExpired, ListStopped)", "SessionExpired, SessionExpired)")
    assert sample(tmp_path, site).unweighed() == [
        ("download_bill", "reads an unread list as SessionExpired, which is no list stop")]


def test_a_list_stop_neither_the_loop_nor_discover_names_is_found(tmp_path):
    """The loop's except Exception would record it as the document's own
    failure, which is the 500 again."""
    docs = DOCS.replace("        except site.ListStopped:\n            raise SystemExit(1)",
                        "        except site.SessionExpired:\n            raise SystemExit(1)")
    assert sample(tmp_path, ASKED, docs).unweighed() == [
        ("download_bill", "reads an unread list as ListStopped, which is no list stop")]
    docs = docs.replace("            except site.SessionExpired:\n                self.session_ended()\n",
                        "            except site.SessionExpired:\n                self.session_ended()\n"
                        "            except site.ListStopped:\n                self.list_changed()\n")
    assert sample(tmp_path, ASKED, docs).unweighed() == []


def test_a_list_read_again_in_a_helper_is_followed(tmp_path):
    site = ASKED.replace("            refused.list_again(lambda: _read(page), SessionExpired, ListStopped)",
                         "            _again(page)") + """

def _again(page):
    return refused.list_again(lambda: _read(page), SessionExpired, ListStopped)
"""
    assert sample(tmp_path, site).unweighed() == []


def test_a_fetch_handed_on_as_a_function_is_unfollowed(tmp_path):
    """Anthem's member documents. The reading cannot follow the fetch into
    the method that calls it, so it is named and read by hand."""
    docs = DOCS + """
    def cmd_letters(self):
        self._save(lambda pg: site.fetch_letter(pg))

    def _save(self, fetch_fn):
        try:
            fetch_fn(page)
        except site.SessionExpired:
            return
"""
    site = ASKED + """

def fetch_letter(page):
    if page.evaluate("letter").get("status") == 401:
        raise SessionExpired("the letter was refused")
"""
    app = sample(tmp_path, site, docs)
    assert [fn for fn, _line in app.unfollowed()] == ["fetch_letter"]
    assert app.wrong() == []

