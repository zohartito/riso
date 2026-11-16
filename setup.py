"""Bundle the canonical root-level assets into installed wheels."""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        for pattern in ("styles/*.toml", "palettes/*.json", "workflows/*.json", "refs/*.png"):
            for source in root.glob(pattern):
                target = Path(self.build_lib) / "riso" / "_assets" / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                self.copy_file(str(source), str(target))


setup(cmdclass={"build_py": BuildWithAssets})
