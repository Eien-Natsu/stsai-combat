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
