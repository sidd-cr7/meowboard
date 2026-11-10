"""
Script to pre-generate application icons and sound assets.
"""
from pathlib import Path
import sys

# Ensure project root is in sys.path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from meowboard.gui.icon_generator import ensure_app_icons
from meowboard.core.sound_generator import ensure_sound_assets
from meowboard.utils.logger import logger


def main():
    assets_dir = root / "meowboard" / "assets"
    icons_dir = assets_dir / "icons"
    sounds_dir = assets_dir / "sounds"

    logger.info("Generating MEOWBOARD icons...")
    ensure_app_icons(icons_dir)

    logger.info("Generating MEOWBOARD feline audio assets...")
    ensure_sound_assets(sounds_dir)

    logger.info("All assets generated successfully!")


if __name__ == "__main__":
    main()
