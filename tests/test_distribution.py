"""Offline wheel smoke test; all build/install artifacts stay in pytest's tmpdir."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_installed_wheel_in_an_empty_directory(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(__file__).resolve().parents[1], source,
        ignore=shutil.ignore_patterns(".git", ".venv", "*.egg-info", "__pycache__", ".pytest_cache", "out", "build"),
    )
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    env.pop("PYTHONPATH", None)
    wheels = tmp_path / "wheels"
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
         "--wheel-dir", str(wheels), str(source)],
        check=True, capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    installed = tmp_path / "installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed),
         str(next(wheels.glob("riso-*.whl")))],
        check=True, capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    env["PYTHONPATH"] = str(installed)
    result = subprocess.run(
        [sys.executable, "-c", '''
import io
from pathlib import Path
from PIL import Image
from riso import cli, comfy, post, styles
assert "installed" in str(Path(cli.__file__).parents[1])
assert styles.available_styles() == ["tennis"]
assert styles.load_style("tennis")["generate"]["ref"].is_file()
assert len(post.load_palette("tennis-felt")) == 5
assert comfy.load_workflow()["redux"]["class_type"] == "StyleModelLoader"
class StandIn:
    def __init__(self, host): pass
    def is_up(self): return True
    def upload_image(self, path): return path.name
    def generate(self, workflow):
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (90, 110, 200)).save(buf, "PNG")
        return buf.getvalue()
cli.Comfy = StandIn
out = cli.generate("crowd", "tennis", seed=7)
assert out.is_file()
assert out.resolve().parent == Path.cwd() / "out"
'''],
        capture_output=True, text=True, env=env, cwd=empty,
    )
    assert result.returncode == 0, result.stderr
