from __future__ import annotations
import gzip
import json
import os
from pathlib import Path
import random
import time
from dataclasses import asdict
import torch
from torch.utils.data import IterableDataset, DataLoader
from .encoding import encode, collate_encoded
from .model import CombatNet, ModelConfig, resolve_device
from .util import append_json, atomic_json, load_json, digest

class ReplayDataset(IterableDataset):
    def __init__(self, directories, backend, split, seed=0, shuffle_buffer=512):
        super().__init__()
        self.files = []
        self.backend=backend; self.split=split; self.seed=seed; self.shuffle_buffer=shuffle_buffer; self.epoch=0
        self.fingerprints=[]; self.provenance=[]; self.objectives=set()
        for directory in directories:
            directory=Path(directory); manifest=load_json(directory/"collection.json")
            settings=manifest["settings"]
            if settings["backend"] != backend or settings["split"] != split:
                raise ValueError("Replay backend/split mismatch; test data cannot be used for training")
            self.fingerprints.append(manifest["fingerprint"])
            self.provenance.append({"directory":str(Path(directory).resolve()),"manifest":manifest})
            self.objectives.add(float(settings["search"]["potion_cost"]))
            self.files.extend(sorted(directory.glob("episode_*.jsonl.gz")))
        if not self.files: raise ValueError("No replay shards")
        if len(self.objectives)!=1: raise ValueError("Do not mix different utility objectives in one replay dataset")
    def __iter__(self):
        if torch.utils.data.get_worker_info() is not None:
            raise RuntimeError("This bounded-shuffle loader intentionally requires num_workers=0")
        rng=random.Random(self.seed+self.epoch); files=self.files.copy()
        if self.split == "train": rng.shuffle(files)
        buffer=[]
        for path in files:
            with gzip.open(path,"rt",encoding="utf-8") as f:
                for line in f:
                    sample=json.loads(line)
                    if sample["backend"] != self.backend or sample["split"] != self.split:
                        raise ValueError("Corrupted/mixed replay shard")
                    if self.split != "train": yield sample; continue
                    buffer.append(sample)
                    if len(buffer) >= self.shuffle_buffer:
                        yield buffer.pop(rng.randrange(len(buffer)))
        while buffer: yield buffer.pop(rng.randrange(len(buffer)))

def collate_samples(samples):
    batch=collate_encoded([encode(s["observation"]) for s in samples])
    policy=torch.zeros_like(batch["action_mask"],dtype=torch.float32)
    for i,s in enumerate(samples):
        if len(s["policy"]) != int(batch["action_mask"][i].sum()): raise ValueError("Policy/action mismatch")
        p=torch.tensor(s["policy"],dtype=torch.float32)
        if not torch.isfinite(p).all() or (p < 0).any() or abs(float(p.sum())-1)>1e-4:
            raise ValueError("Invalid policy target")
        policy[i,:len(p)]=p
    # -1 marks shards predating the explicit column; the caller must then fall
    # back to the visit argmax and say so.
    labels={"policy":policy,"outcome":torch.tensor([s["outcome"] for s in samples]),
            "value":torch.tensor([s["value"] for s in samples]),
            "value_mask":torch.tensor([s["value_mask"] for s in samples]),
            "teacher_action":torch.tensor([s.get("teacher_action_index",-1) for s in samples]),
            # Not a tensor: kept for per-battle KL aggregation, which is the
            # frozen checkpoint-selection metric.
            "episode_id":[s.get("episode_id","?") for s in samples],
            # A state with one legal action scores 1.0 for free; agreement on
            # those must never be mixed into the headline number.
            "decision":torch.tensor([int(batch["action_mask"][i].sum())>1 for i in range(len(samples))])}
    return batch,labels

# Bump when the objective or its normalisation changes meaning. Recorded in
# run.json and in every checkpoint so a later reader can tell which counting
# rule produced a weight.
LOSS_REVISION = 2

def policy_term(elementwise,decision):
    """Mean cross-entropy over states that actually have a choice.

    `elementwise` is expected to be already reduced over actions, so it is
    (batch,) and so is `decision`. The mask is applied elementwise. Reshaping
    the mask to (batch,1) would broadcast the product into a (batch,batch) grid
    and sum batch*batch terms instead of batch, silently scaling the policy
    gradient by the batch size while the auxiliary heads keep their scale. Both
    the rank and the length are checked so that mistake is loud, not silent.
    """
    if elementwise.ndim != 1 or decision.ndim != 1:
        raise ValueError(f"policy term needs rank-1 tensors, got ndim "
                         f"{elementwise.ndim} and {decision.ndim}")
    if elementwise.shape != decision.shape:
        raise ValueError(f"policy term needs matching lengths, got {tuple(elementwise.shape)} "
                         f"and {tuple(decision.shape)}; a (batch,1) mask would build a (batch,batch) grid")
    return (elementwise*decision).sum()/decision.sum().clamp_min(1)

def loss_numerators(output,labels):
    """Per-head SUMS and the counts the sums are valid over.

    Returns numerators, not means. One optimizer update is defined as the whole
    effective batch, so the caller divides by the effective-batch denominators.
    Averaging per-microbatch means instead would silently weight microbatches
    with fewer decision states more heavily per decision state.
    """
    elementwise=-(labels["policy"]*output["policy_logits"].log_softmax(-1)).sum(-1)
    decision=labels["decision"]; mask=labels["value_mask"]
    if elementwise.ndim != 1: raise ValueError("policy logits must reduce to a per-sample vector")
    policy_num=(elementwise*decision).sum()
    outcome_num=(-(labels["outcome"]*output["outcome_logits"].log_softmax(-1)).sum(-1)*mask).sum()
    value_num=(((output["value"]-labels["value"])**2)*mask).sum()
    return ({"policy_num":policy_num,"outcome_num":outcome_num,"value_num":value_num},
            {"D":decision.sum(),"M":mask.sum()})

def combine_numerators(totals,denominators):
    """Assemble the three losses and the total from effective-batch totals.

    Quoting a per-microbatch loss here would mix two different denominators;
    the total is always policy + 0.5*outcome + value of the same aggregate.
    """
    d=max(float(denominators["D"]),1.0); m=max(float(denominators["M"]),1.0)
    policy=totals["policy_num"]/d; outcome=totals["outcome_num"]/m; value=totals["value_num"]/m
    return {"policy_loss":policy,"outcome_loss":outcome,"value_loss":value,
            "loss":policy+0.5*outcome+value}

def losses(output,labels):
    """Single-batch convenience wrapper; the trainer uses loss_numerators."""
    totals,counts=loss_numerators(output,labels)
    parts=combine_numerators({k:float(v.detach()) for k,v in totals.items()},
                             {k:float(v.detach()) for k,v in counts.items()})
    return parts["loss"], {**parts,"decision_fraction":labels["decision"].float().mean()}

def _move(batch,device):
    return {k:(v.to(device,non_blocking=True) if torch.is_tensor(v) else v) for k,v in batch.items()}

def _save(path,model,optimizer,step,epoch,best,backend,config,data_fingerprint):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    from .encoding import ENCODING_REVISION
    from .util import SCHEMA_VERSION
    payload={"format_version":1,"model_config":asdict(model.config),"model_state":model.state_dict(),
             "encoding_revision":ENCODING_REVISION,"observation_schema":SCHEMA_VERSION,
             "loss_revision":LOSS_REVISION,
             "optimizer_state":optimizer.state_dict(),"step":step,"epoch":epoch,"best_val":best,
             "backend":backend,"train_config":config,"data_fingerprint":data_fingerprint,
             "torch_rng":torch.get_rng_state(),"python_rng":random.getstate()}
    if torch.cuda.is_available(): payload["cuda_rng"]=torch.cuda.get_rng_state_all()
    tmp=path.with_suffix(path.suffix+".tmp"); torch.save(payload,tmp); os.replace(tmp,path)

@torch.inference_mode()
def validate(model,loader,device,max_batches=50):
    """Report agreement several ways; the single old number was misleading.

    `teacher_top1_agreement` compared the student's argmax with the argmax of
    the teacher's VISIT distribution, but BeliefSearch breaks visit ties by Q,
    so that argmax is not always the action the teacher actually played.
    `teacher_choice_agreement` uses the recorded action instead. Both are
    reported alongside decision-state-only figures and the policy divergence,
    and forced single-action states are kept out of the decision figures.
    """
    model.eval()
    # Accumulate true numerators and denominators over the WHOLE split, then
    # normalise once. Averaging per-batch means instead would make every
    # reported number depend on the validation batch size.
    totals={"policy_num":0.,"outcome_num":0.,"value_num":0.}
    D=M=0.0
    agree_legacy=agree_choice=0; dec=0; agree_choice_dec=0.0; rows=0; known_rows=0
    kl_sum=0.; entropy_sum=0.; unknown_teacher=0
    per_episode={}; episodes=set()
    for j,(batch,labels) in enumerate(loader):
        if j>=max_batches: break
        episode_ids=labels.get("episode_id")
        batch,labels=_move(batch,device),_move(labels,device)
        with torch.inference_mode(): output=model(batch)
        numerators,counts=loss_numerators(output,labels)
        for key in totals: totals[key]+=float(numerators[key])
        D+=float(counts["D"]); M+=float(counts["M"]); rows+=len(labels["value"])
        student=output["policy_logits"].argmax(-1)
        agree_legacy+=int((student==labels["policy"].argmax(-1)).sum())
        teacher=labels["teacher_action"]
        known=teacher>=0
        known_rows+=int(known.sum()); unknown_teacher+=int((~known).sum())
        if bool(known.any()):
            matched=(student==teacher)&known
            agree_choice+=int(matched.sum())
            decision=labels["decision"]&known
            dec+=int(decision.sum()); agree_choice_dec+=float(matched[decision].sum())
        # KL(teacher||student) over legal actions, with the teacher's own
        # entropy so a plateau is not read as a capacity wall. Mask elementwise
        # terms, never the full tensor against a masked vector.
        logp=output["policy_logits"].log_softmax(-1)
        logp_target=torch.log(labels["policy"].clamp_min(1e-12))
        legal=labels["policy"]>0
        elementwise=(labels["policy"]*(logp_target-logp))
        kl_sum+=float(elementwise[legal].sum())
        entropy_sum+=float((-(labels["policy"]*logp_target))[legal].sum())
        # Per-battle policy KL, the frozen checkpoint-selection metric.
        decision_mask=labels["decision"]
        if episode_ids is not None:
            row_kl=elementwise.sum(-1).detach().cpu().tolist()
            row_decision=decision_mask.detach().cpu().tolist()
            for ep,value,is_decision in zip(episode_ids,row_kl,row_decision):
                episodes.add(ep)
                bucket=per_episode.setdefault(ep,[])
                if is_decision: bucket.append(float(value))
    if rows==0: raise ValueError("Empty validation replay")
    parts=combine_numerators(totals,{"D":D,"M":M})
    battles_with_decisions=sum(1 for v in per_episode.values() if v)
    episode_kl=[sum(v)/len(v) for v in per_episode.values() if v]
    return {**parts,
            "policy_ce_decision":parts["policy_loss"],
            "policy_kl_decision":kl_sum/max(D,1.0),
            "teacher_entropy_decision":entropy_sum/max(D,1.0),
            "teacher_top1_agreement":agree_legacy/max(1,rows),
            "teacher_choice_agreement":agree_choice/max(1,known_rows),
            "teacher_choice_agreement_decision_states":agree_choice_dec/max(1,dec),
            "decision_states":dec,"forced_states":int(D)-dec,
            "unknown_teacher_action_states":unknown_teacher,
            "policy_kl":kl_sum/max(D,1.0),
            "teacher_entropy":entropy_sum/max(D,1.0),
            "decision_numerator_D":D,"masked_numerator_M":M,
            "policy_numerator":totals["policy_num"],
            "outcome_numerator":totals["outcome_num"],
            "value_numerator":totals["value_num"],
            # Primary: mean over battles of the battle's mean decision-state KL.
            "kl_dev":(sum(episode_kl)/len(episode_kl)) if episode_kl else None,
            "battles_seen":len(episodes),"battles_with_decisions":battles_with_decisions,
            "battles_without_decisions":len(episodes)-battles_with_decisions,
            "samples":rows}

def train(train_dirs,val_dirs,output,backend="reference_v1",device="auto",config=None,resume="",init_checkpoint=""):
    if resume and init_checkpoint: raise ValueError("Choose resume OR init_checkpoint, not both")
    cfg={"seed":42,"batch_size":32,"accumulation_steps":2,"learning_rate":3e-4,
         "weight_decay":.01,"max_updates":1000,"epochs":10,"eval_every":100,
         "save_every":100,"validation_batches":50,"shuffle_buffer":512,"amp":True,
         "cpu_threads":4,"model":{}}
    cfg.update(config or {})
    for key in ("batch_size","accumulation_steps","max_updates","epochs","eval_every","save_every","validation_batches","shuffle_buffer","cpu_threads"):
        if cfg[key] < 1: raise ValueError(f"{key} must be positive")
    torch.set_num_threads(cfg["cpu_threads"])
    # Separate streams: the data order must stay fixed across a paired comparison so
    # widths differ only by shape, while initialisation is what the seed varies.
    cfg.setdefault("init_seed",cfg["seed"]); cfg.setdefault("data_seed",cfg["seed"])
    random.seed(cfg["data_seed"]); torch.manual_seed(cfg["init_seed"])
    dev=resolve_device(device)
    if dev.type == "cuda": torch.cuda.reset_peak_memory_stats(dev)
    out=Path(output); out.mkdir(parents=True,exist_ok=True)
    if (out/"last.pt").exists() and not resume:
        raise ValueError("Output already contains a checkpoint; use --resume or a new directory")
    ds=ReplayDataset(train_dirs,backend,"train",cfg["data_seed"],cfg["shuffle_buffer"])
    vd=ReplayDataset(val_dirs,backend,"val",cfg["data_seed"],1)
    if ds.objectives!=vd.objectives: raise ValueError("Train/validation utility objectives differ")
    # If directory provenance is mixed, even disjoint sample rows are not accepted.
    fingerprint=digest({"train":ds.fingerprints,"val":vd.fingerprints,"train_files":[str(p.resolve()) for p in ds.files],"val_files":[str(p.resolve()) for p in vd.files]})
    loader=DataLoader(ds,batch_size=cfg["batch_size"],num_workers=0,collate_fn=collate_samples,pin_memory=dev.type=="cuda")
    vloader=DataLoader(vd,batch_size=cfg["batch_size"],num_workers=0,collate_fn=collate_samples)
    model=CombatNet(ModelConfig(**cfg["model"])).to(dev)
    if init_checkpoint:
        ck=torch.load(init_checkpoint,map_location="cpu",weights_only=True)
        if ck["backend"]!=backend or ck["model_config"]!=asdict(model.config): raise ValueError("Warm-start architecture/backend mismatch")
        model.load_state_dict(ck["model_state"])
    optimizer=torch.optim.AdamW(model.parameters(),lr=cfg["learning_rate"],weight_decay=cfg["weight_decay"])
    step=0; start_epoch=0; best=float("inf"); best_record=None; dropped_tail_rows=0
    if resume:
        ck=torch.load(resume,map_location="cpu",weights_only=True)
        if ck["backend"] != backend or ck["model_config"] != asdict(model.config): raise ValueError("Resume architecture/backend mismatch")
        if ck["data_fingerprint"] != fingerprint: raise ValueError("Resume data changed; start a new training run")
        model.load_state_dict(ck["model_state"]); optimizer.load_state_dict(ck["optimizer_state"])
        for state in optimizer.state.values():
            for key,value in state.items():
                if isinstance(value,torch.Tensor): state[key]=value.to(dev)
        step=ck["step"]; start_epoch=ck["epoch"]; best=ck["best_val"]
        torch.set_rng_state(ck["torch_rng"]); random.setstate(ck["python_rng"])
        if dev.type=="cuda" and "cuda_rng" in ck: torch.cuda.set_rng_state_all(ck["cuda_rng"])
        # Optimizer/RNG resume is supported. A partially consumed epoch restarts;
        # this is intentionally documented as NOT bit-exact sample-cursor resume.
    amp=bool(cfg["amp"] and dev.type=="cuda" and torch.cuda.is_bf16_supported())
    started=time.perf_counter(); seen=0; epoch=start_epoch
    atomic_json(out/"run.json",{"backend":backend,"device":str(dev),"config":cfg,
                "parameters":sum(p.numel() for p in model.parameters()),"data_fingerprint":fingerprint,
                "data_provenance":{"train":ds.provenance,"val":vd.provenance},
                "torch_version":str(torch.__version__),"amp_bfloat16":amp,"resume":str(resume),
                "init_checkpoint":str(init_checkpoint),
                "init_seed":cfg["init_seed"],"data_seed":cfg["data_seed"],
                "validation_batches":cfg["validation_batches"],
                "selection_metric":"kl_dev (mean over battles of battle mean decision-state KL)",
                "loss_revision":LOSS_REVISION,
                "objective":"effective-batch numerators over window denominators; "
                            "L_total = L_policy + 0.5*L_outcome + L_value"})
    try:
        for epoch in range(start_epoch,cfg["epochs"]):
            if step>=cfg["max_updates"]: break
            ds.epoch=epoch; model.train(); optimizer.zero_grad(set_to_none=True); pending=0; window=[]
            for batch,labels in loader:
                batch,labels=_move(batch,dev),_move(labels,dev)
                # Cache the window's labels first so the effective-batch
                # denominators are known before any gradient is produced.
                window.append((batch,labels)); pending+=1; seen+=len(labels["value"])
                if pending<cfg["accumulation_steps"]: continue
                denominators={"D":sum(float(l["decision"].sum()) for _,l in window),
                              "M":sum(float(l["value_mask"].sum()) for _,l in window)}
                totals={"policy_num":0.,"outcome_num":0.,"value_num":0.}
                d=max(denominators["D"],1.0); m=max(denominators["M"],1.0)
                for micro_batch,micro_labels in window:
                    with torch.autocast(device_type=dev.type,dtype=torch.bfloat16,enabled=amp):
                        output=model(micro_batch)
                        numerators,_=loss_numerators(output,micro_labels)
                    for key in totals: totals[key]+=float(numerators[key].detach())
                    # Each microbatch contributes its own numerators over the SAME
                    # effective-batch denominators, then its graph is released.
                    contribution=(numerators["policy_num"]/d
                                  +0.5*numerators["outcome_num"]/m
                                  +numerators["value_num"]/m)
                    if not torch.isfinite(contribution): raise FloatingPointError("Nonfinite loss")
                    contribution.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
                optimizer.step(); optimizer.zero_grad(set_to_none=True); window.clear(); pending=0; step+=1
                entry={"step":step,"epoch":epoch,"samples_seen_this_process":seen,
                       "elapsed_seconds":time.perf_counter()-started,
                       "effective_batch_decision_states":denominators["D"],
                       "effective_batch_masked_states":denominators["M"],
                       "effective_batch_samples":cfg["batch_size"]*cfg["accumulation_steps"],
                       # the actual numerators and denominators of this update
                       "policy_numerator":totals["policy_num"],"outcome_numerator":totals["outcome_num"],
                       "value_numerator":totals["value_num"]}
                entry.update(combine_numerators(totals,denominators))
                if dev.type=="cuda": entry["peak_allocated_bytes"]=torch.cuda.max_memory_allocated(dev)
                append_json(out/"metrics.jsonl",entry)
                if step % cfg["eval_every"]==0 or step==cfg["max_updates"]:
                    val=validate(model,vloader,dev,cfg["validation_batches"])
                    append_json(out/"validation.jsonl",{"step":step,**val})
                    # Selection is the frozen primary metric: mean over battles of the
                    # battle's mean decision-state KL. Ties keep the EARLIER step, so the
                    # comparison is strict and the rule does not favour longer training.
                    primary=val.get("kl_dev")
                    if primary is not None and (best_record is None or primary<best_record[0]-1e-12):
                        best=float(val["loss"]); best_record=(primary,step)
                        _save(out/"best.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
                    model.train()
                if step % cfg["save_every"]==0: _save(out/"last.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
                if step>=cfg["max_updates"]: break
            # A trailing partial window is discarded, as before, rather than
            # scaled up to a full one. The discarded row count is recorded so the
            # budget is auditable instead of implicit.
            dropped_tail_rows+=pending*cfg["batch_size"]
            optimizer.zero_grad(set_to_none=True)
        if step==0: raise ValueError("No optimizer updates; reduce batch_size/accumulation_steps or collect more data")
        val=validate(model,vloader,dev,cfg["validation_batches"])
        primary=val.get("kl_dev")
        if primary is not None and (best_record is None or primary<best_record[0]-1e-12) \
                or not (out/"best.pt").exists():
            best=float(val["loss"]) if best_record is None or primary is not None else best
            best_record=(primary,step) if primary is not None else best_record
            _save(out/"best.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        _save(out/"last.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        report={"steps":step,"backend":backend,"parameters":sum(p.numel() for p in model.parameters()),
                "validation":val,"best_validation_loss":best,"best_selection_metric":best_record,
                "loss_revision":LOSS_REVISION,"dropped_tail_rows":dropped_tail_rows,
                "selection_metric":"kl_dev (mean over battles of battle mean decision-state KL)",
                "elapsed_seconds":time.perf_counter()-started}
        atomic_json(out/"training_summary.json",report); return report
    except (KeyboardInterrupt,RuntimeError,FloatingPointError):
        # Save model + optimizer only at last complete update; partial gradients
        # are not in the checkpoint. OOM is surfaced, never hidden as success.
        _save(out/"interrupted.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        raise
