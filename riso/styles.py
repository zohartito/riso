"""Style presets: reference image + palette + post settings, as TOML data.

A preset is the unit of series consistency — two runs that name the same style
may differ in subject and seed and in nothing else. Everything a style decides
lives in ``styles/*.toml``, never in the CLI.

The ``[post]`` table is passed to ``post.compose`` verbatim, so its schema is
that function's preset schema and nothing here needs to know about halftones.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
STYLE_DIR = REPO_ROOT / "styles"

# Measured band for Redux strength — see refs/srefs.md. Outside it the node
# either copies the reference outright or stops carrying style at all.
STRENGTH_BAND = (0.05, 0.15)

Style = Dict[str, Any]


def load_style(name: Union[str, Path]) -> Style:
    """Load a preset by name (``tennis``) or by path to a TOML file.

    Returns the parsed table with ``generate.ref`` resolved to an absolute
    path, so a preset can name its reference relative to the repo and still
    work from any working directory, on either machine.
    """
    path = Path(name)
    if path.suffix.lower() != ".toml":
        path = STYLE_DIR / f"{path.name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"no style preset at {path}")

    data = tomllib.loads(path.read_text(encoding="utf-8"))

    generate = data.get("generate")
    if not isinstance(generate, dict) or "ref" not in generate:
        raise ValueError(f"{path} needs a [generate] table with a 'ref'")

    ref = Path(generate["ref"])
    if not ref.is_absolute():
        ref = REPO_ROOT / ref
    if not ref.is_file():
        raise FileNotFoundError(f"{path} points at a missing reference: {ref}")
    generate["ref"] = ref

    strength = float(generate.get("strength", 0.1))
    if strength <= 0.0:
        raise ValueError(f"{path} has a non-positive strength: {strength}")
    generate["strength"] = strength

    preset = data.get("post")
    if preset is not None and not isinstance(preset, dict):
        raise ValueError(f"{path} has a [post] that is not a table")

    data.setdefault("name", path.stem)
    return data


def available_styles() -> List[str]:
    """Names of every preset shipped in ``styles/``."""
    return sorted(p.stem for p in STYLE_DIR.glob("*.toml"))
