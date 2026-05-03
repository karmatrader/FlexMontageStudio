"""
curator/parser.py — парсинг постов из Telegram-каналов через Telethon
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from modules.db import save_post, get_posts

logger = logging.getLogger(__name__)


def save_posts_history(new_posts: list) -> int:
    added = 0
    for p in new_posts:
        try:
            save_post(p)
            added += 1
        except Exception:
            pass
    return added


async def fetch_posts_from_channel(client: TelegramClient, channel: str, cfg: dict) -> list:
    posts = []
    hours_lookback = cfg.get("hours_lookback", 2400)
    posts_per_channel = cfg.get("posts_per_channel", 10)
    min_post_length = cfg.get("min_post_length", 100)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)

    try:
        entity = await client.get_entity(channel)
        async for message in client.iter_messages(entity, limit=posts_per_channel * 5):
            if message.date < cutoff:
                continue
            text = message.text or getattr(message, "caption", None) or ""
            if len(text) < min_post_length:
                continue
            posts.append({
                "channel": channel,
                "message_id": message.id,
                "text": text,
                "date": message.date.isoformat(),
                "views": message.views or 0,
                "has_photo": isinstance(message.media, MessageMediaPhoto),
                "has_video": isinstance(message.media, MessageMediaDocument),
                "url": f"https://t.me/{channel.lstrip('@')}/{message.id}",
            })
            if len(posts) >= posts_per_channel:
                break
    except Exception as e:
        logger.error(f"Ошибка при парсинге {channel}: {e}")

    return posts


async def fetch_all_posts(config: dict) -> list:
    tg = config["telegram"]
    curator_cfg = config["curator"]
    source_channels = curator_cfg["source_channels"]
    parsing_cfg = curator_cfg.get("parsing", {})
    session_path = tg.get("session_name", "tghub_session")

    logger.info(f"Начинаю парсинг {len(source_channels)} каналов...")

    async with TelegramClient(session_path, int(tg["api_id"]), tg["api_hash"]) as client:
        all_posts = []
        for channel in source_channels:
            posts = await fetch_posts_from_channel(client, channel, parsing_cfg)
            logger.info(f"{channel}: найдено {len(posts)} постов")
            all_posts.extend(posts)
            await asyncio.sleep(1)

    all_posts.sort(key=lambda x: x["views"], reverse=True)
    added = save_posts_history(all_posts)
    logger.info(f"Сохранено {added} новых постов, всего в базе: {len(get_posts())}")
    return all_posts


async def sync_my_channel(config: dict) -> dict:
    """Синхронизирует посты из собственного канала в таблицу my_posts."""
    from modules.db import save_my_post
    tg = config["telegram"]
    target = config["curator"]["target_channel"]
    session_path = tg.get("session_name", "tghub_session")
    since = datetime.now(timezone.utc) - timedelta(days=90)

    logger.info(f"Синк моего канала: {target}")
    synced = 0
    new_count = 0

    try:
        async with TelegramClient(session_path, int(tg["api_id"]), tg["api_hash"]) as client:
            entity = await client.get_entity(target)
            async for message in client.iter_messages(entity, limit=500):
                if message.date.replace(tzinfo=timezone.utc) < since:
                    break
                text = message.text or getattr(message, "caption", None) or ""
                if len(text) < 20:
                    continue
                is_new = save_my_post(
                    message_id=message.id,
                    text=text[:3000],
                    date=message.date.isoformat(),
                    views=message.views or 0,
                )
                synced += 1
                if is_new:
                    new_count += 1
    except Exception as e:
        logger.error(f"Ошибка синка моего канала: {e}")
        return {"synced": 0, "new": 0, "error": str(e)}

    logger.info(f"Синк завершён: {synced} обработано, {new_count} новых")
    return {"synced": synced, "new": new_count}


async def publish_to_channel(text: str, config: dict, media_path: str = None) -> None:
    import os
    tg = config["telegram"]
    target = config["curator"]["target_channel"]
    session_path = tg.get("session_name", "tghub_session")
    async with TelegramClient(session_path, int(tg["api_id"]), tg["api_hash"]) as client:
        if media_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            full_path = os.path.join(base_dir, "data", "media", media_path)
            if os.path.exists(full_path):
                await client.send_file(target, full_path, caption=text, parse_mode='md')
                return
        await client.send_message(target, text, parse_mode='md')
