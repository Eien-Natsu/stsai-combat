from __future__ import annotations
from .contracts import validate_public
from .hints import enrich

# Belief model of the native adapter. It resamples every RNG stream
# independently and draws construction-time hidden attack bases from the
# candidate set public history allows; it is NOT the original game's
# correlated posterior and does not claim to be.
SAMPLER_REVISION = "public_history_candidate_sampling/2"

# First native compilation and game differential testing must be performed on
# the target machine. Import failure does NOT fall back to the reference engine.
def _module():
    try:
        from . import _lightspeed
    except ImportError as exc:
        raise RuntimeError("Native engine missing. Run scripts/fetch_engine.py and scripts/build_native.py; see docs/04_NATIVE.md") from exc
    return _lightspeed

def engine_metadata(): return dict(_module().build_info())

class NativeBattle:
    def __init__(self,scenario,seed): self._handle=_module().PilotBattle(scenario,int(seed))
    @classmethod
    def _wrap(cls,handle):
        instance=cls.__new__(cls);instance._handle=handle;return instance
    def observe(self):
        obs=enrich(self._handle.observe());validate_public(obs);return obs
    def step(self,action):
        obs=enrich(self._handle.step(str(action["id"])));validate_public(obs);return obs
    def sampler(self):
        # A narrow capability: evaluator/search have no field access to bc/RNG.
        # Copies retain already-observed monster history; future streams and
        # unknown deck order are independently resampled by the native adapter.
        handle=self._handle
        return lambda seed: NativeBattle._wrap(handle.sample(int(seed)))
