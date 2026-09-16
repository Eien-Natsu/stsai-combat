#!/usr/bin/env python3
"""Run ONE bounded native collection -> distillation -> evaluation iteration.
Does not auto-promote, auto-repeat, fetch engines, modify drivers or touch test data.
"""
from pathlib import Path
import argparse,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--config',default='configs/native_pilot.json')
 p.add_argument('--train-episodes',type=int,default=128);p.add_argument('--val-episodes',type=int,default=16)
 p.add_argument('--eval-episodes',type=int,default=32);p.add_argument('--workers',type=int,default=2)
 p.add_argument('--iteration',type=int,default=0);p.add_argument('--checkpoint',default='');p.add_argument('--replay',nargs='*',default=[])
 p.add_argument('--device',default='cuda');a=p.parse_args()
 if not (1<=a.train_episodes<=4096 and 1<=a.val_episodes<=1024 and 1<=a.eval_episodes<=1024 and 1<=a.workers<=32):raise SystemExit('Invalid/budget-exceeding limits')
 if a.iteration<0 or (a.iteration>0 and not a.checkpoint):raise SystemExit('Later iterations require a previous native checkpoint')
 out=Path(a.output).resolve()
 if out.exists() and any(out.iterdir()):raise SystemExit('Use a new empty iteration directory; recover partial stages with individual CLI commands')
 out.mkdir(parents=True,exist_ok=True)
 env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
 def run(*parts):
  cmd=[sys.executable,'-m','stsai',*map(str,parts)];print('RUN',' '.join(cmd),flush=True);subprocess.run(cmd,cwd=ROOT,env=env,check=True)
 run('doctor','--output',out/'doctor.json',*(['--require-cuda'] if a.device=='cuda' else []))
 from stsai.native import engine_metadata
 print(engine_metadata()) # fail early: no reference fallback
 common=['--backend','lightspeed_pilot','--config',a.config]
 teacher=['--checkpoint',a.checkpoint] if a.checkpoint else []
 run('collect','--output',out/'train','--count',a.train_episodes,'--start',a.iteration*100000,'--workers',a.workers,'--iteration',a.iteration,'--sample-actions',*common,*teacher)
 run('collect','--output',out/'val','--split','val','--count',a.val_episodes,'--workers',a.workers,*common)
 run('train','--train-data',out/'train',*a.replay,'--val-data',out/'val','--output',out/'model','--device',a.device,*common,*(['--init-checkpoint',a.checkpoint] if a.checkpoint else []))
 run('evaluate','--output',out/'eval','--count',a.eval_episodes,'--agents','heuristic','search','model','hybrid','--checkpoint',out/'model'/'best.pt','--device',a.device,*common)
 run('mine','--data',out/'train','--output',out/'failures.json')
 print('Iteration finished. Inspect utility/win/latency/confidence intervals; this script DOES NOT promote the model.')
if __name__=='__main__':main()
