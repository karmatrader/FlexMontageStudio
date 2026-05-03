"""
digest/reader.py — чтение сообщений из Telegram через Telethon
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage
from telethon.tl.functions.channels import GetForumTopicsRequest

logger = logging.getLogger(__name__)


class TelegramReader:
    def __init__(self, api_id: str, api_hash: str, session_name: str):
        self.client = TelegramClient(session_name, int(api_id), api_hash)

    async def start(self):
        await self.client.start()
        me = await self.client.get_me()
        logger.info(f"Авторизован как: {me.first_name} (@{me.username})")

    async def stop(self):
        await self.client.disconnect()

    async def read_chat(self, chat_config: dict, days_back: int, messages_limit: int = 2000) -> Optional[dict]:
        chat_id = chat_config["id"]
        chat_type = chat_config.get("type", "group")
        topic_id = chat_config.get("topic_id")
        chat_name = chat_config.get("name", str(chat_id))
        since = datetime.now(timezone.utc) - timedelta(days=days_back)

        try:
            entity = await self.client.get_entity(chat_id)
        except Exception as e:
            logger.error(f"Не удалось получить entity для {chat_name}: {e}")
            return None

        logger.info(f"Читаю: {chat_name} ({chat_type}), лимит {messages_limit} сообщений")
        messages = []
        try:
            if chat_type == "topic" and topic_id:
                messages = await self._read_topic(entity, topic_id, since, limit=messages_limit)
            elif chat_type == "channel":
                messages = await self._read_channel(entity, since)
            else:
                messages = await self._read_group(entity, since, limit=messages_limit)
        except Exception as e:
            logger.error(f"Ошибка чтения {chat_name}: {e}")
            return None

        return {
            "name": chat_name,
            "type": chat_type,
            "id": chat_id,
            "priority": chat_config.get("priority", "normal"),
            "message_count": len(messages),
            "messages": messages,
            "since": since.isoformat(),
        }

    async def _read_channel(self, entity, since: datetime) -> list:
        messages = []
        async for msg in self.client.iter_messages(entity, offset_date=None, reverse=False):
            if msg.date.replace(tzinfo=timezone.utc) < since:
                break
            parsed = self._parse_message(msg)
            if parsed:
                messages.append(parsed)
        return list(reversed(messages))

    async def _read_group(self, entity, since: datetime, limit: int = 2000) -> list:
        messages = []
        async for msg in self.client.iter_messages(entity, limit=limit):
            if msg.date.replace(tzinfo=timezone.utc) < since:
                break
            parsed = self._parse_message(msg)
            if parsed:
                messages.append(parsed)
        return list(reversed(messages))

    async def _read_topic(self, entity, topic_id: int, since: datetime, limit: int = 1000) -> list:
        messages = []
        async for msg in self.client.iter_messages(entity, reply_to=topic_id, limit=limit):
            if msg.date.replace(tzinfo=timezone.utc) < since:
                break
            parsed = self._parse_message(msg)
            if parsed:
                messages.append(parsed)
        return list(reversed(messages))

    async def get_forum_topics(self, chat_id) -> list:
        try:
            entity = await self.client.get_entity(chat_id)
            result = await self.client(GetForumTopicsRequest(
                channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100,
            ))
            return [{"id": t.id, "title": t.title} for t in result.topics]
        except Exception as e:
            logger.error(f"Ошибка получения топиков: {e}")
            return []

    def _parse_message(self, msg) -> Optional[dict]:
        if not msg or (not msg.text and not self._has_media(msg)):
            return None
        text = msg.text or ""
        media_desc = self._get_media_desc(msg)
        if media_desc and not text:
            text = media_desc
        elif media_desc:
            text = f"{text} [{media_desc}]"
        if not text.strip():
            return None

        sender_name = "Unknown"
        if msg.sender:
            s = msg.sender
            if hasattr(s, "first_name"):
                sender_name = ((s.first_name or "") + (" " + s.last_name if s.last_name else "")).strip()
                if hasattr(s, "username") and s.username:
                    sender_name = f"{sender_name} (@{s.username})"
            elif hasattr(s, "title"):
                sender_name = s.title

        return {
            "id": msg.id,
            "date": msg.date.isoformat(),
            "sender": sender_name,
            "is_bot": getattr(msg.sender, "bot", False) if msg.sender else False,
            "text": text[:3000],
            "reply_to": msg.reply_to_msg_id if msg.reply_to else None,
            "views": getattr(msg, "views", None),
            "is_forward": bool(msg.forward),
        }

    def _has_media(self, msg) -> bool:
        return bool(msg.media) and not isinstance(msg.media, MessageMediaWebPage)

    def _get_media_desc(self, msg) -> str:
        if not msg.media:
            return ""
        if isinstance(msg.media, MessageMediaPhoto):
            return "📷 фото"
        if isinstance(msg.media, MessageMediaDocument):
            return "📎 файл/документ"
        return ""
