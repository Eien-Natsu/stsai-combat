"""Small, explicit development-statistics helpers; not a STSAI engine adapter.

Uses only Python + NumPy. No network access, model loading, or training.
KL terms are empirical, not an estimated population/Bayes noise floor.
Paired Brier analysis is conditional on a fixed predictor and frozen baseline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


def distribution(values: Any, name: str) -> np.ndarray:
    p = np.asarray(values, dtype=np.float64)
    if p.ndim != 1 or len(p) == 0:
        raise ValueError(f"{name} must be a nonempty 1D distribution")
    if not np.isfinite(p).all() or np.any(p < 0):
        raise ValueError(f"{name} contains invalid probabilities")
    if not np.isclose(p.sum(), 1.0, rtol=0.0, atol=1e-10):
        raise ValueError(f"{name} must sum to 1; no silent renormalization")
    return p


def kl(p: np.ndarray, q: np.ndarray) -> float:
    if p.shape != q.shape:
        raise ValueError("Distribution shapes differ")
    pos = p > 0
    if np.any(q[pos] == 0):
        return math.inf
    return float(np.sum(p[pos] * (np.log(p[pos]) - np.log(q[pos]))))


def decompose_teacher_kl(teacher_policies: Any, student_policy: Any) -> dict[str, Any]:
    raw = list(teacher_policies)
    if len(raw) < 2:
        raise ValueError("At least two teacher policies are required")
    teachers = [distribution(x, f"teacher[{i}]") for i, x in enumerate(raw)]
    student = distribution(student_policy, "student")
    if any(p.shape != student.shape for p in teachers):
        raise ValueError("All action spaces and lengths must match")
    mean_teacher = np.mean(np.stack(teachers), axis=0)
    losses = [kl(p, student) for p in teachers]
    if not np.isfinite(losses).all():
        raise ValueError("Student assigns zero mass to a positive teacher action; KL is infinite")
    spread = float(np.mean([kl(p, mean_teacher) for p in teachers]))
    gap = kl(mean_teacher, student)
    total = float(np.mean(losses))
    pairs = [kl(p, q) for i, p in enumerate(teachers)
             for j, q in enumerate(teachers) if i != j]
    infinite_pairs = sum(not math.isfinite(x) for x in pairs)
    return {
        "teacher_count": len(teachers),
        "actions": int(student.size),
        "teacher_mean_policy": mean_teacher.tolist(),
        "mean_teacher_to_student_kl": total,
        "empirical_teacher_spread_kl": spread,
        "empirical_mean_to_student_kl": gap,
        "gap_direction": "KL(mean_teacher || student)",
        "identity_residual": total - spread - gap,
        "pairwise_directed_teacher_kl_mean": None if infinite_pairs else float(np.mean(pairs)),
        "pairwise_infinite_terms": infinite_pairs,
        "is_population_noise_floor": False,
    }


def _probability(value: Any, name: str) -> float:
    x = float(value)
    if not math.isfinite(x) or not 0 <= x <= 1:
        raise ValueError(f"{name} must be finite and in [0, 1]")
    return x


def paired_brier(rows: list[dict[str, Any]], *, repetitions: int = 10000,
                 seed: int = 73021) -> dict[str, Any]:
    """Equal-weight means over independent clusters; resamples paired differences.

    Each row: cluster_id, sample_id, y, p_model, p_baseline. The caller defines
    a valid independent cluster (normally episode or scenario family), and
    MUST NOT mix trained models/seeds or unhandled unequal sampling weights.
    Duplicate keys are rejected. Baseline probabilities are supplied, never fit.
    """
    if repetitions < 100:
        raise ValueError("Use at least 100 bootstrap repetitions")
    if not rows:
        raise ValueError("No rows")
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    keys: set[tuple[str, str]] = set()
    deaths = 0
    for r in rows:
        if "weight" in r or "stratum" in r or "training_seed" in r:
            raise ValueError("Weighted/stratified/multi-seed designs need a design-specific analyzer")
        cid, sid = r.get("cluster_id"), r.get("sample_id")
        if not isinstance(cid, str) or not cid or not isinstance(sid, str) or not sid:
            raise ValueError("cluster_id and sample_id must be nonempty strings")
        if (cid, sid) in keys:
            raise ValueError("Duplicate (cluster_id, sample_id)")
        keys.add((cid, sid))
        y = float(r["y"])
        if not math.isfinite(y) or y not in (0.0, 1.0):
            raise ValueError("y must be 0 or 1 (death indicator)")
        p = _probability(r["p_model"], "p_model")
        q = _probability(r["p_baseline"], "p_baseline")
        groups[cid].append(((p-y)**2, (q-y)**2))
        deaths += int(y)
    if len(groups) < 2:
        raise ValueError("At least two independent clusters are required")
    names = sorted(groups)
    scores = np.asarray([np.mean(groups[k], axis=0) for k in names], dtype=np.float64)
    delta = scores[:, 0] - scores[:, 1]
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions, dtype=np.float64)
    # Bound temporary index-array size even for larger inputs.
    chunk = max(1, min(256, 1_000_000 // len(names)))
    for start in range(0, repetitions, chunk):
        count = min(chunk, repetitions-start)
        ix = rng.integers(0, len(names), size=(count, len(names)))
        draws[start:start+count] = delta[ix].mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975]).tolist()
    warnings = [
        "Exploratory percentile bootstrap conditional on fixed predictions and frozen baseline",
        "Cluster independence, sampling design, and baseline provenance are caller responsibilities",
        "No correction for repeated selection, optional stopping, or training-seed uncertainty",
        "Repeated y values in a trajectory are not independent death events",
    ]
    if len(names) < 20:
        warnings.append("Fewer than 20 clusters; interval estimation is particularly fragile")
    return {
        "estimand": "equal-weight mean of within-cluster mean Brier scores",
        "rows": len(rows), "clusters": len(names), "positive_label_rows": deaths,
        "model_brier": float(scores[:, 0].mean()),
        "baseline_brier": float(scores[:, 1].mean()),
        "difference_model_minus_baseline": float(delta.mean()),
        "difference_percentile_interval_95": [low, high],
        "lower_is_better": True,
        "bootstrap_repetitions": repetitions, "bootstrap_seed": seed,
        "cluster_scores": [
            {"cluster_id": k, "rows": len(groups[k]), "model_brier": float(scores[i, 0]),
             "baseline_brier": float(scores[i, 1]), "difference": float(delta[i])}
            for i, k in enumerate(names)
        ],
        "warnings": warnings,
    }


def analyze_kl_document(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("score_space") not in ("action_id", "equivalence_class"):
        raise ValueError("score_space must be action_id or equivalence_class")
    states = doc.get("states")
    if not isinstance(states, list) or not states:
        raise ValueError("states must be a nonempty list")
    seen = set()
    result = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in states:
        sid, eid = s.get("state_id"), s.get("episode_id")
        if not isinstance(sid, str) or not sid or not isinstance(eid, str) or not eid:
            raise ValueError("state_id and episode_id must be nonempty strings")
        key = (eid, sid)
        if key in seen:
            raise ValueError("Duplicate (episode_id, state_id)")
        seen.add(key)
        action_keys = s.get("action_keys")
        if not isinstance(action_keys, list) or not action_keys or any(
            not isinstance(a, str) or not a for a in action_keys
        ) or len(set(action_keys)) != len(action_keys):
            raise ValueError("action_keys must be unique nonempty strings in shared distribution order")
        d = decompose_teacher_kl(s["teacher_policies"], s["student_policy"])
        if len(action_keys) != d["actions"]:
            raise ValueError("action_keys length differs from policy length")
        d.update({"state_id": sid, "episode_id": eid, "forced_action": len(action_keys) == 1})
        result.append(d)
        if len(action_keys) > 1:
            groups[eid].append(d)
    terms = ["mean_teacher_to_student_kl", "empirical_teacher_spread_kl", "empirical_mean_to_student_kl"]
    macro = {
        term: float(np.mean([np.mean([r[term] for r in values]) for values in groups.values()]))
        if groups else None for term in terms
    }
    return {
        "score_space": doc["score_space"], "per_state": result,
        "decision_episodes": len(groups),
        "decision_states": sum(len(x) for x in groups.values()),
        "episode_macro_decision_means": macro,
        "notes": ["Empirical decomposition, not a population noise-floor estimate",
                  "No confidence interval inferred from the number of correlated states",
                  "Action order, equivalence validity, public histories and teacher versions are not verified here"],
    }


def write_json(path: Path, data: dict[str, Any], *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}; pass --force explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["kl", "paired-brier"])
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--repetitions", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=73021)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    try:
        doc = json.loads(args.input.read_text(encoding="utf-8"))
        if args.mode == "kl":
            result = analyze_kl_document(doc)
        else:
            if doc.get("design") != "fixed_predictor_equal_weight_independent_clusters":
                raise ValueError("Set design to fixed_predictor_equal_weight_independent_clusters only when justified")
            if not isinstance(doc.get("baseline_provenance"), str) or not doc["baseline_provenance"]:
                raise ValueError("Provide baseline_provenance; baseline must be frozen outside this evaluation set")
            result = paired_brier(doc["rows"], repetitions=args.repetitions, seed=args.seed)
            result["baseline_provenance"] = doc["baseline_provenance"]
        write_json(args.output, result, overwrite=args.force)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
