from __future__ import annotations
from typing import Any, Protocol, Callable
from .util import canonical

Observation = dict[str, Any]
Action = dict[str, Any]

class Simulator(Protocol):
    def observe(self) -> Observation: ...
    def step(self, action: Action) -> Observation: ...

# This is an interface, not a simulator implementation. Policy/search receive only
# a public observation and a generative sampler; never the live world's RNG.
Sampler = Callable[[int], Simulator]

FORBIDDEN = frozenset({"seed", "rng", "rng_state", "shuffle_rng", "ai_rng", "uuid",
                       "draw_order", "future_intents", "hidden_state", "unique_id"})

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
    if obs.get("schema_version") != 1:
        raise ValueError("Unsupported observation schema")
    if not obs.get("terminal") and not obs.get("actions"):
        raise ValueError("Nonterminal observation has no legal actions")
    if obs.get("terminal") and obs.get("actions"):
        raise ValueError("Terminal observation has actions")
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
