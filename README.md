# riso

Style-locked flat-illustration pipeline: subject prompt + style reference → flat
illustration → riso post-pass → export. Consistency across a series is the
deliverable; one-off pretty images are not.

Spec of record: [`docs/BRIEF.md`](docs/BRIEF.md).
Generation box: [`docs/generation-box.md`](docs/generation-box.md).

## Setup

```bash
source .venv/bin/activate      # Python 3.13 here, syntax kept 3.11-safe
python -m pytest -q
```

## Post-pass

```python
from PIL import Image
from riso import post

art = post.compose(Image.open("in.png"), {
    "palette": "tennis-felt",                              # palettes/*.json
    "halftone": {"angle": 15, "cell": 5, "strength": 0.18},
    "misregister": {"px": 2},
    "grain": {"amount": 0.11, "seed": 7},                  # 2px tooth by default
})
art.save("out/art.png")
```

Steps run in a fixed order — `palette_lock → halftone → misregister → grain` —
and each is optional. Same seed in, byte-identical PNG out. Palettes are data:
add a JSON file to `palettes/` rather than hardcoding colours.

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

**Redux's usable strength band is 0.05–0.15, not the 0.0–10.0 the node
advertises.** At the node's own 1.0 default it reproduces the reference and
ignores the prompt entirely. The workflow ships at 0.10. Measurements and the
reference ledger are in [`refs/srefs.md`](refs/srefs.md).

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
