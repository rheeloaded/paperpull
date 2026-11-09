import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_spec_attributes():
    assert storage.SPEC.provider == "Discover Bank"
    assert storage.SPEC.base_url == "https://bank.discover.com/"
    assert "Discover Bank Document Index.csv" in [c.filename for c in storage.SPEC.csv_files]
    assert "Statements" in [f.name for f in storage.SPEC.folders]
    assert "statements" in [f.attr for f in storage.SPEC.folders]
    assert "statements" in [f.name.lower() for f in storage.SPEC.folders]


def test_provider_string():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") == "2026-01-02 Discover Bank Thing Statement.pdf"


def test_csv_filenames(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "Discover Bank Document Index.csv"


def test_precreated_folders(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Logs', 'Manual Review', 'Statements']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()


def test_the_orchestrator_imports(tmp_path):
    """Verifies that discoverbank_docs and docs.App can be imported and initialized."""
    import discoverbank_docs as docs

    assert hasattr(docs, "main")
    assert hasattr(docs, "App")

    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({
            "owner": "Test Person",
            "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "prof"),
        }),
        encoding="utf-8",
    )
    args = docs.build_parser().parse_args(["--config", str(cfg)])
    app = docs.App(args)
    assert app is not None
    assert app.config["owner"] == "Test Person"
    app.close()
