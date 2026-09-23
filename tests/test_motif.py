"""Offline geometric-poster lane: repeatable plates before press texture."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from riso import motif, post


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _colors(image: Image.Image) -> set[tuple[int, int, int]]:
    pixels = np.asarray(image.convert("RGB")).reshape(-1, 3)
    return {tuple(int(channel) for channel in pixel) for pixel in pixels}


@pytest.mark.parametrize("name", motif.available_motifs())
def test_every_motif_is_sized_flat_and_uses_only_the_palette(name):
    image = motif.render(name, "egypt-cobalt", (240, 360), seed=7)
    palette = set(post.load_palette("egypt-cobalt"))
    assert image.size == (240, 360)
    assert image.mode == "RGB"
    assert 2 <= len(_colors(image)) <= len(palette)
    assert _colors(image) <= palette


@pytest.mark.parametrize("name", motif.available_motifs())
def test_every_motif_has_real_ink_coverage(name):
    image = motif.render(name, "egypt-cobalt", (240, 360), seed=3)
    ink = post.load_palette("egypt-cobalt")[0]
    arr = np.asarray(image)
    coverage = np.all(arr == np.asarray(ink), axis=2).mean()
    assert 0.08 < coverage < 0.92


def test_motif_same_seed_is_byte_identical():
    first = motif.render("mosaic", seed=19)
    second = motif.render("mosaic", seed=19)
    assert _png_bytes(first) == _png_bytes(second)


def test_motif_different_seed_changes_the_geometry():
    first = motif.render("rays", seed=1)
    second = motif.render("rays", seed=2)
    assert _png_bytes(first) != _png_bytes(second)


def test_motif_rejects_unknown_name_bad_size_and_bad_density():
    with pytest.raises(ValueError, match="motif must be"):
        motif.render("obelisk")
    with pytest.raises(ValueError, match="size must be positive"):
        motif.render("crowd", size=(0, 100))
    with pytest.raises(ValueError, match="density must be"):
        motif.render("crowd", density=0.1)


def test_motif_accepts_an_inline_two_color_palette():
    palette = [(4, 20, 80), (240, 230, 210)]
    assert _colors(motif.render("ripples", palette, (120, 180), seed=1)) <= set(palette)
