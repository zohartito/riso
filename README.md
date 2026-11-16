# riso

Style-locked flat-illustration pipeline: subject prompt + style reference → flat
illustration → riso post-pass → export. Consistency across a series is the
deliverable; one-off pretty images are not.

Spec of record: [`docs/BRIEF.md`](docs/BRIEF.md).
Generation box: [`docs/generation-box.md`](docs/generation-box.md).

## Setup

```bash
python3 -m venv .venv          # Python 3.11 or newer
source .venv/bin/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .  # `riso` on PATH
python -m pytest -q
```

`python -m riso` works identically if you would rather not install.

`requirements.txt` is the authoritative lock for runtime, test and build
dependencies, including transitive dependencies and wheel hashes. Install it
first; disabling dependency resolution and build isolation on the second step
keeps the editable install in that environment. CI uses the same commands.
Binary wheels are required; an unsupported Python/platform fails rather than
silently building with unpinned tools. The Python interpreter and the separate
ComfyUI/weight installation are not covered by this lock. Bare `pip install .`
or a Git URL can resolve different dependency versions.

Non-editable installs (`python -m pip install --no-deps --no-build-isolation .`
after the lock) also include the shipped
styles, palettes, workflow and reference images. Output is written to `out/`
under your current working directory, including when installed from a wheel.

## Generate

Generation requires a separately installed, running **ComfyUI** and three model
files. Follow the [public bootstrap and health checks](docs/generation-box.md#public-bootstrap)
first. The post-pass and tests do not require ComfyUI or model weights.

```bash
riso gen "a crowd of tennis spectators seen from behind" --style tennis --ar 3:4
```

One command: ComfyUI generation → riso post-pass → a finished PNG in `out/`,
next to a JSON sidecar recording the prompt, seed, model, adapter and post
settings that made it. `--seed` to reuse a noise seed, `--keep-raw` to also write the
pre-post-pass frame, `riso styles` to list presets.

Default filenames include a unique run ID, so fixed-seed runs remain separate.
An explicit `--out` must be new: existing images, sidecars or requested raw
frames are never implicitly overwritten.
`--out result` becomes `result.png`; unsupported extensions fail before
generation starts.
Sidecars and raw frames include the entire image filename: `art.jpg.json`
and `art.jpg-raw.png`, for example. Thus `art.jpg` and `art.webp` retain
independent records and raw frames.

A style preset in `styles/*.toml` is the unit of series consistency — reference
image, strength, prompt wording, palette, crop and post settings in one file.
For a series, hold the preset and its referenced files, workflow, `--ar` and
generation runtime fixed; the style name alone does not enforce that. Sidecars
record settings and paths, but do not hash the assets/workflow or capture
ComfyUI/torch versions. A seed and style name do not guarantee identical
generation after those inputs change.

Preset names must start with a letter or digit and contain only letters,
digits, underscores and hyphens. References must decode as images and resolve
inside the bundled `refs/` directory (the source `refs/` in an editable install).
For a custom reference, review and copy the image there before using its path
in a preset. Presets cannot select arbitrary external files for upload.
Output paths, including their parent directories, must not be symlinks.

`crop_keep` delivers the densest part of the frame at the size you asked for:
whatever the subject does not fill, the style reference fills with its own
shapes, so the crop trades that away. ComfyUI generates near one megapixel at
latent-compatible dimensions; a final crop preserves the exact requested ratio
before the post-pass. For example, `--ar 3:4` delivers 864×1152 from an 896×1152
latent frame. The sidecar records both delivered `size` and `latent_size`.

`docs/phase5-cropped-sheet.png` is three subjects through one preset, on the
first seed for each, no hunting. Earlier sheets are kept beside it as the
record of how it got there.

## What this pipeline does and does not do

**It targets dense, repeating subjects.** Crowds, banks of faces, fields of
waves, stands of trees. These are the intended scope of the shipped preset,
based on the finite schnell/Redux experiments recorded in `refs/srefs.md`.

Subjects to try: `a crowd of tennis spectators seen from behind`,
`rows of striped umbrellas on a beach`, `a stand of pine trees on a hillside`,
`commuters on a station platform`, `a flock of birds over rooftops`.

**Sparse subjects failed in the recorded experiments.** The prompt "a tennis
player mid-serve seen from the baseline" lost its figure against four tested
references; reference shapes filled the frame instead. That is evidence about
one prompt and those tested settings, not every sparse subject or every seed.

**The current preset has no reproducible published hit rate.** Historical
[run notes](refs/srefs.md#historical-hit-rate-notes-2026-08-15) report ten dense
crowds, but the raw frames, sidecars and versioned scoring criteria are not
included. Treat the sheets as examples and inspect every output.

**`riso gen` cannot tell you when the subject is missing.** It warns on a
featureless frame, but a frame full of confident abstraction is not featureless
— one such failure measured a tonal span of 0.326 against the 0.02 warning
threshold. It is a healthy, high-contrast, entirely subject-free image, and the
tool will report success. Look at what comes out.

## Post-pass

```python
from pathlib import Path
from PIL import Image
from riso import post

art = post.compose(Image.open("in.png"), {
    "palette": "tennis-felt",                              # palettes/*.json
    "palette_mode": "luma",                                # or "nearest"
    "halftone": {"angle": 15, "cell": 5, "strength": 0.18},
    "misregister": {"px": 2},
    "grain": {"amount": 0.11, "seed": 7},                  # 2px tooth by default
})
Path("out").mkdir(exist_ok=True)
art.save("out/art.png")
```

Steps run in a fixed order — `palette_lock → halftone → misregister → grain` —
and each is optional. The tests establish byte-identical PNGs for the same
input pixels, post settings and grain seed in the same library environment;
this does not promise byte-identical ComfyUI generation or cross-version PNG
encoding. Palettes are data:
add a JSON file to `palettes/` rather than hardcoding colours.

**Two palette mappings, because they fail in opposite directions.** `nearest`
picks the closest ink in Oklab and is right when the source already lives near
the palette; on a generated frame, which sits nowhere near it, every pixel can
land on the same ink and the image collapses to one flat field. `luma` ignores
source hue and maps lightness bands onto the palette's lightness order. It can
preserve forms with sufficient lightness contrast, but equal-lightness colours
can merge into one ink. Quantization and the 2nd–98th percentile clipping can
also lose small details; a lightness span below 0.02 becomes one ink. Style
presets use `luma`, so inspect hue-defined forms and fine details after mapping.

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

Two starting points from the historical schnell/Redux tests in
[`refs/srefs.md`](refs/srefs.md), to re-check when inputs change:

- **Start near 0.05–0.15 strength.** The initial sweep used one crowd prompt,
  seed 4242, schnell at four steps and the recorded references. At 1.0 the
  reference dominated that test. This is a tuning suggestion, not a universal
  usable band. The workflow ships at 0.10; `tennis` runs 0.08 with its suffix.
- **Start with flat references for this look.** At 0.10, the two-reference
  comparison at seed 4242 produced a photographic stained-glass variant and a
  flatter poster variant. It does not prove how all references or prompts
  behave. Palette locking supplies the final inks, but cannot guarantee subject
  presence or remove outlines. The paper-medium wording reduced measured
  linework in the recorded crowd comparisons; inspect each generated frame.

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

No model weights are included in this repository. The style-reference workflow
uses `flux1-redux-dev`, whose weights are non-commercial; download it and the
other models yourself under their own licences. The code here is MIT (see
[`LICENSE`](LICENSE)).
