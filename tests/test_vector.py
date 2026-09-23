"""The vector lane: SVG handling, palette lock, engines, and the CLI lane.

No live engine is called — gateway and CLI calls are stubbed. Tests that need
the resvg binary or the vtracer package skip when they are absent; CI installs
both so they run there.
"""

from __future__ import annotations

import json
import shutil
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

from riso import cli, post, vector

PALETTE = [(21, 50, 75), (242, 95, 92), (77, 182, 172), (244, 235, 221)]
INKS = {"#15324B", "#F25F5C", "#4DB6AC", "#F4EBDD"}
NEEDS_RESVG = pytest.mark.skipif(shutil.which("resvg") is None, reason="resvg not installed")

SAMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" fill="#f0e8dc"/>'
    '<circle cx="32" cy="32" r="16" style="fill:#ee6655;stroke:none"/>'
    '<path d="M0 0L10 10" stroke="rgb(20,40,80)"/>'
    '<linearGradient id="g"><stop offset="0" stop-color="#4db6ac"/></linearGradient>'
    '<rect width="8" height="8" fill="url(#g)"/>'
    "</svg>"
)

# Everything a model has been seen to emit, in one drawing.
MESSY = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'viewBox="0 0 100 100" onload="x()">'
    "<style>@import url(x.css); .a{fill:coral} .b{stroke: rgba(1,2,3,.5) !important; opacity:.4}</style>"
    '<script>alert(1)</script><foreignObject><div/></foreignObject>'
    '<filter id="f"><feColorMatrix type="saturate"/></filter>'
    '<image href="data:image/png;base64,AAAA" width="10" height="10"/>'
    '<use href="other.svg#x"/>'
    '<rect class="a" width="10" height="10" filter="url(#f)"/>'
    '<rect class="b" fill="navy" width="10" height="10"/>'
    '<rect fill="rgb(100%,0%,0%)" width="5" height="5" fill-opacity="0.5"/>'
    '<rect fill="#1234" stroke="#11223344" width="5" height="5"/>'
    '<rect fill="hsl(120, 100%, 25%)" width="5" height="5"/>'
    '<rect fill="url(#missing) coral" width="5" height="5"/>'
    '<rect fill="transparent" width="5" height="5"/>'
    '<rect opacity="0" fill="red" width="5" height="5"/>'
    '<g color="teal"><rect fill="currentColor" width="5" height="5"/></g>'
    "<rect width=\"5\" height=\"5\"/>"
    "</svg>"
)


def _paints(svg: str) -> list:
    """Every paint value in an SVG, including those inside <style> sheets."""
    import xml.etree.ElementTree as ET

    return [value for _, _, value in vector._paint_slots(ET.fromstring(svg))]


def _pipeline(svg: str, mode: str = "nearest") -> str:
    root = vector.parse_svg(svg)
    vector.flatten(root)
    vector.lock_palette(root, PALETTE, mode)
    return vector.serialize(root)


# -- reading svg ------------------------------------------------------------


def test_extract_svg_drops_fences_and_prose():
    reply = "Here you go:\n```svg\n" + SAMPLE + "\n```\nEnjoy."
    assert vector.extract_svg(reply) == SAMPLE


def test_extract_svg_takes_the_first_of_two_drawings():
    reply = SAMPLE + "\nand another:\n" + SAMPLE
    assert vector.extract_svg(reply) == SAMPLE


def test_extract_svg_refuses_a_reply_without_svg():
    with pytest.raises(vector.VectorError):
        vector.extract_svg("I cannot draw that.")
    with pytest.raises(vector.VectorError):
        vector.extract_svg(None)


def test_parse_svg_refuses_doctype_foreign_roots_and_deep_nesting():
    with pytest.raises(vector.VectorError):
        vector.parse_svg('<!DOCTYPE svg [<!ENTITY x "y">]><svg/>')
    with pytest.raises(vector.VectorError):
        vector.parse_svg("<html></html>")
    deep = '<svg xmlns="http://www.w3.org/2000/svg">' + "<g>" * 1500 + "</g>" * 1500 + "</svg>"
    with pytest.raises(vector.VectorError, match="levels deep"):
        vector.parse_svg(deep)


# -- flatten ----------------------------------------------------------------


def test_flatten_removes_non_drawing_content():
    root = vector.parse_svg(MESSY)
    counts = vector.flatten(root)
    text = vector.serialize(root)
    for gone in ("script", "foreignObject", "<image", "filter", "onload", "@import", "other.svg", "opacity"):
        assert gone not in text, gone
    assert counts["dropped_elements"] >= 5


def test_flatten_turns_gradients_into_one_flat_ink():
    root = vector.parse_svg(SAMPLE)
    counts = vector.flatten(root)
    text = vector.serialize(root)
    assert "Gradient" not in text and "url(#g)" not in text
    assert 'fill="#4db6ac"' in text
    assert counts["gradients_flattened"] == 1


def test_zero_opacity_still_means_not_drawn():
    root = vector.parse_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect id="a" opacity="0"/>'
        '<rect id="b" fill="red" fill-opacity="0"/></svg>'
    )
    vector.flatten(root)
    text = vector.serialize(root)
    assert 'id="a"' not in text
    assert 'id="b"' in text and 'fill="none"' in text


# -- palette lock -----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("#fff", (255, 255, 255)), ("#15324B", (21, 50, 75)), ("rgb(1, 2, 3)", (1, 2, 3)),
     ("black", (0, 0, 0)), ("navy", (0, 0, 128)), ("#1234", (17, 34, 51)),
     ("#11223344", (17, 34, 51)), ("rgba(1,2,3,.5)", (1, 2, 3)), ("rgb(100%,0%,0%)", (255, 0, 0)),
     ("rgb(1 2 3 / 50%)", (1, 2, 3)), ("hsla(0, 100%, 50%, 0.3)", (255, 0, 0)),
     ("url(#g)", None), ("banana", None)],
)
def test_parse_color(value, expected):
    assert vector.parse_color(value) == expected


def test_every_paint_ends_on_an_ink_or_a_reference():
    """The lane's core promise, on the messiest input we know of."""
    locked = _pipeline(MESSY)
    assert vector.audit_paints(locked, PALETTE) == []
    for value in _paints(locked):
        _, color = vector._split_paint(value)
        assert color.upper() in INKS or color.lower() in ("", "none", "inherit", "currentcolor"), value


def test_css_sheet_colours_are_locked():
    locked = _pipeline(MESSY)
    assert "coral" not in locked and "rgba" not in locked
    assert ".a{fill:#F25F5C}" in locked


def test_unset_paint_is_locked_through_the_root():
    """SVG paints unset fills black; the root now says which ink that is."""
    locked = _pipeline('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
    assert 'fill="#15324B"' in locked.split(">", 1)[0]


def test_unreadable_paint_is_an_error_not_a_pass():
    root = vector.parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect fill="banana"/></svg>')
    with pytest.raises(vector.VectorError, match="banana"):
        vector.lock_palette(root, PALETTE)


def test_lock_palette_nearest_leaves_exact_inks_alone():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" fill="#15324B"><rect fill="#F25F5C"/></svg>'
    root = vector.parse_svg(svg)
    stats = vector.lock_palette(root, PALETTE, "nearest")
    assert set(_paints(vector.serialize(root))) - {"black"} <= {"#F25F5C", "#15324B"}
    assert stats["distinct_on_palette"] == 2


def test_serialized_svg_has_no_ns0_prefix():
    assert "ns0:" not in _pipeline(SAMPLE)


@NEEDS_RESVG
def test_locked_drawing_renders_only_inks(tmp_path):
    """Before grain and misregistration, the proof holds the palette and only it."""
    svg = tmp_path / "locked.svg"
    svg.write_text(_pipeline(MESSY).replace("<svg ", '<svg shape-rendering="crispEdges" ', 1))
    png = tmp_path / "flat.png"
    vector.rasterize(svg, png, 100, PALETTE[-1])
    with Image.open(png) as flat:
        pixels = {tuple(p) for p in np.unique(np.asarray(flat.convert("RGB")).reshape(-1, 3), axis=0)}
    assert pixels <= set(PALETTE), pixels - set(PALETTE)


@NEEDS_RESVG
def test_rasterize_reports_the_drawing_s_real_proportions(tmp_path):
    svg = tmp_path / "square.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100"/></svg>')
    assert vector.rasterize(svg, tmp_path / "out.png", 200, PALETTE[-1]) == (200, 200)


def test_build_prompt_carries_inks_and_canvas():
    text = vector.build_prompt("a crane", ", flat cut paper, ", PALETTE, (832, 1216))
    assert "a crane" in text and "#F25F5C" in text and 'viewBox="0 0 832 1216"' in text
    with pytest.raises(ValueError):
        vector.build_prompt("  ", "", PALETTE, (10, 10))


# -- engines ----------------------------------------------------------------


def test_gateway_key_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv(vector.GATEWAY_KEY_VAR, raising=False)
    env = tmp_path / "env"
    env.write_text("export AI_GATEWAY_API_KEY='abc123'\n")
    monkeypatch.setattr(vector, "GATEWAY_ENV_FILE", env)
    assert vector.gateway_key() == "abc123"


def test_gateway_key_missing_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv(vector.GATEWAY_KEY_VAR, raising=False)
    monkeypatch.setattr(vector, "GATEWAY_ENV_FILE", tmp_path / "absent")
    with pytest.raises(vector.VectorError, match="AI_GATEWAY_API_KEY"):
        vector.gateway_key()


class _Reply:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_gateway_call_sends_model_prompt_and_reference(tmp_path, monkeypatch):
    monkeypatch.setenv(vector.GATEWAY_KEY_VAR, "k")
    ref = tmp_path / "ref.png"
    Image.new("RGB", (4, 4), "red").save(ref)
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return _Reply(200, {"id": "req_1", "usage": {"output_tokens": 9},
                            "choices": [{"message": {"content": SAMPLE}}]})

    monkeypatch.setattr(vector.requests, "post", fake_post)
    text, meta = vector.run_engine(vector.ENGINES["arrow-2"], "a crane", "PROMPT", ref=ref)
    assert text == SAMPLE and meta["request_id"] == "req_1"
    assert seen["url"] == vector.GATEWAY_URL
    assert seen["headers"]["Authorization"] == "Bearer k"
    body = seen["body"]
    assert body["model"] == "quiverai/arrow-2"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "PROMPT"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_gateway_error_never_carries_the_key(monkeypatch):
    key = "sk_live_DUMMY_KEY_1234"
    monkeypatch.setenv(vector.GATEWAY_KEY_VAR, key)
    monkeypatch.setattr(
        vector.requests, "post",
        lambda *a, **k: _Reply(401, {"error": f"bad header Authorization: Bearer {key}"}),
    )
    with pytest.raises(vector.VectorError) as caught:
        vector.run_engine(vector.ENGINES["arrow-2"], "s", "p")
    assert key not in str(caught.value) and "***" in str(caught.value)
    assert vector.redact(f"x {key} y") == "x *** y"


def test_gateway_null_content_is_an_engine_failure(monkeypatch):
    monkeypatch.setenv(vector.GATEWAY_KEY_VAR, "k" * 10)
    monkeypatch.setattr(
        vector.requests, "post", lambda *a, **k: _Reply(200, {"choices": [{"message": {"content": None}}]})
    )
    with pytest.raises(vector.VectorError, match="no text"):
        vector.run_engine(vector.ENGINES["arrow-2-telos"], "s", "p")


def test_cli_engine_passes_prompt_as_one_argument_without_the_key(monkeypatch):
    monkeypatch.setenv(vector.GATEWAY_KEY_VAR, "should-not-leak")
    calls = {}

    class Done:
        returncode = 0
        stdout = SAMPLE
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.update(argv=argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"))
        return Done()

    monkeypatch.setattr(vector.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(vector.subprocess, "run", fake_run)
    text, _ = vector.run_engine(vector.ENGINES["claude"], "s", "draw it; rm -rf /")
    assert text == SAMPLE
    assert "draw it; rm -rf /" in calls["argv"]
    assert calls["cwd"] is not None and "riso" not in calls["cwd"]
    assert vector.GATEWAY_KEY_VAR not in calls["env"]


def test_cli_engine_failure_keeps_what_it_printed():
    engine = vector.Engine("fake", "cli", "m", "l", (sys.executable, "-c", "print('<svg/>'); raise SystemExit(7)"))
    with pytest.raises(vector.VectorError) as caught:
        vector.run_engine(engine, "s", "p")
    assert "exit 7" in str(caught.value) and caught.value.reply.strip() == "<svg/>"


def test_trace_needs_a_source():
    with pytest.raises(vector.VectorError, match="from-image"):
        vector.run_engine(vector.ENGINES["trace"], "", "")


def test_trace_turns_flat_plates_into_palette_svg(tmp_path):
    pytest.importorskip("vtracer")
    source = tmp_path / "plates.png"
    image = Image.new("RGB", (96, 96), PALETTE[3])
    ImageDraw.Draw(image).ellipse((20, 20, 76, 76), fill=PALETTE[1])
    image.save(source)
    locked = _pipeline(vector.extract_svg(vector.trace_raster(source, PALETTE, "nearest")))
    colours = {vector._split_paint(v)[1].upper() for v in _paints(locked)}
    assert colours <= INKS and "#F25F5C" in colours


# -- the lane ---------------------------------------------------------------


@NEEDS_RESVG
def test_render_vector_writes_svg_proof_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(vector, "run_engine", lambda *a, **k: ("```\n" + SAMPLE + "\n```", {"seconds": 1.0}))
    written = cli.render_vector("a crane", "blueprint-coral", ["claude"], aspect="1:1", seed=7, out_dir=tmp_path)
    assert len(written) == 1
    png = written[0]
    assert png.suffix == ".png" and png.is_file()
    assert png.with_name(png.stem + "-raw.svg").read_text() == SAMPLE
    assert vector.audit_paints(png.with_suffix(".svg").read_text(), PALETTE) == []
    sidecar = json.loads(png.with_suffix(".json").read_text())
    assert sidecar["engine"] == "claude" and sidecar["seed"] == 7
    assert sidecar["post"]["palette_mode"] == "nearest"
    assert "#F25F5C" in sidecar["prompt_sent"]
    assert sidecar["flattened"]["gradients_flattened"] == 1
    with Image.open(png) as proof:
        assert list(proof.size) == sidecar["size"] == sidecar["size_requested"]


@NEEDS_RESVG
def test_a_square_drawing_for_a_tall_request_records_its_real_size(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vector, "run_engine", lambda *a, **k: (SAMPLE, {}))
    png = cli.render_vector("a crane", "blueprint-coral", ["claude"], aspect="2:3", seed=4, out_dir=tmp_path)[0]
    sidecar = json.loads(png.with_suffix(".json").read_text())
    width = sidecar["size_requested"][0]
    assert sidecar["size"] == [width, width]
    assert "not 2:3" in capsys.readouterr().err


@NEEDS_RESVG
def test_bake_off_survives_any_engine_failure_and_writes_a_sheet(tmp_path, monkeypatch):
    def fake(engine, *args, **kwargs):
        if engine.name == "gemini":
            raise vector.VectorError("quota")
        if engine.name == "grok":
            raise TypeError("unexpected crash")
        return SAMPLE, {"seconds": 0.5}

    monkeypatch.setattr(vector, "run_engine", fake)
    written = cli.render_vector("a crane", "blueprint-coral", ["gemini", "grok", "claude"], seed=3, out_dir=tmp_path)
    sheet = written[-1]
    assert sheet.name.startswith("vector-bench-")
    bench = json.loads(sheet.with_suffix(".json").read_text())
    assert [r["ok"] for r in bench["results"]] == [False, False, True]
    assert "quota" in bench["results"][0]["error"]
    assert "TypeError" in bench["results"][1]["error"]


def test_a_reply_without_svg_is_kept_for_inspection(tmp_path, monkeypatch):
    monkeypatch.setattr(vector, "run_engine", lambda *a, **k: ("Sorry, no.", {}))
    with pytest.raises(vector.VectorError):
        cli.render_vector("a crane", "blueprint-coral", ["claude"], seed=1, out_dir=tmp_path)
    assert (tmp_path / "vector-blueprint-coral-claude-a-crane-1-reply.txt").read_text() == "Sorry, no."


def test_a_malformed_svg_reply_is_kept_too(tmp_path, monkeypatch):
    broken = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#fff"</svg>'
    monkeypatch.setattr(vector, "run_engine", lambda *a, **k: (broken, {}))
    with pytest.raises(vector.VectorError):
        cli.render_vector("a crane", "blueprint-coral", ["grok"], seed=2, out_dir=tmp_path)
    assert (tmp_path / "vector-blueprint-coral-grok-a-crane-2-reply.txt").read_text() == broken


def test_a_failed_engine_s_partial_output_is_kept(tmp_path, monkeypatch):
    def fake(*args, **kwargs):
        raise vector.VectorError("claude: exit 7", reply="<svg partial")

    monkeypatch.setattr(vector, "run_engine", fake)
    with pytest.raises(vector.VectorError):
        cli.render_vector("a crane", "blueprint-coral", ["claude"], seed=6, out_dir=tmp_path)
    assert (tmp_path / "vector-blueprint-coral-claude-a-crane-6-reply.txt").read_text() == "<svg partial"


def test_a_failed_rerun_does_not_overwrite_earlier_files(tmp_path, monkeypatch):
    stem = tmp_path / "vector-blueprint-coral-claude-a-crane-8"
    stem.with_suffix(".svg").write_text("old")
    monkeypatch.setattr(vector, "run_engine", lambda *a, **k: (SAMPLE, {}))
    monkeypatch.setattr(vector, "rasterize", lambda *a, **k: (_ for _ in ()).throw(vector.VectorError("resvg failed")))
    with pytest.raises(vector.VectorError):
        cli.render_vector("a crane", "blueprint-coral", ["claude"], seed=8, out_dir=tmp_path)
    assert stem.with_suffix(".svg").read_text() == "old"
    assert not (tmp_path / "vector-blueprint-coral-claude-a-crane-8-raw.svg").exists()


@NEEDS_RESVG
def test_from_svg_reposts_without_calling_an_engine(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no engine should run")

    monkeypatch.setattr(vector, "run_engine", refuse)
    source = tmp_path / "kept.svg"
    source.write_text(SAMPLE)
    written = cli.render_vector("", "blueprint-coral", ["claude"], seed=5, out_dir=tmp_path, from_svg=source)
    sidecar = json.loads(written[0].with_suffix(".json").read_text())
    assert sidecar["engine"] == "from-svg" and sidecar["prompt_sent"] is None


def test_unknown_engine_is_rejected_before_any_call(tmp_path):
    with pytest.raises(ValueError, match="unknown engine"):
        cli.render_vector("x", "blueprint-coral", ["dall-e"], out_dir=tmp_path)


def test_cli_reports_errors_and_exits_nonzero(capsys):
    assert cli.main(["vector", "x", "--style", "blueprint-coral", "--engine", "nope"]) == 1
    assert "unknown engine" in capsys.readouterr().err


def test_every_style_can_feed_the_vector_lane():
    """Each preset names a palette the lane can lock to."""
    from riso.styles import available_styles, load_style

    for name in available_styles():
        palette = load_style(name).get("post", {}).get("palette")
        assert palette is not None, name
        assert len(post.load_palette(palette) if isinstance(palette, str) else palette) >= 2
