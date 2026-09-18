"""Patch series for the pinned upstream engine checkout.

Upstream sts_lightspeed is checked out at an immutable revision and then has the
patches under native/patches/ applied in filename order. engine_lock.json
records each patch hash so the build can demonstrate the working tree is exactly
base + patches, instead of quietly building a modified engine.

`assert_tree_matches` compares CONTENT, not filenames: it rebuilds the expected
tree by applying the declared series to the locked revision in a scratch
directory and compares every tracked file hash. A filename check plus a reverse
--check would still accept an extra unregistered line inside a file the patches
already touch, which is exactly the hole this closes.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile
import tempfile


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_lock(root: Path) -> dict:
    return json.loads((root / "engine_lock.json").read_text(encoding="utf-8"))


def check_hashes(root: Path, patches: list) -> None:
    for entry in patches:
        path = root / entry["file"]
        if not path.is_file():
            raise SystemExit(f"Missing declared patch {entry['file']}")
        actual = sha256(path)
        if actual != entry["sha256"]:
            raise SystemExit(f"Patch hash mismatch for {entry['file']}: {actual}")


def touched_files(root: Path, patches: list) -> set:
    files = set()
    for entry in patches:
        for line in (root / entry["file"]).read_text(encoding="utf-8").splitlines():
            if line.startswith("+++ b/"):
                files.add(line[len("+++ b/"):])
    return files


def submodule_paths(upstream: Path) -> set:
    """Paths that hold a gitlink: their content lives in another repository."""
    out = subprocess.check_output(["git", "ls-files", "--stage"], cwd=upstream, text=True)
    return {line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("160000")}


def apply_all(root: Path, upstream: Path, patches: list) -> None:
    """Apply every patch once; already-applied patches are left alone."""
    check_hashes(root, patches)
    for entry in patches:
        path = root / entry["file"]
        forward = subprocess.run(["git", "apply", "--check", str(path)],
                                 cwd=upstream, capture_output=True, text=True)
        if forward.returncode == 0:
            subprocess.run(["git", "apply", str(path)], cwd=upstream, check=True)
            continue
        reverse = subprocess.run(["git", "apply", "--check", "--reverse", str(path)],
                                 cwd=upstream, capture_output=True, text=True)
        if reverse.returncode != 0:
            raise SystemExit(f"{entry['file']} neither applies nor is applied:\n{forward.stderr}")


def expected_tree(root: Path, upstream: Path, patches: list) -> dict:
    """Content of the locked revision after the declared series, as {path: sha256}."""
    check_hashes(root, patches)
    with tempfile.TemporaryDirectory(prefix="stsai-expected-") as scratch:
        scratch = Path(scratch)
        archive = subprocess.run(["git", "archive", "HEAD"], cwd=upstream,
                                 capture_output=True, check=True).stdout
        blob = scratch / "tree.tar"
        blob.write_bytes(archive)
        with tarfile.open(blob) as tar:
            tar.extractall(scratch, filter="data")
        blob.unlink()
        for entry in patches:
            # absolute: git runs with cwd=scratch, so a relative path would not resolve
            subprocess.run(["git", "apply", str((root / entry["file"]).resolve())],
                           cwd=scratch, check=True)
        return {str(p.relative_to(scratch)): sha256(p)
                for p in scratch.rglob("*") if p.is_file()}


def assert_tree_matches(root: Path, upstream: Path, patches: list) -> None:
    """Require the checkout to be exactly the locked revision plus the patch series."""
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                        cwd=upstream, text=True).split()
    if untracked:
        raise SystemExit(f"Upstream checkout has untracked files: {sorted(untracked)[:5]}")

    skip = submodule_paths(upstream)
    expected = expected_tree(root, upstream, patches)
    actual = {}
    for name in subprocess.check_output(["git", "ls-files"], cwd=upstream, text=True).splitlines():
        if any(name == s or name.startswith(s + "/") for s in skip):
            continue
        path = upstream / name
        if path.is_file():
            actual[name] = sha256(path)

    added = sorted(set(actual) - set(expected))
    if added:
        raise SystemExit(f"Files present but not produced by base+patches: {added[:5]}")
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise SystemExit(f"Files produced by base+patches but absent or untracked: {missing[:5]}")
    differing = sorted(name for name in expected if expected[name] != actual[name])
    if differing:
        raise SystemExit(f"Content differs from base+patches in {len(differing)} file(s): {differing[:5]}")
