import copy,random
import numpy as np
import pytest
from stsai.contracts import validate_public,observation_key,FORBIDDEN
from stsai.search import BeliefSearch,SearchConfig
from stsai.reference import ReferenceBattle,Card
from stsai.encoding import encode
@pytest.mark.parametrize('key',sorted(FORBIDDEN))
def test_forbidden_keys_rejected(battle,key):
 o=battle.observe();o['nested']={'deeper':[{key:123}]}
 with pytest.raises(ValueError,match='Hidden'):validate_public(o)
def test_hidden_order_not_observable(battle):
 other=copy.deepcopy(battle);other._draw.reverse();other._rng=random.Random(987)
 assert battle.observe()==other.observe()
 assert np.array_equal(encode(battle.observe()).features,encode(other.observe()).features)
def test_root_sampling_matches_public(battle):
 before=battle.observe()
 for seed in range(20):assert battle.sampler()(seed).observe()==before
 assert battle.observe()==before
def test_samples_vary_future_not_root(battle):
 outcomes=set()
 for seed in range(30):
  sample=battle.sampler()(seed);outcomes.add(tuple(c.id for c in sample._draw))
 assert len(outcomes)>1
 assert len({observation_key(battle.sampler()(seed).observe()) for seed in range(8)})==1
def test_known_top_respected(battle):
 battle._known_top=[battle._draw[-1]];obs=battle.observe()
 for seed in range(10):
  s=ReferenceBattle.from_observation(obs,seed);assert s.observe()==obs
  expected=s._known_top[0];s._draw_cards(1);assert s.hand[-1]==expected
  assert not s._known_top
def test_search_invariant_to_actual_hidden_rng_and_order(battle):
 other=copy.deepcopy(battle);other._draw.reverse();other._rng=random.Random(999999)
 search=BeliefSearch(SearchConfig(simulations=12,rollout_limit=16,max_depth=8))
 a=search.run(battle.observe(),battle.sampler(),7);b=search.run(other.observe(),other.sampler(),7)
 assert a['visits']==b['visits'];assert a['q']==b['q'];assert a['action']==b['action']
def test_sampler_rejects_changed_public_root(battle):
 obs=battle.observe()
 def bad(seed):
  sample=battle.sampler()(seed);sample.player['hp']-=1;return sample
 with pytest.raises(RuntimeError,match='public root'):BeliefSearch(SearchConfig(simulations=2)).run(obs,bad)
def test_noncanonical_draw_rejected(battle):
 o=battle.observe();o['draw_pile'].reverse()
 with pytest.raises(ValueError,match='canonical'):validate_public(o)
def test_duplicate_action_rejected(battle):
 o=battle.observe();o['actions'].append(o['actions'][0])
 with pytest.raises(ValueError,match='Duplicate'):validate_public(o)
