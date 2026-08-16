from __future__ import annotations

from dataclasses import dataclass


REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080
MIN_LAYOUT_SCALE = 0.6
MAX_LAYOUT_SCALE = 2.5
UI_SIZE_MULTIPLIER = 0.9
FONT_SIZE_MULTIPLIER = 0.8


@dataclass(frozen=True)
class LayoutMetrics:
    scale: float
    font_scale: float
    card_width: int
    card_height: int
    card_gap: int
    side_panel_width: int
    font_size: int
    small_font_size: int
    title_font_size: int
    player_name_font_size: int


def calculate_layout_scale(width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 1.0
    fitted_scale = min(width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT)
    return max(MIN_LAYOUT_SCALE, min(MAX_LAYOUT_SCALE, fitted_scale))


def build_layout_metrics(width: int, height: int) -> LayoutMetrics:
    resolution_scale = calculate_layout_scale(width, height)
    scale = resolution_scale * UI_SIZE_MULTIPLIER
    font_scale = resolution_scale * FONT_SIZE_MULTIPLIER
    return LayoutMetrics(
        scale=scale,
        font_scale=font_scale,
        card_width=max(96, round(172 * scale)),
        card_height=max(121, round(217 * scale)),
        card_gap=max(8, round(18 * scale)),
        side_panel_width=max(300, round(470 * scale)),
        font_size=max(12, round(20 * font_scale)),
        small_font_size=max(9, round(12 * font_scale)),
        title_font_size=max(15, round(24 * font_scale)),
        player_name_font_size=max(28, round(48 * font_scale)),
    )


def scale_ui_value(owner, value: int | float, *, minimum: int = 1) -> int:
    return max(minimum, round(value * getattr(owner, "layout_scale", 1.0)))


def scale_font_value(owner, value: int | float, *, minimum: int = 1) -> int:
    return max(minimum, round(value * getattr(owner, "font_scale", 1.0)))
