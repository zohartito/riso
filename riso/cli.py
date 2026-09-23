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
import os
import random
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from riso import motif, post, vector
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


def _publish(files: dict) -> None:
    """Write a run's files all together or not at all.

    Each file is staged beside its target, then renamed into place, so a
    failure part-way never leaves a new SVG next to an old proof.
    """
    staged = []
    try:
        for target, content in files.items():
            temp = target.with_name(f".{target.name}.tmp")
            if isinstance(content, Image.Image):
                content.save(temp, format="PNG")
            else:
                temp.write_text(content, encoding="utf-8")
            staged.append((temp, target))
    except BaseException:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)
        raise
    for temp, target in staged:
        os.replace(temp, target)


def render_vector(
    prompt: str,
    style_name: str,
    engines: Sequence[str],
    aspect: str = "1:1",
    seed: Optional[int] = None,
    out_dir: Path = OUT_DIR,
    from_svg: Optional[Path] = None,
    from_image: Optional[Path] = None,
    svg_mode: str = "nearest",
    timeout: int = 900,
) -> List[Path]:
    """Draw one subject as SVG with each engine; return the proof PNGs written.

    With several engines this is a bake-off: failures are recorded and the
    rest still run, and a labelled contact sheet is written next to them.
    """
    style = load_style(style_name)
    palette = style.get("post", {}).get("palette")
    if palette is None:
        raise ValueError(f"{style['name']} has no [post] palette for the vector lane to lock to")
    colors = [tuple(c) for c in (post.load_palette(palette) if isinstance(palette, str) else palette)]
    width, height = dimensions(parse_aspect(aspect))
    if seed is None:
        seed = random.randrange(2**31)

    if from_svg is not None and from_image is not None:
        raise ValueError("choose one of --from-svg and --from-image")
    # One run per engine: the same name twice would write the same files.
    engines = list(dict.fromkeys(engines))
    if from_svg is not None:
        engines = ["from-svg"]
    elif from_image is not None:
        engines = ["trace"]
    for name in engines:
        if name not in vector.ENGINES and name != "from-svg":
            raise ValueError(f"unknown engine {name!r}; choose from {', '.join(vector.ENGINES)}")

    medium = style["generate"].get("prompt_suffix", "")
    needs_text = any(vector.ENGINES[n].kind in ("gateway", "cli", "local") for n in engines if n in vector.ENGINES)
    prompt_sent = vector.build_prompt(prompt, medium, colors, (width, height)) if needs_text else None
    subject_slug = slugify(prompt or (from_svg or from_image or Path("untitled")).stem)

    # The SVG is already on-palette after the lock, so the raster post-pass
    # must match colours, not re-separate them by lightness.
    preset = _post_preset(style, seed)
    preset["palette_mode"] = "nearest"

    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    sheet_entries: List[Tuple[str, Optional[Path]]] = []
    bench: List[dict] = []
    for name in engines:
        engine = vector.ENGINES.get(name)
        stem = f"vector-{style['name']}-{name}-{subject_slug}-{seed}"
        record: dict = {"engine": name, "stem": stem}
        text: Optional[str] = None
        try:
            if from_svg is not None:
                text, meta = from_svg.read_text(encoding="utf-8"), {"from_svg": _readable_path(from_svg.resolve())}
            else:
                try:
                    text, meta = vector.run_engine(
                        engine, prompt, prompt_sent or "", ref=style["generate"]["ref"],
                        source=from_image, colors=colors, mode=style["post"].get("palette_mode", "nearest"),
                        timeout=timeout,
                    )
                except vector.VectorError as exc:
                    text = exc.reply
                    raise
            text = vector.redact(text) if isinstance(text, str) else text
            raw_svg = vector.extract_svg(text)
            root = vector.parse_svg(raw_svg)
            flattened = vector.flatten(root)
            lock_stats = vector.lock_palette(root, colors, svg_mode)
            locked_svg = vector.serialize(root)
            stray = vector.audit_paints(locked_svg, colors)
            if stray:
                raise vector.VectorError(f"palette lock left {len(stray)} paint value(s): {stray[:5]}")

            with tempfile.TemporaryDirectory() as scratch:
                scratch_svg = Path(scratch) / "locked.svg"
                scratch_svg.write_text(locked_svg, encoding="utf-8")
                size = vector.rasterize(scratch_svg, Path(scratch) / "flat.png", width, colors[-1])
                with Image.open(Path(scratch) / "flat.png") as opened:
                    art = post.compose(opened.convert("RGB"), preset)
            if abs(size[0] / size[1] - width / height) > 0.02 * width / height:
                print(
                    f"note: {name} drew a {size[0]}x{size[1]} canvas, not {aspect}; "
                    "the proof keeps the drawing's own proportions",
                    file=sys.stderr,
                )

            png_path = out_dir / f"{stem}.png"
            sidecar = {
                "generator": "riso.vector",
                "engine": name,
                "engine_kind": engine.kind if engine else "from-svg",
                "model": engine.model if engine else None,
                "prompt": prompt,
                "prompt_sent": prompt if engine and engine.kind == "local" else prompt_sent,
                "style": style["name"],
                "palette": palette,
                "style_ref_sent": (
                    _readable_path(style["generate"]["ref"]) if engine and engine.kind == "gateway" else None
                ),
                "source": _readable_path(from_image.resolve()) if from_image else None,
                "seed": seed,
                "seed_note": "grain only — no engine in this lane is seedable; re-run with --from-svg",
                "size": list(size),
                "size_requested": [width, height],
                "raw_svg_sha256": hashlib.sha256(raw_svg.encode("utf-8")).hexdigest(),
                "engine_meta": meta,
                "flattened": flattened,
                "metrics_raw": vector.metrics(raw_svg),
                "metrics_locked": vector.metrics(locked_svg),
                "palette_lock": lock_stats,
                "post": preset,
                "licence": engine.licence if engine else "re-post of an existing SVG; its engine's licence applies",
            }
            _publish(
                {
                    out_dir / f"{stem}-raw.svg": raw_svg,
                    out_dir / f"{stem}.svg": locked_svg,
                    png_path: art,
                    png_path.with_suffix(".json"): vector.redact(json.dumps(sidecar, indent=2)) + "\n",
                }
            )
            written.append(png_path)
            sheet_entries.append((name, png_path))
            record.update(
                ok=True, seconds=meta.get("seconds"),
                bytes=sidecar["metrics_raw"]["bytes"], paths=sidecar["metrics_raw"]["paths"],
                on_palette=f"{lock_stats['distinct_on_palette']}/{lock_stats['distinct_in']}",
            )
        except Exception as exc:  # one engine failing must never end a bake-off
            detail = str(exc) if isinstance(exc, vector.VectorError) else f"{type(exc).__name__}: {exc}"
            message = vector.redact(detail)
            print(f"riso: {name}: {message}", file=sys.stderr)
            if isinstance(text, str) and text and from_svg is None:
                # The reply cost a model call; keep it so it can be inspected
                # or hand-repaired and re-run with --from-svg.
                try:
                    (out_dir / f"{stem}-reply.txt").write_text(vector.redact(text), encoding="utf-8")
                except OSError as write_error:
                    print(f"riso: {name}: could not keep the reply: {write_error}", file=sys.stderr)
            sheet_entries.append((f"{name} (failed)", None))
            record.update(ok=False, error=message[:300])
        bench.append(record)

    if len(engines) > 1:
        sheet = vector.contact_sheet(sheet_entries, out_dir / f"vector-bench-{style['name']}-{subject_slug}-{seed}.png")
        sheet.with_suffix(".json").write_text(
            json.dumps({"prompt": prompt, "style": style["name"], "seed": seed, "results": bench}, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(sheet)
    if not any(r["ok"] for r in bench):
        raise vector.VectorError("no engine produced an SVG")
    return written


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

    vector_parser = sub.add_parser(
        "vector", help="draw a subject as palette-locked SVG with one or more engines"
    )
    vector_parser.add_argument("prompt", nargs="?", default="", help="subject of the image")
    vector_parser.add_argument("--style", required=True, help="style preset from styles/")
    vector_parser.add_argument(
        "--engine",
        default="claude",
        help=f"comma-separated; several = bake-off with a contact sheet ({', '.join(vector.ENGINES)})",
    )
    vector_parser.add_argument("--ar", default="1:1", help="aspect ratio, e.g. 3:4")
    vector_parser.add_argument("--seed", type=int, help="grain seed; recorded either way")
    vector_parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    vector_parser.add_argument("--from-svg", type=Path, help="re-lock and re-post an existing SVG")
    vector_parser.add_argument("--from-image", type=Path, help="raster to trace (engine: trace)")
    vector_parser.add_argument(
        "--svg-mode", choices=post.PALETTE_MODES, default="nearest",
        help="how SVG colours map to inks: nearest hue, or lightness rank",
    )
    vector_parser.add_argument("--timeout", type=int, default=900, help="seconds per engine")

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
        elif args.command == "vector":
            paths = render_vector(
                args.prompt,
                args.style,
                [name.strip() for name in args.engine.split(",") if name.strip()],
                aspect=args.ar,
                seed=args.seed,
                out_dir=args.out_dir,
                from_svg=args.from_svg,
                from_image=args.from_image,
                svg_mode=args.svg_mode,
                timeout=args.timeout,
            )
            print("\n".join(str(p) for p in paths))
            return 0
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
    except (ComfyError, vector.VectorError, OSError, ValueError) as exc:
        print(f"riso: {vector.redact(str(exc))}", file=sys.stderr)
        return 1

    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
