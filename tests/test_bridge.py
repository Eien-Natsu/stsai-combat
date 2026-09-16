import copy,io,json
import pytest
from stsai.bridge import parse_message,command_for,run_bridge,UnsupportedState
from stsai.contracts import validate_public
@pytest.fixture
def message():
 card={'id':'Strike_R','uuid':'secret-identity','cost':1,'upgrades':0,'type':'ATTACK','has_target':True,'is_playable':True,'exhausts':False,'ethereal':False}
 return {'in_game':True,'ready_for_command':True,'available_commands':['play','end','state','wait'],
 'game_state':{'class':'IRONCLAD','seed':91829182,'ascension_level':20,'screen_type':'NONE','relics':[{'id':'Burning Blood'}],
 'potions':[{'id':'Potion Slot'}], 'combat_state':{'turn':1,'player':{'current_hp':60,'max_hp':80,'block':0,'energy':3,'powers':[]},
 'monsters':[{'id':'Cultist','current_hp':50,'max_hp':50,'block':0,'intent':'ATTACK','move_adjusted_damage':6,'move_hits':1,'powers':[]}],
 'hand':[card],'draw_pile':[copy.deepcopy(card)],'discard_pile':[],'exhaust_pile':[]}}}
def test_bridge_whitelist_discards_secrets(message):
 o=parse_message(message);validate_public(o);s=json.dumps(o)
 assert 'secret-identity' not in s and '91829182' not in s;assert o['hand'][0]['id']=='STRIKE'
def test_command_indices(message):
 a=parse_message(message)['actions'][0];assert command_for(a)=='PLAY 1 0'
 assert command_for({'kind':'end'})=='END'
def test_unsupported_relic_pauses(message):
 message['game_state']['relics'].append({'id':'Runic Dome'})
 with pytest.raises(UnsupportedState):parse_message(message)
def test_unsupported_card_pauses(message):
 message['game_state']['combat_state']['hand'][0]['id']='True Grit'
 with pytest.raises(UnsupportedState):parse_message(message)
def test_hidden_intent_pauses(message):
 message['game_state']['combat_state']['monsters'][0]['intent']='UNKNOWN'
 with pytest.raises(UnsupportedState):parse_message(message)
def test_native_potion_not_faked(message):
 message['game_state']['potions']=[{'id':'Fire Potion'}]
 with pytest.raises(UnsupportedState):parse_message(message)
def test_selection_screen_pauses(message):
 message['game_state']['screen_type']='HAND_SELECT'
 with pytest.raises(UnsupportedState):parse_message(message)
def test_execute_requires_checkpoint(tmp_path):
 with pytest.raises(ValueError):run_bridge(tmp_path/'log.jsonl',execute=True)
def test_observe_only_never_plays(message,tmp_path,monkeypatch,capsys):
 monkeypatch.setattr('sys.stdin',io.StringIO(json.dumps(message)+'\n'))
 run_bridge(tmp_path/'log.jsonl');lines=capsys.readouterr().out.splitlines()
 assert lines==['ready','WAIT 60']
 record=json.loads((tmp_path/'log.jsonl').read_text());assert record['proposed_command']=='PLAY 1 0'
