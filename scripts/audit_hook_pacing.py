#!/usr/bin/env python3
"""Measure opening clarity and chapter pacing without authorizing semantic cuts."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from editorial_promise import validate_promise_bindings
CUES=("今天","分享","介绍","关键","为什么","怎么","效果","问题","功能","结论")
def audit(transcript,visual=None,promise_ledger=None):
    segs=transcript.get("segments",[]);duration=max((float(s.get("end",0)) for s in segs),default=0);first=next((s for s in segs if str(s.get("text","")).strip()),None);first_speech=float(first["start"]) if first else None
    evidence=next((s for s in segs if any(c in str(s.get("text","")) for c in CUES)),first);first_value=float(evidence["start"]) if evidence else None
    opening=[s for s in segs if float(s.get("start",0))<15];opening_text="".join(str(s.get("text","")) for s in opening);clarity=min(5,sum(c in opening_text for c in CUES));dead=max(0,first_speech or 0);duplicate=sum(1 for i,s in enumerate(opening) for t in opening[:i] if str(s.get("text","")).strip()==str(t.get("text","")).strip() and str(s.get("text","")).strip())
    bins=max(1,math.ceil(duration/30));density=[]
    for i in range(bins):density.append({"start":i*30,"end":min(duration,(i+1)*30),"spoken_segments":sum(i*30<=float(s.get("start",0))<(i+1)*30 for s in segs)})
    monotony=((visual or {}).get("visual_analysis") or {}).get("monotony_candidates",[])
    measurements={"duration":round(duration,3),"first_speech":first_speech,"first_value":first_value,"opening_dead_time":round(dead,3),"duplicate_opening_segments":duplicate,"chapter_density":density,"visual_monotony_evidence":monotony}
    judgments={"topic_clarity_score_0_5":clarity,"visible_evidence_score_0_5":min(5,2+int(first_value is not None and first_value<8)),"first_value_score_0_5":5 if first_value is not None and first_value<5 else 3 if first_value is not None and first_value<12 else 1,"heuristic_only":True}
    suggestions=[]
    if dead>1:suggestions.append({"timestamp":0,"suggestion":"review leading dead time","evidence":f"first speech at {dead:.2f}s","requires_semantic_deletion_approval":False})
    if first_value is not None and first_value>8:suggestions.append({"timestamp":first_value,"suggestion":"preview the first concrete value earlier with an overlay; do not delete setup automatically","evidence":f"first value cue at {first_value:.2f}s","requires_semantic_deletion_approval":True})
    if monotony:suggestions.append({"timestamp":monotony[0].get("timestamp"),"suggestion":"consider a nonredundant visual beat in this repetitive interval","evidence":"frame-change analysis","requires_semantic_deletion_approval":False})
    result={"schema_version":1,"measurements":measurements,"heuristic_judgments":judgments,"suggestions":suggestions,"preserve_mode_edl_unchanged":True,"forbidden_automatic_deletions":["caveats","debugging","conclusions"]}
    if promise_ledger:
        proof=list((promise_ledger.get("single_promise") or {}).get("proof_event_ids") or [])
        copy=str((evidence or {}).get("text") or (promise_ledger.get("single_promise") or {}).get("text") or "").strip()
        binding={"surface":"hook","copy":copy,"promise_id":str(promise_ledger.get("promise_id") or ""),"proof_event_ids":proof}
        errors=validate_promise_bindings(promise_ledger,[binding])
        if errors:raise ValueError("; ".join(errors))
        result["promise_binding"]=binding
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--transcript",required=True);p.add_argument("--visual-analysis");p.add_argument("--promise-ledger");p.add_argument("--out",required=True);a=p.parse_args();t=json.loads(Path(a.transcript).read_text(encoding="utf-8"));v=json.loads(Path(a.visual_analysis).read_text(encoding="utf-8")) if a.visual_analysis else None;ledger=json.loads(Path(a.promise_ledger).read_text(encoding="utf-8")) if a.promise_ledger else None;r=audit(t,v,ledger);out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(out);return 0
if __name__=="__main__":raise SystemExit(main())
