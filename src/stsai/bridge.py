"""CommunicationMod stdin/stdout bridge. Defaults to observe-only.
Supported live capability: Ironclad, Cultist/Jaw Worm, pilot cards, Burning Blood,
no usable potions or unsupported powers. Unsupported states PAUSE, never guess.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from .encoding import normalize
from .contracts import validate_public
from .hints import enrich,BASE
from .util import canonical,digest,append_json,SCHEMA_VERSION

class UnsupportedState(ValueError):pass

def parse_message(message:dict,counters=None)->dict:
    if not message.get("in_game") or not message.get("game_state",{}).get("combat_state"):
        raise UnsupportedState("No active combat")
    g=message["game_state"];c=g["combat_state"]
    if g.get("class")!="IRONCLAD":raise UnsupportedState("Only Ironclad pilot is supported")
    if g.get("screen_type","NONE")!="NONE":raise UnsupportedState("Selection/other screens require an audited adapter")
    relics=g.get("relics",[])
    if {normalize(r.get("id","")) for r in relics}!={"BURNING_BLOOD"}:
        raise UnsupportedState("Unsupported relic set (includes Runic Dome/intent-hiding risk)")
    if any(p.get("id")!="Potion Slot" for p in g.get("potions",[])):
        raise UnsupportedState("Native pilot has no potion coverage")
    powers_allowed={"STRENGTH","DEXTERITY","WEAK","VULNERABLE","FRAIL","METALLICIZE","ARTIFACT","RITUAL"}
    def powers(entity):
        values={normalize(p["id"]):int(p["amount"]) for p in entity.get("powers",[])}
        unknown=set(values)-powers_allowed
        if unknown:raise UnsupportedState(f"Unsupported powers: {sorted(unknown)}")
        return values
    rawp=c["player"];pp=powers(rawp)
    p={"hp":rawp["current_hp"],"max_hp":rawp["max_hp"],"block":rawp["block"],"energy":rawp["energy"],
       "strength":pp.get("STRENGTH",0),"dexterity":pp.get("DEXTERITY",0),"artifact":pp.get("ARTIFACT",0),
       "weak":pp.get("WEAK",0),"vulnerable":pp.get("VULNERABLE",0),"frail":pp.get("FRAIL",0),
       "metallicize":pp.get("METALLICIZE",0),**(counters or {"cards_played":0,"attacks_played":0,"skills_played":0})}
    def card(x):
        name=normalize(x["id"])
        if name not in BASE:raise UnsupportedState(f"Unsupported card: {name}")
        return {"id":name,"upgraded":int(x.get("upgrades",0)),"cost":int(x["cost"]),"type":x["type"],
                "exhaust":bool(x.get("exhausts",False)),"ethereal":bool(x.get("ethereal",False)),
                "targeted":bool(x.get("has_target",False)),"free":False,"retain":False,"special":0}
    enemies=[];powerlist=[]
    for i,e in enumerate(c["monsters"]):
        name=normalize(e["id"])
        if name not in ("CULTIST","JAW_WORM"):raise UnsupportedState(f"Unsupported enemy: {name}")
        ep=powers(e);intent=e.get("intent","UNKNOWN")
        if intent in ("NONE","UNKNOWN","DEBUG") and e.get("current_hp",0)>0:
            raise UnsupportedState("Enemy intent is not reliably visible")
        attack="ATTACK" in intent
        adjusted=e.get("move_adjusted_damage",-1)
        if attack and adjusted<0:raise UnsupportedState("Missing observed adjusted enemy damage")
        # A monster whose base attack is rolled at spawn has a public memory the
        # live bridge cannot rebuild from a single mod snapshot: it would need the
        # whole observed history. Refusing is the honest answer; claiming
        # "not applicable" would assert the model has information it does not.
        if name in ("GREEN_LOUSE", "RED_LOUSE"):
            raise UnsupportedState("Live bridge cannot reconstruct a louse's public attack-base memory")
        enemies.append({"id":name,"slot":i,"hp":int(e["current_hp"]),"max_hp":int(e["max_hp"]),
            "block":int(e["block"]),"strength":ep.get("STRENGTH",0),"weak":ep.get("WEAK",0),
            "vulnerable":ep.get("VULNERABLE",0),"artifact":ep.get("ARTIFACT",0),
            "half_dead":bool(e.get("half_dead",False)),"intent":"ATTACK" if attack else "BUFF",
            "intent_damage":adjusted if attack else 0,"hits":max(1,int(e.get("move_hits",1))) if attack else 0,
            "attack_base_low":-1,"attack_base_high":-1})
        if ep.get("RITUAL"):powerlist.append({"id":"RITUAL","owner":i,"amount":ep["RITUAL"]})
    if len(enemies)!=1:raise UnsupportedState("Pilot live bridge requires one enemy")
    obs={"schema_version":SCHEMA_VERSION,"backend":"lightspeed_pilot","turn":int(c["turn"]),"ascension":int(g.get("ascension_level",0)),
         "phase":"PLAYER_NORMAL","player":p,"enemies":enemies,"known_top":[],"choices":[],"potions":[],"potions_used":0,
         "powers":powerlist,"relics":[{"id":"BURNING_BLOOD","counter":-1}],"terminal":False,"won":False,"actions":[]}
    for zone in ("hand","draw_pile","discard_pile","exhaust_pile"):obs[zone]=[card(x) for x in c.get(zone,[])]
    available={s.lower() for s in message.get("available_commands",[])}
    if "play" in available:
        for i,x in enumerate(c["hand"]):
            if not x.get("is_playable",False):continue
            targets=[e["slot"] for e in enemies if e["hp"]>0 and not e["half_dead"]] if x.get("has_target") else [-1]
            for target in targets:
                obs["actions"].append({"id":f"play:{i}:{target}","kind":"play","source":i,"source_zone":"hand",
                    "target":target,"card_id":obs["hand"][i]["id"],"cost":p["energy"] if x["cost"]==-1 else x["cost"],"selection":[]})
    if "end" in available:obs["actions"].append({"id":"end","kind":"end","source":-1,"source_zone":"none","target":-1,"card_id":"END","cost":0,"selection":[]})
    if not obs["actions"]:raise UnsupportedState("No supported legal combat command")
    obs=enrich(obs);validate_public(obs);return obs

def command_for(action):
    if action["kind"]=="end":return "END"
    if action["kind"]=="play":
        command=f"PLAY {int(action['source'])+1}"
        if action.get("target",-1)>=0:command+=f" {int(action['target'])}"
        return command
    if action["kind"]=="potion":
        command=f"POTION Use {int(action['source'])}"
        if action.get("target",-1)>=0:command+=f" {int(action['target'])}"
        return command
    raise UnsupportedState("Selection commands not enabled in pilot bridge")

def run_bridge(log_path,checkpoint="",device="cpu",execute=False):
    from .search import HeuristicEvaluator
    if execute and not checkpoint:raise ValueError("Executing requires a trained native checkpoint")
    evaluator=HeuristicEvaluator()
    if checkpoint:
        from .model import ModelEvaluator
        evaluator=ModelEvaluator.from_checkpoint(checkpoint,device,"lightspeed_pilot")
    print("ready",flush=True)
    previous=None;repeats=0;paused=False;turn=None;pending=None
    counters={"cards_played":0,"attacks_played":0,"skills_played":0}
    for line in sys.stdin:
        try:message=json.loads(line)
        except json.JSONDecodeError:
            append_json(log_path,{"event":"malformed_json"});continue
        available={str(s).lower() for s in message.get("available_commands",[])}
        command="WAIT 60" if "wait" in available else "STATE"
        entry={"event":"observe","execute":execute}
        try:
            if "error" in message:
                paused=True;raise UnsupportedState("Game rejected previous command; paused for human inspection")
            new_turn=message.get("game_state",{}).get("combat_state",{}).get("turn")
            if new_turn!=turn:
                turn=new_turn;counters={k:0 for k in counters}
            elif pending:
                counters["cards_played"]+=1
                if pending=="ATTACK":counters["attacks_played"]+=1
                if pending=="SKILL":counters["skills_played"]+=1
            pending=None
            if not message.get("ready_for_command",False):raise UnsupportedState("Game not ready")
            obs=parse_message(message,counters);key=digest(obs)
            repeats=repeats+1 if key==previous else 0;previous=key
            if execute and repeats>=3:paused=True
            probabilities,value=evaluator.evaluate(obs)
            j=max(range(len(probabilities)),key=lambda i:probabilities[i]);a=obs["actions"][j]
            proposed=command_for(a)
            entry.update(observation=obs,proposed_command=proposed,value_estimate=value,paused=paused)
            if execute and not paused:
                verb=proposed.split()[0].lower()
                if verb not in available:raise UnsupportedState("Proposed verb is not available")
                command=proposed
                if a["kind"]=="play":pending=obs["hand"][a["source"]]["type"]
        except (UnsupportedState,ValueError,KeyError) as exc:
            entry.update(event="pause",reason=str(exc))
        entry["sent_command"]=command;append_json(log_path,entry)
        # stdout contains ONLY protocol commands. STATE polling is rate limited.
        if command=="STATE":time.sleep(.5)
        print(command,flush=True)
