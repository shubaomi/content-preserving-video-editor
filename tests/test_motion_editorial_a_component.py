"""Offline A recipe contracts; mock DOM/GSAP is not rendered/aesthetic evidence."""
from pathlib import Path
import subprocess
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "assets/motion-editorial-v3/authentic-product-editorial.js"


class MotionEditorialAComponentTests(unittest.TestCase):
    def test_contract_and_deterministic_poses(self):
        program = r"""
const assert=require('node:assert/strict');
const A=require(process.argv[1]);
function element(){return {style:{},children:[],ownerDocument:{createElement:element},
  appendChild(n){this.children.push(n);},classList:{contains(){return false;}}};}
function runtime(){return {timeline(options){return {options,ops:[],
  set(target,to,at){this.ops.push({target,to,at});return this;},
  fromTo(target,from,to,at){this.ops.push({target,from,to,at});return this;}};}};}
function plan(){return {recipe_id:'A01',output_start:20,output_end:25,active_end:24,
  phases:{entrance:{start:.1,end:.3},explain:{start:.3,end:.7},hold:{start:.7,end:3.5},exit:{start:3.5,end:3.7}},
  source_crop:{x:.1,y:.05,width:.8,height:.8},source_box:{x:30,y:50,width:540,height:960},
  approved_visible_copy:[],overlay_box:null,evidence:{maximum_scale:1.25}};}
function mount(p){let root=element(),source=element();return {root,source,tl:A.mount(root,source,p,runtime())};}
let p=plan(),before=JSON.stringify(p),a=mount(p);
assert.equal(a.tl.options.paused,true);assert.equal(JSON.stringify(p),before);
assert.equal(a.tl.data.recipe_id,'A01');assert.equal(a.root.children.length,0);
let zoom=a.tl.ops.find(x=>x.to.scale===1.25);
assert.equal(zoom.to.x,-67.5);assert.equal(zoom.to.y,-60);
assert.equal(zoom.at,.3);assert(Math.abs(zoom.to.duration-.4)<1e-12);
assert.equal(a.tl.ops.at(-1).to.scale,1);assert.equal(a.tl.ops.at(-1).to.x,0);
assert(a.tl.ops.every(o=>o.at+(o.to.duration||0)<=p.active_end-p.output_start));
assert(a.tl.ops.filter(x=>x.from).every(x=>x.to.immediateRender===false));
for(const change of [p=>p.output_start=NaN,p=>p.output_end=Infinity,p=>p.phases.hold.start=.2,
 p=>p.phases.exit.end=6,p=>p.active_end=23.6,p=>delete p.active_end,p=>p.source_crop.width=.6,p=>p.source_crop.x=.3,
 p=>delete p.evidence.maximum_scale,p=>p.evidence.maximum_scale=1.2,
 p=>p.source_box.width=0,p=>p.approved_visible_copy=['invented'],p=>p.recipe_id='A99']){
 let bad=plan();change(bad);let root=element(),source=element();
 assert.throws(()=>A.mount(root,source,bad,runtime()));assert.equal(root.children.length,0);
 assert.deepEqual(source.style,{},'validate before mutation');
}
let reveal=plan();reveal.recipe_id='A02';reveal.source_crop=null;
reveal.overlay_box={x:40,y:100,width:180,height:48};reveal.approved_visible_copy=['<b>真实原话</b>'];
reveal.evidence={target_binding_ref:'product_binding_01',target_window:{start:20,end:25}};
let b=mount(reveal);assert.equal(b.root.children.length,1);
assert.equal(b.root.children[0].children[0].textContent,'<b>真实原话</b>');
assert(b.tl.ops.every(o=>o.target!==b.source));
assert.equal(b.tl.ops.at(-1).to.autoAlpha,0);
for(const change of [p=>p.evidence.target_window.start=20.2,p=>p.evidence.target_binding_ref='',
 p=>p.approved_visible_copy.push('extra'),p=>p.overlay_box.height=-1]){
 let bad=structuredClone(reveal);change(bad);assert.throws(()=>mount(bad));
}
let compare=structuredClone(reveal);compare.recipe_id='A03';compare.approved_visible_copy=['放入前','放入后'];
const ref=n=>({path:'C:/fixture/'+n+'.png',sha256:n.repeat(64)});
compare.evidence={before_state_ref:ref('a'),after_state_ref:ref('b'),after_at:2};
let c=mount(compare);assert.equal(c.tl.data.fallback,'sequential_source');
assert.deepEqual(c.root.children[0].children.map(n=>n.textContent),compare.approved_visible_copy);
assert(c.tl.ops.every(o=>o.target!==c.source));
for(const change of [p=>p.evidence.after_state_ref=ref('a'),p=>p.evidence.before_state_ref='fake_ref',p=>p.evidence.after_at=5,
 p=>p.evidence.after_at=.2,p=>p.approved_visible_copy.pop()]){
 let bad=structuredClone(compare);change(bad);assert.throws(()=>mount(bad));
}
const norm=x=>x.tl.ops.map(o=>({from:o.from,to:o.to,at:o.at}));
for(const tagName of ['VIDEO','AUDIO']){let source=element();source.tagName=tagName;
 assert.throws(()=>A.mount(element(),source,plan(),runtime()));}
assert.deepEqual(norm(mount(plan())),norm(mount(plan())));
for(const one of [a,b,c])assert(one.tl.ops.every(o=>!o.to.onUpdate&&!o.to.onComplete));
console.log('A01/A02/A03 deterministic contract fixture passed');
"""
        result = subprocess.run(["node", "-e", program, str(COMPONENT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
