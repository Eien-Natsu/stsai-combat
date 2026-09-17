#!/usr/bin/env python3
"""Independent action-value audit of teacher-versus-student disagreements.

The teacher's own maximum Q is not evidence: it is produced by the same search
being audited. Here each disputed root is evaluated by rolling BOTH actions
forward under one frozen continuation policy, using belief samples drawn
independently of the search that produced the teacher's choice.

    delta(root) = E[U | teacher_action, continuation] - E[U | student_action, continuation]

This is a value difference under one fixed continuation, not a global regret.
Roots are reached by replaying the recorded scenario and action prefix; the
public observation hash is checked at every step and a mismatch aborts that root
and is counted. Branches that never finish carry no utility and are reported as
truncated rather than dropped quietly.
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

from stsai.contracts import observation_key
from stsai.objective import terminal_utility
from stsai.scenarios import make_env
from stsai.search import BeliefSearch, HeuristicEvaluator, SearchConfig
from stsai.util import atomic_json, seed_for

SAMPLES_PER_BRANCH = 64
ROLLOUT_LIMIT = 256


def action_class(obs, action):
    if action["kind"] != "play":
        return ("other", action["kind"], action.get("card_id"), action.get("target"))
    source = obs["hand"][action["source"]]
    return ("play", action["card_id"], action.get("target"), source.get("upgraded"),
            source.get("cost"), source.get("exhaust"), source.get("ethereal"),
            source.get("free"), source.get("retain"), source.get("special"), source.get("type"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default="reports/dev_closed_loop/dev_scenarios.json")
    parser.add_argument("--checkpoint", required=True, help="frozen continuation policy")
    parser.add_argument("--roots", type=int, default=64)
    parser.add_argument("--samples", type=int, default=SAMPLES_PER_BRANCH)
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from stsai.model import ModelEvaluator
    continuation = ModelEvaluator.from_checkpoint(args.checkpoint, args.device, "lightspeed_pilot")
    base = json.loads((ROOT / args.config).read_text())["search"]

    frozen = json.loads((ROOT / args.scenarios).read_text())
    scenarios = frozen["scenarios"]

    # Root rule, fixed before any audit result is seen: the FIRST decision state
    # of the episode, one root per episode, episodes taken in frozen order. The
    # root distribution is therefore episode-balanced, not action-balanced.
    def advance_to_first_decision(env):
        """Play the forced prefix with one deterministic rule until a choice exists."""
        obs = env.observe()
        for _ in range(ROLLOUT_LIMIT):
            if obs["terminal"] or len(obs["actions"]) > 1:
                return obs
            obs = env.step(obs["actions"][0])
        return obs

    roots = []
    replay_failures = []
    for entry in scenarios:
        if len(roots) >= args.roots:
            break
        # Reach the root twice from the same frozen scenario+seed and require the
        # public hash to agree, so a root is only audited if it reproduces.
        probe = advance_to_first_decision(make_env("lightspeed_pilot", entry["scenario"], entry["episode_seed"]))
        if probe["terminal"] or len(probe["actions"]) <= 1:
            continue
        env = make_env("lightspeed_pilot", entry["scenario"], entry["episode_seed"])
        obs = advance_to_first_decision(env)
        if observation_key(obs) != observation_key(probe):
            replay_failures.append(entry["index"])
            continue
        roots.append({"entry": entry, "env": env, "obs": obs})

    rows = []
    started = time.perf_counter()
    for root in roots:
        entry, env, obs = root["entry"], root["env"], root["obs"]
        n = len(obs["actions"])
        classes = [action_class(obs, a) for a in obs["actions"]]
        teacher_result = BeliefSearch(SearchConfig(**base)).run(obs, env.sampler(), 900_000 + entry["index"])
        teacher_index = next(i for i, a in enumerate(obs["actions"])
                             if a["id"] == teacher_result["action"]["id"])
        student_probs, _ = continuation.evaluate(obs)
        student_index = int(np.argmax(student_probs))

        if classes[teacher_index] == classes[student_index]:
            rows.append({"episode_index": entry["index"], "encounter": entry["encounter"],
                         "agree": True, "delta": 0.0, "teacher_action": teacher_index,
                         "student_action": student_index, "mc_se": 0.0,
                         "teacher_truncated": 0, "student_truncated": 0})
            continue

        branch = {}
        for label, index in (("teacher", teacher_index), ("student", student_index)):
            utilities = []; truncated = 0
            for sample in range(args.samples):
                # Stable derivation: Python's hash() is salted per process, so it
                # would make the audit unreproducible across runs.
                sim = env.sampler()(seed_for("audit-sample", entry["index"], label, sample))
                state = sim.step(sim.observe()["actions"][index]) if not sim.observe()["terminal"] else sim.observe()
                for _ in range(ROLLOUT_LIMIT):
                    if state["terminal"]:
                        break
                    probs, _ = continuation.evaluate(state)
                    state = sim.step(state["actions"][int(np.argmax(probs))])
                if state["terminal"]:
                    utilities.append(terminal_utility(state, base.get("potion_cost", 0.02)))
                else:
                    truncated += 1
            branch[label] = {"utilities": utilities, "truncated": truncated}
        values = {k: (float(np.mean(v["utilities"])) if v["utilities"] else None) for k, v in branch.items()}
        delta = None if values["teacher"] is None or values["student"] is None else values["teacher"] - values["student"]
        se = float(np.sqrt(np.var(branch["teacher"]["utilities"], ddof=1) / max(1, len(branch["teacher"]["utilities"]))
                           + np.var(branch["student"]["utilities"], ddof=1) / max(1, len(branch["student"]["utilities"])))) \
            if len(branch["teacher"]["utilities"]) > 1 and len(branch["student"]["utilities"]) > 1 else None
        rows.append({"episode_index": entry["index"], "encounter": entry["encounter"], "agree": False,
                     "delta": delta, "mc_se": se, "teacher_action": teacher_index,
                     "student_action": student_index,
                     "teacher_value": values["teacher"], "student_value": values["student"],
                     "teacher_truncated": branch["teacher"]["truncated"],
                     "student_truncated": branch["student"]["truncated"],
                     "teacher_samples": len(branch["teacher"]["utilities"]),
                     "student_samples": len(branch["student"]["utilities"])})

    disputed = [r for r in rows if not r["agree"] and r["delta"] is not None]
    all_deltas = [r["delta"] for r in rows if r["delta"] is not None]
    by_battle = defaultdict(list)
    for r in rows:
        if r["delta"] is not None:
            by_battle[r["episode_index"]].append(r["delta"])
    battle_means = [float(np.mean(v)) for v in by_battle.values()]

    def bootstrap(values, draws=2000, seed=11):
        if len(values) < 2:
            return None
        rng = np.random.default_rng(seed)
        arr = np.asarray(values)
        return [float(np.quantile([np.mean(arr[rng.integers(0, len(arr), len(arr))]) for _ in range(draws)], q))
                for q in (0.025, 0.975)]

    report = {
        "scope": "development action-value audit under one frozen continuation policy; not a strength claim",
        "continuation_policy": str(args.checkpoint),
        "root_rule": "first decision state of each episode, one root per episode, frozen episode order",
        "roots_requested": args.roots, "roots_used": len(rows), "replay_failures": replay_failures,
        "agreements": sum(1 for r in rows if r["agree"]),
        "disagreements": len(disputed),
        "delta_mean_all_roots": float(np.mean(all_deltas)) if all_deltas else None,
        "delta_bootstrap95_all_roots": bootstrap(all_deltas),
        "delta_mean_disputed_only": float(np.mean([r["delta"] for r in disputed])) if disputed else None,
        "delta_bootstrap95_disputed_only": bootstrap([r["delta"] for r in disputed]),
        "delta_mean_one_per_battle": float(np.mean(battle_means)) if battle_means else None,
        "delta_bootstrap95_one_per_battle": bootstrap(battle_means),
        "median_within_root_mc_se": float(np.median([r["mc_se"] for r in disputed if r["mc_se"]])) if disputed else None,
        "truncated_branches": sum(r.get("teacher_truncated", 0) + r.get("student_truncated", 0) for r in disputed),
        "elapsed_seconds": time.perf_counter() - started,
        "caveats": [
            "Values are expectations under one frozen continuation, not the optimal value of either action.",
            "Agreements are kept in the totals as delta 0, so the mean is over all audited roots.",
            "Belief samples are the adapter's independent-RNG approximation, not the game's posterior.",
        ],
    }
    atomic_json(args.output, report)
    with (Path(args.output).with_suffix(".jsonl")).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
