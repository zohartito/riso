"""SVG mechanics for ``riso vector`` — engines, palette lock, proof raster.

The vector lane draws the same style presets as SVG instead of pixels. It is a
lane beside ``gen``/``motif``/``stylize``, not a replacement: the style still
owns palette and press treatment, and the proof PNG still goes through the
same riso post-pass.

Engines differ in where the SVG comes from:

- ``arrow-2`` / ``arrow-2-telos`` — QuiverAI through Vercel AI Gateway (metered)
- ``claude`` / ``codex`` / ``gemini`` / ``grok`` / ``kimi`` — subscription CLIs
  writing SVG code (the same argv shapes panel's seats use)
- ``omnisvg`` — the open-weight model, run locally through a wrapper command
- ``trace`` — vtracer on an existing raster (e.g. a ``riso gen --keep-raw`` frame)

No engine is seedable, so the raw SVG is always kept: re-running an image means
``--from-svg`` on that file, not calling the model again.

Colour is decided in code, never by the model. ``flatten`` makes the drawing
flat plates — no gradients, opacity, filters or embedded rasters — and
``lock_palette`` snaps every paint in attributes, inline styles and ``<style>``
sheets to the palette. Anything it cannot resolve is an error, not a pass.
"""

from __future__ import annotations

import base64
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageColor, ImageDraw

from riso import post

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
GATEWAY_KEY_VAR = "AI_GATEWAY_API_KEY"
GATEWAY_ENV_FILE = Path("~/.config/vercel/env")

OMNISVG_DIR = Path("~/projects/omnisvg")
OMNISVG_CMD_VAR = "RISO_OMNISVG_CMD"

# Generous for a flat illustration (vtracer output of a busy frame is ~200 KB);
# the caps exist so one runaway reply cannot stall a bake-off.
MAX_REPLY_CHARS = 5_000_000
MAX_DEPTH = 200

RGB = Tuple[int, int, int]


class VectorError(RuntimeError):
    """An engine ran and did not produce a usable SVG.

    ``reply`` carries whatever the engine did return, so the caller can keep it.
    """

    def __init__(self, message: str, reply: Optional[str] = None):
        super().__init__(message)
        self.reply = reply


@dataclass(frozen=True)
class Engine:
    name: str
    kind: str  # "gateway" | "cli" | "local" | "trace"
    model: str
    licence: str
    argv: Tuple[str, ...] = field(default_factory=tuple)


ENGINES: Dict[str, Engine] = {
    engine.name: engine
    for engine in (
        Engine(
            "arrow-2",
            "gateway",
            "quiverai/arrow-2",
            "QuiverAI terms: outputs assigned to you; commercial use needs a paid "
            "QuiverAI plan — the free tier is personal/non-commercial (ToS 5.2)",
        ),
        Engine(
            "arrow-2-telos",
            "gateway",
            "quiverai/arrow-2-telos",
            "QuiverAI terms: outputs assigned to you; commercial use needs a paid "
            "QuiverAI plan — the free tier is personal/non-commercial (ToS 5.2)",
        ),
        Engine(
            "claude",
            "cli",
            "claude-opus-5",
            "Anthropic subscription CLI; outputs are yours under the consumer terms",
            ("claude", "-p", "{prompt}", "--model", "claude-opus-5"),
        ),
        Engine(
            "codex",
            "cli",
            "gpt-5.6-sol",
            "OpenAI subscription CLI; outputs are yours under the OpenAI terms",
            (
                "codex", "exec", "-m", "gpt-5.6-sol",
                "--config", 'model_reasoning_effort="high"',
                "--sandbox", "read-only", "--skip-git-repo-check", "{prompt}",
            ),
        ),
        Engine(
            "gemini",
            "cli",
            "gemini (CLI default)",
            "Google subscription CLI; outputs are yours under the Gemini terms",
            ("gemini", "--skip-trust", "-p", "{prompt}"),
        ),
        Engine(
            "grok",
            "cli",
            "grok-4.6",
            "xAI subscription CLI; outputs are yours under the xAI terms",
            ("grok", "-p", "{prompt}", "-m", "grok-4.6", "--effort", "high"),
        ),
        Engine(
            "kimi",
            "cli",
            "kimi-code/k3",
            "Moonshot subscription CLI; outputs are yours under the Kimi terms",
            ("kimi", "-p", "{prompt}", "-m", "kimi-code/k3"),
        ),
        Engine(
            "omnisvg",
            "local",
            "OmniSVG1.1_8B",
            "Apache-2.0 code and weights; trained on MMSVG-2M (CC BY-NC-SA) — "
            "low but non-zero risk for commercial use of outputs",
        ),
        Engine(
            "trace",
            "trace",
            "vtracer",
            "vtracer is MIT; the source raster's own licence still applies",
        ),
    )
}


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------


def _hex(color: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def build_prompt(subject: str, medium: str, colors: Sequence[RGB], size: Tuple[int, int]) -> str:
    """Instruction for a text or SVG model: subject, medium, fixed inks, canvas."""
    subject = subject.strip()
    if not subject:
        raise ValueError("prompt cannot be empty")
    width, height = size
    inks = ", ".join(_hex(c) for c in colors)
    return (
        f"Draw this as a flat vector illustration: {subject}.\n"
        f"Medium: {medium.strip(' ,')}.\n"
        f"Use only these solid ink colours, no others: {inks}. "
        f"The last colour is the paper; fill the background with it.\n"
        f"No gradients, no opacity, no filters, no text, no embedded images.\n"
        f'Canvas: viewBox="0 0 {width} {height}".\n'
        "Reply with one complete SVG document and nothing else. Do not write files."
    )


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------


def gateway_key() -> str:
    """AI Gateway key from the environment, else from ~/.config/vercel/env."""
    key = os.environ.get(GATEWAY_KEY_VAR, "").strip()
    env_file = GATEWAY_ENV_FILE.expanduser()
    if not key and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() == GATEWAY_KEY_VAR:
                key = value.strip().strip("'\"")
    if not key:
        raise VectorError(
            f"no {GATEWAY_KEY_VAR} — create one in Vercel → AI Gateway → API Keys "
            f"and put it in {GATEWAY_ENV_FILE}"
        )
    return key


def redact(text: str) -> str:
    """Remove the gateway key from any text headed for a console or a file."""
    try:
        key = gateway_key()
    except Exception:  # no key, or an unreadable key file: nothing to redact
        return text
    return text.replace(key, "***") if key else text


def _child_env() -> Dict[str, str]:
    """Environment for engine subprocesses: everything except the gateway key."""
    env = dict(os.environ)
    env.pop(GATEWAY_KEY_VAR, None)
    return env


# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------


def _data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _call_gateway(engine: Engine, prompt: str, ref: Optional[Path], timeout: int) -> Tuple[str, dict]:
    content: List[dict] = [{"type": "text", "text": prompt}]
    if ref is not None:
        content.append({"type": "image_url", "image_url": {"url": _data_url(ref)}})
    key = gateway_key()
    response = requests.post(
        GATEWAY_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": engine.model, "messages": [{"role": "user", "content": content}]},
        timeout=timeout,
    )
    body = response.text.replace(key, "***")
    if response.status_code != 200:
        raise VectorError(f"{engine.name}: gateway HTTP {response.status_code}: {body[:300]}", reply=body)
    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise VectorError(f"{engine.name}: unexpected gateway response shape", reply=body) from exc
    if not isinstance(text, str):
        raise VectorError(f"{engine.name}: gateway returned no text content", reply=body)
    return text, {"request_id": payload.get("id"), "usage": payload.get("usage")}


def _as_text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _run(argv: List[str], label: str, timeout: int, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run an engine process; any failure keeps whatever it printed."""
    try:
        result = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout, env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise VectorError(
            f"{label}: timed out after {timeout}s",
            reply=f"{_as_text(exc.stdout)}\n--- stderr ---\n{redact(_as_text(exc.stderr))}",
        ) from exc
    if result.returncode != 0:
        raise VectorError(
            f"{label}: exit {result.returncode}: {redact(result.stderr.strip()[-300:])}",
            reply=f"{result.stdout}\n--- stderr ---\n{redact(result.stderr)}",
        )
    return result


def _call_cli(engine: Engine, prompt: str, timeout: int) -> Tuple[str, dict]:
    if shutil.which(engine.argv[0]) is None:
        raise VectorError(f"{engine.name}: `{engine.argv[0]}` is not on PATH")
    argv = [prompt if part == "{prompt}" else part for part in engine.argv]
    # A scratch cwd keeps agentic CLIs from reading or editing this repo.
    with tempfile.TemporaryDirectory() as scratch:
        result = _run(argv, engine.name, timeout, cwd=scratch)
    return result.stdout, {}


def omnisvg_argv(prompt: str, out: Path) -> List[str]:
    """Wrapper command for the local model; override with $RISO_OMNISVG_CMD."""
    template = os.environ.get(OMNISVG_CMD_VAR)
    if template:
        parts = template.split()
    else:
        root = OMNISVG_DIR.expanduser()
        parts = [str(root / ".venv/bin/python"), str(root / "omnisvg_gen.py"), "--model", "8B"]
    return parts + ["--prompt", prompt, "--out", str(out)]


def _call_omnisvg(subject: str, timeout: int) -> Tuple[str, dict]:
    # OmniSVG is trained on plain descriptions; ink and canvas instructions
    # would be noise to it. The palette lock supplies the colour afterwards.
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "omnisvg.svg"
        argv = omnisvg_argv(subject.strip(), target)
        if not Path(argv[0]).exists() and shutil.which(argv[0]) is None:
            raise VectorError(f"omnisvg: no runner at {argv[0]} (see {OMNISVG_DIR}/NOTES.md)")
        result = _run(argv, "omnisvg", timeout)
        if not target.is_file():
            raise VectorError("omnisvg: wrapper exited 0 but wrote no SVG", reply=result.stdout)
        return target.read_text(encoding="utf-8"), {"runner": argv[:2]}


def trace_raster(source: Path, colors: Sequence[RGB], mode: str) -> str:
    """Palette-lock a raster to flat plates, then trace the plates with vtracer."""
    try:
        import vtracer
    except ImportError as exc:  # optional dependency — only this engine needs it
        raise VectorError("trace: install the optional dependency with `pip install -e '.[vector]'`") from exc
    with Image.open(source) as opened:
        plates = post.palette_lock(opened.convert("RGB"), colors, mode)
    with tempfile.SpooledTemporaryFile() as buffer:
        plates.save(buffer, format="PNG")
        buffer.seek(0)
        data = buffer.read()
    return vtracer.convert_raw_image_to_svg(
        data, img_format="png", colormode="color", hierarchical="stacked",
        mode="spline", filter_speckle=8, color_precision=8, layer_difference=8,
    )


def run_engine(
    engine: Engine,
    subject: str,
    prompt: str,
    ref: Optional[Path] = None,
    source: Optional[Path] = None,
    colors: Sequence[RGB] = (),
    mode: str = "nearest",
    timeout: int = 900,
) -> Tuple[str, dict]:
    """Return (model text, metadata). The text may wrap the SVG in prose."""
    started = time.monotonic()
    if engine.kind == "gateway":
        text, meta = _call_gateway(engine, prompt, ref, timeout)
    elif engine.kind == "cli":
        text, meta = _call_cli(engine, prompt, timeout)
    elif engine.kind == "local":
        text, meta = _call_omnisvg(subject, timeout)
    elif engine.kind == "trace":
        if source is None:
            raise VectorError("trace needs --from-image: a raster to vectorise")
        text, meta = trace_raster(source, colors, mode), {}
    else:  # pragma: no cover — ENGINES is closed
        raise VectorError(f"unknown engine kind {engine.kind!r}")
    meta["seconds"] = round(time.monotonic() - started, 1)
    return text, meta


# --------------------------------------------------------------------------
# reading svg
# --------------------------------------------------------------------------


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_svg(svg: str) -> ET.Element:
    if len(svg) > MAX_REPLY_CHARS:
        raise VectorError(f"SVG is {len(svg)} characters; the cap is {MAX_REPLY_CHARS}")
    if "<!DOCTYPE" in svg or "<!ENTITY" in svg:
        raise VectorError("SVG with a DOCTYPE or entity declarations is refused")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise VectorError(f"engine returned malformed SVG: {exc}") from exc
    if _local(root.tag) != "svg":
        raise VectorError(f"root element is <{_local(root.tag)}>, not <svg>")
    depth, stack = 0, [(root, 1)]
    while stack:
        element, level = stack.pop()
        depth = max(depth, level)
        stack.extend((child, level + 1) for child in element)
    if depth > MAX_DEPTH:
        raise VectorError(f"SVG nests {depth} levels deep; the cap is {MAX_DEPTH}")
    _check_canvas(root)
    return root


# A drawing wider or taller than this is not an illustration; it is a raster
# the size of a building.
MAX_ASPECT = 10.0


def _check_canvas(root: ET.Element) -> None:
    """Refuse a canvas resvg would silently replace with a 200×200 default."""
    sides = []
    if "viewBox" in root.attrib:
        parts = re.split(r"[\s,]+", root.attrib["viewBox"].strip())
        try:
            numbers = [float(p) for p in parts]
        except ValueError:
            numbers = []
        if len(numbers) != 4 or not all(math.isfinite(n) for n in numbers):
            raise VectorError(f"unusable viewBox {root.attrib['viewBox']!r}")
        sides = numbers[2:]
    else:
        for name in ("width", "height"):
            match = re.fullmatch(r"\s*([0-9.eE+-]+)\s*([a-z]{0,2})\s*", root.attrib.get(name, ""))
            if match:
                try:
                    sides.append(float(match.group(1)))
                except ValueError:
                    raise VectorError(f"unusable {name} {root.attrib[name]!r}")
            elif name in root.attrib and not root.attrib[name].strip().endswith("%"):
                raise VectorError(f"unusable {name} {root.attrib[name]!r}")
    if len(sides) == 2:
        width, height = sides
        if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
            raise VectorError(f"canvas {width}×{height} has no area")
        if max(width / height, height / width) > MAX_ASPECT:
            raise VectorError(f"canvas {width}×{height} is more than {MAX_ASPECT:g}:1")


def extract_svg(text: str) -> str:
    """The first complete ``<svg>…</svg>`` in a reply, fences and prose dropped.

    Tries the widest span first (a drawing may nest ``<svg>``), then the
    narrowest (a reply may hold two drawings, or prose between them).
    """
    if not isinstance(text, str):
        raise VectorError("engine returned no text")
    if len(text) > MAX_REPLY_CHARS:
        raise VectorError(f"reply is {len(text)} characters; the cap is {MAX_REPLY_CHARS}")
    start = re.search(r"<svg[\s>]", text)
    if start is None or "</svg>" not in text[start.start():]:
        raise VectorError("no complete <svg> element in the engine's reply")
    first_end = text.index("</svg>", start.start())
    candidates = [text[start.start(): text.rfind("</svg>") + 6], text[start.start(): first_end + 6]]
    for candidate in candidates:
        try:
            ET.fromstring(candidate)
            return candidate
        except ET.ParseError:
            continue
    return candidates[0]  # let parse_svg report the parse error


def metrics(svg: str) -> dict:
    root = ET.fromstring(svg)
    tags = [_local(e.tag) for e in root.iter()]
    return {
        "bytes": len(svg.encode("utf-8")),
        "elements": len(tags),
        "paths": tags.count("path"),
        "gradients": sum(t.endswith("Gradient") for t in tags),
    }


def serialize(root: ET.Element) -> str:
    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------------------------
# flattening: the drawing becomes flat plates and nothing else
# --------------------------------------------------------------------------

_DROP_TAGS = {
    "script", "foreignObject", "iframe", "image", "filter", "feImage", "audio", "video", "mask",
    "animate", "animateColor", "animateMotion", "animateTransform", "set",
}
# Properties that blend inks into colours no screen holds.
_BLEND_PROPS = ("filter", "mask", "mix-blend-mode")
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_OPACITY_PROPS = ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity", "flood-opacity")
_HREF_ATTRS = ("href", f"{{{XLINK_NS}}}href")
_URL = re.compile(r"url\(\s*['\"]?#([^'\")\s]+)['\"]?\s*\)")


def _style_items(style: str) -> List[Tuple[str, str]]:
    items = []
    for declaration in style.split(";"):
        name, sep, value = declaration.partition(":")
        if sep and name.strip():
            items.append((name.strip().lower(), value.strip()))
    return items


def _set_style(element: ET.Element, items: List[Tuple[str, str]]) -> None:
    if items:
        element.attrib["style"] = ";".join(f"{name}:{value}" for name, value in items)
    else:
        element.attrib.pop("style", None)


def _is_zero(value: str) -> bool:
    try:
        number = value.strip()
        return float(number[:-1]) == 0 if number.endswith("%") else float(number) == 0
    except ValueError:
        return False


def flatten(root: ET.Element) -> dict:
    """Strip what would put off-palette pixels in the drawing. Returns counts.

    Scripts and foreign content go because the file will be opened in
    browsers; images, filters, gradients and opacity go because each one blends
    inks into colours no screen holds.
    """
    counts = {"dropped_elements": 0, "dropped_attributes": 0, "gradients_flattened": 0}
    parent_of = {child: parent for parent in root.iter() for child in parent}

    # Gradients first, while their stops still exist: each becomes one flat
    # ink, the middle stop's colour.
    gradients: Dict[str, Optional[str]] = {}
    by_id = {e.attrib["id"]: e for e in root.iter() if "id" in e.attrib}

    def stops_of(gradient: ET.Element, hops: int = 0) -> List[ET.Element]:
        stops = [s for s in gradient if _local(s.tag) == "stop"]
        if not stops and hops < 4:
            target = next((gradient.attrib[a] for a in _HREF_ATTRS if a in gradient.attrib), "")
            if target.startswith("#") and target[1:] in by_id:
                return stops_of(by_id[target[1:]], hops + 1)
        return stops

    for element in list(root.iter()):
        if _local(element.tag) in ("linearGradient", "radialGradient"):
            stops = stops_of(element)
            color = None
            if stops:
                middle = stops[len(stops) // 2]
                color = middle.attrib.get("stop-color") or dict(
                    _style_items(middle.attrib.get("style", ""))
                ).get("stop-color", "black")
            gradients[element.attrib.get("id", "")] = color

    def swap_gradient(value: str) -> str:
        match = _URL.search(value)
        if match and match.group(1) in gradients:
            counts["gradients_flattened"] += 1
            return gradients[match.group(1)] or "none"
        if match and match.group(1) not in by_id:
            # A reference to nothing paints its fallback, or nothing at all.
            return value[match.end():].strip() or "none"
        return value

    for element in list(root.iter()):
        tag = _local(element.tag)
        if tag in _DROP_TAGS or tag in ("linearGradient", "radialGradient"):
            parent = parent_of.get(element)
            if parent is not None:
                parent.remove(element)
                counts["dropped_elements"] += 1
            continue
        if tag == "use":
            target = next((element.attrib[a] for a in _HREF_ATTRS if a in element.attrib), "#")
            if not target.startswith("#"):
                parent_of[element].remove(element)
                counts["dropped_elements"] += 1
                continue

        if "style" in element.attrib:
            element.attrib["style"] = _CSS_COMMENT.sub("", element.attrib["style"])
        for name in list(element.attrib):
            local = _local(name).lower()
            if local.startswith("on") or local in _BLEND_PROPS or (
                local == "href" and not element.attrib[name].strip().startswith("#")
            ):
                del element.attrib[name]
                counts["dropped_attributes"] += 1
            elif local in _OPACITY_PROPS:
                value = element.attrib.pop(name)
                counts["dropped_attributes"] += 1
                _apply_zero_opacity(element, local, value, parent_of, counts)
            elif local in ("fill", "stroke"):
                element.attrib[name] = swap_gradient(element.attrib[name])

        if "style" in element.attrib:
            kept, hidden = [], []
            for prop, value in _style_items(element.attrib["style"]):
                if prop in _BLEND_PROPS or prop in _OPACITY_PROPS:
                    counts["dropped_attributes"] += 1
                    if prop in _OPACITY_PROPS:
                        _apply_zero_opacity(element, prop, value, parent_of, counts)
                        if _is_zero(value) and prop in ("fill-opacity", "stroke-opacity"):
                            hidden.append(prop.split("-")[0])
                    continue
                kept.append((prop, swap_gradient(value) if prop in ("fill", "stroke") else value))
            # Inline style outranks the attribute _apply_zero_opacity set.
            _set_style(element, [(p, "none" if p in hidden else v) for p, v in kept])

        if tag == "style" and element.text:
            element.text = _flatten_css(_CSS_COMMENT.sub("", element.text), swap_gradient, counts)
    return counts


def _apply_zero_opacity(element, prop, value, parent_of, counts) -> None:
    """Opacity 0 means 'not drawn'; keep that meaning once opacity is gone."""
    if not _is_zero(value):
        return
    if prop == "opacity":
        parent = parent_of.get(element)
        if parent is not None and element in list(parent):
            parent.remove(element)
            counts["dropped_elements"] += 1
    elif prop in ("fill-opacity", "stroke-opacity"):
        element.attrib[prop.split("-")[0]] = "none"


_CSS_DECL = re.compile(r"([\w-]+)\s*:\s*([^;{}]+?)\s*(!important)?\s*(?=;|})")


def _flatten_css(css: str, swap_gradient: Callable[[str], str], counts: dict) -> str:
    css = re.sub(r"@import[^;]*;?", "", css, flags=re.I)

    def rewrite(match: re.Match) -> str:
        prop, value, important = match.group(1).lower(), match.group(2), match.group(3) or ""
        if prop in _BLEND_PROPS or prop in _OPACITY_PROPS:
            counts["dropped_attributes"] += 1
            return ""
        if prop in ("fill", "stroke"):
            value = swap_gradient(value)
        return f"{prop}:{value}{important}"

    return _CSS_DECL.sub(rewrite, css)


# --------------------------------------------------------------------------
# palette lock
# --------------------------------------------------------------------------

_PAINT_PROPS = ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color")
_PASS = {"none", "inherit", "currentcolor"}


def parse_color(value: str) -> Optional[RGB]:
    """Any CSS colour (hex 3/4/6/8, rgb/rgba in any form, hsl, names) → RGB."""
    value = value.strip().lower()
    match = re.fullmatch(r"rgba?\((.*)\)", value)
    if match:
        parts = [p for p in re.split(r"[\s,/]+", match.group(1).strip()) if p][:3]
        if len(parts) == 3:
            try:
                channels = [
                    round(float(p[:-1]) * 2.55) if p.endswith("%") else round(float(p)) for p in parts
                ]
                return tuple(max(0, min(255, c)) for c in channels)  # type: ignore[return-value]
            except ValueError:
                return None
    match = re.fullmatch(r"hsla?\((.*)\)", value)
    if match:
        parts = [p for p in re.split(r"[\s,/]+", match.group(1).strip()) if p][:3]
        value = f"hsl({','.join(parts)})"
    try:
        return tuple(ImageColor.getrgb(value)[:3])  # type: ignore[return-value]
    except ValueError:
        return None


def _paint_slots(root: ET.Element) -> Iterator[Tuple[str, Callable[[Callable[[str], str]], None], str]]:
    """Every paint value in the tree, with a function that rewrites it in place."""
    for element in root.iter():
        for prop in _PAINT_PROPS:
            if prop in element.attrib:
                def set_attr(fn, element=element, prop=prop):
                    element.attrib[prop] = fn(element.attrib[prop])
                yield prop, set_attr, element.attrib[prop]
        if "style" in element.attrib:
            for prop, value in _style_items(element.attrib["style"]):
                if prop in _PAINT_PROPS:
                    def set_style(fn, element=element, prop=prop):
                        _set_style(element, [
                            (p, fn(v) if p == prop else v) for p, v in _style_items(element.attrib["style"])
                        ])
                    yield prop, set_style, value
        if _local(element.tag) == "style" and element.text:
            # One rewriter per sheet, shared by all its declarations, so the
            # caller can apply it exactly once.
            def set_css(fn, element=element):
                element.text = _CSS_DECL.sub(
                    lambda m: f"{m.group(1)}:{fn(m.group(2))}{m.group(3) or ''}"
                    if m.group(1).lower() in _PAINT_PROPS else m.group(0),
                    element.text,
                )
            for match in _CSS_DECL.finditer(element.text):
                if match.group(1).lower() in _PAINT_PROPS:
                    yield match.group(1).lower(), set_css, match.group(2)


def _split_paint(value: str) -> Tuple[str, str]:
    """``url(#a) coral`` → (``url(#a)``, ``coral``); plain colours have no url."""
    match = _URL.match(value.strip())
    if match:
        return match.group(0), value.strip()[match.end():].strip()
    return "", value.strip()


def lock_palette(root: ET.Element, colors: Sequence[RGB], mode: str = "nearest") -> dict:
    """Snap every paint to the palette. Returns adherence stats.

    Distinct source colours go through ``post.palette_lock`` as a 1×N strip, so
    the SVG lane uses exactly the colour science the raster lanes use. Unset
    paint defaults to black in SVG, so the root gets explicit fill and colour
    values too. A value that cannot be read as a colour raises.
    """
    palette = [tuple(c) for c in colors]
    root.attrib.setdefault("fill", "black")
    root.attrib.setdefault("color", "black")

    seen: Dict[str, RGB] = {}
    unresolved: List[str] = []
    slots = list(_paint_slots(root))
    for _, _, value in slots:
        _, color = _split_paint(value)
        if not color or color.lower() in _PASS:
            continue
        if color.lower() == "transparent":
            continue
        rgb = parse_color(color)
        if rgb is None:
            unresolved.append(color)
        else:
            seen[color] = rgb
    if unresolved:
        raise VectorError(f"{len(unresolved)} paint value(s) could not be read as colours: {sorted(set(unresolved))[:5]}")

    distinct = sorted(set(seen.values()))
    mapping: Dict[RGB, RGB] = {}
    if distinct:
        strip = Image.new("RGB", (len(distinct), 1))
        strip.putdata(distinct)
        locked = post.palette_lock(strip, palette, mode)
        mapping = {rgb: tuple(locked.getpixel((i, 0))) for i, rgb in enumerate(distinct)}

    def lock(value: str) -> str:
        url, color = _split_paint(value)
        if not color or color.lower() in _PASS:
            return value.strip()
        if color.lower() == "transparent":
            return f"{url} none".strip()
        if color not in seen:  # already locked by an earlier rewrite
            return value.strip()
        return f"{url} {_hex(mapping[seen[color]])}".strip()

    applied = set()
    for _, rewrite, _ in slots:
        if id(rewrite) not in applied:
            applied.add(id(rewrite))
            rewrite(lock)

    on_palette = sum(1 for rgb in distinct if rgb in palette)
    return {
        "color_refs": len(slots),
        "distinct_in": len(distinct),
        "distinct_on_palette": on_palette,
        "inks_used": sorted({_hex(c) for c in mapping.values()}),
        "mode": mode,
    }


def audit_paints(svg: str, colors: Sequence[RGB]) -> List[str]:
    """Paint values in a finished SVG that are neither an ink nor a reference."""
    inks = {_hex(tuple(c)) for c in colors}
    stray = []
    for _, _, value in _paint_slots(ET.fromstring(svg)):
        url, color = _split_paint(value)
        if color and color.lower() not in _PASS and color.upper() not in inks:
            stray.append(value)
    return stray


# --------------------------------------------------------------------------
# rasterising and contact sheet
# --------------------------------------------------------------------------


def rasterize(svg_path: Path, png_path: Path, width: int, paper: RGB) -> Tuple[int, int]:
    """SVG → opaque PNG at ``width`` px, on the paper ink. Returns the real size.

    resvg keeps the drawing's own aspect ratio, so the height is whatever the
    viewBox says — the caller compares it with what was asked for.
    """
    binary = shutil.which("resvg")
    if binary is None:
        raise VectorError("resvg is not installed — `brew install resvg` (Mac) or `cargo install resvg`")
    result = subprocess.run(
        [binary, "--width", str(width), "--background", _hex(paper), str(svg_path), str(png_path)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    if result.returncode != 0:
        raise VectorError(f"resvg failed: {result.stderr.strip()[-300:]}")
    with Image.open(png_path) as rendered:
        return rendered.size


def contact_sheet(entries: Sequence[Tuple[str, Optional[Path]]], out: Path, cell: int = 420) -> Path:
    """One column per engine: its proof PNG (or a blank for a failure) plus a label."""
    label_h = 28
    sheet = Image.new("RGB", (cell * len(entries), cell + label_h), "white")
    draw = ImageDraw.Draw(sheet)
    for column, (label, image_path) in enumerate(entries):
        x = column * cell
        if image_path is not None and image_path.is_file():
            with Image.open(image_path) as proof:
                thumb = proof.convert("RGB")
                thumb.thumbnail((cell - 12, cell - 12))
                sheet.paste(thumb, (x + (cell - thumb.width) // 2, label_h + (cell - thumb.height) // 2))
        else:
            draw.rectangle((x + 6, label_h + 6, x + cell - 6, label_h + cell - 6), outline="#999999")
        draw.text((x + 8, 8), label, fill="black")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
