"""
digest/summarizer.py — генерация дайджестов через Claude API
"""
import logging
from typing import Optional
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — умный ассистент, который составляет дайджесты Telegram-переписки.
Твоя задача: помочь занятому человеку быстро понять, что обсуждалось в чате, не читая всё самому.

Стиль: лаконично, по делу, на русском языке. Никаких лишних слов и вводных фраз.
Выделяй только действительно важное и интересное — не пересказывай каждое сообщение."""


def build_prompt(chat_data: dict, digest_type: str, days_back: int) -> Optional[str]:
    msgs = [m for m in chat_data["messages"] if not m.get("is_bot", False)]
    if not msgs:
        return None

    formatted = []
    for m in msgs:
        date_str = m["date"][:16].replace("T", " ")
        reply = f" [↩ reply to #{m['reply_to']}]" if m.get("reply_to") else ""
        fwd = " [fwd]" if m.get("is_forward") else ""
        formatted.append(f"[{date_str}] {m['sender']}{fwd}{reply}: {m['text']}")

    period_label = {
        "daily": f"за последние {days_back} день",
        "weekly": f"за последние {days_back} дней",
        "monthly": f"за последние {days_back} дней",
    }.get(digest_type, f"за последние {days_back} дней")

    return f"""Вот переписка из чата/канала «{chat_data['name']}» {period_label} ({len(msgs)} сообщений).

--- НАЧАЛО ПЕРЕПИСКИ ---
{chr(10).join(formatted)}
--- КОНЕЦ ПЕРЕПИСКИ ---

Составь дайджест в строго следующем формате:

**📌 Главные темы**
(3-5 основных тем, которые обсуждались. Каждая тема — 1-2 предложения, суть обсуждения)

**❓ Лучшие Q&A**
(2-3 самых полезных вопроса с ответами. Формат: Вопрос: ... → Ответ: ...)
Если вопросов не было — пропусти этот раздел.

**💡 Ключевые инсайты**
(1-3 важных вывода, факта или совета из обсуждения)

**🔗 Упомянутые ресурсы**
(ссылки, инструменты, сервисы — если упоминались. Если нет — пропусти)

Будь максимально конкретен. Не пиши «участники обсудили» — пиши о чём именно."""


class DigestSummarizer:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def summarize_chat(self, chat_data: dict, digest_type: str, days_back: int, min_messages: int = 5) -> Optional[str]:
        msgs = [m for m in chat_data["messages"] if not m.get("is_bot")]
        if len(msgs) < min_messages:
            logger.info(f"Пропускаю {chat_data['name']}: только {len(msgs)} сообщений")
            return None

        prompt = build_prompt(chat_data, digest_type, days_back)
        if not prompt:
            return None

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Ошибка Claude API для {chat_data['name']}: {e}")
            return None

    async def summarize_all(self, chats_data: list, digest_type: str, days_back: int, min_messages: int = 5) -> list:
        sorted_chats = sorted(
            chats_data,
            key=lambda x: {"high": 0, "normal": 1, "low": 2}.get(x.get("priority", "normal"), 1)
        )
        results = []
        for chat_data in sorted_chats:
            if not chat_data:
                continue
            logger.info(f"Суммаризирую: {chat_data['name']}")
            summary = await self.summarize_chat(chat_data, digest_type, days_back, min_messages)
            if summary:
                results.append({
                    "name": chat_data["name"],
                    "priority": chat_data.get("priority", "normal"),
                    "message_count": chat_data["message_count"],
                    "summary": summary,
                })
        return results
