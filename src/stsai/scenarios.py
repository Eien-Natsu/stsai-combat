from __future__ import annotations
import random
from .util import seed_for

# Bump when the fixture distribution changes in any way that makes old and new
# episodes incomparable. Collection fingerprints include it, so data collected
# under different fixtures cannot be mixed into one training run by accident.
SCENARIO_REVISION = 2

REFERENCE_FAMILIES = ("basic", "wide", "scaling", "low_hp")
# Native fixtures pair a deck family with an encounter family. The decks decide
# what the agent can do; the encounters decide whether the fight is actually in
# doubt. A distribution where every agent wins everything carries no signal, so
# swarm and elite fights are part of the mix rather than single weak monsters.
NATIVE_FAMILIES = ("starter", "swarm", "elite", "mixed")
NATIVE_ENCOUNTERS = {
    "starter": ("CULTIST", "JAW_WORM"),
    "swarm": ("TWO_LOUSE", "THREE_LOUSE", "EXORDIUM_THUGS", "EXORDIUM_WILDLIFE"),
    "elite": ("GREMLIN_NOB", "LAGAVULIN", "THREE_SENTRIES"),
    "mixed": ("GREMLIN_GANG", "SMALL_SLIMES", "LOTS_OF_SLIMES", "LOOTER"),
}
NATIVE_HP = {"starter": (45, 70), "swarm": (45, 65), "elite": (60, 80), "mixed": (50, 70)}
# Deck pools are indexed separately from the encounter family so the two vary
# independently rather than always pairing one deck with one fight.
NATIVE_DECKS = {
    "starter": ["POMMEL_STRIKE", "SHRUG_IT_OFF", "IRON_WAVE"],
    "attack": ["CLEAVE", "UPPERCUT", "CARNAGE", "TWIN_STRIKE"],
    "block": ["METALLICIZE", "IMPERVIOUS", "GHOSTLY_ARMOR", "DISARM"],
    "strength": ["INFLAME", "HEAVY_BLADE", "ANGER", "WHIRLWIND"],
}
STARTER = ["STRIKE"] * 5 + ["DEFEND"] * 4 + ["BASH"]

# A scenario seed describes a benchmark fixture; it is never a network feature.
def make_scenario(backend: str, split: str, index: int, master_seed: int = 20260916) -> tuple[dict, int, str]:
    if split not in ("train", "val", "test"): raise ValueError("split must be train/val/test")
    episode_seed = seed_for("episode", backend, split, index, master_seed)
    rng = random.Random(seed_for("scenario", backend, split, index, master_seed))
    if backend == "reference_v1":
        family = REFERENCE_FAMILIES[index % len(REFERENCE_FAMILIES)]
        pools = {
            "basic": ["POMMEL_STRIKE", "SHRUG_IT_OFF", "ANGER"],
            "wide": ["CLEAVE", "THUNDERCLAP", "WHIRLWIND"],
            "scaling": ["INFLAME", "HEAVY_BLADE", "METALLICIZE", "DISARM"],
            "low_hp": ["IMPERVIOUS", "BLUDGEON", "GHOSTLY_ARMOR", "UPPERCUT"],
        }
        deck = STARTER.copy() + rng.choices(pools[family], k=rng.randint(2, 5))
        deck = [c + "+" if rng.random() < .15 else c for c in deck]
        count = 2 if family == "wide" else 1
        enemies = [{"id": f"TRAINING_{family.upper()}", "hp": rng.randint(22, 38) if count == 2 else rng.randint(42, 70),
                    "damage": rng.randint(4, 6) if count == 2 else rng.randint(7, 11),
                    "scale": 3 if family == "scaling" else 1} for _ in range(count)]
        scenario = {"deck": deck, "enemies": enemies, "max_hp": 80,
                    "hp": rng.randint(14, 28) if family == "low_hp" else rng.randint(45, 75),
                    "potions": [rng.choice(["FIRE", "BLOCK", "STRENGTH"])] if rng.random() < .35 else []}
    elif backend == "lightspeed_pilot":
        family = NATIVE_FAMILIES[index % len(NATIVE_FAMILIES)]
        deck_family = tuple(NATIVE_DECKS)[(index // len(NATIVE_FAMILIES)) % len(NATIVE_DECKS)]
        deck = ["STRIKE_RED"] * 5 + ["DEFEND_RED"] * 4 + ["BASH", "ASCENDERS_BANE"]
        deck += rng.choices(NATIVE_DECKS[deck_family], k=rng.randint(2, 5))
        deck = [c + "+" if c != "ASCENDERS_BANE" and rng.random() < .2 else c for c in deck]
        low, high = NATIVE_HP[family]
        scenario = {"deck": deck, "encounter": rng.choice(NATIVE_ENCOUNTERS[family]),
                    "ascension": 20, "hp": rng.randint(low, high), "max_hp": 80,
                    "floor": 1, "act": 1, "potions": []}
    else: raise ValueError(f"Unknown backend {backend}")
    return scenario, episode_seed, family

def make_env(backend: str, scenario: dict, episode_seed: int):
    if backend == "reference_v1":
        from .reference import ReferenceBattle
        return ReferenceBattle(scenario, episode_seed)
    if backend == "lightspeed_pilot":
        from .native import NativeBattle
        return NativeBattle(scenario, episode_seed)
    raise ValueError(backend)
