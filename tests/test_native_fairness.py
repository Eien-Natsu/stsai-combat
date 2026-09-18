"""Sampling-fairness and public-information audit for the native adapter.

"Sampling did not move the root observation" is not evidence that sampling
ignores hidden state, so these tests vary the hidden state directly and check
that the belief distribution follows the public history alone.

Skips only when the native extension is not compiled. A skip is not a pass.
"""
import pytest

pytest.importorskip("stsai._lightspeed", reason="Native extension not compiled in this environment")
from stsai.native import NativeBattle
from stsai.contracts import validate_public, observation_key

pytestmark = pytest.mark.native

SCENARIO = {"deck": ["STRIKE_RED"] * 5 + ["DEFEND_RED"] * 4 + ["BASH", "ASCENDERS_BANE"],
            "encounter": "CULTIST", "ascension": 20, "hp": 55, "max_hp": 80,
            "floor": 1, "act": 1, "potions": []}
SAMPLER_SEEDS = [0, 7, 12345, 2 ** 40 - 1]


def key(env):
    return observation_key(env.observe())


def rollout_key(env, actions, sampler_seed):
    """Public trajectory produced by a sampler copy playing a fixed action list."""
    sim = env.sampler()(sampler_seed)
    trace = []
    for _ in range(actions):
        obs = sim.observe()
        trace.append(observation_key(obs))
        if obs["terminal"]:
            break
        sim.step(obs["actions"][0])
    return trace


def test_same_public_history_different_hidden_draw_order_samples_identically():
    """Canonical coupling: the same public history and sampler seed must agree.

    The adapter canonicalises the unknown draw pile before shuffling, so it
    promises an exact match rather than merely a matching distribution.
    """
    original = NativeBattle(SCENARIO, 11)
    # A copy whose hidden draw order, RNG streams and seed all differ.
    other = original.sampler()(999)
    assert key(original) == key(other), "the copy must preserve the public root"
    for seed in SAMPLER_SEEDS:
        assert key(original.sampler()(seed)) == key(other.sampler()(seed))
        assert rollout_key(original, 6, seed) == rollout_key(other, 6, seed), \
            "identical public history and sampler seed produced different public futures"


def test_every_distinct_hidden_state_shares_one_belief():
    """Several different hidden worlds must induce the same public belief."""
    live = NativeBattle(SCENARIO, 11)
    public_root = key(live)
    hidden_worlds = [live.sampler()(s) for s in (1, 2, 3, 999, 2 ** 41)]
    for world in hidden_worlds:
        assert key(world) == public_root, "a hidden world leaked into its public state"
    for seed in SAMPLER_SEEDS:
        outcomes = {tuple(rollout_key(world, 6, seed)) for world in [live] + hidden_worlds}
        assert len(outcomes) == 1, f"belief depended on the true hidden world for sampler seed {seed}"


def test_hidden_state_never_appears_in_the_observation():
    env = NativeBattle(SCENARIO, 5)
    obs = env.observe()
    validate_public(obs)  # raises on the forbidden name list
    flat = repr(obs)
    for forbidden in ("seed", "rng", "uniqueId", "uuid", "miscInfo"):
        assert forbidden not in flat, f"{forbidden} leaked into the observation"


def test_public_root_check_detects_a_genuine_difference():
    """Guard against the invariance test passing because it compares nothing."""
    a = NativeBattle(SCENARIO, 11)
    b = NativeBattle({**SCENARIO, "hp": 54}, 11)
    assert key(a) != key(b)


# --- sampler lifecycle: what the enemy is holding vs what it has done --------
#
# The adapter exports `previous_move` (already executed) and never the move the
# enemy is holding for the coming turn. These tests fix that ordering: the move
# held at turn N is the move reported at turn N+1, and nothing in between leaks
# the held move.

KNOWN_FIRST_MOVE = {"CULTIST": "CULTIST_INCANTATION", "JAW_WORM": "JAW_WORM_CHOMP"}
KNOWN_FIRST_INTENT = {"CULTIST": "BUFF", "JAW_WORM": "ATTACK"}

# Keys the adapter is allowed to expose per enemy. Any planned-move field would
# have to appear here to reach the model, so this doubles as the leak guard.
PUBLIC_ENEMY_KEYS = frozenset({
    "id", "slot", "hp", "max_hp", "block", "strength", "weak", "vulnerable",
    "artifact", "half_dead", "intent_damage", "hits", "intent", "previous_move",
})


def turn_one_then_two(encounter):
    env = NativeBattle({**SCENARIO, "encounter": encounter}, 4)
    first = env.observe()
    second = env.step(next(a for a in first["actions"] if a["kind"] == "end"))
    return first, second


def test_previous_move_at_turn_two_is_the_move_executed_in_turn_one():
    """The move held at turn N is reported at turn N+1 as executed."""
    for encounter, held in KNOWN_FIRST_MOVE.items():
        first, second = turn_one_then_two(encounter)
        # Turns are 0-indexed in the observation; assert the transition, not a
        # literal, so a renumbering does not silently invalidate the test.
        assert second["turn"] == first["turn"] + 1
        assert first["enemies"][0]["intent"] == KNOWN_FIRST_INTENT[encounter]
        assert second["enemies"][0]["previous_move"] == held, \
            f"{encounter}: turn 2 must report the turn 1 move, got {second['enemies'][0]['previous_move']}"


def test_no_enemy_field_can_carry_a_held_move():
    """The exported key set is exactly the public set: no held-move channel."""
    for encounter in KNOWN_FIRST_MOVE:
        first, _ = turn_one_then_two(encounter)
        keys = set(first["enemies"][0])
        assert keys == set(PUBLIC_ENEMY_KEYS), \
            f"{encounter}: unexpected enemy fields {keys ^ set(PUBLIC_ENEMY_KEYS)}"
        assert "observed_move" not in keys


def test_previous_move_only_ever_reports_an_executed_move():
    """Across a whole fight the reported move is never the one still to come.

    A held move would surface one turn early. Checking that `previous_move` is
    stable within a turn, and that the turn-N intent matches the move reported
    at turn N+1, rules that out without needing to read the held move itself.
    """
    seen = {}
    for encounter in KNOWN_FIRST_MOVE:
        env = NativeBattle({**SCENARIO, "encounter": encounter}, 9)
        obs = env.observe()
        for _ in range(12):
            if obs["terminal"]:
                break
            enemy = obs["enemies"][0]
            held_intent = enemy["intent"]
            before = enemy["previous_move"]
            after = env.step(next(a for a in obs["actions"] if a["kind"] == "end"))
            resolved = after["enemies"][0]["previous_move"]
            if resolved != before:
                # The move that just resolved was the one held during last turn.
                assert resolved not in seen or seen[resolved] == held_intent, \
                    f"{resolved} appeared under two different intents"
                seen[resolved] = held_intent
            obs = after
    assert len(seen) >= 3, f"expected several distinct moves, saw {seen}"


def test_sampling_preserves_the_executed_history():
    """A belief sample must not rewrite what already happened."""
    env = NativeBattle({**SCENARIO, "encounter": "JAW_WORM"}, 9)
    env.step(next(a for a in env.observe()["actions"] if a["kind"] == "end"))
    live = env.observe()
    for seed in (0, 5, 999):
        copy = env.sampler()(seed).observe()
        assert copy["enemies"][0]["previous_move"] == live["enemies"][0]["previous_move"]
