from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
from dataclasses import asdict
from .scenarios import make_scenario, make_env
from .search import SearchConfig, BeliefSearch
from .objective import outcome_target, terminal_utility
from .util import canonical, atomic_json, digest, seed_for, weighted_index, load_json

@lru_cache(maxsize=4)
def _teacher(checkpoint: str, backend: str, search_json: str):
    evaluator = None
    if checkpoint:
        import torch
        torch.set_num_threads(1)
        from .model import ModelEvaluator
        evaluator = ModelEvaluator.from_checkpoint(checkpoint,"cpu",backend)
    return BeliefSearch(SearchConfig(**json.loads(search_json)),evaluator)

def _collect_episode(job):
    spec, index = job
    scenario, episode_seed, family = make_scenario(spec["backend"], spec["split"], index, spec["master_seed"])
    ep = digest([spec["fingerprint"], index])[:20]
    directory = Path(spec["output"])
    path = directory / f"episode_{index:08d}_{ep}.jsonl.gz"
    meta_path = path.with_suffix(".meta.json")
    if path.exists() and meta_path.exists(): return load_json(meta_path)
    env = make_env(spec["backend"],scenario,episode_seed)
    teacher = _teacher(spec["checkpoint"],spec["backend"],canonical(spec["search"]))
    rows = []; search_time = 0.; simulations = 0; obs = env.observe()
    rng = random.Random(seed_for("behavior",spec["backend"],spec["split"],index,spec["iteration"]))
    for step in range(spec["max_actions"]):
        if obs["terminal"]: break
        result = teacher.run(obs,env.sampler(),seed_for("search-agent",spec["backend"],spec["split"],index,step,spec["iteration"]))
        # Default argmax for stable teachers; optional visit-sampling supports coverage.
        index_action = weighted_index(result["policy"],rng) if spec["sample_actions"] else next(i for i,a in enumerate(obs["actions"]) if a["id"] == result["action"]["id"])
        action = obs["actions"][index_action]
        rows.append({"schema_version":1,"backend":spec["backend"],"split":spec["split"],
                     "episode_id":ep,"family":family,"episode_index":index,"iteration":spec["iteration"],
                     "observation":obs,"policy":result["policy"],"action_index":index_action,
                     "search_q":result["q"],"cutoff_fraction":result["cutoff_fraction"]})
        search_time += result["elapsed_seconds"]; simulations += result["simulations"]
        obs = env.step(action)
    completed = bool(obs["terminal"])
    target = outcome_target(obs)
    utility = terminal_utility(obs,spec["search"].get("potion_cost",.02)) if completed else 0.0
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp,"wt",encoding="utf-8") as f:
        for row in rows:
            row.update(outcome=target,value=utility,value_mask=float(completed))
            f.write(canonical(row)+"\n")
    os.replace(tmp,path)
    meta = {"episode_id":ep,"episode_index":index,"episode_seed":episode_seed,"family":family,
            "backend":spec["backend"],"split":spec["split"],"completed":completed,
            "won":bool(obs["won"]) if completed else None,"truncated":not completed,"steps":len(rows),
            "end_hp":obs["player"]["hp"],"utility":utility if completed else None,
            "search_seconds":search_time,"simulations":simulations,"scenario":scenario}
    atomic_json(meta_path,meta)
    return meta

def collect(output, backend="reference_v1", split="train", count=16, start=0, workers=1,
            search=None, checkpoint="", master_seed=20260916, max_actions=256,
            iteration=0, sample_actions=False):
    if split not in ("train", "val"): raise ValueError("Collection is train/val only; use frozen evaluation manifests for test")
    if count < 1 or start < 0 or workers < 1 or max_actions < 1: raise ValueError("Invalid collection limits")
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    checkpoint = str(Path(checkpoint).resolve()) if checkpoint else ""
    ckhash = hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest() if checkpoint else None
    from .scenarios import SCENARIO_REVISION
    settings = {"backend":backend,"split":split,"search":asdict(SearchConfig(**(search or {}))),
                "checkpoint":checkpoint,"checkpoint_sha256":ckhash,"master_seed":master_seed,
                "max_actions":max_actions,"iteration":iteration,"sample_actions":sample_actions,
                "scenario_revision":SCENARIO_REVISION}
    if backend == "lightspeed_pilot":
        from .native import engine_metadata
        settings["engine"] = engine_metadata()
    fingerprint = digest(settings)
    manifest = output / "collection.json"
    if manifest.exists() and load_json(manifest)["fingerprint"] != fingerprint:
        raise ValueError("Collection settings changed; use a new output directory")
    atomic_json(manifest,{"fingerprint":fingerprint,"settings":settings})
    spec = {**settings,"fingerprint":fingerprint,"output":str(output.resolve())}
    jobs = [(spec,index) for index in range(start,start+count)]
    if workers == 1: summaries = list(map(_collect_episode,jobs))
    else:
        # spawn avoids inheriting an initialized CUDA runtime.
        import multiprocessing as mp
        with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context("spawn")) as pool:
            summaries = list(pool.map(_collect_episode,jobs))
    summary = {"backend":backend,"split":split,"episodes":len(summaries),
               "completed":sum(s["completed"] for s in summaries),
               "wins":sum(s["won"] is True for s in summaries),
               "truncated":sum(s["truncated"] for s in summaries),
               "rows":sum(s["steps"] for s in summaries),
               "search_seconds":sum(s["search_seconds"] for s in summaries)}
    atomic_json(output/f"summary_{start}_{count}.json",summary)
    return summary
