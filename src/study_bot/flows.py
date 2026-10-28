"""Các luồng học: từ mới, ôn từ, bài tập, hội thoại."""

from __future__ import annotations

import asyncio
import logging
import random

from telegram import InputMediaPhoto
from telegram.constants import ParseMode

from . import ipa as ipa_mod
from . import srs
from .cards import render_card
from .common import (
    Ctx,
    button,
    deps,
    fmt_word,
    h,
    kb,
    llm_call,
    local_today,
    reset_mode,
    say,
    st,
    user_dict,
    utc_iso_now,
)
from .db import utcnow

log = logging.getLogger(__name__)

REVIEW_SESSION_SIZE = 10
CHAT_HISTORY_LIMIT = 20


# ---------------------------------------------------------------- từ mới
async def send_new_words(context: Ctx, uid: int, n: int = 5, header: str = "") -> None:
    d = deps(context)
    user = user_dict(context, uid)
    # Nếu có wordlists/<cấp>.txt thì học đúng thứ tự trong danh sách đó,
    # Claude chỉ soạn nghĩa và ví dụ. Không có thì Claude chọn từ theo chủ đề của tuần.
    listed = d.curriculum.wordlist_candidates(
        user["level"], set(d.db.known_words(uid, 100000)), n
    )
    if listed:
        words = await llm_call(context, uid, d.llm.explain_words, user, listed)
    else:
        words = await llm_call(context, uid, d.llm.new_words, user, n, d.db.known_words(uid))
    if words is None:
        return
    for w in words:
        w["word"] = w["word"].strip().lower()
    # Phiên âm: ưu tiên từ điển, không có thì dùng phiên âm Claude đưa ra.
    dictionary_ipa = await ipa_mod.lookup_many([w["word"] for w in words])
    for w in words:
        w["ipa"] = dictionary_ipa.get(w["word"]) or ipa_mod.normalize(w.get("ipa"))
    added = [w for w in words if d.db.add_vocab(
        uid, w["word"], w.get("pos", ""), w.get("meaning_vi", ""),
        w.get("example", ""), w.get("example_vi", ""), w["ipa"],
    )]
    if not added:
        await say(context, uid, "Chưa tạo được từ mới nào (có thể trùng từ đã học). Thử lại nhé.")
        return
    footer = "Các từ này đã vào danh sách ôn. Dùng /review để luyện nhớ."
    markup = kb([button("📖 Ôn từ ngay", "act:review")])
    if await _send_card_images(context, uid, added, header):
        await say(context, uid, footer, markup)
        return
    # Không vẽ/gửi được ảnh thì gửi bản chữ để người học không mất bài.
    text = (header + "\n\n" if header else "") + "\n\n".join(fmt_word(w) for w in added)
    await say(context, uid, f"{text}\n\n{footer}", markup)


async def _send_card_images(
    context: Ctx, uid: int, words: list[dict], header: str
) -> bool:
    try:
        images = [
            await asyncio.to_thread(
                render_card,
                w["word"], w.get("pos", ""), w.get("ipa", ""),
                w.get("meaning_vi", ""), w.get("example", ""), w.get("example_vi", ""),
            )
            for w in words
        ]
        caption = header or None
        if len(images) == 1:
            await context.bot.send_photo(
                chat_id=uid, photo=images[0], caption=caption, parse_mode=ParseMode.HTML
            )
        else:
            media = [
                InputMediaPhoto(
                    media=img,
                    caption=caption if i == 0 else None,
                    parse_mode=ParseMode.HTML if i == 0 and caption else None,
                )
                for i, img in enumerate(images)
            ]
            await context.bot.send_media_group(chat_id=uid, media=media)
        return True
    except Exception:
        log.exception("Không gửi được ảnh flashcard, chuyển sang tin nhắn chữ")
        return False


# ---------------------------------------------------------------- giáo án
async def send_lesson(context: Ctx, uid: int) -> None:
    d = deps(context)
    user = user_dict(context, uid)
    focus = user.get("focus")
    if focus is None:
        await say(context, uid, "Chưa có giáo án cho trình độ này. Bạn vẫn có thể dùng /words, /exercise, /practice.")
        return
    pos = min(user["week_pos"], d.curriculum.length(user["level"]) - 1)
    text = d.db.get_lesson(user["level"], pos, focus.grammar)
    if text is None:
        text = await llm_call(context, uid, d.llm.lesson, user, focus.grammar, focus.theme)
        if not text:
            return
        d.db.save_lesson(user["level"], pos, focus.grammar, text)
    await say(
        context,
        uid,
        f"📘 <b>Tuần {pos + 1}/{d.curriculum.length(user['level'])}</b>\n\n{h(text)}",
        kb(
            [button("🆕 Học từ của tuần", "act:words"), button("📝 Làm bài tập", "act:exercise")],
        ),
    )


# ---------------------------------------------------------------- ôn từ
async def start_review(context: Ctx, uid: int) -> None:
    reset_mode(context, uid)
    st(context, uid)["rv_done"] = 0
    await send_card(context, uid)


async def send_card(context: Ctx, uid: int) -> None:
    d = deps(context)
    state = st(context, uid)
    done = state.get("rv_done", 0)
    rows = d.db.due_vocab(uid, 1) if done < REVIEW_SESSION_SIZE else []
    if not rows:
        if done:
            d.db.log_activity(uid, "review", None, local_today(d.db.get_user(uid)))
            left = d.db.count_due(uid)
            extra = f" Còn {left} từ đến hạn, /review để làm tiếp." if left else ""
            await say(context, uid, f"✅ Xong phiên ôn: {done} từ.{extra}")
        elif d.db.count_vocab(uid) == 0:
            await say(context, uid, "Chưa có từ nào. Dùng /words để nhận từ mới.")
        else:
            await say(context, uid, "🎉 Không còn từ nào đến hạn ôn. Nghỉ ngơi hoặc thử /exercise.")
        reset_mode(context, uid)
        return
    r = rows[0]
    pos = f" <i>({h(r['pos'])})</i>" if r["pos"] else ""
    ipa = f"\n{h(r['ipa'])}" if r["ipa"] else ""
    await say(
        context,
        uid,
        f"📖 <b>{h(r['word'])}</b>{pos}{ipa}\n\nBạn nhớ nghĩa chưa? Hãy tự nhớ trước rồi bấm hiện đáp án.",
        kb([button("👀 Hiện đáp án", f"rv:show:{r['id']}")]),
    )


def card_back(r) -> str:
    pos = f" <i>({h(r['pos'])})</i>" if r["pos"] else ""
    ipa = f"\n{h(r['ipa'])}" if r["ipa"] else ""
    text = f"📖 <b>{h(r['word'])}</b>{pos}{ipa}\n➡️ {h(r['meaning_vi'])}"
    if r["example"]:
        text += f"\n\n<i>{h(r['example'])}</i>"
        if r["example_vi"]:
            text += f"\n{h(r['example_vi'])}"
    return text


def rating_keyboard(vocab_id: int):
    return kb(
        [
            button("❌ Quên", f"rv:rate:{vocab_id}:{srs.AGAIN}"),
            button("😓 Khó", f"rv:rate:{vocab_id}:{srs.HARD}"),
            button("👍 Được", f"rv:rate:{vocab_id}:{srs.GOOD}"),
            button("⚡ Dễ", f"rv:rate:{vocab_id}:{srs.EASY}"),
        ]
    )


def apply_rating(context: Ctx, uid: int, vocab_id: int, rating: int) -> bool:
    """Trả về False nếu thẻ không tồn tại hoặc chưa đến hạn (bấm đúp)."""
    d = deps(context)
    row = d.db.get_vocab(uid, vocab_id)
    if row is None or row["due_at"] > utc_iso_now():
        return False
    box, delta, lapsed = srs.schedule(row["box"], rating)
    d.db.apply_review(uid, vocab_id, box, utcnow() + delta, lapsed)
    state = st(context, uid)
    state["rv_done"] = state.get("rv_done", 0) + 1
    return True


# ---------------------------------------------------------------- bài tập
async def start_exercises(context: Ctx, uid: int, n: int = 5) -> None:
    d = deps(context)
    reset_mode(context, uid)
    user = user_dict(context, uid)
    items = await llm_call(
        context, uid, d.llm.exercises, user, n, d.db.weak_words(uid), d.db.recent_mistakes(uid)
    )
    if items is None:
        return
    queue = []
    for ex in items:
        if not ex.get("prompt") or not ex.get("answer"):
            continue
        if ex["type"] == "multiple_choice":
            opts = [o for o in ex.get("options", []) if o]
            if ex["answer"] not in opts:
                opts.append(ex["answer"])
            if len(opts) < 2:
                continue
            random.shuffle(opts)
            ex["options"] = opts
        queue.append(ex)
    if not queue:
        await say(context, uid, "Chưa tạo được bài tập, bạn thử lại nhé.")
        return
    state = st(context, uid)
    state.update(mode="exercise", queue=queue, idx=0, correct=0)
    await say(context, uid, f"📝 <b>Bài tập ({len(queue)} câu)</b>. Gõ /stop để dừng.")
    await send_exercise(context, uid)


async def send_exercise(context: Ctx, uid: int) -> None:
    state = st(context, uid)
    idx, queue = state["idx"], state["queue"]
    if idx >= len(queue):
        await finish_exercises(context, uid)
        return
    ex = queue[idx]
    head = f"<b>Câu {idx + 1}/{len(queue)}</b>\n{h(ex['prompt'])}"
    if ex["type"] == "multiple_choice":
        rows = [[button(opt[:60], f"mc:{idx}:{i}")] for i, opt in enumerate(ex["options"])]
        await say(context, uid, head, kb(*rows))
    else:
        hint = {
            "translate_vi_en": "Dịch sang tiếng Anh, gõ câu trả lời của bạn.",
            "fill_blank": "Gõ từ/cụm từ cần điền.",
            "fix_error": "Gõ lại câu đã sửa lỗi.",
        }.get(ex["type"], "Gõ câu trả lời của bạn.")
        await say(context, uid, f"{head}\n\n<i>{hint}</i>")


async def finish_exercises(context: Ctx, uid: int) -> None:
    d = deps(context)
    state = st(context, uid)
    total, ok = len(state["queue"]), state["correct"]
    d.db.log_activity(uid, "exercise", 10 * ok / total, local_today(d.db.get_user(uid)))
    reset_mode(context, uid)
    await say(
        context,
        uid,
        f"🏁 Xong! Đúng <b>{ok}/{total}</b>. Các lỗi sai đã được ghi lại để luyện ở bài sau.",
        kb([button("📝 Làm thêm", "act:exercise")]),
    )


async def answer_choice(context: Ctx, uid: int, idx: int, choice: int) -> str | None:
    """Xử lý trắc nghiệm. Trả về None nếu bấm nhầm/bấm đúp."""
    d = deps(context)
    state = st(context, uid)
    if state.get("mode") != "exercise" or state["idx"] != idx:
        return None
    ex = state["queue"][idx]
    if ex["type"] != "multiple_choice" or not 0 <= choice < len(ex["options"]):
        return None
    chosen = ex["options"][choice]
    right = chosen.strip().lower() == ex["answer"].strip().lower()
    state["idx"] += 1
    if right:
        state["correct"] += 1
        msg = f"✅ Đúng! {h(ex['explanation_vi'])}"
    else:
        d.db.add_mistake(uid, f"{ex['prompt']} → {ex['answer']}")
        msg = f"❌ Chưa đúng. Đáp án: <b>{h(ex['answer'])}</b>\n{h(ex['explanation_vi'])}"
    return msg


async def answer_text(context: Ctx, uid: int, text: str) -> None:
    d = deps(context)
    state = st(context, uid)
    ex = state["queue"][state["idx"]]
    if ex["type"] == "multiple_choice":
        await say(context, uid, "Câu này là trắc nghiệm, bạn bấm vào một lựa chọn nhé.")
        return
    user = user_dict(context, uid)
    res = await llm_call(context, uid, d.llm.grade, user, ex, text)
    if res is None:
        return
    state["idx"] += 1
    if res["correct"]:
        state["correct"] += 1
        head = f"✅ Đúng ({res['score']}/10)."
    else:
        head = f"❌ Chưa đúng ({res['score']}/10)."
        note = res.get("mistake_note") or f"{ex['prompt']} → {ex['answer']}"
        d.db.add_mistake(uid, note)
    await say(
        context,
        uid,
        f"{head}\nCâu chuẩn: <b>{h(res['better_version'])}</b>\n{h(res['feedback_vi'])}",
    )
    await send_exercise(context, uid)


# ---------------------------------------------------------------- hội thoại
DEFAULT_TOPICS = [
    "một ngày của bạn",
    "đồ ăn và nấu ăn",
    "du lịch",
    "công việc",
    "phim ảnh và âm nhạc",
    "kế hoạch cuối tuần",
]


async def start_practice(context: Ctx, uid: int, topic: str = "") -> None:
    reset_mode(context, uid)
    user = user_dict(context, uid)
    focus = user.get("focus")
    topic = (
        topic.strip()
        or (focus.theme if focus else "")
        or user.get("interests")
        or random.choice(DEFAULT_TOPICS)
    )
    state = st(context, uid)
    state.update(mode="practice", topic=topic, history=[], turns=0)
    await say(
        context,
        uid,
        f"💬 <b>Luyện hội thoại</b> – chủ đề: {h(topic)}\n"
        "Cứ trả lời bằng tiếng Anh, mình sẽ sửa lỗi sau mỗi tin nhắn. Gõ /stop để kết thúc.",
    )
    await practice_turn(context, uid, None)


async def practice_turn(context: Ctx, uid: int, text: str | None) -> None:
    d = deps(context)
    state = st(context, uid)
    history: list[dict] = state["history"]
    if text is not None:
        history.append({"role": "user", "content": text})
    res = await llm_call(
        context, uid, d.llm.chat_turn, user_dict(context, uid), history, state["topic"],
        d.db.weak_words(uid, 5),
    )
    if res is None:
        if text is not None:
            history.pop()
        return
    history.append({"role": "assistant", "content": res["reply_en"]})
    del history[:-CHAT_HISTORY_LIMIT]
    if text is not None:
        state["turns"] += 1

    parts = []
    corrections = res.get("corrections") or []
    if corrections:
        lines = ["✏️ <b>Sửa lỗi</b>"]
        for c in corrections[:3]:
            lines.append(
                f"• <s>{h(c['original'])}</s> → <b>{h(c['fixed'])}</b>\n   {h(c['explanation_vi'])}"
            )
            d.db.add_mistake(uid, f"{c['original']} → {c['fixed']}: {c['explanation_vi']}")
        parts.append("\n".join(lines))
    elif text is not None and res.get("praise_vi"):
        parts.append(f"👏 {h(res['praise_vi'])}")
    parts.append(f"💬 {h(res['reply_en'])}")
    await say(context, uid, "\n\n".join(parts))


async def stop_mode(context: Ctx, uid: int) -> None:
    d = deps(context)
    state = st(context, uid)
    mode = state.get("mode")
    if mode == "practice" and state.get("turns", 0) >= 2:
        d.db.log_activity(uid, "practice", None, local_today(d.db.get_user(uid)))
        await say(context, uid, f"👋 Kết thúc hội thoại ({state['turns']} lượt). Làm tốt lắm!")
    elif mode:
        await say(context, uid, "Đã dừng.")
    else:
        await say(context, uid, "Hiện không có hoạt động nào đang chạy.")
    reset_mode(context, uid)
