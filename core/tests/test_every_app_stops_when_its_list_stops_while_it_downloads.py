"""A list that stops while documents are downloaded stops the run once.

SDG&E's download_bill opens Billing History again for every bill and takes
the bill only when exactly one row there carries its invoice id and date.
When that list stopped, it logged a line and answered False, so the bill
went to Manual Review with a failure file and the run went on to the next
bill, which read the whole list again and stopped the same way. A Resume
reads no list of its own, so after a whole listing a list that now stops
(a second account has appeared, the history comes back empty, or it answers
500) sent every pending bill to review, each after a read of the whole list
against the provider's bot protection, and the run ended looking clean. An
independent review proved it on PR #126 (NW Natural, a copy of SDG&E), and
eleven apps on main had the same shape in one form or another. Nine more
answered a sign-out in their loop with a return, so the run ended with no
stop in flight and was reported as finished.

So in every document app, what stops Discover stops a download too. The
stops are found by what the code does, the exception classes of the app's
site module that a method Discover reaches catches as site.X, with their
subclasses. The download path is every site function that App.download_one
reaches and neither Discover, the session check nor Login does, with every
function those reach. Where in that path, or in the App methods download_one
reaches, or in the loop that calls download_one, a handler can catch such a
stop escaping its try, it has to leave by raising or by a stop of the run
(SystemExit, tabs.stop or a method that always does one of them). An
except Exception counts too, since it catches a stop as surely as a handler
that names it. IRS was the worked example, list_changed in its loop.

A handler that turns a stop into a document's own failure on purpose is
named below with the site functions its try calls and why, since the stop
it catches there is about that one document (its own page, its own row's
control, one account's one year) and not the list every later document
reads. A change to what that try calls fails this until it is looked at
again.

Two checks read the code. A third drives each app's own loop with a
download that raises each stop its path can let out, and the run has to
stop at the first document with nothing recorded against either.

What this cannot see. About thirty older apps signal a list that did not
show by returning False or None from the very function that also says the
record is gone, so no exception marks the difference. Their download paths
fail each document when the list page will not open or reads empty, and
each needs a distinct signal from its list reader before a rule can hold
it. They are listed in the branch notes, not here.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from paperpull_core import listing

REPO = Path(__file__).resolve().parents[2]

# A handler in a download path that turns a stop into the one document's
# failure, by (app, function, the functions its try calls), and why.
ITS_OWN = {
    ("venmo", "download_bill", ("_open_month", "ready_to_print", "show_all")):
        "a month's own statement page, opened by its own address, that does not show as "
        "asked is that month's matter. Statements itself is opened before this try "
        "(_where), and a stop there reaches the run",
    ("treasurydirect", "download_document", ("_content", "_open_history", "_open_tab",
                                             "account_of", "read_page")):
        "the snapshot's own page, reached by pressing the page's own tabs, that no longer "
        "reads as expected goes to review, as the app was built to do. The account page "
        "every document starts from is read before this try, and a stop there reaches "
        "the run",
    ("chasebusiness", "download_statement", ("_catch_statement",)):
        "a control on the statement's own row that is not one control, or that the guard "
        "refuses, before anything is pressed on it, leaves that statement for review. "
        "The list was read whole on the way to the row (_reach_row), and a stop there "
        "reaches the run",
    ("alpaca", "download_document", ("_catch_document",)):
        "the row's own Download refused by the guard, or the row or the list's answer "
        "changing between finding the row and its press, before anything is pressed, "
        "leaves that document for review, as Chase Business does. The list was read on "
        "the way to the row (_open, _find_row), and a stop there reaches the run",
    ("shelbycounty", "_press_for_blob", ("settled_here",)):
        "the page moved after this document's own press, which is that press's outcome, "
        "not a read of the list",
    ("shelbycounty", "goto_documents", ("settled_here",)):
        "the opener's answer, which every caller in the download path turns into "
        "ListStopped itself (_back_to_parcel)",
    ("spectrum", "is_detail_url", ("decode_statement_id",)):
        "an address test that answers no for a statement id it cannot read",
    ("spectrum", "details_answered", ("answer_of",)):
        "the statement's own page answers, read one by one, whose failure is said in "
        "words and refused by the caller for that statement",
    ("spectrum", "_press_for_statement", ("answer_of", "pdf_of")):
        "a PDF answer of the statement's own press that does not read, kept as empty "
        "bytes and refused for that statement",
    ("usbank", "row_search", ("_row_download_button", "_statement_rows",
                              "account_in_heading", "row_date")):
        "the list read here is one account's one year, as its pickers chose it, and a "
        "row or button of it that would not answer may be this statement or its twin, "
        "so that one is not pressed (#106). The whole list is Discover's to read",
    ("usbank", "on_documents_page", ("collect_documents",)):
        "a test of whether the statements page shows, whose no is the opener's answer "
        "(ensure_statements). An opener that answers no during a download is the shape "
        "this check cannot see, said at the top",
    ("fedex", "download_one", ("download_bill",)):
        "an invoice listed with no download link the app understands is that invoice's "
        "matter. NeedsPerson also says Billing Online is no longer connected, which "
        "would leave every invoice for review, and needs a class of its own before it "
        "can stop the run. FedEx is untested on a connected account",
    ("netbenefits", "download_document", ("make_statement",)):
        "one plan's own statement made to order, which opens that plan alone. Another "
        "plan's documents open their own plan. The plan list itself is read by "
        "_plan_for, where PlanListUnavailable stops the run",
    ("bofa", "learn_pdf_call", ("_ask_pdf",)):
        "the list answered a moment before, so a refusal of this one call says the PDF "
        "address cannot be asked from the page, not that the session ended (see its "
        "comment)",
    ("alpaca", "_catch_document", ("_link_of",)):
        "the link of a press that brought no download, read on the way to a stop of "
        "the run that follows this handler at once",
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


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and site_of(d)
              and {"download_one", "cmd_discover"} <= set(methods_in(parse(entry_of(d)))))
IDS = [d.name for d in APPS]


# -- reading the code ------------------------------------------------------------------

def self_attr(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "self":
        return node.attr
    return None


def site_attr(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "site":
        return node.attr
    return None


def calls(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            yield n


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


class App:
    """One app's docs and site modules, read."""

    def __init__(self, app: Path):
        self.name = app.name
        self.docs = parse(entry_of(app))
        self.site = parse(site_of(app))
        self.methods = methods_in(self.docs)
        self.funcs = {n.name: n for n in self.site.body if isinstance(n, ast.FunctionDef)}
        self.classes = {n.name: n for n in self.site.body if isinstance(n, ast.ClassDef)}
        self.bases = {name: [b.id for b in c.bases if isinstance(b, ast.Name)]
                      for name, c in self.classes.items()}
        self.stops = self._stops()
        self.stoppers = self._stoppers()
        self._escapes = {}

    # what Discover stops on
    def reached(self, start) -> set:
        seen, todo = set(), list(start)
        while todo:
            name = todo.pop()
            if name in seen or name not in self.methods:
                continue
            seen.add(name)
            todo.extend(self_attr(c.func) for c in calls(self.methods[name]))
        return seen

    def ancestors(self, name: str) -> set:
        out, todo = set(), [name]
        while todo:
            n = todo.pop()
            if n in out:
                continue
            out.add(n)
            todo.extend(self.bases.get(n, []))
        return out

    def _stops(self) -> set:
        caught = set()
        for m in self.reached(["cmd_discover"]):
            for n in ast.walk(self.methods[m]):
                if isinstance(n, ast.ExceptHandler) and n.type is not None:
                    for t in (n.type.elts if isinstance(n.type, ast.Tuple) else [n.type]):
                        if site_attr(t) in self.classes:
                            caught.add(site_attr(t))
        return {c for c in self.classes if self.ancestors(c) & caught}

    def _stoppers(self) -> set:
        """The App methods that always stop the run, by raising SystemExit
        or through tabs.stop or another such method, with no return of
        their own."""
        found = set()
        while True:
            more = {name for name, fn in self.methods.items() if name not in found
                    and not any(isinstance(n, ast.Return) for n in own_nodes(fn))
                    and any(self.stops_run(s, found) for s in fn.body)}
            if not more:
                return found
            found |= more

    @staticmethod
    def stops_run(stmt, stoppers) -> bool:
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
            return isinstance(exc, ast.Name) and exc.id == "SystemExit"
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            return ast.unparse(func) in ("tabs.stop", "pressing.stop_run") \
                or self_attr(func) in stoppers
        return False

    def leaves(self, body) -> bool:
        """Whether a handler's body always leaves by raising or by a stop."""
        for stmt in body:
            if isinstance(stmt, ast.Raise) or self.stops_run(stmt, self.stoppers):
                return True
            if isinstance(stmt, ast.If) and self.leaves(stmt.body) and self.leaves(stmt.orelse):
                return True
        return False

    # the download path
    def download_path(self) -> set:
        down = self.reached(["download_one"])
        other = self.reached(["cmd_discover", "check_session", "cmd_login"])

        def site_calls(names):
            return {site_attr(c.func) for m in names for c in calls(self.methods[m])} \
                & set(self.funcs)
        start = site_calls(down) - site_calls(other)
        seen, todo = set(), list(start)
        while todo:
            name = todo.pop()
            if name in seen or name not in self.funcs:
                continue
            seen.add(name)
            todo.extend(c.func.id for c in calls(self.funcs[name])
                        if isinstance(c.func, ast.Name))
        return seen

    # which stops can escape
    def matches(self, handler, name: str) -> bool:
        t = handler.type
        if t is None:
            return True
        for el in (t.elts if isinstance(t, ast.Tuple) else [t]):
            label = el.id if isinstance(el, ast.Name) else site_attr(el) or \
                (el.attr if isinstance(el, ast.Attribute) else None)
            if label in ("Exception", "BaseException") or label in self.ancestors(name):
                return True
        return False

    def raised(self, stmt, rethrown) -> set:
        if not isinstance(stmt, ast.Raise):
            return set()
        if stmt.exc is None:
            return set(rethrown)
        exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        name = exc.id if isinstance(exc, ast.Name) else site_attr(exc)
        return {name} if name in self.stops else set()

    def called(self, node, where: str) -> set:
        out = set()
        for c in calls(node):
            if where == "site" and isinstance(c.func, ast.Name) and c.func.id in self.funcs:
                out |= self.escapes("site", c.func.id)
            elif where == "docs" and site_attr(c.func) in self.funcs:
                out |= self.escapes("site", site_attr(c.func))
            elif where == "docs" and self_attr(c.func) in self.methods:
                out |= self.escapes("docs", self_attr(c.func))
        return out

    def visit(self, stmts, where: str, rethrown=frozenset(), found=None) -> set:
        """The stops that can leave these statements. Each try is read
        against its handlers, and a handler that catches a stop and does
        not leave is put in `found` with the site functions its try calls."""
        out = set()
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Try):
                left = self.visit(stmt.body, where, rethrown, found)
                for h in stmt.handlers:
                    got = {n for n in left if self.matches(h, n)}
                    left -= got
                    if got and found is not None and not self.leaves(h.body):
                        found.append((h, sorted(got), self.try_calls(stmt, where)))
                    out |= self.visit(h.body, where, frozenset(got), found)
                out |= left
                out |= self.visit(stmt.orelse, where, rethrown, found)
                out |= self.visit(stmt.finalbody, where, rethrown, found)
                continue
            out |= self.raised(stmt, rethrown)
            heads = [getattr(stmt, f) for f in ("test", "iter", "value", "exc", "context_expr")
                     if getattr(stmt, f, None) is not None]
            heads += [i.context_expr for i in getattr(stmt, "items", [])]
            for h in heads:
                out |= self.called(h, where)
            inner = [getattr(stmt, f, None) for f in ("body", "orelse")]
            if any(isinstance(b, list) for b in inner):
                for b in inner:
                    if isinstance(b, list):
                        out |= self.visit(b, where, rethrown, found)
            elif not heads:
                out |= self.called(stmt, where)
        return out

    def try_calls(self, node, where: str) -> tuple:
        names = set()
        for stmt in node.body:
            for c in calls(stmt):
                if where == "site" and isinstance(c.func, ast.Name) and c.func.id in self.funcs:
                    names.add(c.func.id)
                elif where == "docs":
                    names.add(site_attr(c.func) or self_attr(c.func) or "")
        return tuple(sorted(names - {""}))

    def escapes(self, where: str, name: str) -> set:
        key = (where, name)
        if key not in self._escapes:
            self._escapes[key] = set()
            fn = (self.funcs if where == "site" else self.methods)[name]
            self._escapes[key] = self.visit(fn.body, where)
        return self._escapes[key]

    def swallowed(self) -> list:
        """Each handler in the download path, the App methods download_one
        reaches and the loop around download_one, that catches a stop and
        does not leave, as (function, stops, the calls of its try)."""
        if not self.stops:
            return []
        out = []
        for name in sorted(self.download_path()):
            found = []
            self.visit(self.funcs[name].body, "site", found=found)
            out += [(name, got, tried) for _h, got, tried in found]
        loops = [m for m, fn in self.methods.items()
                 if any(isinstance(n, ast.Try) and any(self_attr(c.func) == "download_one"
                                                       for s in n.body for c in calls(s))
                        for n in own_nodes(fn))]
        for name in sorted(self.reached(["download_one"]) | set(loops)):
            found = []
            self.visit(self.methods[name].body, "docs", found=found)
            out += [(name, got, tried) for _h, got, tried in found]
        return out

    def let_out(self) -> set:
        """The stops download_one can let out to the loop around it."""
        return self.escapes("docs", "download_one") if self.stops else set()


def wrong(app: App) -> list:
    return ["%s catches %s and goes on" % (fn, "/".join(got))
            for fn, got, tried in app.swallowed()
            if (app.name, fn, tried) not in ITS_OWN]


@pytest.fixture(scope="module")
def read():
    return {d.name: App(d) for d in APPS}


# -- every app, read ---------------------------------------------------------------------

def test_there_are_apps_to_read():
    assert len(APPS) >= 60, IDS


@pytest.mark.parametrize("app", IDS)
def test_no_handler_turns_a_stop_into_one_documents_failure(read, app):
    assert not wrong(read[app])


def test_each_named_handler_is_still_there(read):
    """A name kept after its handler has gone would let a new one through
    unread."""
    seen = {(name, fn, tried) for name, app in read.items()
            for fn, _got, tried in app.swallowed()}
    assert not set(ITS_OWN) - seen, sorted(set(ITS_OWN) - seen)


def test_the_apps_with_the_shape_are_read(read):
    """The checks pass on an app whose Discover catches nothing, so they
    have to be seen reaching the apps whose download reads a list."""
    for name, fn in [("sdge", "download_bill"), ("irs", "download_bill"),
                     ("optum", "download_bill"), ("venmo", "download_bill"),
                     ("nelnet", "_inbox_control"), ("shelbycounty", "download_bill"),
                     ("spectrum", "take_mobile"), ("treasurydirect", "download_document"),
                     ("coinbase", "_fetch_tax_pdf"), ("alpaca", "download_document"),
                     ("chasebusiness", "download_statement"), ("simmons", "_row_button"),
                     ("bilt", "download_statement"), ("firsthorizon", "download_statement")]:
        app = read[name]
        assert "ListStopped" in app.stops, name
        assert fn in app.download_path(), (name, fn)
    for name in ("sdge", "optum", "nelnet", "coinbase", "alpaca", "irs"):
        assert "ListStopped" in read[name].let_out(), name


# -- each app's loop, driven --------------------------------------------------------------

def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def built(app: Path, tmp_path: Path):
    mod = load(app)
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return mod, mod.App(mod.build_parser().parse_args(["--config", str(cfg), "--all"]))


def a_stop(cls):
    try:
        return cls("the list answered 500")
    except TypeError:
        return cls()


LET_OUT = sorted((d.name, stop) for d in APPS for stop in sorted(App(d).let_out()))


def test_there_are_stops_to_drive():
    assert len(LET_OUT) >= 12, LET_OUT


@pytest.mark.parametrize("name,stop", LET_OUT, ids=["%s-%s" % p for p in LET_OUT])
def test_a_stop_out_of_a_download_stops_the_loop_at_once(name, stop, tmp_path, monkeypatch):
    mod, app = built(REPO / "apps" / name, tmp_path)
    taken = []

    def download_one(page, doc, filename):
        taken.append(doc.key)
        raise a_stop(getattr(mod.site, stop))
    page = MagicMock()
    page.url = "about:blank"
    for attr, value in {"download_one": download_one, "check_session": lambda *a, **k: None,
                        "_delay": lambda *a, **k: None, "_on_its_site": lambda *a, **k: page,
                        "page": lambda *a, **k: page}.items():
        monkeypatch.setattr(app, attr, value, raising=False)
    kinds = app.config.get("document_types") or ["Statement"]
    docs = [mod.Document(title="Monthly Statement", category=kinds[0],
                         summary="Monthly Statement", date=day)
            for day in ("2026-01-15", "2025-12-15")]
    assert docs[0].key != docs[1].key
    with pytest.raises(SystemExit):
        app.process(docs)
    assert taken == [docs[0].key], "%s went on past a %s" % (name, stop)
    assert app.stats.get("manual_review", 0) + app.stats.get("failed", 0) == 0
    assert not any(app.progress.get(d.key) for d in docs)
    if stop == "ListStopped" or "ListStopped" in App(REPO / "apps" / name).ancestors(stop):
        # A list that stopped leaves the listing noted as one that did not
        # end whole, so the panel offers a run that lists, not Resume.
        assert listing.last(app) == listing.STOPPED


# -- the rule, on samples --------------------------------------------------------------

DOCS = '''
class App:
    def cmd_discover(self, quiet=False):
        try:
            docs = site.collect_download_docs(page)
        except site.SessionExpired:
            self.session_ended()
        except site.ListStopped:
            raise SystemExit(1)

    def check_session(self, page):
        site.looks_signed_out(page)

    def process(self, docs):
        for doc in docs:
            try:
                self.download_one(page, doc, "x.pdf")
            except KeyboardInterrupt:
                raise
            except site.SessionExpired:
                self.session_ended()
            except Exception as e:
                self._record(doc, "failed")

    def session_ended(self):
        tabs.stop(self, ["signed out"])

    def download_one(self, page, doc, filename):
        if not site.download_bill(page, doc.date):
            self._record(doc, "review")
'''

SITE = '''
class SessionExpired(Exception):
    pass


class ListStopped(Exception):
    pass


def looks_signed_out(page):
    return False


def _bills(page):
    raise ListStopped("no table")


def collect_download_docs(page):
    return _bills(page)


def download_bill(page, iso):
    try:
        found = [b for b in _bills(page) if b == iso]
    except ListStopped as stop:
        log.info("stopped: %s", stop)
        return False
    return bool(found)
'''


def sample(tmp_path, docs=DOCS, site=SITE):
    app = tmp_path / "sample"
    app.mkdir(exist_ok=True)
    (app / "sample_docs.py").write_text(docs, encoding="utf-8")
    (app / "sample_site.py").write_text(site, encoding="utf-8")
    return App(app)


RERAISED = SITE.replace("        return False\n    return bool", "        raise\n    return bool")
STOPS = DOCS.replace("            except Exception as e:",
                     "            except site.ListStopped:\n"
                     "                self.list_changed()\n"
                     "            except Exception as e:") + '''
    def list_changed(self):
        listing.started(self)
        tabs.stop(self, ["the list stopped"])
'''


def test_the_rule_finds_the_old_way(tmp_path):
    assert wrong(sample(tmp_path)) == ["download_bill catches ListStopped and goes on"]


def test_a_stop_let_out_and_caught_by_except_exception_is_found(tmp_path):
    assert wrong(sample(tmp_path, site=RERAISED)) == ["process catches ListStopped and goes on"]


def test_a_stop_let_out_and_stopped_in_the_loop_passes(tmp_path):
    app = sample(tmp_path, docs=STOPS, site=RERAISED)
    assert wrong(app) == []
    assert app.let_out() == {"ListStopped"}


def test_a_stop_turned_into_a_stop_of_the_run_passes(tmp_path):
    site = SITE.replace("        return False\n    return bool",
                        "        raise pressing.Stop('find', 'stopped', ['stopped'])\n    return bool")
    app = sample(tmp_path, site=site)
    assert wrong(app) == [] and app.let_out() == set()


def test_except_exception_around_a_list_read_is_found(tmp_path):
    site = SITE.replace("    except ListStopped as stop:", "    except Exception as stop:")
    assert wrong(sample(tmp_path, site=site)) == ["download_bill catches ListStopped and goes on"]


def test_a_stop_raised_in_a_helper_two_calls_down_is_followed(tmp_path):
    site = SITE.replace("def collect_download_docs(page):",
                        "def _rows(page):\n    return _bills(page)\n\n\n"
                        "def collect_download_docs(page):").replace(
        "found = [b for b in _bills(page) if b == iso]", "found = [b for b in _rows(page) if b == iso]")
    assert wrong(sample(tmp_path, site=site)) == ["download_bill catches ListStopped and goes on"]


def test_a_subclass_of_a_stop_is_a_stop(tmp_path):
    site = SITE.replace("def looks_signed_out(page):",
                        "class CapReached(ListStopped):\n    pass\n\n\ndef looks_signed_out(page):").replace(
        '    raise ListStopped("no table")', '    raise CapReached("too many")')
    app = sample(tmp_path, site=site)
    assert "CapReached" in app.stops
    assert wrong(app) == ["download_bill catches CapReached and goes on"]


def test_a_stop_only_some_of_the_time_does_not_pass(tmp_path):
    site = SITE.replace("        return False\n    return bool",
                        "        if iso:\n            raise\n        return False\n    return bool")
    assert wrong(sample(tmp_path, site=site, docs=STOPS)) == [
        "download_bill catches ListStopped and goes on"]


def test_an_opener_discover_calls_too_is_not_the_download_path(tmp_path):
    """goto_documents answers False to its callers. When download_one and
    Discover both call it, each reads that answer itself, so it is not the
    download path's to judge. A helper the download's own site function
    reaches is, even when Discover reaches it too."""
    site = RERAISED + '''

def goto_documents(page):
    try:
        _bills(page)
    except ListStopped:
        return False
    return True
'''
    docs = DOCS.replace("            docs = site.collect_download_docs(page)",
                        "            site.goto_documents(page)\n"
                        "            docs = site.collect_download_docs(page)").replace(
        "        if not site.download_bill(page, doc.date):",
        "        site.goto_documents(page)\n        if not site.download_bill(page, doc.date):")
    app = sample(tmp_path, docs=docs, site=site)
    assert "goto_documents" in app.funcs
    assert "goto_documents" not in app.download_path()
