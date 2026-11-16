"""Asset location for unpacked wheels and editable source checkouts."""

from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent / "_assets"
if not ASSET_ROOT.is_dir():
    ASSET_ROOT = Path(__file__).resolve().parent.parent
