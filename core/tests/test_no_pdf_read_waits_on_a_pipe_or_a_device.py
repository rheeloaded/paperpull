"""No PDF a record, an index row or a listing names holds a run for good
because it is a named pipe or a device.

pdf_reader opened and hashed the path it was handed in the run's own
process, to look it up among the PDFs the run had refused, before the
worker that holds a PDF to its time ever saw it. The open of a named pipe
waits for a writer, a read of a Windows named pipe waits for data, and a
link to /dev/zero reads for ever, so a record or an index row naming one
held Target's invoice walk and Robinhood's tax form check until the run
was killed, on every run (the bug hunt of 2026-11-14, finding 4). The size
looked at before the open is 0 for each of them, so no limit stopped it.
Where no worker could start, the PDF was read here with no limit at all,
and trim_blank_tail handed a path to the worker with no look at it.

Now a path that is not a plain file is answered at once as a PDF that did
not open, never handed to a worker, never read here, never remembered and
never said as a limit, and the digest reads no more than a document may be
and one byte, since a file can grow after its size was looked at.

A named pipe and a link to a device are POSIX cases, skipped on Windows
with the reason and run under WSL. A Windows named pipe that never writes
stands in for them here, since its read waits as theirs does. Every name
here is invented.
"""
import builtins
import io
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import intake, pdf_reader, receipt_pdf, testkit  # noqa: E402

POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"
WINDOWS_ONLY = "a Windows named pipe, which only Windows makes"


@pytest.fixture(autouse=True)
def fresh_reader(monkeypatch):
    """Each test with no worker running and nothing remembered."""
    pdf_reader.stop()
    pdf_reader.forget()
    monkeypatch.setattr(pdf_reader, "_cannot_start", False)
    yield
    pdf_reader.stop()
    pdf_reader.forget()


def within(seconds, fn, *args, **kwargs):
    """fn(*args, **kwargs) in a thread, failing if it is still waiting after
    `seconds`, with where it waits. What it answered or raised is handed
    back."""
    got = {}

    def run():
        try:
            got["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "still waiting after %s s, in %s" % (seconds, waiting_in(t))
    return got


def waiting_in(thread) -> str:
    """The last lines of PaperPull's own code a thread is in."""
    frame = sys._current_frames().get(thread.ident)
    lines = [f for f in traceback.extract_stack(frame)
             if "paperpull_core" in f.filename or "apps" in Path(f.filename).parts]
    return ", ".join("%s:%d %s" % (Path(f.filename).name, f.lineno, f.name)
                     for f in lines[-3:]) or "a frame of its own"


def a_fifo(at: Path) -> Path:
    if not hasattr(os, "mkfifo"):
        pytest.skip(POSIX_ONLY)
    os.mkfifo(at)
    return at


def let_go_of_a_fifo(at: Path) -> None:
    """Open the pipe for writing and close it, so a reader still waiting in
    its open, under the code before the fix, reads its end and goes."""
    try:
        os.close(os.open(at, os.O_WRONLY | os.O_NONBLOCK))
    except OSError:
        pass


class WindowsPipe:
    """A Windows named pipe with many instances, none of which is ever
    written to, so a read of it waits for good. Closing it breaks the pipe
    and lets any read still waiting go."""

    def __init__(self, instances: int = 64):
        import _winapi
        self._winapi = _winapi
        self.path = Path(r"\\.\pipe\paperpull-test-%d-%s" % (os.getpid(), os.urandom(4).hex()))
        self.handles = [_winapi.CreateNamedPipe(
            str(self.path), _winapi.PIPE_ACCESS_DUPLEX, 0, _winapi.PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0, _winapi.NULL) for _ in range(instances)]

    def close(self) -> None:
        for h in self.handles:
            try:
                self._winapi.CloseHandle(h)
            except OSError:
                pass
        self.handles = []


@pytest.fixture(params=["named pipe", "Windows named pipe"])
def pipe(request, tmp_path):
    """A pipe at a name a record could hold, a named pipe called
    invoice.pdf on POSIX and a Windows named pipe on Windows."""
    if request.param == "named pipe":
        at = a_fifo(tmp_path / "invoice.pdf")
        yield at
        let_go_of_a_fifo(at)
    else:
        if os.name != "nt":
            pytest.skip(WINDOWS_ONLY)
        made = WindowsPipe()
        yield made.path
        made.close()


def good(tmp_path, name="good.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(testkit.text_pdf(["Order 8421997301", "2026-01-15", "Total 1284.55"]))
    return path


class _Counted:
    """A file opened for reading whose reads are counted, or refused with
    `fail` as reading a file past free memory whole refuses."""

    def __init__(self, f, reads, fail):
        self._f, self._reads, self._fail = f, reads, fail

    def _took(self, n):
        if self._fail is not None:
            raise self._fail()
        self._reads.append(n)

    def read(self, *args):
        if self._fail is not None:
            self._took(0)
        data = self._f.read(*args)
        self._took(len(data or b""))
        return data

    def readinto(self, buffer):
        if self._fail is not None:
            self._took(0)
        n = self._f.readinto(buffer)
        self._took(n or 0)
        return n

    def readall(self):
        return self.read()

    def __iter__(self):
        return iter(lambda: self.read(1 << 16), b"")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()

    def __getattr__(self, name):
        return getattr(self._f, name)


def reads_of(monkeypatch, path: Path, fail=None) -> list:
    """Every read of `path` in this process, however it is opened, by
    open, io.open, Path.read_bytes, os.open or os.fdopen, as the number of
    bytes each gave. With `fail`, each read raises it instead."""
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
        if same(file) and "r" in mode:
            return _Counted(f, reads, fail)
        return f

    def os_opened(file, flags, *args, **kwargs):
        fd = real_os_open(file, flags, *args, **kwargs)
        if same(file):
            fds.add(fd)
        return fd

    def os_read(fd, n):
        if fd in fds:
            if fail is not None:
                raise fail()
            data = real_read(fd, n)
            reads.append(len(data))
            return data
        return real_read(fd, n)

    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(io, "open", opened)
    monkeypatch.setattr(os, "open", os_opened)
    monkeypatch.setattr(os, "read", os_read)
    return reads


# -- a pipe -----------------------------------------------------------------------------

def test_a_pipe_is_answered_at_once_as_a_pdf_that_did_not_open(pipe, capsys):
    """Never a worker, never a limit said or remembered, never raised, and
    no text from pdf_text, which promises never to raise."""
    got = within(3, pdf_reader.read, pipe, text_pages=1)
    read = got.get("value")
    assert read is not None, got
    assert not read.opened and read.error, read
    assert read.over_limit == "" and read.kind != pdf_reader.OVER_LIMIT, read
    assert pdf_reader._worker is None, "a worker was started for what is no PDF"
    assert not pdf_reader._REFUSED
    assert capsys.readouterr().out == ""
    assert within(3, receipt_pdf.pdf_text, pipe) == {"value": ""}


def test_a_pipe_is_answered_at_once_where_no_worker_can_start(pipe, tmp_path, monkeypatch):
    """Where no worker can start, a frozen build or a system that refuses
    the process, a PDF is read here with no limit, so nothing that is not
    a plain file may reach that read."""
    monkeypatch.setattr(pdf_reader, "_interpreter", lambda: str(tmp_path / "no-python"))
    read = within(3, pdf_reader.read, pipe, text_pages=1).get("value")
    assert read is not None and not read.opened and not read.over_limit, read
    assert within(3, receipt_pdf.pdf_text, pipe) == {"value": ""}


def test_a_pipe_is_never_handed_to_a_worker_to_trim(pipe):
    assert within(3, pdf_reader.trim_blank_tail, pipe) == {"value": 0}
    assert pdf_reader._worker is None, "a worker was started for what is no PDF"


def test_a_pipe_read_for_pdfplumber_says_it_did_not_open(pipe):
    got = within(3, pdf_reader.plumbed, pipe)
    assert isinstance(got.get("error"), pdf_reader.Unread), got
    assert got["error"].kind != pdf_reader.OVER_LIMIT
    assert pdf_reader._worker is None


def test_validate_pdf_refuses_a_pipe_at_once(pipe):
    """As it did before, by its size of 0."""
    got = within(3, receipt_pdf.validate_pdf, pipe, 1000).get("value")
    assert got is not None and not got.ok and not got.over_limit, got


# -- a device -----------------------------------------------------------------------------

def test_a_link_to_a_device_is_answered_at_once(tmp_path):
    """A link to /dev/zero reads for ever, and its size is 0."""
    if not os.path.exists("/dev/zero"):
        pytest.skip(POSIX_ONLY)
    at = tmp_path / "statement.pdf"
    at.symlink_to("/dev/zero")
    read = within(3, pdf_reader.read, at, text_pages=1).get("value")
    assert read is not None and not read.opened and not read.over_limit, read
    assert pdf_reader._worker is None
    assert within(3, receipt_pdf.pdf_text, at) == {"value": ""}


def test_a_device_named_on_windows_is_answered_at_once():
    if os.name != "nt":
        pytest.skip("a Windows device name")
    read = within(3, pdf_reader.read, Path("NUL"), text_pages=1).get("value")
    assert read is not None and not read.opened and not read.over_limit, read
    assert pdf_reader._worker is None


# -- the digest's own limit ----------------------------------------------------------------

def test_the_digest_reads_no_more_than_a_document_may_be(tmp_path, monkeypatch):
    """The size looked at first said 10 bytes, as one taken before the file
    grew says. The digest reads no more than the limit and one byte all the
    same, and the PDF is refused for its size, with no worker started."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 4096)
    path = tmp_path / "Statement.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * (64 * 1024))
    real_size_of = intake.size_of
    monkeypatch.setattr(intake, "size_of",
                        lambda p: 10 if Path(p) == path else real_size_of(p))
    reads = reads_of(monkeypatch, path)
    got = pdf_reader.read(path, text_pages=1)
    assert sum(reads) <= 4097, "read %d bytes of a document allowed 4096" % sum(reads)
    assert "larger than" in got.over_limit and got.kind == pdf_reader.OVER_LIMIT, got
    assert pdf_reader._worker is None, "a worker was started for a file it never reads"


def test_a_file_that_grew_after_it_was_opened_is_read_no_further_than_the_limit(
        tmp_path, monkeypatch):
    """The size the opened file says is wrong too, as it is for a file
    still being written. The read itself stops at the limit and one byte."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 4096)
    path = tmp_path / "Statement.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * (64 * 1024))
    real_size_of, real_fstat = intake.size_of, os.fstat
    held = os.stat(path)
    monkeypatch.setattr(intake, "size_of",
                        lambda p: 10 if Path(p) == path else real_size_of(p))

    def fstat(fd):
        st = real_fstat(fd)
        if (st.st_ino, st.st_dev) != (held.st_ino, held.st_dev):
            return st
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid,
                               st.st_gid, 10, st.st_atime, st.st_mtime, st.st_ctime))
    monkeypatch.setattr(os, "fstat", fstat)
    reads = reads_of(monkeypatch, path)
    got = pdf_reader.read(path, text_pages=1)
    assert 0 < sum(reads) <= 4097, "read %d bytes of a document allowed 4096" % sum(reads)
    assert "larger than" in got.over_limit and got.kind == pdf_reader.OVER_LIMIT, got
    assert pdf_reader._worker is None, "a worker was started for a file it never reads"


def test_a_pdf_at_the_limit_is_read_whole(tmp_path, monkeypatch):
    """The limit and not a byte less. A PDF of exactly the limit is read."""
    path = good(tmp_path)
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", path.stat().st_size)
    got = pdf_reader.read(path, text_pages=1)
    assert got.opened and not got.over_limit and "8421997301" in got.texts[0], got


# -- what reads as before -----------------------------------------------------------------

def test_a_pdf_reached_through_a_hard_link_reads_on_the_desktop(tmp_path, monkeypatch):
    """A second name of a file, which Windows lets an ordinary user make."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    at = tmp_path / "linked.pdf"
    os.link(good(tmp_path), at)
    got = receipt_pdf.validate_pdf(at, 1000, expect_tokens=["8421997301"])
    assert got.ok and got.text_token_found, got


def test_a_pdf_reached_through_a_symbolic_link_reads_on_the_desktop(tmp_path, monkeypatch):
    """A desktop whose output folder is reached through a link, a synced
    folder say, has always been read through it."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    at = tmp_path / "linked.pdf"
    try:
        at.symlink_to(good(tmp_path))
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let a test make a symbolic link")
    got = receipt_pdf.validate_pdf(at, 1000, expect_tokens=["8421997301"])
    assert got.ok and got.text_token_found, got
    assert "8421997301" in receipt_pdf.pdf_text(at)


def test_bytes_a_relative_path_a_folder_and_a_missing_file_read_as_before(tmp_path,
                                                                          monkeypatch):
    path = good(tmp_path)
    assert pdf_reader.read(path.read_bytes(), text_pages=1).opened
    monkeypatch.chdir(tmp_path)
    assert "8421997301" in receipt_pdf.pdf_text("good.pdf")
    folder = tmp_path / "a folder.pdf"
    folder.mkdir()
    read = within(3, pdf_reader.read, folder).get("value")
    assert read is not None and not read.opened and not read.over_limit, read
    missing = pdf_reader.read(tmp_path / "missing.pdf")
    assert not missing.opened and missing.error and not missing.over_limit, missing
    assert receipt_pdf.pdf_text(tmp_path / "missing.pdf") == ""


def test_a_folder_named_like_a_pdf_starts_no_worker(tmp_path):
    folder = tmp_path / "a folder.pdf"
    folder.mkdir()
    assert not pdf_reader.read(folder).opened
    assert pdf_reader.trim_blank_tail(folder) == 0
    assert pdf_reader._worker is None


# -- the digest of a file a record names -----------------------------------------------------

def test_the_digest_of_a_plain_file_is_its_whole_sha256(tmp_path, monkeypatch):
    import hashlib
    data = os.urandom(5 * 1024 * 1024 + 17)
    path = tmp_path / "Statement.pdf"
    path.write_bytes(data)
    assert intake.plain_sha256(path) == intake.sha256_of(path) == hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", len(data))
    assert intake.plain_sha256(path) == hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", len(data) - 1)
    assert intake.plain_sha256(path) is None and intake.sha256_of(path) == ""


def test_the_digest_of_what_is_no_plain_file_is_refused_before_it_is_opened(tmp_path,
                                                                            monkeypatch):
    folder = tmp_path / "a folder.pdf"
    folder.mkdir()
    opened = reads_of(monkeypatch, folder)
    with pytest.raises(intake.NotPlainFile) as refused:
        intake.plain_sha256(folder)
    assert "a folder" in refused.value.strerror and not opened
    assert intake.sha256_of(folder) == ""
    with pytest.raises(FileNotFoundError):
        intake.plain_sha256(tmp_path / "missing.pdf")
    assert intake.sha256_of(tmp_path / "missing.pdf") == ""
    assert intake.sha256_of("") == "" and intake.sha256_of(None) == ""


def test_the_digest_of_a_pipe_is_refused_at_once(pipe):
    got = within(3, intake.plain_sha256, pipe)
    assert isinstance(got.get("error"), intake.NotPlainFile), got
    assert "a named pipe" in got["error"].strerror
    assert within(3, intake.sha256_of, pipe) == {"value": ""}


# -- the transactions export -------------------------------------------------------------

def test_the_transactions_export_counts_a_row_naming_a_pipe_as_missing(pipe, tmp_path):
    """As it did before, since it asks is_file() first."""
    import csv
    import importlib.util
    pytest.importorskip("pdfplumber")
    tool = Path(__file__).resolve().parents[2] / "tools" / "export_transactions.py"
    spec = importlib.util.spec_from_file_location("export_transactions_pipe", tool)
    xt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(xt)
    (tmp_path / "A Bank").mkdir()
    with open(tmp_path / "A Bank" / "A Bank Document Index.csv", "w", newline="",
              encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["Document Date", "PDF Full Path"])
        w.writeheader()
        w.writerow({"Document Date": "2026-01-01", "PDF Full Path": str(pipe)})
    assert within(5, xt.providers, tmp_path) == {"value": []}
    got = within(5, xt.export, tmp_path, as_csv=True, log=lambda *_: None).get("value")
    assert got is not None and got["missing"] == 1 and got["read"] == 0, got
