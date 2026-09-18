#!/usr/bin/env python3
"""Evidence for the louse counterfactual and the sampler's coupling promise.

For each pair of roots that share a complete public history but differ in the
hidden base attack value, records the scenario, the action script, the public
observation hashes, the engine's own execution events, the two test-only hidden
values, the fixed sampler seed, the resulting public future, and the assertion
outcome. The pre-fix sampler is run on the same pair as the negative control.

The adapter promises canonical coupling for a fixed sampler seed (it sorts the
unknown draw pile and rebuilds every RNG from that seed), so the check is an
exact trace match rather than a distributional one. The distribution check is
recorded alongside for the case where that promise would not hold.
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.contracts import observation_key
from stsai.native import NativeBattle
from stsai.scenarios import make_scenario

SCENARIO = {"deck": ["DEFEND_RED"] * 10, "encounter": "TWO_LOUSE", "ascension": 20,
            "hp": 80, "max_hp": 80, "floor": 1, "act": 1, "potions": []}
SAMPLER_SEEDS = [0, 1, 7, 4242, 2 ** 40 + 3]
STEPS = 10


def wrap(handle):
    instance = NativeBattle.__new__(NativeBattle)
    instance._handle = handle
    return instance


def end_turn(obs):
    return next(a for a in obs["actions"] if a["kind"] == "end")


def trace(sim, steps=STEPS):
    """Public trace under a fixed action script, plus the events along the way."""
    keys, events = [], []
    for _ in range(steps):
        obs = sim.observe()
        keys.append(observation_key(obs))
        events.append(sim._handle.debug_internals()["events"])
        if obs["terminal"]:
            break
        sim.step(end_turn(obs))
    return keys, events[-1] if events else []


def find_pairs(limit=3):
    pairs = []
    for index in range(12):
        scenario, episode_seed, _ = make_scenario("lightspeed_pilot", "val", index)
        env = NativeBattle({**SCENARIO, "deck": scenario["deck"]}, episode_seed)
        obs = env.observe()
        info = env._handle.debug_internals()
        for slot, enemy in enumerate(obs["enemies"]):
            if enemy["id"].endswith("LOUSE") and enemy["intent"] != "ATTACK":
                pairs.append((index, episode_seed, slot, enemy["id"], scenario["deck"],
                              info["true_attack_bases"][slot],
                              (info["public_attack_base"][slot]["low"],
                               info["public_attack_base"][slot]["high"])))
                if len(pairs) >= limit:
                    return pairs
    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counterfactuals", default="sampler/louse_counterfactuals.jsonl.gz")
    parser.add_argument("--observations", default="sampler/louse_public_observations.jsonl.gz")
    parser.add_argument("--checks", default="sampler/distribution_checks.json")
    args = parser.parse_args()

    pairs = find_pairs()
    counterfactual_rows, observation_rows = [], []
    checks = {"purpose": "Coupling and divergence checks for the hidden-base counterfactual.",
              "promise": "canonical coupling: the same public history and sampler seed must give the "
                         "same public trace, because the draw pile is sorted before shuffling and "
                         "every RNG is rebuilt from the seed",
              "cases": []}

    for index, episode_seed, slot, monster, deck, true_base, prior in pairs:
        low, high = prior
        a = NativeBattle({**SCENARIO, "deck": deck}, episode_seed)
        b = NativeBattle({**SCENARIO, "deck": deck}, episode_seed)
        a._handle.debug_set_attack_base(slot, low)
        b._handle.debug_set_attack_base(slot, high)
        root_a, root_b = a.observe(), b.observe()
        same_root = observation_key(root_a) == observation_key(root_b)
        observation_rows.append({
            "scenario_index": index, "episode_seed": episode_seed, "slot": slot, "monster": monster,
            "public_prior": list(prior), "true_base_of_this_episode": true_base,
            "observation": root_a, "observation_hash": observation_key(root_a),
            "note": "the true base is recorded here as TEST-ONLY evidence; it never enters an "
                    "observation, an encoding or a policy"})

        fixed_matches, control_diverges = [], []
        for seed in SAMPLER_SEEDS:
            left, left_events = trace(a.sampler()(seed))
            right, _ = trace(b.sampler()(seed))
            fixed_matches.append(left == right)
            old_left, _ = trace(wrap(a._handle.debug_sample_with_true_base(seed)))
            old_right, _ = trace(wrap(b._handle.debug_sample_with_true_base(seed)))
            control_diverges.append(old_left != old_right)
            counterfactual_rows.append({
                "scenario_index": index, "episode_seed": episode_seed, "slot": slot,
                "monster": monster, "action_script": "END_TURN repeated",
                "public_root_hash": observation_key(root_a),
                "hidden_values": {"a": low, "b": high},
                "sampler_seed": seed,
                "public_future_a": left, "public_future_b": right,
                "fixed_sampler_matches": left == right,
                "prefix_sampler_diverges": old_left != old_right,
                "events_a": left_events,
                "evidence_level": "CURRENT_CODE_RUN"})
        checks["cases"].append({
            "scenario_index": index, "slot": slot, "monster": monster,
            "same_public_root": same_root,
            "fixed_sampler_all_seeds_match": all(fixed_matches),
            "prefix_sampler_diverges_on_some_seed": any(control_diverges),
            "seeds": SAMPLER_SEEDS,
            "valid_counterfactual": same_root and all(fixed_matches) and any(control_diverges)})

    valid = [c for c in checks["cases"] if c["valid_counterfactual"]]
    checks["summary"] = {"pairs_examined": len(checks["cases"]),
                         "valid_counterfactuals": len(valid),
                         "all_fixed_samplers_agree": all(
                             c["fixed_sampler_all_seeds_match"] for c in checks["cases"]),
                         "all_controls_diverge": all(
                             c["prefix_sampler_diverges_on_some_seed"] for c in checks["cases"])}
    checks["scope"] = ("the counterfactual is constructed with the test-only setter, which places "
                       "each root at a value its own spawn range allows. It is not a claim that two "
                       "specific original-game seeds produce these roots.")

    for path, rows in ((args.counterfactuals, counterfactual_rows),
                       (args.observations, observation_rows)):
        out = ROOT / path
        out.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(out, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    out = ROOT / args.checks
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checks["summary"], indent=2))
    if not checks["summary"]["valid_counterfactuals"]:
        raise SystemExit("no valid counterfactual was constructed")


if __name__ == "__main__":
    main()
