"""Vẽ flashcard từ vựng thành ảnh PNG."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

W = 900
MIN_H = 520
MARGIN = 28
PAD = 52
CANVAS = "#E8EEF6"
CARD = "#FFFFFF"
ACCENT = "#4F46E5"
TEXT = "#111827"
MUTED = "#6B7280"
MEANING = "#047857"
BORDER = "#CBD5E1"


@lru_cache(maxsize=32)
def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"NotoSans-{style}.ttf"), size)


def _wrap(measure: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if measure.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return lines


def render_card(
    word: str, pos: str, ipa: str, meaning_vi: str, example: str, example_vi: str
) -> bytes:
    left, right = MARGIN + PAD, W - MARGIN - PAD
    max_w = right - left
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # --- Bố cục: tính trước mọi dòng chữ để biết chiều cao thẻ ---
    size = 84
    while size > 40 and measure.textlength(word, font=_font("Bold", size)) > max_w:
        size -= 4
    meaning_lines = _wrap(measure, meaning_vi, _font("Bold", 42), max_w, 3)
    example_lines = _wrap(measure, example, _font("Italic", 32), max_w, 4) if example else []
    example_vi_lines = _wrap(measure, example_vi, _font("Regular", 28), max_w, 3) if example_vi else []

    top = MARGIN + 52
    y_ipa = top + size + 22
    y_line = y_ipa + 70
    y_meaning = y_line + 28
    y_example = y_meaning + 56 * len(meaning_lines) + 14
    y_example_vi = y_example + (44 * len(example_lines) + 4 if example_lines else 0)
    y_end = y_example_vi + 38 * len(example_vi_lines)
    h = max(MIN_H, y_end + MARGIN + 40)

    # --- Vẽ ---
    img = Image.new("RGB", (W, h), CANVAS)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (MARGIN, MARGIN, W - MARGIN, h - MARGIN), radius=28, fill=CARD, outline=BORDER, width=2
    )
    d.rounded_rectangle((MARGIN, MARGIN, W - MARGIN, MARGIN + 14), radius=7, fill=ACCENT)

    d.text((left, top), word, font=_font("Bold", size), fill=TEXT)
    if ipa:
        d.text((left, y_ipa), ipa, font=_font("Regular", 38), fill=ACCENT)
    if pos:
        f = _font("Bold", 24)
        tw = d.textlength(pos, font=f)
        box = (right - tw - 36, y_ipa + 4, right, y_ipa + 48)
        d.rounded_rectangle(box, radius=22, fill="#EEF2FF", outline=ACCENT, width=2)
        d.text((box[0] + 18, box[1] + 6), pos, font=f, fill=ACCENT)
    d.line((left, y_line, right, y_line), fill=BORDER, width=2)

    for i, line in enumerate(meaning_lines):
        d.text((left, y_meaning + 56 * i), line, font=_font("Bold", 42), fill=MEANING)
    for i, line in enumerate(example_lines):
        d.text((left, y_example + 44 * i), line, font=_font("Italic", 32), fill=TEXT)
    for i, line in enumerate(example_vi_lines):
        d.text((left, y_example_vi + 38 * i), line, font=_font("Regular", 28), fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
