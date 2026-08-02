#!/usr/bin/env python3
"""Run a dependency-aware render pipeline with hash-compatible resumable stages."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path

from dependency_graph import DependencyGraph, DependencyGraphError

ORDER=("extraction","graphics_render","video_encode","audio_mix","mux","verification")
SAFE_STAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
def file_hash(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def stable_hash(value)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def stage_signature(stage:dict,root:Path,dep_sigs:dict,settings:dict)->str:
    inputs={str(p):file_hash((root/p).resolve()) for p in stage.get("inputs",[]) if (root/p).is_file()}
    missing=[str(p) for p in stage.get("inputs",[]) if not (root/p).is_file()]
    return stable_hash({"inputs":inputs,"missing":missing,"dependencies":{d:dep_sigs[d] for d in stage.get("depends_on",[])},"command":stage.get("command"),"settings":settings,"stage_settings":stage.get("settings",{})})
def valid_marker(marker:Path,signature:str,root:Path)->bool:
    if not marker.is_file():return False
    try:data=json.loads(marker.read_text(encoding="utf-8"))
    except Exception:return False
    if data.get("signature")!=signature:return False
    return all((root/p).is_file() and file_hash(root/p)==digest for p,digest in data.get("outputs",{}).items())
def atomic_json(path:Path,value:dict):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+".partial");temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");os.replace(temp,path)
def run_pipeline(config:dict,root:Path,cache:Path,status_path:Path,stop_after:str|None)->dict:
    declared=config.get("stages")
    if not isinstance(declared,list) or not declared:raise ValueError("render pipeline requires non-empty stages")
    for stage in declared:
        if not SAFE_STAGE_ID.fullmatch(str(stage.get("id") or "")):raise ValueError(f"unsafe render stage id: {stage.get('id')}")
    graph=DependencyGraph(declared);order=graph.topological_order();stages={s["id"]:s for s in declared}
    if stop_after is not None and stop_after not in stages:raise ValueError(f"unknown stop-after stage: {stop_after}")
    dep_sigs={};status={"schema_version":2,"pipeline":config.get("name"),"execution_order":order,"started_at":time.time(),"stages":{},"state":"running"};atomic_json(status_path,status)
    for name in order:
        stage=stages[name];sig=stage_signature(stage,root,dep_sigs,config.get("settings",{}));dep_sigs[name]=sig;marker=cache/name/"done.json"
        if valid_marker(marker,sig,root):status["stages"][name]={"state":"reused","signature":sig};atomic_json(status_path,status)
        else:
            for rel in stage.get("partial_outputs",[]):
                p=root/rel
                if p.exists():p.unlink()
            status["stages"][name]={"state":"running","signature":sig};atomic_json(status_path,status)
            result=subprocess.run([str(x) for x in stage["command"]],cwd=root,capture_output=True,text=True,encoding="utf-8",errors="replace")
            if result.returncode:status["state"]="failed";status["stages"][name].update({"state":"failed","returncode":result.returncode,"stderr_tail":result.stderr[-2000:]});atomic_json(status_path,status);return status
            for pair in stage.get("atomic_outputs",[]):
                working,final=root/pair["working"],root/pair["final"]
                if not working.is_file():raise FileNotFoundError(working)
                final.parent.mkdir(parents=True,exist_ok=True);os.replace(working,final)
            outputs={rel:file_hash(root/rel) for rel in stage.get("outputs",[]) if (root/rel).is_file()}
            if len(outputs)!=len(stage.get("outputs",[])):status["state"]="failed";status["stages"][name]["state"]="missing_output";atomic_json(status_path,status);return status
            atomic_json(marker,{"stage":name,"signature":sig,"outputs":outputs,"completed_at":time.time()});status["stages"][name]={"state":"completed","signature":sig,"outputs":outputs};atomic_json(status_path,status)
        if stop_after==name:status["state"]="interrupted_for_test";atomic_json(status_path,status);return status
    status["state"]="completed";status["completed_at"]=time.time();atomic_json(status_path,status);return status
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--pipeline",required=True);p.add_argument("--root",required=True);p.add_argument("--cache-dir",required=True);p.add_argument("--status",required=True);p.add_argument("--stop-after");a=p.parse_args();result=run_pipeline(json.loads(Path(a.pipeline).read_text(encoding="utf-8")),Path(a.root).resolve(),Path(a.cache_dir).resolve(),Path(a.status).resolve(),a.stop_after);print(Path(a.status).resolve());return 0 if result["state"] in ("completed","interrupted_for_test") else 2
if __name__=="__main__":raise SystemExit(main())
