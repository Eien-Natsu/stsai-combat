#!/usr/bin/env python3
"""Verify a review package before anything is built, replayed or recomputed.

    python review/check_review_inputs.py --repo <checkout> --package <dir or .zip> \
        --out <receipt.json> [--lock <artifact_lock.json>]

Why this runs first: a package can be complete-looking and still be unreviewable -
a weight that is really a training checkpoint, a summary with no per-episode
records behind it, a member that escaped the package, an S1R model substituted for
the S2 one. Those are cheap to detect and expensive to discover after a cold build.

Every check is reported on its own line and in the receipt as PASS / FAIL /
NOT_RUN; NOT_RUN is "this machine could not evaluate it" and is never a pass. The
exit code is non-zero unless every required check passed, so a missing input
cannot be mistaken for a clean package by a wrapper that only reads the status.

`--lock` takes a JSON map of source path -> sha256 (the artifact lock of the
round). Every artifact-residency input is then also checked against it, which is
what makes an artifact root "verified" rather than merely present.
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import package_contract as contract  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def report_add(rows, name, ok, note, required=True):
    status = "NOT_RUN" if ok is None else ("PASS" if ok is True else "FAIL")
    rows.append({"check": name, "status": status, "note": note, "required": required})
    print(f"{status:8s} {name:22s} {note}", flush=True)
    return ok is True


# --- package addressing ------------------------------------------------------

UNSAFE_NAMES = ("..",)


def zip_members(zip_path):
    """Members of an archive, with the ones that may not be extracted.

    A member is unsafe if it is absolute, climbs out of the archive, is a link or
    a device, or duplicates a name: extracting any of those writes outside the
    directory the reviewer chose.
    """
    unsafe, safe = [], []
    seen = set()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            problems = []
            if name.startswith("/") or os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
                problems.append("absolute path")
            parts = Path(name.replace("\\", "/")).parts
            if any(part in UNSAFE_NAMES for part in parts):
                problems.append("escapes the archive root")
            mode = (info.external_attr >> 16) & 0o170000
            if mode in (0o120000, 0o10000) or (info.external_attr & 0xF0000000) == 0xA0000000:
                problems.append("symlink")
            if name in seen:
                problems.append("duplicate name")
            seen.add(name)
            (unsafe if problems else safe).append({"name": name, "problems": problems})
    return safe, unsafe


def open_package(package, work):
    """Return the package directory, extracting a verified archive if needed."""
    package = Path(package).resolve()
    if package.is_dir():
        return package, "directory", []
    if package.suffix != ".zip":
        raise SystemExit(f"{package} is neither a directory nor a .zip")
    safe, unsafe = zip_members(package)
    if work is None:
        raise SystemExit(f"{package} is an archive; pass --work for a scratch directory")
    target = Path(work) / "package"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        for member in safe:
            archive.extract(member["name"], target)
    return target, "zip", unsafe


# --- checks ------------------------------------------------------------------

def check_layout(package):
    missing = [e["package_path"] for e in contract.REQUIRED_INPUTS
               if not (package / e["package_path"]).is_file()]
    if missing:
        return False, f"{len(missing)} of {len(contract.REQUIRED_INPUTS)} required inputs missing: {missing}", missing
    return True, f"all {len(contract.REQUIRED_INPUTS)} required inputs are present", []


def check_manifest(package):
    manifest_path = package / "MANIFEST.sha256"
    if not manifest_path.is_file():
        return False, "the package has no MANIFEST.sha256", {}
    recorded = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            recorded[name.strip()] = digest.strip()
    mismatched, missing = [], []
    for name, digest in sorted(recorded.items()):
        path = package / name
        if not path.is_file():
            missing.append(name)
        elif sha256(path) != digest:
            mismatched.append(name)
    unlisted = sorted(str(p.relative_to(package).as_posix())
                      for p in package.rglob("*")
                      if p.is_file() and p.name != "MANIFEST.sha256"
                      and str(p.relative_to(package).as_posix()) not in recorded)
    verified = len(recorded) - len(mismatched) - len(missing)
    detail = {"entries": len(recorded), "verified": verified, "mismatched": mismatched[:10],
              "missing": missing[:10], "unlisted_files": unlisted[:10]}
    if mismatched or missing:
        return False, (f"{len(mismatched)} mismatched, {len(missing)} missing of {len(recorded)}: "
                       f"{(mismatched + missing)[:5]}"), detail
    if unlisted:
        return False, f"{len(unlisted)} file(s) are not covered by the manifest: {unlisted[:5]}", detail
    return True, f"{verified} members verify against the manifest", detail


def check_path_scope(package, kind, unsafe):
    if kind == "zip" and unsafe:
        return False, f"{len(unsafe)} unsafe archive member(s): {unsafe[:3]}", unsafe
    root = Path(os.path.realpath(package))
    escaped = []
    for entry in contract.REQUIRED_INPUTS:
        path = package / entry["package_path"]
        if not path.is_file():
            continue
        real = Path(os.path.realpath(path))
        if root != real and root not in real.parents:
            escaped.append(entry["package_path"])
    if escaped:
        return False, f"{len(escaped)} input(s) resolve outside the package root: {escaped[:5]}", escaped
    return True, "every input stays inside the package root", []


def check_provenance(package, repo):
    path = package / "provenance.json"
    if not path.is_file():
        return False, "the package has no provenance.json", {}
    provenance = json.loads(path.read_text(encoding="utf-8"))
    lock = json.loads((repo / "engine_lock.json").read_text(encoding="utf-8"))
    problems, detail = [], {}
    if provenance.get("engine", {}).get("revision") != lock["revision"]:
        problems.append("engine revision differs from engine_lock.json")
    if provenance.get("engine", {}).get("patches") and \
            [p["sha256"] for p in provenance["engine"]["patches"]] != \
            [p["sha256"] for p in lock["patches"]]:
        problems.append("patch series differs from engine_lock.json")
    head = provenance.get("head", "")
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        problems.append("head is not a full commit SHA")
    # The provenance names the files it hashed; if the package really carries those
    # bytes, the two digests must still agree. This is what catches a package whose
    # contents were swapped after the records were written.
    named = {
        "protocol.json": provenance.get("protocol", {}).get("protocol_file", {}).get("sha256"),
        "model/D384_s17_selected.pt": provenance.get("model", {}).get("shipped", {}).get("sha256"),
        "evaluation/episodes.jsonl.gz": provenance.get("evaluation", {}).get("episodes", {}).get("sha256"),
        "evaluation/decision_latency.jsonl.gz": provenance.get("evaluation", {}).get("decisions", {}).get("sha256"),
    }
    detail["provenance_hashes"] = {}
    for name, expected in named.items():
        path = package / name
        if expected is None:
            problems.append(f"provenance does not record {name}")
            continue
        if not path.is_file():
            problems.append(f"{name} is named by provenance but absent")
            continue
        measured = sha256(path)
        detail["provenance_hashes"][name] = {"recorded": expected, "measured": measured,
                                             "matches": measured == expected}
        if measured != expected:
            problems.append(f"{name} does not match the provenance digest")
    detail["head"], detail["branch"] = head, provenance.get("branch")
    if problems:
        return False, "; ".join(problems[:4]), detail
    return True, f"provenance is consistent with the checkout and the package ({len(named)} digests)", detail


def check_versions(package, repo):
    """The package's declared input semantics must be this build's semantics."""
    sys.path.insert(0, str(repo / "src"))
    package_protocol = json.loads((package / "protocol.json").read_text(encoding="utf-8"))
    declared = dict(package_protocol.get("versions", {}))
    provenance_path = package / "provenance.json"
    if provenance_path.is_file():
        from_provenance = json.loads(provenance_path.read_text(encoding="utf-8")).get("versions", {})
        for key, value in from_provenance.items():
            if key in declared and declared[key] != value:
                return False, (f"protocol.json and provenance.json disagree on {key}: "
                               f"{declared[key]} vs {value}"), {}
            declared.setdefault(key, value)
    problems, detail = [], {}
    for field, (module_name, attribute) in contract.VERSION_FIELDS.items():
        module = __import__(module_name, fromlist=[attribute])
        current = getattr(module, attribute)
        if field not in declared:
            problems.append(f"{field} is not declared by the package")
        elif declared[field] != current:
            problems.append(f"{field}: package says {declared[field]}, this build uses {current}")
        detail[field] = {"package": declared.get(field), "checkout": current}
    if problems:
        return False, "; ".join(problems[:4]), detail
    return True, f"{len(contract.VERSION_FIELDS)} declared revisions match this build", detail


def check_protocol_identity(package):
    """The shipped protocol must be the fixed-budget data-volume one.

    The S2 name is shared with an earlier louse-fix round whose protocol is still
    in the tree; shipping that one would silently answer a different question.
    """
    protocol = json.loads((package / "protocol.json").read_text(encoding="utf-8"))
    required = ["purpose", "question", "fixed_budget_means", "baseline_commit", "run_table",
                "training_config", "selection", "evaluation", "statistics", "resource_limits"]
    missing = [key for key in required if key not in protocol]
    if missing:
        return False, f"protocol.json is missing {missing}; this does not look like the volume protocol", {}
    question = json.dumps(protocol["question"]).lower()
    if not ("96" in question and "384" in question):
        return False, "the protocol question is not the 96-to-384 data-volume contrast", {}
    runs = protocol.get("run_table", [])
    names = sorted(r.get("run") for r in runs) if isinstance(runs, list) else []
    return True, (f"volume protocol, {len(runs)} runs declared: {names[:3]}..."), {"runs": names}


def check_model(package):
    """The shipped weight must be an inference export of the selected D384 run.

    Four ways this can be wrong, and each has to fail: a training checkpoint that
    was renamed; a weight whose input semantics are another round's; a weight whose
    data is the 96-battle set rather than the 384 one; and a weight whose recorded
    source is not the run the package says it ships.
    """
    path = package / "model" / "D384_s17_selected.pt"
    if not path.is_file():
        return False, "the package ships no model/D384_s17_selected.pt", {}
    try:
        import torch
    except ImportError:
        return None, "torch is not installed, so the weight cannot be inspected", {}
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as error:  # noqa: BLE001 - the reason is part of the finding
        return False, f"the weight cannot be loaded: {type(error).__name__}: {error}", {}
    missing = [key for key in contract.MODEL_EXPORT_REQUIRED_KEYS if key not in checkpoint]
    present = [key for key in contract.MODEL_EXPORT_FORBIDDEN_KEYS if key in checkpoint]
    if missing:
        return False, f"the weight is not a complete export; missing {missing}", {}
    if present:
        return False, (f"the weight still carries {present}: this is a training checkpoint, not the "
                       "optimizer-free export the package declares"), {}
    export = checkpoint["export"]
    export_source = Path(str(export.get("source_checkpoint", "")))
    problems = []
    if export_source.name != "best.pt" or "D384_s17" not in str(export_source):
        problems.append(f"the export's source is {export.get('source_checkpoint')!r}, not the "
                        "selected D384_s17 run")
    if export.get("source_sha256") == sha256(path):
        problems.append("the export's source hash equals its own digest: a checkpoint was relabelled "
                        "rather than exported")
    declared = json.loads((package / "protocol.json").read_text(encoding="utf-8")).get("versions", {})
    problems += [f"{field}={checkpoint.get(field)} but the package declares {declared[field]}"
                 for field in ("encoding_revision", "observation_schema", "loss_revision",
                               "sampler_revision")
                 if field in declared and checkpoint.get(field) != declared[field]]
    runs = json.loads((package / "training" / "runs.json").read_text(encoding="utf-8"))["runs"]
    selected = next((run for run in runs if run["run"] == "D384_s17"), None)
    expected_fingerprint = (selected or {}).get("data_fingerprint")
    if expected_fingerprint and checkpoint.get("data_fingerprint") != expected_fingerprint:
        problems.append(f"data_fingerprint={checkpoint.get('data_fingerprint')} is not the D384_s17 "
                        f"data set ({expected_fingerprint}); this weight was trained on other data")
    provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
    recorded_source = next((run.get("selected_sha256") for run in provenance["training"]["runs"]
                            if run["run"] == "D384_s17"), None)
    if recorded_source and export.get("source_sha256") != recorded_source:
        problems.append("the export's source checkpoint hash is not the selected hash provenance "
                        "records for D384_s17")
    detail = {"bytes": path.stat().st_size, "sha256": sha256(path),
              "contains_optimizer_state": False, "export": export,
              "data_fingerprint": checkpoint.get("data_fingerprint"),
              "recorded_selected_sha256": recorded_source}
    if problems:
        return False, "; ".join(problems[:3]), detail
    return True, f"optimizer-free export of {export_source.name} at step {export.get('source_step')}", detail


def check_evaluation_records(package):
    """Per-episode records, complete and unique, derived from the package's own declarations.

    A summary on its own is not reviewable: the protocol's statistics have to be
    recomputed from the episodes. The expected key grid comes from what the package
    declares - the materialised scenario lists and the trained runs plus the two
    baselines - so a package that ships four runs' records while declaring six fails.
    """
    episodes_path = package / "evaluation" / "episodes.jsonl.gz"
    if not episodes_path.is_file():
        extra = " (only a summary is present)" if (package / "evaluation/paired_summary.json").is_file() else ""
        return False, f"evaluation/episodes.jsonl.gz is missing{extra}; the statistics cannot be recomputed", {}
    with gzip.open(episodes_path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    scenarios = json.loads(gzip.open(package / "evaluation" / "scenarios.json.gz",
                                     "rt", encoding="utf-8").read())
    runs = json.loads((package / "training" / "runs.json").read_text(encoding="utf-8"))["runs"]
    declared_sets = sorted(k for k, v in scenarios.items() if isinstance(v, dict) and "scenarios" in v)
    declared_policies = sorted([r["run"] for r in runs] + contract.BASELINE_POLICIES)
    expected = {(s, p, i) for s in declared_sets for p in declared_policies
                for i in range(len(scenarios[s]["scenarios"]))}
    keys = [(row.get("set"), row.get("policy"), row.get("episode_index")) for row in rows]
    missing = sorted(expected - set(keys))[:5]
    duplicates = len(keys) - len(set(keys))
    extra = sorted(set(keys) - expected)[:5]
    fields_missing = sorted({field for row in rows
                             for field in contract.EPISODE_FIELDS if field not in row})
    detail = {"episodes": len(rows), "expected_keys": len(expected), "unique_keys": len(set(keys)),
              "sets": declared_sets, "policies": declared_policies,
              "missing_keys": missing, "unexpected_keys": extra, "duplicates": duplicates,
              "fields_missing": fields_missing}
    if duplicates:
        return False, f"{duplicates} duplicated (set, policy, scenario) keys", detail
    if missing or extra:
        return False, (f"{len(missing)} declared keys have no record (first {missing}); "
                       f"{len(extra)} records have no declared key"), detail
    if fields_missing:
        return False, f"episode records are missing {fields_missing}", detail
    return True, f"{len(rows)} per-episode records, {len(expected)} unique declared keys", detail


def check_decision_records(package, episodes_path):
    """The per-decision records must describe the same battles as the per-episode ones.

    Two files that agree on their key set can still disagree about what happened:
    a latency file from another run has the same keys and different actions. So the
    action sequence and the decision count are compared step by step, which is what
    makes the latency input usable as evidence rather than as a second copy of the
    key list.
    """
    path = package / "evaluation" / "decision_latency.jsonl.gz"
    if not path.is_file() or not episodes_path.is_file():
        return False, "the package does not ship both record files", {}
    episodes = {}
    with gzip.open(episodes_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                episodes[(row["set"], row["policy"], row["episode_index"])] = row
    decisions = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                decisions.setdefault((row["set"], row["policy"], row["episode_index"]), []).append(row)
    missing = [key for key in episodes if key not in decisions]
    counts = [key for key, rows in decisions.items()
              if key in episodes and len(rows) != episodes[key]["decisions"]]
    actions = [key for key, rows in decisions.items()
               if key in episodes
               and [row["action_index"] for row in sorted(rows, key=lambda r: r["step"])]
               != episodes[key]["actions"]]
    detail = {"decision_rows": sum(len(rows) for rows in decisions.values()),
              "battles_with_decisions": len(decisions), "battles_without": len(missing),
              "count_mismatches": len(counts), "action_mismatches": len(actions),
              "example_mismatch": (actions or counts or missing)[:2]}
    if missing or counts or actions:
        return False, (f"{len(missing)} battles have no decision records, {len(counts)} disagree "
                       f"on the decision count, {len(actions)} on the actions taken"), detail
    return True, (f"{detail['decision_rows']} decisions match the episodes step by step"), detail


def check_training_records(package):
    runs_path = package / "training" / "runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8"))
    names = sorted(r["run"] for r in runs["runs"])
    provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
    declared = sorted(r["run"] for r in provenance["training"]["runs"])
    problems = []
    if names != declared:
        problems.append(f"runs.json lists {names} but provenance lists {declared}")
    if len(runs["runs"]) != 6:
        problems.append(f"{len(runs['runs'])} runs recorded; the round compared six")
    for entry in provenance["training"]["runs"]:
        if not entry.get("selected_sha256") or not entry.get("last_sha256"):
            problems.append(f"{entry['run']} records no selected/last hash")
    shipped = [r["run"] for r in provenance["training"]["runs"] if r["run"] == "D384_s17"]
    if not shipped:
        problems.append("provenance does not record the shipped run D384_s17")
    detail = {"runs": names, "reused": [r["run"] for r in runs["runs"] if r.get("reused_from")]}
    if problems:
        return False, "; ".join(problems[:3]), detail
    return True, f"six runs recorded, {len(declared)} carry selected and last hashes", detail


def check_native_sources(package, repo):
    archive = package / "native_sources.tar.gz"
    manifest_path = package / "native_sources_manifest.json"
    if not archive.is_file() or not manifest_path.is_file():
        return False, "the offline source archive or its manifest is missing", {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = json.loads((repo / "engine_lock.json").read_text(encoding="utf-8"))
    problems = []
    if sha256(archive) != manifest.get("archive_sha256"):
        problems.append("the archive does not hash as its manifest says")
    if manifest.get("engine", {}).get("base_revision") != lock["revision"]:
        problems.append("the snapshot's base revision differs from engine_lock.json")
    if manifest.get("engine", {}).get("patch_order") != lock["patches"]:
        problems.append("the snapshot's patch order differs from engine_lock.json")
    states = {entry["patch_state"] for entry in manifest.get("files", [])
              if entry.get("origin") == "sts_lightspeed"}
    if states != {"PRE_PATCH"}:
        problems.append(f"engine files are not PRE_PATCH: {sorted(states)}")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    escaped = [n for n in names if n.startswith("/") or ".." in Path(n).parts]
    odd = [m.name for m in tarfile.open(archive).getmembers() if not m.isfile() and not m.isdir()]
    if escaped:
        problems.append(f"{len(escaped)} archive member(s) escape the extraction root")
    if odd:
        problems.append(f"{len(odd)} archive member(s) are links or devices, not files: {odd[:3]}")
    detail = {"archive_sha256": sha256(archive), "files": len(manifest.get("files", [])),
              "members": len(names), "base_revision": manifest.get("engine", {}).get("base_revision")}
    if problems:
        return False, "; ".join(problems[:3]), detail
    return True, f"snapshot verified, {len(names)} members, base {lock['revision'][:12]}", detail


def check_artifact_lock(package, lock_path, repo):
    """Every artefact input must match the round's locked digest, not merely exist."""
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    digests = lock.get("sha256", lock)
    problems, checked = [], 0
    for entry in contract.artifact_entries():
        expected = digests.get(entry["source_path"]) or digests.get(entry["package_path"])
        path = package / entry["package_path"]
        if expected is None:
            problems.append(f"{entry['package_path']} has no locked digest")
            continue
        if not path.is_file():
            problems.append(f"{entry['package_path']} is absent")
            continue
        checked += 1
        if sha256(path) != expected:
            problems.append(f"{entry['package_path']} does not match the locked digest")
    if problems:
        return False, "; ".join(problems[:4]), {"checked": checked}
    return True, f"{checked} artefact inputs match the lock", {"checked": checked}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="the checkout the package will be reviewed against")
    parser.add_argument("--package", required=True, help="the unpacked package directory, or its .zip")
    parser.add_argument("--out", required=True, help="where to write the structured receipt")
    parser.add_argument("--lock", default=None, help="a JSON map of source path -> sha256 for artefacts")
    parser.add_argument("--work", default=None, help="scratch directory, required for a .zip package")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    rows = []
    work = Path(args.work).resolve() if args.work else None
    package, kind, unsafe = open_package(args.package, work or Path(tempfile.mkdtemp(prefix="stsai-check-")))

    report_add(rows, "package_root", True, f"{kind} package at {package}")
    report_add(rows, "archive_safety", not unsafe,
               f"{len(unsafe)} unsafe member(s): {unsafe[:3]}" if unsafe else "no unsafe archive members")
    layout_ok, layout_note, missing = check_layout(package)
    report_add(rows, "layout", layout_ok, layout_note)
    manifest_ok, manifest_note, manifest_detail = check_manifest(package)
    report_add(rows, "manifest", manifest_ok, manifest_note)
    scope_ok, scope_note, _ = check_path_scope(package, kind, unsafe)
    report_add(rows, "path_scope", scope_ok, scope_note)

    # The remaining checks read package contents; a package that failed the layout
    # check is described as it is rather than cascading into misleading findings.
    if not layout_ok:
        for name in ("provenance", "versions", "protocol_identity", "model_identity",
                     "evaluation_records", "decision_records", "training_records",
                     "native_sources"):
            report_add(rows, name, None, "not evaluated: the package is incomplete", required=True)
    else:
        ok, note, detail = check_provenance(package, repo)
        report_add(rows, "provenance", ok, note)
        ok, note, _ = check_versions(package, repo)
        report_add(rows, "versions", ok, note)
        ok, note, protocol_detail = check_protocol_identity(package)
        report_add(rows, "protocol_identity", ok, note)
        ok, note, _ = check_model(package)
        report_add(rows, "model_identity", ok, note)
        ok, note, episode_detail = check_evaluation_records(package)
        report_add(rows, "evaluation_records", ok, note)
        ok, note, _ = check_decision_records(package,
                                             package / "evaluation" / "episodes.jsonl.gz")
        report_add(rows, "decision_records", ok, note)
        ok, note, _ = check_training_records(package)
        report_add(rows, "training_records", ok, note)
        ok, note, _ = check_native_sources(package, repo)
        report_add(rows, "native_sources", ok, note)

    if args.lock:
        ok, note, _ = check_artifact_lock(package, args.lock, repo)
        report_add(rows, "artifact_lock", ok, note)

    receipt = {"kind": "s2r_input_contract_check", "contract_version": contract.CONTRACT_VERSION,
               "repo": str(repo), "package": str(Path(args.package).resolve()), "package_kind": kind,
               "checks": rows,
               "manifest": manifest_detail,
               "required_inputs": len(contract.REQUIRED_INPUTS)}
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    blocking = [r for r in rows if r["required"] and r["status"] != "PASS"]
    print(f"receipt: {out}")
    if blocking:
        print("blocking: " + ", ".join(f"{r['check']}={r['status']}" for r in blocking), file=sys.stderr)
        raise SystemExit(1)
    print("the package satisfies the input contract")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
