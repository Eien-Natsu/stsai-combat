from __future__ import annotations
from dataclasses import dataclass, asdict
import os
from pathlib import Path
import torch
from torch import nn
from .encoding import FEATURES, VOCAB, encode, collate_encoded
from .contracts import validate_public

@dataclass
class ModelConfig:
    d_model: int = 192
    layers: int = 4
    heads: int = 6
    dropout: float = .1
    def __post_init__(self):
        if self.d_model % self.heads: raise ValueError("d_model must be divisible by heads")

class CombatNet(nn.Module):
    def __init__(self, config: ModelConfig | None = None):
        super().__init__(); self.config = config or ModelConfig(); c = self.config
        self.ids = nn.Embedding(VOCAB, c.d_model, padding_idx=0)
        self.features = nn.Linear(FEATURES, c.d_model)
        layer = nn.TransformerEncoderLayer(c.d_model, c.heads, c.d_model*4,
                    c.dropout, batch_first=True, norm_first=True, activation="gelu")
        self.encoder = nn.TransformerEncoder(layer, c.layers, norm=nn.LayerNorm(c.d_model), enable_nested_tensor=False)
        self.action_kind = nn.Embedding(5, c.d_model)
        self.action_features = nn.Linear(FEATURES, c.d_model)
        self.policy = nn.Sequential(nn.Linear(c.d_model*4,c.d_model),nn.GELU(),nn.Linear(c.d_model,1))
        self.outcome = nn.Sequential(nn.Linear(c.d_model,c.d_model),nn.GELU(),nn.Linear(c.d_model,11))
        self.value = nn.Sequential(nn.Linear(c.d_model,c.d_model),nn.GELU(),nn.Linear(c.d_model,1))

    def forward(self, batch):
        x = self.ids(batch["ids"]) + self.features(batch["features"])
        x = self.encoder(x, src_key_padding_mask=~batch["entity_mask"])
        b, a, k = batch["action_sources"].shape
        d = x.shape[-1]
        source_ix = batch["action_sources"].reshape(b,-1)
        source = x.gather(1, source_ix.unsqueeze(-1).expand(-1,-1,d)).reshape(b,a,k,d)
        sm = (batch["action_sources"] != 0).unsqueeze(-1)
        source = (source * sm).sum(2) / sm.sum(2).clamp_min(1)
        target = x.gather(1,batch["action_target"].unsqueeze(-1).expand(-1,-1,d))
        target = target * (batch["action_target"] != 0).unsqueeze(-1)
        state = x[:,0]
        action = self.action_kind(batch["action_kind"]) + self.action_features(batch["action_features"])
        logits = self.policy(torch.cat([state[:,None].expand(-1,a,-1),source,target,action],dim=-1)).squeeze(-1)
        logits = logits.float().masked_fill(~batch["action_mask"], -1e9)
        return {"policy_logits": logits, "outcome_logits": self.outcome(state).float(),
                "value": self.value(state).float().sigmoid().squeeze(-1)}

def resolve_device(device: str) -> torch.device:
    if device == "auto": device = "cuda" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable; CPU fallback is NOT automatic")
    return torch.device(device)

def check_checkpoint_semantics(checkpoint, path, data_fingerprint=None):
    """Reject a checkpoint whose input semantics differ from this build.

    Used by every entry point that can consume a checkpoint - inference, warm
    start and resume - so none of them can accept an old model silently. A
    MISSING field means the revision that predates the field, never the current
    one; relabelling metadata alone is not a conversion.
    """
    from .encoding import ENCODING_REVISION
    from .native import SAMPLER_REVISION
    from .util import LOSS_REVISION, SCHEMA_VERSION
    for key, current, legacy in (("encoding_revision", ENCODING_REVISION, 1),
                                 ("observation_schema", SCHEMA_VERSION, 1),
                                 ("loss_revision", LOSS_REVISION, 1)):
        stored = checkpoint.get(key, legacy)
        if stored != current:
            raise ValueError(f"{path}: {key}={stored} but this build uses {current}; "
                             "the inputs or the objective no longer mean the same thing")
    from .util import SAMPLER_NOT_APPLICABLE
    stored_sampler = checkpoint.get("sampler_revision")
    backend = checkpoint.get("backend")
    if backend == "lightspeed_pilot":
        # The sampler IS the belief model for this backend, so it must be declared.
        # Missing or None means a checkpoint written before the field existed, and
        # that is not the same as the current sampler.
        if stored_sampler is None:
            raise ValueError(f"{path}: native checkpoints must record sampler_revision; a missing "
                             "value is the pre-field revision, not the current one")
        if stored_sampler != SAMPLER_REVISION:
            raise ValueError(f"{path}: sampler_revision={stored_sampler} but this build uses "
                             f"{SAMPLER_REVISION}")
    else:
        # A backend without a sampler states that explicitly rather than leaving
        # the field out, so absence is never a pass.
        if stored_sampler != SAMPLER_NOT_APPLICABLE:
            raise ValueError(f"{path}: backend {backend!r} must record sampler_revision="
                             f"{SAMPLER_NOT_APPLICABLE!r}, found {stored_sampler!r}")
    if data_fingerprint is not None and checkpoint.get("data_fingerprint") != data_fingerprint:
        raise ValueError(f"{path}: data changed; this checkpoint was trained on a different set")


def load_checkpoint(path, device="cpu"):
    # Only load trusted locally generated checkpoints, even with weights_only.
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("format_version") != 1: raise ValueError("Unknown checkpoint format")
    check_checkpoint_semantics(checkpoint, path)
    model = CombatNet(ModelConfig(**checkpoint["model_config"]))
    model.load_state_dict(checkpoint["model_state"])
    model.to(resolve_device(device)); model.eval()
    return model, checkpoint

class ModelEvaluator:
    def __init__(self, model: CombatNet, device="cpu", backend: str | None = None):
        self.device = resolve_device(device); self.model = model.to(self.device).eval(); self.backend = backend
    @classmethod
    def from_checkpoint(cls, path, device="cpu", expected_backend=None):
        model, ckpt = load_checkpoint(path,device)
        backend = ckpt["backend"]
        if expected_backend and expected_backend != backend: raise ValueError(f"Checkpoint backend {backend} != {expected_backend}")
        return cls(model,device,backend)
    def evaluate(self, obs):
        return self.evaluate_batch([obs])[0]
    @torch.inference_mode()
    def evaluate_batch(self, observations):
        for obs in observations:
            validate_public(obs)
            if self.backend and obs["backend"] != self.backend: raise ValueError("Cross-backend checkpoint use prohibited")
        batch = {k:v.to(self.device) for k,v in collate_encoded([encode(o) for o in observations]).items()}
        output = self.model(batch)
        probs = output["policy_logits"].softmax(-1).cpu().numpy()
        values = output["value"].cpu().tolist()
        return [(probs[i,:len(o["actions"])].tolist(),values[i]) for i,o in enumerate(observations)]
