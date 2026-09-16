"""Small STS-inspired engineering fixture. NOT an exact original-game simulator.

Use it for tests and smoke-training only. Real-game experiments use lightspeed.
Enemies are intentionally named TRAINING_* to prevent benchmark confusion.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import copy
import math
import random
from typing import Any
from .contracts import Observation, Action, validate_public
from .util import canonical

@dataclass(frozen=True)
class Definition:
    cost: int
    type: str
    damage: int = 0
    block: int = 0
    draw: int = 0
    hits: int = 1
    vulnerable: int = 0
    weak: int = 0
    strength: int = 0
    metallicize: int = 0
    exhaust: bool = False
    ethereal: bool = False
    aoe: bool = False
    xcost: bool = False

CARDS = {
    "STRIKE": Definition(1, "ATTACK", damage=6),
    "DEFEND": Definition(1, "SKILL", block=5),
    "BASH": Definition(2, "ATTACK", damage=8, vulnerable=2),
    "ANGER": Definition(0, "ATTACK", damage=6),
    "CLEAVE": Definition(1, "ATTACK", damage=8, aoe=True),
    "IRON_WAVE": Definition(1, "ATTACK", damage=5, block=5),
    "POMMEL_STRIKE": Definition(1, "ATTACK", damage=9, draw=1),
    "SHRUG_IT_OFF": Definition(1, "SKILL", block=8, draw=1),
    "INFLAME": Definition(1, "POWER", strength=2),
    "METALLICIZE": Definition(1, "POWER", metallicize=3),
    "DISARM": Definition(1, "SKILL", strength=-2, exhaust=True),
    "UPPERCUT": Definition(2, "ATTACK", damage=13, weak=1, vulnerable=1),
    "HEAVY_BLADE": Definition(2, "ATTACK", damage=14),
    "THUNDERCLAP": Definition(1, "ATTACK", damage=4, vulnerable=1, aoe=True),
    "TWIN_STRIKE": Definition(1, "ATTACK", damage=5, hits=2),
    "IMPERVIOUS": Definition(2, "SKILL", block=30, exhaust=True),
    "BLUDGEON": Definition(3, "ATTACK", damage=32),
    "GHOSTLY_ARMOR": Definition(1, "SKILL", block=10, ethereal=True),
    "CARNAGE": Definition(2, "ATTACK", damage=20, ethereal=True),
    "WHIRLWIND": Definition(-1, "ATTACK", damage=5, aoe=True, xcost=True),
    "WOUND": Definition(-2, "STATUS"),
    "DAZED": Definition(-2, "STATUS", ethereal=True),
    "BURN": Definition(-2, "STATUS"),
    "ASCENDERS_BANE": Definition(-2, "CURSE", ethereal=True),
}

@dataclass(frozen=True)
class Card:
    id: str
    upgraded: bool = False
    def __post_init__(self):
        if self.id not in CARDS: raise ValueError(f"Unsupported reference card {self.id}")
    def definition(self) -> Definition:
        d = asdict(CARDS[self.id])
        if self.upgraded:
            if d["damage"]: d["damage"] += 3 if self.id != "BLUDGEON" else 10
            if d["block"]: d["block"] += 3 if self.id != "IMPERVIOUS" else 10
            if d["strength"]: d["strength"] += 1 if d["strength"] > 0 else -1
            if d["metallicize"]: d["metallicize"] += 1
            if self.id in ("BASH", "UPPERCUT"):
                if d["vulnerable"]: d["vulnerable"] += 1
                if d["weak"]: d["weak"] += 1
            if self.id == "POMMEL_STRIKE": d["draw"] += 1
        return Definition(**d)
    def public(self) -> dict[str, Any]:
        d = self.definition()
        return {"id": self.id, "upgraded": int(self.upgraded), "cost": d.cost,
                "type": d.type, "damage": d.damage, "block": d.block,
                "draw": d.draw, "hits": d.hits, "exhaust": d.exhaust,
                "ethereal": d.ethereal, "targeted": not d.aoe and
                (d.type == "ATTACK" or self.id == "DISARM")}

class ReferenceBattle:
    backend = "reference_v1"
    def __init__(self, scenario: dict[str, Any], seed: int):
        self._rng = random.Random(seed)
        self.player = {"hp": int(scenario.get("hp", 60)), "max_hp": int(scenario.get("max_hp", 80)),
                       "block": 0, "energy": 3, "strength": 0, "dexterity": 0,
                       "weak": 0, "vulnerable": 0, "metallicize": 0}
        self.turn = 1
        self.hand: list[Card] = []
        self.discard: list[Card] = []
        self.exhaust: list[Card] = []
        self.potions = list(scenario.get("potions", []))
        if any(p not in ("FIRE", "BLOCK", "STRENGTH") for p in self.potions):
            raise ValueError("Unsupported reference potion")
        self.potions_used = 0
        self.terminal = False
        self.won = False
        self._known_top: list[Card] = []  # top first, only legitimately revealed cards
        self._draw = [Card(c[:-1], True) if c.endswith("+") else Card(c) for c in scenario["deck"]]
        self._rng.shuffle(self._draw)
        self.enemies = []
        for i, e in enumerate(scenario["enemies"]):
            hp = int(e["hp"])
            self.enemies.append({"id": e["id"], "slot": i, "hp": hp, "max_hp": hp,
                                 "block": 0, "strength": 0, "weak": 0, "vulnerable": 0,
                                 "base_damage": int(e.get("damage", 7)), "scale": int(e.get("scale", 1)),
                                 "intent": "ATTACK", "hits": 1})
        self._draw_cards(5)

    @classmethod
    def from_observation(cls, obs: Observation, seed: int) -> "ReferenceBattle":
        validate_public(obs)
        if obs["backend"] != "reference_v1": raise ValueError("Wrong backend")
        self = cls.__new__(cls)
        self._rng = random.Random(seed)
        self.player = copy.deepcopy(obs["player"])
        self.turn = obs["turn"]
        make = lambda c: Card(c["id"], bool(c["upgraded"]))
        self.hand = list(map(make, obs["hand"]))
        self.discard = list(map(make, obs["discard_pile"]))
        self.exhaust = list(map(make, obs["exhaust_pile"]))
        self._draw = list(map(make, obs["draw_pile"]))
        self._known_top = list(map(make, obs.get("known_top", [])))
        for card in self._known_top: self._draw.remove(card)
        self._rng.shuffle(self._draw)
        self._draw += list(reversed(self._known_top))
        self.enemies = copy.deepcopy(obs["enemies"])
        # These are recomputed; redundant observable fields do not become engine state.
        for e in self.enemies:
            e.pop("intent_damage", None); e.pop("powers", None)
        self.potions = [p["id"] for p in obs["potions"]]
        self.potions_used = obs["potions_used"]
        self.terminal = obs["terminal"]; self.won = obs["won"]
        return self

    def sampler(self):
        public = self.observe()
        return lambda seed: ReferenceBattle.from_observation(public, seed)

    def _draw_cards(self, count: int):
        for _ in range(count):
            if len(self.hand) >= 10: break
            if not self._draw:
                if not self.discard: break
                self._draw, self.discard = self.discard, []
                self._rng.shuffle(self._draw)
                self._known_top = []
            c = self._draw.pop()
            if self._known_top:
                if self._known_top[0] != c: raise RuntimeError("Known-top invariant violated")
                self._known_top.pop(0)
            self.hand.append(c)

    def _damage(self, base: int, enemy: dict, card: Card | None = None) -> int:
        multiplier = (5 if card.upgraded else 3) if card and card.id == "HEAVY_BLADE" else 1
        value = max(0, base + self.player["strength"] * multiplier)
        if self.player["weak"]: value = math.floor(value * 0.75)
        if enemy["vulnerable"]: value = math.floor(value * 1.5)
        return value

    def _incoming(self, e: dict) -> int:
        if e["hp"] <= 0 or e["intent"] != "ATTACK": return 0
        damage = max(0, e["base_damage"] + e["strength"])
        if e["weak"]: damage = math.floor(damage * 0.75)
        if self.player["vulnerable"]: damage = math.floor(damage * 1.5)
        return damage

    @staticmethod
    def _hit(target: dict, damage: int):
        damage = max(0, damage)
        absorbed = min(target["block"], damage)
        target["block"] -= absorbed
        target["hp"] = max(0, target["hp"] - damage + absorbed)

    def _check(self):
        if self.player["hp"] <= 0:
            self.terminal, self.won = True, False
        elif all(e["hp"] <= 0 for e in self.enemies):
            self.terminal, self.won = True, True

    def legal_actions(self) -> list[Action]:
        if self.terminal: return []
        actions = []
        for i, c in enumerate(self.hand):
            d = c.definition()
            if d.cost == -2 or (d.cost >= 0 and d.cost > self.player["energy"]): continue
            targeted = c.public()["targeted"]
            targets = [e["slot"] for e in self.enemies if e["hp"] > 0] if targeted else [-1]
            for target in targets:
                enemies = [self.enemies[target]] if targeted else [e for e in self.enemies if e["hp"] > 0]
                hits = self.player["energy"] if d.xcost else d.hits
                damage = sum(self._damage(d.damage, e, c) * hits for e in enemies) if d.damage else 0
                actions.append({"id": f"play:{i}:{target}", "kind": "play", "source": i,
                                "source_zone": "hand", "target": target, "card_id": c.id,
                                "cost": self.player["energy"] if d.xcost else d.cost,
                                "damage": damage, "block": max(0, d.block + self.player["dexterity"]) if d.block else 0,
                                "draw": d.draw, "hits": hits, "weak": d.weak,
                                "vulnerable": d.vulnerable, "buff": d.strength + d.metallicize,
                                "selection": []})
        for i, p in enumerate(self.potions):
            if p == "EMPTY": continue
            targets = [e["slot"] for e in self.enemies if e["hp"] > 0] if p == "FIRE" else [-1]
            for t in targets:
                actions.append({"id": f"potion:{i}:{t}", "kind": "potion", "source": i,
                                "source_zone": "potions", "target": t, "card_id": p,
                                "damage": 20 if p == "FIRE" else 0, "block": 12 if p == "BLOCK" else 0,
                                "cost": 0, "draw": 0, "buff": 2 if p == "STRENGTH" else 0, "selection": []})
        actions.append({"id": "end", "kind": "end", "source": -1, "source_zone": "none",
                        "target": -1, "card_id": "END", "cost": 0, "selection": []})
        return actions

    def observe(self) -> Observation:
        enemies = copy.deepcopy(self.enemies)
        for e in enemies: e["intent_damage"] = self._incoming(e)
        return {"schema_version": 1, "backend": self.backend, "turn": self.turn,
                "phase": "PLAYER_NORMAL", "ascension": 0,
                "player": copy.deepcopy(self.player), "enemies": enemies,
                "hand": [c.public() for c in self.hand],
                "draw_pile": sorted([c.public() for c in self._draw], key=canonical),
                "discard_pile": [c.public() for c in self.discard],
                "exhaust_pile": [c.public() for c in self.exhaust],
                "known_top": [c.public() for c in self._known_top],
                "potions": [{"id": p, "slot": i} for i, p in enumerate(self.potions)],
                "potions_used": self.potions_used, "powers": [], "relics": [],
                "terminal": self.terminal, "won": self.won, "actions": self.legal_actions()}

    def step(self, action: Action) -> Observation:
        legal = {a["id"]: a for a in self.legal_actions()}
        if action.get("id") not in legal: raise ValueError(f"Illegal action: {action.get('id')}")
        a = legal[action["id"]]  # Never trust caller-provided damage or indices.
        if a["kind"] == "end":
            self._end_turn()
        elif a["kind"] == "potion":
            p = self.potions[a["source"]]
            if p == "FIRE": self._hit(self.enemies[a["target"]], 20)
            elif p == "BLOCK": self.player["block"] += 12
            elif p == "STRENGTH": self.player["strength"] += 2
            self.potions[a["source"]] = "EMPTY"; self.potions_used += 1
            self._check()
        else:
            c = self.hand.pop(a["source"]); d = c.definition()
            energy = self.player["energy"]
            self.player["energy"] -= energy if d.xcost else d.cost
            if d.block: self.player["block"] += max(0, d.block + self.player["dexterity"])
            targets = [self.enemies[a["target"]]] if a["target"] >= 0 else self.enemies
            for e in targets:
                if e["hp"] <= 0: continue
                if d.damage:
                    for _ in range(energy if d.xcost else d.hits):
                        self._hit(e, self._damage(d.damage, e, c))
                if e["hp"] > 0:
                    e["vulnerable"] += d.vulnerable; e["weak"] += d.weak
                    if c.id == "DISARM": e["strength"] += d.strength
            if d.type == "POWER":
                self.player["strength"] += d.strength
                self.player["metallicize"] += d.metallicize
            elif d.exhaust: self.exhaust.append(c)
            else: self.discard.append(c)
            if c.id == "ANGER": self.discard.append(c)
            self._check()
            if not self.terminal: self._draw_cards(d.draw)
        return self.observe()

    def _end_turn(self):
        self.player["block"] += self.player["metallicize"]
        for c in self.hand:
            if c.id == "BURN": self._hit(self.player, 2)
            (self.exhaust if c.definition().ethereal else self.discard).append(c)
        self.hand = []
        for e in self.enemies:
            if e["hp"] <= 0: continue
            e["block"] = 0
            if e["intent"] == "ATTACK":
                for _ in range(e["hits"]): self._hit(self.player, self._incoming(e))
            else:
                e["strength"] += e["scale"]
                e["block"] += 5
            e["weak"] = max(0, e["weak"] - 1)
            e["vulnerable"] = max(0, e["vulnerable"] - 1)
        self._check()
        if self.terminal: return
        for k in ("weak", "vulnerable"): self.player[k] = max(0, self.player[k] - 1)
        self.turn += 1; self.player["energy"] = 3; self.player["block"] = 0
        for e in self.enemies:
            if e["hp"] > 0:
                e["intent"] = "BUFF" if self._rng.random() < 0.22 else "ATTACK"
        self._draw_cards(5)
