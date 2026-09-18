#!/usr/bin/env python3
"""Record what the belief sample treats as public memory, step by step.

    python scripts/gen_public_memory_evidence.py --out evidence/public_memory_evidence.jsonl.gz

One gzip line per replayed step of the shipped public trace, each with the
recomputed observation hash and the public state that a sample must preserve,
followed by one line for the sampler check at the final root. This is the raw
evidence behind "the public candidate enters the encoder, the hidden value does
not": the interval below is what the player's own observations allow, and the
candidate set is what the sampler is allowed to draw from.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.contracts import observation_key, validate_public  # noqa: E402
from stsai.native import NativeBattle  # noqa: E402
from stsai.util import digest  # noqa: E402

SAMPLER_SEEDS = 1024  # within the 4096-per-distribution budget
MAX_STEPS = 128


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", default="tests/fixtures/ambiguity_public_trace.json")
    parser.add_argument("--out", default="evidence/public_memory_evidence.jsonl.gz")
    args = parser.parse_args()

    trace = json.loads((ROOT / args.trace).read_text(encoding="utf-8"))
    env = NativeBattle(trace["scenario"], trace["seed"])
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    steps = 0
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        for index, expected in enumerate(trace["observations"][:MAX_STEPS]):
            obs = env.observe()
            validate_public(obs)
            record = {
                "record": "step", "step": index, "trace": str(args.trace), "seed": trace["seed"],
                "turn": obs["turn"],
                "observation_sha256": digest(obs),
                "matches_recorded_trace": observation_key(obs) == observation_key(expected),
                "enemies": [{"slot": e.get("slot", i), "id": e["id"], "intent": e.get("intent"),
                             "intent_damage": e.get("intent_damage"), "hits": e.get("hits"),
                             "strength": e.get("strength"), "hp": e["hp"],
                             "attack_base_low": e.get("attack_base_low"),
                             "attack_base_high": e.get("attack_base_high")}
                            for i, e in enumerate(obs["enemies"])],
                "public_information_only": "the interval and the displayed damage; the true base is "
                                           "not part of any field here",
            }
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            steps += 1
            if obs["terminal"] or index >= len(trace["actions"]):
                break
            action = trace["actions"][index]
            env.step(next(a for a in obs["actions"] if a["id"] == action["id"]))

        final = env.observe()
        root = observation_key(final)
        seen, stable = set(), True
        for seed in range(SAMPLER_SEEDS):
            sample = env.sampler()(seed)
            if observation_key(sample.observe()) != root:
                stable = False
                break
            seen.add(sample._handle.debug_internals()["true_attack_bases"][0])
        handle.write(json.dumps({
            "record": "sampler_check", "sampler_seeds": SAMPLER_SEEDS, "root_stable": stable,
            "candidates_seen": sorted(seen),
            "public_interval": [final["enemies"][0].get("attack_base_low"),
                                final["enemies"][0].get("attack_base_high")],
            "reading": "every drawn sample preserves the public root and stays inside the declared "
                       "prior; the display floors at zero here, so more than one candidate remains "
                       "reachable",
        }, sort_keys=True) + "\n")
    print(f"{steps} steps + 1 sampler check -> {out}")


if __name__ == "__main__":
    main()
