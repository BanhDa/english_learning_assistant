"""Đọc giáo án (curriculum.toml) và danh sách từ tùy chọn (wordlists/<CẤP>.txt)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# C2 dùng chung giáo án C1.
_FALLBACK = {"C2": "C1"}


@dataclass(frozen=True)
class Week:
    grammar: str
    theme: str


class Curriculum:
    def __init__(self, path: str, wordlist_dir: str):
        self.wordlist_dir = Path(wordlist_dir)
        self._weeks: dict[str, list[Week]] = {}
        p = Path(path)
        if not p.exists():
            log.warning("Không thấy giáo án %s, bot sẽ dạy không theo lộ trình.", p)
            return
        with p.open("rb") as f:
            data = tomllib.load(f)
        for level, items in data.items():
            self._weeks[level] = [Week(i["grammar"], i["theme"]) for i in items]

    def _level(self, level: str) -> str:
        return _FALLBACK.get(level, level)

    def length(self, level: str) -> int:
        return len(self._weeks.get(self._level(level), []))

    def week(self, level: str, pos: int) -> Week | None:
        weeks = self._weeks.get(self._level(level), [])
        if not weeks:
            return None
        return weeks[max(0, min(pos, len(weeks) - 1))]

    def wordlist_candidates(self, level: str, known: set[str], n: int) -> list[str]:
        """Lấy n từ đầu tiên chưa học trong wordlists/<cấp>.txt (nếu file tồn tại)."""
        f = self.wordlist_dir / f"{self._level(level)}.txt"
        if not f.exists():
            return []
        out: list[str] = []
        for line in f.read_text(encoding="utf-8").splitlines():
            w = line.strip().lower()
            if w and not w.startswith("#") and w not in known and w not in out:
                out.append(w)
                if len(out) >= n:
                    break
        return out
