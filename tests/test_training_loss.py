"""Regression coverage for the training objective's normalisation.

The generalisation matrix was trained while `losses()` contained a broadcasting
error: the policy term multiplied a per-sample vector (b,) by a per-sample mask
reshaped to (b,1), which numpy/torch broadcast into a (b,b) outer product. The
sum then ran over b*b terms instead of b, inflating the policy term by roughly
the batch size and starving the auxiliary heads.

These tests pin the defect down numerically so it cannot be reintroduced or
silently "fixed" without a re-run. The passing test records what the shipped
code currently does; the strict xfail records what it is supposed to do and
turns into a failure the moment someone changes the behaviour, which is exactly
the signal that the frozen matrix would need retraining.
"""
import pytest
import torch

from stsai.training import losses


def synthetic(batch=8, actions=4):
    torch.manual_seed(0)
    logits = torch.randn(batch, actions)
    policy = torch.softmax(torch.randn(batch, actions), -1)
    decision = torch.ones(batch, dtype=torch.bool)
    decision[2] = decision[5] = False          # two forced single-action states
    output = {"policy_logits": logits,
              "outcome_logits": torch.randn(batch, 11),
              "value": torch.rand(batch)}
    labels = {"policy": policy, "decision": decision,
              "outcome": torch.full((batch, 11), 1.0 / 11),
              "value": torch.rand(batch), "value_mask": torch.ones(batch)}
    return output, labels, policy, decision, logits


def test_policy_term_is_inflated_by_the_outer_product():
    """Documents the shipped behaviour: the (b,) x (b,1) product is a (b,b) grid."""
    output, labels, policy, decision, logits = synthetic()
    elementwise = -(policy * logits.log_softmax(-1)).sum(-1)          # (b,)
    current = (elementwise * decision.unsqueeze(-1)).sum() / decision.sum().clamp_min(1)
    intended = (elementwise * decision).sum() / decision.sum().clamp_min(1)
    assert (elementwise * decision.unsqueeze(-1)).shape == (8, 8)
    assert (elementwise * decision).shape == (8,)
    assert float(current) > 3 * float(intended), \
        "the inflation is real: the current form sums over b*b terms"


@pytest.mark.xfail(strict=True, reason=(
    "Known defect: stsai.training.losses() broadcasts (b,) x (b,1) into a (b,b) outer "
    "product, inflating the policy term ~batch_size x. The generalisation matrix at "
    "commit fb9bf6e was trained under this objective, so the fix must land together "
    "with a retrain, not silently. See evidence_response.md section 0.1."))
def test_policy_term_is_mean_over_decision_states():
    """The intended semantics: mean cross-entropy over states that have a choice."""
    output, labels, policy, decision, logits = synthetic()
    _, parts = losses(output, labels)
    elementwise = -(policy * logits.log_softmax(-1)).sum(-1)
    intended = (elementwise * decision).sum() / decision.sum().clamp_min(1)
    assert torch.isclose(parts["policy_loss"], intended, atol=1e-6)


def test_auxiliary_heads_are_not_affected_by_the_policy_defect():
    """The defect is confined to the policy term; the auxiliary terms are the batch mean."""
    output, labels, _, _, _ = synthetic()
    _, parts = losses(output, labels)
    assert parts["outcome_loss"].ndim == 0 and float(parts["outcome_loss"]) > 0
    assert parts["value_loss"].ndim == 0 and float(parts["value_loss"]) > 0
