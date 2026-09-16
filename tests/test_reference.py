import copy,random
import pytest
from stsai.reference import ReferenceBattle,Card
from stsai.contracts import validate_public,observation_key
from stsai.scenarios import make_scenario,make_env

def action(e,name):return next(a for a in e.observe()['actions'] if a.get('card_id')==name)
def test_attack_energy(battle):
 o=battle.step(action(battle,'STRIKE'));assert o['enemies'][0]['hp']==34;assert o['player']['energy']==2
 assert o['discard_pile'][0]['id']=='STRIKE'
def test_block(battle):
 o=battle.step(action(battle,'DEFEND'));assert o['player']['block']==5;assert o['player']['energy']==2
def test_bash_applies_after_damage(battle):
 o=battle.step(action(battle,'BASH'));assert o['enemies'][0]['hp']==32;assert o['enemies'][0]['vulnerable']==2
 o=battle.step(action(battle,'STRIKE'));assert o['enemies'][0]['hp']==23
def test_forged_damage_ignored(battle):
 a=action(battle,'STRIKE');a['damage']=999999
 assert battle.step(a)['enemies'][0]['hp']==34
def test_illegal_action_is_error(battle):
 with pytest.raises(ValueError):battle.step({'id':'invented:123'})
def test_unaffordable_mask(battle):
 battle.player['energy']=0;assert [a['kind'] for a in battle.observe()['actions']]==['end']
def test_exhaust_and_power(battle):
 battle.hand=[Card('IMPERVIOUS'),Card('INFLAME')]
 battle.step(action(battle,'IMPERVIOUS'));assert [c.id for c in battle.exhaust]==['IMPERVIOUS']
 battle.step(action(battle,'INFLAME'));assert battle.player['strength']==2;assert not battle.discard
 assert all(c.id!='INFLAME' for c in battle.exhaust)
def test_ethereal_at_turn_end(battle):
 battle.hand=[Card('GHOSTLY_ARMOR'),Card('DAZED')]
 battle.step({'id':'end'});assert {c.id for c in battle.exhaust}=={'GHOSTLY_ARMOR','DAZED'}
def test_anger_copy(battle):
 battle.hand=[Card('ANGER')];battle.step(action(battle,'ANGER'));assert len(battle.discard)==2
 assert battle.player['energy']==3
def test_potion_slot_stable(battle):
 battle.potions=['FIRE','BLOCK'];a=next(a for a in battle.observe()['actions'] if a['kind']=='potion' and a['source']==0)
 o=battle.step(a);assert o['potions_used']==1;assert battle.potions==['EMPTY','BLOCK']
 assert all(a['source']==1 for a in o['actions'] if a['kind']=='potion')
def test_death_and_win_terminal(battle):
 battle.enemies[0]['hp']=6;o=battle.step(action(battle,'STRIKE'));assert o['terminal'] and o['won'] and o['actions']==[]
def test_player_death(battle):
 battle.player['hp']=1;battle.hand=[];o=battle.step({'id':'end'});assert o['terminal'] and not o['won']
@pytest.mark.parametrize('index',range(8))
def test_deterministic_complete_episode(index):
 s,z,_=make_scenario('reference_v1','train',index);a=make_env('reference_v1',s,z);b=make_env('reference_v1',s,z);rng=random.Random(15)
 for _ in range(192):
  oa,ob=a.observe(),b.observe();validate_public(oa);assert oa==ob
  if oa['terminal']:return
  act=rng.choice(oa['actions']);a.step(act);b.step(act)
 pytest.fail('Reference random episode did not terminate within budget')
def test_bad_card_fails():
 with pytest.raises(ValueError):Card('UNSUPPORTED_CARD')
