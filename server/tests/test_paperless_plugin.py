"""The Paperless plug-in copies a run's new documents, and only copies them.

It is run the way the panel runs it, as a program of its own with the run's
description on stdin, and its folders are throwaway ones. A consume folder
deletes what it imports, so PaperPull's own files must stay where they are,
and Paperless must never be handed half a file.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "paperless"


def run(event, consume, **env):
    """(exit code, what it said) for one run of the plug-in."""
    full = dict(os.environ, PAPERLESS_CONSUME_DIR=str(consume))
    full.pop("PAPERLESS_SUBFOLDERS", None)
    full.update(env)
    done = subprocess.run([sys.executable, "paperless.py"], cwd=PLUGIN,
                          input=event if isinstance(event, str) else json.dumps(event),
                          capture_output=True, text=True, env=full, timeout=60)
    return done.returncode, (done.stdout + done.stderr).strip()


@pytest.fixture()
def saved(tmp_path):
    """Two documents a run saved, and a spreadsheet beside them."""
    folder = tmp_path / "data" / "Shop Receipts" / "In-Store"
    folder.mkdir(parents=True)
    one = folder / "2026-01-02 Shop Receipt.pdf"
    two = folder / "2026-01-09 Shop Receipt.pdf"
    one.write_bytes(b"%PDF-1.7 one")
    two.write_bytes(b"%PDF-1.7 two")
    sheet = tmp_path / "data" / "Shop Receipts" / "Shop Order History.csv"
    sheet.write_text("date,total\n", encoding="utf-8")
    return [one, two, sheet]


def event_for(files, provider="Shop Receipts"):
    return {"event": "run-finished", "version": 1, "provider": provider,
            "new_files": [str(f) for f in files]}


def test_each_new_document_is_copied_and_kept(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()

    code, said = run(event_for(saved), consume)

    assert code == 0 and "Copied 2 new documents" in said, said
    assert sorted(p.name for p in consume.iterdir()) == [saved[0].name, saved[1].name]
    assert (consume / saved[0].name).read_bytes() == b"%PDF-1.7 one"
    assert all(p.is_file() for p in saved), "PaperPull's own files stay"


def test_only_documents_go_to_paperless(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    run(event_for(saved), consume)
    assert not list(consume.glob("*.csv"))


def test_nothing_half_written_is_left_for_paperless(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    run(event_for(saved), consume)
    assert not [p for p in consume.iterdir() if p.name.startswith(".")]


def test_the_same_file_twice_is_left_alone(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    run(event_for(saved[:1]), consume)

    code, said = run(event_for(saved[:1]), consume)

    assert code == 0 and "Copied 0 new documents" in said and "1 was already there" in said
    assert len(list(consume.iterdir())) == 1


def test_another_file_of_the_same_name_gets_a_number(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    (consume / saved[0].name).write_bytes(b"%PDF-1.7 somebody else's")

    run(event_for(saved[:1]), consume)

    numbered = consume / ("%s (2).pdf" % saved[0].stem)
    assert numbered.read_bytes() == b"%PDF-1.7 one"
    assert (consume / saved[0].name).read_bytes() == b"%PDF-1.7 somebody else's"


def test_with_no_consume_folder_nothing_is_copied(saved, tmp_path):
    code, said = run(event_for(saved), tmp_path / "not mounted")
    assert code == 0 and "No Paperless folder is mounted" in said
    assert not (tmp_path / "not mounted").exists()


def test_subfolders_name_the_provider_and_stay_inside(saved, tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()

    run(event_for(saved[:1], provider="Shop Receipts"), consume, PAPERLESS_SUBFOLDERS="1")
    run(event_for(saved[1:2], provider="../../outside"), consume, PAPERLESS_SUBFOLDERS="1")

    assert (consume / "Shop Receipts" / saved[0].name).is_file()
    inside = [p for p in consume.rglob("*.pdf")]
    assert len(inside) == 2 and not (tmp_path / "outside").exists()


def test_a_run_with_no_new_documents_says_nothing(tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    assert run(event_for([]), consume) == (0, "")


def test_a_description_it_cannot_read_copies_nothing(tmp_path):
    code, said = run("not json", tmp_path)
    assert code == 1 and "could not be read" in said


def test_the_manifest_says_what_the_panel_needs():
    manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["events"] == ["run-finished"]
    assert manifest["run"] == ["python", "paperless.py"]
