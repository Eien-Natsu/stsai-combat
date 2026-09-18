#!/usr/bin/env python3
"""Paired development comparison for S1-E, with the pre-registered bootstrap.

Twenty thousand paired replicates over scenarios, seed 20260918, conditional on
the fixed models. Latency is reported two ways and named precisely: pooled
percentiles over every decision, and the median of per-episode percentiles.
Those are different quantities and the earlier report conflated them.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

REPLICATES = 20000
BOOTSTRAP_SEED = 20260918


def load_episodes(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    by_agent = {}
    for row in rows:
        by_agent.setdefault(row["episode_index"], {})[row["agent"]] = row
    return rows, by_agent


def load_latency(path):
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            out.setdefault(row["agent"], []).append(row)
    return out


def environment():
    """What the evaluation actually ran on, so the latency column is readable."""
    import os
    import platform
    try:
        import torch
        torch_threads = torch.get_num_threads()
        torch_version = torch.__version__
        cuda_available = torch.cuda.is_available()
    except Exception as exc:  # recorded rather than omitted
        torch_threads, torch_version, cuda_available = None, f"unavailable: {exc}", None
    model = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "host": platform.platform(), "cpu_model": model, "logical_cpus": os.cpu_count(),
        "torch_version": torch_version, "torch_threads_default": torch_threads,
        "thread_env": {name: os.environ.get(name) for name in
                       ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
        "device_for_this_report": "cpu fp32, batch one, no explicit thread pinning",
        "gpu": "present and used for training only" if cuda_available else "not used",
        "note": "recomputed at aggregation time in the same environment the evaluation ran in; "
                "the evaluation did not set thread counts explicitly",
    }


def paired(by_agent, a, b):
    """Paired utility difference, resampling scenarios, complete pairs only."""
    keys = [k for k, v in by_agent.items()
            if v.get(a, {}).get("completed") and v.get(b, {}).get("completed")]
    if not keys:
        return None
    a_utility = np.asarray([by_agent[k][a]["utility"] for k in keys])
    b_utility = np.asarray([by_agent[k][b]["utility"] for k in keys])
    delta = a_utility - b_utility
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = [float(np.mean(delta[rng.integers(0, len(delta), len(delta))])) for _ in range(REPLICATES)]
    return {
        "n_pairs": len(keys),
        "dropped_incomplete": len(by_agent) - len(keys),
        "mean": float(delta.mean()),
        "bootstrap95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "bootstrap_replicates": REPLICATES, "bootstrap_seed": BOOTSTRAP_SEED,
        "a_better": int((delta > 0).sum()), "b_better": int((delta < 0).sum()),
        "tie": int((delta == 0).sum()),
        "scope": "paired initial scenarios, conditional on these fixed checkpoints; development only",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", default="reports/s1_eval/episodes.jsonl")
    parser.add_argument("--latency", default="reports/s1_eval/decision_latency.jsonl.gz")
    parser.add_argument("--output", default="reports/s1_eval/paired_summary.json")
    args = parser.parse_args()

    rows, by_agent = load_episodes(ROOT / args.episodes)
    latency = load_latency(ROOT / args.latency)
    agents = sorted({r["agent"] for r in rows})
    student = next(a for a in agents if a not in ("heuristic", "search", "random"))

    comparisons = {f"{student}_minus_heuristic": paired(by_agent, student, "heuristic"),
                   f"{student}_minus_search": paired(by_agent, student, "search"),
                   "search_minus_heuristic": paired(by_agent, "search", "heuristic")}

    latency_summary = {}
    for agent, decisions in sorted(latency.items()):
        every = np.asarray([d["ms"] for d in decisions])
        decided = np.asarray([d["ms"] for d in decisions if not d["forced"]])
        latency_summary[agent] = {
            "decisions_timed": len(every),
            "forced_decisions": int(sum(1 for d in decisions if d["forced"])),
            "pooled_p50_ms_all_decisions": float(np.percentile(every, 50)),
            "pooled_p95_ms_all_decisions": float(np.percentile(every, 95)),
            "pooled_p50_ms_excluding_forced": float(np.percentile(decided, 50)) if decided.size else None,
            "pooled_p95_ms_excluding_forced": float(np.percentile(decided, 95)) if decided.size else None,
            "note": "pooled over every recorded decision, not a per-episode statistic",
        }

    report = {
        "environment": environment(),
        "scope": ("unverified simulator pilot, single training seed, development scenarios already "
                  "seen; not original-game strength and not a final test"),
        "scenarios": len(by_agent), "agents": agents,
        "paired": comparisons,
        "latency": latency_summary,
        "latency_definitions": {
            "pooled": "percentiles computed over every decision across all episodes",
            "median_of_episode_percentiles": "computed per episode then medianed; a different quantity",
        },
        "historical_note": ("the fb9bf6e results are kept as-is. Interface, counting rule and data "
                            "trajectories all changed together, so no difference here can be "
                            "attributed to any single factor."),
    }
    out = ROOT / args.output
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for key, value in comparisons.items():
        if value:
            print(f"{key:34s} mean={value['mean']:+.5f} "
                  f"ci95=[{value['bootstrap95'][0]:+.5f},{value['bootstrap95'][1]:+.5f}] "
                  f"pairs={value['n_pairs']} dropped={value['dropped_incomplete']}")
    print("wrote", out)


if __name__ == "__main__":
    main()
