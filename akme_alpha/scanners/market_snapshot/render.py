"""Render the market snapshot as an ultra-minimal 16:9 PNG (1280×720).

Design:
  • Masthead: "Market Snapshot - DATE" (no subtitle/chip/live indicator)
  • 7 sections, each with a header + 2-column ticker grid
  • Green (#22C57E) / red (#EF4444) on the Move column
  • Text-wrapped driver narratives for top-5 movers (2-3 sentences each)
  • Brass (#C9A24E) accent for @Purrtfolio
  • No 'auto-generated' in footer
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import (
    BG, BRASS, GREEN, GRAY, GRAY_LT, HEIGHT, MARGIN, RED, TEXT, WIDTH,
)


def _font(size: int, weight: str = "regular"):
    """Load system font, fall back to default."""
    if weight == "bold":
        names = ["arialbd.ttf", "segoeuib.ttf", "Arial_Bold.ttf"]
    else:
        names = ["arial.ttf", "segoeui.ttf", "Arial.ttf"]
    for name in names:
        for p in [Path("C:/Windows/Fonts") / name,
                  Path("/usr/share/fonts") / name]:
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_section_header(draw, y, label):
    """Draw a section header in uppercase, brass color."""
    f = _font(15, "bold")
    text = label.upper()
    draw.text((MARGIN, y), text, fill=BRASS, font=f)
    return y + 20  # height of this header + gap


def _draw_ticker_row(draw, y, left_ticker, right_ticker):
    """Draw two tickers side by side on a single row (14px height)."""
    f_sym = _font(13, "bold")
    f_name = _font(12)
    f_val = _font(12)
    row_h = 16
    half_w = (WIDTH - MARGIN * 2) / 2

    for i, t in enumerate([left_ticker, right_ticker]):
        if t is None:
            continue
        x = MARGIN + (half_w * i)
        color = GREEN if t["is_positive"] else RED
        sym_text = f"{t['display_ticker']}  {t['name']}"
        level_text = t["level"]
        move_text = t["move"]

        # Symbol + name (left side)
        draw.text((x, y), sym_text, fill=TEXT, font=f_sym)
        # Name is part of sym_text for compactness; if too long, truncate
        bbox = draw.textbbox((0, 0), sym_text, font=f_sym)
        name_w = bbox[2] - bbox[0]

        # Level (right-aligned within half)
        level_w = _text_width(draw, level_text, f_val)
        move_w = _text_width(draw, move_text, f_val)
        gap = 8
        total_w = name_w + 2 + level_w + gap + move_w
        # If total too wide, shrink name area — just right-align level/move
        level_x = x + half_w - 12 - level_w - gap - move_w
        move_x = x + half_w - 12 - move_w

        draw.text((level_x, y), level_text, fill=GRAY, font=f_val)
        draw.text((move_x, y), move_text, fill=color, font=f_val)

    return y + row_h


def _wrap_text(draw, text, font, max_width):
    """Wrap text into lines fitting within max_width. Returns list of lines."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if _text_width(draw, test, font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_png(analysis: dict, output_path: str | Path) -> str:
    """Render the full market snapshot PNG from an analyze() result.

    Expects: {date, tickers: [...], top_narratives: [...], summary: {...}}
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    y = MARGIN - 8

    # ── Masthead ───────────────────────────────────────────────────────────
    f_title = _font(26, "bold")
    date_str = analysis.get("date", "")
    try:
        d = dt.date.fromisoformat(date_str)
        date_fmt = d.strftime("%B %d %Y")
    except (ValueError, TypeError):
        date_fmt = date_str or "—"

    masthead = f"Market Snapshot — {date_fmt}"
    draw.text((MARGIN, y), masthead, fill=TEXT, font=f_title)
    y += 40

    # ── Summary line ─────────────────────────────────────────────────────
    s = analysis.get("summary", {})
    f_sub = _font(13)
    summary_text = (
        f"{s.get('total_tickers', 0)} tickers  •  "
        f"{s.get('green_count', 0)} green  •  {s.get('red_count', 0)} red"
    )
    draw.text((MARGIN, y), summary_text, fill=GRAY, font=f_sub)
    y += 24

    # ── Sections ─────────────────────────────────────────────────────────
    from .config import SECTIONS

    tickers = analysis.get("tickers", [])
    tickers_by_section = {sec: [t for t in tickers if t["section"] == sec]
                          for sec in SECTIONS}

    for section_name in SECTIONS:
        section_tickers = tickers_by_section.get(section_name, [])
        if not section_tickers:
            continue

        # Section header
        y = _draw_section_header(draw, y, section_name)

        # Ticker rows in 2-column layout
        for i in range(0, len(section_tickers), 2):
            left = section_tickers[i]
            right = section_tickers[i + 1] if i + 1 < len(section_tickers) else None
            y = _draw_ticker_row(draw, y, left, right)

        y += 6  # gap after section

    # ── Driver Narratives ────────────────────────────────────────────────
    narratives = analysis.get("top_narratives", [])
    f_label = _font(15, "bold")
    f_body = _font(12)

    label = "Drivers"
    draw.text((MARGIN, y), label, fill=BRASS, font=f_label)
    y += 20

    max_w = WIDTH - MARGIN * 2
    for nv in narratives[:5]:
        # Ticker header line
        header = f"{nv['ticker']}  ({nv['section']})"
        draw.text((MARGIN, y), header, fill=TEXT, font=_font(12, "bold"))
        y += 16

        # Narrative body (wrapped, 2-3 sentences)
        lines = _wrap_text(draw, nv["narrative"], f_body, max_w)
        for line in lines[:3]:
            draw.text((MARGIN, y), line, fill=GRAY, font=f_body)
            y += 15
        y += 4  # gap between entries

    # ── Footer ───────────────────────────────────────────────────────────
    f_footer = _font(12)
    footer_y = HEIGHT - 28
    draw.text((MARGIN, footer_y), "@Purrtfolio", fill=BRASS, font=f_footer)
    draw.text((MARGIN + 96, footer_y), "akme.alpha", fill=GRAY, font=f_footer)

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", dpi=(200, 200))
    return str(output_path)


def main():
    ap = argparse.ArgumentParser(description="Render market snapshot PNG")
    ap.add_argument("--db", default=None, help="DB path")
    ap.add_argument("--output", default="market_snapshot.png", help="Output path")
    args = ap.parse_args()

    from .analyze import analyze
    result = analyze(db_path=args.db)
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    path = render_png(result, args.output)
    print(f"Rendered: {path}")
    print(f"Date: {result['date']} | {result['summary']}")


if __name__ == "__main__":
    main()
