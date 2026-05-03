"""
modules/db.py — SQLite база данных для TG Hub
"""
import json
import os
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/tghub.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы если не существуют."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS digests (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                days_back INTEGER NOT NULL,
                chats_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS digest_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                digest_id TEXT NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                priority TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                summary TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                date TEXT NOT NULL,
                views INTEGER,
                has_photo INTEGER DEFAULT 0,
                has_video INTEGER DEFAULT 0,
                url TEXT,
                UNIQUE(channel, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_digests_created ON digests(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel);
            CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date DESC);

            CREATE TABLE IF NOT EXISTS voice_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                label TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_voice_examples_created ON voice_examples(created_at DESC);

            CREATE TABLE IF NOT EXISTS publication_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                scheduled_at TEXT NOT NULL,
                published_at TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                media_path TEXT DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_queue_status ON publication_queue(status);
            CREATE INDEX IF NOT EXISTS idx_queue_scheduled ON publication_queue(scheduled_at);

            CREATE TABLE IF NOT EXISTS my_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER UNIQUE,
                text TEXT NOT NULL,
                date TEXT NOT NULL,
                views INTEGER,
                category TEXT DEFAULT NULL,
                synced_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_my_posts_date ON my_posts(date DESC);
            CREATE INDEX IF NOT EXISTS idx_my_posts_category ON my_posts(category);

            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                variant_a TEXT NOT NULL,
                variant_b TEXT NOT NULL,
                winner TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ab_tests_created ON ab_tests(created_at DESC);

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                totp_secret TEXT,
                totp_verified INTEGER DEFAULT 0,
                anthropic_api_key TEXT NOT NULL DEFAULT '',
                anthropic_model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                target_channel TEXT NOT NULL DEFAULT '',
                channel_description TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_digest_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                type TEXT DEFAULT 'group',
                topic_id INTEGER,
                priority TEXT DEFAULT 'normal',
                UNIQUE(user_id, chat_id, topic_id)
            );

            CREATE TABLE IF NOT EXISTS user_curator_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                UNIQUE(user_id, channel)
            );

            CREATE TABLE IF NOT EXISTS user_digest_schedule (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                daily_enabled INTEGER DEFAULT 1,
                daily_time TEXT DEFAULT '08:00',
                weekly_enabled INTEGER DEFAULT 1,
                weekly_time TEXT DEFAULT '08:00',
                monthly_enabled INTEGER DEFAULT 1,
                monthly_time TEXT DEFAULT '08:00',
                curator_hours TEXT DEFAULT '12,18',
                queue_interval_hours INTEGER DEFAULT 4,
                messages_limit_daily INTEGER DEFAULT 2000,
                messages_limit_weekly INTEGER DEFAULT 5000,
                messages_limit_monthly INTEGER DEFAULT 10000,
                analyzer_count INTEGER DEFAULT 5,
                analyzer_days INTEGER DEFAULT 14,
                digest_posts_per_day INTEGER DEFAULT 2
            );

            CREATE TABLE IF NOT EXISTS digest_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                digest_id TEXT NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
                digest_type TEXT NOT NULL DEFAULT 'daily',
                theme TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT 'report',
                category TEXT NOT NULL DEFAULT 'expert',
                text TEXT NOT NULL,
                user_note TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                user_id INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_digest_posts_digest ON digest_posts(digest_id);
            CREATE INDEX IF NOT EXISTS idx_digest_posts_status ON digest_posts(status);
            CREATE INDEX IF NOT EXISTS idx_digest_posts_user ON digest_posts(user_id);
        """)
    # Миграция: добавить digest_posts_per_day если ещё нет
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(user_digest_schedule)").fetchall()]
        if "digest_posts_per_day" not in cols:
            conn.execute("ALTER TABLE user_digest_schedule ADD COLUMN digest_posts_per_day INTEGER DEFAULT 2")

    # Миграция: добавить media_path если ещё нет (для существующих БД)
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(publication_queue)").fetchall()]
        if "media_path" not in cols:
            conn.execute("ALTER TABLE publication_queue ADD COLUMN media_path TEXT DEFAULT NULL")

    # Миграция: добавить preview_path в digest_posts если ещё нет
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(digest_posts)").fetchall()]
        if "preview_path" not in cols:
            conn.execute("ALTER TABLE digest_posts ADD COLUMN preview_path TEXT DEFAULT NULL")

    # Миграция: добавить поля уведомлений в user_digest_schedule
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(user_digest_schedule)").fetchall()]
        notify_cols = {
            "notify_queue_published": "INTEGER DEFAULT 1",
            "notify_queue_failed": "INTEGER DEFAULT 1",
            "notify_digest_ready": "INTEGER DEFAULT 1",
            "notify_auto_generation": "INTEGER DEFAULT 1",
            "notify_parse_complete": "INTEGER DEFAULT 0",
        }
        for col, typedef in notify_cols.items():
            if col not in cols:
                try:
                    conn.execute(f"ALTER TABLE user_digest_schedule ADD COLUMN {col} {typedef}")
                except Exception:
                    pass

    # Миграция: добавить post_signature в users если ещё нет
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "post_signature" not in cols:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN post_signature TEXT DEFAULT ''")
            except Exception:
                pass

    # Миграция: добавить category в posts если ещё нет
    with get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if "category" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN category TEXT DEFAULT NULL")

    # Миграция: добавить user_id во все старые таблицы (идемпотентно, DEFAULT 1)
    _migrate_add_user_id_columns()


def migrate_from_json(digests_json: str, posts_json: str):
    """Мигрирует данные из JSON файлов в SQLite."""
    init_db()
    migrated_digests = 0
    migrated_posts = 0

    # Дайджесты
    if os.path.exists(digests_json):
        with open(digests_json, encoding="utf-8") as f:
            records = json.load(f)
        with get_conn() as conn:
            for r in records:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO digests (id, type, created_at, days_back, chats_count) VALUES (?,?,?,?,?)",
                        (r["id"], r["type"], r["created_at"], r["days_back"], r["chats_count"])
                    )
                    for s in r.get("summaries", []):
                        conn.execute(
                            "INSERT INTO digest_summaries (digest_id, name, priority, message_count, summary) VALUES (?,?,?,?,?)",
                            (r["id"], s["name"], s["priority"], s["message_count"], s["summary"])
                        )
                    migrated_digests += 1
                except Exception:
                    pass
        print(f"Мигрировано дайджестов: {migrated_digests}")

    # Посты
    if os.path.exists(posts_json):
        with open(posts_json, encoding="utf-8") as f:
            posts = json.load(f)
        with get_conn() as conn:
            for p in posts:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO posts
                           (channel, message_id, text, date, views, has_photo, has_video, url)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (p["channel"], p["message_id"], p["text"], p["date"],
                         p.get("views"), int(p.get("has_photo", False)),
                         int(p.get("has_video", False)), p.get("url"))
                    )
                    migrated_posts += 1
                except Exception:
                    pass
        print(f"Мигрировано постов: {migrated_posts}")


# ─── Дайджесты ───────────────────────────────────────────────────────────────

def save_digest(digest_type: str, summaries: list, days_back: int, user_id: int = 1):
    """Сохраняет дайджест в БД."""
    init_db()
    digest_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + f"_u{user_id}"
    created_at = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO digests (id, type, created_at, days_back, chats_count, user_id) VALUES (?,?,?,?,?,?)",
            (digest_id, digest_type, created_at, days_back, len(summaries), user_id)
        )
        for s in summaries:
            conn.execute(
                "INSERT INTO digest_summaries (digest_id, name, priority, message_count, summary) VALUES (?,?,?,?,?)",
                (digest_id, s["name"], s["priority"], s["message_count"], s["summary"])
            )
    return digest_id


def get_digests(limit: int = 200, user_id: int = 1) -> list:
    """Возвращает список дайджестов без summaries."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM digests WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            summaries = conn.execute(
                "SELECT name, priority, message_count FROM digest_summaries WHERE digest_id=?",
                (d["id"],)
            ).fetchall()
            d["summaries"] = [dict(s) for s in summaries]
            result.append(d)
        return result


def get_digest_by_id(digest_id: str) -> dict | None:
    """Возвращает дайджест с полными summaries."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM digests WHERE id=?", (digest_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        summaries = conn.execute(
            "SELECT name, priority, message_count, summary FROM digest_summaries WHERE digest_id=?",
            (digest_id,)
        ).fetchall()
        d["summaries"] = [dict(s) for s in summaries]
        return d


# ─── Посты ───────────────────────────────────────────────────────────────────

def save_post(post: dict, user_id: int = 1):
    """Сохраняет пост (игнорирует дубликаты)."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO posts
               (channel, message_id, text, date, views, has_photo, has_video, url, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (post["channel"], post["message_id"], post["text"], post["date"],
             post.get("views"), int(post.get("has_photo", False)),
             int(post.get("has_video", False)), post.get("url"), user_id)
        )


def get_posts(limit: int = 2000, user_id: int = 1) -> list:
    """Возвращает посты, отсортированные по дате."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE user_id=? ORDER BY date DESC LIMIT ?", (user_id, limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_posts_by_ids(ids: list) -> list:
    """Возвращает посты по списку id."""
    if not ids:
        return []
    init_db()
    placeholders = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM posts WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [dict(r) for r in rows]


def set_post_category(post_id: int, category: str):
    """Сохраняет категорию поста."""
    init_db()
    with get_conn() as conn:
        conn.execute("UPDATE posts SET category=? WHERE id=?", (category, post_id))


def get_posts_without_category(limit: int = 500, user_id: int = 1) -> list:
    """Возвращает посты без категории."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE category IS NULL AND user_id=? ORDER BY date DESC LIMIT ?",
            (user_id, limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_posts_category_stats(user_id: int = 1) -> dict:
    """Возвращает count по каждой категории и общее количество классифицированных."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM posts WHERE category IS NOT NULL AND user_id=? GROUP BY category",
            (user_id,)
        ).fetchall()
        total_classified = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE category IS NOT NULL AND user_id=?", (user_id,)
        ).fetchone()[0]
        total_all = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=?", (user_id,)).fetchone()[0]
    return {
        "stats": {r["category"]: r["cnt"] for r in rows},
        "classified": total_classified,
        "total": total_all,
    }


# ─── Мои посты (собственный канал) ───────────────────────────────────────────

def save_my_post(message_id: int, text: str, date: str, views: int = None, user_id: int = 1) -> bool:
    """Сохраняет пост из своего канала. Возвращает True если новый."""
    init_db()
    synced_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO my_posts (message_id, text, date, views, synced_at, user_id) VALUES (?,?,?,?,?,?)",
            (message_id, text, date, views, synced_at, user_id)
        )
        return cur.rowcount > 0


def set_my_post_category(post_id: int, category: str):
    """Сохраняет категорию поста."""
    init_db()
    with get_conn() as conn:
        conn.execute("UPDATE my_posts SET category=? WHERE id=?", (category, post_id))


def get_my_posts(limit: int = 200, user_id: int = 1) -> list:
    """Возвращает свои посты, отсортированные по дате."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM my_posts WHERE user_id=? ORDER BY date DESC LIMIT ?", (user_id, limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_posts_without_category(limit: int = 500, user_id: int = 1) -> list:
    """Возвращает свои посты без категории."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM my_posts WHERE category IS NULL AND user_id=? ORDER BY date DESC LIMIT ?",
            (user_id, limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_posts_category_stats(user_id: int = 1) -> dict:
    """Возвращает статистику категорий своих постов."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM my_posts WHERE category IS NOT NULL AND user_id=? GROUP BY category",
            (user_id,)
        ).fetchall()
        total_classified = conn.execute(
            "SELECT COUNT(*) FROM my_posts WHERE category IS NOT NULL AND user_id=?", (user_id,)
        ).fetchone()[0]
        total_all = conn.execute("SELECT COUNT(*) FROM my_posts WHERE user_id=?", (user_id,)).fetchone()[0]
    return {
        "stats": {r["category"]: r["cnt"] for r in rows},
        "classified": total_classified,
        "total": total_all,
    }


def get_posts_since(days: int, limit: int = 500, user_id: int = 1) -> list:
    """Посты за последние N дней, сортировка по views DESC."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE date >= ? AND user_id=? ORDER BY views DESC LIMIT ?",
            (since, user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Voice examples ───────────────────────────────────────────────────────────

def add_voice_example(text: str, label: str = "", user_id: int = 1) -> int:
    """Добавляет пример текста для стиля голоса."""
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO voice_examples (text, label, created_at, user_id) VALUES (?,?,?,?)",
            (text, label, created_at, user_id)
        )
        return cur.lastrowid


def get_voice_examples(user_id: int = 1) -> list:
    """Возвращает примеры стиля голоса."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_examples WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_voice_example(example_id: int, user_id: int = 1) -> bool:
    """Удаляет пример стиля голоса."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM voice_examples WHERE id=? AND user_id=?", (example_id, user_id)
        )
        return cur.rowcount > 0


# ─── Publication queue ────────────────────────────────────────────────────────

def enqueue_post(text: str, scheduled_at: str, source_url: str = "", user_id: int = 1) -> int:
    """Добавляет пост в очередь публикации."""
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO publication_queue (text, source_url, scheduled_at, status, created_at, user_id) VALUES (?,?,?,'pending',?,?)",
            (text, source_url, scheduled_at, created_at, user_id)
        )
        return cur.lastrowid


def enqueue_post_manual(text: str, scheduled_at: str, source_url: str = "",
                         media_path: str = None, user_id: int = 1) -> int:
    """Добавляет пост вручную (из планера), с опциональным фото."""
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO publication_queue (text, source_url, scheduled_at, status, created_at, media_path, user_id) VALUES (?,?,?,'pending',?,?,?)",
            (text, source_url, scheduled_at, created_at, media_path, user_id)
        )
        return cur.lastrowid


def get_queue(status: str = None, user_id: int = 1) -> list:
    """Возвращает очередь публикаций."""
    init_db()
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM publication_queue WHERE status=? AND user_id=? ORDER BY scheduled_at ASC",
                (status, user_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM publication_queue WHERE user_id=? ORDER BY scheduled_at ASC",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_due_queue_items(user_id: int = 1) -> list:
    """Возвращает pending посты с scheduled_at <= now UTC."""
    init_db()
    now_ts = datetime.now(timezone.utc).timestamp()
    with get_conn() as conn:
        # Берём все pending и фильтруем по времени в Python — защита от разных форматов строк
        rows = conn.execute(
            "SELECT * FROM publication_queue WHERE status='pending' AND user_id=? ORDER BY scheduled_at ASC",
            (user_id,)
        ).fetchall()
        result = []
        for row in rows:
            try:
                raw = row["scheduled_at"].replace(" ", "T").replace("Z", "+00:00")
                if "." in raw:
                    # убираем миллисекунды: 2026-04-27T13:51:00.000+00:00 → 2026-04-27T13:51:00+00:00
                    dot_idx = raw.index(".")
                    plus_idx = raw.find("+", dot_idx)
                    raw = raw[:dot_idx] + (raw[plus_idx:] if plus_idx > 0 else "")
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.timestamp() <= now_ts:
                    result.append(dict(row))
            except Exception as e:
                logger.warning(f"get_due_queue_items: не удалось распарсить дату '{row['scheduled_at']}': {e}")
        return result


def update_queue_item(item_id: int, scheduled_at: str = None, text: str = None,
                      media_path: str = None, user_id: int = 1) -> bool:
    """Обновляет поля поста в очереди (scheduled_at, text, media_path)."""
    fields = {}
    if scheduled_at is not None:
        fields["scheduled_at"] = scheduled_at
    if text is not None:
        fields["text"] = text
    if media_path is not None:
        fields["media_path"] = media_path
    if not fields:
        return False
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [item_id, user_id]
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE publication_queue SET {sets} WHERE id=? AND status='pending' AND user_id=?", vals
        )
        return cur.rowcount > 0


def delete_queue_item(item_id: int, user_id: int = 1) -> bool:
    """Удаляет pending пост из очереди."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM publication_queue WHERE id=? AND status='pending' AND user_id=?",
            (item_id, user_id)
        )
        return cur.rowcount > 0


def mark_queue_item_published(item_id: int):
    """Отмечает пост как опубликованный."""
    init_db()
    published_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE publication_queue SET status='published', published_at=? WHERE id=?",
            (published_at, item_id)
        )


def mark_queue_item_failed(item_id: int):
    """Отмечает пост как упавший."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE publication_queue SET status='failed' WHERE id=?",
            (item_id,)
        )


def get_next_scheduled_at(interval_hours: int, user_id: int = 1) -> str:
    """Возвращает следующий свободный слот для публикации."""
    init_db()
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT scheduled_at FROM publication_queue WHERE status='pending' AND user_id=? ORDER BY scheduled_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    if row:
        # Python 3.10 не умеет парсить все варианты ISO: пробел вместо T, суффикс Z, миллисекунды
        raw = row["scheduled_at"].replace(" ", "T").replace("Z", "+00:00")
        # Убираем миллисекунды если есть (.000)
        if "." in raw and ("+" in raw or raw.endswith("00:00")):
            raw = raw.split(".")[0] + raw[raw.index("+"):]
        elif "." in raw:
            raw = raw.split(".")[0]
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        next_slot = last + timedelta(hours=interval_hours)
        # Не раньше чем сейчас + interval
        if next_slot < now + timedelta(hours=interval_hours):
            next_slot = now + timedelta(hours=interval_hours)
    else:
        next_slot = now + timedelta(hours=interval_hours)
    return next_slot.isoformat()


# ─── A/B тесты ───────────────────────────────────────────────────────────────

def save_ab_test(category: str, variant_a: str, variant_b: str, user_id: int = 1) -> int:
    """Сохраняет новый A/B тест, возвращает id."""
    init_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO ab_tests (category, variant_a, variant_b, created_at, user_id) VALUES (?,?,?,?,?)",
            (category, variant_a, variant_b, now, user_id)
        )
        return cur.lastrowid


def set_ab_winner(test_id: int, winner: str):
    """Записывает победителя ('a' или 'b')."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE ab_tests SET winner=? WHERE id=?",
            (winner, test_id)
        )


def get_ab_stats(user_id: int = 1) -> list:
    """Статистика выборов по категориям."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT category,
                   SUM(CASE WHEN winner='a' THEN 1 ELSE 0 END) as a_wins,
                   SUM(CASE WHEN winner='b' THEN 1 ELSE 0 END) as b_wins,
                   COUNT(*) as total
            FROM ab_tests
            WHERE winner IS NOT NULL AND user_id=?
            GROUP BY category
            ORDER BY total DESC
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]


# ─── Миграция: user_id в старые таблицы ──────────────────────────────────────

def _migrate_add_user_id_columns():
    """Добавляет user_id INTEGER DEFAULT 1 в старые таблицы (идемпотентно)."""
    tables = ["posts", "voice_examples", "publication_queue", "my_posts", "digests", "ab_tests"]
    with get_conn() as conn:
        for table in tables:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "user_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")


# ─── Пользователи ────────────────────────────────────────────────────────────

def create_user(username: str, password_hash: str, anthropic_api_key: str = "",
                anthropic_model: str = "claude-sonnet-4-6", target_channel: str = "",
                channel_description: str = "", is_admin: int = 0) -> int:
    """Создаёт нового пользователя, возвращает id."""
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users
               (username, password_hash, anthropic_api_key, anthropic_model,
                target_channel, channel_description, is_admin, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (username, password_hash, anthropic_api_key, anthropic_model,
             target_channel, channel_description, is_admin, created_at)
        )
        user_id = cur.lastrowid
        # Создаём дефолтное расписание
        conn.execute(
            "INSERT OR IGNORE INTO user_digest_schedule (user_id) VALUES (?)",
            (user_id,)
        )
        return user_id


def get_user(user_id: int) -> dict | None:
    """Возвращает пользователя по id."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    """Возвращает пользователя по username."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def get_all_users() -> list:
    """Возвращает всех пользователей."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def get_user_count() -> int:
    """Возвращает количество пользователей."""
    init_db()
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def update_user(user_id: int, **kwargs) -> bool:
    """Обновляет поля пользователя. kwargs: username, password_hash, anthropic_api_key,
    anthropic_model, target_channel, channel_description, totp_secret, totp_verified."""
    allowed = {"username", "password_hash", "anthropic_api_key", "anthropic_model",
               "target_channel", "channel_description", "totp_secret", "totp_verified",
               "post_signature"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user_id]
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
        return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    """Удаляет пользователя и все его данные."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        return cur.rowcount > 0


# ─── Чаты дайджеста (per-user) ────────────────────────────────────────────────

def get_user_digest_chats(user_id: int) -> list:
    """Возвращает чаты дайджеста пользователя."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_digest_chats WHERE user_id=? ORDER BY id ASC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_user_digest_chat(user_id: int, name: str, chat_id: int, chat_type: str = "group",
                          topic_id: int = None, priority: str = "normal") -> int:
    """Добавляет чат дайджеста пользователю."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_digest_chats (user_id, name, chat_id, type, topic_id, priority) VALUES (?,?,?,?,?,?)",
            (user_id, name, chat_id, chat_type, topic_id, priority)
        )
        return cur.lastrowid


def update_user_digest_chat(chat_id_row: int, user_id: int, **kwargs) -> bool:
    """Обновляет чат дайджеста (по row id)."""
    allowed = {"name", "priority", "topic_id"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [chat_id_row, user_id]
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE user_digest_chats SET {sets} WHERE id=? AND user_id=?", vals)
        return cur.rowcount > 0


def delete_user_digest_chat(chat_id_row: int, user_id: int) -> bool:
    """Удаляет чат дайджеста."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM user_digest_chats WHERE id=? AND user_id=?", (chat_id_row, user_id)
        )
        return cur.rowcount > 0


# ─── Источники куратора (per-user) ────────────────────────────────────────────

def get_user_curator_sources(user_id: int) -> list:
    """Возвращает источники куратора пользователя."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_curator_sources WHERE user_id=? ORDER BY id ASC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_user_curator_source(user_id: int, channel: str) -> int:
    """Добавляет источник куратора."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_curator_sources (user_id, channel) VALUES (?,?)",
            (user_id, channel)
        )
        return cur.lastrowid


def delete_user_curator_source(source_id: int, user_id: int) -> bool:
    """Удаляет источник куратора."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM user_curator_sources WHERE id=? AND user_id=?", (source_id, user_id)
        )
        return cur.rowcount > 0


# ─── Расписание пользователя ──────────────────────────────────────────────────

def get_user_schedule(user_id: int) -> dict:
    """Возвращает расписание пользователя (создаёт дефолт если нет)."""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_digest_schedule WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO user_digest_schedule (user_id) VALUES (?)", (user_id,))
            conn.commit()
            row = conn.execute(
                "SELECT * FROM user_digest_schedule WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row)


def update_user_schedule(user_id: int, **kwargs) -> bool:
    """Обновляет расписание пользователя."""
    allowed = {"daily_enabled", "daily_time", "weekly_enabled", "weekly_time",
               "monthly_enabled", "monthly_time", "curator_hours", "queue_interval_hours",
               "messages_limit_daily", "messages_limit_weekly", "messages_limit_monthly",
               "analyzer_count", "analyzer_days", "digest_posts_per_day",
               "notify_queue_published", "notify_queue_failed", "notify_digest_ready",
               "notify_auto_generation", "notify_parse_complete"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    init_db()
    # Гарантируем что запись существует
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_digest_schedule (user_id) VALUES (?)", (user_id,))
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [user_id]
        cur = conn.execute(f"UPDATE user_digest_schedule SET {sets} WHERE user_id=?", vals)
        return cur.rowcount > 0


def get_user_notify_settings(user_id: int) -> dict:
    """Возвращает настройки уведомлений пользователя."""
    sched = get_user_schedule(user_id)
    return {
        "queue_published":  bool(sched.get("notify_queue_published", 1)),
        "queue_failed":     bool(sched.get("notify_queue_failed", 1)),
        "digest_ready":     bool(sched.get("notify_digest_ready", 1)),
        "auto_generation":  bool(sched.get("notify_auto_generation", 1)),
        "parse_complete":   bool(sched.get("notify_parse_complete", 0)),
    }


def should_notify(user_id: int, event: str) -> bool:
    """Проверяет, нужно ли отправлять уведомление о событии.
    event: 'queue_published' | 'queue_failed' | 'digest_ready' | 'auto_generation' | 'parse_complete'
    """
    ns = get_user_notify_settings(user_id)
    return ns.get(event, True)


# ─── Миграция первого пользователя из config.yaml ────────────────────────────

def migrate_first_user_from_config(config: dict) -> int:
    """
    При первом запуске создаёт admin-пользователя из config.yaml.
    Если users не пустая — ничего не делает, возвращает 1.
    """
    if get_user_count() > 0:
        return 1

    import bcrypt as _bcrypt
    password_hash = _bcrypt.hashpw(b"changeme", _bcrypt.gensalt()).decode()

    anthropic_api_key = config.get("anthropic", {}).get("api_key", "")
    anthropic_model = config.get("anthropic", {}).get("model", "claude-sonnet-4-6")
    target_channel = config.get("curator", {}).get("target_channel", "")
    channel_description = config.get("curator", {}).get("channel_description", "")

    user_id = create_user(
        username="admin",
        password_hash=password_hash,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
        target_channel=target_channel,
        channel_description=channel_description,
        is_admin=1,
    )

    # Переносим чаты дайджеста
    for chat in config.get("digest", {}).get("chats", []):
        add_user_digest_chat(
            user_id=user_id,
            name=chat.get("name", ""),
            chat_id=int(chat.get("id", 0) or chat.get("chat_id", 0)),
            chat_type=chat.get("type", "group"),
            topic_id=chat.get("topic_id"),
            priority=chat.get("priority", "normal"),
        )

    # Переносим источники куратора
    for ch in config.get("curator", {}).get("source_channels", []):
        add_user_curator_source(user_id, ch)

    # Переносим расписание
    dcfg = config.get("digest", {}).get("schedule", {})
    curator_hours = config.get("curator", {}).get("schedule", {}).get("hours", [12, 18])
    queue_interval = config.get("curator", {}).get("queue", {}).get("interval_hours", 4)
    lim = config.get("digest", {}).get("messages_limits", {})
    az = config.get("curator", {}).get("analyzer", {})

    update_user_schedule(
        user_id,
        daily_enabled=int(dcfg.get("daily", {}).get("enabled", True)),
        daily_time=dcfg.get("daily", {}).get("time", "08:00"),
        weekly_enabled=int(dcfg.get("weekly", {}).get("enabled", True)),
        weekly_time=dcfg.get("weekly", {}).get("time", "08:00"),
        monthly_enabled=int(dcfg.get("monthly", {}).get("enabled", True)),
        monthly_time=dcfg.get("monthly", {}).get("time", "08:00"),
        curator_hours=",".join(str(h) for h in curator_hours),
        queue_interval_hours=queue_interval,
        messages_limit_daily=lim.get("daily", 2000),
        messages_limit_weekly=lim.get("weekly", 5000),
        messages_limit_monthly=lim.get("monthly", 10000),
        analyzer_count=az.get("count", 5),
        analyzer_days=az.get("days", 14),
    )

    return user_id


# ─── Digest Posts (посты сгенерированные из дайджестов) ──────────────────────

def save_digest_post(digest_id: str, digest_type: str, theme: str, format: str,
                     category: str, text: str, user_id: int = 1) -> int:
    """Сохраняет сгенерированный из дайджеста пост."""
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO digest_posts
               (digest_id, digest_type, theme, format, category, text, status, created_at, user_id)
               VALUES (?,?,?,?,?,?,'draft',?,?)""",
            (digest_id, digest_type, theme, format, category, text, created_at, user_id)
        )
        return cur.lastrowid


def get_digest_posts(digest_id: str = None, user_id: int = 1) -> list:
    """Возвращает посты из дайджестов. Если digest_id — только для конкретного дайджеста."""
    init_db()
    with get_conn() as conn:
        if digest_id:
            rows = conn.execute(
                "SELECT * FROM digest_posts WHERE digest_id=? AND user_id=? ORDER BY id ASC",
                (digest_id, user_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM digest_posts WHERE user_id=? ORDER BY created_at DESC LIMIT 200",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_digest_post_by_id(post_id: int, user_id: int) -> dict | None:
    """Возвращает один пост по id."""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM digest_posts WHERE id=? AND user_id=?", (post_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def update_digest_post(post_id: int, user_id: int, **kwargs) -> bool:
    """Обновляет пост (текст, заметку, статус, категорию, preview_path)."""
    allowed = {"text", "user_note", "status", "category", "format", "preview_path"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [post_id, user_id]
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE digest_posts SET {sets} WHERE id=? AND user_id=?", vals
        )
        return cur.rowcount > 0


def delete_digest_post(post_id: int, user_id: int) -> bool:
    """Удаляет пост из дайджеста."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM digest_posts WHERE id=? AND user_id=?", (post_id, user_id)
        )
        return cur.rowcount > 0


# ─── get_user_config — совместимость со старым форматом ──────────────────────

def get_user_config(user_id: int, system_config: dict) -> dict:
    """
    Собирает config dict совместимый со старым форматом.
    system_config — системный YAML (telegram api_id/hash, bot token, web port).
    Пользовательские данные берутся из БД.
    """
    user = get_user(user_id)
    if not user:
        return system_config

    chats = get_user_digest_chats(user_id)
    sources = get_user_curator_sources(user_id)
    sched = get_user_schedule(user_id)

    cfg = deepcopy(system_config)

    # Anthropic
    if "anthropic" not in cfg:
        cfg["anthropic"] = {}
    cfg["anthropic"]["api_key"] = user["anthropic_api_key"]
    cfg["anthropic"]["model"] = user["anthropic_model"]

    # Curator
    if "curator" not in cfg:
        cfg["curator"] = {}
    cfg["curator"]["target_channel"] = user["target_channel"]
    cfg["curator"]["channel_description"] = user["channel_description"]
    cfg["curator"]["post_signature"] = user.get("post_signature", "")
    cfg["curator"]["source_channels"] = [s["channel"] for s in sources]

    # Расписание куратора
    curator_hours = [int(h.strip()) for h in sched["curator_hours"].split(",") if h.strip()]
    if "schedule" not in cfg["curator"]:
        cfg["curator"]["schedule"] = {}
    cfg["curator"]["schedule"]["hours"] = curator_hours
    if "queue" not in cfg["curator"]:
        cfg["curator"]["queue"] = {}
    cfg["curator"]["queue"]["interval_hours"] = sched["queue_interval_hours"]
    if "analyzer" not in cfg["curator"]:
        cfg["curator"]["analyzer"] = {}
    cfg["curator"]["analyzer"]["count"] = sched["analyzer_count"]
    cfg["curator"]["analyzer"]["days"] = sched["analyzer_days"]
    cfg["curator"]["digest_posts_per_day"] = sched.get("digest_posts_per_day", 2)

    # Digest чаты
    if "digest" not in cfg:
        cfg["digest"] = {}
    cfg["digest"]["chats"] = [
        {
            "name": c["name"],
            "id": c["chat_id"],
            "type": c["type"],
            "priority": c["priority"],
            **({"topic_id": c["topic_id"]} if c.get("topic_id") else {}),
        }
        for c in chats
    ]

    # Расписание дайджеста
    cfg["digest"]["schedule"] = {
        "daily": {"enabled": bool(sched["daily_enabled"]), "time": sched["daily_time"]},
        "weekly": {"enabled": bool(sched["weekly_enabled"]), "time": sched["weekly_time"],
                   "weekday": system_config.get("digest", {}).get("schedule", {}).get("weekly", {}).get("weekday", "friday")},
        "monthly": {"enabled": bool(sched["monthly_enabled"]), "time": sched["monthly_time"],
                    "day": system_config.get("digest", {}).get("schedule", {}).get("monthly", {}).get("day", 1)},
    }

    # Лимиты сообщений
    cfg["digest"]["messages_limits"] = {
        "daily": sched["messages_limit_daily"],
        "weekly": sched["messages_limit_weekly"],
        "monthly": sched["messages_limit_monthly"],
    }

    return cfg
