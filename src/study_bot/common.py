"""Hàm dùng chung cho các handler."""

from __future__ import annotations

import datetime as dt
import html
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import Settings
from .curriculum import Curriculum
from .db import Database, utcnow
from .llm import LLM

log = logging.getLogger(__name__)

Ctx = ContextTypes.DEFAULT_TYPE


@dataclass
class Deps:
    settings: Settings
    db: Database
    llm: LLM
    curriculum: Curriculum
    # trạng thái tạm thời theo người dùng (mất khi khởi động lại bot)
    state: dict[int, dict[str, Any]] = field(default_factory=dict)


def deps(context: Ctx) -> Deps:
    return context.application.bot_data["deps"]


def st(context: Ctx, uid: int) -> dict[str, Any]:
    return deps(context).state.setdefault(uid, {})


def reset_mode(context: Ctx, uid: int) -> None:
    deps(context).state[uid] = {}


def h(text: object) -> str:
    return html.escape(str(text), quote=False)


def button(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(list(rows))


async def say(
    context: Ctx, uid: int, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    # Trong chat riêng, chat_id trùng với user id.
    await context.bot.send_message(
        chat_id=uid,
        text=text[:4000],
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


def local_today(user: Any) -> str:
    try:
        tz = ZoneInfo(user["tz"])
    except Exception:
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    return dt.datetime.now(tz).date().isoformat()


def user_dict(context: Ctx, uid: int) -> dict[str, Any]:
    """Hồ sơ người dùng kèm chủ điểm của tuần học hiện tại (khóa 'focus')."""
    d = deps(context)
    row = d.db.get_user(uid)
    u = dict(row) if row else {"level": "A2", "goal": "", "interests": "", "week_pos": 0}
    u["focus"] = d.curriculum.week(u["level"], u["week_pos"])
    last = max(d.curriculum.length(u["level"]) - 1, 0)
    u["week_no"] = min(u["week_pos"], last) + 1
    return u


async def llm_call(
    context: Ctx, uid: int, fn: Callable[..., Awaitable[Any]], *args: Any
) -> Any | None:
    """Gọi Claude có giới hạn số lần mỗi ngày; lỗi thì báo người dùng và trả None."""
    d = deps(context)
    if d.db.calls_today(uid) >= d.settings.max_llm_calls_per_day:
        await say(
            context,
            uid,
            "Hôm nay bạn đã dùng hết số lượt gọi AI cho phép. Mai mình tiếp tục nhé. "
            "(Ôn từ bằng /review vẫn dùng được.)",
        )
        return None
    d.db.add_call(uid)
    try:
        return await fn(*args)
    except Exception:
        log.exception("Lỗi khi gọi Claude")
        await say(context, uid, "Mình gặp lỗi khi gọi AI, bạn thử lại sau ít phút nhé.")
        return None


def fmt_word(w: dict[str, Any]) -> str:
    pos = f" <i>({h(w['pos'])})</i>" if w.get("pos") else ""
    ipa = f" {h(w['ipa'])}" if w.get("ipa") else ""
    out = f"• <b>{h(w['word'])}</b>{ipa}{pos}: {h(w['meaning_vi'])}"
    if w.get("example"):
        out += f"\n   <i>{h(w['example'])}</i>"
        if w.get("example_vi"):
            out += f"\n   {h(w['example_vi'])}"
    return out


def utc_iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")
