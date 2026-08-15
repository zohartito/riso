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
| `style-flat-mosaic.png` | Dense interlocking flat regions, map-like, muted red/green/orange. No objects, no lettering, no shadows. Thin borders between regions. | `tennis` |
| `style-flat-planes.png` | Four large flat planes, cream/coral/yellow, soft curved boundaries. No objects, no borders, no shadows. | — (outline-free alternative, see the trade below) |
| `style-riso-poster.png` | Flat two-ink screenprint poster: teal/lilac blocks, cream ground, **one circle**. | — (retired 2026-08-15: the circle reproduced into output) |
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

## What a reference contributes, in the order it was learned

Every rule here cost a round of generation. Read this before minting a ref.

**1. Lettering.** The first poster ref carried a caption band and Redux
reproduced garbled text ("Terk, 2008") into every output. Cropped off.

**2. Any distinctive object, not just lettering.** The poster ref's single
white circle reappeared verbatim in Phase 3 output — a specific object, moved
across. Generalise: a reference contributes anything memorable in it. A good
ref is texture, palette and edge quality with **no memorable element**.

**3. Density transfers.** Measured over 10 seeds on one dense subject: a dense
reference (many small regions) produced crowds that fill the frame; a
four-plane reference produced the same subject compressed into a band with
most of the frame empty. The share of the frame taken by the single biggest
ink was identical at 59% for all three references tested — so density changes
what fills the frame, not how much of it is filled.

**4. Edge quality transfers, including borders.** `style-flat-mosaic.png` has
thin borders between its regions, and its output draws **thin dark outlines
around figures** — measured, not eyeballed: the darkest ink is 55.7% solid
under a 2px erosion in the Phase 4 crowd panel against 89–95% in every Phase 3
panel, i.e. the dark ink went from solid masses to line work. **This violates
the "no outlines" bullet in the look spec.** `style-flat-planes.png` has no
borders and does not do it — and produces weaker, emptier compositions. That
trade is unresolved and is a decision for Zohar, not for this file: switching
is one line in `styles/tennis.toml`.

**5. A sparse subject renders as the reference, whatever the reference is.**
"A tennis player mid-serve seen from the baseline" was run against four
different references and produced no subject at all in every case — the poster
ref's blocks, the planes ref's planes, the mosaic ref's regions, and with a
patchwork-of-squares ref a literal checkerboard. This is the strongest form of
the density rule below: it is not that sparse subjects render weakly, it is
that Redux fills unspecified space with the reference. A dense subject
suppresses the reference's motif; a sparse one hands the frame to it.

Consequence: a ref that is safe on dense subjects can still be unusable. The
patchwork-of-squares ref scored 10/10 legible crowds and was still rejected,
because the two sparse subjects came back as checkerboard. **Judge a candidate
reference on at least one dense and one sparse subject.**

## Hit rate (measured 2026-08-15, the number to quote)

Ten consecutive seeds, 1–10, one dense subject ("a crowd of tennis spectators
seen from behind"), shipped preset, no seed hunting:

- **0 of 10 dead frames**, and **10 of 10 legible crowds** on the mosaic ref.
- Ink coverage: 5 of 5 inks above 1% of the frame in 7 of 10.

That is the honest quality of this pipeline **on a dense subject**. It does not
generalise: the same measurement on a sparse subject is close to 0, per rule 5
above. Pick subjects accordingly.

### Prompts that minted these refs

- `style-riso-poster.png` — "risograph screenprint poster, two ink colours only,
  flat geometric shapes, no outlines, heavy visible paper grain, minimal
  editorial composition, misregistered ink" (seed 900, cropped to drop captions)
- `style-stained-glass.png` — "ornate art nouveau stained glass window, thick
  black leading between every pane, saturated jewel tones, decorative botanical
  pattern, backlit glow" (seed 901)
- `style-flat-mosaic.png` — "dense interlocking flat colour regions like a map,
  filling the sheet edge to edge, even distribution, flat matte ink printed
  directly on paper, no shadows, no depth, no highlights, no objects, no
  symbols, no lettering, uniform screenprint grain" (seed 33)
- `style-flat-planes.png` — "risograph poster background, broad flat colour
  areas of unequal size meeting at soft irregular edges" + the same negative
  clauses (seed 33, cropped to drop faint corner lettering)

Eighteen candidates were minted across four rounds to get two keepers. Most
were rejected on rule 2: circles, squares, grids, dots, torn-paper shadows.
Dense and object-free pull against each other — density wants many repeated
marks, and repeated marks are objects.
