"""The input contract: a package that cannot be reviewed must not be accepted.

Each test builds a small package that satisfies the contract, breaks exactly one
thing, and requires `review/check_review_inputs.py` to exit non-zero. The mutations
are the ones that would otherwise be found only after a cold build: a missing
weight, records reduced to a summary, a tampered member, an S1R weight standing in
for the S2 one, a member that escapes the package, an unsafe archive entry, and a
package written against another round's semantics.

The fixture is synthetic on purpose - the real package is a 13 MB release
attachment, not something a unit test should need.
"""
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "review"))

import package_contract as contract  # noqa: E402

CHECKER = ROOT / "review" / "check_review_inputs.py"
D384_FINGERPRINT = "749254379e59f4295ebd96f37014fd7dc18630d5ce3fd4e7b2eb8187bca0d1c2"
D96_FINGERPRINT = "a7b6882273cd828688442c0f85bd9549e41ab9f8d405b6fef119886ac1cc2b02"
RUNS = ["D96_s17", "D96_s29", "D96_s43", "D384_s17", "D384_s29", "D384_s43"]
SETS = ["dev_old256", "dev_probe256"]
SCENARIOS = 3


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")


def build_package(root):
    """A package that satisfies every check, small enough for a test."""
    package = root / "package"
    for entry in contract.REQUIRED_INPUTS:
        (package / entry["package_path"]).parent.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "engine_lock.json").read_text(encoding="utf-8"))
    versions = {field: getattr(__import__(module, fromlist=[attribute]), attribute)
                for field, (module, attribute) in contract.VERSION_FIELDS.items()}

    protocol = {"purpose": "test", "question": "does 384 beat 96 under a fixed budget",
                "fixed_budget_means": "at most 500 optimizer updates", "baseline_commit": "a" * 40,
                "run_table": [{"run": name} for name in RUNS], "training_config": {},
                "selection": {}, "evaluation": {}, "statistics": {}, "resource_limits": {},
                "versions": versions, "data": {}}
    runs = {"runs": [{"run": name, "selected_step": 400, "reused_from": None,
                      "data_fingerprint": D384_FINGERPRINT if name.startswith("D384")
                      else D96_FINGERPRINT} for name in RUNS]}
    scenarios = {name: {"scenarios": [{"index": i} for i in range(SCENARIOS)]} for name in SETS}
    episodes = []
    for set_name in SETS:
        for policy in RUNS + contract.BASELINE_POLICIES:
            for index in range(SCENARIOS):
                episodes.append({"set": set_name, "policy": policy, "episode_index": index,
                                 "completed": True, "utility": 0.5, "truncated": False, "won": True,
                                 "end_hp": 10, "decisions": 3, "actions": [0, 1],
                                 "action_sequence_sha256": "0" * 64})
    export = {"format_version": 1, "model_config": {"d_model": 4}, "model_state": {"w": torch.zeros(2)},
              "backend": "reference_v1", "encoding_revision": versions["encoding_revision"],
              "observation_schema": versions["observation_schema"],
              "loss_revision": versions["loss_revision"],
              "sampler_revision": versions["sampler_revision"],
              "data_fingerprint": D384_FINGERPRINT,
              "export": {"source_checkpoint": "runs/s2/D384_s17/model/best.pt",
                         "source_sha256": "b" * 64, "source_step": 500, "source_epoch": 2}}
    (package / "model").mkdir(parents=True, exist_ok=True)
    torch.save(export, package / "model" / "D384_s17_selected.pt")

    write(package / "protocol.json", protocol)
    write(package / "semantic_compatibility.json", {"kind": "test"})
    for name in ("review/README.md", "review/run_review.py", "review/offline_native_build.py",
                 "review/counterfactual_replay.py", "review/model_smoke.py",
                 "review/recompute_s2.py", "data/composition_and_shards.json", "data/coverage.json",
                 "model/smoke_expected.json", "training/selected_summary.csv",
                 "reports/known_limitations.md", "reports/commands_and_limits.md"):
        write(package / name, "placeholder\n")
    write(package / "training/runs.json", runs)
    with gzip.open(package / "training/metrics.jsonl.gz", "wt") as handle:
        handle.write("{}\n")
    with gzip.open(package / "training/validation.jsonl.gz", "wt") as handle:
        handle.write("{}\n")
    with gzip.open(package / "model/smoke_observations.jsonl.gz", "wt") as handle:
        handle.write("{}\n")
    with gzip.open(package / "data/initial_scenarios.json.gz", "wt") as handle:
        handle.write("{}")
    with gzip.open(package / "evaluation/scenarios.json.gz", "wt") as handle:
        handle.write(json.dumps(scenarios))
    with gzip.open(package / "evaluation/episodes.jsonl.gz", "wt") as handle:
        for row in episodes:
            handle.write(json.dumps(row) + "\n")
    with gzip.open(package / "evaluation/decision_latency.jsonl.gz", "wt") as handle:
        handle.write("{}\n")
    write(package / "tests/junit.xml", "<testsuite tests='0'/>")
    with gzip.open(package / "tests/build_and_test.log.gz", "wt") as handle:
        handle.write("build log\n")
    write(package / "evaluation/paired_summary.json", {"mean": 0.0})

    snapshot = root / "snapshot"
    (snapshot / "native_sources").mkdir(parents=True)
    write(snapshot / "native_sources" / "engine.cpp", "// pre-patch\n")
    archive = package / "native_sources.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(snapshot / "native_sources", arcname="native_sources")
    write(package / "native_sources_manifest.json",
          {"archive_sha256": sha256(archive),
           "engine": {"base_revision": lock["revision"], "patch_order": lock["patches"]},
           "files": [{"path": "engine.cpp", "sha256": sha256(snapshot / "native_sources/engine.cpp"),
                      "origin": "sts_lightspeed", "patch_state": "PRE_PATCH"}]})

    write(package / "provenance.json",
          {"head": "c" * 40, "branch": "s2/fixed-budget-data",
           "protocol": {"baseline_commit": "a" * 40,
                        "protocol_file": {"sha256": sha256(package / "protocol.json")}},
           "engine": {"revision": lock["revision"],
                      "patches": [{"file": p["file"], "sha256": p["sha256"]} for p in lock["patches"]]},
           "versions": versions,
           "training": {"runs": [{"run": name, "selected_sha256": "b" * 64, "last_sha256": "d" * 64}
                                 for name in RUNS]},
           "model": {"shipped": {"sha256": sha256(package / "model/D384_s17_selected.pt")}},
           "evaluation": {"episodes": {"sha256": sha256(package / "evaluation/episodes.jsonl.gz")},
                          "decisions": {"sha256": sha256(package / "evaluation/decision_latency.jsonl.gz")}}})

    reseal(package)
    return package


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    root = tmp_path_factory.mktemp("contract")
    return build_package(root)


def run_checker(package, tmp_path, extra=()):
    out = tmp_path / "receipt.json"
    result = subprocess.run([sys.executable, str(CHECKER), "--repo", str(ROOT),
                             "--package", str(package), "--out", str(out), *extra],
                            capture_output=True, text=True)
    receipt = json.loads(out.read_text()) if out.is_file() else {"checks": []}
    return result, {row["check"]: row["status"] for row in receipt["checks"]}, receipt


def reseal(package):
    """Rewrite the manifest after a test has changed a member."""
    entries = sorted(p for p in package.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (package / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(package).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")


def copied(package, tmp_path, name):
    target = tmp_path / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(package, target, symlinks=True)
    return target


def test_a_complete_package_is_accepted(package, tmp_path):
    result, statuses, receipt = run_checker(package, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(statuses.values()) == {"PASS"}
    evaluation = next(row for row in receipt["checks"] if row["check"] == "evaluation_records")
    assert evaluation["status"] == "PASS"


def test_a_missing_weight_is_rejected(package, tmp_path):
    broken = copied(package, tmp_path, "no_model")
    (broken / "model/D384_s17_selected.pt").unlink()
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["layout"] == "FAIL"
    assert "model/D384_s17_selected.pt" in result.stdout


def test_a_weight_with_optimizer_state_is_rejected(package, tmp_path):
    """A training checkpoint renamed as the export must not pass as an export."""
    broken = copied(package, tmp_path, "checkpoint_weight")
    path = broken / "model/D384_s17_selected.pt"
    payload = torch.load(path, map_location="cpu", weights_only=True)
    payload["optimizer_state"] = {"state": {}}
    torch.save(payload, path)
    entries = sorted(p for p in broken.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (broken / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(broken).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["model_identity"] == "FAIL"
    assert "optimizer" in result.stdout


def test_an_s1r_weight_substituted_for_the_s2_one_is_rejected(package, tmp_path):
    """Same architecture, same semantics, other round's data: still not the S2 weight."""
    broken = copied(package, tmp_path, "s1r_weight")
    path = broken / "model/D384_s17_selected.pt"
    payload = torch.load(path, map_location="cpu", weights_only=True)
    payload["data_fingerprint"] = D96_FINGERPRINT
    torch.save(payload, path)
    entries = sorted(p for p in broken.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (broken / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(broken).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["model_identity"] == "FAIL"
    assert "data_fingerprint" in result.stdout


def test_summary_without_per_episode_records_is_rejected(package, tmp_path):
    broken = copied(package, tmp_path, "summary_only")
    (broken / "evaluation/episodes.jsonl.gz").unlink()
    (broken / "evaluation/decision_latency.jsonl.gz").unlink()
    entries = sorted(p for p in broken.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (broken / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(broken).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["layout"] == "FAIL"
    assert "episodes.jsonl.gz" in result.stdout
    assert "only a summary is present" not in result.stdout  # the files are gone, not summarised


def test_a_tampered_member_is_rejected(package, tmp_path):
    broken = copied(package, tmp_path, "tampered")
    write(broken / "data/coverage.json", {"tampered": True})
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["manifest"] == "FAIL"
    assert "data/coverage.json" in result.stdout


def test_a_half_filled_episode_grid_is_rejected(package, tmp_path):
    """Dropping the scenarios that did not suit the conclusion must not pass."""
    broken = copied(package, tmp_path, "partial_grid")
    rows = []
    with gzip.open(broken / "evaluation/episodes.jsonl.gz", "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if not (row["set"] == "dev_probe256" and row["policy"] == "D384_s17"
                    and row["episode_index"] == 0):
                rows.append(row)
    with gzip.open(broken / "evaluation/episodes.jsonl.gz", "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    entries = sorted(p for p in broken.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (broken / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(broken).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["evaluation_records"] == "FAIL"
    assert "declared keys have no record" in result.stdout


def test_another_rounds_semantics_are_rejected(package, tmp_path):
    broken = copied(package, tmp_path, "old_versions")
    protocol = json.loads((broken / "protocol.json").read_text())
    protocol["versions"]["encoding_revision"] = 4
    write(broken / "protocol.json", protocol)
    provenance = json.loads((broken / "provenance.json").read_text())
    provenance["protocol"]["protocol_file"]["sha256"] = sha256(broken / "protocol.json")
    write(broken / "provenance.json", provenance)
    entries = sorted(p for p in broken.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (broken / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(broken).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["versions"] == "FAIL"
    assert "encoding_revision" in result.stdout


def test_a_member_that_escapes_the_package_is_rejected(package, tmp_path):
    broken = copied(package, tmp_path, "escaping_member")
    outside = tmp_path / "outside_weight.pt"
    shutil.copy2(broken / "model/D384_s17_selected.pt", outside)
    (broken / "model/D384_s17_selected.pt").unlink()
    (broken / "model/D384_s17_selected.pt").symlink_to(outside)
    result, statuses, _ = run_checker(broken, tmp_path)
    assert result.returncode != 0
    assert statuses["path_scope"] == "FAIL"
    assert "outside the package root" in result.stdout


def test_an_unsafe_archive_member_is_rejected(package, tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("package/protocol.json", "{}")
        handle.writestr("../escaped.json", "{}")
        handle.writestr("/absolute.json", "{}")
    result, statuses, receipt = run_checker(archive, tmp_path, extra=["--work", str(tmp_path / "w")])
    assert result.returncode != 0
    assert statuses["archive_safety"] == "FAIL"
    assert not (tmp_path / "escaped.json").exists()


def test_a_locked_artifact_that_changed_is_rejected(package, tmp_path):
    lock = tmp_path / "lock.json"
    entry = next(e for e in contract.artifact_entries())
    lock.write_text(json.dumps({"sha256": {entry["source_path"]: "0" * 64}}), encoding="utf-8")
    result, statuses, _ = run_checker(package, tmp_path, extra=["--lock", str(lock)])
    assert result.returncode != 0
    assert statuses["artifact_lock"] == "FAIL"


def test_contract_sources_resolve_or_are_declared_artifacts():
    """Every listed source is either tracked in this checkout or declared an artifact.

    This is the reorganisation guard: moving a directory without updating the
    contract leaves an entry that resolves nowhere, which no longer silently
    produces a package with a missing input.
    """
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    tracked = set(tracked)
    for entry in contract.REQUIRED_INPUTS:
        if entry["residency"] == "repository":
            assert entry["source_path"] in tracked, \
                f"{entry['source_path']} is declared as a repository input but is not tracked"
            assert (ROOT / entry["source_path"]).is_file(), entry["source_path"]
        else:
            assert entry["source_path"] not in tracked or entry["source_path"].endswith(".pt"), \
                f"{entry['source_path']} is declared as an artifact but is tracked in git"


def test_the_packer_and_the_checker_share_one_list():
    """The packer derives its list instead of keeping a second copy of it.

    A packer with its own list can drift from the checker silently: the package it
    builds then fails a check nobody changed.
    """
    import ast
    source = (ROOT / "scripts" / "make_s2_package.py").read_text(encoding="utf-8")
    assignment = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.Assign)
                      and getattr(node.targets[0], "id", "") == "FILES")
    segment = ast.get_source_segment(source, assignment)
    assert "contract.REQUIRED_INPUTS" in segment
    hardcoded = [entry["package_path"] for entry in contract.REQUIRED_INPUTS
                 if entry["package_path"] in segment]
    assert not hardcoded, f"the packer still hardcodes {hardcoded[:3]}"
