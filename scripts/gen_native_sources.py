#!/usr/bin/env python3
"""Snapshot the redistributable sources needed to build the native extension offline.

The review containers have no route to GitHub or PyPI, so three previous rounds
could only skip the native tests. This collects the minimum that compiles:
the locked sts_lightspeed `src`/`include`, the nlohmann/json headers it needs,
the pybind11 headers and CMake support files, and every licence.

The snapshot is POST-PATCH: it already contains the local rule fixes, so the
patches must NOT be applied again. The manifest says so per file.
"""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "third_party" / "sts_lightspeed"
PYBIND11 = ROOT / ".venv" / "lib" / "python3.12" / "site-packages" / "pybind11"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collect():
    """(archive_path, source_path, origin, licence) for every file to ship."""
    entries = []
    for relative in ("src", "include"):
        for path in sorted((UPSTREAM / relative).rglob("*")):
            if path.is_file():
                entries.append((f"sts_lightspeed/{path.relative_to(UPSTREAM)}", path,
                                "sts_lightspeed", "MIT"))
    entries.append(("sts_lightspeed/LICENSE.md", UPSTREAM / "LICENSE.md", "sts_lightspeed", "MIT"))
    for relative in ("single_include/nlohmann/json.hpp", "include/nlohmann/json.hpp"):
        path = UPSTREAM / "json" / relative
        if path.is_file():
            # must sit inside the engine dir: the CMake adds
            # ${STS_ENGINE_DIR}/json/single_include to the include path
            entries.append((f"sts_lightspeed/json/{relative}", path, "nlohmann/json", "MIT"))
    entries.append(("sts_lightspeed/json/LICENSE.MIT", UPSTREAM / "json" / "LICENSE.MIT",
                    "nlohmann/json", "MIT"))
    for path in sorted((PYBIND11 / "include").rglob("*")):
        if path.is_file():
            entries.append((f"pybind11/include/{path.relative_to(PYBIND11 / 'include')}", path,
                            "pybind11", "BSD-3-Clause"))
    for path in sorted((PYBIND11 / "share").rglob("*")):
        if path.is_file():
            entries.append((f"pybind11/share/{path.relative_to(PYBIND11 / 'share')}", path,
                            "pybind11", "BSD-3-Clause"))
    licenses = list((PYBIND11 / "dist-info").glob("licenses/*")) if (PYBIND11 / "dist-info").exists() else []
    licenses += [p for p in PYBIND11.glob("LICENSE*")]
    for path in sorted(set(licenses)):
        if path.is_file():
            entries.append((f"pybind11/{path.name}", path, "pybind11", "BSD-3-Clause"))
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tar", default="native_sources.tar.gz")
    parser.add_argument("--manifest", default="native_sources_manifest.json")
    args = parser.parse_args()
    lock = json.loads((ROOT / "engine_lock.json").read_text())
    entries = collect()
    files = []
    tar_path = ROOT / args.tar
    with tarfile.open(tar_path, "w:gz") as tar:
        for name, source, origin, licence in entries:
            tar.add(source, arcname=f"native_sources/{name}")
            files.append({"path": name, "sha256": sha256(source), "bytes": source.stat().st_size,
                          "origin": origin, "license": licence,
                          "patch_state": "POST_PATCH" if origin == "sts_lightspeed" else "PRISTINE"})
    manifest = {
        "purpose": "Minimum redistributable sources to build native/bridge.cpp with no network.",
        "archive": args.tar, "archive_sha256": sha256(tar_path),
        "build_command": "python review/offline_native_build.py --repo <checkout> --sources <extracted>",
        "engine": {"url": lock["url"], "base_revision": lock["revision"],
                   "patches": lock["patches"], "json_submodule": lock["json_submodule"]},
        "patch_state": ("POST_PATCH: this snapshot already contains the local fixes. The patches "
                        "in engine_lock.json must NOT be applied again on top of it."),
        "build_dependencies": {
            "cmake": ">=3.20", "compiler": "C++17", "python": "3.11-3.13",
            "pybind11": "2.13.6 (headers included)", "nlohmann/json": "single-header (included)"},
        "licenses": {"sts_lightspeed": "MIT", "nlohmann/json": "MIT", "pybind11": "BSD-3-Clause"},
        "not_included": ["any .git directory", "CUDA or GPU libraries", "build outputs",
                         "the game jar or assets", "any virtualenv"],
        "file_count": len(files), "files": files,
    }
    (ROOT / args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(files)} files -> {args.tar} ({tar_path.stat().st_size/1e6:.2f} MB)")
    print("wrote", args.manifest)


if __name__ == "__main__":
    main()
