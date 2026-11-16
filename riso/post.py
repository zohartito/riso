"""Riso post-pass: flat-colour quantise, halftone, misregistration, grain.

Pure numpy + Pillow. No GPU, no Photoshop. Every step is deterministic — the
only randomness is `grain`, and it is seeded.

Chain order in `compose` is fixed and deliberate:

    palette_lock -> halftone -> misregister -> grain

Quantise first so forms read by colour adjacency; screen and misregister the
flat plates the way a press would; grain last so it sits on top of everything,
uniform across the full frame.

`content_crop` sits outside that chain, and before it: the CLI generates a
frame larger than it ships and crops to the delivered size, so grain tooth and
halftone pitch stay true to the pixels that survive.

Note that `halftone` and `grain` intentionally introduce colours outside the
palette — that is ink overlay and paper texture, not a bug. `palette_lock` on
its own is the step that holds the image to the palette and nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union

import numpy as np
from PIL import Image

from riso.resources import ASSET_ROOT

PALETTE_DIR = ASSET_ROOT / "palettes"

RGB = Tuple[int, int, int]
Palette = Sequence[RGB]
Preset = Dict[str, Any]

# Rec. 709 luma weights, used for the halftone's luminance channel.
_LUMA = (0.2126, 0.7152, 0.0722)


# --------------------------------------------------------------------------
# palettes (data lives in palettes/*.json — never hardcode colours here)
# --------------------------------------------------------------------------


def _hex_to_rgb(value: str) -> RGB:
    """Parse ``#RRGGBB`` (or ``RRGGBB``) into an 8-bit RGB triple."""
    digits = value.lstrip("#")
    if len(digits) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def load_palette(name: Union[str, Path]) -> List[RGB]:
    """Load a palette by name (``tennis-felt``) or by path to a JSON file."""
    path = Path(name)
    if path.suffix.lower() != ".json":
        path = PALETTE_DIR / f"{path.name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no palette at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        raw = data["colors"]
    except (TypeError, KeyError) as exc:
        raise ValueError(f"{path} has no 'colors' list") from exc

    colors = [_hex_to_rgb(c) for c in raw]
    if len(colors) < 2:
        raise ValueError(f"{path} needs at least 2 colours, got {len(colors)}")
    return colors


def available_palettes() -> List[str]:
    """Names of every palette shipped in ``palettes/``."""
    return sorted(p.stem for p in PALETTE_DIR.glob("*.json"))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _to_array(img: Image.Image) -> np.ndarray:
    """PIL image -> ``(H, W, 3)`` uint8 array, dropping alpha and palettes."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def _to_image(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.ascontiguousarray(arr, dtype=np.uint8), mode="RGB")


def _srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """sRGB in ``0..1`` -> Oklab. Shape ``(..., 3)`` in, same shape out.

    Nearest-colour matching in raw sRGB assigns muddy, luminance-blind
    neighbours; Oklab keeps the perceptual ordering that makes a flat palette
    read correctly.
    """
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]

    long_ = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    med = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    short = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)

    return np.stack(
        [
            0.2104542553 * long_ + 0.7936177850 * med - 0.0040720468 * short,
            1.9779984951 * long_ - 2.4285922050 * med + 0.4505937099 * short,
            0.0259040371 * long_ + 0.7827717662 * med - 0.8086757660 * short,
        ],
        axis=-1,
    )


def _shift_plane(plane: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """Shift a 2-D plane by ``(dx, dy)`` px, clamping at the edges.

    Edge-clamped rather than wrapped: a wrapped channel drags the opposite
    border into frame, which reads as a glitch and not as a press offset.
    """
    if dx == 0 and dy == 0:
        return plane.copy()
    pad = max(abs(dx), abs(dy))
    padded = np.pad(plane, pad, mode="edge")
    height, width = plane.shape
    top, left = pad - dy, pad - dx
    return padded[top : top + height, left : left + width]


# --------------------------------------------------------------------------
# the post-pass steps
# --------------------------------------------------------------------------


PALETTE_MODES = ("nearest", "luma")


def _lock_nearest(arr: np.ndarray, colors: List[RGB]) -> np.ndarray:
    """Index of the nearest swatch to each pixel, measured in Oklab."""
    pixels = _srgb_to_oklab(arr.astype(np.float32) / 255.0)
    swatches = _srgb_to_oklab(np.asarray(colors, dtype=np.float32) / 255.0)

    # One distance plane per swatch: N is tiny, and this keeps peak memory at
    # (H, W) floats instead of (H, W, N).
    best_index = np.zeros(arr.shape[:2], dtype=np.intp)
    best_distance = np.full(arr.shape[:2], np.inf, dtype=np.float32)
    for index, swatch in enumerate(swatches):
        delta = pixels - swatch
        distance = np.einsum("ijk,ijk->ij", delta, delta)
        closer = distance < best_distance
        best_distance = np.where(closer, distance, best_distance)
        best_index = np.where(closer, index, best_index)
    return best_index


def _oklab_lightness(arr: np.ndarray) -> np.ndarray:
    return _srgb_to_oklab(arr.astype(np.float32) / 255.0)[..., 0]


def tonal_span(img: Image.Image) -> float:
    """Oklab lightness range of an image, ignoring the outer 2% at each end.

    The number `luma` mode separates on. Near zero means little lightness
    contrast survives the clipping; hue-defined forms and small details may
    still exist, but luma mapping can discard them.
    """
    low, high = np.percentile(_oklab_lightness(_to_array(img)), (2.0, 98.0))
    return float(high) - float(low)


# Below this the frame is featureless: what is left is sampling noise, and
# stretching it across the palette turns that noise into speckle.
FLAT_FRAME_SPAN = 0.02


def _lock_luma(arr: np.ndarray, colors: List[RGB]) -> np.ndarray:
    """Index of the swatch whose lightness rank matches each pixel's band.

    A separation, not a colour match: the frame is cut into as many lightness
    bands as there are inks, and the inks are laid on darkest-first.

    Bands are equal width in lightness, clipped to the 2nd–98th percentile so
    one stray specular pixel cannot stretch the range and shift every band —
    two images in a series have to separate the same way to read as a series.

    Cutting the bands at **quantiles** instead, so every ink gets an equal
    share of pixels, was built and measured on 10 frames and rejected: it
    raised ink coverage from 4.5 to 4.7 inks per frame and broke the plates up
    5× more (2.2% → 11.0% of adjacent pixels landing on different inks). A
    near-flat area is not perfectly flat, and equalising population shreds it
    into two-ink mottle. Flat plates are the look; an unused ink is not worth
    losing them for.
    """
    lightness = _oklab_lightness(arr)
    swatch_lightness = _srgb_to_oklab(np.asarray(colors, dtype=np.float32) / 255.0)[
        ..., 0
    ]
    ranked = np.argsort(swatch_lightness, kind="stable")

    low, high = np.percentile(lightness, (2.0, 98.0))
    if float(high) - float(low) < FLAT_FRAME_SPAN:
        # Nothing to separate. Lay a single ink rather than amplifying noise,
        # so a dead frame still looks dead.
        nearest = int(np.argmin(np.abs(swatch_lightness - float(lightness.mean()))))
        return np.full(lightness.shape, nearest, dtype=np.intp)

    bands = len(colors)
    span = float(high) - float(low)
    band = np.clip(
        np.floor((lightness - float(low)) / span * bands).astype(np.intp), 0, bands - 1
    )
    return ranked[band]


def detail_map(img: Image.Image, palette: Palette, tile: int = 32) -> np.ndarray:
    """Per-tile density of ink boundaries — where the *subject* is.

    A crowd is hundreds of small regions and scores high. A torn-paper plane,
    a sky, or any large flat shape scores near zero however colourful it is.
    That distinction is the one that matters here, because the failure being
    measured is a frame half-filled with handsome abstraction.
    """
    plates = np.asarray(palette_lock(img, palette, "luma"), dtype=np.int32)
    key = plates[..., 0] * 65536 + plates[..., 1] * 256 + plates[..., 2]

    edges = np.zeros(key.shape, dtype=np.float32)
    edges[:, :-1] += key[:, :-1] != key[:, 1:]
    edges[:-1, :] += key[:-1, :] != key[1:, :]

    height = key.shape[0] // tile * tile
    width = key.shape[1] // tile * tile
    return edges[:height, :width].reshape(
        height // tile, tile, width // tile, tile
    ).mean(axis=(1, 3))


def content_crop(
    img: Image.Image, palette: Palette, size: Tuple[int, int], tile: int = 32
) -> Image.Image:
    """Take the window of exactly ``size`` holding the most subject.

    The frame is generated larger than it ships and this chooses which part
    ships: slide a target-sized window, keep the placement with the most ink
    boundaries in it. Cropping rather than re-prompting is the cheap lever —
    the subject Flux drew is usually good, it is just sharing the frame with a
    lot of style reference, and the reference always loses this competition
    because large flat shapes carry no boundaries.

    Exact output size in, exact output size out: ``--ar 3:4`` still delivers
    3:4 at full resolution, not whatever shape the subject happened to take.
    """
    target_w, target_h = int(size[0]), int(size[1])
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"crop size must be positive, got {size}")
    if img.width <= target_w or img.height <= target_h:
        return img.copy()

    density = detail_map(img, palette, tile)
    if density.size == 0 or density.sum() <= 0:
        return img.copy()

    window_h = max(1, target_h // tile)
    window_w = max(1, target_w // tile)
    integral = np.pad(density.cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    best_score, best_yx = -1.0, (0, 0)
    for y in range(density.shape[0] - window_h + 1):
        for x in range(density.shape[1] - window_w + 1):
            score = (
                integral[y + window_h, x + window_w]
                - integral[y, x + window_w]
                - integral[y + window_h, x]
                + integral[y, x]
            )
            if score > best_score:
                best_score, best_yx = float(score), (y, x)

    top = min(best_yx[0] * tile, img.height - target_h)
    left = min(best_yx[1] * tile, img.width - target_w)
    return img.crop((left, top, left + target_w, top + target_h))


def palette_lock(
    img: Image.Image, palette: Palette, mode: str = "nearest"
) -> Image.Image:
    """Quantise every pixel to a palette colour. No dithering, ever — the look
    is flat plates and dithering would smuggle gradients back in.

    Two mappings, because they fail in opposite directions:

    ``nearest`` (default) picks the closest swatch in Oklab. Right when the
    source already lives near the palette. When it does not — and Redux output
    rarely does, since the reference contributes flatness but not hue — every
    pixel can land on the *same* swatch and the image collapses to one field.

    ``luma`` ignores source hue and maps lightness bands onto the palette's own
    lightness order. Form always survives, so it is the mapping a generated
    frame wants; the cost is that source colour no longer chooses the ink.
    """
    colors = [tuple(int(c) for c in entry) for entry in palette]
    if len(colors) < 2:
        raise ValueError(f"palette needs at least 2 colours, got {len(colors)}")
    if mode not in PALETTE_MODES:
        raise ValueError(f"mode must be one of {PALETTE_MODES}, got {mode!r}")

    arr = _to_array(img)
    index = _lock_nearest(arr, colors) if mode == "nearest" else _lock_luma(arr, colors)
    return _to_image(np.asarray(colors, dtype=np.uint8)[index])


def grain(img: Image.Image, amount: float, seed: int, scale: int = 2) -> Image.Image:
    """Add monochromatic screenprint grain, uniform across the whole frame.

    ``amount`` is 0..1, scaled to a symmetric integer range of 8-bit levels.
    One noise plane is shared by R, G and B, so the grain shifts value without
    tinting — photo noise is per-channel, screenprint grain is not.

    ``scale`` is the tooth size in px, defaulting to the 2px specified in the
    look spec. At 1 the grain is per-pixel, which at ~1024px reads as sensor
    noise; 2–3 gives the coarser tooth of ink sitting on paper. Raising it does
    not change the amplitude, only the clump size.
    """
    if not 0.0 <= amount <= 1.0:
        raise ValueError(f"amount must be in 0..1, got {amount}")
    if scale < 1:
        raise ValueError(f"scale must be at least 1, got {scale}")

    arr = _to_array(img)
    span = int(round(amount * 255))
    if span == 0:
        return _to_image(arr)

    height, width = arr.shape[:2]
    rng = np.random.default_rng(seed)
    coarse = rng.integers(
        -span,
        span + 1,
        size=(-(-height // scale), -(-width // scale)),
        dtype=np.int16,
    )
    noise = np.repeat(np.repeat(coarse, scale, axis=0), scale, axis=1)
    noise = noise[:height, :width]

    grained = arr.astype(np.int16) + noise[:, :, None]
    return _to_image(np.clip(grained, 0, 255))


def halftone(
    img: Image.Image, angle: float, cell: float, strength: float = 1.0
) -> Image.Image:
    """Screen the image with rotated halftone dots driven by luminance.

    ``angle`` in degrees, ``cell`` is the dot pitch in px. Dots grow as the
    area darkens, and darken the plate by ``strength`` (0..1) where they land —
    an ink overlay on a duplicated luminance channel, not a replacement.
    """
    if cell <= 0:
        raise ValueError(f"cell must be positive, got {cell}")
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"strength must be in 0..1, got {strength}")

    arr = _to_array(img)
    if strength == 0.0:
        return _to_image(arr)

    values = arr.astype(np.float32)
    luma = (
        _LUMA[0] * values[..., 0] + _LUMA[1] * values[..., 1] + _LUMA[2] * values[..., 2]
    ) / 255.0

    height, width = luma.shape
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    theta = np.deg2rad(float(angle))
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    u = (xs * cos_t + ys * sin_t) / cell
    v = (-xs * sin_t + ys * cos_t) / cell

    # Distance from the nearest rotated cell centre, normalised so the
    # inscribed circle of a cell is radius 1.
    du = u - np.floor(u) - 0.5
    dv = v - np.floor(v) - 0.5
    radius = np.sqrt(du * du + dv * dv) * 2.0

    dots = radius < np.sqrt(np.clip(1.0 - luma, 0.0, 1.0))
    factor = np.where(dots, 1.0 - strength, 1.0).astype(np.float32)
    screened = np.rint(values * factor[:, :, None])
    return _to_image(np.clip(screened, 0, 255))


def misregister(img: Image.Image, px: int) -> Image.Image:
    """Offset the red and blue plates by ``px`` in opposite directions.

    Green holds the register, as it carries most of the luminance — so the
    image stays legible while the edges fringe the way a two-pass print does.
    """
    arr = _to_array(img)
    offset = int(px)
    if offset == 0:
        return _to_image(arr)

    out = arr.copy()
    out[..., 0] = _shift_plane(arr[..., 0], offset, 0)
    out[..., 2] = _shift_plane(arr[..., 2], -offset, 0)
    return _to_image(out)


# --------------------------------------------------------------------------
# preset chaining
# --------------------------------------------------------------------------


def compose(img: Image.Image, preset: Preset) -> Image.Image:
    """Run the post-pass described by ``preset``.

    Every step is optional; omit a key to skip it. ``palette`` takes a palette
    name, a path, or an explicit list of RGB triples::

        {
            "palette": "tennis-felt",
            "palette_mode": "luma",   # "nearest" (default) or "luma"
            "halftone": {"angle": 15, "cell": 4, "strength": 0.25},
            "misregister": {"px": 2},
            "grain": {"amount": 0.12, "seed": 7},
        }
    """
    unknown = set(preset) - {
        "palette",
        "palette_mode",
        "halftone",
        "misregister",
        "grain",
    }
    if unknown:
        raise ValueError(f"unknown preset keys: {sorted(unknown)}")

    out = img
    palette = preset.get("palette")
    if palette is not None:
        colors = (
            load_palette(palette) if isinstance(palette, (str, Path)) else list(palette)
        )
        out = palette_lock(out, colors, preset.get("palette_mode", "nearest"))

    screen = preset.get("halftone")
    if screen is not None:
        out = halftone(out, **screen)

    offset = preset.get("misregister")
    if offset is not None:
        out = misregister(out, **offset)

    speckle = preset.get("grain")
    if speckle is not None:
        out = grain(out, **speckle)

    return out
