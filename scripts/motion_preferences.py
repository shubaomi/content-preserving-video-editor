#!/usr/bin/env python3
"""Record and apply only approved motion preferences with scoped provenance."""
from __future__ import annotations
import argparse,json
from pathlib import Path
FIELDS={"position","scale","duration","easing","density","color","sfx_family","caption_treatment","rejected_patterns","profile","density_target_per_minute","sfx_cues_per_minute","visual_family_rotation","caption_emphasis"}
def load(path):return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema_version":1,"enabled":True,"global":{},"content_types":{},"videos":{},"history":[]}
def record(profile,scope,key,values,provenance,approved):
    if not approved:raise ValueError("Only user-approved final adjustments may be learned; pass --approved")
    if scope not in {"global","content_type","video"}:raise ValueError("A valid --scope is required")
    if scope!="global" and not key:raise ValueError("--key is required for content_type and video scopes")
    if not provenance:raise ValueError("--provenance is required for every learned preference")
    unknown=set(values)-FIELDS
    if unknown:raise ValueError(f"Unsupported preference fields: {sorted(unknown)}")
    target=profile["global"] if scope=="global" else profile["content_types"].setdefault(key,{}) if scope=="content_type" else profile["videos"].setdefault(key,{})
    target.update(values);profile["history"].append({"scope":scope,"key":key,"values":values,"provenance":provenance,"approved":True});return profile
def apply(profile,content_type,video_id,safety=None):
    if not profile.get("enabled",True):return {"enabled":False,"preferences":{},"safety_repairs":[]}
    merged=dict(profile.get("global",{}));merged.update(profile.get("content_types",{}).get(content_type,{}));merged.update(profile.get("videos",{}).get(video_id,{}));repairs=[];safety=safety or {}
    if "position" in merged and merged["position"] in safety.get("forbidden_positions",[]):repairs.append({"field":"position","rejected":merged["position"],"replacement":safety.get("fallback_position","left")});merged["position"]=safety.get("fallback_position","left")
    if "scale" in merged and "max_scale" in safety and float(merged["scale"])>float(safety["max_scale"]):repairs.append({"field":"scale","rejected":merged["scale"],"replacement":safety["max_scale"]});merged["scale"]=safety["max_scale"]
    sources=[]
    if profile.get("global"):sources.append("global")
    if profile.get("content_types",{}).get(content_type):sources.append(f"content_type:{content_type}")
    if profile.get("videos",{}).get(video_id):sources.append(f"video:{video_id}")
    return {"enabled":True,"preferences":merged,"safety_repairs":repairs,"sources":sources}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("command",choices=("record","apply","disable","enable","reset","show"));p.add_argument("--profile",required=True);p.add_argument("--scope",choices=("global","content_type","video"));p.add_argument("--key");p.add_argument("--values");p.add_argument("--values-file");p.add_argument("--provenance");p.add_argument("--approved",action="store_true");p.add_argument("--content-type",default="generic");p.add_argument("--video-id",default="unknown");p.add_argument("--safety");p.add_argument("--out");a=p.parse_args();path=Path(a.profile);profile=load(path)
    if a.command=="record":
        if bool(a.values)==bool(a.values_file):raise ValueError("Provide exactly one of --values or --values-file")
        values=json.loads(Path(a.values_file).read_text(encoding="utf-8")) if a.values_file else json.loads(a.values)
        profile=record(profile,a.scope,a.key,values,a.provenance,a.approved)
    elif a.command=="disable":profile["enabled"]=False
    elif a.command=="enable":profile["enabled"]=True
    elif a.command=="reset":profile={"schema_version":1,"enabled":True,"global":{},"content_types":{},"videos":{},"history":[]}
    elif a.command=="apply":
        result=apply(profile,a.content_type,a.video_id,json.loads(Path(a.safety).read_text(encoding="utf-8")) if a.safety else None);out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(out);return 0
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(profile,ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
