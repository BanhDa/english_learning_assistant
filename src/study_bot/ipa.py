"""Phiên âm IPA: ưu tiên từ điển trực tuyến, nếu không có thì dùng phiên âm Claude đưa ra."""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

_API = "https://api.dictionaryapi.dev/api/v2/entries/en/"
_SIMPLE_WORD = re.compile(r"^[A-Za-z][A-Za-z'\-]{0,40}$")
_TIMEOUT = 4.0


def normalize(ipa: str | None) -> str:
    """'həˈləʊ' | '[həˈləʊ]' | '/həˈləʊ/' -> '/həˈləʊ/'; chuỗi rỗng nếu không có."""
    if not ipa:
        return ""
    core = ipa.strip().strip("/[]").strip()
    if not core or len(core) > 60:
        return ""
    return f"/{core}/"


async def _lookup_one(client: httpx.AsyncClient, word: str) -> str:
    # Từ điển chỉ có từ đơn; cụm từ nhiều chữ thì bỏ qua và dùng phiên âm của Claude.
    if not _SIMPLE_WORD.match(word):
        return ""
    try:
        resp = await client.get(_API + quote(word.lower()))
        if resp.status_code != 200:
            return ""
        for entry in resp.json():
            for p in entry.get("phonetics", []):
                text = normalize(p.get("text"))
                if text:
                    return text
            text = normalize(entry.get("phonetic"))
            if text:
                return text
    except Exception as e:  # mạng lỗi/timeout/JSON lạ đều không được làm hỏng bài học
        log.debug("Tra phiên âm %r thất bại: %s", word, e)
    return ""


async def lookup_many(words: list[str]) -> dict[str, str]:
    """Trả về {từ: phiên âm}; từ nào không tra được thì vắng mặt hoặc rỗng."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        results = await asyncio.gather(*(_lookup_one(client, w) for w in words))
    return dict(zip(words, results))
