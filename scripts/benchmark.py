#!/usr/bin/env python3
"""Measure actual local throughput, not extrapolated marketing throughput."""
import argparse,json,time,random,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from stsai.scenarios import make_scenario,make_env
from stsai.search import BeliefSearch,SearchConfig
from stsai.util import atomic_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--backend',default='reference_v1');p.add_argument('--output',default='runs/benchmark.json')
 p.add_argument('--transitions',type=int,default=500);p.add_argument('--simulations',type=int,default=32);a=p.parse_args()
 if a.transitions<1 or a.simulations<1:raise SystemExit('Counts must be positive')
 scenario,seed,_=make_scenario(a.backend,'val',0);env=make_env(a.backend,scenario,seed);obs=env.observe();rng=random.Random(7)
 started=time.perf_counter();resets=0
 for _ in range(a.transitions):
  if obs['terminal']:
   resets+=1;env=make_env(a.backend,scenario,seed+resets);obs=env.observe()
  obs=env.step(rng.choice(obs['actions']))
 duration=time.perf_counter()-started
 env=make_env(a.backend,scenario,seed);search=BeliefSearch(SearchConfig(simulations=a.simulations))
 result=search.run(env.observe(),env.sampler(),19)
 report={'backend':a.backend,'transitions':a.transitions,'transitions_per_second_including_observation_and_resets':a.transitions/duration,
 'reset_count':resets,'search_simulations':result['simulations'],'search_seconds':result['elapsed_seconds'],'search_cutoff_fraction':result['cutoff_fraction'],
 'warning':'One process, one sampled root; measure representative states and worker scaling before budgeting. Reference speed does not predict native speed.'}
 atomic_json(a.output,report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
