import copy
import numpy as np
import pytest
import torch
from stsai.search import BeliefSearch,SearchConfig
from stsai.encoding import encode,collate_encoded,normalize
from stsai.model import CombatNet,ModelConfig,resolve_device
from stsai.objective import terminal_utility,outcome_target

def test_search_valid_visits(battle):
 o=battle.observe();r=BeliefSearch(SearchConfig(simulations=12,rollout_limit=16)).run(o,battle.sampler(),4)
 assert r['action'] in o['actions'];assert sum(r['visits'])==r['simulations'];assert min(r['visits'])>=1
 assert abs(sum(r['policy'])-1)<1e-8;assert np.isfinite(r['q']).all()
def test_search_takes_forced_lethal(battle):
 battle.player['hp']=1;battle.player['energy']=1;battle.enemies[0]['hp']=6
 from stsai.reference import Card
 battle.hand=[Card('STRIKE')]
 r=BeliefSearch(SearchConfig(simulations=24,rollout_limit=8)).run(battle.observe(),battle.sampler(),3)
 assert r['action']['card_id']=='STRIKE'
def test_search_does_not_mutate_live(battle):
 before=battle.observe();BeliefSearch(SearchConfig(simulations=4,rollout_limit=8)).run(before,battle.sampler())
 assert battle.observe()==before
def test_masked_network_backward(battle):
 torch.set_num_threads(2);a=battle.observe();b=copy.deepcopy(a);b['actions']=b['actions'][:1]
 batch=collate_encoded([encode(a),encode(b)]);model=CombatNet(ModelConfig(d_model=48,layers=1,heads=4))
 out=model(batch);p=out['policy_logits'].softmax(-1)
 assert torch.isfinite(out['value']).all();assert torch.allclose(p.sum(-1),torch.ones(2))
 assert torch.equal(p[1,1:],torch.zeros_like(p[1,1:]));assert out['outcome_logits'].shape==(2,11)
 loss=out['value'].sum()+out['policy_logits'][0,0];loss.backward()
 assert all(torch.isfinite(x.grad).all() for x in model.parameters() if x.grad is not None)
def test_no_entity_or_action_truncation(battle):
 with pytest.raises(ValueError,match='Entity'):encode(battle.observe(),max_entities=1)
 with pytest.raises(ValueError,match='Action'):encode(battle.observe(),max_actions=1)
@pytest.mark.parametrize('source,target',[('Strike_R','STRIKE'),('Shrug It Off','SHRUG_IT_OFF'),('AscendersBane','ASCENDERS_BANE'),('JawWorm','JAW_WORM')])
def test_name_normalization(source,target):assert normalize(source)==target
def test_censored_outcome_not_death(battle):
 assert sum(outcome_target(battle.observe()))==0
 with pytest.raises(ValueError):terminal_utility(battle.observe())
def test_terminal_utility_and_distribution(battle):
 o=battle.observe();o.update(terminal=True,won=True,actions=[]);o['player']['hp']=40
 assert abs(terminal_utility(o)-.9)<1e-7;assert abs(sum(outcome_target(o))-1)<1e-7
 o['won']=False;assert terminal_utility(o)==0;assert outcome_target(o)[0]==1
def test_explicit_cuda_never_silent_cpu(monkeypatch):
 monkeypatch.setattr(torch.cuda,'is_available',lambda:False)
 with pytest.raises(RuntimeError):resolve_device('cuda')

def test_encoder_enforces_firewall(battle):
 o=battle.observe();o['rng_state']=[1,2,3]
 with pytest.raises(ValueError,match='Hidden'):encode(o)
