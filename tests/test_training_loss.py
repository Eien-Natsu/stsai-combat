"""Regression tests for the objective's counting rules (S1-A).

The effective batch is defined as every microbatch inside one optimizer update,
so the policy term is `sum_i d_i*CE_i / sum_i d_i` over that whole window rather
than an unweighted average of per-microbatch means. These tests pin the unit
contract, the hand-computed value, the absence of broadcasting, partition
invariance of the real trainer, validation-batch invariance and log
consistency.

The end-to-end tests drive `stsai.training.train` on a synthetic collection
built from the pure-Python reference environment, so they need no native
extension, no GPU and no teacher budget.
"""
import gzip
import json
import random
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.training import (LOSS_REVISION, ReplayDataset, collate_samples,
                            combine_numerators, loss_numerators, policy_term,
                            train, validate)


# --- unit contract -----------------------------------------------------------

def test_policy_term_hand_computed():
    elementwise = torch.tensor([1.0, 2.0, 3.0, 4.0])
    decision = torch.tensor([1, 0, 1, 0], dtype=torch.bool)
    assert float(policy_term(elementwise, decision)) == pytest.approx(2.0)


def test_policy_term_rejects_rank_two():
    with pytest.raises(ValueError, match="rank-1"):
        policy_term(torch.tensor([1.0, 2.0]), torch.tensor([[1.0], [0.0]]))


def test_policy_term_rejects_length_mismatch():
    with pytest.raises(ValueError, match="matching lengths"):
        policy_term(torch.tensor([1.0, 2.0, 3.0]), torch.tensor([1, 0], dtype=torch.bool))


def test_loss_revision_recorded():
    assert isinstance(LOSS_REVISION, int) and LOSS_REVISION >= 2


# --- effective-batch arithmetic ---------------------------------------------

def test_hand_computed_effective_batch_mean_is_three_not_two_point_five():
    """The reviewer's counterexample, restated as the rule now requires.

    costs [1,0,3,5], decision [1,0,1,1], two microbatches of two. Averaging the
    microbatch means gives 2.5; the effective-batch mean is 3.
    """
    costs = torch.tensor([1.0, 0.0, 3.0, 5.0])
    decision = torch.tensor([1, 0, 1, 1], dtype=torch.bool)
    microbatch_means = (policy_term(costs[:2], decision[:2])
                        + policy_term(costs[2:], decision[2:])) / 2
    assert float(microbatch_means) == pytest.approx(2.5)      # the superseded rule
    assert float(costs[decision].sum() / decision.sum()) == pytest.approx(3.0)


def test_effective_batch_mean_ignores_the_partitioning():
    costs = torch.tensor([1.0, 0.0, 3.0, 5.0])
    decision = torch.tensor([1, 0, 1, 1], dtype=torch.bool)
    for splits in ([(0, 4)], [(0, 2), (2, 4)], [(0, 1), (1, 2), (2, 3), (3, 4)]):
        numerator = sum(float((costs[a:b] * decision[a:b]).sum()) for a, b in splits)
        denominator = sum(float(decision[a:b].sum()) for a, b in splits)
        assert numerator / denominator == pytest.approx(3.0)


def test_all_forced_batch_is_finite_and_has_zero_policy_gradient():
    logits = torch.randn(3, 4, requires_grad=True)
    labels = {"policy": torch.softmax(torch.randn(3, 4), -1),
              "decision": torch.zeros(3, dtype=torch.bool),
              "outcome": torch.full((3, 11), 1 / 11), "value": torch.zeros(3),
              "value_mask": torch.zeros(3)}
    output = {"policy_logits": logits, "outcome_logits": torch.randn(3, 11),
              "value": torch.zeros(3)}
    numerators, counts = loss_numerators(output, labels)
    assert torch.isfinite(numerators["policy_num"]) and float(counts["D"]) == 0.0
    parts = combine_numerators({k: float(v.detach()) for k, v in numerators.items()},
                               {k: float(v.detach()) for k, v in counts.items()})
    assert parts["policy_loss"] == 0.0
    (numerators["policy_num"] / 1.0).backward()
    assert torch.allclose(logits.grad, torch.zeros_like(logits))


def test_auxiliary_terms_match_an_explicit_reference():
    torch.manual_seed(0)
    logits, outcome_logits, value = torch.randn(4, 3), torch.randn(4, 11), torch.rand(4)
    outcome, value_target = torch.softmax(torch.randn(4, 11), -1), torch.rand(4)
    mask = torch.tensor([1.0, 1.0, 0.0, 1.0])
    labels = {"policy": torch.softmax(torch.randn(4, 3), -1),
              "decision": torch.ones(4, dtype=torch.bool), "outcome": outcome,
              "value": value_target, "value_mask": mask}
    output = {"policy_logits": logits, "outcome_logits": outcome_logits, "value": value}
    numerators, counts = loss_numerators(output, labels)
    parts = combine_numerators({k: float(v) for k, v in numerators.items()},
                               {k: float(v) for k, v in counts.items()})
    ref_outcome = float((-(outcome * outcome_logits.log_softmax(-1)).sum(-1) * mask).sum() / mask.sum())
    ref_value = float((((value - value_target) ** 2) * mask).sum() / mask.sum())
    assert parts["outcome_loss"] == pytest.approx(ref_outcome, abs=1e-6)
    assert parts["value_loss"] == pytest.approx(ref_value, abs=1e-6)
    assert parts["loss"] == pytest.approx(
        parts["policy_loss"] + 0.5 * parts["outcome_loss"] + parts["value_loss"])


# --- synthetic collection built from the reference environment ---------------

BACKEND = "reference_v1"


def _write_shard(path, samples):
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


def build_collection(directory, split, episodes=6, steps=8, seed=7):
    """Materialise a small collection with the fields the trainer consumes."""
    from stsai.objective import outcome_target, terminal_utility
    from stsai.scenarios import make_env, make_scenario

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for index in range(episodes):
        scenario, episode_seed, family = make_scenario(BACKEND, "train" if split == "train" else "val",
                                                       index, master_seed=99)
        env = make_env(BACKEND, scenario, episode_seed)
        obs = env.observe()
        rows = []
        for _ in range(steps):
            if obs["terminal"]:
                break
            actions = obs["actions"]
            policy = [1.0 / len(actions)] * len(actions)
            rows.append({"schema_version": obs["schema_version"], "backend": BACKEND, "split": split,
                         "episode_id": f"ep{index}", "family": family, "episode_index": index,
                         "observation": obs, "policy": policy, "action_index": 0,
                         "teacher_action_index": 0})
            obs = env.step(actions[rng.randrange(len(actions))])
        target = outcome_target(obs)
        utility = terminal_utility(obs, 0.02) if obs["terminal"] else 0.0
        for row in rows:
            row.update(outcome=target, value=utility, value_mask=float(bool(obs["terminal"])))
        _write_shard(directory / f"episode_{index:08d}_{index:012d}.jsonl.gz", rows)
    settings = {"backend": BACKEND, "split": split, "search": {"potion_cost": 0.02},
                "master_seed": 99, "max_actions": 64}
    (directory / "collection.json").write_text(
        json.dumps({"fingerprint": f"synthetic-{split}-{seed}", "settings": settings}), encoding="utf-8")
    return directory


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    train_dir = build_collection(root / "train", "train")
    val_dir = build_collection(root / "val", "val", episodes=3, steps=6)
    return train_dir, val_dir


def _config(batch, accum, updates=1):
    return {"seed": 17, "init_seed": 17, "data_seed": 42, "batch_size": batch,
            "accumulation_steps": accum, "learning_rate": 3e-4, "weight_decay": 0.01,
            "max_updates": updates, "epochs": 4, "eval_every": 10 ** 6, "save_every": 10 ** 6,
            "validation_batches": 10 ** 6, "shuffle_buffer": 512, "amp": False, "cpu_threads": 1,
            "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}}


def test_effective_batch_partition_invariance_end_to_end(synthetic, tmp_path):
    """32x1, 16x2 and 8x4 must produce the same parameters after one update.

    Dropout is off and the data order is fixed, so the only difference is how
    the same 32 samples are grouped. The superseded rule averaged microbatch
    means, which weighted microbatches by their decision-state count instead of
    by the effective batch.
    """
    train_dir, val_dir = synthetic
    reference = None
    for batch, accum in ((32, 1), (16, 2), (8, 4)):
        out = tmp_path / f"partition_{batch}_{accum}"
        train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
              config=_config(batch, accum))
        state = torch.load(out / "last.pt", map_location="cpu", weights_only=True)["model_state"]
        if reference is None:
            reference = state
            continue
        for key in reference:
            assert torch.allclose(reference[key], state[key], atol=1e-5, rtol=1e-4), \
                f"parameters differ for batch={batch} accum={accum} at {key}"


def test_validation_aggregates_are_independent_of_batch_size(synthetic):
    from torch.utils.data import DataLoader
    from stsai.model import CombatNet, ModelConfig
    _, val_dir = synthetic
    torch.manual_seed(3)
    model = CombatNet(ModelConfig(d_model=16, layers=1, heads=2, dropout=0.0)).eval()
    results = []
    for batch_size in (1, 2, 3, 7):
        loader = DataLoader(ReplayDataset([str(val_dir)], BACKEND, "val", 42, 1),
                            batch_size=batch_size, collate_fn=collate_samples)
        results.append(validate(model, loader, torch.device("cpu"), 10 ** 6))
    first = results[0]
    for other in results[1:]:
        for key in ("policy_loss", "outcome_loss", "value_loss", "loss", "kl_dev",
                    "policy_kl_decision", "teacher_entropy_decision",
                    "decision_numerator_D", "masked_numerator_M", "samples"):
            assert other[key] == pytest.approx(first[key], abs=1e-6), f"{key} depends on batch size"


def test_logged_total_equals_the_three_aggregates(synthetic, tmp_path):
    train_dir, val_dir = synthetic
    out = tmp_path / "log_check"
    train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
          config=_config(16, 2))
    lines = [json.loads(line) for line in (out / "metrics.jsonl").read_text().splitlines() if line.strip()]
    assert lines, "no optimizer update was logged"
    for entry in lines:
        assert entry["loss"] == pytest.approx(
            entry["policy_loss"] + 0.5 * entry["outcome_loss"] + entry["value_loss"], abs=1e-9)
        assert entry["effective_batch_samples"] == 32
        assert entry["effective_batch_decision_states"] > 0
    summary = json.loads((out / "training_summary.json").read_text())
    assert summary["loss_revision"] == LOSS_REVISION
    assert summary["dropped_tail_rows"] >= 0
