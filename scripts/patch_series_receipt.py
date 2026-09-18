#!/usr/bin/env python3
"""Apply the declared patch series to the locked revision and record what happened.

    python scripts/patch_series_receipt.py [--out audit/patch_reconstruction.json]

Starts from a detached worktree of the real upstream checkout at the locked
revision - not from a reconstructed base and not from a synthetic repository -
and runs `git apply` for each declared patch in filename order, capturing the
command, its exit code and every touched file's hash after each step. The hash
of the working checkout's own files is recorded too, so the shipped tree can be
compared with what the series produces.

The point is the SEQUENCE: each patch must be the incremental difference from
the state the previous ones leave behind. A cumulative patch that only applies
on top of a hand-built base would fail here.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from engine_patches import load_lock, touched_files  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args, cwd, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {cwd}:\n{result.stderr}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="audit/patch_reconstruction.json")
    parser.add_argument("--upstream", default=str(ROOT / "third_party/sts_lightspeed"))
    args = parser.parse_args()

    upstream = Path(args.upstream).resolve()
    lock = load_lock(ROOT)
    patches = lock["patches"]
    files = sorted(touched_files(ROOT, patches))
    receipt = {
        "purpose": "Cold-start application of the declared patch series to the locked revision.",
        "upstream": lock["url"],
        "base_revision": lock["revision"],
        "patch_order": [entry["file"] for entry in patches],
        "scope": "The worktree is created from the pinned upstream checkout at the locked "
                 "revision; `git rev-parse HEAD` inside it is recorded below. It is not a "
                 "reconstructed or synthetic base.",
        "steps": [],
    }

    for entry in patches:
        if sha256(ROOT / entry["file"]) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} does not match engine_lock.json")

    with tempfile.TemporaryDirectory(prefix="stsai-series-") as scratch:
        tree = Path(scratch) / "tree"
        git("worktree", "add", "--detach", str(tree), lock["revision"], cwd=upstream)
        try:
            head = git("rev-parse", "HEAD", cwd=tree).stdout.strip()
            receipt["worktree_head"] = head
            if head != lock["revision"]:
                raise SystemExit(f"worktree is at {head}, not the locked revision")
            dirty = git("status", "--porcelain", cwd=tree).stdout.strip()
            receipt["worktree_clean_at_start"] = not dirty
            if dirty:
                raise SystemExit(f"worktree is not clean at the locked revision:\n{dirty}")
            receipt["files_before"] = {name: sha256(tree / name) for name in files}

            for entry in patches:
                patch = (ROOT / entry["file"]).resolve()
                check = git("apply", "--check", str(patch), cwd=tree, check=False)
                step = {
                    "patch": entry["file"],
                    "sha256": entry["sha256"],
                    "command": ["git", "apply", str(entry["file"])],
                    "check_returncode": check.returncode,
                    "check_stderr": check.stderr.strip(),
                }
                if check.returncode != 0:
                    step["returncode"] = None
                    step["note"] = "forward --check failed; the patch is not incremental here"
                    receipt["steps"].append(step)
                    receipt["result"] = "FAIL: the series does not apply in order"
                    Path(ROOT / args.out).parent.mkdir(parents=True, exist_ok=True)
                    Path(ROOT / args.out).write_text(json.dumps(receipt, indent=2) + "\n",
                                                    encoding="utf-8")
                    raise SystemExit(f"{entry['file']} does not apply on top of its predecessors")

                applied = git("apply", str(patch), cwd=tree, check=False)
                step["returncode"] = applied.returncode
                step["stderr"] = applied.stderr.strip()
                step["hashes_after"] = {name: sha256(tree / name) for name in files}
                receipt["steps"].append(step)
                if applied.returncode != 0:
                    receipt["result"] = f"FAIL: {entry['file']} did not apply"
                    Path(ROOT / args.out).parent.mkdir(parents=True, exist_ok=True)
                    Path(ROOT / args.out).write_text(json.dumps(receipt, indent=2) + "\n",
                                                    encoding="utf-8")
                    raise SystemExit(f"{entry['file']} failed to apply:\n{applied.stderr}")

            receipt["files_after_series"] = {name: sha256(tree / name) for name in files}
            receipt["files_in_worktree_now"] = {name: sha256(upstream / name) for name in files}
            receipt["worktree_matches_series"] = (
                receipt["files_after_series"] == receipt["files_in_worktree_now"])
            receipt["result"] = ("PASS: every patch applied in order and the built checkout "
                                 "matches the series output"
                                 if receipt["worktree_matches_series"] else
                                 "FAIL: the checkout differs from the series output")
        finally:
            git("worktree", "remove", "--force", str(tree), cwd=upstream, check=False)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"{len(receipt['steps'])} patches applied in order; wrote {out}")
    print(receipt["result"])
    if not receipt.get("worktree_matches_series"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
