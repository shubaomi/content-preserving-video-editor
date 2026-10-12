/* B-direction visual consumer. No semantic selection, media I/O, or timeline edits.
 * Caller validates current evidence bytes, target/layout safety and font availability.
 * Coordinates: crop normalized to source; source_box/overlay_box in output pixels.
 * Phases/steps/after_at are event-local; active_end is output-global.
 * Mount on an empty, positioned bounded event layer. sourceElement is a dedicated
 * neutral (x=0,y=0,scale=1) untimed wrapper, never the video/.clip itself. Caller
 * owns registration/scheduling and must not overlap source-wrapper transforms.
 */
(function (global) {
  'use strict';
  const PHASES = ['entrance', 'explain', 'hold', 'exit'];
  function fail(message, code = 'invalid_motion_editorial_b') {
    const error = new Error(message); error.code = code; throw error;
  }
  function finite(value, name) {
    if (typeof value !== 'number' || !Number.isFinite(value)) fail(name + ' must be finite');
    return value;
  }
  function box(value, name, normalized = false) {
    if (!value || typeof value !== 'object') fail(name + ' required');
    for (const key of ['x', 'y', 'width', 'height']) finite(value[key], name + '.' + key);
    if (value.x < 0 || value.y < 0 || value.width <= 0 || value.height <= 0) fail(name + ' invalid bounds');
    if (normalized && (value.x + value.width > 1 || value.y + value.height > 1)) fail(name + ' exceeds source');
    return value;
  }
  function reference(value) {
    if (!value || typeof value.path !== 'string' || !/^(?:[A-Za-z]:[\\/]|\/)/.test(value.path)
      || !/^[a-f0-9]{64}$/.test(value.sha256 || '')) fail('Current local frame reference required');
  }
  function copy(value) {
    if (typeof value !== 'string' || !value.trim() || /[<>\r\n]/.test(value)) fail('Single-line literal approved copy required');
  }
  function validate(event) {
    if (!event || !['B01', 'B02', 'B03'].includes(event.recipe_id)) fail('Unknown B recipe');
    const start = finite(event.output_start, 'output_start');
    const duration = finite(event.output_end, 'output_end') - start;
    const active = finite(event.active_end, 'active_end') - start;
    if (start < 0 || duration <= 0 || active <= 0 || active > duration) fail('Invalid active window');
    let end = 0;
    for (const name of PHASES) {
      const p = event.phases && event.phases[name];
      if (!p || finite(p.start, name) < end || finite(p.end, name) <= p.start || p.end > active) fail('Unordered or out-of-window phase');
      end = p.end;
    }
    const refs = event.evidence && event.evidence.frame_refs;
    if (!Array.isArray(refs) || !refs.length) fail('Observed UI frame evidence required');
    refs.forEach(reference);
    if (!Array.isArray(event.approved_visible_copy)) fail('Approved copy list required');
    event.approved_visible_copy.forEach(copy);
    if (new Set(event.approved_visible_copy).size !== event.approved_visible_copy.length) fail('Duplicate approved copy');
    if (event.overlay_box !== null) box(event.overlay_box, 'overlay_box');
    if (event.source_crop !== null) {
      const crop = box(event.source_crop, 'source_crop', true);
      box(event.source_box, 'source_box');
      if (Math.abs(crop.width-crop.height) > 1e-9) fail('Uniform source crop required; do not guess aspect handling');
      const scale = Math.min(1 / crop.width, 1 / crop.height);
      const maximum = finite(event.evidence.maximum_scale, 'maximum_scale');
      if (maximum < 1 || scale > maximum) fail('Crop exceeds evidenced maximum scale');
    }
    if (event.recipe_id === 'B01') {
      if (event.approved_visible_copy.length > 1) fail('B01 accepts at most one approved short label');
      if (event.approved_visible_copy.length && !event.overlay_box) fail('Label needs approved output box');
      if (!event.source_crop && !event.overlay_box) fail('B01 has no explicit visual action');
    }
    if (event.recipe_id === 'B02') {
      if (event.source_crop !== null) fail('B02 retains original source container');
      if (!Array.isArray(event.steps) || event.steps.length < 2) fail('B02 requires explicit proof steps');
      let previous = event.phases.entrance.start;
      event.steps.forEach(step => {
        if (finite(step.start, 'step.start') < previous || finite(step.end, 'step.end') <= step.start
          || step.end > event.phases.exit.end) fail('Invalid proof-step order/window');
        copy(step.copy); reference(step.frame_ref); box(step.overlay_box, 'step.overlay_box');
        previous = step.end;
      });
      if (JSON.stringify(event.steps.map(s => s.copy)) !== JSON.stringify(event.approved_visible_copy)) fail('Proof copy differs from approved list');
    }
    if (event.recipe_id === 'B03') {
      if (event.comparison_mode !== 'sequential_source') fail('Parallel/wipe requires separately supplied real-state elements', 'unavailable_real_state_elements');
      if (event.source_crop !== null) fail('Sequential fallback cannot reframe or swap source');
      box(event.overlay_box, 'comparison label box');
      const states = event.evidence.states;
      if (!Array.isArray(states) || states.length !== 2) fail('Two real state references required');
      states.forEach(s => { reference(s.frame_ref); copy(s.label); if (finite(s.source_time, 'source_time') < 0) fail('Negative source time'); });
      if (states[0].source_time >= states[1].source_time || states[0].frame_ref.sha256 === states[1].frame_ref.sha256) fail('Distinct chronological states required');
      if (JSON.stringify(states.map(s => s.label)) !== JSON.stringify(event.approved_visible_copy)) fail('State labels differ from approved copy');
      const after = finite(event.after_at, 'after_at');
      if (after <= event.phases.entrance.end || after >= event.phases.exit.start) fail('State transition outside readable hold');
    }
    return {duration, active};
  }
  function node(root, bounds, text, underline) {
    const el = root.ownerDocument.createElement('div');
    Object.assign(el.style, {position:'absolute', left:bounds.x + 'px', top:bounds.y + 'px',
      width:bounds.width + 'px', height:bounds.height + 'px', boxSizing:'border-box',
      pointerEvents:'none', opacity:'0'});
    if (underline) Object.assign(el.style, {backgroundColor:'#2B6CAD', transformOrigin:'0% 50%'});
    else {
      el.textContent = text;
      Object.assign(el.style, {color:'#172033', backgroundColor:'#FFFFFF', fontFamily:'"Microsoft YaHei UI", sans-serif',
        fontWeight:'600', fontSize:'24px', lineHeight:'1.25', padding:'4px 8px', overflow:'hidden', whiteSpace:'nowrap'});
    }
    root.appendChild(el); return el;
  }
  function visibility(tl, el, start, end, enterDuration, exitDuration) {
    const fadeIn = Math.min(enterDuration, (end-start)/3);
    const fadeOut = Math.min(exitDuration, (end-start)/3);
    tl.fromTo(el, {opacity:0}, {opacity:1, duration:fadeIn, ease:'power2.out', immediateRender:false}, start);
    tl.fromTo(el, {opacity:1}, {opacity:0, duration:fadeOut, ease:'power2.in', immediateRender:false}, end-fadeOut);
    tl.set(el, {opacity:0}, end);
  }
  function mount(root, sourceElement, event, gsap) {
    const window = validate(event); // Validate all input before changing any DOM.
    if (!root || !root.ownerDocument || !root.appendChild || root.children.length) fail('Empty bounded event root required');
    if (!sourceElement || sourceElement === root || ['VIDEO','AUDIO'].includes(sourceElement.tagName)
      || (sourceElement.classList && sourceElement.classList.contains('clip'))) fail('Dedicated untimed source wrapper required');
    if (event.source_crop && sourceElement.style && sourceElement.style.transform && sourceElement.style.transform !== 'none') fail('Source wrapper must start untransformed');
    if (!gsap || typeof gsap.timeline !== 'function') fail('Pinned local GSAP required');
    const tl = gsap.timeline({paused:true});
    const p = event.phases;
    tl.data = {recipe_id:event.recipe_id, local_active_end:window.active,
      fallback:event.recipe_id === 'B03' ? 'sequential_source' : null,
      evidence_status:'upstream_current_hash_validation_required', source_swapped:false};
    if (event.source_crop) {
      const c = event.source_crop, b = event.source_box;
      const scale = Math.min(1/c.width, 1/c.height);
      // Transform local source pixels around its existing output placement.
      const pose = {x:b.width/2-(c.x+c.width/2)*b.width*scale,
        y:b.height/2-(c.y+c.height/2)*b.height*scale, scale, transformOrigin:'0% 0%'};
      const neutral = {x:0,y:0,scale:1,transformOrigin:'0% 0%'};
      tl.set(sourceElement,neutral,0);
      tl.fromTo(sourceElement, neutral, {...pose,duration:p.entrance.end-p.entrance.start,ease:'power3.out',immediateRender:false}, p.entrance.start);
      tl.fromTo(sourceElement, pose, {...neutral,duration:p.exit.end-p.exit.start,ease:'power2.inOut',immediateRender:false}, p.exit.start);
      tl.set(sourceElement,neutral,p.exit.end);
    }
    if (event.recipe_id === 'B01' && event.overlay_box) {
      const el = node(root,event.overlay_box,event.approved_visible_copy[0] || '',!event.approved_visible_copy.length);
      visibility(tl,el,p.entrance.start,p.exit.end,p.entrance.end-p.entrance.start,p.exit.end-p.exit.start);
    }
    if (event.recipe_id === 'B02' || event.recipe_id === 'B03') {
      const container = root.ownerDocument.createElement('div');
      Object.assign(container.style,{position:'absolute',inset:'0',pointerEvents:'none'});
      root.appendChild(container);
      const steps = event.recipe_id === 'B02' ? event.steps : [
        {start:p.entrance.start,end:event.after_at,copy:event.evidence.states[0].label,overlay_box:event.overlay_box},
        {start:event.after_at,end:p.exit.end,copy:event.evidence.states[1].label,overlay_box:event.overlay_box}];
      steps.forEach(step => {
        const el = node(container,step.overlay_box,step.copy,false);
        visibility(tl,el,step.start,step.end,p.entrance.end-p.entrance.start,p.exit.end-p.exit.start);
      });
    }
    return tl;
  }
  const api = Object.freeze({mount,validate});
  global.MotionEditorialB = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
