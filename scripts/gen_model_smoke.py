#!/usr/bin/env python3
"""Write the 12 public observations and the numbers a fresh load must reproduce.

    python scripts/gen_model_smoke.py --checkpoint model/policy_weights.pt \
        --out-dir model [--scenarios reports/s1_eval/dev_scenarios.json]

The observations are the initial states of development scenarios: public, no
debug fields, valid under `validate_public`. The expectations are the selected
weights' own policy probabilities, argmax action and value, recorded so an
independent load can be checked with a stated tolerance without re-deriving
them. A tie is recorded as a tie; different float backends may order an exact
tie differently, and the checker accepts any argmax among the tied actions.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import torch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.contracts import validate_public  # noqa: E402
from stsai.model import ModelEvaluator  # noqa: E402
from stsai.native import NativeBattle  # noqa: E402
from stsai.util import atomic_json, digest  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="model/policy_weights.pt")
    parser.add_argument("--scenarios", default="reports/s1_eval/dev_scenarios.json")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--out-dir", default="model")
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--tie-epsilon", type=float, default=1e-6)
    args = parser.parse_args()

    scenarios = json.loads((ROOT / args.scenarios).read_text())["scenarios"][:args.count]
    evaluator = ModelEvaluator.from_checkpoint(str(ROOT / args.checkpoint), "cpu")
    cases, observations = [], []
    for entry in scenarios:
        env = NativeBattle(entry["scenario"], entry["episode_seed"])
        obs = env.observe()
        validate_public(obs)
        ids = [a["id"] for a in obs["actions"]]
        if len(ids) < 2:
            raise SystemExit(f"scenario {entry['index']} is a forced state; pick another case")
        observations.append(obs)
    results = evaluator.evaluate_batch(observations)
    for entry, obs, (probs, value) in zip(scenarios, observations, results):
        order = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
        tie = len(probs) > 1 and (probs[order[0]] - probs[order[1]]) <= args.tie_epsilon
        cases.append({
            "index": entry["index"], "episode_seed": entry["episode_seed"],
            "encounter": entry["encounter"],
            "action_ids": [a["id"] for a in obs["actions"]],
            "action_index": order[0], "probabilities": list(probs), "value": value,
            "tie_at_the_top": bool(tie),
            "observation_sha256": digest(obs),
        })

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / "smoke_observations.jsonl.gz", "wt", encoding="utf-8") as handle:
        for entry, obs in zip(scenarios, observations):
            handle.write(json.dumps({"case": entry["index"], "episode_seed": entry["episode_seed"],
                                     "observation": obs}, sort_keys=True) + "\n")
    atomic_json(out_dir / "smoke_expected.json", {
        "purpose": "Expected outputs of the shipped selected weights on the shipped observations.",
        "checkpoint": str(args.checkpoint),
        "device": "cpu fp32", "tolerance": args.tolerance, "tie_epsilon": args.tie_epsilon,
        "tolerance_note": "absolute difference on probability and value; an argmax is accepted "
                          "among actions whose expected probabilities differ by less than the tie "
                          "epsilon, because float backends may order an exact tie differently",
        "debug_fields": "none: every observation passes validate_public, and the hidden/base "
                        "debug surface is not part of the input",
        "cases": cases,
    })
    print(f"{len(cases)} cases written to {out_dir}/smoke_observations.jsonl.gz")
    print(f"ties at the top: {sum(c['tie_at_the_top'] for c in cases)}")


if __name__ == "__main__":
    main()
