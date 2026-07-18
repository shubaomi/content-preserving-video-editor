# BGM Provider Cascade

Resolve one instrumental music bed into a frozen local file. Provider differences stop at that boundary; the HyperFrames composition consumes only the normalized local asset and metadata.

## Order

1. Reuse an approved project or personal-profile BGM when its mood and license fit.
2. Retrieve from HeyGen after OAuth/API authorization preflight.
3. Generate with MiniMax `music-2.6` when a Token Plan or paid API key and matching host are configured.
4. Generate locally with MusicGen only after dependency/download preflight and consent.
5. Continue without BGM if every provider fails. BGM is optional and must never block the video.

Stop after the first usable asset. Do not spend quota on all providers during a normal run. Generate alternatives only when the user asks to compare or rejects the current track.

## HeyGen

- Prefer OAuth so usage follows the user's web subscription instead of an API wallet.
- Retrieve by concrete mood and function, not vague genre alone.
- Record plan, query, source duration, and local frozen path.
- Do not trust a provider volume default when the source video already contains speech; apply the project speech-bed volume.

## MiniMax

- Load `/minimax-multimodal-toolkit` and verify current official API documentation before integration because model names and quotas change.
- China host: `https://api.minimaxi.com`; global host: `https://api.minimax.io`.
- Token Plan Key and pay-as-you-go API Key are distinct. Never print either key.
- Prefer `music-2.6` with `is_instrumental: true`, a required concrete `prompt`, non-streaming output, 44.1 kHz or 48 kHz, and MP3/WAV.
- Download URL output immediately when used because signed URLs expire.
- Record model, host region, prompt, duration, and quota source without recording the secret.

## MusicGen

- Use only when cloud retrieval/generation is unavailable or rejected.
- Report the model download and expected CPU/GPU cost before installation.
- Generate a short seed and crossfade-loop it for long videos; do not generate the entire long-form duration when a seamless bed suffices.

## Normalize and mix

- Freeze the chosen track inside the video project and register provenance.
- Prepare a full-duration bed with clean fades and preferably crossfade-safe looping.
- Preview speech videos around `0.08–0.12` volume.
- Keep original audio at full priority and apply declared volume automation or export-time sidechain ducking.
- Make BGM independently hideable in Studio and configurable off without removing source files.
