#!/usr/bin/env python3
"""Write the S2 protocol, on top of the frozen lists, before anything is collected.

    python scripts/gen_s2_protocol.py [--out reports/s2_protocol.json]

The protocol is committed before the first new trajectory and before the first
training run, so the run table, the resource limits, the selection rule and the
statistical direction are on the record rather than reconstructed from what
happened to be done.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    # The earlier S2 round (sampler/louse fixes) already owns reports/s2_protocol.json;
    # this round writes its own file rather than overwriting that report.
    parser.add_argument("--out", default="reports/s2_volume_protocol.json")
    parser.add_argument("--config", default="configs/s1_m128_r0_s17.json")
    args = parser.parse_args()

    from stsai.encoding import ENCODING_REVISION
    from stsai.native import SAMPLER_REVISION
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import LOSS_REVISION, SCHEMA_VERSION

    lock = json.loads((ROOT / "engine_lock.json").read_text())
    lists = json.loads((ROOT / "reports/s2_dev_lists.json").read_text())
    config = json.loads((ROOT / args.config).read_text())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()

    protocol = {
        "purpose": "S2 protocol (fixed training budget, data-volume contrast), written before any "
                   "new collection or training.",
        "file_name_note": "stored as reports/s2_volume_protocol.json because the earlier S2 "
                          "round (s2/louse-and-events) owns reports/s2_protocol.json; that "
                          "report is left untouched",
        "question": "With the same model, teacher, scenario distribution, optimizer-update ceiling "
                    "and checkpoint rule, does raising the number of independent training battles "
                    "from 96 to 384 improve the student's utility on the development scenarios?",
        "fixed_budget_means": "same model, same effective batch, at most 500 optimizer updates. "
                              "The extra teacher collection is reported separately; this is not a "
                              "claim of equal total project compute.",
        "baseline_commit": "c31ba2f02dccb92ff96d593e14ed5b3dd2644183",
        "protocol_written_on_top_of": head,
        "branch": subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip(),
        "engine": {
            "revision": lock["revision"], "url": lock["url"],
            "json_submodule": lock["json_submodule"],
            "patches": [{"file": entry["file"], "sha256": entry["sha256"]}
                        for entry in lock["patches"]],
            "snapshot_archive_sha256": json.loads(
                (ROOT / "native" / "native_sources_manifest.json").read_text())["archive_sha256"],
        },
        "versions": {"observation_schema": SCHEMA_VERSION, "encoding_revision": ENCODING_REVISION,
                     "loss_revision": LOSS_REVISION, "sampler_revision": SAMPLER_REVISION,
                     "scenario_revision": SCENARIO_REVISION, "utility_revision": UTILITY_REVISION},
        "s1r_weight_sha256": "57ffb03f01d5e7b163bf952b004dc4b07535563bccdedc8b8586a22e5fceaf04",
        "s1r_compatibility": "reports/s2_semantic_compatibility.json: patch 0005 is one standard "
                             "header include, and the five-patch build replays the 256 "
                             "development episodes identically to the S1R record",
        "data": {
            "shards": {name: lists["shards"][name] for name in ("D96", "V24")},
            "D96_manifest_sha256": lists["shards"]["D96_manifest_sha256"],
            "V24_manifest_sha256": lists["shards"]["V24_manifest_sha256"],
            "lists": lists["lists"], "overlaps": lists["overlaps"],
            "new_collection": {"directory": "data/s2/add288", "split": "train", "start": 96,
                               "count": 288, "workers_max": 2, "iterations": 1,
                               "master_seed": 20260916, "max_actions": 256, "sample_actions": True,
                               "search": config["search"],
                               "note": "same generator, same teacher budget, no student, no network "
                                       "prior, no leaf value"},
            "composition": "D384 is read from two verified directories, data/s1r/train and "
                           "data/s2/add288; D96 is a strict subset of D384 and appears once. The "
                           "collection.json of neither directory is edited to fake a single source.",
        },
        "dev_sets": {
            "DEV_OLD256": {"sha256": lists["lists"]["DEV_OLD256"]["sha256"], "already_used": True,
                           "role": "secondary diagnostic; a reused development set, not a test"},
            "DEV_PROBE256": {"sha256": lists["lists"]["DEV_PROBE256"]["sha256"],
                             "master_seed": lists["master_seeds"]["dev_probe256"],
                             "role": "primary comparison set; materialised before training, run "
                                     "only after every checkpoint is selected on V24, marked used "
                                     "from the first read; not P6 and not a held-out test"},
        },
        "run_table": [
            {"run": "D96_s17", "data": "D96", "init_seed": 17, "execution": "reuse the S1R run"},
            {"run": "D96_s29", "data": "D96", "init_seed": 29, "execution": "new"},
            {"run": "D96_s43", "data": "D96", "init_seed": 43, "execution": "new"},
            {"run": "D384_s17", "data": "D384", "init_seed": 17, "execution": "new"},
            {"run": "D384_s29", "data": "D384", "init_seed": 29, "execution": "new"},
            {"run": "D384_s43", "data": "D384", "init_seed": 43, "execution": "new"},
        ],
        "training_config": config["training"],
        "training_config_note": "data_seed stays 42 for every run; only init_seed varies. Random "
                                "initialisation, no warm start, no architecture change.",
        "selection": {
            "metric": "kl_dev: mean over battles of the per-battle mean decision-state KL on the "
                      "full V24 labelled validation set",
            "excluded": "states with a single legal action do not enter the primary metric",
            "ties": "keep the earlier step",
            "reporting": "selected and last are reported separately with their own step and sha256 "
                         "and are never mixed",
            "secondary": "teacher_choice_agreement_decision_states is the reported teacher "
                         "agreement; teacher_top1_agreement is a legacy diagnostic that includes "
                         "forced states and visit-argmax ties",
            "no_reselection": "development results never reselect a checkpoint or a seed",
        },
        "evaluation": {
            "sets": ["DEV_OLD256", "DEV_PROBE256"],
            "policies": ["six selected networks", "heuristic", "search (64 simulations)"],
            "device": "CPU FP32, batch one, torch threads fixed at 1 for every policy",
            "budget": {"network_episodes": 6 * 512, "baseline_episodes": 2 * 512, "total": 4096,
                       "max_actions": 256},
            "baselines_rerun": "heuristic and search are re-run once per set in the current code; "
                               "the S1R search scores are not reused as a current baseline",
            "truncation": "an episode that reaches the action ceiling is reported separately and "
                          "counts as utility 0 in the conservative primary summary, with a "
                          "complete-pairs sensitivity result beside it",
            "recording": "per-episode win/loss/truncation/HP/utility/decisions and per-decision "
                         "action index and latency, gzip jsonl",
        },
        "statistics": {
            "primary": "delta_s,i = utility(D384, seed s, scenario i) - utility(D96, seed s, "
                       "scenario i) on DEV_PROBE256, for s in {17, 29, 43}",
            "report": ["three paired deltas with scenario-bootstrap intervals",
                       "mean, standard deviation and range of the three seed means",
                       "an overall interval from per-scenario means over the three seeds, "
                       "resampled over scenarios"],
            "bootstrap": {"replicates": 20000, "seed": 20260920, "unit": "scenario"},
            "conditional_on": "the three trained seeds; this does not cover training randomness",
            "not_independent": "the 3x256 rows are not 768 independent scenarios",
            "direction": "positive means D384 is better",
            "also_reported": "each configuration and seed against heuristic and search on both "
                             "sets, same treatment; per-encounter and per-family strata are "
                             "exploratory and carry their n",
            "decision_rule": {
                "supports_d384": "all three seeds move the same way, the mean difference is "
                                 "positive, and the conditional scenario interval's lower bound "
                                 "is above 0",
                "insufficient": "the interval crosses 0, the seeds disagree in direction, or the "
                                "two development sets disagree - reported as insufficient "
                                "evidence, with both configurations kept and no extra seeds",
                "kl_without_utility": "if KL improves without a confirmed utility gain, that is "
                                      "recorded as distribution fit not transferring, and no "
                                      "DAgger, value audit or new teacher target is added",
                "not_a_threshold": "auxiliary-head losses are not a pass criterion, and no new "
                                   "Brier/ECE conclusion is reported without per-sample "
                                   "predictions and labels",
            },
        },
        "resource_limits": {
            "new_collection_episodes": 288, "collection_workers_max": 2,
            "new_training_runs_max": 5, "optimizer_updates_max": 500,
            "evaluation_episodes": 4096, "max_actions": 256,
            "bootstrap_replicates": 20000, "bootstrap_seed": 20260920,
            "training_seeds": [17, 29, 43], "cloud": False, "p6": False,
            "prohibited": ["192-dim model", "capacity or structure changes", "reward or teacher "
                           "budget changes", "DAgger", "hybrid search", "leaf value", "mechanism "
                           "expansion", "a fourth training seed", "P6"],
        },
        "claim": "unverified simulator pilot with a declared sampling approximation; "
                 "game_differential_verified=false",
    }
    out = ROOT / args.out
    out.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} (protocol on top of {head[:7]})")


if __name__ == "__main__":
    main()
