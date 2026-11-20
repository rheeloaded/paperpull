"""The empty-folder cleanup after a Move without kind folders never takes
away a link or a junction (follow-up of the 0.69.0 release review, #201).

drop_empty_kind_folders called rmdir on each folder of a kind in the
documents folder. A person can make Watched/Statements a junction or a
link to a folder somewhere else, and Windows takes such a name away with
rmdir without looking inside where it leads, whether that folder is empty
or full. Only a real folder with nothing in it goes now.

A junction is made where Windows is, a symbolic link where the system lets
this account make one, and each test that cannot make one says why it is
skipped. Every folder is a throwaway one under tmp_path.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.storage import Paths  # noqa: E402


def junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("a junction is made on Windows only")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip("this account may not make a symbolic link here (%s)" % (getattr(e, "strerror", None) or type(e).__name__))


MAKE = {"junction": junction, "symlink": symlink}


def flat(tmp_path) -> Paths:
    paths = Paths(tmp_path / "out", documents_dir=str(tmp_path / "Watched"), kind_folders=False)
    (tmp_path / "Watched").mkdir()
    return paths


@pytest.mark.parametrize("kind", sorted(MAKE))
@pytest.mark.parametrize("full", [False, True], ids=["empty target", "full target"])
def test_a_kind_folder_that_is_a_link_stays(tmp_path, kind, full):
    paths = flat(tmp_path)
    target = tmp_path / "Elsewhere"
    target.mkdir()
    if full:
        (target / "kept.pdf").write_bytes(b"%PDF-1.4 invented\n")
    link = tmp_path / "Watched" / "Statements"
    MAKE[kind](link, target)
    paths.drop_empty_kind_folders()
    assert os.path.lexists(link), "the %s itself was taken away" % kind
    assert target.is_dir()
    assert [p.name for p in target.iterdir()] == (["kept.pdf"] if full else [])


@pytest.mark.parametrize("kind", sorted(MAKE))
def test_a_kind_folder_that_is_a_link_to_nothing_stays(tmp_path, kind):
    paths = flat(tmp_path)
    target = tmp_path / "Gone"
    target.mkdir()
    link = tmp_path / "Watched" / "Statements"
    MAKE[kind](link, target)
    target.rmdir()
    paths.drop_empty_kind_folders()
    assert os.path.lexists(link)


def test_a_real_empty_kind_folder_is_taken_away_and_a_full_one_stays(tmp_path):
    """The control, as it always was."""
    paths = flat(tmp_path)
    (tmp_path / "Watched" / "Statements").mkdir()
    full = tmp_path / "Watched" / "Other Documents"
    full.mkdir()
    (full / "kept.pdf").write_bytes(b"%PDF-1.4 invented\n")
    paths.drop_empty_kind_folders()
    assert not (tmp_path / "Watched" / "Statements").exists()
    assert (full / "kept.pdf").is_file()


def test_with_kind_folders_nothing_is_taken_away(tmp_path):
    paths = Paths(tmp_path / "out", documents_dir=str(tmp_path / "Watched"))
    (tmp_path / "Watched" / "Statements").mkdir(parents=True)
    paths.drop_empty_kind_folders()
    assert (tmp_path / "Watched" / "Statements").is_dir()
