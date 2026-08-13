#!/usr/bin/env python3
"""Build isolated, deterministic WP6 HyperFrames Style Reel projects.

This helper only prepares the exact user-confirmed short window.  It does not
render a full video and it never mutates the source canary or its old project.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any


DURATION_SECONDS = 38.58
FPS = 25
WIDTH = 544
HEIGHT = 960

DIRECTIONS: dict[str, dict[str, Any]] = {
    "luminous_intelligence": {
        "recipe_id": "PBM-04",
        "label": "理性对照",
        "accent": "#45e6d5",
        "warm": "#ffba75",
        "class_name": "direction-luminous",
    },
    "high_energy_creator": {
        "recipe_id": "PBM-01",
        "label": "创作者能量",
        "accent": "#7cf8e8",
        "warm": "#ff8f4d",
        "class_name": "direction-energy",
    },
    "humanist_cinema": {
        "recipe_id": "PBM-08",
        "label": "温暖收束",
        "accent": "#ffd08a",
        "warm": "#ff9b78",
        "class_name": "direction-humanist",
    },
}


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(argv, cwd=cwd, check=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {argv}")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        temp = Path(handle.name)
    try:
        shutil.copyfile(source, temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_text(target: Path, value: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, delete=False, mode="w", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(value)
        temp = Path(handle.name)
    try:
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _trim_source(source: Path, target: Path, start_seconds: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.building{target.suffix}")
    temp.unlink(missing_ok=True)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_seconds:.3f}", "-i", str(source),
        "-t", f"{DURATION_SECONDS:.3f}",
        "-map", "0:v:0", "-map", "0:a:0",
        "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-movflags", "+faststart", str(temp),
    ])
    temp.replace(target)


def _html(direction_id: str, direction: dict[str, Any]) -> str:
    recipe_id = direction["recipe_id"]
    accent = direction["accent"]
    warm = direction["warm"]
    direction_class = direction["class_name"]
    return f"""<!doctype html>
<html lang="zh-CN" data-resolution="portrait">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>HongRun Portrait Style Reel — {direction_id}</title>
  <script src="assets/gsap-3.14.2.min.js"></script>
  <link rel="stylesheet" href="assets/hyperframes-portrait-components-v2.css" />
  <style>
    @font-face {{ font-family:"HongRun YaHei"; src:local("Microsoft YaHei UI"),local("Microsoft YaHei"); font-display:block; }}
    * {{ box-sizing:border-box; }}
    html,body {{ margin:0; width:100%; height:100%; overflow:hidden; background:#071313; }}
    #root {{ position:relative; width:{WIDTH}px; height:{HEIGHT}px; overflow:hidden; isolation:isolate; background:#071313; }}
    .clip {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }}
    #source-shade {{ position:absolute; inset:0; z-index:2; pointer-events:none; background:
      linear-gradient(180deg,rgba(3,14,17,.05) 0%,rgba(3,14,17,0) 42%,rgba(3,14,17,.14) 72%,rgba(3,14,17,.36) 100%); }}
    .pbm-event {{ z-index:20; --pbm-mint:{accent}; --pbm-cyan:{accent}; --pbm-warm:{warm}; }}
    .pbm-event::before {{ opacity:calc(.08 + .20 * var(--pbm-progress)); }}
    .pbm-copy {{ font-family:"HongRun YaHei",system-ui,sans-serif; font-size:42px; line-height:1.04; text-shadow:0 4px 18px rgba(0,0,0,.72); }}
    .pbm-copy span {{ padding:.08em .04em; }}
    .pbm-primitive {{ filter:drop-shadow(0 0 10px color-mix(in srgb,var(--pbm-cyan) 48%,transparent)); }}
    .{direction_class}.pbm-thought-contrast-planes .pbm-copy {{ inset:58% 6% auto; width:88%; gap:30px; }}
    .{direction_class}.pbm-thought-contrast-planes .pbm-copy span {{ max-width:46%; padding:.22em .16em .18em; border-bottom-width:3px; }}
    .{direction_class}.pbm-thought-contrast-planes .pbm-relation-axis {{ left:17%; right:17%; top:68%; height:2px; }}
    .{direction_class}.pbm-thought-contrast-planes .pbm-primitive {{ left:39%; top:57%; width:22vmin; height:22vmin; }}
    .{direction_class}.pbm-thought-contrast-planes .pbm-focus-beam {{ left:39%; top:70%; width:22vw; }}
    .{direction_class}.pbm-luminous-phrase-pulse .pbm-copy {{ left:8%; top:59%; max-width:80%; flex-direction:column; gap:2px; font-size:48px; }}
    .{direction_class}.pbm-luminous-phrase-pulse .pbm-copy span+span {{ color:{warm}; margin-left:52px; }}
    .{direction_class}.pbm-luminous-phrase-pulse .pbm-primitive {{ left:61%; top:55%; width:26vmin; height:26vmin; }}
    .{direction_class}.pbm-luminous-phrase-pulse .pbm-focus-beam {{ left:9%; top:75%; width:48vw; height:3px; }}
    .{direction_class}.pbm-emotional-resolution-bloom .pbm-copy {{ left:7%; bottom:27%; width:86%; max-width:86%; flex-direction:column; gap:2px; font-size:44px; }}
    .{direction_class}.pbm-emotional-resolution-bloom .pbm-copy span+span {{ color:{warm}; align-self:flex-end; margin-right:8px; }}
    .{direction_class}.pbm-emotional-resolution-bloom .pbm-primitive {{ right:7%; bottom:29%; width:25vmin; height:25vmin; }}
    .{direction_class}.pbm-emotional-resolution-bloom .pbm-focus-beam {{ left:9%; bottom:24%; width:52vw; height:2px; }}
    .{direction_class}.pbm-emotional-resolution-bloom .pbm-resolution-bloom {{ left:8%; right:8%; bottom:20%; height:34%; }}
    #direction-mark {{ position:absolute; z-index:24; right:20px; top:28px; color:rgba(255,255,255,.78); font:600 12px/1.1 system-ui,sans-serif; letter-spacing:.16em; text-transform:uppercase; opacity:0; }}
  </style>
</head>
<body>
  <div id="root" data-hf-id="style-reel-{direction_id}" data-composition-id="main"
       data-start="0" data-duration="{DURATION_SECONDS:.2f}" data-width="{WIDTH}" data-height="{HEIGHT}" data-fps="{FPS}">
    <video id="a-roll" class="clip" data-hf-id="style-reel-a-roll" src="assets/style-reel-source.mp4"
           muted playsinline preload="auto" data-start="0" data-duration="{DURATION_SECONDS:.2f}" data-track-index="0"></video>
    <audio id="a-roll-audio" data-hf-id="style-reel-audio" src="assets/style-reel-source.mp4"
           preload="auto" data-start="0" data-duration="{DURATION_SECONDS:.2f}" data-track-index="6" data-volume="1"></audio>
    <div id="source-shade" data-layout-ignore></div>
    <div id="direction-mark" data-layout-ignore>{direction["label"]}</div>
  </div>
  <script type="module">
    import {{createPortraitMotion,applyPortraitPhase,visibleCopyManifest}} from "./assets/hyperframes-portrait-components-v2.js";
    const root = document.getElementById("root");
    const node = createPortraitMotion({{
      recipeId:"{recipe_id}", eventId:"life-halves-question", visibleCopy:["上半辈子","下半辈子"],
      supportingLayers:["ambient_light_field","focus_vignette"], bindings:{{}}, expectedBindings:{{}}, authorityDigests:{{}},
      sourceWindow:{{start_seconds:17.71,end_seconds:27.81}}, outputWindow:{{start_seconds:0,end_seconds:10.10}}
    }});
    node.classList.add("{direction_class}");
    node.dataset.hfId = "life-halves-question";
    node.dataset.start = "0";
    node.dataset.duration = "10.10";
    node.dataset.trackIndex = "3";
    root.append(node);
    applyPortraitPhase(node,"entrance",0);
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{paused:true}});
    tl.set(node,{{display:"block",opacity:0,"--pbm-progress":0,attr:{{"data-phase":"entrance"}}}},0);
    tl.fromTo(node,{{opacity:0,y:20,scale:.97}},{{opacity:1,y:0,scale:1,duration:.62,ease:"power3.out",immediateRender:false}},.18);
    tl.to(node,{{"--pbm-progress":1,duration:1.05,ease:"power2.out",attr:{{"data-phase":"explain"}}}},.22);
    tl.fromTo("#life-halves-question .pbm-copy span",{{opacity:0,y:18}},{{opacity:1,y:0,duration:.56,stagger:.16,ease:"power3.out",immediateRender:false}},.34);
    tl.fromTo("#life-halves-question .pbm-primitive",{{opacity:0}},{{opacity:.82,duration:.9,ease:"power2.out",immediateRender:false}},.42);
    tl.fromTo("#life-halves-question .pbm-focus-beam",{{opacity:0,scaleX:0}},{{opacity:.9,scaleX:1,duration:.72,ease:"power2.out",immediateRender:false}},.72);
    tl.to(node,{{attr:{{"data-phase":"hold"}}}},1.45);
    tl.to("#life-halves-question .pbm-primitive",{{opacity:.66,duration:2.2,yoyo:true,repeat:2,ease:"sine.inOut"}},1.5);
    tl.fromTo("#direction-mark",{{opacity:0,x:10}},{{opacity:.72,x:0,duration:.42,ease:"power2.out",immediateRender:false}},.32);
    tl.to("#direction-mark",{{opacity:0,duration:.28,ease:"power2.in"}},4.4);
    tl.to(node,{{attr:{{"data-phase":"exit"}},"--pbm-progress":.2,duration:.6,ease:"power2.in"}},9.1);
    tl.to(node,{{opacity:0,y:-12,scale:.985,duration:.42,ease:"power2.in"}},9.54);
    tl.set(node,{{opacity:0,attr:{{"data-phase":"post_exit"}}}},10.1);
    tl.seek(0);
    window.__timelines.main = tl;
    window.__portraitStyleReel = Object.freeze({{
      directionId:"{direction_id}", recipeId:"{recipe_id}", eventId:"life-halves-question",
      approvedVisibleCopy:visibleCopyManifest(node), eventEndSeconds:10.10,
    }});
  </script>
</body>
</html>
"""


def build(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.output_root).resolve()
    source = Path(args.source).resolve()
    template = Path(args.template_project).resolve()
    repo = Path(args.repo).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    component_js = repo / "references" / "hyperframes-portrait-components-v2.js"
    component_css = repo / "references" / "hyperframes-portrait-components-v2.css"
    gsap = template / "assets" / "gsap-3.14.2.min.js"
    for required in (component_js, component_css, gsap, template / "package.json", template / "hyperframes.json"):
        if not required.is_file():
            raise FileNotFoundError(required)

    clip = root / "source" / "style-reel-source.mp4"
    _trim_source(source, clip, float(args.start_seconds))
    projects: dict[str, Any] = {}
    for direction_id, direction in DIRECTIONS.items():
        project = root / "hyperframes" / direction_id
        assets = project / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "hyperframes.json"):
            _atomic_copy(template / name, project / name)
        meta = {"id": f"wp6-{direction_id}", "name": f"wp6-{direction_id}", "createdAt": "2026-08-12T00:00:00-07:00"}
        _atomic_text(project / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        _atomic_copy(gsap, assets / gsap.name)
        _atomic_copy(component_js, assets / component_js.name)
        _atomic_copy(component_css, assets / component_css.name)
        _atomic_copy(clip, assets / clip.name)
        _atomic_text(project / "index.html", _html(direction_id, direction))
        projects[direction_id] = {
            "project": str(project),
            "index_sha256": _sha256(project / "index.html"),
            "recipe_id": direction["recipe_id"],
        }

    report = {
        "schema_version": 1,
        "status": "prepared",
        "source_clip": {"path": str(clip), "sha256": _sha256(clip)},
        "source_start_seconds": round(float(args.start_seconds), 3),
        "duration_seconds": DURATION_SECONDS,
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "projects": projects,
        "full_video_render_authorized": False,
    }
    _atomic_text(root / "wp6-hyperframes-projects.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--start-seconds", required=True, type=float)
    parser.add_argument("--template-project", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
