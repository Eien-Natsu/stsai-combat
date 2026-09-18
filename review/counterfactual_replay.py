#!/usr/bin/env python3
"""Replay the shipped public trace and re-run the louse counterfactual.

    python review/counterfactual_replay.py --repo <checkout> --trace <json> --out <json>

Everything here is executed against the freshly built engine: the recorded
observations are recomputed and compared hash by hash, the belief samples are
drawn again, and the two-hidden-values pair is rebuilt and compared. Nothing is
read from a stored pass/fail boolean.

Budget: one root at a time, at most 128 actions per replay and at most 4096
sampler seeds per distribution. This is a regression replay, not a new search.
"""
import argparse
import json
import sys
from pathlib import Path

MAX_STEPS = 128
SAMPLER_SEEDS = 1024  # <= the 4096 per-distribution budget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    sys.path.insert(0, str(repo / "src"))
    from stsai.contracts import observation_key, validate_public
    from stsai.native import NativeBattle

    trace = json.loads(Path(args.trace).read_text(encoding="utf-8"))
    result = {"trace": str(args.trace), "scenario": trace["scenario"], "seed": trace["seed"]}

    env = NativeBattle(trace["scenario"], trace["seed"])
    replayed, mismatches = 0, []
    for index, expected in enumerate(trace["observations"][:MAX_STEPS]):
        obs = env.observe()
        validate_public(obs)
        if observation_key(obs) != observation_key(expected):
            mismatches.append(index)
        replayed += 1
        if obs["terminal"] or index >= len(trace["actions"]):
            break
        action = trace["actions"][index]
        match = [a for a in obs["actions"] if a["id"] == action["id"]]
        if not match:
            mismatches.append(f"{index}: recorded action {action['id']} is not legal")
            break
        env.step(match[0])
    result["steps_replayed"] = replayed
    result["observation_hash_mismatches"] = mismatches

    # The belief sample must not move the public root, and must stay inside the
    # candidate set public history allows.
    final = env.observe()
    root = observation_key(final)
    seen = set()
    stable = True
    for seed in range(SAMPLER_SEEDS):
        sample = env.sampler()(seed)
        if observation_key(sample.observe()) != root:
            stable = False
            break
        seen.add(sample._handle.debug_internals()["true_attack_bases"][0])
    result["sampler_seeds"] = SAMPLER_SEEDS
    result["root_stable"] = stable
    result["candidates_seen"] = sorted(seen)
    result["public_interval"] = [final["enemies"][0]["attack_base_low"],
                                final["enemies"][0]["attack_base_high"]]

    # The counterfactual: same public history, two different hidden bases.
    low, high = result["public_interval"]
    scenario, seed = trace["scenario"], trace["seed"]
    left = NativeBattle(scenario, seed); left._handle.debug_set_attack_base(0, low)
    right = NativeBattle(scenario, seed); right._handle.debug_set_attack_base(0, high)
    result["pair_roots_identical"] = observation_key(left.observe()) == observation_key(right.observe())

    def rollout(sample, steps=8):
        sim = sample if isinstance(sample, NativeBattle) else NativeBattle._wrap(sample)
        keys = []
        for _ in range(min(steps, MAX_STEPS)):
            obs = sim.observe()
            keys.append(observation_key(obs))
            if obs["terminal"]:
                break
            sim.step(next(a for a in obs["actions"] if a["kind"] == "end"))
        return keys

    fixed_agree, fixed_diverge = 0, 0
    prefix_diverge = 0
    for sampler_seed in (0, 1, 7, 4242):
        if rollout(left.sampler()(sampler_seed)) == rollout(right.sampler()(sampler_seed)):
            fixed_agree += 1
        else:
            fixed_diverge += 1
        if rollout(left._handle.debug_sample_with_true_base(sampler_seed)) != \
                rollout(right._handle.debug_sample_with_true_base(sampler_seed)):
            prefix_diverge += 1
    result["fixed_sampler_agrees_on"] = fixed_agree
    result["fixed_sampler_diverges_on"] = fixed_diverge
    result["prefix_sampler_diverges_on"] = prefix_diverge
    result["counterfactual_shows_dependency"] = prefix_diverge > 0
    result["counterfactual_removed_by_fix"] = fixed_diverge == 0 and fixed_agree > 0

    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "scenario"}))

    ok = (not mismatches and stable and result["pair_roots_identical"]
          and result["counterfactual_removed_by_fix"] and result["counterfactual_shows_dependency"])
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
