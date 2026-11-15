import unittest
import threading
import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import software_demo_pilot as demo


# A tiny functional software product for integration checks; no user/project data.
APP = """<!doctype html><html lang="zh"><meta charset="utf-8"><title>拾页 · 阅读清单</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f2eee7;color:#252924;font:20px 'Microsoft YaHei',sans-serif}
main{max-width:830px;margin:36px auto}small{color:#4f6b60;letter-spacing:2px}h1{font-size:42px;margin:12px 0}
nav{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #414a42;padding-bottom:18px}
button{background:#215341;color:white;border:0;padding:12px 22px;border-radius:5px;font:inherit}
article{display:flex;align-items:center;gap:22px;border-bottom:1px solid #bbc4b5;padding:15px 0}
i{background:#b76d4f;color:white;font:22px Georgia;padding:12px}b{flex:1}span{color:#526559;font-size:16px}
</style><main><small>拾页　/　软件功能验证 · 虚构演示数据</small><h1>我的阅读清单</h1>
<nav><strong id="status">全部书目 · 3 本</strong><button>只看待读</button></nav>
<article><i>01</i><b>海边的灯塔</b><span>待读</span></article>
<article data-done><i>02</i><b>夜间列车</b><span>读完</span></article>
<article><i>03</i><b>一座城的四季</b><span>待读</span></article></main>
<script>document.querySelector('button').onclick=()=>{
document.querySelector('[data-done]').remove();document.querySelector('#status').textContent=
'待读书目 · '+document.querySelectorAll('article').length+' 本'}</script></html>"""


@contextmanager
def sample_app(headers=()):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/demo" else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(APP.encode("utf8") if self.path == "/demo" else b"")

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield {"url":f"http://127.0.0.1:{srv.server_port}/demo","paths":["/demo"],
                   "steps":[{"expect":"全部书目 · 3 本","copy":"三本书放在一起，哪本还没读？","seconds":3},
                            {"click":"只看待读","expect":"待读书目 · 2 本","copy":"点「只看待读」，留下两本还没读的书。","seconds":4}]}
        finally:
            srv.shutdown()


def example():
    return {"url": "http://127.0.0.1:8000/demo", "paths": ["/demo"],
            "steps": [{"expect": "Overview", "copy": "Open the board.", "seconds": 2},
                      {"click": "Filter", "expect": "Two items", "copy": "Two items remain.", "seconds": 3}]}


class SoftwareDemoPilotTests(unittest.TestCase):
    def test_network_paths_are_not_opened(self):
        for path in ("//server/share/demo", r"\\server\share", r"\\?\C:\demo"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                demo.local_path(path)

    def test_do_not_weaken_product_headers(self):
        with sample_app([("Content-Security-Policy", "script-src 'none'")]) as plan:
            with self.assertRaisesRegex(ValueError, "response policy"):
                demo.fetch_assets(plan)

    def test_failed_real_click_does_not_deliver_or_overwrite(self):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        with tempfile.TemporaryDirectory() as tmp, sample_app() as plan:
            out = Path(tmp) / "pilot"
            plan["steps"][1]["expect"] = "结果没有出现"
            with self.assertRaises(BrowserTimeout):
                demo.build(plan, out)
            self.assertTrue((out / "state-00.png").exists())
            self.assertFalse((out / "receipt.json").exists())
            self.assertFalse((out / "software-demo-preview.mp4").exists())
            with self.assertRaises(FileExistsError):
                demo.build(plan, out)

    def test_timed_description_not_transcript(self):
        plan = example()
        demo.validate(plan)
        self.assertIn("00:00:02,000 --> 00:00:05,000", demo.descriptions(plan["steps"]))

    def test_forbid_remote_credentials_query_and_implicit_resources(self):
        for field, values in {"url":["https://example.org/demo","http://user@127.0.0.1:8000/demo",
                                     "http://127.0.0.1:8000/demo?secret=1","http://127.0.0.1:8000/other"],
                              "paths":[["/demo","/../private"],["/demo","//server/x"],["/demo","/%2f"]]
                              }.items():
            for value in values:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    demo.validate(example() | {field:value})

    def test_reject_injection_unverified_click_and_unbounded_time(self):
        for change in ({"copy":"text\n2\nInjected"}, {"seconds":True}, {"seconds":80},
                       {"expect":""}, {"evaluate":"run()"}, {"click":""}, {"copy":"字"*29}):
            plan = example()
            plan["steps"][1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                demo.validate(plan)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--render-example":
        with sample_app() as scenario:
            print(demo.build(scenario, Path(sys.argv[2])))
    else:
        unittest.main()
