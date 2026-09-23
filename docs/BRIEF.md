# riso — build brief

Spec of record. If context is cleared, re-read this file before doing anything.

---

## Phase 0 findings (already gathered 2026-08-15 — do not re-run these)

Probed from the Mac before the repo was scaffolded:

| check | result |
|---|---|
| `desktop-zt` on Tailscale | **online**, `100.65.251.41`, direct, active |
| `desktop-zt:8188` (ComfyUI) | **closed / refused** — host reachable, nothing listening |
| `desktop-zt:8000` | open (something else; not identified) |
| Mac `127.0.0.1:8188` | no response |
| launchd `com.zohar.comfyui-mac-krea` | loaded, `RunAtLoad=false`, no PID — never started |

**Known breakage — the Mac launchd job is pointed at a dead path.**
The plist runs:

```
/Users/zohartito/code/zohar-infra/mac/flux-krea-dev/run-comfyui-krea.sh   <- does not exist
```

The script actually lives at:

```
/Users/zohartito/projects/_local-only/zohar-infra-files--code/mac/flux-krea-dev/run-comfyui-krea.sh
```

It was swept into `_local-only` during the 2026-07-30 consolidation and the plist
was never updated. `WorkingDirectory` in the plist (`~/comfyui-mac`) is still valid.

Fixing that plist is **not** part of this repo's job — ask Zohar before editing
anything under `~/Library/LaunchAgents` or `_local-only`. For Phase 0 you may run
the script directly to get a ComfyUI instance up.

On the PC side: a refused connection on 8188 means either ComfyUI is not running
in WSL, or it is running but WSL2's NAT is not forwarding the port to the Windows
host (and therefore not to Tailscale). Diagnose which before reaching for a fix.

---

## Goal

Build an original editorial/risograph illustration system, using external work
only to study generic print mechanics rather than copy palettes, subjects or
compositions. The repeatable local pipeline has four entry lanes: semantic generation,
deterministic geometric composition, imported artwork, or palette-locked SVG from a
pluggable engine (Phase 10) → riso post-pass → export.
**Style consistency across a series is the whole point; one-off pretty images are
not the deliverable.**

## What the look is (mechanical spec — verify output against this)

- 3–5 flat colors, zero gradients except grain
- uniform heavy grain across the full frame (screenprint, not photo noise) —
  **2px tooth** at ~1024px (`grain(scale=2)`, the default). Per-pixel grain
  reads as sensor noise, which is the thing this bullet rules out; the earlier
  wording implied per-pixel and contradicted itself. Corrected 2026-08-15.
- no outlines; forms read by color adjacency only
- 1–2px RGB channel misregistration
- optional halftone on a duplicated luminance channel

## Two laws about driving the model — these are not about tennis

Both were paid for in generation time on this repo, and neither is specific to
it. If you are reading this before touching a prompt or a reference, read these
two things first. Measurements and workings are in `refs/srefs.md`.

**1. A negative cannot overrule the convention a noun carries. It can only trim
what survives once the noun agrees.**

The prompt said "flat editorial illustration" and every crowd came back in
heavy contour lines, because that phrase means vector line art. Adding "no
outlines, no linework" moved thin-line coverage from 3.64% to 3.75% — nothing.
Adding the *same clause* to "cut-paper collage" moved it from 1.79% to 0.94%.
Change the noun first; the negative only tidies up afterwards. Naming a paper
medium instead of an illustration medium took the same measure to 0.31%.

**2. Whatever the subject does not fill, the style reference fills.**

A sparse subject does not render weakly — it renders *as the reference*. The
same prompt against four different references produced no subject in all four:
the poster ref's blocks, the planes ref's planes, the mosaic ref's regions, and
from a patchwork-of-squares reference a literal checkerboard. Ask for torn
paper collage and the empty regions become torn paper.

Three consequences, all load-bearing: choose subjects that fill the frame
(see "Subject selection is part of the style" below); judge a candidate
reference on one dense **and** one sparse subject, never dense alone; and crop
to the subject, because the space it does not occupy is never neutral.

## Existing assets — do not re-clone or re-download

- ComfyUI on the PC (Tailscale host `desktop-zt`, RTX A6000 48 GB primary plus
  RTX 4070 Ti SUPER 16 GB since the 2026-08 rebuild):
  WSL at `~/code/comfyui` and `~/comfy/ComfyUI`
- ComfyUI on the Mac: `~/comfyui-mac`
- Weights already pulled: `flux-krea-dev`, `flux1-schnell-fp8`, `flux_text_encoders`
  — **that list describes the Mac, not the PC.** Corrected 2026-08-15 after
  querying `/object_info` on the PC box, which has `flux1-schnell-fp8` and
  nothing else. Do not pull krea-dev onto the PC.
- `~/projects/comfyui-ltx25` is a ComfyUI **fork** for video. Leave it alone.

---

## Phases

Each has a gate. Do not start a phase until the previous gate passes.

### Phase 0 — reachability

Get a ComfyUI instance answering. Prefer the PC (`desktop-zt:8188`); fall back to
the Mac only if the PC cannot be fixed in one pass — and say so explicitly rather
than switching silently. Record what you did in `docs/generation-box.md`.

**Gate:** a JSON response from `/system_stats` with GPU info, and the fix (or the
documented fallback) written down.

### Phase 1 — riso post-processor  ← BUILD THIS FIRST

Python + numpy + Pillow in `riso/post.py`. No Photoshop dependency, no GPU.

- `palette_lock(img, palette)` — nearest-color quantize to a 3–5 color palette
- `grain(img, amount, seed)` — monochromatic, uniform, seeded
- `halftone(img, angle, cell)` — on luminance
- `misregister(img, px)` — per-channel offset
- `compose()` — chains the above from a preset

Palettes are data, in `palettes/*.json`. Two starters are already there
(`tennis-felt`, `riso-nightsea`) — match that schema, do not hardcode colors.

**Gate:** pytest proving (a) same seed → byte-identical output, (b) `palette_lock`
output contains exactly N unique colors. Then run it on any existing image and show
Zohar before/after so he can judge it by eye.

### Phase 2 — ComfyUI style-reference workflow

`workflows/flux-redux-styleref.json` in ComfyUI **API** format (not the UI export).

Flux Redux is the local equivalent of Midjourney `--sref`: it carries style from a
reference image while the text prompt supplies subject and crop. Download only the
Redux adapter — the base Flux weights are already on disk.

**Corrected 2026-08-15:** Redux is two files, not one — the adapter
(`flux1-redux-dev.safetensors`) plus the SigLIP vision encoder it reads the
reference through (`sigclip_vision_patch14_384.safetensors`). Both approved.
The base model stays `flux1-schnell-fp8`: Redux supports schnell, 4 steps keep
iteration fast, and Apache-2.0 removes the non-commercial problem entirely.

**Gate:** two proofs, saved as image pairs in `docs/`:

- (a) same subject prompt + two different style refs → visibly **different** styles
- (b) same style ref + two different subjects → visibly **consistent** style

If (b) fails, the pipeline has no value. Say so rather than shipping it.

**Both proofs passed. Three corrections came out of reading them closely**
(2026-08-15, confirmed on both machines — the full record is in `refs/srefs.md`):

1. **A reference teaches rendering mode, not just style.** In proof (a) the
   stained-glass output is a photograph; the flat poster ref produced flat art.
   Only ever use FLAT style references. As load-bearing as the strength band.
2. **Raw Redux output does not meet the look spec.** Both proof (b) skies are
   smooth vertical ramps, and the spec allows zero gradients except grain. So
   `palette_lock` is load-bearing, not cosmetic.
3. **The reference palette does not transfer.** The ref is teal/lilac/mauve/
   cream; the outputs are blue and violet. Not one reference colour survived.
   Stop describing Redux output as carrying the palette — it carries "cool,
   few colours". Palette comes from `palettes/*.json` in the post-pass.

### Phase 3 — CLI

```
riso gen "a crowd of tennis spectators seen from behind" --style tennis --ar 3:4
```

Chains Phase 2 → Phase 1 → writes a PNG. Style presets (ref image + palette + post
settings) live in `styles/*.toml`, read with stdlib `tomllib`. Output to `out/`
(gitignored).

**Gate (tightened 2026-08-15, replacing "one command produces a finished
image"):** that command, from cold, produces one finished PNG — *and* three
different subjects run through the same preset land in one contact sheet in
`docs/`. The sheet is the deliverable: it is the first time both halves of this
repo are visible in one image, and it either reads as a coherent series or the
repo does not work yet.

**Passed.** `docs/phase3-contact-sheet.png`, three subjects, `tennis` preset,
seeds 8 / 55 / 21. Measured against the look spec rather than eyeballed:

| spec bullet | measurement |
|---|---|
| zero gradients except grain | flat areas vary by sd 2.07 levels; grain alone predicts 2.0. The ramp is gone. |
| 2px tooth | pixel differences inside a grain block 5–6, across a block boundary 21 |
| 1–2px channel misregistration | R-to-B offset 4px, i.e. ±2px per plate |
| no outlines | nothing in the chain draws one; forms read by colour adjacency and press fringe |
| 3–5 flat colours | 5 inks locked, then modulated by grain and halftone as the spec allows |

**Three findings the sheet also produced — Phase 4 material, not shipped:**

- **Subject fidelity falls off as the subject gets sparser.** The crowd panel
  is specific; the serve panel reads as "a figure with a racket"; the handshake
  panel does not read as two players at all. Dense subjects hold, sparse
  multi-figure interactions do not.
- **Composition bleeds from the reference.** The cream negative space and the
  navy block with a circle in panels 2 and 3 are the poster ref's composition,
  not the prompt's. At 0.08 that bleed is the price of flatness.
- **Chartreuse is nearly absent.** Equal-interval lightness bands over a
  bimodal histogram (dark figures, light ground) leave the middle bands empty,
  so the fifth ink shows only at edges. Within spec, but the palette is not
  fully exercised.

**Two failure modes worth knowing before Phase 4:**

- schnell returns a genuinely empty frame on some seed/subject pairs (2 of 15
  measured). `riso gen` now warns and names the seed instead of dressing up a
  dead frame; re-run with another seed.
- `palette_lock`'s default nearest-colour mapping collapses a generated frame
  onto one ink, because Redux output sits nowhere near any palette. Style
  presets set `palette_mode = "luma"`, which bands by lightness instead.

---

### Phase 4 — what the contact sheet taught

Scope was four items, set after reading the Phase 3 sheet. Result:
`docs/phase4-contact-sheet.png`, same three subjects, **seed 1 for all three,
no seed hunting**, so it is comparable to `docs/phase3-contact-sheet.png`.

**a) Quantile banding — built, measured, rejected.** Cutting the luma bands by
pixel population instead of lightness width was meant to recover the fifth ink.
Over 10 frames it raised coverage from 4.5 to 4.7 inks and broke the plates up
5× (2.2% → 11.0% of adjacent pixels landing on different inks): a near-flat
area is not perfectly flat, and equalising population shreds it into two-ink
mottle. Flat plates are the look. `luma` stays equal-width, and the reasoning
is in the docstring so nobody re-tries it blind.

**b) New object-free reference — done.** `style-flat-mosaic.png` replaces the
poster ref. The white circle is gone. Two new rules came out of minting it, both
in `refs/srefs.md`: a reference contributes any distinctive *object*, and — the
one that matters more — **a sparse subject renders as the reference, whatever
the reference is.** Four different refs, same sparse prompt, no subject in any
of them.

**c) Hit rate: 0 dead and 10 legible crowds out of 10 unhunted seeds** on a
dense subject. Five inks above 1% of frame in 7 of 10. On a sparse subject the
same measurement is close to zero.

**d) The sheet.** Panel 1 (crowd) is the best image this repo has made. Panel 3
(handshake) now reads as two hands, which it did not in Phase 3. Panel 2
(mid-serve) has no subject at all.

**What the sheet still gets wrong — read before Phase 5:**

- **The output has outlines and the look spec forbids them.** ~~The mosaic ref
  draws them.~~ **Corrected in Phase 5: the model draws them, not the
  reference** — the raw generation already contains contour lines with every
  reference tested, and the erosion measurement originally cited here does not
  detect outlines at all. Full retraction in `refs/srefs.md` rule 4, evidence
  in `docs/outlines-come-from-the-model.png`. Still unsolved.
- Panel 2 is a failure, and picking a different seed would not fix it.

### Phase 5a — the reference A/B, so the choice is between two visible things

`docs/phase5-planes-sheet.png` is `docs/phase4-contact-sheet.png` with one
variable changed: `style-flat-planes.png` instead of `style-flat-mosaic.png`.
Same three subjects, same seed 1, same preset, same post-pass. `tennis.toml`
was switched to generate it and switched straight back — **the preset still
ships the mosaic ref**, pending the call.

What the pair actually shows, panel by panel:

| | mosaic (phase 4) | planes (phase 5) |
|---|---|---|
| 1 crowd | dense, fills the lower half, chartreuse ground | sparser, more empty cream, pink ground |
| 2 serve | no subject | no subject |
| 3 handshake | reads as two hands | one figure, does not read |

**The decision is about density and composition, and nothing else.** Both
references outline identically, both fail the sparse subject identically, and
the biggest-ink share is 59% for both — so emptiness is the subject's, not the
reference's.

**Settled 2026-08-15: the mosaic ref stays, and this is not to be reopened.**
The only argument for the planes ref was outlines, and outlines turned out to
come from the model. On the axis that actually separates them the mosaic wins
two panels of three. `docs/phase5-planes-sheet.png` is kept as the record.

### Phase 5b — the outlines are fixed, by one phrase

`docs/outlines-fixed-by-the-medium-word.png`, and the sheet it produces is
`docs/phase5-outline-fix-sheet.png`.

The prompt said "flat editorial illustration", which in training data means
vector line art. Naming a paper medium instead — **"torn paper collage, matte
paper shapes"** — drops thin-dark-line coverage from 3.64% to 0.31%, against a
0.00–0.04% floor for genuinely line-free images. The look spec's "no outlines"
bullet is now met.

Three things learned that generalise past this repo:

- **Substitution beats deletion and negation.** A "no outlines" clause moved
  the number from 3.64% to 3.75%, i.e. not at all. The model does not take
  instruction not to draw something; it takes instruction to draw a different
  thing.
- **Validate a metric before you trust it.** The erosion measure that blamed
  the reference was never tested against a known-positive and a
  known-negative. Its replacement was, before it was used.
- **The fix is not free.** `docs/outline-fix-what-it-costs.png`: the paper
  wording draws smaller figures packed denser; the illustration wording drew
  larger, crisper ones. The spec decides it, but Zohar can overrule on sight.

### Phase 5c — crop, which is what makes the emptiness survivable

`docs/phase5-cropped-sheet.png` against `docs/phase5-outline-fix-sheet.png`:
same three subjects, same seed, one setting added.

`crop_keep = 0.71` in the preset means *deliver the densest 71% of the frame,
rescaled back to full size*. `post.content_crop` slides a target-sized window
and keeps the placement holding the most ink boundaries — large flat shapes
carry none, so the style reference always loses that competition to the
subject. The upscale afterwards costs nothing visible because `palette_lock`
re-quantises to flat plates, and grain lands at the delivered size, so the 2px
tooth stays 2px. `--ar 3:4` still delivers 3:4 at full resolution.

Subject share on the crowd goes 44.8% → 61.1%. Panels 1 and 3 are clearly
better; panel 2 is unchanged in kind, because a frame with no subject in it has
nothing to crop to.

**Generating larger and cropping back was tried first and is worse.** At 1.15×
and 1.35× Flux draws fewer, bigger figures, so a crowd stops being a crowd:
whole-frame subject share fell from 48.9% at native size to 37.9% and 27.6%.
Resolution bought that way costs the density that makes the look work.

### Subject selection is part of the style

Phase 4's clearest finding, and it belongs with the look spec rather than in a
phase note. **This aesthetic needs dense subjects.** Flat colour adjacency has
to describe form without outlines or shading, and it needs repeated elements to
do that — a crowd of caps, a field of waves, a bank of faces. That is what the
reference material (Ege Berkina, Gizem Akdag) is made of.

A lone figure on an empty court gives the pipeline nothing to work with, and
the empty space does not stay empty: Redux fills it with the reference. Choose
subjects that fill the frame with repeated elements. This is a property of the
aesthetic, not a defect to be fixed.

### Phase 6 — deterministic geometric-poster lane

The 2026-08-30 Gizem Akdag “Egypt exploration” source made the next boundary
clear: repeated figures, rays, folded fields, ripples and object-free mosaics
are composed geometry before they are image-generation problems. Flux should
not be asked to invent a sparse poster when five reproducible drawing systems
can construct it directly.

`riso motif` now renders five original families without ComfyUI:

- `crowd` — varied flat human glyphs in a repeatable field
- `rays` — uneven sectors around an off-centre void
- `peaks` — staggered folded pennants with negative space
- `ripples` — alternating contour bands with no landmark or horizon
- `mosaic` — balanced low-frequency organic regions

All use palette files rather than hardcoded colours, expose seed/density/aspect,
and run through the same grain and misregistration finish as `riso gen`. The
JSON receipt says `riso.motif` and explicitly records that no external model or
adapter was involved.

`riso stylize` is the complementary import lane: an existing sketch, render or
photo goes through luma palette separation and the press treatment. Its receipt
includes the source SHA-256 and keeps the source-rights warning explicit.

**Gate passed:** `docs/phase6-egypt-cobalt/06-proof-sheet.png` holds one calibration target plus
all five procedural families. The first rendering pass exposed escaped margins
and overfilled peaks/mosaics; the renderer was corrected and the final sheet was
visually inspected. Phase-completion suite: **100 passed**. The calibration target at
`docs/phase6-egypt-cobalt/00-calibration-target.png` was made with the built-in
image tool and is concept-only; it is not used by Redux or the procedural engine.
The folder is now explicitly marked internal-study-only and must not be used as
public post media.

### Phase 7 — original prompt-authored publication lane

`blueprint-coral` proves the intended creative split: the user's prompt supplies
the subject, viewpoint, organization and action; the preset supplies only a
generic block-print medium, an original three-ink palette, and an object-free
abstract reference generated by `riso.motif`.

`riso gen --show-prompt` exposes the exact concatenated prompt without starting
ComfyUI. Every live output records both `prompt` and `prompt_sent` in its sidecar.
The first four-image proof, `assets/2026-08-30-construction-choreography/`, uses
four architecture-specific prompts and no artist names, Egypt imagery, sampled
palette, or source composition. The PC generated all four live through Flux
schnell + Redux; each passed visual inspection and the PC was returned to its
prior state (ComfyUI inactive, idle-unload timer active).

**Gate passed:** four distinct architectural subjects rendered at 832×1280,
with exact receipts, clean metadata, and a reviewed contact sheet. The set stays
in `production` until Zohar approves the creative treatment. Redux's
Non-Commercial restriction remains attached. Current full suite: **105 passed**.

### Phase 8 — source-bound material-collage translation

The “Red and blue” reference added one useful generic mechanic: tactile pigment
sitting on physical material, framed as a monumental central silhouette. Its
actual subjects, stripe geometry, red/blue swatches and compositions are
excluded. `site-signals` translates the mechanism into survey equipment,
prefabricated facade cassettes, wind-testing scaffold and weather instruments,
using a new orange/violet/ink/paper palette and internal abstract reference.

The `site-signals` preset and prompt contract pass local tests. Live Flux/Redux
validation is **pending** because `desktop-zt` answered Tailscale ping but its
SSH port timed out twice; the Mac Comfy checkout has no model weights. Four
review images were still completed through a truthfully recorded fallback:
built-in image generation from the original prompts with no reference images,
followed by deterministic `riso stylize` post-processing.

**Review gate passed:** all four 1024×1536 finals and raws were visually
inspected; exact prompts, source hashes, post settings and final hashes are in
`assets/2026-08-30-site-signals/`. No private metadata or actual text appears.
Creative approval and live preset validation remain open. Current suite:
**107 passed**.

### Phase 9 — repetition becomes an architectural field

The Ege Berkina “Just another day in the crowd” reference contributes one
generic compositional mechanism: a dense repeated field becomes narrative when
one element breaks its rhythm. Its people, seats, phones, clothing, gestures,
green-dominant palette, signatures, and compositions are excluded.

`field-exceptions` assigns the repeated-field role to architectural assemblies:
sawtooth roof monitors interrupted by a rain court, balcony bays interrupted by
a shared terrace, structural columns crossed by an accessibility ramp, and a
grid of cistern covers redirected into a rain garden. A new rose/aqua/plum/
vellum palette and deterministic object-free reference keep the visible system
independent from the source.

The preset contract and prompt boundary pass locally. Live Flux/Redux visual
validation remains pending because `desktop-zt` answers Tailscale but Windows
SSH still times out. The review set therefore uses the same truthfully recorded
fallback as Phase 8: built-in image generation with no input image, followed by
deterministic `riso stylize`. Do not describe those fallback images as
`riso gen` or Redux output.

**Review gate passed:** four 1024×1536 raws and finals were visually inspected,
with exact prompts, raw/final hashes, source boundaries, post settings, and a
review contact sheet recorded in `assets/2026-08-31-field-exceptions/`.
Creative approval and live preset validation remain open. Current suite:
**109 passed**.

### Phase 10 — the vector lane

`riso vector` draws a style preset's subject as SVG instead of pixels. The style
still owns palette and press treatment; only the source of the drawing changes.
Engines: QuiverAI Arrow 2 / Arrow 2 Telos through Vercel AI Gateway (metered),
the subscription CLIs panel already drives (claude, codex, gemini, grok, kimi),
OmniSVG 1.1 open weights run locally (`~/projects/omnisvg`, MPS on the Mac), and
vtracer on an existing raster. Colour is decided in code: `flatten` removes
gradients, opacity, filters and embedded rasters, `lock_palette` snaps every
paint (attributes, inline styles, `<style>` sheets, the unset-black default) to
the palette, and anything unreadable fails the run instead of passing.

**Build gate passed (2026-09-22):** 158 tests; a Codex (gpt-5.6-sol) review's
findings — colours escaping the lock, a crash ending a bake-off, a key echoed in
an error — each fixed and pinned by a test.

First live bake-off, one subject (`blueprint-coral`, 2:3, seed 304):

| engine | result | seconds |
|---|---|---|
| claude (opus-5) | usable flat poster, 4/4 inks | 381 |
| codex (gpt-5.6-sol) | usable, most dimensional, 4/4 inks | 109 |
| gemini | usable, most finished composition, 4/4 inks | 195 |
| grok (4.6) | reply was malformed XML | — |
| kimi (k3) | usable, simplest, 4/4 inks | 310 |
| omnisvg (8B, Mac) | 5 paths, square canvas — not usable for scenes | 238 |
| trace (vtracer on the Phase 7 raw frame) | faithful, 117 paths | 0.5 |

**Series gate — not yet passed.** Before vector output counts as a series:
three subjects × the candidate engines on one contact sheet, judged the way
Phases 3–5 were, and one engine that holds the style on all three. Arrow 2 is
not in the bake-off yet: it needs an AI Gateway key, and Vercel releases its
free credit only after a card is added. Arrow output is also non-commercial on
QuiverAI's free tier.

## Deferred — do not build these now

SDXL + IP-Adapter, style LoRA training, an MCP server, a web UI, Docker, a job queue,
any Photoshop integration. Photoshop is the hand-finishing lane for hero images; the
automated path stays headless. If Phases 1–3 work, these get scoped separately.

## Constraints

- Python, PEP 8, f-strings, `pathlib`. venv is at `.venv`.
- Paths must work on macOS and Windows/WSL — this repo syncs between both via git.
- Prefer stdlib + numpy/Pillow. Justify any other dependency before adding it.
- Short README only. No docs that were not asked for.

## Licensing — put this in the README

Flux dev and Flux Krea-dev are **non-commercial**. Flux schnell is Apache-2.0.
Output from this repo may feed the @zohar_tito account, so flag which model
produced what.

## First step

Before writing code, state the plan: each phase paired with the command that
verifies it. Then start at Phase 0.
