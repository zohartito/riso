# Egypt-cobalt Phase 6 image manifest

> **Internal study only — do not publish as Zohar's finished work.** This set
> was built while analyzing an external artist reference and remains too close
> to that source's palette and motif vocabulary for a public authorship claim.
> It is retained as a transparent development receipt, not as post media.

This folder is the durable record of the 2026-08-30 cobalt geometric-poster run.
It contains every image created for the run and the settings needed to reproduce
the five images that came from `riso`.

## What is in the folder

| file | how it was made | prompt? |
|---|---|---|
| `00-calibration-target.png` | OpenAI built-in image tool using the four linked images as broad visual references | Yes — exact prompt below and in `00-calibration-target.json` |
| `01-crowd.png` | local `riso.motif` geometry → grain/misregistration | No |
| `02-rays.png` | local `riso.motif` geometry → grain/misregistration | No |
| `03-peaks.png` | local `riso.motif` geometry → grain/misregistration | No |
| `04-ripples.png` | local `riso.motif` geometry → grain/misregistration | No |
| `05-mosaic.png` | local `riso.motif` geometry → grain/misregistration | No |
| `06-proof-sheet.png` | Pillow contact sheet of the six images above | No |

The five numbered motif images each have a same-named JSON receipt containing
the motif, seed, density, palette, size, grain and misregistration. The working
copies also remain under `out/egypt-cobalt-proof/`, but `out/` is gitignored;
this folder is the durable reviewed set.

The original artist images are not stored here and are not consumed by the
procedural renderer. Source link:
<https://x.com/gizakdag/status/2094027774134554666>

## The only AI image prompt in this run

```text
Use case: stylized-concept
Asset type: calibration target for a local procedural print-illustration system
Primary request: create one original, object-free portrait-format abstract print reference that captures only the broad production qualities of the supplied images, not their compositions or motifs
Style/medium: flat two-ink block print on warm paper; large adjacent matte paper-like shapes; uniform coarse pigment tooth; subtle handmade edge irregularity; no modeled lighting, no gradients, no outlines
Composition/framing: dense all-over arrangement of irregular interlocking rounded and angular regions, balanced across a 2:3 portrait page with a narrow paper margin; no central icon or focal object
Color palette: deep cobalt blue ink, warm sand ink, off-white paper only
Constraints: entirely original; no people, no pyramids, no sarcophagus, no moon, no water, no radiating rays, no repeated stripes, no text, no lettering, no symbols, no recognizable objects; avoid copying any supplied composition; suitable only as an object-free texture and edge-quality calibration target
```

That prompt made `00-calibration-target.png`. It did not make, seed or feed the
other five images. It is a visual benchmark only.

## Exact procedural commands

```bash
riso motif crowd --palette egypt-cobalt --ar 2:3 --seed 11 --density 0.95 --out out/egypt-cobalt-proof/01-crowd.png
riso motif rays --palette egypt-cobalt --ar 2:3 --seed 23 --density 1.05 --out out/egypt-cobalt-proof/02-rays.png
riso motif peaks --palette egypt-cobalt --ar 2:3 --seed 37 --density 1.00 --out out/egypt-cobalt-proof/03-peaks.png
riso motif ripples --palette egypt-cobalt --ar 2:3 --seed 41 --density 0.90 --out out/egypt-cobalt-proof/04-ripples.png
riso motif mosaic --palette egypt-cobalt --ar 2:3 --seed 53 --density 1.10 --out out/egypt-cobalt-proof/05-mosaic.png
```

These commands run on the current Mac with Python, NumPy and Pillow. They do
not contact the PC, ComfyUI, Flux or any cloud image model.

## How the model-free path works

```text
motif name + seed + density
        ↓
Python draws exact flat shapes into palette plates
        ↓
egypt-cobalt.json supplies cobalt / sand / paper
        ↓
riso.post adds 1 px misregistration and seeded 2 px grain
        ↓
PNG + JSON receipt
```

`riso gen` is different: it still sends a text prompt and style reference to
Flux/Redux through ComfyUI on the PC, then applies the same post-pass.

`riso stylize` is different again: it takes an existing image as input, with no
text prompt, and palette-separates plus post-processes that image locally.
