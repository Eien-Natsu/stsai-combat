"""Regression tests for the policy term in the training objective.

The generalisation matrix at fb9bf6e was trained while this term broadcast a
(batch,) vector against a (batch,1) mask, producing a (batch,batch) outer
product: the sum ran over batch*batch entries instead of batch, inflating the
policy loss by roughly the batch size while the auxiliary heads kept their
scale. These tests pin the shape, the hand-computed value, and the absence of
the broadcast.
"""
import pytest
import torch

from stsai.training import losses, policy_term


def synthetic(batch=4, decision=(1.0, 0.0, 1.0, 0.0), actions=4):
    torch.manual_seed(0)
    logits = torch.randn(batch, actions)
    policy = torch.softmax(torch.randn(batch, actions), -1)
    decision = torch.tensor(decision, dtype=torch.bool)
    output = {"policy_logits": logits,
              "outcome_logits": torch.randn(batch, 11),
              "value": torch.rand(batch)}
    labels = {"policy": policy, "decision": decision,
              "outcome": torch.full((batch, 11), 1.0 / 11),
              "value": torch.rand(batch), "value_mask": torch.ones(batch)}
    return output, labels


# --- Test 1: loss shape ------------------------------------------------------
def test_losses_returns_scalar_policy_term():
    output, labels = synthetic(batch=4, decision=(1, 0, 1, 0))
    _, parts = losses(output, labels)
    assert parts["policy_loss"].shape == torch.Size([]), "policy loss must be a scalar"
    assert parts["outcome_loss"].shape == torch.Size([])
    assert parts["value_loss"].shape == torch.Size([])


# --- Test 2: hand-computed value --------------------------------------------
def test_policy_term_matches_hand_computation():
    elementwise = torch.tensor([1.0, 2.0, 3.0, 4.0])
    decision = torch.tensor([1, 0, 1, 0], dtype=torch.bool)
    assert float(policy_term(elementwise, decision)) == pytest.approx(2.0)


# --- Test 3: broadcasting is forbidden --------------------------------------
def test_policy_term_rejects_a_broadcasting_mask():
    """A (batch,1) mask must raise rather than build a (batch,batch) grid."""
    elementwise = torch.tensor([1.0, 2.0, 3.0, 4.0])
    with pytest.raises(ValueError, match="batch,batch"):
        policy_term(elementwise, torch.tensor([1.0, 0.0, 1.0, 0.0]).unsqueeze(-1))


def test_broadcast_value_is_not_what_the_term_returns():
    """The defect would have produced 10 here; the correct term is 2.

    The product is rows of [1,2,3,4] repeated for each decision-flagged sample:
    its sum is 20 against a denominator of 2, i.e. 10. Pinning both the correct
    value and the defective one means a reintroduction cannot pass by looking
    merely plausible.
    """
    elementwise = torch.tensor([1.0, 2.0, 3.0, 4.0])
    decision = torch.tensor([1.0, 0.0, 1.0, 0.0])
    grid = elementwise * decision.unsqueeze(-1)
    assert grid.shape == (4, 4)
    broadcast = float(grid.sum() / decision.sum())
    assert broadcast == pytest.approx(10.0)
    assert float(policy_term(elementwise, decision.bool())) == pytest.approx(2.0)


def test_policy_term_is_invariant_to_batch_size():
    """The defect scaled with batch size; the correct term must not."""
    elementwise = torch.tensor([1.0, 3.0])
    decision = torch.tensor([True, True])
    small = float(policy_term(elementwise, decision))
    big = float(policy_term(torch.cat([elementwise] * 8), torch.cat([decision] * 8)))
    assert small == pytest.approx(big)


def test_auxiliary_heads_are_unaffected():
    output, labels = synthetic()
    _, parts = losses(output, labels)
    assert float(parts["outcome_loss"]) > 0
    assert float(parts["value_loss"]) > 0
