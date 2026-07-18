# Pre-Publish Content Safety

## Terminology and transcript accuracy

Build a project glossary from source filenames, visible UI text, product/repository names, profile vocabulary, and repeated transcript candidates. Preserve the raw ASR output, then apply traceable corrections. Flag uncertain person names, brands, URLs, commands, and technical terms; do not replace them with a confident-sounding guess.

Check captions against visible UI and narration at every chapter boundary. Store glossary corrections and their evidence.

## Visual and audio privacy

Scan the source and final timeline, not only transcript text. Review scene changes, OCR-rich frames, notifications, address bars, terminals, account menus, file pickers, and frames adjacent to cuts. Detect or manually inspect:

- emails, phone numbers, account IDs, addresses, and private messages;
- API keys, tokens, passwords, QR codes, cookies, and terminal secrets;
- personal filenames, browser history, bookmarks, and private tabs;
- unintended faces, voices, or copyrighted private material.

Blur, mask, replace, or remove only the necessary interval and document the reason. Never publish a frame merely because it appears for less than a second.

## Claims and demonstrations

Do not turn an observed demo into a broader unsupported claim. Keep product labels, performance statements, before/after comparisons, and generated cover hooks consistent with what the video actually shows.

## Asset rights

Record source, license/authorization basis, generation provider/model, and local frozen path for music, SFX, fonts, photos, screenshots, and generated images. Treat missing rights information as a release warning. User-owned photos and source recordings should be marked project-authorized, not assumed public-domain.
