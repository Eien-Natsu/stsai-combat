from __future__ import annotations
from typing import Any, Protocol, Callable
from .util import canonical, SCHEMA_VERSION

Observation = dict[str, Any]
Action = dict[str, Any]

class Simulator(Protocol):
    def observe(self) -> Observation: ...
    def step(self, action: Action) -> Observation: ...

# This is an interface, not a simulator implementation. Policy/search receive only
# a public observation and a generative sampler; never the live world's RNG.
Sampler = Callable[[int], Simulator]

FORBIDDEN = frozenset({"seed", "rng", "rng_state", "shuffle_rng", "ai_rng", "uuid",
                       "draw_order", "future_intents", "hidden_state", "unique_id",
                       # Names the adapter's debug surface uses for values the player
                       # cannot see. Listing them keeps a leaked debug dump from ever
                       # validating as a public observation.
                       "true_attack_bases", "public_attack_base", "miscinfo",
                       "held_moves", "executed_moves", "combat_events"})

def validate_public(obs: Observation) -> None:
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            bad = FORBIDDEN.intersection(k.lower() for k in x)
            if bad:
                raise ValueError(f"Hidden/identity fields in observation: {sorted(bad)}")
            for v in x.values(): walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x: walk(v)
    walk(obs)
    if obs.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported observation schema")
    if not obs.get("terminal") and not obs.get("actions"):
        raise ValueError("Nonterminal observation has no legal actions")
    if obs.get("terminal") and obs.get("actions"):
        raise ValueError("Terminal observation has actions")
    if obs.get("backend") == "lightspeed_pilot":
        # The native adapter is required to export the public memory digest; a
        # missing field would otherwise read as "not applicable" and silently
        # claim the model has all the information.
        for enemy in obs.get("enemies", []):
            if "attack_base_low" not in enemy or "attack_base_high" not in enemy:
                raise ValueError("Native observation omits the public attack-base memory")
    ids = [a["id"] for a in obs["actions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate legal action IDs")
    if obs["draw_pile"] != sorted(obs["draw_pile"], key=canonical):
        raise ValueError("Unknown draw pile must be a canonical multiset, not draw order")

def observation_key(obs: Observation) -> str:
    # Search nodes are already scoped by history. Retain all observable state,
    # but remove backend labels that do not affect the game.
    from .util import digest
    return digest({k: v for k, v in obs.items() if k not in ("backend", "schema_version")})
