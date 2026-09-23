"""Phase 3 CLI: aspect ratios, style presets, and the generation chain.

The ComfyUI half is stubbed — these prove the wiring and the framing maths,
not the model. What the model does is judged by eye, in docs/.
"""

from __future__ import annotations

import json
import hashlib
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


def test_cobalt_blockprint_preset_is_internal_and_prompt_driven():
    style = styles.load_style("cobalt-blockprint")
    settings = style["generate"]
    assert settings["ref"].name == "style-cobalt-blockprint-abstract.png"
    assert settings["ref"].is_file()
    assert style["post"]["palette"] == "egypt-cobalt"
    assert settings["strength"] == 0.08

    subject = "workers carrying modular panels in staggered rows"
    sent = cli.resolved_prompt(subject, style)
    assert sent.startswith(subject)
    assert "block print" in sent
    for borrowed in ("gizem", "akdag", "egypt", "pyramid", "sarcophagus", "moon"):
        assert borrowed not in sent.lower()


def test_blueprint_coral_preset_has_original_inputs_and_mechanical_suffix():
    style = styles.load_style("blueprint-coral")
    settings = style["generate"]
    assert settings["ref"].name == "style-blueprint-coral-abstract.png"
    assert settings["ref"].is_file()
    assert style["post"]["palette"] == "blueprint-coral"

    subject = "a crane lowering a stair core into a timber frame"
    sent = cli.resolved_prompt(subject, style)
    assert sent.startswith(subject)
    assert "architectural block print" in sent
    for borrowed in ("gizem", "akdag", "egypt", "pyramid", "sarcophagus"):
        assert borrowed not in sent.lower()


def test_site_signals_preset_has_original_inputs_and_no_source_subjects():
    style = styles.load_style("site-signals")
    settings = style["generate"]
    assert settings["ref"].name == "style-site-signals-abstract.png"
    assert settings["ref"].is_file()
    assert style["post"]["palette"] == "signal-violet"

    subject = "survey prisms arranged along an unfinished concrete ramp"
    sent = cli.resolved_prompt(subject, style)
    assert sent.startswith(subject)
    assert "architectural material collage" in sent
    for borrowed in (
        "gizem",
        "akdag",
        "camel",
        "pyramid",
        "zebra",
        "mountain",
        "striped",
    ):
        assert borrowed not in sent.lower()


def test_field_exceptions_preset_has_original_inputs_and_no_source_subjects():
    style = styles.load_style("field-exceptions")
    settings = style["generate"]
    assert settings["ref"].name == "style-field-exceptions-abstract.png"
    assert settings["ref"].is_file()
    assert style["post"]["palette"] == "rose-aqua-field"

    subject = "sawtooth roof monitors surrounding an inverted rain court"
    sent = cli.resolved_prompt(subject, style)
    assert sent.startswith(subject)
    assert "architectural relief" in sent
    for borrowed in (
        "ege",
        "berkina",
        "commuter",
        "passenger",
        "auditorium",
        "phone",
        "green skin",
    ):
        assert borrowed not in sent.lower()


def test_resolved_prompt_rejects_empty_subject():
    with pytest.raises(ValueError, match="cannot be empty"):
        cli.resolved_prompt("   ", styles.load_style("cobalt-blockprint"))


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
        assert art.size == cli.dimensions((3, 4))
    assert out.with_name("shot-raw.png").is_file()

    record = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["seed"] == 4242
    assert record["size"] == list(cli.dimensions((3, 4)))
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
    listed = capsys.readouterr().out.split()
    assert "tennis" in listed
    assert "cobalt-blockprint" in listed
    assert "blueprint-coral" in listed
    assert "site-signals" in listed
    assert "field-exceptions" in listed


def test_show_prompt_prints_exact_text_without_contacting_comfy(capsys, monkeypatch):
    class _MustNotStart:
        def __init__(self, *args, **kwargs):
            raise AssertionError("--show-prompt must not construct Comfy")

    monkeypatch.setattr(cli, "Comfy", _MustNotStart)
    subject = "paper kites crossing stepped rooftops"
    assert cli.main(
        ["gen", subject, "--style", "cobalt-blockprint", "--show-prompt"]
    ) == 0
    sent = capsys.readouterr().out.strip()
    assert sent.startswith(subject)
    assert "cut-paper shapes" in sent


# -- offline geometric and input-image lanes --------------------------------


def test_motif_writes_finished_raw_and_provenance(tmp_path):
    out = tmp_path / "rays.png"
    written = cli.render_motif(
        "rays",
        palette="egypt-cobalt",
        aspect="2:3",
        seed=23,
        density=1.2,
        out=out,
        keep_raw=True,
    )

    assert written == out and out.is_file()
    assert out.with_name("rays-raw.png").is_file()
    with Image.open(out) as image:
        assert image.size == cli.dimensions((2, 3))
    record = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["generator"] == "riso.motif"
    assert record["motif"] == "rays"
    assert record["palette"] == "egypt-cobalt"
    assert record["seed"] == 23
    assert record["density"] == 1.2
    assert "no external model" in record["licence"]


def test_motif_cli_does_not_need_comfyui(tmp_path, capsys):
    out = tmp_path / "crowd.png"
    assert cli.main(
        ["motif", "crowd", "--seed", "4", "--out", str(out)]
    ) == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


def test_stylize_writes_a_finished_png_and_hashes_its_source(tmp_path):
    source = tmp_path / "source.jpg"
    out = tmp_path / "finished.png"
    Image.linear_gradient("L").resize((120, 180)).convert("RGB").save(source)

    written = cli.stylize(source, seed=11, out=out)

    assert written == out and out.is_file()
    with Image.open(out) as image:
        assert image.size == (120, 180)
    record = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["generator"] == "riso.stylize"
    assert record["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert record["post"]["palette"] == "egypt-cobalt"
    assert "source-image rights" in record["licence"]


def test_stylize_reports_a_missing_input(capsys):
    assert cli.main(["stylize", "not-here.png"]) == 1
    assert "no input image" in capsys.readouterr().err


def test_stylize_refuses_to_overwrite_its_input(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 20), "white").save(source)
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.stylize(source, seed=1, out=source)


def test_inventory_subcommands_list_the_new_assets(capsys):
    assert cli.main(["motifs"]) == 0
    assert set(capsys.readouterr().out.split()) >= {"crowd", "rays", "peaks"}
    assert cli.main(["palettes"]) == 0
    assert "egypt-cobalt" in capsys.readouterr().out.split()
