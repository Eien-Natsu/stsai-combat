"""Counterfactual tests for the louse's construction-time hidden attack base.

`Monster::construct` (Monster.cpp:118-120) rolls the louse's base attack into
`miscInfo` at spawn, and the two BITE moves attack with it
(MonsterSpecific.cpp:745, :1006). Until the louse shows an attack, the player
cannot see that number. The pre-fix sampler copied `miscInfo` verbatim, so a
search rollout was conditioned on a value the player did not have.

Each test below states which side of that line it is on: CURRENT_CODE_RUN for
the fixed sampler, OLD_VERSION_NEGATIVE_CONTROL_RUN for the hook that reproduces
the pre-fix behaviour, SOURCE_ARGUMENT_ONLY where only the upstream source is
cited. No test asserts anything from an expected string.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("stsai._lightspeed", reason="Native extension not compiled in this environment")
from stsai.contracts import observation_key, validate_public
from stsai.native import NativeBattle
from stsai.scenarios import make_scenario

pytestmark = pytest.mark.native

SCENARIO = {"deck": ["DEFEND_RED"] * 10, "encounter": "TWO_LOUSE", "ascension": 20,
            "hp": 80, "max_hp": 80, "floor": 1, "act": 1, "potions": []}
# A20: Monster.cpp:118 rolls the louse base uniformly over this closed range.
PUBLIC_PRIOR = (6, 8)


def internals(env):
    return env._handle.debug_internals()


def end_turn(obs):
    return next(a for a in obs["actions"] if a["kind"] == "end")


def louse_roots():
    """Reachable roots where a louse is holding a non-attack, so its base is hidden."""
    found = []
    for index in range(12):
        scenario, episode_seed, _ = make_scenario("lightspeed_pilot", "val", index)
        env = NativeBattle({**SCENARIO, **{k: v for k, v in scenario.items() if k == "deck"}},
                           episode_seed)
        obs = env.observe()
        info = internals(env)
        for slot, enemy in enumerate(obs["enemies"]):
            if enemy["id"].endswith("LOUSE") and enemy["intent"] != "ATTACK":
                found.append((index, episode_seed, slot, enemy["id"],
                              info["true_attack_bases"][slot]))
    return found


def build(episode_seed, deck):
    return NativeBattle({**SCENARIO, "deck": list(deck)}, episode_seed)


def rollout(sim, steps=10):
    """Public trace under a fixed action script, so branches differ only in state."""
    trace = []
    for _ in range(steps):
        obs = sim.observe()
        trace.append(observation_key(obs))
        if obs["terminal"]:
            break
        sim.step(end_turn(obs))
    return trace


# --- the value really is hidden, and becomes public when shown --------------

def test_the_base_range_is_public_and_the_true_value_is_not():
    roots = louse_roots()
    assert roots, "no reachable non-attack louse root to test against"
    for index, episode_seed, slot, monster, true_base in roots[:6]:
        scenario, _, _ = make_scenario("lightspeed_pilot", "val", index)
        env = NativeBattle({**SCENARIO, "deck": scenario["deck"]}, episode_seed)
        obs = env.observe()
        enemy = obs["enemies"][slot]
        assert (enemy["attack_base_low"], enemy["attack_base_high"]) == PUBLIC_PRIOR, \
            "before any attack the player only knows the spawn range"
        assert PUBLIC_PRIOR[0] <= true_base <= PUBLIC_PRIOR[1]
        assert true_base not in (enemy["intent_damage"],), \
            "a non-attack turn must not display the base"


def test_an_attack_display_pins_the_base():
    """Once the louse attacks, the shown number plus visible modifiers fix it."""
    roots = louse_roots()
    assert roots
    index, episode_seed, slot, monster, true_base = roots[0]
    scenario, _, _ = make_scenario("lightspeed_pilot", "val", index)
    env = NativeBattle({**SCENARIO, "deck": scenario["deck"]}, episode_seed)
    obs = env.observe()
    for _ in range(12):
        if obs["terminal"]:
            break
        obs = env.step(end_turn(obs))
        enemy = obs["enemies"][slot]
        if enemy["intent"] == "ATTACK":
            # no strength, no vulnerable/weak on either side in this fixture
            assert enemy["attack_base_low"] == enemy["attack_base_high"] == enemy["intent_damage"]
            break
    else:
        pytest.fail("the louse never attacked inside the fixture budget")


# --- the counterfactual ------------------------------------------------------

def test_two_roots_same_public_history_different_hidden_base_agree_under_the_fixed_sampler():
    """CURRENT_CODE_RUN: the fixed sampler must not depend on the true base."""
    roots = louse_roots()
    assert roots
    index, episode_seed, slot, monster, true_base = roots[0]
    scenario, _, _ = make_scenario("lightspeed_pilot", "val", index)

    low, high = PUBLIC_PRIOR
    a = build(episode_seed, scenario["deck"]); a._handle.debug_set_attack_base(slot, low)
    b = build(episode_seed, scenario["deck"]); b._handle.debug_set_attack_base(slot, high)

    assert observation_key(a.observe()) == observation_key(b.observe()), \
        "the two roots must be indistinguishable from public information alone"
    validate_public(a.observe())

    for sampler_seed in (0, 1, 7, 4242, 2 ** 40 + 3):
        left = rollout(a.sampler()(sampler_seed))
        right = rollout(b.sampler()(sampler_seed))
        assert left == right, f"belief depended on the hidden base for sampler seed {sampler_seed}"


def test_negative_control_the_prefix_sampler_exposes_the_dependency():
    """OLD_VERSION_NEGATIVE_CONTROL_RUN.

    The same pair under the pre-fix sampler semantics (hidden base copied
    verbatim) must diverge, otherwise the counterfactual above would be vacuous
    and would not be testing anything.
    """
    roots = louse_roots()
    assert roots
    index, episode_seed, slot, monster, true_base = roots[0]
    scenario, _, _ = make_scenario("lightspeed_pilot", "val", index)
    low, high = PUBLIC_PRIOR
    if low == high:
        pytest.skip("prior is a single value; the dependency cannot be shown")

    a = build(episode_seed, scenario["deck"]); a._handle.debug_set_attack_base(slot, low)
    b = build(episode_seed, scenario["deck"]); b._handle.debug_set_attack_base(slot, high)

    diverged = False
    for sampler_seed in (0, 1, 7, 4242, 2 ** 40 + 3):
        left = rollout(_wrap(a._handle.debug_sample_with_true_base(sampler_seed)))
        right = rollout(_wrap(b._handle.debug_sample_with_true_base(sampler_seed)))
        if left != right:
            diverged = True
            break
    assert diverged, "the hidden base never influenced the pre-fix rollout; the pair is not a counterfactual"


def _wrap(handle):
    instance = NativeBattle.__new__(NativeBattle)
    instance._handle = handle
    return instance


# --- knowledge is kept, and ambiguity is kept ---------------------------------

def test_a_pinned_base_is_not_re_randomised():
    """Once public history determines the value, sampling keeps it."""
    roots = louse_roots()
    assert roots
    index, episode_seed, slot, monster, true_base = roots[0]
    scenario, _, _ = make_scenario("lightspeed_pilot", "val", index)
    env = build(episode_seed, scenario["deck"])
    obs = env.observe()
    for _ in range(12):
        if obs["terminal"]:
            break
        obs = env.step(end_turn(obs))
        if obs["enemies"][slot]["intent"] == "ATTACK":
            break
    pinned = obs["enemies"][slot]["attack_base_low"]
    assert pinned == obs["enemies"][slot]["attack_base_high"] == obs["enemies"][slot]["intent_damage"]
    for sampler_seed in (0, 3, 99):
        copy = env.sampler()(sampler_seed)
        info = internals(copy)
        assert info["true_attack_bases"][slot] == pinned, \
            "a publicly known base must survive sampling rather than be redrawn"


# The weak ambiguity test that used to live here passed even when the interval
# never widened, so it proved nothing about the branch. It is superseded by
# tests/test_ambiguity_regression.py, which drives a real zeroed display to -9
# strength and checks the whole declared prior stays reachable.
