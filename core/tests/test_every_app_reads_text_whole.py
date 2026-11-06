"""Every app reads a provider's text whole, so half of a character never
gets past the place it came in (paperpull_core.characters).

The browser hands Python U+FFFD for half of a character, from evaluate,
from a page's text and from an in-page fetch. Python keeps the half only
where it reads the text itself, a provider's JSON through the json module
(Response.json(), APIResponse.json(), json.loads of a body or of what a
page made with JSON.stringify) and a PDF's text through pypdf or
pdfplumber. With the half in memory, the first line a run printed stopped
it with UnicodeEncodeError under the control panel, and every record,
row and file name made from it disagreed with the next.

So this reads every app's own code, the core's and the transactions
tool's. Every JSON parse, json.loads, json.load or a response's .json(),
has to be read inside what is handed to whole_json, in the same
expression, and every PDF text pypdf or pdfplumber reads inside what is
handed to whole_characters or whole_json, so nothing it gave is kept
before it is whole. A parse kept in a name and made whole later is not
followed, and is named as wrong. The core's own files, the local
browser's own answers and a failure report the core wrote itself are the
only parses left alone, each named below with why. The canary at the end
holds the census to the shapes it has to see.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PARSERS = {"loads", "load"}
# What pypdf and pdfplumber read a page's text with.
PDF_TEXT = {"extract_text", "extract_text_lines", "extract_text_simple", "extract_words"}
# Parses that read no provider's text, by module and the function holding
# them, and why.
OWN = {
    ("browser.py", "debug_port_holder"): "the local browser's own /json/version",
    ("browser.py", "wait_for_debug_port"): "the local browser's own /json/version",
    ("browser.py", "_wanted_chromium_build"): "Playwright's own browsers.json, packaged with it",
    ("browser.py", "_install_takes_no_remove"): "Playwright's own package.json, packaged with it",
    ("classification.py", "load_rules"): "rules packaged with the app",
    ("doc_types.py", "load_rules"): "rules packaged with the app",
    ("export_transactions.py", "statement_name"): "a list of folders the core wrote itself",
    ("host_sandbox.py", "probe"): "the host check's own child, which asks the kernel, "
                                  "never a provider",
    ("export_transactions.py", "__init__"): "the tool's own cache, whose paths stay as the "
                                            "disk gave them and whose text is made whole",
    ("listing.py", "_before"): "the note this core wrote itself",
    ("pdf_reader.py", "start"): "the PDF reader's own word that it is ready",
    ("pdf_reader.py", "_serve"): "the app's own job for its PDF reader, whose path stays as "
                                 "the disk gave it",
    ("listing.py", "last"): "the note this core wrote itself",
    ("storage.py", "load_config"): "the person's own config.json",
    ("storage.py", "ensure_owner"): "the person's own config.json",
    ("storage.py", "documents_roots"): "a list of folders this core wrote itself",
    ("storage.py", "load"): "the JsonStore's own file, made whole as it is read",
    ("storage.py", "_recover_from_backup"): "the JsonStore's own backup, made whole as it is read",
    ("testkit.py", "*"): "the local test browser's own answers",
}


def sources():
    apps = [p for p in (REPO / "apps").glob("*/*.py")
            if not p.name.startswith("test_") and p.name != "storage.py"]
    return sorted(apps) + sorted((REPO / "core" / "paperpull_core").glob("*.py")) + [
        REPO / "tools" / "export_transactions.py"]


def _parents(tree) -> dict:
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _enclosing(node, parents) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return ""


def _from_json(tree) -> set:
    """The names a module took from the json module itself, loads or load
    under whatever name it gave them."""
    return {alias.asname or alias.name for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "json"
            for alias in node.names if alias.name in PARSERS}


def _failure_read(node) -> bool:
    """The failure report the core wrote, which every app reads back
    through json imported as _failure_json."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "_failure_json")


def _kind(node, from_json=frozenset()) -> str:
    """"json" for a JSON parse, "pdf" for a PDF's text, or "". A request's
    post_data_json is Playwright's json.loads of the page's request body."""
    if isinstance(node, ast.Attribute) and node.attr == "post_data_json":
        return "json"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in from_json:
        return "json"
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return ""
    attr, owner = node.func.attr, node.func.value
    if attr == "json" and not node.args and not node.keywords:
        return "json"
    if attr in PARSERS and isinstance(owner, ast.Name) and owner.id.endswith("json"):
        return "json"
    if attr in PDF_TEXT:
        return "pdf"
    return ""


WHOLE = {"json": {"whole_json"}, "pdf": {"whole_characters", "whole_json"}}


def _handed_to(node, parents, kind: str) -> bool:
    """Whether node is read inside what is handed to the function that makes
    it whole, in the same expression, so nothing it gave is kept before it
    is whole. A name it is given first and made whole later is not followed,
    and counts as not."""
    at = node
    while at in parents and not isinstance(at, (ast.stmt, ast.Lambda)):
        up = parents[at]
        if (isinstance(up, ast.Call) and ast.unparse(up.func) in WHOLE[kind]
                and at is not up.func):
            return True
        at = up
    return False


def census(source: str, name: str = "") -> tuple:
    """(what is wrong, as "line: why", the parses found) for one module."""
    tree = ast.parse(source)
    parents = _parents(tree)
    taken = _from_json(tree)
    wrong, found = [], 0
    for node in ast.walk(tree):
        kind = _kind(node, taken)
        if not kind or _failure_read(node):
            continue
        fn = _enclosing(node, parents)
        if kind == "json" and ((name, fn) in OWN or (name, "*") in OWN):
            continue
        found += 1
        if not _handed_to(node, parents, kind):
            wrong.append("%d: %s in %s() is not made whole by %s where it is read" % (
                node.lineno, ast.unparse(node)[:60], fn or "the module",
                "whole_json" if kind == "json" else "whole_characters"))
    return wrong, found


def test_every_parse_of_a_providers_text_is_made_whole():
    wrong, total = [], 0
    for path in sources():
        said, found = census(path.read_text(encoding="utf-8-sig"), path.name)
        total += found
        wrong += ["%s:%s" % (path.relative_to(REPO).as_posix(), s) for s in said]
    assert not wrong, "\n".join(wrong)
    assert total >= 80, total


def test_every_named_own_parse_is_still_there():
    """A name in OWN that no longer holds a parse is taken out, so the list
    never lets a new parse through under an old name."""
    held = set()
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        parents, taken = _parents(tree), _from_json(tree)
        for node in ast.walk(tree):
            if _kind(node, taken) == "json":
                held.add((path.name, _enclosing(node, parents)))
    named = {k for k in OWN if k[1] != "*"}
    assert named <= held, sorted(named - held)


CANARY = '''
import json
def a(r):
    return r.json()
def b(r):
    return whole_json(r.json())
def c(body):
    data = json.loads(body)
    return whole_json(data)
def d(body):
    return whole_json(json.loads(body.decode("utf-8")))
def e(reader):
    return whole_characters(" ".join((pg.extract_text() or "") for pg in reader.pages))
def f(page):
    return page.extract_text().strip()
def g(r):
    capture.append(whole_json(r.json()))
def h(r):
    return whole_json(r.json().get("x"))
def i(r):
    return whole_characters(r.json())
def j(res):
    sent = res.request.post_data_json
    return whole_json(res.request.post_data_json)
from json import loads as read_it
def k(body):
    return read_it(body), whole_json(read_it(body))
'''


def test_the_census_sees_the_shapes_it_has_to():
    wrong, found = census(CANARY)
    assert found == 13
    lines = sorted(int(w.split(":")[0]) for w in wrong)
    # a() and f() make nothing whole, c() makes whole a name it kept first,
    # i() hands a JSON answer to what makes only text whole, and j() and k()
    # each keep one parse as it came, a request's post_data_json and json's
    # own loads under another name.
    assert lines == [4, 8, 15, 21, 23, 27], wrong
