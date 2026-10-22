"""Render the market regime dashboard as a 16:9 PNG (1280×720 @ 200 DPI).

Ultra-minimal editorial design:
- Green (#22C57E) / red (#EF4444) for risk direction
- Brass (#C9A24E) accent for @Purrtfolio
- Masthead: "Market Regime — date" + PNG download button

Layout:
  ┌────────────────────────────────────────────────────────────┐
  │ Market Regime — Oct 22 2026             [Download PNG]    │
  │                                                            │
  │                    [ EXPANSION ]                           │
  │              Last shift: Oct 15, 2026                      │
  │                                                            │
  │  Valuation    ██████████░░░░░░░░░░  +1.4σ                  │
  │  Growth/Value ████████░░░░░░░░░░░░  +0.9σ                  │
  │  Yield Curve  ██████░░░░░░░░░░░░░░  +0.6σ                  │
  │                                                            │
  │  Market regime holds at EXPANSION...                     │
  │                                                            │
  │  @Purrtfolio • regime.akme.dev                             │
  └────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import REGIME_COLORS

# ── Layout constants ────────────────────────────────────────────────────
WIDTH = 1280
HEIGHT = 720
MARGIN = 64
HEADER_HEIGHT = 100
PILL_HEIGHT = 110
GAUGE_HEIGHT = 38
NARRATIVE_HEIGHT = 90
FOOTER_HEIGHT = 50

BG = "#0F1012"
TEXT_BG = "#FFFFFF"
BRASS = "#C9A24E"
GRAY = "#6B7280"
GRAY_LT = "#37383A"


# ── Font loading ────────────────────────────────────────────────────────

def _font(size: int, weight: str = "regular"):
    """Load system font, fall back to default."""
    fonts_to_try = []
    if weight == "bold":
        fonts_to_try = ["arialbd.ttf", "segoeuib.ttf", "Arial_Bold.ttf"]
    else:
        fonts_to_try = ["arial.ttf", "segoeui.ttf", "Arial.ttf"]
    for name in fonts_to_try:
        for path in [
            Path("C:/Windows/Fonts") / name,
            Path("/usr/share/fonts") / name,
        ]:
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


# ── Drawing helpers ────────────────────────────────────────────────────

def _draw_text_centered(draw, xy, text, font, fill):
    """Draw text centered at (cx, cy)."""
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x - w / 2, y - h / 2), text, fill=fill, font=font)


def _draw_gauge(draw, x, y, width, height, label, zscore, color, max_zscore=3.0):
    """Draw a horizontal gauge bar for a factor z-score."""
    # Label
    f_label = _font(15)
    draw.text((x, y - 8), label, fill=TEXT_BG, font=f_label)

    # Track background (gray)
    track_y = y + 12
    draw.rounded_rectangle(
        [x, track_y, x + width, track_y + height],
        radius=height / 2,
        fill=GRAY_LT,
    )

    # Filled portion — centered at 0, extends based on zscore
    # Scale: max_zscore maps to full bar width in each direction
    half_width = width / 2
    fill_width = min(abs(zscore) / max_zscore * half_width, half_width)
    if zscore >= 0:
        bar_x1 = x + half_width - fill_width
        bar_x2 = x + half_width + fill_width
    else:
        bar_x1 = x + half_width - fill_width
        bar_x2 = x + half_width + fill_width

    draw.rounded_rectangle(
        [bar_x1, track_y, bar_x2, track_y + height],
        radius=height / 2,
        fill=color,
    )

    # Center line (at 0)
    draw.line([x + half_width, track_y, x + half_width, track_y + height],
              fill=GRAY, width=1)

    # Z-score value text
    f_value = _font(13)
    value_text = f"{zscore:+.2f}σ"
    # Position: to the right of the track
    draw.text((x + width + 12, y + 10), value_text, fill=color, font=f_value)


# ── Main render ────────────────────────────────────────────────────────

def render_png(regime_record: dict, output_path: str | Path) -> str:
    """Render the regime dashboard PNG from a regime_daily record dict.

    Expects: {date, verdict, composite_score, top_factors, narrative,
              last_shift_date, source_health}
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # ── Header ─────────────────────────────────────────────────────────────
    f_masthead = _font(24, "bold")
    date_str = regime_record.get("date", "")
    try:
        date_obj = dt.date.fromisoformat(date_str)
        date_fmt = date_obj.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        date_fmt = date_str or "—"

    masthead = f"Market Regime — {date_fmt}"
    draw.text((MARGIN, MARGIN - 16), masthead, fill=TEXT_BG, font=f_masthead)

    # ── Verdict pill ────────────────────────────────────────────────────────
    verdict = regime_record.get("verdict", "HARBOR")
    color = REGIME_COLORS.get(verdict, GRAY)
    f_verdict = _font(36, "bold")
    f_sub = _font(15)

    pill_center_x = WIDTH / 2
    pill_y = MARGIN + HEADER_HEIGHT
    pill_text = f" {verdict} "

    # Pill background
    bbox = draw.textbbox((0, 0), pill_text, font=f_verdict)
    pill_w = bbox[2] - bbox[0] + 24
    pill_h = bbox[3] - bbox[1] + 16
    pill_x1 = pill_center_x - pill_w / 2
    pill_y1 = pill_y
    draw.rounded_rectangle(
        [pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + pill_h],
        radius=pill_h / 2,
        fill=color,
    )
    _draw_text_centered(draw, (pill_center_x, pill_y1 + pill_h / 2),
                        pill_text, f_verdict, BG)

    # Last shift date
    last_shift = regime_record.get("last_shift_date", "")
    if last_shift:
        try:
            ls_date = dt.date.fromisoformat(last_shift).strftime("%b %d, %Y")
        except (ValueError, TypeError):
            ls_date = last_shift
    else:
        ls_date = "—"
    sub_text = f"Last shift: {ls_date}"
    _draw_text_centered(draw, (pill_center_x, pill_y1 + pill_h + 24),
                        sub_text, f_sub, GRAY)

    # ── Gauges ─────────────────────────────────────────────────────────────
    gauge_start_y = pill_y + pill_h + PILL_HEIGHT
    gauge_width = WIDTH - MARGIN * 2 - 120

    top_factors = regime_record.get("top_factors", [])[:3]
    if not top_factors:
        # Fallback: show composite
        top_factors = [{"name": "Composite", "zscore": regime_record.get("composite_score", 0)}]

    for i, f in enumerate(top_factors):
        y = gauge_start_y + i * (GAUGE_HEIGHT + 30)
        label = f.get("name", "unknown").replace("_", " ").title()
        zscore = f.get("zscore", 0) or 0
        f_color = "#22C57E" if zscore >= 0 else "#EF4444"
        _draw_gauge(draw, MARGIN, y, gauge_width, GAUGE_HEIGHT,
                    label, zscore, f_color)

    # ── Narrative ──────────────────────────────────────────────────────────
    narrative_y = gauge_start_y + len(top_factors) * (GAUGE_HEIGHT + 30) + 20
    f_narrative = _font(16)
    narrative = regime_record.get("narrative", "")
    # Wrap text
    _draw_wrapped_text(draw, MARGIN, narrative_y,
                       WIDTH - MARGIN * 2, narrative, f_narrative, TEXT_BG,
                       line_height=26, max_lines=3)

    # ── Footer ─────────────────────────────────────────────────────────────
    footer_y = HEIGHT - FOOTER_HEIGHT
    f_footer = _font(13)
    draw.text((MARGIN, footer_y), "@Purrtfolio", fill=BRASS, font=f_footer)
    draw.text((MARGIN + 80, footer_y), "regime.akme.dev", fill=GRAY, font=f_footer)

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", dpi=(200, 200))
    return str(output_path)


def _draw_wrapped_text(draw, x, y, max_width, text, font, fill,
                       line_height=24, max_lines=3):
    """Draw wrapped text within max_width, truncating to max_lines."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    # Truncate with "..." if needed
    if len(lines) == max_lines and current:
        for i in range(len(lines)):
            if i == max_lines - 1:
                last = lines[i]
                if len(last) > 3:
                    lines[i] = last[:-3] + "…"

    for i, line in enumerate(lines[:max_lines]):
        draw.text((x, y + i * line_height), line, fill=fill, font=font)


def main():
    ap = argparse.ArgumentParser(description="Render regime dashboard PNG")
    ap.add_argument("--db", default=None, help="DB path")
    ap.add_argument("--output", default="regime_dashboard.png", help="Output path")
    args = ap.parse_args()

    from .analyze import analyze
    result = analyze(db_path=args.db)
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    path = render_png(result, args.output)
    print(f"Rendered: {path}")
    print(f"Verdict: {result['verdict']} | Composite: {result['composite_score']:+.3f}")


if __name__ == "__main__":
    main()
