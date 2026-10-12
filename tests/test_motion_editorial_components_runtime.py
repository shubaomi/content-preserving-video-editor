"""Real Chromium + GSAP synthetic seek tests, not a HyperFrames media render.

Set MOTION_EDITORIAL_BROWSER to the installed HyperFrames browser executable and
MOTION_EDITORIAL_GSAP to a trusted existing local GSAP file. No installation,
network requests, user-project writes, or video renders are performed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MotionEditorialComponentsRuntimeTests(unittest.TestCase):
    def test_real_gsap_four_phase_forward_reverse_seek(self):
        browser_path = os.environ.get("MOTION_EDITORIAL_BROWSER")
        gsap_path = os.environ.get("MOTION_EDITORIAL_GSAP")
        if not browser_path or not gsap_path:
            self.skipTest("explicit installed HyperFrames browser and trusted local GSAP required")
        self.assertTrue(Path(browser_path).is_file(), "configured browser missing")
        self.assertTrue(Path(gsap_path).is_file(), "configured GSAP missing")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("local Playwright unavailable; no install attempted")
        sources = {
            "A": ROOT / "assets/motion-editorial-v3/authentic-product-editorial.js",
            "B": ROOT / "assets/motion-editorial-v3/professional-software-demo.js",
        }
        for path in sources.values():
            self.assertTrue(path.is_file(), str(path))
        receipts = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=browser_path, headless=True)
            try:
                context = browser.new_context(viewport={"width": 640, "height": 1000}, offline=True)
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_content("""<!doctype html><html><head><style>
html,body{margin:0;background:#ddd}#frame{position:relative;width:640px;height:1000px;overflow:hidden}
#source{position:absolute;left:30px;top:20px;width:540px;height:960px;background:#789}
#product{position:absolute;left:100px;top:200px;width:220px;height:300px;background:#456}
#overlay{position:absolute;inset:0;overflow:hidden}
</style></head><body><div id="frame"><div id="source"><div id="product"></div></div><div id="overlay"></div></div></body></html>""")
                page.add_script_tag(content=Path(gsap_path).read_text(encoding="utf-8"))
                for path in sources.values():
                    page.add_script_tag(content=path.read_text(encoding="utf-8"))
                page.evaluate("""() => {
window.makePlan=(recipe)=>{
 const ref=n=>({path:'C:/synthetic/'+n+'.png',sha256:n.repeat(64)});
 const p={recipe_id:recipe,output_start:10,output_end:15,active_end:14,
 phases:{entrance:{start:.1,end:.3},explain:{start:.3,end:.7},hold:{start:.7,end:3.5},exit:{start:3.5,end:3.7}},
 source_crop:{x:.1,y:.05,width:.8,height:.8},source_box:{x:30,y:20,width:540,height:960},
 overlay_box:null,approved_visible_copy:[],evidence:{maximum_scale:1.25,frame_refs:[ref('a')]}};
 if(recipe==='B01')p.overlay_box={x:120,y:200,width:220,height:2};
 if(recipe.endsWith('02')||recipe.endsWith('03')){
   p.source_crop=null;p.overlay_box={x:80,y:100,width:240,height:50};
 }
 if(recipe==='A02'){
   p.approved_visible_copy=['真实结果'];p.evidence={target_binding_ref:'real_product',target_window:{start:10,end:15}};
 }
 if(recipe==='A03'){
   p.approved_visible_copy=['操作前','操作后'];p.evidence={before_state_ref:ref('a'),after_state_ref:ref('b'),after_at:1.4};
 }
 if(recipe==='B02'){
   p.approved_visible_copy=['第一步','结果'];p.steps=[
   {start:.1,end:1.4,copy:'第一步',overlay_box:p.overlay_box,frame_ref:ref('a')},
   {start:1.4,end:3.7,copy:'结果',overlay_box:p.overlay_box,frame_ref:ref('b')}];
 }
 if(recipe==='B03'){
   p.comparison_mode='sequential_source';p.after_at=1.4;p.approved_visible_copy=['操作前','操作后'];
   p.evidence.states=[{frame_ref:ref('a'),source_time:11,label:'操作前'},
                      {frame_ref:ref('b'),source_time:12,label:'操作后'}];
 }
 return p;
};
window.mountRecipe=recipe=>{
 if(window.testTimeline)window.testTimeline.kill();
 const source=document.getElementById('source');
 gsap.set(source,{clearProps:'transform'});source.style.transform='';
 document.getElementById('overlay').replaceChildren();
 window.testTimeline=window['MotionEditorial'+recipe[0]].mount(document.getElementById('overlay'),source,makePlan(recipe),gsap);
};
window.sampleAt=t=>{
 testTimeline.seek(t,false);
 const source=document.getElementById('source');
 const visible=node=>{
   let current=node;
   while(current&&current.id!=='frame'){
     const s=getComputedStyle(current);
     if(Number(s.opacity)<.001||s.visibility==='hidden'||s.display==='none')return false;
     current=current.parentElement;
   }
   return true;
 };
 const nodes=[...document.querySelectorAll('#overlay *')];
 const painted=n=>{const s=getComputedStyle(n);return visible(n)&&
   ((n.children.length===0&&n.textContent.trim())||s.backgroundColor!=='rgba(0, 0, 0, 0)'||parseFloat(s.borderWidth)>0);};
 const matrix=new DOMMatrix(getComputedStyle(source).transform);
 return {scale:matrix.a,
   sourceTransform:[matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f],
   visibleNodes:nodes.filter(painted).length,
   copy:nodes.filter(n=>n.children.length===0&&visible(n)).map(n=>n.textContent),
   states:nodes.filter(painted).map(n=>({transform:getComputedStyle(n).transform,opacity:getComputedStyle(n).opacity,
     visibility:getComputedStyle(n).visibility,text:n.textContent}))};
};
}""")
                for recipe in ("A01", "A02", "A03", "B01", "B02", "B03"):
                    with self.subTest(recipe=recipe):
                        page.evaluate("mountRecipe", recipe)
                        self.assertTrue(page.evaluate("testTimeline.paused()"))
                        phases = [0, .2, .5, 2.0, 3.6, 4.1]
                        first, screenshots = {}, {}
                        for time in phases:
                            first[time] = page.evaluate("sampleAt", time)
                            screenshots[time] = hashlib.sha256(page.screenshot()).hexdigest()
                        # Reverse and non-monotonic seeks must match first traversal exactly.
                        for time in (2.0, .2, 4.1, .5, 0, 3.6, 2.0):
                            self.assertEqual(page.evaluate("sampleAt", time), first[time])
                            self.assertEqual(hashlib.sha256(page.screenshot()).hexdigest(), screenshots[time])
                        self.assertEqual(first[0]["visibleNodes"], 0)
                        self.assertEqual(first[4.1]["visibleNodes"], 0)
                        self.assertAlmostEqual(first[0]["scale"], 1)
                        self.assertAlmostEqual(first[4.1]["scale"], 1)
                        if recipe.endswith("01"):
                            self.assertAlmostEqual(first[2.0]["scale"], 1.25)
                        else:
                            self.assertAlmostEqual(first[2.0]["scale"], 1)
                            self.assertEqual(len(first[2.0]["copy"]), 1)
                            if recipe.endswith("03"):
                                self.assertEqual(first[.5]["copy"], ["操作前"])
                                self.assertEqual(first[2.0]["copy"], ["操作后"])
                        receipts.append({"recipe": recipe, "phase_states": first})
                print(json.dumps({"evidence_tier": "synthetic_browser_real_gsap",
                    "hyperframes_media_render": False,
                    "browser_path": browser_path,
                    "gsap_sha256": hashlib.sha256(Path(gsap_path).read_bytes()).hexdigest(),
                    "component_sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in sources.items()},
                    "recipes_passed": [row["recipe"] for row in receipts]}, ensure_ascii=False))
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
