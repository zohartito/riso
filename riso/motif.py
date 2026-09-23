"""Deterministic geometric-poster primitives for ``riso motif``.

The ComfyUI lane is good at dense semantic subjects and poor at sparse poster
geometry.  This module handles the opposite case without a model: repeated
figures, radial fields, folded peaks, ripples and abstract mosaics drawn as
flat plates.  The press texture still comes from :mod:`riso.post` afterwards.

No renderer traces a source illustration.  Each is a small generative system
whose seed and density are recorded, so a useful result is reproducible and a
series can vary without drifting into another visual language.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Sequence, Tuple, Union

import numpy as np
from PIL import Image, ImageDraw

from riso import post

RGB = Tuple[int, int, int]
PaletteSource = Union[str, Path, Sequence[RGB]]
Box = Tuple[int, int, int, int]
Renderer = Callable[
    [ImageDraw.ImageDraw, Box, RGB, RGB, RGB, np.random.Generator, float], None
]

MOTIFS = ("crowd", "rays", "peaks", "ripples", "mosaic")


def available_motifs() -> List[str]:
    """Names accepted by :func:`render`."""
    return list(MOTIFS)


def _relative_luma(color: RGB) -> float:
    """Enough ordering for choosing ink, field and paper from a palette."""
    rgb = np.asarray(color, dtype=np.float64) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])


def _plates(source: PaletteSource) -> Tuple[RGB, RGB, RGB]:
    if isinstance(source, (str, Path)):
        colors = post.load_palette(source)
    else:
        colors = [tuple(int(channel) for channel in color) for color in source]
    if len(colors) < 2:
        raise ValueError(f"motif palette needs at least 2 colours, got {len(colors)}")

    ordered = sorted(colors, key=_relative_luma)
    ink = ordered[0]
    paper = ordered[-1]
    field = ordered[-2] if len(ordered) > 2 else paper
    return ink, field, paper


def _crowd(
    draw: ImageDraw.ImageDraw,
    box: Box,
    ink: RGB,
    field: RGB,
    paper: RGB,
    rng: np.random.Generator,
    density: float,
) -> None:
    """A field of varied, adjacency-only human glyphs."""
    del paper
    left, top, right, bottom = box
    draw.rectangle(box, fill=ink)
    width, height = right - left, bottom - top
    cols = max(3, round(6 * density))
    rows = max(4, round(9 * density))
    cell_w, cell_h = width / cols, height / rows

    for row in range(rows):
        for col in range(cols):
            cx = left + (col + 0.5) * cell_w + rng.uniform(-0.09, 0.09) * cell_w
            cy = top + row * cell_h + rng.uniform(0.05, 0.14) * cell_h
            person_h = cell_h * rng.uniform(0.70, 0.90)
            shoulder = cell_w * rng.uniform(0.17, 0.25)
            stroke = max(2, round(min(cell_w, cell_h) * rng.uniform(0.10, 0.15)))
            head_r = max(2, round(stroke * rng.uniform(0.75, 1.05)))

            draw.ellipse(
                (cx - head_r, cy, cx + head_r, cy + 2 * head_r),
                fill=field,
            )
            neck_y = cy + 2.0 * head_r
            hip_y = cy + person_h * 0.62
            foot_y = min(bottom - 1, cy + person_h)
            sway = rng.uniform(-0.09, 0.09) * cell_w
            draw.line(
                [(cx, neck_y), (cx + sway, hip_y)],
                fill=field,
                width=stroke,
            )
            draw.line(
                [
                    (cx - shoulder, neck_y + stroke * 0.5),
                    (cx + sway, neck_y + stroke * 2.4),
                    (cx + shoulder, neck_y + stroke * 0.5),
                ],
                fill=field,
                width=stroke,
                joint="curve",
            )
            leg_gap = max(stroke, shoulder * 0.58)
            draw.line(
                [(cx + sway, hip_y), (cx + sway - leg_gap, foot_y)],
                fill=field,
                width=stroke,
            )
            draw.line(
                [(cx + sway, hip_y), (cx + sway + leg_gap, foot_y)],
                fill=field,
                width=stroke,
            )


def _rays(
    draw: ImageDraw.ImageDraw,
    box: Box,
    ink: RGB,
    field: RGB,
    paper: RGB,
    rng: np.random.Generator,
    density: float,
) -> None:
    """Uneven angular sectors around an off-centre void."""
    del paper
    left, top, right, bottom = box
    draw.rectangle(box, fill=field)
    width, height = right - left, bottom - top
    cx = left + width * rng.uniform(0.38, 0.62)
    cy = top + height * rng.uniform(0.40, 0.68)
    radius = math.hypot(width, height) * 1.7
    sectors = max(10, round(18 * density))
    weights = rng.uniform(0.65, 1.35, size=sectors)
    spans = weights / weights.sum() * math.tau
    angle = rng.uniform(-math.pi, math.pi)

    for index, span in enumerate(spans):
        start = angle
        end = angle + float(span) * rng.uniform(0.80, 0.97)
        if index % 2 == 0:
            a = (cx + radius * math.cos(start), cy + radius * math.sin(start))
            b = (cx + radius * math.cos(end), cy + radius * math.sin(end))
            draw.polygon([(cx, cy), a, b], fill=ink)
        angle += float(span)

    # Break the mechanically perfect convergence without adding an icon.
    knot = min(width, height) * rng.uniform(0.035, 0.065)
    points = []
    for index in range(9):
        theta = math.tau * index / 9
        radius_i = knot * rng.uniform(0.65, 1.15)
        points.append((cx + math.cos(theta) * radius_i, cy + math.sin(theta) * radius_i))
    draw.polygon(points, fill=field)


def _peaks(
    draw: ImageDraw.ImageDraw,
    box: Box,
    ink: RGB,
    field: RGB,
    paper: RGB,
    rng: np.random.Generator,
    density: float,
) -> None:
    """A staggered field of folded pennants with visible negative space."""
    del paper
    left, top, right, bottom = box
    draw.rectangle(box, fill=field)
    width, height = right - left, bottom - top
    cols = max(4, round(6 * density))
    rows = max(5, round(8 * density))
    cell_w, cell_h = width / cols, height / rows

    for row in range(rows + 1):
        offset = -0.5 * cell_w if row % 2 else 0.0
        for col in range(cols + 1):
            cx = left + (col + 0.5) * cell_w + offset
            peak_y = top + row * cell_h - cell_h * rng.uniform(0.12, 0.42)
            base_y = peak_y + cell_h * rng.uniform(1.05, 1.42)
            half = cell_w * rng.uniform(0.31, 0.43)
            lean = cell_w * rng.uniform(-0.16, 0.16)
            notch = cell_h * rng.uniform(0.48, 0.72)
            draw.polygon(
                [
                    (cx + lean, peak_y),
                    (cx + half, peak_y + notch),
                    (cx + half * 0.64, base_y),
                    (cx - half * 0.64, base_y),
                    (cx - half, peak_y + notch),
                ],
                fill=ink,
            )


def _ripples(
    draw: ImageDraw.ImageDraw,
    box: Box,
    ink: RGB,
    field: RGB,
    paper: RGB,
    rng: np.random.Generator,
    density: float,
) -> None:
    """Alternating contour bands with no horizon, moon or landmark."""
    del paper
    left, top, right, bottom = box
    draw.rectangle(box, fill=ink)
    width, height = right - left, bottom - top
    bands = max(10, round(20 * density))
    step_y = height / bands
    samples = max(24, round(width / 18))
    phase = rng.uniform(0, math.tau)

    for band in range(0, bands, 2):
        y0 = top + band * step_y
        y1 = min(bottom, y0 + step_y * rng.uniform(0.62, 1.12))
        amp = step_y * rng.uniform(0.16, 0.46) * (0.7 + band / max(1, bands))
        freq = rng.uniform(1.2, 3.4)
        upper = []
        lower = []
        for sample in range(samples + 1):
            t = sample / samples
            x = left + t * width
            wobble = math.sin(t * math.tau * freq + phase + band * 0.31)
            wobble += 0.35 * math.sin(t * math.tau * (freq * 2.3) - phase)
            jitter = rng.uniform(-0.08, 0.08) * step_y
            upper.append((x, y0 + wobble * amp + jitter))
            lower.append((x, y1 + wobble * amp * 0.72 + jitter))
        draw.polygon(upper + list(reversed(lower)), fill=field)


def _mosaic(
    draw: ImageDraw.ImageDraw,
    box: Box,
    ink: RGB,
    field: RGB,
    paper: RGB,
    rng: np.random.Generator,
    density: float,
) -> None:
    """A balanced, low-frequency field of interlocking organic regions."""
    del paper
    left, top, right, bottom = box
    draw.rectangle(box, fill=field)
    width, height = right - left, bottom - top
    grid_w = max(4, round(6 * math.sqrt(density)))
    grid_h = max(6, round(grid_w * height / max(1, width)))
    noise = rng.integers(0, 256, size=(grid_h, grid_w), dtype=np.uint8)
    smooth = Image.fromarray(noise, mode="L").resize(
        (width + 1, height + 1), Image.Resampling.BICUBIC
    )
    values = np.asarray(smooth)
    threshold = float(np.median(values))
    mask = Image.fromarray(np.where(values > threshold, 255, 0).astype(np.uint8), mode="L")
    draw.bitmap((left, top), mask, fill=ink)


_RENDERERS: dict[str, Renderer] = {
    "crowd": _crowd,
    "rays": _rays,
    "peaks": _peaks,
    "ripples": _ripples,
    "mosaic": _mosaic,
}


def render(
    motif: str,
    palette: PaletteSource = "egypt-cobalt",
    size: Tuple[int, int] = (768, 1152),
    seed: int = 0,
    density: float = 1.0,
) -> Image.Image:
    """Render one exact-palette geometric plate.

    The returned image contains palette colours only.  Apply
    :func:`riso.post.compose` afterwards for misregistration and grain.
    """
    if motif not in _RENDERERS:
        raise ValueError(f"motif must be one of {MOTIFS}, got {motif!r}")
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {size}")
    if not 0.25 <= density <= 3.0:
        raise ValueError(f"density must be in 0.25..3.0, got {density}")

    ink, field, paper = _plates(palette)
    image = Image.new("RGB", (width, height), paper)
    margin = max(4, round(min(width, height) * 0.035))
    inner_w, inner_h = width - 2 * margin, height - 2 * margin
    inner = Image.new("RGB", (inner_w, inner_h), field)
    inner_box = (0, 0, inner_w - 1, inner_h - 1)
    _RENDERERS[motif](
        ImageDraw.Draw(inner),
        inner_box,
        ink,
        field,
        paper,
        np.random.default_rng(seed),
        density,
    )
    image.paste(inner, (margin, margin))
    return image
