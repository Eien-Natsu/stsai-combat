import gzip,json
from pathlib import Path
import pytest
from stsai.collection import collect
from stsai.scenarios import make_scenario
from stsai.training import train,ReplayDataset
from stsai.model import ModelEvaluator
from stsai.evaluation import evaluate,make_manifest,wilson
from stsai.mining import mine
ROOT=Path(__file__).resolve().parents[1]
SC={'simulations':4,'max_depth':8,'rollout_limit':12}
TC={'batch_size':2,'accumulation_steps':1,'max_updates':2,'epochs':4,'eval_every':1,'save_every':1,'validation_batches':2,'shuffle_buffer':16,'cpu_threads':2,'model':{'d_model':32,'layers':1,'heads':4,'dropout':0.}}
def test_split_seed_namespaces():
 triples=[make_scenario('reference_v1',s,0)[1] for s in ('train','val','test')];assert len(set(triples))==3
def test_wilson_bounds():
 a=wilson(0,10);b=wilson(10,10);assert a[0]==0;assert b[1]==1;assert 0<a[1]<1 and 0<b[0]<1
@pytest.mark.integration
def test_collection_train_eval_resume(tmp_path):
 td=tmp_path/'train';vd=tmp_path/'val'
 a=collect(td,count=2,search=SC,max_actions=128)
 collect(vd,split='val',count=1,search=SC,max_actions=128)
 assert a['rows']>0;assert a['truncated']==0
 assert collect(td,count=2,search=SC,max_actions=128)==a
 with pytest.raises(ValueError):collect(td,count=1,search={'simulations':5},max_actions=128)
 with pytest.raises(ValueError):ReplayDataset([vd],'reference_v1','train')
 report=train([td],[vd],tmp_path/'model',device='cpu',config=TC);assert report['steps']==2
 ck=tmp_path/'model'/'best.pt';ModelEvaluator.from_checkpoint(ck,'cpu','reference_v1')
 with pytest.raises(ValueError):ModelEvaluator.from_checkpoint(ck,'cpu','lightspeed_pilot')
 train([td],[vd],tmp_path/'model',device='cpu',config={**TC,'max_updates':3},resume=tmp_path/'model'/'last.pt')
 warm=train([td],[vd],tmp_path/'warm',device='cpu',config=TC,init_checkpoint=ck);assert warm['steps']==2
 er=evaluate(tmp_path/'eval',agents=['heuristic','model'],count=2,checkpoint=ck,device='cpu',search_config=SC,max_actions=128)
 assert er['episodes_per_agent']==2;assert er['agents']['model']['wins']+er['agents']['model']['losses']+er['agents']['model']['truncated']==2
 mr=mine([td],tmp_path/'cases.json',3);assert 0<mr['selected']<=3
@pytest.mark.integration
def test_truncation_mask(tmp_path):
 collect(tmp_path/'t',count=1,search=SC,max_actions=1)
 with gzip.open(next((tmp_path/'t').glob('episode_*.jsonl.gz')),'rt') as f:row=json.loads(next(f))
 assert row['value_mask']==0 and sum(row['outcome'])==0
 assert row['value']==0 # masked placeholder, NOT a death label

def test_frozen_manifest(tmp_path):
 path=tmp_path/'test.json';mf=make_manifest(path,'reference_v1',2);assert mf['split']=='test'
 with pytest.raises(ValueError):make_manifest(path,'reference_v1',2)
 with pytest.raises(ValueError):evaluate(tmp_path/'e',split='test',count=2)
 mf['indices'].append(100);path.write_text(json.dumps(mf))
 with pytest.raises(ValueError):evaluate(tmp_path/'e2',split='test',manifest=path)

@pytest.mark.integration
def test_parallel_collection(tmp_path):
 report=collect(tmp_path/'parallel',count=2,workers=2,search=SC,max_actions=128)
 assert report['episodes']==2 and report['rows']>0

def test_all_shipped_configs_parse():
 from stsai.search import SearchConfig
 from stsai.model import ModelConfig
 for path in (ROOT/'configs').glob('*.json'):
  data=json.loads(path.read_text());SearchConfig(**data['search']);ModelConfig(**data['training']['model'])

def test_native_missing_never_falls_back(monkeypatch):
 import stsai.native as n
 def missing():raise RuntimeError('Missing native test sentinel')
 monkeypatch.setattr(n,'_module',missing)
 with pytest.raises(RuntimeError,match='sentinel'):n.NativeBattle({},0)


def test_collect_refuses_test_split(tmp_path):
 with pytest.raises(ValueError,match='train/val'):collect(tmp_path/'leak',split='test',count=1,search=SC)

def test_distinct_objective_rejected(tmp_path):
 collect(tmp_path/'a',count=1,search={**SC,'potion_cost':.02},max_actions=16)
 collect(tmp_path/'b',count=1,search={**SC,'potion_cost':.07},max_actions=16)
 with pytest.raises(ValueError,match='objectives'):ReplayDataset([tmp_path/'a',tmp_path/'b'],'reference_v1','train')
