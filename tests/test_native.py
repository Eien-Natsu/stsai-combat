"""Skipped without compiled extension. A skip is NOT a native pass."""
import random
import pytest
native=pytest.importorskip('stsai._lightspeed',reason='Native extension not compiled in this environment')
from stsai.native import NativeBattle,engine_metadata
from stsai.scenarios import make_scenario
from stsai.contracts import validate_public,observation_key
from stsai.search import BeliefSearch,SearchConfig
pytestmark=pytest.mark.native
@pytest.mark.parametrize('index',range(12))
def test_native_playthrough_and_public_root(index):
 scenario,seed,_=make_scenario('lightspeed_pilot','val',index)
 e=NativeBattle(scenario,seed);rng=random.Random(index)
 for _ in range(256):
  o=e.observe();validate_public(o)
  if o['terminal']:return
  for s in [11,39]:assert observation_key(e.sampler()(s).observe())==observation_key(o)
  e.step(rng.choice(o['actions']))
 pytest.fail('Native pilot exceeded 256 actions')
def test_native_search():
 scenario,seed,_=make_scenario('lightspeed_pilot','val',0);e=NativeBattle(scenario,seed);before=e.observe()
 r=BeliefSearch(SearchConfig(simulations=8,rollout_limit=32)).run(before,e.sampler(),12)
 assert r['action'] in before['actions'];assert e.observe()==before
def test_native_rejects_unsupported():
 s,z,_=make_scenario('lightspeed_pilot','val',0);s['deck'].append('TRUE_GRIT')
 with pytest.raises((ValueError,RuntimeError)):NativeBattle(s,z)
def test_native_provenance():
 m=engine_metadata();assert len(m['revision'])==40;assert m['game_differential_verified'] is False
