#!/usr/bin/env python3
"""Build `reports/s2r/input_receipt.json`: where every S2 package input comes from.

Read-only. For every entry of `scripts/make_s2_package.py:FILES` it records the
package path, the checkout path, the external (original execution directory)
path, availability in a clean checkout, bytes, the expected SHA256 from the
historical package manifest/provenance and the measured SHA256 in both copies,
and whether the two agree.

It also verifies the two hash semantics the round has to keep apart: a training
checkpoint (optimizer state present) and the inference export shipped in the
package (optimizer state removed), and the six runs' selected/last checkpoints
against `provenance.json`.

Text files are hashed as LF and as CRLF: the historical provenance recorded
Linux working-tree bytes, while the documentation audit was taken on a Windows
checkout with EOL conversion, so the same file has two legitimate digests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

FILES = [
    ("protocol.json", "reports/s2_volume_protocol.json"),
    ("semantic_compatibility.json", "reports/s2_semantic_compatibility.json"),
    ("native_sources.tar.gz", "native/native_sources.tar.gz"),
    ("native_sources_manifest.json", "native/native_sources_manifest.json"),
    ("review/README.md", "review/README.md"),
    ("review/run_review.py", "review/run_review.py"),
    ("review/offline_native_build.py", "review/offline_native_build.py"),
    ("review/counterfactual_replay.py", "review/counterfactual_replay.py"),
    ("review/model_smoke.py", "review/model_smoke.py"),
    ("review/recompute_s2.py", "review/recompute_s2.py"),
    ("data/initial_scenarios.json.gz", "runs/s2/package_data/data/initial_scenarios.json.gz"),
    ("data/composition_and_shards.json", "runs/s2/package_data/data/composition_and_shards.json"),
    ("data/coverage.json", "runs/s2/package_data/data/coverage.json"),
    ("training/runs.json", "training/runs.json"),
    ("training/metrics.jsonl.gz", "training/metrics.jsonl.gz"),
    ("training/validation.jsonl.gz", "training/validation.jsonl.gz"),
    ("training/selected_summary.csv", "training/selected_summary.csv"),
    ("model/D384_s17_selected.pt", "model/D384_s17_selected.pt"),
    ("model/smoke_observations.jsonl.gz", "model/smoke_observations.jsonl.gz"),
    ("model/smoke_expected.json", "model/smoke_expected.json"),
    ("evaluation/scenarios.json.gz", "runs/s2/package_data/evaluation/scenarios.json.gz"),
    ("evaluation/episodes.jsonl.gz", "runs/s2/evaluation/episodes.jsonl.gz"),
    ("evaluation/decision_latency.jsonl.gz", "runs/s2/evaluation/decision_latency.jsonl.gz"),
    ("evaluation/paired_summary.json", "reports/s2_paired_summary.json"),
    ("tests/junit.xml", "reports/s2_junit.xml"),
    ("reports/known_limitations.md", "reports/s2_known_limitations.md"),
    ("reports/commands_and_limits.md", "reports/s2_commands_and_limits.md"),
    ("tests/build_and_test.log.gz", "reports/s2_build_and_test.log"),
]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digests(path):
    """sha256 of the bytes as stored, plus the LF and CRLF canonical forms.

    `.gz` files additionally get the digest of their decompressed content, so a
    recompressed container is never confused with changed data.
    """
    import gzip
    data = Path(path).read_bytes()
    crlf = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    result = {"bytes": len(data), "sha256": sha256_bytes(data),
              "sha256_lf": sha256_bytes(data.replace(b"\r\n", b"\n")),
              "sha256_crlf": sha256_bytes(crlf), "binary_same_eol": data == crlf,
              "content_sha256": None}
    if str(path).endswith(".gz"):
        try:
            result["content_sha256"] = sha256_bytes(gzip.decompress(data))
            result["content_bytes"] = len(gzip.decompress(data))
        except OSError:
            result["content_sha256"] = None
    return result


def same_data(left, right):
    """True when two files carry the same data, allowing for EOL and gzip containers.

    The package ships `tests/build_and_test.log.gz`, a gzip of a source file that
    is not itself compressed, so a compressed side may be compared against the
    plain digest of the other side.
    """
    if left["sha256"] == right["sha256"] or left["sha256_lf"] == right["sha256_lf"]:
        return True
    plain = {left["sha256"], left["sha256_lf"]}
    if right["content_sha256"] is not None and right["content_sha256"] in plain:
        return True
    if left["content_sha256"] is not None and left["content_sha256"] in {right["sha256"],
                                                                        right["sha256_lf"]}:
        return True
    return (left["content_sha256"] is not None
            and left["content_sha256"] == right["content_sha256"])


def last_commit_touching(repo, relative):
    result = subprocess.run(["git", "log", "-1", "--format=%H %s", "--", relative],
                            cwd=repo, capture_output=True, text=True)
    return result.stdout.strip()


def read_manifest(package):
    text = (Path(package) / "MANIFEST.sha256").read_text(encoding="utf-8")
    entries = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split("  ", 1)
            entries[name.strip()] = digest.strip()
    return entries


def tracked_in_git(repo, relative):
    result = subprocess.run(["git", "ls-files", "--error-unmatch", relative],
                            cwd=repo, capture_output=True, text=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="clean checkout / this branch")
    parser.add_argument("--package", required=True, help="extracted historical ZIP")
    parser.add_argument("--external-root", required=True,
                        help="original execution directory holding the untracked artefacts")
    parser.add_argument("--out", required=True)
    parser.add_argument("--head", default="")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    package = Path(args.package).resolve()
    external = Path(args.external_root).resolve()

    manifest = read_manifest(package)
    provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
    audit = json.loads((repo / "reports/docs_consolidation_audit.json").read_text(encoding="utf-8"))
    audit_hashes = audit["preservation"]["baseline_sha256"]

    receipt = {
        "kind": "s2r_input_receipt",
        "round": "S2R-REPRO",
        "repo": str(repo),
        "head": args.head,
        "package": {"path": str(package), "zip": str(package) + ".zip",
                    "manifest_entries": len(manifest),
                    "provenance_head": provenance["head"],
                    "provenance_branch": provenance["branch"],
                    "protocol_baseline_commit": provenance["protocol"]["baseline_commit"]},
        "external_root": str(external),
        "hash_policy": ("The historical package manifest and provenance record Linux working-tree "
                        "(LF) bytes. The documentation audit records a Windows checkout (CRLF). "
                        "Both are reported; neither is rewritten."),
        "manifest_verification": None,
        "entries": [],
        "checkpoint_hash_semantics": {},
        "training_run_checkpoints": [],
        "gaps": [],
    }

    manifest_ok, manifest_bad = 0, []
    for name, digest in sorted(manifest.items()):
        member = package / name
        if not member.is_file():
            manifest_bad.append({"path": name, "problem": "missing from package"})
            continue
        measured = digests(member)
        if digest == measured["sha256_lf"] or digest == measured["sha256"]:
            manifest_ok += 1
        else:
            manifest_bad.append({"path": name, "expected": digest, "measured": measured["sha256"]})
    receipt["manifest_verification"] = {"verified": manifest_ok, "entries": len(manifest),
                                        "failures": manifest_bad}

    missing_in_audit = {item["source"] for item in audit["package_input_check"]["missing"]}
    for package_path, source in FILES:
        checkout_file = repo / source
        external_file = external / source
        entry = {
            "package_path": package_path,
            "checkout_path": source,
            "external_source": str(external_file),
            "listed_missing_in_clean_checkout": source in missing_in_audit,
            "tracked_by_git": tracked_in_git(repo, source),
            "present_in_checkout": checkout_file.is_file(),
            "present_externally": external_file.is_file(),
            "present_in_package": (package / package_path).is_file(),
            "expected_sha256": manifest.get(package_path),
            "expected_source": "package MANIFEST.sha256",
            "round": provenance["head"],
            "restored_from_original_package": False,
            "checks": {},
        }
        if not entry["present_in_package"]:
            entry["checks"]["in_package"] = False
            receipt["gaps"].append({"package_path": package_path, "problem": "not in package"})
            receipt["entries"].append(entry)
            continue
        in_package = digests(package / package_path)
        entry["checks"]["in_package_manifest"] = in_package["sha256"] == entry["expected_sha256"]
        entry["package_bytes"] = in_package["bytes"]
        entry["package_sha256"] = in_package["sha256"]
        entry["package_content_sha256"] = in_package["content_sha256"]
        if external_file.is_file():
            on_disk = digests(external_file)
            entry["external_sha256"] = on_disk["sha256"]
            entry["external_bytes"] = on_disk["bytes"]
            entry["external_content_sha256"] = on_disk["content_sha256"]
            entry["checks"]["external_matches_package"] = same_data(on_disk, in_package)
            entry["checks"]["external_byte_identical"] = on_disk["sha256"] == in_package["sha256"]
            entry["restored_from_original_package"] = bool(
                entry["checks"]["external_matches_package"])
        if checkout_file.is_file():
            in_checkout = digests(checkout_file)
            entry["checkout_sha256"] = in_checkout["sha256"]
            entry["checks"]["checkout_matches_package"] = same_data(in_checkout, in_package)
            entry["checks"]["checkout_byte_identical"] = \
                in_checkout["sha256"] == in_package["sha256"] or \
                in_checkout["sha256_lf"] == in_package["sha256"]
            if not entry["checks"]["checkout_byte_identical"]:
                # A difference here is only meaningful if it can be attributed:
                # either the container was rewritten around identical data, the
                # package member is a gzip generated from the checkout file, or
                # the file was edited by a later commit. Say which one it is.
                entry["difference_from_package"] = {
                    "container_only": bool(in_checkout["content_sha256"] is not None
                                           and in_checkout["content_sha256"]
                                           == in_package["content_sha256"]),
                    "package_member_is_generated_gzip_of_checkout_file": bool(
                        package_path.endswith(".gz") and not source.endswith(".gz")
                        and in_package["content_sha256"] is not None
                        and in_package["content_sha256"] in {in_checkout["sha256"],
                                                             in_checkout["sha256_lf"]}),
                    "checkout_content_sha256": in_checkout["content_sha256"],
                    "package_content_sha256": in_package["content_sha256"],
                    "last_commit_touching_the_path": last_commit_touching(repo, source),
                    "package_manifest_still_consistent": entry["checks"]["in_package_manifest"],
                    "data_unchanged": bool(entry["checks"]["checkout_matches_package"]),
                }
        elif source in audit_hashes:
            entry["audit_sha256_crlf"] = audit_hashes[source]
            entry["checks"]["audit_hash_is_crlf_of_package"] = \
                audit_hashes[source] == in_package["sha256_crlf"]
        receipt["entries"].append(entry)

    # Training checkpoint vs inference export: different files, different hashes,
    # different meaning. Neither is a corruption of the other.
    export_path = external / "model/D384_s17_selected.pt"
    source_path = external / "runs/s2/D384_s17/model/best.pt"
    export_record = json.loads((external / "runs/s2/D384_s17/model/export.json").read_text())
    if export_path.is_file() and source_path.is_file():
        import torch
        exported = torch.load(export_path, map_location="cpu", weights_only=True)
        source_ckpt = torch.load(source_path, map_location="cpu", weights_only=True)
        exported_digest = digests(export_path)
        source_digest = digests(source_path)
        receipt["checkpoint_hash_semantics"] = {
            "inference_export": {
                "path": "model/D384_s17_selected.pt",
                "bytes": exported_digest["bytes"], "sha256": exported_digest["sha256"],
                "contains_optimizer_state": "optimizer_state" in exported,
                "keys": sorted(exported.keys()),
                "records_export": exported.get("export"),
                "matches_provenance_model_shipped": provenance["model"]["shipped"]["sha256"]
                == exported_digest["sha256"],
                "matches_export_json": export_record["sha256"] == exported_digest["sha256"],
            },
            "training_checkpoint": {
                "path": "runs/s2/D384_s17/model/best.pt",
                "bytes": source_digest["bytes"], "sha256": source_digest["sha256"],
                "contains_optimizer_state": "optimizer_state" in source_ckpt,
                "matches_export_json_source_sha256": export_record["source_sha256"]
                == source_digest["sha256"],
                "matches_provenance_selected_sha256": next(
                    run["selected_sha256"] for run in provenance["training"]["runs"]
                    if run["run"] == "D384_s17") == source_digest["sha256"],
            },
            "hashes_are_different_files_not_corruption":
                exported_digest["sha256"] != source_digest["sha256"],
            "explanation": ("The package ships the optimizer-free export; the training checkpoint "
                            "stays on the execution machine. A matching hash is not expected and "
                            "would mean one of the two was mislabelled."),
        }
    else:
        receipt["gaps"].append({"problem": "model export or its source checkpoint is unavailable"})

    # The other five runs travel as records, not weights: check the records against
    # whatever checkpoints exist rather than claiming the files were shipped.
    for run in provenance["training"]["runs"]:
        name = run["run"]
        directory = external / ("runs/s1r/M128-R0-s17-S1R/model" if run.get("reused_from")
                                else f"runs/s2/{name}/model")
        row = {"run": name, "reused_from": run.get("reused_from"),
               "directory": str(directory), "selected_step": run["selected_step"],
               "weights_in_package": name == "D384_s17"}
        for label, filename, key in (("selected", "best.pt", "selected_sha256"),
                                     ("last", "last.pt", "last_sha256")):
            path = directory / filename
            row[f"{label}_expected_sha256"] = run[key]
            if path.is_file():
                measured = digests(path)["sha256"]
                row[f"{label}_measured_sha256"] = measured
                row[f"{label}_matches"] = measured == run[key]
                row[f"{label}_bytes"] = path.stat().st_size
            else:
                row[f"{label}_matches"] = None
                row[f"{label}_note"] = "checkpoint not present on this machine"
        receipt["training_run_checkpoints"].append(row)

    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    restored = [e for e in receipt["entries"] if e["restored_from_original_package"]]
    print(f"manifest {manifest_ok}/{len(manifest)} verified, failures={len(manifest_bad)}")
    print(f"entries={len(receipt['entries'])} restored_from_package={len(restored)} "
          f"gaps={len(receipt['gaps'])}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
