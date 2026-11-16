"""Another record's file is read within a document's limit.

A PDF just taken is compared with the other records of its date, and a
record saved before digests were kept is compared by its file's own bytes
(#96). _same_bytes_elsewhere read that file whole into memory. One larger
than free memory raised MemoryError, which its except OSError did not
catch, so the new document was recorded Failed and every later run fetched
it and failed again (the bug hunt of 2026-11-14, finding 6). A download is
never larger than intake.DOCUMENT_BYTES, so a file larger than that cannot
hold the same bytes and is never read.

Reading a file past free memory is stood in for by reads that raise
MemoryError, and its size by lowering DOCUMENT_BYTES, so no test makes a
large file. Everything here is invented.
"""
import builtins
import hashlib
import importlib.util
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import storage  # noqa: E402,F401  binds this provider's AppSpec
import etrade_docs  # noqa: E402
from paperpull_core import intake, testkit  # noqa: E402
from paperpull_core.models import State  # noqa: E402


def _harness():
    """test_two_accounts.py, for its app and the records kept before #96."""
    spec = importlib.util.spec_from_file_location(
        "etrade_another_records_harness", HERE / "test_two_accounts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _harness()
app = harness.app


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


def test_a_file_larger_than_a_document_is_never_read_to_compare(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 4096)
    big = tmp_path / ("%s ETRADE Account Statement.pdf" % harness.DAY)
    big.write_bytes(b"%PDF-1.4\n" + b"1" * (64 * 1024))
    out = tmp_path / "just saved.pdf"
    out.write_bytes(b"%PDF-1.4\n" + b"0" * 3000)
    fake = SimpleNamespace(progress=SimpleNamespace(data={
        "Statement:%s:Brokerage Statement:1111" % harness.DAY: {
            "date": harness.DAY, "pdf_path": str(big), "state": State.COMPLETED.value}}))
    doc = etrade_docs.Document(title=harness.BROKERAGE, category="Statement",
                               date=harness.DAY, account=harness.SECOND)
    reads = reads_of(monkeypatch, big)
    same = etrade_docs.App._same_bytes_elsewhere(
        fake, doc, hashlib.sha256(out.read_bytes()).hexdigest(), out)
    assert sum(reads) <= 4097, "read %d bytes of a file a document may not be" % sum(reads)
    assert same is False


def test_a_file_of_the_same_bytes_within_the_limit_is_still_found(tmp_path):
    """Read in blocks, the digest is the whole file's, so a record kept
    before digests still finds its own bytes."""
    data = os.urandom(5 * 1024 * 1024 + 3)
    older = tmp_path / "older.pdf"
    older.write_bytes(data)
    out = tmp_path / "just saved.pdf"
    out.write_bytes(data)
    fake = SimpleNamespace(progress=SimpleNamespace(data={
        "Statement:%s:Retirement Statement:1111" % harness.DAY: {
            "date": harness.DAY, "pdf_path": str(older), "state": State.COMPLETED.value}}))
    doc = etrade_docs.Document(title=harness.BROKERAGE, category="Statement",
                               date=harness.DAY, account=harness.FIRST)
    assert etrade_docs.App._same_bytes_elsewhere(
        fake, doc, hashlib.sha256(data).hexdigest(), out) is True


@pytest.mark.parametrize("size", ["within the limit", "past the limit"])
def test_a_huge_file_saved_before_digests_never_fails_the_new_document(app, monkeypatch, size):
    """The retirement statement of the day was saved before digests were
    kept, so it is compared by its file, and its file stands in for one
    past free memory. Within the limit it is read and every read raises
    MemoryError. Past it, it is never read at all. Either way the brokerage
    statement, which differs, is kept and recorded as done."""
    older = harness._saved_before(app, harness.RETIREMENT,
                                  "%s ETRADE Account Statement.pdf" % harness.DAY,
                                  prints=harness._statement("Account Number: XXXX-1111"))
    app.listing(harness._raw(harness.BROKERAGE, harness.FIRST, "g1"),
                harness._raw(harness.RETIREMENT, harness.FIRST, "g2"))
    kept = app.progress.data[harness._key(harness.RETIREMENT, "1111")]
    assert not kept.get("pdf_sha256") and Path(kept["pdf_path"]) == older
    new = testkit.text_pdf(harness._statement("Account Number: XXXX-1111", "Brokerage"))
    take, _failures = harness._taking(app, monkeypatch, {harness.FIRST: new})
    if size == "past the limit":
        with open(older, "ab") as f:
            f.write(b" " * 60000)
        assert len(new) < 32 * 1024 < older.stat().st_size
        monkeypatch.setattr(intake, "DOCUMENT_BYTES", 32 * 1024)
    reached = reads_of(monkeypatch, older, fail=MemoryError)
    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if os.path.normcase(os.path.abspath(self)) == os.path.normcase(str(older)):
            reached.append("read_bytes")
            raise MemoryError()
        return real_read_bytes(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    app._on_its_site = lambda: SimpleNamespace(url="")
    doc = harness._doc_of(app, harness.FIRST)

    app.process([doc])

    rec = app.progress.data[doc.key]
    assert rec.get("state") == State.COMPLETED.value and rec.get("downloaded_ok"), (
        rec.get("state"), rec.get("notes"))
    assert app.stats["failed"] == 0 and app.stats["manual_review"] == 0, app.stats
    if size == "past the limit":
        assert not reached, "a file past the limit was read, %r" % reached
    else:
        assert reached, "the older file was never read, so this proves nothing"
