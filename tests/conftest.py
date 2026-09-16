import pytest
from stsai.reference import ReferenceBattle,Card
@pytest.fixture
def battle():
 e=ReferenceBattle({'deck':['STRIKE']*5+['DEFEND']*4+['BASH'],'enemies':[{'id':'TRAINING_TEST','hp':40,'damage':7}],'hp':60,'max_hp':80},123)
 e.hand=[Card('STRIKE'),Card('DEFEND'),Card('BASH')];e._draw=[Card('DEFEND'),Card('STRIKE'),Card('ANGER')]
 e.discard=[];e.exhaust=[]
 return e
