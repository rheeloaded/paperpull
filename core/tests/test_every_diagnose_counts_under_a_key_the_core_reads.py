"""Every Diagnose counts what it read under a key the core reads.

The core reads a Diagnose's finding, the dict an app writes through
write_shaped with "signed_out" in it, for whether it read anything
(paperpull_core.words, _note_what_was_read). A finding whose app's own
checks said it was signed out or met a security check, and that counted
nothing, ends as a report that read nothing, and the person is told to sign
in and make it again.

The core read only "collected", while 43 apps counted under another key.
Some of those counts are what a reader of the provider's own list read,
"documents_total" in four apps whose list is an API answer, two of U.S.
Bank's and one of Discover Card's, and "rows_collected" in thirteen apps
whose Diagnose reads the list their runs read. A report of theirs that read
rows where a check also tripped told the person to sign in, when it held
what a repair needs. The core reads words.COUNT_KEYS, and those thirteen
write "collected" now.

The rest are a loose scrape made only for Diagnose, "rows_collected" of
every row a page has and "links_collected" of every link, which a sign-in
page's own lists of links fill. Read as rows read, a report made signed
out would say it was saved. So the core does not read them, and T-Mobile,
whose "collected" was such a scrape, writes it as "rows_collected" now.
test_every_count_the_core_reads_finds_nothing_on_a_sign_in_page.py runs
each count the core reads against a made-up sign-in page.

- Every count written into a finding, a len(), a sum() or a whole number,
  goes under a key the core reads, a scrape's key or one named here as a
  count of something other than documents. A new name fails until it is
  put in one of them.
- Every finding counts under a key the core reads, or its app is named here
  as one whose Diagnose counts only a scrape, or as one that counts no
  documents at the top of its finding. Both lists are exact, so a name that
  no longer belongs fails too.
- Every key a Diagnose reads back from its finding is one it writes. U.S.
  Bank printed "Rows collected" from a key it never wrote, so the line read
  "Rows collected: ?", and its year picker line read another such key.

That each write of those keys is a count, never an error, is held by
test_diagnose_counts_what_it_collected.py.

A finding is found by what it does. In each function of an app's own
script, a name passed to write_shaped as what to write is a finding when
the function writes "signed_out" into it. A key is read when it is written
as a subscript, plain, added to or typed, or in a dict literal the name is
given, or through update(), setdefault() or dict(). A key held in a
variable is not read, and no app writes one that way.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core.words import COUNT_KEYS  # noqa: E402

ENTRIES = sorted(p for p in REPO.glob("apps/*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")) and not p.name.startswith("."))

# The keys a loose scrape made only for Diagnose is counted under, which the
# core does not read.
SCRAPE_KEYS = {
    "rows_collected": "every row a page has that holds a link, a date or a word, a sign-in "
                      "page's lists of links among them",
    "links_collected": "every link on the tab, a sign-in page's among them",
}

# Counts a finding holds that are not of documents read, so the core does
# not read them as something read.
NOT_DOCUMENTS = {
    "print_receipt_controls": "the Print receipt controls on one receipt page",
    "invoice_controls": "the invoice controls on one receipt page",
    "pay_assignments": "Paylocity's pay assignments, the jobs a person is paid for",
}

_LI = "keeps every table row, [role=row] or li holding a link, a date or the word download"
_TABLE = "keeps every table row or [role=row] holding a link, a date or the word download"

# The apps whose Diagnose counts only a loose scrape, read from each one's
# collect_documents. A check that tripped there still reads as nothing read,
# since nothing it counts tells a sign-in page from its list. An app whose
# count is the list its runs read writes it as "collected" instead.
SCRAPE_ONLY = {
    "adp": _LI, "amfam": _LI, "applecard": _LI, "att": _LI, "coinbase": _LI, "etrade": _LI,
    "golden1": _LI, "irs": _LI, "nelnet": _LI, "newrez": _LI, "optum": _LI, "sba": _LI,
    "smud": _LI, "statefarm": _LI, "tmobile": _LI, "verizonmobile": _LI, "wellsfargo": _LI,
    "cetera": _TABLE, "nwnatural": _TABLE, "portlandgeneral": _TABLE, "sdge": _TABLE,
    "tualatin": _TABLE, "ziply": _TABLE,
    "shelbycounty": "keeps every table body row",
    "venmo": "counts what an input shows that reads as a month",
    "treasurydirect": "counts every link on the tab",
}

# The apps whose Diagnose finding counts no documents at its top, so a check
# that tripped there still reads as nothing read.
COUNTS_NO_DOCUMENTS = {
    "amazon": "counts the controls on one receipt page",
    "bestbuy": "counts the controls on one receipt page",
    "ebay": "counts the controls on one receipt page",
    "gap": "counts the controls on one receipt page",
    "homedepot": "counts the controls on one receipt page",
    "lowes": "counts the controls on one receipt page",
    "target": "counts the controls on one receipt page",
    "walmart": "counts the controls on one receipt page",
    "costco": "counts its history rows inside its history survey",
    "github": "counts its history rows inside its history survey",
    "kroger": "counts its history rows inside its history survey",
    "meijer": "counts its history rows inside its history survey",
    "apple": "says whether each of its two stores was signed in",
    "uber": "says whether rides and Uber Eats were each signed in",
    "bofa": "surveys the page and counts nothing",
}


def _const_key(key):
    """A constant key, through Fixed("...") as ING writes its keys, or None."""
    if isinstance(key, ast.Call) and key.args and isinstance(key.args[0], ast.Constant):
        key = key.args[0]
    return key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None


def _is_name(node, name) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_count(node) -> bool:
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("len", "sum")):
        return True
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return True
    if isinstance(node, ast.IfExp):
        return _is_count(node.body) or _is_count(node.orelse)
    return False


def _dict_items(node):
    """The constant keys of a dict literal, dict(...) or a list of pairs."""
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            key = _const_key(k) if k is not None else None
            if key:
                yield key, v
    elif isinstance(node, (ast.List, ast.Tuple)):
        for pair in node.elts:
            if isinstance(pair, (ast.Tuple, ast.List)) and len(pair.elts) == 2:
                key = _const_key(pair.elts[0])
                if key:
                    yield key, pair.elts[1]
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
          and node.func.id == "dict"):
        for kw in node.keywords:
            if kw.arg:
                yield kw.arg, kw.value
        for arg in node.args:
            yield from _dict_items(arg)


def _targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        for part in node.elts:
            yield from _targets(part)
    else:
        yield node


def _writes(func, name):
    """Each key written into `name` in this function, with its value."""
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if _is_name(target, name):
                    yield from _dict_items(node.value)
                for part in _targets(target):
                    if isinstance(part, ast.Subscript) and _is_name(part.value, name):
                        key = _const_key(part.slice)
                        if key:
                            value = node.value
                            if (isinstance(target, (ast.Tuple, ast.List))
                                    and isinstance(value, (ast.Tuple, ast.List))
                                    and len(value.elts) == len(target.elts)
                                    and part in target.elts):
                                value = value.elts[target.elts.index(part)]
                            yield key, value
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            target = node.target
            if isinstance(target, ast.Subscript) and _is_name(target.value, name):
                key = _const_key(target.slice)
                if key and node.value is not None:
                    yield key, node.value
            elif _is_name(target, name) and node.value is not None:
                yield from _dict_items(node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and _is_name(node.func.value, name)):
            if node.func.attr == "update":
                for kw in node.keywords:
                    if kw.arg:
                        yield kw.arg, kw.value
                for arg in node.args:
                    yield from _dict_items(arg)
            elif node.func.attr in ("setdefault", "__setitem__") and len(node.args) == 2:
                key = _const_key(node.args[0])
                if key:
                    yield key, node.args[1]


def _reads(func, name):
    """Each key this function reads back from `name`, with its line."""
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and _is_name(node.func.value, name) and node.args):
            key = _const_key(node.args[0])
            if key:
                yield key, node.lineno
        elif (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
              and _is_name(node.value, name)):
            key = _const_key(node.slice)
            if key:
                yield key, node.lineno
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and isinstance(node.ops[0], (ast.In, ast.NotIn))
              and _is_name(node.comparators[0], name)):
            key = _const_key(node.left)
            if key:
                yield key, node.lineno


def _shaped_names(func):
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[1], ast.Name):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if called == "write_shaped":
                yield node.args[1].id


def findings_in(tree):
    """Each Diagnose finding in a module, as (function, name, writes, reads)."""
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for name in sorted(set(_shaped_names(func))):
            writes = list(_writes(func, name))
            if any(key == "signed_out" for key, _ in writes):
                yield func, name, writes, list(_reads(func, name))


def _findings(path: Path):
    return list(findings_in(ast.parse(path.read_text(encoding="utf-8"))))


def _app(path: Path) -> str:
    return path.parent.name


def _unknown_counts(findings):
    return sorted({key for _f, _n, writes, _r in findings for key, value in writes
                   if _is_count(value) and key not in COUNT_KEYS and key not in SCRAPE_KEYS
                   and key not in NOT_DOCUMENTS})


def _counts_documents(findings) -> bool:
    return all(any(key in COUNT_KEYS for key, _ in writes) for _f, _n, writes, _r in findings)


def _counts_a_scrape(findings) -> bool:
    return all(any(key in SCRAPE_KEYS for key, _ in writes) for _f, _n, writes, _r in findings)


def _read_unwritten(findings):
    out = []
    for _func, _name, writes, reads in findings:
        written = {key for key, _ in writes}
        out += ["%s at line %d" % (key, line) for key, line in reads if key not in written]
    return out


def test_the_census_reads_every_diagnose():
    """Every app script that writes signed_out has its finding read here,
    so a finding built some way this does not follow fails rather than
    passing unread."""
    found = {path: _findings(path) for path in ENTRIES}
    assert sum(len(f) for f in found.values()) >= 90, "the census found the findings"
    unread = [str(path.relative_to(REPO)) for path, f in found.items()
              if not f and '"signed_out"' in path.read_text(encoding="utf-8")]
    assert not unread, "these write signed_out in a finding this census did not find: %s" % unread


@pytest.mark.parametrize("path", ENTRIES, ids=_app)
def test_every_count_is_one_the_core_reads_or_is_not_of_documents(path):
    unknown = _unknown_counts(_findings(path))
    assert not unknown, (
        "%s counts under %s, which the core does not read for whether a Diagnose read "
        "anything. Count what a reader of the provider's list read under a key of "
        "paperpull_core.words.COUNT_KEYS, a loose scrape under rows_collected, or name a "
        "count of something other than documents in NOT_DOCUMENTS here."
        % (path.relative_to(REPO), ", ".join(unknown)))


@pytest.mark.parametrize("path", ENTRIES, ids=_app)
def test_every_diagnose_counts_its_documents_where_the_core_reads(path):
    findings = _findings(path)
    if not findings:
        return
    app = _app(path)
    counts, scrape = _counts_documents(findings), _counts_a_scrape(findings)
    if app in SCRAPE_ONLY:
        assert scrape and not counts, (
            "%s is named in SCRAPE_ONLY, as counting only a loose scrape, and it %s, so "
            "take it off" % (app, "counts under a key the core reads" if counts
                             else "counts no scrape"))
    elif app in COUNTS_NO_DOCUMENTS:
        assert not counts and not scrape, ("%s now counts something, so take it off "
                                           "COUNTS_NO_DOCUMENTS" % app)
    else:
        assert counts, (
            "%s's Diagnose counts nothing under a key of paperpull_core.words.COUNT_KEYS, so "
            "a report that read rows where a sign-in check tripped tells the person to sign "
            "in. Count the list its runs read under collected. If what it counts is a loose "
            "scrape of the page, name the app in SCRAPE_ONLY with what the scrape keeps."
            % path.relative_to(REPO))


def test_every_app_named_here_is_an_app_with_a_finding():
    apps = {_app(path) for path in ENTRIES if _findings(path)}
    named = set(COUNTS_NO_DOCUMENTS) | set(SCRAPE_ONLY)
    assert named <= apps, named - apps
    assert not set(COUNTS_NO_DOCUMENTS) & set(SCRAPE_ONLY)


@pytest.mark.parametrize("path", ENTRIES, ids=_app)
def test_what_diagnose_reads_back_it_wrote(path):
    unwritten = _read_unwritten(_findings(path))
    assert not unwritten, ("%s reads back from its finding what it never writes there, so "
                           "what it prints of it is never right: %s"
                           % (path.relative_to(REPO), ", ".join(unwritten)))


def test_the_core_reads_no_key_named_here_as_not_documents():
    assert not (set(NOT_DOCUMENTS) | set(SCRAPE_KEYS)) & set(COUNT_KEYS)


def test_every_key_named_here_is_written_by_an_app():
    """A key no app writes any more is taken off, so the lists only say
    what is so."""
    written = {key for path in ENTRIES for _f, _n, writes, _r in _findings(path) for key, _ in writes}
    stale = (set(COUNT_KEYS) | set(SCRAPE_KEYS) | set(NOT_DOCUMENTS)) - written
    assert not stale, stale


# The census's own checks, against invented code.

def _one(src):
    return list(findings_in(ast.parse(src)))


FINDING = '''
def cmd_diagnose(self):
    info = {"timestamp": now_iso()}
    info["signed_out"] = site.looks_signed_out(page)
    %s
    write_shaped(out, info, words)
    %s
'''


def test_a_count_under_a_new_key_is_found():
    findings = _one(FINDING % ('info["statements_found"] = len(rows)', ""))
    assert _unknown_counts(findings) == ["statements_found"]
    assert not _counts_documents(findings)


@pytest.mark.parametrize("write", [
    'info["documents_total"] = len(rows)',
    'info[Fixed("documents_total")] = len(rows)',
    'info["documents_total"]: int = len(rows)',
    'info.update(documents_total=len(rows))',
    'info.update({"documents_total": len(rows)})',
    'info.update([("documents_total", len(rows))])',
    'info.setdefault("documents_total", len(rows))',
    'info["documents_total"], info["more"] = len(rows), bool(more)',
])
def test_a_count_the_core_reads_is_found_however_it_is_written(write):
    findings = _one(FINDING % (write, ""))
    assert _counts_documents(findings), write
    assert not _unknown_counts(findings), write


def test_a_finding_written_whole_is_read():
    src = '''
def cmd_diagnose(self):
    info = {"signed_out": site.looks_signed_out(page), "documents_total": len(docs)}
    write_shaped(out, info, words)
'''
    assert _counts_documents(_one(src))


def test_a_finding_that_counts_nothing_is_found():
    findings = _one(FINDING % ('info["rows"] = rows', ""))
    assert findings and not _counts_documents(findings)


def test_a_file_without_signed_out_is_no_finding():
    src = '''
def cmd_trace(self):
    info = {"rows": len(rows)}
    write_shaped(out, info, words)
'''
    assert not _one(src)


@pytest.mark.parametrize("read", [
    'print(info.get("collected", "?"))',
    'print(info["collected"])',
    'if "collected" in info: print(1)',
])
def test_a_key_read_back_but_never_written_is_found(read):
    findings = _one(FINDING % ('info["collected_generic"] = len(docs)', read))
    assert _read_unwritten(findings) and _read_unwritten(findings)[0].startswith("collected ")


def test_a_key_read_back_as_written_passes():
    findings = _one(FINDING % ('info["collected_generic"] = len(docs)',
                               'print(info.get("collected_generic", "?"))'))
    assert not _read_unwritten(findings)
