"""Three acceptance tests; all three deliberately FAIL on bf26b0f.
Copy into the repo tests/ after reviewing. They must pass before new native training.
These test implementation contracts, not original-game strength or full fairness.
"""
from copy import deepcopy
from dataclasses import fields
import numpy as np
import pytest
import torch


def test_public_attack_base_reaches_encoder():
    pytest.importorskip('stsai._lightspeed')
    from stsai.native import NativeBattle
    from stsai.encoding import encode
    from stsai.contracts import observation_key
    env=NativeBattle({'deck':['DISARM+']*10,'encounter':'TWO_LOUSE',
                      'ascension':20,'hp':200,'max_hp':200,'floor':1,'act':1,'potions':[]},
                     985017620115975495)
    a=env.observe(); b=deepcopy(a)
    assert a['enemies'][0]['attack_base_low']==6 and a['enemies'][0]['attack_base_high']==8
    b['enemies'][0]['attack_base_low']=7;b['enemies'][0]['attack_base_high']=7
    # Synthetic sensitivity case, not a claimed pair of reachable original-game states.
    assert observation_key(a)!=observation_key(b)
    ea,eb=encode(a),encode(b)
    assert any(not np.array_equal(getattr(ea,f.name),getattr(eb,f.name)) for f in fields(ea)), \
        'A public attack-base interval changed but every network input is identical'


def test_native_checkpoint_requires_sampler_revision():
    from stsai.model import check_checkpoint_semantics
    from stsai.encoding import ENCODING_REVISION
    from stsai.util import SCHEMA_VERSION, LOSS_REVISION
    metadata={'backend':'lightspeed_pilot','encoding_revision':ENCODING_REVISION,
              'observation_schema':SCHEMA_VERSION,'loss_revision':LOSS_REVISION}
    with pytest.raises(ValueError):
        check_checkpoint_semantics(metadata,'missing_native_sampler.pt')


def test_outcome_batch_cannot_broadcast_across_policy_batch():
    from stsai.training import loss_numerators
    output={'policy_logits':torch.zeros(4,3,requires_grad=True),
            'outcome_logits':torch.zeros(1,11,requires_grad=True),
            'value':torch.zeros(4,requires_grad=True)}
    labels={'policy':torch.full((4,3),1/3),'outcome':torch.full((1,11),1/11),
            'decision':torch.ones(4,dtype=torch.bool),'value':torch.zeros(4),
            'value_mask':torch.ones(4)}
    with pytest.raises(ValueError):
        loss_numerators(output,labels)
