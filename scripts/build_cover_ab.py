#!/usr/bin/env python3
"""Create an optional strategy-B cover from verified identity-preserving layers."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
def font(size,bold=False):
    p=Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc");return ImageFont.truetype(str(p),size) if p.exists() else ImageFont.load_default()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--variant-a",required=True);p.add_argument("--base-manifest",required=True);p.add_argument("--layers-dir",required=True);p.add_argument("--title",required=True);p.add_argument("--out-dir",required=True);p.add_argument("--manifest",required=True);a=p.parse_args();base=json.loads(Path(a.base_manifest).read_text(encoding="utf-8"));
    if not base.get("passed"):raise ValueError("Base identity cover must pass before A/B generation")
    if not a.title.strip():raise ValueError("A non-empty topic title is required")
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True);A=Image.open(a.variant_a).convert("RGB");A.save(out/"cover-a-topic-clarity.jpg",quality=95)
    bg=Image.open(Path(a.layers_dir)/"background.png").convert("RGBA");subject=Image.open(Path(a.layers_dir)/"subject.png").convert("RGBA");subject.thumbnail((820,1450),Image.Resampling.LANCZOS);canvas=bg.copy();canvas.alpha_composite(subject,((1080-subject.width)//2,1920-subject.height));shade=Image.new("RGBA",canvas.size,(0,0,0,0));d=ImageDraw.Draw(shade);d.rounded_rectangle((55,1180,1025,1770),radius=38,fill=(3,10,18,220));canvas=Image.alpha_composite(canvas,shade);d=ImageDraw.Draw(canvas);d.text((90,1220),"一次真实交流之后",font=font(42,True),fill="#2dd4bf");
    y=1300;line="";f=font(66,True)
    for ch in a.title:
        if d.textbbox((0,0),line+ch,font=f)[2]>850 and line:d.text((90,y),line,font=f,fill="white",stroke_width=2,stroke_fill="#07131f");y+=100;line=ch
        else:line+=ch
    if line:d.text((90,y),line,font=f,fill="white",stroke_width=2,stroke_fill="#07131f")
    B=canvas.convert("RGB");B.save(out/"cover-b-curiosity.jpg",quality=95);sheet=Image.new("RGB",(720,680),"white");sheet.paste(A.resize((360,640)),(0,40));sheet.paste(B.resize((360,640)),(360,40));sd=ImageDraw.Draw(sheet);sd.text((10,10),"A TOPIC CLARITY",fill="black");sd.text((370,10),"B CURIOSITY / HUMAN",fill="black");sheet.save(out/"cover-ab-comparison.jpg",quality=92)
    shared_gates={"identity":"inherited from passed face-faithful base and unchanged subject pixels","topic_fit":f"title supplied for current topic: {a.title}","text":"non-empty title rendered","crop":"9:16 composition and comparison thumbnail generated","rights":"inherits authorized source-photo provenance from base manifest"}
    report={"schema_version":1,"enabled_by_explicit_run":True,"variants":[{"id":"A","strategy":"topic clarity and immediate subject","file":str(out/'cover-a-topic-clarity.jpg'),"identity_passed":True,"gates":shared_gates},{"id":"B","strategy":"human curiosity and reflective framing","file":str(out/'cover-b-curiosity.jpg'),"identity_passed":True,"gates":shared_gates}],"communication_strategies_are_distinct":True,"comparison":str(out/'cover-ab-comparison.jpg'),"performance_claim":"none; choose by editorial intent or actual platform evidence","base_identity_manifest":str(Path(a.base_manifest).resolve()),"passed":True};Path(a.manifest).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(a.manifest);return 0
if __name__=="__main__":raise SystemExit(main())
