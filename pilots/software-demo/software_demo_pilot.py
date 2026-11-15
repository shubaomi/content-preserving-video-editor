"""Opt-in, local-only software walkthrough proof. Not a Director stage."""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local_path(path):
    """Reject share/device paths before resolving, and mapped network volumes on Windows."""
    path = Path(path)
    for candidate in (path, path.absolute()):
        require(not str(candidate).replace("\\", "/").startswith("//"), "local paths only")
    if os.name == "nt":
        import ctypes
        require(ctypes.windll.kernel32.GetDriveTypeW(path.absolute().anchor) in (2, 3, 6),
                "expected a local volume")
    resolved = path.resolve()
    require(not str(resolved).replace("\\", "/").startswith("//"), "resolved to a network path")
    return resolved


def validate(plan):
    require(isinstance(plan, dict) and set(plan) == {"url", "paths", "steps"}, "invalid scenario")
    require(isinstance(plan["url"], str) and
            re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}/[A-Za-z0-9_./-]*", plan["url"]),
            "only an explicit HTTP loopback port and path are supported")
    url = urlsplit(plan["url"])
    require(url.port and isinstance(plan["paths"], list) and 1 <= len(plan["paths"]) <= 64,
            "bounded static allowlist required")
    for path in plan["paths"]:
        require(isinstance(path, str) and re.fullmatch(r"/[A-Za-z0-9_./-]*", path)
                and "//" not in path and not {".", ".."}.intersection(path.split("/")), "unsafe path")
    require(url.path in plan["paths"], "start path not authorized")
    require(isinstance(plan["steps"], list) and 2 <= len(plan["steps"]) <= 8, "need 2–8 proof beats")
    for i, s in enumerate(plan["steps"]):
        fields = {"expect", "copy", "seconds"} | ({"click"} if i else set())
        require(isinstance(s, dict) and set(s) == fields, "unexpected or missing step fields")
        for key in fields - {"seconds"}:
            v = s[key]
            require(isinstance(v, str) and v.strip() == v and 0 < len(v) <= 90
                    and v.isprintable() and not any(c in v for c in "<>{}\\"), "unsafe text")
        require(type(s["seconds"]) is int and 1 <= s["seconds"] <= 8, "invalid hold")
        units = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s["copy"])
        require(units <= 56, "shorten the on-screen explanation to one line")
    require(sum(s["seconds"] for s in plan["steps"]) <= 30, "pilot exceeds 30 seconds")


def descriptions(steps):
    cues, start = [], 0
    for i, step in enumerate(steps, 1):
        end = start + step["seconds"]
        cues.append(f"{i}\n00:00:{start:02},000 --> 00:00:{end:02},000\n{step['copy']}\n\n")
        start = end
    return "".join(cues)


def fetch_assets(plan):
    port = urlsplit(plan["url"]).port
    assets, total = {}, 0
    for path in dict.fromkeys(plan["paths"]):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", path)
            resp = connection.getresponse()
            require(resp.status == 200, "declared asset unavailable (redirects not followed)")
            # Replaying just the bytes must not lift a product policy or present a
            # login/cookie-dependent response as a fresh anonymous interaction.
            neutral = {"server", "date", "content-type", "content-length", "last-modified",
                       "etag", "accept-ranges", "cache-control", "connection", "keep-alive",
                       "transfer-encoding", "expires", "pragma"}
            require(all(k.lower() in neutral for k, _ in resp.getheaders()),
                    "unsupported response policy, encoding or state; use an authorized recording")
            blob = resp.read(8_000_001)
            total += len(blob)
            require(len(blob) <= 8_000_000 and total <= 32_000_000, "capture asset budget exceeded")
            assets[path] = (resp.getheader("Content-Type", "application/octet-stream"), blob)
        finally:
            connection.close()
    return assets


def capture(plan, assets, out):
    from playwright.sync_api import sync_playwright

    origin = "http://" + urlsplit(plan["url"]).netloc
    policy = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none'; "
              "worker-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'")
    denied = []

    def route(req):
        url = req.request.url
        path = url.removeprefix(origin)
        if req.request.method != "GET" or path not in assets or url != origin + path:
            denied.append(True)
            return req.abort()
        mime, body = assets[path]
        req.fulfill(status=200, headers={"Content-Type": mime, "Content-Security-Policy": policy}, body=body)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", args=["--disable-background-networking"])
        ctx = browser.new_context(viewport={"width": 960, "height": 464}, offline=True,
                                  accept_downloads=False, service_workers="block", reduced_motion="reduce")
        ctx.route("**/*", route)
        def deny_socket(ws):
            denied.append(True)
            ws.close()
        ctx.route_web_socket("**/*", deny_socket)
        page = ctx.new_page()
        page.set_default_timeout(4500)
        page.goto(plan["url"], wait_until="load", timeout=12000)
        for i, step in enumerate(plan["steps"]):
            target = page.get_by_text(step["expect"], exact=True)
            if i:
                require(not target.is_visible(), "requested result already visible before click")
                page.get_by_role("button", name=step["click"], exact=True).click()
            target.wait_for(state="visible")
            target.scroll_into_view_if_needed()
            require(target.evaluate("""e => {
                const b=e.getBoundingClientRect(), x=b.x+b.width/2, y=b.y+b.height/2;
                return e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) &&
                    e.contains(document.elementFromPoint(x,y));
            }"""), "assertion text not in view or obscured")
            page.screenshot(path=str(out / f"state-{i:02}.png"), animations="disabled")
            require(not denied and ctx.pages == [page] and page.url.startswith(origin + "/"),
                    "unexpected request, extra window or origin change")
        browser.close()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(plan, out):
    validate(plan)
    out = local_path(out)
    require(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required")
    out.mkdir(exist_ok=False)
    # Everything stays in a fresh directory. A failed capture never gets a success receipt.
    assets = fetch_assets(plan)
    capture(plan, assets, out)
    steps = plan["steps"]
    (out / "description.srt").write_text(descriptions(steps), encoding="utf8")
    frames = [out / f"state-{i:02}.png" for i in range(len(steps))]
    total = sum(s["seconds"] for s in steps)
    manifest = "".join(f"file '{p.name}'\nduration {s['seconds']}\n" for p, s in zip(frames, steps))
    (out / "frames.txt").write_text(manifest + f"file '{frames[-1].name}'\n", encoding="ascii")
    provisional = out / "private-check.mp4"
    vf = ("fps=24,pad=iw:ih+76:0:0:color=0x15212c,subtitles=description.srt:"
          "force_style='Fontname=Microsoft YaHei,Fontsize=16,MarginV=10,Outline=0,Shadow=0'")
    subprocess.run(["ffmpeg","-v","error","-nostdin","-n","-f","concat","-safe","1","-i","frames.txt",
                    "-vf",vf,"-t",str(total),"-an","-c:v","libx264","-pix_fmt","yuv420p",
                    "-movflags","+faststart",provisional.name], cwd=out, check=True, timeout=120)
    probe = json.loads(subprocess.check_output(["ffprobe","-v","error","-count_frames","-show_streams",
                                                "-of","json",str(provisional)],timeout=60))
    streams = probe["streams"]
    require(len(streams) == 1 and streams[0]["codec_name"] == "h264" and
            int(streams[0]["nb_read_frames"]) == 24 * total, "incomplete pilot stream")
    subprocess.run(["ffmpeg","-nostdin","-v","error","-xerror","-i",str(provisional),"-f","null","-"],
                   check=True, timeout=60)
    video = out / "software-demo-preview.mp4"
    provisional.rename(video)
    receipt = {"kind":"private_static_state_pilot", "duration_seconds":total, "audio":False,
               "approval":"not_reviewed", "scenario":plan,
               "assets":{k:hashlib.sha256(v[1]).hexdigest() for k,v in assets.items()},
               "sha256":{p.name:sha(p) for p in [*frames,out/"description.srt",video]}}
    (out / "receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf8")
    return video


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("scenario", type=Path)
    cli.add_argument("out", type=Path)
    cli.add_argument("--confirm-demo-capture", required=True, action="store_true")
    args = cli.parse_args()
    print(build(json.loads(local_path(args.scenario).read_text(encoding="utf-8-sig")), args.out))
