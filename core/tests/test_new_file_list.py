"""Every provider must replace the previous run's import list, even when empty."""
import ast
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from paperpull_core.storage import atomic_write_text, now_iso

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (ROOT / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_empty_run_replaces_previous_download_list(entry, tmp_path):
    # Exercise the actual method without importing browser code or reading configs.
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "write_run_summary")
    # The method is exec'd in isolation, so every name it reaches for must be
    # supplied here. report_run_result arrived with #19 after this test was
    # written, and every app failed until it was stubbed. It prints a
    # counts-only line for the panel, which this test does not care about.
    scope = {"atomic_write_text": atomic_write_text, "now_iso": now_iso,
             "report_run_result": lambda stats: None}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(entry), "exec"), scope)
    stats = defaultdict(int, started="2026-01-01T00:00:00", mode="all",
                        dates=[], dates_processed=[], new_files=["Statements/synthetic.pdf"])
    app = SimpleNamespace(stats=stats, paths=SimpleNamespace(root=tmp_path,
                          run_summary=tmp_path / "run-summary.txt"))
    scope["write_run_summary"](app)
    listing = tmp_path / "new-this-run.txt"
    assert "Statements/synthetic.pdf" in listing.read_text()
    stats["new_files"] = []
    scope["write_run_summary"](app)
    lines = listing.read_text().splitlines()
    assert lines[0].startswith("# 0 file(s)")
    assert not [line for line in lines if line.strip() and not line.startswith("#")]
    # Repeated empty runs must not resurrect old entries.
    scope["write_run_summary"](app)
    assert "Statements/synthetic.pdf" not in listing.read_text()
