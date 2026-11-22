# Adaptive Aspect and Layout

## Detect effective orientation

Read encoded width and height plus rotation metadata. Swap the display dimensions when rotation is 90 or 270 degrees. Classify the effective ratio:

- portrait: width / height below 0.85;
- square or near-square: 0.85 through 1.20;
- landscape: above 1.20.

Store encoded dimensions, display dimensions, rotation, exact ratio, orientation, and chosen canvas in project metadata. Do not infer orientation from the filename or recording type.

## Choose the video canvas

- Preserve the source display orientation by default.
- Use 9:16 for portrait sources, 16:9 for landscape sources, and 1:1 for square sources unless the user requests another delivery format.
- When the source ratio differs from the standard canvas, prefer contain, designed padding, or a blurred/graphic extension. Do not crop faces, UI controls, or meaningful content merely to fill the frame.
- For mixed-orientation sources, choose the dominant narrative orientation and adapt the minority clips with a designed frame; record the decision.

## Adapt every generated layer

Generate topic images, diagrams, intro/outro art, callouts, and HyperFrames compositions for the chosen video canvas. Do not generate 16:9 assets first and crop them blindly into 9:16.

- Landscape: favor side panels, left/right callouts, wide process paths, and bottom-center captions.
- Portrait: favor stacked cards, top/bottom reveals, vertical process paths, smaller picture-in-picture, and center-safe typography.
- Square: favor centered hierarchy, compact radial or stacked diagrams, and conservative edge use.

Use face-, pointer-, and UI-aware safe zones from sampled frames. Captions normally occupy the lower safe band but move when they would cover a face, keyboard action, or critical control. Validate at the beginning, middle, and end of every layout family.

## Mobile playback review

For a shared mobile master, design for the usable area common to the target players, not just the encoded 9:16 frame. Map the visible video edges separately from UI drawn over the picture. In Douyin inspect the top search bar, right action rail, lower description and collection entry; in WeChat Channels inspect playback controls, author notice, collection card, description and bottom actions. These are examples of variable UI, not fixed pixel masks. Owner and viewer views may differ even on the same device.

Keep full caption glyphs, essential labels, faces in speaking shots and the action the audience must see inside the usable area. Full-bleed scenery can stay full-bleed. Move the caption band or split at a semantic boundary before shrinking type; recheck it does not now cover the action. Reposition or omit a repeated decorative byline before shrinking all artwork. Cover edits cannot repair playback occlusion.

At sample review and before delivery, compare the actual encoded frame with controls visible at phone size: include the longest caption, an edge title and a key action. Use the same output time when comparing scenes. For each target log device/viewport, viewer or owner view, visible UI (including collection when relevant), affected element and result. If two device captures exist, inspect both; do not transfer one phone's pass to the other. A clipped word or obscured key action fails that view; a footer collision is a warning unless that text is required. Different timestamps can establish a fixed-label collision but not a missing scene element. Report simulated overlay checks separately from observed device checks; missing captures remain unverified, not an instruction to upload. Try a short layout-only proof before a full rerender; prefer one common layout unless conflicting verified constraints require variants.

### Feed navigation and stacked interviews

- Include the actual entry surface, not only a generic search/toolbar mask: back/avatar, feed tabs, feed-mode selector and their icons can occupy the same row as a burned-in series label. Review the opening and the longest recurring header with that row visible. A chapter title clearing navigation does not clear the smaller line above it. If identifying text matters, move it into the verified content area or introduce it once beside the subject; if redundant, omit it. A partially hidden permanent label is not a finished layout. Do not push the whole composition down into the caption or description zone.
- Give each text band a distinct job. Read a phone-size frame in order: main question, speaker or evidence, spoken caption. If an eyebrow, a second question/card and a decorative rule add no information beyond the title or speech, combine or remove them before making text smaller. Keep a card that actually explains a distinction. For a concrete example, consider one timely authorized visual or a clearly marked diagram instead of repeating the speaker's noun as a label. Preserve useful breathing room and existing safe caption placement; empty space alone is not a defect.
- Accept each observed view separately: all retained header words clear the top overlay; a long caption stays readable clear of side controls and lower metadata; the speaking face and necessary action stay visible. Distinguish a confirmed overlap from an editorial improvement. Match each field screenshot to its own exported caption/scene before blaming the upload, crop, compression or source camera; stills cannot establish pacing, sound or retention. Record only generalized findings in shared guidance, not private screenshots or account names.

## Platform covers

For a normal single-episode handoff targeting **WeChat Channels and Douyin**, deliver two cover files for three slots: one **3:4 portrait** shared by WeChat Channels and Douyin, and one **4:3 landscape** for Douyin. Point both portrait entries in the posting guide to the same file. Do not generate a spare 1:1 or 9:16 cover unless explicitly requested or required by an actual upload slot. This is a delivery default, not a platform restriction; honor different project or slot requirements. It does not change the video canvas or replace a collection cover.

Recompose the selected design for each delivered ratio; check the title and key action at thumbnail size. When using an authorized personal portrait, preserve identity in both layouts. Do not stretch one export to fill the other.
