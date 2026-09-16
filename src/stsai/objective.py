from __future__ import annotations
import numpy as np

OUTCOME_BINS = 11  # death plus 10 equally spaced surviving HP bin CENTRES

def terminal_utility(obs: dict, potion_cost: float = .02) -> float:
    if not obs["terminal"]: raise ValueError("Terminal outcome required")
    if not obs["won"]: return 0.0
    p = obs["player"]
    return max(0.0, .8 + .2 * p["hp"] / max(1, p["max_hp"]) - potion_cost * obs.get("potions_used", 0))

def outcome_target(obs: dict) -> list[float]:
    if not obs["terminal"]: return [0.0] * OUTCOME_BINS
    y = np.zeros(OUTCOME_BINS, dtype=np.float32)
    if not obs["won"]: y[0] = 1.0
    else:
        # Interpolate centres at HP fractions 0.05,0.15,...,0.95.
        x = np.clip(obs["player"]["hp"] / max(1, obs["player"]["max_hp"]) * 10 - .5, 0, 9)
        lo = int(x); hi = min(9, lo + 1); f = float(x - lo)
        y[1 + lo] += 1 - f; y[1 + hi] += f
    return y.tolist()

def utility_from_distribution(probabilities, potions_used: int = 0, potion_cost: float = .02) -> float:
    values = np.array([0.] + [.8 + .2 * ((i + .5) / 10) - potion_cost * potions_used for i in range(10)])
    return float(np.clip(np.dot(probabilities, values), 0, 1))
