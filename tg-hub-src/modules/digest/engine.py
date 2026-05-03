"""
digest/engine.py — оркестратор: читаем → фильтруем → суммаризируем → сохраняем → отправляем
"""
import logging
from modules.digest.reader import TelegramReader
from modules.digest.summarizer import DigestSummarizer
from modules.digest.sender import DigestSender
from modules.db import save_digest

logger = logging.getLogger(__name__)


class DigestEngine:
    def __init__(self, config: dict):
        self.config = config
        tg = config["telegram"]
        dcfg = config["digest"]
        bot = config["bot"]
        ai = config["anthropic"]

        self.reader = TelegramReader(
            api_id=tg["api_id"],
            api_hash=tg["api_hash"],
            session_name=tg.get("session_name", "tghub_session"),
        )
        self.summarizer = DigestSummarizer(
            api_key=ai["api_key"],
            model=ai.get("model", "claude-opus-4-6"),
        )
        self.sender = DigestSender(
            bot_token=bot["token"],
            owner_id=int(bot["owner_id"]),
        )
        self.digest_cfg = dcfg

    async def run_digest(self, digest_type: str):
        schedule_cfg = self.digest_cfg["schedule"][digest_type]
        days_back = schedule_cfg["days_back"]
        filters = self.digest_cfg.get("filters", {})
        chats = self.digest_cfg["chats"]

        logger.info(f"=== Запускаю {digest_type} дайджест (за {days_back} дней) ===")
        await self.sender.send_status(f"⏳ Собираю {digest_type} дайджест из {len(chats)} чатов...")

        # Лимит сообщений для текущего типа дайджеста
        limits_cfg = self.digest_cfg.get("messages_limits", {})
        messages_limit = limits_cfg.get(digest_type, {"daily": 2000, "weekly": 5000, "monthly": 10000}[digest_type])

        await self.reader.start()
        chats_data = []
        for chat_cfg in chats:
            try:
                data = await self.reader.read_chat(chat_cfg, days_back, messages_limit=messages_limit)
                if data:
                    data["messages"] = self._apply_filters(data["messages"], filters)
                    chats_data.append(data)
            except Exception as e:
                logger.error(f"Ошибка чтения {chat_cfg.get('name', '?')}: {e}")
        await self.reader.stop()

        logger.info(f"Прочитано {len(chats_data)} чатов")
        summaries = await self.summarizer.summarize_all(
            chats_data,
            digest_type=digest_type,
            days_back=days_back,
            min_messages=filters.get("min_messages_for_summary", 5),
        )
        logger.info(f"Суммаризировано {len(summaries)} чатов")
        save_digest(digest_type, summaries, days_back)
        await self.sender.send_digest(summaries, digest_type, days_back)
        logger.info(f"=== {digest_type} дайджест отправлен ===")

    def _apply_filters(self, messages: list, filters: dict) -> list:
        min_len = filters.get("min_message_length", 20)
        skip_bots = filters.get("skip_bots", True)
        skip_fwd = filters.get("skip_forwards_only", False)
        result = []
        for msg in messages:
            if len(msg.get("text", "")) < min_len:
                continue
            if skip_bots and msg.get("is_bot"):
                continue
            if skip_fwd and msg.get("is_forward") and not msg.get("reply_to"):
                continue
            result.append(msg)
        return result
