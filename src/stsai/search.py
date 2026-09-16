"""History-indexed, root-sampled PUCT for a single-player partially observed game.

Chance outcomes branch by PUBLIC observation, never by hidden state or RNG.
This is a practical POMCP-style variant, not a claim of exact POMDP solution.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import random
import time
from typing import Protocol
import numpy as np
from .contracts import Observation, Sampler, validate_public, observation_key
from .objective import terminal_utility

class Evaluator(Protocol):
    def evaluate(self, obs: Observation) -> tuple[list[float], float]: ...

class HeuristicEvaluator:
    def evaluate(self, obs: Observation) -> tuple[list[float], float]:
        incoming = sum(e.get("intent_damage", 0) * e.get("hits", 1) for e in obs["enemies"] if e["hp"] > 0)
        deficit = max(0, incoming - obs["player"]["block"])
        scores = []
        for a in obs["actions"]:
            damage = a.get("damage", 0)
            block = min(deficit, a.get("block", 0))
            score = .12 * damage + .17 * block + .2 * a.get("draw", 0) + .15 * abs(a.get("buff", 0))
            score += .12 * (a.get("weak", 0) + a.get("vulnerable", 0))
            if a["kind"] == "end": score = -2.5 if len(obs["actions"]) > 1 else 0
            if a["kind"] == "potion": score -= .8
            t = a.get("target", -1)
            enemy = next((e for e in obs["enemies"] if e["slot"] == t), None)
            if enemy and damage >= enemy["hp"] + enemy.get("block", 0): score += 2.0
            scores.append(max(-12, min(12, score)))
        x = np.asarray(scores, dtype=np.float64)
        priors = np.exp(x - x.max()); priors /= priors.sum()
        # Only a cutoff heuristic, NOT a calibrated probability of winning.
        hp = obs["player"]["hp"] / max(1, obs["player"]["max_hp"])
        threat = sum(e["hp"] for e in obs["enemies"]) / 200
        value = float(np.clip(.55 + .35 * hp - .15 * threat - .004 * deficit, 0, 1))
        return priors.tolist(), value

@dataclass
class SearchConfig:
    simulations: int = 64
    max_depth: int = 60
    rollout_limit: int = 100
    c_puct: float = 1.5
    rollout_epsilon: float = .12
    potion_cost: float = .02
    use_leaf_value: bool = False
    def __post_init__(self):
        if self.simulations < 1 or self.max_depth < 1 or self.rollout_limit < 1:
            raise ValueError("Search budgets must be positive")
        if not 0 <= self.rollout_epsilon <= 1: raise ValueError("Invalid rollout_epsilon")

@dataclass
class Edge:
    prior: float
    visits: int = 0
    total: float = 0.0
    children: dict[str, "Node"] = field(default_factory=dict)
    @property
    def q(self): return self.total / self.visits if self.visits else 0.0

@dataclass
class Node:
    edges: dict[str, Edge] = field(default_factory=dict)
    visits: int = 0
    value: float = 0.0

class BeliefSearch:
    def __init__(self, config: SearchConfig | None = None, evaluator: Evaluator | None = None):
        self.config = config or SearchConfig()
        self.evaluator = evaluator or HeuristicEvaluator()
        self.rollout_evaluator = HeuristicEvaluator()

    def _expand(self, node: Node, obs: Observation):
        priors, value = self.evaluator.evaluate(obs)
        if len(priors) != len(obs["actions"]) or not np.isfinite(priors).all() or sum(priors) <= 0 or min(priors) < 0:
            raise ValueError("Invalid policy output")
        total = sum(priors)
        node.edges = {a["id"]: Edge(float(p) / total) for a, p in zip(obs["actions"], priors)}
        node.value = float(np.clip(value, 0, 1))

    def run(self, obs: Observation, sampler: Sampler, seed: int = 0) -> dict:
        validate_public(obs)
        if obs["terminal"]: raise ValueError("Cannot search terminal state")
        root = Node(); self._expand(root, obs)
        rng = random.Random(seed)
        started = time.perf_counter()
        root_key = observation_key(obs)
        # At least one visit per root action; all remain legal candidates.
        budget = max(self.config.simulations, len(obs["actions"]))
        cutoffs = 0
        for i in range(budget):
            sim = sampler(rng.getrandbits(63))
            cur = sim.observe()
            if observation_key(cur) != root_key:
                raise RuntimeError("Belief sample changed the public root observation")
            node = root; path: list[tuple[Node, Edge]] = []
            value = 0.0
            for depth in range(self.config.max_depth):
                if cur["terminal"]:
                    value = terminal_utility(cur, self.config.potion_cost); break
                legal = {a["id"]: a for a in cur["actions"]}
                if set(legal) != set(node.edges):
                    raise RuntimeError("Same information state produced different legal actions")
                unvisited = [k for k, e in node.edges.items() if e.visits == 0]
                if unvisited:
                    aid = max(unvisited, key=lambda k: node.edges[k].prior)
                else:
                    aid = max(node.edges, key=lambda k: node.edges[k].q + self.config.c_puct * node.edges[k].prior * math.sqrt(node.visits + 1) / (1 + node.edges[k].visits))
                edge = node.edges[aid]; path.append((node, edge))
                cur = sim.step(legal[aid])
                if cur["terminal"]:
                    value = terminal_utility(cur, self.config.potion_cost); break
                key = observation_key(cur)
                if key not in edge.children:
                    child = Node(); self._expand(child, cur); edge.children[key] = child
                    if self.config.use_leaf_value:
                        value = child.value; cutoffs += 1
                    else:
                        value, censored = self._rollout(sim, cur, rng); cutoffs += int(censored)
                    break
                node = edge.children[key]
            else:
                _, value = self.evaluator.evaluate(cur); cutoffs += 1
            for parent, edge in path:
                parent.visits += 1; edge.visits += 1; edge.total += value
        visits = [root.edges[a["id"]].visits for a in obs["actions"]]
        total = sum(visits)
        pi = [n / total for n in visits]
        index = max(range(len(visits)), key=lambda j: (visits[j], root.edges[obs["actions"][j]["id"]].q))
        return {"action": obs["actions"][index], "policy": pi, "visits": visits,
                "q": [root.edges[a["id"]].q for a in obs["actions"]],
                "simulations": budget, "cutoff_fraction": cutoffs / budget,
                "elapsed_seconds": time.perf_counter() - started}

    def _rollout(self, sim, obs, rng):
        for _ in range(self.config.rollout_limit):
            if obs["terminal"]: return terminal_utility(obs, self.config.potion_cost), False
            p, _ = self.rollout_evaluator.evaluate(obs)
            index = rng.randrange(len(p)) if rng.random() < self.config.rollout_epsilon else int(np.argmax(p))
            obs = sim.step(obs["actions"][index])
        if obs["terminal"]: return terminal_utility(obs, self.config.potion_cost), False
        _, value = self.evaluator.evaluate(obs)
        return value, True
