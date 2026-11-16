"""Executable examples and prerequisites promised by the README."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def test_readme_setup_creates_venv_and_installs_test_dependencies():
    setup = (ROOT / "README.md").read_text().split("```bash", 1)[1].split("```", 1)[0]
    commands = [line.split("#", 1)[0].strip() for line in setup.splitlines() if line.strip()]
    create = next((i for i, line in enumerate(commands) if "-m venv .venv" in line), -1)
    activate = commands.index("source .venv/bin/activate")
    dependencies = next((i for i, line in enumerate(commands) if "-r requirements.txt" in line), -1)
    run_tests = commands.index("python -m pytest -q")
    assert 0 <= create < activate, "create the venv before activating it"
    assert activate < dependencies < run_tests, "install test dependencies before pytest"
    assert "pytest==" in (ROOT / "requirements.txt").read_text()


def test_readme_post_example_creates_its_output_directory(tmp_path, monkeypatch):
    example = (ROOT / "README.md").read_text().split("```python", 1)[1].split("```", 1)[0]
    monkeypatch.chdir(tmp_path)
    Image.new("RGB", (32, 32), (100, 120, 140)).save("in.png")
    assert not Path("out").exists()
    exec(compile(example, "README post-pass example", "exec"), {})
    with Image.open("out/art.png") as art:
        assert art.size == (32, 32)
        assert art.format == "PNG"
