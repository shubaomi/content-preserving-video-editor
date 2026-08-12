#!/usr/bin/env python3
"""Validate a media export against a dated platform preset."""

from __future__ import annotations

import argparse, hashlib, json, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels", "-of", "json", str(path)], text=True, encoding="utf-8"))


def loudness(path: Path) -> dict:
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"], text=True, encoding="utf-8", errors="replace", capture_output=True)
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", run.stderr, re.S)
    if not blocks: return {"measured": False}
    value = json.loads(blocks[-1])
    return {"measured": True, "integrated_lufs": float(value["input_i"]), "true_peak_dbtp": float(value["input_tp"])}


def decode(path: Path) -> bool:
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"], capture_output=True).returncode == 0


def snapshot(media: Path, zone: dict, output: Path) -> None:
    temp = output.with_suffix(".frame.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(media), "-frames:v", "1", str(temp)], check=True)
    image = Image.open(temp).convert("RGB"); draw = ImageDraw.Draw(image); w,h=image.size
    draw.rectangle((zone["x0"]*w,zone["y0"]*h,zone["x1"]*w,zone["y1"]*h), outline="#20e3b2", width=max(3,w//300))
    output.parent.mkdir(parents=True, exist_ok=True); image.save(output, quality=92); temp.unlink()


def cover_preview(cover: Path, safe: dict, output: Path) -> None:
    image=Image.open(cover).convert("RGB"); draw=ImageDraw.Draw(image); w,h=image.size
    draw.rectangle((safe["x0"]*w,safe["y0"]*h,safe["x1"]*w,safe["y1"]*h),outline="#f59e0b",width=max(3,w//300)); image.save(output,quality=92)


def validate(media: Path, preset: dict, platform: str, loud: dict, decoded: bool) -> dict:
    data=probe(media); video=next(s for s in data["streams"] if s["codec_type"]=="video"); audios=[s for s in data["streams"] if s["codec_type"]=="audio"]
    w,h=int(video["width"]),int(video["height"]); ratio=w/h
    checks={"container_mp4":media.suffix.lower()==".mp4","video_codec":video.get("codec_name")==preset["video"]["codec"],"pixel_format":video.get("pix_fmt")==preset["video"]["pixel_format"],"minimum_short_edge":min(w,h)>=preset["minimum_short_edge"],"ratio":preset["accepted_ratio_range"][0]<=ratio<=preset["accepted_ratio_range"][1],"audio_present":bool(audios),"full_decode":decoded,"file_size_warning":int(data["format"]["size"])>preset["file_size_warning_bytes"]}
    if loud.get("measured"):
        checks["speech_loudness_recommendation"] = abs(loud["integrated_lufs"]-preset["audio"]["loudness_lufs"])<=3
        checks["true_peak_recommendation"] = loud["true_peak_dbtp"]<=preset["audio"]["true_peak_dbtp"]+0.5
    required=[v for k,v in checks.items() if k not in ("file_size_warning","speech_loudness_recommendation")]
    return {"schema_version":1,"platform":platform,"media":str(media),"dimensions":[w,h],"duration":float(data["format"]["duration"]),"loudness":loud,"checks":checks,"passed":all(required),"recommendation_warnings":[k for k in ("speech_loudness_recommendation","true_peak_recommendation") if checks.get(k) is False]}


def bind_universal_output(report: dict, media: Path) -> dict:
    digest = hashlib.sha256()
    with media.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        **report,
        "status": "pass" if report.get("passed") is True else "fail",
        "file_sha256": digest.hexdigest(),
        "universal_output": True,
    }


def bind_cover(report: dict, cover: Path) -> dict:
    digest = hashlib.sha256()
    with cover.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {**report, "cover": str(cover.resolve()), "cover_sha256": digest.hexdigest()}


def validate_bound_report(report: dict, media: Path, cover: Path | None) -> list[str]:
    errors = []
    required_checks = ("container_mp4", "video_codec", "pixel_format", "minimum_short_edge",
                       "ratio", "audio_present", "full_decode", "true_peak_recommendation")
    media_hash = hashlib.sha256(media.read_bytes()).hexdigest() if media.is_file() else None
    cover_present = bool(cover and cover.is_file())
    cover_hash = hashlib.sha256(cover.read_bytes()).hexdigest() if cover_present else None
    if (report.get("schema_version") != 1 or report.get("status") != "pass"
            or report.get("passed") is not True or report.get("universal_output") is not True
            or report.get("file_sha256") != media_hash or report.get("cover_sha256") != cover_hash
            or not report.get("preset_version") or not report.get("preset_verified_on")
            or any((report.get("checks") or {}).get(name) is not True for name in required_checks)):
        errors.append("platform report structure, checks, or byte bindings did not pass")
    evidence_fields = [("safe_zone_snapshot", "safe_zone_snapshot_sha256")]
    if cover_present:
        evidence_fields.append(("cover_crop_preview", "cover_crop_preview_sha256"))
    for path_field, hash_field in evidence_fields:
        path = Path(str(report.get(path_field, "")))
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if not path.is_file() or report.get(hash_field) != actual:
            errors.append(f"platform evidence is missing or stale: {path_field}")
    if media.is_file() and report.get("platform") in {"douyin", "wechat_channels"}:
        try:
            presets = json.loads((Path(__file__).parents[1] / "references" / "platform-presets.json")
                                 .read_text(encoding="utf-8"))
            platform = report["platform"]
            fresh = validate(media, presets["platforms"][platform], platform,
                             loudness(media), decode(media))
            if (
                report.get("preset_version") != presets.get("preset_version")
                or report.get("preset_verified_on") != presets.get("verified_on")
                or report.get("dimensions") != fresh.get("dimensions")
                or abs(float(report.get("duration", -1)) - float(fresh.get("duration", 0))) > 0.01
                or report.get("checks") != fresh.get("checks")
                or report.get("loudness") != fresh.get("loudness")
            ):
                errors.append("platform report does not match fresh probe/decode/audio validation")
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            errors.append("platform report could not be independently revalidated")
    return errors


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--media",required=True);p.add_argument("--platform",required=True,choices=("douyin","wechat_channels"));p.add_argument("--presets",default=str(Path(__file__).parents[1]/"references"/"platform-presets.json"));p.add_argument("--cover");p.add_argument("--out",required=True);p.add_argument("--evidence-dir",required=True);a=p.parse_args()
    presets=json.loads(Path(a.presets).read_text(encoding="utf-8")); preset=presets["platforms"][a.platform]; media=Path(a.media).resolve(); evidence=Path(a.evidence_dir).resolve(); evidence.mkdir(parents=True,exist_ok=True)
    report=bind_universal_output(validate(media,preset,a.platform,loudness(media),decode(media)),media); report["preset_version"]=presets["preset_version"];report["preset_verified_on"]=presets["verified_on"];report["sources"]=preset["sources"];report["recommendation_fields"]=preset["recommendation_fields"]
    safe=evidence/f"{a.platform}-safe-zone.jpg";snapshot(media,preset["caption_safe_zone"],safe);report["safe_zone_snapshot"]=str(safe);report["safe_zone_snapshot_sha256"]=hashlib.sha256(safe.read_bytes()).hexdigest()
    if a.cover:
        cover=Path(a.cover).resolve();cp=evidence/f"{a.platform}-cover-crop.jpg";cover_preview(cover,preset["cover"]["center_safe"],cp);report=bind_cover(report,cover);report["cover_crop_preview"]=str(cp);report["cover_crop_preview_sha256"]=hashlib.sha256(cp.read_bytes()).hexdigest()
    out=Path(a.out).resolve();out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(out);return 0 if report["passed"] else 2
if __name__=="__main__": raise SystemExit(main())
