"""Executable examples and prerequisites promised by the README."""

from pathlib import Path


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
