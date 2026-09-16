#!/usr/bin/env python3
"""Can the network represent the teacher at all? A bounded overfit probe.

Takes a fixed, small set of development states and freezes the teacher's soft
labels away from the live search. Dropout, weight decay and the value/outcome
auxiliary losses are switched off and the run is FP32, so the only question
left is whether the policy head can drive the cross-entropy down to the
teacher's own entropy. A failure here is an implementation problem -- input
aliasing, action misalignment, masking, optimisation -- not a generalisation
result. Success here says nothing about validation performance.

Also reports input collisions: states whose ENCODED input is identical but
whose teacher labels differ. Those are unfittable by construction, so they are
counted and excluded rather than silently averaged into the target.
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import torch

from stsai.encoding import encode, collate_encoded, ENCODING_REVISION
from stsai.model import CombatNet, ModelConfig, resolve_device
from stsai.util import atomic_json, SCHEMA_VERSION


def load_rows(directories, limit=None):
    import gzip
    rows = []
    for directory in directories:
        for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                rows += [json.loads(line) for line in handle if line.strip()]
            if limit and len(rows) >= limit:
                break
    return rows


def input_key(encoded):
    """Stable hash of exactly what the network sees."""
    parts = [encoded.ids.tobytes(), encoded.features.astype(np.float32).tobytes(),
             encoded.action_kind.tobytes(), encoded.action_sources.tobytes(),
             encoded.action_target.tobytes(), encoded.action_features.astype(np.float32).tobytes()]
    return hashlib.sha256(b"".join(parts)).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--states", type=int, default=256)
    parser.add_argument("--updates", type=int, default=1500)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    device = resolve_device(args.device)

    rows = [r for r in load_rows(args.data) if len(r["policy"]) > 1][:args.states]
    if not rows:
        raise SystemExit("No decision states available")
    encoded = [encode(r["observation"]) for r in rows]
    keys = [input_key(e) for e in encoded]

    groups = defaultdict(list)
    for index, key in enumerate(keys):
        groups[key].append(index)
    collisions = {}
    for key, members in groups.items():
        if len(members) < 2:
            continue
        first = np.asarray(rows[members[0]]["policy"], dtype=np.float64)
        if any(not np.allclose(first, np.asarray(rows[m]["policy"], dtype=np.float64))
               for m in members[1:]):
            collisions[key] = members
    dropped = {m for members in collisions.values() for m in members}

    keep = [i for i in range(len(rows)) if i not in dropped]
    batch = collate_encoded([encoded[i] for i in keep])
    policy = torch.zeros_like(batch["action_mask"], dtype=torch.float32)
    for slot, i in enumerate(keep):
        p = torch.tensor(rows[i]["policy"], dtype=torch.float32)
        policy[slot, :len(p)] = p
    batch = {k: v.to(device) for k, v in batch.items()}
    policy = policy.to(device)
    legal = policy > 0
    logp_target = torch.log(policy.clamp_min(1e-12))
    teacher_entropy = float((-(policy * logp_target)[legal]).sum() / policy.shape[0])

    model = CombatNet(ModelConfig(d_model=128, layers=4, heads=4, dropout=0.0)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=0.0)
    model.train()

    curve = []
    for step in range(1, args.updates + 1):
        logits = model(batch)["policy_logits"].float()
        logp = logits.log_softmax(-1)
        kl = (policy * (logp_target - logp))[legal].sum() / policy.shape[0]
        optimizer.zero_grad(set_to_none=True)
        kl.backward()
        optimizer.step()
        if step == 1 or step % max(1, args.updates // 15) == 0 or step == args.updates:
            curve.append({"step": step, "train_kl": float(kl.detach())})

    final_kl = curve[-1]["train_kl"]
    report = {
        "scope": "bounded representability probe on frozen development labels; not a model-selection run",
        "data": [str(Path(d).resolve()) for d in args.data],
        "encoding_revision": ENCODING_REVISION, "observation_schema": SCHEMA_VERSION,
        "states_considered": len(rows), "states_used": len(keep),
        "input_collisions": {"groups": len(collisions), "states_dropped": len(dropped),
                             "note": "identical encoded input with different teacher labels; unfittable by construction"},
        "teacher_entropy_on_used_states": teacher_entropy,
        "updates": args.updates, "learning_rate": args.lr, "device": str(device),
        "final_train_kl": final_kl, "curve": curve,
        "target": 0.01, "target_met": final_kl <= 0.01,
        "caveat": "Fitting 256 frozen states is an engineering check, not evidence of battle strength.",
    }
    atomic_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "curve"}, indent=2))
    print("curve:", [(c["step"], round(c["train_kl"], 5)) for c in curve])


if __name__ == "__main__":
    main()
