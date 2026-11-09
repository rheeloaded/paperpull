"""A capture that saved nothing is a failure, never one for Manual Review.

Ally's tax forms API lists a 2019 Form 1099-INT its Tax Forms page cannot
open (#152). The download said so and answered that it saved nothing, and
the app recorded that as Needs Manual Review and counted it with the
outcomes that really put a file in the Manual Review folder. So the run
summary said one document needed review, the panel said a document set
aside sat in the Manual Review folder, and the folder was empty. Every
document app but Wealthfront had the same branch word for word, from the
template they were made from, and Anthem's surfaces fetched through its API
had one of their own. Wealthfront recorded a row it could not find as No
Receipt Available, which is final, so the document was never asked for again.

A branch here is one taken when the answer of a call, the capture, says
nothing was saved: `if not saved`, `if not taken`, `if not pdf`, and the
same with more after an `or`. Nothing finds an app by its name or the
name of its function. On such a branch, nothing may record Needs Manual
Review or count manual_review unless the branch puts a file aside, in the
Manual Review folder or a quarantine, so that the folder holds what the
count says. A branch inside one, as E*TRADE's refusals of a document its
list gave no account, is a refusal a person has to settle, and is named
below with its reason rather than passed over.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULES = sorted(p for p in (REPO / "apps").glob("*/*.py") if not p.name.startswith("test_"))

# What says a file was put aside on a branch.
ASIDE = ("manual_review,", "manual_review)", "quarantine", "open_zip")

# Branches inside a capture branch that refuse a document for a person to
# settle and count it for review, by (app, function, what the branch tests).
NAMED = {
    ("etrade", "download_one", "SHARED_WITH_NO_ACCOUNT"):
        "E*TRADE's list gave the document no account and more than one of its date and title, "
        "so nothing was pressed. Which one it is takes a person, and counting it for review is "
        "how the panel asks. Nothing is saved, so the panel's Manual Review wording is wrong "
        "for it too, a follow-up of #152 for every refusal.",
    ("etrade", "download_one", "TWICE_FOR_ONE_ACCOUNT"):
        "E*TRADE's list gave two documents of one date and title for one account, so nothing "
        "was pressed. As above.",
}


def _root(value):
    """The name an attribute or item is read from, as got in got.ok."""
    while isinstance(value, (ast.Attribute, ast.Subscript)):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _bound_from_calls(fn) -> set:
    """Names this function binds from the answer of a call, or from a part
    of such an answer, as BofA and TSP bind saved = got.ok."""
    out, grew = set(), True
    while grew:
        grew = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            v = node.value
            if not (any(isinstance(n, (ast.Call, ast.Await)) for n in ast.walk(v)) or _root(v) in out):
                continue
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id not in out:
                        out.add(n.id)
                        grew = True
    return out


def _says_nothing_saved(test, names) -> bool:
    """`not saved`, or `not saved or ...`, on a name bound from a call."""
    def is_not(t):
        return (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                and isinstance(t.operand, ast.Name) and t.operand.id in names)
    if is_not(test):
        return True
    return isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and is_not(test.values[0])


def _counts_for_review(stmts) -> bool:
    for s in stmts:
        for n in ast.walk(s):
            if isinstance(n, ast.Attribute) and n.attr == "NEEDS_MANUAL_REVIEW":
                return True
            if isinstance(n, ast.Constant) and n.value == "Needs Manual Review":
                return True
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                    and n.slice.value == "manual_review":
                return True
    return False


def _names_a_file(stmts) -> bool:
    """The branch points the record at a file, as Target's does at an
    invoice it put aside in Manual Review, so the count has a file."""
    return any(isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Attribute) and t.attr == "pdf_path" for t in n.targets)
        for s in stmts for n in ast.walk(s))


def _own(stmts) -> list:
    """The branch's own statements, without the branches inside it."""
    return [s for s in stmts if not isinstance(s, (ast.If, ast.For, ast.While, ast.Try, ast.With))]


def census():
    """Every capture branch, and of them each one or its inner branch that
    counts a document for review with nothing put aside."""
    branches, found = [], {}
    for path in MODULES:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            names = _bound_from_calls(fn)
            for node in ast.walk(fn):
                if not (isinstance(node, ast.If) and _says_nothing_saved(node.test, names)):
                    continue
                where = (path.parent.name, fn.name)
                branches.append(where)
                text = "\n".join(ast.get_source_segment(src, s) or "" for s in node.body)
                aside = any(w in text for w in ASIDE) or _names_a_file(node.body)
                if _counts_for_review(_own(node.body)) and not aside:
                    found[where + ("",)] = node.lineno
                for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(inner, ast.If) and _counts_for_review(_own(inner.body)):
                        inner_text = "\n".join(ast.get_source_segment(src, s) or "" for s in inner.body)
                        if any(w in inner_text for w in ASIDE) or _names_a_file(inner.body):
                            continue
                        test = ast.get_source_segment(src, inner.test) or ""
                        named = next((k for k in NAMED if k[:2] == where and k[2] in test), None)
                        found[named or where + (test[:60],)] = inner.lineno
    return branches, found


BRANCHES, FOUND = census()


def test_no_capture_that_saved_nothing_is_counted_for_review():
    """Each one here records Needs Manual Review or counts manual_review on a
    branch that put nothing in the Manual Review folder."""
    unnamed = {k: v for k, v in FOUND.items() if k not in NAMED}
    assert not unnamed, "\n".join("apps/%s %s() line %d%s" % (k[0], k[1], line, " [%s]" % k[2] if k[2] else "")
                                  for k, line in sorted(unnamed.items()))


def test_each_named_refusal_is_still_there():
    """A refusal named above that is no longer found was fixed or moved, and
    is taken off the list, so the list says what is true."""
    gone = set(NAMED) - set(FOUND)
    assert not gone, sorted(gone)


def test_the_census_reaches_every_document_app():
    """Not a check that passes because it found nobody. Every document app
    has a capture branch, Anthem has its own for the surfaces it fetches
    through its API, and the receipt apps' branch after their save is
    found too, though it only returns."""
    apps = {a for a, _f in BRANCHES}
    documents = {p.parent.name for p in MODULES if p.name.endswith("_docs.py")}
    missing = documents - apps - {"wealthfront"}
    assert not missing, sorted(missing)
    assert {"bofa", "tsp"} <= apps, "saved = got.ok is a capture's answer too"
    assert ("anthem", "_save_collected") in BRANCHES
    assert {"walmart", "target", "costco"} <= apps
    assert len(documents) >= 67
