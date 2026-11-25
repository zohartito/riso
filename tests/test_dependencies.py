"""The documented environment must pin and hash its dependency closure."""

from importlib.metadata import distribution
from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _lock():
    text = (ROOT / "requirements.txt").read_text().replace("\\\n", " ")
    entries = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line.split(" --hash=", 1)[0].strip())
        entries[canonicalize_name(requirement.name)] = (requirement, line)
    return entries


def test_dependency_lock_pins_and_hashes_every_entry():
    for name, (requirement, line) in _lock().items():
        assert re.fullmatch(r"==[^,*]+", str(requirement.specifier)), name
        assert re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", line), name


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_dependency_lock_covers_runtime_test_and_build_closure(platform):
    locked = _lock()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pending = project["project"]["dependencies"] + project["build-system"]["requires"] + ["pytest", "wheel"]
    checked = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({"sys_platform": platform, "extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        assert name in locked, f"unlocked dependency: {requirement} on {platform}"
        pin = next(iter(locked[name][0].specifier)).version
        assert requirement.specifier.contains(pin), f"incompatible lock: {requirement}"
        if name in checked:
            continue
        checked.add(name)
        if name == "colorama" and platform == "win32":
            continue  # Windows-only leaf, not installed on Linux/macOS.
        pending.extend(distribution(name).requires or [])


def test_readme_and_ci_use_the_lock_without_resolving_again():
    for path in [ROOT / "README.md", ROOT / ".github/workflows/ci.yml"]:
        text = path.read_text()
        assert "--require-hashes -r requirements.txt" in text
        assert "--no-deps --no-build-isolation -e ." in text
