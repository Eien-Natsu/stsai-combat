#!/usr/bin/env python3
"""Split the student's divergence into label noise and student error.

On one fixed set of states, measured against one fixed teacher budget:

  teacher_self_kl   mean pairwise KL between independent teacher runs. A perfect
                    student cannot beat what the teacher itself reproduces, so
                    this is the empirical floor imposed by search randomness.
  student_kl        KL from the teacher's stored label to the student.
  mean_teacher_kl   KL from one run to the per-action MEAN of the runs. This is
                    the KL a predictor that knew the true distribution would pay
                    against a single sampled label.

Everything is computed on the same states so the numbers subtract meaningfully.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import torch

from teacher_stability import load_episodes, reach_state, action_class
from stsai.encoding import encode, collate_encoded
from stsai.model import load_checkpoint
from stsai.search import BeliefSearch, SearchConfig
from stsai.util import atomic_json


def kl(p, q):
    p = np.asarray(p, dtype=np.float64); q = np.asarray(q, dtype=np.float64)
    nz = p > 0
    return float((p[nz] * (np.log(p[nz]) - np.log(np.clip(q[nz], 1e-12, None)))).sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--states", type=int, default=24)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--budget", type=int, default=256)
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    base = json.loads((ROOT / args.config).read_text())["search"]
    config = SearchConfig(**{**base, "simulations": args.budget})
    model, _ = load_checkpoint(args.checkpoint, args.device)
    device = next(model.parameters()).device

    episodes = load_episodes(args.data)
    picks = []
    for episode in episodes:
        for step, row in enumerate(episode["rows"]):
            if len(row["policy"]) > 1:
                picks.append((episode, step))
    picks = picks[:: max(1, len(picks) // args.states)][:args.states]

    rows = []
    for episode, step in picks:
        env, obs = reach_state(episode, step, "lightspeed_pilot")
        n = len(obs["actions"])
        classes = [action_class(obs, a) for a in obs["actions"]]
        runs = []
        for seed in range(args.seeds):
            result = BeliefSearch(config).run(obs, env.sampler(), 20_000 * seed + step)
            index = next(i for i, a in enumerate(obs["actions"]) if a["id"] == result["action"]["id"])
            runs.append({"policy": np.asarray(result["policy"]), "index": index, "class": classes[index]})
        mean_policy = np.mean([r["policy"] for r in runs], axis=0)
        with torch.inference_mode():
            batch = {k: v.to(device) for k, v in collate_encoded([encode(obs)]).items()}
            logits = model(batch)["policy_logits"].float()[0, :n]
            student = torch.softmax(logits, -1).cpu().numpy().astype(np.float64)

        self_kls = [kl(runs[a]["policy"], runs[b]["policy"])
                    for a in range(len(runs)) for b in range(a + 1, len(runs))]
        rows.append({
            "episode_index": episode["meta"]["episode_index"], "step": step, "actions": n,
            "teacher_self_kl": float(np.mean(self_kls)),
            "mean_teacher_kl": float(np.mean([kl(r["policy"], mean_policy) for r in runs])),
            "student_kl": kl(mean_policy, student),
            "student_class_agreement": float(np.mean([classes[int(np.argmax(student))] == r["class"] for r in runs])),
            "teacher_class_agreement": float(np.mean([runs[a]["class"] == runs[b]["class"]
                                                      for a in range(len(runs)) for b in range(a + 1, len(runs))])),
        })

    def mean(key):
        return float(np.mean([r[key] for r in rows]))

    report = {
        "scope": "development states only; diagnostic decomposition, not a strength result",
        "data": str(Path(args.data).resolve()), "checkpoint": str(args.checkpoint),
        "states": len(rows), "teacher_seeds": args.seeds, "teacher_budget": args.budget,
        "teacher_self_kl": mean("teacher_self_kl"),
        "mean_teacher_kl": mean("mean_teacher_kl"),
        "student_kl": mean("student_kl"),
        "student_excess_kl_over_teacher_self": mean("student_kl") - mean("teacher_self_kl"),
        "ratio_student_to_teacher_self": mean("student_kl") / max(mean("teacher_self_kl"), 1e-12),
        "teacher_class_agreement": mean("teacher_class_agreement"),
        "student_class_agreement": mean("student_class_agreement"),
        "per_state": rows,
        "caveats": [
            "Teacher runs are not samples from a fixed distribution: more simulations also "
            "change the distribution, so the self-KL is an empirical floor, not a theorem.",
            "All states come from one development split; these are correlated within a battle.",
        ],
    }
    atomic_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "per_state"}, indent=2))


if __name__ == "__main__":
    main()
