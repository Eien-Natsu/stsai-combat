"""What an S2 review package must contain, as data.

Both ends of the round read this one list: `scripts/make_s2_package.py` builds a
package from it, `review/check_review_inputs.py` verifies a package against it.
Keeping one list is the point - a checker with its own copy would drift from the
packer and then agree with nobody.

`residency` says where a source comes from:

  repository  the file is tracked by git and a clean checkout has it
  artifact    the file is a run artefact (weights, per-episode records, materialised
              scenarios, collection coverage). It is deliberately NOT in git, so it
              must be resolved against an explicit artifact root and is expected to
              travel as a release attachment with a locked SHA256.

Nothing here asserts that the historical package was complete; it says what a
package has to contain to be reviewable.
"""

CONTRACT_VERSION = 1

REQUIRED_INPUTS = [
    # protocol and argument
    {"package_path": "protocol.json", "source_path": "reports/s2_volume_protocol.json",
     "residency": "repository", "kind": "protocol"},
    {"package_path": "semantic_compatibility.json", "source_path": "reports/s2_semantic_compatibility.json",
     "residency": "repository", "kind": "protocol"},
    # native sources, offline
    {"package_path": "native_sources.tar.gz", "source_path": "native/native_sources.tar.gz",
     "residency": "repository", "kind": "native"},
    {"package_path": "native_sources_manifest.json", "source_path": "native/native_sources_manifest.json",
     "residency": "repository", "kind": "native"},
    # the review chain itself
    {"package_path": "review/README.md", "source_path": "review/README.md",
     "residency": "repository", "kind": "review"},
    {"package_path": "review/run_review.py", "source_path": "review/run_review.py",
     "residency": "repository", "kind": "review"},
    {"package_path": "review/offline_native_build.py", "source_path": "review/offline_native_build.py",
     "residency": "repository", "kind": "review"},
    {"package_path": "review/counterfactual_replay.py", "source_path": "review/counterfactual_replay.py",
     "residency": "repository", "kind": "review"},
    {"package_path": "review/model_smoke.py", "source_path": "review/model_smoke.py",
     "residency": "repository", "kind": "review"},
    {"package_path": "review/recompute_s2.py", "source_path": "review/recompute_s2.py",
     "residency": "repository", "kind": "review"},
    # data
    {"package_path": "data/initial_scenarios.json.gz",
     "source_path": "runs/s2/package_data/data/initial_scenarios.json.gz",
     "residency": "artifact", "kind": "data"},
    {"package_path": "data/composition_and_shards.json",
     "source_path": "runs/s2/package_data/data/composition_and_shards.json",
     "residency": "artifact", "kind": "data"},
    {"package_path": "data/coverage.json", "source_path": "runs/s2/package_data/data/coverage.json",
     "residency": "artifact", "kind": "data"},
    # training records
    {"package_path": "training/runs.json", "source_path": "training/runs.json",
     "residency": "repository", "kind": "training"},
    {"package_path": "training/metrics.jsonl.gz", "source_path": "training/metrics.jsonl.gz",
     "residency": "repository", "kind": "training"},
    {"package_path": "training/validation.jsonl.gz", "source_path": "training/validation.jsonl.gz",
     "residency": "repository", "kind": "training"},
    {"package_path": "training/selected_summary.csv", "source_path": "training/selected_summary.csv",
     "residency": "repository", "kind": "training"},
    # the one shipped weight, as an inference export
    {"package_path": "model/D384_s17_selected.pt", "source_path": "model/D384_s17_selected.pt",
     "residency": "artifact", "kind": "model"},
    {"package_path": "model/smoke_observations.jsonl.gz", "source_path": "model/smoke_observations.jsonl.gz",
     "residency": "repository", "kind": "model"},
    {"package_path": "model/smoke_expected.json", "source_path": "model/smoke_expected.json",
     "residency": "repository", "kind": "model"},
    # evaluation: materialised scenarios and the per-episode records
    {"package_path": "evaluation/scenarios.json.gz",
     "source_path": "runs/s2/package_data/evaluation/scenarios.json.gz",
     "residency": "artifact", "kind": "evaluation"},
    {"package_path": "evaluation/episodes.jsonl.gz", "source_path": "runs/s2/evaluation/episodes.jsonl.gz",
     "residency": "artifact", "kind": "evaluation"},
    {"package_path": "evaluation/decision_latency.jsonl.gz",
     "source_path": "runs/s2/evaluation/decision_latency.jsonl.gz",
     "residency": "artifact", "kind": "evaluation"},
    {"package_path": "evaluation/paired_summary.json", "source_path": "reports/s2_paired_summary.json",
     "residency": "repository", "kind": "evaluation"},
    # round evidence
    {"package_path": "tests/junit.xml", "source_path": "reports/s2_junit.xml",
     "residency": "repository", "kind": "evidence"},
    {"package_path": "tests/build_and_test.log.gz", "source_path": "reports/s2_build_and_test.log",
     "residency": "repository", "kind": "evidence", "gzip_on_pack": True},
    {"package_path": "reports/known_limitations.md", "source_path": "reports/s2_known_limitations.md",
     "residency": "repository", "kind": "evidence"},
    {"package_path": "reports/commands_and_limits.md", "source_path": "reports/s2_commands_and_limits.md",
     "residency": "repository", "kind": "evidence"},
]

# Written while assembling the package rather than copied from the checkout.
GENERATED_IN_PACKAGE = [
    "MANIFEST.sha256",          # every other member's digest; written last
    "provenance.json",          # hashes and the run/engine records, generated
    "repo.bundle",              # the history, so the package can be cloned
    "INDEX.md",
    "SUMMARY.md",
    "reports/command_log.txt",  # the raw logs concatenated
]

# Fields the per-episode records must carry for an independent recomputation.
EPISODE_FIELDS = ["set", "policy", "episode_index", "completed", "utility", "truncated",
                  "won", "end_hp", "decisions", "actions", "action_sequence_sha256"]

# The policies the round compared: the six trained runs plus the two baselines.
BASELINE_POLICIES = ["heuristic", "search"]

# What the shipped weight must be: an inference export of the selected D384 run,
# with the optimizer state removed, not a training checkpoint and not another round's.
MODEL_EXPORT_REQUIRED_KEYS = ["format_version", "model_config", "model_state", "backend",
                              "encoding_revision", "observation_schema", "loss_revision",
                              "sampler_revision", "export", "data_fingerprint"]
MODEL_EXPORT_FORBIDDEN_KEYS = ["optimizer_state"]

# Version fields the package declares, and the module attribute each must equal.
VERSION_FIELDS = {
    "observation_schema": ("stsai.util", "SCHEMA_VERSION"),
    "encoding_revision": ("stsai.encoding", "ENCODING_REVISION"),
    "loss_revision": ("stsai.util", "LOSS_REVISION"),
    "utility_revision": ("stsai.objective", "UTILITY_REVISION"),
    "scenario_revision": ("stsai.scenarios", "SCENARIO_REVISION"),
    "sampler_revision": ("stsai.native", "SAMPLER_REVISION"),
}


def required(package_path):
    for entry in REQUIRED_INPUTS:
        if entry["package_path"] == package_path:
            return entry
    return None


def artifact_entries():
    return [entry for entry in REQUIRED_INPUTS if entry["residency"] == "artifact"]


def repository_entries():
    return [entry for entry in REQUIRED_INPUTS if entry["residency"] == "repository"]


def resolve_source(entry, repo, artifacts):
    """Where to read this input from, given a checkout and an artifact root."""
    root = artifacts if entry["residency"] == "artifact" else repo
    return root / entry["source_path"]
