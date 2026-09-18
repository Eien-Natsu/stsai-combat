#!/usr/bin/env python3
"""Rebuild the S1 trajectories on the same initial scenarios with the fixed sampler.

    python scripts/s1r_rebuild_data.py --s1 data/s1 --out data/s1r \
        [--config configs/native_pilot.json] [--workers 2]

The initial scenarios are fixed: `make_scenario(backend, split, index, master_seed)`
is deterministic, and the S1 collection materialised them per episode, so every
index is re-derived here and compared with the recorded scenario and episode
seed before anything is collected. Nothing is reused from the pre-fix labels:
every trajectory is played again under the fixed sampler and the current
observation schema, which is the point of the rebuild.

The report records what the round is required to state in the open: the number
of independent battles, total states, decision states, terminal and truncated
counts, the utility definition, and where each split's continuation comes from.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.collection import collect  # noqa: E402
from stsai.objective import UTILITY_REVISION, terminal_utility  # noqa: E402
from stsai.scenarios import make_scenario  # noqa: E402
from stsai.util import atomic_json, digest  # noqa: E402

CONTINUATION = {
    "train": "behaviour continuation (sample_actions=true): the episode's own ending is "
             "written to every state; the search still produces the top-1 target",
    "val": "greedy teacher continuation (sample_actions=false): the label comes from the "
           "teacher's own recommendation, not from a sampled action",
}


def sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_initial_scenarios(s1, split, master_seed):
    """Every index this round will collect must be the one S1 materialised."""
    directory = Path(s1) / split
    metas = sorted(directory.glob("episode_*.meta.json"))
    if not metas:
        raise SystemExit(f"no S1 materialised scenarios under {directory}")
    checked = []
    for path in metas:
        recorded = json.loads(path.read_text())
        index = recorded["episode_index"]
        scenario, seed, family = make_scenario("lightspeed_pilot", split, index, master_seed)
        ok = (digest(scenario) == digest(recorded["scenario"]) and seed == recorded["episode_seed"]
              and family == recorded["family"])
        if not ok:
            raise SystemExit(f"{split}[{index}] does not reproduce the S1 initial scenario")
        checked.append({"index": index, "episode_seed": seed, "family": family,
                        "scenario_sha256": digest(scenario), "s1_meta_sha256": sha256(path)})
    return checked


def describe(out_dir, split):
    """Counts the report has to state, taken from the shards that were written."""
    shards = sorted(Path(out_dir).glob("episode_*.jsonl.gz"))
    states = decisions = completed = 0
    shard_hashes = {}
    for shard in shards:
        shard_hashes[shard.name] = sha256(shard)
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                states += 1
                if len(row["observation"]["actions"]) > 1:
                    decisions += 1
    metas = [json.loads(p.read_text()) for p in sorted(Path(out_dir).glob("episode_*.meta.json"))]
    completed = sum(1 for m in metas if m["completed"])
    utility = [m["utility"] for m in metas if m["completed"]]
    return {"independent_battles": len(shards), "total_states": states,
            "decision_states": decisions, "forced_states": states - decisions,
            "completed": completed, "truncated": len(metas) - completed,
            "wins": sum(1 for m in metas if m["won"] is True),
            "mean_utility_completed": (sum(utility) / len(utility)) if utility else None,
            "continuation": CONTINUATION[split], "shards": shard_hashes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1", default="data/s1")
    parser.add_argument("--out", default="data/s1r")
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--report", default="reports/s1r_collection_report.json")
    parser.add_argument("--manifest", default="training/data_manifests.json")
    parser.add_argument("--scenarios", default="training/initial_scenarios.json")
    args = parser.parse_args()
    if args.workers > 2:
        raise SystemExit("the protocol allows at most two collection workers")

    config = json.loads((ROOT / args.config).read_text())
    report = {"purpose": "S1R data rebuild: same initial scenarios, fixed sampler, new semantics.",
              "s1_source": str(args.s1), "output": str(args.out),
              "config": args.config, "workers": args.workers,
              "teacher_search": config["search"], "master_seed": config["master_seed"],
              "max_actions": config["max_actions"], "utility_revision": UTILITY_REVISION,
              "utility_definition": "terminal_utility(terminal observation, potion_cost="
                                    f"{config['search']['potion_cost']}); truncated episodes score 0.0 "
                                    "and are marked value_mask=0",
              "splits": {}}
    scenarios_out = {"purpose": "The initial scenarios this round collected, re-derived and checked "
                                "against the S1 materialisation.",
                     "master_seed": config["master_seed"], "splits": {}}
    manifests = {"purpose": "Per-shard hashes and semantic versions of the rebuilt collection.",
                 "splits": {}}

    for split in ("train", "val"):
        checked = verify_initial_scenarios(args.s1, split, config["master_seed"])
        print(f"{split}: {len(checked)} initial scenarios reproduce the S1 materialisation", flush=True)
        summary = collect(str(ROOT / args.out / split), backend="lightspeed_pilot", split=split,
                          count=len(checked), workers=args.workers, search=config["search"],
                          master_seed=config["master_seed"], max_actions=config["max_actions"],
                          iteration=0, sample_actions=(split == "train"))
        collection = json.loads((ROOT / args.out / split / "collection.json").read_text())
        described = describe(ROOT / args.out / split, split)
        report["splits"][split] = {"initial_scenarios_verified": len(checked),
                                   "collect_summary": summary, **described}
        scenarios_out["splits"][split] = {"count": len(checked), "items": checked}
        manifests["splits"][split] = {
            "fingerprint": collection["fingerprint"], "settings": collection["settings"],
            "shards": described["shards"]}
        print(f"{split}: {described['independent_battles']} battles, "
              f"{described['total_states']} states, {described['decision_states']} decision states",
              flush=True)

    atomic_json(ROOT / args.report, report)
    atomic_json(ROOT / args.scenarios, scenarios_out)
    atomic_json(ROOT / args.manifest, manifests)
    print(json.dumps({split: {k: v for k, v in values.items() if k != "shards"}
                      for split, values in report["splits"].items()}, indent=2))


if __name__ == "__main__":
    main()
