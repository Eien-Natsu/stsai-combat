from __future__ import annotations
import random
from .util import seed_for

REFERENCE_FAMILIES = ("basic", "wide", "scaling", "low_hp")
NATIVE_FAMILIES = ("starter", "attack", "block", "strength")
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
        pools = {"starter": ["POMMEL_STRIKE", "SHRUG_IT_OFF", "IRON_WAVE"],
                 "attack": ["CLEAVE", "UPPERCUT", "CARNAGE", "TWIN_STRIKE"],
                 "block": ["METALLICIZE", "IMPERVIOUS", "GHOSTLY_ARMOR", "DISARM"],
                 "strength": ["INFLAME", "HEAVY_BLADE", "ANGER", "WHIRLWIND"]}
        deck = ["STRIKE_RED"] * 5 + ["DEFEND_RED"] * 4 + ["BASH", "ASCENDERS_BANE"]
        deck += rng.choices(pools[family], k=rng.randint(2, 5))
        deck = [c + "+" if c != "ASCENDERS_BANE" and rng.random() < .2 else c for c in deck]
        scenario = {"deck": deck, "encounter": rng.choice(["CULTIST", "JAW_WORM"]),
                    "ascension": 20, "hp": rng.randint(30, 70), "max_hp": 80,
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
