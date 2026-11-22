"""A sign-in checkpoint that cannot be read stops Continue rather than being
guessed at, since it is the proof of the account the run began on. Every
value here is made up."""
import json
from pathlib import Path
import sys

import pytest

from paperpull_core.listing import ListNotRead

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_docs as connector

GOOD = {"scope": {name: None for name in connector.RESUME_SCOPE}, "pending": ["a" * 64],
        "source": "https://healthy.kaiserpermanente.org/northern-california/secure/my-documents",
        "anchors": ["b" * 64]}


def app(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic", "output_dir": str(tmp_path / "archive"),
                                  "profile_dir": str(tmp_path / "profile")}))
    monkeypatch.setattr(connector.App, "_setup_logging", lambda self: None)
    return connector.App(connector.build_parser().parse_args(["--config", str(config), "--resume"]))


@pytest.mark.parametrize("damaged", [
    "{not json", "[]", json.dumps({**GOOD, "scope": {}}), json.dumps({**GOOD, "anchors": None}),
    json.dumps({**GOOD, "pending": "a"}), json.dumps({**GOOD, "anchors": [7]}),
])
def test_a_damaged_checkpoint_stops_continue(tmp_path, monkeypatch, damaged):
    kaiser = app(tmp_path, monkeypatch)
    kaiser._sign_in_resume.write_text(damaged, encoding="utf-8")
    with pytest.raises(ListNotRead):
        kaiser._sign_in_checkpoint()
    assert kaiser._sign_in_checkpoint(strict=False) is None


def test_a_whole_checkpoint_is_read(tmp_path, monkeypatch):
    kaiser = app(tmp_path, monkeypatch)
    kaiser._sign_in_resume.write_text(json.dumps(GOOD), encoding="utf-8")
    assert kaiser._sign_in_checkpoint() == GOOD
    kaiser._sign_in_resume.unlink()
    assert kaiser._sign_in_checkpoint() is None
