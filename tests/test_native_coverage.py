"""Directed per-card and per-enemy coverage for the pilot whitelist.

Every whitelisted card is asserted in both its base and upgraded form against
known Slay the Spire card values, and both pilot enemies must expose every move
they can visibly make. This is directed evidence for the supported range; it is
NOT a claim that the supported range covers the game.

Skips only when the native extension is not compiled. A skip is not a pass.
"""
from pathlib import Path

import pytest

pytest.importorskip("stsai._lightspeed", reason="Native extension not compiled in this environment")
from stsai.native import NativeBattle
from stsai.contracts import validate_public
from stsai.encoding import normalize

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.native

# The adapter exposes canonical cross-backend names (STRIKE_RED -> STRIKE).
def canonical(card):
    return normalize(card)

ASCENSION = 20
PLAYER_HP = 80

# card -> (cost, upgraded cost). Costs do not change on upgrade for this set.
COSTS = {
    "STRIKE_RED": 1, "DEFEND_RED": 1, "BASH": 2, "POMMEL_STRIKE": 1, "SHRUG_IT_OFF": 1,
    "IRON_WAVE": 1, "CLEAVE": 1, "UPPERCUT": 2, "CARNAGE": 2, "TWIN_STRIKE": 1,
    "METALLICIZE": 1, "IMPERVIOUS": 2, "GHOSTLY_ARMOR": 1, "DISARM": 1, "INFLAME": 1,
    "HEAVY_BLADE": 2, "ANGER": 0, "WHIRLWIND": -1, "THUNDERCLAP": 1, "BLUDGEON": 3,
}
# Whirlwind is X-cost; the bridge reports the energy it would consume.
XCOST = {"WHIRLWIND"}
# Status cards injected by supported enemies. Slimed is playable (it exhausts);
# Dazed is unplayable and ethereal.
STATUS_INJECTED = {"SLIMED": 1, "DAZED": 0}
UNPLAYABLE = {"ASCENDERS_BANE", "DAZED"}
PLAYABLE = sorted(COSTS) + ["SLIMED"]
ALL_CARDS = PLAYABLE + sorted(UNPLAYABLE)
# None of these have an upgraded form inside the pilot range, so that
# combination is not generated rather than silently skipped.
NO_UPGRADE = UNPLAYABLE | {"SLIMED"}
CARD_FORMS = [(c, up) for c in ALL_CARDS for up in (False, True) if not (up and c in NO_UPGRADE)]


TANK_HP = 200  # coverage fixture: survive long enough to see later enemy branches


def end_turn(obs):
    """The one action that advances enemy behaviour without dealing damage."""
    return next(a for a in obs["actions"] if a["kind"] == "end")


def pilot(card, upgraded=False, encounter="CULTIST", hp=PLAYER_HP, copies=10, seed=7, extra=()):
    """Deck of identical copies so the opening hand is deterministic."""
    deck = [card + "+" if upgraded else card] * copies + list(extra)
    scenario = {"deck": deck, "encounter": encounter, "ascension": ASCENSION,
                "hp": hp, "max_hp": max(PLAYER_HP, hp), "floor": 1, "act": 1, "potions": []}
    return NativeBattle(scenario, seed)


def play(env, obs, card):
    """Play the sole legal action for `card`; fail if it is not offered."""
    matches = [a for a in obs["actions"] if a.get("card_id") == canonical(card)]
    assert matches, f"{card} not offered; legal actions: {[a.get('card_id') for a in obs['actions']]}"
    return env.step(matches[0])


def enemy(obs):
    return obs["enemies"][0]


def zone_count(obs, card):
    """How many copies of `card` sit in the public deck zones."""
    name = canonical(card)
    return sum(1 for zone in ("hand", "draw_pile", "discard_pile", "exhaust_pile")
               for c in obs[zone] if c["id"] == name)


def test_ascenders_bane_cannot_be_upgraded():
    # The one card the adapter must refuse outright rather than paper over.
    with pytest.raises((ValueError, RuntimeError)):
        pilot("ASCENDERS_BANE", upgraded=True).observe()


@pytest.mark.parametrize("card,upgraded", CARD_FORMS)
def test_card_is_offered_with_correct_cost(card, upgraded):
    env = pilot(card, upgraded)
    obs = env.observe()
    validate_public(obs)
    offered = [a for a in obs["actions"] if a.get("card_id") == canonical(card)]
    if card in UNPLAYABLE:
        assert not offered, f"{card} must never be a legal action"
        assert obs["player"]["energy"] == 3
        return
    assert offered, f"{card} not offered in an all-{card} deck"
    expected = obs["player"]["energy"] if card in XCOST else COSTS.get(card, STATUS_INJECTED.get(card))
    assert {a["cost"] for a in offered} == {expected}


@pytest.mark.parametrize("card,base,upgraded", [
    ("STRIKE_RED", 6, 9), ("BASH", 8, 10), ("POMMEL_STRIKE", 9, 10),
    ("UPPERCUT", 13, 13), ("CARNAGE", 20, 28), ("HEAVY_BLADE", 14, 14),
    ("ANGER", 6, 8), ("BLUDGEON", 32, 42), ("IRON_WAVE", 5, 7),
])
def test_single_target_attack_damage(card, base, upgraded):
    for up, expected in ((False, base), (True, upgraded)):
        env = pilot(card, up)
        before = env.observe()
        after = play(env, before, card)
        dealt = enemy(before)["hp"] - enemy(after)["hp"]
        assert dealt == expected, f"{card}{'+' if up else ''} dealt {dealt}, expected {expected}"


def test_twin_strike_hits_twice():
    for up, expected in ((False, 5), (True, 7)):
        env = pilot("TWIN_STRIKE", up)
        before = env.observe()
        after = play(env, before, "TWIN_STRIKE")
        assert enemy(before)["hp"] - enemy(after)["hp"] == 2 * expected
        assert before["hand"][0]["hits"] == 2


def test_cleave_hits_every_enemy():
    env = pilot("CLEAVE")
    before = env.observe()
    after = play(env, before, "CLEAVE")
    assert enemy(before)["hp"] - enemy(after)["hp"] == 8


def test_whirlwind_spends_all_energy_and_scales():
    for up, per_hit in ((False, 5), (True, 8)):
        env = pilot("WHIRLWIND", up)
        before = env.observe()
        energy = before["player"]["energy"]
        assert energy > 0, "fixture must have energy for an X-cost card"
        after = play(env, before, "WHIRLWIND")
        assert after["player"]["energy"] == 0, "X-cost must consume all energy"
        assert enemy(before)["hp"] - enemy(after)["hp"] == per_hit * energy


@pytest.mark.parametrize("card,base,upgraded", [
    ("DEFEND_RED", 5, 8), ("IRON_WAVE", 5, 7), ("SHRUG_IT_OFF", 8, 11),
    ("GHOSTLY_ARMOR", 10, 13), ("IMPERVIOUS", 30, 40),
])
def test_block_gain(card, base, upgraded):
    for up, expected in ((False, base), (True, upgraded)):
        env = pilot(card, up)
        before = env.observe()
        after = play(env, before, card)
        assert after["player"]["block"] - before["player"]["block"] == expected


def test_pommel_strike_and_shrug_it_off_draw():
    for card, per_draw in (("POMMEL_STRIKE", (1, 2)), ("SHRUG_IT_OFF", (1, 1))):
        for up, expected in ((False, per_draw[0]), (True, per_draw[1])):
            env = pilot(card, up)
            before = env.observe()
            hand = len(before["hand"])
            # Playing removes one card from hand, then the card draws `expected`.
            after = play(env, before, card)
            assert len(after["hand"]) == hand - 1 + expected, f"{card} draw on upgrade={up}"


@pytest.mark.parametrize("card,base,upgraded", [
    ("BASH", 2, 3), ("UPPERCUT", 1, 2), ("THUNDERCLAP", 1, 1),
])
def test_vulnerable_application(card, base, upgraded):
    for up, expected in ((False, base), (True, upgraded)):
        env = pilot(card, up)
        after = play(env, env.observe(), card)
        assert enemy(after)["vulnerable"] == expected, f"{card} vulnerable on upgrade={up}"


@pytest.mark.parametrize("base,upgraded", [(1, 2)])
def test_uppercut_applies_weak(base, upgraded):
    for up, expected in ((False, base), (True, upgraded)):
        env = pilot("UPPERCUT", up)
        after = play(env, env.observe(), "UPPERCUT")
        assert enemy(after)["weak"] == expected


def test_disarm_reduces_enemy_strength_and_exhausts():
    for up, expected in ((False, -2), (True, -3)):
        env = pilot("DISARM", up)
        before = env.observe()
        after = play(env, before, "DISARM")
        assert enemy(after)["strength"] - enemy(before)["strength"] == expected
        assert any(c["id"] == "DISARM" for c in after["exhaust_pile"]), "Disarm must exhaust"


def test_inflame_and_metallicize_are_powers():
    for card, base, upgraded in (("INFLAME", 2, 3), ("METALLICIZE", 3, 4)):
        for up, expected in ((False, base), (True, upgraded)):
            env = pilot(card, up)
            before = env.observe()
            after = play(env, before, card)
            key = "strength" if card == "INFLAME" else "metallicize"
            assert after["player"][key] - before["player"][key] == expected, f"{card} upgrade={up}"
            assert zone_count(after, card) == zone_count(before, card) - 1, \
                "a played power must leave the deck zones"


def test_impervious_and_ghostly_armor_flags():
    env = pilot("IMPERVIOUS")
    before = env.observe()
    assert before["hand"][0]["exhaust"] == 1, "Impervious must report exhaust"
    after = play(env, before, "IMPERVIOUS")
    assert any(c["id"] == "IMPERVIOUS" for c in after["exhaust_pile"])

    env = pilot("GHOSTLY_ARMOR")
    before = env.observe()
    assert before["hand"][0]["ethereal"] == 1, "Ghostly Armor must report ethereal"


def test_carnage_is_ethereal():
    env = pilot("CARNAGE")
    assert env.observe()["hand"][0]["ethereal"] == 1


def test_anger_adds_a_copy_to_discard():
    for up, expected in ((False, 6), (True, 8)):
        env = pilot("ANGER", up)
        before = env.observe()
        discarded = [c["id"] for c in before["discard_pile"]]
        after = play(env, before, "ANGER")
        assert enemy(before)["hp"] - enemy(after)["hp"] == expected
        assert [c["id"] for c in after["discard_pile"]].count("ANGER") == discarded.count("ANGER") + 2, \
            "Anger puts itself plus a copy into the discard pile"


def test_ascenders_bane_is_never_playable():
    env = pilot("STRIKE_RED", extra=["ASCENDERS_BANE"])
    obs = env.observe()
    assert all(a.get("card_id") != "ASCENDERS_BANE" for a in obs["actions"])
    # The hand must still contain it, so the refusal is about legality, not absence.
    assert any(c["id"] == "ASCENDERS_BANE" for c in obs["hand"]) or \
           any(c["id"] == "ASCENDERS_BANE" for c in obs["draw_pile"])


POWERS = {"INFLAME", "METALLICIZE"}


def test_play_never_creates_or_destroys_cards_by_accident():
    """Playing a card moves it: powers leave the deck, Anger copies itself, the rest recycle."""
    for card in PLAYABLE:
        env = pilot(card)
        before = env.observe()
        after = play(env, before, card)
        delta = zone_count(after, card) - zone_count(before, card)
        if card in POWERS:
            expected = -1
        elif card == "ANGER":
            expected = +1
        else:
            expected = 0
        assert delta == expected, f"{card} changed deck-zone count by {delta}, expected {expected}"


# --- enemy visible-behaviour coverage -------------------------------------

def test_build_reports_the_locked_revision_and_patch_hashes():
    """A build must never misreport a patched tree as pristine upstream."""
    import json
    from pathlib import Path
    from stsai.native import engine_metadata
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "engine_lock.json").read_text(encoding="utf-8"))
    info = engine_metadata()
    assert info["revision"] == lock["revision"]
    assert info["patches"] == [p["sha256"] for p in lock.get("patches", [])]
    assert info["game_differential_verified"] is False, \
        "original-game differential testing has not been performed; do not claim it"


def executed_moves(env):
    """Internal move names, via the TEST-ONLY hook.

    observe() exports the public intent CLASS, and two moves of one monster can
    share a class (Looter Mug and Lunge are both ATTACK), so branch coverage
    cannot be measured from the observation. The hook is the only place an
    internal move name is visible; `test_observe_exports_no_internal_move`
    asserts it never appears in an observation.
    """
    return env._handle.debug_internals()


def observed_moves(encounter, seeds=range(24), turns=60):
    """Moves the enemy has EXECUTED, per branch-coverage requirements."""
    moves, monsters = set(), set()
    for seed in seeds:
        env = pilot("DEFEND_RED", encounter=encounter, hp=TANK_HP, seed=seed)
        for _ in range(turns):
            obs = env.observe()
            for e in obs["enemies"]:
                monsters.add(e["id"])
            for name in executed_moves(env)["executed_moves"].values():
                if name != "INVALID":
                    moves.add(name)
            if obs["terminal"]:
                break
            env.step(end_turn(obs))
    return monsters, moves


# Every move upstream defines for each monster reachable in Act 1, read from the
# pinned revision's MonsterMoves.h table.
MONSTER_MOVES = {
    "CULTIST": {"CULTIST_INCANTATION", "CULTIST_DARK_STRIKE"},
    "JAW_WORM": {"JAW_WORM_CHOMP", "JAW_WORM_THRASH", "JAW_WORM_BELLOW"},
    "GREEN_LOUSE": {"GREEN_LOUSE_BITE", "GREEN_LOUSE_SPIT_WEB"},
    "RED_LOUSE": {"RED_LOUSE_BITE", "RED_LOUSE_GROW"},
    "BLUE_SLAVER": {"BLUE_SLAVER_STAB", "BLUE_SLAVER_RAKE"},
    "RED_SLAVER": {"RED_SLAVER_STAB", "RED_SLAVER_SCRAPE", "RED_SLAVER_ENTANGLE"},
    "FUNGI_BEAST": {"FUNGI_BEAST_BITE", "FUNGI_BEAST_GROW"},
    "LOOTER": {"LOOTER_MUG", "LOOTER_LUNGE", "LOOTER_SMOKE_BOMB", "LOOTER_ESCAPE"},
    "GREMLIN_NOB": {"GREMLIN_NOB_BELLOW", "GREMLIN_NOB_RUSH", "GREMLIN_NOB_SKULL_BASH"},
    "LAGAVULIN": {"LAGAVULIN_SLEEP", "LAGAVULIN_ATTACK", "LAGAVULIN_SIPHON_SOUL"},
    "SENTRY": {"SENTRY_BEAM", "SENTRY_BOLT"},
    "FAT_GREMLIN": {"FAT_GREMLIN_SMASH"},
    "MAD_GREMLIN": {"MAD_GREMLIN_SCRATCH"},
    "SHIELD_GREMLIN": {"SHIELD_GREMLIN_PROTECT", "SHIELD_GREMLIN_SHIELD_BASH"},
    "SNEAKY_GREMLIN": {"SNEAKY_GREMLIN_PUNCTURE"},
    "GREMLIN_WIZARD": {"GREMLIN_WIZARD_CHARGING", "GREMLIN_WIZARD_ULTIMATE_BLAST"},
    "ACID_SLIME_S": {"ACID_SLIME_S_LICK", "ACID_SLIME_S_TACKLE"},
    "ACID_SLIME_M": {"ACID_SLIME_M_CORROSIVE_SPIT", "ACID_SLIME_M_LICK", "ACID_SLIME_M_TACKLE"},
    "ACID_SLIME_L": {"ACID_SLIME_L_CORROSIVE_SPIT", "ACID_SLIME_L_LICK", "ACID_SLIME_L_TACKLE",
                     "ACID_SLIME_L_SPLIT"},
    "SPIKE_SLIME_S": {"SPIKE_SLIME_S_TACKLE"},
    "SPIKE_SLIME_M": {"SPIKE_SLIME_M_FLAME_TACKLE", "SPIKE_SLIME_M_LICK"},
    "SPIKE_SLIME_L": {"SPIKE_SLIME_L_FLAME_TACKLE", "SPIKE_SLIME_L_LICK", "SPIKE_SLIME_L_SPLIT"},
}
# Exordium Thugs/Wildlife and the louse, slime and gremlin groups draw their
# roster from a per-encounter pool, so their monsters vary by seed.
ENCOUNTERS = {
    "CULTIST": {"CULTIST"}, "JAW_WORM": {"JAW_WORM"},
    "BLUE_SLAVER": {"BLUE_SLAVER"}, "RED_SLAVER": {"RED_SLAVER"},
    "TWO_FUNGI_BEASTS": {"FUNGI_BEAST"}, "LOOTER": {"LOOTER"},
    "GREMLIN_NOB": {"GREMLIN_NOB"}, "LAGAVULIN": {"LAGAVULIN"},
    "THREE_SENTRIES": {"SENTRY"},
    "TWO_LOUSE": {"GREEN_LOUSE", "RED_LOUSE"}, "THREE_LOUSE": {"GREEN_LOUSE", "RED_LOUSE"},
    "EXORDIUM_THUGS": {"GREEN_LOUSE", "RED_LOUSE", "BLUE_SLAVER", "RED_SLAVER", "LOOTER",
                       "ACID_SLIME_M", "SPIKE_SLIME_M", "CULTIST"},
    "EXORDIUM_WILDLIFE": {"FUNGI_BEAST", "GREEN_LOUSE", "RED_LOUSE", "JAW_WORM",
                          "ACID_SLIME_M", "SPIKE_SLIME_M"},
    "GREMLIN_GANG": {"SNEAKY_GREMLIN", "MAD_GREMLIN", "FAT_GREMLIN", "SHIELD_GREMLIN",
                     "GREMLIN_WIZARD"},
    "SMALL_SLIMES": {"ACID_SLIME_M", "ACID_SLIME_S", "SPIKE_SLIME_M", "SPIKE_SLIME_S"},
    "LOTS_OF_SLIMES": {"ACID_SLIME_S", "SPIKE_SLIME_S"},
    "LARGE_SLIME": {"ACID_SLIME_L", "SPIKE_SLIME_L", "ACID_SLIME_M", "ACID_SLIME_S"},
}


@pytest.mark.parametrize("encounter", sorted(ENCOUNTERS))
def test_encounter_stays_inside_its_declared_move_space(encounter):
    monsters, moves = observed_moves(encounter)
    assert monsters, f"{encounter} produced no observation"
    assert monsters <= ENCOUNTERS[encounter], f"{encounter} produced unexpected monsters: {monsters}"
    allowed = set().union(*(MONSTER_MOVES[m] for m in monsters))
    assert moves <= allowed, f"{encounter} used undeclared moves: {moves - allowed}"


@pytest.mark.parametrize("encounter", ["CULTIST", "JAW_WORM", "BLUE_SLAVER", "RED_SLAVER",
                                       "TWO_FUNGI_BEASTS", "LOOTER", "GREMLIN_NOB",
                                       "LAGAVULIN", "THREE_SENTRIES"])
def test_fixed_encounter_covers_every_visible_branch(encounter):
    """Fixed-roster encounters must exercise every move the monster can make."""
    monsters, moves = observed_moves(encounter)
    assert len(monsters) == 1, f"{encounter} should have one monster type, saw {monsters}"
    expected = MONSTER_MOVES[next(iter(monsters))]
    assert moves == expected, f"{encounter} missed {expected - moves}"


def test_cultist_ritual_is_exported_as_a_power():
    env = pilot("STRIKE_RED", encounter="CULTIST")
    after = env.step(env.observe()["actions"][-1])  # end turn -> Incantation resolves
    ritual = [p for p in after["powers"] if p["id"] == "RITUAL"]
    assert ritual and ritual[0]["amount"] > 0
    assert ritual[0]["owner"] == 0


def test_gremlin_nob_follows_the_a18_fixed_pattern():
    """A18+ replaces the random choice with Bellow, Skull Bash, Rush, Rush, ..."""
    env = pilot("DEFEND_RED", encounter="GREMLIN_NOB", hp=TANK_HP)
    executed = []
    for _ in range(9):
        obs = env.observe()
        assert not obs["terminal"], "the tanky fixture must survive the sampled turns"
        previous = executed_moves(env)["executed_moves"][0]
        if previous != "INVALID":
            executed.append(previous)
        env.step(end_turn(obs))  # never damages the Nob, so the cycle runs on
    expected = ["GREMLIN_NOB_BELLOW", "GREMLIN_NOB_SKULL_BASH",
                "GREMLIN_NOB_RUSH", "GREMLIN_NOB_RUSH",
                "GREMLIN_NOB_SKULL_BASH", "GREMLIN_NOB_RUSH",
                "GREMLIN_NOB_RUSH", "GREMLIN_NOB_SKULL_BASH"]
    assert executed == expected, executed


PUBLIC_ENEMY_KEYS = frozenset({
    "id", "slot", "hp", "max_hp", "block", "strength", "weak", "vulnerable",
    "artifact", "half_dead", "intent_damage", "hits", "intent", "previous_intent",
    # public-derived memory of a construction-time hidden attack base
    "attack_base_low", "attack_base_high",
})


def test_observe_exports_no_internal_move():
    """The hook knows the held move; observe() must not, under any key."""
    for encounter in ("JAW_WORM", "LAGAVULIN", "LOOTER", "CULTIST", "THREE_SENTRIES"):
        env = pilot("STRIKE_RED", encounter=encounter, seed=3)
        enemy = env.observe()["enemies"][0]
        assert set(enemy) == set(PUBLIC_ENEMY_KEYS), f"{encounter}: {set(enemy) ^ set(PUBLIC_ENEMY_KEYS)}"
        held = executed_moves(env)["held_moves"][0]
        assert held not in repr(enemy), f"{encounter} leaked the held move {held}"


def test_intent_is_a_documented_public_class():
    allowed = {"ATTACK", "ATTACK_DEFEND", "ATTACK_DEBUFF", "ATTACK_BUFF", "DEFEND",
               "DEFEND_BUFF", "DEFEND_DEBUFF", "DEBUFF", "BUFF", "SLEEP", "ESCAPE",
               "UNKNOWN", "NONE"}
    for encounter in ENCOUNTERS:
        env = pilot("STRIKE_RED", encounter=encounter, seed=11)
        for _ in range(12):
            obs = env.observe()
            for e in obs["enemies"]:
                assert e["intent"] in allowed, f"{encounter}: {e['intent']} is not a public class"
            if obs["terminal"]:
                break
            env.step(end_turn(obs))


def test_previous_intent_only_ever_reports_an_executed_move():
    """At turn 1 nothing has resolved; afterwards it is the executed class."""
    env = pilot("DEFEND_RED", encounter="JAW_WORM", hp=TANK_HP)
    assert env.observe()["enemies"][0]["previous_intent"] == "NONE"
    after = env.step(end_turn(env.observe()))
    # the executed move was the one held at turn 1: Jaw Worm always opens Chomp
    assert after["enemies"][0]["previous_intent"] == "ATTACK"


def test_enemy_powers_are_exported_generically():
    """A non-Ritual power must still surface: Lagavulin gives itself Metallicize."""
    env = pilot("DEFEND_RED", encounter="LAGAVULIN", hp=200)
    powers = set()
    for _ in range(12):
        obs = env.observe()
        powers |= {p["id"] for p in obs["powers"]}
        if obs["terminal"]:
            break
        env.step(obs["actions"][0])
    assert "METALLICIZE" in powers, f"Lagavulin's Metallicize was not exported: {powers}"


def test_intent_table_matches_its_generator():
    """The generated table must not drift from the derivation it came from."""
    import subprocess
    result = subprocess.run([__import__("sys").executable, "scripts/gen_intent_table.py", "--verify"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_supported_move_has_an_audited_public_intent():
    """A move with no mapping raises rather than defaulting to a class."""
    import csv
    from pathlib import Path as _P
    rows = list(csv.DictReader((ROOT / "input/intent_mapping.csv").open(encoding="utf-8")))
    assert rows, "the mapping must not be empty"
    for row in rows:
        assert row["public_intent"], row
        assert row["source"], row
        assert row["game_differential_verified"] == "False"
        assert row["evidence_level"] in ("ENGINE_DERIVED_ONLY", "UI_SOURCE_VERIFIED",
                                         "ORIGINAL_GAME_VERIFIED")
        # never claim original-game verification without the game
        assert row["evidence_level"] != "ORIGINAL_GAME_VERIFIED"
        if row["public_intent"] == "UNKNOWN":
            assert row["unknown_kind"] in ("GAME_SHOWS_UNKNOWN", "MAPPING_NOT_KNOWN"), row


def test_the_field_audit_does_not_decide_categories_by_scan():
    """A collision scan is coverage, never a pass criterion."""
    import json as _json
    audit = _json.loads((ROOT / "sampler/field_audit.json").read_text(encoding="utf-8"))
    assert "COVERAGE STATISTIC ONLY" in audit["coverage_scan"]["role"]
    assert audit["incomplete_evidence"], "the audit must keep an incomplete-evidence bucket"
    required = {"monster", "field", "init_write", "future_read", "visibility",
                "category", "grounds", "test"}
    for field in audit["fields"]:
        assert required <= set(field), f"field entry is missing {required - set(field)}: {field}"
        assert field["category"] in ("PUBLIC_DETERMINED", "RESAMPLED", "UNSUPPORTED")
        if field["category"] == "RESAMPLED":
            assert field.get("approximation"), "a resampled field must name its approximation"
    determined = [f for f in audit["fields"] if f["category"] == "PUBLIC_DETERMINED"]
    assert determined, "the audit would be vacuous without any determined field"


def test_the_louse_field_is_audited_as_resampled():
    """The field the review found unlisted must now be present and honest."""
    import json as _json
    audit = _json.loads((ROOT / "sampler/field_audit.json").read_text(encoding="utf-8"))
    louse = [f for f in audit["fields"] if "LOUSE" in f["monster"]]
    assert louse, "the louse miscInfo entry must exist"
    assert louse[0]["category"] == "RESAMPLED"
    assert "miscInfo" in louse[0]["field"]


def test_the_engine_lock_declares_exactly_the_patches_on_disk():
    """A lock that under-declares the patch series makes builds misreport provenance.

    The patch files are committed independently of the lock, so a missing lock
    update leaves a checkout that applies three patches while build_info claims
    two. The two must agree.
    """
    import hashlib as _hashlib
    import json as _json
    root = Path(__file__).resolve().parents[1]
    lock = _json.loads((root / "engine_lock.json").read_text(encoding="utf-8"))
    on_disk = sorted(p.name for p in (root / "native" / "patches").glob("*.patch"))
    declared = sorted(Path(p["file"]).name for p in lock.get("patches", []))
    assert on_disk == declared, f"disk {on_disk} vs lock {declared}"
    for entry in lock["patches"]:
        path = root / entry["file"]
        assert _hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["file"]
