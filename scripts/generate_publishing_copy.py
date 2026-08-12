#!/usr/bin/env python3
"""Generate evidence-linked Douyin and WeChat Channels publishing copy."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from editorial_promise import validate_promise_bindings
def clean(text):return re.sub(r"\s+","",str(text)).strip("，。！？,.!?")
def select_claims(transcript,terms=(),count=3):
    segs=[s for s in transcript.get("segments",[]) if 6<=len(clean(s.get("text","")))<=46]
    cues=("关键","因为","所以","不是","可以","功能","实现","觉得","建议")
    def rank(item):
        _,segment=item;text=clean(segment.get("text",""));raw=str(segment.get("text",""))
        topic=sum(t.lower() in text.lower() for t in terms if t)
        cue=sum(c in text for c in cues)
        complete=int(raw.rstrip().endswith(("。","！","？",".","!","?")))
        length_fit=-abs(len(text)-24)
        score=topic*3+complete*3+cue*4
        return (-score,-complete,-cue,-topic,-length_fit,float(segment.get("start",0)))
    ranked=sorted(enumerate(segs),key=rank)
    chosen=[]
    for _,s in ranked:
        if all(abs(float(s["start"])-float(p["start"]))>20 for p in chosen):chosen.append(s)
        if len(chosen)==count:break
    return [{"text":clean(s["text"]),"evidence":{"type":"transcript","start":float(s["start"]),"end":float(s["end"])}} for s in chosen]
def build(title,transcript,terms,promise_ledger=None):
    claims=select_claims(transcript,terms);primary=claims[0] if claims else {"text":title,"evidence":{"type":"user_title"}};term=terms[0] if terms else title;tag_term=re.sub(r"\s+","",term)
    evidence={"title":{"type":"user_supplied_title","value":title},"primary_claim":primary["evidence"],"search_terms":[{"type":"user_supplied_search_term","value":t} for t in terms]}
    common={"claims":claims,"evidence_map":evidence,"claim_policy":"Every factual content statement is linked to transcript evidence; titles and search terms are explicitly user supplied. No performance, product, or personal claims are invented.","external_action_gate":"Publishing/upload requires explicit user action."}
    douyin_title=title[:32]
    douyin={"recommended":{"title":douyin_title,"description":f"一个具体判断：{primary['text']}","hashtags":[f"#{tag_term}","#AI实践"],"pinned_comment":"你最想继续追问哪一点？"},"alternatives":[{"title":f"{term}，先看一个具体判断"},{"title":f"关于{term}，这段交流讲了什么"}],"adaptation":"direct hook, transcript-backed claim, short interaction prompt",**common}
    wechat={"recommended":{"title":title,"description":f"记录一次关于{term}的交流。其中一个具体判断是：{primary['text']}","hashtags":[f"#{tag_term}","#AI实践"],"pinned_comment":"欢迎留下你的理解或不同经验。"},"alternatives":[{"title":f"一次关于{term}的交流记录"},{"title":f"从交流里重新理解{term}"}],"adaptation":"context-first, reflective framing, community discussion",**common}
    result={"schema_version":1,"recommended_platform":"both","douyin":douyin,"wechat_channels":wechat,"search_terms":terms}
    if promise_ledger:
        promise_id=str(promise_ledger.get("promise_id") or "")
        proof=list((promise_ledger.get("single_promise") or {}).get("proof_event_ids") or [])
        result["promise_binding"]={
            "promise_id":promise_id,"proof_event_ids":proof,
            "surfaces":[
                {"surface":"title","copy":douyin["recommended"]["title"],"promise_id":promise_id,"proof_event_ids":proof},
                {"surface":"description","copy":douyin["recommended"]["description"],"promise_id":promise_id,"proof_event_ids":proof},
                {"surface":"title","copy":wechat["recommended"]["title"],"promise_id":promise_id,"proof_event_ids":proof},
                {"surface":"description","copy":wechat["recommended"]["description"],"promise_id":promise_id,"proof_event_ids":proof},
            ],
        }
        errors=validate_promise_bindings(promise_ledger,result["promise_binding"]["surfaces"])
        if errors:raise ValueError("; ".join(errors))
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--title",required=True);p.add_argument("--transcript",required=True);p.add_argument("--term",action="append",default=[]);p.add_argument("--promise-ledger");p.add_argument("--out",required=True);a=p.parse_args();ledger=json.loads(Path(a.promise_ledger).read_text(encoding="utf-8")) if a.promise_ledger else None;r=build(a.title,json.loads(Path(a.transcript).read_text(encoding="utf-8")),a.term,ledger);out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(out);return 0
if __name__=="__main__":raise SystemExit(main())
