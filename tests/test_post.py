"""Phase 1 gate: seeded output is reproducible, and palette_lock locks."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from riso import post

PRESET = {
    "palette": "tennis-felt",
    "halftone": {"angle": 15, "cell": 5, "strength": 0.3},
    "misregister": {"px": 2},
    "grain": {"amount": 0.12, "seed": 7},
}


def _rgb_cube(step: int = 16) -> Image.Image:
    """Every corner of the RGB cube, so any sane palette is fully exercised."""
    levels = np.arange(0, 256, step, dtype=np.uint8)
    grid = np.stack(np.meshgrid(levels, levels, levels, indexing="ij"), axis=-1)
    side = int(round(len(levels) ** 1.5))
    return Image.fromarray(grid.reshape(side, side, 3), mode="RGB")


def _noise_image(seed: int = 0, size: int = 96) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _png_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _unique_colors(img: Image.Image) -> set:
    arr = np.asarray(img.convert("RGB"))
    return {tuple(int(c) for c in row) for row in arr.reshape(-1, 3)}


# --- gate (a): same seed -> byte-identical output --------------------------


def test_compose_same_seed_is_byte_identical():
    source = _noise_image()
    first = post.compose(source, PRESET)
    second = post.compose(source, PRESET)
    assert _png_bytes(first) == _png_bytes(second)


def test_grain_same_seed_is_byte_identical():
    source = _noise_image()
    assert _png_bytes(post.grain(source, 0.2, seed=42)) == _png_bytes(
        post.grain(source, 0.2, seed=42)
    )


def test_grain_different_seed_differs():
    source = _noise_image()
    assert _png_bytes(post.grain(source, 0.2, seed=42)) != _png_bytes(
        post.grain(source, 0.2, seed=43)
    )


def test_compose_is_stable_across_a_reloaded_image():
    """Determinism has to survive a round trip through disk, not just RAM."""
    source = _noise_image()
    once = post.compose(source, PRESET)
    reloaded = Image.open(io.BytesIO(_png_bytes(source)))
    assert _png_bytes(post.compose(reloaded, PRESET)) == _png_bytes(once)


# --- gate (b): palette_lock yields exactly N unique colours ----------------


@pytest.mark.parametrize("name", post.available_palettes())
def test_palette_lock_yields_exactly_n_colors(name):
    palette = post.load_palette(name)
    locked = post.palette_lock(_rgb_cube(), palette)
    assert _unique_colors(locked) == set(palette)
    assert len(_unique_colors(locked)) == len(palette)


def test_palette_lock_never_invents_a_color():
    palette = post.load_palette("riso-nightsea")
    locked = post.palette_lock(_noise_image(seed=3), palette)
    assert _unique_colors(locked) <= set(palette)


def test_palette_lock_is_idempotent():
    """Re-locking an already-locked plate must not drift."""
    palette = post.load_palette("tennis-felt")
    once = post.palette_lock(_rgb_cube(), palette)
    assert _png_bytes(post.palette_lock(once, palette)) == _png_bytes(once)


def test_palette_lock_rejects_a_one_color_palette():
    with pytest.raises(ValueError):
        post.palette_lock(_noise_image(), [(0, 0, 0)])


# --- luma mode: the separation that survives an off-palette source ----------


def _blue_ramp() -> Image.Image:
    """A frame like Redux actually returns: all one hue, nothing near the palette."""
    height, width = 64, 64
    ramp = np.linspace(40, 210, height, dtype=np.uint8)[:, None].repeat(width, axis=1)
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[..., 2] = ramp
    arr[..., 0] = ramp // 4
    return Image.fromarray(arr, mode="RGB")


def test_luma_mode_keeps_form_where_nearest_collapses_it():
    palette = post.load_palette("tennis-felt")
    source = _blue_ramp()
    assert len(_unique_colors(post.palette_lock(source, palette))) <= 2
    assert len(_unique_colors(post.palette_lock(source, palette, "luma"))) == len(palette)


def test_luma_mode_lays_ink_down_dark_to_light():
    """Darker source, darker ink — the ordering is the whole mechanism."""
    palette = post.load_palette("riso-nightsea")
    locked = np.asarray(post.palette_lock(_blue_ramp(), palette, "luma"), dtype=np.float32)
    lightness = post._srgb_to_oklab(locked / 255.0)[..., 0]
    assert np.all(np.diff(lightness.mean(axis=1)) >= 0)


def test_luma_mode_never_invents_a_color():
    palette = post.load_palette("riso-nightsea")
    locked = post.palette_lock(_noise_image(seed=5), palette, "luma")
    assert _unique_colors(locked) <= set(palette)


def _bimodal_frame() -> Image.Image:
    """Dark figures on a light ground and nothing between — a generated frame.

    Equal-width bands leave the middle inks unused on this; quantile bands
    cannot, because every band holds the same number of pixels.
    """
    arr = np.full((80, 80, 3), 235, dtype=np.uint8)
    arr[40:, :, :] = 30
    arr[10:20, 10:70] = 240  # a second light plate, slightly off the ground
    arr[60:70, 10:70] = 25  # and a second dark one
    return Image.fromarray(arr, mode="RGB")


def test_luma_mode_keeps_a_near_flat_plate_whole():
    """The regression that killed quantile banding.

    A generated plate is never *exactly* flat — it carries a level or two of
    sampling wobble. Bands cut by pixel population split that wobble between
    two inks and the plate comes out mottled. Bands cut by lightness width do
    not, and a plate that covers most of the frame must survive intact.
    """
    palette = post.load_palette("tennis-felt")
    rng = np.random.default_rng(0)
    arr = np.full((90, 90, 3), 210, dtype=np.uint8)
    arr[:70] += rng.integers(0, 2, size=(70, 90, 1), dtype=np.uint8)  # the wobble
    arr[70:] = 30  # dark figures, so the frame has real structure too

    locked = np.asarray(post.palette_lock(Image.fromarray(arr, "RGB"), palette, "luma"))
    assert len(_unique_colors(Image.fromarray(locked[:70]))) == 1


def test_luma_mode_still_separates_the_plates_it_is_given():
    palette = post.load_palette("tennis-felt")
    locked = post.palette_lock(_bimodal_frame(), palette, "luma")
    assert 2 <= len(_unique_colors(locked)) <= len(_unique_colors(_bimodal_frame()))


def test_luma_mode_lays_one_ink_on_a_featureless_frame():
    """A dead generation must stay dead, not become speckle."""
    palette = post.load_palette("tennis-felt")
    arr = np.full((32, 32, 3), 90, dtype=np.uint8)
    arr[..., 2] = 180
    arr[::2, ::2, 2] = 181  # sampling noise, nothing more
    flat = Image.fromarray(arr, mode="RGB")

    assert post.tonal_span(flat) < post.FLAT_FRAME_SPAN
    assert len(_unique_colors(post.palette_lock(flat, palette, "luma"))) == 1


def test_tonal_span_separates_a_real_frame_from_a_dead_one():
    assert post.tonal_span(_blue_ramp()) > post.FLAT_FRAME_SPAN
    assert post.tonal_span(Image.new("RGB", (16, 16), (10, 60, 160))) == 0.0


def test_palette_lock_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        post.palette_lock(_noise_image(), post.load_palette("tennis-felt"), "median")


def test_compose_passes_the_mode_through():
    palette = post.load_palette("tennis-felt")
    source = _blue_ramp()
    banded = post.compose(source, {"palette": "tennis-felt", "palette_mode": "luma"})
    assert _png_bytes(banded) == _png_bytes(post.palette_lock(source, palette, "luma"))
    assert _png_bytes(post.compose(source, {"palette": "tennis-felt"})) == _png_bytes(
        post.palette_lock(source, palette)
    )


# --- the individual steps --------------------------------------------------


def test_grain_is_monochromatic():
    """The same noise plane in all three channels: value shifts, no tint."""
    flat = Image.new("RGB", (64, 64), (128, 128, 128))
    arr = np.asarray(post.grain(flat, 0.2, seed=1), dtype=np.int16)
    assert np.array_equal(arr[..., 0], arr[..., 1])
    assert np.array_equal(arr[..., 1], arr[..., 2])


def test_grain_amount_zero_is_identity():
    source = _noise_image()
    assert _png_bytes(post.grain(source, 0.0, seed=9)) == _png_bytes(source)


def test_grain_amount_scales_deviation():
    flat = Image.new("RGB", (128, 128), (128, 128, 128))
    light = np.asarray(post.grain(flat, 0.05, seed=2), dtype=np.float64)
    heavy = np.asarray(post.grain(flat, 0.3, seed=2), dtype=np.float64)
    assert heavy.std() > light.std() > 0


def test_grain_scale_clumps_the_particles():
    """scale=n must produce n-px blocks, and keep the same amplitude."""
    flat = Image.new("RGB", (64, 64), (128, 128, 128))
    coarse = np.asarray(post.grain(flat, 0.2, seed=4, scale=4), dtype=np.int16)
    block = coarse[0:4, 0:4, 0]
    assert np.all(block == block[0, 0])
    fine = np.asarray(post.grain(flat, 0.2, seed=4, scale=1), dtype=np.int16)
    assert abs(coarse.std() - fine.std()) < 3.0


def test_grain_defaults_to_the_specified_2px_tooth():
    """The look spec fixes the default tooth; a silent drift to 1 is a regression."""
    flat = Image.new("RGB", (64, 64), (128, 128, 128))
    assert _png_bytes(post.grain(flat, 0.2, seed=8)) == _png_bytes(
        post.grain(flat, 0.2, seed=8, scale=2)
    )


def test_grain_scale_handles_a_ragged_edge():
    """A size that is not a multiple of scale must still come back whole."""
    source = _noise_image(size=70)
    assert post.grain(source, 0.2, seed=5, scale=3).size == (70, 70)


def test_grain_scale_below_one_is_rejected():
    with pytest.raises(ValueError):
        post.grain(_noise_image(), 0.2, seed=1, scale=0)


def test_misregister_moves_red_and_blue_but_holds_green():
    source = _noise_image()
    shifted = np.asarray(post.misregister(source, 2))
    original = np.asarray(source)
    assert np.array_equal(shifted[..., 1], original[..., 1])
    assert not np.array_equal(shifted[..., 0], original[..., 0])
    assert not np.array_equal(shifted[..., 2], original[..., 2])
    # Opposite directions: red lands where red used to be, two px left.
    assert np.array_equal(shifted[:, 2:, 0], original[:, :-2, 0])
    assert np.array_equal(shifted[:, :-2, 2], original[:, 2:, 2])


def test_misregister_zero_is_identity():
    source = _noise_image()
    assert _png_bytes(post.misregister(source, 0)) == _png_bytes(source)


def test_halftone_darkens_and_stays_put():
    source = Image.new("RGB", (128, 128), (160, 160, 160))
    screened = np.asarray(post.halftone(source, angle=15, cell=6), dtype=np.float64)
    assert screened.mean() < 160.0
    assert screened.shape == (128, 128, 3)


def test_halftone_angle_changes_the_screen():
    source = _noise_image(seed=5, size=128)
    assert _png_bytes(post.halftone(source, 0, 6)) != _png_bytes(
        post.halftone(source, 45, 6)
    )


def test_halftone_strength_zero_is_identity():
    source = _noise_image()
    assert _png_bytes(post.halftone(source, 15, 6, strength=0.0)) == _png_bytes(source)


def test_steps_preserve_size_and_mode():
    source = _noise_image(size=70)
    for result in (
        post.palette_lock(source, post.load_palette("tennis-felt")),
        post.grain(source, 0.1, seed=1),
        post.halftone(source, 15, 4),
        post.misregister(source, 1),
        post.compose(source, PRESET),
    ):
        assert result.size == (70, 70)
        assert result.mode == "RGB"


def test_rgba_input_is_accepted():
    source = Image.new("RGBA", (32, 32), (200, 30, 60, 128))
    assert post.compose(source, PRESET).mode == "RGB"


# --- palettes are data -----------------------------------------------------


def test_starter_palettes_load():
    assert set(post.available_palettes()) >= {"tennis-felt", "riso-nightsea"}
    for name in ("tennis-felt", "riso-nightsea"):
        palette = post.load_palette(name)
        assert 3 <= len(palette) <= 5
        assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in palette)


def test_palette_loads_by_path_too():
    path = post.PALETTE_DIR / "tennis-felt.json"
    assert post.load_palette(path) == post.load_palette("tennis-felt")


def test_missing_palette_is_a_clear_error():
    with pytest.raises(FileNotFoundError):
        post.load_palette("no-such-palette")


def test_bad_hex_is_a_clear_error(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"colors": ["#12345", "#000000"]}', encoding="utf-8")
    with pytest.raises(ValueError):
        post.load_palette(bad)


# --- compose ---------------------------------------------------------------


def test_compose_skips_omitted_steps():
    source = _noise_image()
    assert _png_bytes(post.compose(source, {})) == _png_bytes(source)


def test_compose_palette_only_keeps_exactly_n_colors():
    locked = post.compose(_rgb_cube(), {"palette": "tennis-felt"})
    assert len(_unique_colors(locked)) == 5


def test_compose_accepts_an_inline_palette():
    inline = [(0, 0, 0), (255, 255, 255)]
    locked = post.compose(_noise_image(), {"palette": inline})
    assert _unique_colors(locked) <= set(inline)


def test_compose_rejects_a_typo_in_the_preset():
    with pytest.raises(ValueError, match="unknown preset keys"):
        post.compose(_noise_image(), {"pallette": "tennis-felt"})


# --- content_crop: pick the window with the subject in it -------------------


def _subject_in_corner() -> Image.Image:
    """A busy patch in one corner of an otherwise flat frame."""
    rng = np.random.default_rng(4)
    arr = np.full((400, 400, 3), 230, dtype=np.uint8)
    arr[:120, :120] = rng.integers(0, 255, size=(120, 120, 3), dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


def test_content_crop_finds_the_subject():
    palette = post.load_palette("tennis-felt")
    cropped = post.content_crop(_subject_in_corner(), palette, (160, 160))
    assert cropped.size == (160, 160)
    # the busy corner is the top-left, so the crop must sit there
    detail = post.detail_map(cropped, palette)
    assert detail.mean() > post.detail_map(_subject_in_corner(), palette).mean()


def test_content_crop_returns_the_requested_size_exactly():
    palette = post.load_palette("tennis-felt")
    for size in [(160, 160), (96, 300), (399, 128)]:
        assert post.content_crop(_subject_in_corner(), palette, size).size == size


def test_content_crop_is_a_no_op_when_the_target_is_not_smaller():
    palette = post.load_palette("tennis-felt")
    source = _subject_in_corner()
    assert post.content_crop(source, palette, (400, 400)).size == (400, 400)
    assert post.content_crop(source, palette, (500, 500)).size == (400, 400)


def test_content_crop_rejects_a_nonsense_size():
    palette = post.load_palette("tennis-felt")
    with pytest.raises(ValueError):
        post.content_crop(_subject_in_corner(), palette, (0, 100))


def test_detail_map_separates_a_crowd_from_a_flat_plane():
    palette = post.load_palette("tennis-felt")
    flat = Image.new("RGB", (256, 256), (200, 90, 70))
    assert post.detail_map(flat, palette).mean() < 0.01
    assert post.detail_map(_subject_in_corner(), palette).mean() > 0.01
