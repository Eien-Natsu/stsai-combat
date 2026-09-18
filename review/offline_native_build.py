#!/usr/bin/env python3
"""Build the native extension from the offline PRE_PATCH snapshot. No network.

    python review/offline_native_build.py --repo <checkout of repo.bundle> \
        --sources native_sources.tar.gz [--out <build dir>] [--receipt <json>]

Steps, in order:
  1. hash the snapshot archive against its manifest;
  2. verify every file in it, and that the engine files really are PRE_PATCH;
  3. apply engine_lock.json's patch series, in the declared order, to a copy of
     the snapshot - the compiled tree is base + patches by construction;
  4. configure and build with cmake in a scratch directory;
  5. install the module into the checkout so `stsai._lightspeed` imports it;
  6. import it and check build_info against the lock.

Compiling successfully is not original-game verification: the script asserts
game_differential_verified is still false rather than treating a build as parity.

Exit status: 0 built, 1 failed, 2 NOT_RUN (no toolchain) - a required step that
could not run must not look like a pass.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, cwd=None, check=True):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(map(str, command))}\n"
                         f"{result.stdout}{result.stderr}")
    return result


def log(receipt, step, **fields):
    receipt.setdefault("steps", []).append({"step": step, **fields})
    print(f"[{step}] " + json.dumps(fields)[:300], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="checkout of repo.bundle")
    parser.add_argument("--sources", required=True, help="native_sources.tar.gz")
    parser.add_argument("--manifest", default=None, help="defaults to the manifest beside --sources")
    parser.add_argument("--out", default=None)
    parser.add_argument("--receipt", default=None, help="write the structured result here")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    # The patch helpers come from the checkout under review, not from this
    # package: the package ships repo.bundle, not a copy of the repository.
    sys.path.insert(0, str(repo / "scripts"))
    from engine_patches import touched_files
    sources = Path(args.sources).resolve()
    manifest_path = Path(args.manifest) if args.manifest else sources.with_name("native_sources_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = json.loads((repo / "engine_lock.json").read_text(encoding="utf-8"))
    receipt = {"snapshot": str(sources), "repo": str(repo), "steps": []}

    def finish(status, code):
        receipt["status"] = status
        if args.receipt:
            Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(code)

    if sha256(sources) != manifest["archive_sha256"]:
        receipt["error"] = "snapshot archive hash does not match the manifest"
        finish("FAIL", 1)
    log(receipt, "snapshot_archive", sha256=sha256(sources), verified=True)

    work = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="stsai-native-"))
    work.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sources) as tar:
        tar.extractall(work / "src", filter="data")
    snapshot = work / "src" / "native_sources"

    bad = [entry["path"] for entry in manifest["files"]
           if not (snapshot / entry["path"]).is_file()
           or sha256(snapshot / entry["path"]) != entry["sha256"]]
    if bad:
        receipt["error"] = f"{len(bad)} snapshot files failed verification"
        receipt["bad_files"] = bad[:10]
        finish("FAIL", 1)
    if manifest["engine"]["base_revision"] != lock["revision"]:
        receipt["error"] = "snapshot base revision differs from the lock"
        finish("FAIL", 1)
    if manifest["engine"]["patch_order"] != lock["patches"]:
        receipt["error"] = "snapshot patch order differs from the lock"
        finish("FAIL", 1)
    engine_states = {entry["patch_state"] for entry in manifest["files"]
                     if entry["origin"] == "sts_lightspeed"}
    if engine_states != {"PRE_PATCH"}:
        receipt["error"] = f"engine files are not PRE_PATCH: {sorted(engine_states)}"
        finish("FAIL", 1)
    log(receipt, "snapshot_files", verified=len(manifest["files"]), patch_state="PRE_PATCH")

    # 3. base + patches, in the declared order, on a copy of the snapshot.
    engine = work / "engine"
    shutil.copytree(snapshot / "sts_lightspeed", engine)
    applied = []
    for entry in lock["patches"]:
        patch = (repo / entry["file"]).resolve()
        if not patch.is_file() or sha256(patch) != entry["sha256"]:
            receipt["error"] = f"patch {entry['file']} is missing or does not match the lock"
            finish("FAIL", 1)
        result = run(["git", "apply", str(patch)], cwd=engine, check=False)
        applied.append({"patch": entry["file"], "command": ["git", "apply", str(patch)],
                        "returncode": result.returncode,
                        "stderr": result.stderr.strip()[:400]})
        if result.returncode != 0:
            receipt["patches_applied"] = applied
            receipt["error"] = f"{entry['file']} did not apply to the locked base"
            finish("FAIL", 1)
    receipt["patches_applied"] = applied
    post = {name: sha256(engine / name) for name in sorted(touched_files(repo, lock["patches"]))}
    receipt["post_patch_hashes"] = post
    log(receipt, "patch_series", applied=len(applied), files=sorted(post))

    for tool in ("cmake",):
        if shutil.which(tool) is None:
            receipt["missing_tool"] = tool
            finish("NOT_RUN", 2)
    if shutil.which("c++") is None and shutil.which("g++") is None:
        receipt["missing_tool"] = "c++ compiler"
        finish("NOT_RUN", 2)

    # 4. build.
    build = work / "build"
    module_dir = work / "module"
    module_dir.mkdir(parents=True, exist_ok=True)
    pybind11_dir = snapshot / "pybind11" / "share" / "cmake" / "pybind11"
    run(["cmake", "-S", str(repo / "native"), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
         f"-DSTS_ENGINE_DIR={engine}",
         f"-DSTSAI_ENGINE_REVISION={lock['revision']}",
         f"-DSTSAI_ENGINE_PATCHES={','.join(p['sha256'] for p in lock['patches'])}",
         f"-DPython_EXECUTABLE={sys.executable}",
         f"-Dpybind11_DIR={pybind11_dir}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={module_dir}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE={module_dir}"])
    run(["cmake", "--build", str(build), "--config", "Release", "--parallel", str(args.jobs)])
    log(receipt, "build", ok=True, directory=str(build))

    # 5. make it importable by the checkout's own package.
    built = sorted(module_dir.glob("_lightspeed*.so"))
    if not built:
        receipt["error"] = "the build produced no module"
        finish("FAIL", 1)
    target = repo / "src" / "stsai" / built[0].name
    shutil.copy2(built[0], target)
    receipt["module_path"] = str(target)
    log(receipt, "installed", module=target.name)

    # 6. import it the way the tests do, and check what it reports it was built from.
    probe = run([sys.executable, "-c",
                 "import json,sys;sys.path.insert(0,sys.argv[1]);"
                 "from stsai import _lightspeed as m;print(json.dumps(m.build_info()))",
                 str(repo / "src")])
    info = json.loads(probe.stdout.strip())
    receipt["build_info"] = info
    if info["revision"] != lock["revision"]:
        receipt["error"] = "the module reports a different revision"
        finish("FAIL", 1)
    if info["patches"] != [p["sha256"] for p in lock["patches"]]:
        receipt["error"] = "the module reports a different patch series"
        finish("FAIL", 1)
    if info["game_differential_verified"] is not False:
        receipt["error"] = "a build must not claim original-game verification"
        finish("FAIL", 1)
    receipt["engine_source_dir"] = str(engine)
    log(receipt, "import", revision=info["revision"][:12], patches=len(info["patches"]))
    print(f"engine sources for the intent generator: {engine}")
    print(f"artifacts in {work}")
    finish("PASS", 0)


if __name__ == "__main__":
    main()
