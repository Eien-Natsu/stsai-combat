from __future__ import annotations
from dataclasses import asdict
import math
import hashlib
from pathlib import Path
import random
import secrets
import time
import numpy as np
from .scenarios import make_scenario,make_env
from .search import BeliefSearch,HeuristicEvaluator,SearchConfig
from .objective import terminal_utility
from .util import seed_for,atomic_json,append_json,load_json,digest

def wilson(successes,n,z=1.959963984540054):
    if n<1: return [0.,1.]
    p=successes/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [0. if successes==0 else max(0.,mid-half), 1. if successes==n else min(1.,mid+half)]

def make_manifest(path,backend,count=1000):
    p=Path(path)
    if p.exists(): raise ValueError("Refusing to replace an existing held-out test manifest")
    if count<1: raise ValueError("count must be positive")
    manifest={"schema_version":1,"backend":backend,"split":"test","master_seed":secrets.randbits(60),
              "indices":list(range(count)),"purpose":"Frozen final evaluation; never feed to training or model selection"}
    manifest["fingerprint"]=digest(manifest);atomic_json(p,manifest);return manifest

def _decision(agent,obs,env,search,evaluator,rng,decision_seed):
    if agent=="random": return rng.randrange(len(obs["actions"]))
    if agent=="heuristic":
        p,_=HeuristicEvaluator().evaluate(obs);return int(np.argmax(p))
    if agent=="model":
        p,_=evaluator.evaluate(obs);return int(np.argmax(p))
    if agent in ("search","hybrid"):
        result=search.run(obs,env.sampler(),decision_seed)
        return next(i for i,a in enumerate(obs["actions"]) if a["id"]==result["action"]["id"])
    raise ValueError(agent)

def evaluate(output,backend="reference_v1",agents=("heuristic","search"),count=32,split="val",
             master_seed=20260916,checkpoint="",device="cpu",search_config=None,max_actions=256,manifest=""):
    agents=list(dict.fromkeys(agents))
    if not agents or any(a not in ("random","heuristic","search","model","hybrid") for a in agents): raise ValueError("Invalid agents")
    if count<1 or max_actions<1: raise ValueError("Invalid evaluation limits")
    if split not in ("val","test"): raise ValueError("Evaluation split must be val or test")
    if split=="test" and not manifest: raise ValueError("Final test requires a frozen manifest generated after model selection")
    indices=list(range(count));mf=None
    if manifest:
        mf=load_json(manifest)
        if mf["backend"]!=backend or mf["split"]!="test": raise ValueError("Manifest mismatch")
        expected=dict(mf);expected.pop("fingerprint",None)
        if digest(expected)!=mf["fingerprint"]: raise ValueError("Manifest was modified")
        indices=mf["indices"];master_seed=mf["master_seed"];split="test"
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if (out/"episodes.jsonl").exists(): raise ValueError("Evaluation output already exists; use a new directory")
    evaluator=None
    if any(a in ("model","hybrid") for a in agents):
        if not checkpoint: raise ValueError("model/hybrid requires checkpoint")
        import torch
        torch.set_num_threads(2)
        from .model import ModelEvaluator
        evaluator=ModelEvaluator.from_checkpoint(checkpoint,device,backend)
    sc=SearchConfig(**(search_config or {}))
    basic_search=BeliefSearch(sc);hybrid_search=BeliefSearch(sc,evaluator) if evaluator else None
    records=[];latencies={a:[] for a in agents}
    for index in indices:
        scenario,ep_seed,family=make_scenario(backend,split,index,master_seed)
        for agent in agents:
            env=make_env(backend,scenario,ep_seed);obs=env.observe();rng=random.Random(seed_for("eval-agent",agent,backend,split,index));steps=0
            for step in range(max_actions):
                if obs["terminal"]:break
                t=time.perf_counter()
                j=_decision(agent,obs,env,hybrid_search if agent=="hybrid" else basic_search,evaluator,rng,seed_for("eval-search-agent",backend,split,index,step))
                latencies[agent].append(time.perf_counter()-t)
                obs=env.step(obs["actions"][j]);steps+=1
            record={"agent":agent,"episode_index":index,"family":family,"backend":backend,
                    "completed":obs["terminal"],"won":obs["won"] if obs["terminal"] else None,
                    "truncated":not obs["terminal"],"end_hp":obs["player"]["hp"],
                    "utility":terminal_utility(obs,sc.potion_cost) if obs["terminal"] else None,"steps":steps}
            append_json(out/"episodes.jsonl",record);records.append(record)
    result={"backend":backend,"split":split,"episodes_per_agent":len(indices),
            "search_config":asdict(sc),"checkpoint":str(checkpoint),
            "checkpoint_sha256":hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest() if checkpoint else None,
            "master_seed":master_seed,"max_actions":max_actions,"manifest_fingerprint":mf["fingerprint"] if mf else None,
            "warning":"REFERENCE FIXTURE ONLY: not an original-game win rate" if backend=="reference_v1" else "Native pilot only; real-game fidelity must be validated separately",
            "agents":{},"paired":{}}
    for agent in agents:
        rr=[r for r in records if r["agent"]==agent];n=len(rr)
        wins=sum(r["won"] is True for r in rr);trunc=sum(r["truncated"] for r in rr)
        completed=[r for r in rr if r["completed"]];survivors=[r for r in rr if r["won"]]
        result["agents"][agent]={"wins":wins,"losses":n-wins-trunc,"truncated":trunc,
            "known_win_fraction":wins/n,"win_rate_bounds_due_to_truncation":[wins/n,(wins+trunc)/n],
            "wilson95_with_censoring_bounds":[wilson(wins,n)[0],wilson(wins+trunc,n)[1]],
            "mean_utility_completed_only":float(np.mean([r["utility"] for r in completed])) if completed else None,
            "mean_end_hp_survivors_only":float(np.mean([r["end_hp"] for r in survivors])) if survivors else None,
            "decision_p50_ms":float(np.percentile(latencies[agent],50)*1000) if latencies[agent] else 0,
            "decision_p95_ms":float(np.percentile(latencies[agent],95)*1000) if latencies[agent] else 0}
    base=agents[0]
    for other in agents[1:]:
        aa={r["episode_index"]:r for r in records if r["agent"]==base}
        bb={r["episode_index"]:r for r in records if r["agent"]==other}
        keys=[k for k in aa if aa[k]["completed"] and bb[k]["completed"]]
        if keys:
            delta=np.asarray([bb[k]["utility"]-aa[k]["utility"] for k in keys])
            rng=np.random.default_rng(42)
            # Chunk-free bootstrap loop avoids B*N allocation on large test sets.
            means=[float(np.mean(delta[rng.integers(0,len(delta),size=len(delta))])) for _ in range(2000)]
            result["paired"][f"{other}_minus_{base}"]={"complete_pairs":len(keys),"mean_utility_delta":float(delta.mean()),
                "bootstrap95":np.quantile(means,[.025,.975]).tolist(),
                "all_pairs_complete":len(keys)==len(indices),
                "promotion_decision":"NOT_DECIDED: completion is not a strength or fidelity certificate",
                "interpretation":"Paired initial scenarios/seeds; future random streams can diverge with actions. IID scenario bootstrap, not a universal generalization guarantee."}
    if backend=="lightspeed_pilot":
        from .native import engine_metadata
        result["engine"]=engine_metadata()
    atomic_json(out/"report.json",result);return result
