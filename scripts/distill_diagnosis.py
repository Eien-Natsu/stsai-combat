#!/usr/bin/env python3
"""Decompose the distillation gap on already-collected development states.

The headline number this replaces ("teacher top-1 agreement") compared the
student's argmax against the argmax of the teacher's VISIT distribution. But
the teacher does not act on that argmax: BeliefSearch breaks visit ties by Q.
On any state where the visits tie, the two disagree, and the student is marked
wrong for copying what the teacher actually did.

Every row therefore reports several different things and never conflates them:

  raw_top1      student argmax vs policy argmax   (the old metric)
  te_choice     student argmax vs the teacher's real action (reconstructed)
  tie_tolerant  student argmax among the visit-maximal actions
  class_agree   agreement after conservative action equivalence classes
  kl / ce / H   policy divergence, with the teacher's own entropy shown so a
                "plateau" is not mistaken for a capacity wall

Runs on development data only. Never point this at a frozen test manifest.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import torch

from stsai.encoding import encode, collate_encoded
from stsai.model import load_checkpoint
from stsai.util import atomic_json

EPS = 1e-12


def load_rows(directories, limit=None):
    import gzip
    rows = []
    for directory in directories:
        for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                return rows[:limit]
    return rows[:limit] if limit else rows


def teacher_choice(policy, q):
    """Reproduce BeliefSearch's root selection: max visits, ties broken by Q."""
    return max(range(len(policy)), key=lambda j: (policy[j], q[j]))


def action_class(obs, action):
    """Conservative identity for an action; None means 'do not merge'.

    Same card name is NOT enough: upgrade count, current cost, free-play, retain
    and special instance data all change the outcome. Different enemy slots are
    never merged even when both monsters share a name.
    """
    if action["kind"] != "play":
        return ("other", action["kind"], action.get("card_id"), action.get("target"))
    source = obs["hand"][action["source"]]
    return ("play", action["card_id"], action.get("target"), source.get("upgraded"),
            source.get("cost"), source.get("exhaust"), source.get("ethereal"),
            source.get("free"), source.get("retain"), source.get("special"), source.get("type"))


def page(model, device, observations, batch_size=64):
    """Student probabilities for a list of observations, memory-bounded."""
    out = []
    with torch.inference_mode():
        for start in range(0, len(observations), batch_size):
            chunk = observations[start:start + batch_size]
            batch = {k: v.to(device) for k, v in collate_encoded([encode(o) for o in chunk]).items()}
            logits = model(batch)["policy_logits"].float()
            for i, obs in enumerate(chunk):
                n = len(obs["actions"])
                out.append(torch.log_softmax(logits[i, :n], -1).cpu().numpy())
    return out


def entropy(p):
    p = np.asarray(p, dtype=np.float64)
    nz = p > 0
    return float(-(p[nz] * np.log(p[nz])).sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", nargs="+", required=True, help="development collection dirs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--per-state", default="", help="optional JSONL of one row per state")
    args = parser.parse_args()

    model, checkpoint = load_checkpoint(args.checkpoint, args.device)
    device = next(model.parameters()).device
    rows = load_rows(args.data, args.limit or None)
    if not rows:
        raise SystemExit("No development rows found")

    observations = [r["observation"] for r in rows]
    logs = page(model, device, observations)

    per_state = []
    strata = defaultdict(list)
    for row, obs, logp in zip(rows, observations, logs):
        n = len(obs["actions"])
        policy = np.asarray(row["policy"][:n], dtype=np.float64)
        policy = policy / max(policy.sum(), EPS)
        q = row.get("search_q") or [0.0] * n
        student = logp.argmax()

        visits = policy
        visit_max = float(visits.max())
        tied = [j for j in range(n) if visits[j] >= visit_max - 1e-12]
        teacher = teacher_choice(policy.tolist(), list(q))
        # Older shards predate the explicit column; reconstruct from the same
        # rule the search used, and say so rather than pretending it was stored.
        stored = row.get("teacher_action_index")
        teacher_source = "stored" if stored is not None else "reconstructed"
        if stored is not None:
            teacher = stored

        kl = float(sum(policy[j] * (math.log(max(policy[j], EPS)) - logp[j]) for j in range(n) if policy[j] > 0))
        teacher_h = entropy(policy)
        ce = kl + teacher_h

        student_class = action_class(obs, obs["actions"][student])
        teacher_class = action_class(obs, obs["actions"][teacher])
        classes = [action_class(obs, a) for a in obs["actions"]]
        class_mass_student = sum(policy[j] for j in range(n) if classes[j] == student_class)

        record = {
            "episode_index": row.get("episode_index"), "family": row.get("family"),
            "turn": obs["turn"], "actions": n,
            "raw_top1": int(student == int(np.argmax(policy))),
            "te_choice": int(student == teacher),
            "tie_tolerant": int(student in tied),
            "class_agree": int(student_class == teacher_class),
            "kl": kl, "teacher_entropy": teacher_h, "ce": ce,
            "teacher_source": teacher_source,
            "visit_tie": int(len(tied) > 1),
            "sampled_action": bool(row.get("sampled_action", False)),
            "best_class_gap": (1.0 - class_mass_student) if n > 1 else 0.0,
        }
        per_state.append(record)
        if n > 1:
            strata["encounter:" + str(obs["enemies"][0]["id"] if obs["enemies"] else "none")].append(record)
            strata["hp_band:" + ("low" if obs["player"]["hp"] <= obs["player"]["max_hp"] * 0.35 else
                                 "mid" if obs["player"]["hp"] <= obs["player"]["max_hp"] * 0.7 else "high")].append(record)
            strata["turn_band:" + ("early" if obs["turn"] <= 2 else "mid" if obs["turn"] <= 5 else "late")].append(record)
            strata["legal_actions:" + ("2-3" if n <= 3 else "4-6" if n <= 6 else "7+")].append(record)

    def summarise(items):
        if not items:
            return None
        return {
            "states": len(items),
            "raw_top1": float(np.mean([r["raw_top1"] for r in items])),
            "te_choice": float(np.mean([r["te_choice"] for r in items])),
            "tie_tolerant": float(np.mean([r["tie_tolerant"] for r in items])),
            "class_agree": float(np.mean([r["class_agree"] for r in items])),
            "kl": float(np.mean([r["kl"] for r in items])),
            "teacher_entropy": float(np.mean([r["teacher_entropy"] for r in items])),
            "ce": float(np.mean([r["ce"] for r in items])),
            "visit_tie_rate": float(np.mean([r["visit_tie"] for r in items])),
        }

    forced = [r for r in per_state if r["actions"] == 1]
    decision = [r for r in per_state if r["actions"] > 1]
    # Where the old metric and the teacher's real action disagree, the old metric
    # was punishing the student for being right.
    metric_split = [r for r in decision if r["raw_top1"] != r["te_choice"]]

    report = {
        "scope": "development data only; never a frozen test manifest",
        "checkpoint": str(args.checkpoint),
        "data": [str(Path(d).resolve()) for d in args.data],
        "device": str(device),
        "states_total": len(per_state),
        "states_forced_single_action": len(forced),
        "all": summarise(per_state),
        "decision_states": summarise(decision),
        "forced_states": summarise(forced),
        "metric_disagreement": {
            "states_where_old_metric_and_teacher_choice_differ": len(metric_split),
            "share_of_decision_states": len(metric_split) / max(1, len(decision)),
            "note": "on these states policy.argmax() is not the action the search played",
        },
        "strata": {k: summarise(v) for k, v in sorted(strata.items())},
        "teacher_source": {"stored": sum(1 for r in per_state if r["teacher_source"] == "stored"),
                           "reconstructed": sum(1 for r in per_state if r["teacher_source"] == "reconstructed")},
        "caveats": [
            "States within one battle are correlated; these are not independent samples.",
            "Soft targets have a minimum achievable cross-entropy equal to the teacher entropy, not zero.",
            "Teacher visits are not calibrated probabilities and are not optimal values.",
        ],
    }
    atomic_json(args.output, report)
    if args.per_state:
        with open(args.per_state, "w", encoding="utf-8") as handle:
            for record in per_state:
                handle.write(json.dumps(record) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("strata",)}, indent=2))
    print("\nstrata:")
    for name, summary in report["strata"].items():
        print(f"  {name:28s} n={summary['states']:5d} raw_top1={summary['raw_top1']:.3f} "
              f"te_choice={summary['te_choice']:.3f} class={summary['class_agree']:.3f} "
              f"kl={summary['kl']:.4f} H_teacher={summary['teacher_entropy']:.4f}")


if __name__ == "__main__":
    main()
