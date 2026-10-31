"""Every way a document's bytes come in goes through a limit.

An audit of 0.53.0 found that a document could be any size and take any
time. capture.fetch_pdf read an answer's whole body, receipt_pdf.open_zip
unpacked whatever an archive held, and validate_pdf and pdf_text let pypdf
read a PDF for as long as it liked in the app's own process. The fix put
the limits in paperpull_core.intake and the reading of PDFs in
paperpull_core.pdf_reader, and this reads every file that ships, the
apps' own included and the tests apart, so that no way in skips them.

A way in is any of these, and each is allowed in the one place that holds
its limit and nowhere else.

    an answer's body          resp.body()                   intake.body
    base64 handed back        base64.b64decode()            intake.decode
    a download's file         download.save_as(), .path()   intake.save_download_as,
                                                            intake.read_file
    a download waited for     .failure(), .delete(), and    intake.failure,
                              expect_download with no       intake.discard, and a
                              timeout                       timeout given
    a body read in the page   arrayBuffer(), blob(), ...    intake.reading, ppRead, ppBlob
    a printed page            "Page.printToPDF"             receipt_pdf.printed_pdf
    a PDF read                PdfReader, extract_text       pdf_reader
    an archive opened         zipfile.ZipFile               receipt_pdf.open_zip
    packed bytes unpacked     zlib.decompress, ...          intake.inflate

A download's own file, a copy of it, why it failed and deleting it each
wait in Playwright until it has finished, for as long as the provider
sends, so intake asks for them only once intake.finish has waited its
limit (test_intake_waits_for_a_download_only_through_finish). A listener
that hears a download never waits for it, since every listener after it on
the same event would wait with it (test_no_download_listener_waits_for_its_download).

A snippet that reads a body in the page (ppRead, ppBlob) is run
through intake.evaluate, which puts the reader in front of it with the
limit of the moment and says a refusal in words. Each such snippet is
compiled in a real browser with the reader in front, since a test of the
Python around it proves nothing of the JavaScript.

A use that is not a document is named below with the reason.

An answer read whole as text or JSON is a listing far more often than a
document, and is not held to DOCUMENT_BYTES unless it carries one. Each
place one is read is named in ANSWERS below, with what bounds it, so a new
one is looked at before it ships. One the app asked for itself through the
session is read through intake.text_of or intake.json_of, and a document
carried in text or JSON read in the page, a page an app prints or letters
it renders, through ppText or ppJson.
"""
import ast
import functools
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

ROOTS = ("apps", "core", "gui", "server", "tools", "packaging")
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}

INTAKE = "core/paperpull_core/intake.py"
READER = "core/paperpull_core/pdf_reader.py"
RECEIPT_PDF = "core/paperpull_core/receipt_pdf.py"
DELIVERY = "core/paperpull_core/delivery.py"

# Where each kind of way in is allowed, the one place holding its limit.
HOME = {
    "body": {INTAKE},
    "decode": {INTAKE},
    "save_as": {INTAKE},
    "download_path": {INTAKE},
    "download_wait": {INTAKE},
    "page_read": {INTAKE},
    "print": {RECEIPT_PDF},
    "pdf": {READER},
    "zip": {RECEIPT_PDF},
    "inflate": {INTAKE},
}

# Uses that are not a document coming in, or that hold the limit another
# way, with the reason. Keyed by the file, the function the use is in (""
# for the module) and the kind.
NOT_A_DOCUMENT = {
    ("apps/lowes/lowes_site.py", "details_id", "decode"):
        "an order's id in a link, at most 80 characters, checked to be base64",
    ("apps/lowes/lowes_site.py", "pair_cards", "decode"):
        "an order's id in a link, at most 80 characters, checked to be base64",
    ("apps/meijer/meijer_site.py", "press_row_receipt", "download_path"):
        "asked for only once intake.finish says the download finished, canceled after "
        "twenty seconds, the file then read through intake.read_file "
        "(test_a_download_file_asked_for_outside_intake_waits_through_finish_first)",
    ("apps/spectrum/spectrum_site.py", "decode_statement_id", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/spectrum/spectrum_site.py", "pair", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/spectrum/spectrum_site.py", "private_words_of", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/uber/uber_site.py", "token_time", "decode"):
        "a list's page token, which holds a time, not a document",
    ("core/paperpull_core/receipt_pdf.py", "printed_pdf", "decode"):
        "a piece of a printed page, asked for a megabyte at a time and counted "
        "against the limit as it comes",
    ("core/paperpull_core/testkit.py", "sample_pdf", "pdf"):
        "a stand-in PDF a test writes, never one read in",
    ("gui/app.py", "_history_upload", "decode"):
        "a history export sent to the panel, held to HISTORY_MAX_BYTES as it "
        "streams in and read under tools/migrate.py's own limits",
    ("gui/app.py", "api_aside_download", "zip"):
        "a ZIP of Manual Review the panel writes for a download, nothing read in",
    ("packaging/build_windows.py", "zip_it", "zip"):
        "the release's own ZIP, written when a release is built",
    ("server/selftest.py", "browser_checks", "decode"):
        "the server's self test printing a blank page of its own, never a provider's",
    ("server/selftest.py", "browser_checks", "print"):
        "the server's self test printing a blank page of its own, never a provider's",
    ("tools/migrate.py", "read", "zip"):
        "a history export, read under the module's own MAX_ limits",
    ("tools/migrate.py", "build", "zip"):
        "a history export being written, nothing read in",
}

# A body read whole inside a page, in a snippet's own text.
PAGE_READS = re.compile(r"\.arrayBuffer\(|\.blob\(\)|getReader\(|readAsDataURL|readAsArrayBuffer|"
                        r"readAsBinaryString|\.bytes\(\)")
DECODERS = {"b64decode", "urlsafe_b64decode", "standard_b64decode", "decodebytes",
            "a2b_base64"}
PDF_NAMES = {"PdfReader", "PdfWriter", "PdfFileReader", "PdfMerger", "PdfDocument"}
UNPACKERS = {"zlib", "_zlib", "gzip", "bz2", "lzma", "brotli", "zstd"}
READERS = re.compile(r"\bpp(?:Read|Blob|Text|Json)\(")
# A snippet that fetches and hands bytes back to Python as base64, which
# has to have read them with ppRead or ppBlob.
HANDS_BACK = re.compile(r"\bbtoa\(|\bb64\s*[:=]")
# Playwright calls that wait for a download to begin, with the event's name
# where they take one.
DOWNLOAD_STARTS = {"expect_download": None, "expect_event": "download",
                   "wait_for_event": "download"}
# Download's calls that wait until it has finished, besides path() and
# save_as(), which are counted above.
WAITS_FOR_FINISH = {"failure", "delete"}


def _starts_a_download_wait(node: ast.Call, name: str, constants=None) -> bool:
    """Whether a call waits for a download to begin, with no time given. A
    timeout named by a module constant is read as that constant."""
    if name not in DOWNLOAD_STARTS:
        return False
    event = DOWNLOAD_STARTS[name]
    if event is not None:
        first = node.args[0] if node.args else next(
            (k.value for k in node.keywords if k.arg == "event"), None)
        if not (isinstance(first, ast.Constant) and first.value == event):
            return False
    given = next((k.value for k in node.keywords if k.arg == "timeout"), None)
    if isinstance(given, ast.Name) and given.id in (constants or {}):
        given = ast.Constant(constants[given.id])
    # No timeout, or one of 0, which Playwright takes as none.
    return given is None or (isinstance(given, ast.Constant) and not given.value)


def is_test(path: Path) -> bool:
    parts = path.relative_to(REPO).parts
    return ("tests" in parts or path.name.startswith("test_")
            or path.name == "conftest.py" or ".venv" in parts
            or any(p.startswith(".") for p in parts))


def sources():
    """Every Python file that ships, tests and copies a build made apart."""
    out = sorted(REPO.glob("*.py"))
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            dirs[:] = [d for d in dirs if d not in MADE_FOLDERS and not d.startswith(".")
                       and d != "__pycache__"]
            out.extend(Path(folder) / f for f in files if f.endswith(".py"))
    return [p for p in out if not is_test(p)]


@functools.lru_cache(maxsize=None)
def _parsed(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    owner = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            owner[child] = name
            inner = child.name if isinstance(child, (ast.FunctionDef,
                                                     ast.AsyncFunctionDef)) else name
            walk(child, inner)
    walk(tree, "")
    return tree, owner


def _strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, node.value


def ways_in(path: Path, root: Path = REPO):
    """The file's path from `root`, and (kind, line, function, what) for
    every way in it holds outside that kind's home."""
    rel = path.relative_to(root).as_posix()
    tree, owner = _parsed(path)
    found = []
    # Module constants a download wait's timeout may name.
    constants = {n.targets[0].id: n.value.value for n in tree.body
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
    for node in ast.walk(tree):
        fn = owner.get(node, "")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            bare = not node.args and not node.keywords
            if name == "body" and isinstance(f, ast.Attribute) and bare:
                found.append(("body", node.lineno, fn, "an answer's body read whole"))
            elif name in DECODERS:
                found.append(("decode", node.lineno, fn, "base64 decoded"))
            elif name == "save_as" and isinstance(f, ast.Attribute):
                found.append(("save_as", node.lineno, fn, "a download copied"))
            elif name == "path" and isinstance(f, ast.Attribute) and bare:
                found.append(("download_path", node.lineno, fn, "a download's own file"))
            elif name in WAITS_FOR_FINISH and isinstance(f, ast.Attribute) and bare:
                found.append(("download_wait", node.lineno, fn,
                              "a download waited for until it finishes"))
            elif isinstance(f, ast.Attribute) and _starts_a_download_wait(node, name, constants):
                found.append(("download_wait", node.lineno, fn,
                              "a download's start waited for with no time given"))
            elif name in ("extract_text", "open") and isinstance(f, ast.Attribute) \
                    and (name == "extract_text" or getattr(f.value, "id", "") == "pdfplumber"):
                found.append(("pdf", node.lineno, fn, "a PDF's text read"))
            elif name == "ZipFile":
                found.append(("zip", node.lineno, fn, "an archive opened"))
            elif name in ("decompress", "decompressobj") and isinstance(f, ast.Attribute) \
                    and getattr(f.value, "id", "") in UNPACKERS:
                found.append(("inflate", node.lineno, fn, "packed bytes unpacked"))
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in PDF_NAMES:
                found.append(("pdf", node.lineno, fn, "pypdf used directly"))
        if isinstance(node, ast.alias) and node.name.split(".")[-1] in PDF_NAMES:
            found.append(("pdf", getattr(node, "lineno", 0), fn, "pypdf imported directly"))
    for node, text in _strings(tree):
        fn = owner.get(node, "")
        if PAGE_READS.search(text):
            found.append(("page_read", node.lineno, fn, "a body read whole in the page"))
        elif HANDS_BACK.search(text) and "fetch(" in text and not READERS.search(text):
            found.append(("page_read", node.lineno, fn, "bytes fetched in the page and "
                          "handed back unread by ppRead"))
        if text.strip() == "Page.printToPDF":
            found.append(("print", node.lineno, fn, "a page printed whole"))
    return rel, [w for w in found if rel not in HOME[w[0]]]


def unlimited(paths=None, root: Path = REPO):
    out = []
    for path in paths if paths is not None else sources():
        rel, found = ways_in(path, root)
        for kind, line, fn, what in found:
            if (rel, fn, kind) in NOT_A_DOCUMENT:
                continue
            out.append("%s:%d %s (%s, in %s)" % (rel, line, what, kind, fn or "the module"))
    return sorted(set(out))


def test_every_way_a_document_comes_in_goes_through_its_limit():
    left = unlimited()
    assert not left, "a way in with no limit:\n" + "\n".join(left)


# -- a snippet that reads a body is run through intake.evaluate ----------------

def _reader_names(tree):
    """Names bound to a snippet that calls ppRead or ppBlob."""
    names = set()
    for node in ast.walk(tree):
        # Built of strings, never a call that was handed one.
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Constant, ast.BinOp,
                                                                    ast.JoinedStr)):
            text = "".join(c.value for c in ast.walk(node.value)
                           if isinstance(c, ast.Constant) and isinstance(c.value, str))
            if READERS.search(text):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _is_intake_evaluate(func) -> bool:
    if isinstance(func, ast.Attribute) and func.attr == "evaluate":
        return getattr(func.value, "id", "") in ("intake", "_intake")
    return False


def snippets_run_without_the_reader(paths=None, root: Path = REPO):
    out = []
    for path in paths if paths is not None else sources():
        rel = path.relative_to(root).as_posix()
        if rel == INTAKE:
            continue
        tree, _ = _parsed(path)
        names = _reader_names(tree)
        inline = [n for n, text in _strings(tree) if READERS.search(text)]
        if not names and not inline:
            continue
        handed = {id(a) for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and _is_intake_evaluate(node.func) for a in node.args[1:2]}
        assigned = {id(t) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    for t in node.targets}
        # A piece of a snippet built by joining strings belongs to the name
        # it is assigned to, and that name is what is checked.
        pieces = {id(c) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  for c in ast.walk(node.value)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names and id(node) not in assigned \
                    and id(node) not in handed:
                out.append("%s:%d %s is used other than through intake.evaluate"
                           % (rel, node.lineno, node.id))
        for node in inline:
            if id(node) not in handed and id(node) not in pieces:
                out.append("%s:%d a snippet that reads a body is not run through "
                           "intake.evaluate" % (rel, node.lineno))
    return sorted(out)


def test_every_snippet_that_reads_a_body_runs_through_intake_evaluate():
    left = snippets_run_without_the_reader()
    assert not left, "\n".join(left)


SAMPLE = (
    "import base64, zipfile\n"
    "NEVER = 0\n"
    "from pypdf import PdfReader\n"
    "JS = 'async (u) => { const r = await fetch(u); return await r.arrayBuffer(); }'\n"
    "B64 = 'async (u) => { const r = await fetch(u); return {b64: btoa(await r.text())}; }'\n"
    "READ = 'async (u) => { const r = await fetch(u); return await ppRead(r); }'\n"
    "def take(page, resp, dl, path):\n"
    "    resp.body()\n"
    "    dl.failure()\n"
    "    with page.expect_download() as info:\n"
    "        pass\n"
    "    page.wait_for_event('download', timeout=0)\n"
    "    page.expect_download(timeout=NEVER)\n"
    "    base64.b64decode('')\n"
    "    dl.save_as(path)\n"
    "    open(dl.path(), 'rb').read()\n"
    "    PdfReader(path).pages[0].extract_text()\n"
    "    zipfile.ZipFile(path)\n"
    "    page.context.new_cdp_session(page).send('Page.printToPDF', {})\n"
    "    page.evaluate(READ, 'x')\n"
    "    import zlib\n"
    "    zlib.decompress(b'')\n")


def test_the_census_finds_what_it_looks_for(tmp_path):
    """Not passing on nothing. Each kind of way in is found in a made-up
    app, which is written to a folder of the test's own and never into the
    checkout, and a snippet handed straight to the page is found too."""
    sample = tmp_path / "apps" / "sample" / "sample_site.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(SAMPLE, encoding="utf-8")
    _, found = ways_in(sample, tmp_path)
    kinds = {k for k, *_ in found}
    assert kinds == set(HOME), kinds
    assert len([w for w in found if w[0] == "page_read"]) == 2, found
    assert len([w for w in found if w[0] == "download_wait"]) == 4, found
    assert any("sample_site.py" in line
               for line in snippets_run_without_the_reader([sample], tmp_path))
    good = sample.with_name("good_site.py")
    good.write_text("from paperpull_core import intake\n"
                    "READ = 'async (u) => { const r = await fetch(u); return await ppRead(r); }'\n"
                    "def take(page, out):\n"
                    "    with page.expect_download(timeout=20000) as info:\n"
                    "        page.expect_event('popup')\n"
                    "    intake.save_download_as(info.value, out)\n"
                    "    intake.failure(info.value, page)\n"
                    "    return intake.evaluate(page, READ, 'x')\n", encoding="utf-8")
    assert snippets_run_without_the_reader([good], tmp_path) == []
    assert unlimited([good], tmp_path) == []


def test_intake_waits_for_a_download_only_through_finish():
    """intake is the one place a download is waited for, and every wait there
    is held to DOWNLOAD_SECONDS by finish() first, but for the fiber finish
    starts, which waits with nothing held up behind it."""
    tree, owner = _parsed(REPO / INTAKE)
    waits: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("path", "save_as", "failure", "delete"):
            waits.setdefault(owner.get(node, ""), []).append(node.lineno)
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "wait" in {n.name for n in ast.walk(functions["_follow"])
                      if isinstance(n, ast.FunctionDef)}, "the fiber moved"
    unheld = []
    for fn, lines in sorted(waits.items()):
        if fn == "wait":
            continue
        called = {c.func.id for c in ast.walk(functions[fn])
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        if "finish" not in called:
            unheld.append("%s at line %s" % (fn, lines))
    assert not unheld, "a download waited for without finish():\n" + "\n".join(unheld)
    assert set(waits) == {"wait", "save_download_as", "failure", "discard"}, waits


def _is_intake_finish(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
        and node.func.attr == "finish" and getattr(node.func.value, "id", "") == "intake"


def _asked_before_finish(fn) -> list:
    """Lines where a function asks for a download's own file other than in
    the body of an `if intake.finish(...)` on that same download, where it
    has finished."""
    parents = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    loose = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "path" and not node.args and not node.keywords):
            continue
        which = ast.unparse(node.func.value)
        child, up = node, parents.get(node)
        while up is not None and not (isinstance(up, ast.If) and _is_intake_finish(up.test)
                                      and up.test.args and ast.unparse(up.test.args[0]) == which
                                      and child in up.body):
            child, up = up, parents.get(up)
        if up is None:
            loose.append(node.lineno)
    return loose


def test_a_download_file_asked_for_outside_intake_waits_through_finish_first():
    """A download's own file named above with a reason, outside intake, is
    asked for only once intake.finish says the download finished, so it is
    never waited for longer than finish allows. Meijer's is."""
    loose = []
    for rel, fn, kind in NOT_A_DOCUMENT:
        if kind != "download_path":
            continue
        tree, _ = _parsed(REPO / rel)
        found = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn]
        assert found, "%s has no %s" % (rel, fn)
        for node in found:
            loose.extend("%s:%d in %s" % (rel, line, fn) for line in _asked_before_finish(node))
    assert not loose, "a download's file asked for before intake.finish:\n" + "\n".join(loose)


def test_the_finish_first_check_finds_a_file_asked_for_too_soon():
    soon = ast.parse("def take(dl, page):\n"
                     "    dl.path()\n"
                     "    if not intake.finish(dl, page):\n"
                     "        dl.path()\n"
                     "    if intake.finish(dl, page):\n"
                     "        pass\n"
                     "    else:\n"
                     "        dl.path()\n"
                     "    if intake.finish(other, page):\n"
                     "        dl.path()\n").body[0]
    assert _asked_before_finish(soon) == [2, 4, 8, 10]
    held = ast.parse("def take(downloads, page):\n"
                     "    if intake.finish(downloads[0], page, seconds=20):\n"
                     "        try:\n"
                     "            saved = downloads[0].path()\n"
                     "        except Exception:\n"
                     "            saved = None\n").body[0]
    assert _asked_before_finish(held) == []


# -- a listener that hears a download ---------------------------------------------
#
# Playwright's sync API runs every listener of one event in a single fiber,
# one after another. A listener that waited there for its download to finish
# held every listener after it for as long, pressing.press_once's ear for
# what a press brought among them. Delivery's listener did, and Meijer's did
# until both followed the download through intake.follow instead.

# Calls that wait, for a download to finish, for something on a page or for
# time to pass. Canceling does not, and intake.discard cancels first, so the
# delete after it is at once (only where canceling raised, with the browser
# gone, does it wait as finish allows).
LISTENER_WAITS = {"path", "save_as", "failure", "delete", "finish", "waits_for",
                  "save_download_as", "take_download", "save_download",
                  "wait_for", "wait_for_timeout", "wait_for_event", "wait_for_load_state",
                  "wait_for_selector", "wait_for_function", "wait_for_url",
                  "expect_download", "expect_event", "expect_popup", "expect_page",
                  "expect_navigation", "expect_request", "expect_response",
                  "goto", "reload", "sleep"}


def _is_download(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "download"


def _download_listeners(tree) -> list:
    """Every listener handed to on("download") or once("download"), or
    following "download" in a tuple listed among others, the way a loop over
    events hands them out."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("on", "once") and len(node.args) >= 2 \
                and _is_download(node.args[0]):
            out.append(node.args[1])
        elif isinstance(node, (ast.Tuple, ast.List)):
            for listed in node.elts:
                if isinstance(listed, ast.Tuple):
                    out.extend(b for a, b in zip(listed.elts, listed.elts[1:]) if _is_download(a))
    return out


def listeners_that_wait(paths=None, root: Path = REPO):
    """Each wait inside a download listener, and each listener this cannot
    read. A helper of the module's own that the listener calls, by its name
    or as self's, is read as part of the listener."""
    out = []
    for path in paths if paths is not None else sources():
        rel = path.relative_to(root).as_posix()
        tree, _ = _parsed(path)
        defs: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
        for handler in _download_listeners(tree):
            if isinstance(handler, ast.Lambda):
                todo = [handler]
            else:
                name = handler.attr if isinstance(handler, ast.Attribute) \
                    else getattr(handler, "id", "")
                todo = list(defs.get(name, []))
                if not todo:
                    out.append("%s:%d a download listener this cannot read (%s)"
                               % (rel, handler.lineno, ast.unparse(handler)))
            read = set()
            while todo:
                body = todo.pop()
                if id(body) in read:
                    continue
                read.add(id(body))
                for call in ast.walk(body):
                    if not isinstance(call, ast.Call):
                        continue
                    f = call.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                    if name in LISTENER_WAITS:
                        out.append("%s:%d %s() inside a download listener" % (rel, call.lineno, name))
                    if isinstance(f, ast.Name) or (isinstance(f, ast.Attribute)
                                                   and getattr(f.value, "id", "") == "self"):
                        todo.extend(defs.get(name, []))
    return sorted(set(out))


def test_no_download_listener_waits_for_its_download():
    left = listeners_that_wait()
    assert not left, ("a download listener that waits holds every listener after it:\n"
                      + "\n".join(left))


LISTENING = (
    "import time\n"
    "from paperpull_core import intake\n"
    "def keep(dl):\n"
    "    return dl.path()\n"
    "class Watch:\n"
    "    def _on_download(self, dl):\n"
    "        self._save(dl)\n"
    "    def _save(self, dl):\n"
    "        intake.save_download_as(dl, 'x')\n"
    "    def arm(self, page):\n"
    "        page.on('download', self._on_download)\n"
    "def press(page, popup, handed):\n"
    "    page.on('download', keep)\n"
    "    page.once('download', lambda d: d.failure())\n"
    "    def on_download(d):\n"
    "        time.sleep(1)\n"
    "    for event, fn in (('download', on_download), ('popup', keep)):\n"
    "        popup.on(event, fn)\n"
    "    page.on('download', handed)\n")


def test_the_listener_census_finds_a_listener_that_waits(tmp_path):
    sample = tmp_path / "apps" / "sample" / "sample_site.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(LISTENING, encoding="utf-8")
    found = listeners_that_wait([sample], tmp_path)
    assert found == ["apps/sample/sample_site.py:14 failure() inside a download listener",
                     "apps/sample/sample_site.py:16 sleep() inside a download listener",
                     "apps/sample/sample_site.py:19 a download listener this cannot read (handed)",
                     "apps/sample/sample_site.py:4 path() inside a download listener",
                     "apps/sample/sample_site.py:9 save_download_as() inside a download listener"], \
        found
    good = sample.with_name("good_site.py")
    good.write_text("from paperpull_core import intake\n"
                    "def press(page, popup):\n"
                    "    heard = []\n"
                    "    def on_download(d):\n"
                    "        heard.append(d)\n"
                    "        intake.follow(d)\n"
                    "    page.on('download', on_download)\n"
                    "    page.on('download', lambda d: intake.discard(d))\n"
                    "    for event, fn in (('download', on_download), ('popup', on_download)):\n"
                    "        popup.on(event, fn)\n"
                    "    if intake.finish(heard[0], page):\n"
                    "        return heard[0].path()\n", encoding="utf-8")
    assert listeners_that_wait([good], tmp_path) == []


def test_every_reason_still_names_a_use_that_is_there():
    """A reason whose use has gone stays here as a hole a new use could slip
    through, so it goes too."""
    seen = set()
    for path in sources():
        rel, found = ways_in(path)
        seen.update((rel, fn, kind) for kind, _, fn, _ in found)
    gone = sorted("%s %s %s" % k for k in NOT_A_DOCUMENT if k not in seen)
    assert not gone, "named with a reason and not there any more:\n" + "\n".join(gone)


# -- an answer read whole as text or JSON ---------------------------------------
#
# What bounds each kind, measured where it says so.

PAGE_ANSWER = ("a listing in a page's own answer heard on the network, whose body Chromium "
               "keeps only up to about 10 MB, so a larger one raises rather than comes "
               "(test_a_page_answer_larger_than_chromium_keeps_never_comes)")
PAGE_ANSWER_PDF = ("a page's own answer heard on the network, held by Chromium as a listing's "
                   "is, which can carry a PDF in base64, decoded through intake.decode")
IN_PAGE = ("a listing read whole inside the page, held there by the tab's own memory and by "
           "V8's longest string, about 512 million characters, never a document")
IN_PAGE_BESIDE = ("an answer beside the document in a snippet that reads the document through "
                  "ppRead, a listing, a token or an error's words, never the document")
PANEL = "the panel's own page asking the panel, never a provider's answer"

ANSWERS = {
    ("apps/adp/adp_site.py", "on_response"): PAGE_ANSWER,
    ("apps/affirm/affirm_site.py", "on_response"): PAGE_ANSWER,
    ("apps/ally/ally_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/alpaca/alpaca_site.py", "read_list"): PAGE_ANSWER,
    ("apps/alpaca/alpaca_site.py", "_link_of"): PAGE_ANSWER,
    ("apps/amfam/amfam_site.py", "on_response"): PAGE_ANSWER,
    ("apps/applecard/applecard_site.py", "on_response"): PAGE_ANSWER,
    ("apps/att/att_site.py", "on_response"): PAGE_ANSWER,
    ("apps/chase/chase_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/chasebusiness/chasebusiness_site.py", "read_answer"): PAGE_ANSWER,
    ("apps/coinbase/coinbase_site.py", "on_response"): PAGE_ANSWER,
    ("apps/discovercard/discovercard_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/etrade/etrade_site.py", "on_response"): PAGE_ANSWER_PDF,
    ("apps/fairfaxwater/fairfaxwater_site.py", "on_response"): PAGE_ANSWER,
    ("apps/fedex/fedex_site.py", "on_response"): PAGE_ANSWER,
    ("apps/fidelity/fidelity_site.py", "on_response"): PAGE_ANSWER,
    ("apps/golden1/golden1_site.py", "on_response"): PAGE_ANSWER,
    ("apps/invest529/invest529_site.py", "on_response"): PAGE_ANSWER,
    ("apps/meijer/meijer_site.py", "on_response"): PAGE_ANSWER,
    ("apps/nelnet/nelnet_site.py", "on_response"): PAGE_ANSWER,
    ("apps/netbenefits/netbenefits_site.py", "on_response"): PAGE_ANSWER,
    ("apps/newrez/newrez_site.py", "on_response"): PAGE_ANSWER,
    ("apps/paypal/paypal_site.py", "_answered"): PAGE_ANSWER,
    ("apps/pge/pge_site.py", "_pdf_in_aura"): PAGE_ANSWER_PDF,
    ("apps/robinhood/robinhood_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/robinhood/robinhood_site.py", "_click_and_capture"): PAGE_ANSWER,
    ("apps/sba/sba_site.py", "on_response"): PAGE_ANSWER,
    ("apps/smud/smud_site.py", "on_response"): PAGE_ANSWER,
    ("apps/spectrum/spectrum_site.py", "check_session"): PAGE_ANSWER,
    ("apps/spectrum/spectrum_site.py", "answer_of"): PAGE_ANSWER_PDF,
    ("apps/spectrum/spectrum_site.py", "_fault"): PAGE_ANSWER,
    ("apps/statefarm/statefarm_site.py", "on_response"): PAGE_ANSWER,
    ("apps/stripe/stripe_site.py", "on_response"): PAGE_ANSWER,
    ("apps/tsp/tsp_site.py", "on_response"): PAGE_ANSWER,
    ("apps/ups/ups_site.py", "on_response"): PAGE_ANSWER,
    ("apps/usaa/usaa_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/usbank/usbank_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/vanguard/vanguard_site.py", "on_resp"): PAGE_ANSWER,
    ("apps/venmo/venmo_site.py", "_read_pending"): PAGE_ANSWER,
    ("apps/wellsfargo/wellsfargo_site.py", "on_response"): PAGE_ANSWER,
    ("core/paperpull_core/api_census.py", "_record"): PAGE_ANSWER,
    ("core/paperpull_core/recorder.py", "_on_response"): PAGE_ANSWER,
    ("gui/app.py", "*"): PANEL,
    # Read inside the page, by the snippet's name or the function holding it.
    ("apps/adp/adp_site.py", "_FETCH_JSON_JS"): IN_PAGE,
    ("apps/affirm/affirm_site.py", "_GET_JS"): IN_PAGE,
    ("apps/anthem/anthem_site.py", "_SUMMARY_JS"): IN_PAGE,
    ("apps/anthem/anthem_site.py", "_MEMBER_DOCS_LIST_JS"): IN_PAGE,
    ("apps/anthem/anthem_site.py", "_IDCARD_LIST_JS"): IN_PAGE,
    ("apps/anthem/anthem_site.py", "_MEMBER_DOC_DOWNLOAD_JS"): IN_PAGE_BESIDE,
    ("apps/anthem/anthem_site.py", "_IDCARD_VIEW_JS"): IN_PAGE_BESIDE,
    ("apps/bestbuy/bestbuy_site.py", "_FETCH_JS"): IN_PAGE,
    ("apps/capitalone/capitalone_site.py", "_JSON_FETCH_JS"): IN_PAGE,
    ("apps/capitalone/capitalone_site.py", "_BYTES_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/citi/citi_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/ezpassva/ezpassva_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/homedepot/homedepot_site.py", "_FETCH_HISTORY_JS"): IN_PAGE,
    ("apps/kroger/kroger_site.py", "_FETCH_HISTORY_JS"): IN_PAGE,
    ("apps/myecp/myecp_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/mypay/mypay_site.py", "_HISTORY_JS"): IN_PAGE,
    ("apps/netbenefits/netbenefits_site.py", "_PROBE_JS"): IN_PAGE,
    ("apps/netbenefits/netbenefits_site.py", "_SIGNED_IN_JS"): IN_PAGE,
    ("apps/paypal/paypal_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/schwab/schwab_site.py", "_get_token"): IN_PAGE,
    ("apps/schwab/schwab_site.py", "_gateway_json"): IN_PAGE,
    ("apps/statefarm/statefarm_site.py", "_FETCH_JSON"): IN_PAGE,
    ("apps/stripe/stripe_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
    ("apps/uber/uber_site.py", "_POST_JS"): (
        "a listing read whole inside the page. A receipt's answer carries its HTML too, of "
        "which only the receipt's id and time are read, and the receipt saved is the PDF "
        "Uber makes, read through ppRead"),
    ("apps/ups/ups_site.py", "_FETCH_JS"): IN_PAGE_BESIDE,
}

# A read of a fetched answer's text or JSON inside a snippet.
SNIPPET_READS = re.compile(r"\.(?:json|text)\(\)|\bresponseText\b")
# What makes a string a snippet run in the page.
IS_SNIPPET = re.compile(r"=>|\bfunction\s*\(|\bawait\s")


def answers_read_whole(paths=None, root: Path = REPO):
    """(file, name, line) of every answer read whole as text or JSON, in
    Python a bare .json() or .text() named by the function holding it, and
    in a snippet named by the module's name for it or the function holding
    it."""
    out = []
    for path in paths if paths is not None else sources():
        rel = path.relative_to(root).as_posix()
        tree, owner = _parsed(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("json", "text") and not node.args \
                    and not node.keywords:
                out.append((rel, owner.get(node, ""), node.lineno))
        # A module's snippet is looked at whole, its pieces joined the way
        # the module joins them, so a piece holding the read and nothing
        # that looks like code is not missed.
        named, whole = {}, _module_strings(tree, rel)
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                for piece in ast.walk(node.value):
                    named[id(piece)] = node.targets[0].id
                text = whole.get(node.targets[0].id)
                if text and SNIPPET_READS.search(text) and IS_SNIPPET.search(text):
                    out.append((rel, node.targets[0].id, node.lineno))
        for node, text in _strings(tree):
            if id(node) not in named and SNIPPET_READS.search(text) and IS_SNIPPET.search(text):
                out.append((rel, owner.get(node, ""), node.lineno))
    return out


def _module_strings(tree, rel: str) -> dict:
    """Every module-level name bound to a string, its pieces joined."""
    strings: dict = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 \
                or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            value = eval(compile(ast.Expression(node.value), rel, "eval"),
                         {"__builtins__": {}}, dict(strings))
        except Exception:
            continue
        if isinstance(value, str):
            strings[node.targets[0].id] = value
    return strings


def unnamed_answers(paths=None, root: Path = REPO):
    return sorted("%s:%d %s" % (rel, line, name or "the module")
                  for rel, name, line in answers_read_whole(paths, root)
                  if (rel, name) not in ANSWERS and (rel, "*") not in ANSWERS)


def test_every_answer_read_whole_is_named_with_what_bounds_it():
    left = unnamed_answers()
    assert not left, ("an answer read whole as text or JSON, not named in ANSWERS. A listing "
                      "is named there with what bounds it. One asked through the session is "
                      "read through intake.json_of or intake.text_of, and a document read "
                      "in the page through ppText or ppJson:\n" + "\n".join(left))


def test_every_answer_named_is_still_read_there():
    seen = {(rel, name) for rel, name, _ in answers_read_whole()}
    seen |= {(rel, "*") for rel, _, _ in answers_read_whole()}
    gone = sorted("%s %s" % k for k in ANSWERS if k not in seen)
    assert not gone, "named in ANSWERS and not read there any more:\n" + "\n".join(gone)


def test_the_answers_census_finds_what_it_looks_for(tmp_path):
    sample = tmp_path / "apps" / "sample" / "sample_site.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(
        "LIST = 'async (u) => { const r = await fetch(u); return await r.json(); }'\n"
        "DOC = 'async (u) => { const r = await fetch(u); return await ppText(r); }'\n"
        "def read(resp, page):\n"
        "    resp.text()\n"
        "    page.evaluate('async () => (await fetch(\"/x\")).json()')\n"
        "JOINED = ('async (u) => { const r = await fetch(u); '\n"
        "          'return r.json(); }')\n"
        "OLD = 'function (u) { var x = new XMLHttpRequest(); return x.responseText; }'\n",
        encoding="utf-8")
    assert unnamed_answers([sample], tmp_path) == [
        "apps/sample/sample_site.py:1 LIST", "apps/sample/sample_site.py:4 read",
        "apps/sample/sample_site.py:5 read", "apps/sample/sample_site.py:6 JOINED",
        "apps/sample/sample_site.py:8 OLD"]


# -- every bounded snippet compiles in a real browser ---------------------------

def bounded_snippets():
    """(file, name, source) of every module-level snippet that reads a body
    through ppRead or ppBlob, its pieces joined the way the module joins
    them, from the source and without importing the app."""
    out = []
    for path in sources():
        rel = path.relative_to(REPO).as_posix()
        if rel == INTAKE:
            continue
        tree, _ = _parsed(path)
        strings: dict = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 \
                    or not isinstance(node.targets[0], ast.Name):
                continue
            try:
                value = eval(compile(ast.Expression(node.value), rel, "eval"),
                             {"__builtins__": {}}, dict(strings))
            except Exception:
                continue
            if isinstance(value, str):
                strings[node.targets[0].id] = value
                if READERS.search(value):
                    out.append((rel, node.targets[0].id, value))
        named = {value for where, _, value in out if where == rel}
        for node, text in _strings(tree):
            # A whole snippet written where it is run, not one bound to a name.
            if READERS.search(text) and text.lstrip().startswith("async") and text not in named:
                out.append((rel, "line %d" % node.lineno, text))
    return out


def test_the_census_compiles_every_snippet_it_should():
    found = {(rel, name) for rel, name, _ in bounded_snippets()}
    for expected in (("core/paperpull_core/capture.py", "FETCH_AS_B64"),
                     ("core/paperpull_core/blob_capture.py", "TAKE_JS"),
                     ("apps/mypay/mypay_site.py", "_PDF_JS"),
                     ("apps/usaa/usaa_site.py", "_BLOB_FETCH_JS")):
        assert expected in found, expected
    assert len(found) >= 30, len(found)


def test_every_bounded_snippet_compiles_in_a_browser():
    from paperpull_core import intake
    sync_playwright = pytest.importorskip("playwright.sync_api",
                                          reason="needs a browser").sync_playwright
    snippets = bounded_snippets()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-extensions", "--disable-sync",
                                          "--no-first-run"])
        try:
            page = browser.new_page()
            broken = page.evaluate("""(all) => all.map(([where, src]) => {
                try {
                    const f = (0, eval)('(' + src + ')');
                    return typeof f === 'function' ? '' : where + ' is not a function';
                } catch (e) { return where + ': ' + String(e); }
            }).filter(Boolean)""", [["%s %s" % (rel, name), intake.reading(src)]
                                    for rel, name, src in snippets])
        finally:
            browser.close()
    assert not broken, "\n".join(broken)
