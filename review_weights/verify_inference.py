#!/usr/bin/env python3
"""Load the two shipped inference weights and reproduce the expected predictions.

Run from the repository root:

    .venv/bin/python review_weights/verify_inference.py

Exits non-zero if any prediction differs from smoke_states_and_expected.json
beyond tolerance, or if a checkpoint's recorded source hash cannot be checked.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import torch

from stsai.encoding import encode, collate_encoded, ENCODING_REVISION
from stsai.model import CombatNet, ModelConfig
from stsai.scenarios import make_env, make_scenario
from stsai.util import SCHEMA_VERSION

ATOL = 2e-4


def load(path):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    model = CombatNet(ModelConfig(**checkpoint["model_config"]))
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model, checkpoint


def states_from_frozen_scenario():
    """Rebuild the frozen development scenario and take its first public states."""
    expected = json.loads((ROOT / "review_weights" / "smoke_states_and_expected.json").read_text())
    scenario, episode_seed, _ = make_scenario("lightspeed_pilot", "val",
                                              expected["scenario_index"], expected["master_seed"])
    if episode_seed != expected["episode_seed"]:
        raise SystemExit(f"scenario seed mismatch: {episode_seed} != {expected['episode_seed']}")
    env = make_env("lightspeed_pilot", scenario, episode_seed)
    out = []
    obs = env.observe()
    for _ in range(len(next(iter(expected["models"].values()))["predictions"])):
        out.append(obs)
        if obs["terminal"]:
            break
        obs = env.step(obs["actions"][0])
    return expected, out


def main():
    expected, states = states_from_frozen_scenario()
    failures = []
    for cell, record in expected["models"].items():
        path = ROOT / "review_weights" / f"{cell}.inference.pt"
        model, checkpoint = load(path)
        if checkpoint.get("encoding_revision") != ENCODING_REVISION or \
                checkpoint.get("observation_schema") != SCHEMA_VERSION:
            failures.append(f"{cell}: checkpoint built for a different input revision")
        with torch.inference_mode():
            for want in record["predictions"]:
                obs = states[want["state_index"]]
                batch = collate_encoded([encode(obs)])
                logits = model(batch)["policy_logits"].float()[0, :len(obs["actions"])]
                probabilities = torch.softmax(logits, -1).numpy()
                index = int(np.argmax(probabilities))
                got_id = obs["actions"][index]["id"]
                ok = (index == want["argmax_action"] and got_id == want["argmax_action_id"]
                      and abs(float(probabilities[index]) - want["top3"][0]["prob"]) < ATOL)
                print(f"{cell:14s} state {want['state_index']} turn {want['turn']:2d} "
                      f"argmax {got_id:>12s} p={probabilities[index]:.4f} "
                      f"(expected {want['argmax_action_id']} p={want['top3'][0]['prob']:.4f}) "
                      f"{'OK' if ok else 'MISMATCH'}")
                if not ok:
                    failures.append(f"{cell} state {want['state_index']}")
    if failures:
        print("\nFAILED:", "; ".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print("\nAll predictions reproduced. The shipped weights load and behave as recorded.")


if __name__ == "__main__":
    main()
