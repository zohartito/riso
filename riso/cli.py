"""``riso gen`` — subject prompt + style preset, one command, one finished PNG.

Chains Phase 2 (ComfyUI style-reference generation) into Phase 1 (the riso
post-pass). Presets hold style settings; callers must also hold aspect ratio,
referenced assets, workflow and generation runtime fixed across a series.

Every image is written with a JSON sidecar naming the model, adapter, seed and
post settings that made it. It records paths and settings, not immutable asset
hashes or generation runtime versions.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import re
import sys
import uuid
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageOps
from requests import RequestException

from riso import post
from riso.comfy import Comfy, ComfyError, apply_params, load_workflow
from riso.styles import REPO_ROOT, STRENGTH_BAND, available_styles, load_style

OUT_DIR = Path("out")

# ~1 MP total, which is what schnell was trained around, snapped to a multiple
# the latent can hold exactly.
BASE_PIXELS = 1024
LATENT_MULTIPLE = 64


def parse_aspect(value: str) -> Tuple[int, int]:
    """Parse ``3:4`` (or ``3x4``) into a ratio pair."""
    match = re.fullmatch(r"\s*(\d+)\s*[:x]\s*(\d+)\s*", value)
    if not match:
        raise ValueError(f"expected an aspect ratio like 3:4, got {value!r}")
    width, height = int(match.group(1)), int(match.group(2))
    if width == 0 or height == 0:
        raise ValueError(f"aspect ratio cannot have a zero side: {value!r}")
    return width, height


def dimensions(
    ratio: Tuple[int, int],
    base: int = BASE_PIXELS,
    multiple: int = LATENT_MULTIPLE,
) -> Tuple[int, int]:
    """Latent size near the aspect ratio, holding area near ``base**2``."""
    ratio_w, ratio_h = ratio
    scale = base / math.sqrt(ratio_w * ratio_h)

    def snap(side: float) -> int:
        return max(multiple, int(round(side / multiple)) * multiple)

    return snap(ratio_w * scale), snap(ratio_h * scale)


def slugify(text: str, limit: int = 40) -> str:
    """Short filesystem-safe stem from a prompt."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "untitled"


def _readable_path(path: Path) -> str:
    """Repo-relative if it lives here, absolute if it does not.

    The sidecar has to stay meaningful on the other machine, and this repo
    syncs between two.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _post_preset(style: dict, seed: int) -> dict:
    """The style's ``[post]`` table, with grain seeded from the run seed.

    A style that pins its own grain seed keeps it; one that does not gets grain
    that varies across a series while any single image stays reproducible.
    """
    preset = json.loads(json.dumps(style.get("post", {}), default=str))
    grain = preset.get("grain")
    if isinstance(grain, dict):
        grain.setdefault("seed", seed)
    return preset


def generate(
    prompt: str,
    style_name: str,
    aspect: str = "1:1",
    seed: Optional[int] = None,
    host: str = "127.0.0.1:8188",
    out: Optional[Path] = None,
    keep_raw: bool = False,
) -> Path:
    """Generate one image and return the path it was written to."""
    style = load_style(style_name)
    settings = style["generate"]
    ratio = parse_aspect(aspect)
    width, height = dimensions(ratio)
    divisor = math.gcd(*ratio)
    ratio_w, ratio_h = (side // divisor for side in ratio)
    factor = max(1, min(width // ratio_w, height // ratio_h))
    delivered_size = (ratio_w * factor, ratio_h * factor)
    if seed is None:
        seed = random.randrange(2**31)

    if out is None:
        out = OUT_DIR / f"{style['name']}-{slugify(prompt)}-{seed}-{uuid.uuid4().hex}.png"
    if not out.suffix:
        out = out.with_suffix(".png")
    image_format = Image.registered_extensions().get(out.suffix.lower())
    if image_format not in Image.SAVE:
        raise ValueError(f"unsupported output extension: {out.suffix}")
    sidecar = out.with_name(f"{out.name}.json")
    raw_out = out.with_name(f"{out.name}-raw.png")
    targets = [out, sidecar] + ([raw_out] if keep_raw else [])
    for target in targets:
        if any(part.is_symlink() for part in (target, *target.parents)):
            raise ValueError(f"output paths must not contain a symlink: {target}")
        if target.exists():
            raise FileExistsError(f"refusing to overwrite {target}; choose another --out")

    keep = float(settings.get("crop_keep", 1.0))
    if not 0.0 < keep <= 1.0:
        raise ValueError(f"crop_keep must be in (0, 1], got {keep}")

    low, high = STRENGTH_BAND
    if not low <= settings["strength"] <= high:
        print(
            f"note: {style['name']} runs at strength {settings['strength']}, "
            f"outside the measured {low}-{high} band",
            file=sys.stderr,
        )

    workflow = load_workflow(settings.get("workflow", "flux-redux-styleref"))
    checkpoint = workflow["checkpoint"]["inputs"]["ckpt_name"]

    comfy = Comfy(host)
    if not comfy.is_up():
        raise ComfyError(
            f"no ComfyUI at {host} — in your ComfyUI checkout, start "
            "`python main.py --listen 127.0.0.1 --port 8188` "
            "(see docs/generation-box.md for installation; "
            "`systemctl --user start comfyui` only applies if you installed that unit)"
        )

    # In the recorded crowd tests, a flatness clause helped balance style and
    # subject at low strength. See refs/srefs.md for the tested settings.
    full_prompt = prompt + settings.get("prompt_suffix", "")

    uploaded = comfy.upload_image(settings["ref"])
    raw_png = comfy.generate(
        apply_params(
            workflow,
            prompt=full_prompt,
            style_ref=uploaded,
            style_strength=settings["strength"],
            seed=seed,
            steps=settings.get("steps"),
            width=width,
            height=height,
            filename_prefix=f"riso/{style['name']}",
        )
    )

    preset = _post_preset(style, seed)
    with Image.open(io.BytesIO(raw_png)) as raw:
        raw.load()

        # schnell occasionally returns an empty field for a given seed and
        # subject. The post-pass cannot rescue that, and a silent flat plate is
        # worse than a warning — a series is judged whole.
        if post.tonal_span(raw) < post.FLAT_FRAME_SPAN:
            print(
                f"warning: seed {seed} generated a featureless frame for "
                f"{prompt!r} — re-run with a different --seed",
                file=sys.stderr,
            )

        framed = raw
        if keep < 1.0:
            palette = preset.get("palette")
            if palette is None:
                raise ValueError("crop_keep needs a [post] palette to find the subject")
            colors = post.load_palette(palette) if isinstance(palette, str) else palette

            # Crop to the subject, then scale back to the size that was asked
            # for. The upscale costs nothing visible because palette_lock
            # re-quantises to flat plates afterwards, and grain lands at the
            # delivered size, so the 2px tooth stays 2px.
            framed = post.content_crop(
                raw, colors, (round(width * keep), round(height * keep))
            ).resize((width, height), Image.LANCZOS)

        # Latent multiples approximate the ratio; trim to an exact integer
        # ratio before adding texture so the final grain stays at pixel scale.
        framed = ImageOps.fit(framed, delivered_size, method=Image.LANCZOS)
        art = post.compose(framed, preset)

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("xb") as handle:
            art.save(handle, format=image_format)

        if keep_raw:
            with raw_out.open("xb") as handle:
                raw.save(handle, format="PNG")

    record = json.dumps(
            {
                "prompt": prompt,
                "prompt_sent": full_prompt,
                "style": style["name"],
                "style_ref": _readable_path(settings["ref"]),
                "strength": settings["strength"],
                "model": checkpoint,
                "style_adapter": workflow["redux"]["inputs"]["style_model_name"],
                "licence": (
                    "base model Apache-2.0; the Redux adapter is FLUX.1 [dev] "
                    "Non-Commercial, and that restriction travels with this image"
                ),
                "seed": seed,
                "steps": settings.get("steps"),
                "size": list(delivered_size),
                "latent_size": [width, height],
                "crop_keep": keep,
                "post": preset,
            },
            indent=2,
        ) + "\n"
    with sidecar.open("x", encoding="utf-8") as handle:
        handle.write(record)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riso", description="Style-locked flat-illustration pipeline."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("gen", help="generate one finished image")
    gen.add_argument("prompt", help="subject of the image")
    gen.add_argument(
        "--style",
        required=True,
        help=f"style preset from styles/ ({', '.join(available_styles()) or 'none yet'})",
    )
    gen.add_argument("--ar", default="1:1", help="aspect ratio, e.g. 3:4")
    gen.add_argument("--seed", type=int, help="defaults to random; recorded either way")
    gen.add_argument("--out", type=Path, help="new output path (default out/<style>-<slug>-<seed>-<run-id>.png)")
    gen.add_argument("--host", default="127.0.0.1:8188", help="ComfyUI host:port")
    gen.add_argument(
        "--keep-raw",
        action="store_true",
        help="also write the pre-post-pass image, for judging what each half did",
    )

    sub.add_parser("styles", help="list style presets")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "styles":
        for name in available_styles():
            print(name)
        return 0

    try:
        out = generate(
            args.prompt,
            args.style,
            aspect=args.ar,
            seed=args.seed,
            host=args.host,
            out=args.out,
            keep_raw=args.keep_raw,
        )
    except (ComfyError, RequestException, TimeoutError, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"riso: {exc}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
