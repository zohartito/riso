# riso

Style-locked flat-illustration pipeline: subject prompt + style reference → flat
illustration → riso post-pass → export. Consistency across a series is the
deliverable; one-off pretty images are not.

Spec of record: [`docs/BRIEF.md`](docs/BRIEF.md).
Generation box: [`docs/generation-box.md`](docs/generation-box.md).

## Setup

```bash
source .venv/bin/activate      # Python 3.13 here, syntax kept 3.11-safe
pip install -e .               # puts the `riso` command on PATH
python -m pytest -q
```

`python -m riso` works identically if you would rather not install.

## Generate

```bash
riso gen "a crowd of tennis spectators seen from behind" --style tennis --ar 3:4
```

One command: ComfyUI generation → riso post-pass → a finished PNG in `out/`,
next to a JSON sidecar recording the prompt, seed, model, adapter and post
settings that made it. `--seed` to reproduce, `--keep-raw` to also write the
pre-post-pass frame, `riso styles` to list presets.

A style preset in `styles/*.toml` is the unit of series consistency — reference
image, strength, palette and post settings in one file. Two runs naming the
same style differ in subject and seed and nothing else.

`docs/phase3-contact-sheet.png` is three subjects through one preset.

## Post-pass

```python
from PIL import Image
from riso import post

art = post.compose(Image.open("in.png"), {
    "palette": "tennis-felt",                              # palettes/*.json
    "palette_mode": "luma",                                # or "nearest"
    "halftone": {"angle": 15, "cell": 5, "strength": 0.18},
    "misregister": {"px": 2},
    "grain": {"amount": 0.11, "seed": 7},                  # 2px tooth by default
})
art.save("out/art.png")
```

Steps run in a fixed order — `palette_lock → halftone → misregister → grain` —
and each is optional. Same seed in, byte-identical PNG out. Palettes are data:
add a JSON file to `palettes/` rather than hardcoding colours.

**Two palette mappings, because they fail in opposite directions.** `nearest`
picks the closest ink in Oklab and is right when the source already lives near
the palette; on a generated frame, which sits nowhere near it, every pixel can
land on the same ink and the image collapses to one flat field. `luma` ignores
source hue and maps lightness bands onto the palette's lightness order, so form
always survives. Style presets use `luma`.

Generated images go to `out/`, which is gitignored. Style references in `refs/`
are committed on purpose — they are the style identity.

## Style reference

`workflows/flux-redux-styleref.json` (ComfyUI API format) carries style from a
reference image while the prompt supplies the subject — the local equivalent of
`--sref`. Drive it with `riso.comfy`:

```python
from riso.comfy import Comfy, apply_params, load_workflow

comfy = Comfy()                                    # 127.0.0.1:8188, WSL-local
ref = comfy.upload_image("refs/style-riso-poster.png")
png = comfy.generate(apply_params(load_workflow(),
                                  prompt="a crowd of tennis spectators seen from behind",
                                  style_ref=ref, seed=4242))
```

Two rules, both measured, both in [`refs/srefs.md`](refs/srefs.md) with the runs
behind them:

- **The usable strength band is 0.05–0.15, not the 0.0–10.0 the node
  advertises.** At the node's own 1.0 default it reproduces the reference and
  ignores the prompt entirely. The workflow ships at 0.10; `tennis` runs 0.08.
- **A reference teaches rendering mode, so only ever use flat references.** A
  dimensional reference lets the base model fall back to photoreal no matter
  what the prompt says. The reference does not carry the palette — that comes
  from the post-pass — and its output is not literally flat either, which is
  why `palette_lock` is not optional.

## Models and licensing

**`flux1-schnell-fp8` is the default, and it is Apache-2.0.** The pipeline
stays on it: Redux style-referencing supports schnell, 4 steps keep iteration
fast, and the licence carries no commercial restriction — output can feed
@zohar_tito freely.

Flux dev and Flux Krea-dev are **non-commercial** and are not used here. If a
hero image is ever generated with one of them, that restriction travels with the
image. Record which model produced each image.

**One catch: the Redux adapter is not Apache-2.0.** `flux1-redux-dev` ships
under the FLUX.1 [dev] Non-Commercial License. The base model being Apache-2.0
does not launder that — any image made through the style-reference workflow
inherits the adapter's restriction, even though schnell itself is unrestricted.
Post-pass-only output (Phase 1, no Redux) stays fully Apache-2.0. Worth knowing
before anything from here is used commercially.
