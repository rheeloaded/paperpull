"""Reading a PDF in a process of its own, with a time and a memory it may
not pass.

pypdf reads a PDF in the process that asks, and a PDF can be made to keep
it busy for as long as it likes or to fill the memory, a page tree that
refers back to itself, a stream that unpacks to gigabytes, a cross
reference table that has to be rebuilt object by object. pypdf 6 bounds
some of these and older ones bound none, and an install keeps whatever
pypdf it was set up with. pdfplumber, which the transactions export reads
statements with, bounds none of them either (plumbed). A thread cannot be
stopped from outside in Python, so the reading happens in a worker
process, and the worker is stopped when it passes intake.PDF_SECONDS or
intake.PDF_MEMORY_BYTES.

One worker serves the whole run and is started the first time a PDF is
read, so a document costs a round trip to it rather than a new Python. It
is the same interpreter with the same import path as the app, and it is
handed the folder of the same paperpull_core, so a checkout's core and an
install's are read alike. Its memory is held by the system where the
system can hold it, a job object on Windows and an address space limit on
Linux, and by a watch inside the worker on macOS, which enforces neither.
A worker stopped for either limit is replaced on the next read.

A PDF refused for a limit is remembered for the rest of the run by its
content, so the same bytes are never read twice, a copy in Manual Review
checked again or a second download of the same document. Nothing here
deletes or moves a file. A caller told that a PDF was refused keeps it
wherever it keeps a PDF it refuses.

Where no worker can be started, a frozen build or a system that refuses
the process, the PDF is read here as it always was, and the log says so
once. A limit never refuses a PDF because a reader would not start, and a
reader stopped once from outside is given the PDF again in a new one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

from . import intake
from .characters import whole_characters, whole_json

log = logging.getLogger("paperpull.pdf_reader")


class Read(NamedTuple):
    """What reading one PDF gave.

    `opened` with `pages` when pypdf opened it, and `error` in pypdf's own
    words when it did not. `texts` holds each page's text that was asked
    for, and `text_error` says why the text of a page could not be had,
    `texts` then holding the pages before it. `over_limit` is a sentence
    when the PDF was refused for a limit, and is empty otherwise. `kind` is
    the name of what went wrong, pypdf's own exception's when it raised,
    OVER_LIMIT for a limit, for a failure file that may carry a name and no
    words."""
    opened: bool = False
    pages: int = 0
    texts: tuple = ()
    text_error: str = ""
    error: str = ""
    over_limit: str = ""
    kind: str = ""


OVER_LIMIT = "OverLimit"


class Unread(Exception):
    """A PDF whose pages or text could not be had, for whatever reason, said
    in words. Raised by page_texts, for callers that read a PDF inside a
    try and take any failure as no text. `kind` is Read.kind."""

    def __init__(self, said: str, kind: str = ""):
        super().__init__(said)
        self.kind = kind or "Unread"


ALL = None


def _source(source):
    """(path, bytes, size) of a PDF handed over as a path or as its bytes."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        return None, data, len(data)
    # Absolute, since the worker runs in a folder of its own and an app
    # hands over a path from its output folder as it was set.
    path = os.path.abspath(os.fspath(source))
    return path, None, intake.size_of(path)


def _asked(job: dict, source):
    """The worker's answer to `job` over a PDF, or the sentence refusing it
    for a limit, said and remembered for the run as read() does."""
    path, data, size = _source(source)
    if size > intake.DOCUMENT_BYTES:
        return None, _said_size(size)
    digest = _digest(data, path)
    if digest is not None and digest in _REFUSED:
        return None, _REFUSED[digest]
    answer = _ask(job, path, data)
    over = answer.get("over_limit") or ""
    if over and digest is not None and answer.get("remember", True):
        _REFUSED[digest] = over
    return answer, over


def read(source, *, text_pages: Optional[int] = 0, layout: bool = False) -> Read:
    """Open a PDF, a path or its bytes, count its pages and, when asked,
    read the text of the first `text_pages` of them (ALL for every page, 0
    for none). With `layout`, each page is read in pypdf's layout mode and,
    when that fails, the plain way. Never raises."""
    answer, over = _asked({"op": "read", "text_pages": text_pages, "layout": bool(layout)},
                          source)
    if over:
        return _refused(over)
    return Read(opened=bool(answer.get("opened")), pages=int(answer.get("pages") or 0),
                texts=tuple(answer.get("texts") or ()), text_error=answer.get("text_error") or "",
                error=answer.get("error") or "",
                kind=answer.get("error_kind") or answer.get("text_error_kind") or "")


def _refused(said: str) -> Read:
    """A PDF refused for a limit, said on the run's output and in the log."""
    log.warning(said)
    print("  " + said)
    return Read(over_limit=said, kind=OVER_LIMIT)


def page_texts(source, pages: Optional[int] = ALL, *, layout: bool = False) -> list:
    """The text of the first `pages` pages of a PDF (ALL for every page), a
    list with one string a page. Raises Unread when the PDF did not open, a
    page's text could not be had, or a limit was passed, wherever reading
    it with pypdf directly would have raised."""
    got = read(source, text_pages=pages, layout=layout)
    if got.over_limit:
        raise Unread(got.over_limit, got.kind)
    if not got.opened:
        raise Unread(got.error or "the PDF could not be opened", got.kind)
    if got.text_error:
        raise Unread(got.text_error, got.kind)
    return list(got.texts)


def plumbed(source, *, chars_when: int = 0) -> list:
    """Every page of a PDF, a path or its bytes, as pdfplumber reads its
    lines, read in the worker and held to its limits like any other read.

    A page is {"lines": [...]}, each line its text and its top, and each
    also its characters (x0, x1, top, size, height and text) on a page with
    at least `chars_when` lines of one or two characters, where a caller may
    rebuild a block pdfplumber scattered. A page whose lines pdfplumber
    could not read is {"text": ...}, its text read the plain way. Raises
    Unread where the PDF did not open or was refused for a limit."""
    answer, over = _asked({"op": "plumber", "chars_when": int(chars_when or 0)}, source)
    if over:
        _refused(over)
        raise Unread(over, OVER_LIMIT)
    if not answer.get("opened"):
        raise Unread(answer.get("error") or "the PDF could not be opened",
                     answer.get("error_kind") or "")
    return list(answer.get("plumbed") or ())


def trim_blank_tail(path) -> int:
    """Remove the pages at the end of a PDF that hold no text and no image,
    keeping the first page whatever it holds, and answer how many went. The
    PDF is written again in place only when one does. 0 when it could not
    be read, and nothing is written then."""
    path = os.path.abspath(os.fspath(path))
    size = intake.size_of(path)
    if size > intake.DOCUMENT_BYTES:
        log.info("not looked at for blank pages, %s", _said_size(size))
        return 0
    answer = _ask({"op": "trim_blank_tail"}, path, None)
    # A worker ended in the middle of the write leaves the copy it was
    # writing beside the PDF, which is left as it was. A link someone left
    # under such a name goes as a link, never what it leads to.
    import glob
    for left in sorted(glob.glob(glob.escape(path + TRIMMING) + ".*")):
        try:
            os.remove(left)
        except OSError:
            pass
    if answer.get("over_limit") or answer.get("error"):
        log.info("could not look for blank pages at the end (%s)",
                 answer.get("over_limit") or answer.get("error"))
        return 0
    return int(answer.get("removed") or 0)


def _said_size(size: int) -> str:
    return ("The PDF is larger than the %s PaperPull reads (%s), so it was not opened. %s"
            % (intake._mb(intake.DOCUMENT_BYTES), intake._mb(size),
               intake.raising("DOCUMENT_BYTES", "lets a larger one in")))


def _said_time(seconds=None) -> str:
    return ("The PDF took longer than %d seconds to read, so it was set aside unread. %s"
            % (intake.PDF_SECONDS if seconds is None else seconds,
               intake.raising("PDF_SECONDS", "gives a PDF longer")))


def _said_memory(memory=None) -> str:
    return ("The PDF needed more than the %s of memory PaperPull gives a PDF, so it was "
            "set aside unread. %s" % (intake._mb(intake.PDF_MEMORY_BYTES if memory is None
                                                  else memory),
                                       intake.raising("PDF_MEMORY_BYTES", "gives a PDF more")))


def _said_stopped() -> str:
    return ("The PDF stopped the reader twice, which is what one over its memory "
            "does, so it was set aside unread. %s"
            % intake.raising("PDF_MEMORY_BYTES", "gives a PDF more"))


# -- remembered for the run ---------------------------------------------------
#
# In this process's memory and nowhere else, never written to a file, so it
# ends with the run. Every run of an app is a process of its own, started
# by the panel, the server or a person, and neither the panel nor the
# server reads a PDF itself. The next run asks for the document again, and
# reads it again, as it does for every document a run refused.

_REFUSED: dict = {}


def _digest(data, path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        if data is not None:
            h.update(data)
        else:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def forget() -> None:
    """Forget every PDF refused so far in this process. For tests."""
    _REFUSED.clear()


# -- the conversation with the worker ------------------------------------------
#
# Each message is eight bytes of length and then that many bytes. The app
# sends a job as JSON, and the PDF's bytes as a second message when it has
# no path, and the worker answers with JSON.

_HEAD = struct.Struct(">Q")


def _message_bytes() -> int:
    """A message larger than this is not one. The largest is a PDF's own
    bytes, and the next an answer holding the text of its pages."""
    return intake.DOCUMENT_BYTES + 156 * intake.MiB


def _send(stream, payload: bytes) -> None:
    stream.write(_HEAD.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def _recv(stream) -> Optional[bytes]:
    head = stream.read(_HEAD.size)
    if len(head) < _HEAD.size:
        return None
    (n,) = _HEAD.unpack(head)
    if n > _message_bytes():
        return None
    payload = stream.read(n)
    return payload if len(payload) == n else None


# How the worker is started. It reads where to import from as its first
# message, before it imports anything of the core's, so the core it runs is
# the app's own whatever its import path would have found.
_BOOT = (
    "import json, struct, sys\n"
    "h = sys.stdin.buffer.read(8)\n"
    "sys.path[:0] = json.loads(sys.stdin.buffer.read(struct.unpack('>Q', h)[0]))\n"
    "from paperpull_core import pdf_reader\n"
    "pdf_reader._serve()\n")

# How long a new worker may take to say it is ready, Python started and
# pypdf imported. Measured at under half a second here, and a NAS is slower.
_START_SECONDS = 30

# How a worker that stopped itself says why, by its exit code.
_EXIT_MEMORY = 86
_EXIT_TIME = 87
_EXIT_ORPHAN = 88

_TIMED_OUT = "timed out"
_DIED = "died"


class _Worker:
    def __init__(self):
        self.proc = None
        self.answers: queue.Queue = queue.Queue()
        self.job = None

    def start(self) -> bool:
        """Start the worker and wait for it to say it is ready. False, with
        nothing left running, when it could not be started or never said."""
        exe = _interpreter()
        if not exe:
            return False
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                [exe, "-I"] + _bytecode_switches() + ["-c", _BOOT], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=_quiet_folder(exe),
                creationflags=flags)
        except (OSError, ValueError) as e:
            log.warning("no PDF reader process could be started (%s)", type(e).__name__)
            self.proc = None
            return False
        if os.name == "nt":
            self.job = _hold_memory(self.proc)
        threading.Thread(target=self._listen, args=(self.proc, self.answers),
                         name="pdf-reader-answers", daemon=True).start()
        try:
            _send(self.proc.stdin, json.dumps(_import_path()).encode("utf-8"))
            _send(self.proc.stdin, json.dumps({
                "memory": intake.PDF_MEMORY_BYTES, "seconds": intake.PDF_SECONDS,
                "parent": os.getpid()}).encode("utf-8"))
        except (OSError, ValueError):
            self.stop()
            return False
        try:
            ready = self.answers.get(timeout=_START_SECONDS)
        except queue.Empty:
            ready = None
        try:
            ready = json.loads(ready.decode("utf-8")) if ready else {}
        except ValueError:
            ready = {}
        if not ready.get("ready"):
            log.warning("the PDF reader process did not start")
            self.stop()
            return False
        return True

    @staticmethod
    def _listen(proc, answers) -> None:
        while True:
            try:
                got = _recv(proc.stdout)
            except (OSError, ValueError):
                got = None
            answers.put(got)
            if got is None:
                return

    def ask(self, job: dict, data: Optional[bytes]):
        """The worker's answer to one job, as a dictionary, or _TIMED_OUT,
        or _DIED with how it ended."""
        try:
            _send(self.proc.stdin, json.dumps(job).encode("utf-8"))
            if data is not None:
                _send(self.proc.stdin, data)
        except (OSError, ValueError):
            return _DIED, self._ended()
        try:
            got = self.answers.get(timeout=intake.PDF_SECONDS + 1)
        except queue.Empty:
            self.stop()
            return _TIMED_OUT, None
        if got is None:
            return _DIED, self._ended()
        try:
            # Its texts were made whole in the worker, and JSON carries a
            # half that got past as its escape, which is made whole here.
            answer = whole_json(json.loads(got.decode("utf-8")))
        except ValueError:
            self.stop()
            return _DIED, None
        for name, level, message in answer.pop("logged", ()) or ():
            logging.getLogger(str(name)).log(int(level), "%s", message)
        if answer.pop("retire", False):
            self.stop()
        return answer, None

    def _ended(self):
        code = None
        if self.proc is not None:
            try:
                code = self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self.stop()
        return code

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
            for stream in (proc.stdin, proc.stdout):
                try:
                    stream.close()
                except (OSError, AttributeError):
                    pass
            try:
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if self.job is not None:
            _close_handle(self.job)
            self.job = None
        self.answers = queue.Queue()


_lock = threading.Lock()
_worker: Optional[_Worker] = None
_cannot_start = False


def _ask(job: dict, path, data) -> dict:
    """One job, answered by the worker or, where none can run, here. A
    worker that ends in the middle of a job for no reason it gave is given
    the job once more in a new one, so a reader that was stopped from
    outside never refuses a PDF."""
    if path is not None:
        job = dict(job, path=path)
    with _lock:
        for attempt in (1, 2):
            worker = _running()
            if worker is None:
                return _here(job, data)
            answer, code = worker.ask(job, data)
            if answer == _TIMED_OUT or code == _EXIT_TIME:
                return {"over_limit": _said_time()}
            if code == _EXIT_MEMORY:
                return {"over_limit": _said_memory()}
            if answer != _DIED:
                return answer
        # Not remembered for the run, since something outside, a scanner
        # ending python, can stop a reader twice as well as a PDF can.
        return {"over_limit": _said_stopped(), "remember": False}


def _running() -> Optional[_Worker]:
    global _worker, _cannot_start
    if _worker is not None and _worker.proc is not None and _worker.proc.poll() is None:
        return _worker
    if _worker is not None:
        _worker.stop()
        _worker = None
    if _cannot_start:
        return None
    worker = _Worker()
    if not worker.start():
        _cannot_start = True
        log.warning("PDFs are read in this process, with no limit on their time or memory")
        return None
    _worker = worker
    return worker


def _here(job: dict, data) -> dict:
    try:
        return _do(job, data)
    except MemoryError:
        return {"over_limit": _said_memory()}


def stop() -> None:
    """Stop the worker, if one is running. The next read starts another."""
    global _worker
    with _lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def _interpreter() -> str:
    """The Python the worker runs on. A virtual environment's python.exe on
    Windows is a launcher that starts the real one as a child of its own,
    which a job object handed the launcher would not hold from the start,
    so the real one is run, given the app's import path."""
    if getattr(sys, "frozen", False):
        return ""
    if os.name == "nt":
        base = getattr(sys, "_base_executable", "") or ""
        if base and os.path.isfile(base):
            return base
    return sys.executable or ""


def _import_path() -> list:
    """Where the worker imports from, the folder holding this paperpull_core
    first and then the app's own import path, every entry made absolute and
    the current folder left out."""
    out = [str(Path(__file__).resolve().parent.parent)]
    for entry in sys.path:
        if not entry or not isinstance(entry, str):
            continue
        absolute = os.path.abspath(entry)
        if absolute not in out and os.path.exists(absolute):
            out.append(absolute)
    return out


def _bytecode_switches() -> list:
    """Where the worker writes the bytecode it compiles, wherever its app
    writes its own. -I takes away every PYTHON variable, and the Mac app
    keeps bytecode out of its signed bundle with PYTHONPYCACHEPREFIX alone,
    so a worker left to itself wrote __pycache__ into the bundle, which then
    reads as damaged (review, 2026-10-17)."""
    out = []
    if sys.dont_write_bytecode:
        out.append("-B")
    prefix = getattr(sys, "pycache_prefix", None)
    if prefix:
        out += ["-X", "pycache_prefix=%s" % prefix]
    return out


def _quiet_folder(exe: str) -> Optional[str]:
    """A folder to start the worker in that holds nothing to import."""
    return os.path.dirname(os.path.abspath(exe)) or None


def _at_exit() -> None:
    try:
        stop()
    except Exception:
        pass


import atexit as _atexit  # noqa: E402

_atexit.register(_at_exit)


# -- holding the worker's memory on Windows ------------------------------------

def _hold_memory(proc):
    """A job object holding the worker to intake.PDF_MEMORY_BYTES, and
    ending it when this process ends. None when Windows refused, and the
    worker then runs held by its time alone."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic),
                    ("IoInfo", Counters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    LIMIT_PROCESS_MEMORY = 0x100
    LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
    LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    EXTENDED_LIMIT_INFORMATION = 9
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                     ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = (LIMIT_PROCESS_MEMORY | LIMIT_KILL_ON_JOB_CLOSE
                                                 | LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        info.ProcessMemoryLimit = intake.PDF_MEMORY_BYTES
        if not kernel32.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION,
                                                ctypes.byref(info), ctypes.sizeof(info)) \
                or not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
            log.warning("Windows would not hold the PDF reader's memory (error %d), so it "
                        "is held by its time alone", ctypes.get_last_error())
            _close_handle(job)
            return None
        return job
    except Exception as e:
        log.warning("the PDF reader's memory could not be held (%s)", type(e).__name__)
        return None


def _close_handle(handle) -> None:
    try:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(handle)
    except Exception:
        pass


# -- the worker itself ---------------------------------------------------------

def _serve() -> None:
    """The worker's loop. Reads its limits, says it is ready, then answers
    jobs until the app closes the conversation."""
    stdin = sys.stdin.buffer
    out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    # Anything else that writes to the output, pypdf included, writes
    # nowhere, so the conversation holds only answers.
    try:
        quiet = os.open(os.devnull, os.O_WRONLY)
        os.dup2(quiet, sys.stdout.fileno())
        os.close(quiet)
    except OSError:
        pass
    sys.stdout = open(os.devnull, "w")
    limits = json.loads((_recv(stdin) or b"{}").decode("utf-8"))
    memory = int(limits.get("memory") or intake.PDF_MEMORY_BYTES)
    seconds = float(limits.get("seconds") or intake.PDF_SECONDS)
    watch = _Watch(memory, seconds, int(limits.get("parent") or 0),
                   memory_watch=sys.platform == "darwin")
    _hold_address_space(memory)
    kept = _Kept()
    logging.getLogger().addHandler(kept)
    logging.getLogger().setLevel(logging.WARNING)
    threading.Thread(target=watch.run, name="pdf-reader-watch", daemon=True).start()
    try:
        import pypdf
        version = getattr(pypdf, "__version__", "")
    except Exception:
        version = ""
    _send(out, json.dumps({"ready": True, "pypdf": version}).encode("utf-8"))
    while True:
        raw = _recv(stdin)
        if raw is None:
            return
        job = json.loads(raw.decode("utf-8"))
        data = None
        if "path" not in job:
            data = _recv(stdin)
            if data is None:
                return
        watch.begin()
        try:
            answer = _do(job, data)
        except MemoryError:
            answer = {"over_limit": _said_memory(memory)}
        watch.end()
        answer["logged"] = kept.take()
        # On macOS, where only the most memory ever used can be read, a
        # worker whose use once grew past half its limit is replaced.
        answer["retire"] = watch.grew_past(memory // 2)
        _send(out, json.dumps(answer).encode("utf-8"))


class _Kept(logging.Handler):
    """What pypdf logged during a job, handed back so the app's own log has
    it, as it did when pypdf ran in the app."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list = []

    def emit(self, record) -> None:
        if len(self.records) < 50:
            try:
                self.records.append((record.name, record.levelno, record.getMessage()[:500]))
            except Exception:
                pass

    def take(self) -> list:
        out, self.records = self.records, []
        return out


def _hold_address_space(memory: int) -> None:
    """On Linux, the system holds the worker to `memory`. macOS takes the
    setting and does not enforce it, and the watch holds it there."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    except (ImportError, ValueError, OSError):
        pass


class _Watch:
    """Inside the worker, a second line behind the app's own. It ends the
    worker when a job has run twice its time, so a worker whose app went
    away in the middle of a job does not run on, and when the app that
    started it is gone. On macOS, which enforces no memory limit, it also
    ends the worker when the most memory it has used passes the limit.

    That most is the process's, and a process can start out holding the
    most its parent ever used (measured on Linux, a child read 746 MB its
    parent had freed). So only growth past what the worker started with
    counts, and Linux, held by its address space limit, is not watched."""

    def __init__(self, memory: int, seconds: float, parent: int,
                 memory_watch: bool = False):
        self.memory = memory
        self.seconds = seconds
        self.parent = parent
        self.started = None
        self.memory_watch = memory_watch
        self.at_start = self.peak() if memory_watch else 0

    def grew_past(self, limit: int) -> bool:
        """Whether the worker's own memory has grown past `limit`."""
        if not self.memory_watch:
            return False
        used = self.peak()
        return used > limit and used > self.at_start

    def begin(self) -> None:
        self.started = time.monotonic()

    def end(self) -> None:
        self.started = None

    @staticmethod
    def peak() -> int:
        try:
            import resource
        except ImportError:
            return 0
        used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Bytes on macOS, kilobytes on Linux.
        return used if sys.platform == "darwin" else used * 1024

    def run(self) -> None:
        while True:
            time.sleep(0.05)
            started = self.started
            if started is not None and time.monotonic() - started > 2 * self.seconds:
                os._exit(_EXIT_TIME)
            if self.grew_past(self.memory):
                os._exit(_EXIT_MEMORY)
            if os.name != "nt" and self.parent and os.getppid() != self.parent:
                os._exit(_EXIT_ORPHAN)


def _do(job: dict, data: Optional[bytes]) -> dict:
    """One job, in whichever process reads PDFs. Every failure of pypdf's is
    an answer, never an exception, except running out of memory."""
    if job.get("op") == "plumber":
        return _plumb(job, data)
    try:
        from pypdf import PdfReader
    except Exception as e:
        return {"opened": False, "error": "%s" % e, "error_kind": type(e).__name__}
    if job.get("op") == "about":
        return {"pycache_prefix": getattr(sys, "pycache_prefix", None),
                "dont_write_bytecode": bool(sys.dont_write_bytecode)}
    import io
    source = io.BytesIO(data) if data is not None else str(job.get("path") or "")
    try:
        reader = PdfReader(source)
        pages = len(reader.pages)
    except MemoryError:
        raise
    except Exception as e:
        return {"opened": False, "error": "%s" % e, "error_kind": type(e).__name__}
    if job.get("op") == "trim_blank_tail":
        try:
            return _trim(reader, pages, str(job.get("path") or ""))
        except MemoryError:
            raise
        except Exception as e:
            return {"opened": True, "pages": pages, "error": type(e).__name__}
    want = job.get("text_pages", 0)
    texts, text_error, text_error_kind = [], "", ""
    if want != 0:
        chosen = reader.pages if want is None else reader.pages[:max(1, int(want))]
        try:
            for page in chosen:
                texts.append(_text(page, bool(job.get("layout"))))
        except MemoryError:
            raise
        except Exception as e:
            text_error = ("%s" % e) or type(e).__name__
            text_error_kind = type(e).__name__
    return {"opened": True, "pages": pages, "texts": texts, "text_error": text_error,
            "text_error_kind": text_error_kind}


def _text(page, layout: bool) -> str:
    # Made whole where pypdf hands it over, so half of a character never
    # reaches the app (characters.py).
    if layout:
        try:
            return whole_characters(page.extract_text(extraction_mode="layout") or "")
        except MemoryError:
            raise
        except Exception:
            pass
    return whole_characters(page.extract_text() or "")


def _trim(reader, total: int, path: str) -> dict:
    """The pages at the end that hold no text and no image, removed, the
    first page always kept. Apple's printed invoice had a second page with
    nothing on it."""
    keep = total
    while keep > 1:
        page = reader.pages[keep - 1]
        if whole_characters(page.extract_text() or "").strip():
            break
        resources = page.get("/Resources") or {}
        try:
            resources = resources.get_object()
        except Exception:
            pass
        if "/XObject" in resources:
            break
        keep -= 1
    if keep == total:
        return {"opened": True, "pages": total, "removed": 0}
    from pypdf import PdfWriter
    writer = PdfWriter()
    for page in reader.pages[:keep]:
        writer.add_page(page)
    # Written beside and put in place whole, since the worker can be ended
    # at any moment, and a PDF written over in place would be left cut off.
    # Beside it under a name nobody can guess, opened so it can never be
    # anything already there, where a fixed name was one someone on
    # PaperPull Server's share could leave a link at, and the PDF was
    # written through it (a private report of 2026-11-10).
    beside = "%s%s.%s" % (path, TRIMMING, os.urandom(4).hex())
    fd = os.open(beside, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    # One cut off is left for trim_blank_tail to take away, as a worker
    # ended in the middle of it leaves it.
    with os.fdopen(fd, "wb") as out:
        writer.write(out)
    os.replace(beside, path)
    return {"opened": True, "pages": total, "removed": total - keep}


TRIMMING = ".trimming"


# What plumbed() hands back of each character pdfplumber read.
_CHAR_KEYS = ("x0", "x1", "top", "size", "height", "text")


def _plumb(job: dict, data: Optional[bytes]) -> dict:
    """Every page's lines as pdfplumber reads them, the way the transactions
    export read them in its own process before (plumbed). Every failure is
    an answer, except running out of memory."""
    try:
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        import pdfplumber
    except Exception as e:
        return {"opened": False, "error": "%s" % e, "error_kind": type(e).__name__}
    import io
    source = io.BytesIO(data) if data is not None else str(job.get("path") or "")
    chars_when = int(job.get("chars_when") or 0)
    pages = []
    try:
        with pdfplumber.open(source) as pdf:
            for page in pdf.pages:
                try:
                    pages.append(_plumbed_page(page, chars_when))
                finally:
                    # pdfplumber keeps every page it has read, and a dense
                    # statement of 60 pages held 358 MB that way against
                    # 30 MB closed page by page (measured 2026-10-18,
                    # review), which the memory limit would have refused.
                    page.close()
    except Exception as e:
        if _out_of_memory(e):
            raise MemoryError from None
        return {"opened": False, "error": ("%s" % e) or type(e).__name__,
                "error_kind": type(e).__name__}
    return {"opened": True, "pages": len(pages), "plumbed": pages}


def _plumbed_page(page, chars_when: int) -> dict:
    try:
        # Made whole where pdfplumber hands it over (characters.py).
        return {"lines": whole_json(_lines(page.extract_text_lines(
            layout=False, strip=True, return_chars=True), chars_when))}
    except Exception as e:
        if _out_of_memory(e):
            raise MemoryError from None
        return {"text": whole_characters(page.extract_text() or "")}


def _out_of_memory(error) -> bool:
    """Whether an error is running out of memory, which pdfplumber hands on
    inside a PdfminerException of its own (pdfplumber 0.11.10, page.py)."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, MemoryError):
            return True
        seen.add(id(error))
        inner = [a for a in getattr(error, "args", ()) if isinstance(a, BaseException)]
        error = error.__cause__ or error.__context__ or (inner[0] if inner else None)
    return False


def _lines(found: list, chars_when: int) -> list:
    """pdfplumber's lines of a page with what plumbed() hands back of each,
    and their characters on a page with at least `chars_when` lines of one
    or two characters."""
    # Counted on the text made whole, as the caller counts it, where the two
    # halves of one character are one (review).
    short = sum(1 for tl in found if len(whole_characters(tl.get("text") or "").strip()) <= 2)
    keep = bool(chars_when) and short >= chars_when
    return [_line(tl, keep) for tl in found]


def _line(found: dict, chars: bool) -> dict:
    out = {"text": found.get("text") or "", "top": float(found.get("top") or 0.0)}
    if not chars:
        return out
    kept: list = []
    for c in found.get("chars") or ():
        one = {k: (c[k] if k == "text" else float(c[k] or 0.0)) for k in _CHAR_KEYS if k in c}
        text = one.get("text") or ""
        if kept and _half(text, 0xDC00) and _half(kept[-1].get("text") or "", 0xD800):
            # The two halves of one character, read as two characters, are
            # kept as one, so they are made whole together into what they
            # make, as the line's own text is, and not each into U+FFFD.
            kept[-1]["text"] += text
            kept[-1]["x1"] = one.get("x1", kept[-1].get("x1", 0.0))
            continue
        kept.append(one)
    out["chars"] = kept
    return out


def _half(text: str, first: int) -> bool:
    """Whether text is one half of a surrogate pair, the high half for
    0xD800 and the low half for 0xDC00."""
    return len(text) == 1 and first <= ord(text) <= first + 0x3FF
