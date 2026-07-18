#!/usr/bin/env python3
"""Two-pass EBU R128 normalization while copying the video stream."""
from __future__ import annotations
import argparse,json,os,re,subprocess
from pathlib import Path
def measure(path:Path,target_i:float,target_tp:float,lra:float)->dict:
    r=subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",str(path),"-vn","-af",f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json","-f","null","-"],text=True,encoding="utf-8",errors="replace",capture_output=True,check=True)
    blocks=re.findall(r"\{\s*\"input_i\".*?\}",r.stderr,re.S)
    if not blocks:raise RuntimeError("loudnorm did not return measurement JSON")
    return json.loads(blocks[-1])
def normalize(source:Path,output:Path,target_i=-14.0,target_tp=-1.5,lra=11.0)->dict:
    m=measure(source,target_i,target_tp,lra);flt=(f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_name(output.stem+".partial"+output.suffix)
    try:
        r=subprocess.run(["ffmpeg","-hide_banner","-nostats","-y","-i",str(source),"-map","0:v:0","-map","0:a:0","-c:v","copy","-af",flt,"-c:a","aac","-b:a","192k","-movflags","+faststart",str(temp)],text=True,encoding="utf-8",errors="replace",capture_output=True,check=True)
        os.replace(temp,output)
    finally:
        if temp.exists():temp.unlink()
    return {"source":str(source),"output":str(output),"target":{"integrated_lufs":target_i,"true_peak_dbtp":target_tp,"lra":lra},"first_pass":m,"method":"ffmpeg_two_pass_loudnorm","video_stream":"copied","audio_change":"documented_loudness_repair"}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--source",required=True);p.add_argument("--out",required=True);p.add_argument("--manifest",required=True);p.add_argument("--lufs",type=float,default=-14);p.add_argument("--true-peak",type=float,default=-1.5);p.add_argument("--lra",type=float,default=11);a=p.parse_args();report=normalize(Path(a.source).resolve(),Path(a.out).resolve(),a.lufs,a.true_peak,a.lra);manifest=Path(a.manifest).resolve();manifest.parent.mkdir(parents=True,exist_ok=True);manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(report["output"]);return 0
if __name__=="__main__":raise SystemExit(main())
