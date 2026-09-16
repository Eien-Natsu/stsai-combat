"""Public card-effect hints for priors/features, NEVER the legality/rules engine.
Values are estimates for the restricted pilot, not a generic effects interpreter.
"""
from __future__ import annotations
import math
from .encoding import normalize
from .util import canonical

# base damage, upgraded damage, base block, upgraded block, draw, upgraded draw
BASE={
 "STRIKE":(6,9,0,0,0,0),"DEFEND":(0,0,5,8,0,0),"BASH":(8,10,0,0,0,0),
 "POMMEL_STRIKE":(9,10,0,0,1,2),"SHRUG_IT_OFF":(0,0,8,11,1,1),
 "IRON_WAVE":(5,7,5,7,0,0),"CLEAVE":(8,11,0,0,0,0),"UPPERCUT":(13,13,0,0,0,0),
 "CARNAGE":(20,28,0,0,0,0),"TWIN_STRIKE":(5,7,0,0,0,0),"METALLICIZE":(0,0,0,0,0,0),
 "IMPERVIOUS":(0,0,30,40,0,0),"GHOSTLY_ARMOR":(0,0,10,13,0,0),"DISARM":(0,0,0,0,0,0),
 "INFLAME":(0,0,0,0,0,0),"HEAVY_BLADE":(14,14,0,0,0,0),"ANGER":(6,8,0,0,0,0),
 "WHIRLWIND":(5,8,0,0,0,0),"THUNDERCLAP":(4,7,0,0,0,0),"BLUDGEON":(32,42,0,0,0,0),
 "ASCENDERS_BANE":(0,0,0,0,0,0)
}

def enrich(obs):
    p=obs["player"]
    for zone in ("hand","draw_pile","discard_pile","exhaust_pile","known_top","choices"):
        for c in obs.get(zone,[]):
            c["id"]=normalize(c["id"])
            if c["id"] not in BASE: raise ValueError(f"Unsupported pilot card {c['id']}")
            d=BASE[c["id"]]; up=bool(c.get("upgraded",0))
            c["damage"]=d[int(up)]; c["block"]=d[2+int(up)]; c["draw"]=d[4+int(up)]
            c["hits"]=2 if c["id"]=="TWIN_STRIKE" else 1
    for e in obs["enemies"]: e["id"]=normalize(e["id"])
    for a in obs["actions"]:
        if a["kind"]!="play": continue
        c=obs["hand"][a["source"]]; name=c["id"]; up=bool(c["upgraded"])
        a["card_id"]=name
        hits=p["energy"] if name=="WHIRLWIND" else c["hits"]
        targets=[e for e in obs["enemies"] if e["hp"]>0 and (a["target"]<0 or e["slot"]==a["target"])]
        total=0
        for e in targets:
            if c["damage"]:
                mult=(5 if up else 3) if name=="HEAVY_BLADE" else 1
                damage=max(0,c["damage"]+mult*p.get("strength",0))
                factor=(.75 if p.get("weak",0) else 1)*(1.5 if e.get("vulnerable",0) else 1)
                total+=math.floor(damage*factor)*hits
        block=max(0,c["block"]+p.get("dexterity",0)) if c["block"] else 0
        if p.get("frail",0): block=math.floor(block*.75)
        a.update(damage=total,block=block,draw=c["draw"],hits=hits)
        a["weak"]=(2 if up else 1) if name=="UPPERCUT" else 0
        a["vulnerable"]=(3 if up else 2) if name=="BASH" else ((2 if up else 1) if name=="UPPERCUT" else (1 if name=="THUNDERCLAP" else 0))
        a["buff"]=(3 if up else 2) if name in ("INFLAME","DISARM") else ((4 if up else 3) if name=="METALLICIZE" else 0)
    obs["draw_pile"].sort(key=canonical)
    return obs
