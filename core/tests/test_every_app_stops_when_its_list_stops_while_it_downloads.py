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
eleven apps on main had the same shape in one form or another. Sixteen more
answered a sign-out in their loop with a return, so the run left with no
stop in flight and was reported as finished, or as failed where main
returned 2 for it. PayPal alone had been mended (review of #61).

So in every document app, what stops Discover stops a download too. The
stops are found by what the code does, the exception classes of the app's
site module that a method Discover reaches catches as site.X, and those the
loop around download_one names, with their subclasses. The download path is
every site function that App.download_one reaches and neither Discover, the
session check nor Login does, with every function those reach. Where in
that path, or in the App methods download_one reaches, or in the loop that
calls download_one, a handler can catch such a stop escaping its try, it
has to leave by a stop of the run (SystemExit, tabs.stop, ListNotRead or a
method that always does one of them) or by raising something that still
stops it. An except Exception counts too, since it catches a stop as surely
as a handler that names it, and so does a raise of a built-in exception,
which the loop's except Exception records as one document's failure. A list
that stops leaves on ListNotRead (listing.read_again_stopped), so the panel
offers a run that reads the list first, not Continue, which would read the
same list for its first document and stop there again (#124).

A handler that turns a stop into a document's own failure on purpose is
named below with the site functions its try calls directly and why, since
the stop it catches there is about that one document (its own page, one
plan, one account's one year) and not the list every later document reads.
A change to the functions that try calls directly fails this until it is
looked at again. A call added further down is not seen.

A list stop (ListStopped or a class built on it, or a class of an app's own
named in LIST_STOPS) that a handler turns into a stop of the run has to
leave the list unread too. Every stop class is named a list stop or not,
so a new one is looked at. PayPal, Bank of America and NetBenefits stopped
on lists of their own that no class named ListStopped marks, and left on a
plain SystemExit. Simmons, Bilt, First
Horizon and Coinbase's card statements made one into a pressing.Stop, which
pressing.stop_run ended with a plain SystemExit, so the panel offered
Continue and Continue stopped at the same list again. So every way out of
such a handler passes the stop on, raises a stop class the reading follows,
calls listing.read_again_stopped (or a method that always does), or raises
a pressing stop made with list_unread=True, which stop_run turns into
ListNotRead. A function that builds the stop is followed to what each of
its returns builds. A handler whose ListStopped comes from a check made
after the document's own control was pressed is about that press, not the
list, and is named below with why.

Three checks read the code. A fourth drives each app's own loop with a
download that raises each stop its path can let out or its loop names, and
the run has to stop at the first document with nothing recorded against
either, leaving the list unread for a list stop and only then. A fifth
drives each app's main with a download that raises each stop a list stop is
made into, and the run has to leave the list unread.

What this cannot see. About thirty older apps signal a list that did not
show by returning False or None from the very function that also says the
record is gone, so no exception marks the difference, and their Discover
and loop name no class. Their download paths fail each document when the
list page will not open or reads empty, and each needs a distinct signal
from its list reader before a rule can hold it. They are listed in the
branch notes, not here. Nor does it read a stop swallowed by
contextlib.suppress, an except whose classes are kept in a name, a handler
inside a match, or a return inside a finally. None is in a download path
today. A stop raised by a name (PayPal's raise why) is followed only to
the loop that names it. A class is a list stop or not, so a class raised
both for the list and for one document has to be split first, as Bank
of America's ListUnread was, and a class built on one named here is
named with it.
"""
import ast
import builtins
import importlib
import inspect
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from paperpull_core import listing
from paperpull_core.run_reporting import PREFIX, ListNotRead

REPO = Path(__file__).resolve().parents[2]

# How a stop of the run that leaves the list unread is raised.
LIST_NOT_READ = ("ListNotRead", "run_reporting.ListNotRead", "listing.ListNotRead")

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
        "a row whose shape, or whose own save menu or Saves document link, is refused "
        "before anything on it is pressed leaves that statement for review. Chase draws "
        "two shapes of row, and a stop there would stop every later run at the same row. "
        "A refusal once something on the row was pressed stops the run (Run.presses), "
        "and a stop of the list on the way to the row (_reach_row) reaches the run",
    ("schwab", "listed_alike", ("list_documents",)):
        "one account's one day, asked only to find the id a record keeps has moved. The "
        "id the record keeps is still tried, and a document that will not come goes to "
        "review by itself, so a day refused for one account costs the others nothing. "
        "The whole list is Discover's to read",
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
        "matter. Billing Online no longer connected is NotConnected, which this handler "
        "passes on and the loop stops on. FedEx is untested on a connected account",
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
    ("portlandgeneral", "_readable", ("bills_of",)):
        "the bills of the rows read before the list stopped, gathered for the "
        "ListStopped raised next, which reaches the run",
    ("portlandgeneral", "download_bill", ("_fetch",)):
        "a refusal of the authorization this run kept from an earlier read, which "
        "reads the list again once. A refusal of a list just read reaches the run",
    ("nwnatural", "download_bill", ("_fetch",)):
        "a refusal of a View address read earlier in this run, which reads the list "
        "again once, or of one right after a list that answered, which is that bill's "
        "alone. A refusal of the list itself reaches the run",
    ("verizonmobile", "download_bill", ("_fetch", "pdf_url")):
        "a refusal of one bill's PDF, after which the history is read again. A sign-out "
        "or a list that stops shows there and reaches the run, and a history that still "
        "reads leaves the refusal that bill's alone, so one bill Verizon will not give "
        "never stops every later run at it",
    ("cetera", "download_bill", ("_fetch",)):
        "a refusal of the headers this run kept from an earlier reading, whose token "
        "may have run out, which reads the lists again once. A refusal right after the "
        "lists were read reaches the run",
}

# A handler in a download path that turns a list stop into a stop of the run
# the panel continues from, by (app, function, the functions its try calls),
# and why. Each catches a ListStopped raised by a check made after the
# document's own control was pressed, about what the press brought and not
# the list. It stops as any press does, and Continue reads the list again
# before it presses anything, which stops with the list unread when the
# list will not read.
AT_A_PRESS = {
    ("bilt", "_take", ("read_details",)):
        "the details answer the statement's own button brought, which does not name "
        "this statement",
    ("chasebusiness", "download_statement", ("_catch_statement",)):
        "a refusal once something on the statement's row was pressed (Run.presses). A "
        "refusal before any press is that statement's review, named in ITS_OWN",
    ("shelbycounty", "_press_for_blob", ("settled_here",)):
        "the page a document's print control left behind, which may be the payment site",
}

# Every stop is a list stop or not, and each app's stops are named here so a
# new one is looked at. ListStopped and the classes built on it are list
# stops. These are too, by (app, class), with why. A list stop leaves the
# list unread (ListNotRead), since a Resume reads no list of its own and its
# first document would read the same list again (#124).
LIST_STOPS = {
    ("paypal", "ReportsUnread"):
        "the business statements list, read again for each business statement, that "
        "never came",
    ("paypal", "SentElsewhere"):
        "the statements page the list is read from, which sent the tab to another of "
        "PayPal's pages, as loading it again would",
    ("bofa", "ListUnread"):
        "the page's own list call learned again, or the list posted again, for one "
        "statement, that did not answer the way this app knows",
    ("netbenefits", "PlanListUnavailable"):
        "the plan list, read again for a document whose plan this run has not listed, "
        "that did not show. A list that shows without the document's plan is that "
        "document's review",
    ("coinbase", "CardListUnread"):
        "the card statements list Discover could not read whole. No download reads it",
}

# The stops that are not a list, by class for every app or by (app, class),
# and why. Continue carries on from them once the person has done what the
# stop asked, or they are one document's.
NOT_A_LIST = {
    "SessionExpired": "a sign-in or a check, which the person answers before Continue",
    "OtpRequired": "a code only the account holder answers, before Continue",
    "DeadlineReached": "the run's own time at the site, which the next run starts again",
    ("alpaca", "NotLive"):
        "the Paper account or another page than the documents page, which the account "
        "holder changes",
    ("treasurydirect", "NotLive"):
        "a tab that is not a signed-in page with its top tabs, which the account holder "
        "changes",
    ("bofa", "NotThere"):
        "a tab that left Statements & Documents, which the person opens again",
    ("bofa", "NotLearned"):
        "in a download, one statement's own address or the page's PDF form, which no "
        "list read again changes. The list read again raises ListUnread",
    ("bofa", "ListCut"):
        "in a download, one statement's own PDF the page could not ask for. The list "
        "read again raises ListUnread",
    ("scalable", "NotBuilt"):
        "a first shell, which lists and downloads nothing until it is built, so no list "
        "read again changes it",
    ("consorsbank", "NotBuilt"):
        "a first shell, which lists and downloads nothing until it is built, so no list "
        "read again changes it",
    ("fedex", "NeedsPerson"):
        "something only the account holder may do, connecting Billing Online among them",
    ("venmo", "ProfileChanged"):
        "another Venmo profile signed in than the one listed, which the person changes "
        "back",
    ("netbenefits", "PlanDidNotOpen"):
        "one plan that opened earlier would not open again, that plan's documents alone",
    ("usbank", "RowUnread"):
        "a part of one account's one year, read for one statement, which may be that "
        "statement or its twin (#106). The whole list is Discover's",
    ("portlandgeneral", "OtherAccountShown"):
        "another account shown on the site than the one a bill was listed under, "
        "which the person chooses again before Continue",
    ("nwnatural", "Challenged"):
        "the portal's bot protection answering in place of the list or a bill, which "
        "the person answers in the browser before Continue",
    ("verizonmobile", "OtherAccountShown"):
        "another account shown in My Verizon than the one a bill was listed under, "
        "which the person chooses again before Continue",
    ("ziply", "OtherAccountShown"):
        "another account asked about on Billing than the one a bill was listed under, "
        "which the person chooses again before Continue",
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
    return nodes_of(list(ast.iter_child_nodes(fn)))


def nodes_of(stmts):
    """The nodes of these statements, with what own_nodes leaves out."""
    todo = list(stmts)
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
        self.list_stops = {c for c in self.stops if any(
            a == "ListStopped" or (self.name, a) in LIST_STOPS for a in self.ancestors(c))}
        self.stoppers = self._stoppers()
        self.list_stoppers = self._list_stoppers()
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

    def loops(self) -> list:
        """The App methods that call download_one inside a try."""
        return [m for m, fn in self.methods.items()
                if any(isinstance(n, ast.Try) and any(self_attr(c.func) == "download_one"
                                                      for s in n.body for c in calls(s))
                       for n in own_nodes(fn))]

    def _stops(self) -> set:
        """The site classes a method Discover reaches catches, and those
        the loop around download_one names, with their subclasses. A class
        the loop names is one the app treats as more than one document's
        failure, a sign-out most often."""
        caught = set()
        for m in self.reached(["cmd_discover"]) | set(self.loops()):
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
            return ast.unparse(func) in ("tabs.stop", "pressing.stop_run",
                                         "listing.read_again_stopped") \
                or self_attr(func) in stoppers
        return False

    # what leaves a list unread
    def _list_stoppers(self) -> set:
        """The App methods that always stop the run as one whose list was
        not read, through listing.read_again_stopped, ListNotRead or
        another such method, with no return of their own."""
        found = set()
        while True:
            more = {name for name, fn in self.methods.items() if name not in found
                    and not any(isinstance(n, ast.Return) for n in own_nodes(fn))
                    and any(self.stops_unread(s, found) for s in fn.body)}
            if not more:
                return found
            found |= more

    @staticmethod
    def stops_unread(stmt, list_stoppers) -> bool:
        if isinstance(stmt, ast.Raise) and stmt.exc is not None:
            exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
            return ast.unparse(exc) in LIST_NOT_READ
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            return ast.unparse(func) == "listing.read_again_stopped" \
                or self_attr(func) in list_stoppers
        return False

    def builds(self, expr, seen=frozenset()) -> set:
        """What raising `expr` raises, as far as the site module shows it,
        "unread" for a pressing stop made with list_unread=True, "stop" for
        any other pressing stop, "other" for anything this cannot follow. A
        site function is followed to what each of its returns builds."""
        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "pressing":
                unread = any(k.arg == "list_unread" and isinstance(k.value, ast.Constant)
                             and k.value.value is True for k in expr.keywords)
                return {"unread" if unread else "stop"}
            if isinstance(func, ast.Name) and func.id in self.funcs and func.id not in seen:
                returns = [n for n in own_nodes(self.funcs[func.id]) if isinstance(n, ast.Return)]
                if not returns or any(r.value is None for r in returns):
                    return {"other"}
                return set().union(*(self.builds(r.value, seen | {func.id}) for r in returns))
        return {"other"}

    def exits(self, body) -> list:
        """The ways out of a handler's body by a raise or a stop of the run."""
        return [n for n in nodes_of(body) if isinstance(n, ast.Raise)
                or (isinstance(n, ast.Expr) and self.stops_run(n, self.stoppers))]

    def leaves_unread(self, stmt, name) -> bool:
        """Whether a way out of a handler that caught a list stop leaves the
        list unread. The stop passed on, or a stop class raised, is followed
        by the reading on its way up. A pressing stop has to be made with
        list_unread=True, and a stop of the run has to be one of a list."""
        if isinstance(stmt, ast.Raise):
            if stmt.exc is None or (isinstance(stmt.exc, ast.Name) and stmt.exc.id == name):
                return True
            target = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
            label = target.id if isinstance(target, ast.Name) else site_attr(target)
            if label in self.stops or self.stops_unread(stmt, self.list_stoppers):
                return True
            return self.builds(stmt.exc) == {"unread"}
        return self.stops_unread(stmt, self.list_stoppers)

    def leaves(self, body, name=None) -> bool:
        """Whether a handler's body always leaves by a stop of the run or by
        raising something that still stops it. `name` is what the handler
        calls the exception it caught."""
        for stmt in body:
            if isinstance(stmt, ast.Raise) and self.still_stops(stmt, name):
                return True
            if self.stops_run(stmt, self.stoppers):
                return True
            if isinstance(stmt, ast.If) and self.leaves(stmt.body, name) \
                    and self.leaves(stmt.orelse, name):
                return True
        return False

    def still_stops(self, stmt, name) -> bool:
        """A raise that passes the stop on, raises another stop or a stop of
        the run, or raises what a function builds (a pressing.Stop, as
        _page_stopped does). A built-in exception other than SystemExit, or
        a site class that is no stop, is caught as one document's failure
        by the loop's except Exception, so it does not count."""
        if stmt.exc is None:
            return True
        if isinstance(stmt.exc, ast.Name) and stmt.exc.id == name:
            return True
        target = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        label = target.id if isinstance(target, ast.Name) else site_attr(target)
        known = getattr(builtins, label or "", None)
        if isinstance(known, type) and issubclass(known, BaseException):
            return issubclass(known, (SystemExit, KeyboardInterrupt))
        if label in self.classes:
            return label in self.stops
        return True

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

    def raised(self, stmt, rethrown, name=None) -> set:
        if not isinstance(stmt, ast.Raise):
            return set()
        if stmt.exc is None or (isinstance(stmt.exc, ast.Name) and stmt.exc.id == name):
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

    def visit(self, stmts, where: str, rethrown=frozenset(), found=None, name=None) -> set:
        """The stops that can leave these statements. Each try is read
        against its handlers, and a handler that catches a stop is put in
        `found` with the stops and the site functions its try calls."""
        out = set()
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Try):
                left = self.visit(stmt.body, where, rethrown, found, name)
                for h in stmt.handlers:
                    got = {n for n in left if self.matches(h, n)}
                    left -= got
                    if got and found is not None:
                        found.append((h, sorted(got), self.try_calls(stmt, where)))
                    out |= self.visit(h.body, where, frozenset(got), found, h.name)
                out |= left
                out |= self.visit(stmt.orelse, where, rethrown, found, name)
                out |= self.visit(stmt.finalbody, where, rethrown, found, name)
                continue
            out |= self.raised(stmt, rethrown, name)
            heads = [getattr(stmt, f) for f in ("test", "iter", "value", "exc", "context_expr")
                     if getattr(stmt, f, None) is not None]
            heads += [i.context_expr for i in getattr(stmt, "items", [])]
            for h in heads:
                out |= self.called(h, where)
            inner = [getattr(stmt, f, None) for f in ("body", "orelse")]
            if any(isinstance(b, list) for b in inner):
                for b in inner:
                    if isinstance(b, list):
                        out |= self.visit(b, where, rethrown, found, name)
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

    def caught(self) -> list:
        """Each handler in the download path, the App methods download_one
        reaches and the loop around download_one, that catches a stop, as
        (handler, function, stops, the calls of its try)."""
        if not self.stops:
            return []
        out = []
        for name in sorted(self.download_path()):
            found = []
            self.visit(self.funcs[name].body, "site", found=found)
            out += [[h, name, got, tried] for h, got, tried in found]
        for name in sorted(self.reached(["download_one"]) | set(self.loops())):
            found = []
            self.visit(self.methods[name].body, "docs", found=found)
            out += [[h, name, got, tried] for h, got, tried in found]
        # A handler of the loop that names a stop is the app's own word that
        # it is more than one document's failure, so it is read for what it
        # names whether or not the reading above follows the stop that far.
        seen = {id(entry[0]): entry for entry in out}
        for name, node, h, named in self.loop_handlers():
            if named and id(h) in seen:
                seen[id(h)][2] = sorted(set(seen[id(h)][2]) | set(named))
            elif named:
                out.append([h, name, named, self.try_calls(node, "docs")])
        return [tuple(entry) for entry in out]

    def loop_handlers(self):
        """Each handler of a try around download_one in the loop, as (loop,
        the try, the handler, the stops it names)."""
        for name in self.loops():
            for node in own_nodes(self.methods[name]):
                if not isinstance(node, ast.Try) or not any(
                        self_attr(c.func) == "download_one" for s in node.body for c in calls(s)):
                    continue
                for h in node.handlers:
                    named = sorted({site_attr(t) for t in (
                        h.type.elts if isinstance(h.type, ast.Tuple) else [h.type])}
                        & self.stops) if h.type is not None else []
                    yield name, node, h, named

    def driven(self) -> set:
        """The stops to drive the loop with, those download_one can let out
        and those a handler of the loop names. The reading cannot follow a
        stop raised by a name (PayPal's `raise why`), and the loop names it."""
        return self.let_out() | {n for *_rest, named in self.loop_handlers() for n in named}

    def swallowed(self) -> list:
        """Each handler that catches a stop and does not leave, as
        (function, stops, the calls of its try)."""
        return [(name, got, tried) for h, name, got, tried in self.caught()
                if not self.leaves(h.body, h.name)]

    def continued(self) -> list:
        """Each handler that catches a list stop and has a way out that does
        not leave the list unread, a pressing stop made without list_unread,
        a SystemExit, tabs.stop or a raise this cannot follow, as (function,
        list stops, the calls of its try). The panel offers Continue after
        such a stop, and Continue reads the same list for its first document
        (#124)."""
        out = []
        for h, name, got, tried in self.caught():
            lists = [g for g in got if g in self.list_stops]
            if lists and not all(self.leaves_unread(s, h.name) for s in self.exits(h.body)):
                out.append((name, lists, tried))
        return out

    def made_into(self) -> set:
        """The site functions a list stop is made into a stop of the run
        through, raised by a handler that caught one and is not named in
        AT_A_PRESS."""
        out = set()
        for h, name, got, tried in self.caught():
            if not set(got) & self.list_stops or (self.name, name, tried) in AT_A_PRESS:
                continue
            for stmt in self.exits(h.body):
                if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call) \
                        and isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id in self.funcs:
                    out.add(stmt.exc.func.id)
        return out

    def let_out(self) -> set:
        """The stops download_one can let out to the loop around it."""
        return self.escapes("docs", "download_one") if self.stops else set()


def wrong(app: App) -> list:
    return ["%s catches %s and goes on" % (fn, "/".join(got))
            for fn, got, tried in app.swallowed()
            if (app.name, fn, tried) not in ITS_OWN]


def continued_from(app: App) -> list:
    return ["%s turns %s into a stop the panel offers Continue after" % (fn, "/".join(got))
            for fn, got, tried in app.continued()
            if (app.name, fn, tried) not in AT_A_PRESS]


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


@pytest.mark.parametrize("app", IDS)
def test_no_list_stop_becomes_a_stop_the_panel_continues_from(read, app):
    assert not continued_from(read[app])


def test_each_handler_named_at_a_press_is_still_there(read):
    seen = {(name, fn, tried) for name, app in read.items()
            for fn, _got, tried in app.continued()}
    assert not set(AT_A_PRESS) - seen, sorted(set(AT_A_PRESS) - seen)


def named_a_list_or_not(app: App, stop: str) -> bool:
    return any(a == "ListStopped" or (app.name, a) in LIST_STOPS
               or a in NOT_A_LIST or (app.name, a) in NOT_A_LIST for a in app.ancestors(stop))


@pytest.mark.parametrize("app", IDS)
def test_every_stop_is_named_a_list_or_not(read, app):
    """PayPal, Bank of America and NetBenefits each stop on a list of their
    own that no class named ListStopped marks, and their loops left on a
    plain SystemExit. A stop class nobody has looked at fails here."""
    assert not [s for s in sorted(read[app].stops) if not named_a_list_or_not(read[app], s)]


def test_each_named_stop_is_still_a_stop(read):
    """A name kept after its class has gone would let a new one through."""
    gone = [k for k in list(LIST_STOPS) + list(NOT_A_LIST)
            if (isinstance(k, tuple) and k[1] not in read[k[0]].stops)
            or (isinstance(k, str) and not any(k in a.stops for a in read.values()))]
    assert not gone, gone
    assert not set(LIST_STOPS) & set(NOT_A_LIST)


def test_the_list_stops_made_into_stops_of_the_run_are_read(read):
    """Not vacuous. The handlers that make a list stop into a pressing.Stop
    are read as ones that caught a list stop, and the function each raises
    through is followed to a stop made with list_unread=True."""
    for name, fn, helper in [("simmons", "download_document", "_page_stopped"),
                             ("bilt", "download_statement", "_page_stopped"),
                             ("firsthorizon", "download_statement", "_page_stopped"),
                             ("coinbase", "_take_card_statement", "_list_changed")]:
        app = read[name]
        assert any(f == fn and "ListStopped" in got for _h, f, got, _t in app.caught()), (name, fn)
        assert helper in app.made_into(), (name, helper)
        assert app.builds(ast.parse("%s(stop)" % helper, mode="eval").body) == {"unread"}, name


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


def configured(app: Path, tmp_path: Path) -> Path:
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return cfg


def built(app: Path, tmp_path: Path):
    mod = load(app)
    cfg = configured(app, tmp_path)
    return mod, mod.App(mod.build_parser().parse_args(["--config", str(cfg), "--all"]))


def two_documents(mod, config: dict) -> list:
    kinds = config.get("document_types") or ["Statement"]
    docs = [mod.Document(title="Monthly Statement", category=kinds[0],
                         summary="Monthly Statement", date=day)
            for day in ("2026-01-15", "2025-12-15")]
    assert docs[0].key != docs[1].key
    return docs


def a_stop(cls):
    """One of the stop class, built with one word, with two (a stop that names
    two things, such as the account a bill wants and the one shown), or with
    none."""
    for args in (("the list answered 500",), ("0012", "0034"), ()):
        try:
            return cls(*args)
        except TypeError:
            continue
    raise TypeError(f"{cls.__name__} could not be built with one, two or no arguments")


DRIVEN = sorted((d.name, stop) for d in APPS for stop in sorted(App(d).driven()))


def test_there_are_stops_to_drive():
    assert len(DRIVEN) >= 12, DRIVEN
    assert {("paypal", "ReportsUnread"), ("bofa", "ListUnread"), ("bofa", "NotLearned"),
            ("netbenefits", "PlanListUnavailable")} <= set(DRIVEN)


@pytest.mark.parametrize("name,stop", DRIVEN, ids=["%s-%s" % p for p in DRIVEN])
def test_a_stop_out_of_a_download_stops_the_loop_at_once(name, stop, tmp_path, monkeypatch):
    mod, app = built(REPO / "apps" / name, tmp_path)
    taken = []

    def download_one(page, doc, filename, *_a, **_kw):
        taken.append(doc.key)
        raise a_stop(getattr(mod.site, stop))
    page = MagicMock()
    page.url = "about:blank"
    for attr, value in {"download_one": download_one, "check_session": lambda *a, **k: None,
                        "_delay": lambda *a, **k: None, "_on_its_site": lambda *a, **k: page,
                        "page": lambda *a, **k: page}.items():
        monkeypatch.setattr(app, attr, value, raising=False)
    docs = two_documents(mod, app.config)
    with pytest.raises(SystemExit) as end:
        app.process(docs)
    assert taken == [docs[0].key], "%s went on past a %s" % (name, stop)
    assert app.stats.get("manual_review", 0) + app.stats.get("failed", 0) == 0
    assert not any(app.progress.get(d.key) for d in docs)
    if stop in App(REPO / "apps" / name).list_stops:
        # A list that stopped leaves the listing noted as one that did not
        # end whole, and the run leaves on ListNotRead, so the panel offers
        # a run that lists, not Continue, which would stop here again.
        assert listing.last(app) == listing.STOPPED
        assert isinstance(end.value, ListNotRead), type(end.value)
    else:
        # A sign-in or another stop the person answers is continued from.
        assert not isinstance(end.value, ListNotRead), type(end.value)


MADE_INTO = sorted((d.name, helper) for d in APPS for helper in sorted(App(d).made_into()))


def test_there_are_list_stops_made_into_stops_of_the_run():
    assert {("simmons", "_page_stopped"), ("bilt", "_page_stopped"),
            ("firsthorizon", "_page_stopped"), ("coinbase", "_list_changed")} <= set(MADE_INTO)


def made(mod, helper: str):
    """The stop `helper` makes of a list that answered 500, each argument it
    needs the list stop itself or a step in fixed words."""
    fn = getattr(mod.site, helper)
    stop = a_stop(mod.site.ListStopped)
    return fn(*[stop if p.name == "stop" or "ListStopped" in str(p.annotation) else "a step"
                for p in inspect.signature(fn).parameters.values()
                if p.default is p.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])


@pytest.mark.parametrize("name,helper", MADE_INTO, ids=["%s-%s" % p for p in MADE_INTO])
def test_a_list_stop_made_into_a_stop_of_the_run_leaves_the_list_unread(
        name, helper, tmp_path, monkeypatch, capsys):
    """The app's own main runs Run All, and the first download raises the
    stop the app makes of a list that stopped. The run stops there with
    nothing recorded, the listing is noted as one that stopped, the failure
    file is written, and the run leaves on ListNotRead, so the result line
    has the panel offer a run that lists first, not Continue."""
    app_dir = REPO / "apps" / name
    mod = load(app_dir)
    cfg = configured(app_dir, tmp_path)
    import playwright.sync_api as sync_api

    def no_browser(*_args, **_kwargs):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))
    ran, docs, taken = [], [], []

    def cmd_run(self, mode="all", *_a, **_kw):
        ran.append(self)
        self.stats["mode"] = mode
        docs.extend(two_documents(mod, self.config))
        self.process(list(docs))

    def download_one(self, page, doc, filename, *_a, **_kw):
        taken.append(doc.key)
        raise made(mod, helper)
    page = MagicMock()
    page.url = "about:blank"
    for attr, value in {"cmd_run": cmd_run, "download_one": download_one,
                        "check_session": lambda *a, **k: None, "_delay": lambda *a, **k: None,
                        "_on_its_site": lambda *a, **k: page, "page": lambda *a, **k: page}.items():
        monkeypatch.setattr(mod.App, attr, value, raising=False)
    capsys.readouterr()
    with pytest.raises(SystemExit) as ended:
        mod.main(["--config", str(cfg), "--all", "--yes"])
    out = capsys.readouterr().out
    said = " ".join(out.split(PREFIX)[0].split())
    assert isinstance(ended.value, ListNotRead), (type(ended.value), said[-1500:])
    assert ended.value.code == 0
    app = ran[0]
    assert taken == [docs[0].key], "%s went on past the list's stop" % name
    assert app.stats.get("manual_review", 0) + app.stats.get("failed", 0) == 0
    assert not any(app.progress.get(d.key) for d in docs)
    assert listing.last(app) == listing.STOPPED
    written = sorted((tmp_path / "out").rglob("failure-*.json"))
    assert len(written) == 1, sorted(p.name for p in (tmp_path / "out").rglob("*"))
    assert json.loads(written[0].read_text(encoding="utf-8"))["step"] == made(mod, helper).step
    results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
               if line.startswith(PREFIX)]
    assert results and results[-1]["stopped"] == 1 and results[-1].get("list_not_read") == 1
    assert "then run Pilot or Run All, either of which reads the list first." in said
    for words in ("press resume", "resume carries on", "run this again"):
        assert words not in said.lower(), said[-1500:]


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
        listing.read_again_stopped(self, "the list stopped")
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
                        "        raise pressing.Stop('find', 'stopped', ['stopped'], "
                        "list_unread=True)\n    return bool")
    app = sample(tmp_path, site=site)
    assert wrong(app) == [] and app.let_out() == set()
    assert continued_from(app) == []


CONTINUED = ["download_bill turns ListStopped into a stop the panel offers Continue after"]


def test_a_list_stop_made_into_a_press_stop_the_panel_continues_from_is_found(tmp_path):
    """Simmons, Bilt and First Horizon, before this. The run stopped, so
    the first rule passes it, and the panel offered Continue."""
    site = SITE.replace("        return False\n    return bool",
                        "        raise pressing.Stop('find', 'stopped', ['stopped'], "
                        "after_a_press=True)\n    return bool")
    app = sample(tmp_path, site=site)
    assert wrong(app) == []
    assert continued_from(app) == CONTINUED


HELPER = SITE.replace("        return False\n    return bool",
                      "        raise _page_stopped(stop)\n    return bool") + '''

def _page_stopped(stop):
    return pressing.Stop('find', 'stopped', ['stopped: %s' % stop]{flag})
'''


@pytest.mark.parametrize("flag,found", [("", CONTINUED), (", list_unread=True", []),
                                        (", list_unread=False", CONTINUED)])
def test_a_function_that_makes_the_stop_is_followed(tmp_path, flag, found):
    app = sample(tmp_path, site=HELPER.replace("{flag}", flag))
    assert wrong(app) == []
    assert continued_from(app) == found
    assert app.made_into() == {"_page_stopped"}


def test_a_function_followed_to_each_of_its_returns(tmp_path):
    """Coinbase's _list_changed is raised for three reasons. A function
    that builds the stop one way on one return and another way on another
    leaves the list unread only some of the time."""
    site = HELPER.replace("{flag}", ", list_unread=True").replace(
        "def _page_stopped(stop):\n",
        "def _page_stopped(stop):\n    if not stop:\n        return _plain(stop)\n") + '''

def _plain(stop):
    return pressing.no_answer('find', 'stopped', 'stopped')
'''
    assert continued_from(sample(tmp_path, site=site)) == CONTINUED


@pytest.mark.parametrize("raised", [
    "SystemExit(0)", "RuntimeError('stopped')", "_built(stop)", "made"])
def test_a_list_stop_made_into_anything_this_cannot_follow_is_found(tmp_path, raised):
    """A SystemExit stops the run with the list noted whole. A function
    that returns something other than a pressing stop, or a name, cannot be
    followed, so it does not count as leaving the list unread."""
    site = SITE.replace("        return False\n    return bool",
                        "        made = _built(stop)\n        raise %s\n    return bool" % raised) + '''

def _built(stop):
    return RuntimeError('stopped')
'''
    assert continued_from(sample(tmp_path, site=site)) == CONTINUED


def test_a_loop_that_stops_a_list_stop_with_tabs_stop_is_found(tmp_path):
    """tabs.stop stops the run, so the first rule passes it, and the
    listing stays noted whole."""
    docs = STOPS.replace('listing.read_again_stopped(self, "the list stopped")',
                         'tabs.stop(self, ["the list stopped"])')
    app = sample(tmp_path, docs=docs, site=RERAISED)
    assert wrong(app) == []
    assert continued_from(app) == [
        "process turns ListStopped into a stop the panel offers Continue after"]
    assert continued_from(sample(tmp_path, docs=STOPS, site=RERAISED)) == []


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


def test_a_loop_that_answers_a_sign_out_with_a_return_is_found(tmp_path):
    """Sixteen loops printed Stopped and returned, and the run left with no
    stop in flight. The loop's own handler names the class, so it is read
    even where Discover catches no such class and nothing shows the stop
    leaving download_one."""
    docs = STOPS.replace("        except site.SessionExpired:\n            self.session_ended()\n", "").replace(
        "            except site.SessionExpired:\n                self.session_ended()\n",
        "            except site.SessionExpired:\n                print('Stopped.')\n                return\n")
    app = sample(tmp_path, docs=docs, site=RERAISED)
    assert "SessionExpired" in app.stops
    assert wrong(app) == ["process catches SessionExpired and goes on"]


def test_a_stop_raised_again_as_another_exception_is_found(tmp_path):
    site = SITE.replace("        return False\n    return bool",
                        "        raise RuntimeError('stopped')\n    return bool")
    assert wrong(sample(tmp_path, docs=STOPS, site=site)) == [
        "download_bill catches ListStopped and goes on"]


def test_a_stop_raised_again_by_its_name_passes(tmp_path):
    site = SITE.replace("        return False\n    return bool", "        raise stop\n    return bool")
    app = sample(tmp_path, docs=STOPS, site=site)
    assert wrong(app) == [] and app.let_out() == {"ListStopped"}
