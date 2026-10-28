from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ApplicationHandlerStop

from . import flows
from .common import Ctx, button, deps, h, kb, llm_call, local_today, reset_mode, say, st, user_dict
from .config import LEVELS, REMINDER_KINDS
from .db import utcnow
from .reminders import due_slots, parse_times

log = logging.getLogger(__name__)

HELP = """<b>Trợ lý học tiếng Anh</b>

<b>Học</b>
/words [n] – nhận n từ mới (mặc định 5)
/review – ôn từ đến hạn (lặp lại ngắt quãng)
/exercise [n] – làm bài tập (mặc định 5 câu)
/practice [chủ đề] – hội thoại tiếng Anh, bot sửa lỗi
/ask câu hỏi – hỏi về ngữ pháp/từ vựng
/stop – dừng hoạt động đang chạy

<b>Giáo án</b>
/plan – xem chủ điểm tuần này và các tuần tới
/lesson – bài học ngữ pháp của tuần
/nextweek – sang tuần kế tiếp ngay (mặc định tự chuyển sau 7 ngày)

<b>Cá nhân hóa</b>
/level B1 – đặt trình độ (A1–C2)
/goal mục tiêu – ví dụ: giao tiếp đi du lịch, IELTS 6.5
/interests chủ đề – ví dụ: nấu ăn, công nghệ, bóng đá
/tz Asia/Ho_Chi_Minh – múi giờ

<b>Nhắc học</b>
/reminders – xem và bật/tắt nhắc
/remind words 07:30,19:00 – đổi giờ nhắc (words, review, exercise, practice)
/pause, /resume – tạm dừng/bật lại mọi nhắc

/stats – tiến độ của bạn
/deleteme – xóa toàn bộ dữ liệu của bạn"""


def _arg(context: Ctx) -> str:
    return " ".join(context.args or []).strip()


# ------------------------------------------------------------------ gate
async def gate(update: Update, context: Ctx) -> None:
    """Chặn mọi người không nằm trong danh sách cho phép."""
    d = deps(context)
    user, chat, msg = update.effective_user, update.effective_chat, update.effective_message
    if user is None or chat is None or chat.type != "private":
        raise ApplicationHandlerStop
    if user.id in d.settings.allowed_user_ids:
        row = d.db.ensure_user(user.id, user.first_name or "")
        if not row["week_started"]:
            d.db.update_user(user.id, week_started=local_today(row))
        return
    cmd = (msg.text or "").split()[0].split("@")[0] if msg and msg.text else ""
    if cmd in ("/start", "/myid"):
        await msg.reply_text(
            f"ID Telegram của bạn: {user.id}\n"
            "Bot này là bot riêng. Để dùng, hãy thêm ID này vào danh sách user ID của bot "
            "trong file .env (BOTn_USER_IDS) rồi khởi động lại bot."
        )
    raise ApplicationHandlerStop


# ------------------------------------------------------------------ cơ bản
async def start(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    reset_mode(context, uid)
    name = update.effective_user.first_name or "bạn"
    await say(
        context,
        uid,
        f"Chào {h(name)}! 👋 Mình là trợ lý học tiếng Anh của bạn. Trong ngày mình sẽ nhắc bạn "
        "học từ mới, ôn từ, làm bài tập và luyện hội thoại.\n\n"
        "Trước hết, bạn chọn trình độ hiện tại:",
        kb(
            [button(lv, f"lvl:{lv}") for lv in LEVELS[:3]],
            [button(lv, f"lvl:{lv}") for lv in LEVELS[3:]],
        ),
    )


async def help_cmd(update: Update, context: Ctx) -> None:
    await say(context, update.effective_user.id, HELP)


async def myid(update: Update, context: Ctx) -> None:
    await say(context, update.effective_user.id, f"ID của bạn: <code>{update.effective_user.id}</code>")


async def stop(update: Update, context: Ctx) -> None:
    await flows.stop_mode(context, update.effective_user.id)


# ------------------------------------------------------------------ học
def _num(context: Ctx, default: int, lo: int, hi: int) -> int:
    arg = _arg(context)
    if arg.isdigit():
        return max(lo, min(hi, int(arg)))
    return default


async def words(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    await flows.send_new_words(context, uid, _num(context, 5, 1, 10))


async def review(update: Update, context: Ctx) -> None:
    await flows.start_review(context, update.effective_user.id)


async def exercise(update: Update, context: Ctx) -> None:
    await flows.start_exercises(context, update.effective_user.id, _num(context, 5, 1, 10))


async def practice(update: Update, context: Ctx) -> None:
    await flows.start_practice(context, update.effective_user.id, _arg(context))


async def ask(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    question = _arg(context)
    if not question:
        await say(context, uid, "Cách dùng: /ask sự khác nhau giữa 'since' và 'for'?")
        return
    await _explain(context, uid, question)


async def _explain(context: Ctx, uid: int, question: str) -> None:
    d = deps(context)
    answer = await llm_call(context, uid, d.llm.explain, user_dict(context, uid), question[:2000])
    if answer:
        await say(context, uid, h(answer))


async def text_message(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    text = (update.effective_message.text or "").strip()
    if not text:
        return
    state = st(context, uid)
    mode = state.get("mode")
    if mode == "practice":
        await flows.practice_turn(context, uid, text[:2000])
    elif mode == "exercise":
        await flows.answer_text(context, uid, text[:2000])
    else:
        await _explain(context, uid, text)


# ------------------------------------------------------------------ cá nhân hóa
def set_level(context: Ctx, uid: int, lv: str) -> None:
    """Đổi trình độ; đổi sang cấp khác thì giáo án bắt đầu lại từ tuần 1."""
    d = deps(context)
    user = d.db.get_user(uid)
    if user["level"] == lv:
        return
    d.db.update_user(uid, level=lv, week_pos=0, week_started=local_today(user))


async def level(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    lv = _arg(context).upper()
    if lv not in LEVELS:
        await say(context, uid, f"Chọn một trong: {', '.join(LEVELS)}. Ví dụ: /level B1")
        return
    set_level(context, uid, lv)
    await say(context, uid, f"Đã đặt trình độ: <b>{lv}</b>. Xem giáo án bằng /plan.")


# ------------------------------------------------------------------ giáo án
async def plan(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    d = deps(context)
    user = d.db.get_user(uid)
    total = d.curriculum.length(user["level"])
    if not total:
        await say(context, uid, "Chưa có giáo án cho trình độ này.")
        return
    pos = min(user["week_pos"], total - 1)
    lines = [f"🗓 <b>Giáo án {user['level']}</b> (tuần {pos + 1}/{total})", ""]
    for i in range(pos, min(pos + 3, total)):
        wk = d.curriculum.week(user["level"], i)
        mark = "👉" if i == pos else "   "
        lines.append(f"{mark} <b>Tuần {i + 1}</b>\n      Ngữ pháp: {h(wk.grammar)}\n      Chủ đề: {h(wk.theme)}")
    lines.append("\nMọi từ mới, bài tập và hội thoại đều bám theo tuần hiện tại.")
    await say(
        context, uid, "\n".join(lines),
        kb([button("📘 Xem bài học", "act:lesson")]),
    )


async def lesson(update: Update, context: Ctx) -> None:
    await flows.send_lesson(context, update.effective_user.id)


async def nextweek(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    d = deps(context)
    user = d.db.get_user(uid)
    total = d.curriculum.length(user["level"])
    if user["week_pos"] + 1 >= total:
        await say(context, uid, "Bạn đang ở tuần cuối của giáo án này. Muốn học tiếp, đổi cấp bằng /level.")
        return
    d.db.update_user(uid, week_pos=user["week_pos"] + 1, week_started=local_today(user))
    await _announce_week(context, uid)


async def _announce_week(context: Ctx, uid: int, prefix: str = "") -> None:
    u = user_dict(context, uid)
    wk = u["focus"]
    await say(
        context,
        uid,
        f"{prefix}📅 <b>Tuần {u['week_no']}</b>\nNgữ pháp: {h(wk.grammar)}\nChủ đề: {h(wk.theme)}",
        kb([button("📘 Xem bài học", "act:lesson")]),
    )


async def maybe_advance_week(context: Ctx, user) -> None:
    """Sau 7 ngày ở một tuần thì tự chuyển sang tuần kế tiếp."""
    d = deps(context)
    uid = user["id"]
    today = local_today(user)
    if not user["week_started"]:
        d.db.update_user(uid, week_started=today)
        return
    days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(user["week_started"])).days
    if days < 7:
        return
    total = d.curriculum.length(user["level"])
    if user["week_pos"] + 1 < total:
        d.db.update_user(uid, week_pos=user["week_pos"] + 1, week_started=today)
        await _announce_week(context, uid, prefix="Tuần mới bắt đầu! ")
    elif total:
        d.db.update_user(uid, week_started=today)
        await say(
            context, uid,
            f"🎓 Bạn đã học hết giáo án {user['level']}. Muốn lên cấp mới, dùng /level (ví dụ /level B2). "
            "Hoặc cứ tiếp tục luyện tập, bot vẫn giữ chủ điểm tuần cuối.",
        )


async def goal(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    text = _arg(context)[:200]
    if not text:
        await say(context, uid, "Ví dụ: /goal giao tiếp khi đi du lịch")
        return
    deps(context).db.update_user(uid, goal=text)
    await say(context, uid, f"Đã lưu mục tiêu: {h(text)}")


async def interests(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    text = _arg(context)[:200]
    if not text:
        await say(context, uid, "Ví dụ: /interests nấu ăn, công nghệ, bóng đá")
        return
    deps(context).db.update_user(uid, interests=text)
    await say(context, uid, f"Đã lưu chủ đề yêu thích: {h(text)}")


async def tz(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    name = _arg(context)
    try:
        ZoneInfo(name)
        ok = bool(name)
    except Exception:
        ok = False
    if not ok:
        await say(context, uid, "Múi giờ không hợp lệ. Ví dụ: /tz Asia/Ho_Chi_Minh")
        return
    deps(context).db.update_user(uid, tz=name)
    await say(context, uid, f"Đã đặt múi giờ: {h(name)}")


# ------------------------------------------------------------------ nhắc học
def _reminders_view(context: Ctx, uid: int):
    d = deps(context)
    user = d.db.get_user(uid)
    lines = ["⏰ <b>Lịch nhắc</b>" + (" (đang tạm dừng)" if user["paused"] else "")]
    rows = []
    for r in d.db.get_reminders(uid):
        name = REMINDER_KINDS[r["kind"]][0]
        state = "bật" if r["enabled"] else "tắt"
        lines.append(f"• {name}: {r['times']} – {state}")
        label = ("🔕 Tắt " if r["enabled"] else "🔔 Bật ") + name
        rows.append([button(label, f"rem:{r['kind']}")])
    lines.append(f"\nMúi giờ: {h(user['tz'])}. Đổi giờ: /remind words 07:30,19:00")
    return "\n".join(lines), kb(*rows)


async def reminders(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    text, markup = _reminders_view(context, uid)
    await say(context, uid, text, markup)


async def remind(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    d = deps(context)
    args = context.args or []
    kinds = ", ".join(REMINDER_KINDS)
    if len(args) < 2 or args[0] not in REMINDER_KINDS:
        await say(context, uid, f"Cách dùng: /remind &lt;{kinds}&gt; &lt;HH:MM,HH:MM | on | off&gt;")
        return
    kind, value = args[0], " ".join(args[1:])
    if value.lower() in ("on", "off"):
        d.db.set_reminder(uid, kind, enabled=value.lower() == "on")
    else:
        times = parse_times(value)
        if times is None:
            await say(context, uid, "Giờ không hợp lệ. Ví dụ: /remind words 07:30,19:00 (tối đa 6 mốc)")
            return
        d.db.set_reminder(uid, kind, times=times, enabled=True)
    text, markup = _reminders_view(context, uid)
    await say(context, uid, text, markup)


async def pause(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    deps(context).db.update_user(uid, paused=1)
    await say(context, uid, "⏸ Đã tạm dừng mọi lời nhắc. /resume để bật lại.")


async def resume(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    deps(context).db.update_user(uid, paused=0)
    await say(context, uid, "▶️ Đã bật lại lời nhắc.")


# ------------------------------------------------------------------ thống kê / xóa dữ liệu
async def stats(update: Update, context: Ctx) -> None:
    uid = update.effective_user.id
    d = deps(context)
    user = d.db.get_user(uid)
    week = d.db.stats_since(uid, utcnow() - dt.timedelta(days=7))
    names = {"review": "phiên ôn từ", "exercise": "bài tập", "practice": "buổi hội thoại"}
    lines = [
        f"📊 <b>Tiến độ</b> (trình độ {user['level']})",
        f"🔥 Chuỗi ngày học liên tiếp: {user['streak']}",
        f"📚 Tổng số từ: {d.db.count_vocab(uid)}, đến hạn ôn: {d.db.count_due(uid)}",
        "",
        "<b>7 ngày qua</b>",
    ]
    if not week:
        lines.append("Chưa có hoạt động nào.")
    for kind, label in names.items():
        if kind in week:
            row = week[kind]
            extra = f", điểm TB {row['avg']:.1f}/10" if row["avg"] is not None else ""
            lines.append(f"• {row['n']} {label}{extra}")
    mistakes = d.db.recent_mistakes(uid, 3)
    if mistakes:
        lines += ["", "<b>Lỗi gần đây</b>"] + [f"• {h(m)}" for m in mistakes]
    await say(context, uid, "\n".join(lines))


async def deleteme(update: Update, context: Ctx) -> None:
    await say(
        context,
        update.effective_user.id,
        "Xóa toàn bộ từ vựng, tiến độ và cài đặt của bạn? Việc này không hoàn tác được.",
        kb([button("Xóa hết", "del:yes"), button("Hủy", "del:no")]),
    )


# ------------------------------------------------------------------ nút bấm
async def on_callback(update: Update, context: Ctx) -> None:
    q = update.callback_query
    uid = update.effective_user.id
    d = deps(context)
    data = q.data or ""
    parts = data.split(":")
    await q.answer()

    async def strip_buttons() -> None:
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    kind = parts[0]
    if kind == "lvl" and len(parts) == 2 and parts[1] in LEVELS:
        set_level(context, uid, parts[1])
        await strip_buttons()
        await say(
            context,
            uid,
            f"Trình độ: <b>{parts[1]}</b>. Tiếp theo hãy cho mình biết mục tiêu và chủ đề bạn thích để bài học sát hơn:\n"
            "/goal giao tiếp khi đi du lịch\n/interests nấu ăn, công nghệ\n\n"
            "Nhắc học mặc định: từ mới 6 lần/ngày (07:30, 09:30, 11:00, 14:30, 16:00, 19:00), ôn từ 12:30 và 20:00, bài tập 17:30, hội thoại 21:00 (giờ Việt Nam). "
            "Đổi bằng /reminders. Bắt đầu ngay với /words nhé!",
        )
    elif kind == "act" and len(parts) == 2:
        await strip_buttons()
        if parts[1] == "review":
            await flows.start_review(context, uid)
        elif parts[1] == "exercise":
            await flows.start_exercises(context, uid)
        elif parts[1] == "practice":
            await flows.start_practice(context, uid)
        elif parts[1] == "words":
            await flows.send_new_words(context, uid, 5)
        elif parts[1] == "lesson":
            await flows.send_lesson(context, uid)
    elif kind == "rv" and len(parts) >= 3 and parts[2].isdigit():
        vocab_id = int(parts[2])
        row = d.db.get_vocab(uid, vocab_id)
        if row is None:
            return
        if parts[1] == "show":
            await q.edit_message_text(
                flows.card_back(row), parse_mode="HTML", reply_markup=flows.rating_keyboard(vocab_id)
            )
        elif parts[1] == "rate" and len(parts) == 4 and parts[3].isdigit() and int(parts[3]) <= 3:
            await strip_buttons()
            if flows.apply_rating(context, uid, vocab_id, int(parts[3])):
                await flows.send_card(context, uid)
    elif kind == "mc" and len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        msg = await flows.answer_choice(context, uid, int(parts[1]), int(parts[2]))
        if msg is not None:
            await strip_buttons()
            await say(context, uid, msg)
            await flows.send_exercise(context, uid)
    elif kind == "rem" and len(parts) == 2 and parts[1] in REMINDER_KINDS:
        cur = {r["kind"]: r["enabled"] for r in d.db.get_reminders(uid)}
        d.db.set_reminder(uid, parts[1], enabled=not cur.get(parts[1], 1))
        text, markup = _reminders_view(context, uid)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    elif kind == "del" and len(parts) == 2:
        await strip_buttons()
        if parts[1] == "yes":
            d.db.delete_user(uid)
            d.state.pop(uid, None)
            await say(context, uid, "Đã xóa toàn bộ dữ liệu. Gõ /start nếu muốn bắt đầu lại.")
        else:
            await say(context, uid, "Đã hủy.")


# ------------------------------------------------------------------ nhắc học theo giờ
def _local_hour(user) -> int:
    try:
        tz = ZoneInfo(user["tz"])
    except Exception:
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    return dt.datetime.now(tz).hour


async def tick(context: Ctx) -> None:
    d = deps(context)
    now = utcnow()
    d.db.prune_slots((now - dt.timedelta(days=3)).date().isoformat())
    for user in d.db.all_users():
        uid = user["id"]
        if user["paused"] or uid not in d.settings.allowed_user_ids:
            continue
        try:
            if _local_hour(user) >= 7:  # không báo tuần mới lúc nửa đêm
                await maybe_advance_week(context, user)
        except Exception:
            log.exception("Không cập nhật được tuần học của %s", uid)
        rems = [(r["kind"], r["times"], bool(r["enabled"])) for r in d.db.get_reminders(uid)]
        for kind, slot in due_slots(user["tz"], rems, now):
            if not d.db.claim_slot(uid, kind, slot):
                continue
            try:
                await fire_reminder(context, uid, kind)
            except Exception:
                log.exception("Không gửi được nhắc %s cho %s", kind, uid)


async def fire_reminder(context: Ctx, uid: int, kind: str) -> None:
    d = deps(context)
    user = d.db.get_user(uid)
    streak = f" 🔥{user['streak']}" if user["streak"] >= 2 else ""
    if kind == "words":
        await flows.send_new_words(context, uid, 5, header=f"☀️ <b>Từ mới hôm nay</b>{streak}")
    elif kind == "review":
        due = d.db.count_due(uid)
        if due:
            await say(
                context, uid, f"📖 Bạn có <b>{due}</b> từ cần ôn. Chỉ mất vài phút thôi!{streak}",
                kb([button("Ôn ngay", "act:review")]),
            )
    elif kind == "exercise":
        await say(
            context, uid, f"📝 Đến giờ làm bài tập rồi!{streak}",
            kb([button("Làm bài tập", "act:exercise")]),
        )
    elif kind == "practice":
        await say(
            context, uid, f"💬 Luyện nói một chút trước khi ngủ nhé?{streak}",
            kb([button("Bắt đầu hội thoại", "act:practice")]),
        )


async def on_error(update: object, context: Ctx) -> None:
    log.error("Lỗi không xử lý được", exc_info=context.error)
