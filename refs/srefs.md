# Style reference ledger

Two kinds of reference live here. Log both — a style you cannot reproduce
next month is not a style.

## Midjourney sref codes

| code | look | `--sw` that worked | seen on |
|---|---|---|---|
| | | | |

## Local reference images

Drop the image in this folder and log it. These are committed on purpose —
they are the style identity, not scratch files.

| file | look | used by style preset |
|---|---|---|
| `style-riso-poster.png` | Flat two-ink screenprint poster: teal/lilac blocks, cream ground, one circle. No outlines, no depth. | `tennis` |
| `style-stained-glass.png` | Art nouveau stained glass: heavy black leading, jewel tones, dense botanical pattern, backlit. Deliberately the opposite of the poster. | — (Phase 2 proof ref; **never** use as a live ref, see below) |

Both were generated locally on 2026-08-15 with `flux1-schnell-fp8` (Apache-2.0)
rather than scraped, so they are licence-clean and reproducible. Prompts are in
the Phase 2 record below.

## What Redux actually does with these

Measured 2026-08-15, `flux1-redux-dev` + `sigclip_vision_patch14_384` on
`flux1-schnell-fp8`, 4 steps, seed 4242, subject "a crowd of tennis spectators
seen from behind".

| `strength` (`multiply`) | result |
|---|---|
| 1.0 / 0.8 / 0.5 / 0.3 | Reference reproduced. Subject **gone** — the prompt contributes nothing. |
| 0.20 | Subject reduced to a silhouette strip; style dominates. |
| **0.10** | **Balance.** Subject reads clearly, style carries palette and flatness. |
| 0.05 | Subject dominant, style only tints the palette. |

`attn_bias` behaves the same way on the same scale — 0.1 works, 0.3+ swallows
the subject. There is no advantage either way at these values, so the workflow
stays on `multiply`.

**The lesson: Redux's usable band is 0.05–0.15, not the 0.0–10.0 the node
advertises.** Anything at or above the node's 1.0 default is a style *copier*,
not a style *reference*. Per-style overrides belong in `styles/*.toml`.

## A reference teaches rendering mode — so only ever use FLAT references

Read off proof (a), where one subject ran against both refs at 0.10. The
stained-glass output is a **photograph**: real faces, depth of field,
photographic light, tinted dark red. The riso-poster output is genuinely flat
and silhouetted. Same strength, same subject, same seed — the difference is
that one reference is dimensional and the other is not.

So the reference does not merely tint the palette. It decides whether the base
model renders flat or falls back to photoreal, and a dimensional reference
hands that decision back to the base model. **A style ref for this pipeline
must be flat.** This is as load-bearing as the strength band above it.

Two things a reference does *not* carry, also measured:

- **Not the palette.** The poster ref is teal/lilac/mauve/cream; its outputs
  are blue and violet. Not one reference colour survived. Redux carries "cool,
  few colours" — the palette comes from `palettes/*.json` in the post-pass.
- **Not flatness in the literal sense.** Raw output renders smooth vertical
  ramps in open sky. `palette_lock` is what makes the zero-gradients rule true,
  which is why it is not optional in a style preset.

## Strength and the prompt are one setting, not two (Phase 3, 6 seeds each)

| setting | result |
|---|---|
| 0.10, prompt = subject only | Flat, but the composition collapses on some seeds — 896×1152 seed 436484879 returned three empty colour bands, no subject at all. |
| 0.06, prompt = subject only | Subject sharp and specific — and **photoreal**. Real faces, gradient skies. Below the band the ref stops holding rendering mode. |
| **0.08, prompt carries "flat … no gradients"** | **Subject legible on all 6 seeds, flat on all 6.** What `tennis` ships. |

The reference cannot carry both flatness and subject clarity at one strength.
Say "flat" in words as well, and the strength is free to sit low enough for the
subject to survive. That is what `prompt_suffix` in a style preset is for.

Steps were swept too: 8 steps looks identical to 4 on schnell. Stay at 4.

Keep captions and lettering out of a reference image. The first poster ref was
generated with a caption band and Redux dutifully reproduced garbled text
("Terk, 2008") into every output; the band was cropped off before the proofs.

### Prompts that minted these refs

- `style-riso-poster.png` — "risograph screenprint poster, two ink colours only,
  flat geometric shapes, no outlines, heavy visible paper grain, minimal
  editorial composition, misregistered ink" (seed 900, cropped to drop captions)
- `style-stained-glass.png` — "ornate art nouveau stained glass window, thick
  black leading between every pane, saturated jewel tones, decorative botanical
  pattern, backlit glow" (seed 901)
