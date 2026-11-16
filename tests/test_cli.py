"""Phase 3 CLI: aspect ratios, style presets, and the generation chain.

The ComfyUI half is stubbed — these prove the wiring and the framing maths,
not the model. What the model does is judged by eye, in docs/.
"""

from __future__ import annotations

import json
import math

import pytest
from PIL import Image

from riso import cli, styles


# -- aspect ratio -> pixel size --------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [("3:4", (3, 4)), ("16:9", (16, 9)), (" 1 : 1 ", (1, 1)), ("3x4", (3, 4))],
)
def test_parse_aspect(text, expected):
    assert cli.parse_aspect(text) == expected


@pytest.mark.parametrize("bad", ["3/4", "3:", "", "a:b", "0:4"])
def test_parse_aspect_rejects_junk(bad):
    with pytest.raises(ValueError):
        cli.parse_aspect(bad)


def test_dimensions_are_latent_sized_and_near_one_megapixel():
    for ratio in [(1, 1), (3, 4), (4, 3), (16, 9)]:
        width, height = cli.dimensions(ratio)
        assert width % cli.LATENT_MULTIPLE == 0
        assert height % cli.LATENT_MULTIPLE == 0
        assert 0.85 <= (width * height) / cli.BASE_PIXELS**2 <= 1.15


def test_dimensions_follow_the_ratio():
    width, height = cli.dimensions((3, 4))
    assert width < height
    assert math.isclose(width / height, 3 / 4, rel_tol=0.05)


def test_slugify():
    assert cli.slugify("a crowd of tennis spectators!") == "a-crowd-of-tennis-spectators"
    assert cli.slugify("...") == "untitled"


# -- style presets ----------------------------------------------------------


def test_tennis_preset_is_loadable_and_in_band():
    style = styles.load_style("tennis")
    low, high = styles.STRENGTH_BAND
    assert low <= style["generate"]["strength"] <= high
    assert style["generate"]["ref"].is_file()
    assert style["post"]["palette"] == "tennis-felt"


def test_tennis_preset_post_table_is_a_valid_compose_preset():
    from riso import post

    style = styles.load_style("tennis")
    swatch = Image.new("RGB", (16, 16), (120, 130, 140))
    assert post.compose(swatch, cli._post_preset(style, seed=1)).size == (16, 16)


def test_load_style_rejects_a_missing_reference(tmp_path):
    preset = tmp_path / "ghost.toml"
    preset.write_text('[generate]\nref = "refs/not-here.png"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        styles.load_style(preset)


def test_grain_seed_falls_back_to_the_run_seed():
    style = styles.load_style("tennis")
    assert cli._post_preset(style, seed=99)["grain"]["seed"] == 99


def test_a_pinned_grain_seed_wins(tmp_path):
    ref = styles.REPO_ROOT / "refs" / "style-riso-poster.png"
    preset = tmp_path / "pinned.toml"
    preset.write_text(
        f'[generate]\nref = "{ref.as_posix()}"\n'
        "[post.grain]\namount = 0.1\nseed = 5\n",
        encoding="utf-8",
    )
    style = styles.load_style(preset)
    assert cli._post_preset(style, seed=99)["grain"]["seed"] == 5


# -- the chain --------------------------------------------------------------


class _StubComfy:
    """Stands in for a running ComfyUI; records what the CLI asked it for."""

    last_workflow = None

    def __init__(self, host="127.0.0.1:8188", timeout=30.0):
        self.host = host

    def is_up(self):
        return True

    def upload_image(self, path, overwrite=True):
        return f"uploaded-{path.name}"

    def generate(self, workflow, timeout=900.0):
        type(self).last_workflow = workflow
        buffer = __import__("io").BytesIO()
        Image.new("RGB", (64, 64), (90, 110, 200)).save(buffer, format="PNG")
        return buffer.getvalue()


def test_gen_writes_a_finished_png_and_a_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Comfy", _StubComfy)
    out = tmp_path / "shot.png"

    written = cli.generate(
        "a crowd of tennis spectators seen from behind",
        "tennis",
        aspect="3:4",
        seed=4242,
        out=out,
        keep_raw=True,
    )

    assert written == out and out.is_file()
    with Image.open(out) as art:
        # cropping to the subject must not change what the caller asked for:
        # --ar 3:4 delivers 3:4 at full size, whatever the crop threw away
        assert art.size == (864, 1152)
        assert art.width * 4 == art.height * 3
    assert out.with_name("shot-raw.png").is_file()

    record = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["seed"] == 4242
    assert record["size"] == [864, 1152]
    assert record["latent_size"] == list(cli.dimensions((3, 4)))
    assert record["model"] == "flux1-schnell-fp8.safetensors"
    assert record["post"]["grain"]["seed"] == 4242
    assert "Non-Commercial" in record["licence"]
    assert record["style_ref"] == "refs/style-flat-mosaic.png"  # portable across machines


def test_gen_patches_the_workflow_from_the_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Comfy", _StubComfy)
    cli.generate("a lighthouse", "tennis", aspect="3:4", seed=7, out=tmp_path / "a.png")

    workflow = _StubComfy.last_workflow
    sent = workflow["positive"]["inputs"]["text"]
    assert sent.startswith("a lighthouse")
    assert "no gradients" in sent  # the preset's flatness clause rides along
    assert workflow["style_ref"]["inputs"]["image"] == "uploaded-style-flat-mosaic.png"
    assert workflow["style_apply"]["inputs"]["strength"] == 0.08
    assert workflow["sampler"]["inputs"]["seed"] == 7
    width, height = cli.dimensions((3, 4))
    assert workflow["latent"]["inputs"]["width"] == width
    assert workflow["latent"]["inputs"]["height"] == height


def test_gen_reports_a_dead_comfyui_instead_of_traceback(capsys, monkeypatch):
    class _Down(_StubComfy):
        def is_up(self):
            return False

    monkeypatch.setattr(cli, "Comfy", _Down)
    assert cli.main(["gen", "anything", "--style", "tennis"]) == 1
    assert "systemctl --user start comfyui" in capsys.readouterr().err


def test_styles_subcommand_lists_presets(capsys):
    assert cli.main(["styles"]) == 0
    assert "tennis" in capsys.readouterr().out.split()


def test_dead_comfyui_points_to_a_public_launch_command(capsys, monkeypatch):
    class Down(_StubComfy):
        def is_up(self):
            return False

    monkeypatch.setattr(cli, "Comfy", Down)
    assert cli.main(["gen", "anything", "--style", "tennis"]) == 1
    error = capsys.readouterr().err
    assert "python main.py --listen 127.0.0.1 --port 8188" in error
    assert "docs/generation-box.md" in error


def test_default_outputs_keep_prompts_with_the_same_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Comfy", _StubComfy)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path)
    prefix = "a crowd of tennis spectators seen from behind at "
    first = cli.generate(prefix + "dawn", "tennis", seed=7)
    original = first.read_bytes()
    second = cli.generate(prefix + "dusk", "tennis", seed=7)
    assert first != second
    assert first.read_bytes() == original
    assert len(list(tmp_path.glob("*.png"))) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


@pytest.mark.parametrize("existing", ["shot.png", "shot.json", "shot-raw.png"])
def test_output_collision_is_rejected_before_generation(existing, tmp_path, monkeypatch):
    class Unused(_StubComfy):
        def is_up(self):
            pytest.fail("output conflicts must be checked before ComfyUI")

    monkeypatch.setattr(cli, "Comfy", Unused)
    target = tmp_path / existing
    target.write_bytes(b"keep this artifact")
    with pytest.raises(FileExistsError):
        cli.generate("crowd", "tennis", seed=7, out=tmp_path / "shot.png", keep_raw=True)
    assert target.read_bytes() == b"keep this artifact"


@pytest.mark.parametrize("aspect", ["3:4", "4:5", "4:3", "2:3", "16:9", "6:8", "1:1"])
@pytest.mark.parametrize("crop_keep", [0.71, 1.0])
def test_delivered_image_preserves_exact_aspect(aspect, crop_keep, tmp_path, monkeypatch):
    style = styles.load_style("tennis")
    style["generate"]["crop_keep"] = crop_keep
    monkeypatch.setattr(cli, "load_style", lambda name: style)
    monkeypatch.setattr(cli, "Comfy", _StubComfy)
    out = cli.generate("crowd", "tennis", aspect=aspect, seed=7, out=tmp_path / "art.png")
    a, b = cli.parse_aspect(aspect)
    with Image.open(out) as art:
        assert art.width * b == art.height * a
        assert 0.8 <= art.width * art.height / cli.BASE_PIXELS**2 <= 1.15
        assert json.loads(out.with_suffix(".json").read_text())["size"] == list(art.size)


def test_output_without_extension_saves_as_png(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Comfy", _StubComfy)
    out = cli.generate("crowd", "tennis", seed=7, out=tmp_path / "result")
    assert out == tmp_path / "result.png"
    with Image.open(out) as art:
        assert art.format == "PNG"


def test_unsupported_output_extension_fails_before_generation(tmp_path, monkeypatch):
    class Unused(_StubComfy):
        def is_up(self):
            pytest.fail("validate the extension before ComfyUI")

    monkeypatch.setattr(cli, "Comfy", Unused)
    with pytest.raises(ValueError, match="unsupported output extension"):
        cli.generate("crowd", "tennis", out=tmp_path / "result.unknown")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../../outside/pwn", "../pwn", "a/b", "a\\b", ""])
def test_preset_names_cannot_be_output_paths(name, tmp_path):
    preset = tmp_path / "unsafe.toml"
    preset.write_text(f'name = {json.dumps(name)}\n[generate]\nref = "refs/style-flat-mosaic.png"\n')
    with pytest.raises(ValueError, match="style name"):
        styles.load_style(preset)


@pytest.mark.parametrize("kind", ["text", "outside_image", "symlink"])
def test_reference_is_an_image_inside_refs(kind, tmp_path, monkeypatch):
    root = tmp_path / "assets"
    refs = root / "refs"
    refs.mkdir(parents=True)
    monkeypatch.setattr(styles, "REPO_ROOT", root)
    external = tmp_path / "private.png"
    Image.new("RGB", (8, 8)).save(external)
    if kind == "text":
        ref = refs / "not-an-image.png"
        ref.write_text("synthetic non-image")
    elif kind == "symlink":
        ref = refs / "link.png"
        ref.symlink_to(external)
    else:
        ref = external
    preset = tmp_path / "unsafe.toml"
    preset.write_text(f'[generate]\nref = "{ref.as_posix()}"\n')
    with pytest.raises(ValueError, match="reference"):
        styles.load_style(preset)


@pytest.mark.parametrize("target", ["image", "sidecar", "raw", "parent"])
def test_output_symlinks_are_rejected_before_generation(target, tmp_path, monkeypatch):
    class Unused(_StubComfy):
        def is_up(self):
            pytest.fail("reject symlinks before ComfyUI")

    monkeypatch.setattr(cli, "Comfy", Unused)
    out = tmp_path / "art.png"
    if target == "parent":
        outside = tmp_path / "outside"
        outside.mkdir()
        linked = tmp_path / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        out = linked / "art.png"
    else:
        linked = {"image": out, "sidecar": out.with_suffix(".json"),
                  "raw": out.with_name("art-raw.png")}[target]
        linked.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError, match="symlink"):
        cli.generate("crowd", "tennis", out=out, keep_raw=True)
    assert not (tmp_path / "missing-target").exists()
