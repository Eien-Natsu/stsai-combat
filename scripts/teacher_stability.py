#!/usr/bin/env python3
"""Is the teacher's label a property of the state, or of the search seed?

Replays development episodes back to selected decision states and re-runs the
teacher there with independent search seeds and budgets. If the same state
yields materially different labels, no student can be right, and a validation
cross-entropy floor is imposed by label noise rather than by the network.

Roots are reached by replaying the recorded action prefix, not by loading a
saved state: the observation hash is checked at every step and the run stops
loudly on the first mismatch. Seeds here are search randomness only; the
episode seed that builds the environment never enters an observation, a feature
or a search decision.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from stsai.contracts import observation_key, validate_public
from stsai.scenarios import make_env
from stsai.search import BeliefSearch, SearchConfig
from stsai.util import atomic_json, load_json


def load_episodes(directory):
    episodes = []
    for meta_path in sorted(Path(directory).glob("episode_*.jsonl.meta.json")):
        meta = load_json(meta_path)
        shard = meta_path.parent / meta_path.name.replace(".meta.json", ".gz")
        if not shard.exists():
            continue
        import gzip
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        episodes.append({"meta": meta, "rows": rows, "shard": str(shard)})
    return episodes


def reach_state(episode, step, backend):
    """Rebuild the environment and replay the recorded prefix to `step`."""
    meta = episode["meta"]
    env = make_env(backend, meta["scenario"], meta["episode_seed"])
    obs = env.observe()
    for index in range(step):
        expected = episode["rows"][index]["observation"]
        if observation_key(obs) != observation_key(expected):
            raise RuntimeError(f"replay diverged at step {index} of episode {meta['episode_index']}")
        action_index = episode["rows"][index]["action_index"]
        action = obs["actions"][action_index]
        obs = env.step(action)
    expected = episode["rows"][step]["observation"]
    if observation_key(obs) != observation_key(expected):
        raise RuntimeError(f"replay diverged at the target step of episode {meta['episode_index']}")
    validate_public(obs)
    return env, obs


def action_class(obs, action):
    if action["kind"] != "play":
        return ("other", action["kind"], action.get("card_id"), action.get("target"))
    source = obs["hand"][action["source"]]
    return ("play", action["card_id"], action.get("target"), source.get("upgraded"),
            source.get("cost"), source.get("exhaust"), source.get("ethereal"),
            source.get("free"), source.get("retain"), source.get("special"), source.get("type"))


def kl(p, q):
    p = np.asarray(p, dtype=np.float64); q = np.asarray(q, dtype=np.float64)
    nz = p > 0
    return float((p[nz] * (np.log(p[nz]) - np.log(np.clip(q[nz], 1e-12, None)))).sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="development collection directory (train split)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--states", type=int, default=64)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--budgets", nargs="+", type=int, default=[64, 256, 1024])
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--backend", default="lightspeed_pilot")
    parser.add_argument("--max-depth", type=int, default=64)
    parser.add_argument("--rollout-limit", type=int, default=128)
    args = parser.parse_args()

    base = load_json(args.config)["search"]
    episodes = load_episodes(args.data)
    if not episodes:
        raise SystemExit("No development episodes found")

    # Stratify by encounter so a rare elite is not drowned out by repeats.
    picks = []
    for episode in episodes:
        rows = episode["rows"]
        for step, row in enumerate(rows):
            if len(row["policy"]) > 1:
                encounter = row["observation"]["enemies"][0]["id"] if row["observation"]["enemies"] else "NONE"
                picks.append((encounter, episode, step))
    by_encounter = defaultdict(list)
    for encounter, episode, step in picks:
        by_encounter[encounter].append((episode, step))
    chosen = []
    index = 0
    while len(chosen) < args.states:
        progressed = False
        for encounter in sorted(by_encounter):
            bucket = by_encounter[encounter]
            if index < len(bucket):
                chosen.append((encounter, *bucket[index])); progressed = True
                if len(chosen) >= args.states:
                    break
        if not progressed:
            break
        index += 1

    records = []
    started = time.perf_counter()
    for encounter, episode, step in chosen:
        try:
            env, obs = reach_state(episode, step, args.backend)
        except RuntimeError as exc:
            records.append({"encounter": encounter, "episode_index": episode["meta"]["episode_index"],
                            "step": step, "replay_error": str(exc)})
            continue
        actions = obs["actions"]
        classes = [action_class(obs, a) for a in actions]
        for budget in args.budgets:
            runs = []
            for seed in range(args.seeds):
                search = BeliefSearch(SearchConfig(simulations=budget, max_depth=args.max_depth,
                                                   rollout_limit=args.rollout_limit, **{
                                                       k: v for k, v in base.items()
                                                       if k not in ("simulations", "max_depth", "rollout_limit")}))
                result = search.run(obs, env.sampler(), 10_000 * seed + step)
                chosen_index = next(i for i, a in enumerate(actions) if a["id"] == result["action"]["id"])
                runs.append({"seed": seed, "index": chosen_index, "class": classes[chosen_index],
                             "policy": result["policy"], "q": result["q"], "visits": result["visits"],
                             "cutoff_fraction": result["cutoff_fraction"],
                             "elapsed": result["elapsed_seconds"]})
            class_agree = 0; pairs = 0; kls = []
            for a in range(len(runs)):
                for b in range(a + 1, len(runs)):
                    pairs += 1
                    class_agree += int(runs[a]["class"] == runs[b]["class"])
                    kls.append(kl(runs[a]["policy"], runs[b]["policy"]))
            ties = sum(1 for r in runs if len(set(r["visits"])) < len(r["visits"]) or
                       sum(1 for v in r["visits"] if v == max(r["visits"])) > 1)
            records.append({
                "encounter": encounter, "episode_index": episode["meta"]["episode_index"], "step": step,
                "budget": budget, "legal_actions": len(actions),
                "pairwise_class_agreement": class_agree / max(1, pairs),
                "mean_pairwise_kl": float(np.mean(kls)) if kls else 0.0,
                "max_pairwise_kl": float(np.max(kls)) if kls else 0.0,
                "visit_tie_rate": ties / len(runs),
                "mean_cutoff_fraction": float(np.mean([r["cutoff_fraction"] for r in runs])),
                "mean_elapsed": float(np.mean([r["elapsed"] for r in runs])),
                "distinct_actions": len({r["class"] for r in runs}),
            })

    def summarise(budget):
        subset = [r for r in records if r.get("budget") == budget]
        if not subset:
            return None
        return {
            "states": len(subset),
            "pairwise_class_agreement": float(np.mean([r["pairwise_class_agreement"] for r in subset])),
            "unanimous_states": int(sum(1 for r in subset if r["pairwise_class_agreement"] == 1.0)),
            "mean_pairwise_kl": float(np.mean([r["mean_pairwise_kl"] for r in subset])),
            "mean_visit_tie_rate": float(np.mean([r["visit_tie_rate"] for r in subset])),
            "mean_cutoff_fraction": float(np.mean([r["mean_cutoff_fraction"] for r in subset])),
            "mean_elapsed": float(np.mean([r["mean_elapsed"] for r in subset])),
            "simulations_per_state": budget * args.seeds,
        }

    report = {
        "scope": "teacher label stability on replayed development roots; not a strength measurement",
        "data": str(Path(args.data).resolve()),
        "states_requested": args.states, "states_replayed": len({(r["episode_index"], r["step"]) for r in records}),
        "search_seeds_per_state": args.seeds, "budgets": args.budgets,
        "replay_failures": [r for r in records if "replay_error" in r],
        "by_budget": {str(b): summarise(b) for b in args.budgets},
        "by_encounter": {
            str(b): {enc: {
                "states": len(v),
                "pairwise_class_agreement": float(np.mean([r["pairwise_class_agreement"] for r in v])),
                "mean_pairwise_kl": float(np.mean([r["mean_pairwise_kl"] for r in v])),
            } for enc, v in sorted({e: [r for r in records if r.get("budget") == b and r.get("encounter") == e]
                                    for e in {r.get("encounter") for r in records}}.items()) if v}
            for b in args.budgets},
        "instructions": {
            "budget_argument": base.get("simulations"),
            "max_depth": args.max_depth, "rollout_limit": args.rollout_limit,
        },
        "elapsed_seconds": time.perf_counter() - started,
        "caveats": [
            "Agreement between teacher runs is an empirical reference for label stability, "
            "not a mathematical ceiling on student accuracy.",
            "Root visits are not calibrated probabilities and the maximum Q is not the optimal value.",
        ],
    }
    atomic_json(args.output, report)
    for budget in args.budgets:
        summary = report["by_budget"][str(budget)]
        print(json.dumps({"budget": budget, **summary}, indent=2))
    if report["replay_failures"]:
        print(f"REPLAY FAILURES: {len(report['replay_failures'])}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
