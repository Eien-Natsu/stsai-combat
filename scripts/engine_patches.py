"""Patch series for the pinned upstream engine checkout.

Upstream sts_lightspeed is checked out at an immutable revision and then has the
patches under native/patches/ applied in filename order. engine_lock.json
records each patch hash so the build can demonstrate the working tree is exactly
base + patches, instead of quietly building a modified engine.
"""
from pathlib import Path
import hashlib
import json
import subprocess


def load_lock(root: Path) -> dict:
    return json.loads((root / "engine_lock.json").read_text(encoding="utf-8"))


def check_hashes(root: Path, patches: list) -> None:
    for entry in patches:
        path = root / entry["file"]
        if not path.is_file():
            raise SystemExit(f"Missing declared patch {entry['file']}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"Patch hash mismatch for {entry['file']}: {actual}")


def touched_files(root: Path, patches: list) -> set:
    files = set()
    for entry in patches:
        for line in (root / entry["file"]).read_text(encoding="utf-8").splitlines():
            if line.startswith("+++ b/"):
                files.add(line[len("+++ b/"):])
    return files


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


def assert_tree_matches(root: Path, upstream: Path, patches: list) -> None:
    """Require the checkout to be exactly base revision plus the patch series."""
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=upstream, text=True)
    modified, untracked = set(), set()
    for line in status.splitlines():
        code, name = line[:2], line[3:].strip()
        (untracked if code.strip() == "??" else modified).add(name)
    if untracked:
        raise SystemExit(f"Upstream checkout has untracked files: {sorted(untracked)}")
    expected = touched_files(root, patches) if patches else set()
    if modified != expected:
        raise SystemExit(f"Upstream checkout modified {sorted(modified)}, expected exactly {sorted(expected)}")
    for entry in patches:
        reverse = subprocess.run(["git", "apply", "--check", "--reverse", str(root / entry["file"])],
                                 cwd=upstream, capture_output=True, text=True)
        if reverse.returncode != 0:
            raise SystemExit(f"{entry['file']} is declared but not applied: {reverse.stderr}")
