"""
digest/sender.py — форматирование и отправка дайджеста через бота
"""
import asyncio
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

DIGEST_HEADERS = {
    "daily": "📰 ЕЖЕДНЕВНЫЙ ДАЙДЖЕСТ",
    "weekly": "📊 ЕЖЕНЕДЕЛЬНЫЙ ДАЙДЖЕСТ",
    "monthly": "🗓 ЕЖЕМЕСЯЧНЫЙ ДАЙДЖЕСТ",
}
PRIORITY_EMOJI = {"high": "🔴", "normal": "🔵", "low": "⚪️"}


class DigestSender:
    def __init__(self, bot_token: str, owner_id: int):
        self.bot = Bot(token=bot_token)
        self.owner_id = owner_id

    def format_digest(self, summaries: list, digest_type: str, days_back: int) -> list:
        now = datetime.now()
        date_str = now.strftime("%d.%m.%Y %H:%M")
        header = DIGEST_HEADERS.get(digest_type, "📋 ДАЙДЖЕСТ")
        period_map = {"daily": "за сегодня", "weekly": f"за {days_back} дней", "monthly": f"за {days_back} дней"}
        period_str = period_map.get(digest_type, f"за {days_back} дней")

        if not summaries:
            return [f"{header}\n{date_str}\n\nНечего показывать — активности не было."]

        parts = [
            f"*{header}*\n_{date_str} • {period_str}_\nЧатов: {len(summaries)}\n{'═' * 30}"
        ]
        toc = ["*📋 Что внутри:*"] + [
            f"{i}. {PRIORITY_EMOJI.get(s['priority'], '🔵')} {s['name']} ({s['message_count']} сообщ.)"
            for i, s in enumerate(summaries, 1)
        ]
        parts.append("\n".join(toc))

        chat_blocks = []
        for i, s in enumerate(summaries, 1):
            emoji = PRIORITY_EMOJI.get(s["priority"], "🔵")
            chat_blocks.append(
                f"{'─' * 30}\n*{emoji} {i}. {s['name']}*\n_{s['message_count']} сообщений_\n\n{s['summary']}"
            )

        messages = []
        current = "\n\n".join(parts)
        for block in chat_blocks:
            if len(current) + len(block) + 4 > 4000:
                messages.append(current)
                current = block
            else:
                current += "\n\n" + block
        if current:
            messages.append(current)

        total = len(messages)
        if total > 1:
            messages = [f"{msg}\n\n_Часть {i}/{total}_" for i, msg in enumerate(messages, 1)]

        return messages

    async def send_digest(self, summaries: list, digest_type: str, days_back: int):
        messages = self.format_digest(summaries, digest_type, days_back)
        logger.info(f"Отправляю дайджест: {len(messages)} сообщений")
        for i, text in enumerate(messages):
            try:
                await self.bot.send_message(
                    chat_id=self.owner_id, text=text,
                    parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
                )
                if i < len(messages) - 1:
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка отправки части {i+1}: {e}")
                try:
                    clean = text.replace("*", "").replace("_", "").replace("`", "")
                    await self.bot.send_message(chat_id=self.owner_id, text=clean, disable_web_page_preview=True)
                except Exception as e2:
                    logger.error(f"Не удалось отправить без форматирования: {e2}")

    async def send_status(self, message: str):
        try:
            await self.bot.send_message(chat_id=self.owner_id, text=message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Ошибка отправки статуса: {e}")
