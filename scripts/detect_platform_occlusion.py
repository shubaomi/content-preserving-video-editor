#!/usr/bin/env python3
"""Detect collisions with optional, versioned platform UI templates and opaque layers."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw

def area(b): return max(0,b["x1"]-b["x0"])*max(0,b["y1"]-b["y0"])
def overlap(a,b): return max(0,min(a["x1"],b["x1"])-max(a["x0"],b["x0"]))*max(0,min(a["y1"],b["y1"])-max(a["y0"],b["y0"]))
def analyze(elements,zones):
    findings=[]
    for e in elements:
        for z in zones:
            ratio=overlap(e,z)/max(area(e),1e-9)
            if ratio>.05: findings.append({"code":"platform_ui_collision","element":e["id"],"role":e.get("role"),"zone":z["id"],"overlap_ratio":round(ratio,4),"repair":"move inward, reduce size, or choose the opposite safe zone"})
    for lower in elements:
        for upper in elements:
            if upper.get("z",0)<=lower.get("z",0) or upper.get("opacity",1)<.9: continue
            ratio=overlap(lower,upper)/max(area(lower),1e-9)
            if ratio>.5: findings.append({"code":"opaque_layer_occlusion","element":lower["id"],"occluder":upper["id"],"overlap_ratio":round(ratio,4),"repair":"raise z-order, move layers, or make the occluder intentionally transparent"})
    return findings
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--frame",required=True);p.add_argument("--elements",required=True);p.add_argument("--platform",required=True);p.add_argument("--orientation",choices=("portrait","landscape"),required=True);p.add_argument("--templates",default=str(Path(__file__).parents[1]/"references"/"platform-ui-templates.json"));p.add_argument("--out",required=True);p.add_argument("--annotated",required=True);a=p.parse_args()
    config=json.loads(Path(a.templates).read_text(encoding="utf-8")); zones=((config.get("templates") or {}).get(a.platform) or {}).get(a.orientation); elements=json.loads(Path(a.elements).read_text(encoding="utf-8"))["elements"]
    warnings=[]
    if zones is None: zones=[]; warnings.append("no current platform UI template; safety is unknown")
    findings=analyze(elements,zones); image=Image.open(a.frame).convert("RGB");d=ImageDraw.Draw(image);w,h=image.size
    for z in zones:d.rectangle((z["x0"]*w,z["y0"]*h,z["x1"]*w,z["y1"]*h),outline="#ef4444",width=max(3,w//300));d.text((z["x0"]*w+4,z["y0"]*h+4),z["id"],fill="#ef4444")
    for e in elements:d.rectangle((e["x0"]*w,e["y0"]*h,e["x1"]*w,e["y1"]*h),outline="#22c55e",width=max(3,w//300));d.text((e["x0"]*w+4,e["y0"]*h+4),e["id"],fill="#22c55e")
    ann=Path(a.annotated);ann.parent.mkdir(parents=True,exist_ok=True);image.save(ann,quality=92);report={"schema_version":1,"platform":a.platform,"orientation":a.orientation,"template_version":config["template_version"],"template_verified_on":config["verified_on"],"warnings":warnings,"findings":findings,"annotated":str(ann),"passed":not findings and not warnings};out=Path(a.out);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(out);return 0 if report["passed"] else 2
if __name__=="__main__":raise SystemExit(main())
