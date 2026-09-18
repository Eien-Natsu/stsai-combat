from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from typing import Any
import numpy as np

FEATURES = 24
VOCAB = 8192

# Bump when the encoder changes which information reaches the model. Checkpoints
# record it and refuse to load across a mismatch, so an old model can never be
# silently evaluated on inputs it was not trained on.
ENCODING_REVISION = 3
MAX_SELECTION = 10
KIND = {"play": 0, "end": 1, "potion": 2, "select": 3, "select_many": 4}
ZONE = {"player": 1, "enemies": 2, "hand": 3, "draw_pile": 4, "discard_pile": 5,
        "exhaust_pile": 6, "potions": 7, "powers": 8, "relics": 9, "choices": 10, "known_top": 11}
ALIASES = {"STRIKE_R": "STRIKE", "STRIKE_RED": "STRIKE", "DEFEND_R": "DEFEND", "DEFEND_RED": "DEFEND",
           "ASCENDERSBANE": "ASCENDERS_BANE", "SHRUGITOFF": "SHRUG_IT_OFF", "POMMELSTRIKE": "POMMEL_STRIKE",
           "IRONWAVE": "IRON_WAVE", "TWINSTRIKE": "TWIN_STRIKE", "HEAVYBLADE": "HEAVY_BLADE",
           "GHOSTLYARMOR": "GHOSTLY_ARMOR", "JAW_WORM": "JAW_WORM", "JAWWORM": "JAW_WORM"}

def normalize(name: str) -> str:
    name = str(name).replace("'", "")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return ALIASES.get(name, name)

def token_id(name: str) -> int:
    # Stable across Python processes; never Python's randomized hash().
    return 1 + int.from_bytes(hashlib.blake2b(name.encode(), digest_size=8).digest(), "little") % (VOCAB - 1)

@dataclass
class Encoded:
    ids: np.ndarray
    features: np.ndarray
    action_kind: np.ndarray
    action_sources: np.ndarray
    action_target: np.ndarray
    action_features: np.ndarray

def encode(obs: dict, max_entities: int = 512, max_actions: int = 1024) -> Encoded:
    from .contracts import validate_public
    validate_public(obs)
    ids = [token_id("CLS")]; feats = [[0.] * FEATURES]
    sources: dict[tuple[str, int], int] = {}
    def add(zone, slot, name, values):
        row = [0.] * FEATURES
        row[0] = ZONE[zone] / 12
        # Unordered draw/discard representations do not get hidden positions.
        row[1] = slot / 10 if zone in ("hand", "enemies", "potions", "choices", "known_top") else 0
        for index, value in values.items(): row[index] = float(value)
        sources[zone, slot] = len(ids)
        ids.append(token_id(zone + ":" + normalize(name))); feats.append(row)
    p = obs["player"]
    add("player", 0, "IRONCLAD", {2: p["hp"] / 100, 3: p["max_hp"] / 100,
        4: p.get("block", 0) / 100, 5: p.get("energy", 0) / 10,
        6: p.get("strength", 0) / 30, 7: p.get("dexterity", 0) / 30,
        8: p.get("weak", 0) / 10, 9: p.get("vulnerable", 0) / 10,
        10: obs["turn"] / 50, 11: obs.get("ascension", 0) / 20,
        12: obs.get("potions_used", 0) / 5, 13: p.get("metallicize", 0) / 20,
        14: p.get("cards_played", 0) / 20, 15: p.get("attacks_played", 0) / 20,
        16: p.get("skills_played", 0) / 20, 17: p.get("artifact", 0) / 5,
        18: p.get("no_draw", 0), 19: p.get("frail", 0) / 10})
    feats[0][0] = obs["turn"] / 50
    feats[0][1] = len(obs["hand"]) / 10
    feats[0][2] = len(obs["draw_pile"]) / 60
    feats[0][3] = len(obs["discard_pile"]) / 60
    feats[0][4] = len(obs["exhaust_pile"]) / 60
    for i, e in enumerate(obs["enemies"]):
        slot = e.get("slot", i)
        add("enemies", slot, e["id"], {2: e["hp"] / 200, 3: e["max_hp"] / 200,
            4: e.get("block", 0) / 100, 5: e.get("intent_damage", 0) / 50,
            6: e.get("strength", 0) / 30, 7: e.get("hits", 1) / 10,
            8: e.get("weak", 0) / 10, 9: e.get("vulnerable", 0) / 10,
            10: float(e["hp"] > 0), 11: e.get("half_dead", 0),
            12: e.get("artifact", 0) / 5})
        # Intent type and visible power identity must not be reduced to damage.
        add("powers", 10000 + i, "ENEMY_INTENT_" + str(slot) + "_" + str(e.get("intent", "UNKNOWN")), {2: 1})
        # The enemy's already-executed move is public: the player watched it
        # resolve. Empirically several enemies choose their next move from that
        # history, so dropping it made the student strictly less informed than
        # the search that produced its labels. The planned move is deliberately
        # NOT exported -- see the adapter.
        previous = e.get("previous_intent")
        if previous and previous != "NONE":
            add("powers", 20000 + i, "ENEMY_PREV_" + str(slot) + "_" + normalize(str(previous)), {2: 1})
    for zone in ("hand", "draw_pile", "discard_pile", "exhaust_pile", "choices", "known_top"):
        for i, c in enumerate(obs.get(zone, [])):
            add(zone, i, c["id"], {2: c.get("cost", 0) / 5,
                3: c.get("upgraded", 0), 4: c.get("damage", 0) / 50,
                5: c.get("block", 0) / 50, 6: c.get("draw", 0) / 5,
                7: c.get("hits", 1) / 10, 8: c.get("exhaust", 0),
                9: c.get("ethereal", 0), 10: c.get("targeted", 0),
                11: float(c.get("type") == "ATTACK"), 12: float(c.get("type") == "SKILL"),
                13: float(c.get("type") == "POWER"), 14: c.get("special", 0) / 100,
                15: c.get("free", 0), 16: c.get("retain", 0)})
    for zone in ("potions", "powers", "relics"):
        for i, x in enumerate(obs.get(zone, [])):
            # Offset power slots so intent token locations are not overwritten.
            slot = x.get("slot", i)
            add(zone, slot, x["id"], {2: x.get("amount", x.get("counter", 0)) / 30,
                                   3: x.get("owner", -1) / 5})
    actions = obs["actions"]
    if len(ids) > max_entities: raise ValueError(f"Entity budget exceeded: {len(ids)} > {max_entities}; no silent truncation")
    if len(actions) > max_actions: raise ValueError(f"Action budget exceeded: {len(actions)} > {max_actions}")
    kinds, src, targets, af = [], [], [], []
    for a in actions:
        if a["kind"] not in KIND: raise ValueError(f"Unknown action kind {a['kind']}")
        kinds.append(KIND[a["kind"]])
        zone = a.get("source_zone", "hand")
        selected = a.get("selection", []) or ([a["source"]] if a.get("source", -1) >= 0 else [])
        if len(selected) > MAX_SELECTION: raise ValueError("Selection size exceeds vanilla hand-size bound")
        slots = [sources.get((zone, i), 0) for i in selected]
        src.append(slots + [0] * (MAX_SELECTION - len(slots)))
        targets.append(sources.get(("enemies", a.get("target", -1)), 0))
        row = [0.] * FEATURES
        row[:12] = [a.get("cost", 0) / 5, a.get("damage", 0) / 100, a.get("block", 0) / 100,
                    a.get("draw", 0) / 5, a.get("hits", 0) / 10, a.get("weak", 0) / 10,
                    a.get("vulnerable", 0) / 10, a.get("buff", 0) / 20,
                    len(selected) / 10, float(a.get("target", -1) >= 0),
                    float(a["kind"] == "end"), float(a["kind"] == "potion")]
        af.append(row)
    return Encoded(np.asarray(ids, dtype=np.int64), np.asarray(feats, dtype=np.float32),
                   np.asarray(kinds, dtype=np.int64), np.asarray(src, dtype=np.int64).reshape(-1, MAX_SELECTION),
                   np.asarray(targets, dtype=np.int64), np.asarray(af, dtype=np.float32).reshape(-1, FEATURES))

def collate_encoded(items: list[Encoded]) -> dict:
    import torch
    if not items: raise ValueError("Empty batch")
    b = len(items); n = max(len(e.ids) for e in items); a = max(len(e.action_kind) for e in items)
    result = {"ids": torch.zeros(b,n,dtype=torch.long), "features": torch.zeros(b,n,FEATURES),
              "entity_mask": torch.zeros(b,n,dtype=torch.bool),
              "action_kind": torch.zeros(b,a,dtype=torch.long),
              "action_sources": torch.zeros(b,a,MAX_SELECTION,dtype=torch.long),
              "action_target": torch.zeros(b,a,dtype=torch.long),
              "action_features": torch.zeros(b,a,FEATURES), "action_mask": torch.zeros(b,a,dtype=torch.bool)}
    for i, e in enumerate(items):
        nt, na = len(e.ids), len(e.action_kind)
        result["ids"][i,:nt] = torch.from_numpy(e.ids)
        result["features"][i,:nt] = torch.from_numpy(e.features)
        result["entity_mask"][i,:nt] = True
        for k in ("action_kind", "action_sources", "action_target", "action_features"):
            result[k][i,:na] = torch.from_numpy(getattr(e,k))
        result["action_mask"][i,:na] = True
    return result
