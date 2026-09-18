"""The reviewer's real ambiguity case, pinned as a regression.

A louse's base attack is hidden until it shows an attack. DISARM+ drives its
strength to -9, which makes the displayed damage floor at 0 for several
candidates at once, so the public interval genuinely cannot collapse. This is
the case the earlier `test_ambiguity_is_kept_when_several_candidates_fit` only
claimed: that test passed with `widened` false, so it never exercised the branch.

The public trace in tests/fixtures/ambiguity_public_trace.json is the reviewer's
own, replayed here rather than restated.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("stsai._lightspeed", reason="Native extension not compiled in this environment")
from stsai.contracts import observation_key, validate_public
from stsai.native import NativeBattle

pytestmark = pytest.mark.native

ROOT = Path(__file__).resolve().parents[1]
TRACE = json.loads((ROOT / "tests/fixtures/ambiguity_public_trace.json").read_text(encoding="utf-8"))


def build():
    return NativeBattle(TRACE["scenario"], TRACE["seed"])


def test_the_reviewers_public_trace_replays():
    env = build()
    for index, expected in enumerate(TRACE["observations"]):
        obs = env.observe()
        assert observation_key(obs) == observation_key(expected), f"diverged at step {index}"
        validate_public(obs)
        if obs["terminal"]:
            break
        if index < len(TRACE["actions"]):
            action = TRACE["actions"][index]
            match = [a for a in obs["actions"] if a["id"] == action["id"]]
            assert match, f"recorded action {action['id']} is not legal at step {index}"
            env.step(match[0])


def test_zeroed_damage_leaves_the_interval_ambiguous():
    """strength reaches -9, the displayed number floors at 0, [6,8] must survive."""
    env = build()
    for index, action in enumerate(TRACE["actions"]):
        obs = env.observe()
        if obs["terminal"]:
            break
        env.step(next(a for a in obs["actions"] if a["id"] == action["id"]))
    obs = env.observe()
    enemy = obs["enemies"][0]
    assert enemy["strength"] == -9, enemy["strength"]
    assert enemy["intent"] == "ATTACK"
    assert enemy["intent_damage"] == 0, "the fixture must drive the display to zero"
    assert (enemy["attack_base_low"], enemy["attack_base_high"]) == (6, 8), \
        "a zeroed display must not be resolved into a unique candidate"
    # and the interval must still be reachable through the sampler
    seen = set()
    root = observation_key(obs)
    for seed in range(1024):
        copy = env.sampler()(seed)
        assert observation_key(copy.observe()) == root, "sampling changed the public root"
        seen.add(copy._handle.debug_internals()["true_attack_bases"][0])
    assert seen <= {6, 7, 8}, f"a sample left the declared prior: {sorted(seen)}"
    assert len(seen) == 3, f"the whole declared prior should still be reachable, saw {sorted(seen)}"


def test_same_turn_plan_change_is_not_recorded_as_an_execution():
    """LICK becomes SPLIT in the same turn; only real executions may be logged."""
    scenario = {"deck": ["STRIKE_RED"] * 10, "encounter": "LARGE_SLIME", "ascension": 20,
                "hp": 200, "max_hp": 200, "floor": 1, "act": 1, "potions": []}
    env = NativeBattle(scenario, 3)
    obs = env.observe()
    for _ in range(40):
        if obs["terminal"]:
            break
        plays = [a for a in obs["actions"] if a["kind"] == "play"]
        obs = env.step(plays[0] if plays else next(a for a in obs["actions"] if a["kind"] == "end"))
        info = env._handle.debug_internals()
        executed = [e for e in info["events"] if e["kind"] == "EXECUTED"]
        # every EXECUTED event must name a move the monster actually held that turn
        for event in executed:
            assert event["move"].startswith("SPIKE_SLIME_L"), event
        spawns = [e for e in info["events"] if e["kind"] == "SPAWNED"
                  and e["move"].startswith(("ACID_SLIME_M", "SPIKE_SLIME_M"))]
        if spawns:
            break
    assert spawns, "the fixture must reach the split"
    # the split was executed once; the plan change before it added nothing
    assert [e["move"] for e in executed].count("SPIKE_SLIME_L_SPLIT") == 1
    assert info["executed_moves"][0] == "INVALID", "the new occupant inherited an execution"
    assert obs["enemies"][0]["previous_intent"] == "NONE"
