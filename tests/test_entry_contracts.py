"""Contracts at the boundaries the review found unguarded.

Four small gaps, all reachable without training anything: the production loss
function accepted a (B,1) mask, only the inference entry point checked checkpoint
semantics, the discarded-tail counter used a nominal batch size, and `losses()`
returned a detached float from something named like a loss. Each test below
fails against the pre-fix behaviour and passes against the current one.
"""
import json
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from stsai.model import check_checkpoint_semantics, load_checkpoint
from stsai.training import collate_samples, loss_numerators, losses, train
from stsai.util import LOSS_REVISION, SCHEMA_VERSION
from test_training_loss import BACKEND, build_collection


def synthetic_batch(batch=4, actions=3):
    torch.manual_seed(0)
    labels = {"policy": torch.softmax(torch.randn(batch, actions), -1),
              "decision": torch.tensor([1, 0, 1, 1][:batch], dtype=torch.bool),
              "outcome": torch.softmax(torch.randn(batch, 11), -1),
              "value": torch.rand(batch), "value_mask": torch.ones(batch)}
    # leaves, so the loss graph is real and backward() is meaningful
    output = {"policy_logits": torch.randn(batch, actions, requires_grad=True),
              "outcome_logits": torch.randn(batch, 11, requires_grad=True),
              "value": torch.rand(batch, requires_grad=True)}
    return output, labels


# --- 4.1 the production loss path checks shapes ------------------------------

def test_loss_numerators_rejects_a_broadcasting_decision_mask():
    """The review's counterexample: (B,1) decision used to be accepted."""
    output, labels = synthetic_batch()
    labels["decision"] = labels["decision"].unsqueeze(-1)
    with pytest.raises(ValueError, match="rank 1"):
        loss_numerators(output, labels)


def test_every_head_must_share_one_batch():
    """A short outcome batch used to broadcast one outcome error over four rows.

    Each head can match its own target and still describe a different batch; the
    review's counterexample was policy B=4 against outcome B=1 with a B=4 mask.
    """
    for batch in (1, 3, 9):
        output, labels = synthetic_batch()
        output["outcome_logits"] = torch.randn(batch, 11, requires_grad=True)
        labels["outcome"] = torch.softmax(torch.randn(batch, 11), -1)
        with pytest.raises(ValueError, match="does not match the policy batch"):
            loss_numerators(output, labels)


def test_loss_numerators_rejects_length_and_rank_mismatches():
    output, labels = synthetic_batch()
    for broken, match in (({"decision": torch.ones(3, dtype=torch.bool)}, "rank 1"),
                          ({"value_mask": torch.ones(4, 1)}, "rank 1"),
                          ({"value": torch.rand(9)}, "rank 1")):
        bad = dict(labels); bad.update(broken)
        with pytest.raises(ValueError, match=match):
            loss_numerators(output, bad)
    bad_output = dict(output); bad_output["policy_logits"] = torch.randn(4, 5)
    with pytest.raises(ValueError, match="do not match the target"):
        loss_numerators(bad_output, labels)
    bad_output = dict(output); bad_output["outcome_logits"] = torch.randn(4, 7)
    with pytest.raises(ValueError, match="do not match the target"):
        loss_numerators(bad_output, labels)
    bad_output = dict(output); bad_output["policy_logits"] = torch.randn(4)
    with pytest.raises(ValueError, match="rank 2"):
        loss_numerators(bad_output, labels)


def test_the_accepting_batch_still_works():
    output, labels = synthetic_batch()
    numerators, counts = loss_numerators(output, labels)
    assert float(counts["D"]) == 3.0
    assert torch.isfinite(numerators["policy_num"])


# --- 4.4 losses() is a loss ---------------------------------------------------

def test_losses_returns_a_differentiable_tensor():
    output, labels = synthetic_batch()
    loss, parts = losses(output, labels)
    assert isinstance(loss, torch.Tensor) and loss.requires_grad, \
        "a function named losses() must return something backwardable"
    loss.backward()
    assert output["policy_logits"].grad is not None, "gradient did not reach the logits"
    assert torch.isfinite(output["policy_logits"].grad).all()
    for name, value in parts.items():
        assert not isinstance(value, float), f"{name} was detached to a float"


# --- 4.2 every checkpoint entry point checks semantics -----------------------

def _stale_checkpoint(tmp):
    """A checkpoint carrying the semantics of an older build."""
    torch.manual_seed(0)
    from stsai.model import CombatNet, ModelConfig
    model = CombatNet(ModelConfig(d_model=16, layers=1, heads=2, dropout=0.0))
    path = tmp / "stale.pt"
    torch.save({"format_version": 1, "model_config": {"d_model": 16, "layers": 1, "heads": 2,
                                                      "dropout": 0.0},
                "model_state": model.state_dict(), "optimizer_state": {},
                "step": 0, "epoch": 0, "best_val": 0.0, "backend": BACKEND,
                "train_config": {}, "data_fingerprint": "x",
                "encoding_revision": 1, "observation_schema": 1, "loss_revision": 1}, path)
    return path


def test_load_checkpoint_rejects_stale_semantics(tmp_path):
    with pytest.raises(ValueError, match="no longer mean the same thing"):
        load_checkpoint(_stale_checkpoint(tmp_path))


def test_warm_start_and_resume_reject_the_same_stale_semantics(tmp_path):
    """The gap the review found: only inference was guarded."""
    train_dir = build_collection(tmp_path / "train", "train")
    val_dir = build_collection(tmp_path / "val", "val", episodes=3, steps=6)
    stale = _stale_checkpoint(tmp_path)
    config = {"seed": 17, "batch_size": 16, "accumulation_steps": 2, "max_updates": 1,
              "epochs": 2, "eval_every": 10 ** 6, "save_every": 10 ** 6,
              "validation_batches": 10 ** 6, "amp": False, "cpu_threads": 1,
              "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}}
    with pytest.raises(ValueError, match="no longer mean the same thing"):
        train([str(train_dir)], [str(val_dir)], str(tmp_path / "warm"), backend=BACKEND,
              device="cpu", config=config, init_checkpoint=str(stale))
    with pytest.raises(ValueError, match="no longer mean the same thing"):
        train([str(train_dir)], [str(val_dir)], str(tmp_path / "resume"), backend=BACKEND,
              device="cpu", config=config, resume=str(stale))


def test_a_missing_revision_is_treated_as_the_old_one_not_the_current_one():
    with pytest.raises(ValueError, match="no longer mean the same thing"):
        check_checkpoint_semantics({}, "bare.pt")
    from stsai.encoding import ENCODING_REVISION
    from stsai.native import SAMPLER_REVISION
    from stsai.util import SAMPLER_NOT_APPLICABLE
    check_checkpoint_semantics({"backend": "lightspeed_pilot", "encoding_revision": ENCODING_REVISION,
                                "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION,
                                "sampler_revision": SAMPLER_REVISION}, "current_native.pt")
    check_checkpoint_semantics({"backend": BACKEND, "encoding_revision": ENCODING_REVISION,
                                "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION,
                                "sampler_revision": SAMPLER_NOT_APPLICABLE}, "current_reference.pt")
    for label, metadata in (
            ("native without sampler_revision",
             {"backend": "lightspeed_pilot", "encoding_revision": ENCODING_REVISION,
              "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION}),
            ("native with sampler_revision None",
             {"backend": "lightspeed_pilot", "encoding_revision": ENCODING_REVISION,
              "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION,
              "sampler_revision": None}),
            ("native with an older sampler",
             {"backend": "lightspeed_pilot", "encoding_revision": ENCODING_REVISION,
              "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION,
              "sampler_revision": "independent_rng_approximation/1"}),
            ("reference that leaves the marker out",
             {"backend": BACKEND, "encoding_revision": ENCODING_REVISION,
              "observation_schema": SCHEMA_VERSION, "loss_revision": LOSS_REVISION})):
        with pytest.raises(ValueError, match="sampler_revision"):
            check_checkpoint_semantics(metadata, f"{label}.pt")


def _native_checkpoint_without_declared_sampler(tmp):
    """Current revisions everywhere else, but the sampler is simply not recorded."""
    torch.manual_seed(0)
    from stsai.encoding import ENCODING_REVISION
    from stsai.model import CombatNet, ModelConfig
    from stsai.util import SAMPLER_NOT_APPLICABLE  # noqa: F401 - documents what must NOT be written
    model = CombatNet(ModelConfig(d_model=16, layers=1, heads=2, dropout=0.0))
    path = tmp / "native_without_sampler.pt"
    torch.save({"format_version": 1, "model_config": {"d_model": 16, "layers": 1, "heads": 2,
                                                      "dropout": 0.0},
                "model_state": model.state_dict(), "optimizer_state": {},
                "step": 0, "epoch": 0, "best_val": 0.0, "backend": "lightspeed_pilot",
                "train_config": {}, "data_fingerprint": "x",
                "encoding_revision": ENCODING_REVISION, "observation_schema": SCHEMA_VERSION,
                "loss_revision": LOSS_REVISION}, path)
    return path


def test_every_entry_point_refuses_a_native_checkpoint_with_no_sampler_revision(tmp_path):
    """Inference, warm start and resume share the check, on the real entry points.

    A native checkpoint's sampler IS its belief model, so a file that omits the
    field was written by a build that predates it. Reading that as agreement
    would evaluate an old belief model under the current semantics.
    """
    missing = _native_checkpoint_without_declared_sampler(tmp_path)
    train_dir = build_collection(tmp_path / "ntrain", "train")
    val_dir = build_collection(tmp_path / "nval", "val", episodes=3, steps=6)
    config = {"seed": 17, "batch_size": 16, "accumulation_steps": 2, "max_updates": 1,
              "epochs": 2, "eval_every": 10 ** 6, "save_every": 10 ** 6,
              "validation_batches": 10 ** 6, "amp": False, "cpu_threads": 1,
              "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}}
    # The collection is the reference one; the checkpoint is what declares itself
    # native, and the semantic guard is what must reject it - before the run's own
    # backend/architecture comparison ever gets a say.
    with pytest.raises(ValueError, match="must record sampler_revision"):
        load_checkpoint(missing)
    with pytest.raises(ValueError, match="must record sampler_revision"):
        train([str(train_dir)], [str(val_dir)], str(tmp_path / "nwarm"),
              backend=BACKEND, device="cpu", config=config, init_checkpoint=str(missing))
    with pytest.raises(ValueError, match="must record sampler_revision"):
        train([str(train_dir)], [str(val_dir)], str(tmp_path / "nresume"),
              backend=BACKEND, device="cpu", config=config, resume=str(missing))


def test_current_semantics_still_load_and_train(tmp_path):
    train_dir = build_collection(tmp_path / "train2", "train")
    val_dir = build_collection(tmp_path / "val2", "val", episodes=3, steps=6)
    out = tmp_path / "ok"
    summary = train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
                    config={"seed": 17, "batch_size": 16, "accumulation_steps": 2,
                            "max_updates": 1, "epochs": 2, "eval_every": 10 ** 6,
                            "save_every": 10 ** 6, "validation_batches": 10 ** 6, "amp": False,
                            "cpu_threads": 1,
                            "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}})
    assert summary["loss_revision"] == LOSS_REVISION
    load_checkpoint(out / "last.pt")            # current semantics still load
    resumed = train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
                    config={"seed": 17, "batch_size": 16, "accumulation_steps": 2,
                            "max_updates": 2, "epochs": 2, "eval_every": 10 ** 6,
                            "save_every": 10 ** 6, "validation_batches": 10 ** 6, "amp": False,
                            "cpu_threads": 1,
                            "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}},
                    resume=str(out / "last.pt"))
    assert resumed["steps"] == 2


# --- 4.3 the tail count reflects the rows actually cached ---------------------

def test_dropped_tail_rows_counts_the_short_window(tmp_path):
    """The discarded tail is measured, not inferred from disk.

    12 episodes x 7 steps gives 84 rows against a 64-row window (16 x 4), so one
    window is used and 20 rows are left over. The old rule would have reported
    4 x 16 = 64 discarded, and would have logged 64 as the window size even when
    the window was short.
    """
    train_dir = build_collection(tmp_path / "train3", "train", episodes=12, steps=7)
    val_dir = build_collection(tmp_path / "val3", "val", episodes=3, steps=6)
    import gzip
    rows = sum(1 for shard in train_dir.glob("*.jsonl.gz") for _ in gzip.open(shard, "rt"))
    out = tmp_path / "tail"
    summary = train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
                    config={"seed": 17, "batch_size": 16, "accumulation_steps": 4,
                            "max_updates": 100, "epochs": 1, "eval_every": 10 ** 6,
                            "save_every": 10 ** 6, "validation_batches": 10 ** 6, "amp": False,
                            "cpu_threads": 1,
                            "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}})
    logged = [json.loads(line) for line in (out / "metrics.jsonl").read_text().splitlines()
              if line.strip()]
    used = sum(entry["effective_batch_samples"] for entry in logged)
    assert summary["dropped_tail_rows"] > 0, "the fixture must leave a short tail to measure"
    assert rows == used + summary["dropped_tail_rows"], \
        f"{rows} read, {used} used, {summary['dropped_tail_rows']} reported as dropped"
    for entry in logged:
        assert entry["effective_batch_samples"] <= 64
