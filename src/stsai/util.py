from __future__ import annotations
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any

# Observation schema. Bumped 1->2 when the adapter stopped exporting the
# enemy's planned move; bumped 2->3 when the enemy intent was widened from
# ATTACK/BUFF to the classes the game actually shows, and previous_move
# became previous_intent (a class, not an identity). A reader of schema 2
# would misread both fields. Bumped 3->4 when the adapter began exporting the
# public-derived attack-base range for monsters whose base is rolled at
# construction (the louse), so a schema-3 reader would miss it.
SCHEMA_VERSION = 4

def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def seed_for(*parts: Any) -> int:
    return int(digest(parts)[:15], 16)

def atomic_json(path: str | Path, value: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, p)

def append_json(path: str | Path, value: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(canonical(value) + "\n")

def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def weighted_index(weights: list[float], rng: random.Random) -> int:
    if not weights or min(weights) < 0 or sum(weights) <= 0:
        raise ValueError("Invalid categorical weights")
    x = rng.random() * sum(weights)
    for i, weight in enumerate(weights):
        x -= weight
        if x < 0:
            return i
    return len(weights) - 1
