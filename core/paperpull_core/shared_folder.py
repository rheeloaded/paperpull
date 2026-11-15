"""PaperPull Server's data folder, which other people may write.

On PaperPull Server every provider's folder lives in the data folder,
APPS_ROOT (/data), often a shared folder that other people on the network
can write to, and some shares let them leave a link there, a folder or a
file name that leads somewhere else. The container's user also owns
/config, where the server's password is kept, and /profiles, where every
signed-in browser profile is kept, so a write that followed a link out of
the data folder could land in either.

So on the server a run checks, where it writes, that the folder it writes
into is still inside the data folder once its links are followed, and a
write to a fixed or guessable name opens the file in a way that never
writes through a link left at that name. Off the server every function
here does exactly what the plain call it stands for does.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
from pathlib import Path


class LeadsOut(SystemExit):
    """A write PaperPull Server refused, since it would have gone through a
    link out of the data folder. A SystemExit, so it ends the run with its
    sentence rather than be taken for one failed document."""


def on_server() -> bool:
    return os.environ.get("PAPERPULL_SERVER") == "1"


def _named_root() -> str:
    return os.environ.get("APPS_ROOT") or "/data"


def data_folder() -> str:
    """The data folder, where its own links lead."""
    return os.path.realpath(_named_root())


def _within(path: str, root: str) -> bool:
    path, root = os.path.normcase(path), os.path.normcase(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def leads_out(path) -> bool:
    """Whether a path named inside the data folder leads out of it once its
    links are followed, a link on the way to it included. A path named
    elsewhere, a browser profile or a temporary folder, is not one this
    module looks after, so it answers False for those."""
    named = os.path.abspath(path)
    data = data_folder()
    if not (_within(named, os.path.abspath(_named_root())) or _within(named, data)):
        return False
    return not _within(os.path.realpath(path), data)


def _refuse(path, how: str, doing: str = "writing") -> None:
    raise LeadsOut(
        "%s %s. On PaperPull Server a run never goes through a link it finds where it "
        "writes in the shared folder, so this run stopped before %s there. Someone who "
        "can write to the shared folder may have left the link. Remove it, and run again."
        % (path, how, doing))


def hold(path) -> None:
    """On the server, stop the run unless the folder or file it names, once
    its links are followed, is still where it was named, inside the data
    folder. Call it before a folder is made or written into, since making a
    folder through a link makes it outside."""
    if on_server() and leads_out(path):
        _refuse(path, "leads outside %s, the data folder, through a link" % data_folder())


def _is_link(path, st) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    junction = getattr(os.path, "isjunction", None)
    return bool(junction and junction(path))


def _a_link_at(path) -> bool:
    """Whether a name is a link or a junction, never what it leads to."""
    try:
        return _is_link(path, os.lstat(path))
    except OSError:
        return False


def linked(path) -> bool:
    """Whether a name is a link, a junction or a second name of another
    file, a hard link. A name with nothing there is none of them."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return _is_link(path, st) or (stat.S_ISREG(st.st_mode) and st.st_nlink > 1)


_NOT_PLAIN = "is a link or a second name of another file"


def _open_plain(path, flags: int, doing: str) -> int:
    """An open file descriptor on a plain file of its own at path, never one
    reached through a link at that name. On Linux and macOS the open itself
    refuses a link (O_NOFOLLOW). Windows has no such flag, so there a link
    at the name is looked for before the open. Either way the file opened
    has to be a plain file with no second name, a hard link."""
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        before = None
    if before is not None and (_is_link(path, before) or not stat.S_ISREG(before.st_mode)
                               or before.st_nlink > 1):
        _refuse(path, _NOT_PLAIN, doing)
    try:
        # O_NONBLOCK as well, since a named pipe left at the name after the
        # look above would hold the open for good. On a plain file it
        # changes nothing.
        fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                     | getattr(os, "O_NONBLOCK", 0), 0o666)
    except OSError as e:
        if e.errno == errno.ELOOP:
            _refuse(path, _NOT_PLAIN, doing)
        raise
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
            _refuse(path, _NOT_PLAIN, doing)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_to_write(path, mode: str = "w", encoding=None, newline=None):
    """open(path, mode) for "w", "a", "wb" or "ab". On the server the folder
    is held first and the file is opened by _open_plain, so a link left at
    its name is never written through, and it is emptied for "w" only once
    it is known to be the file's own."""
    if not on_server():
        return open(path, mode, encoding=encoding, newline=newline)
    if mode not in ("w", "a", "wb", "ab"):
        raise ValueError("open_to_write takes w, a, wb or ab, not %r" % mode)
    path = Path(path)
    hold(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode.startswith("a") else 0)
    fd = _open_plain(path, flags, "writing")
    try:
        if mode.startswith("w"):
            os.ftruncate(fd, 0)
        return os.fdopen(fd, mode, encoding=encoding, newline=newline)
    except BaseException:
        os.close(fd)
        raise


def open_to_read(path, mode: str = "r", encoding=None, newline=None):
    """open(path, mode) for "r" or "rb". On the server the file is opened by
    _open_plain, for a file a run reads and then writes back into the
    shared folder, its records or its index, where what a link led to would
    be copied in."""
    if not on_server():
        return open(path, mode, encoding=encoding, newline=newline)
    if mode not in ("r", "rb"):
        raise ValueError("open_to_read takes r or rb, not %r" % mode)
    path = Path(path)
    hold(path.parent)
    fd = _open_plain(path, os.O_RDONLY, "reading")
    try:
        return os.fdopen(fd, mode, encoding=encoding, newline=newline)
    except BaseException:
        os.close(fd)
        raise


# The most read_plain reads. A history of years of documents is a few
# megabytes.
READ_LIMIT = 256 * 1024 * 1024


def read_plain(path, limit: int = READ_LIMIT) -> bytes:
    """The bytes of a plain file at path, for the control panel and the
    tools it runs, which read files of the shared folder that a run wrote.
    Never a named pipe or a device, whose open or read waits for good and
    would hold the panel's thread, on either edition. On PaperPull Server
    never through a link at its name either, and never a file with a second
    name, a hard link, since what either leads to, the server's password
    file among them, would be copied into a spreadsheet, a history or an
    answer. Linux refuses the link in the open itself (O_NOFOLLOW). The
    desktop's folders are the person's alone, and a link there, to a synced
    folder say, is read as it always was. OSError for any of that, never
    the LeadsOut a run stops on, since the panel answers it and goes on.
    ValueError past limit."""
    server = on_server()
    before = os.lstat(path) if server else os.stat(path)
    if not stat.S_ISREG(before.st_mode) or (server and _is_link(path, before)):
        raise OSError(errno.EINVAL, "not a plain file of its own", str(path))
    # O_NONBLOCK on the server alone, since a named pipe is what someone on the share
    # can leave there, and the desktop's files can be cloud placeholders a
    # non-blocking open has not been tried on.
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | ((getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)) if server else 0))
    fd = os.open(path, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (server and st.st_nlink > 1):
            raise OSError(errno.EINVAL, "not a plain file of its own", str(path))
        parts, got = [], 0
        # The first read is the size the file says, so a small file is one
        # read of its own size, never a buffer of the limit's.
        want = min(st.st_size, limit) + 1
        while True:
            piece = os.read(fd, want)
            if not piece:
                break
            got += len(piece)
            if got > limit:
                raise ValueError("%s is larger than %d bytes" % (path, limit))
            parts.append(piece)
            want = 1 << 20
        return b"".join(parts)
    finally:
        os.close(fd)


# The errors Python 3.12's Path.exists() answers False for rather than raises.
_NOT_THERE = (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP)
# Windows' "cannot move the file to a different disk drive", which Python
# reads as EXDEV too, named here should a version not.
_NOT_SAME_DEVICE = 17
# Not ready, an invalid name, a name that cannot be resolved, which 3.12's
# pathlib answers False for on Windows as well (_IGNORED_WINERRORS).
_NOT_THERE_ON_WINDOWS = (21, 123, 1921)


def not_there(error: OSError) -> bool:
    """Whether a stat's error says the file is not there, as Python 3.12's
    exists() read it, rather than that it could not be looked at. 3.12
    raised the others from exists(), and 3.14 answers False for every one,
    so a caller that stats and sorts the error here answers the same on
    every Python (validate_pdf, renaming.plan)."""
    return (error.errno in _NOT_THERE
            or getattr(error, "winerror", None) in _NOT_THERE_ON_WINDOWS)


def path_text(value) -> str:
    """The text of a path a record, an index row or a listing holds, and ""
    for anything that is not text or a path. A hand edit or a damaged file
    can leave a number, a list or a mapping where a path belongs, which
    names no file (a bug hunt of 2026-11-14)."""
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    return value if isinstance(value, str) else ""


def file_there(path) -> bool:
    """Whether path names a file that is there, asked so it never raises.
    Python 3.12's Path.is_file() and exists() raise for a file in a folder
    the run may not search, and a run asking about a path a record, an
    index row or a listing named ended there (a bug hunt of 2026-11-14).
    Such a file, and a path that is not text, count as not there."""
    path = path_text(path)
    if not path:
        return False
    try:
        return Path(path).is_file()
    except (OSError, ValueError):
        return False


def read_text(path, encoding: str = "utf-8", errors: str = "strict",
              limit: int = READ_LIMIT) -> str:
    """read_plain, as text."""
    return read_plain(path, limit).decode(encoding, errors)


def write_whole(path, data) -> None:
    """Text or bytes written to path whole, as a new file of its own beside
    it under a name nobody can guess, opened so it can never be anything
    already there (O_EXCL), then moved into the name's place. A link left at
    the name is replaced, never written through, and a file half written
    is never at the name. The same on both editions, in place of a fixed
    temporary name, x.tmp or x.trimming, at which someone on the share
    could leave a link (a private report of 2026-11-10). OSError when it
    cannot be written, and on the server LeadsOut when the folder leads out
    of the data folder."""
    path = Path(path)
    if on_server():
        hold(path.parent)
    # Eight characters nobody can guess, kept short, since the name is
    # longer than the file's own and Windows refuses a path past 259.
    tmp = path.with_name(".%s.%s.part" % (path.name, os.urandom(4).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def move(src, dst) -> None:
    """shutil.move(src, dst) for a file. On the server a link left at dst
    is replaced, never followed, where shutil.move moved the file into the
    folder a link there led to, or copied it through one to wherever it led
    when the two were on different drives (a private report of 2026-11-10).
    Across drives the file is read as a plain file of its own and written
    whole (write_whole). LeadsOut when dst's folder leads out of the data
    folder, OSError when it cannot be moved."""
    if not on_server():
        # A rename first. shutil.move copies and then deletes whenever its
        # rename fails, and a file another program held open, a sync client
        # say, was then copied into place and could not be taken away, so
        # the caller counted it not moved and the next run saved it a second
        # time (a release review of 2026-11-15). The copy is for another
        # drive alone, which a rename cannot reach.
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if e.errno != errno.EXDEV and getattr(e, "winerror", None) != _NOT_SAME_DEVICE:
                raise
        shutil.move(str(src), str(dst))
        return
    dst = Path(dst)
    hold(dst.parent)
    # The file moved has to be a plain file of its own too, never a link,
    # which a same-drive move would carry into place as a link.
    st = os.lstat(src)
    if _is_link(src, st) or not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
        raise OSError(errno.EINVAL, "not a plain file of its own", str(src))
    try:
        os.replace(src, dst)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            if not _a_link_at(dst):
                raise
            # Windows refuses a rename onto a link to a folder, which Linux
            # replaces as it would a file, so there the link goes first. Only
            # the link goes, never what it leads to (CI of 2026-11-15).
            os.unlink(dst)
            os.replace(src, dst)
            return
    try:
        data = read_plain(src)
    except ValueError as e:
        raise OSError(errno.EFBIG, str(e), str(src)) from e
    write_whole(dst, data)
    os.remove(src)


def copy_whole(src, path) -> None:
    """The file at src copied to path whole, on both editions. The copy is a
    new file under a short name nobody can guess beside path, opened so it
    can never be anything already there (O_EXCL), made in that folder as any
    file is, so it takes the folder's permissions, and moved into path's
    place, which replaces a link there rather than writing through it. src
    is the browser's own copy or one in a private temporary folder, never a
    file of the share. OSError when it cannot be copied, and on the server
    LeadsOut when path's folder leads out of the data folder."""
    path = Path(path)
    if on_server():
        hold(path.parent)
    # Made when it is not there yet, as Playwright's save_as made it.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Its name does not grow with the document's, so a path that fits
    # Windows' 259 characters as the document still fits as the copy.
    tmp = path.with_name(".%s.part" % os.urandom(4).hex())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as f:
            shutil.copyfileobj(f, out, 1 << 20)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_bytes(path, data: bytes) -> None:
    """Path(path).write_bytes(data), through open_to_write on the server."""
    if not on_server():
        Path(path).write_bytes(data)
        return
    with open_to_write(path, "wb") as f:
        f.write(data)


# Folders below a run's own that nothing a run does writes into, so a link
# in one leads nowhere a run goes. A virtual environment holds links to the
# system's Python, and a browser profile copied from a desktop holds links
# of its own.
_NOWHERE_A_RUN_WRITES = (".venv", "venv", "__pycache__")


def _walked(name: str) -> bool:
    return name not in _NOWHERE_A_RUN_WRITES and not name.endswith("browser-profile")


def _download_folder(name: str) -> bool:
    return name.startswith(".") and name.endswith("-downloads")


def first_link_out(root, folders=None) -> str | None:
    """The first file or folder a run could write through that is a link
    leading outside the data folder, or None.

    Every entry of root itself is looked at. Below it the folders a run
    writes into are walked, those named in `folders` and a browser's
    .<name>-downloads, or every folder when `folders` is None, all but a
    virtual environment, a cache and a browser profile, which no run writes
    into. A folder that is a link staying inside the data folder is walked
    where it leads, since a run writes there through it, each place once."""
    data = data_folder()
    top = os.path.realpath(root)
    stack, seen = [], set()

    def look(folder: str, at_top: bool):
        try:
            with os.scandir(folder) as entries:
                found = list(entries)
        except OSError:
            return None
        for entry in found:
            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                where = os.path.realpath(entry.path)
                if not _within(where, data):
                    return entry.path
                walk = os.path.isdir(where)
            else:
                where = entry.path
                try:
                    walk = entry.is_dir(follow_symlinks=False)
                except OSError:
                    walk = False
            if not walk or not _walked(entry.name):
                continue
            if at_top and folders is not None and entry.name not in folders \
                    and not _download_folder(entry.name):
                continue
            stack.append(where)
        return None

    seen.add(os.path.normcase(top))
    found = look(top, True)
    while found is None and stack:
        folder = stack.pop()
        key = os.path.normcase(os.path.realpath(folder))
        if key in seen:
            continue
        seen.add(key)
        found = look(folder, False)
    return found
