#!/usr/bin/env python3
"""Re-label existing development states with a larger teacher budget.

The stored policy for a state comes from ONE search run. At 64 simulations two
such runs disagree on the action class for a third of states, so the student is
partly fitting search noise. Averaging more simulations gives a better estimate
of the same quantity, which is a different thing from collecting more states.

States are reached by replaying the recorded action prefix; every step is
checked against the stored observation hash and a mismatch aborts the run.
Writes a fresh collection directory: observations are copied verbatim, only the
teacher label changes, and the manifest records the budget it was produced at.
"""
import argparse
import gzip
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def process_episode(job):
    source_dir, out_dir, name, budget, config = job
    sys.path.insert(0, str(ROOT / "src"))
    from stsai.contracts import observation_key
    from stsai.scenarios import make_env
    from stsai.search import BeliefSearch, SearchConfig
    from stsai.util import load_json

    meta_path = Path(source_dir) / name.replace(".jsonl.gz", ".jsonl.meta.json")
    meta = load_json(meta_path)
    with gzip.open(Path(source_dir) / name, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    env = make_env("lightspeed_pilot", meta["scenario"], meta["episode_seed"])
    obs = env.observe()
    search = BeliefSearch(SearchConfig(**config))
    relabelled = []
    for index, row in enumerate(rows):
        if observation_key(obs) != observation_key(row["observation"]):
            return {"episode_index": meta["episode_index"], "error": f"replay diverged at step {index}"}
        if len(obs["actions"]) > 1:
            result = search.run(obs, env.sampler(), 10_000_000 + index)
            teacher = next(i for i, a in enumerate(obs["actions"]) if a["id"] == result["action"]["id"])
            row = {**row, "policy": result["policy"], "search_q": result["q"],
                   "teacher_action_index": teacher, "cutoff_fraction": result["cutoff_fraction"],
                   "relabel_budget": budget}
        relabelled.append(row)
        action = obs["actions"][row["action_index"]]
        obs = env.step(action)
    path = Path(out_dir) / name
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for row in relabelled:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)
    with open(Path(out_dir) / name.replace(".jsonl.gz", ".jsonl.meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    return {"episode_index": meta["episode_index"], "rows": len(relabelled)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget", type=int, required=True, help="simulations per state")
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    base = json.loads((ROOT / args.config).read_text())["search"]
    config = {**base, "simulations": args.budget}
    source = Path(args.source)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "collection.json").exists():
        raise SystemExit("Use a new output directory")

    names = sorted(p.name for p in source.glob("episode_*.jsonl.gz"))
    if not names:
        raise SystemExit("No source episodes")
    started = time.perf_counter()
    jobs = [(str(source), str(out), name, args.budget, config) for name in names]
    with Pool(args.workers) as pool:
        results = pool.map(process_episode, jobs, chunksize=1)
    failures = [r for r in results if "error" in r]
    if failures:
        for failure in failures[:5]:
            print(failure, file=sys.stderr)
        raise SystemExit(f"{len(failures)} episodes failed to replay; refusing to write a manifest")

    # Carry the source manifest forward with the budget corrected, so the trainer
    # sees a consistent fingerprint instead of an unlabelled directory.
    from stsai.util import digest
    source_manifest = json.loads((source / "collection.json").read_text(encoding="utf-8"))
    settings = dict(source_manifest["settings"])
    settings["search"] = {**settings["search"], "simulations": args.budget}
    settings["relabel"] = {"source": str(source.resolve()), "budget": args.budget}
    manifest = {
        "relabelled_from": str(source.resolve()),
        "relabel_budget": args.budget,
        "episodes": len(results),
        "rows": sum(r["rows"] for r in results),
        "search_config": config,
        "note": "Observations are copied verbatim; only teacher labels changed.",
        "elapsed_seconds": time.perf_counter() - started,
    }
    (out / "collection.json").write_text(json.dumps(
        {"fingerprint": digest(settings), "settings": settings}, indent=2) + "\n", encoding="utf-8")
    (out / "relabel.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
