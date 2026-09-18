#!/usr/bin/env python3
"""Load a shipped checkpoint and check it against the shipped public expectations.

    python review/model_smoke.py --model model/policy_weights.pt --out smoke.json

The observations are the public ones in model/smoke_observations.jsonl.gz; the
expected action, probabilities and value are in model/smoke_expected.json. This
is a load-and-run check for the delivered weights, not a strength measurement:
it says the file loads under the current semantics and reproduces the recorded
numbers on CPU FP32, with a stated tolerance.

A tie is not a failure: if the recorded top two probabilities are equal within
the tie epsilon, any argmax among them is accepted, because different float
backends may order an exact tie differently.
"""
import argparse
import gzip
import json
from pathlib import Path

TOLERANCE = 1e-4
TIE_EPSILON = 1e-6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--observations", default="model/smoke_observations.jsonl.gz")
    parser.add_argument("--expected", default="model/smoke_expected.json")
    parser.add_argument("--out", default="model_smoke.json")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args()

    from stsai.model import ModelEvaluator

    paths = []
    with gzip.open(args.observations, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                paths.append(json.loads(line))
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    if len(expected["cases"]) != len(paths):
        raise SystemExit(f"{len(paths)} observations but {len(expected['cases'])} expected cases")

    evaluator = ModelEvaluator.from_checkpoint(args.model, device="cpu")
    observations = [case["observation"] for case in paths]
    results = evaluator.evaluate_batch(observations)

    report = {"model": str(args.model), "tolerance": args.tolerance,
              "tie_epsilon": TIE_EPSILON, "device": "cpu", "cases": []}
    failures = []
    for index, (case, (probs, value)) in enumerate(zip(expected["cases"], results)):
        got_action = max(range(len(probs)), key=lambda i: probs[i])
        want_probs = case["probabilities"]
        want_action = case["action_index"]
        tie = len(want_probs) > 1 and (sorted(want_probs)[-1] - sorted(want_probs)[-2]) <= TIE_EPSILON
        action_ok = got_action == want_action or (tie and want_probs[got_action] >= max(want_probs) - TIE_EPSILON)
        prob_delta = max(abs(a - b) for a, b in zip(probs, want_probs))
        value_delta = abs(value - case["value"])
        entry = {"index": index, "actions": len(probs), "action_index": got_action,
                 "expected_action_index": want_action, "action_ok": action_ok, "tie": tie,
                 "max_probability_delta": prob_delta, "value": value,
                 "value_delta": value_delta,
                 "ok": bool(action_ok and prob_delta <= args.tolerance
                            and value_delta <= args.tolerance)}
        report["cases"].append(entry)
        if not entry["ok"]:
            failures.append(entry)

    report["cases_checked"] = len(report["cases"])
    report["failures"] = failures
    report["passed"] = not failures
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    worst = max((c["max_probability_delta"] for c in report["cases"]), default=0.0)
    print(f"{report['cases_checked']} observations loaded and run; "
          f"max probability delta {worst:.2e}; {len(failures)} failures")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
