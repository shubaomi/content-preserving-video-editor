# Acceptance matrix

| Gate | Automated evidence | Human/NLE evidence | Blocks |
|---|---|---|---|
| Package integrity | Exact complete nested inventory, hashes, no extra files | — | Package pass |
| Safe output | Root/child Junction, symlink, traversal, interrupted-write tests | — | Any materialization |
| Standard repair kit | Distinct automatic/pre-caption paths with current hashes; exact SRT/ASS/style-plan copies; current HyperFrames inventory; no native-draft claim | Import in any chosen professional editor when needed | Normal full delivery |
| Clean A-roll | Full decode, exact EDL duration/cuts, speech retained, no burned Director caption/motion signature | Visual spot check | Package pass |
| Captions | Current SRT exact; emphasis plan exact word/span/time binding; ASS deterministic | Import SRT and edit one block in Jianying Desktop | Compatibility promotion |
| Event motion | Decode, alpha channel/coverage, exact event window, black/white/busy composite | Import, place at offset, hide/trim one event | Jianying profile pass |
| Full overlay | Zero origin, exact full duration, sparse alpha, recomposition parity | Drag to zero and compare | Optional convenience layer pass |
| Audio stems | Decode, 48 kHz, duration/alignment, plan/cue identity, recomposition loudness/peak | Mute BGM and one SFX without affecting dialogue | Audio editability pass |
| IP assets | Current source/hash/rights/profile binding, transparent image decode | Reposition or remove one IP asset | IP package pass |
| Outro | Text-free overlay, icons, copy/timing, stem inventory, reference parity | Change CTA copy and remove one icon/SFX | Outro editability pass |
| Timeline | EDL/OTIO round-trip, rational time, exact clip/marker inventory | Follow import guide without guessing offsets | Package usability pass |
| Alpha compatibility | Candidate codec and PNG fallback technical QA | Current Jianying Desktop import, transparency, frame/duration check | Codec promotion |
| Returned final | Existing full decode, captions, audio, visual, final-edit-correctness, aesthetic/platform QA | User confirms intended manual changes | Delivery completion |

## Required negative tests

- missing/extra/stale nested file;
- package root or any child replaced by Windows Junction;
- unavailable row with fabricated hash;
- standard H.264 MP4 labeled as alpha;
- alpha file with opaque/empty channel;
- event overlay with wrong timeline offset or semantic ID;
- clean A-roll containing burned caption/motion;
- SRT/semantic-emphasis plan text or timing drift;
- IP/font asset without redistribution rights;
- outro alpha layer with baked editable copy but marked native-editable;
- audio stem with wrong cue, gain, onset, duration, or sample rate;
- failed format import still described as Jianying-compatible;
- human-return file reusing automatic-master path;
- package generation attempted while feature is disabled.

## Canary sequence

1. `fixture`: 10–15 second synthetic package proving schema, paths, alpha, stems,
   captions, IP/outro assembly, and deterministic recomposition.
2. `real_short`: 45–60 second HongRun portrait product sample using the current
   approved source and existing evidence; no full-video render.
3. `jianying_desktop`: manual import on the user's installed current version;
   record file support, alpha behavior, subtitle editability, alignment, relink
   friction, and time to make five representative edits.
4. `returned_short`: export the adjusted sample and run the complete return QA.
5. Only then consider `fixture_validated`/`real_project_validated` promotion for
   the named package profile. Production default remains separately gated.

## Five human edit tasks

- correct one subtitle segment and change its emphasis styling;
- move or remove one event motion overlay;
- mute one SFX while preserving dialogue;
- reposition/remove one personal-IP illustration;
- change outro CTA copy and hide one CTA icon.

The canary passes usability only when the user can complete these without
re-rendering the full HyperFrames project and judges the handoff worthwhile.
