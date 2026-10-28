from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

# loại nhắc -> (tên hiển thị, giờ mặc định)
REMINDER_KINDS = {
    "words": ("Từ mới", "07:30,09:30,11:00,14:30,16:00,19:00"),
    "review": ("Ôn từ", "12:30,20:00"),
    "exercise": ("Bài tập", "17:30"),
    "practice": ("Luyện hội thoại", "21:00"),
}

DEFAULT_TZ = "Asia/Ho_Chi_Minh"


@dataclass(frozen=True)
class BotConfig:
    """Một bot Telegram và những người được phép dùng nó."""

    name: str
    token: str
    allowed_user_ids: frozenset[int]


@dataclass(frozen=True)
class Settings:
    # telegram_token và allowed_user_ids là của bot đang chạy; xem main.py (mỗi bot một bản Settings).
    telegram_token: str
    anthropic_api_key: str
    allowed_user_ids: frozenset[int]
    claude_model: str
    max_llm_calls_per_day: int
    db_path: str
    curriculum_path: str = "curriculum.toml"
    wordlist_dir: str = "wordlists"
    bots: tuple[BotConfig, ...] = ()


def _parse_ids(raw: str, label: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                raise SystemExit(f"{label} có giá trị không hợp lệ: {part!r}")
    return frozenset(ids)


def _load_bots() -> tuple[BotConfig, ...]:
    """Đọc BOT1_*, BOT2_*, ... Nếu không có thì dùng TELEGRAM_BOT_TOKEN/ALLOWED_USER_IDS như một bot duy nhất."""
    bots: list[BotConfig] = []
    for i in range(1, 21):
        token = os.getenv(f"BOT{i}_TOKEN", "").strip()
        if not token:
            continue
        bots.append(
            BotConfig(
                name=os.getenv(f"BOT{i}_NAME", "").strip() or f"bot{i}",
                token=token,
                allowed_user_ids=_parse_ids(os.getenv(f"BOT{i}_USER_IDS", ""), f"BOT{i}_USER_IDS"),
            )
        )
    if not bots:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "Chưa cấu hình bot nào. Điền BOT1_TOKEN (và BOT2_TOKEN...) hoặc TELEGRAM_BOT_TOKEN trong .env"
            )
        bots.append(
            BotConfig("bot", token, _parse_ids(os.getenv("ALLOWED_USER_IDS", ""), "ALLOWED_USER_IDS"))
        )

    # Dữ liệu học tập gắn với ID người dùng, nên một người không được dùng hai bot.
    tokens = [b.token for b in bots]
    if len(set(tokens)) != len(tokens):
        raise SystemExit("Hai bot đang dùng cùng một token.")
    seen: dict[int, str] = {}
    for b in bots:
        for uid in b.allowed_user_ids:
            if uid in seen:
                raise SystemExit(f"ID {uid} có trong cả bot '{seen[uid]}' và '{b.name}'. Mỗi người chỉ dùng một bot.")
            seen[uid] = b.name
    return tuple(bots)


def load_settings(env_file: str | None = None) -> Settings:
    """Đọc cấu hình. env_file chỉ định rõ thì file đó phải tồn tại; không thì đọc .env nếu có."""
    if env_file:
        if not os.path.isfile(env_file):
            raise SystemExit(f"Không thấy file cấu hình: {env_file}")
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Thiếu ANTHROPIC_API_KEY trong .env")
    bots = _load_bots()

    return Settings(
        telegram_token=bots[0].token,
        anthropic_api_key=api_key,
        allowed_user_ids=bots[0].allowed_user_ids,
        claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5").strip(),
        max_llm_calls_per_day=int(os.getenv("MAX_LLM_CALLS_PER_DAY", "150")),
        db_path=os.getenv("DB_PATH", "data/study.db").strip(),
        curriculum_path=os.getenv("CURRICULUM_PATH", "curriculum.toml").strip(),
        wordlist_dir=os.getenv("WORDLIST_DIR", "wordlists").strip(),
        bots=bots,
    )
