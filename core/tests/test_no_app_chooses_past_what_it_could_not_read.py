"""A control that could not be read is never taken to be absent.

E*TRADE's control lookup read each control on the page with a two second
wait and passed over one that did not answer in time, as if it were not
there. Then it chose by counting, the one control naming the document is
pressed and two are refused as a guess. On a stalled CI runner (run
36792330947) every control timed out, the lookup found nothing and wrote
nothing down, and a test failed. On a real page with two controls naming
the document and one of them slow, the other was pressed as the only one,
the guess the count exists to refuse.

The census that followed asked every app and the core one question. Which
loops read the page element by element, keep some elements, and then
choose by what they kept, by how many there are or by an element's place
among them, and what does each do with an element it could not read. The
same shape turned up in E*TRADE's row link step, its named link and its
Download button, in Ally's rows of a date and tax rows, which are told
apart only by their place, in PG&E's look across the page, in State
Farm's controls of a date and controls carrying a name, and in Apple
Card's buttons of a date, whose name read as nothing when it could not be
read.

So that is checked here. A loop is in when it reads the page and keeps
elements, and what it kept is counted against one or two, or indexed by a
place that is not fixed, in the function itself, by a caller of the
function that returns it, or by a caller that keeps what this function
answers for each element. In such a loop a read that fails has to leave a
mark the choice reads, a name read after the loop or one the function
returns, or leave the loop. Passed over, or kept with words it did not
read, is a drop. So is the answer of a helper that answers nothing when
it could not read, or of one that hands such an answer on, taken to mean
the element is not the one. Nothing here finds a loop by the name of
anything.

Some drops are not seen here and were found by reading, with tests of
their own. A choice by preference rather than by count or place, as
E*TRADE's period picker preferring its own button over a year in its open
list. A step that assumes the other rows are folded, as Navy Federal's.
What a click revealed, the difference of two surveys of the controls,
which the core now reads whole and marks when it could not.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MODULES = sorted(p for p in (REPO / "apps").glob("*/*.py")) + \
    sorted((REPO / "core" / "paperpull_core").glob("*.py"))

# Playwright calls that read an element or the page, and can fail or wait.
READS = {
    "element_handle", "element_handles", "inner_text", "text_content", "get_attribute", "inner_html",
    "input_value", "is_visible", "is_hidden", "is_enabled", "is_disabled", "is_checked", "is_editable",
    "bounding_box", "evaluate", "evaluate_handle", "all_inner_texts", "all_text_contents", "count",
    "wait_for", "wait_for_selector", "query_selector", "query_selector_all", "get_property",
    "json_value", "content_frame", "frame_element", "get_properties",
}
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
LOOPS = (ast.For, ast.AsyncFor, ast.While)
KEEPS = ("append", "add", "extend", "insert")


def under(nodes):
    """Every node under `nodes`, not entering a nested function or class."""
    stack = list(nodes)
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, DEFS))


def call_name(c) -> str:
    f = c.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


def bare(c) -> str:
    """The name a call gives when it calls a function by its bare name, or
    "". A method call never stands for one of the module's functions."""
    return c.func.id if isinstance(c.func, ast.Name) else ""


def names(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def reads_page(nodes) -> bool:
    return any(isinstance(n, ast.Call) and (call_name(n) in READS or any(k.arg == "timeout" for k in n.keywords))
               for n in under(nodes))


def broad(handler) -> bool:
    if handler.type is None:
        return True
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    words = [c.id if isinstance(c, ast.Name) else getattr(c, "attr", "") for c in caught]
    return any(w in ("Exception", "BaseException") or "Timeout" in w or w.endswith("Error") for w in words)


def stored(nodes) -> set:
    out = set()
    for n in under(nodes):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                out |= names(t)
    return out


def leaves(nodes) -> bool:
    return any(isinstance(n, (ast.Return, ast.Raise, ast.Break)) for n in under(nodes))


def loops_of(func) -> list:
    """The loops whose nearest function is `func`."""
    out = []

    def visit(nodes):
        for n in nodes:
            if isinstance(n, DEFS):
                continue
            if isinstance(n, LOOPS):
                out.append(n)
            visit(list(ast.iter_child_nodes(n)))
    visit(func.body)
    return out


def kept_by(loop) -> set:
    return {n.func.value.id for n in under(loop.body)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in KEEPS
            and isinstance(n.func.value, ast.Name)}


def returned(func) -> set:
    out = set()
    for n in under(func.body):
        if isinstance(n, ast.Return) and n.value is not None:
            out |= names(n.value)
    return out


def built(func, start: int, seeds: set) -> set:
    """`seeds` and every name assigned after line `start` from them."""
    out, later = set(seeds), [n for n in under(func.body) if getattr(n, "lineno", 0) > start]
    grew = True
    while grew:
        grew = False
        for n in later:
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and names(n.value) & out:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for x in names(t) - out:
                        out.add(x)
                        grew = True
            elif isinstance(n, ast.For) and names(n.iter) & out:
                for x in names(n.target) - out:
                    out.add(x)
                    grew = True
    return out


def decides(func, start: int, held: set) -> int:
    """The line where `func`, after line `start`, chooses by what `held`
    names hold, by how many against one or two or by a place that is not
    fixed, or 0."""
    for n in under(func.body):
        if getattr(n, "lineno", 0) <= start:
            continue
        if isinstance(n, ast.Compare):
            sides = [n.left] + list(n.comparators)
            counted = any((isinstance(s, ast.Call) and call_name(s) == "len" and s.args and names(s.args[0]) & held)
                          or (isinstance(s, ast.Name) and s.id in held) for s in sides)
            if counted and any(isinstance(s, ast.Constant) and s.value in (1, 2) for s in sides):
                return n.lineno
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and isinstance(n.value, ast.Name) \
                and n.value.id in held and isinstance(n.slice, (ast.Name, ast.Attribute, ast.BinOp)):
            return n.lineno
    return 0


def answers_nothing(func) -> bool:
    """A reader that answers None, {}, "", False or 0 when its read fails."""
    for t in under(func.body):
        if isinstance(t, ast.Try) and reads_page(t.body):
            for h in t.handlers:
                if broad(h) and any(isinstance(s, ast.Return) and (s.value is None or (
                        isinstance(s.value, ast.Constant) and not s.value.value) or (
                        isinstance(s.value, (ast.Dict, ast.List, ast.Tuple)) and not (
                            getattr(s.value, "keys", None) or getattr(s.value, "elts", None))))
                        for s in h.body):
                    return True
    return False


def nothing_readers(funcs: dict) -> dict:
    """The module's readers that answer nothing when a read fails, and the
    functions that hand such an answer on, a name they took from one of
    them and return."""
    out = {name: f for name, f in funcs.items() if answers_nothing(f)}
    grew = True
    while grew:
        grew = False
        for name, f in funcs.items():
            if name in out:
                continue
            took = set()
            for n in under(f.body):
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and bare(n.value) in out:
                    took |= set().union(*(names(t) for t in n.targets))
            if took & returned(f):
                out[name] = f
                grew = True
    return out


def falsy_test(test, x: set) -> bool:
    """Whether `test` holds when the value named in `x` came back empty."""
    for n in ast.walk(test):
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and names(n.operand) & x:
            return True
        if isinstance(n, ast.Compare) and names(n.left) & x and any(
                isinstance(op, (ast.Is, ast.Eq)) for op in n.ops) and any(
                isinstance(c, ast.Constant) and c.value is None for c in n.comparators):
            return True
    return False


def drops(loop, readers: dict, marks: set) -> list:
    """Each place in `loop` where an element whose read failed goes on
    without a mark in `marks`, as (line, how)."""
    out = []
    for t in under(loop.body):
        if not isinstance(t, ast.Try) or not reads_page(t.body):
            continue
        for h in t.handlers:
            if broad(h) and not leaves(h.body) and not (stored(h.body) & marks):
                out.append((t.lineno, "a read that failed goes on without a mark"))
    for n in under(loop.body):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call) or bare(n.value) not in readers:
            continue
        got = set().union(*(names(t) for t in n.targets))
        marked = skipped = False
        for i in under(loop.body):
            if not isinstance(i, ast.If) or not (names(i.test) & got):
                continue
            if falsy_test(i.test, got):
                if leaves(i.body) or stored(i.body) & marks:
                    marked = True
                elif any(isinstance(s, ast.Continue) for s in under(i.body)):
                    skipped = True
            elif any(isinstance(s, ast.Call) and call_name(s) in KEEPS for s in under(i.body)):
                skipped = True
        if skipped and not marked:
            out.append((n.lineno, "%s answers nothing when it could not read, and that drops the element"
                        % call_name(n.value)))
    return out


def census(tree):
    """(the deciding loops, as (function, line, why), and their drops)."""
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    readers = nothing_readers(funcs)
    found, problems = [], []

    def judge(func, loop, why, marks):
        if (func.name, loop.lineno, why) in found:
            return
        found.append((func.name, loop.lineno, why))
        for line, how in drops(loop, readers, marks):
            said = "%s line %d, %s (%s)" % (func.name, line, how, why)
            if said not in problems:
                problems.append(said)

    for func in funcs.values():
        gives = returned(func)
        for loop in loops_of(func):
            kept = kept_by(loop)
            if not kept:
                continue
            after = {n.id for n in under(func.body) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                     and n.lineno > loop.end_lineno}
            line = decides(func, loop.end_lineno, built(func, loop.end_lineno, kept))
            if line:
                judge(func, loop, "chosen at line %d" % line, after | gives)
            elif built(func, loop.end_lineno, kept) & gives:
                for caller in funcs.values():
                    calls = [n for n in under(caller.body) if isinstance(n, (ast.Assign, ast.AnnAssign))
                             and n.value is not None and any(isinstance(c, ast.Call) and bare(c) == func.name
                                                             for c in ast.walk(n.value))]
                    for a in calls:
                        held = set().union(*(names(t) for t in (a.targets if isinstance(a, ast.Assign) else [a.target])))
                        line = decides(caller, a.lineno - 1, built(caller, a.lineno - 1, held))
                        if line:
                            judge(func, loop, "%s chooses by its answer at line %d" % (caller.name, line), after | gives)
                            break
                    else:
                        continue
                    break
            # A helper whose answer this loop keeps for each element.
            if line:
                for n in under(loop.body):
                    if isinstance(n, ast.Call) and bare(n) in funcs and bare(n) != func.name \
                            and reads_page(funcs[bare(n)].body) and bare(n) not in readers:
                        helper = funcs[bare(n)]
                        for inner in loops_of(helper):
                            judge(helper, inner, "%s keeps its answer, chosen at line %d" % (func.name, line),
                                  returned(helper))
    return found, problems


TREES = {p: ast.parse(p.read_text(encoding="utf-8-sig")) for p in MODULES}
CENSUS = {p: census(t) for p, t in TREES.items()}


def _where(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


@pytest.mark.parametrize("path", [p for p in MODULES if CENSUS[p][0]], ids=_where)
def test_a_loop_that_chooses_never_goes_on_past_what_it_could_not_read(path):
    _found, problems = CENSUS[path]
    assert not problems, "%s goes on past an element it could not read and then chooses: %s" % (
        _where(path), "; ".join(problems))


def test_the_census_finds_the_choices_it_is_about():
    """Not vacuous. The loops this was written about are found by what they
    do, and so are others in other apps."""
    found = {(_where(p).split("/")[1], f) for p, (loops, _) in CENSUS.items() for f, _line, _why in loops}
    for app, func in (("etrade", "_control_for"), ("etrade", "_row_link_for"), ("etrade", "_named_link"),
                      ("etrade", "_tick_and_download"), ("ally", "_rows_for_date"),
                      ("ally", "_find_tax_row_control"), ("ally", "_row_control_read"),
                      ("pge", "_bill_rows_page_wide"), ("statefarm", "_controls_for"),
                      ("statefarm", "_visible_named"), ("applecard", "_dated")):
        assert (app, func) in found, ((app, func), sorted(found))
    assert len(found) >= 20 and len({a for a, _ in found}) >= 8, sorted(found)


# Each shape the census found, as it stood, and as it was repaired. The check
# has to see every one of the first and pass every one of the second.
SHAPES = {
    "passed over, then counted": ("""
def pick(page):
    ctrls = page.get_by_role("link")
    kept = []
    for i in range(ctrls.count()):
        try:
            el = ctrls.nth(i).element_handle(timeout=2000)
        except Exception:
            continue
        kept.append(el)
    if len(kept) == 1:
        return kept[0]
""", """
def pick(page):
    ctrls = page.get_by_role("link")
    kept, unread = [], 0
    for i in range(ctrls.count()):
        try:
            el = ctrls.nth(i).element_handle(timeout=2000)
        except Exception:
            unread += 1
            continue
        kept.append(el)
    if unread:
        return None
    if len(kept) == 1:
        return kept[0]
"""),
    "kept with words it did not read, then taken by place": ("""
def pick(page, n):
    rows = page.locator("tr")
    kept = []
    for i in range(rows.count()):
        try:
            text = rows.nth(i).inner_text(timeout=800)
        except Exception:
            text = ""
        kept.append((rows.nth(i), text))
    plain = [r for r, t in kept if "trust" not in t]
    return plain[n]
""", """
def pick(page, n):
    rows = page.locator("tr")
    kept, unread = [], False
    for i in range(rows.count()):
        try:
            text = rows.nth(i).inner_text(timeout=800)
        except Exception:
            unread = True
            continue
        kept.append((rows.nth(i), text))
    if unread:
        return None
    plain = [r for r, t in kept if "trust" not in t]
    return plain[n]
"""),
    "a helper whose answer a counting loop keeps": ("""
def named(row):
    for j in range(row.count()):
        try:
            el = row.nth(j).element_handle(timeout=2000)
        except Exception:
            continue
        return el
    return None


def pick(page):
    rows = page.get_by_role("row")
    kept = []
    for i in range(rows.count()):
        link = named(rows.nth(i))
        if link is not None:
            kept.append(link)
    if len(kept) == 1:
        return kept[0]
""", """
def named(row):
    unread = False
    for j in range(row.count()):
        try:
            el = row.nth(j).element_handle(timeout=2000)
        except Exception:
            unread = True
            continue
        return el, False
    return None, unread


def pick(page):
    rows = page.get_by_role("row")
    kept, unread = [], 0
    for i in range(rows.count()):
        link, missed = named(rows.nth(i))
        if missed:
            unread += 1
        if link is not None:
            kept.append(link)
    if unread:
        return None
    if len(kept) == 1:
        return kept[0]
"""),
    "a reader that answers nothing, counted by a caller": ("""
def read(el):
    try:
        return el.evaluate("e => e.innerText")
    except Exception:
        return None


def dated(page, iso):
    out = []
    for h in page.query_selector_all("a"):
        got = read(h)
        if got is not None and iso in got:
            out.append(h)
    return out


def press(page, iso):
    found = dated(page, iso)
    if len(found) > 1:
        return False
    found[0].click()
""", """
def read(el):
    try:
        return el.evaluate("e => e.innerText")
    except Exception:
        return None


def dated(page, iso):
    out, unread = [], 0
    for h in page.query_selector_all("a"):
        got = read(h)
        if got is None:
            unread += 1
            continue
        if iso in got:
            out.append(h)
    return out, unread


def press(page, iso):
    found, unread = dated(page, iso)
    if unread or len(found) > 1:
        return False
    found[0].click()
"""),
    "an empty answer handed on by another helper": ("""
def label(el):
    try:
        return el.get_attribute("aria-label") or ""
    except Exception:
        return ""


def read(el):
    name = label(el)
    return name, name.endswith("2031")


def dated(page):
    names = []
    for i in range(page.count()):
        name, ok = read(page.nth(i))
        if ok:
            names.append(name)
    return names


def pick(page):
    names = dated(page)
    if len(names) != 1:
        return None
    return names[0]
""", """
def label(el):
    try:
        return el.get_attribute("aria-label") or ""
    except Exception:
        return None


def read(el):
    name = label(el)
    if name is None:
        return None, False
    return name, name.endswith("2031")


def dated(page):
    names, unread = [], 0
    for i in range(page.count()):
        name, ok = read(page.nth(i))
        if name is None:
            unread += 1
            continue
        if ok:
            names.append(name)
    if unread:
        return None
    return names


def pick(page):
    names = dated(page)
    if names is None or len(names) != 1:
        return None
    return names[0]
"""),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_check_sees_the_shape_and_passes_its_repair(shape):
    before, after = SHAPES[shape]
    found, problems = census(ast.parse(before))
    assert found and problems, (shape, found, problems)
    found, problems = census(ast.parse(after))
    assert found and not problems, (shape, found, problems)
