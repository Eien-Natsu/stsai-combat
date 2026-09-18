#!/usr/bin/env python3
"""Generate the public-intent table for the pilot's supported encounters.

Single source of truth: the table is written as an X-macro file that
`native/bridge.cpp` includes to build its lookup and that this script re-reads to
emit `input/intent_mapping.csv`. Deriving the class from the simulator's own
effect composition keeps every row citable to a line of the locked upstream
source; a small override table records the cases where the game shows something
the effect composition alone would not tell us, each with its reference.

The class is PUBLIC: it is what the player sees. The internal move id is used
only to compute it and is never exported.
"""
import argparse
import csv
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONSTER_CPP = ROOT / "third_party/sts_lightspeed" / "src" / "combat" / "MonsterSpecific.cpp"

# Monsters reachable through the 17 whitelisted encounters.
IN_SCOPE = {
    "CULTIST", "JAW_WORM", "GREEN_LOUSE", "RED_LOUSE", "BLUE_SLAVER", "RED_SLAVER",
    "FUNGI_BEAST", "LOOTER", "GREMLIN_NOB", "LAGAVULIN", "SENTRY",
    "FAT_GREMLIN", "MAD_GREMLIN", "SHIELD_GREMLIN", "SNEAKY_GREMLIN", "GREMLIN_WIZARD",
    "ACID_SLIME_S", "ACID_SLIME_M", "ACID_SLIME_L",
    "SPIKE_SLIME_S", "SPIKE_SLIME_M", "SPIKE_SLIME_L",
}
SPLIT_MOVES = {"ACID_SLIME_L_SPLIT", "SPIKE_SLIME_L_SPLIT"}

# Evidence levels, strongest last. Nothing here is ORIGINAL_GAME_VERIFIED: this
# host has no legal copy of the game, so no row can claim UI parity with it.
EVIDENCE_LEVELS = ("ENGINE_DERIVED_ONLY", "UI_SOURCE_VERIFIED", "ORIGINAL_GAME_VERIFIED")

# Two different reasons a class can be UNKNOWN, kept apart on purpose:
#   GAME_SHOWS_UNKNOWN  - a public source says the game itself shows the unknown icon
#   MAPPING_NOT_KNOWN   - this project has not established what the game shows
UNKNOWN_KIND = {
    "ACID_SLIME_L_SPLIT": "GAME_SHOWS_UNKNOWN",
    "SPIKE_SLIME_L_SPLIT": "GAME_SHOWS_UNKNOWN",
    "GREMLIN_WIZARD_CHARGING": "MAPPING_NOT_KNOWN",
}

# Cases where the visible intent is not simply the effect composition.
# source_checked means a reference was consulted; game_differential_verified stays
# false everywhere because no legal copy of the game is available on this host.
OVERRIDES = {
    "JAW_WORM_BELLOW": ("DEFEND_BUFF",
        "https://slaythespire.wiki.gg/wiki/Jaw_Worm", "wiki: 'defend/buff intent'; gains Strength and Block"),
    "JAW_WORM_THRASH": ("ATTACK_DEFEND",
        "https://slaythespire.wiki.gg/wiki/Jaw_Worm", "wiki: 'attack + defend intent'"),
    "SENTRY_BOLT": ("DEBUFF",
        "https://slaythespire.wiki.gg/wiki/Sentry", "wiki: Bolt 'shown with a debuff intent icon'"),
    "SHIELD_GREMLIN_PROTECT": ("DEFEND",
        "https://slaythespire.wiki.gg/wiki/Shield_Gremlin", "wiki: 'displays the defend intent icon'"),
    "ACID_SLIME_L_SPLIT": ("UNKNOWN",
        "https://slaythespire.wiki.gg/wiki/Acid_Slime", "wiki: Split 'shown with the unknown icon'"),
    "SPIKE_SLIME_L_SPLIT": ("UNKNOWN",
        "https://slaythespire.wiki.gg/wiki/Acid_Slime", "large slime Split family: unknown intent icon"),
    "LAGAVULIN_SLEEP": ("SLEEP",
        "https://slaythespire.wiki.gg/wiki/Lagavulin", "wiki: 'shows the sleep intent icon'"),
    "GREMLIN_WIZARD_CHARGING": ("UNKNOWN", "",
        "no observable effect on the turn it is used; the game's icon was not verified"),
}


def classify(body):
    attack = "attackPlayerHelper(" in body
    block = ("MonsterGainBlock(" in body or "GainBlockRandomEnemy(" in body
             or re.search(r"\baddBlock\(", body) is not None)
    debuff = "DebuffPlayer<" in body
    buff = re.search(r"\bbuff<", body) is not None
    escape = "isEscapingB = true" in body
    status = "MakeTempCard" in body
    if escape: return "ESCAPE"
    if attack and block: return "ATTACK_DEFEND"
    if attack and (debuff or status): return "ATTACK_DEBUFF"
    if attack and buff: return "ATTACK_BUFF"
    if attack: return "ATTACK"
    if block and buff: return "DEFEND_BUFF"
    if block and debuff: return "DEFEND_DEBUFF"
    if block: return "DEFEND"
    if debuff: return "DEBUFF"
    if buff: return "BUFF"
    if status: return "DEBUFF"
    return "UNKNOWN"


def resolve_source(monster_cpp=None):
    """Where the locked MonsterSpecific.cpp is.

    Three sources, in order: an explicit --monster-cpp, the STSAI_ENGINE_SOURCE_DIR
    environment variable (set by review/run_review.py to the patched source the
    build just verified), or the vendored checkout.
    """
    if monster_cpp:
        return Path(monster_cpp)
    from_env = os.environ.get("STSAI_ENGINE_SOURCE_DIR")
    if from_env:
        return Path(from_env) / "src" / "combat" / "MonsterSpecific.cpp"
    return MONSTER_CPP


def derive(monster_cpp=None):
    # The source can come from the offline snapshot when the review machine has no
    # checkout of the upstream repository.
    source_path = resolve_source(monster_cpp)
    if not source_path.is_file():
        raise SystemExit(f"upstream source not found at {source_path}; pass --monster-cpp, set "
                         "STSAI_ENGINE_SOURCE_DIR or run fetch_engine.py")
    lines = source_path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("void Monster::takeTurn"))
    cases = []
    for i in range(start, len(lines)):
        m = re.match(r"\s*case MMID::([A-Z0-9_]+):", lines[i])
        if m:
            cases.append((m.group(1), i))
        elif re.match(r"^\}", lines[i]) and cases:
            break
    rows = []
    for k, (name, lo) in enumerate(cases):
        hi = cases[k + 1][1] if k + 1 < len(cases) else lo + 1
        body = "\n".join(lines[lo:hi])
        # longest matching monster prefix, not rsplit: names like ACID_SLIME_M
        # would otherwise be truncated to ACID_SLIME
        monster = max((m for m in IN_SCOPE if name.startswith(m + "_")), key=len, default=None)
        if monster is None:
            continue
        cls = classify(body)
        if name in SPLIT_MOVES:
            cls = "UNKNOWN"
        source = f"MonsterSpecific.cpp:{lo + 1}"
        level = "ENGINE_DERIVED_ONLY"
        ref = source
        page = ""
        if name in OVERRIDES:
            cls, url, why = OVERRIDES[name]
            level = "UI_SOURCE_VERIFIED" if url else "ENGINE_DERIVED_ONLY"
            page = url
            ref = f"{source}; {url + ' ' if url else ''}{why}"
        rows.append({"monster": monster, "internal_move": name, "public_intent": cls,
                     "evidence_level": level,
                     "unknown_kind": UNKNOWN_KIND.get(name, "") if cls == "UNKNOWN" else "",
                     "source": ref, "source_url": page,
                     "source_checked": bool(name in OVERRIDES and OVERRIDES[name][1]),
                     "game_differential_verified": False})
    return rows


def write_def(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"PUBLIC_INTENT({r['internal_move']}, {r['public_intent']})" for r in rows)
    path.write_text(
        "// GENERATED by scripts/gen_intent_table.py - do not edit by hand.\n"
        "// Internal move id -> the intent class the player actually sees. The move id\n"
        "// is used only to compute this and is never exported (see docs/S1 report).\n"
        "// Verification: source_checked, game_differential_verified=false for every row.\n"
        f"{body}\n", encoding="utf-8")


def read_def(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        m = re.match(r"PUBLIC_INTENT\(([A-Z0-9_]+),\s*([A-Z_]+)\)", line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--def-path", default="native/intent_table.def")
    parser.add_argument("--csv", default="input/intent_mapping.csv")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--monster-cpp", default=None,
                        help="path to the locked MonsterSpecific.cpp; defaults to the vendored checkout")
    args = parser.parse_args()
    rows = derive(args.monster_cpp)
    if args.verify:
        on_disk = read_def(ROOT / args.def_path)
        fresh = [(r["internal_move"], r["public_intent"]) for r in rows]
        if on_disk != fresh:
            raise SystemExit("native/intent_table.def is stale; regenerate it")
        print(f"{args.def_path} matches the derivation ({len(fresh)} rows)")
        return
    write_def(rows, ROOT / args.def_path)
    out = ROOT / args.csv
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["monster", "internal_move", "public_intent",
                                                    "evidence_level", "unknown_kind", "source",
                                                    "source_url", "source_checked",
                                                    "game_differential_verified"])
        writer.writeheader()
        writer.writerows(rows)
    classes = sorted({r["public_intent"] for r in rows})
    print(f"{len(rows)} moves across {len({r['monster'] for r in rows})} monsters")
    print("classes:", classes)
    levels = {}
    for r in rows: levels[r["evidence_level"]] = levels.get(r["evidence_level"], 0) + 1
    print("evidence levels:", levels)
    # a class that does not separate the moves of one monster would be a leak
    collisions = {}
    for r in rows:
        collisions.setdefault((r["monster"], r["public_intent"]), []).append(r["internal_move"])
    ambiguous = {k: v for k, v in collisions.items() if len(v) > 1}
    print("same-monster classes covering more than one move:", ambiguous or "none")
    json.dump({"rows": len(rows), "classes": classes, "evidence_levels": levels,
               "unknown_rows": {r["internal_move"]: r["unknown_kind"]
                                for r in rows if r["public_intent"] == "UNKNOWN"},
               "same_class_collisions": {f"{m}|{c}": v for (m, c), v in ambiguous.items()}},
              open(ROOT / "reports/s1_intent_table_summary.json", "w"), indent=2)


if __name__ == "__main__":
    main()
