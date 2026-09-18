#!/usr/bin/env python3
"""Snapshot the redistributable sources needed to build the native extension offline.

The review containers have no route to GitHub or PyPI, so three previous rounds
could only skip the native tests. This collects the minimum that compiles:
the locked sts_lightspeed `src`/`include`, the nlohmann/json headers it needs,
the pybind11 headers and CMake support files, and every licence.

The snapshot is PRE_PATCH: the engine files are the locked revision's own
copies, taken from the commit rather than from the patched working tree, and
review/offline_native_build.py applies engine_lock.json's series to them in
order. That makes "the compiled source is base + patches" true by construction
instead of a claim to be checked afterwards. Vendored files (json, pybind11)
are PRISTINE and take no patches.

The manifest records all of it per file: origin, licence, hash and patch state,
plus the base revision and the patch order.
"""
import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "third_party" / "sts_lightspeed"
SITE = ROOT / ".venv" / "lib" / "python3.12" / "site-packages"
PYBIND11 = SITE / "pybind11"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args, cwd=UPSTREAM):
    return subprocess.check_output(["git", *args], cwd=cwd)


def stage_engine(stage: Path):
    """The locked revision's src/include, written out unpatched."""
    entries = []
    names = git("ls-files", "src", "include").decode().split()
    for name in names:
        dest = stage / "sts_lightspeed" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git("show", f"HEAD:{name}"))
        entries.append((f"sts_lightspeed/{name}", dest, "sts_lightspeed", "MIT", "PRE_PATCH"))
    licence = stage / "sts_lightspeed/LICENSE.md"
    licence.write_bytes(git("show", "HEAD:LICENSE.md"))
    entries.append(("sts_lightspeed/LICENSE.md", licence, "sts_lightspeed", "MIT", "PRE_PATCH"))
    return entries


def stage_copy(stage: Path, source: Path, name: str, origin: str, licence: str):
    dest = stage / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())
    return (name, dest, origin, licence, "PRISTINE")


def stage_vendored(stage: Path):
    entries = []
    # nlohmann/json must sit inside the engine dir: the CMake adds
    # ${STS_ENGINE_DIR}/json/single_include to the include path.
    for relative in ("single_include/nlohmann/json.hpp", "include/nlohmann/json.hpp"):
        path = UPSTREAM / "json" / relative
        if path.is_file():
            entries.append(stage_copy(stage, path, f"sts_lightspeed/json/{relative}",
                                      "nlohmann/json", "MIT"))
    for relative in ("LICENSE.MIT", "LICENSE.md"):
        path = UPSTREAM / "json" / relative
        if path.is_file():
            entries.append(stage_copy(stage, path, "sts_lightspeed/json/LICENSE.MIT",
                                      "nlohmann/json", "MIT"))
            break
    for path in sorted((PYBIND11 / "include").rglob("*")):
        if path.is_file():
            entries.append(stage_copy(stage, path,
                                      f"pybind11/include/{path.relative_to(PYBIND11 / 'include')}",
                                      "pybind11", "BSD-3-Clause"))
    for path in sorted((PYBIND11 / "share").rglob("*")):
        if path.is_file():
            entries.append(stage_copy(stage, path,
                                      f"pybind11/share/{path.relative_to(PYBIND11 / 'share')}",
                                      "pybind11", "BSD-3-Clause"))
    # pybind11 ships its licence inside the dist-info directory, next to the
    # package rather than in it. The earlier snapshot looked in the package and
    # therefore shipped no pybind11 licence at all.
    version = (PYBIND11 / "_version.py").read_text(encoding="utf-8").split('"')[1]
    licence = SITE / f"pybind11-{version}.dist-info" / "LICENSE"
    if not licence.is_file():
        raise SystemExit(f"pybind11 {version} has no LICENSE at {licence}")
    text = licence.read_text(encoding="utf-8")
    if "BSD 3-Clause" not in text and "Redistribution and use in source and binary" not in text:
        raise SystemExit("the pybind11 licence is not the expected BSD-3-Clause text")
    entries.append(stage_copy(stage, licence, f"pybind11/LICENSE.pybind11-{version}",
                              "pybind11", "BSD-3-Clause"))
    return entries, version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tar", default="native/native_sources.tar.gz")
    parser.add_argument("--manifest", default="native/native_sources_manifest.json")
    args = parser.parse_args()
    lock = json.loads((ROOT / "engine_lock.json").read_text(encoding="utf-8"))
    revision = git("rev-parse", "HEAD").decode().strip()
    if revision != lock["revision"]:
        raise SystemExit(f"checkout is at {revision}, not the locked {lock['revision']}")
    for entry in lock["patches"]:
        if sha256(ROOT / entry["file"]) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} does not match the lock; regenerate the lock first")

    files = []
    tar_path = ROOT / args.tar
    with tempfile.TemporaryDirectory(prefix="stsai-snapshot-") as scratch:
        stage = Path(scratch) / "native_sources"
        entries = stage_engine(stage)
        vendored, pybind11_version = stage_vendored(stage)
        entries += vendored
        with tarfile.open(tar_path, "w:gz") as tar:
            for name, source, origin, licence, state in entries:
                tar.add(source, arcname=f"native_sources/{name}")
                files.append({"path": name, "sha256": sha256(source), "bytes": source.stat().st_size,
                              "origin": origin, "license": licence, "patch_state": state})

    manifest = {
        "purpose": "Minimum redistributable sources to build native/bridge.cpp with no network.",
        "archive": args.tar, "archive_sha256": sha256(tar_path),
        "build_command": "python review/offline_native_build.py --repo <checkout> --sources <archive>",
        "engine": {
            "url": lock["url"], "base_revision": lock["revision"],
            "json_submodule": lock["json_submodule"],
            "patch_order": lock["patches"],
            "applied_by": "review/offline_native_build.py, before configuring CMake"},
        "patch_state": ("PRE_PATCH: sts_lightspeed files are the locked revision's own copies. "
                        "The patches in engine_lock.json must be applied, in the declared order, "
                        "on top of them; the build script does this and fails if one does not "
                        "apply. Vendored files (nlohmann/json, pybind11) are PRISTINE."),
        "build_dependencies": {
            "cmake": ">=3.20", "compiler": "C++17", "python": "3.11-3.13",
            "pybind11": f"{pybind11_version} (headers included)",
            "nlohmann/json": "single-header (included)"},
        "licenses": {"sts_lightspeed": "MIT", "nlohmann/json": "MIT", "pybind11": "BSD-3-Clause"},
        "not_included": ["any .git directory", "CUDA or GPU libraries", "build outputs",
                         "the game jar or assets", "any virtualenv", "compiled .so files"],
        "file_count": len(files), "files": files,
    }
    (ROOT / args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(files)} files -> {args.tar} ({tar_path.stat().st_size/1e6:.2f} MB)")
    print("wrote", args.manifest)


if __name__ == "__main__":
    main()
