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

LEFT names the apps that still have the shape, each by the function that
reads the refusal, until each is looked at. A name that no longer has it
fails, so the list only shrinks.

What this cannot see. The receipt apps, whose purchase loops name no
sign-out and meet one inside process_one (Apple's stopped sides), so what
stops a run there needs a reading of its own. A refusal told by what the tab
shows rather than by the answer (looks_signed_out after a press), a helper
more than two calls down, a stop raised by a name, and a handler kept in a
name. A list read again that is called but whose answer is thrown away is
not seen either, which each app's own tests hold.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What a refusal is read by, in a test or in a site helper it calls.
REFUSED_STATUSES = (401, 403, "401", "403")

# The apps that read one document's refusal as a sign-out of the whole run,
# by the site function where it is read, not yet looked at. Each was seen
# on 2026-11-12. Ziply Fiber was mended that day.
LEFT = {
    "affirm": "download_document",
    "amexbanking": "amexbanking_download",
    "anthem": "download_document",
    "bilt": "_take",
    "bofa": "document_bytes",
    "fedex": "_fetch_file",
    "firsthorizon": "_catch_statement",
    "ing": "_fetch",
    "irs": "_fetch",
    "mtb": "download_statement",
    "mypay": "download_document",
    "portlandgeneral": "_fetch",
    "sdge": "_fetch",
    "simmons": "_fetch_asked",
    "stripe": "_fetch_file",
    "tualatin": "_fetch",
    "ups": "_post",
}


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

    def reads_the_list(self, where: str, name: str, handler, attempt, cls: str) -> bool:
        """Whether the handler, or the loop its try sits in, calls a
        function Discover reaches that can raise the same stop, so a session
        that ended shows there. The loop counts only for a handler that
        goes on to its next pass, one with no return or break of its own."""
        readers = {f for f in self.listers
                   if any(isinstance(n, ast.Raise) and n.exc is not None
                          and cls in self.ancestors(label_of(n.exc) or "")
                          for g in self.closure([f]) for n in own_nodes(self.funcs[g]))}
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
        for place in places:
            for c in calls(place):
                f = c.func.id if isinstance(c.func, ast.Name) else attr_of(c.func, "site")
                if f in readers:
                    return True
                m = attr_of(c.func, "self")
                if m in self.methods and self.site_calls(self.reached([m])) & readers:
                    return True
        return False

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


def test_the_apps_that_weigh_a_refusal_are_read(read):
    """Not vacuous. The apps mended so far are seen reading a refusal of
    one document and keeping it in a function that reads the list again."""
    assert ("download_bill", "_fetch") in read["cetera"].weighed()
    assert ("download_bill", "_fetch") in read["verizonmobile"].weighed()
    assert ("download_bill", "_fetch") in read["nwnatural"].weighed()
    assert ("download_bill", "_fetch") in read["ziply"].weighed()
    for app in ("cetera", "verizonmobile", "nwnatural", "ziply"):
        assert read[app].refusals(), app
        assert "SessionExpired" in read[app].stops, app


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
