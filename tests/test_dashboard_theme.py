import tomllib
from pathlib import Path

import pytest

from charts import PALETTES

ROOT = Path(__file__).resolve().parent.parent
THEME = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_native_controls_and_charts_use_the_same_palette(theme):
    native = THEME[theme]
    palette = PALETTES[theme]

    assert native["primaryColor"] == palette["green"]
    assert native["textColor"] == palette["text"]
    assert native["secondaryBackgroundColor"] == palette["surface"]
    assert native["chartCategoricalColors"] == [palette["green"], palette["amber"]]


def luminance(hex_color):
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, [0.2126, 0.7152, 0.0722], strict=True))


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("background", ["backgroundColor", "secondaryBackgroundColor"])
def test_body_text_meets_wcag_aa_contrast(theme, background):
    native = THEME[theme]
    dark, light = sorted([luminance(native["textColor"]), luminance(native[background])])

    assert (light + 0.05) / (dark + 0.05) >= 4.5


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_selected_filter_tags_have_readable_text(theme):
    palette = PALETTES[theme]
    dark, light = sorted([luminance(palette["green"]), luminance(palette["on_green"])])

    assert (light + 0.05) / (dark + 0.05) >= 4.5
