"""A receipt app whose purchase list did not come whole does not finish
clean.

Best Buy, Home Depot, Uber and Apple read their purchase lists through the
provider's own API from inside the signed-in page, and Kroger did until
f98d3f5. When that API refused, gave no answer, or answered without the
list, partway or at its first page, each wrote a failure file and went on
as though the list had ended, and the run finished clean. The panel said
"finished, no issues reported" with purchases missed, and it offers a
failure file only when a run needs attention, so nobody was told.

So in every receipt app, a failure file written while the purchase list is
read is written where the run stops, at once or at its end. The places are
found by what the code does, every self.write_failure call in a method that
cmd_discover reaches. The block that holds the call has to raise
SystemExit, call a method that always raises it, or mark the run as one
that did not read its list, and a mark is an attribute set to True, or
added to, that a method tests before it raises SystemExit. A failure that
is not the list failing to come, a purchase the provider answered for in a
shape the app cannot use, is named below with why it does not stop a run.

An app that keeps such a mark stops on it in Discover itself and at every
way out of Pilot, Run All and Resume once they have read the list or worked
from it, since a mark nothing stops on is the same clean finish.

This reads the shape of the code. Whether a mark is ever taken away again,
which answers count as the list not coming, and a list read as ended with
no failure file written at all are left to each app's own tests, which
drive the app against made-up answers in a real browser.
"""
import ast
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# A failure file written in discovery that does not stop the run, by app
# folder and the reason the app gives, and why. Each is the provider
# answering, for one purchase or in a shape never seen, in a way the app
# cannot use, which asking again may answer the same way, so a stop would
# end every run there. The failure file is for whoever repairs the app.
NOT_THE_LIST = {
    ("uber", "a trip could not be placed on a day"):
        "the trip's details answered with no start and its list subtitle names no day "
        "the page's window holds, which asking again does not change",
    ("uber", "an order carried no date"):
        "Uber Eats answered for the order with no date of any kind on it",
    ("uber", "a trip's details came without the trip"):
        "Uber answered for one trip without the trip, which may be that trip's own answer "
        "every time, where no answer at all, a 429 or a server error stops the run",
    ("apple", "neither the family nor the account named anyone"):
        "Report a Problem answered both calls, in a shape that names nobody, which asking "
        "again does not change",
    ("apple", "the order list carried no data"):
        "the Apple Store list of an account with no orders was never seen, and if it comes "
        "without its data a stop would end every run of such an account",
    ("apple", "a details page carried no order"):
        "one order's own details page, which may come without the order every time",
}

# The commands that read the list or work from it, and so have to stop on a
# mark at every way out.
COMMANDS = ("cmd_pilot", "cmd_run", "cmd_resume")
# The calls that read the list or work from what it gave.
READERS = {"cmd_discover", "process_purchases"}


def entries():
    return sorted(p for p in (REPO / "apps").glob("*/*_receipts.py"))


ENTRIES = entries()
IDS = [p.parent.name for p in ENTRIES]


def app_class(tree):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return node
    return None


def methods_of(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    cls = app_class(tree)
    if cls is None:
        return {}
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def self_attr(node):
    """The name X of self.X, or None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "self":
        return node.attr
    return None


def self_calls(node):
    """The method names called on self anywhere under node."""
    return [self_attr(n.func) for n in ast.walk(node)
            if isinstance(n, ast.Call) and self_attr(n.func)]


def raises_system_exit(node):
    exc = node.exc if isinstance(node, ast.Raise) else None
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def in_statements(statements):
    """Every node under a list of statements."""
    for stmt in statements:
        yield from ast.walk(stmt)


def marked(statements):
    """The attributes the statements set to True or add to."""
    out = set()
    for node in in_statements(statements):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and node.value.value is True:
            out |= {self_attr(t) for t in node.targets} - {None}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("add", "update") and self_attr(node.func.value):
            out.add(self_attr(node.func.value))
    return out


def stop_flags(methods):
    """The marks, and the methods that stop on them, as (flags, flag_stops).

    A mark is an attribute a method tests in an if whose body raises
    SystemExit, and that a method other than __init__ sets to True or adds
    to. The second half leaves out what a stop tests that is not a mark, a
    connected browser with no context in it, or a count of lists missed in
    a row, which stops the run where it is counted."""
    tested = {}
    for name, fn in methods.items():
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and any(raises_system_exit(n)
                                                for n in in_statements(node.body)):
                for attr in {self_attr(n) for n in ast.walk(node.test)} - {None}:
                    tested.setdefault(attr, set()).add(name)
    set_somewhere = set()
    for name, fn in methods.items():
        if name != "__init__":
            set_somewhere |= marked(fn.body)
    flags = set(tested) & set_somewhere
    return flags, {name for attr in flags for name in tested[attr]}


def stoppers(methods):
    """The methods that always raise SystemExit, at the top of their body or
    through another that does."""
    found = set()
    while True:
        more = {name for name, fn in methods.items() if name not in found and any(
            raises_system_exit(s) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                                      and self_attr(s.value.func) in found)
            for s in fn.body)}
        if not more:
            return found
        found |= more


def marks(statements, flags):
    """Whether one of the statements, itself and not something inside it,
    sets a flag to True or adds to one."""
    return any(isinstance(s, (ast.Assign, ast.Expr)) and marked([s]) & flags
               for s in statements)


def markers(methods, flags):
    """The methods that set a flag at the top of their body."""
    return {name for name, fn in methods.items() if marks(fn.body, flags)}


def reached_from_discover(methods):
    seen, todo = set(), ["cmd_discover"]
    while todo:
        name = todo.pop()
        if name in seen or name not in methods or name == "write_failure":
            continue
        seen.add(name)
        todo += self_calls(methods[name])
    return seen


def blocks(fn):
    """Each statement in fn with the block that holds it, nested functions
    left out, since they are not run where they are written."""
    def visit(statements):
        for stmt in statements:
            yield stmt, statements
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, field, None)
                if isinstance(inner, list):
                    yield from visit(inner)
            for handler in getattr(stmt, "handlers", None) or []:
                yield from visit(handler.body)
    yield from visit(fn.body)


def own_nodes(stmt):
    """The nodes of a statement itself, not of the blocks inside it."""
    todo = [stmt]
    while todo:
        node = todo.pop()
        yield node
        for field, value in ast.iter_fields(node):
            if field in ("body", "orelse", "finalbody", "handlers") and node is stmt:
                continue
            if isinstance(value, list):
                todo += [v for v in value if isinstance(v, ast.AST)]
            elif isinstance(value, ast.AST):
                todo.append(value)


def failures_in_discovery(path):
    """Each failure file written in a method cmd_discover reaches, as
    (method, line, reason, covered)."""
    methods = methods_of(path)
    flags, _stops = stop_flags(methods)
    always = stoppers(methods)
    marking = markers(methods, flags)
    out = []
    for name in sorted(reached_from_discover(methods)):
        for stmt, block in blocks(methods[name]):
            for node in own_nodes(stmt):
                if not (isinstance(node, ast.Call) and self_attr(node.func) == "write_failure"):
                    continue
                reason = node.args[1].value if len(node.args) > 1 and isinstance(
                    node.args[1], ast.Constant) else ast.unparse(node.args[1]) if len(
                    node.args) > 1 else ""
                called = set(self_calls(ast.Module(body=block, type_ignores=[])))
                # A call that marks counts only as a statement of the block
                # itself, as a mark does, not one under an if inside it.
                said = {self_attr(s.value.func) for s in block
                        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)}
                covered = (any(raises_system_exit(n) for n in in_statements(block))
                           or bool(called & always) or bool(said & marking)
                           or marks(block, flags))
                out.append((name, node.lineno, reason, covered))
    return out


def unstopped(path):
    """What in this app writes a failure file while its list is read and
    still lets the run finish clean."""
    app = path.parent.name
    return ["%s line %d, %r" % (name, line, reason)
            for name, line, reason, covered in failures_in_discovery(path)
            if not covered and (app, reason) not in NOT_THE_LIST]


def ways_out_without_a_stop(path):
    """In an app that keeps a mark, each way out of Discover, Pilot, Run All
    and Resume that does not stop on it."""
    methods = methods_of(path)
    _flags, stops = stop_flags(methods)
    if not stops:
        return []
    wrong = []
    discover = methods.get("cmd_discover")
    if discover is None or not set(self_calls(discover)) & stops:
        wrong.append("cmd_discover never stops on the mark")

    def a_stop(stmt):
        return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) \
            and self_attr(stmt.value.func) in stops

    for command in COMMANDS:
        fn = methods.get(command)
        if fn is None:
            continue
        read = [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Call) and self_attr(n.func) in READERS]
        if not read:
            continue
        for stmt, block in blocks(fn):
            if isinstance(stmt, ast.Return) and stmt.lineno > min(read):
                at = block.index(stmt)
                if at == 0 or not a_stop(block[at - 1]):
                    wrong.append("%s returns at line %d without stopping on the mark"
                                 % (command, stmt.lineno))
        last = fn.body[-1]
        if not (a_stop(last) or isinstance(last, (ast.Return, ast.Raise))):
            wrong.append("%s ends without stopping on the mark" % command)
    return wrong


# -- every receipt app ------------------------------------------------------------------

def test_there_are_receipt_apps_to_check():
    assert len(ENTRIES) >= 14, IDS


def test_the_check_finds_what_it_looks_for():
    """Not a check that passes because it finds nothing to look at. Every
    receipt app writes a failure file when its list never opens, and
    Kroger's mark for a history cut short is found as one."""
    found = {p.parent.name: failures_in_discovery(p) for p in ENTRIES}
    assert all(found.values()), [app for app, f in found.items() if not f]
    kroger = REPO / "apps" / "kroger" / "kroger_receipts.py"
    assert "_history_cut_short" in stop_flags(methods_of(kroger))[0]
    assert any(reason == "the purchase history api stopped partway" and covered
               for _name, _line, reason, covered in found["kroger"])


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_a_failure_in_reading_the_list_stops_the_run(entry):
    assert not unstopped(entry)


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_a_run_that_did_not_read_its_list_stops_on_its_way_out(entry):
    assert not ways_out_without_a_stop(entry)


def test_the_apps_that_keep_a_mark_are_checked_for_their_ways_out():
    """The second check passes on an app with no mark to stop on, so it has
    to be seen reaching the apps that keep one."""
    with_a_mark = {p.parent.name for p in ENTRIES if stop_flags(methods_of(p))[1]}
    assert {"apple", "bestbuy", "homedepot", "kroger", "uber"} <= with_a_mark, with_a_mark


def test_each_failure_named_as_not_the_list_is_still_there():
    """A name left behind after its code changed would let a new failure
    with the same words through without anybody looking at it."""
    found = {(p.parent.name, reason) for p in ENTRIES
             for _name, _line, reason, _covered in failures_in_discovery(p)}
    assert set(NOT_THE_LIST) <= found, set(NOT_THE_LIST) - found


# -- the rule, on samples --------------------------------------------------------------

STOP = '''
    def _stop_if_cut_short(self):
        if self._cut_short:
            print("Not all of it came.")
            raise SystemExit(0)

    def _cut(self):
        self._cut_short = True
'''


def sample(tmp_path, body, extra=STOP):
    path = tmp_path / "sample" / "sample_receipts.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text("class App:\n" + body + extra, encoding="utf-8")
    return path


def test_the_rule_catches_the_old_way(tmp_path):
    """The shape Best Buy shipped, a failure file and the end of the walk."""
    path = sample(tmp_path, '''
    def cmd_discover(self, finish=True):
        for year in years:
            got = site.fetch_year(page, query, year)
            if got["status"] != 200:
                self.write_failure("read the purchase history", "the history query failed")
                break
        if finish:
            self._stop_if_cut_short()
''')
    found = unstopped(path)
    assert len(found) == 1 and found[0].startswith("cmd_discover line ") \
        and found[0].endswith("'the history query failed'"), found


@pytest.mark.parametrize("stops", [
    "                raise SystemExit(0)\n",
    "                self._cut_short = True\n",
    "                self._sides_cut_short.add(side)\n",
    "                self._gone()\n",
    "                self._note(side)\n",
], ids=["raises", "marks", "adds to a mark", "calls what always raises", "calls what marks"])
def test_the_rule_takes_a_stop_or_a_mark_in_the_same_block(tmp_path, stops):
    path = sample(tmp_path, '''
    def cmd_discover(self, finish=True):
        for year in years:
            got = site.fetch_year(page, query, year)
            if got["status"] != 200:
                self.write_failure("read the purchase history", "the history query failed")
%s                break
        if finish:
            self._stop_if_cut_short()

    def _gone(self):
        print("It stopped.")
        raise SystemExit(0)

    def _note(self, side):
        self._sides_cut_short.add(side)
''' % stops, extra=STOP.replace("if self._cut_short:", "if self._cut_short or self._sides_cut_short:"))
    assert not unstopped(path)


def test_a_mark_nothing_stops_on_is_not_a_mark(tmp_path):
    path = sample(tmp_path, '''
    def cmd_discover(self):
        if not query:
            self._noted = True
            self.write_failure("read the purchase history", "the page made no history query")
''')
    assert unstopped(path)


def test_a_mark_set_only_some_of_the_time_does_not_cover_the_failure(tmp_path):
    path = sample(tmp_path, '''
    def cmd_discover(self):
        if not query:
            if pages:
                self._cut_short = True
            self.write_failure("read the purchase history", "the page made no history query")
''')
    assert unstopped(path)


def test_a_call_that_marks_only_some_of_the_time_does_not_cover_the_failure(tmp_path):
    path = sample(tmp_path, '''
    def cmd_discover(self):
        if not query:
            if pages:
                self._cut()
            self.write_failure("read the purchase history", "the page made no history query")
''')
    assert unstopped(path)


def test_what_a_stop_tests_is_a_mark_only_once_something_sets_it(tmp_path):
    """browser() stops on a connected browser with no context in it, which
    is not a run that did not read its list, and no method sets it."""
    path = sample(tmp_path, '''
    def browser(self):
        self._browser = connect()
        if not self._browser.contexts:
            raise SystemExit("Connected browser has no context.")
''', extra="")
    assert stop_flags(methods_of(path)) == (set(), set())


def test_a_mark_set_somewhere_else_does_not_cover_the_failure(tmp_path):
    path = sample(tmp_path, '''
    def cmd_discover(self, finish=True):
        if pages:
            self._cut_short = True
        if not query:
            self.write_failure("read the purchase history", "the page made no history query")
        if finish:
            self._stop_if_cut_short()
''')
    assert unstopped(path)


def test_a_failure_in_a_helper_discovery_calls_is_found(tmp_path):
    path = sample(tmp_path, '''
    def cmd_discover(self):
        walk = self._walk()
        self._say(walk)

    def _say(self, walk):
        if walk["stop"] == "refused":
            print("Stopped answering partway.")
            self.write_failure("read the list", "a list call was not answered")

    def process_one(self, purchase):
        self.write_failure("save the receipt", "no receipt came back")
''')
    found = unstopped(path)
    assert len(found) == 1 and found[0].startswith("_say line ") \
        and found[0].endswith("'a list call was not answered'"), found


def test_a_command_that_reads_the_list_has_to_stop_on_the_mark_on_its_way_out(tmp_path):
    good = '''
    def cmd_discover(self, finish=True):
        if finish:
            self._stop_if_cut_short()

    def cmd_run(self):
        if not self.args.yes:
            print("Aborted.")
            return
        self.cmd_discover(finish=False)
        selected = self._select()
        if not selected:
            print("Nothing to do.")
            self._stop_if_cut_short()
            return
        self.process_purchases(selected)
        self._stop_if_cut_short()
'''
    assert not ways_out_without_a_stop(sample(tmp_path, good))
    early = good.replace("            self._stop_if_cut_short()\n            return",
                         "            return")
    found = ways_out_without_a_stop(sample(tmp_path, early))
    assert len(found) == 1 and found[0].startswith("cmd_run returns at line ") \
        and found[0].endswith("without stopping on the mark"), found
    late = good.replace("        self.process_purchases(selected)\n        self._stop_if_cut_short()",
                        "        self.process_purchases(selected)")
    assert ways_out_without_a_stop(sample(tmp_path, late)) == [
        "cmd_run ends without stopping on the mark"]
    never = good.replace("        if finish:\n            self._stop_if_cut_short()\n",
                         "        pass\n")
    assert ways_out_without_a_stop(sample(tmp_path, never)) == [
        "cmd_discover never stops on the mark"]
