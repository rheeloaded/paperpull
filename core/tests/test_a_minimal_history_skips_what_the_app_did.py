"""A history moved with --minimal skips what the old computer skipped.

tools/migrate.py --minimal writes only the fields a skip decision reads, so
a history can move to another computer with far less of a person's
purchases and accounts in it. A field an app's _already_done reads that the
tool leaves out makes that app download again on the new computer what it
saved before, and quietly, since a second download looks like a first.
Robinhood finds a tax form listed again without its year through the
undated key it was saved under, and a crypto statement saved under its old
key through the page that listed it, and --minimal carried neither.

So it is asked two ways. By reading, every record field each app's
_already_done reads, followed through what it calls in the app's own
modules and in the core, is one the tool carries for that app's provider.
So is every field read off a saved record wherever the app goes through
its saved records, found by what the code does however it reaches them
(Walks says what it follows and what it does not). American Family looks
there for another bill's statement with the very bytes it just took,
Optum for the tax form saved under the key of its title, and AT&T for a
bill 0.34.0 saved under the wrong year, and after a --minimal move each
found nothing. A walk that decides no download says why. By running, each
app's own _already_done answers the same for a record and for that record
as --minimal cuts it, over every state, marker, note, day and review copy
a record holds, and Robinhood's records go through a real export and
import, as American Family's, Optum's and AT&T's do in their own suites.
Every name and number is invented.
"""
import argparse
import ast
import functools
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from paperpull_core import not_shown
from paperpull_core import storage as core_storage
from paperpull_core.models import State

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "paperpull_core"

sys.path.insert(0, str(REPO / "tools"))
migrate = pytest.importorskip("migrate")

# Dicts a skip decision reads that are not a record. Anything else it reads
# a field of is taken for a record, so a new one is looked at, not passed.
NOT_RECORDS = {"self.config"}

# Core modules a skip decision reaches that read no saved record, each with
# why, which are not followed. The dictionaries they read are their own.
READS_NO_RECORD = {
    "paperpull_core.pdf_reader":
        "reads a PDF in a worker process for validate_pdf, and the dictionaries "
        "it reads are its own messages to that worker and pypdf's own objects",
}

# A field read only inside one core function, which the tool carries
# exactly when that function needs it. _skip_fields keeps a record's last
# note when not_shown.asked_again holds, the only note that reads.
CARRIED_FOR = {("paperpull_core.not_shown", "asked_again"): {"notes"}}

# Fields an app's skip decisions read that decide nothing, each with why. One
# no longer read fails, so the list cannot outlive its reason.
DECIDES_NOTHING = {
    "robinhood": {
        "period": "copied onto a form moved to the key of its year",
        "tax_year": "read off the page's listing of the form, not a saved record",
    },
    # _place_from_saved goes through the saved records for combined
    # statements, and asks downloaded_ok only to read back a file this app
    # kept. It places a plan whose page names no employer, for a statement
    # held in Manual Review, and decides no download.
    "netbenefits": {
        "employer": "the employer a saved combined statement was made under, an employer's "
                    "name --minimal leaves out. Without it the statement places no plan, and "
                    "a held statement waits in Manual Review, as before any was saved",
        "digest": "read off this run's plan list (note_combined, plans_named, employer_of)",
        "path": "read off this run's plan list (plans_named)",
        "heading": "read off this run's plan list (_name_key)",
        "label": "read off this run's plan list (_name_key)",
    },
}

# Walks of the saved records that decide no download, each with why, by the
# module and function that read the record (Walks). One no longer found
# fails, so the list cannot outlive its reason. These put right only what
# Rename reads, and a record without the fields matches nothing there and
# changes nothing.
WALKS_FOR_RENAME = {
    "costco": {
        "costco_receipts.App._settle_stores":
            "gives each purchase the part of Costco its receipt's heading names, before "
            "Rename builds names from them",
        "costco_receipts.App._store_kept": "the store _settle_stores keeps for a purchase",
    },
    "golden1": {
        "golden1_docs.App._carry_index_rows":
            "gives an index row the title its record was carried to, and the index "
            "does not move with a history",
    },
    "kroger": {
        "kroger_receipts.App._settle_stores":
            "gives each purchase the store its receipt names, before Rename builds names "
            "from them",
        "kroger_receipts.App._store_kept": "the store _settle_stores keeps for a purchase",
    },
    "newrez": {
        "newrez_docs._DatedByStatement.__init__":
            "dates a saved statement's row by the day it prints, in Rename's view alone",
    },
    "target": {
        "target_receipts.App._mend_invoice_lists":
            "points each order's list of invoices at its files as they are now, before "
            "Rename or Review Names reads the list. --minimal carries the list, and a "
            "purchase type or order number a record lacks is read off its key, which "
            "every history carries",
    },
}

CUT_KEY = ("moves a record off a key cut before 0.34.0, and --minimal carries what it reads "
           "for such a record (KEY_FIELDS, test_a_minimal_history_moves_a_cut_key.py)")

# And these decide no download for another reason, or read only what a moved
# record holds, some of it another way.
WALKS_DECIDE_NOTHING = {
    "robinhood": {
        "robinhood_docs.migrate_html_titles":
            "moves a record titled with the control's words Download HTML under the cleaned "
            "title's key. It decides no download. document_id is read only so a record keyed "
            "by its id keeps that key, and the title key it rebuilds otherwise uses category, "
            "date, title and account, which --minimal carries",
    },
    "aafmaa": {
        "aafmaa_docs.forget_postback_names":
            "takes out of a record an id that --minimal never carries",
    },
    "amazon": {
        "amazon_receipts.App.cmd_reparse_items":
            "reads item prices off receipts already on disk into the record, offline",
        "amazon_receipts.App._replace_history_rows":
            "rewrites the order history's rows for cmd_reparse_items",
    },
    "apple": {
        "apple_receipts.App._oldest_given":
            "dates the oldest receipt Apple gave an account, to learn where this run stops "
            "asking its refused purchases. Without the moved dates it learns from this run's "
            "receipts alone, as on the account's first run, and a purchase left unasked is "
            "asked on the run that would make its record",
    },
    "chase": {"chase_docs.migrate_legacy_keys": CUT_KEY},
    "netbenefits": {
        "netbenefits_docs.App._judge_held":
            "files a statement held in Manual Review or sets it aside, and downloads nothing. "
            "--minimal leaves out held, so after a move such a statement is a Manual Review "
            "record like any set aside, never filed, and is made and judged again once its "
            "file is gone",
        "netbenefits_docs.App._own_or_combined":
            "checks a held statement _judge_held hands it and files it under its summary",
        "netbenefits_docs.App._place_from_saved":
            "reads saved combined statements again to place a plan for a held statement, and "
            "downloads nothing. Without the employer --minimal leaves out it places nothing",
        "netbenefits_docs.App._record": "writes the record of a held statement once judged",
        "netbenefits_docs.App._write_row":
            "writes that statement's index row, and the index does not move with a history",
    },
    "newrez": {
        "newrez_docs._statement_months":
            "the months of the statements discovery and the saved records know, to tell a "
            "capture of another listed statement. Discovery holds every statement the list "
            "gives, and a capture is only ever of one of them",
    },
    "optum": {
        "optum_docs.adopt_product_keys":
            "moves a record off a key without its product, which no released version wrote, "
            "since Optum first shipped in 0.46.0 with this move",
    },
    "target": {
        "renaming._numbers_naming":
            "which other order's row, pdf_path or list of invoices names a file. "
            "--minimal carries pdf_path and the list, and an order number a record lacks "
            "is read off its key, which every history carries, so a moved order's record "
            "claims the files it claimed before the move",
        "renaming._also_saved":
            "the other invoices of an order its notes name, which Review Names and Rename "
            "carry with its first. Target's own walk asks _numbers_naming without them, and "
            "a moved record still names every invoice in its list of invoices, which "
            "--minimal carries",
    },
}

# Walks in the core, met by every app that hands its records there.
CORE_WALKS = {
    "keys._identity": CUT_KEY,
    "keys.told_apart":
        "reads a saved record's id, which --minimal leaves out. Discovery never moves with "
        "a history, whole or minimal, so after a move every saved record is one discovery "
        "lacks, found by its key through the app's key_of and given the number its key "
        "holds. So the first run after a move numbers same-day twins as they were saved "
        "with or without the ids, and from then on discovery holds the id each was listed "
        "under, which it asks after the saved record's",
}


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))
IDS = [d.name for d in APPS]


def provider_of(app: Path) -> str:
    """The provider the tool reads from the install's storage.py."""
    found = migrate.PROVIDER_RE.search((app / "storage.py").read_text(encoding="utf-8"))
    return found.group(1) if found else app.name


# -- by reading ---------------------------------------------------------------

class Module:
    """One module's functions, string constants and imports, by the names
    its own code reaches them by."""

    def __init__(self, name: str, path: Path):
        self.name = name
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        self.funcs, self.consts, self.aliases, self.imported = {}, {}, {}, {}
        # Each function's name as the module spells it, "f" or "Class.f".
        self.qual, self.classes = {}, {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
                self.qual[id(node)] = node.name
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = node
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.funcs.setdefault("self." + sub.name, sub)
                        self.funcs["%s.%s" % (node.name, sub.name)] = sub
                        self.qual[id(sub)] = "%s.%s" % (node.name, sub.name)
            elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.consts[target.id] = node.value.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.aliases[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom):
                # The core's own modules import each other relatively.
                source = ("paperpull_core" + ("." + node.module if node.module else "")
                          if node.level else node.module)
                for a in node.names:
                    if source == "paperpull_core":
                        self.aliases[a.asname or a.name] = "paperpull_core." + a.name
                    elif source:
                        self.imported[a.asname or a.name] = (source, a.name)


CORE_MODULES = {"paperpull_core." + p.stem: Module("paperpull_core." + p.stem, p)
                for p in sorted(CORE.glob("*.py"))}


def modules_of(app: Path) -> dict:
    found = dict(CORE_MODULES)
    for path in sorted(app.glob("*.py")):
        found[path.stem] = Module(path.stem, path)
    return found


def _string(node, mod: Module, modules: dict):
    """The string a key expression holds, a constant or a name for one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in mod.consts:
            return mod.consts[node.id]
        source = mod.imported.get(node.id)
        if source and source[0] in modules:
            return modules[source[0]].consts.get(source[1])
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        other = modules.get(mod.aliases.get(node.value.id, ""))
        if other is not None:
            return other.consts.get(node.attr)
    return None


def _reads(fn, mod: Module, modules: dict):
    """(dict expression, key) for every key this function reads."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "pop", "setdefault") and node.args):
            key = _string(node.args[0], mod, modules)
            if key is not None:
                yield ast.unparse(node.func.value), key
        elif isinstance(node, ast.Subscript):
            key = _string(node.slice, mod, modules)
            if key is not None:
                yield ast.unparse(node.value), key
        elif (isinstance(node, ast.Compare)
                and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)):
            key = _string(node.left, mod, modules)
            if key is not None:
                yield ast.unparse(node.comparators[0]), key


def _callee(call: ast.Call, mod: Module, modules: dict):
    """(module, function) a call reaches in the app or the core, or None."""
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in mod.funcs:
            return mod, mod.funcs[f.id]
        source = mod.imported.get(f.id)
        other = modules.get(source[0]) if source else None
        if other is not None and source[1] in other.funcs:
            return other, other.funcs[source[1]]
        return None
    if isinstance(f, ast.Attribute):
        base = ast.unparse(f.value)
        name = "%s.%s" % (base, f.attr)
        if name in mod.funcs:
            return mod, mod.funcs[name]
        other = modules.get(mod.aliases.get(base, ""))
        if other is not None and f.attr in other.funcs:
            return other, other.funcs[f.attr]
    return None


def _finds_a_saved_record(fn) -> bool:
    """A function that goes through every saved record and asks whether one
    is done, to find the saved copy of a listed document."""
    walks = any(isinstance(n, (ast.For, ast.comprehension))
                and "self.progress.data" in ast.unparse(n.iter) for n in ast.walk(fn))
    asks = any(isinstance(n, ast.Call) and ast.unparse(n.func).endswith("is_done")
               for n in ast.walk(fn))
    return walks and (asks or "'downloaded_ok'" in ast.unparse(fn))


def skip_decisions(app: Path, mod: Module):
    """The app's _already_done, and every other method of its App that
    finds a saved record of a listed document, as Robinhood does for a tax
    form the page now lists under its year."""
    start = mod.funcs.get("App._already_done")
    assert start is not None, "%s has no App._already_done to read" % app.name
    return [start] + [fn for name, fn in sorted(mod.funcs.items())
                      if name.startswith("App.") and fn is not start
                      and _finds_a_saved_record(fn)]


def fields_read(app: Path, passed_over=None) -> dict:
    """{field: [where]} for every record field the app's skip decisions
    read, and everything they call in the app's own modules and the core.
    The modules of READS_NO_RECORD they reach go in `passed_over`."""
    modules = modules_of(app)
    mod = modules[entry_of(app).stem]
    found, seen = {}, set()
    todo = [(mod, fn) for fn in skip_decisions(app, mod)]
    while todo:
        mod, fn = todo.pop()
        if mod.name in READS_NO_RECORD and passed_over is not None:
            passed_over.add(mod.name)
        if id(fn) in seen or mod.name in READS_NO_RECORD:
            continue
        seen.add(id(fn))
        for obj, key in _reads(fn, mod, modules):
            if obj in NOT_RECORDS or key in CARRIED_FOR.get((mod.name, fn.name), ()):
                continue
            found.setdefault(key, []).append("%s.%s" % (mod.name, fn.name))
        for call in ast.walk(fn):
            if isinstance(call, ast.Call):
                reached = _callee(call, mod, modules)
                if reached is not None:
                    todo.append(reached)
    return found


def test_every_module_passed_over_is_still_reached():
    """A module named in READS_NO_RECORD that no skip decision reaches any
    more is taken out, so the list never passes over a new one."""
    reached = set()
    for app in APPS:
        fields_read(app, reached)
    assert set(READS_NO_RECORD) <= reached, sorted(set(READS_NO_RECORD) - reached)


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_field_a_skip_decision_reads_goes_with_minimal(app):
    read = fields_read(app)
    # Not a census of nothing. Every skip decision reads both of these.
    assert {"downloaded_ok", "state"} <= set(read), (app.name, sorted(read))
    idle = DECIDES_NOTHING.get(app.name, {})
    assert set(idle) <= set(read), (app.name, "no longer read", set(idle) - set(read))
    carried = set(migrate.skip_fields_of(provider_of(app)))
    left_out = {k: v for k, v in read.items() if k not in carried and k not in idle}
    assert not left_out, (
        "%s's skip decisions read %s, which --minimal leaves out, so a history "
        "moved with it is downloaded again. Carry it in tools/migrate.py "
        "(PROVIDER_SKIP_FIELDS when only this app reads it) if it names no "
        "person or account, or say in the tool's docstring what --minimal "
        "then carries" % (app.name, left_out))


# -- every walk of the saved records ------------------------------------------

# What a name holds of the saved records. The store, its records by key, one
# key, one record, a key and its record from items(), and many of any of
# them, a list, a tuple or a loop's worth. A document made from a record is
# MADE and its class, and a name a function is handed a fixed word in holds
# that word after "=".
STORE, RECORDS, KEY, RECORD, PAIR = "store", "records", "key", "record", "pair"
MANY, MADE = "many ", "made "
COPIES = ("list", "tuple", "set", "frozenset", "sorted", "reversed")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _split(starts):
    """(the nodes of one scope, the functions and comprehensions at its
    edge, each a scope of its own)."""
    own, inner, todo = [], [], list(starts)
    while todo:
        node = todo.pop()
        if isinstance(node, _FUNCTIONS + _COMPREHENSIONS):
            inner.append(node)
            continue
        own.append(node)
        todo.extend(ast.iter_child_nodes(node))
    return own, inner


class Walks:
    """Every field read off a saved record where an app goes through its
    saved records, found by what the code does, not by how it is spelled.

    The store is self.progress, app.progress or getattr of either, and its
    records its data, however either is reached. Kept in a name, put in a
    tuple or list and looped over, as (self.progress, self.discovery) is,
    copied with dict(), list(), set() or a comprehension, or handed to a
    function of the app or the core by place, by keyword or among *args.
    A record is one taken from the records' values or items, one looked up
    in them by any key, as keys.told_apart looks up what it is handed as
    saved=, or one looked up in the store by a key from a loop over the
    records' keys. A field is read off a record by get, by index or by
    "in", and off a document made from one by from_dict or Class(**record),
    by each attribute asked of it, a property such as key by every field it
    reads. A field named by a word handed to the function, or by a loop over
    fixed words, is that word, and one named by nothing it can read is
    "?" and what names it. A comprehension, or a function inside another,
    binds names of its own.

    What it does not follow is said here, so the list cannot be taken for
    more. A record handed back by a function, a function handed in as a
    value or written as a lambda, a document's attribute that is not its
    own field's name, and a record the store's get gives under a key not
    taken from the records, which is how an app reads the one document it
    is on. fields_read above reads those of _already_done and the methods
    that find a saved record for it, and no census reads the others."""

    def __init__(self, app: Path):
        self.modules = modules_of(app)
        self.found, self.seen = {}, set()
        for name, mod in self.modules.items():
            if not name.startswith("paperpull_core."):
                for qual, fn in mod.funcs.items():
                    if not qual.startswith("self."):
                        self.run(mod, fn, {})

    # -- what an expression holds

    def kind(self, expr, env, mod):
        def k(e):
            return self.kind(e, env, mod)
        if isinstance(expr, ast.Name):
            return env.get(expr.id)
        if isinstance(expr, ast.Attribute):
            if expr.attr == "progress" and isinstance(expr.value, ast.Name):
                return STORE
            return RECORDS if expr.attr == "data" and k(expr.value) == STORE else None
        if isinstance(expr, ast.Subscript):
            return RECORD if k(expr.value) == RECORDS else None
        if isinstance(expr, ast.BoolOp):
            return next((x for x in map(k, expr.values) if x), None)
        if isinstance(expr, ast.IfExp):
            return k(expr.body) or k(expr.orelse)
        if isinstance(expr, ast.BinOp):
            return MANY + KEY if MANY + KEY in (k(expr.left), k(expr.right)) else None
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            if expr.elts and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                 for e in expr.elts):
                return "=" + "\0".join(e.value for e in expr.elts)
            found = next((x for x in map(k, expr.elts) if x), None)
            return MANY + found if found else None
        if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            found = self.kind(expr.elt, self.comp_env(expr, env, mod), mod)
            return MANY + found if found else None
        if isinstance(expr, ast.DictComp):
            found = self.kind(expr.value, self.comp_env(expr, env, mod), mod)
            return RECORDS if found == RECORD else None
        if isinstance(expr, ast.Call):
            return self.called(expr, env, mod)
        return None

    def called(self, call, env, mod):
        def k(e):
            return self.kind(e, env, mod)
        f, args = call.func, call.args
        if isinstance(f, ast.Name):
            if f.id == "getattr" and len(args) >= 2:
                attr = _string(args[1], mod, self.modules)
                if attr == "progress":
                    return STORE
                if attr == "data" and k(args[0]) == STORE:
                    return RECORDS
            if f.id in COPIES and args:
                each = self.each(args[0], env, mod)
                return MANY + each if each else None
            if f.id == "dict" and args and k(args[0]) == RECORDS:
                return RECORDS
        if isinstance(f, ast.Attribute):
            base = k(f.value)
            if f.attr in ("get", "pop", "setdefault") and args:
                if base == RECORDS or (base == STORE and k(args[0]) == KEY):
                    return RECORD
            if base == RECORDS and f.attr in ("values", "items", "keys"):
                return MANY + {"values": RECORD, "items": PAIR, "keys": KEY}[f.attr]
            if f.attr == "from_dict" and args and k(args[0]) == RECORD:
                made = self.class_of(f.value, mod)
                return MADE + made if made else None
        if any(kw.arg is None and k(kw.value) == RECORD for kw in call.keywords):
            made = self.class_of(f, mod)
            return MADE + made if made else None
        return None

    def each(self, expr, env, mod):
        """What each turn of a loop over `expr` holds. A loop over fixed
        words holds one of them."""
        kind = self.kind(expr, env, mod)
        if kind == RECORDS:
            return KEY
        if kind and kind.startswith("="):
            return kind
        return kind[len(MANY):] if kind and kind.startswith(MANY) else None

    def comp_env(self, comp, env, mod) -> dict:
        """What the names hold inside a comprehension, whose own names hide
        the function's."""
        inner = dict(env)
        for gen in comp.generators:
            kind = self.each(gen.iter, inner, mod)
            for name in ast.walk(gen.target):
                if isinstance(name, ast.Name):
                    inner.pop(name.id, None)
            self.bind(gen.target, kind, inner)
        return inner

    def class_of(self, expr, mod):
        """"module:Class" for a class of the app's or the core's, or None."""
        if isinstance(expr, ast.Name):
            if expr.id in mod.classes:
                return "%s:%s" % (mod.name, expr.id)
            source = mod.imported.get(expr.id)
            if source and source[1] in getattr(self.modules.get(source[0]), "classes", {}):
                return "%s:%s" % source
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            other = self.modules.get(mod.aliases.get(expr.value.id, ""))
            if other is not None and expr.attr in other.classes:
                return "%s:%s" % (other.name, expr.attr)
        return None

    # -- what a function reads

    @staticmethod
    def bind(target, kind, env):
        if kind is None:
            return
        if isinstance(target, ast.Name):
            env.setdefault(target.id, kind)
        elif isinstance(target, (ast.Tuple, ast.List)) and kind == PAIR and len(target.elts) == 2:
            Walks.bind(target.elts[0], KEY, env)
            Walks.bind(target.elts[1], RECORD, env)

    def run(self, mod, fn, env: dict):
        mark = (id(fn), frozenset(env.items()))
        if mark in self.seen:
            return
        self.seen.add(mark)
        where = "%s.%s" % (mod.name.rsplit(".", 1)[-1], mod.qual.get(id(fn), fn.name))
        self.scope(mod, fn.body, dict(env), where)

    def scope(self, mod, starts, env: dict, where: str):
        """Bind what one scope's names hold, then read and follow with them.
        A function or lambda inside it, or a comprehension, is a scope of
        its own, whose names hide these."""
        own, inner = _split(starts)
        for _ in range(8):
            before = dict(env)
            for node in own:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        self.bind(target, self.kind(node.value, env, mod), env)
                elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    self.bind(node.target, self.kind(node.value, env, mod), env)
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    self.bind(node.target, self.each(node.iter, env, mod), env)
            if env == before:
                break
        fields = set(self.reads(own, env, mod))
        if fields:
            self.found.setdefault(where, set()).update(fields)
        for node in own:
            if isinstance(node, ast.Call):
                self.follow(node, env, mod)
        for node in inner:
            if isinstance(node, _COMPREHENSIONS):
                parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
                parts += [part for gen in node.generators for part in [gen.iter] + gen.ifs]
                self.scope(mod, parts, self.comp_env(node, env, mod), where)
            else:
                args = node.args
                hidden = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs
                          + [args.vararg, args.kwarg] if a is not None}
                body = node.body if isinstance(node.body, list) else [node.body]
                self.scope(mod, body, {n: v for n, v in env.items() if n not in hidden}, where)

    def reads(self, own, env, mod):
        def k(e):
            return self.kind(e, env, mod)
        for node in own:
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "pop", "setdefault") and node.args
                    and k(node.func.value) == RECORD):
                yield from self.named(node.args[0], env, mod)
            elif (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                    and k(node.value) == RECORD):
                yield from self.named(node.slice, env, mod)
            elif (isinstance(node, ast.Compare) and node.comparators
                    and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
                    and k(node.comparators[0]) == RECORD):
                yield from self.named(node.left, env, mod)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                made = k(node.value)
                if made and made.startswith(MADE):
                    yield from self.made_reads(made[len(MADE):], node.attr)

    def named(self, node, env, mod):
        """The field a key expression names."""
        word = _string(node, mod, self.modules)
        if word is not None:
            return [word]
        if isinstance(node, ast.Name) and str(env.get(node.id, "")).startswith("="):
            return env[node.id][1:].split("\0")
        return ["?" + ast.unparse(node)]

    def made_reads(self, made: str, attr: str) -> set:
        """The fields an attribute of a document made from a record reads,
        the field of that name, or every one a property or method of its
        class reads of itself."""
        source, name = made.split(":")
        methods = {f.name: f for f in self.modules[source].classes[name].body
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if attr not in methods:
            return {attr}
        todo, seen, fields = [attr], set(), set()
        while todo:
            name = todo.pop()
            if name in seen or name not in methods:
                continue
            seen.add(name)
            for n in ast.walk(methods[name]):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id == "self"):
                    if n.attr in methods:
                        todo.append(n.attr)
                    else:
                        fields.add(n.attr)
        return fields

    def follow(self, call, env, mod):
        """Into an app's or the core's function, with what each of its
        parameters is handed."""
        reached = _callee(call, mod, self.modules)
        if reached is None:
            return
        cmod, cfn = reached
        a = cfn.args
        params = [p.arg for p in a.posonlyargs + a.args]
        if params and params[0] in ("self", "cls") and "." in cmod.qual.get(id(cfn), ""):
            params = params[1:]
        bound = {}
        for p, d in list(zip(params[len(params) - len(a.defaults):], a.defaults)) + \
                [(p.arg, d) for p, d in zip(a.kwonlyargs, a.kw_defaults)]:
            if isinstance(d, ast.Constant) and isinstance(d.value, str):
                bound[p] = "=" + d.value
        extra = []
        for i, arg in enumerate(call.args):
            if isinstance(arg, ast.Starred):
                break
            kind = self.kind(arg, env, mod) or self.word(arg)
            if i < len(params):
                bound.pop(params[i], None)
                if kind:
                    bound[params[i]] = kind
            elif kind and not kind.startswith("="):
                extra.append(kind)
        if extra and a.vararg:
            bound[a.vararg.arg] = MANY + extra[0]
        for kw in call.keywords:
            if kw.arg:
                bound.pop(kw.arg, None)
                kind = self.kind(kw.value, env, mod) or self.word(kw.value)
                if kind:
                    bound[kw.arg] = kind
        if any(not v.startswith("=") for v in bound.values()):
            self.run(cmod, cfn, bound)

    @staticmethod
    def word(node):
        return "=" + node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) \
            else None


def walk_reads(app: Path) -> dict:
    """{where: fields} for every walk of the app's saved records."""
    return Walks(app).found


@functools.lru_cache(maxsize=None)
def walks_of(app: Path) -> dict:
    return walk_reads(app)


def carried_for(provider: str) -> set:
    """Every field --minimal carries for a provider, some of them for one
    kind of its records alone."""
    return (set(migrate.skip_fields_of(provider))
            | set(migrate.PROVIDER_KIND_FIELDS.get(provider, (None, ()))[1]))


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_walk_of_the_saved_records_reads_what_minimal_carries(app):
    read = walks_of(app)
    why = dict(WALKS_FOR_RENAME.get(app.name, {}), **WALKS_DECIDE_NOTHING.get(app.name, {}))
    assert set(why) <= set(read), (app.name, "no longer found", sorted(set(why) - set(read)))
    carried = carried_for(provider_of(app)) | set(DECIDES_NOTHING.get(app.name, {}))
    left_out = {where: sorted(read[where] - carried) for where in sorted(read)
                if where not in why and where not in CORE_WALKS and read[where] - carried}
    assert not left_out, (
        "%s goes through its saved records and reads %s, which --minimal leaves out, "
        "so on a new computer that check finds nothing. Carry it in tools/migrate.py "
        "(PROVIDER_SKIP_FIELDS, or PROVIDER_KIND_FIELDS for one kind of record) and say "
        "in the tool's docstring what it then carries, or say here why it decides no "
        "download" % (app.name, left_out))


def test_every_core_walk_is_still_met():
    met = {where for app in APPS for where in walks_of(app)}
    assert set(CORE_WALKS) <= met, sorted(set(CORE_WALKS) - met)


@pytest.mark.parametrize("app, where, fields", [
    ("amfam", "amfam_docs.App.download_one", {"pdf_sha256", "date", "account"}),
    ("robinhood", "robinhood_docs.App._account_of", {"source_url"}),
    ("optum", "optum_docs.hold_known_forms", {"href", "account", "title", "document_id"}),
    ("apple", "apple_receipts.App._oldest_given", {"purchase_date", "purchase_type"}),
    ("kroger", "kroger_receipts.App._settle_stores", {"store_info"}),
    ("kroger", "kroger_receipts.App._store_kept", {"store_read"}),
    ("capitalone", "keys.told_apart", {"document_id", "downloaded_ok"}),
    ("att", "att_docs.find_wrong_year_copies", {"date", "pdf_pages"}),
    ("att", "att_docs._bill_of", {"account", "category"}),
    ("att", "att_docs._saved_size", {"pdf_size"}),
    ("newrez", "newrez_docs._statement_months", {"category", "date"}),
    ("optum", "optum_docs.adopt_product_keys", {"category", "date"}),
    ("amazon", "amazon_receipts.App._replace_history_rows", {"items", "order_number"}),
    ("aafmaa", "keys._identity", {"category", "date", "title", "account", "document_id"}),
], ids=["a loop over items", "a record handed to a method", "among *args",
        "getattr of the store", "a loop over keys alone", "the store's get under such a key",
        "saved= and a word by default", "handed on again", "a record's bill read apart",
        "a function of one record",
        "the store among *args", "from_dict and its key", "a document handed on",
        "a loop over fixed words"])
def test_the_walk_census_follows_each_way_an_app_reaches_its_records(app, where, fields):
    """Not a census of nothing. Each way an app reaches its saved records,
    and what the census reads there."""
    read = walks_of(REPO / "apps" / app)
    assert fields <= read.get(where, set()), (where, sorted(read.get(where, ())), sorted(read))


SHADOWS = '''
class App:
    def comprehension(self):
        record = self.progress.data.get("k")
        titles = [record.get("title") for record in self.discovery.data.values()]
        return record.get("pdf_path"), titles

    def inner(self):
        record = self.progress.data.get("k")

        def other(record):
            return record.get("summary")
        return other({}), record.get("state")
'''


def test_a_name_bound_again_in_a_comprehension_or_an_inner_function_is_its_own(tmp_path):
    """A comprehension or a function inside one binds its own names, so a
    record of discovery there, or one handed in, is not the saved record of
    the same name outside."""
    (tmp_path / "invented_docs.py").write_text(SHADOWS, encoding="utf-8")
    assert walk_reads(tmp_path) == {"invented_docs.App.comprehension": {"pdf_path"},
                                    "invented_docs.App.inner": {"state"}}


def test_a_provider_list_carries_only_what_that_app_reads():
    """Every field carried for one provider is a field its skip decisions
    or a walk of its saved records read, and every provider named is an
    app's, or a name nobody uses would carry nothing and a field nobody
    reads would carry for nothing."""
    by_provider = {provider_of(app): app for app in APPS}
    for provider in set(migrate.PROVIDER_SKIP_FIELDS) | set(migrate.PROVIDER_KIND_FIELDS):
        assert provider in by_provider, provider
        app = by_provider[provider]
        read = set(fields_read(app)).union(*walks_of(app).values())
        own = carried_for(provider) - set(migrate.SKIP_FIELDS)
        assert own <= read, (provider, own - read)


def test_every_app_is_read():
    """The apps with an entry script, every one of them."""
    assert len(APPS) >= 65, IDS


# -- by running ---------------------------------------------------------------

def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


@pytest.fixture
def loading(monkeypatch):
    """What loading an app sets in the core, put back after."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    return load


def app_over(mod, folder: Path, records: dict):
    """The app's own downloader over these records, without its __init__,
    which would want a config file and a browser."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "owner": ""}
    inst.args = argparse.Namespace(redownload=False)
    inst.paths = storage.Paths(folder)
    inst.paths.ensure()
    # Loaded first, or the first read loads the folder's file over these.
    inst.progress = storage.JsonStore(inst.paths.progress_json)
    inst.progress.load()
    inst.progress.data = records
    inst.discovery = storage.JsonStore(inst.paths.discovery_json)
    inst.discovery.load()
    return inst


class Listed:
    """A document or purchase listed again under KEY, with nothing else
    known of it."""

    key = "listed:1"

    def __getattr__(self, name):
        return ""


def opening_pdf(path: Path) -> Path:
    """A one page PDF of invented words that opens."""
    from pypdf import PdfWriter
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 200})
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


# What else a record holds, which --minimal leaves out.
HISTORY = {"title": "Invented Monthly Statement", "summary": "Invented Statement",
           "account": "INVENTED *0000", "total": "12.34", "items": "Garden Hose",
           "order_number": "INV0001", "document_id": "DOC0001",
           "date": "2026-05-14", "category": "Statement", "store_info": "Main St",
           "source_url": "https://statements.example.invalid/page",
           "undated_key": "Statement::Invented_Monthly_Statement:",
           "pdf_filename": "2026-05-14 Invented Statement.pdf", "pdf_size": "4096",
           "pdf_sha256": "ab" * 32, "text_sha256": "cd" * 32}


def records(folder: Path):
    """A record of every state a record can hold, with and without the
    marker, a note an older version wrote or a later one, the days a
    receipt page showed nothing, and a review copy that opens, is gone or
    was never kept."""
    saved = str(opening_pdf(folder / "review" / "copy.pdf"))
    gone = str(folder / "review" / "gone.pdf")
    old_note = sorted(not_shown.OLD_NOTES)[0]
    days = ["2031-01-0%d" % d for d in range(1, not_shown.DAYS + 1)]
    for state in [s.value for s in State] + [""]:
        for marker in (None, False, True):
            for notes in (None, "Listed; " + old_note, "Listed; Invented later note"):
                for shown in (None, days):
                    for path in ("", saved, gone):
                        rec = dict(HISTORY, state=state, pdf_path=path,
                                   discovered_at="2031-01-01T10:00:00")
                        for field, value in (("downloaded_ok", marker), ("notes", notes),
                                             (not_shown.DAYS_KEY, shown)):
                            if value is not None:
                                rec[field] = value
                        yield rec


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_app_skips_a_minimal_record_as_it_skipped_the_whole_one(app, loading, tmp_path):
    mod = loading(app)
    provider = provider_of(app)
    inst = app_over(mod, tmp_path / "out", {})
    answers, differ = set(), []
    for rec in records(tmp_path):
        inst.progress.data = {Listed.key: rec}
        whole = bool(inst._already_done(Listed()))
        inst.progress.data = {Listed.key: migrate._skip_fields(rec, provider)}
        cut = bool(inst._already_done(Listed()))
        answers.add(whole)
        if cut != whole:
            differ.append((whole, {k: rec.get(k) for k in
                                   ("state", "downloaded_ok", "notes", "pdf_path")}))
    assert answers == {True, False}, (app.name, answers)
    assert not differ, (app.name, len(differ), differ[:3])


# -- Robinhood, through the tool ----------------------------------------------

ROBINHOOD = REPO / "apps" / "robinhood"


def computers(tmp_path: Path):
    """A Robinhood install on one computer and a fresh one on another, each
    an output folder with its own storage.py, as the tool finds them."""
    found = []
    for side in ("old", "new"):
        out = tmp_path / side / "Robinhood Statements"
        out.mkdir(parents=True)
        shutil.copy(ROBINHOOD / "storage.py", out / "storage.py")
        (out / "progress.json").write_text("{}", encoding="utf-8")
        found.append(out)
    return found


def moved(tmp_path: Path, old: Path, new: Path, records: dict, minimal=True) -> dict:
    """The records exported from the old computer's folder and imported
    into the new computer's."""
    (old / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    archive = tmp_path / "history.ppz"
    assert migrate.export(old.parent, archive, minimal=minimal) == 0
    assert migrate.do_import(archive, new.parent, assume_yes=True) == 0
    return json.loads((new / "progress.json").read_text(encoding="utf-8"))


def text_pdf(path: Path, lines) -> Path:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b" " * 4000)
    return path


def statement(mod, date="2010-01-31", account="", page=""):
    site = sys.modules["robinhood_site"]
    page = page or dict((a, u) for u, a in site.STATEMENT_PAGES)[account]
    return mod.Document(title="Invented Monthly Statement", category=mod.doc_types.STATEMENT,
                        summary="Monthly Statement", date=date, source_url=page,
                        account=account)


def saved(doc, **more) -> dict:
    return dict(doc.to_dict(), downloaded_ok=True, state=State.COMPLETED.value, **more)


def test_a_robinhood_tax_form_listed_again_without_its_year_stays_done(loading, tmp_path):
    """A form saved before its year was read is kept under its dated key,
    with the undated one it was saved under, for a page that lists it
    without a year again (#62)."""
    mod = loading(ROBINHOOD)
    site = sys.modules["robinhood_site"]
    tax = mod.doc_types.TAX
    undated = mod.Document(title="Invented Consolidated 1099", category=tax,
                           summary="Consolidated 1099", date="", source_url=site.TAX_URL)
    dated = mod.Document(title="Invented Consolidated 1099", category=tax,
                         summary="Consolidated 1099", date="2021-12-31", tax_year="2021",
                         source_url=site.TAX_URL)
    held = {dated.key: saved(dated, undated_key=undated.key)}
    old, new = computers(tmp_path)
    assert app_over(mod, old, held)._already_done(undated)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._already_done(undated), \
        "the form would be downloaded again on the new computer"
    assert got[dated.key]["undated_key"] == undated.key
    assert "summary" not in got[dated.key]


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_a_robinhood_tax_form_saved_without_a_date_moves_to_its_year(loading, tmp_path,
                                                                      minimal):
    """A form saved before its year was read, never opened since, is moved
    to the key its page now dates it by, read from its category, title and
    account and the year its file prints, here the file copied across. Or
    the form is downloaded again beside the copy already saved."""
    mod = loading(ROBINHOOD)
    site = sys.modules["robinhood_site"]
    tax = mod.doc_types.TAX
    old, new = computers(tmp_path)
    undated = mod.Document(title="Invented Consolidated 1099", category=tax,
                           summary="Consolidated 1099", date="", source_url=site.TAX_URL)
    pdf = text_pdf(app_over(mod, old, {}).paths.folder_for(tax) / "Invented 1099.pdf",
                   ["Invented Securities LLC", "2022 1099-DIV", "Tax Year 2022"])
    held = {undated.key: saved(undated, pdf_path=str(pdf))}

    got = moved(tmp_path, old, new, held, minimal=minimal)
    inst = app_over(mod, new, got)
    shutil.copy(pdf, Path(got[undated.key]["pdf_path"]))
    dated = mod.Document(title="Invented Consolidated 1099", category=tax,
                         summary="Consolidated 1099", date="2022-12-31", tax_year="2022",
                         source_url=site.TAX_URL)
    inst.discovery.data = {dated.key: dict(dated.to_dict(), state=State.DISCOVERED.value)}
    assert inst._date_saved_forms({dated.key}) == 1
    assert inst._already_done(dated), "the form would be downloaded again"


def test_another_accounts_saved_statement_is_known_after_the_move(loading, tmp_path):
    """A crypto statement with the very bytes of the individual statement
    saved for that date is that statement, not the crypto one, and goes to
    review. The saved statement is known by its account, date and digest,
    with no copy of its file on the new computer."""
    mod = loading(ROBINHOOD)
    old, new = computers(tmp_path)
    individual = statement(mod)
    held = {individual.key: saved(individual, pdf_sha256="ab" * 32)}
    crypto = statement(mod, account="Crypto")
    assert app_over(mod, old, held)._other_accounts_statement(crypto, "ab" * 32)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._other_accounts_statement(crypto, "ab" * 32), \
        "the individual statement would be saved again as the crypto one"


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_another_accounts_statement_is_known_by_its_text_after_the_move(loading, tmp_path,
                                                                       minimal):
    """A month served as HTML is a new file on each print, and is known by
    the digest of its text, which the move carries."""
    mod = loading(ROBINHOOD)
    old, new = computers(tmp_path)
    individual = statement(mod)
    held = {individual.key: saved(individual, pdf_sha256="ab" * 32, text_sha256="cd" * 32)}
    crypto = statement(mod, account="Crypto")
    got = moved(tmp_path, old, new, held, minimal=minimal)
    assert app_over(mod, new, got)._other_accounts_statement(crypto, "ef" * 32, "cd" * 32), \
        "the individual statement would be saved again as the crypto one"


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_a_newer_file_mends_a_robinhood_history_an_older_minimal_moved(loading, tmp_path,
                                                                       monkeypatch, minimal):
    """The history was moved first with a --minimal that carried nothing of
    Robinhood's own, and then a file made now was imported over it. The
    saved statement takes its digest and account from the second, and is
    known again in place of the crypto one."""
    mod = loading(ROBINHOOD)
    old, new = computers(tmp_path)
    individual = statement(mod)
    held = {individual.key: saved(individual, pdf_sha256="ab" * 32)}
    crypto = statement(mod, account="Crypto")
    with monkeypatch.context() as older:
        older.setattr(migrate, "PROVIDER_SKIP_FIELDS", {})
        first = moved(tmp_path, old, new, held)
    assert not app_over(mod, new, first)._other_accounts_statement(crypto, "ab" * 32)

    got = moved(tmp_path, old, new, held, minimal=minimal)
    assert got[individual.key].get("pdf_sha256") == "ab" * 32, got[individual.key]
    assert app_over(mod, new, got)._other_accounts_statement(crypto, "ab" * 32), \
        "the individual statement would be saved again as the crypto one"


def test_a_robinhood_crypto_statement_under_its_old_key_stays_done(loading, tmp_path):
    """A crypto statement saved before its account was part of its key
    counts as done only when the crypto page listed it."""
    mod = loading(ROBINHOOD)
    crypto_page = statement(mod, account="Crypto").source_url
    old_doc = statement(mod, page=crypto_page)
    listed = statement(mod, account="Crypto")
    assert old_doc.key != listed.key
    held = {old_doc.key: saved(old_doc)}
    old, new = computers(tmp_path)
    assert app_over(mod, old, held)._already_done(listed)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._already_done(listed), \
        "the statement would be downloaded again on the new computer"
    assert got[old_doc.key]["source_url"] == crypto_page
    assert "summary" not in got[old_doc.key]


@pytest.mark.parametrize("app_beside", [True, False], ids=["install", "folder-only"])
def test_a_second_persons_robinhood_history_carries_the_same(loading, tmp_path, app_beside):
    """A second person's folder sits beside the install, made by Add a
    person, and holds no storage.py of its own, so a folder with no app is
    named for itself. Its records are still Robinhood's, whether the app is
    still in the install beside it or only its storage.py is."""
    import add_account
    mod = loading(ROBINHOOD)
    crypto_page = statement(mod, account="Crypto").source_url
    old_doc = statement(mod, page=crypto_page)
    listed = statement(mod, account="Crypto")
    people = []
    for install in computers(tmp_path):
        if app_beside:
            shutil.copy(entry_of(ROBINHOOD), install / entry_of(ROBINHOOD).name)
        (install / "config.json").write_text(json.dumps(
            {"output_dir": ".", "cdp_url": "http://127.0.0.1:9226"}), encoding="utf-8")
        add_account.make_config(install, "Dana Example", taken=set())
        person = install.parent / ("%s - Dana Example" % install.name)
        assert person.is_dir() and not (person / "storage.py").exists()
        (person / "progress.json").write_text("{}", encoding="utf-8")
        people.append(person)

    got = moved(tmp_path, people[0], people[1], {old_doc.key: saved(old_doc)})
    assert app_over(mod, people[1], got)._already_done(listed), \
        "the second person's statement would be downloaded again"
    assert "summary" not in got[old_doc.key]


def test_another_app_does_not_carry_a_providers_own_fields():
    """The same field can hold more in another app, so only the records of
    the provider that reads it carry it."""
    rec = dict(HISTORY, state=State.COMPLETED.value, downloaded_ok=True, pdf_pages="2",
               href="/account/products/12345678/tax_documents/777.pdf",
               occurrence=1, covers=["cd" * 32], plan="ef" * 32,
               invoices=[{"file": "Invoices/2026-05-14 Invented Invoice (1 of 1).pdf",
                          "part": "1 of 1", "number": "10000000000000001", "kept": True,
                          "names": True, "size": 4096, "pages": 1}])
    own = {provider: set(fields) for provider, fields in migrate.PROVIDER_SKIP_FIELDS.items()}
    for provider, (_which, fields) in migrate.PROVIDER_KIND_FIELDS.items():
        own.setdefault(provider, set()).update(fields)
    assert {"Robinhood", "American Family", "AT&T", "Optum Bank", "Target",
            "NetBenefits"} <= set(own)
    for provider, fields in own.items():
        assert fields <= set(migrate._skip_fields(rec, provider)), provider
    every = set().union(*own.values())
    for provider in ("", "Chase", "Walmart"):
        cut = migrate._skip_fields(rec, provider)
        assert not every & set(cut), (provider, cut)


def test_an_optum_statement_carries_none_of_a_forms_fields():
    """Optum's statements are never read where a form's address is, so a
    statement keeps no address, product, title or id, and a form does."""
    form = dict(HISTORY, href="/account/products/12345678/tax_documents/777.pdf",
                account="12345678", category="Tax Document", document_id="")
    statement = dict(form, href="/account/products/12345678/statements/900001.pdf",
                     category="Statement")
    fields = set(migrate.PROVIDER_KIND_FIELDS["Optum Bank"][1])
    assert fields <= set(migrate._skip_fields(form, "Optum Bank"))
    assert not fields & set(migrate._skip_fields(statement, "Optum Bank"))


def merge_into(cur: dict, inc: dict, provider: str):
    """The record an import leaves of `cur` with `inc` from a file, and how
    many records it counts as changed."""
    target = {"k": dict(cur)}
    _added, updated = migrate._merge(target, {"k": inc}, [], Path("unused"),
                                     provider=provider)
    return target["k"], updated


MOVED = {"state": State.COMPLETED.value, "downloaded_ok": True, "pdf_path": "",
         "date": "2026-09-12"}


def test_a_newer_file_fills_only_what_a_moved_record_lacks():
    """Each field its provider's own checks read that a record lacks, and
    none it holds, so what a run here wrote stays. A field nobody of that
    provider reads is not filled, and the import counts the record as
    changed, so the panel writes it."""
    inc = dict(HISTORY, state=State.COMPLETED.value, downloaded_ok=True, date="2031-01-31")
    got, updated = merge_into(MOVED, inc, "American Family")
    assert (got["pdf_sha256"], got["account"]) == (HISTORY["pdf_sha256"], HISTORY["account"])
    assert got["date"] == "2026-09-12", "a field the record holds is never overwritten"
    assert "title" not in got and updated == 1
    got, updated = merge_into(MOVED, inc, "Chase")
    assert "pdf_sha256" not in got and updated == 0


def test_a_field_a_run_emptied_is_not_filled_again():
    """AT&T empties a wrong-year copy's size as it clears the copy, and a
    file made before that still holds the size."""
    cur = dict(MOVED, category="Statement", account="", pdf_size="", pdf_pages="")
    got, _ = merge_into(cur, dict(cur, pdf_size="240546", pdf_pages=4), "AT&T")
    assert (got["pdf_size"], got["pdf_pages"]) == ("", "")


def test_an_optum_statement_takes_none_of_a_forms_fields_from_a_whole_file():
    form = dict(HISTORY, href="/account/products/12345678/tax_documents/777.pdf",
                account="12345678", category="Tax Document", document_id="")
    statement = dict(form, href="/account/products/12345678/statements/900001.pdf",
                     category="Statement")
    got, _ = merge_into(MOVED, statement, "Optum Bank")
    assert not {"href", "title", "document_id", "account"} & set(got), got
    got, _ = merge_into(MOVED, form, "Optum Bank")
    assert {f: got[f] for f in ("href", "account", "title", "document_id")} == \
        {f: form[f] for f in ("href", "account", "title", "document_id")}
