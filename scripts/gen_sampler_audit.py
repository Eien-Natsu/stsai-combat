#!/usr/bin/env python3
"""Field-by-field audit of what a belief sample carries.

The category of every field is declared here from the source and from tests. A
random scan over reachable states is still run, but ONLY as a coverage statistic:
it never decides a category, because "no counterexample found" is not "public
information determines it". Cases where no counterexample exists but no argument
either are listed as incomplete evidence rather than promoted.

Categories
    PUBLIC_DETERMINED  the complete legal public history determines it, grounds given
    RESAMPLED          drawn from a declared conditional law or a named approximation
    UNSUPPORTED        this interface cannot handle it; the branch refuses or is out of range
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SCENARIO = {"deck": ["STRIKE_RED"] * 5 + ["DEFEND_RED"] * 4 + ["BASH", "ASCENDERS_BANE"],
            "encounter": "CULTIST", "ascension": 20, "hp": 55, "max_hp": 80,
            "floor": 1, "act": 1, "potions": []}

LOUSE_GROUNDS = (
    "The spawn range is public (Monster.cpp:118-120) and every attack intent the "
    "player is shown displays calculateDamageToPlayer(base), so the candidate set is "
    "narrowed by the displayed number and only ever shrinks. Sampling draws once from "
    "that set and keeps the draw; the true miscInfo is never read. Tests: "
    "tests/test_louse_hidden_base.py (fixed sampler agrees across two hidden values, "
    "pre-fix sampler diverges on the same pair)."
)

FIELDS = [
    {"monster": "GREEN_LOUSE / RED_LOUSE", "field": "miscInfo (base attack)",
     "init_write": "Monster.cpp:118-120, at construct, from monsterHpRng",
     "future_read": "MonsterSpecific.cpp:745 (GREEN_LOUSE_BITE), :1006 (RED_LOUSE_BITE)",
     "visibility": "the displayed attack damage, once an attack intent is shown",
     "category": "RESAMPLED",
     "evidence_type": "SOURCE_ARGUMENT plus a constructed counterfactual",
     "grounds": LOUSE_GROUNDS,
     "approximation": "uniform prior over the spawn range, narrowed by public observations; "
                      "not the original game's correlated posterior",
     "test": "tests/test_louse_hidden_base.py"},

    {"monster": "GREMLIN_WIZARD", "field": "monsterData / miscInfo (charge counter)",
     "init_write": "MonsterSpecific.cpp:2440 sets monsterData=1; :774 increments miscInfo",
     "future_read": "MonsterSpecific.cpp:774 (charges) and the charge state drives its move",
     "visibility": "the charging intent is displayed on every turn it charges",
     "category": "PUBLIC_DETERMINED",
     "evidence_type": "SOURCE_ARGUMENT (no counterfactual test)",
     "grounds": "the counter only advances on turns whose intent the player sees, so "
                "counting them recovers it",
     "test": "tests/test_native_coverage.py covers both of its moves"},

    {"monster": "RED_SLAVER", "field": "miscInfo (usedEntangle)",
     "init_write": "set when Entangle is used, MonsterSpecific.cpp:1017",
     "future_read": "MonsterSpecific.cpp:2780 in getMoveForRoll",
     "visibility": "Entangle applies Entangled to the player, so its use is public",
     "category": "PUBLIC_DETERMINED",
     "evidence_type": "SOURCE_ARGUMENT (no counterfactual test)",
     "grounds": "a boolean about whether a publicly visible debuff has already happened",
     "test": "tests/test_native_coverage.py covers all three of its moves"},

    {"monster": "DARKLING", "field": "miscInfo (base attack)",
     "init_write": "Monster.cpp:126-128, same pattern as the louse",
     "future_read": "its multi-strike move",
     "visibility": "as the louse, but unreachable here",
     "category": "UNSUPPORTED",
     "evidence_type": "SOURCE_ARGUMENT (read site recorded; no reachable path here)",
     "grounds": "Act 3 monster, not in the 17 supported encounters; the adapter refuses the "
                "encounter before this can arise, and widening the list requires applying the "
                "same candidate treatment",
     "test": "the encounter whitelist rejects it (bridge.cpp supported_encounters)"},

    {"monster": "THE_CHAMP, SPIKER, WRITHING_MASS, TIME_EATER, AWAKENED_ONE, BOOK_OF_STABBING, "
                "BRONZE_ORB", "field": "miscInfo / monsterData read during move selection",
     "init_write": "per monster",
     "future_read": "MonsterSpecific.cpp:2855-2881, :2981, :3090, :3189, :3245, :2069, :2257",
     "visibility": "not audited",
     "category": "UNSUPPORTED",
     "evidence_type": "NOT_VERIFIED (no reachable path here; the sites are only listed)",
     "grounds": "none of these is reachable in the 17 supported encounters; the read sites are "
                "recorded so widening the encounter list cannot forget them",
     "test": "no reachable path"},

    {"monster": "all supported", "field": "moveHistory[0] (held move)",
     "init_write": "Monster::setMove at roll time",
     "future_read": "getMoveForRoll via lastMove / lastTwoMoves",
     "visibility": "the intent class plus the displayed damage and hit count",
     "category": "PUBLIC_DETERMINED",
     "grounds": "the class plus the displayed damage and hit count separated every held move in "
                "a finite sample of reachable states (3584 states, 93 signatures). The class "
                "alone does not separate Looter Mug from Lunge; the damage number does.",
     "evidence_type": "FINITE_SAMPLE_COVERAGE plus a source argument",
     "not_a_proof": "a coverage regression over sampled states, not a proof over all reachable "
                    "states, and it cannot detect a determined move whose hidden parameters are "
                    "still unknown (that is the louse case, listed separately)",
     "test": "tests/test_native_fairness.py::test_the_held_move_is_determined_by_public_information"},

    {"monster": "all supported", "field": "moveHistory[1] and the executed history",
     "init_write": "Monster::setMove",
     "future_read": "the adapter, via the engine's execution events",
     "visibility": "the move is watched resolving, and its class is exported",
     "category": "PUBLIC_DETERMINED",
     "evidence_type": "CONSTRUCTED_COUNTERFACTUAL plus a source argument",
     "grounds": "taken from the engine's own execution events, not inferred from a turn counter",
     "test": "tests/test_native_fairness.py lifecycle suite"},

    {"monster": "all supported", "field": "aiRng, cardRandomRng, miscRng, monsterHpRng, "
                                           "potionRng, shuffleRng",
     "init_write": "BattleContext construction",
     "future_read": "every rule that rolls",
     "visibility": "never visible",
     "category": "RESAMPLED",
     "evidence_type": "MODEL_ASSUMPTION",
     "grounds": "all six streams are reconstructed from the sampler seed",
     "approximation": "independent streams, not the original game's correlated seeded streams",
     "test": "tests/test_native_fairness.py::test_every_distinct_hidden_state_shares_one_belief"},

    {"monster": "all supported", "field": "cards.drawPile order",
     "init_write": "shuffle at battle start and on reshuffle",
     "future_read": "every draw",
     "visibility": "only the multiset is public",
     "category": "RESAMPLED",
     "evidence_type": "CONSTRUCTED_COUNTERFACTUAL plus a model assumption",
     "grounds": "sorted by the cross-backend canonical key then shuffled with the sampler rng, "
                "so the sampled order never depends on the real one",
     "approximation": "a uniformly random order over the public multiset",
     "test": "tests/test_native_fairness.py::test_same_public_history_different_hidden_draw_order_samples_identically"},

    {"monster": "all supported", "field": "bc.seed",
     "init_write": "scenario construction",
     "future_read": "debug only",
     "visibility": "never visible",
     "category": "RESAMPLED",
     "evidence_type": "MODEL_ASSUMPTION",
     "grounds": "zeroed in the copy; never an agent input",
     "approximation": "no seed is modelled at all, which is strictly less information than the "
                      "player has",
     "test": "tests/test_native_fairness.py::test_hidden_state_never_appears_in_the_observation"},

    {"monster": "all supported", "field": "player state, card zones, powers, block, statuses",
     "init_write": "game flow",
     "future_read": "rules and the model alike",
     "visibility": "all exported in the observation",
     "category": "PUBLIC_DETERMINED",
     "evidence_type": "SOURCE_ARGUMENT (exported verbatim, checked on every observation)",
     "grounds": "copied verbatim and fully exported",
     "test": "validate_public on every observation"},

    {"monster": "all supported", "field": "the engine event log",
     "init_write": "MonsterGroup doMonsterTurn and the spawn sites (patch 0003)",
     "future_read": "the adapter's previous_intent and slot reset",
     "visibility": "only executed actions and spawns, both of which the player watches",
     "category": "PUBLIC_DETERMINED",
     "evidence_type": "CONSTRUCTED_COUNTERFACTUAL plus a source argument",
     "grounds": "records only what actually happened; no rule reads it",
     "test": "tests/test_native_fairness.py lifecycle suite"},
]


def coverage_scan(encounters, seeds=8, turns=30):
    from stsai.native import NativeBattle
    signatures, checked = {}, 0
    for encounter in encounters:
        for seed in range(seeds):
            env = NativeBattle({**SCENARIO, "deck": ["DEFEND_RED"] * 10, "encounter": encounter,
                                "hp": 200, "max_hp": 200}, seed)
            for _ in range(turns):
                obs = env.observe()
                held = env._handle.debug_internals()["held_moves"]
                for slot, enemy in enumerate(obs["enemies"]):
                    signature = (enemy["id"], enemy["intent"], enemy["intent_damage"], enemy["hits"])
                    signatures.setdefault(signature, set()).add(held[slot])
                    checked += 1
                if obs["terminal"]:
                    break
                env.step(next(a for a in obs["actions"] if a["kind"] == "end"))
    collisions = {str(k): sorted(v) for k, v in signatures.items() if len(v) > 1}
    return {"states_inspected": checked, "distinct_public_signatures": len(signatures),
            "collisions": collisions}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="evidence/field_audit.json")
    parser.add_argument("--traces", default="evidence/events_and_observations.jsonl.gz")
    args = parser.parse_args()
    from stsai.scenarios import NATIVE_ENCOUNTERS

    encounters = tuple(e for v in NATIVE_ENCOUNTERS.values() for e in v)
    scan = coverage_scan(encounters)

    by_category = {}
    for field in FIELDS:
        by_category.setdefault(field["category"], []).append(
            f"{field['monster']}: {field['field']}")

    audit = {
        "purpose": "Field-by-field classification of what a belief sample carries.",
        "categories": {
            "PUBLIC_DETERMINED": "complete legal public history determines it; grounds given",
            "RESAMPLED": "drawn from a declared conditional law or a named approximation",
            "UNSUPPORTED": "cannot be handled here; the branch refuses or is out of range",
        },
        "coverage_scan": {
            **scan,
            "role": "COVERAGE REGRESSION ONLY. It never decides a category: absence of a "
                    "counterexample is not an argument that public information determines a "
                    "field, and it cannot detect a determined move whose hidden parameters "
                    "are still unknown. Each field below states separately whether it rests on a source "
                    "argument, a model assumption, a constructed counterfactual or an actual "
                    "game run; none is an original-game verification.",
        },
        "fields": FIELDS,
        "by_category": by_category,
        "incomplete_evidence": [
            {"item": "miscInfo for monsters outside the 17 encounters",
             "why": "read sites are recorded but no reachable path exists to test them"},
            {"item": "post-execution identifiability of a move from its visible consequences",
             "why": "assumed, not measured; the finer intent classes removed the need for it in "
                    "the cases that were checked"},
            {"item": "the coverage scan itself",
             "why": "sampled states, not a proof over all reachable states"},
            {"item": "original-game UI parity for the intent mapping",
             "why": "no legal copy of the game on this host; rows are ENGINE_DERIVED_ONLY or "
                    "UI_SOURCE_VERIFIED, never ORIGINAL_GAME_VERIFIED"},
            {"item": "the exact original-game posterior over hidden parameters",
             "why": "the sampler is a declared approximation over an independent RNG model"},
        ],
        "explicitly_not_used_as_proof": [
            "a random collision scan", "the absence of a move_id key in the observation"],
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    # lifecycle traces, carrying the engine events as the independent oracle
    from stsai.native import NativeBattle
    traces = []
    for encounter in encounters:
        for seed in range(4):
            env = NativeBattle({**SCENARIO, "deck": ["DEFEND_RED"] * 10, "encounter": encounter,
                                "hp": 200, "max_hp": 200}, seed)
            steps = []
            for _ in range(24):
                obs = env.observe()
                info = env._handle.debug_internals()
                steps.append({"turn": obs["turn"],
                              "enemies": [{k: e[k] for k in sorted(e)} for e in obs["enemies"]],
                              "events": info["events"],
                              "test_only_executed_moves": info["executed_moves"]})
                if obs["terminal"]:
                    steps.append({"terminal": True, "won": obs["won"]})
                    break
                env.step(next(a for a in obs["actions"] if a["kind"] == "end"))
            traces.append({"scenario": {"encounter": encounter, "episode_seed": seed}, "steps": steps})
    trace_path = ROOT / args.traces
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(trace_path, "wt", encoding="utf-8") as handle:
        for record in traces:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"fields audited: {len(FIELDS)}")
    for category, items in sorted(by_category.items()):
        print(f"  {category}: {len(items)}")
    print(f"coverage scan (NOT a pass criterion): {scan['states_inspected']} states, "
          f"{scan['distinct_public_signatures']} signatures, {len(scan['collisions'])} collisions")
    print("wrote", out, "and", trace_path)


if __name__ == "__main__":
    main()
