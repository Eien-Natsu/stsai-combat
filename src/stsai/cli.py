from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .util import load_json

def main():
    p=argparse.ArgumentParser(prog="stsai",description="Combat workbench: reference results are not original-game results")
    sub=p.add_subparsers(dest="cmd",required=True)
    d=sub.add_parser("doctor");d.add_argument("--output",default="runs/doctor.json");d.add_argument("--require-cuda",action="store_true")
    c=sub.add_parser("collect")
    c.add_argument("--output",required=True);c.add_argument("--backend",default="reference_v1",choices=["reference_v1","lightspeed_pilot"])
    c.add_argument("--split",default="train",choices=["train","val"]);c.add_argument("--count",type=int,default=16);c.add_argument("--start",type=int,default=0)
    c.add_argument("--workers",type=int,default=1);c.add_argument("--config",default="configs/smoke.json")
    c.add_argument("--checkpoint",default="");c.add_argument("--iteration",type=int,default=0);c.add_argument("--sample-actions",action="store_true")
    t=sub.add_parser("train");t.add_argument("--train-data",nargs="+",required=True);t.add_argument("--val-data",nargs="+",required=True)
    t.add_argument("--output",required=True);t.add_argument("--backend",default="reference_v1");t.add_argument("--device",default="auto")
    t.add_argument("--config",default="configs/smoke.json");t.add_argument("--resume",default="");t.add_argument("--init-checkpoint",default="")
    e=sub.add_parser("evaluate");e.add_argument("--output",required=True);e.add_argument("--backend",default="reference_v1")
    e.add_argument("--agents",nargs="+",default=["heuristic","search"]);e.add_argument("--count",type=int,default=16)
    e.add_argument("--split",default="val",choices=["val","test"]);e.add_argument("--checkpoint",default="");e.add_argument("--device",default="cpu")
    e.add_argument("--config",default="configs/smoke.json");e.add_argument("--manifest",default="")
    m=sub.add_parser("make-test-manifest");m.add_argument("--output",required=True);m.add_argument("--backend",required=True);m.add_argument("--count",type=int,default=1000)
    f=sub.add_parser("mine");f.add_argument("--data",nargs="+",required=True);f.add_argument("--output",required=True);f.add_argument("--limit",type=int,default=100)
    b=sub.add_parser("bridge");b.add_argument("--log",default="runs/live/bridge.jsonl");b.add_argument("--checkpoint",default="")
    b.add_argument("--device",default="cpu");b.add_argument("--execute",action="store_true")
    args=p.parse_args()
    try:
        cfg=load_json(args.config) if hasattr(args,"config") else {}
        if args.cmd=="doctor":
            from .doctor import doctor
            result=doctor(args.output,args.require_cuda)
        elif args.cmd=="collect":
            from .collection import collect
            result=collect(args.output,args.backend,args.split,args.count,args.start,args.workers,cfg.get("search"),args.checkpoint,
                cfg.get("master_seed",20260916),cfg.get("max_actions",256),args.iteration,args.sample_actions)
        elif args.cmd=="train":
            from .training import train
            result=train(args.train_data,args.val_data,args.output,args.backend,args.device,cfg.get("training"),args.resume,args.init_checkpoint)
        elif args.cmd=="evaluate":
            from .evaluation import evaluate
            result=evaluate(args.output,args.backend,args.agents,args.count,args.split,cfg.get("master_seed",20260916),args.checkpoint,
                args.device,cfg.get("search"),cfg.get("max_actions",256),args.manifest)
        elif args.cmd=="make-test-manifest":
            from .evaluation import make_manifest
            result=make_manifest(args.output,args.backend,args.count)
        elif args.cmd=="mine":
            from .mining import mine
            result=mine(args.data,args.output,args.limit)
        else:
            from .bridge import run_bridge
            run_bridge(args.log,args.checkpoint,args.device,args.execute);return
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    except (ValueError,RuntimeError,OSError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr);raise SystemExit(2)

if __name__=="__main__":main()
