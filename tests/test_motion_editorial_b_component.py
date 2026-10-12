"""Offline component-contract tests; DOM/GSAP fixture, not rendered visual evidence."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "assets/motion-editorial-v3/professional-software-demo.js"


class MotionEditorialBTests(unittest.TestCase):
    def test_runtime_contract(self):
        program = r"""
const assert = require('node:assert/strict');
const B = require(process.argv[1]);
function element() { return {style:{},children:[],ownerDocument:{createElement:element},
  appendChild(n){this.children.push(n);},classList:{contains(){return false;}}}; }
function runtime() { return {timeline(options){return {options,ops:[],
  fromTo(target,from,to,at){this.ops.push({target,from,to,at});return this;},
  set(target,to,at){this.ops.push({target,from:{},to,at});return this;}};}}; }
const ref = (n) => ({path:'C:/evidence/'+n+'.png',sha256:n.repeat(64)});
function plan(){return {recipe_id:'B01',output_start:10,output_end:15,active_end:14,
 phases:{entrance:{start:.1,end:.3},explain:{start:.3,end:1},hold:{start:1,end:3.5},exit:{start:3.5,end:3.7}},
 source_crop:{x:.1,y:.1,width:.8,height:.8},source_box:{x:100,y:0,width:960,height:624},
 overlay_box:{x:400,y:200,width:30,height:2},approved_visible_copy:[],
 evidence:{maximum_scale:1.25,frame_refs:[ref('a')]}};}
function mount(p){let root=element(),source=element();return {root,source,tl:B.mount(root,source,p,runtime())};}
let p=plan(),before=JSON.stringify(p),one=mount(p);
assert.equal(one.tl.options.paused,true);
assert.equal(JSON.stringify(p),before,'plan immutable');
assert.equal(one.tl.data.recipe_id,'B01');
assert(one.tl.ops.every(o=>o.at+(o.to.duration||0)<=4),'before active boundary');
assert(one.tl.ops.some(o=>o.target===one.source&&o.to.scale===1));
assert.equal(one.root.children.length,1,'only locator, no default card');
assert(!JSON.stringify(one.root).includes('boxShadow'));
for(const change of [p=>p.active_end=13.6,p=>{p.source_crop.width=.01;p.source_crop.height=.01;},
 p=>p.phases.hold.end=4,p=>p.output_start=NaN,p=>p.evidence.frame_refs=[],
 p=>p.approved_visible_copy=['<img src=x>'],p=>p.source_box.width=0]){
 let bad=plan();change(bad);let root=element();assert.throws(()=>B.mount(root,element(),bad,runtime()));assert.equal(root.children.length,0);
}
let b2=plan();b2.recipe_id='B02';b2.source_crop=null;b2.approved_visible_copy=['第一步','结果'];
b2.steps=[{start:.1,end:1.2,copy:'第一步',overlay_box:{x:400,y:200,width:180,height:48},frame_ref:ref('a')},
 {start:1.2,end:3.7,copy:'结果',overlay_box:{x:400,y:200,width:180,height:48},frame_ref:ref('b')}];
let two=mount(b2);assert.equal(two.root.children.length,1,'one stable proof container');
assert.equal(two.root.children[0].children.length,2);
assert.deepEqual(two.root.children[0].children.map(x=>x.textContent),b2.approved_visible_copy);
let bad=structuredClone(b2);bad.steps[1].start=1;assert.throws(()=>mount(bad));
bad=structuredClone(b2);bad.steps[1].copy='invented';assert.throws(()=>mount(bad));
let b3=plan();b3.recipe_id='B03';b3.source_crop=null;b3.comparison_mode='sequential_source';b3.after_at=2;
b3.approved_visible_copy=['操作前','操作后'];b3.overlay_box={x:400,y:200,width:180,height:48};
b3.evidence.states=[{frame_ref:ref('a'),source_time:11,label:'操作前'},{frame_ref:ref('b'),source_time:12,label:'操作后'}];
let three=mount(b3);assert.equal(three.tl.data.fallback,'sequential_source');
assert(three.tl.ops.every(o=>o.target!==three.source),'never swaps/reframes source');
bad=structuredClone(b3);bad.comparison_mode='wipe';assert.throws(()=>mount(bad),e=>e.code==='unavailable_real_state_elements');
bad=structuredClone(b3);bad.evidence.states[1].frame_ref=ref('a');assert.throws(()=>mount(bad));
bad=structuredClone(b3);bad.after_at=5;assert.throws(()=>mount(bad));
// Construction is deterministic and uses explicit start/end poses, not callbacks.
let normalize = x => x.tl.ops.map(o=>({from:o.from,to:o.to,at:o.at}));
assert.deepEqual(normalize(mount(plan())),normalize(mount(plan())));
assert(one.tl.ops.every(o=>!o.to.onUpdate&&!o.to.onComplete));
console.log('B01/B02/B03 contract fixture passed');
"""
        result = subprocess.run(["node", "-e", program, str(COMPONENT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
