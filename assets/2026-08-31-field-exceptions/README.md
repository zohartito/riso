# Field Exceptions — review set

**Status:** `review` — source boundary and technical checks passed; Zohar has
not yet selected or approved a direction. Nothing was posted or staged.

## Review the four directions

1. `01-roof-rain-court.png` — strongest overall composition and clearest
   field-versus-exception reading.
2. `02-balcony-commons.png` — strongest social architecture idea; the shared
   terrace interrupts a repetitive private facade.
3. `03-ramp-column-field.png` — most spatial and architectural; the ramp acts
   as a continuous counter-rhythm through the frame.
4. `04-rain-garden-grid.png` — most plan-like and diagrammatic; water redirects
   a rigid utility grid into one ecological collector.

`contact-sheet.png` is for review only. Use the four individual PNGs for any
future post or design development.

## Why this is independent work

The linked “Just another day in the crowd” post was inspected outside the
generation workflow. Only generic mechanics were retained: edge-to-edge
repetition, compressed depth, overlapping silhouettes, and one deviation that
changes how the whole field reads.

The new work changes every creative layer:

- roof monitors, balcony bays, columns, ramps, cistern covers, and drainage
  replace the source's commuters and auditorium seating;
- rain court, communal terrace, accessibility ramp, and rain garden replace
  the source actions, gestures, expressions, and compositions;
- rose, aqua, plum, and warm vellum replace its green-dominant palette;
- an internally generated object-free motif replaces the external imagery as
  the provisional preset reference;
- no source image or artist name entered any image-generation call.

This supports an independent-process claim, not a legal guarantee of exclusive
copyright.

## Actual production route

The PC answered Tailscale ping but Windows SSH timed out. To avoid describing
an untested Flux preset as live, this review set used a fully recorded fallback:

```text
four original architecture prompts
        ↓
OpenAI built-in image generation, no reference images
        ↓
riso stylize --palette rose-aqua-field --grain 0.09 --misregister 1
        ↓
four final 1024×1536 PNGs + source hashes + seeded post receipts
```

The exact built-in prompts and raw hashes are in `prompt-receipts.json`. Each
finished PNG has a same-named JSON file containing its raw source hash, palette,
seed, and deterministic post settings. Raw files remain under `raw/`.

The `field-exceptions` Flux/Redux preset is implemented for future PC testing,
but it did **not** produce these four review images. Its live visual gate remains
pending.

## Verification

- visually inspected every raw and final at full resolution;
- no source-specific person, seat, phone, gesture, expression, signature, or
  copied composition appears;
- four 1024×1536 RGB PNGs with no private metadata;
- OCR detected no text;
- final, raw, contact-sheet, and internal-reference hashes match
  `manifest.json`;
- repository tests, compilation, JSON parsing, and diff checks pass.

Built-in image-generation terms apply to the raw source images. `riso stylize`
is deterministic post-processing and does not alter the upstream rights
boundary. Flux Redux's non-commercial restriction does not apply to these four
fallback outputs because Redux was not used.
