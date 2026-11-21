"""A refused kind_folders setting stops only a run that may save or move a
document (follow-up of the 0.69.0 release review, #201).

set_kind_folders refuses "kind_folders": false with no documents folder of
the account's own, a value that is not true or false, and names that would
not say which kind a document is. That stopped every run at load_config,
Login and the Support report (--diagnose) too, so a person could not even
sign in to fix it from the panel. A run started only with --login,
--open-browser or --diagnose, and --config beside them, now goes on with
documents in the folders of their kind, the setting not taken, and says
so. Any other flag beside them, a shortened one included, has the run
stopped as before, with the same words.

Every folder is a throwaway one under tmp_path.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import storage  # noqa: E402
from paperpull_core.storage import Paths  # noqa: E402
from test_documents_folder import write  # noqa: E402


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


READ_ONLY = [["--login"], ["--open-browser"], ["--diagnose"],
             ["--login", "--config", "config.b.json"], ["--config=config.b.json", "--diagnose"],
             ["--diagnose", "--login"]]
SAVING = [[], ["--all"], ["--pilot"], ["--resume", "--yes"], ["--rename", "--apply"],
          ["--verify"], ["--discover"], ["--record"], ["--diagnose", "--all"],
          ["--login", "--rename"], ["--diag"], ["--log"], ["--login", "--yes"],
          ["--diagnose", "--year", "2025"], ["-h"], ["--config", "x.json"]]


@pytest.mark.parametrize("argv", READ_ONLY, ids=" ".join)
def test_login_and_a_support_report_save_nothing(argv):
    assert storage._saves_nothing(argv)


@pytest.mark.parametrize("argv", SAVING, ids=lambda a: " ".join(a) or "no flags")
def test_every_other_run_may_save_or_move(argv):
    assert not storage._saves_nothing(argv)


REFUSED = {
    "no documents folder": {"kind_folders": False},
    "not true or false": {"kind_folders": "false", "documents_dir": "Watched"},
    "names that do not say the kind": {"kind_folders": False, "documents_dir": "Watched",
                                       "filename_pattern": "{year}/{date} {account}"},
}


def config(tmp_path, settings) -> Path:
    settings = dict(settings, output_dir=str(tmp_path / "out"))
    if "documents_dir" in settings:
        settings["documents_dir"] = str(tmp_path / settings["documents_dir"])
    return write(tmp_path / "app", settings)


@pytest.mark.parametrize("why", sorted(REFUSED))
@pytest.mark.parametrize("argv", [["--login"], ["--diagnose"]], ids=" ".join)
def test_a_refused_setting_lets_the_run_go_on_with_kind_folders(tmp_path, monkeypatch, capsys,
                                                                 why, argv):
    monkeypatch.setattr(sys, "argv", ["app_docs.py"] + argv)
    cfg = storage.load_config(config(tmp_path, REFUSED[why]))
    said = capsys.readouterr().out
    assert "not taken for this run" in said and "stops until it is changed" in said, said
    assert storage.kind_folders_for(cfg["output_dir"]) is True
    paths = Paths(Path(cfg["output_dir"]))
    assert paths.kind_folders is True
    assert not any(isinstance(f, storage.FlatRoot) for f in paths.filing_folders()), \
        "the documents folder is no filing folder for a repair at start"


@pytest.mark.parametrize("why", sorted(REFUSED))
@pytest.mark.parametrize("argv", [[], ["--all", "--yes"], ["--diagnose", "--all"]],
                         ids=lambda a: " ".join(a) or "no flags")
def test_a_refused_setting_stops_a_run_that_may_save_with_the_same_words(
        tmp_path, monkeypatch, capsys, why, argv):
    monkeypatch.setattr(sys, "argv", ["app_docs.py"] + argv)
    with pytest.raises(SystemExit) as stop:
        storage.load_config(config(tmp_path, REFUSED[why]))
    assert "stopped before saving or moving anything" in str(stop.value)
    assert capsys.readouterr().out == ""


def test_a_setting_that_is_taken_is_taken_for_login_too(tmp_path, monkeypatch, capsys):
    """The control. kind_folders false with a documents folder of its own
    and names that say the kind is taken whatever the run."""
    monkeypatch.setattr(sys, "argv", ["app_docs.py", "--login"])
    cfg = storage.load_config(config(tmp_path, {
        "kind_folders": False, "documents_dir": "Watched",
        "filename_pattern": "{date} {summary} {kind}"}))
    assert storage.kind_folders_for(cfg["output_dir"]) is False
    assert capsys.readouterr().out == ""
