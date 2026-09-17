#!/usr/bin/env python3
"""Regenerate the fb9bf6e review reconciliations from already-saved artefacts.

Every subcommand here is a pure re-export: it reads checkpoints, collection
shards and closed-loop records that were produced before this review, and
performs inference or arithmetic only. No training, no new data, no teacher
budget change.

    paired        per-seed paired utility differences and win/loss crossovers
    coverage      training-set coverage plus the kl_dev/utility correspondence
    bridge        the 2x2 Brier reconciliation (old/new checkpoint x old/frozen constant)
    brier-scan    model Brier across matrix and pre-change checkpoints
    ambiguity     how many ambiguous coarse-intent states the training set holds
    loss-repro    numeric repro of the broadcasting defect in losses()
"""
import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np


def shards(directory):
    rows = []
    for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            rows += [json.loads(line) for line in handle if line.strip()]
    return rows


def bootstrap_mean(values, draws=4000, seed=21):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    draws_values = [float(np.mean(values[rng.integers(0, len(values), len(values))])) for _ in range(draws)]
    return float(values.mean()), [float(np.quantile(draws_values, 0.025)), float(np.quantile(draws_values, 0.975))]


# ---------------------------------------------------------------- paired
def cmd_paired(_args):
    records = [json.loads(line) for line in
               (ROOT / "reports/dev_closed_loop/episodes.jsonl").read_text().splitlines() if line.strip()]
    by = collections.defaultdict(dict)
    for record in records:
        by[record["episode_index"]][record["agent"]] = record
    order = sorted(by)

    def utility(index, agent):
        record = by[index].get(agent)
        return record["utility"] if record and record["completed"] else None

    def compare(a, b):
        deltas = []; a_better = b_better = tie = dropped = 0
        for index in order:
            x, y = utility(index, a), utility(index, b)
            if x is None or y is None:
                dropped += 1; continue
            deltas.append(x - y)
            a_better += x > y; b_better += y > x; tie += x == y
        mean, interval = bootstrap_mean(deltas)
        return {"n": len(deltas), "dropped": dropped, "mean": mean, "ci": interval,
                "a_better": a_better, "b_better": b_better, "tie": tie}

    models = [f"M128-R0-s{s}" for s in (17, 29, 43)] + [f"M192-R1-s{s}" for s in (17, 29, 43)]
    comparisons = [(f"{m} - heuristic", m, "heuristic") for m in models]
    comparisons += [("search - heuristic", "search", "heuristic")]
    comparisons += [(f"search - M128-R0-s{s}", "search", f"M128-R0-s{s}") for s in (17, 29, 43)]
    comparisons += [("M192-R1-s43 - M128-R0-s17", "M192-R1-s43", "M128-R0-s17")]

    print("=== per-seed paired utility differences (resampling SCENARIOS only, conditional on these checkpoints) ===")
    for label, a, b in comparisons:
        r = compare(a, b)
        print(f"{label:30s} n={r['n']} dropped={r['dropped']} mean={r['mean']:+.5f} "
              f"ci=[{r['ci'][0]:+.5f},{r['ci'][1]:+.5f}] | A>B {r['a_better']:3d}  "
              f"B>A {r['b_better']:3d}  tie {r['tie']:3d}")
    print()
    print("每行是【单个 checkpoint】对启发式，逐种子列出；不是三种子平均。")
    print("区间只对场景重采样，条件于当前这几个已训练模型，不重采样训练种子。")


# -------------------------------------------------------------- coverage
def cmd_coverage(_args):
    matrix = json.loads((ROOT / "reports/generalization_matrix.json").read_text())
    closed = json.loads((ROOT / "reports/dev_closed_loop/summary.json").read_text())
    utility = {k: v["mean_utility"] for k, v in closed["by_agent"].items()}
    wins = {k: v["wins"] for k, v in closed["by_agent"].items()}
    print("=== all 12 runs: kl_dev vs played utility (single-model numbers) ===")
    print(f"{'cell':14s} {'kl_dev':>9s} {'kl(dec)':>9s} {'policy_kl':>9s} {'utility':>9s} {'wins':>5s} {'params':>9s} {'best_step':>9s}")
    rows = sorted(matrix["by_cell"], key=lambda r: (r["d_model"], r["weight_decay"], r["init_seed"]))
    kls = [r["kl_dev"] for r in rows]; utils = [utility[r["cell"]] for r in rows]
    for r in rows:
        c = r["cell"]
        print(f"{c:14s} {r['kl_dev']:9.5f} {r['kl_over_decision_states']:9.5f} {r['policy_kl']:9.5f} "
              f"{utility[c]:9.5f} {wins[c]:5d} {r['parameters']:9d} {r['best_step']:9d}")
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); out = [0] * len(v)
        for pos, i in enumerate(order): out[i] = pos
        return out
    ra, rb = rank(kls), rank(utils); n = len(ra)
    rho = 1 - 6 * sum((ra[i] - rb[i]) ** 2 for i in range(n)) / (n * (n * n - 1))
    print(f"\nSpearman rho(kl_dev, utility) over 12 runs = {rho:+.3f}  (n=12; only 3 seeds per config)")
    print(f"exact rank agreement: {sum(1 for i in range(n) if ra[i] == rb[i])}/12")

    print("\n=== training data coverage (data/dev/train) ===")
    encounter = collections.Counter(); family = collections.Counter(); hp = []; total = decision = forced = 0
    for shard in sorted((ROOT / "data/dev/train").glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line); obs = row["observation"]; total += 1
                decision += len(obs["actions"]) > 1; forced += len(obs["actions"]) <= 1
                encounter[obs["enemies"][0]["id"] if obs["enemies"] else "NONE"] += 1
                family[row["family"]] += 1; hp.append(obs["player"]["hp"])
    episodes = len(list((ROOT / "data/dev/train").glob("episode_*.jsonl.gz")))
    print(f"independent episodes={episodes}  raw states={total}  decision states={decision} "
          f"({decision/total:.1%})  forced={forced}")
    print(f"encounter strata (states): {dict(sorted(encounter.items()))}")
    print(f"family strata (states): {dict(sorted(family.items()))}")
    hp = np.asarray(hp)
    print(f"player HP: min {hp.min()} p25 {np.percentile(hp,25):.0f} median {np.median(hp):.0f} "
          f"p75 {np.percentile(hp,75):.0f} max {hp.max()}")


# ---------------------------------------------------------------- bridge
def _model_death_probabilities(checkpoint, rows):
    import torch
    from stsai.encoding import collate_encoded, encode
    from stsai.model import load_checkpoint
    model, _ = load_checkpoint(checkpoint, "cuda")
    device = next(model.parameters()).device
    out = []
    with torch.inference_mode():
        for start in range(0, len(rows), 64):
            chunk = rows[start:start + 64]
            batch = {k: v.to(device) for k, v in collate_encoded([encode(r["observation"]) for r in chunk]).items()}
            probs = model(batch)["outcome_logits"].softmax(-1).float().cpu().numpy()
            out += [float(probs[i, 0]) for i in range(len(chunk))]
    return np.asarray(out)


def cmd_bridge(_args):
    import hashlib
    from pathlib import Path as P
    val = shards(ROOT / "data/dev/val"); train = shards(ROOT / "data/dev/train")
    y = np.array([np.asarray(r["outcome"], dtype=np.float64)[0] for r in val])
    q_eval = float(y.mean())
    q_frozen = float(np.mean([np.asarray(r["outcome"], dtype=np.float64)[0] for r in train]))
    print(f"rows={len(val)} battles={len({r['episode_id'] for r in val})} deaths={int(y.sum())}")
    print(f"q_eval   (evaluation-set death rate) = {q_eval:.10f}")
    print(f"q_frozen (frozen from data/dev/train) = {q_frozen:.10f}\n")
    for name, ckpt in [("dev_base2 (used by old calibration_val.json)", "runs/dev_base2/model/best.pt"),
                       ("M128-R0-s17 (used by this round)", "runs/matrix/M128-R0-s17/model/best.pt")]:
        p = _model_death_probabilities(ROOT / ckpt, val)
        model_brier = float(np.mean((p - y) ** 2))
        base_eval = float(np.mean((q_eval - y) ** 2)); base_frozen = float(np.mean((q_frozen - y) ** 2))
        print(f"{name}   sha256={hashlib.sha256((ROOT/ckpt).read_bytes()).hexdigest()}")
        print(f"   model Brier                     = {model_brier:.10f}")
        print(f"   baseline @ q_eval   = {base_eval:.10f}  ->  diff = {model_brier-base_eval:+.10f}")
        print(f"   baseline @ q_frozen = {base_frozen:.10f}  ->  diff = {model_brier-base_frozen:+.10f}\n")
    print("reviewer's conditional arithmetic used the OLD checkpoint:")
    print("   0.1177685950 + (0.24634-0.1363636364)^2 = 0.1298633956 -> diff -0.0397203303    <- reproduces")


def cmd_brier_scan(_args):
    val = shards(ROOT / "data/dev/val"); train = shards(ROOT / "data/dev/train")
    y = np.array([np.asarray(r["outcome"], dtype=np.float64)[0] for r in val])
    q = float(np.mean([np.asarray(r["outcome"], dtype=np.float64)[0] for r in train]))
    base = float(np.mean((q - y) ** 2))
    print(f"frozen baseline Brier (q={q:.9f}) = {base:.10f}\n")
    print(f"{'checkpoint':46s} {'model Brier':>13s} {'diff':>15s}")
    candidates = [("dev_base2 (old loss, old selection)", "runs/dev_base2/model/best.pt"),
                  ("dev_relabel (old loss, 256-sim labels)", "runs/dev_relabel/model/best.pt")]
    candidates += [(f"M128-R0-s{s}", f"runs/matrix/M128-R0-s{s}/model/best.pt") for s in (17, 29, 43)]
    candidates += [("M192-R0-s43", "runs/matrix/M192-R0-s43/model/best.pt"),
                   ("M192-R1-s43", "runs/matrix/M192-R1-s43/model/best.pt"),
                   ("M128-R0-s17 last.pt", "runs/matrix/M128-R0-s17/model/last.pt")]
    for name, ckpt in candidates:
        if not (ROOT / ckpt).exists():
            print(f"{name:46s} MISSING"); continue
        p = _model_death_probabilities(ROOT / ckpt, val)
        brier = float(np.mean((p - y) ** 2))
        print(f"{name:46s} {brier:13.10f} {brier-base:+15.10f}")


# ------------------------------------------------------------- ambiguity
AMBIGUOUS = {"JAW_WORM": ("ATTACK", "Chomp vs Thrash; the game shows ATTACK vs ATTACK_DEFEND"),
             "ACID_SLIME_M": ("ATTACK", "Corrosive Spit vs Tackle; the game shows ATTACK_DEBUFF vs ATTACK"),
             "LAGAVULIN": ("BUFF", "Sleep vs Siphon Soul; the game shows SLEEP vs DEBUFF"),
             "LOOTER": ("BUFF", "Escape vs Smoke Bomb; the game shows ESCAPE vs DEFEND")}


def cmd_ambiguity(_args):
    from stsai.native import NativeBattle
    from stsai.scenarios import NATIVE_ENCOUNTERS
    encounters = [e for v in NATIVE_ENCOUNTERS.values() for e in v]
    exported = set()
    for encounter in encounters:
        env = NativeBattle({"deck": ["DEFEND_RED"] * 10, "encounter": encounter, "ascension": 20,
                            "hp": 200, "max_hp": 200, "floor": 1, "act": 1, "potions": []}, 0)
        exported |= set(env.observe()["enemies"][0].keys())
    print("adapter exports per enemy:", sorted(exported))
    print("planned move exported:", "observed_move" in exported, "(must be False)")
    print()
    counts = collections.Counter(); decision = collections.Counter(); total = dec_total = 0
    for shard in sorted((ROOT / "data/dev/train").glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obs = json.loads(line)["observation"]; total += 1
                is_decision = len(obs["actions"]) > 1; dec_total += is_decision
                for enemy in obs["enemies"]:
                    spec = AMBIGUOUS.get(enemy["id"])
                    if spec and enemy["intent"] == spec[0]:
                        counts[enemy["id"]] += 1; decision[enemy["id"]] += is_decision
    print("training states whose enemy sits on an ambiguous COARSE intent:")
    for key in sorted(counts):
        print(f"  {key:14s} states={counts[key]:5d} ({counts[key]/total:6.2%})  "
              f"decision states={decision[key]:5d} ({decision[key]/dec_total:6.2%})")
    print(f"  TOTAL          states={sum(counts.values()):5d} ({sum(counts.values())/total:6.2%})  "
          f"decision states={sum(decision.values()):5d} ({sum(decision.values())/dec_total:6.2%})")
    print("\nall four pairs are separated by the real game's Intent enum:")
    for key, (_intent, why) in AMBIGUOUS.items():
        print(f"  {key:14s} {why}")


# ------------------------------------------------------------ loss-repro
def cmd_loss_repro(_args):
    import torch
    from stsai.training import losses
    batch, actions = 16, 4
    torch.manual_seed(0)
    logits = torch.randn(batch, actions)
    policy = torch.softmax(torch.randn(batch, actions), -1)
    decision = torch.ones(batch, dtype=torch.bool); decision[3] = decision[7] = decision[11] = False
    output = {"policy_logits": logits, "outcome_logits": torch.randn(batch, 11), "value": torch.rand(batch)}
    labels = {"policy": policy, "decision": decision,
              "outcome": torch.full((batch, 11), 1.0 / 11), "value": torch.rand(batch),
              "value_mask": torch.ones(batch)}
    elementwise = -(policy * logits.log_softmax(-1)).sum(-1)
    wrong = elementwise * decision.unsqueeze(-1)
    right = elementwise * decision
    print(f"elementwise {tuple(elementwise.shape)}  decision {tuple(decision.shape)}")
    print(f"current path (b,)*(b,1) -> {tuple(wrong.shape)}   <- outer product")
    print(f"intended     (b,)*(b,)  -> {tuple(right.shape)}")
    print(f"current  policy term = {float(wrong.sum()/decision.sum()):.4f}")
    print(f"intended policy term = {float(right.sum()/decision.sum()):.4f}")
    print(f"inflation            = {float(wrong.sum()/right.sum()):.2f}x")
    _, parts = losses(output, labels)
    print(f"\nlosses() actually returns policy_loss = {float(parts['policy_loss']):.4f}")
    print(f"measured on real runs: 16.90 (matrix) vs 1.07 (pre-change)")
    print(f"auxiliary heads unaffected: outcome={float(parts['outcome_loss']):.4f} value={float(parts['value_loss']):.4f}")


SUBCOMMANDS = {"paired": cmd_paired, "coverage": cmd_coverage, "bridge": cmd_bridge,
               "brier-scan": cmd_brier_scan, "ambiguity": cmd_ambiguity, "loss-repro": cmd_loss_repro}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(SUBCOMMANDS))
    args = parser.parse_args()
    SUBCOMMANDS[args.command](args)


if __name__ == "__main__":
    main()
