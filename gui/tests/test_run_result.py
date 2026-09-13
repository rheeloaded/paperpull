import asyncio
import io
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import run_result


def line(**overrides):
    return run_result.PREFIX + json.dumps(dict(manual_review=0, failed=0,
            validation_failures=0, new_files=0, **{}) | overrides)


@pytest.mark.parametrize("field", ["manual_review", "failed", "validation_failures"])
def test_any_unresolved_count_requires_attention(field):
    assert run_result.parse(line(**{field: 1}))["attention"]
    assert not run_result.parse(line(new_files=4))["attention"]


@pytest.mark.parametrize("value", ["ordinary output", run_result.PREFIX + "{}",
    run_result.PREFIX + "null", run_result.PREFIX + "broken", line(failed=-1), line(failed=True)])
def test_invalid_or_incomplete_results_are_not_success(value):
    assert run_result.parse(value) is None


def test_result_drops_unexpected_private_fields():
    result = run_result.parse(line(account="synthetic", path="private/example"))
    assert "account" not in result and "path" not in result


def test_stream_carries_current_counts_and_keeps_exit_code(tmp_path, monkeypatch):
    class Process:
        def __init__(self, *args, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("ordinary output\n" + line(manual_review=4) + "\n")
        def wait(self, **kwargs): return 0
        def poll(self): return 0
    monkeypatch.setattr(app, "discover_apps", lambda: {"example": {"dir": str(tmp_path)}})
    monkeypatch.setattr(app, "_build_cmd", lambda *args: ["synthetic-command"])
    monkeypatch.setattr(app.subprocess, "Popen", Process)
    async def consume():
        return "".join([part async for part in app.api_run("example", action="all").body_iterator])
    output = asyncio.run(consume())
    assert '"attention": true' in output
    assert '"manual_review": 4' in output
    assert "event: result" in output and "event: done\ndata: 0" in output
    assert run_result.PREFIX not in output
    assert "example" not in app._RUNNING
