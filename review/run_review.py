#!/usr/bin/env python3
"""Re-run the S1R checks from this package in one command; non-zero on failure.

    python review/run_review.py --repo <checkout of repo.bundle> \
        --sources native_sources.tar.gz [--package <unpacked package>] [--model model/policy_weights.pt]

Order, and it matters:

  attachments   every file in the package manifest still hashes as recorded
  sources       the offline snapshot hashes as its manifest says, and the patch
                series applies to it in order (done by the build step)
  native_build  build in a scratch directory from the PRE_PATCH snapshot
  import        the built module is importable as stsai._lightspeed and reports
                the locked revision and patch hashes
  intent        the intent table regenerates from the VERIFIED patched source
  tests         the whole suite, with the native module present, zero skips
  counterfactual replay the shipped public trace and recompute its observation
                hashes against the built engine
  model_smoke   only when a model is supplied: load it and run the 12 shipped
                public observations

Running pytest first and building afterwards would leave the native tests
skipped and the build unverified, and reading a saved boolean is not running the
counterfactual, so the order is enforced here rather than left to the reader.

A required step that cannot run reports NOT_RUN and makes the run non-zero:
"the toolchain is missing" must never come out looking like "checks passed".
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def python(*args, cwd=None, timeout=None):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


class Report:
    """PASS / FAIL / NOT_RUN / TIMEOUT, kept apart on purpose.

    NOT_RUN is "this machine cannot run it"; TIMEOUT is "it was still running
    when its budget ran out". Neither is a failure of the code under review and
    neither is a pass, so both keep the run non-zero when the step is required.
    """
    def __init__(self):
        self.rows = []

    def add(self, name, ok, note, required=True):
        if ok is None:
            status = "NOT_RUN"
        elif isinstance(ok, str):
            status = ok  # an explicit status such as TIMEOUT
        else:
            status = "PASS" if ok else "FAIL"
        self.rows.append({"step": name, "status": status, "note": note, "required": required})
        print(f"{status:8s} {name:14s} {note}", flush=True)

    def exit_code(self):
        blocking = [r for r in self.rows if r["status"] in ("FAIL", "TIMEOUT")
                    or (r["status"] == "NOT_RUN" and r["required"])]
        for status in ("FAIL", "TIMEOUT", "NOT_RUN"):
            rows = [r for r in blocking if r["status"] == status
                    and (status != "NOT_RUN" or r["required"])]
            if rows:
                print(f"{status}: " + ", ".join(r["step"] for r in rows), file=sys.stderr)
        if blocking:
            return 1
        print("all required checks passed on this machine")
        return 0


def step_attachments(package):
    if package is None:
        return None, "no --package given"
    manifest = Path(package) / "MANIFEST.sha256"
    if not manifest.is_file():
        return False, "the package has no MANIFEST.sha256"
    problems = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        path = Path(package) / name.strip()
        if not path.is_file() or sha256(path) != digest:
            problems.append(name.strip())
    return (not problems), (f"{len(problems)} mismatches: {problems[:5]}" if problems
                            else "manifest verified")


def step_build(repo, sources, work, timeout):
    receipt = work / "native_build_receipt.json"
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        result = python(str(HERE / "offline_native_build.py"), "--repo", str(repo), "--sources",
                        str(sources), "--receipt", str(receipt), "--logs", str(logs),
                        "--timeout", str(timeout), cwd=PKG, timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"the build step exceeded {timeout + 60}s of wall clock", {}
    (logs / "offline_build_stdout.log").write_text(
        f"$ offline_native_build.py\nexit code: {result.returncode}\n\n{result.stdout}\n{result.stderr}",
        encoding="utf-8")
    tail = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    detail = json.loads(receipt.read_text()) if receipt.is_file() else {}
    if result.returncode == 2:
        return None, f"NOT_RUN: {detail.get('missing_tool', 'toolchain missing')}", detail
    if result.returncode == 3:
        return "TIMEOUT", detail.get("error", "the build timed out"), detail
    if result.returncode != 0:
        return False, detail.get("error", tail[-1] if tail else "build failed"), detail
    return True, f"built and installed {Path(detail['module_path']).name}", detail


def step_import(repo, build_detail):
    if not build_detail.get("module_path"):
        return None, "the module was not built"
    code = ("import json,sys;sys.path.insert(0,sys.argv[1]);"
            "from stsai import _lightspeed as m;print(json.dumps(m.build_info()))")
    result = python("-c", code, str(Path(repo) / "src"))
    if result.returncode != 0:
        return False, result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "import failed"
    info = json.loads(result.stdout.strip())
    return (info == build_detail.get("build_info")), f"revision {info['revision'][:12]}, {len(info['patches'])} patches"


def step_intent(repo, build_detail):
    source = build_detail.get("engine_source_dir")
    if not source:
        return None, "no verified engine source from the build step"
    monster_cpp = Path(source) / "src" / "combat" / "MonsterSpecific.cpp"
    if not monster_cpp.is_file():
        return False, f"the patched source is missing {monster_cpp}"
    result = python("scripts/gen_intent_table.py", "--verify", "--monster-cpp", str(monster_cpp),
                    cwd=repo)
    tail = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    return result.returncode == 0, tail[-1] if tail else ""


def step_tests(repo, work, build_detail, timeout):
    if not build_detail.get("module_path"):
        return None, "the native module was not built, so the native tests would skip"
    junit = work / "junit.xml"
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(repo) / "src")
    # The cloned checkout has no third_party (it is not tracked); point the intent
    # generator at the patched source the build step just verified instead.
    if build_detail.get("engine_source_dir"):
        env["STSAI_ENGINE_SOURCE_DIR"] = build_detail["engine_source_dir"]
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                                 f"--junitxml={junit}"], cwd=repo, capture_output=True, text=True,
                                env=env, timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        (logs / "pytest.log").write_text(
            f"TIMEOUT after {timeout}s\n{expired.stdout or ''}{expired.stderr or ''}",
            encoding="utf-8")
        return "TIMEOUT", f"pytest did not finish within {timeout}s"
    (logs / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if not junit.is_file():
        return False, "pytest produced no report"
    import xml.etree.ElementTree as ET
    suite = ET.parse(junit).getroot().find("testsuite")
    skipped = int(suite.get("skipped", 0)); tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    native = [c for c in suite.iter("testcase")
              if "native" in (c.get("classname") or "") or "louse" in (c.get("classname") or "")
              or "ambiguity" in (c.get("classname") or "") or "gate" in (c.get("classname") or "")]
    note = (f"{tests} tests, {failures} failed, {skipped} skipped, "
            f"{len(native)} native/regression cases")
    if failures:
        return False, note
    if skipped or not native:
        # A skipped native test means the module was not actually exercised.
        return False, note + " - the native module was not exercised"
    return True, note


def step_counterfactual(repo, work, build_detail, timeout):
    """Replay the shipped public trace and recompute its observation hashes."""
    if not build_detail.get("module_path"):
        return None, "the native module was not built; the counterfactual cannot be replayed"
    trace = Path(repo) / "tests" / "fixtures" / "ambiguity_public_trace.json"
    if not trace.is_file():
        return None, "this package does not ship the public trace"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(repo) / "src")
    out = work / "counterfactual.json"
    try:
        result = subprocess.run([sys.executable, str(HERE / "counterfactual_replay.py"),
                                 "--repo", str(repo), "--trace", str(trace), "--out", str(out)],
                                cwd=repo, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"the replay did not finish within {timeout}s"
    tail = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    if not out.is_file():
        return False, tail[-1] if tail else "the replay produced no result"
    detail = json.loads(out.read_text())
    return result.returncode == 0, (f"{detail['steps_replayed']} steps replayed, "
                                    f"{detail['sampler_seeds']} sampler seeds, "
                                    f"root stable={detail['root_stable']}")


def step_model(repo, model, package, work, build_detail, timeout):
    if model is None:
        return None, "no --model given (expected when the round did not train)"
    if not build_detail.get("module_path"):
        return None, "the native module was not built"
    # The observations and expectations ship beside the weights in the package,
    # which is a different directory from the checkout the tests run in.
    base = Path(package) if package else Path(repo)
    observations = base / "model" / "smoke_observations.jsonl.gz"
    expected = base / "model" / "smoke_expected.json"
    for path in (observations, expected):
        if not path.is_file():
            return False, (f"{path.name} is not in {base} ({'the package' if package else 'the checkout'}"
                           f"); pass --package to point at the directory that ships it")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(repo) / "src")
    try:
        result = subprocess.run([sys.executable, str(HERE / "model_smoke.py"), "--model", str(model),
                                 "--observations", str(observations), "--expected", str(expected),
                                 "--out", str(work / "model_smoke.json")], cwd=repo,
                                capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"the model smoke did not finish within {timeout}s"
    tail = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    return result.returncode == 0, tail[-1] if tail else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sources", default=None, help="native_sources.tar.gz")
    parser.add_argument("--package", default=None, help="the unpacked review package")
    parser.add_argument("--model", default=None, help="a selected inference checkpoint")
    parser.add_argument("--work", default=None)
    parser.add_argument("--receipt", default=None, help="where to write the structured receipt")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="seconds per external step; a step that overruns reports TIMEOUT")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if args.work:
        work = Path(args.work).resolve(); work.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile
        work = Path(tempfile.mkdtemp(prefix="stsai-review-"))

    report = Report()
    ok, note = step_attachments(args.package)
    report.add("attachments", ok, note, required=args.package is not None)

    if args.sources is None:
        report.add("native_build", None, "no --sources given", required=True)
        build_ok, build_note, detail = None, "no --sources given", {}
    else:
        build_ok, build_note, detail = step_build(repo, Path(args.sources).resolve(), work,
                                                  args.timeout)
        report.add("native_build", build_ok, build_note)

    ok, note = step_import(repo, detail)
    report.add("import", ok, note)
    ok, note = step_intent(repo, detail)
    report.add("intent", ok, note)
    ok, note = step_tests(repo, work, detail, args.timeout)
    report.add("tests", ok, note)
    ok, note = step_counterfactual(repo, work, detail, args.timeout)
    report.add("counterfactual", ok, note)
    ok, note = step_model(repo, Path(args.model).resolve() if args.model else None,
                          Path(args.package).resolve() if args.package else None, work, detail,
                          args.timeout)
    report.add("model_smoke", ok, note, required=args.model is not None)

    receipt = Path(args.receipt).resolve() if args.receipt else work / "review_receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(
        {"repo": str(repo), "sources": args.sources, "package": args.package,
         "steps": report.rows}, indent=2) + "\n", encoding="utf-8")
    print(f"receipt: {receipt}")
    raise SystemExit(report.exit_code())


if __name__ == "__main__":
    main()
