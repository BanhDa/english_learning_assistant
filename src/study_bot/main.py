from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import signal

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import handlers as hd
from .common import Deps
from .config import BotConfig, Settings, load_settings
from .curriculum import Curriculum
from .db import Database
from .llm import LLM

log = logging.getLogger(__name__)

COMMANDS = [
    ("plan", "Giáo án tuần này"),
    ("lesson", "Bài học của tuần"),
    ("words", "Nhận từ mới"),
    ("review", "Ôn từ đến hạn"),
    ("exercise", "Làm bài tập"),
    ("practice", "Hội thoại tiếng Anh"),
    ("ask", "Hỏi về tiếng Anh"),
    ("stop", "Dừng hoạt động hiện tại"),
    ("reminders", "Xem/bật/tắt lời nhắc"),
    ("stats", "Tiến độ học"),
    ("level", "Đặt trình độ"),
    ("goal", "Đặt mục tiêu"),
    ("interests", "Đặt chủ đề yêu thích"),
    ("help", "Hướng dẫn"),
]

HANDLERS = {
    "start": hd.start,
    "help": hd.help_cmd,
    "myid": hd.myid,
    "stop": hd.stop,
    "words": hd.words,
    "review": hd.review,
    "exercise": hd.exercise,
    "practice": hd.practice,
    "ask": hd.ask,
    "level": hd.level,
    "plan": hd.plan,
    "lesson": hd.lesson,
    "nextweek": hd.nextweek,
    "goal": hd.goal,
    "interests": hd.interests,
    "tz": hd.tz,
    "reminders": hd.reminders,
    "remind": hd.remind,
    "pause": hd.pause,
    "resume": hd.resume,
    "stats": hd.stats,
    "deleteme": hd.deleteme,
}


def build_app(
    bot: BotConfig, settings: Settings, db: Database, llm: LLM, curriculum: Curriculum
) -> Application:
    """Dựng một Application cho một bot. Database, Claude và giáo án dùng chung giữa các bot."""
    if not bot.allowed_user_ids:
        log.warning(
            "Bot '%s': danh sách user ID đang trống nên sẽ từ chối mọi người. "
            "Nhắn /start cho bot này để lấy ID rồi điền vào .env.",
            bot.name,
        )
    # Mỗi bot có bản Settings riêng: token và danh sách người được phép của chính nó.
    # Nhờ vậy mỗi bot chỉ gửi nhắc cho người của nó, qua đúng bot đó.
    own = dataclasses.replace(
        settings, telegram_token=bot.token, allowed_user_ids=bot.allowed_user_ids
    )
    app = ApplicationBuilder().token(bot.token).build()
    app.bot_data["deps"] = Deps(settings=own, db=db, llm=llm, curriculum=curriculum)

    # group -1: kiểm tra quyền trước mọi handler khác
    app.add_handler(TypeHandler(Update, hd.gate), group=-1)
    for name, fn in HANDLERS.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(hd.on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, hd.text_message))
    app.add_error_handler(hd.on_error)
    app.job_queue.run_repeating(hd.tick, interval=60, first=15, name="reminders")
    return app


async def run_all(apps: list[tuple[BotConfig, Application]]) -> None:
    """Chạy nhiều bot trong cùng một tiến trình và dừng gọn khi nhận Ctrl+C/SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    initialized: list[Application] = []
    running: list[Application] = []
    try:
        for cfg, app in apps:
            await app.initialize()
            initialized.append(app)
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        for cfg, app in apps:
            await app.start()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            running.append(app)
            log.info("Bot '%s' (@%s) đang chạy", cfg.name, app.bot.username)
        await stop.wait()
        log.info("Đang dừng...")
    finally:
        for app in reversed(running):
            await app.updater.stop()
            await app.stop()
        for app in reversed(initialized):
            await app.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(prog="study_bot", description="Trợ lý học tiếng Anh trên Telegram")
    parser.add_argument(
        "--env", metavar="FILE", default=None, help="file cấu hình (mặc định .env)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx ghi URL (có chứa token bot) ở mức INFO, nên hạ xuống.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings(args.env)
    db = Database(settings.db_path)
    llm = LLM(settings.anthropic_api_key, settings.claude_model)
    curriculum = Curriculum(settings.curriculum_path, settings.wordlist_dir)

    apps = [(b, build_app(b, settings, db, llm, curriculum)) for b in settings.bots]
    asyncio.run(run_all(apps))


if __name__ == "__main__":
    main()
