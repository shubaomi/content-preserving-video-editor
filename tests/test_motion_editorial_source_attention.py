"""FIX03 source-region attention: compiler authority and real painted DOM."""
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import motion_editorial as me


class SourceAttentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        frame = self.root / 'frame.png'
        frame.write_bytes(b'synthetic fixture, not actual source evidence')
        self.ref = me.ref(frame)
        self.projection = {'fixture': True}
        self.brief = {'events': [{'id': 'compare@body', 'decision': 'render',
            'output_start': 10, 'output_end': 15, 'approved_visible_copy': [],
            'editorial_copy_policy': 'source_only',
            'target_binding_ids': ['legend-binding', 'plot-binding'],
            'target_frame_evidence': [str(frame)]}]}
        self.bindings = {}
        steps = []
        for index, (target, region) in enumerate((
                ('legend', {'x': .2, 'y': .7, 'width': .5, 'height': .08}),
                ('plot', {'x': .2, 'y': .2, 'width': .5, 'height': .4}))):
            key = target + '-binding'
            self.bindings[key] = {'schema_version': '1.1.0', 'binding_id': key,
                'semantic_event_id': 'compare@body', 'created_at': '2026-10-12T00:00:00Z',
                'producer': 'synthetic-test', 'target_kind': 'chart_region',
                'tracking_mode': 'static', 'target_ids': [target],
                'source_window': {'start_seconds': 30, 'end_seconds': 35},
                'output_window': {'start_seconds': 10, 'end_seconds': 15},
                'active_windows': [{'start_seconds': 10, 'end_seconds': 14}],
                'observations': [{'timestamp_seconds': t, 'target_id': target,
                    'source_state_sha256': 'a' * 64, 'visible': True,
                    'confidence': .99, 'bbox': region,
                    'evidence': {**self.ref, 'source': 'synthetic-test'}} for t in (30, 31, 33, 35)],
                'state_events': [], 'invalidation_policy': {'on_state_change': 'exit',
                    'on_target_lost': 'exit', 'minimum_confidence': .8},
                'status': 'resolved', 'input_hashes': {'source_media_sha256': 'b' * 64,
                    'evidence_bundle_sha256': 'c' * 64}}
            steps.append({'start': .1 if index == 0 else 1.4, 'end': 1.4 if index == 0 else 3.7,
                'binding_id': key, 'target_id': target, 'source_state_sha256': 'a' * 64,
                'source_region': region, 'frame_ref': self.ref})
        self.event = {'instance_id': 'compare@body', 'decision': 'overlay', 'recipe_id': 'B02',
            'viewer_task': 'Compare actual legend and plot', 'information_gain': 'Source relation',
            'primary_focus': 'real chart', 'rationale': 'No extra labels',
            'source_crop': None, 'source_box': {'x': 40, 'y': 20, 'width': 500, 'height': 400},
            'overlay_box': None, 'approved_visible_copy': [], 'output_start': 10, 'output_end': 15,
            'active_end': 14, 'target_binding_ids': ['legend-binding', 'plot-binding'],
            'phases': {'entrance': {'start': .1, 'end': .3}, 'explain': {'start': .3, 'end': 1},
                'hold': {'start': 1, 'end': 3.5}, 'exit': {'start': 3.5, 'end': 3.7}},
            'evidence': {'frame_refs': [self.ref]},
            'sound': {'decision': 'intentionally_silent', 'reason': 'speech first'},
            'source_attention': {'schema_version': 1, 'mode': 'dim_outside',
                'dim_opacity': .18, 'steps': steps}}

    def compile(self, event=None, bindings=None):
        plan = {'schema_version': 2, 'kind': 'shot_motion_plan',
            'direction': 'professional_software_demo', 'projection_sha256': me.digest(self.projection),
            'semantic_sha256': me.digest(self.brief), 'default_decorations': False,
            'events': [self.event if event is None else event]}
        return me.compile_shot_plan(plan, projection=self.projection, output_brief=self.brief,
            direction='professional_software_demo', roots=[self.root],
            target_bindings=self.bindings if bindings is None else bindings)

    def test_compiler_accepts_real_source_attention_without_copy(self):
        result = self.compile()
        self.assertEqual(result['events'][0]['source_attention'], self.event['source_attention'])
        self.assertEqual(result['events'][0]['approved_visible_copy'], [])
        self.assertEqual(result['dependencies'], [str((self.root / 'frame.png').resolve())])

    def test_component_accepts_compiled_payload_and_creates_painted_masks(self):
        payload = self.compile()['events'][0]
        program = r"""
const assert=require('node:assert/strict'), B=require(process.argv[1]);
const p=JSON.parse(process.argv[2]);
function el(){return {style:{},children:[],attrs:{},ownerDocument:{createElement:el},
appendChild(n){this.children.push(n)},setAttribute(k,v){this.attrs[k]=v},classList:{contains(){return false}}};}
const root=el(),source=el(); const gsap={timeline(){return {ops:[],fromTo(t,f,v,at){this.ops.push({t,f,v,at});return this},set(t,v,at){this.ops.push({t,v,at});return this}}}};
const tl=B.mount(root,source,p,gsap);
assert.equal(root.children.length,2);
assert(root.children.every(step=>step.children.length===4));
assert(root.children.flatMap(s=>s.children).every(n=>n.style.backgroundColor==='rgba(0, 0, 0, 0.18)'&&!n.textContent));
assert(tl.ops.every(op=>op.t!==source));
for(const change of [p=>p.steps=[],p=>p.source_attention.extra=1,p=>p.source_attention.steps[0].source_region.x=.9,
 p=>p.source_attention.dim_opacity=.8,p=>p.source_attention.steps[1].start=.5,p=>p.source_attention.steps[0].frame_ref.sha256='bad']){
const bad=structuredClone(p);change(bad);assert.throws(()=>B.validate(bad));}
"""
        result = subprocess.run(['node', '-e', program,
            str(ROOT / 'assets/motion-editorial-v3/professional-software-demo.js'), json.dumps(payload)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compiler_fails_closed_on_stale_wrong_or_unbounded_targets(self):
        changes = [lambda b: b.clear(),
            lambda b: b['legend-binding'].update(status='unresolved'),
            lambda b: b['legend-binding'].update(semantic_event_id='other@body'),
            lambda b: b['legend-binding']['active_windows'][0].update(end_seconds=10.5),
            lambda b: b['legend-binding']['observations'][0]['evidence'].update(sha256='0'*64),
            lambda b: b['legend-binding']['observations'][0].update(source_state_sha256='d'*64),
            lambda b: b['legend-binding']['observations'][0]['bbox'].update(x=.21),
            lambda b: b['legend-binding']['observations'].pop(0),
            lambda b: b['legend-binding']['invalidation_policy'].update(on_state_change='rebind')]
        for change in changes:
            with self.subTest(change=change):
                bindings = deepcopy(self.bindings)
                change(bindings)
                with self.assertRaises(ValueError):
                    self.compile(bindings=bindings)

    def test_compiled_payload_real_browser_painted_masks_and_seek(self):
        browser_path = os.environ.get('MOTION_EDITORIAL_BROWSER')
        gsap_path = os.environ.get('MOTION_EDITORIAL_GSAP')
        if not browser_path or not gsap_path:
            self.skipTest('explicit installed browser and local GSAP required; no install')
        from playwright.sync_api import sync_playwright
        payload = self.compile()['events'][0]
        component = ROOT / 'assets/motion-editorial-v3/professional-software-demo.js'
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path, headless=True)
            try:
                context = browser.new_context(viewport={'width': 600, 'height': 460}, offline=True)
                context.route('**/*', lambda route: route.abort())
                page = context.new_page()
                page.set_content('<style>body{margin:0}#frame{position:relative;width:600px;height:460px;background:white}'
                    '#source{position:absolute;left:40px;top:20px;width:500px;height:400px;background:rgb(180,200,220)}'
                    '#overlay{position:absolute;inset:0}</style><div id="frame"><div id="source"></div><div id="overlay"></div></div>')
                page.add_script_tag(content=Path(gsap_path).read_text(encoding='utf-8'))
                page.add_script_tag(content=component.read_text(encoding='utf-8'))
                page.evaluate('p=>{window.tl=MotionEditorialB.mount(document.querySelector("#overlay"),document.querySelector("#source"),p,gsap);}', payload)
                def sample(time):
                    state = page.evaluate('''t=>{tl.seek(t,false);return {
                        transform:getComputedStyle(document.querySelector('#source')).transform,
                        text:document.querySelector('#overlay').textContent,
                        masks:[...document.querySelectorAll('[data-source-attention-step]')].filter(n=>Number(getComputedStyle(n).opacity)>.99)
                         .flatMap(n=>[...n.children].map(m=>{const r=m.getBoundingClientRect();return {
                           x:r.x,y:r.y,width:r.width,height:r.height,color:getComputedStyle(m).backgroundColor,
                           target:n.getAttribute('data-target-id')}}))}}''', time)
                    return state, hashlib.sha256(page.screenshot()).hexdigest()
                first = {t: sample(t) for t in (0, .5, 2, 4.1)}
                for t in (2, .5, 4.1, 0, 2):
                    self.assertEqual(sample(t), first[t])
                self.assertEqual(first[0][0]['masks'], [])
                self.assertEqual(first[4.1][0]['masks'], [])
                for time, target, hole in ((.5, 'legend', (140, 300, 250, 32)), (2, 'plot', (140, 100, 250, 160))):
                    state = first[time][0]
                    self.assertEqual(state['transform'], 'none')
                    self.assertEqual(state['text'], '')
                    self.assertEqual(len(state['masks']), 4)
                    area = 0
                    for mask in state['masks']:
                        self.assertEqual(mask['target'], target)
                        self.assertEqual(mask['color'], 'rgba(0, 0, 0, 0.18)')
                        self.assertGreaterEqual(mask['x'], 40)
                        self.assertGreaterEqual(mask['y'], 20)
                        self.assertLessEqual(mask['x'] + mask['width'], 540)
                        self.assertLessEqual(mask['y'] + mask['height'], 420)
                        self.assertTrue(mask['x'] + mask['width'] <= hole[0] or mask['x'] >= hole[0]+hole[2]
                            or mask['y']+mask['height'] <= hole[1] or mask['y'] >= hole[1]+hole[3])
                        area += mask['width'] * mask['height']
                    self.assertAlmostEqual(area, 500 * 400 - hole[2] * hole[3])
                print(json.dumps({'evidence_tier':'synthetic_browser_real_gsap', 'hyperframes_media_render':False,
                    'component_sha256':me.sha256_file(component), 'painted_masks':8,
                    'sequential_targets':['legend','plot'], 'nonmonotonic_seek_equal':True}))
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
