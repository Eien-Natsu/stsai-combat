#!/usr/bin/env python3
"""Collect the S2 addition: the generator's train indices 96-383, once.

    python scripts/s2_collect_add288.py [--workers 2]

D96 is not re-collected. This plays exactly the 288 scenarios the protocol
names, with the same teacher budget and action sampling S1R used, into its own
directory so the two sources stay distinguishable: D384 is a composition of two
verified directories, not one rewritten manifest.

Every new episode is checked against D96, V24 and both development sets for an
identical (scenario, episode seed) pair, and the report states the counts rather
than asserting that none exist.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.collection import collect  # noqa: E402
from stsai.scenarios import make_scenario  # noqa: E402
from stsai.util import atomic_json, digest  # noqa: E402

TIMING_KEYS = ("search_seconds", "elapsed_seconds", "simulations", "ms", "seconds",
               "seconds_per_step", "throughput")


def sha256(path):
    return __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()


def normalized_sample_hash(directory):
    """A hash of the samples themselves, with every timing field dropped.

    The archive hash identifies the bytes on disk; this identifies the content,
    so two machines that took different amounts of time to produce the same
    samples still agree here.
    """
    rows = []
    for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                rows.append({k: v for k, v in sorted(row.items())
                             if not any(t in k for t in TIMING_KEYS)})
    metas = []
    for path in sorted(Path(directory).glob("episode_*.meta.json")):
        meta = json.loads(path.read_text())
        metas.append({k: v for k, v in sorted(meta.items())
                      if not any(t in k for t in TIMING_KEYS)})
    return digest({"rows": rows, "metas": metas})


def identities(directory):
    out = []
    for path in sorted(Path(directory).glob("episode_*.meta.json")):
        meta = json.loads(path.read_text())
        out.append({"index": meta["episode_index"], "episode_seed": meta["episode_seed"],
                    "scenario_sha256": digest(meta["scenario"]),
                    "identity": digest([digest(meta["scenario"]), meta["episode_seed"]])})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/s2/add288")
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--report", default="runs/s2/add288_report.json")
    args = parser.parse_args()
    if args.workers > 2:
        raise SystemExit("the protocol allows at most two collection workers")

    config = json.loads((ROOT / args.config).read_text())
    master_seed = config["master_seed"]
    directory = ROOT / args.out
    if directory.exists() and any(directory.iterdir()):
        print(f"{directory} already has content; verifying it instead of re-collecting")

    expected = []
    for index in range(96, 384):
        scenario, episode_seed, family = make_scenario("lightspeed_pilot", "train", index, master_seed)
        expected.append({"index": index, "episode_seed": episode_seed, "family": family,
                         "scenario_sha256": digest(scenario)})

    summary = collect(str(directory), backend="lightspeed_pilot", split="train", count=288,
                      start=96, workers=args.workers, search=config["search"],
                      master_seed=master_seed, max_actions=config["max_actions"],
                      iteration=0, sample_actions=True)

    wanted = {(e["scenario_sha256"], e["episode_seed"]) for e in expected}
    found = identities(directory)
    wrong = [e for e in found if (e["scenario_sha256"], e["episode_seed"]) not in wanted]
    missing = len(wanted) - len(found)

    others = {"D96": identities(ROOT / "data/s1r/train"),
              "V24": identities(ROOT / "data/s1r/val"),
              "DEV_OLD256": [{"identity": digest([e["scenario_sha256"], e["episode_seed"]])}
                             for e in json.loads((ROOT / "runs/s2/dev_old256.json").read_text())["scenarios"]],
              "DEV_PROBE256": [{"identity": digest([e["scenario_sha256"], e["episode_seed"]])}
                               for e in json.loads((ROOT / "runs/s2/dev_probe256.json").read_text())["scenarios"]]}
    overlaps = {}
    new_ids = {e["identity"] for e in found}
    for name, entries in others.items():
        other_ids = {e["identity"] for e in entries}
        overlaps[name] = len(new_ids & other_ids)

    collection = json.loads((directory / "collection.json").read_text())
    report = {
        "purpose": "The one new collection of the S2 round: train indices 96-383.",
        "directory": str(directory), "workers": args.workers,
        "settings": collection["settings"], "fingerprint": collection["fingerprint"],
        "collect_summary": summary,
        "scenarios_expected": len(expected), "scenarios_found": len(found),
        "episodes_not_matching_the_generator": wrong[:5], "missing": missing,
        "overlaps_with": overlaps,
        "overlap_note": "an identical (scenario, episode seed) pair would be a duplicate episode; "
                        "zero here means the 288 are new, not that openings never coincide",
        "shards": {p.name: sha256(p) for p in sorted(directory.glob("episode_*.jsonl.gz"))},
        "normalized_sample_hash": normalized_sample_hash(directory),
        "initial_scenarios": expected,
    }
    atomic_json(ROOT / args.report, report)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("shards", "initial_scenarios", "settings")}, indent=2)[:1200])
    if wrong or missing:
        raise SystemExit("the collected data does not match the generator; STOP")


if __name__ == "__main__":
    main()
