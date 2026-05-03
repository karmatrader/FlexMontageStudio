"""
run.py — главная точка входа TG Hub
Запускает все компоненты в одном процессе:
  - Flask веб-панель (поток)
  - Curator бот (asyncio)
  - Digest планировщик (asyncio)
"""
import asyncio
import logging
import sys
import threading
import yaml

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("tghub.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_web(config: dict):
    """Запускает Flask в отдельном потоке."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "web"))
    # Инициализируем БД и первого пользователя
    from modules.db import init_db, migrate_first_user_from_config
    init_db()
    migrate_first_user_from_config(config)
    from web.app import app
    web_cfg = config.get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = web_cfg.get("port", 5000)
    logger.info(f"Веб-панель: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


async def _run_digest(engine, digest_type: str):
    await engine.run_digest(digest_type)


def setup_digest_scheduler_for_user(scheduler: AsyncIOScheduler, user_id: int, system_config: dict):
    """Добавляет digest-задачи для конкретного пользователя."""
    from modules.db import get_user_config
    from modules.digest.engine import DigestEngine

    cfg = get_user_config(user_id, system_config)
    engine = DigestEngine(cfg)
    dcfg = cfg["digest"]["schedule"]
    day_map = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
               "friday": "fri", "saturday": "sat", "sunday": "sun"}

    if dcfg.get("daily", {}).get("enabled"):
        t = dcfg["daily"]["time"].split(":")
        scheduler.add_job(
            _run_digest,
            CronTrigger(hour=int(t[0]), minute=int(t[1]), timezone=MOSCOW_TZ),
            args=[engine, "daily"],
            id=f"digest_daily_u{user_id}", name=f"Digest ежедневный u{user_id}",
            replace_existing=True,
        )
        logger.info(f"[u{user_id}] Digest ежедневный: {dcfg['daily']['time']} МСК")

    if dcfg.get("weekly", {}).get("enabled"):
        t = dcfg["weekly"]["time"].split(":")
        day = day_map.get(dcfg["weekly"].get("weekday", "friday").lower(), "fri")
        scheduler.add_job(
            _run_digest,
            CronTrigger(day_of_week=day, hour=int(t[0]), minute=int(t[1]), timezone=MOSCOW_TZ),
            args=[engine, "weekly"],
            id=f"digest_weekly_u{user_id}", name=f"Digest еженедельный u{user_id}",
            replace_existing=True,
        )
        logger.info(f"[u{user_id}] Digest еженедельный: {dcfg['weekly']['time']} МСК")

    if dcfg.get("monthly", {}).get("enabled"):
        t = dcfg["monthly"]["time"].split(":")
        day_num = dcfg["monthly"].get("day", 1)
        scheduler.add_job(
            _run_digest,
            CronTrigger(day=day_num, hour=int(t[0]), minute=int(t[1]), timezone=MOSCOW_TZ),
            args=[engine, "monthly"],
            id=f"digest_monthly_u{user_id}", name=f"Digest ежемесячный u{user_id}",
            replace_existing=True,
        )
        logger.info(f"[u{user_id}] Digest ежемесячный: {day_num}-е {dcfg['monthly']['time']} МСК")


def setup_digest_scheduler(scheduler: AsyncIOScheduler, config: dict):
    """Обратная совместимость: настраивает digest для первого пользователя."""
    setup_digest_scheduler_for_user(scheduler, 1, config)


async def publish_queue_job(config: dict, bot=None, user_id: int = 1):
    """Публикует посты из очереди, время которых наступило."""
    from modules.db import get_due_queue_items, mark_queue_item_published, mark_queue_item_failed
    from modules.curator.parser import publish_to_channel, sync_my_channel
    from modules.curator.bot import notify_owner
    items = get_due_queue_items(user_id=user_id)
    if not items:
        return
    logger.info(f"[Queue/u{user_id}] Публикую {len(items)} поста(ов) из очереди")
    for item in items:
        try:
            await publish_to_channel(item["text"], config, media_path=item.get("media_path"))
            mark_queue_item_published(item["id"])
            logger.info(f"[Queue/u{user_id}] Опубликован #{item['id']}")
            if bot:
                preview = item["text"][:150].replace("*", "").replace("_", "").replace("`", "")
                await notify_owner(bot, config, f"✅ Опубликован пост \\#{item['id']}:\n_{preview}_",
                                   event="queue_published", user_id=user_id)
            # Автосинк my_posts сразу после публикации
            try:
                result = await sync_my_channel(config)
                logger.info(f"[Queue/u{user_id}] Автосинк my_channel: {result}")
            except Exception as se:
                logger.warning(f"[Queue/u{user_id}] Автосинк my_channel ошибка: {se}")
        except Exception as e:
            mark_queue_item_failed(item["id"])
            logger.error(f"[Queue/u{user_id}] Ошибка публикации #{item['id']}: {e}")
            if bot:
                await notify_owner(bot, config, f"❌ Ошибка публикации \\#{item['id']}: {e}",
                                   event="queue_failed", user_id=user_id)


def setup_curator_scheduler_for_user(scheduler: AsyncIOScheduler, app, user_id: int,
                                      system_config: dict):
    """Добавляет curator-задачи для конкретного пользователя."""
    from modules.db import get_user_config, get_user_schedule
    from modules.curator.bot import trigger_auto_generation
    from modules.curator.parser import fetch_all_posts, sync_my_channel

    cfg = get_user_config(user_id, system_config)
    sched = get_user_schedule(user_id)

    # Ежедневный парсинг новых постов
    parse_hour = cfg["curator"]["schedule"].get("parse_hour", 9)
    scheduler.add_job(
        lambda c=cfg: asyncio.create_task(fetch_all_posts(c)),
        CronTrigger(hour=parse_hour, minute=0, timezone=MOSCOW_TZ),
        id=f"curator_parse_u{user_id}",
        name=f"[u{user_id}] Curator парсинг {parse_hour:02d}:00",
        replace_existing=True,
    )

    # Публикация из очереди каждые 5 минут — точное срабатывание по времени
    scheduler.add_job(
        publish_queue_job,
        CronTrigger(minute="*/5", timezone=MOSCOW_TZ),
        args=[cfg, getattr(app, "bot", None), user_id],
        id=f"curator_queue_u{user_id}",
        name=f"[u{user_id}] Curator очередь",
        replace_existing=True,
    )

    # Синк собственного канала (03:00 МСК)
    scheduler.add_job(
        lambda c=cfg: asyncio.create_task(sync_my_channel(c)),
        CronTrigger(hour=3, minute=0, timezone=MOSCOW_TZ),
        id=f"my_channel_sync_u{user_id}",
        name=f"[u{user_id}] Синк моего канала",
        replace_existing=True,
    )

    # Автогенерация постов
    hours = cfg["curator"]["schedule"].get("hours", [12])
    for hour in hours:
        scheduler.add_job(
            trigger_auto_generation,
            CronTrigger(hour=hour, minute=0, timezone=MOSCOW_TZ),
            args=[getattr(app, "bot", None), cfg, user_id],
            id=f"curator_auto_{hour}_u{user_id}",
            name=f"[u{user_id}] Curator автогенерация {hour:02d}:00",
            replace_existing=True,
        )
    logger.info(f"[u{user_id}] Curator scheduler настроен")


def setup_curator_scheduler(scheduler: AsyncIOScheduler, app, config: dict):
    """Обратная совместимость: настраивает curator для первого пользователя."""
    setup_curator_scheduler_for_user(scheduler, app, 1, config)


async def run_all(config: dict):
    """Основной async цикл."""
    # Инициализируем БД и мигрируем первого пользователя из config.yaml
    from modules.db import init_db, migrate_first_user_from_config, get_all_users
    init_db()
    migrate_first_user_from_config(config)

    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

    # Curator бот (один на инстанс, для TG-уведомлений)
    curator_app = None
    if config["curator"].get("enabled", True):
        from modules.curator.bot import build_curator_app
        curator_app = build_curator_app(config)

    # Настраиваем schedulers для всех пользователей
    users = get_all_users()
    for user in users:
        uid = user["id"]
        if config["digest"].get("enabled", True):
            try:
                setup_digest_scheduler_for_user(scheduler, uid, config)
            except Exception as e:
                logger.warning(f"[u{uid}] Ошибка настройки digest scheduler: {e}")
        if config["curator"].get("enabled", True) and curator_app:
            try:
                setup_curator_scheduler_for_user(scheduler, curator_app, uid, config)
            except Exception as e:
                logger.warning(f"[u{uid}] Ошибка настройки curator scheduler: {e}")

    scheduler.start()
    logger.info("✅ Планировщик запущен")

    for job in scheduler.get_jobs():
        if job.next_run_time:
            logger.info(f"  → {job.name}: {job.next_run_time.strftime('%d.%m %H:%M %Z')}")

    # Запускаем бота
    if curator_app:
        await curator_app.initialize()
        await curator_app.start()
        await curator_app.updater.start_polling()
        logger.info("✅ Curator бот запущен")

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Останавливаю...")
        scheduler.shutdown()
        if curator_app:
            await curator_app.updater.stop()
            await curator_app.stop()
            await curator_app.shutdown()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TG Hub — Telegram Automation")
    parser.add_argument("command", nargs="?", default="run",
        choices=["run", "web", "digest-daily", "digest-weekly", "digest-monthly"],
        help="run — всё; web — только панель; digest-* — разовый дайджест")
    args = parser.parse_args()

    config = load_config()

    if args.command == "web":
        run_web(config)
        return

    if args.command in ("digest-daily", "digest-weekly", "digest-monthly"):
        digest_type = args.command.replace("digest-", "")
        async def _run():
            from modules.digest.engine import DigestEngine
            engine = DigestEngine(config)
            await engine.run_digest(digest_type)
        asyncio.run(_run())
        return

    # Полный режим: веб в потоке + async всё остальное
    web_thread = threading.Thread(target=run_web, args=(config,), daemon=True)
    web_thread.start()
    logger.info("Веб-панель запущена в фоне")

    asyncio.run(run_all(config))


if __name__ == "__main__":
    main()
