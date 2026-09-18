"""`--jobs` must reach the compile step, not stop at the wrapper.

`offline_native_build.py` defaults to `min(4, cpu_count)` workers on its own, which
is over the project's two-worker budget, so `run_review.py` forwards the value
explicitly and defaults it to 2.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "review"))

import run_review  # noqa: E402


def test_the_wrapper_defaults_to_two_workers():
    assert run_review.build_parser().parse_args(["--repo", "r"]).jobs == 2


def test_jobs_reaches_the_offline_build_command(tmp_path, monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_python(*args, cwd=None, timeout=None):
        captured["command"] = args
        return Result()

    monkeypatch.setattr(run_review, "python", fake_python)
    work = tmp_path / "work"
    (work / "logs").mkdir(parents=True)
    (work / "native_build_receipt.json").write_text(json.dumps({"module_path": "/x/_lightspeed.so"}))
    run_review.step_build(tmp_path, tmp_path / "sources.tar.gz", work, 60, 7)
    command = captured["command"]
    assert command[command.index("--jobs") + 1] == "7"


def test_the_command_line_value_reaches_the_build_step(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(run_review, "step_build",
                        lambda *a, **k: captured.update(jobs=a[4]) or (True, "stub", {}))
    work = tmp_path / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["run_review.py", "--repo", str(tmp_path),
                                      "--sources", str(tmp_path / "sources.tar.gz"),
                                      "--work", str(work), "--jobs", "5"])
    with pytest.raises(SystemExit):
        run_review.main()
    assert captured["jobs"] == 5
