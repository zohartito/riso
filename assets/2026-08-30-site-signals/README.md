# Site signals — review set

**Status:** `review` — source boundary and technical checks passed; Zohar has
not yet selected or approved a direction. Nothing was posted or staged.

## Review the four directions

1. `01-survey-ramp.png` — clearest narrative and strongest architectural
   section-like movement.
2. `02-facade-cassettes.png` — strongest repeatable system and material
   inventory.
3. `03-wind-scaffold.png` — most kinetic; mesh and ribbons make wind visible.
4. `04-weather-array.png` — most technical and closest to field-instrument
   architecture.

`contact-sheet.png` is for review only. Use the four individual PNGs for any
future post or design development.

## Why this is independent work

The linked “Red and blue” post was inspected outside the generation workflow.
Only generic mechanics were retained: tactile pigment on physical materials, a
monumental silhouette, and a saturated limited palette.

The new work changes every creative layer:

- architecture field equipment replaces people, animals, camel/pyramids and
  landscape;
- survey ramp, fabrication inventory, wind scaffold and weather array replace
  the source compositions;
- safety orange, signal violet, deep ink and warm paper replace the source
  swatches;
- irregular inspection patches, instruments, mesh and construction geometry
  replace its stripe language;
- no source image or artist name entered any image-generation call.

This supports an independent-process claim, not a legal guarantee of exclusive
copyright.

## Actual production route

The PC answered Tailscale ping but Windows SSH timed out twice, and the Mac
Comfy install has no usable model weights. To avoid pretending the new Flux
preset had run, this review set used a fully recorded fallback:

```text
four original architecture prompts
        ↓
OpenAI built-in image generation, no reference images
        ↓
riso stylize --palette signal-violet --grain 0.09 --misregister 1
        ↓
four final 1024×1536 PNGs + source hashes + seeded post receipts
```

The exact built-in prompts and raw hashes are in `prompt-receipts.json`. Each
finished PNG has a same-named JSON file with its raw source, SHA-256, palette,
seed and post settings. The raw files remain under `raw/` for visual comparison.

The `site-signals` Flux/Redux preset is implemented separately for future PC
testing, but it did **not** produce these four review images. Its live visual
gate remains pending.

## Verification

- visually inspected every raw and final at full resolution;
- no source-specific person, animal, pyramid, camel, mountain or copied
  composition appears;
- 1024×1536 PNGs with no private metadata;
- OCR found no actual text; a few texture marks produced false-positive glyphs;
- final hashes match `manifest.json`;
- repository suite: 107 tests passed; compile and diff checks clean.

Built-in image-generation terms apply to the raw source images. `riso stylize`
is deterministic post-processing and does not alter the upstream rights
boundary. Flux Redux's non-commercial restriction does not apply to these four
fallback outputs because Redux was not used.
