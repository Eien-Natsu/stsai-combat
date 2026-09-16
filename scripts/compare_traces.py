#!/usr/bin/env python3
"""Compare ALREADY ALIGNED public-state JSONL traces, never hidden states.
This is a comparator, not an implemented original-game scenario injector.
Each input line: {"observation": <schema1 state>, "action_id": <logical id>}
Canonical adapters must give action/card/enemy identities common semantics first.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from stsai.util import atomic_json
from stsai.contracts import validate_public
FIELDS=('turn','terminal','won','player','hand','draw_pile','discard_pile','exhaust_pile','enemies','potions')
def diffs(a,b,path='$'):
 if type(a)!=type(b):return [{'path':path,'left':a,'right':b}]
 if isinstance(a,dict):
  result=[]
  for k in sorted(set(a)|set(b)):
   if k not in a or k not in b:result.append({'path':f'{path}.{k}','left':a.get(k),'right':b.get(k)})
   else:result.extend(diffs(a[k],b[k],f'{path}.{k}'))
  return result
 if isinstance(a,list):
  if len(a)!=len(b):return [{'path':path+'.length','left':len(a),'right':len(b)}]
  return [d for i,(x,y) in enumerate(zip(a,b)) for d in diffs(x,y,f'{path}[{i}]')]
 return [] if a==b else [{'path':path,'left':a,'right':b}]
def main():
 p=argparse.ArgumentParser();p.add_argument('left');p.add_argument('right');p.add_argument('--output',required=True);a=p.parse_args()
 left=[json.loads(s) for s in Path(a.left).read_text().splitlines() if s.strip()];right=[json.loads(s) for s in Path(a.right).read_text().splitlines() if s.strip()]
 if not left or len(left)!=len(right):raise SystemExit('Empty traces or unequal lengths')
 mismatches=[]
 for i,(l,r) in enumerate(zip(left,right)):
  validate_public(l['observation']);validate_public(r['observation'])
  d=diffs({k:l['observation'][k] for k in FIELDS},{k:r['observation'][k] for k in FIELDS})
  if l.get('action_id')!=r.get('action_id'):d.append({'path':'$.action_id','left':l.get('action_id'),'right':r.get('action_id')})
  if d:mismatches.append({'step':i,'differences':d})
 report={'compared_steps':len(left),'matched':not mismatches,'mismatches':mismatches,
 'scope':'Only supplied aligned traces. Matching does not certify unsupported cards, RNG equivalence, or the entire game.'}
 atomic_json(a.output,report);print(json.dumps({'matched':not mismatches,'compared_steps':len(left)}))
 if mismatches:raise SystemExit(1)
if __name__=='__main__':main()
