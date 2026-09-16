#!/usr/bin/env python3
"""Bounded end-to-end reference-only engineering smoke; NOT a game benchmark."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',default='runs/smoke');p.add_argument('--device',default='cpu');args=p.parse_args()
 out=Path(args.output).resolve()
 if out.exists() and any(out.iterdir()):raise SystemExit('Use an empty output directory')
 out.mkdir(parents=True,exist_ok=True)
 env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
 def cmd(*parts):
  line=[sys.executable,'-m','stsai',*map(str,parts)]
  print('RUN', ' '.join(line),flush=True)
  subprocess.run(line,cwd=ROOT,env=env,check=True)
 started=time.perf_counter()
 cmd('collect','--output',out/'train','--count',4,'--workers',1)
 cmd('collect','--output',out/'val','--split','val','--count',2)
 cmd('train','--train-data',out/'train','--val-data',out/'val','--output',out/'model','--device',args.device)
 cmd('evaluate','--output',out/'eval','--agents','heuristic','search','model','hybrid','--count',4,'--checkpoint',out/'model'/'best.pt','--device',args.device)
 cmd('mine','--data',out/'train','--output',out/'failures.json','--limit',12)
 report={'scope':'reference_v1 engineering smoke ONLY','status':'completed','device_requested':args.device,'elapsed_seconds':time.perf_counter()-started,
  'training':json.loads((out/'model'/'training_summary.json').read_text()),'evaluation':json.loads((out/'eval'/'report.json').read_text()),
  'native_compilation_verified':False,'original_game_differential_verified':False,'superhuman_claim':False}
 (out/'smoke_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('SMOKE COMPLETE',out/'smoke_report.json')
if __name__=='__main__':main()
