"""
web/app.py — Flask веб-панель управления TG Hub
"""
import os
import subprocess
import sys
import threading
import yaml
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect

MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

# Статус фонового запуска дайджеста
_digest_status = {"running": False, "last": None, "error": None}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

app = Flask(__name__)

# Flask session
_secret_path = os.path.join(BASE_DIR, "data", ".secret_key")
if os.path.exists(_secret_path):
    with open(_secret_path, "rb") as _f:
        app.secret_key = _f.read()
else:
    app.secret_key = os.urandom(32)
    os.makedirs(os.path.dirname(_secret_path), exist_ok=True)
    with open(_secret_path, "wb") as _f:
        _f.write(app.secret_key)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Импорт auth-хелперов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import (login_required, admin_required, hash_password, check_password,
                  generate_totp_secret, verify_totp, get_totp_uri, generate_qr_base64)


def load_config() -> dict:
    """Загружает системный config.yaml (telegram, bot, web)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_user_cfg() -> dict:
    """Возвращает user-config для текущего залогиненного пользователя."""
    from modules.db import get_user_config
    return get_user_config(session["user_id"], load_config())


def get_posts_history() -> list:
    from modules.db import get_posts
    return get_posts(user_id=session.get("user_id", 1))


def get_digests_history() -> list:
    from modules.db import get_digests
    return get_digests(user_id=session.get("user_id", 1))


# ─── Auth routes ────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    from modules.db import get_user_by_username, migrate_first_user_from_config
    # Автоматически создаём первого пользователя если база пустая
    migrate_first_user_from_config(load_config())

    if request.method == "GET":
        next_url = request.args.get("next", "/")
        error = request.args.get("error", "")
        return render_template("login.html", next=next_url, error=error)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    next_url = request.form.get("next", "/")

    user = get_user_by_username(username)
    if not user or not check_password(password, user["password_hash"]):
        return redirect(f"/login?next={next_url}&error=Неверный логин или пароль")

    # Если TOTP активен — нужно ввести код
    if user["totp_verified"]:
        session["_pending_user_id"] = user["id"]
        session["_pending_next"] = next_url
        return redirect("/login/totp")

    # Нет 2FA — сразу в сессию
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user["is_admin"])
    return redirect(next_url or "/")


@app.route("/login/totp", methods=["GET", "POST"])
def login_totp():
    from modules.db import get_user
    pending_id = session.get("_pending_user_id")
    if not pending_id:
        return redirect("/login")

    if request.method == "GET":
        error = request.args.get("error", "")
        return render_template("login_totp.html", error=error)

    code = request.form.get("code", "").strip()
    user = get_user(pending_id)
    if not user or not verify_totp(user["totp_secret"], code):
        return redirect("/login/totp?error=Неверный код")

    next_url = session.pop("_pending_next", "/")
    session.pop("_pending_user_id", None)
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user["is_admin"])
    return redirect(next_url or "/")


@app.route("/register", methods=["GET", "POST"])
def register():
    from modules.db import get_user_by_username, create_user
    if request.method == "GET":
        error = request.args.get("error", "")
        return render_template("register.html", error=error)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    password2 = request.form.get("password2", "").strip()
    api_key = request.form.get("anthropic_api_key", "").strip()
    target_channel = request.form.get("target_channel", "").strip()

    if not username or len(username) < 3:
        return redirect("/register?error=Имя пользователя минимум 3 символа")
    if not password or len(password) < 8:
        return redirect("/register?error=Пароль минимум 8 символов")
    if password != password2:
        return redirect("/register?error=Пароли не совпадают")
    if get_user_by_username(username):
        return redirect("/register?error=Имя пользователя уже занято")

    phash = hash_password(password)
    user_id = create_user(
        username=username,
        password_hash=phash,
        anthropic_api_key=api_key,
        target_channel=target_channel,
    )
    # После регистрации — сразу логиним и отправляем на setup-totp
    session.permanent = True
    session["user_id"] = user_id
    session["username"] = username
    session["is_admin"] = False
    return redirect("/setup-totp")


@app.route("/setup-totp", methods=["GET", "POST"])
@login_required
def setup_totp():
    from modules.db import get_user, update_user
    user = get_user(session["user_id"])

    if request.method == "GET":
        # Генерируем secret если ещё нет
        secret = user.get("totp_secret") or generate_totp_secret()
        if not user.get("totp_secret"):
            update_user(session["user_id"], totp_secret=secret)
        uri = get_totp_uri(secret, user["username"])
        qr_b64 = generate_qr_base64(uri)
        return render_template("setup_totp.html", secret=secret, qr_b64=qr_b64, error="")

    code = request.form.get("code", "").strip()
    user = get_user(session["user_id"])  # reload
    if not user.get("totp_secret") or not verify_totp(user["totp_secret"], code):
        secret = user.get("totp_secret", "")
        uri = get_totp_uri(secret, user["username"]) if secret else ""
        qr_b64 = generate_qr_base64(uri) if uri else ""
        return render_template("setup_totp.html", secret=secret, qr_b64=qr_b64,
                               error="Неверный код, попробуйте ещё раз")
    update_user(session["user_id"], totp_verified=1)
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ─── Страницы ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    config = get_user_cfg()
    posts_count = len(get_posts_history())
    chats_count = len(config["digest"]["chats"])
    sources_count = len(config["curator"].get("source_channels", []))
    return render_template("index.html",
        chats_count=chats_count,
        sources_count=sources_count,
        posts_count=posts_count,
        config=config,
    )


@app.route("/digest")
@login_required
def digest_page():
    config = get_user_cfg()
    return render_template("digest.html", config=config, chats=config["digest"]["chats"])


@app.route("/curator")
@login_required
def curator_page():
    config = get_user_cfg()
    posts = get_posts_history()
    return render_template("curator.html", config=config, posts_count=len(posts))


@app.route("/settings")
@login_required
def settings_page():
    from modules.db import get_user_notify_settings
    config = get_user_cfg()
    notifications = get_user_notify_settings(session["user_id"])
    return render_template("settings.html", config=config, notifications=notifications)


# ─── API: Digest чаты ───────────────────────────────────────────────────────

@app.route("/api/digest/chats", methods=["GET"])
@login_required
def api_get_chats():
    from modules.db import get_user_digest_chats
    chats = get_user_digest_chats(session["user_id"])
    # Совместимость с фронтом: id поле = chat_id
    result = [{"id": c["chat_id"], "name": c["name"], "type": c["type"],
               "priority": c["priority"], "topic_id": c.get("topic_id"), "_row_id": c["id"]}
              for c in chats]
    return jsonify(result)


@app.route("/api/digest/chats", methods=["POST"])
@login_required
def api_add_chat():
    from modules.db import add_user_digest_chat
    data = request.json
    name = data.get("name", "").strip()
    chat_id = int(data.get("id", 0) or data.get("chat_id", 0))
    if not name or not chat_id:
        return jsonify({"ok": False, "error": "Укажи name и id"}), 400
    chat_type = data.get("type", "group")
    priority = data.get("priority", "normal")
    topic_id = int(data["topic_id"]) if data.get("topic_id") else None
    row_id = add_user_digest_chat(session["user_id"], name, chat_id, chat_type, topic_id, priority)
    chat = {"id": chat_id, "name": name, "type": chat_type, "priority": priority,
            "topic_id": topic_id, "_row_id": row_id}
    return jsonify({"ok": True, "chat": chat})


@app.route("/api/digest/chats/<int:idx>", methods=["DELETE"])
@login_required
def api_delete_chat(idx: int):
    from modules.db import get_user_digest_chats, delete_user_digest_chat
    chats = get_user_digest_chats(session["user_id"])
    if idx < 0 or idx >= len(chats):
        return jsonify({"ok": False, "error": "Индекс не найден"}), 404
    row_id = chats[idx]["id"]
    delete_user_digest_chat(row_id, session["user_id"])
    return jsonify({"ok": True, "removed": chats[idx]})


@app.route("/api/digest/chats/<int:idx>", methods=["PUT"])
@login_required
def api_update_chat(idx: int):
    from modules.db import get_user_digest_chats, update_user_digest_chat
    chats = get_user_digest_chats(session["user_id"])
    if idx < 0 or idx >= len(chats):
        return jsonify({"ok": False, "error": "Индекс не найден"}), 404
    data = request.json
    row_id = chats[idx]["id"]
    kwargs = {}
    if "name" in data:
        kwargs["name"] = data["name"]
    if "priority" in data:
        kwargs["priority"] = data["priority"]
    if "topic_id" in data:
        kwargs["topic_id"] = int(data["topic_id"]) if data["topic_id"] else None
    update_user_digest_chat(row_id, session["user_id"], **kwargs)
    updated = {**chats[idx], **kwargs}
    return jsonify({"ok": True, "chat": updated})


# ─── API: Curator источники ─────────────────────────────────────────────────

@app.route("/api/curator/sources", methods=["GET"])
@login_required
def api_get_sources():
    from modules.db import get_user_curator_sources
    sources = get_user_curator_sources(session["user_id"])
    return jsonify([s["channel"] for s in sources])


@app.route("/api/curator/sources", methods=["POST"])
@login_required
def api_add_source():
    from modules.db import get_user_curator_sources, add_user_curator_source
    channel = (request.json or {}).get("channel", "").strip()
    if not channel:
        return jsonify({"ok": False, "error": "Пустой канал"}), 400
    if not channel.startswith("@"):
        channel = "@" + channel
    existing = [s["channel"] for s in get_user_curator_sources(session["user_id"])]
    if channel in existing:
        return jsonify({"ok": False, "error": "Канал уже добавлен"}), 400
    add_user_curator_source(session["user_id"], channel)
    return jsonify({"ok": True, "channel": channel})


@app.route("/api/curator/sources/<int:idx>", methods=["DELETE"])
@login_required
def api_delete_source(idx: int):
    from modules.db import get_user_curator_sources, delete_user_curator_source
    sources = get_user_curator_sources(session["user_id"])
    if idx < 0 or idx >= len(sources):
        return jsonify({"ok": False, "error": "Индекс не найден"}), 404
    delete_user_curator_source(sources[idx]["id"], session["user_id"])
    return jsonify({"ok": True, "removed": sources[idx]["channel"]})


# ─── API: Настройки ─────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    from modules.db import update_user_schedule, update_user
    data = request.json
    user_id = session["user_id"]
    sched_kwargs = {}

    if "digest_schedule" in data:
        s = data["digest_schedule"]
        sched_kwargs.update({
            "daily_time": s.get("daily_time", "08:00"),
            "daily_enabled": int(s.get("daily_enabled", True)),
            "weekly_time": s.get("weekly_time", "08:00"),
            "weekly_enabled": int(s.get("weekly_enabled", True)),
            "monthly_time": s.get("monthly_time", "08:00"),
            "monthly_enabled": int(s.get("monthly_enabled", True)),
        })

    if "curator_schedule" in data:
        hours = data["curator_schedule"].get("hours", [12])
        sched_kwargs["curator_hours"] = ",".join(str(h) for h in hours)

    if "anthropic_model" in data:
        update_user(user_id, anthropic_model=data["anthropic_model"])

    if "queue_interval_hours" in data:
        sched_kwargs["queue_interval_hours"] = int(data["queue_interval_hours"])

    if "digest_posts_per_day" in data:
        sched_kwargs["digest_posts_per_day"] = max(1, min(10, int(data["digest_posts_per_day"])))

    if "messages_limits" in data:
        lim = data["messages_limits"]
        sched_kwargs.update({
            "messages_limit_daily": int(lim.get("daily", 2000)),
            "messages_limit_weekly": int(lim.get("weekly", 5000)),
            "messages_limit_monthly": int(lim.get("monthly", 10000)),
        })

    if "analyzer" in data:
        az = data["analyzer"]
        sched_kwargs.update({
            "analyzer_count": int(az.get("count", 5)),
            "analyzer_days": int(az.get("days", 14)),
        })

    if "notifications" in data:
        ntf = data["notifications"]
        sched_kwargs.update({
            "notify_queue_published": int(bool(ntf.get("queue_published", True))),
            "notify_queue_failed":    int(bool(ntf.get("queue_failed", True))),
            "notify_digest_ready":    int(bool(ntf.get("digest_ready", True))),
            "notify_auto_generation": int(bool(ntf.get("auto_generation", True))),
            "notify_parse_complete":  int(bool(ntf.get("parse_complete", False))),
        })

    if sched_kwargs:
        update_user_schedule(user_id, **sched_kwargs)

    return jsonify({"ok": True})


# ─── Посты ───────────────────────────────────────────────────────────────────

@app.route("/posts")
@login_required
def posts_page():
    return render_template("posts.html")


# ─── Дайджесты ───────────────────────────────────────────────────────────────

@app.route("/digests")
@login_required
def digests_page():
    return render_template("digests.html")


@app.route("/api/digests")
@login_required
def api_digests():
    records = get_digests_history()
    return jsonify({"digests": records, "total": len(records)})


@app.route("/api/digests/<digest_id>")
@login_required
def api_digest_detail(digest_id: str):
    from modules.db import get_digest_by_id
    d = get_digest_by_id(digest_id)
    if not d:
        return jsonify({"error": "не найден"}), 404
    return jsonify(d)


@app.route("/api/digest/run", methods=["POST"])
@login_required
def api_run_digest():
    digest_type = request.json.get("type", "daily")
    if digest_type not in ("daily", "weekly", "monthly"):
        return jsonify({"ok": False, "error": "Неверный тип"}), 400
    if _digest_status["running"]:
        return jsonify({"ok": False, "error": "Дайджест уже запущен"}), 409

    def run():
        _digest_status["running"] = True
        _digest_status["error"] = None
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(BASE_DIR, "run.py"), f"digest-{digest_type}"],
                capture_output=True, text=True, cwd=BASE_DIR, timeout=600
            )
            if result.returncode != 0:
                _digest_status["error"] = result.stderr[-500:] if result.stderr else "Неизвестная ошибка"
        except Exception as e:
            _digest_status["error"] = str(e)
        finally:
            _digest_status["running"] = False
            _digest_status["last"] = datetime.now().strftime("%d.%m %H:%M")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"{digest_type} дайджест запущен"})


@app.route("/api/digest/status")
@login_required
def api_digest_run_status():
    return jsonify(_digest_status)


@app.route("/api/posts")
@login_required
def api_posts():
    from modules.db import get_posts
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    user_id = session["user_id"]
    all_posts = get_posts(user_id=user_id)
    total = len(all_posts)
    page = all_posts[offset:offset + limit]
    return jsonify({"posts": page, "total": total, "offset": offset, "limit": limit})


@app.route("/api/posts/stats")
@login_required
def api_posts_stats():
    from modules.db import get_posts_category_stats
    return jsonify(get_posts_category_stats(user_id=session["user_id"]))


_classify_status = {"running": False}


@app.route("/api/posts/classify", methods=["POST"])
@login_required
def api_classify_posts():
    if _classify_status["running"]:
        return jsonify({"ok": False, "error": "Классификация уже запущена"}), 409

    from modules.db import get_posts_without_category, set_post_category
    from modules.curator import generator

    config = get_user_cfg()
    posts = get_posts_without_category(limit=500, user_id=session["user_id"])
    if not posts:
        return jsonify({"ok": True, "classified": 0, "message": "Все посты уже классифицированы"})

    try:
        _classify_status["running"] = True
        results = generator.classify_posts(posts, config)
        for item in results:
            set_post_category(item["id"], item["category"])
        return jsonify({"ok": True, "classified": len(results), "total": len(posts)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _classify_status["running"] = False


# ─── API: Voice examples ─────────────────────────────────────────────────────

@app.route("/api/curator/voice-examples", methods=["GET"])
@login_required
def api_get_voice_examples():
    from modules.db import get_voice_examples
    return jsonify(get_voice_examples(user_id=session["user_id"]))


@app.route("/api/curator/voice-examples", methods=["POST"])
@login_required
def api_add_voice_example():
    from modules.db import add_voice_example
    data = request.json
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Пустой текст"}), 400
    label = (data.get("label") or "").strip()
    eid = add_voice_example(text, label, user_id=session["user_id"])
    return jsonify({"ok": True, "id": eid})


@app.route("/api/curator/voice-examples/<int:eid>", methods=["DELETE"])
@login_required
def api_delete_voice_example(eid: int):
    from modules.db import delete_voice_example
    ok = delete_voice_example(eid, user_id=session["user_id"])
    if not ok:
        return jsonify({"ok": False, "error": "Не найден"}), 404
    return jsonify({"ok": True})


@app.route("/api/curator/voice-examples/clear", methods=["DELETE"])
@login_required
def api_clear_voice_examples():
    from modules.db import get_conn, init_db
    user_id = session["user_id"]
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM voice_examples WHERE user_id=?", (user_id,))
    return jsonify({"ok": True})


# ─── API: Publication queue ───────────────────────────────────────────────────

@app.route("/api/curator/queue")
@login_required
def api_get_queue():
    from modules.db import get_queue
    status = request.args.get("status")
    return jsonify(get_queue(status, user_id=session["user_id"]))


@app.route("/api/curator/queue", methods=["POST"])
@login_required
def api_add_to_queue():
    from modules.db import enqueue_post_manual
    data = request.json or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Пустой текст"}), 400
    scheduled_at = (data.get("scheduled_at") or "").strip()
    if not scheduled_at:
        scheduled_at = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    item_id = enqueue_post_manual(text, scheduled_at, user_id=session["user_id"])
    return jsonify({"ok": True, "id": item_id, "scheduled_at": scheduled_at})


@app.route("/api/curator/queue/<int:item_id>", methods=["DELETE"])
@login_required
def api_delete_queue_item(item_id: int):
    from modules.db import delete_queue_item
    ok = delete_queue_item(item_id, user_id=session["user_id"])
    if not ok:
        return jsonify({"ok": False, "error": "Не найден или уже опубликован"}), 404
    return jsonify({"ok": True})


@app.route("/api/curator/queue/<int:item_id>", methods=["PUT"])
@login_required
def api_update_queue_item(item_id: int):
    from modules.db import update_queue_item
    data = request.json or {}
    scheduled_at = data.get("scheduled_at", "").strip() or None
    text = data.get("text", "").strip() or None
    media_path = data.get("media_path", None)
    if not scheduled_at and not text and media_path is None:
        return jsonify({"ok": False, "error": "Нет данных для обновления"}), 400
    ok = update_queue_item(item_id, scheduled_at=scheduled_at, text=text,
                           media_path=media_path, user_id=session["user_id"])
    if not ok:
        return jsonify({"ok": False, "error": "Не найден или уже опубликован"}), 404
    return jsonify({"ok": True})


# ─── API: Curator парсинг ────────────────────────────────────────────────────

_parse_status = {"running": False, "last": None, "error": None}


@app.route("/api/curator/parse", methods=["POST"])
@login_required
def api_run_parse():
    if _parse_status["running"]:
        return jsonify({"ok": False, "error": "Парсинг уже запущен"}), 409

    user_cfg = get_user_cfg()

    def run(cfg):
        _parse_status["running"] = True
        _parse_status["error"] = None
        try:
            import asyncio
            from modules.curator.parser import fetch_all_posts
            asyncio.run(fetch_all_posts(cfg))
        except Exception as e:
            _parse_status["error"] = str(e)
        finally:
            _parse_status["running"] = False
            _parse_status["last"] = datetime.now().strftime("%d.%m %H:%M")

    threading.Thread(target=run, args=(user_cfg,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/curator/parse/status")
@login_required
def api_parse_status():
    return jsonify(_parse_status)


# ─── API: Статус ─────────────────────────────────────────────────────────────

@app.route("/api/status")
@login_required
def api_status():
    config = get_user_cfg()
    posts = get_posts_history()
    return jsonify({
        "digest_chats": len(config["digest"]["chats"]),
        "curator_sources": len(config["curator"].get("source_channels", [])),
        "posts_in_db": len(posts),
        "digest_enabled": config["digest"].get("enabled", True),
        "curator_enabled": config["curator"].get("enabled", True),
        "model": config["anthropic"].get("model", ""),
        "target_channel": config["curator"].get("target_channel", ""),
        "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
    })


# ─── API: Генерация из выбранных постов ──────────────────────────────────────

_generate_status = {"running": False}


@app.route("/api/curator/generate-from-posts", methods=["POST"])
@login_required
def api_generate_from_posts():
    if _generate_status["running"]:
        return jsonify({"ok": False, "error": "Генерация уже запущена"}), 409
    data = request.json
    post_ids = data.get("post_ids", [])
    if not post_ids or len(post_ids) > 5:
        return jsonify({"ok": False, "error": "Укажи от 1 до 5 постов"}), 400

    from modules.db import get_posts_by_ids
    from modules.curator import generator
    config = get_user_cfg()

    posts = get_posts_by_ids([int(i) for i in post_ids])
    if not posts:
        return jsonify({"ok": False, "error": "Посты не найдены"}), 404

    try:
        _generate_status["running"] = True
        text = generator.generate_post(posts, config)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _generate_status["running"] = False


# ─── Планер ──────────────────────────────────────────────────────────────────

@app.route("/planner")
@login_required
def planner_page():
    return render_template("planner.html")


@app.route("/api/planner/posts")
@login_required
def api_planner_posts():
    from modules.db import get_queue
    month = request.args.get("month", "")  # формат: 2026-04
    items = get_queue(user_id=session["user_id"])
    if month:
        # Нормализуем scheduled_at к дате — убираем зависимость от формата строки
        def item_month(item):
            raw = item["scheduled_at"].replace(" ", "T").replace("Z", "+00:00")
            if "." in raw:
                raw = raw.split(".")[0] + ("+00:00" if raw.endswith("+00:00") else "")
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(raw)
                # Конвертируем в МСК (+3) для отображения
                from datetime import timedelta
                dt_msk = dt.astimezone(timezone(timedelta(hours=3)))
                return dt_msk.strftime("%Y-%m")
            except Exception:
                return raw[:7]
        items = [i for i in items if item_month(i) == month]
    return jsonify(items)


@app.route("/api/planner/posts", methods=["POST"])
@login_required
def api_planner_add_post():
    from modules.db import enqueue_post_manual
    import uuid

    text = request.form.get("text", "").strip()
    scheduled_at = request.form.get("scheduled_at", "").strip()
    if not text or not scheduled_at:
        return jsonify({"ok": False, "error": "Укажи текст и время"}), 400

    media_path = None
    file = request.files.get("media")
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return jsonify({"ok": False, "error": "Только изображения (jpg, png, gif, webp)"}), 400
        filename = f"{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(MEDIA_DIR, filename))
        media_path = filename

    item_id = enqueue_post_manual(text, scheduled_at, media_path=media_path, user_id=session["user_id"])
    return jsonify({"ok": True, "id": item_id})


@app.route("/api/planner/upload-media", methods=["POST"])
@login_required
def api_planner_upload_media():
    """Загружает медиа-файл и возвращает путь (для прикрепления к уже существующему посту)."""
    import uuid
    file = request.files.get("media")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Файл не передан"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return jsonify({"ok": False, "error": "Только изображения (jpg, png, gif, webp)"}), 400
    filename = f"{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(MEDIA_DIR, filename))
    return jsonify({"ok": True, "file_path": filename, "url": f"/media/{filename}"})


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(MEDIA_DIR, filename)


# ─── API: Мои посты (собственный канал) ──────────────────────────────────────

TARGETS = {"expert": 40, "personal": 25, "entertaining": 15, "motivational": 10, "promotional": 7, "engaging": 3}
CATEGORY_LABELS = {
    "expert": "🎓 Экспертный", "personal": "🎭 Личный",
    "entertaining": "😄 Развлекательный", "motivational": "💡 Мотивационный",
    "promotional": "📢 Продающий", "engaging": "🔥 Вовлекающий",
}


def _compute_recommendation(stats: dict, total: int) -> dict:
    if not total:
        return {"category": "expert", "label": "🎓 Экспертный", "deficit_pct": 40}
    real = {k: round(stats.get(k, 0) / total * 100, 1) for k in TARGETS}
    deficit = {k: TARGETS[k] - real[k] for k in TARGETS}
    cat = max(deficit, key=deficit.get)
    return {"category": cat, "label": CATEGORY_LABELS[cat], "deficit_pct": round(deficit[cat], 1)}


@app.route("/api/my-posts/stats")
@login_required
def api_my_posts_stats():
    from modules.db import get_my_posts_category_stats
    data = get_my_posts_category_stats(user_id=session["user_id"])
    rec = _compute_recommendation(data["stats"], data["classified"])
    data["recommendation"] = rec
    return jsonify(data)


@app.route("/api/my-posts/import-json", methods=["POST"])
@login_required
def api_my_posts_import_json():
    from modules.db import save_my_post
    import json as _json

    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "Файл не передан"}), 400

    try:
        data = _json.loads(file.read().decode("utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "Невалидный JSON"}), 400

    messages = []
    if "messages" in data:
        messages = data["messages"]
    elif "chats" in data:
        for chat in data["chats"].get("list", []):
            messages.extend(chat.get("messages", []))

    def extract_text(raw):
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            return "".join(p["text"] if isinstance(p, dict) else str(p) for p in raw).strip()
        return ""

    imported = 0
    for msg in messages:
        if msg.get("type") != "message":
            continue
        if msg.get("forwarded_from"):
            continue
        text = extract_text(msg.get("text", ""))
        if len(text) < 20:
            continue
        save_my_post(
            message_id=msg.get("id", 0),
            text=text[:3000],
            date=msg.get("date", ""),
            views=msg.get("views", 0),
            user_id=session["user_id"],
        )
        imported += 1

    return jsonify({"ok": True, "imported": imported, "total": len(messages)})


_my_sync_status = {"running": False}


@app.route("/api/my-posts/sync", methods=["POST"])
@login_required
def api_my_posts_sync():
    if _my_sync_status["running"]:
        return jsonify({"ok": False, "error": "Синк уже запущен"}), 409

    import asyncio
    from modules.curator.parser import sync_my_channel
    config = get_user_cfg()

    try:
        _my_sync_status["running"] = True
        result = asyncio.run(sync_my_channel(config))
        if "error" in result:
            return jsonify({"ok": False, "error": result["error"]}), 500
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _my_sync_status["running"] = False


_my_classify_status = {"running": False}


@app.route("/api/my-posts/classify", methods=["POST"])
@login_required
def api_my_posts_classify():
    if _my_classify_status["running"]:
        return jsonify({"ok": False, "error": "Классификация уже запущена"}), 409

    from modules.db import get_my_posts_without_category, set_my_post_category
    from modules.curator import generator
    config = get_user_cfg()
    posts = get_my_posts_without_category(limit=500, user_id=session["user_id"])
    if not posts:
        return jsonify({"ok": True, "classified": 0, "message": "Все посты уже классифицированы"})

    try:
        _my_classify_status["running"] = True
        results = generator.classify_posts(posts, config)
        for item in results:
            set_my_post_category(item["id"], item["category"])
        return jsonify({"ok": True, "classified": len(results), "total": len(posts)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _my_classify_status["running"] = False


@app.route("/api/my-posts/generate-by-category", methods=["POST"])
@login_required
def api_generate_by_category():
    category = (request.json or {}).get("category", "expert")
    config = get_user_cfg()
    from modules.curator import generator
    try:
        text = generator.generate_post_by_category(category, config)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── API: Импорт стиля голоса из Telegram JSON экспорта ──────────────────────

@app.route("/api/curator/voice-examples/import-json", methods=["POST"])
@login_required
def api_import_voice_json():
    from modules.db import add_voice_example
    import json as _json

    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "Файл не передан"}), 400

    min_len = int(request.form.get("min_len", 50))
    max_posts = int(request.form.get("max_posts", 200))

    try:
        data = _json.loads(file.read().decode("utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "Невалидный JSON"}), 400

    # Поддерживаем два формата: прямой экспорт канала и вложенный chats.list
    messages = []
    if "messages" in data:
        messages = data["messages"]
    elif "chats" in data:
        for chat in data["chats"].get("list", []):
            messages.extend(chat.get("messages", []))

    def extract_text(raw):
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            return "".join(
                p["text"] if isinstance(p, dict) else str(p)
                for p in raw
            ).strip()
        return ""

    imported = 0
    for msg in messages:
        if msg.get("type") != "message":
            continue
        if msg.get("forwarded_from"):
            continue
        text = extract_text(msg.get("text", ""))
        if len(text) < min_len:
            continue
        add_voice_example(text, label="импорт TG", user_id=session["user_id"])
        imported += 1
        if imported >= max_posts:
            break

    return jsonify({"ok": True, "imported": imported, "total": len(messages)})


# ─── API: Анализ постов ───────────────────────────────────────────────────────

_analyze_status = {"running": False}


# ─── API: A/B тест ────────────────────────────────────────────────────────────

@app.route("/api/curator/ab-generate", methods=["POST"])
@login_required
def api_ab_generate():
    data = request.json or {}
    category = data.get("category", "").strip() or None
    config = get_user_cfg()
    from modules.curator.generator import generate_ab_variants
    from modules.db import save_ab_test
    try:
        variant_a, variant_b = generate_ab_variants(config, category)
        test_id = save_ab_test(category or "general", variant_a, variant_b, user_id=session["user_id"])
        return jsonify({"ok": True, "test_id": test_id, "category": category or "general",
                        "variant_a": variant_a, "variant_b": variant_b})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/curator/ab-choose", methods=["POST"])
@login_required
def api_ab_choose():
    from modules.db import set_ab_winner, enqueue_post_manual
    data = request.json or {}
    test_id = data.get("test_id")
    winner = data.get("winner", "").strip()
    text = data.get("text", "").strip()
    scheduled_at = data.get("scheduled_at", "").strip()
    if not test_id or winner not in ("a", "b") or not text:
        return jsonify({"ok": False, "error": "Неверные параметры"}), 400
    if not scheduled_at:
        scheduled_at = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    set_ab_winner(test_id, winner)
    item_id = enqueue_post_manual(text, scheduled_at, user_id=session["user_id"])
    return jsonify({"ok": True, "id": item_id, "scheduled_at": scheduled_at})


@app.route("/api/curator/ab-stats")
@login_required
def api_ab_stats():
    from modules.db import get_ab_stats
    return jsonify(get_ab_stats(user_id=session["user_id"]))


@app.route("/api/curator/analyze-posts", methods=["POST"])
@login_required
def api_analyze_posts():
    if _analyze_status["running"]:
        return jsonify({"ok": False, "error": "Анализ уже запущен"}), 409
    data = request.json or {}
    config = get_user_cfg()

    analyzer_cfg = config.get("curator", {}).get("analyzer", {})
    days = int(data.get("days", analyzer_cfg.get("days", 14)))
    count = int(data.get("count", analyzer_cfg.get("count", 5)))
    days = max(1, min(days, 90))
    count = max(1, min(count, 20))

    from modules.db import get_posts_since
    from modules.curator import generator

    posts = get_posts_since(days=days, limit=500, user_id=session["user_id"])
    if not posts:
        return jsonify({"ok": True, "results": [], "message": "Нет постов за указанный период"})

    try:
        _analyze_status["running"] = True
        results = generator.analyze_posts(posts, config, top_n=count)
        return jsonify({"ok": True, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _analyze_status["running"] = False


# ─── Digest → Posts pipeline ─────────────────────────────────────────────────

_digest_extract_status = {"running": False}
_digest_gen_status = {"running": False}


@app.route("/api/digests/<digest_id>/extract-themes", methods=["POST"])
@login_required
def api_extract_digest_themes(digest_id: str):
    """Анализирует дайджест и возвращает все горячие темы."""
    if _digest_extract_status["running"]:
        return jsonify({"ok": False, "error": "Анализ уже запущен"}), 409
    from modules.db import get_digest_by_id
    from modules.curator import generator

    d = get_digest_by_id(digest_id)
    if not d:
        return jsonify({"ok": False, "error": "Дайджест не найден"}), 404

    config = get_user_cfg()
    try:
        _digest_extract_status["running"] = True
        themes = generator.extract_digest_themes(d["summaries"], config)
        # Сохраняем темы в БД чтобы пережили обновление страницы
        from modules.db import save_digest_themes
        save_digest_themes(digest_id, themes, user_id=session["user_id"])
        return jsonify({"ok": True, "themes": themes, "digest_type": d["type"]})
    except Exception as e:
        logger.error(f"extract_digest_themes: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _digest_extract_status["running"] = False


@app.route("/api/digests/<digest_id>/themes", methods=["GET"])
@login_required
def api_get_digest_themes(digest_id: str):
    """Возвращает сохранённые горячие темы для дайджеста."""
    from modules.db import get_digest_themes
    themes = get_digest_themes(digest_id, user_id=session["user_id"])
    return jsonify({"ok": True, "themes": themes})


@app.route("/api/digests/<digest_id>/generate-post", methods=["POST"])
@login_required
def api_generate_digest_post(digest_id: str):
    """Генерирует один пост из темы дайджеста и сохраняет в digest_posts."""
    from modules.db import get_digest_by_id, save_digest_post
    from modules.curator import generator

    data = request.json or {}
    theme = (data.get("theme") or "").strip()
    description = (data.get("description") or "").strip()
    fmt = data.get("format", "report")
    category = data.get("category", "expert")
    user_note = (data.get("user_note") or "").strip()

    if not theme:
        return jsonify({"ok": False, "error": "Нет темы"}), 400

    d = get_digest_by_id(digest_id)
    if not d:
        return jsonify({"ok": False, "error": "Дайджест не найден"}), 404

    config = get_user_cfg()
    valid_formats = {"report", "opinion", "minto", "story", "trend"}
    valid_cats = {"expert", "personal", "entertaining", "motivational", "promotional", "engaging"}
    if fmt not in valid_formats:
        fmt = "report"
    if category not in valid_cats:
        category = "expert"

    try:
        text = generator.generate_post_from_digest(
            theme=theme,
            description=description,
            summaries=d["summaries"],
            format=fmt,
            category=category,
            config=config,
            user_note=user_note,
        )
        post_id = save_digest_post(
            digest_id=digest_id,
            digest_type=d["type"],
            theme=theme,
            format=fmt,
            category=category,
            text=text,
            user_id=session["user_id"],
        )
        return jsonify({"ok": True, "id": post_id, "text": text})
    except Exception as e:
        logger.error(f"generate_digest_post: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/digest-posts/<int:post_id>", methods=["PUT"])
@login_required
def api_update_digest_post(post_id: int):
    """Обновляет текст/заметку/статус/категорию поста из дайджеста."""
    from modules.db import update_digest_post
    data = request.json or {}
    allowed = {"text", "user_note", "status", "category", "format"}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    ok = update_digest_post(post_id, session["user_id"], **kwargs)
    return jsonify({"ok": ok})


@app.route("/api/digest-posts/<int:post_id>", methods=["DELETE"])
@login_required
def api_delete_digest_post(post_id: int):
    """Удаляет пост из дайджеста."""
    from modules.db import delete_digest_post
    ok = delete_digest_post(post_id, session["user_id"])
    return jsonify({"ok": ok})


@app.route("/api/digest-posts/<int:post_id>/enqueue", methods=["POST"])
@login_required
def api_enqueue_digest_post(post_id: int):
    """Добавляет пост из дайджеста в очередь публикации."""
    from modules.db import get_digest_posts, update_digest_post, enqueue_post, get_next_scheduled_at, get_user_schedule
    data = request.json or {}
    text = (data.get("text") or "").strip()
    scheduled_at = (data.get("scheduled_at") or "").strip()

    # Берём текст из поста если не передан явно
    if not text:
        posts = get_digest_posts(user_id=session["user_id"])
        post = next((p for p in posts if p["id"] == post_id), None)
        if not post:
            return jsonify({"ok": False, "error": "Пост не найден"}), 404
        text = post["text"]

    if not scheduled_at:
        sched = get_user_schedule(session["user_id"])
        interval = sched.get("queue_interval_hours", 4)
        scheduled_at = get_next_scheduled_at(interval, user_id=session["user_id"])

    queue_id = enqueue_post(text, scheduled_at, source_url="digest", user_id=session["user_id"])
    update_digest_post(post_id, session["user_id"], status="queued")
    return jsonify({"ok": True, "queue_id": queue_id, "scheduled_at": scheduled_at})


@app.route("/api/digest-posts", methods=["GET"])
@login_required
def api_get_all_digest_posts():
    """Возвращает все сохранённые посты из всех дайджестов."""
    from modules.db import get_digest_posts
    posts = get_digest_posts(user_id=session["user_id"])
    return jsonify({"ok": True, "posts": posts})


@app.route("/api/digests/<digest_id>/posts", methods=["GET"])
@login_required
def api_get_digest_posts(digest_id: str):
    """Возвращает все сохранённые посты для данного дайджеста."""
    from modules.db import get_digest_posts
    posts = get_digest_posts(digest_id=digest_id, user_id=session["user_id"])
    return jsonify({"ok": True, "posts": posts})


# ─── Генерация превью изображений ────────────────────────────────────────────

@app.route("/api/digest-posts/<int:post_id>/generate-preview", methods=["POST"])
@login_required
def api_generate_preview(post_id: int):
    """Генерирует превью-изображение для поста через Gemini API."""
    from modules.db import get_digest_post_by_id, update_digest_post
    from modules.media.image_gen import generate_preview

    data = request.get_json(silent=True) or {}
    use_face = data.get("use_face")          # None = авто, True/False = принудительно
    aspect_ratio = data.get("aspect_ratio")  # None = случайный

    # Получаем данные поста
    post = get_digest_post_by_id(post_id, user_id=session["user_id"])
    if not post:
        return jsonify({"ok": False, "error": "Пост не найден"}), 404

    config = load_config()

    result = generate_preview(
        theme=post.get("theme", ""),
        post_text=post.get("text", ""),
        category=post.get("category", "expert"),
        post_format=post.get("format", "opinion"),
        config=config,
        use_face=use_face,
        aspect_ratio=aspect_ratio,
    )

    if not result["success"]:
        return jsonify({"ok": False, "error": result["error"]}), 500

    # Сохраняем путь к превью в БД
    update_digest_post(post_id, user_id=session["user_id"], preview_path=result["path"])

    return jsonify({
        "ok": True,
        "preview_url": f"/media/previews/{result['filename']}",
        "aspect_ratio": result["aspect_ratio"],
        "used_face": result["used_face"],
    })


@app.route("/api/generate-preview-free", methods=["POST"])
@login_required
def api_generate_preview_free():
    """Генерирует превью без привязки к посту (свободный запрос)."""
    from modules.media.image_gen import generate_preview

    data = request.get_json(silent=True) or {}
    theme = data.get("theme", "")
    post_text = data.get("text", "")
    category = data.get("category", "expert")
    post_format = data.get("format", "opinion")
    use_face = data.get("use_face")
    aspect_ratio = data.get("aspect_ratio")
    show_text = data.get("show_text", True)

    if not theme and not post_text:
        return jsonify({"ok": False, "error": "Нужна тема или текст"}), 400

    config = load_config()
    result = generate_preview(
        theme=theme,
        post_text=post_text,
        category=category,
        post_format=post_format,
        config=config,
        use_face=use_face,
        aspect_ratio=aspect_ratio,
        show_text=bool(show_text),
    )

    if not result["success"]:
        return jsonify({"ok": False, "error": result["error"]}), 500

    # media_path в БД — относительный путь от data/media/ (как используется в publish_to_channel)
    db_media_path = f"previews/{result['filename']}"
    return jsonify({
        "ok": True,
        "preview_url": f"/media/previews/{result['filename']}",
        "file_path": db_media_path,
        "aspect_ratio": result["aspect_ratio"],
        "used_face": result["used_face"],
    })


# ─── Подпись к постам ────────────────────────────────────────────────────────

@app.route("/api/curator/signature", methods=["GET"])
@login_required
def api_get_signature():
    from modules.db import get_user
    user = get_user(session["user_id"])
    return jsonify({"ok": True, "signature": user.get("post_signature", "") if user else ""})


@app.route("/api/curator/signature", methods=["POST"])
@login_required
def api_save_signature():
    from modules.db import update_user
    data = request.json or {}
    sig = data.get("signature", "")
    update_user(session["user_id"], post_signature=sig)
    return jsonify({"ok": True})


# ─── Профиль и администрирование ─────────────────────────────────────────────

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    from modules.db import get_user, update_user
    user = get_user(session["user_id"])
    error = ""
    success = ""

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "update_profile":
            api_key = request.form.get("anthropic_api_key", "").strip()
            model = request.form.get("anthropic_model", "claude-sonnet-4-6")
            target_channel = request.form.get("target_channel", "").strip()
            channel_description = request.form.get("channel_description", "").strip()
            update_user(session["user_id"],
                        anthropic_api_key=api_key,
                        anthropic_model=model,
                        target_channel=target_channel,
                        channel_description=channel_description)
            success = "Профиль обновлён"
            user = get_user(session["user_id"])

        elif action == "change_password":
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "").strip()
            new_pw2 = request.form.get("new_password2", "").strip()
            if not check_password(old_pw, user["password_hash"]):
                error = "Неверный текущий пароль"
            elif len(new_pw) < 8:
                error = "Новый пароль минимум 8 символов"
            elif new_pw != new_pw2:
                error = "Пароли не совпадают"
            else:
                update_user(session["user_id"], password_hash=hash_password(new_pw))
                success = "Пароль изменён"

    return render_template("profile.html", user=user, error=error, success=success)


@app.route("/profile/totp", methods=["GET", "POST"])
@login_required
def profile_totp():
    from modules.db import get_user, update_user
    user = get_user(session["user_id"])
    error = ""

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "enable":
            # Генерируем новый secret
            secret = generate_totp_secret()
            update_user(session["user_id"], totp_secret=secret, totp_verified=0)
            return redirect("/setup-totp")

        elif action == "disable":
            code = request.form.get("code", "").strip()
            if not user.get("totp_secret") or not verify_totp(user["totp_secret"], code):
                error = "Неверный код"
            else:
                update_user(session["user_id"], totp_secret=None, totp_verified=0)
                return redirect("/profile")

    return render_template("profile_totp.html", user=user, error=error)


@app.route("/admin")
@admin_required
def admin_page():
    from modules.db import get_all_users
    users = get_all_users()
    return render_template("admin.html", users=users)


@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@admin_required
def api_admin_delete_user(uid: int):
    from modules.db import delete_user, get_user
    if uid == session["user_id"]:
        return jsonify({"ok": False, "error": "Нельзя удалить себя"}), 400
    user = get_user(uid)
    if not user:
        return jsonify({"ok": False, "error": "Не найден"}), 404
    delete_user(uid)
    return jsonify({"ok": True})
