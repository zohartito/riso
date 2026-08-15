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

## Models and licensing

**`flux1-schnell-fp8` is the default, and it is Apache-2.0.** The pipeline
stays on it: Redux style-referencing supports schnell, 4 steps keep iteration
fast, and the licence carries no commercial restriction — output can feed
@zohar_tito freely.

Flux dev and Flux Krea-dev are **non-commercial** and are not used here. If a
hero image is ever generated with one of them, that restriction travels with the
image. Record which model produced each image.
