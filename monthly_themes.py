"""Approved monthly artwork and copy, bundled for offline rendering."""
from functools import lru_cache
from pathlib import Path

from PIL import Image


THEMES = {
    10: ("桂香", "把秋天过慢一点", "october-osmanthus.png"),
    11: ("暖食", "天凉了，一起吃顿热饭", "november-warm-meal.png"),
}
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "themes"


@lru_cache(maxsize=4)
def theme_artwork(filename, width, height):
    with Image.open(ASSET_DIR / filename) as source:
        artwork = source.convert("RGBA")
    bounds = artwork.getchannel("A").getbbox()
    if bounds:
        artwork = artwork.crop(bounds)
    artwork.thumbnail((width, height), Image.Resampling.LANCZOS)
    return artwork
