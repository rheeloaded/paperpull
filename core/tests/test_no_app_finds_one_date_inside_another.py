"""No app takes one date for another by finding it inside a longer one.

Dominion found a bill's panel by spelling the bill's date 1/5/2025 and
taking the first panel header that held that text. 1/5/2025 is inside
11/5/2025, and bills are listed newest first, so a January bill opened the
November panel above it and saved November's PDF under January's date,
where it was remembered as done for good. A read-only audit found it on
2026-10-01.

This finds the same shape everywhere. A date, or a spelling of one, looked
for as a plain substring of what a page or a provider's answer said, with
Python's in, a str method, a pattern made from the date's own text, a
locator that matches a string anywhere in an element (has_text,
get_by_text, get_by_role and their kin), a selector that does the same
(has-text, text=, contains, *=), or a page script that tests text with
includes or indexOf, whether the date is handed to it or written into it.
Places are found by what the code does, never by the name of an app, a
function or a variable.

What a place looks for is worked out by running the app's own code. Its
needle is followed back through names, loops, tuple unpacking, parameters
and their callers, helper returns and the records the app keeps, to a date
the app holds, and that date is taken to be each of sixteen sample dates in
turn. A needle built for one date that is found inside the way a page
prints another is a place that can take one for the other. The sample
dates hold every way that happens, a month of 1 inside 11, a day of 1 or 5
inside 11 or 15, and a year of 2020 written 20 at the front of 2025.

Text the page printed, which the app reads a date out of somewhere, is not
spelled by the app, so it is taken to be any form a page prints with its
year. A function counts as reading a date out of a value when, called with
"January 5, 2025" and the like, it hands back 2025-01-05. A record field
the app fills with dates of its own making is read as one of those, even
where some other path into it is raw text.

Found this way on the code as it stood on 2026-10-01, and each fixed with a
browser test that fails without the fix. Dominion's bill panels, Ally's
statement rows on a page that writes dates as numbers, and USAA's document
rows for a document discovered without its id. Checked and found whole,
E*TRADE and Meijer, whose patterns keep a digit off either end of a date,
Navy Federal and Vanguard, which write the month and day with their zeros,
and Verizon, which writes the month's name.

What it does not see. A date pattern written out by hand states where its
date ends, and that is left to its author. A page script that reads one
date off the page and compares it with another never hands Python a date.
And a script's text is searched for includes, indexOf and new RegExp, not
parsed.
"""
import ast
import builtins
import contextlib
import importlib
import inspect
import itertools
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core.identity import date_variants, period_variants  # noqa: E402

# What the page or the provider's answer said.
TEXT_READS = {"inner_text", "text_content", "all_inner_texts", "all_text_contents",
              "inner_html", "evaluate", "get_attribute", "input_value", "content",
              "json", "text", "evaluate_handle", "json_value", "get_property"}
COLL_READS = {"all_inner_texts", "all_text_contents"}
STR_READS = {"inner_text", "text_content", "inner_html", "get_attribute", "input_value",
             "content", "text"}
STR_KEEP = {"lower", "upper", "strip", "lstrip", "rstrip", "replace", "casefold",
            "title", "capitalize", "removeprefix", "removesuffix", "expandtabs",
            "center", "ljust", "rjust", "zfill", "encode", "decode", "normalize"}
TO_COLL = {"split", "rsplit", "splitlines", "items", "values", "keys", "partition",
           "rpartition", "findall", "groups"}
WRAP_COLL = {"list", "tuple", "set", "sorted", "reversed", "frozenset", "dict",
             "fromkeys", "filter", "map", "enumerate", "zip"}
WRAP_SAME = {"next", "iter", "max", "min", "unescape"}
FILLS = {"append", "add", "insert", "extend", "update", "appendleft"}
MONTH_WORDS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
               "oct", "nov", "dec")
SEPS = ("/", "-", ".")

# The labels a value carries. A date of the app's own making, a spelling of
# one, and text the page printed that the app reads a date out of.
DATEISH = {"ISO", "SPELL", "DATETEXT"}
TYPING = {"STR", "COLL"}

# A locator that finds a string anywhere in an element.
PW_TEXT = {"get_by_text", "get_by_label", "get_by_title", "get_by_placeholder", "get_by_alt_text"}
STR_TESTS = {"find", "index", "rfind", "rindex", "count", "endswith", "startswith", "__contains__"}
# A selector that matches an element's text or an attribute by a piece of it.
SELECTOR_CALLS = {"locator", "query_selector", "query_selector_all", "wait_for_selector",
                  "frame_locator", "eval_on_selector", "eval_on_selector_all"}
SELECTOR_SUBSTRING = re.compile(r"has-text|text=|contains\(|:text\(|\*=|~=")
SELECTOR_TEXTS = [re.compile(p) for p in (
    r"has-text\(\s*(['\"])(?P<t>.*?)\1\s*\)",
    r":text\(\s*(['\"])(?P<t>.*?)\1\s*\)",
    r"text=(['\"]?)(?P<t>[^'\"\]>]+)\1",
    r"contains\([^,()]*,\s*(['\"])(?P<t>.*?)\1\s*\)",
    r"[*~]=\s*(['\"])(?P<t>.*?)\1")]
SCRIPT_TEXTS = re.compile(
    r"\.(?:includes|indexOf|lastIndexOf|startsWith|endsWith|search|match)\(\s*(['\"])(?P<t>.*?)\1\s*\)")
RE_TESTS = {"search", "match", "findall", "finditer", "fullmatch"}
SCRIPTS = {"evaluate", "evaluate_handle", "wait_for_function"}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Every way one date sits inside another's spelling.
SAMPLES = ["%04d-%02d-%02d" % (y, m, d) for y in (2020, 2025)
           for m in (1, 11) for d in (1, 5, 11, 15)]


def printed(iso, with_year=False):
    """Every way a page might print this date, or the month it falls in.
    With its year only, for text the page printed, which a row or a header
    gives in full."""
    y, m, d = (int(x) for x in iso.split("-"))
    name = MONTHS[m - 1]
    dated = date_variants(iso) + [
        "%d/%02d/%04d" % (m, d, y), "%s %02d, %04d" % (name, d, y),
        "%s %02d, %04d" % (name[:3], d, y), "%d-%d-%04d" % (m, d, y),
        "%d.%d.%04d" % (m, d, y), "%04d%02d%02d" % (y, m, d)] + period_variants(iso[:7])
    if with_year:
        return list(dict.fromkeys(dated))
    return list(dict.fromkeys(dated + [
        "%s %d" % (name, d), "%s %d" % (name[:3], d), "%d/%d" % (m, d), "%02d/%02d" % (m, d)]))


class Unknown(Exception):
    """What a place looks for could not be worked out."""


class Blank(str):
    """Something that is not a date, standing in for whatever the run would
    hold there. It reads as empty text, and so does anything taken from it."""

    def __new__(cls):
        return str.__new__(cls, "")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Blank()

    def __getitem__(self, key):
        return Blank()

    def __call__(self, *a, **k):
        return Blank()

    def get(self, *a, **k):
        return Blank()


BUILTIN_NAMES = set(dir(builtins))


def _constant_text(node):
    """A string put together from string constants alone, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _constant_text(node.left), _constant_text(node.right)
        return (a or "") + (b or "") if (a is not None or b is not None) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return None


def _month_table(node) -> bool:
    """A written-out list of the twelve months' names."""
    if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 12:
        words = [e.value.lower() for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return sum(1 for w in words if w[:3] in MONTH_WORDS) >= 12
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "split":
            return _month_table(node.func.value)
        return any(_month_table(a) for a in node.args)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        words = node.value.lower().split()
        return len(words) >= 12 and sum(1 for w in words if w[:3] in MONTH_WORDS) >= 12
    return False


class Mod:
    def __init__(self, path: Path, rel: str, app: str):
        self.path, self.rel, self.app = path, rel, app
        self.tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        self.imports, self.funcs, self.consts, self.strings = {}, {}, {}, {}
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
            elif isinstance(node, ast.ClassDef):
                for fn in node.body:
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.funcs["%s.%s" % (node.name, fn.name)] = fn
            elif isinstance(node, ast.Assign):
                text = _constant_text(node.value)
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        if text is not None:
                            self.strings[t.id] = text
                        if _month_table(node.value):
                            self.consts[t.id] = {"MONTHS"}


class Fn:
    def __init__(self, mod, qual, node):
        self.mod, self.qual, self.node = mod, qual, node
        parts = qual.split(".")
        self.cls = parts[0] if len(parts) > 1 and not parts[1].startswith("<") else None
        self.env = defaultdict(set)
        a = node.args
        self.params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
        if a.vararg:
            self.params.append(a.vararg.arg)
        if a.kwarg:
            self.params.append(a.kwarg.arg)
        pos = a.posonlyargs + a.args
        self.defaults = {x.arg: d for x, d in zip(pos[len(pos) - len(a.defaults):], a.defaults)}
        self.nodes = None
        self.bindings = None


def own_nodes(fn):
    """The function's own nodes, not those of a function defined inside it."""
    if fn.nodes is None:
        nodes, stack = [], list(ast.iter_child_nodes(fn.node))
        while stack:
            n = stack.pop()
            nodes.append(n)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            stack.extend(ast.iter_child_nodes(n))
        fn.nodes = nodes
    return fn.nodes


def _is_int(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "int"


def _path_to(target, name):
    if isinstance(target, ast.Name):
        return () if target.id == name else None
    if isinstance(target, (ast.Tuple, ast.List)):
        for i, e in enumerate(target.elts):
            p = _path_to(e, name)
            if p is not None:
                return (i,) + p
    return None


def _take(value, path):
    for i in path:
        value = list(value)[i]
    return value


def _copy(node):
    return ast.parse(ast.unparse(node), mode="eval").body


def _key(n):
    return n.pattern if isinstance(n, re.Pattern) else n


def leaves(v):
    if v is None or isinstance(v, Blank):
        return
    if isinstance(v, (str, re.Pattern)):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from leaves(x)
    elif isinstance(v, (list, tuple, set, frozenset)):
        for x in v:
            yield from leaves(x)


def finds(kind, needle, hay):
    """Whether a place of this kind finds the needle in this text."""
    if kind.startswith("re.") and isinstance(needle, str):
        try:
            needle = re.compile(needle)
        except re.error:
            return False
    if isinstance(needle, re.Pattern):
        if kind == "re.match":
            return needle.match(hay) is not None
        if kind == "re.fullmatch":
            return needle.fullmatch(hay) is not None
        return needle.search(hay) is not None
    if not needle:
        return False
    if kind == "str.startswith":
        return hay.startswith(needle)
    if kind == "str.endswith":
        return hay.endswith(needle)
    return needle.lower() in hay.lower()


class Census:
    """Every place in these modules that looks for a date inside what a page
    said, and what each one looks for."""

    def __init__(self, files):
        """files are (path, relative name, app) for every module read."""
        self.mods = {}
        for path, rel, app in files:
            try:
                self.mods[rel] = Mod(path, rel, app)
            except SyntaxError:
                continue
        self._resolve_imports()
        self.ret, self.param, self.field = defaultdict(set), defaultdict(set), defaultdict(set)
        self.parses = defaultdict(set)
        self.phase, self.changed, self._memo = 1, False, {}
        self.fns = {(m.rel, q): Fn(m, q, n) for m in self.mods.values() for q, n in m.funcs.items()}
        for m in self.mods.values():
            for q, n in list(m.funcs.items()):
                for sub in ast.walk(n):
                    if sub is not n and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        key = (m.rel, "%s.<%s>" % (q, sub.name))
                        self.fns[key] = Fn(m, key[1], sub)
        self.parent = {k: self.fns.get((k[0], k[1].rsplit(".<", 1)[0]))
                       for k in self.fns if ".<" in k[1]}
        self._imported = {}
        self._settle()
        self.parsers = self._verified_parsers()
        for k in list(self.parses):
            self.parses[k] = {p for p in self.parses[k] if (k[0], k[1], p) in self.parsers}
        self.phase = 2
        self._settle()
        self.callers = defaultdict(list)
        for f in self.fns.values():
            for n in own_nodes(f):
                if isinstance(n, ast.Call):
                    t = self.callee(f, n)
                    if t:
                        self.callers[t].append((f, n))
        self.sites = self._find_sites()
        self.writes = self._field_writes()
        self._possible, self._names, self._open_fields = {}, {}, set()

    # -- reading the modules ------------------------------------------------

    def _core_rel(self, name):
        rel = "core/paperpull_core/%s.py" % name
        return rel if rel in self.mods else None

    def _resolve_imports(self):
        for m in self.mods.values():
            for node in ast.walk(m.tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.startswith("paperpull_core."):
                            rel = self._core_rel(a.name.split(".")[-1])
                        else:
                            rel = "apps/%s/%s.py" % (m.app, a.name)
                        if rel in self.mods:
                            m.imports[a.asname or a.name.split(".")[-1]] = ("mod", rel)
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    for a in node.names:
                        local = a.asname or a.name
                        if base == "paperpull_core" or (m.app == "core" and node.level and not base):
                            rel = self._core_rel(a.name)
                            if rel:
                                m.imports[local] = ("mod", rel)
                                continue
                        if base.startswith("paperpull_core.") or (m.app == "core" and node.level and base):
                            rel = self._core_rel(base.split(".")[-1])
                        else:
                            rel = "apps/%s/%s.py" % (m.app, base)
                        if rel in self.mods:
                            m.imports[local] = ("fn", rel, a.name)

    def imported(self, mod):
        """The module itself, imported the way its own app imports it."""
        if mod.rel not in self._imported:
            if mod.app == "core":
                self._imported[mod.rel] = importlib.import_module("paperpull_core.%s" % mod.path.stem)
            else:
                # every app has a storage module of its own
                sys.modules.pop("storage", None)
                sys.modules.pop(mod.path.stem, None)
                sys.path.insert(0, str(mod.path.parent))
                try:
                    self._imported[mod.rel] = importlib.import_module(mod.path.stem)
                finally:
                    sys.path.pop(0)
        return self._imported[mod.rel]

    def callee(self, fn, call):
        """The function a call reaches, when it can be told."""
        f, mod = call.func, fn.mod
        if isinstance(f, ast.Name):
            nested = (mod.rel, "%s.<%s>" % (fn.qual.split(".<")[0], f.id))
            if nested in self.fns:
                return nested
            if f.id in mod.funcs:
                return (mod.rel, f.id)
            imp = mod.imports.get(f.id)
            if imp and imp[0] == "fn" and imp[2] in self.mods[imp[1]].funcs:
                return (imp[1], imp[2])
            if "%s.__init__" % f.id in mod.funcs:
                return (mod.rel, "%s.__init__" % f.id)
            return None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            owner = f.value.id
            if owner in ("self", "cls") and fn.cls:
                q = "%s.%s" % (fn.cls, f.attr)
                if q in mod.funcs:
                    return (mod.rel, q)
            imp = mod.imports.get(owner)
            if imp and imp[0] == "mod" and f.attr in self.mods[imp[1]].funcs:
                return (imp[1], f.attr)
        return None

    def bound_args(self, target, call):
        tf = self.fns[target]
        params = list(tf.params)
        if tf.cls and params and params[0] in ("self", "cls"):
            params = params[1:]
        out = []
        for p, a in zip(params, call.args):
            if isinstance(a, ast.Starred):
                break
            out.append((p, a))
        for kw in call.keywords:
            if kw.arg:
                out.append((kw.arg, kw.value))
        return out

    # -- what every value carries --------------------------------------------

    def _add(self, store, key, labels):
        labels = set(labels) - {"MONTHS"}
        if labels and not labels <= store[key]:
            store[key] |= labels
            self.changed = True

    def _bind(self, fn, target, lab):
        if isinstance(target, ast.Name):
            if not lab <= fn.env[target.id]:
                fn.env[target.id] |= lab
                self.changed = True
        elif isinstance(target, (ast.Tuple, ast.List)):
            inner = lab - {"COLL"}
            if inner & DATEISH and "COLL" not in lab:
                inner = (inner - DATEISH) | {"PART"}
            for e in target.elts:
                self._bind(fn, e, inner)
        elif isinstance(target, ast.Starred):
            self._bind(fn, target.value, lab)
        elif isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Name):
                self._add(self.field, (fn.mod.app, "a", target.attr), lab - {"PART", "MONTHNAME"})
        elif isinstance(target, ast.Subscript):
            key = target.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self._add(self.field, (fn.mod.app, "k", key.value), lab - {"PART", "MONTHNAME"})
            elif isinstance(target.value, ast.Name):
                self._bind(fn, target.value, (lab - TYPING) | {"COLL"})

    @staticmethod
    def _element_of(lab):
        """What iterating a value gives."""
        if "MONTHS" in lab:
            return {"MONTHNAME", "STR"}
        if "COLL" in lab:
            return lab - {"COLL"}
        # a character of a date is a piece of one
        return (lab & {"PAGE"}) | ({"PART"} if lab & DATEISH else set())

    def _comprehension(self, fn, gens):
        for g in gens:
            self._bind(fn, g.target, self._element_of(self.labels(fn, g.iter)))

    def _numeric(self, fn, node) -> bool:
        if node is None or _is_int(node):
            return True
        if isinstance(node, ast.Attribute) and node.attr in ("day", "month", "year"):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "group":
            return True
        return "PART" in self.labels(fn, node)

    def _month(self, fn, node) -> bool:
        if isinstance(node, ast.Subscript):
            return "MONTHS" in self.labels(fn, node.value) or self._month(fn, node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in STR_KEEP:
            return self._month(fn, node.func.value)
        if isinstance(node, ast.Name):
            return "MONTHNAME" in self.labels(fn, node)
        return False

    def _spelling(self, fn, parts, specs, literals):
        """What a template spells, from the values put in it (None for a
        number slot of a % format), their formats and the text between."""
        numeric = [i for i, p in enumerate(parts) if self._numeric(fn, p)]
        months = [i for i, p in enumerate(parts) if p is not None and self._month(fn, p)]
        dated = [i for i, p in enumerate(parts) if p is not None and self.labels(fn, p) & DATEISH]
        others = [i for i in range(len(parts)) if i not in numeric and i not in months and i not in dated]
        text = "".join(literals)
        wordy = bool(re.search(r"[A-Za-z]{2,}", text)) or bool(others)
        seps = set(re.sub(r"[A-Za-z0-9\s,]", "", text))
        if (len(numeric) >= 2 and (seps & set(SEPS) or months)) or (months and numeric):
            if wordy:
                return "HASDATE"
            if len(numeric) == 3 and not months and seps == {"-"} and specs[:3] == ["04d", "02d", "02d"]:
                return "ISO"
            return "SPELL"
        if dated:
            return "HASDATE" if (wordy or len(parts) > 1) else "SPELL"
        return None

    @staticmethod
    def _nondate(labs):
        return labs - DATEISH - {"PART", "MONTHNAME", "MONTHS", "COLL", "RX", "HASDATE"}

    def labels(self, fn, node) -> set:
        if node is None:
            return set()
        key = (id(fn), id(node))
        if key in self._memo:
            return self._memo[key]
        out = self._labels(fn, node)
        self._memo[key] = out
        return out

    def _labels(self, fn, node) -> set:
        L = self.labels
        if isinstance(node, ast.Name):
            out = set(fn.env.get(node.id, ()))
            out |= fn.mod.consts.get(node.id, set())
            if node.id in fn.mod.strings:
                out.add("STR")
            imp = fn.mod.imports.get(node.id)
            if imp and imp[0] == "fn":
                out |= self.mods[imp[1]].consts.get(imp[2], set())
            return out
        if isinstance(node, ast.Constant):
            return {"STR"} if isinstance(node.value, str) else set()
        if isinstance(node, ast.JoinedStr):
            parts, specs, lits = [], [], []
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    spec = "".join(c.value for c in getattr(v.format_spec, "values", [])
                                   if isinstance(c, ast.Constant)) if v.format_spec else ""
                    parts.append(v.value)
                    specs.append(spec)
                elif isinstance(v, ast.Constant):
                    lits.append(v.value)
            out = {"STR"}
            for p in parts:
                out |= self._nondate(L(fn, p)) | (L(fn, p) & {"RX", "HASDATE"})
            kind = self._spelling(fn, parts, specs, lits)
            return out | ({kind} if kind else set())
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) \
                    and isinstance(node.left.value, str):
                fmt = node.left.value
                args = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
                slots = re.findall(r"%[-0-9.]*[sdir]", fmt)
                lits = re.split(r"%[-0-9.]*[sdir]", fmt)
                parts = [None if s[-1] in "di" else a for s, a in zip(slots, args)]
                out = {"STR"}
                for a in args:
                    out |= self._nondate(L(fn, a)) | (L(fn, a) & {"RX", "HASDATE"})
                kind = self._spelling(fn, parts, [s[1:] for s in slots], lits)
                return out | ({kind} if kind else set())
            if isinstance(node.op, ast.Add):
                pieces = []

                def flat(n):
                    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                        flat(n.left)
                        flat(n.right)
                    else:
                        pieces.append(n)
                flat(node)
                labs = [L(fn, p) for p in pieces]
                if any("COLL" in l for l in labs) and not any("STR" in l for l in labs):
                    return set().union(*labs)
                lits = [p.value for p in pieces if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                parts = [p for p in pieces if not (isinstance(p, ast.Constant) and isinstance(p.value, str))]
                out = {"STR"}
                for l in labs:
                    out |= self._nondate(l) | (l & {"RX", "HASDATE"})
                kind = self._spelling(fn, parts, [""] * len(parts), lits)
                return out | ({kind} if kind else set())
            return L(fn, node.left) | L(fn, node.right)
        if isinstance(node, ast.BoolOp):
            return set().union(*(L(fn, v) for v in node.values))
        if isinstance(node, ast.IfExp):
            return L(fn, node.body) | L(fn, node.orelse)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            if _month_table(node):
                return {"MONTHS"}
            out = set()
            for e in node.elts:
                out |= L(fn, e) - TYPING
            return out | {"COLL"}
        if isinstance(node, ast.Dict):
            out = set()
            for k, v in zip(node.keys, node.values):
                vl = L(fn, v)
                out |= vl - TYPING
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    self._add(self.field, (fn.mod.app, "k", k.value), vl - {"PART", "MONTHNAME"})
            return out | {"COLL"}
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            self._comprehension(fn, node.generators)
            return (L(fn, node.elt) - TYPING) | {"COLL"}
        if isinstance(node, ast.DictComp):
            self._comprehension(fn, node.generators)
            return (L(fn, node.value) - TYPING) | {"COLL"}
        if isinstance(node, ast.Subscript):
            base, key = L(fn, node.value), node.slice
            if "MONTHS" in base:
                return {"MONTHNAME", "STR"}
            if isinstance(key, ast.Slice):
                if base & DATEISH and "COLL" not in base:
                    return (base - DATEISH) | {"PART", "STR"}
                return base
            out = base - {"COLL"}
            if base & DATEISH and "COLL" not in base and "STR" in base:
                out = (out - DATEISH) | {"PART"}
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out = (out - DATEISH) | self.field.get((fn.mod.app, "k", key.value), set())
            return out
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                out = set()
            else:
                out = L(fn, node.value) & {"PAGE"}
            out |= self.field.get((fn.mod.app, "a", node.attr), set())
            if node.attr in ("day", "month", "year"):
                out = (out - DATEISH) | {"PART"}
            return out
        if isinstance(node, ast.Call):
            return self._call(fn, node)
        if isinstance(node, (ast.Starred, ast.Await)):
            return L(fn, node.value)
        if isinstance(node, ast.NamedExpr):
            lab = L(fn, node.value)
            self._bind(fn, node.target, lab)
            return lab
        return set()

    def _note_parse(self, fn, subject):
        """A parameter read with a pattern, or handed on into something that
        reads it. Only a candidate, until calling the function says it reads
        a date out of it."""
        if self.phase != 1:
            return
        for n in ast.walk(subject):
            if isinstance(n, ast.Name) and n.id in fn.params \
                    and n.id not in self.parses[(fn.mod.rel, fn.qual)]:
                self.parses[(fn.mod.rel, fn.qual)].add(n.id)
                self.changed = True

    def _date_text(self, fn, node):
        """A value handed to a function that reads a date out of it is text
        the page printed, wherever else it goes."""
        if isinstance(node, ast.Name):
            if "DATETEXT" not in fn.env[node.id]:
                fn.env[node.id].add("DATETEXT")
                self.changed = True
        elif isinstance(node, ast.Attribute):
            self._add(self.field, (fn.mod.app, "a", node.attr), {"DATETEXT"})
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            self._add(self.field, (fn.mod.app, "k", node.slice.value), {"DATETEXT"})
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            self._add(self.field, (fn.mod.app, "k", node.args[0].value), {"DATETEXT"})

    def _call(self, fn, call):
        L = self.labels
        f = call.func
        target = self.callee(fn, call)
        if target and target in self.fns:
            for p, a in self.bound_args(target, call):
                al = L(fn, a)
                self._add(self.param, (target[0], target[1], p), al)
                if p in self.parses.get(target, ()):
                    if self.phase == 1:
                        self._note_parse(fn, a)
                    elif not al & {"ISO", "SPELL"}:
                        self._date_text(fn, a)
            if target[1].endswith("__init__"):
                for kw in call.keywords:
                    if kw.arg:
                        self._add(self.field, (fn.mod.app, "a", kw.arg), L(fn, kw.value) - {"PART", "MONTHNAME"})
                return set()
            return set(self.ret.get(target, set()))
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if isinstance(f, ast.Name) and f.id[:1].isupper():
            for kw in call.keywords:
                if kw.arg:
                    self._add(self.field, (fn.mod.app, "a", kw.arg), L(fn, kw.value) - {"PART", "MONTHNAME"})
            return set()
        out = set()
        recv = L(fn, f.value) if isinstance(f, ast.Attribute) else set()
        is_re = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re"
        if name == "strftime":
            fmt = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else ""
            out |= {"STR", "ISO" if fmt == "%Y-%m-%d" else "SPELL"}
        if name == "isoformat":
            out |= {"ISO", "STR"}
        if name in TEXT_READS and isinstance(f, ast.Attribute):
            out.add("PAGE")
            out |= {"COLL"} if name in COLL_READS else ({"STR"} if name in STR_READS else recv & {"COLL"})
        if isinstance(f, ast.Attribute):
            if name in FILLS and isinstance(f.value, ast.Name):
                for a in call.args[-1:]:
                    lab = L(fn, a) - TYPING
                    if name in ("extend", "update"):
                        lab = L(fn, a) - TYPING
                    self._bind(fn, f.value, lab | {"COLL"})
            if name in STR_KEEP:
                out |= (recv - {"COLL"}) | {"STR"}
            if name in TO_COLL:
                out |= (recv & {"PAGE", "HASDATE", "RX"}) | {"COLL"}
                if (name in ("split", "rsplit") and recv & DATEISH) or name == "groups":
                    out.add("PART")
            if name in ("get", "pop", "setdefault"):
                out |= recv - {"COLL"} - DATEISH
                if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                    out |= self.field.get((fn.mod.app, "k", call.args[0].value), set())
                if len(call.args) > 1:
                    out |= L(fn, call.args[1])
            if name == "copy":
                out |= recv
            if name == "group":
                out |= (recv & {"PAGE"}) | {"PART", "STR"}
            if name == "join":
                arg = call.args[0] if call.args else None
                inner = L(fn, arg) if arg is not None else set()
                out |= self._nondate(inner) | (inner & {"HASDATE", "RX"}) | {"STR"}
                sep = f.value.value if isinstance(f.value, ast.Constant) else None
                elts = getattr(arg, "elts", None)
                if sep in SEPS and elts and len(elts) >= 2 and all(
                        self._numeric(fn, e) or self._month(fn, e) for e in elts):
                    out.add("SPELL")
                elif inner & DATEISH:
                    out.add("HASDATE")
            if name == "format" and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
                fmt = f.value.value
                slots = re.findall(r"\{[^{}]*\}", fmt)
                lits = re.split(r"\{[^{}]*\}", fmt)
                specs = [s.split(":")[1][:-1] if ":" in s else "" for s in slots]
                for a in call.args:
                    out |= self._nondate(L(fn, a))
                kind = self._spelling(fn, list(call.args[:len(slots)]), specs, lits)
                out |= {"STR"} | ({kind} if kind else set())
            if name in ("sub", "subn") and call.args:
                out |= (L(fn, call.args[-1]) - {"COLL"}) | {"STR"}
            if is_re and name == "escape" and call.args:
                inner = L(fn, call.args[0])
                out |= {"STR"} | self._nondate(inner) | (inner & {"RX"})
                if inner & (DATEISH | {"PART"}):
                    out.add("RX")
            if is_re and name == "compile" and call.args:
                out |= L(fn, call.args[0]) & {"RX", "PAGE"}
            if name in RE_TESTS:
                if is_re and len(call.args) >= 2:
                    self._note_parse(fn, call.args[1])
                elif not is_re and call.args:
                    self._note_parse(fn, call.args[0])
            if name == "strptime" and call.args:
                self._note_parse(fn, call.args[0])
            if name in WRAP_COLL:
                for a in call.args:
                    out |= L(fn, a) - TYPING
                out.add("COLL")
        if isinstance(f, ast.Name):
            if f.id in WRAP_COLL:
                if f.id in ("list", "tuple") and call.args and _month_table(call.args[0]):
                    return {"MONTHS"}
                for a in call.args:
                    out |= L(fn, a) - TYPING
                out.add("COLL")
            elif f.id in WRAP_SAME:
                for a in call.args:
                    out |= L(fn, a)
                if f.id in ("next", "max", "min"):
                    out.discard("COLL")
            elif f.id == "str":
                for a in call.args:
                    out |= L(fn, a) - {"COLL"}
                out.add("STR")
            elif f.id in ("int", "float"):
                out = {"PART"} if any(L(fn, a) & (DATEISH | {"PART", "PAGE"}) for a in call.args) else set()
        return out

    def _walk(self, fn):
        for p in fn.params:
            lab = self.param.get((fn.mod.rel, fn.qual, p))
            if lab and not lab <= fn.env[p]:
                fn.env[p] |= lab
                self.changed = True
        for node in own_nodes(fn):
            if isinstance(node, ast.Assign):
                lab = self.labels(fn, node.value)
                for t in node.targets:
                    self._bind(fn, t, lab)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self._bind(fn, node.target, self.labels(fn, node.value))
            elif isinstance(node, ast.AugAssign):
                self._bind(fn, node.target, self.labels(fn, node.value))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._bind(fn, node.target, self._element_of(self.labels(fn, node.iter)))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        self._bind(fn, item.optional_vars, self.labels(fn, item.context_expr))
            elif isinstance(node, ast.Return) and node.value is not None:
                self._add(self.ret, (fn.mod.rel, fn.qual), self.labels(fn, node.value))
            elif isinstance(node, (ast.Yield, ast.YieldFrom)) and node.value is not None:
                self._add(self.ret, (fn.mod.rel, fn.qual), (self.labels(fn, node.value) - {"STR"}) | {"COLL"})
            elif isinstance(node, (ast.Call, ast.NamedExpr)):
                self.labels(fn, node)
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                self._comprehension(fn, node.generators)

    def _settle(self):
        """Carry labels to a fixed point, a round at a time."""
        self.changed = True
        rounds = 0
        while self.changed and rounds < 100:
            self.changed, self._memo = False, {}
            rounds += 1
            for fn in self.fns.values():
                self._walk(fn)

    def _verified_parsers(self):
        """(module, function, parameter) for every function that hands back
        2025-01-05 when that parameter holds "January 5, 2025" or another
        way a page prints it. Asked by calling it, since reading a value
        with a pattern and returning a date somewhere is what a great many
        functions do. Only a module's own functions are called."""
        out = set()
        for (rel, qual), params in self.parses.items():
            if not params or "." in qual or "ISO" not in self.ret.get((rel, qual), set()):
                continue
            try:
                f = getattr(self.imported(self.mods[rel]), qual, None)
                sig = inspect.signature(f)
            except Exception:
                continue
            for p in params:
                if p not in sig.parameters:
                    continue
                good = 0
                for iso in ("2025-01-05", "2026-11-23"):
                    y, m, d = (int(x) for x in iso.split("-"))
                    for form in ("%s %d, %04d" % (MONTHS[m - 1], d, y), "%02d/%02d/%04d" % (m, d, y),
                                 "%s %02d, %04d" % (MONTHS[m - 1][:3], d, y), "%d/%d/%04d" % (m, d, y)):
                        args = {n: form if n == p else ""
                                for n, prm in sig.parameters.items()
                                if n == p or (prm.default is inspect.Parameter.empty
                                              and prm.kind not in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD))}
                        try:
                            got = f(**args)
                        except Exception:
                            continue
                        first = got[0] if isinstance(got, (tuple, list)) and got else got
                        good += first == iso
                if good >= 4:
                    out.add((rel, qual, p))
        return out

    # -- the places --------------------------------------------------------

    def _find_sites(self):
        sites = []

        def site(kind, fn, node, needle):
            sites.append({"kind": kind, "fn": fn, "node": node, "needle": needle})
        L = self.labels
        for fn in self.fns.values():
            for node in own_nodes(fn):
                if isinstance(node, ast.Compare):
                    left = node.left
                    for op, right in zip(node.ops, node.comparators):
                        if isinstance(op, (ast.In, ast.NotIn)):
                            ll, rl = L(fn, left), L(fn, right)
                            # a substring of the page's words, not one of a
                            # collection's members
                            if ll & DATEISH and "PAGE" in rl and ("STR" in rl or "COLL" not in rl):
                                site("in", fn, node, left)
                        left = right
                    continue
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                exact = any(kw.arg == "exact" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                            for kw in node.keywords)
                for kw in node.keywords:
                    lab = L(fn, kw.value)
                    if kw.arg in ("has_text", "has_not_text") and lab & (DATEISH | {"RX"}):
                        site(kw.arg, fn, node, kw.value)
                    if kw.arg == "name" and name == "get_by_role" and not exact and lab & (DATEISH | {"RX"}):
                        site("get_by_role", fn, node, kw.value)
                if name in PW_TEXT and node.args and not exact and L(fn, node.args[0]) & (DATEISH | {"RX"}):
                    site(name, fn, node, node.args[0])
                # a selector, or a script's own text, with a date written in
                written = node.args[0] if node.args else None
                if written is not None and L(fn, written) & (DATEISH | {"HASDATE"}):
                    text = self._literal_text(fn, written)
                    if name in SELECTOR_CALLS and SELECTOR_SUBSTRING.search(text):
                        site("selector", fn, node, written)
                    if name in SCRIPTS and _JS_SUBSTRING.search(text):
                        site("script text", fn, node, written)
                if isinstance(f, ast.Attribute) and name in STR_TESTS and node.args \
                        and L(fn, node.args[0]) & DATEISH and "PAGE" in L(fn, f.value):
                    site("str." + name, fn, node, node.args[0])
                if isinstance(f, ast.Attribute) and name in RE_TESTS:
                    is_re = isinstance(f.value, ast.Name) and f.value.id == "re"
                    pat, hay = (node.args[0], node.args[1]) if is_re and len(node.args) >= 2 else \
                        (f.value, node.args[0] if node.args else None)
                    if not (is_re and len(node.args) < 2) and hay is not None \
                            and "RX" in L(fn, pat) and "PAGE" in L(fn, hay):
                        site("re." + name, fn, node, pat)
                if name in SCRIPTS and len(node.args) > 1 and L(fn, node.args[1]) & (DATEISH | {"HASDATE"}):
                    site("script", fn, node, node.args[1])
        return sites

    def _literal_text(self, fn, node, depth=0):
        """The text written into a string put together from parts, through
        a name written once here or held at module level."""
        if isinstance(node, ast.Name):
            if node.id in fn.mod.strings:
                return fn.mod.strings[node.id]
            defs = self.definitions(fn, node.id)
            if depth < 3 and len(defs) == 1 and defs[0][0] == "value" and not defs[0][2]:
                return self._literal_text(fn, defs[0][1], depth + 1)
            return ""
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else ""
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            return self._literal_text(fn, node.left, depth) + self._literal_text(fn, node.right, depth)
        return ""

    # -- what a place looks for ----------------------------------------------

    def _field_writes(self):
        """Where each field of a record or a dict is written, each (app,
        namespace, name) to the (function, value written) of every place
        that writes it."""
        out = defaultdict(list)
        for fn in self.fns.values():
            app = fn.mod.app
            for node in own_nodes(fn):
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            out[(app, "k", k.value)].append((fn, v))
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute):
                            out[(app, "a", t.attr)].append((fn, node.value))
                        elif isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
                                and isinstance(t.slice.value, str):
                            out[(app, "k", t.slice.value)].append((fn, node.value))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id[:1].isupper() and self.callee(fn, node) is None:
                    for kw in node.keywords:
                        if kw.arg:
                            out[(app, "a", kw.arg)].append((fn, kw.value))
        return out

    def field_values(self, app, ns, name, sample, depth, probe):
        """What a field holds for this date. When its labels do not say,
        what the app writes into it, every place it is written."""
        try:
            return self.held(self.field.get((app, ns, name), set()), sample, probe)
        except Unknown:
            pass
        key = (app, ns, name, sample, probe)
        if key in self._open_fields or depth > 25:
            raise Unknown("a spelling that cannot be followed")
        self._open_fields.add(key)
        try:
            out = []
            for wfn, expr in self.writes.get((app, ns, name), []):
                try:
                    out.extend(self.possible(wfn, expr, sample, depth + 1, probe))
                except Unknown:
                    continue
        finally:
            self._open_fields.discard(key)
        if not out:
            raise Unknown("a spelling that cannot be followed")
        return out

    def definitions(self, fn, name):
        """Every statement in fn that binds name, as (how, value, where in
        the value the name sits)."""
        if fn.bindings is None:
            fn.bindings = defaultdict(list)

            def bind(target, how, value):
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        path = _path_to(target, n.id)
                        if path is not None:      # not a name inside x.attr or x[i]
                            fn.bindings[n.id].append((how, value, path))
            for node in own_nodes(fn):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, (ast.Name, ast.Tuple, ast.List)):
                            bind(t, "value", node.value)
                elif isinstance(node, ast.AnnAssign) and node.value is not None \
                        and isinstance(node.target, ast.Name):
                    bind(node.target, "value", node.value)
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    bind(node.target, "each", node.iter)
                elif isinstance(node, ast.NamedExpr):
                    bind(node.target, "value", node.value)
                elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                    bind(node.target, "unknown", node)
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if item.optional_vars is not None:
                            bind(item.optional_vars, "unknown", item)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn.bindings[node.name].append(("unknown", node, ()))
        return fn.bindings.get(name, [])

    def held(self, labs, sample, probe):
        """What a value holds for this date when nothing more can be followed.

        A value the app fills with dates of its own making is read as one,
        even where some other path into it is raw text. Raw date text is any
        form a page prints with its year. Anything else is not a date,
        unless this is the second look, which tries it as one as well."""
        if "ISO" in labs:
            return [sample]
        if "DATETEXT" in labs:
            return printed(sample, with_year=True)
        if labs & {"SPELL", "HASDATE", "RX"}:
            raise Unknown("a spelling that cannot be followed")
        return [Blank(), sample] if probe else [Blank()]

    def name_values(self, fn, name, sample, depth, probe):
        key = (fn.mod.rel, fn.qual, name, sample, probe)
        if key in self._names:
            return self._names[key]
        self._names[key] = []        # a name that leads back to itself holds nothing more
        try:
            out = self._name_values(fn, name, sample, depth, probe)
        except Unknown:
            out = None
        if not out:
            out = self.held(fn.env.get(name, set()), sample, probe)
        self._names[key] = out
        return out

    def _name_values(self, fn, name, sample, depth, probe):
        defs = self.definitions(fn, name)
        if defs:
            out = []
            for how, expr, path in defs:
                if how == "unknown":
                    raise Unknown("%s is bound in a way that cannot be followed" % name)
                for v in self.possible(fn, expr, sample, depth + 1, probe):
                    items = [v]
                    if how == "each":
                        if isinstance(v, Blank):
                            items = [Blank()]
                        else:
                            try:
                                items = list(v)
                            except TypeError:
                                continue
                    for item in items:
                        try:
                            out.append(Blank() if isinstance(item, Blank) else _take(item, path))
                        except Exception:
                            continue
            return out
        if name in fn.params:
            out = []
            if not fn.env.get(name, set()) & (DATEISH | {"HASDATE", "RX"}):
                return out
            for caller, call in self.callers.get((fn.mod.rel, fn.qual), []):
                for p, a in self.bound_args((fn.mod.rel, fn.qual), call):
                    if p == name:
                        try:
                            out.extend(self.possible(caller, a, sample, depth + 1, probe))
                        except Unknown:
                            continue
            if not out and name in fn.defaults:
                out = self.possible(fn, fn.defaults[name], sample, depth + 1, probe)
            return out
        par = self.parent.get((fn.mod.rel, fn.qual))
        if par is not None:
            return self.name_values(par, name, sample, depth + 1, probe)
        return []

    @staticmethod
    def _field_of(node):
        """(namespace, name) and the value read, for x.attr, x['key'] and
        x.get('key'), else (None, None)."""
        if isinstance(node, ast.Attribute):
            return ("a", node.attr), node.value
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            return ("k", node.slice.value), node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            return ("k", node.args[0].value), node.func.value
        return None, None

    def _is_field(self, fn, node, bound, module):
        """A field of a record or of a page's answer, read the way the app's
        records hold it, rather than worked out here."""
        key, base = self._field_of(node)
        if key is None or not isinstance(base, ast.Name) or base.id in bound:
            return False
        if base.id in vars(module) and base.id not in fn.params and not self.definitions(fn, base.id):
            return False
        defs = self.definitions(fn, base.id)
        if key[0] == "k" and defs and all(h == "value" and not p and isinstance(e, ast.Dict)
                                          for h, e, p in defs):
            return False     # a dict written out right here
        if base.id != "self" and self.labels(fn, base) & DATEISH:
            return False     # a date's own text
        return True

    def possible(self, fn, expr, sample, depth=0, probe=False):
        """Every value this expression takes in fn for the sample date."""
        key = (id(fn), id(expr), sample, probe)
        if key not in self._possible:
            try:
                self._possible[key] = self._evaluate(fn, expr, sample, depth, probe)
            except Unknown as e:
                self._possible[key] = e
        got = self._possible[key]
        if isinstance(got, Unknown):
            raise got
        return got

    def _each(self, fn, nodes, sample, depth, probe):
        """Every value of each node, one that cannot be worked out read as
        nothing, so a record is not lost for one field."""
        out = []
        for node in nodes:
            try:
                out.append(self.possible(fn, node, sample, depth + 1, probe))
            except Unknown:
                out.append([Blank()])
        return out

    def _evaluate(self, fn, expr, sample, depth, probe):
        if depth > 25:
            raise Unknown("followed too far")
        labs = self.labels(fn, expr)
        if isinstance(expr, ast.Call) and labs & DATEISH == {"ISO"} and not labs & {"HASDATE", "RX", "COLL"}:
            return [sample]
        # A list, a tuple or a dict written out holds each of its values,
        # and what is looked for is in its values, so they are kept side by
        # side rather than in every combination.
        if isinstance(expr, ast.Dict) and all(isinstance(k, ast.Constant) for k in expr.keys):
            vals = self._each(fn, expr.values, sample, depth, probe)
            keys = [k.value for k in expr.keys]
            return [dict(zip(keys, row)) for row in _side_by_side(vals)]
        if isinstance(expr, (ast.List, ast.Tuple)) and not any(isinstance(e, ast.Starred) for e in expr.elts):
            vals = self._each(fn, expr.elts, sample, depth, probe)
            kind = list if isinstance(expr, ast.List) else tuple
            return [kind(row) for row in _side_by_side(vals)] if vals else [kind()]
        module = self.imported(fn.mod)
        bound = set()
        for n in ast.walk(expr):
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                for g in n.generators:
                    bound |= {t.id for t in ast.walk(g.target) if isinstance(t, ast.Name)}
            elif isinstance(n, ast.Lambda):
                bound |= {a.arg for a in n.args.args}
        census, fields = self, []

        class Fields(ast.NodeTransformer):
            def visit(self, node):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and not (node.func.attr == "get" and node.args
                                 and isinstance(node.args[0], ast.Constant)):
                    # a method called on something, not a field read from it
                    node.func.value = self.visit(node.func.value)
                    node.args = [self.visit(a) for a in node.args]
                    for kw in node.keywords:
                        kw.value = self.visit(kw.value)
                    return node
                if census._is_field(fn, node, bound, module):
                    name = "__field%d__" % len(fields)
                    fields.append((name, node))
                    return ast.copy_location(ast.Name(id=name, ctx=ast.Load()), node)
                return super().visit(node)
        body = Fields().visit(_copy(expr))
        names = sorted({n.id for n in ast.walk(body) if isinstance(n, ast.Name)
                        and isinstance(n.ctx, ast.Load) and n.id not in bound
                        and not n.id.startswith("__field") and n.id not in BUILTIN_NAMES
                        and (n.id not in vars(module) or n.id in fn.params or self.definitions(fn, n.id))})
        choices = [self.name_values(fn, name, sample, depth, probe) for name in names]
        for _name, node in fields:
            ns, _ = self._field_of(node)
            choices.append(self.field_values(fn.mod.app, ns[0], ns[1], sample, depth, probe))
        code = compile(ast.fix_missing_locations(ast.Expression(body=body)), "<needle>", "eval")
        keys = names + [n for n, _ in fields]
        size = 1
        for c in choices:
            size *= len(c)
        rows = itertools.product(*choices) if size <= 400 else _side_by_side(choices)
        out = []
        for combo in rows:
            env = dict(vars(module))
            env.update(zip(keys, combo))
            try:
                out.append(eval(code, env))
            except Exception:
                continue
        if not out:
            raise Unknown("the needle could not be worked out")
        return out

    def needles(self, fn, expr, pick=None):
        """What is looked for on each sample date, keeping only what changes
        with the date. A first look reads what is not a date as nothing, and
        when that leaves nothing that changes, a second tries it as a date."""
        for probe in (False, True):
            per = {}
            for a in SAMPLES:
                vals = self.possible(fn, expr, a, probe=probe)
                if pick is not None:
                    vals = [x for v in vals for x in pick(v)]
                per[a] = [n for v in vals for n in leaves(v)]
            same = set.intersection(*({_key(n) for n in per[a]} for a in SAMPLES))
            per = {a: [n for n in per[a] if _key(n) not in same] for a in SAMPLES}
            if any(per.values()):
                return per
        return per

    # -- page scripts ------------------------------------------------------

    def _script_cases(self, s):
        """(function, script text, the value handed in) for a place that
        hands a page script a date. A script that arrives through a
        parameter is taken from each caller."""
        fn, node = s["fn"], s["node"]
        js, value = node.args[0], node.args[1]
        text = self._script_text(fn, js)
        if text is not None:
            return [(fn, text, value)]
        if not (isinstance(js, ast.Name) and js.id in fn.params and isinstance(value, ast.Name)):
            raise Unknown("the script's text could not be found")
        cases = []
        for caller, call in self.callers.get((fn.mod.rel, fn.qual), []):
            args = dict(self.bound_args((fn.mod.rel, fn.qual), call))
            if js.id in args and value.id in args:
                text = self._script_text(caller, args[js.id])
                if text is None:
                    raise Unknown("the script's text could not be found")
                cases.append((caller, text, args[value.id]))
        return cases

    def _script_text(self, fn, js):
        if isinstance(js, ast.Name):
            if js.id in fn.mod.strings:
                return fn.mod.strings[js.id]
            imp = fn.mod.imports.get(js.id)
            if imp and imp[0] == "fn":
                return self.mods[imp[1]].strings.get(imp[2])
            return None
        return _constant_text(js)

    def judge(self, s):
        """('loose', what was found where), ('tight', why) or
        ('not a date', why). Raises Unknown when it cannot tell."""
        if s["kind"] == "script":
            return self._judge_script(s)
        # A selector or a script with the date written into it looks for
        # the text its substring tests are given, so that is the needle.
        pick = {"selector": _selector_texts, "script text": _script_texts}.get(s["kind"])
        per = self.needles(s["fn"], s["needle"], pick=pick)
        if not any(per.values()):
            return "not a date", "what it looks for does not change with the date"
        hit = collision(s["kind"], per)
        if hit:
            return "loose", hit
        if any(finds(s["kind"], n, h) for a in SAMPLES for n in per[a] for h in printed(a)):
            return "tight", "finds its own date and no other"
        return "not a date", "never finds its own date the way a page prints it"

    def _judge_script(self, s):
        checked = 0
        for fn, text, value in self._script_cases(s):
            names = js_names(js_signature(text))
            derived = js_derived(text, names)
            for kind, base, path, snippet in js_lookups(text, derived):
                how = names[base]

                def pick(v, how=how, path=path):
                    return js_follow(js_reach(v, how), path)
                per = self.needles(fn, value, pick=pick)
                if not any(per.values()):
                    continue
                checked += 1
                if kind == "bounded":
                    continue
                hit = collision("in", per)
                if hit:
                    return "loose", hit + ("the script tests %s with %s" % (base, " ".join(snippet.split())[:70]),)
        if checked:
            return "tight", "%d place(s) in the script checked" % checked
        return "not a date", "the script looks for nothing it is handed"


def _selector_texts(value):
    """What a selector looks for as a piece of an element's text or of an
    attribute."""
    if not isinstance(value, str):
        return []
    return [m.group("t") for p in SELECTOR_TEXTS for m in p.finditer(value) if m.group("t")]


def _script_texts(value):
    """What a script with text written into it looks for as a piece."""
    if not isinstance(value, str):
        return []
    return [m.group("t") for m in SCRIPT_TEXTS.finditer(value) if m.group("t")]


def _side_by_side(choices):
    """Rows that hold every value of every choice at least once, as many
    rows as the longest choice has values."""
    if not choices:
        return [()]
    longest = max(len(c) for c in choices)
    return [tuple(c[i % len(c)] for c in choices) for i in range(longest)]


def collision(kind, per):
    """(needle, found in, date asked for, date found) for the first needle
    of one sample date found in a way a page prints another, else None.

    A needle is held to what it names. One built for a single date is
    compared with every way a page prints any other. One built the same for
    every day of a month names the month, and is compared with the ways a
    page prints other months, since finding it in any day of its own month
    is what it is for. One built the same for a day in either year is a
    day written without its year, and is compared with the other days. A
    spelling both dates share is not one inside another."""
    keys = {a: {_key(n) for n in per[a]} for a in SAMPLES}
    for a in SAMPLES:
        mine = set(printed(a)) | keys[a]
        for n in per[a]:
            sharers = {b for b in SAMPLES if _key(n) in keys[b]}
            for b in SAMPLES:
                if b in sharers:
                    continue
                if len(sharers) == 1 or all(s[5:] == a[5:] for s in sharers):
                    hays = printed(b) + [x for x in per[b] if isinstance(x, str)]
                else:
                    hays = period_variants(b[:7])
                for h in hays:
                    if h not in mine and finds(kind, n, h):
                        return (_key(n), h, a, b)
    return None


# -- page scripts, read as text --------------------------------------------

def _ident(name):
    return r"(?<![\w$.\\])%s(?![\w$])" % re.escape(name)


def _balanced(src, start):
    depth, i = 1, start
    while i < len(src) and depth:
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        i += 1
    return src[start:i - 1], i


def js_signature(src):
    m = re.match(r"\s*(?:async\s*)?(?:function\s*\w*\s*)?\(", src)
    if m:
        return _balanced(src, m.end())[0]
    m = re.match(r"\s*(?:async\s*)?(\w+)\s*=>", src)
    return m.group(1) if m else ""


def js_names(sig):
    """Each name in the script's signature, and how it is reached from the
    value handed in. An element's evaluate hands the element first and the
    value second."""
    parts, depth, cur = [], 0, ""
    for ch in sig:
        depth += {"[": 1, "{": 1, "(": 1, "]": -1, "}": -1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    arg = parts[-1] if len(parts) >= 2 else (parts[0] if parts else "")
    out = {}
    if arg.startswith("["):
        for i, n in enumerate(x.strip() for x in arg.strip("[]").split(",")):
            if re.fullmatch(r"\w+", n):
                out[n] = ("i", i)
    elif arg.startswith("{"):
        for piece in arg.strip("{}").split(","):
            k, _, n = piece.partition(":")
            n = (n or k).strip().split("=")[0].strip()
            if re.fullmatch(r"\w+", n):
                out[n] = ("k", k.strip())
    elif re.fullmatch(r"\w+", arg):
        out[arg] = ("all", None)
    return out


def _block_after(src, i):
    """Where the statement or block starting at i ends."""
    j = i
    while j < len(src) and src[j].isspace():
        j += 1
    if j < len(src) and src[j] == "{":
        depth = 0
        for k in range(j, len(src)):
            depth += {"{": 1, "}": -1}.get(src[k], 0)
            if depth == 0:
                return k + 1
        return len(src)
    end = src.find(";", j)
    return len(src) if end < 0 else end + 1


def js_derived(src, names):
    """Names the script makes from those it was handed. Each (name, start,
    end) leads to the name handed in and a path, which is properties, or
    each for a collection's members, and start and end are where the name
    means that. A callback's parameter means it only inside its callback,
    and a loop's only inside its loop. Only a value that starts from the
    name counts, so a list of rows filtered by a test of the date is not
    the date."""
    derived = {(n, 0, len(src)): (n, ()) for n in names}
    grew = True
    while grew:
        grew = False
        for (t, lo, hi), (base, path) in list(derived.items()):
            for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*([^;\n]*)", src[lo:hi]):
                new, rhs = m.group(1), m.group(2)
                mm = re.match(r"\s*[(\[!]*\s*" + _ident(t) + r"((?:\.\w+)*)", rhs)
                if mm and (new, lo, hi) not in derived:
                    props = tuple(p for p in mm.group(1).split(".") if p and p not in
                                  ("filter", "slice", "map", "concat", "trim", "toLowerCase"))
                    derived[(new, lo, hi)] = (base, path + props)
                    grew = True
            for m in re.finditer(_ident(t) + r"(?:\.\w+)*\s*\.\s*(?:map|filter|some|every|forEach|find|flatMap)"
                                 r"\s*(\()\s*\(?\s*(\w+)", src[lo:hi]):
                opened = lo + m.start(1) + 1
                _, closed = _balanced(src, opened)
                key = (m.group(2), opened, closed)
                if key not in derived:
                    derived[key] = (base, path + ("each",))
                    grew = True
            for m in re.finditer(r"for\s*\(\s*(?:const|let|var)\s+(\w+)\s+of\s+" + _ident(t) + r"[^)]*\)",
                                 src[lo:hi]):
                start = lo + m.end()
                key = (m.group(1), start, _block_after(src, start))
                if key not in derived:
                    derived[key] = (base, path + ("each",))
                    grew = True
    return derived


_JS_SUBSTRING = re.compile(r"\.(includes|indexOf|lastIndexOf|startsWith|endsWith|search|match)\s*\(")
_JS_BOUNDED = re.compile(r"\[\^0-9|\[\^\\\\d|\(\?<!|\(\?!|\\\\b")


def js_lookups(src, derived):
    """Where the script looks for something it was handed inside text,
    [(substring or bounded, name handed in, path, the words around it)]."""
    out = []

    def meant_at(pos):
        return [(t, base, path) for (t, lo, hi), (base, path) in derived.items() if lo <= pos < hi]
    for m in _JS_SUBSTRING.finditer(src):
        arg, end = _balanced(src, m.end())
        here = meant_at(m.start())
        recv = re.search(r"([\w$]+)(?:\.[\w$]+)*\s*\)?\s*$", src[max(0, m.start() - 60):m.start()])
        if recv and recv.group(1) in {t for t, _, _ in here}:
            continue      # the handed-in list asked whether it holds something, which is equality
        for t, base, path in here:
            mm = re.search(_ident(t) + r"((?:\.\w+)*)", arg)
            if mm:
                props = tuple(p for p in mm.group(1).split(".")
                              if p and p not in ("slice", "trim", "toLowerCase", "replace"))
                out.append(("substring", base, path + props, src[max(0, m.start() - 30):end]))
    for m in re.finditer(r"new\s+RegExp\s*\(", src):
        arg, end = _balanced(src, m.end())
        for t, base, path in meant_at(m.start()):
            if re.search(_ident(t), arg):
                out.append(("bounded" if _JS_BOUNDED.search(arg) else "substring", base, path,
                            src[m.start():end]))
    return out


def js_reach(value, how):
    kind, key = how
    if kind == "all":
        return value
    try:
        return value[key]
    except Exception:
        return None


def js_follow(value, path):
    vals = [value]
    for p in path:
        nxt = []
        for v in vals:
            if p == "each":
                if isinstance(v, (list, tuple, set)):
                    nxt.extend(v)
            elif isinstance(v, dict):
                if p in v:
                    nxt.append(v[p])
            else:
                nxt.append(v)
        vals = nxt
    return vals


# -- the repository ----------------------------------------------------------

def _repo_files():
    files = [(p, p.relative_to(REPO).as_posix(), p.parent.name)
             for p in sorted((REPO / "apps").glob("*/*.py"))]
    files += [(p, p.relative_to(REPO).as_posix(), "core")
              for p in sorted((REPO / "core" / "paperpull_core").glob("*.py"))]
    return files


def _where(s):
    return "%s line %d in %s" % (s["fn"].mod.rel, s["node"].lineno, s["fn"].qual)


@contextlib.contextmanager
def _app_modules_put_back(root):
    """Takes every app module the census imported out of sys.modules again,
    and puts back each one it took out or replaced, so a later test imports
    its own app's modules and its own storage as it always has."""
    before = dict(sys.modules)

    def ours(mod):
        return str(getattr(mod, "__file__", None) or "").startswith(str(root))
    try:
        yield
    finally:
        for name in [n for n, m in sys.modules.items() if before.get(n) is not m and ours(m)]:
            del sys.modules[name]
        for name, mod in before.items():
            if sys.modules.get(name) is not mod and ours(mod):
                sys.modules[name] = mod


@pytest.fixture(scope="module")
def repo():
    with _app_modules_put_back(REPO / "apps"):
        census = Census(_repo_files())
        verdicts = []
        for s in census.sites:
            try:
                verdicts.append((s,) + census.judge(s))
            except Unknown as e:
                verdicts.append((s, "unknown", str(e)))
    return census, verdicts


def test_no_app_finds_one_date_inside_another(repo):
    _, verdicts = repo
    loose = ["%s looks for %r and finds it inside %r, so %s can be taken for %s%s" % (
        _where(s), hit[0], hit[1], hit[2], hit[3], (", where " + hit[4]) if len(hit) > 4 else "")
        for s, verdict, hit in verdicts if verdict == "loose"]
    assert not loose, "\n".join(loose)


def test_every_place_that_looks_for_a_date_can_be_worked_out(repo):
    _, verdicts = repo
    unknown = ["%s, %s" % (_where(s), why) for s, verdict, why in verdicts if verdict == "unknown"]
    assert not unknown, "\n".join(unknown)


def test_the_census_reaches_the_places_it_is_about(repo):
    """Not vacuous. The places found by what they do include every app this
    was checked against, and each is judged on dates it really looks for."""
    census, verdicts = repo
    tight = {s["fn"].mod.app for s, verdict, _ in verdicts if verdict == "tight"}
    for app in ("ally", "etrade", "meijer", "navyfederal", "vanguard", "verizon"):
        assert app in tight, (app, sorted(tight))
    assert sum(1 for _, verdict, _ in verdicts if verdict == "tight") >= 25
    assert len(census.parsers) >= 50, "the functions that read a date out of text"


# -- planted slips -------------------------------------------------------------
#
# The census run on small made-up apps. olddominion is Dominion's own code
# before the fix, reading a bill's date out of its panel header and finding
# the panel again by the date's spelling. plantedrows holds one of each
# other shape, every way to look for a date the census follows, done loosely
# and done whole.

PLANTED = {
    "olddominion": {
        "olddominion_site.py": r'''
import re

PANEL_HEADER = ".MuiExpansionPanelSummary-root"
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _panel_dates(page):
    out = []
    loc = page.locator(PANEL_HEADER)
    for i in range(loc.count()):
        try:
            t = loc.nth(i).inner_text(timeout=800) or ""
        except Exception:
            continue
        m = _DATE_RE.search(t)
        if m:
            out.append(f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
    return out


def _find_panel_for(page, iso: str):
    try:
        y, m, d = iso.split("-")
    except Exception:
        return None
    mmddyyyy = f"{int(m)}/{int(d)}/{y}"
    loc = page.locator(PANEL_HEADER)
    for i in range(loc.count()):
        h = loc.nth(i)
        try:
            if mmddyyyy in (h.inner_text(timeout=800) or ""):
                return h
        except Exception:
            continue
    return None


def download_statement(page, iso_date: str, out_path) -> bool:
    header = _find_panel_for(page, iso_date)
    if header is None:
        return False
    header.click()
    return True
''',
        "olddominion_docs.py": r'''
import olddominion_site as site


class Document:
    def __init__(self, title="", date=""):
        self.title = title
        self.date = date


def discover(page):
    return [Document(title="Statement", date=iso) for iso in site._panel_dates(page)]


def download_one(page, doc, out_path):
    return site.download_statement(page, doc.date, out_path)
''',
    },
    "plantedrows": {
        "plantedrows_site.py": r'''
import re

from paperpull_core.dates import human_date

_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
LOOSE_JS = "([dates]) => [...document.querySelectorAll('tr')].find(r => dates.some(d => r.innerText.includes(d)))"
WHOLE_JS = ("([dates]) => { const res = dates.map(d => new RegExp('(^|[^0-9])' + d + '(?![0-9])')); "
            "return [...document.querySelectorAll('tr')].find(r => res.some(x => x.test(r.innerText))) }")


def parse_date(text):
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    return "%04d-%02d-%02d" % (int(m.group(3)), int(m.group(1)), int(m.group(2)))


def _spelled(iso):
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}/{y}"


def loose_row(page, iso):
    return page.locator("tr").filter(has_text=_spelled(iso))


def whole_row(page, iso):
    return page.locator("tr").filter(
        has_text=re.compile(r"(?<![0-9])" + re.escape(_spelled(iso)) + r"(?![0-9])"))


def padded_row(page, iso):
    return page.locator("tr").filter(has_text=f"{iso[5:7]}/{iso[8:10]}/{iso[:4]}")


def named_row(page, iso):
    return page.get_by_text(human_date(iso))


def _press(page, label):
    return page.get_by_role("button", name=label)


def passed_on(page, iso):
    return _press(page, _spelled(iso))


def raw_row(page, date_text):
    for row in page.locator("tr").all():
        if date_text in row.inner_text():
            return row
    return None


def loose_script(page, iso):
    return page.evaluate_handle(LOOSE_JS, [[_spelled(iso), iso]])


def whole_script(page, iso):
    return page.evaluate_handle(WHOLE_JS, [[_spelled(iso), iso]])


def joined_selector(page, iso):
    return page.locator("tr:has-text('" + _spelled(iso) + "')")


def attribute_selector(page, iso):
    return page.locator("[aria-label*='%s']" % _spelled(iso))


def padded_selector(page, iso):
    return page.locator(f"tr:has-text('{iso[5:7]}/{iso[8:10]}/{iso[:4]}')")


def written_script(page, iso):
    found = "() => [...document.querySelectorAll('tr')].find(r => r.innerText.includes('%s'))"
    return page.evaluate_handle(found % _spelled(iso))
''',
        "plantedrows_docs.py": r'''
import plantedrows_site as site


class Document:
    def __init__(self, date="", date_text=""):
        self.date = date
        self.date_text = date_text


def discover(page):
    out = []
    for row in page.locator("tr").all():
        text = row.inner_text()
        out.append(Document(date=site.parse_date(text), date_text=text))
    return out


def run(page, docs):
    for doc in docs:
        site.loose_row(page, doc.date)
        site.whole_row(page, doc.date)
        site.padded_row(page, doc.date)
        site.named_row(page, doc.date)
        site.passed_on(page, doc.date)
        site.raw_row(page, doc.date_text)
        site.loose_script(page, doc.date)
        site.whole_script(page, doc.date)
        site.joined_selector(page, doc.date)
        site.attribute_selector(page, doc.date)
        site.padded_selector(page, doc.date)
        site.written_script(page, doc.date)
''',
    },
}


@pytest.fixture(scope="module")
def planted():
    root = Path(tempfile.mkdtemp(prefix="date-census-"))
    try:
        with _app_modules_put_back(root):
            files = []
            for app, sources in PLANTED.items():
                (root / "apps" / app).mkdir(parents=True)
                for name, text in sources.items():
                    path = root / "apps" / app / name
                    path.write_text(text.lstrip(), encoding="utf-8")
                    files.append((path, "apps/%s/%s" % (app, name), app))
            files += [(p, p.relative_to(REPO).as_posix(), "core")
                      for p in sorted((REPO / "core" / "paperpull_core").glob("*.py"))]
            census = Census(files)
            verdicts = {}
            for s in census.sites:
                try:
                    verdict = census.judge(s)
                except Unknown as e:
                    verdict = ("unknown", str(e))
                if s["fn"].mod.app != "core":
                    verdicts.setdefault(s["fn"].qual, []).append(verdict)
        yield verdicts
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _only(verdicts, qual):
    found = verdicts.get(qual, [])
    assert len(found) == 1, (qual, found)
    return found[0]


def test_dominions_own_code_before_the_fix_is_caught(planted):
    verdict, hit = _only(planted, "_find_panel_for")
    assert verdict == "loose", hit
    needle, found_in, asked, found = hit
    # a January bill, and the November one whose header holds its spelling
    assert asked[5:7] == "01" and found[5:7] == "11" and needle in found_in, hit


@pytest.mark.parametrize("qual", ["loose_row", "_press", "raw_row", "loose_script",
                                  "joined_selector", "attribute_selector", "written_script"])
def test_a_planted_slip_is_caught(planted, qual):
    verdict, hit = _only(planted, qual)
    assert verdict == "loose", (qual, hit)


@pytest.mark.parametrize("qual", ["whole_row", "padded_row", "named_row", "whole_script",
                                  "padded_selector"])
def test_a_date_looked_for_whole_is_let_be(planted, qual):
    verdict, why = _only(planted, qual)
    assert verdict == "tight", (qual, why)
