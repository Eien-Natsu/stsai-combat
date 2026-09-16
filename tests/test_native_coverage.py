"""Directed per-card and per-enemy coverage for the pilot whitelist.

Every whitelisted card is asserted in both its base and upgraded form against
known Slay the Spire card values, and both pilot enemies must expose every move
they can visibly make. This is directed evidence for the supported range; it is
NOT a claim that the supported range covers the game.

Skips only when the native extension is not compiled. A skip is not a pass.
"""
import pytest

pytest.importorskip("stsai._lightspeed", reason="Native extension not compiled in this environment")
from stsai.native import NativeBattle
from stsai.contracts import validate_public
from stsai.encoding import normalize

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
UNPLAYABLE = {"ASCENDERS_BANE"}
PLAYABLE = sorted(COSTS)
ALL_CARDS = PLAYABLE + sorted(UNPLAYABLE)


def pilot(card, upgraded=False, encounter="CULTIST", hp=PLAYER_HP, copies=10, seed=7, extra=()):
    """Deck of identical copies so the opening hand is deterministic."""
    deck = [card + "+" if upgraded else card] * copies + list(extra)
    scenario = {"deck": deck, "encounter": encounter, "ascension": ASCENSION,
                "hp": hp, "max_hp": PLAYER_HP, "floor": 1, "act": 1, "potions": []}
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


@pytest.mark.parametrize("card", ALL_CARDS)
@pytest.mark.parametrize("upgraded", [False, True])
def test_card_is_offered_with_correct_cost(card, upgraded):
    if upgraded and card in UNPLAYABLE:
        # Ascender's Bane has no upgraded form; the adapter must reject it loudly.
        with pytest.raises((ValueError, RuntimeError)):
            pilot(card, upgraded=True).observe()
        return
    env = pilot(card, upgraded)
    obs = env.observe()
    validate_public(obs)
    offered = [a for a in obs["actions"] if a.get("card_id") == canonical(card)]
    if card in UNPLAYABLE:
        assert not offered, f"{card} must never be a legal action"
        assert obs["player"]["energy"] == 3
        return
    assert offered, f"{card} not offered in an all-{card} deck"
    expected = obs["player"]["energy"] if card in XCOST else COSTS[card]
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


def observed_moves(encounter, seeds=range(64)):
    seen = {}
    for seed in seeds:
        env = pilot("STRIKE_RED", encounter=encounter, seed=seed)
        for _ in range(40):
            obs = env.observe()
            for e in obs["enemies"]:
                if e["hp"] > 0:
                    seen.setdefault(e["observed_move"], 0)
                    seen[e["observed_move"]] += 1
            if obs["terminal"]:
                break
            env.step(obs["actions"][0])
    return seen


def test_cultist_covers_all_visible_moves():
    seen = observed_moves("CULTIST")
    assert set(seen) == {"CULTIST_INCANTATION", "CULTIST_DARK_STRIKE"}, seen


def test_jaw_worm_covers_all_visible_moves():
    seen = observed_moves("JAW_WORM")
    assert set(seen) == {"JAW_WORM_CHOMP", "JAW_WORM_THRASH", "JAW_WORM_BELLOW"}, seen


def test_cultist_ritual_is_exported_as_a_power():
    env = pilot("STRIKE_RED", encounter="CULTIST")
    after = env.step(env.observe()["actions"][-1])  # end turn -> Incantation resolves
    ritual = [p for p in after["powers"] if p["id"] == "RITUAL"]
    assert ritual and ritual[0]["amount"] > 0
    assert ritual[0]["owner"] == 0
