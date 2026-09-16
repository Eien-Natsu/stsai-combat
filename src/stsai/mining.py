from __future__ import annotations
import gzip
import heapq
import json
from pathlib import Path
from .util import atomic_json

def mine(directories,output,limit=100):
    if limit<1:raise ValueError("limit must be positive")
    heap=[];counter=0
    for directory in directories:
        for path in sorted(Path(directory).glob("episode_*.jsonl.gz")):
            with gzip.open(path,"rt",encoding="utf-8") as f:
                for line in f:
                    row=json.loads(line)
                    if row["split"]=="test":raise ValueError("Never mine final-test cases into training")
                    if not row["value_mask"]:continue
                    expected=sum(p*q for p,q in zip(row["policy"],row["search_q"]))
                    surprise=abs(expected-row["value"])
                    priority=surprise+(1.0 if row["outcome"][0]>.5 else 0)
                    item=(priority,counter,{"priority":priority,"estimated_value_surprise":surprise,"sample":row})
                    counter+=1
                    if len(heap)<limit:heapq.heappush(heap,item)
                    elif priority>heap[0][0]:heapq.heapreplace(heap,item)
    cases=[item[2] for item in sorted(heap,key=lambda x:(-x[0],x[1]))]
    report={"criterion":"Death/value-surprise triage, NOT proven regret or root-cause attribution","cases":cases}
    atomic_json(output,report);return {"selected":len(cases),"scanned":counter,"output":str(output)}
