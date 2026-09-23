"""``riso gen`` — subject prompt + style preset, one command, one finished PNG.

Chains Phase 2 (ComfyUI style-reference generation) into Phase 1 (the riso
post-pass). The subject and the seed are the only things that vary between
runs of a series; everything else comes from ``styles/*.toml``.

Every image is written with a JSON sidecar naming the model, adapter, seed and
post settings that made it — licence travels with the image, and a series that
cannot be re-run is not a series.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageOps

from riso import motif, post
from riso.comfy import Comfy, ComfyError, apply_params, load_workflow
from riso.styles import REPO_ROOT, STRENGTH_BAND, available_styles, load_style

OUT_DIR = REPO_ROOT / "out"

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
    """Pixel size for an aspect ratio, holding total area near ``base**2``."""
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


def resolved_prompt(prompt: str, style: dict) -> str:
    """Exact text sent to Flux: user-authored subject plus medium mechanics."""
    subject = prompt.strip()
    if not subject:
        raise ValueError("prompt cannot be empty")
    return subject + style["generate"].get("prompt_suffix", "")


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
    width, height = dimensions(parse_aspect(aspect))
    if seed is None:
        seed = random.randrange(2**31)

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
            f"no ComfyUI at {host} — start it with `systemctl --user start comfyui` "
            "from inside WSL on the PC (see docs/generation-box.md)"
        )

    # The reference cannot carry flatness and subject clarity at the same
    # strength — see refs/srefs.md. The preset says "flat" in words too, which
    # is what lets the strength sit low enough for the subject to survive.
    full_prompt = resolved_prompt(prompt, style)

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

        art = post.compose(framed, preset)

        if out is None:
            out = OUT_DIR / f"{style['name']}-{slugify(prompt)}-{seed}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        art.save(out)

        if keep_raw:
            raw.save(out.with_name(f"{out.stem}-raw.png"))

    out.with_suffix(".json").write_text(
        json.dumps(
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
                "size": [width, height],
                "crop_keep": keep,
                "post": preset,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def _offline_post(seed: int, grain: float, misregister: int) -> dict:
    """Press treatment shared by procedural motifs and imported artwork."""
    preset = {
        "grain": {"amount": grain, "seed": seed, "scale": 2},
    }
    if misregister:
        preset["misregister"] = {"px": misregister}
    return preset


def render_motif(
    motif_name: str,
    palette: str = "egypt-cobalt",
    aspect: str = "2:3",
    seed: Optional[int] = None,
    density: float = 1.0,
    grain: float = 0.08,
    misregister: int = 1,
    out: Optional[Path] = None,
    keep_raw: bool = False,
) -> Path:
    """Render one model-free geometric poster and write its provenance."""
    if seed is None:
        seed = random.randrange(2**31)
    width, height = dimensions(parse_aspect(aspect))
    raw = motif.render(motif_name, palette, (width, height), seed, density)
    preset = _offline_post(seed, grain, misregister)
    art = post.compose(raw, preset)

    if out is None:
        out = OUT_DIR / f"motif-{motif_name}-{palette}-{seed}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    art.save(out)
    if keep_raw:
        raw.save(out.with_name(f"{out.stem}-raw.png"))

    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "generator": "riso.motif",
                "motif": motif_name,
                "palette": palette,
                "seed": seed,
                "density": density,
                "size": [width, height],
                "post": preset,
                "licence": "procedural renderer; no external model or adapter",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def stylize(
    source: Path,
    palette: str = "egypt-cobalt",
    seed: Optional[int] = None,
    palette_mode: str = "luma",
    grain: float = 0.08,
    misregister: int = 1,
    out: Optional[Path] = None,
) -> Path:
    """Apply the deterministic press pipeline to an existing image."""
    source = source.expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"no input image at {source}")
    if out is not None and out.expanduser().resolve() == source.resolve():
        raise ValueError("stylize output must not overwrite its input image")
    if seed is None:
        seed = random.randrange(2**31)

    preset = {
        "palette": palette,
        "palette_mode": palette_mode,
        **_offline_post(seed, grain, misregister),
    }
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        art = post.compose(image, preset)

    if out is None:
        out = OUT_DIR / f"stylized-{slugify(source.stem)}-{palette}-{seed}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    art.save(out)
    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "generator": "riso.stylize",
                "source": _readable_path(source.resolve()),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "palette": palette,
                "seed": seed,
                "size": [art.width, art.height],
                "post": preset,
                "licence": "post-processing only; source-image rights still apply",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
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
    gen.add_argument(
        "--out",
        type=Path,
        help="output path (default out/<style>-<slug>-<seed>.png)",
    )
    gen.add_argument("--host", default="127.0.0.1:8188", help="ComfyUI host:port")
    gen.add_argument(
        "--keep-raw",
        action="store_true",
        help="also write the pre-post-pass image, for judging what each half did",
    )
    gen.add_argument(
        "--show-prompt",
        action="store_true",
        help="print the exact user prompt plus style suffix without generating",
    )

    motif_parser = sub.add_parser(
        "motif", help="render a deterministic geometric poster without ComfyUI"
    )
    motif_parser.add_argument("motif", choices=motif.available_motifs())
    motif_parser.add_argument("--palette", default="egypt-cobalt")
    motif_parser.add_argument("--ar", default="2:3", help="aspect ratio, e.g. 2:3")
    motif_parser.add_argument("--seed", type=int, help="defaults to random; recorded either way")
    motif_parser.add_argument(
        "--density", type=float, default=1.0, help="motif repetition, 0.25 to 3.0"
    )
    motif_parser.add_argument("--grain", type=float, default=0.08, help="grain amount, 0 to 1")
    motif_parser.add_argument(
        "--misregister", type=int, default=1, help="RGB plate offset in pixels"
    )
    motif_parser.add_argument("--out", type=Path)
    motif_parser.add_argument("--keep-raw", action="store_true")

    stylize_parser = sub.add_parser(
        "stylize", help="apply palette and press texture to an existing image"
    )
    stylize_parser.add_argument("input", type=Path)
    stylize_parser.add_argument("--palette", default="egypt-cobalt")
    stylize_parser.add_argument("--seed", type=int, help="defaults to random; recorded either way")
    stylize_parser.add_argument(
        "--palette-mode", choices=post.PALETTE_MODES, default="luma"
    )
    stylize_parser.add_argument("--grain", type=float, default=0.08)
    stylize_parser.add_argument("--misregister", type=int, default=1)
    stylize_parser.add_argument("--out", type=Path)

    sub.add_parser("styles", help="list style presets")
    sub.add_parser("motifs", help="list procedural motif renderers")
    sub.add_parser("palettes", help="list palettes")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "styles":
        for name in available_styles():
            print(name)
        return 0

    if args.command == "motifs":
        for name in motif.available_motifs():
            print(name)
        return 0

    if args.command == "palettes":
        for name in post.available_palettes():
            print(name)
        return 0

    try:
        if args.command == "gen":
            if args.show_prompt:
                print(resolved_prompt(args.prompt, load_style(args.style)))
                return 0
            out = generate(
                args.prompt,
                args.style,
                aspect=args.ar,
                seed=args.seed,
                host=args.host,
                out=args.out,
                keep_raw=args.keep_raw,
            )
        elif args.command == "motif":
            out = render_motif(
                args.motif,
                palette=args.palette,
                aspect=args.ar,
                seed=args.seed,
                density=args.density,
                grain=args.grain,
                misregister=args.misregister,
                out=args.out,
                keep_raw=args.keep_raw,
            )
        else:
            out = stylize(
                args.input,
                palette=args.palette,
                seed=args.seed,
                palette_mode=args.palette_mode,
                grain=args.grain,
                misregister=args.misregister,
                out=args.out,
            )
    except (ComfyError, OSError, ValueError) as exc:
        print(f"riso: {exc}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
