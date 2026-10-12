/* Deterministic, visual-only A recipes. Caller owns evidence/rights/font/layout
 * validation, original media, and a single master timeline. Add this paused,
 * event-local timeline at event.output_start. A01 requires an exclusive,
 * untransformed same-size source wrapper; never mount competing camera tracks.
 * Evidence IDs are references, not proof that the referenced files were verified.
 */
(function (global) {
  'use strict';
  function requireValue(ok, message) {
    if (!ok) throw new TypeError('MotionEditorialA: ' + message);
  }
  function number(value) { return typeof value === 'number' && Number.isFinite(value); }
  function text(value) { return typeof value === 'string' && value.trim().length > 0; }
  function reference(value) {
    return value && typeof value.path === 'string' && /^(?:[A-Za-z]:[\\/]|\/)/.test(value.path)
      && /^[a-f0-9]{64}$/.test(value.sha256 || '');
  }
  function box(value, normalized) {
    requireValue(value && ['x', 'y', 'width', 'height'].every(k => number(value[k])), 'finite box required');
    requireValue(value.x >= 0 && value.y >= 0 && value.width > 0 && value.height > 0, 'invalid box');
    if (normalized) requireValue(value.x + value.width <= 1 && value.y + value.height <= 1, 'crop outside source');
  }
  function validate(event) {
    requireValue(event && ['A01', 'A02', 'A03'].includes(event.recipe_id), 'unknown recipe');
    requireValue(number(event.output_start) && event.output_start >= 0 && number(event.output_end) && event.output_end > event.output_start, 'invalid output window');
    requireValue(number(event.active_end) && event.active_end > event.output_start && event.active_end <= event.output_end, 'invalid active window');
    const active = event.active_end - event.output_start;
    let previous = 0;
    for (const name of ['entrance', 'explain', 'hold', 'exit']) {
      const phase = event.phases && event.phases[name];
      requireValue(phase && number(phase.start) && number(phase.end) && phase.start >= previous && phase.end > phase.start && phase.end <= active, 'invalid local phase ' + name);
      previous = phase.end;
    }
    requireValue(Array.isArray(event.approved_visible_copy) && event.approved_visible_copy.every(text), 'exact approved copy required');
    requireValue(event.evidence && typeof event.evidence === 'object', 'evidence required');
    const evidence = event.evidence;
    if (event.recipe_id === 'A01') {
      box(event.source_crop, true);
      box(event.source_box, false);
      requireValue(Math.abs(event.source_crop.width - event.source_crop.height) < 1e-9, 'uniform crop required');
      requireValue(number(evidence.maximum_scale) && evidence.maximum_scale >= 1 && 1 / event.source_crop.width <= evidence.maximum_scale, 'measured maximum_scale required');
      requireValue(event.approved_visible_copy.length === 0 && event.overlay_box === null, 'A01 uses source only');
    } else {
      requireValue(event.source_crop === null, 'label recipes cannot reframe source');
      box(event.overlay_box, false);
      if (event.recipe_id === 'A02') {
        const window = evidence.target_window;
        requireValue(event.approved_visible_copy.length === 1, 'A02 requires one approved label');
        requireValue(text(evidence.target_binding_ref) && window && number(window.start) && number(window.end) && window.start <= event.output_start && window.end >= event.output_end, 'resolved target window must cover event');
      } else {
        requireValue(event.approved_visible_copy.length === 2, 'A03 requires two approved state labels');
        requireValue(reference(evidence.before_state_ref) && reference(evidence.after_state_ref) && evidence.before_state_ref.sha256 !== evidence.after_state_ref.sha256, 'two distinct hash-bound real state references required');
        requireValue(number(evidence.after_at) && evidence.after_at >= event.phases.explain.start && evidence.after_at < event.phases.exit.start, 'state switch outside explain/hold');
      }
    }
  }
  function mount(root, sourceElement, event, gsap) {
    validate(event); // All plan rejection precedes DOM mutation.
    requireValue(root && root.style && root.ownerDocument && typeof root.appendChild === 'function', 'event root required');
    requireValue(sourceElement && sourceElement !== root && sourceElement.style, 'separate source wrapper required');
    requireValue(!['VIDEO', 'AUDIO'].includes(sourceElement.tagName), 'media elements are owned by HyperFrames');
    requireValue(!root.classList || !root.classList.contains('clip'), 'do not animate framework clip');
    requireValue(gsap && typeof gsap.timeline === 'function', 'GSAP runtime required');
    if (event.recipe_id === 'A01') {
      requireValue(!sourceElement.style.transform || sourceElement.style.transform === 'none', 'source wrapper must have no prior transform');
      requireValue(!sourceElement.classList || !sourceElement.classList.contains('clip'), 'source must be a dedicated wrapper');
    }
    const timeline = gsap.timeline({paused: true});
    const phases = event.phases;
    timeline.data = {recipe_id: event.recipe_id, time_basis: 'event_local',
      output_start: event.output_start, output_end: event.output_end, active_end: event.active_end,
      fallback: event.recipe_id === 'A03' ? 'sequential_source' : null};
    if (event.recipe_id === 'A01') {
      const crop = event.source_crop, source = event.source_box;
      const identity = {x: 0, y: 0, scale: 1, transformOrigin: '0px 0px'};
      const focus = {x: -crop.x * source.width / crop.width,
        y: -crop.y * source.height / crop.width, scale: 1 / crop.width, transformOrigin: '0px 0px'};
      timeline.set(sourceElement, identity, 0);
      timeline.fromTo(sourceElement, identity, Object.assign({}, focus, {
        duration: phases.explain.end - phases.explain.start, ease: 'power2.inOut', immediateRender: false
      }), phases.explain.start);
      timeline.fromTo(sourceElement, focus, Object.assign({}, identity, {
        duration: phases.exit.end - phases.exit.start, ease: 'power2.inOut', immediateRender: false
      }), phases.exit.start);
      timeline.set(sourceElement, identity, phases.exit.end);
      return timeline;
    }
    const bounds = event.overlay_box;
    const panel = root.ownerDocument.createElement('div');
    Object.assign(panel.style, {position: 'absolute', left: bounds.x + 'px', top: bounds.y + 'px',
      width: bounds.width + 'px', height: bounds.height + 'px', overflow: 'hidden',
      background: '#1B2528', color: '#F5F3EE', opacity: '0', visibility: 'hidden',
      pointerEvents: 'none', fontFamily: 'Microsoft YaHei UI', fontWeight: '700',
      fontSize: (bounds.height * 0.48) + 'px', lineHeight: '1.2'});
    const labels = event.approved_visible_copy.map((copy, index) => {
      const label = root.ownerDocument.createElement('div');
      label.textContent = copy;
      Object.assign(label.style, {position: 'absolute', inset: '0', display: 'flex',
        alignItems: 'center', justifyContent: 'center', whiteSpace: 'nowrap',
        opacity: index === 0 ? '1' : '0', visibility: index === 0 ? 'visible' : 'hidden'});
      panel.appendChild(label);
      return label;
    });
    root.appendChild(panel);
    timeline.set(panel, {autoAlpha: 0}, 0);
    timeline.fromTo(panel, {autoAlpha: 0}, {autoAlpha: 1,
      duration: phases.entrance.end - phases.entrance.start, ease: 'power2.out', immediateRender: false}, phases.entrance.start);
    if (event.recipe_id === 'A03') {
      timeline.set(labels[0], {autoAlpha: 1}, 0);
      timeline.set(labels[1], {autoAlpha: 0}, 0);
      timeline.set(labels[0], {autoAlpha: 0}, event.evidence.after_at);
      timeline.set(labels[1], {autoAlpha: 1}, event.evidence.after_at);
    }
    timeline.fromTo(panel, {autoAlpha: 1}, {autoAlpha: 0,
      duration: phases.exit.end - phases.exit.start, ease: 'power2.in', immediateRender: false}, phases.exit.start);
    timeline.set(panel, {autoAlpha: 0}, phases.exit.end);
    return timeline;
  }
  const api = Object.freeze({mount: mount});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.MotionEditorialA = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
