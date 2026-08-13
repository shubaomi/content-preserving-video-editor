const RECIPE_COMPONENTS = {
  "PBM-01": "luminous-phrase-pulse",
  "PBM-02": "speaker-depth-phrase",
  "PBM-03": "gesture-echo",
  "PBM-04": "thought-contrast-planes",
  "PBM-05": "cinematic-camera-phrase",
  "PBM-06": "semantic-cutaway-window",
  "PBM-07": "luminous-chapter-bridge",
  "PBM-08": "emotional-resolution-bloom",
};

const PHASES = new Set(["entrance", "explain", "hold", "exit", "post_exit"]);

function requiredObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is required`);
  }
  return value;
}

function validateBinding(value, expectedKind, expectedAuthoritySha256, label, sourceWindow, outputWindow) {
  const binding = requiredObject(value, label);
  if (binding.kind !== expectedKind) throw new Error(`${label} kind is invalid`);
  if (!/^[0-9a-f]{64}$/.test(String(binding.authority_sha256 || "")) ||
      !/^[0-9a-f]{64}$/.test(String(binding.source_sha256 || ""))) {
    throw new Error(`${label} hashes are missing or malformed`);
  }
  if (binding.authority_sha256 !== expectedAuthoritySha256) {
    throw new Error(`${label} authority hash differs from compiler projection`);
  }
  if (!["current", "tracked", "visible"].includes(binding.status)) {
    throw new Error(`${label} status is not usable`);
  }
  if (["subject_track", "gesture_track"].includes(expectedKind) && binding.visible !== true) {
    throw new Error(`${label} is not visible`);
  }
  const authorityWindow = requiredObject(binding.window, `${label}.window`);
  const eventWindow = binding.time_domain === "source" ? sourceWindow :
    binding.time_domain === "output" ? outputWindow : null;
  requiredObject(eventWindow, `${label} event window`);
  const a0 = Number(authorityWindow.start_seconds); const a1 = Number(authorityWindow.end_seconds);
  const e0 = Number(eventWindow.start_seconds); const e1 = Number(eventWindow.end_seconds);
  if (![a0, a1, e0, e1].every(Number.isFinite) || a1 < e0 || a0 > e1) {
    throw new Error(`${label} is outside the event window`);
  }
  return binding;
}

function textNode(value, className) {
  const node = document.createElement("span");
  node.className = className;
  node.dataset.visibleCopy = "true";
  node.textContent = value;
  return node;
}

function svgPrimitive(className, gesturePoints = null) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("pbm-primitive", className);
  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", "50"); circle.setAttribute("cy", "50"); circle.setAttribute("r", "32");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  if (Array.isArray(gesturePoints) && gesturePoints.length >= 2) {
    const points = gesturePoints.map(([x, y]) => [
      Math.max(0, Math.min(100, Number(x) * 100)),
      Math.max(0, Math.min(100, Number(y) * 100)),
    ]);
    path.setAttribute("d", points.map((point, index) => `${index ? "L" : "M"}${point[0]} ${point[1]}`).join(" "));
    svg.dataset.gesturePointCount = String(points.length);
  } else {
    path.setAttribute("d", "M12 58 Q50 12 88 58");
  }
  svg.append(circle, path);
  return svg;
}

function addRecipeSpecificLayer(root, recipeId, bindings, authorityDigests, eventId, sourceWindow, outputWindow) {
  if (recipeId === "PBM-02") {
    const subject = validateBinding(bindings.subjectBinding, "subject_track", authorityDigests.subjectBinding, "PBM-02 subjectBinding", sourceWindow, outputWindow);
    root.dataset.subjectEvidenceId = String(subject.evidence_id || "");
    const halo = document.createElement("i");
    halo.className = "pbm-subject-depth";
    halo.dataset.subjectEvidenceId = String(subject.evidence_id || "");
    root.append(halo);
  }
  if (recipeId === "PBM-03") {
    const gesture = validateBinding(bindings.gestureBinding, "gesture_track", authorityDigests.gestureBinding, "PBM-03 gestureBinding", sourceWindow, outputWindow);
    if (!Array.isArray(gesture.points) || gesture.points.length < 2) {
      throw new Error("PBM-03 gestureBinding.points requires at least two points");
    }
    root.dataset.gestureEvidenceId = String(gesture.evidence_id || "");
    root.append(svgPrimitive("pbm-gesture-path", gesture.points));
  }
  if (recipeId === "PBM-04") {
    const relation = document.createElement("i");
    relation.className = "pbm-relation-axis";
    relation.dataset.relation = "concept-a-to-concept-b";
    root.append(relation);
  }
  if (recipeId === "PBM-05") {
    const subject = validateBinding(bindings.subjectBinding, "subject_track", authorityDigests.subjectBinding, "PBM-05 subjectBinding", sourceWindow, outputWindow);
    const sourceTargetId = String(bindings.sourceTargetId || "");
    if (!sourceTargetId) throw new Error("PBM-05 sourceTargetId is required");
    root.dataset.subjectEvidenceId = String(subject.evidence_id || "");
    root.dataset.sourceTargetId = sourceTargetId;
    const frame = document.createElement("i");
    frame.className = "pbm-camera-frame";
    frame.dataset.sourceTargetId = sourceTargetId;
    root.append(frame);
  }
  if (recipeId === "PBM-06") {
    const asset = requiredObject(bindings.assetRef, "PBM-06 assetRef");
    const assetUrl = String(
      (window.location.protocol === "file:" && bindings.assetRuntimeUrl) ||
      bindings.assetUrl || asset.url || ""
    );
    if (!assetUrl || !/^[0-9a-f]{64}$/.test(String(asset.sha256 || ""))) {
      throw new Error("PBM-06 requires assetUrl and a valid asset hash");
    }
    if (asset.sha256 !== authorityDigests.assetRef) {
      throw new Error("PBM-06 asset hash differs from compiler projection");
    }
    const image = document.createElement("img");
    image.className = "pbm-semantic-asset";
    image.src = assetUrl;
    image.alt = "";
    image.dataset.assetSha256 = String(asset.sha256);
    root.append(image);
  }
  if (recipeId === "PBM-07") {
    const boundary = validateBinding(bindings.chapterBoundaryBinding, "chapter_boundary", authorityDigests.chapterBoundaryBinding, "PBM-07 chapterBoundaryBinding", sourceWindow, outputWindow);
    root.dataset.chapterBoundaryEvidenceId = String(boundary.evidence_id || "");
    const bridge = document.createElement("i");
    bridge.className = "pbm-chapter-bridge-line";
    root.append(bridge);
  }
  if (recipeId === "PBM-08") {
    const bloom = document.createElement("i");
    bloom.className = "pbm-resolution-bloom";
    root.append(bloom);
  }
  root.dataset.recipeSemantics = `${recipeId}:${eventId}`;
}

export function createPortraitMotion({
  recipeId, eventId, visibleCopy, supportingLayers = [], bindings = {},
  expectedBindings = {}, authorityDigests = {}, sourceWindow, outputWindow,
}) {
  if (!RECIPE_COMPONENTS[recipeId]) throw new Error(`Unknown portrait recipe: ${recipeId}`);
  if (!eventId) throw new Error("eventId is required");
  if (!Array.isArray(visibleCopy) || visibleCopy.length === 0) throw new Error("visibleCopy is required");
  if (JSON.stringify(bindings) !== JSON.stringify(expectedBindings)) {
    throw new Error(`${recipeId} runtime bindings differ from compiler authority`);
  }
  const root = document.createElement("section");
  root.className = `annotation pbm-event pbm-${RECIPE_COMPONENTS[recipeId]}`;
  root.id = eventId;
  root.dataset.eventId = eventId;
  root.dataset.portraitRecipeId = recipeId;
  root.dataset.phase = "post_exit";
  root.dataset.reducedMotion = "opacity-weight-focus-only";
  root.dataset.supportingLayers = supportingLayers.join(",");
  root.setAttribute("aria-label", visibleCopy.join(" / "));
  if (recipeId !== "PBM-03") root.append(svgPrimitive("pbm-orbit-trace"));
  root.querySelector(".pbm-primitive")?.setAttribute("id", `${eventId}-primitive`);
  const copy = document.createElement("div");
  copy.className = "pbm-copy";
  copy.id = `${eventId}-copy`;
  copy.dataset.pbmPrimary = "true";
  visibleCopy.forEach((value, index) => copy.append(textNode(value, `pbm-copy-${index + 1}`)));
  root.append(copy);
  const beam = document.createElement("i");
  beam.className = "pbm-focus-beam";
  beam.id = `${eventId}-beam`;
  beam.setAttribute("aria-hidden", "true");
  root.append(beam);
  addRecipeSpecificLayer(root, recipeId, bindings, authorityDigests, eventId, sourceWindow, outputWindow);
  return root;
}

export function applyPortraitPhase(node, phase, progress = 1) {
  if (!node || !PHASES.has(phase)) throw new Error(`Unsupported portrait phase: ${phase}`);
  const clamped = Math.max(0, Math.min(1, Number(progress)));
  node.dataset.phase = phase;
  node.style.setProperty("--pbm-progress", String(clamped));
  node.style.opacity = phase === "post_exit" ? "0" : "1";
  node.style.display = phase === "post_exit" ? "none" : "block";
  if (node.dataset.portraitRecipeId === "PBM-05") {
    const source = document.getElementById(node.dataset.sourceTargetId || "");
    if (source) {
      source.style.transformOrigin = "50% 40%";
      source.style.transform = phase === "post_exit" ? "" : `scale(${1 + clamped * 0.035}) translateY(${-clamped * 0.8}%)`;
      source.dataset.pbmCameraActive = phase === "post_exit" ? "false" : "true";
    }
  }
  return node;
}

export function visibleCopyManifest(node) {
  return [...node.querySelectorAll("[data-visible-copy]")].map((item) => item.textContent || "");
}

export const portraitRecipeComponents = Object.freeze({...RECIPE_COMPONENTS});

if (typeof window !== "undefined") {
  window.PortraitBrandMotionV2 = Object.freeze({
    createPortraitMotion, applyPortraitPhase, visibleCopyManifest,
    recipeComponents: portraitRecipeComponents,
  });
}
