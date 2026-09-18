"""Diagnose the batch-partition invariance failure from CI run 35369602279.

Observation only: this script calls the unmodified `stsai.training.train` for the
three partitions the failing test uses (32x1, 16x2, 8x4 of the same 32 samples)
and records, for every parameter, the pre-step gradient, the AdamW update that
was applied and the resulting difference against the reference partition.

`torch.optim.AdamW.step` is wrapped so the pre-step gradient can be read; the
original implementation is what actually runs, so loss, optimizer and model
semantics are untouched.

Usage:
    python reports/s2r/t0_partition_diagnose.py --out /tmp/t0.json
"""
from __future__ import annotations
import argparse
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import torch  # noqa: E402

import stsai  # noqa: E402
from stsai.model import CombatNet, ModelConfig  # noqa: E402
from stsai.util import LOSS_REVISION  # noqa: E402

import test_training_loss as ttl  # noqa: E402  (the failing test's own helpers)

PARTITIONS = ((32, 1), (16, 2), (8, 4))


def parameter_names(model_config):
    """Parameter index -> name, in the order `model.parameters()` yields them."""
    model = CombatNet(ModelConfig(**model_config))
    return [name for name, _ in model.named_parameters()]


def run_partition(batch, accum, train_dir, val_dir, out, names, capture):
    """One `train()` call with its single optimizer step observed."""
    original_step = torch.optim.AdamW.step

    def spy(self, *args, **kwargs):
        params = [p for group in self.param_groups for p in group["params"]]
        before = [p.detach().clone() for p in params]
        grads = [None if p.grad is None else p.grad.detach().clone() for p in params]
        result = original_step(self, *args, **kwargs)   # the real update
        capture.append({"grads": grads, "before": before,
                        "after": [p.detach().clone() for p in params]})
        return result

    torch.optim.AdamW.step = spy
    try:
        ttl.train([str(train_dir)], [str(val_dir)], str(out), backend=ttl.BACKEND,
                  device="cpu", config=ttl._config(batch, accum))
    finally:
        torch.optim.AdamW.step = original_step

    state = torch.load(out / "last.pt", map_location="cpu", weights_only=True)
    if not capture:
        raise SystemExit(f"no optimizer step was observed for batch={batch} accum={accum}")
    return {
        "state": state["model_state"],
        "steps": len(capture),
        "grads": {names[i]: capture[0]["grads"][i] for i in range(len(names))},
        "before": {names[i]: capture[0]["before"][i] for i in range(len(names))},
        "after": {names[i]: capture[0]["after"][i] for i in range(len(names))},
    }


def tensor_summary(value):
    if value is None:
        return None
    flat = value.float().flatten()
    return {"shape": list(value.shape), "abs_max": float(flat.abs().max()),
            "abs_sum": float(flat.abs().sum()), "numel": int(flat.numel())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--keep", default="")
    args = parser.parse_args()

    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="t0-partition-"))
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    train_dir = ttl.build_collection(work / "train", "train")
    val_dir = ttl.build_collection(work / "val", "val", episodes=3, steps=6)

    names = parameter_names(ttl._config(32, 1)["model"])
    report = {"environment": {
        "python": sys.version.split()[0], "platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor(),
        "torch": torch.__version__, "torch_cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "stsai_module": stsai.__file__, "loss_revision": LOSS_REVISION,
        "cpu_count": torch.get_num_threads(), "work": str(work)},
        "partitions": {}}

    states = {}
    for batch, accum in PARTITIONS:
        key = f"{batch}x{accum}"
        capture = []
        torch.manual_seed(0)
        observed = run_partition(batch, accum, train_dir, val_dir, work / key, names, capture)
        states[key] = observed["state"]
        report["partitions"][key] = {
            "optimizer_steps_observed": observed["steps"],
            "parameter_difference_vs_32x1": None,
            "gradient": tensor_summary(observed["grads"]["policy.2.bias"]),
            "adamw_update": tensor_summary(observed["after"]["policy.2.bias"]
                                           - observed["before"]["policy.2.bias"]),
            "value_before": float(observed["before"]["policy.2.bias"].flatten()[0]),
            "value_after": float(observed["after"]["policy.2.bias"].flatten()[0]),
            "policy_bias_gradient_raw": [float(x) for x in
                                         observed["grads"]["policy.2.bias"].flatten()],
            "policy_bias_update_raw": [float(x) for x in
                                       (observed["after"]["policy.2.bias"]
                                        - observed["before"]["policy.2.bias"]).flatten()],
            "gradient_abs_max_all_parameters": sorted(
                ((name, tensor_summary(g)["abs_max"]) for name, g in observed["grads"].items()),
                key=lambda item: -item[1])[:8],
        }

    reference = states["32x1"]
    for key, state in states.items():
        rows = []
        for name in reference:
            diff = (reference[name].float() - state[name].float()).abs().max().item()
            rows.append((name, diff, reference[name].float().abs().max().item()))
        rows.sort(key=lambda row: -row[1])
        report["partitions"][key]["parameter_difference_vs_32x1"] = [
            {"parameter": name, "max_abs_diff": diff, "reference_abs_max": scale}
            for name, diff, scale in rows[:8]]
        report["partitions"][key]["max_abs_diff_over_all_parameters"] = rows[0][1]
        report["partitions"][key]["allclose_at_1e-5_rtol_1e-4"] = all(
            bool(torch.allclose(reference[name], state[name], atol=1e-5, rtol=1e-4))
            for name in reference)

    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk in ("allclose_at_1e-5_rtol_1e-4", "max_abs_diff_over_all_parameters",
                                    "gradient", "adamw_update", "value_before", "value_after")}
                      for k, v in report["partitions"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
