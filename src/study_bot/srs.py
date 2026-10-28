"""Lặp lại ngắt quãng kiểu Leitner, đơn giản và dễ đoán."""

from __future__ import annotations

import datetime as dt

# Khoảng cách (ngày) theo từng "hộp"; hộp 0 là từ mới hoặc vừa quên.
INTERVAL_DAYS = [0, 1, 3, 7, 14, 30, 60, 120]
MAX_BOX = len(INTERVAL_DAYS) - 1

AGAIN, HARD, GOOD, EASY = 0, 1, 2, 3


def schedule(box: int, rating: int) -> tuple[int, dt.timedelta, bool]:
    """Trả về (hộp mới, khoảng thời gian đến lần ôn kế, có bị quên hay không)."""
    if rating == AGAIN:
        return 0, dt.timedelta(minutes=10), True
    if rating == HARD:
        days = max(1, INTERVAL_DAYS[box] // 2)
        return box, dt.timedelta(days=days), False
    step = 1 if rating == GOOD else 2
    new_box = min(box + step, MAX_BOX)
    return new_box, dt.timedelta(days=max(1, INTERVAL_DAYS[new_box])), False
