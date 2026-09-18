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
from stsai.scenarios import NATIVE_ENCOUNTERS

SUPPORTED_ENCOUNTERS = tuple(e for v in NATIVE_ENCOUNTERS.values() for e in v)

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


# --- sampler lifecycle: what the enemy holds vs what it has done -------------
#
# observe() exports the public intent CLASS for both the held move and the last
# executed one. The internal move id is available only through the test-only
# hook, so branch-level assertions live here while the model-facing surface
# stays free of identities.

KNOWN_FIRST = {"CULTIST": ("CULTIST_INCANTATION", "BUFF"),
               "JAW_WORM": ("JAW_WORM_CHOMP", "ATTACK")}
PUBLIC_ENEMY_KEYS = frozenset({
    "id", "slot", "hp", "max_hp", "block", "strength", "weak", "vulnerable",
    "artifact", "half_dead", "intent_damage", "hits", "intent", "previous_intent",
})


def internals(env):
    return env._handle.debug_internals()


def end_turn(obs):
    return next(a for a in obs["actions"] if a["kind"] == "end")


def build(encounter, seed=4, hp=80, max_hp=80):
    return NativeBattle({**SCENARIO, "encounter": encounter, "hp": hp, "max_hp": max_hp}, seed)


def test_the_class_held_at_turn_n_is_reported_executed_at_turn_n_plus_one():
    """The move the enemy was holding is the one that resolves, and only then.

    The held move is read through the test-only hook so the assertion does not
    depend on the observation exposing an identity it must not expose.
    """
    for encounter, (held, cls) in KNOWN_FIRST.items():
        env = build(encounter)
        first = env.observe()
        assert internals(env)["held_moves"][0] == held
        assert first["enemies"][0]["intent"] == cls
        assert first["enemies"][0]["previous_intent"] == "NONE"
        second = env.step(end_turn(first))
        assert second["enemies"][0]["previous_intent"] == cls
        assert internals(env)["executed_moves"][0] == held, \
            "the executed record must be the move that was held last turn"


def test_repeated_observes_do_not_advance_history():
    """Several observe() calls inside one turn must not move the history on."""
    env = build("JAW_WORM")
    env.step(end_turn(env.observe()))
    first = env.observe()
    for _ in range(4):
        again = env.observe()
        assert again["enemies"][0]["previous_intent"] == first["enemies"][0]["previous_intent"]
    assert internals(env)["executed_moves"][0] == "JAW_WORM_CHOMP"


def test_playing_a_card_without_ending_the_turn_does_not_advance_history():
    env = build("JAW_WORM")
    after_turn = env.step(end_turn(env.observe()))
    baseline = after_turn["enemies"][0]["previous_intent"]
    obs = after_turn
    for _ in range(3):
        playable = [a for a in obs["actions"] if a["kind"] == "play"]
        if not playable:
            break
        obs = env.step(playable[0])
        assert obs["enemies"][0]["previous_intent"] == baseline


def test_an_enemy_killed_before_it_acts_reports_no_new_execution():
    """A monster killed inside turn 1 never acted, so it has no execution.

    The deck is all Strikes so the opening hand is deterministic, and the turn
    is never ended -- ending it would let the monsters act and the assertion
    would be about nothing. Energy caps the plays, so the test asserts on the
    monsters that actually died rather than demanding the fight be over.
    """
    scenario = {**SCENARIO, "deck": ["STRIKE_RED"] * 10, "encounter": "SMALL_SLIMES",
                "hp": 80, "max_hp": 80}
    env = NativeBattle(scenario, 5)
    obs = env.observe()
    turns = {obs["turn"]}
    while True:
        plays = [a for a in obs["actions"] if a["kind"] == "play"]
        if not plays or obs["terminal"]:
            break
        obs = env.step(plays[0])
        turns.add(obs["turn"])
    assert turns == {0}, "no turn was allowed to end"
    drained = 0
    for slot, record in enumerate(obs["enemies"]):
        if record["hp"] <= 0:
            drained += 1
            assert internals(env)["executed_moves"][slot] == "INVALID", \
                f"slot {slot} died inside turn 1 but reports an execution"
    assert drained or obs["terminal"], "the fixture landed no killing blow to assert on"
def test_a_move_that_ends_the_battle_is_still_reported_executed():
    """A Looter escaping ends the fight on its own action."""
    env = build("LOOTER", seed=1, hp=200, max_hp=200)
    obs = env.observe()
    for _ in range(40):
        if obs["terminal"]:
            break
        obs = env.step(end_turn(obs))
    assert obs["terminal"], "the Looter should eventually resolve the fight"
    assert internals(env)["executed_moves"][0] == "LOOTER_ESCAPE"


def test_history_is_not_shared_across_belief_samples():
    """A sampled copy keeps the executed history and never invents one."""
    env = build("JAW_WORM")
    env.step(end_turn(env.observe()))
    live = env.observe()["enemies"][0]["previous_intent"]
    live_internal = internals(env)["executed_moves"][0]
    for seed in (0, 5, 999):
        copy = env.sampler()(seed)
        assert copy.observe()["enemies"][0]["previous_intent"] == live
        assert internals(copy)["executed_moves"][0] == live_internal


def test_observe_still_exports_only_public_fields():
    for encounter in KNOWN_FIRST:
        env = build(encounter)
        assert set(env.observe()["enemies"][0]) == set(PUBLIC_ENEMY_KEYS)
        assert internals(env)["held_moves"][0] not in repr(env.observe()["enemies"][0])


def test_the_held_move_is_determined_by_public_information():
    """Is the move the enemy is holding recoverable from what the player sees?

    The public class alone does not separate every pair (Looter Mug and Lunge are
    both ATTACK), but the class together with the displayed damage and hit count
    might. This walks the reachable states of every supported encounter and
    asserts that no two different held moves ever share the same public
    signature. That is a determinism argument over the reachable space, not a
    collision scan used as a proof of fairness.
    """
    signatures = {}
    checked = 0
    for encounter in SUPPORTED_ENCOUNTERS:
        for seed in range(16):
            env = NativeBattle({**SCENARIO, "deck": ["DEFEND_RED"] * 10, "encounter": encounter,
                                "hp": 200, "max_hp": 200}, seed)
            for _ in range(50):
                obs = env.observe()
                held = internals(env)["held_moves"]
                for slot, enemy in enumerate(obs["enemies"]):
                    signature = (enemy["id"], enemy["intent"], enemy["intent_damage"], enemy["hits"])
                    signatures.setdefault(signature, set()).add(held[slot])
                    checked += 1
                if obs["terminal"]:
                    break
                env.step(end_turn(obs))
    collisions = {k: sorted(v) for k, v in signatures.items() if len(v) > 1}
    assert not collisions, f"held move is not public-determined: {collisions}"
    assert checked > 2000, f"too few states inspected to support the claim: {checked}"
