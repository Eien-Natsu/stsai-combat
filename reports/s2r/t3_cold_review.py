#!/usr/bin/env python3
"""Drive the S2R cold review in an environment with no reachable credentials.

    python reports/s2r/t3_cold_review.py --package <stsai_s2_review_*.zip> \
        --checkout <empty dir for a fresh clone> --out <round output dir> \
        --venv <python venv> --lock reports/s2r/artifact_lock.json

Every step runs as its own process with a scrubbed environment - HOME points at an
empty directory, PATH holds only the venv and the system binaries, and no token
variable survives - so the code under review cannot read an SSH key, a keyring or
a GitHub token even though they exist on the host. Each step's cwd, command, start
and end times, exit code and complete output go to `<out>/logs`, and the summary is
written to `<out>/cold_review.json`.

Steps stop at the first non-zero exit: a later step run against a half-built tree
produces evidence that looks like a result and is not one.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, help="the .zip delivery attachment")
    parser.add_argument("--checkout", required=True, help="an empty directory for the fresh clone")
    parser.add_argument("--out", required=True)
    parser.add_argument("--venv", required=True, help="python prefix; cmake is expected in its bin")
    parser.add_argument("--lock", default=None)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()

    package = Path(args.package).resolve()
    checkout = Path(args.checkout).resolve()
    out = Path(args.out).resolve()
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    home = out / "isolated-home"
    home.mkdir(parents=True, exist_ok=True)
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    venv_bin = Path(args.venv).resolve() / "bin"
    python = str(venv_bin / "python")

    env = {"HOME": str(home), "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin",
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(tmp),
           "PYTHONDONTWRITEBYTECODE": "1"}

    rows = []

    def run(name, command, cwd, timeout=None):
        started = stamp()
        clock = time.time()
        try:
            result = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True,
                                    text=True, timeout=timeout or args.timeout)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as expired:
            code, stdout, stderr = "TIMEOUT", expired.stdout or "", expired.stderr or ""
        elapsed = time.time() - clock
        (logs / f"{name}.stdout.log").write_text(stdout, encoding="utf-8")
        (logs / f"{name}.stderr.log").write_text(stderr, encoding="utf-8")
        (logs / f"{name}.command.txt").write_text(
            f"cwd: {cwd}\ncommand: {' '.join(map(str, command))}\n"
            f"env: HOME={env['HOME']} PATH={env['PATH']}\n"
            f"started: {started}\nfinished: {stamp()}\nelapsed_seconds: {elapsed:.1f}\n"
            f"exit_code: {code}\n", encoding="utf-8")
        print(f"{str(code):>8s} {name:26s} {elapsed:7.1f}s  {' '.join(map(str, command))[:90]}",
              flush=True)
        rows.append({"step": name, "command": [str(part) for part in command], "cwd": str(cwd),
                     "started": started, "finished": stamp(), "elapsed_seconds": round(elapsed, 1),
                     "exit_code": code,
                     "stdout_log": str(logs / f"{name}.stdout.log"),
                     "stderr_log": str(logs / f"{name}.stderr.log")})
        return code

    def finish(status):
        summary = {"kind": "s2r_cold_review", "status": status, "package": str(package),
                   "checkout": str(checkout), "out": str(out), "python": python,
                   "jobs": args.jobs, "timeout_seconds": args.timeout,
                   "environment": {"HOME": env["HOME"], "PATH": env["PATH"],
                                   "ssh_dir_exists": (home / ".ssh").exists(),
                                   "gh_config_exists": (home / ".config/gh").exists(),
                                   "token_variables": [k for k in os.environ
                                                       if "TOKEN" in k.upper() or "KEY" in k.upper()],
                                   "gcc": subprocess.run(["gcc", "--version"], env=env,
                                                         capture_output=True, text=True
                                                         ).stdout.splitlines()[:1],
                                   "cmake": subprocess.run(["cmake", "--version"], env=env,
                                                           capture_output=True, text=True
                                                           ).stdout.splitlines()[:1]},
                   "steps": rows}
        (out / "cold_review.json").write_text(json.dumps(summary, indent=2, sort_keys=True),
                                              encoding="utf-8")
        print(f"cold review: {status}; summary in {out / 'cold_review.json'}")
        raise SystemExit(0 if status == "PASS" else 1)

    # 0. the package is verified before anything is unpacked, then extracted by the
    #    checker itself: it refuses an archive with unsafe members and extracts only
    #    the rest.
    lock = ["--lock", str(Path(args.lock).resolve())] if args.lock else []
    command = [python, str(ROOT / "review" / "check_review_inputs.py"), "--repo", str(ROOT),
               "--package", str(package), "--work", str(out / "work"),
               "--out", str(out / "input_receipt.json"), *lock]
    if run("00_verify_and_extract", command, ROOT) != 0:
        finish("BLOCKED at attachments")
    extracted = out / "work" / "package"

    # 1. fresh clone from the package's own bundle, no reuse of an existing build
    if checkout.exists() and any(checkout.iterdir()):
        shutil.rmtree(checkout)
    checkout.mkdir(parents=True, exist_ok=True)
    if run("01_clone_bundle",
           ["git", "clone", str(extracted / "repo.bundle"), str(checkout)],
           out) != 0:
        finish("BLOCKED at clone")
    if run("02_checkout_pinned_commit",
           ["git", "-C", str(checkout), "checkout", "--detach",
            json.loads((extracted / "provenance.json").read_text())["head"]], out) != 0:
        finish("BLOCKED at checkout")

    # 2. the same contract, now against the checkout that will be reviewed
    command = [python, str(ROOT / "review" / "check_review_inputs.py"), "--repo", str(checkout),
               "--package", str(extracted), "--out", str(out / "input_receipt_checkout.json"), *lock]
    if run("03_contract_against_checkout", command, ROOT) != 0:
        finish("BLOCKED at contract")

    # 3. the review chain: attachments, cold build, import, intent, tests, counterfactual, smoke
    command = [python, str(ROOT / "review" / "run_review.py"), "--repo", str(checkout),
               "--package", str(extracted), "--sources", str(extracted / "native_sources.tar.gz"),
               "--model", str(extracted / "model/D384_s17_selected.pt"),
               "--jobs", str(args.jobs), "--timeout", str(int(args.timeout)),
               "--work", str(out / "work/review"), "--receipt", str(out / "review_receipt.json")]
    review_code = run("04_run_review", command, ROOT)

    # 4. independent recomputation of the paired statistics from the raw episodes
    command = [python, str(ROOT / "review" / "recompute_s2.py"), "--package", str(extracted),
               "--out", str(out / "recomputed_s2.json")]
    recompute_code = run("05_recompute_s2", command, ROOT)

    status = "PASS" if review_code == 0 and recompute_code == 0 else "FAIL"
    finish(status)


if __name__ == "__main__":
    main()
