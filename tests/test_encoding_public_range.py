"""Features 13/14/15 carry the public attack-base interval into the encoder.

A monster whose base attack is rolled at spawn (the louse) has a public
*interval*, not a public value: the spawn range is known, an attack display
narrows it, and the true value never enters an observation. The four legal
field states are [6,8] before anything is shown, [6,7] and [7,7] once a display
brackets it, and "this monster has no such parameter at all". States that carry
different information must produce different network inputs, and the encoding
must be the declared normalization rather than something merely distinct.

"Not applicable" is spelled `attack_base_low == -1`, never a missing key:
`validate_public` refuses a native observation that omits the field, so an
adapter that forgot to export the memory cannot pass as one that did.
"""
import copy
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.contracts import validate_public
from stsai.encoding import encode, normalize, token_id
from stsai.util import SCHEMA_VERSION


def observation(backend="lightspeed_pilot", **enemy):
    """A minimal valid observation with one enemy slot."""
    fields = {"id": "GREEN_LOUSE", "slot": 0, "hp": 12, "max_hp": 16, "block": 0,
              "strength": 0, "weak": 0, "vulnerable": 0, "artifact": 0, "half_dead": False,
              "intent": "ATTACK", "intent_damage": 7, "hits": 1, "previous_intent": "NONE"}
    fields.update(enemy)
    return {"schema_version": SCHEMA_VERSION, "backend": backend, "turn": 1,
            "phase": "PLAYER_NORMAL", "ascension": 20,
            "player": {"hp": 70, "max_hp": 80, "block": 0, "energy": 3},
            "enemies": [fields], "hand": [], "draw_pile": [], "discard_pile": [],
            "exhaust_pile": [], "known_top": [], "potions": [], "potions_used": 0,
            "powers": [], "relics": [], "terminal": False, "won": False,
            "actions": [{"id": "end", "kind": "end"}]}


def enemy_row(obs):
    """The encoder row for the enemy, found by its token, not by a fixed index."""
    encoded = encode(obs)
    wanted = token_id("enemies:" + normalize(obs["enemies"][0]["id"]))
    index = list(encoded.ids).index(wanted)
    return encoded, encoded.features[index]


STATES = {
    "spawn_range": (6, 8),      # nothing shown yet: the whole spawn range
    "narrowed": (6, 7),         # a display that still admits two candidates
    "pinned": (7, 7),           # a display that fixes it
    "not_applicable": (-1, -1),  # this monster has no such parameter
}


def test_every_legal_field_state_has_its_own_normalized_encoding():
    rows = {}
    for name, (low, high) in STATES.items():
        _, row = enemy_row(observation(attack_base_low=low, attack_base_high=high))
        applies = 0.0 if low < 0 else 1.0
        assert row[13] == applies, f"{name}: applicability flag {row[13]} != {applies}"
        assert row[14] == pytest.approx((low if applies else 0.0) / 10)
        assert row[15] == pytest.approx((high if applies else 0.0) / 10)
        rows[name] = row

    names = sorted(rows)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            assert not np.array_equal(rows[left], rows[right]), \
                f"{left} and {right} carry different information but encode identically"


def test_not_applicable_is_not_the_same_input_as_a_known_zero():
    """The flag exists so "no parameter" never collapses onto "the value is 0"."""
    _, absent = enemy_row(observation(attack_base_low=-1, attack_base_high=-1))
    _, zero = enemy_row(observation(attack_base_low=0, attack_base_high=0))
    assert absent[13] == 0.0 and zero[13] == 1.0
    assert absent[14] == zero[14] == absent[15] == zero[15] == 0.0
    assert not np.array_equal(absent, zero)


def test_only_the_public_interval_reaches_the_encoder():
    """Same public state, different true hidden base: byte-identical inputs.

    The two observations below are the ones a player could not tell apart; the
    hidden values they disagree about are not in the observation at all, so the
    encoder has nothing to leak.
    """
    left = observation(attack_base_low=6, attack_base_high=8)
    right = copy.deepcopy(left)
    assert encode(left).features.tobytes() == encode(right).features.tobytes()
    for hidden in ("true_attack_bases", "public_attack_base", "miscInfo", "held_moves",
                   "rng_state", "seed"):
        poisoned = copy.deepcopy(left)
        poisoned["enemies"][0][hidden] = 7
        with pytest.raises(ValueError, match="Hidden"):
            encode(poisoned)


def test_a_native_observation_may_not_omit_the_memory():
    """Absence must not read as "not applicable" on the backend that has it."""
    for missing in ("attack_base_low", "attack_base_high"):
        obs = observation(attack_base_low=6, attack_base_high=8)
        del obs["enemies"][0][missing]
        with pytest.raises(ValueError, match="public attack-base memory"):
            encode(obs)


def test_a_backend_without_the_parameter_declares_it_absent():
    """The reference engine has no such field, and that is not an omission.

    Its default is the explicit not-applicable value the encoder reads, so the
    flag is zero and both interval features stay at zero.
    """
    obs = observation(backend="reference_v1")
    validate_public(obs)  # no field required for a backend that has none
    _, row = enemy_row(obs)
    assert row[13] == 0.0 and row[14] == 0.0 and row[15] == 0.0

    explicit = observation(backend="reference_v1", attack_base_low=-1, attack_base_high=-1)
    assert np.array_equal(row, enemy_row(explicit)[1]), \
        "an omitted field and an explicit not-applicable value must agree on this backend"
