from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .config import DEFAULT_TZ, REMINDER_KINDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'A2',
    goal TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    tz TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    paused INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    last_active_day TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    times TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, kind)
);
CREATE TABLE IF NOT EXISTS reminder_log (
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    slot TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, slot)
);
CREATE TABLE IF NOT EXISTS vocab (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    pos TEXT NOT NULL DEFAULT '',
    ipa TEXT NOT NULL DEFAULT '',
    meaning_vi TEXT NOT NULL DEFAULT '',
    example TEXT NOT NULL DEFAULT '',
    example_vi TEXT NOT NULL DEFAULT '',
    box INTEGER NOT NULL DEFAULT 0,
    due_at TEXT NOT NULL,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, word)
);
CREATE INDEX IF NOT EXISTS idx_vocab_due ON vocab (user_id, due_at);
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS lessons (
    level TEXT NOT NULL,
    pos INTEGER NOT NULL,
    grammar TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (level, pos, grammar)
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    score REAL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Thêm cột mới cho database tạo từ phiên bản cũ."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
        if "week_pos" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN week_pos INTEGER NOT NULL DEFAULT 0")
        if "week_started" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN week_started TEXT NOT NULL DEFAULT ''")
        vcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(vocab)")}
        if "ipa" not in vcols:
            self.conn.execute("ALTER TABLE vocab ADD COLUMN ipa TEXT NOT NULL DEFAULT ''")

    # ---- users ----
    def ensure_user(self, user_id: int, name: str = "") -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO users (id, name, tz, created_at) VALUES (?,?,?,?)",
                (user_id, name, DEFAULT_TZ, iso(utcnow())),
            )
            for kind, (_, times) in REMINDER_KINDS.items():
                self.conn.execute(
                    "INSERT INTO reminders (user_id, kind, times) VALUES (?,?,?)",
                    (user_id, kind, times),
                )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return row

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def all_users(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users").fetchall()

    _USER_FIELDS = {
        "name", "level", "goal", "interests", "tz", "paused", "week_pos", "week_started",
    }

    # ---- bài học đã soạn (dùng chung cho mọi người cùng cấp và tuần) ----
    def get_lesson(self, level: str, pos: int, grammar: str) -> str | None:
        row = self.conn.execute(
            "SELECT content FROM lessons WHERE level=? AND pos=? AND grammar=?",
            (level, pos, grammar),
        ).fetchone()
        return row["content"] if row else None

    def save_lesson(self, level: str, pos: int, grammar: str, content: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO lessons (level, pos, grammar, content) VALUES (?,?,?,?)",
            (level, pos, grammar, content),
        )
        self.conn.commit()

    def update_user(self, user_id: int, **fields) -> None:
        bad = set(fields) - self._USER_FIELDS
        if bad:
            raise ValueError(f"Trường không hợp lệ: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), user_id)
        )
        self.conn.commit()

    # ---- reminders ----
    def get_reminders(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM reminders WHERE user_id=? ORDER BY kind", (user_id,)
        ).fetchall()

    def set_reminder(
        self, user_id: int, kind: str, times: str | None = None, enabled: bool | None = None
    ) -> None:
        if kind not in REMINDER_KINDS:
            raise ValueError(kind)
        if times is not None:
            self.conn.execute(
                "UPDATE reminders SET times=? WHERE user_id=? AND kind=?",
                (times, user_id, kind),
            )
        if enabled is not None:
            self.conn.execute(
                "UPDATE reminders SET enabled=? WHERE user_id=? AND kind=?",
                (int(enabled), user_id, kind),
            )
        self.conn.commit()

    def claim_slot(self, user_id: int, kind: str, slot: str) -> bool:
        """Đánh dấu đã gửi nhắc; trả về False nếu slot này đã gửi rồi."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO reminder_log (user_id, kind, slot) VALUES (?,?,?)",
            (user_id, kind, slot),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def prune_slots(self, before_date: str) -> None:
        """Xóa log nhắc cũ. slot có dạng 'YYYY-MM-DD HH:MM'."""
        self.conn.execute("DELETE FROM reminder_log WHERE slot < ?", (before_date,))
        self.conn.commit()

    # ---- vocab ----
    def add_vocab(
        self,
        user_id: int,
        word: str,
        pos: str = "",
        meaning_vi: str = "",
        example: str = "",
        example_vi: str = "",
        ipa: str = "",
    ) -> bool:
        now = iso(utcnow())
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO vocab "
            "(user_id, word, pos, ipa, meaning_vi, example, example_vi, due_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, word.strip().lower(), pos, ipa, meaning_vi, example, example_vi, now, now),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def due_vocab(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM vocab WHERE user_id=? AND due_at<=? ORDER BY due_at LIMIT ?",
            (user_id, iso(utcnow()), limit),
        ).fetchall()

    def count_due(self, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM vocab WHERE user_id=? AND due_at<=?",
            (user_id, iso(utcnow())),
        ).fetchone()[0]

    def count_vocab(self, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM vocab WHERE user_id=?", (user_id,)
        ).fetchone()[0]

    def get_vocab(self, user_id: int, vocab_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM vocab WHERE id=? AND user_id=?", (vocab_id, user_id)
        ).fetchone()

    def known_words(self, user_id: int, limit: int = 300) -> list[str]:
        rows = self.conn.execute(
            "SELECT word FROM vocab WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [r["word"] for r in rows]

    def weak_words(self, user_id: int, limit: int = 10) -> list[str]:
        rows = self.conn.execute(
            "SELECT word FROM vocab WHERE user_id=? AND lapses>0 "
            "ORDER BY lapses DESC, box ASC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [r["word"] for r in rows]

    def apply_review(
        self, user_id: int, vocab_id: int, box: int, due_at: dt.datetime, lapsed: bool
    ) -> None:
        self.conn.execute(
            "UPDATE vocab SET box=?, due_at=?, reps=reps+1, lapses=lapses+? "
            "WHERE id=? AND user_id=?",
            (box, iso(due_at), int(lapsed), vocab_id, user_id),
        )
        self.conn.commit()

    # ---- mistakes ----
    def add_mistake(self, user_id: int, note: str) -> None:
        self.conn.execute(
            "INSERT INTO mistakes (user_id, note, created_at) VALUES (?,?,?)",
            (user_id, note, iso(utcnow())),
        )
        self.conn.commit()

    def recent_mistakes(self, user_id: int, limit: int = 8) -> list[str]:
        rows = self.conn.execute(
            "SELECT note FROM mistakes WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [r["note"] for r in rows]

    # ---- usage limit ----
    def calls_today(self, user_id: int) -> int:
        day = utcnow().date().isoformat()
        row = self.conn.execute(
            "SELECT calls FROM usage WHERE user_id=? AND day=?", (user_id, day)
        ).fetchone()
        return row["calls"] if row else 0

    def add_call(self, user_id: int) -> None:
        day = utcnow().date().isoformat()
        self.conn.execute(
            "INSERT INTO usage (user_id, day, calls) VALUES (?,?,1) "
            "ON CONFLICT(user_id, day) DO UPDATE SET calls=calls+1",
            (user_id, day),
        )
        self.conn.commit()

    # ---- activity / streak ----
    def log_activity(
        self, user_id: int, kind: str, score: float | None, today_local: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO activity (user_id, kind, score, created_at) VALUES (?,?,?,?)",
            (user_id, kind, score, iso(utcnow())),
        )
        user = self.get_user(user_id)
        if user and user["last_active_day"] != today_local:
            yesterday = (dt.date.fromisoformat(today_local) - dt.timedelta(days=1)).isoformat()
            streak = user["streak"] + 1 if user["last_active_day"] == yesterday else 1
            self.conn.execute(
                "UPDATE users SET streak=?, last_active_day=? WHERE id=?",
                (streak, today_local, user_id),
            )
        self.conn.commit()

    def stats_since(self, user_id: int, since: dt.datetime) -> dict:
        rows = self.conn.execute(
            "SELECT kind, COUNT(*) n, AVG(score) avg FROM activity "
            "WHERE user_id=? AND created_at>=? GROUP BY kind",
            (user_id, iso(since)),
        ).fetchall()
        return {r["kind"]: {"n": r["n"], "avg": r["avg"]} for r in rows}

    def delete_user(self, user_id: int) -> None:
        for table in ("reminders", "reminder_log", "vocab", "mistakes", "usage", "activity"):
            self.conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
        self.conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        self.conn.commit()
