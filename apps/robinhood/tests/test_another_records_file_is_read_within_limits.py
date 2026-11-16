"""Another record's file is read within a document's limit, and never one
that is not a plain file.

A statement of an account page is compared with the saved statements of
the other accounts of its date, and a record saved before digests were kept
is compared by its file's own bytes. _sha256 read that file whole into
memory. One larger than free memory raised MemoryError, which its except
OSError did not catch, so the new statement was recorded Failed and every
later run fetched it and failed again (the bug hunt of 2026-11-14, finding
6, MemoryError at robinhood_docs.py:270 on a sparse file of 1 TiB). A
download is never larger than intake.DOCUMENT_BYTES, so a file larger than
that cannot hold the same bytes and is never read.

A saved tax form is read for the year it prints, and a record naming a
named pipe held that read for good (finding 4). It is answered now as a
file that prints no year.

Reading a file past free memory is stood in for by reads that raise
MemoryError, and its size by lowering DOCUMENT_BYTES, so no test makes a
large file. A named pipe is POSIX, skipped on Windows with the reason, and
a Windows named pipe stands in for it there. Everything here is invented.
"""
import builtins
import hashlib
import importlib.util
import io
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import storage  # noqa: E402,F401  binds this provider's AppSpec
import robinhood_docs  # noqa: E402
from paperpull_core import intake  # noqa: E402
from paperpull_core import storage as core_storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402

POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"


def _harness():
    """test_speed_and_retirement.py, for _app, _take and _presses."""
    spec = importlib.util.spec_from_file_location(
        "robinhood_another_records_harness", HERE / "test_speed_and_retirement.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _harness()


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def within(seconds, fn, *args, **kwargs):
    """fn(*args, **kwargs) in a thread, failing if it is still waiting after
    `seconds`, with where it waits."""
    got = {}

    def run():
        try:
            got["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        frame = sys._current_frames().get(t.ident)
        lines = [f for f in traceback.extract_stack(frame)
                 if "paperpull_core" in f.filename or "apps" in Path(f.filename).parts]
        where = ", ".join("%s:%d %s" % (Path(f.filename).name, f.lineno, f.name)
                          for f in lines[-3:])
        raise AssertionError("still waiting after %s s, in %s" % (seconds, where))
    return got


@pytest.fixture(params=["named pipe", "Windows named pipe"])
def pipe(request, tmp_path):
    """A pipe a record could name, which no one ever writes to."""
    if request.param == "named pipe":
        if not hasattr(os, "mkfifo"):
            pytest.skip(POSIX_ONLY)
        at = tmp_path / "2025 Robinhood 1099.pdf"
        os.mkfifo(at)
        yield at
        try:
            os.close(os.open(at, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        return
    if os.name != "nt":
        pytest.skip("a Windows named pipe, which only Windows makes")
    import _winapi
    name = r"\\.\pipe\paperpull-test-%d-%s" % (os.getpid(), os.urandom(4).hex())
    handles = [_winapi.CreateNamedPipe(name, _winapi.PIPE_ACCESS_DUPLEX, 0,
                                       _winapi.PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0,
                                       _winapi.NULL) for _ in range(64)]
    yield Path(name)
    for h in handles:
        _winapi.CloseHandle(h)


class _Counted:
    """A file opened for reading whose reads are counted, or refused with
    `fail` as reading a file past free memory whole refuses."""

    def __init__(self, f, reads, fail):
        self._f, self._reads, self._fail = f, reads, fail

    def read(self, *args):
        if self._fail is not None:
            self._reads.append("refused")
            raise self._fail()
        data = self._f.read(*args)
        self._reads.append(len(data or b""))
        return data

    def readinto(self, buffer):
        if self._fail is not None:
            self._reads.append("refused")
            raise self._fail()
        n = self._f.readinto(buffer)
        self._reads.append(n or 0)
        return n

    def readall(self):
        return self.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()

    def __getattr__(self, name):
        return getattr(self._f, name)


def reads_of(monkeypatch, path: Path, fail=None) -> list:
    """Every read of `path` in this process, however it is opened, by
    open, io.open, Path.read_bytes, os.open or os.fdopen, as the bytes each
    gave. With `fail`, each read raises it instead."""
    target = os.path.normcase(os.path.abspath(path))
    reads, fds = [], set()
    real_open, real_os_open, real_read = builtins.open, os.open, os.read

    def same(file) -> bool:
        if isinstance(file, int):
            return file in fds
        try:
            return os.path.normcase(os.path.abspath(os.fspath(file))) == target
        except TypeError:
            return False

    def opened(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return _Counted(f, reads, fail) if same(file) and "r" in mode else f

    def os_opened(file, flags, *args, **kwargs):
        fd = real_os_open(file, flags, *args, **kwargs)
        if same(file):
            fds.add(fd)
        return fd

    def os_read(fd, n):
        if fd not in fds:
            return real_read(fd, n)
        if fail is not None:
            reads.append("refused")
            raise fail()
        data = real_read(fd, n)
        reads.append(len(data))
        return data

    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(io, "open", opened)
    monkeypatch.setattr(os, "open", os_opened)
    monkeypatch.setattr(os, "read", os_read)
    return reads


# -- the digest of another record's file ------------------------------------------------

def test_a_file_larger_than_a_document_is_never_read_for_its_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 4096)
    path = tmp_path / "2010-01-31 Robinhood Monthly Statement.pdf"
    data = b"%PDF-1.4\n" + b"0" * (64 * 1024)
    path.write_bytes(data)
    reads = reads_of(monkeypatch, path)
    got = robinhood_docs._sha256(path)
    assert sum(reads) <= 4097, "read %d bytes of a file a document may not be" % sum(reads)
    assert got != hashlib.sha256(data).hexdigest() and got == "", got


def test_the_digest_is_the_whole_files_read_in_blocks(tmp_path):
    path = tmp_path / "2010-01-31 Robinhood Monthly Statement.pdf"
    data = os.urandom(5 * 1024 * 1024 + 17)
    path.write_bytes(data)
    assert robinhood_docs._sha256(path) == hashlib.sha256(data).hexdigest()
    assert robinhood_docs._sha256(str(path)) == hashlib.sha256(data).hexdigest()
    assert robinhood_docs._sha256(tmp_path / "missing.pdf") == ""
    assert robinhood_docs._sha256(tmp_path) == ""


def test_a_pipe_has_no_digest_and_holds_nothing(pipe):
    assert within(5, robinhood_docs._sha256, pipe) == {"value": ""}


# -- a retirement statement taken beside an older individual one -------------------------

def _process(app, page, doc):
    """The run's own loop over one document, with its per-document handler,
    and what it wrote down."""
    app.page = lambda: page
    app.process([doc])
    return app.progress.get(doc.key) or {}


@pytest.mark.parametrize("size", ["within the limit", "past the limit"])
def test_a_huge_older_individual_file_never_fails_the_new_statement(tmp_path, monkeypatch,
                                                                    size):
    """The individual statement of the day was saved before digests were
    kept, so it is compared by its file, and its file stands in for one
    past free memory. Within the limit it is read and every read raises
    MemoryError. Past it, it is never read at all. Either way the retirement
    statement, which differs, is kept and recorded as done."""
    app = harness._app(tmp_path)
    harness._presses(monkeypatch)
    page = harness._Tab(headings={harness.RETIREMENT: ["Retirement"]})
    individual = harness._statement()
    saved = harness._take(app, page, individual)
    assert saved["downloaded_ok"]
    app.progress.update(individual.key, {"pdf_sha256": ""})
    older = Path(saved["pdf_path"])
    if size == "past the limit":
        # The statement about to be taken is about 5 KB, so a limit between
        # that and the older file's size keeps the older one out alone.
        with open(older, "ab") as f:
            f.write(b" " * 60000)
        monkeypatch.setattr(intake, "DOCUMENT_BYTES", 32 * 1024)
    reached = reads_of(monkeypatch, older, fail=MemoryError)
    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if os.path.normcase(os.path.abspath(self)) == os.path.normcase(str(older)):
            reached.append("read_bytes")
            raise MemoryError()
        return real_read_bytes(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    doc = harness._retirement()
    rec = _process(app, page, doc)

    assert rec.get("state") == State.COMPLETED.value and rec.get("downloaded_ok"), (
        rec.get("state"), rec.get("notes"))
    assert app.stats["failed"] == 0 and app.stats["wrong_document"] == 0, app.stats
    # Measured either way, so this holds something whichever way it passed.
    if size == "past the limit":
        assert not reached, "a file past the limit was read, %r" % reached
    else:
        assert reached, "the older file was never read, so this proves nothing"


# -- a tax form whose file is a pipe ------------------------------------------------------

def test_a_saved_form_that_is_a_pipe_moves_nowhere(pipe):
    listed = [("Tax:1099:2031", {"date": "2031-12-31"})]
    got = within(5, robinhood_docs.App._which_listed_form, {"pdf_path": str(pipe)}, listed)
    assert got == {"value": None}, got


def test_a_saved_form_of_the_year_that_is_a_pipe_is_answered_at_once(pipe, tmp_path):
    app = harness._app(tmp_path)
    doc = robinhood_docs.Document(title="Form 1099", category="Tax Document",
                                  summary="1099", date="2031-12-31")
    rec = dict(doc.to_dict(), pdf_path=str(pipe), downloaded_ok=True,
               state=State.COMPLETED.value)
    app.progress.update("Tax:other", rec)
    got = within(5, app._saved_form_of_year, doc, "2031")
    assert got.get("value") == ("Tax:other", app.progress.get("Tax:other")), got
