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
    labels={"policy":policy,"outcome":torch.tensor([s["outcome"] for s in samples]),
            "value":torch.tensor([s["value"] for s in samples]),
            "value_mask":torch.tensor([s["value_mask"] for s in samples])}
    return batch,labels

def losses(output,labels):
    policy=-(labels["policy"]*output["policy_logits"].log_softmax(-1)).sum(-1).mean()
    mask=labels["value_mask"]; count=mask.sum().clamp_min(1)
    outcome=(-(labels["outcome"]*output["outcome_logits"].log_softmax(-1)).sum(-1)*mask).sum()/count
    value=(((output["value"]-labels["value"])**2)*mask).sum()/count
    return policy+.5*outcome+value, {"policy_loss":policy,"outcome_loss":outcome,"value_loss":value}

def _move(batch,device): return {k:v.to(device,non_blocking=True) for k,v in batch.items()}

def _save(path,model,optimizer,step,epoch,best,backend,config,data_fingerprint):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    payload={"format_version":1,"model_config":asdict(model.config),"model_state":model.state_dict(),
             "optimizer_state":optimizer.state_dict(),"step":step,"epoch":epoch,"best_val":best,
             "backend":backend,"train_config":config,"data_fingerprint":data_fingerprint,
             "torch_rng":torch.get_rng_state(),"python_rng":random.getstate()}
    if torch.cuda.is_available(): payload["cuda_rng"]=torch.cuda.get_rng_state_all()
    tmp=path.with_suffix(path.suffix+".tmp"); torch.save(payload,tmp); os.replace(tmp,path)

@torch.inference_mode()
def validate(model,loader,device,max_batches=50):
    model.eval(); total=0; sums={"loss":0.,"policy_loss":0.,"outcome_loss":0.,"value_loss":0.}
    agree=0
    for j,(batch,labels) in enumerate(loader):
        if j>=max_batches: break
        batch,labels=_move(batch,device),_move(labels,device)
        output=model(batch); loss,metrics=losses(output,labels); n=len(labels["value"])
        sums["loss"]+=float(loss)*n
        for key,value in metrics.items(): sums[key]+=float(value)*n
        agree+=int((output["policy_logits"].argmax(-1)==labels["policy"].argmax(-1)).sum())
        total+=n
    if total == 0: raise ValueError("Empty validation replay")
    return {**{k:v/total for k,v in sums.items()},"teacher_top1_agreement":agree/total,"samples":total}

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
    random.seed(cfg["seed"]); torch.manual_seed(cfg["seed"])
    dev=resolve_device(device)
    if dev.type == "cuda": torch.cuda.reset_peak_memory_stats(dev)
    out=Path(output); out.mkdir(parents=True,exist_ok=True)
    if (out/"last.pt").exists() and not resume:
        raise ValueError("Output already contains a checkpoint; use --resume or a new directory")
    ds=ReplayDataset(train_dirs,backend,"train",cfg["seed"],cfg["shuffle_buffer"])
    vd=ReplayDataset(val_dirs,backend,"val",cfg["seed"],1)
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
    step=0; start_epoch=0; best=float("inf")
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
                "torch_version":str(torch.__version__),"amp_bfloat16":amp,"resume":str(resume),"init_checkpoint":str(init_checkpoint)})
    try:
        for epoch in range(start_epoch,cfg["epochs"]):
            if step>=cfg["max_updates"]: break
            ds.epoch=epoch; model.train(); optimizer.zero_grad(set_to_none=True); pending=0
            for batch,labels in loader:
                batch,labels=_move(batch,dev),_move(labels,dev)
                with torch.autocast(device_type=dev.type,dtype=torch.bfloat16,enabled=amp):
                    output=model(batch); loss,parts=losses(output,labels)
                if not torch.isfinite(loss): raise FloatingPointError("Nonfinite loss")
                (loss/cfg["accumulation_steps"]).backward(); pending+=1; seen+=len(labels["value"])
                if pending<cfg["accumulation_steps"]: continue
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
                optimizer.step(); optimizer.zero_grad(set_to_none=True); pending=0; step+=1
                entry={"step":step,"epoch":epoch,"loss":float(loss.detach()),"samples_seen_this_process":seen,
                       "elapsed_seconds":time.perf_counter()-started}
                entry.update({k:float(v.detach()) for k,v in parts.items()})
                if dev.type=="cuda": entry["peak_allocated_bytes"]=torch.cuda.max_memory_allocated(dev)
                append_json(out/"metrics.jsonl",entry)
                if step % cfg["eval_every"]==0 or step==cfg["max_updates"]:
                    val=validate(model,vloader,dev,cfg["validation_batches"])
                    append_json(out/"validation.jsonl",{"step":step,**val})
                    if val["loss"]<best:
                        best=val["loss"]; _save(out/"best.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
                    model.train()
                if step % cfg["save_every"]==0: _save(out/"last.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
                if step>=cfg["max_updates"]: break
            # Partial accumulation is discarded, rather than silently applying
            # incorrectly scaled gradients. Keep batch*accum <= replay samples.
            optimizer.zero_grad(set_to_none=True)
        if step==0: raise ValueError("No optimizer updates; reduce batch_size/accumulation_steps or collect more data")
        val=validate(model,vloader,dev,cfg["validation_batches"])
        if val["loss"]<best or not (out/"best.pt").exists():
            best=val["loss"]; _save(out/"best.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        _save(out/"last.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        report={"steps":step,"backend":backend,"parameters":sum(p.numel() for p in model.parameters()),
                "validation":val,"best_validation_loss":best,"elapsed_seconds":time.perf_counter()-started}
        atomic_json(out/"training_summary.json",report); return report
    except (KeyboardInterrupt,RuntimeError,FloatingPointError):
        # Save model + optimizer only at last complete update; partial gradients
        # are not in the checkpoint. OOM is surfaced, never hidden as success.
        _save(out/"interrupted.pt",model,optimizer,step,epoch,best,backend,cfg,fingerprint)
        raise
