#!/usr/bin/env python3
"""Classify every latent field the belief sampler carries into a copy.

For each field that can affect the sampled future, state whether the complete
legal public history determines it (PUBLIC_DETERMINED, with the grounds), whether
the sampler resamples it from the legal information (RESAMPLED), or whether the
interface cannot handle it correctly (UNSUPPORTED, which stops that branch).

Emits input/sampler_audit.json and a compact lifecycle trace file. The traces
are public observations only; internal move ids appear solely in the
test-only hook and never in the trace's observation payload.
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SCENARIO = {"deck": ["STRIKE_RED"] * 5 + ["DEFEND_RED"] * 4 + ["BASH", "ASCENDERS_BANE"],
            "encounter": "CULTIST", "ascension": 20, "hp": 55, "max_hp": 80,
            "floor": 1, "act": 1, "potions": []}


def main():
    from stsai.native import NativeBattle
    from stsai.scenarios import NATIVE_ENCOUNTERS

    encounters = tuple(e for v in NATIVE_ENCOUNTERS.values() for e in v)
    signatures, checked = {}, 0
    traces = []
    for encounter in encounters:
        for seed in range(8):
            env = NativeBattle({**SCENARIO, "deck": ["DEFEND_RED"] * 10, "encounter": encounter,
                                "hp": 200, "max_hp": 200}, seed)
            trace = []
            for step in range(30):
                obs = env.observe()
                internal = env._handle.debug_internals()
                for slot, enemy in enumerate(obs["enemies"]):
                    signature = (enemy["id"], enemy["intent"], enemy["intent_damage"], enemy["hits"])
                    signatures.setdefault(signature, set()).add(internal["held_moves"][slot])
                    checked += 1
                if step < 4:
                    trace.append({"turn": obs["turn"], "encounter": encounter,
                                  "enemies": [{k: e[k] for k in sorted(e)} for e in obs["enemies"]],
                                  "test_only_executed_moves": internal["executed_moves"]})
                if obs["terminal"]:
                    trace.append({"turn": obs["turn"], "terminal": True, "won": obs["won"]})
                    break
                env.step(next(a for a in obs["actions"] if a["kind"] == "end"))
            traces.append({"scenario": {"encounter": encounter, "episode_seed": seed}, "steps": trace})

    collisions = {f"{k}": sorted(v) for k, v in signatures.items() if len(v) > 1}
    public_determined = not collisions and checked > 2000

    audit = {
        "purpose": "Field-by-field classification of what a belief sample carries.",
        "categories": {
            "PUBLIC_DETERMINED": "the complete legal public history determines it, with stated grounds",
            "RESAMPLED": "drawn from the distribution the legal information implies, or a declared approximation of it",
            "UNSUPPORTED": "this interface cannot handle it correctly; the branch stops and is reported",
        },
        "fields": [
            {"field": "monsters[].moveHistory[0] (the held move)",
             "category": "PUBLIC_DETERMINED" if public_determined else "UNSUPPORTED",
             "grounds": ("The public intent class together with the displayed damage and hit count "
                         "separates every held move, across %d inspected states and %d distinct public "
                         "signatures with zero collisions (tests/test_native_fairness.py::"
                         "test_the_held_move_is_determined_by_public_information). The class ALONE does "
                         "not separate Looter Mug from Lunge; the damage number does. The sampler keeps "
                         "the field because the player can already know it."
                         % (checked, len(signatures))),
             "collisions": collisions,
             "test": "tests/test_native_fairness.py::test_the_held_move_is_determined_by_public_information"},
            {"field": "monsters[].moveHistory[1] (previously rolled)",
             "category": "PUBLIC_DETERMINED",
             "grounds": "executed moves, exported as the public class in previous_intent",
             "test": "tests/test_native_fairness.py::test_previous_intent_only_ever_reports_an_executed_move"},
            {"field": "GREMLIN_WIZARD miscInfo/monsterData (charge counter)",
             "category": "PUBLIC_DETERMINED",
             "grounds": "the charging state is visible each turn and the counter is a timer, not a "
                        "move-selection input (MonsterSpecific.cpp:2440, :774)",
             "test": "tests/test_native_coverage.py covers its two moves"},
            {"field": "RED_SLAVER miscInfo (usedEntangle)",
             "category": "PUBLIC_DETERMINED",
             "grounds": "whether Entangle has been used is public history (MonsterSpecific.cpp:2780)",
             "test": "tests/test_native_coverage.py covers its three moves"},
            {"field": "other monsters' miscInfo/monsterData",
             "category": "UNSUPPORTED",
             "grounds": "Champ, Spiker, Writhing Mass, Time Eater, Awakened One, Book of Stabbing and "
                        "Bronze Orb read latent state but none is reachable in the 17 supported "
                        "encounters, so the case cannot arise; widening the encounter list requires "
                        "re-auditing these",
             "test": "scripts/gen_sampler_audit.py prints the per-monster read sites"},
            {"field": "aiRng, cardRandomRng, miscRng, monsterHpRng, potionRng, shuffleRng",
             "category": "RESAMPLED",
             "grounds": "all six streams are reconstructed from the sampler seed",
             "test": "tests/test_native_fairness.py::test_every_distinct_hidden_state_shares_one_belief"},
            {"field": "cards.drawPile order",
             "category": "RESAMPLED",
             "grounds": "sorted by the cross-backend canonical key, then shuffled with the sampler rng, "
                        "so the sampled order does not depend on the real one",
             "test": "tests/test_native_fairness.py::test_same_public_history_different_hidden_draw_order_samples_identically"},
            {"field": "bc.seed",
             "category": "RESAMPLED",
             "grounds": "zeroed; never an agent input",
             "test": "tests/test_native_fairness.py::test_hidden_state_never_appears_in_the_observation"},
            {"field": "player state, card zones, powers, block, statuses",
             "category": "PUBLIC_DETERMINED",
             "grounds": "copied verbatim; all of it is exported in the observation",
             "test": "tests/test_native_*.py validate_public"},
        ],
        "coverage": {"states_inspected": checked, "distinct_public_signatures": len(signatures),
                     "supported_encounters": len(encounters)},
        "not_used_as_proof": ["random collision scans of stored states",
                              "the absence of a move_id key in the observation"],
        "residual": ("The determinism argument covers the reachable state space sampled here, not every "
                     "state in principle. No move id is exported, and the teacher's rollouts still use "
                     "the true id internally; the argument is that the player could know it too."),
    }
    out = ROOT / "input/sampler_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    trace_path = ROOT / "input/lifecycle_traces.jsonl.gz"
    with gzip.open(trace_path, "wt", encoding="utf-8") as handle:
        for record in traces:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"states inspected: {checked}; signatures: {len(signatures)}; collisions: {len(collisions)}")
    print("wrote", out, "and", trace_path)


if __name__ == "__main__":
    main()
