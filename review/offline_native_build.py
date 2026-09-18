#!/usr/bin/env python3
"""Build the native extension from the offline source snapshot. No network.

    python review/offline_native_build.py --repo <checkout of repo.bundle> \
        --sources <native_sources.tar.gz> [--out <build dir>]

Verifies every file in the snapshot against native_sources_manifest.json before
building anything, uses the bridge and CMakeLists from the repository checkout
(not from the snapshot), then imports the module and prints build_info.

The snapshot is POST_PATCH, so the engine patches are deliberately NOT applied.

Compiling successfully is not original-game verification: the script asserts
game_differential_verified is still false rather than treating a build as parity.
Exit status is non-zero if any step fails; a missing toolchain reports NOT_RUN.
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


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="checkout of repo.bundle")
    parser.add_argument("--sources", required=True, help="native_sources.tar.gz")
    parser.add_argument("--manifest", default=None, help="defaults to the manifest beside --sources")
    parser.add_argument("--out", default=None)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    sources = Path(args.sources).resolve()
    manifest_path = Path(args.manifest) if args.manifest else sources.with_name("native_sources_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256(sources) != manifest["archive_sha256"]:
        raise SystemExit("snapshot archive hash does not match the manifest")

    work = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="stsai-native-"))
    work.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sources) as tar:
        tar.extractall(work / "src")
    snapshot = work / "src" / "native_sources"

    bad = []
    for entry in manifest["files"]:
        path = snapshot / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            bad.append(entry["path"])
    if bad:
        raise SystemExit(f"{len(bad)} snapshot files failed verification, e.g. {bad[:5]}")
    print(f"snapshot verified: {len(manifest['files'])} files, patch state {manifest['patch_state'][:11]}")

    for tool in ("cmake",):
        if shutil.which(tool) is None:
            print(f"NOT_RUN: {tool} is not on PATH; the snapshot is verified but cannot be built here")
            raise SystemExit(2)
    if shutil.which("c++") is None and shutil.which("g++") is None:
        print("NOT_RUN: no C++ compiler on PATH")
        raise SystemExit(2)

    engine = snapshot / "sts_lightspeed"
    lock = json.loads((repo / "engine_lock.json").read_text(encoding="utf-8"))
    pybind11_dir = snapshot / "pybind11" / "share" / "cmake" / "pybind11"
    build = work / "build"
    module_dir = work / "module"
    module_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["cmake", "-S", str(repo / "native"), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
           f"-DSTS_ENGINE_DIR={engine}",
           f"-DSTSAI_ENGINE_REVISION={lock['revision']}",
           f"-DSTSAI_ENGINE_PATCHES={','.join(p['sha256'] for p in lock['patches'])}",
           f"-DPython_EXECUTABLE={sys.executable}",
           f"-Dpybind11_DIR={pybind11_dir}",
           f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={module_dir}",
           f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE={module_dir}"]
    subprocess.run(cmd, check=True)
    subprocess.run(["cmake", "--build", str(build), "--config", "Release",
                    "--parallel", str(args.jobs)], check=True)

    probe = subprocess.run([sys.executable, "-c",
                            "import sys;sys.path.insert(0,sys.argv[1]);"
                            "import _lightspeed as m;print(m.build_info())", str(module_dir)],
                           capture_output=True, text=True, check=True)
    info = eval(probe.stdout.strip())  # noqa: S307 - our own build's dict repr
    print("build_info:", info)
    assert info["revision"] == lock["revision"], info
    assert info["patches"] == [p["sha256"] for p in lock["patches"]], info
    assert info["game_differential_verified"] is False, \
        "a successful build is not original-game verification"
    print("offline build OK; game_differential_verified stays false")
    if not args.out:
        print("artifacts in", work)


if __name__ == "__main__":
    main()
