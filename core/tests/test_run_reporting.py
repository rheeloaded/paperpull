import ast
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from paperpull_core.run_reporting import report_run_result, PREFIX
from paperpull_core.storage import atomic_write_text, now_iso

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for base in (ROOT / "apps",)
                 for p in base.glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_each_provider_reports_current_run_counts(entry, tmp_path, capsys):
    # Execute the actual summary method, without loading browsers or private configs.
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "write_run_summary")
    scope = {"atomic_write_text": atomic_write_text, "now_iso": now_iso,
             "report_run_result": report_run_result}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(entry), "exec"), scope)
    stats = defaultdict(int, started="2026-01-01T00:00:00", mode="all", dates=[], dates_processed=[],
                        new_files=["Statements/synthetic.pdf"], manual_review=2)
    app = SimpleNamespace(stats=stats, paths=SimpleNamespace(root=tmp_path,
                          run_summary=tmp_path / "run-summary.txt"))
    scope["write_run_summary"](app)
    assert "Statements/synthetic.pdf" in (tmp_path / "new-this-run.txt").read_text()
    stats.update(new_files=[], manual_review=0)
    scope["write_run_summary"](app)
    reports = [json.loads(line[len(PREFIX):]) for line in capsys.readouterr().out.splitlines()
               if line.startswith(PREFIX)]
    assert reports[0]["manual_review"] == 2
    assert reports[1] == {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_interrupt_saves_progress_and_returns_nonzero(entry):
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    saved = []
    class FakeApp:
        def __init__(self, args):
            self.stats = {"mode": "all"}
            self.progress = SimpleNamespace(save=lambda: saved.append("progress"))
            self.discovery = SimpleNamespace(save=lambda: saved.append("discovery"))
        def cmd_run(self, *args, **kwargs): raise KeyboardInterrupt
        def write_run_summary(self): saved.append("summary")
        def close(self): saved.append("closed")
    args = SimpleNamespace(start_date=None, end_date=None, open_browser=False,
                           login=False, discover=False, pilot=False, all=True,
                           pilot_online=False, pilot_instore=False, online=False, instore=False)
    scope = {"ONLINE": "Online", "IN_STORE": "In-Store", "App": FakeApp, "build_parser": lambda: SimpleNamespace(parse_args=lambda argv: args)}
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(entry), "exec"), scope)
    assert scope["main"]([]) == 130
    assert saved == ["progress", "discovery", "summary", "closed"]
