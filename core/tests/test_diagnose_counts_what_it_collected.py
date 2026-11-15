"""What a Diagnose writes as "collected" is a count, never an error.

The core reads a detailed Diagnose file for whether it read anything at all
(paperpull_core.words, _note_what_was_read). A report made on a sign-in page
or a security check that collected nothing says so, and the panel tells the
person to sign in rather than that a report was saved. "Nothing" there is a
count of none.

Seven apps wrote the error their listing met into "collected", the type of
error in four first shells and its whole message in Fidelity, NetBenefits and
Invest529. A signed-out report then held words there, which read as
something collected, so it was called a saved report. And three of those
wrote the count over the error a moment later anyway, so the error was lost
and a listing that failed read as an account with nothing to list. An error
goes under a key of its own, "collect_error", as several apps already did.

The core reads every key of paperpull_core.words.COUNT_KEYS for that count,
not "collected" alone, since some apps count under another name, so each of
those keys is held to a count here the same way. The core takes only a
whole number there, so an error is not read as a count, and still a key
that says how much was read holds how much was read. U.S. Bank wrote the
error its statement reader met under "statements_read", one of them, and
now writes it under "collect_error" too.

This reads the shape of the code. Every write of "collected" in an app's
own script is a len() of something, a whole number such as the 0 a failed
listing collected, or, as two apps write it, a len() or None. A write is an
assignment, plain, added to, typed, or one of several targets at once, a
dict written out with the key, from a list of pairs too, a keyword of that
name, setdefault(), __setitem__() or operator.setitem(). A key held in a
variable is not read, and no app writes it that way.
"""
import ast
from pathlib import Path

import pytest

from paperpull_core.words import COUNT_KEYS

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in REPO.glob("apps/*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")) and not p.name.startswith("."))


def _is_count(node) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
        return True
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return True
    if isinstance(node, ast.IfExp):
        return all(_is_count(n) or (isinstance(n, ast.Constant) and n.value is None)
                   for n in (node.body, node.orelse))
    return False


def _const_key(key):
    """A constant key, through Fixed("...") as ING writes its keys, or None."""
    if isinstance(key, ast.Call) and key.args and isinstance(key.args[0], ast.Constant):
        key = key.args[0]
    return key.value if isinstance(key, ast.Constant) else None


def _key(target):
    """The constant key of a subscript, or None."""
    return _const_key(target.slice) if isinstance(target, ast.Subscript) else None


def _pairs(target, value):
    """Each target an assignment writes, with the value it gets. The parts
    of a tuple or list target take the parts of a value of the same length,
    and otherwise the whole value, which is then no count and so is refused
    rather than passed unread."""
    if isinstance(target, (ast.Tuple, ast.List)):
        parts = (value.elts if isinstance(value, (ast.Tuple, ast.List))
                 and len(value.elts) == len(target.elts) else None)
        for i, part in enumerate(target.elts):
            yield from _pairs(part, parts[i] if parts else value)
    else:
        yield target, value


def _writes_in(tree):
    """Each value written to a key of COUNT_KEYS in this tree, with its line
    and the key."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for part, value in _pairs(target, node.value):
                    if _key(part) in COUNT_KEYS:
                        yield value.lineno, value, _key(part)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if _key(node.target) in COUNT_KEYS and node.value is not None:
                yield node.value.lineno, node.value, _key(node.target)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is not None and _const_key(key) in COUNT_KEYS:
                    yield value.lineno, value, _const_key(key)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in COUNT_KEYS:
                    yield keyword.value.lineno, keyword.value, keyword.arg
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            args = node.args
            if (name in ("setdefault", "__setitem__") and len(args) == 2
                    and _const_key(args[0]) in COUNT_KEYS):
                yield args[1].lineno, args[1], _const_key(args[0])
            if name == "setitem" and len(args) == 3 and _const_key(args[1]) in COUNT_KEYS:
                yield args[2].lineno, args[2], _const_key(args[1])
            if name in ("update", "dict") and args and isinstance(args[0], (ast.List, ast.Tuple)):
                for pair in args[0].elts:
                    if (isinstance(pair, (ast.Tuple, ast.List)) and len(pair.elts) == 2
                            and _const_key(pair.elts[0]) in COUNT_KEYS):
                        yield pair.elts[1].lineno, pair.elts[1], _const_key(pair.elts[0])


def _writes(path: Path):
    return _writes_in(ast.parse(path.read_text(encoding="utf-8")))


def test_the_census_finds_apps_to_read():
    assert len(ENTRIES) > 80
    assert sum(1 for p in ENTRIES for _ in _writes(p)) >= 40, "the census found the writes"


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.parent.name)
def test_collected_is_only_ever_a_count(path):
    wrong = ["%s:%d %s" % (path.relative_to(REPO), line, key)
             for line, value, key in _writes(path) if not _is_count(value)]
    assert not wrong, ("something other than a count is written where the core reads how "
                       "much a Diagnose read. Put an error under collect_error. "
                       + ", ".join(wrong))


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_the_census_reads_every_key_the_core_reads(key):
    found = list(_writes_in(ast.parse('info["%s"] = "ERR %%s" %% e' % key)))
    assert len(found) == 1 and found[0][2] == key and not _is_count(found[0][1])


def test_the_census_tells_an_error_from_a_count():
    """Its own check, against the two shapes it is there to catch and the
    shapes it lets through."""
    def value(src):
        return ast.parse(src).body[0].value
    assert _is_count(value("x = len(docs)"))
    assert _is_count(value("x = len(docs) if docs is not None else None"))
    assert _is_count(value("x = 0"))
    assert not _is_count(value("x = True"))
    assert not _is_count(value("x = type(e).__name__"))
    assert not _is_count(value('x = "%s: %s" % (type(e).__name__, e)'))
    assert not _is_count(value("x = len(docs) if docs else type(e).__name__"))


@pytest.mark.parametrize("src", [
    'info["collected"] = type(e).__name__',
    'info[Fixed("collected")] = type(e).__name__',
    'info["collected"] += type(e).__name__',
    'info["collected"]: str = type(e).__name__',
    'info = {"collected": type(e).__name__}',
    'info.update(collected=type(e).__name__)',
    'info.update({"collected": type(e).__name__})',
    'info = dict(collected=type(e).__name__)',
    'info.setdefault("collected", type(e).__name__)',
    'info.setdefault(Fixed("collected"), type(e).__name__)',
    'info["collected"], info["collect_error"] = type(e).__name__, str(e)',
    '[info["collected"], err] = [type(e).__name__, str(e)]',
    'info["collected"], err = listing()',
    'info.__setitem__("collected", type(e).__name__)',
    'operator.setitem(info, "collected", type(e).__name__)',
    'info.update([("collected", type(e).__name__)])',
    'info = dict([("collected", type(e).__name__)])',
])
def test_the_census_reads_every_way_to_write_the_key(src):
    """An app writing the key another way than an assignment is read too,
    not passed unread. Each way here writes an error, so each is found once
    and refused."""
    found = list(_writes_in(ast.parse(src)))
    assert len(found) == 1, (src, found)
    assert not _is_count(found[0][1]), src


def test_a_count_written_beside_another_key_is_a_count():
    """Several targets at once pair each with its own part, so a count
    written beside something else, as Apple writes its order count beside
    whether there are more, passes, and the line named is the count's."""
    src = 'out["more"] = 1\ninfo["collected"], info["more"] = (\n    len(docs),\n    listed["more"])'
    found = list(_writes_in(ast.parse(src)))
    assert len(found) == 1 and _is_count(found[0][1]), found
    assert found[0][0] == 3, "the line of the count, not of the statement"
