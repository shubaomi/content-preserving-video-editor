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

## Platform covers

Cover ratio is a publishing decision separate from video ratio. For Douyin and WeChat Channels, default to a 9:16 cover, including for horizontal videos. Keep the face and title in a center-safe region so platform list/grid crops remain useful. Generate a separate 16:9 cover only when the platform or user specifically needs it.

For a personal creator, prefer an authorized real photo and a topic-specific cinematic poster. Preserve identity and verify the 9:16 thumbnail; do not stretch or center-crop a horizontal cover as a substitute.
