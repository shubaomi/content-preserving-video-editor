# Sonic Language v2

Status: proposed; no audio assets are approved by this document.

## 1. Intent

The sonic system should make motion feel physical and coherent without turning
the talking head into a trailer or masking the speaker. It extends the existing
100% audio-decision model; it does not require a cue on every event.

## 2. Signature envelope

The HongRun signature follows the same temporal idea as the visual primitive:

1. **pulse** — a short idea onset;
2. **orbit** — one or two internal notes/noise movements;
3. **focus** — a soft tonal landing or short tail.

Motifs may omit one stage for micro events. The common envelope creates identity
while pitch, duration, timbre, and spatial motion provide variety.

## 3. Initial motif families

| ID | Family | Typical duration | Use | Avoid |
|---|---|---:|---|---|
| PBM-S01 | crystal pulse | 0.45–1.0s | PBM-01 word/idea landing | sharp notification-like ping |
| PBM-S02 | orbit sweep | 0.7–1.6s | PBM-02/03 path, gesture, depth movement | loud broadband whoosh |
| PBM-S03 | contrast dyad | 0.8–1.8s | PBM-04 two-part relation | comic error/correct buzzer |
| PBM-S04 | chapter lift | 1.0–2.2s | PBM-05/07 chapter or camera transition | repeated trailer riser |
| PBM-S05 | warm resolve | 1.2–2.2s | PBM-08 emotional conclusion | sentimental stock jingle |

Each family needs at least two perceptually distinct, licensed variants before it
can claim production readiness. Variants share the signature envelope but must
not be transposed copies masquerading as variety.

## 4. Decision contract

Every selected visual event records one of:

- `cue`: one primary motif plus optional restrained layer tied to named phases;
- `intentionally_silent`: an event-specific reason such as emotional quiet,
  speech density, existing source sound, or repeated sonic pressure.

A cue records event/recipe IDs, family/variant, asset path and SHA-256, rights,
visual and word landing times, phase mapping, duration, gain, measured onset,
decoded-PCM fingerprint, dialogue-relative audibility, and final true peak.

## 5. Speech-safe mixing

- Voice remains dominant at all times.
- Audibility is measured from the actual mixed review bytes, not nominal gain.
- Dialogue-relative cue level uses short windows around the cue; a cue that is
  inaudible is not fixed by blindly raising all SFX.
- Avoid heavy energy in the main speech presence band; prefer short spectral
  gaps, spatial motion, and controlled tail.
- One primary motif per visual beat. Multiple layers must form one perceptual
  event rather than simultaneous unrelated sounds.
- Maintain safe post-AAC true peak under the existing delivery gate.

## 6. Rhythm binding

- Word emphasis lands within 80ms of the approved word/phrase boundary unless a
  recipe declares an anticipatory lead with evidence.
- Gesture echo lands within 120ms of the verified gesture apex.
- Chapter lift may lead the visual transition by up to 180ms and must settle with
  the first stable next-chapter frame.
- Audio decisions use the same energy map as motion; a quiet chapter cannot be
  made high energy only by sound.

These values are proposed test tolerances for the implementation phase and must
be validated on actual playback before production promotion.

## 7. Review

Each Style Reel exposes:

- voice only / SFX off;
- SFX on;
- optional BGM off/on if an authorized BGM exists;
- an event timeline showing motif family, landing, and reason;
- loudness/onset measurements from exact review bytes.

Automated checks may prove decodability, identity, onset, masking, and true peak.
Multimodal review may reject a mismatch. HongRun decides whether the sonic
identity feels appropriate and reusable.

## 8. Rights and generation

- Local designed assets are preferred and must carry source/project provenance.
- Generated or external SFX require provider, plan/cost, license, result, and
  output-hash evidence under the existing governance chain.
- No Jianying/CapCut sound may be extracted or imitated from a proprietary
  template.
- Missing authorized assets yields `unavailable` or a silent/fallback decision,
  never a fabricated cue.
