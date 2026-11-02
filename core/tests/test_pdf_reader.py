"""PDFs are read in a process of their own, held to a time and a memory.

An audit of 0.53.0 found validate_pdf and pdf_text letting pypdf read a
PDF in the app's own process for as long as it liked. pypdf 6.19 takes
175 seconds over a PDF of 72 KB that holds one long string, and nothing in
a thread can stop it (measured 2026-10-17). So paperpull_core.pdf_reader
reads PDFs in a worker process and stops it at intake.PDF_SECONDS or
intake.PDF_MEMORY_BYTES.

Every PDF here is made up and small on disk, built to be slow or large to
read, and every one goes through the real worker, started the way an app
starts it. The limits are lowered for each test so a stall costs a second.
"""
import io
import os
import subprocess
import sys
import textwrap
import time
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import identity, intake, pdf_reader, receipt_pdf, testkit  # noqa: E402


def made_pdf(stream: bytes) -> bytes:
    """A one-page PDF whose page draws `stream`, deflated."""
    body = zlib.compress(stream, 9)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    # Padded past every app's minimum size, as a real statement is.
    return bytes(out) + b" " * 4000


def stalling_pdf(pieces: int = 1_000_000) -> bytes:
    """A PDF of a few kilobytes that pypdf takes many seconds to read the
    text of, a million pieces of text drawn one after another. A hundred
    thousand took 2.6 s here and well under a second on Linux in WSL
    (measured 2026-10-17), so a million, for a stall on either."""
    return made_pdf(b"BT /F1 1 Tf " + b"(x) Tj 1 0 Td " * pieces + b"ET")


def bloating_pdf() -> bytes:
    """A PDF of about 76 KB whose one string of text is 70 MB once unpacked,
    which pypdf holds, and copies, while it reads it (175 s here)."""
    return made_pdf(b"BT /F1 1 Tf (" + b"x" * (70 * 1024 * 1024) + b") Tj ET")


@pytest.fixture(autouse=True)
def fresh_reader(monkeypatch):
    """Each test with its own worker and nothing remembered, and the limits
    put back however it ends."""
    pdf_reader.stop()
    pdf_reader.forget()
    monkeypatch.setattr(pdf_reader, "_cannot_start", False)
    yield
    pdf_reader.stop()
    pdf_reader.forget()


@pytest.fixture
def quick(monkeypatch):
    """A second to read a PDF in, so a stall costs a second."""
    monkeypatch.setattr(intake, "PDF_SECONDS", 1)


def good(tmp_path, name="good.pdf", lines=("Order 8421997301", "2026-01-15", "Total 1284.55")):
    path = tmp_path / name
    path.write_bytes(testkit.text_pdf(list(lines)))
    return path


# -- time ---------------------------------------------------------------------

def test_a_pdf_that_stalls_the_reader_is_refused_in_time_and_kept(tmp_path, quick, capsys):
    """Its text is what stalls, which validate_pdf reads when it has facts
    to look for. Opened and counted alone it is quick, and passes."""
    path = tmp_path / "Statement.pdf"
    data = stalling_pdf()
    path.write_bytes(data)
    started = time.monotonic()
    got = receipt_pdf.validate_pdf(path, 1000, expect_tokens=["8421997301"])
    took = time.monotonic() - started
    assert not got.ok and got.over_limit, got
    assert "longer than 1 seconds" in got.reason
    # The budget, the second of grace and the worker's start, never the
    # seconds the stall itself would take.
    assert took < 6, took
    assert path.read_bytes() == data, "the refused PDF was changed or removed"
    assert "set aside unread" in capsys.readouterr().out


def test_the_same_pdf_is_never_read_twice_in_a_run(tmp_path, quick):
    """Its copy in Manual Review checked again, or a second download of the
    same document, is refused at once from what the run remembers."""
    data = stalling_pdf()
    first, again = tmp_path / "a.pdf", tmp_path / "Manual Review copy.pdf"
    first.write_bytes(data)
    again.write_bytes(data)
    assert receipt_pdf.validate_pdf(first, 1000, expect_tokens=["8421997301"]).over_limit
    started = time.monotonic()
    assert receipt_pdf.validate_pdf(again, 1000, expect_tokens=["8421997301"]).over_limit
    assert receipt_pdf.pdf_text(again) == ""
    assert time.monotonic() - started < 0.5


def test_a_stopped_reader_is_replaced_and_the_next_pdf_reads(tmp_path, quick):
    stalled = tmp_path / "stalled.pdf"
    stalled.write_bytes(stalling_pdf())
    assert receipt_pdf.validate_pdf(stalled, 1000, expect_tokens=["8421997301"]).over_limit
    ok = receipt_pdf.validate_pdf(good(tmp_path), 1000, expect_tokens=["8421997301"])
    assert ok.ok and ok.text_token_found and ok.page_count == 1, ok


def test_the_app_stops_the_worker_whatever_its_own_watch_allows(tmp_path, monkeypatch):
    """The watch inside the worker is a second line, given its limits when
    it starts. Started with half a minute, the app's own wait still ends a
    read at the limit of the moment."""
    monkeypatch.setattr(intake, "PDF_SECONDS", 30)
    assert pdf_reader.read(good(tmp_path)).opened
    monkeypatch.setattr(intake, "PDF_SECONDS", 1)
    path = tmp_path / "stall.pdf"
    path.write_bytes(stalling_pdf())
    started = time.monotonic()
    assert pdf_reader.read(path, text_pages=1).over_limit
    assert time.monotonic() - started < 5


def test_a_pdf_within_the_time_is_read_whole(tmp_path):
    """The default limit reads the stalling PDF, which a real statement of
    hundreds of pages is slower than, with its text all there."""
    path = tmp_path / "long.pdf"
    path.write_bytes(stalling_pdf(100_000))
    got = pdf_reader.read(path, text_pages=pdf_reader.ALL)
    assert got.opened and not got.over_limit and len(got.texts[0]) >= 100_000


# -- memory -------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS enforces no memory limit, the worker's own watch holds it there")
def test_a_pdf_that_needs_more_memory_than_allowed_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "PDF_MEMORY_BYTES", 200 * intake.MiB)
    monkeypatch.setattr(intake, "PDF_SECONDS", 300)
    path = tmp_path / "Statement.pdf"
    data = bloating_pdf()
    path.write_bytes(data)
    assert len(data) < 100_000
    started = time.monotonic()
    got = receipt_pdf.validate_pdf(path, 1000, expect_tokens=["8421997301"])
    assert not got.ok and got.over_limit, got
    assert "memory" in got.reason
    assert time.monotonic() - started < 60
    assert path.read_bytes() == data
    # The worker that ran out is gone, and another reads the next PDF.
    assert receipt_pdf.validate_pdf(good(tmp_path), 1000).ok


def test_the_watch_inside_the_worker_ends_it_past_its_memory(monkeypatch):
    """The watch macOS depends on, run here with the most memory used read
    the way macOS reads it, in bytes, and a limit already passed."""
    monkeypatch.setattr(pdf_reader._Watch, "peak", staticmethod(lambda: 0))
    watch = pdf_reader._Watch(memory=1, seconds=60, parent=0, memory_watch=True)
    monkeypatch.setattr(pdf_reader._Watch, "peak", staticmethod(lambda: 10))
    ended = []

    def exit_(code):
        ended.append(code)
        raise SystemExit

    monkeypatch.setattr(pdf_reader.os, "_exit", exit_)
    turns = []

    def sleep(seconds):
        # A watch that never ends the worker would turn here for ever.
        turns.append(seconds)
        if len(turns) > 5:
            raise RuntimeError("the watch went on and never ended the worker")

    monkeypatch.setattr(pdf_reader.time, "sleep", sleep)
    with pytest.raises(SystemExit):
        watch.run()
    assert ended == [pdf_reader._EXIT_MEMORY]


def test_the_watch_inside_the_worker_ends_a_job_past_twice_its_time(monkeypatch):
    watch = pdf_reader._Watch(memory=10 ** 12, seconds=1, parent=0)
    monkeypatch.setattr(pdf_reader._Watch, "peak", staticmethod(lambda: 0))
    clock = iter([0.0] + [5.0] * 20)
    monkeypatch.setattr(pdf_reader.time, "monotonic", lambda: next(clock))
    watch.begin()
    ended = []

    def exit_(code):
        ended.append(code)
        raise SystemExit

    monkeypatch.setattr(pdf_reader.os, "_exit", exit_)
    turns = []

    def sleep(seconds):
        # A watch that never ends the worker would turn here for ever.
        turns.append(seconds)
        if len(turns) > 5:
            raise RuntimeError("the watch went on and never ended the worker")

    monkeypatch.setattr(pdf_reader.time, "sleep", sleep)
    with pytest.raises(SystemExit):
        watch.run()
    assert ended == [pdf_reader._EXIT_TIME]


# -- size ---------------------------------------------------------------------

def test_a_pdf_larger_than_a_document_may_be_is_not_opened(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    path = good(tmp_path)
    started = intake.size_of(path)
    assert started > 2000
    got = receipt_pdf.validate_pdf(path, 100)
    assert not got.ok and "larger than" in got.over_limit
    assert pdf_reader._worker is None, "a worker was started for a file it never reads"
    assert path.exists() and intake.size_of(path) == started


# -- callers read what they read before ----------------------------------------

def test_the_text_is_what_pypdf_reads_in_the_app_itself(tmp_path):
    from pypdf import PdfReader
    path = good(tmp_path)
    direct = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    assert receipt_pdf.pdf_text(path) == direct
    assert pdf_reader.page_texts(path.read_bytes()) == [direct]


def test_a_path_relative_to_the_app_is_read_where_the_app_meant(tmp_path, monkeypatch):
    """An install's output folder is "." by default, so an app hands over
    "Statements/x.pdf", and the worker runs in a folder of its own. Found
    by the zipped-download census, every app's statement failing to open."""
    (tmp_path / "Statements").mkdir()
    good(tmp_path / "Statements")
    monkeypatch.chdir(tmp_path)
    got = receipt_pdf.validate_pdf(Path("Statements") / "good.pdf", 1000,
                                   expect_tokens=["8421997301"])
    assert got.ok and got.text_token_found, got
    assert "8421997301" in receipt_pdf.pdf_text("Statements/good.pdf")


def test_a_pdf_that_will_not_open_says_so_in_pypdfs_words(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"not a pdf at all " * 300)
    got = receipt_pdf.validate_pdf(path, 100)
    assert not got.ok and got.reason.startswith("pypdf could not open file: ")
    assert not got.over_limit
    with pytest.raises(pdf_reader.Unread) as caught:
        pdf_reader.page_texts(path)
    assert caught.value.kind and caught.value.kind != pdf_reader.OVER_LIMIT


def test_an_unreadable_pdf_is_unreadable_to_the_identity_check_never_refused(tmp_path, quick):
    """A PDF past a limit has no text, so the identity check cannot say it is
    another document, and it is never destroyed as one. The app's own
    validation then sets it aside."""
    path = tmp_path / "Statement.pdf"
    path.write_bytes(stalling_pdf())
    verdict = identity.verify(path, identity.Identity(number="8421997301", date="2026-01-15"))
    assert verdict.outcome == identity.UNREADABLE, verdict
    assert receipt_pdf.validate_pdf(path, 1000).over_limit


def test_blank_pages_at_the_end_are_trimmed_in_the_worker(tmp_path):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(testkit.text_pdf(["Invoice 12345"]))))
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    path = tmp_path / "invoice.pdf"
    path.write_bytes(buf.getvalue())
    assert pdf_reader.trim_blank_tail(path) == 1
    assert len(PdfReader(str(path)).pages) == 1
    assert pdf_reader.trim_blank_tail(path) == 0


def test_layout_mode_falls_back_to_the_plain_way(tmp_path):
    path = good(tmp_path)
    assert "8421997301" in pdf_reader.page_texts(path, 1, layout=True)[0]


# -- the worker itself -------------------------------------------------------------

def test_the_worker_runs_this_checkouts_core(tmp_path):
    here = str(Path(pdf_reader.__file__).resolve().parent.parent)
    assert pdf_reader._import_path()[0] == here
    assert pdf_reader.read(good(tmp_path)).opened
    assert pdf_reader._worker is not None and pdf_reader._worker.proc.poll() is None


def test_where_no_worker_can_start_pdfs_are_read_here_and_never_refused(tmp_path, monkeypatch,
                                                                        caplog):
    monkeypatch.setattr(pdf_reader, "_interpreter", lambda: str(tmp_path / "no-python.exe"))
    with caplog.at_level("WARNING", logger="paperpull.pdf_reader"):
        got = receipt_pdf.validate_pdf(good(tmp_path), 1000, expect_tokens=["8421997301"])
        assert got.ok and got.text_token_found
        assert receipt_pdf.validate_pdf(good(tmp_path, "second.pdf"), 1000).ok
    said = [r.getMessage() for r in caplog.records if "in this process" in r.getMessage()]
    assert len(said) == 1, said


def test_a_worker_stopped_from_outside_mid_job_is_given_the_job_again(tmp_path, monkeypatch):
    real = pdf_reader._Worker.ask
    calls = []

    def ask(self, job, data):
        calls.append(job["op"])
        if len(calls) == 1:
            self.stop()
            return pdf_reader._DIED, None
        return real(self, job, data)

    monkeypatch.setattr(pdf_reader._Worker, "ask", ask)
    assert receipt_pdf.validate_pdf(good(tmp_path), 1000).ok
    assert calls == ["read", "read"]


def test_a_pdf_that_stops_the_worker_twice_is_refused(tmp_path, monkeypatch):
    def ask(self, job, data):
        self.stop()
        return pdf_reader._DIED, None

    monkeypatch.setattr(pdf_reader._Worker, "ask", ask)
    got = receipt_pdf.validate_pdf(good(tmp_path), 1000)
    assert not got.ok and "twice" in got.over_limit
    # Not remembered, since a scanner ending python stops a reader as well.
    monkeypatch.undo()
    assert receipt_pdf.validate_pdf(good(tmp_path), 1000).ok


def test_the_memory_watch_counts_only_what_the_worker_grew(monkeypatch):
    """A process can start out holding the most its parent ever used. A
    worker started so is not ended, or replaced on every PDF, for it."""
    monkeypatch.setattr(pdf_reader._Watch, "peak", staticmethod(lambda: 900))
    watch = pdf_reader._Watch(memory=1000, seconds=60, parent=0, memory_watch=True)
    assert not watch.grew_past(500), "replaced for its parent's memory"
    monkeypatch.setattr(pdf_reader._Watch, "peak", staticmethod(lambda: 1200))
    assert watch.grew_past(1000)
    assert not pdf_reader._Watch(memory=1, seconds=60, parent=0).grew_past(0), \
        "watched where the system holds the memory"


def test_the_worker_writes_bytecode_where_its_app_does(tmp_path, monkeypatch):
    """The Mac app keeps bytecode out of its signed bundle by an environment
    variable alone, which -I takes away (review, 2026-10-17)."""
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "pycache"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    pdf_reader.stop()
    about = pdf_reader._ask({"op": "about"}, None, b"")
    assert about == {"pycache_prefix": str(tmp_path / "pycache"), "dont_write_bytecode": True}


def test_a_trim_cut_off_leaves_the_pdf_whole(tmp_path, monkeypatch):
    """The worker can be ended in the middle of writing the trimmed PDF.
    It writes beside the PDF, and what it left there is taken away."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(testkit.text_pdf(["Invoice 12345"]))))
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    path = tmp_path / "invoice.pdf"
    path.write_bytes(buf.getvalue())

    def cut_off(self, out):
        out.write(b"%PDF-1.4 half")
        raise MemoryError

    monkeypatch.setattr(PdfWriter, "write", cut_off)
    reader = PdfReader(str(path))
    with pytest.raises(MemoryError):
        pdf_reader._trim(reader, len(reader.pages), str(path))
    assert path.read_bytes() == buf.getvalue(), "the PDF was cut off"
    monkeypatch.undo()
    assert (tmp_path / ("invoice.pdf" + pdf_reader.TRIMMING)).exists()
    assert pdf_reader.trim_blank_tail(path) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["invoice.pdf"]


def test_the_worker_ends_with_the_app_that_started_it(tmp_path):
    """A worker in the middle of a stalling PDF when its app is killed does
    not run on, ended by its job object on Windows and by its own watch
    elsewhere. Measured from the processes themselves, not the handles."""
    core = str(Path(pdf_reader.__file__).resolve().parents[1])
    stall = tmp_path / "stall.pdf"
    # Half a minute of reading and more, so the worker is in the middle of
    # it, never waiting for its next job, when its app goes.
    stall.write_bytes(stalling_pdf())
    # The real interpreter, never a virtual environment's launcher, whose
    # own job would end the worker with it and prove nothing of this one's.
    python = getattr(sys, "_base_executable", "") or sys.executable
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    script = textwrap.dedent("""
        import sys, threading, time
        sys.path.insert(0, %r)
        from paperpull_core import intake, pdf_reader
        intake.PDF_SECONDS = 600
        threading.Thread(target=pdf_reader.read, args=(%r,), kwargs={"text_pages": None},
                         daemon=True).start()
        while pdf_reader._worker is None or pdf_reader._worker.proc is None:
            time.sleep(0.05)
        print(pdf_reader._worker.proc.pid, flush=True)
        time.sleep(600)
    """) % (core, str(stall))
    app = subprocess.Popen([python, "-c", script], stdout=subprocess.PIPE, text=True, env=env)
    try:
        worker = int(app.stdout.readline())
        # Long enough for the job to be handed over and begun.
        time.sleep(1.5)
        assert _running(worker)
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(app.pid)], capture_output=True)
        else:
            app.kill()
        app.wait(timeout=30)
    deadline = time.monotonic() + 15
    while _running(worker) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _running(worker), "the worker ran on after its app was gone"


def _running(pid: int) -> bool:
    """Whether the process is there and not a zombie. From /proc on Linux
    and from ps on macOS, which has no /proc."""
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    if not sys.platform.startswith("linux"):
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                               capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().split(") ", 1)[1][:1] != "Z"
    except OSError:
        return False


def test_what_a_run_remembers_ends_with_the_run(tmp_path):
    """A PDF one run refused for its time is read again by the next run, a
    process of its own, which comes in once the limit allows it. Nothing of
    what a run remembers is written anywhere."""
    core = str(Path(pdf_reader.__file__).resolve().parents[1])
    stall = tmp_path / "stall.pdf"
    # Seconds to read here and on Linux, far past a fifth of one.
    stall.write_bytes(stalling_pdf(300_000))
    run = textwrap.dedent("""
        import sys
        sys.path.insert(0, %r)
        from paperpull_core import intake, pdf_reader
        intake.PDF_SECONDS = float(sys.argv[1])
        got = pdf_reader.read(%r, text_pages=1)
        print("refused" if got.over_limit else "read")
    """) % (core, str(stall))
    before = sorted(p.name for p in tmp_path.iterdir())

    def a_run(seconds):
        return subprocess.run([sys.executable, "-c", run, str(seconds)], capture_output=True,
                              text=True, timeout=300).stdout.strip().splitlines()[-1]

    assert a_run(0.2) == "refused"
    assert a_run(120) == "read"
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_every_refusal_says_which_limit_and_where_it_is_raised():
    for said, limit in ((pdf_reader._said_time(), "PDF_SECONDS"),
                        (pdf_reader._said_memory(), "PDF_MEMORY_BYTES"),
                        (pdf_reader._said_stopped(), "PDF_MEMORY_BYTES"),
                        (pdf_reader._said_size(10 ** 9), "DOCUMENT_BYTES")):
        assert "%s in paperpull_core/intake.py is the limit, and raising it" % limit in said, said
        assert hasattr(intake, limit)


# -- pdfplumber, for the transactions export ------------------------------------
#
# tools/export_transactions.py read the person's archive with pdfplumber in its
# own process, with nothing to stop a PDF made to keep it busy or to fill the
# memory. It reads them through plumbed() in the worker now.

def test_pdfplumber_reads_in_the_worker_and_a_stall_is_refused_in_time(tmp_path, quick, capsys):
    path = tmp_path / "Statement.pdf"
    data = stalling_pdf()
    path.write_bytes(data)
    started = time.monotonic()
    with pytest.raises(pdf_reader.Unread) as refused:
        pdf_reader.plumbed(path)
    assert time.monotonic() - started < 6
    assert refused.value.kind == pdf_reader.OVER_LIMIT
    assert "PDF_SECONDS in paperpull_core/intake.py" in str(refused.value)
    assert "set aside unread" in capsys.readouterr().out
    assert path.read_bytes() == data, "the refused PDF was changed or removed"
    # Remembered for the run, as every read is.
    again = time.monotonic()
    with pytest.raises(pdf_reader.Unread):
        pdf_reader.plumbed(path)
    assert time.monotonic() - again < 0.5


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS enforces no memory limit, the worker's own watch holds it there")
def test_pdfplumber_past_its_memory_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "PDF_MEMORY_BYTES", 200 * intake.MiB)
    monkeypatch.setattr(intake, "PDF_SECONDS", 300)
    path = tmp_path / "Statement.pdf"
    path.write_bytes(bloating_pdf())
    started = time.monotonic()
    with pytest.raises(pdf_reader.Unread) as refused:
        pdf_reader.plumbed(path)
    # Its memory and never its time, which is five minutes here. pdfplumber
    # fills it more slowly than pypdf, 67 s on a busy machine (2026-10-18).
    assert refused.value.kind == pdf_reader.OVER_LIMIT and "memory" in str(refused.value)
    assert time.monotonic() - started < 240
    assert pdf_reader.plumbed(good(tmp_path))[0]["lines"]


def pages_pdf(pages: int, lines: int = 46) -> bytes:
    """A statement of `pages` dense pages, `lines` lines of transactions each."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for p in range(pages):
        stream = "".join(
            "BT /F1 9 Tf 36 %d Td (%02d/%02d POS DEBIT GROCER STORE %05d CITY ST  $%d.%02d) Tj ET\n"
            % (760 - 16 * i, 1 + p % 12, 1 + i % 28, p * 100 + i, i * 3, i % 100)
            for i in range(lines)).encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % len(objects))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), pages)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS enforces no memory limit, the worker's own watch holds it there")
def test_a_long_statement_is_read_by_pdfplumber_page_by_page_within_its_memory(
        tmp_path, monkeypatch):
    """pdfplumber keeps every page it has read unless each is closed. Sixty
    dense pages held 358 MB that way and 30 MB closed (measured 2026-10-18),
    so a long correct statement was refused for memory (review). Within
    200 MB, every page is read."""
    monkeypatch.setattr(intake, "PDF_MEMORY_BYTES", 200 * intake.MiB)
    path = tmp_path / "Statement.pdf"
    path.write_bytes(pages_pdf(60))
    pages = pdf_reader.plumbed(path)
    assert len(pages) == 60 and all(len(p["lines"]) == 46 for p in pages)


def test_pdfplumber_is_never_asked_in_the_app(tmp_path, monkeypatch):
    """The app's own pdfplumber is one that cannot open anything, and the
    lines still come, from the worker's."""
    import types

    class Refuses(types.ModuleType):
        def open(self, *a, **k):
            raise AssertionError("pdfplumber was asked in the app's own process")
    monkeypatch.setitem(sys.modules, "pdfplumber", Refuses("pdfplumber"))
    pages = pdf_reader.plumbed(good(tmp_path))
    assert [tl["text"] for tl in pages[0]["lines"]] == ["Order 8421997301", "2026-01-15",
                                                        "Total 1284.55"]


def test_pdfplumber_gives_characters_only_where_a_caller_may_rebuild_them(tmp_path):
    path = good(tmp_path)
    plain = pdf_reader.plumbed(path)
    assert all("chars" not in tl for tl in plain[0]["lines"])
    assert all(isinstance(tl["top"], float) for tl in plain[0]["lines"])
    # Two lines of one character. Asked for characters from a page of two
    # such lines, every line comes with its own, and from three, none does.
    short = good(tmp_path, "short.pdf", lines=("A", "B", "Total 1284.55"))
    rebuilt = pdf_reader.plumbed(short, chars_when=2)
    for tl in rebuilt[0]["lines"]:
        assert "".join(c["text"] for c in tl["chars"]).replace(" ", "") == \
            tl["text"].replace(" ", ""), tl
        assert set(tl["chars"][0]) <= {"x0", "x1", "top", "size", "height", "text"}
    assert all("chars" not in tl for tl in pdf_reader.plumbed(short, chars_when=3)[0]["lines"])


def test_a_pdf_pdfplumber_cannot_open_says_so(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nnot a PDF at all\n")
    with pytest.raises(pdf_reader.Unread) as unread:
        pdf_reader.plumbed(path)
    assert unread.value.kind != pdf_reader.OVER_LIMIT
