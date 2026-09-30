"""A purchase is written into an app's CSVs once.

Target saved an online order's invoices in a step of its own. The step wrote
the order into both CSVs, counted it, and said it had saved it, and
process_one, told so, wrote the order and counted it again, as it does after
every receipt. In the owner's archive 22 of 23 invoice orders had two rows in
the receipt index for their one file, the first saying Review Needed, and
each of their items was in the order history twice, so the purchases
workbook listed it twice. Every invoice order was counted as needing review,
and review_names offered each one for renaming however good its name.
Walmart kept a copy of that step with the same fault and one more, a second
write on the way out when anything after the first went wrong, though
nothing had called it since the first version.

Nothing here finds an app by the name of anything. A writer is a method that
adds rows to a CSV, and each CSV is told apart by what the app calls it, so
a writer filling the order history and the index once each writes each
once. A method that writes and acts on what a helper answered is never told
yes by a helper that wrote already, followed through the helpers whose
answer it hands back as its own. And no way through a method adds rows to
the same CSV twice. A loop writes for a different purchase each time round,
so what one time round wrote does not count against the next.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))

# The receipt apps, each of which writes a purchase down after asking the
# step that saves its document how that went.
RECEIPT_APPS = ("amazon", "apple", "bestbuy", "costco", "ebay", "gap", "github",
                "homedepot", "kroger", "lowes", "meijer", "target", "uber", "walmart")

NONE = frozenset()


def _self_call(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "self")


def _appended(node) -> frozenset:
    """The CSVs rows are added to right here, by what the app calls them."""
    return frozenset(ast.unparse(n.func.value) for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "append_rows")


def _says_no(value) -> bool:
    """An answer that says nothing was saved."""
    return value is None or (isinstance(value, ast.Constant) and not value.value)


class Census:
    """One class that writes rows, read for every way through its methods."""

    def __init__(self, app: str, cls: ast.ClassDef):
        self.app = app
        self.methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}
        self.writers = {name: _appended(f) for name, f in self.methods.items() if _appended(f)}

    def written(self, node) -> frozenset:
        """The CSVs this adds rows to, itself or through a writer it calls."""
        out = set(_appended(node))
        for n in ast.walk(node):
            if _self_call(n) and n.func.attr in self.writers:
                out |= self.writers[n.func.attr]
        return frozenset(out)

    def walk(self, stmts, wrote: frozenset, found: list):
        """Follow every way through these statements. Returns the CSVs that
        may have been written to by the end, and whether every way ended in
        a return or a raise first."""
        for s in stmts:
            if isinstance(s, ast.Return):
                here = self.written(s.value) if s.value is not None else NONE
                if here & wrote:
                    found.append(("writes twice", s.lineno))
                if (wrote | here) and not _says_no(s.value):
                    found.append(("says it saved after writing", s.lineno))
                return wrote | here, True
            if isinstance(s, (ast.Raise, ast.Continue, ast.Break)):
                return wrote, True
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(s, ast.If):
                ways = [self.walk(s.body, wrote, found), self.walk(s.orelse, wrote, found)]
            elif isinstance(s, (ast.For, ast.AsyncFor, ast.While)):
                # Once round for each purchase, so each time starts as this one.
                self.walk(s.body, wrote, found)
                ways = [self.walk(s.orelse, wrote, found)]
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                ways = [self.walk(s.body, wrote, found)]
            elif isinstance(s, ast.Try):
                body, ended = self.walk(s.body, wrote, found)
                ways = [] if ended else [self.walk(s.orelse, body, found)]
                # A handler can run after any part of the body has.
                ways += [self.walk(h.body, wrote | body, found) for h in s.handlers]
                if s.finalbody:
                    live = frozenset().union(*[w for w, e in ways if not e])
                    last, gone = self.walk(s.finalbody, wrote | body | live, found)
                    if gone:
                        return last, True
                    ways = [(w | last, e) for w, e in ways]
            else:
                here = self.written(s)
                if here & wrote:
                    found.append(("writes twice", s.lineno))
                wrote = wrote | here
                continue
            live = [w for w, ended in ways if not ended]
            if not live:
                return wrote, True
            wrote = frozenset().union(*live)
        return wrote, False

    def asked(self, fn) -> set:
        """The helpers whose answer this method acts on."""
        out = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and _self_call(n.value):
                out.add(n.value.func.attr)
            if isinstance(n, (ast.If, ast.While)):
                test = n.test.operand if isinstance(n.test, ast.UnaryOp) else n.test
                if _self_call(test):
                    out.add(test.func.attr)
        return out & set(self.methods)

    def handed_back(self, fn) -> set:
        """The helpers whose answer this method hands back as its own."""
        out, kept = set(), {}
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name) and _self_call(n.value):
                kept.setdefault(n.targets[0].id, set()).add(n.value.func.attr)
        for n in ast.walk(fn):
            if isinstance(n, ast.Return) and n.value is not None:
                if _self_call(n.value):
                    out.add(n.value.func.attr)
                elif isinstance(n.value, ast.Name):
                    out |= kept.get(n.value.id, set())
        return out & set(self.methods)

    def told_by(self, name: str) -> set:
        """Every helper whose answer reaches this method."""
        reach, todo = set(), sorted(self.asked(self.methods[name]) - {name})
        while todo:
            h = todo.pop()
            if h not in reach:
                reach.add(h)
                todo.extend(self.handed_back(self.methods[h]))
        return reach

    def faults(self) -> list:
        out = []
        for name, fn in self.methods.items():
            found = []
            self.walk(fn.body, NONE, found)
            out += ["%s writes a second time at line %d" % (name, line)
                    for kind, line in found if kind == "writes twice"]
        for name, fn in self.methods.items():
            if not self.written(fn):
                continue
            for helper in sorted(self.told_by(name) - set(self.writers)):
                found = []
                self.walk(self.methods[helper].body, NONE, found)
                out += ["%s is told yes by %s, which wrote first, at line %d"
                        % (name, helper, line)
                        for kind, line in found if kind == "says it saved after writing"]
        return out


def census_of(source: str, app: str) -> list:
    tree = ast.parse(source)
    return [Census(app, cls) for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
            and any(isinstance(f, ast.FunctionDef) and _appended(f) for f in cls.body)]


CENSUS = [c for e in ENTRIES for c in census_of(e.read_text(encoding="utf-8-sig"),
                                                 e.parent.name)]


def test_the_census_reads_every_app():
    """Not vacuous. Every app has one class that writes its CSVs, and every
    receipt app is read for the step that saves a document and answers."""
    assert len(ENTRIES) >= 61, [e.parent.name for e in ENTRIES]
    assert sorted(c.app for c in CENSUS) == sorted(e.parent.name for e in ENTRIES)
    asking = {c.app for c in CENSUS for name, fn in c.methods.items()
              if c.written(fn) and c.told_by(name)}
    for app in RECEIPT_APPS:
        assert app in asking, (app, sorted(asking))


# Target's shape in a few lines. The step that saves an invoice writes the
# purchase and says yes, and the caller writes it again. And Walmart's
# second write, on the way out of a step that had written already.
FAULTY = '''
class App:
    def _write_csv_rows(self, p):
        self.order_csv.append_rows([{}])
        self.index_csv.append_rows([{}])

    def process_one(self, p):
        saved = self._save_receipt(p)
        if not saved:
            return
        self._write_csv_rows(p)

    def _save_receipt(self, p):
        return self._save_invoice(p)

    def _save_invoice(self, p):
        ok = self._finish(p)
        if ok:
            self._write_csv_rows(p)
        return ok

    def _finish(self, p):
        return True

    def _handle_no_receipt(self, p):
        try:
            ok = self._finish(p)
            if ok:
                self._write_csv_rows(p)
            return ok
        except Exception:
            pass
        self._write_csv_rows(p)
        return False
'''

# The shape every other receipt app has. The step saves and says so, and
# the caller writes the purchase down once. A step that could not save
# writes that down itself and says no.
FINE = '''
class App:
    def _write_csv_rows(self, p):
        self.order_csv.append_rows([{}])
        self.index_csv.append_rows([{}])

    def process_one(self, p):
        saved = self._save_receipt(p)
        if not saved:
            return
        self._write_csv_rows(p)

    def _save_receipt(self, p):
        if not self._finish(p):
            self._write_csv_rows(p)
            return False
        return self._save_invoice(p)

    def _save_invoice(self, p):
        return self._finish(p)

    def _finish(self, p):
        return True

    def process_all(self, ps):
        for p in ps:
            self._write_csv_rows(p)
'''


def test_the_census_knows_the_fault_when_it_sees_it():
    faults = census_of(FAULTY, "made-up")[0].faults()
    assert any(f.startswith("process_one is told yes by _save_invoice") for f in faults), faults
    assert any(f.startswith("_handle_no_receipt writes a second time") for f in faults), faults
    assert census_of(FINE, "made-up")[0].faults() == []


@pytest.mark.parametrize("census", CENSUS, ids=lambda c: c.app)
def test_a_purchase_is_written_once(census):
    faults = census.faults()
    assert not faults, (
        "%s can write one purchase into its CSVs twice. A step that saves a "
        "document should say whether it did and leave the rows to the method "
        "that asked, which writes them once. %s." % (census.app, ". ".join(faults)))
