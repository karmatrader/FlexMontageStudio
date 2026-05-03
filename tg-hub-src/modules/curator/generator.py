"""
curator/generator.py — генерация постов для канала через Claude API
"""
import json
import logging
import anthropic

logger = logging.getLogger(__name__)


def build_context(posts: list) -> str:
    if not posts:
        return "Новых постов не найдено."
    lines = []
    for i, post in enumerate(posts[:20], 1):
        lines.append(
            f"--- Пост {i} из {post['channel']} (просмотры: {post['views']}) ---\n"
            f"{post['text']}\nСсылка: {post['url']}\n"
        )
    return "\n".join(lines)


def build_voice_context() -> str:
    """Читает примеры из БД, форматирует в блок для prompt."""
    try:
        from modules.db import get_voice_examples
        examples = get_voice_examples()
        if not examples:
            return ""
        lines = ["Примеры постов в нужном стиле голоса канала (пиши похожим образом):"]
        for ex in examples[:10]:
            label = f" ({ex['label']})" if ex.get("label") else ""
            lines.append(f"\n[Пример{label}]\n{ex['text']}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Не удалось загрузить примеры голоса: {e}")
        return ""


def humanize_post(text: str, config: dict) -> str:
    """
    Двухпроходная гуманизация по правилам humanizer skill (24 категории AI-паттернов).
    Проход 1: аудит AI-паттернов.
    Проход 2: переписываем с учётом найденных проблем.
    """
    model = config["anthropic"].get("model", "claude-opus-4-6")
    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])

    # ── Проход 1: аудит ──────────────────────────────────────────────────────
    audit_prompt = f"""Ты — редактор, который ловит AI-штампы в текстах на русском языке.

Проверь текст ниже и коротко перечисли найденные проблемы (без исправлений):

ЗАПРЕЩЁННЫЕ ПАТТЕРНЫ которые ищешь:
1. Длинное тире (—) вместо запятой или точки
2. Конструкции «не только X, но и Y», «это не просто X, это Y» (антитезы-параллелизмы)
3. Правило трёх — перечисления ровно из трёх элементов без реальной нужды
4. Рекламный язык: «революционный», «инновационный», «прорывной», «уникальный», «трансформирует»
5. AI-словарь: «невероятно», «потрясающий», «ключевой», «подчёркивает», «важно отметить»,
   «в заключение», «давайте разберёмся», «в современном мире», «в мире где»,
   «напоминает нам», «это свидетельствует», «примечательно что»
6. Причастные обороты на -ющий/-ящий в конце предложения для псевдо-глубины
   (подчёркивая, отражая, демонстрируя, указывая, показывая)
7. Безликие атрибуции: «эксперты говорят», «исследования показывают», «специалисты считают»
8. Общий позитивный вывод: «будущее выглядит светлым», «впереди нас ждёт», «это открывает новые горизонты»
9. Канцелярит: «в рамках», «в целях», «на предмет», «осуществлять»
10. Пустые вводные: «Интересно, что...», «Стоит отметить, что...», «Следует подчеркнуть»

Текст:
---
{text}
---

Ответь коротко: перечисли найденные проблемы. Если проблем нет — напиши «ЧИСТО»."""

    audit_msg = client.messages.create(
        model=model, max_tokens=400,
        messages=[{"role": "user", "content": audit_prompt}],
    )
    audit_result = audit_msg.content[0].text.strip()

    # Если аудит нашёл проблемы — переписываем; если чисто — возвращаем как есть
    if audit_result.upper().startswith("ЧИСТО"):
        return text

    # ── Проход 2: переписываем ───────────────────────────────────────────────
    rewrite_prompt = f"""Перепиши текст ниже, устранив найденные AI-паттерны.

Найденные проблемы:
{audit_result}

ПРАВИЛА ПЕРЕПИСЫВАНИЯ:
- Длинное тире (—) → замени на запятую, точку или двоеточие
- «не только X, но и Y» → «и X, и Y» или переформулируй без параллелизма
- Перечисления из трёх → оставь только если это реально нужно, иначе сократи
- Рекламные слова → удали или замени конкретными фактами
- AI-словарь → удали вводные, переформулируй мысль напрямую
- Причастные обороты в хвосте → замени на отдельное предложение или удали
- Безликие атрибуции → либо убери, либо добавь конкретику
- Общий вывод → конкретный вывод или вообще без него
- Канцелярит → живой язык
- Пустые вводные → удали, начни сразу с сути

СОХРАНИ:
- Все факты и смысл
- Примерную длину (±15%)
- Тон и стиль автора
- Ссылки если есть

Верни ТОЛЬКО готовый текст без пояснений.

Текст:
---
{text}
---"""

    rewrite_msg = client.messages.create(
        model=model, max_tokens=1500,
        messages=[{"role": "user", "content": rewrite_prompt}],
    )
    return rewrite_msg.content[0].text.strip()


def generate_post(posts: list, config: dict) -> str:
    if not posts:
        raise ValueError("Нет постов для анализа")

    channel_desc = config["curator"]["channel_description"]
    voice_block = build_voice_context()
    context = build_context(posts)
    model = config["anthropic"].get("model", "claude-opus-4-6")

    voice_section = f"\n{voice_block}\n" if voice_block else ""

    prompt = f"""Ты — редактор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}
Ниже — свежие посты из других каналов для вдохновения и мониторинга трендов:

{context}

Твоя задача:
1. Найди самую интересную и полезную тему/идею из этих постов для аудитории канала
2. Напиши оригинальный пост на эту тему — НЕ пересказывай чужой пост, а создай свой взгляд
3. Добавь практическую ценность: совет, инсайт, конкретный шаг
4. В конце поста можешь дать ссылку на источник если это уместно

ВАЖНО: Пиши только текст поста, без пояснений. Только готовый текст для публикации."""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def generate_multiple_posts(posts: list, config: dict, count: int = 3) -> list:
    if not posts:
        raise ValueError("Нет постов для анализа")

    channel_desc = config["curator"]["channel_description"]
    voice_block = build_voice_context()
    context = build_context(posts)
    model = config["anthropic"].get("model", "claude-opus-4-6")

    voice_section = f"\n{voice_block}\n" if voice_block else ""

    prompt = f"""Ты — редактор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}
Ниже — свежие посты из других каналов для вдохновения и мониторинга трендов:

{context}

Твоя задача: выбери {count} РАЗНЫЕ темы из этих материалов и напиши по одному посту на каждую.

Требования:
- Каждый пост — на отдельную, непохожую тему
- НЕ пересказывай чужие посты, создавай свой взгляд
- Добавляй практическую ценность: советы, инсайты, конкретные шаги

Ответ строго в формате (без лишнего текста вокруг):

ТЕМА 1: [короткое название темы]
[текст поста]
---
ТЕМА 2: [короткое название темы]
[текст поста]
---
ТЕМА 3: [короткое название темы]
[текст поста]
---"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    results = []
    for block in raw.split("---"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n", 1)
        if len(lines) == 2 and lines[0].startswith("ТЕМА"):
            theme = lines[0].split(":", 1)[-1].strip()
            text = lines[1].strip()
        else:
            theme = f"Вариант {len(results) + 1}"
            text = block
        results.append({"theme": theme, "text": text})

    return results[:count]


VALID_CATEGORIES = {"expert", "personal", "entertaining", "motivational", "promotional", "engaging"}


def classify_posts(posts: list, config: dict) -> list:
    """
    Классифицирует посты по категории контента батчами по 50.
    Возвращает [{id, category}, ...].
    """
    if not posts:
        return []

    model = config["anthropic"].get("model", "claude-opus-4-6")
    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    results = []
    batch_size = 50

    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        lines = []
        for p in batch:
            snippet = (p["text"] or "")[:300].replace("\n", " ")
            lines.append(f'ID:{p["id"]}|{snippet}')
        posts_text = "\n".join(lines)

        prompt = f"""Классифицируй каждый пост по одной из категорий:
- expert (экспертный: советы, инструкции, разборы, гайды, лайфхаки)
- personal (личный: истории из жизни, закулисье, личный опыт)
- entertaining (развлекательный: юмор, ирония, лёгкий контент, мемы)
- motivational (мотивационный: вдохновение, кейсы, результаты, успех)
- promotional (продающий: анонсы, офферы, призывы купить/подписаться)
- engaging (вовлекающий: опросы, вопросы к аудитории, дискуссии)

Посты (формат ID|текст):
{posts_text}

Ответь ТОЛЬКО JSON-массивом без markdown:
[{{"id":N,"category":"..."}}]"""

        try:
            message = client.messages.create(
                model=model, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip().rstrip("```").strip()
            items = json.loads(raw)
            for item in items:
                cat = item.get("category", "").strip()
                if cat in VALID_CATEGORIES:
                    results.append({"id": item["id"], "category": cat})
        except Exception as e:
            logger.error(f"classify_posts batch {i}: {e}")

    return results


def analyze_posts(posts: list, config: dict, top_n: int = 5) -> list:
    """
    Оценивает посты по релевантности каналу через Claude.
    Возвращает топ top_n постов: [{id, channel, text, url, date, views, score, reason}, ...]
    """
    if not posts:
        return []

    channel_desc = config["curator"]["channel_description"]
    model = config["anthropic"].get("model", "claude-opus-4-6")

    # Берём не более 50 постов (топ по просмотрам уже отсортированы в DB)
    sample = posts[:50]
    posts_by_id = {p["id"]: p for p in sample}

    posts_text_lines = []
    for p in sample:
        snippet = (p["text"] or "")[:200].replace("\n", " ")
        posts_text_lines.append(
            f'ID:{p["id"]}|{snippet}'
        )
    posts_text = "\n".join(posts_text_lines)

    prompt = f"""Ты — куратор Telegram-канала.

Описание канала:
{channel_desc[:500]}

Оцени каждый пост (шкала 1-10): релевантность теме канала, практическая ценность.

Посты (формат ID:текст):
{posts_text}

Ответь ТОЛЬКО JSON-массивом, без markdown:
[{{"id":N,"score":1-10,"reason":"1 предложение"}}]"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Убираем возможный markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"analyze_posts: не удалось распарсить JSON: {e}\n{raw[:300]}")
        return []

    # Мерджим score с данными поста
    results = []
    for item in scores:
        post_id = item.get("id")
        post = posts_by_id.get(post_id)
        if not post:
            continue
        results.append({
            "id": post["id"],
            "channel": post["channel"],
            "text": post["text"],
            "url": post.get("url", ""),
            "date": post.get("date", ""),
            "views": post.get("views") or 0,
            "score": int(item.get("score", 0)),
            "reason": item.get("reason", ""),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


CATEGORY_PROMPTS = {
    "expert":       "экспертный пост: совет, инструкция, разбор или лайфхак из своей области",
    "personal":     "личный пост: история из жизни, закулисье, личный опыт или наблюдение",
    "entertaining": "развлекательный пост: лёгкий, ироничный или юмористический контент",
    "motivational": "мотивационный пост: вдохновляющая история, кейс с результатом или инсайт",
    "promotional":  "продающий пост: анонс, оффер или призыв к целевому действию",
    "engaging":     "вовлекающий пост: вопрос к аудитории, мини-опрос или тема для дискуссии",
}

CATEGORY_LABELS = {
    "expert":       "🎓 Экспертный",
    "personal":     "🎭 Личный",
    "entertaining": "😄 Развлекательный",
    "motivational": "💡 Мотивационный",
    "promotional":  "📢 Продающий",
    "engaging":     "🔥 Вовлекающий",
}


def generate_post_by_category(category: str, config: dict) -> str:
    """Генерирует пост нужной категории на основе описания канала и стиля голоса."""
    channel_desc = config["curator"]["channel_description"]
    voice_block = build_voice_context()
    model = config["anthropic"].get("model", "claude-opus-4-6")
    category_desc = CATEGORY_PROMPTS.get(category, "экспертный пост")
    voice_section = f"\n{voice_block}\n" if voice_block else ""

    prompt = f"""Ты — автор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}
Напиши {category_desc} для этого канала.

Требования:
- Длина: 150-400 символов (оптимально для Telegram)
- Стиль: живой, человечный, без AI-штампов
- Только текст поста, без пояснений и заголовков

ЗАПРЕЩЕНО:
- Длинное тире (—) — замени запятой или точкой
- «не только X, но и Y», «это не просто X — это Y»
- Слова: невероятно, потрясающий, революционный, ключевой, уникальный
- Вводные: «важно отметить», «стоит подчеркнуть», «интересно, что»
- Общие финалы: «будущее светлое», «открывает новые горизонты»"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def generate_ab_variants(config: dict, category: str = None) -> tuple:
    """Генерирует 2 варианта поста с разными стилями подачи."""
    channel_desc = config["curator"]["channel_description"]
    voice_block = build_voice_context()
    model = config["anthropic"].get("model", "claude-opus-4-6")
    category_desc = CATEGORY_PROMPTS.get(category, "экспертный пост") if category else "пост для канала"
    voice_section = f"\n{voice_block}\n" if voice_block else ""

    base = f"""Ты — автор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}"""

    no_ai = """
ЗАПРЕЩЕНО:
- Длинное тире (—) — замени запятой или точкой
- «не только X, но и Y», «это не просто X — это Y»
- Слова: невероятно, потрясающий, революционный, ключевой, уникальный
- Вводные: «важно отметить», «стоит подчеркнуть», «интересно, что»
- Общие финалы: «будущее светлое», «открывает новые горизонты»"""

    prompt_a = base + f"""Напиши {category_desc}.
Формат A — конкретика: факты, советы, шаги, цифры. Сухо и по делу.
Длина: 150-400 символов. Только текст поста без пояснений.{no_ai}"""

    prompt_b = base + f"""Напиши {category_desc}.
Формат B — история или личное наблюдение: начни с ситуации или инсайта, раскрой через опыт.
Длина: 150-400 символов. Только текст поста без пояснений.{no_ai}"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    msg_a = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt_a}],
    )
    msg_b = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt_b}],
    )
    return msg_a.content[0].text.strip(), msg_b.content[0].text.strip()


# ─── Форматы постов из дайджестов ────────────────────────────────────────────

POST_FORMATS = {
    "report":   "Репортаж — от первого лица, голос с рынка: «Сообщество сегодня столкнулось с...» — нейтральный, фактический",
    "opinion":  "Мнение эксперта — твоя личная позиция и оценка происходящего, можно полемично",
    "minto":    "Структура Минто: сначала главный тезис, затем 2-3 довода/факта из обсуждений, финальный вывод",
    "story":    "История — конкретный кейс или ситуация из обсуждений → урок или вывод для читателя",
    "trend":    "Тренд — паттерн который повторяется в обсуждениях → что это значит для ютуберов прямо сейчас",
}

FORMAT_LABELS = {
    "report":  "📡 Репортаж",
    "opinion": "💬 Мнение",
    "minto":   "🧱 Минто",
    "story":   "📖 История",
    "trend":   "📈 Тренд",
}

CATEGORY_LABELS_RU = {
    "expert":       "🎓 Экспертный",
    "personal":     "🎭 Личный",
    "entertaining": "😄 Развлекательный",
    "motivational": "💡 Мотивационный",
    "promotional":  "📢 Продающий",
    "engaging":     "🔥 Вовлекающий",
}


def extract_digest_themes(summaries: list, config: dict) -> list:
    """
    Анализирует сводки дайджеста и извлекает ВСЕ горячие темы.
    Возвращает список:
    [{theme, description, heat, suggested_format, suggested_category}, ...]
    heat: hot/warm/cold
    """
    if not summaries:
        return []

    channel_desc = config["curator"].get("channel_description", "")
    model = config["anthropic"].get("model", "claude-opus-4-6")

    # Собираем все сводки в один текст
    digest_text = ""
    for s in summaries:
        digest_text += f"\n\n=== {s['name']} ({s['message_count']} сообщений) ===\n{s['summary']}"

    prompt = f"""Ты — редактор Telegram-канала эксперта по YouTube-бизнесу.

Описание канала автора:
{channel_desc[:600]}

Ниже — сводки обсуждений из тематических чатов за период:
{digest_text[:6000]}

Твоя задача: извлечь ВСЕ горячие темы которые обсуждались.

Для каждой темы определи:
1. Краткое название темы (3-7 слов)
2. Суть в 1-2 предложениях (без упоминания источников, групп, авторов — только суть)
3. Температура: hot (активно обсуждалась много людей), warm (несколько упоминаний), cold (разовое)
4. Лучший формат поста: report / opinion / minto / story / trend
5. Категория контента: expert / personal / entertaining / motivational / promotional / engaging

Форматы:
- report: нейтральный репортаж с рынка
- opinion: личная позиция эксперта
- minto: тезис → доводы → вывод
- story: конкретный кейс → урок
- trend: паттерн → что значит для ютуберов

Категории:
- expert: советы, разборы, инструкции
- personal: личный опыт, наблюдения
- entertaining: лёгкий, ироничный
- motivational: вдохновение, кейсы
- promotional: анонсы, предложения
- engaging: вопросы, дискуссии

Ответь ТОЛЬКО JSON-массивом без markdown:
[
  {{"theme": "...", "description": "...", "heat": "hot|warm|cold", "format": "report|opinion|minto|story|trend", "category": "expert|personal|..."}}
]"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    try:
        themes = json.loads(raw)
        valid_formats = set(POST_FORMATS.keys())
        valid_cats = set(CATEGORY_LABELS_RU.keys())
        result = []
        for t in themes:
            if not t.get("theme") or not t.get("description"):
                continue
            result.append({
                "theme": t["theme"],
                "description": t.get("description", ""),
                "heat": t.get("heat", "warm") if t.get("heat") in ("hot", "warm", "cold") else "warm",
                "format": t.get("format", "report") if t.get("format") in valid_formats else "report",
                "category": t.get("category", "expert") if t.get("category") in valid_cats else "expert",
            })
        return result
    except Exception as e:
        logger.error(f"extract_digest_themes: не удалось распарсить JSON: {e}\n{raw[:300]}")
        return []


def generate_post_from_digest(
    theme: str,
    description: str,
    summaries: list,
    format: str,
    category: str,
    config: dict,
    user_note: str = "",
) -> str:
    """
    Генерирует пост из темы дайджеста.
    Без упоминания источников, групп, авторов — от первого лица.
    user_note — опциональное живое мнение автора (вариант Б).
    """
    channel_desc = config["curator"].get("channel_description", "")
    voice_block = build_voice_context()
    model = config["anthropic"].get("model", "claude-opus-4-6")

    format_instruction = POST_FORMATS.get(format, POST_FORMATS["report"])
    category_instruction = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["expert"])

    voice_section = f"\n{voice_block}\n" if voice_block else ""
    note_section = f"\nЛичное мнение автора которое нужно органично вплести в пост:\n«{user_note}»\n" if user_note else ""

    # Контекст из сводок — только факты, без имён групп
    context_lines = []
    for s in summaries:
        # Берём только текст summary, без имени чата
        context_lines.append(s.get("summary", "")[:800])
    context = "\n\n---\n\n".join(context_lines[:5])

    prompt = f"""Ты — автор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}
Тема поста: {theme}
Суть темы: {description}

Контекст из обсуждений (только факты и тренды, без ссылок на источники):
{context[:3000]}
{note_section}
Напиши {category_instruction} в формате «{format_instruction}».

СТРОГИЕ ПРАВИЛА (обязательные):
- Никаких упоминаний групп, чатов, каналов-конкурентов, имён авторов
- Пиши от первого лица автора канала, как будто это твои наблюдения и выводы
- Вместо «в одном чате написали» — «сообщество всё чаще сталкивается с...»
- Вместо «по данным канала X» — «на практике это выглядит так...»
- Длина: 200-600 символов (оптимально для Telegram)
- Только готовый текст поста, без заголовков и пояснений

ЗАПРЕЩЕНО КАТЕГОРИЧЕСКИ (AI-паттерны):
- Длинное тире (—) — заменяй на запятую, точку или двоеточие
- Конструкции «не только X, но и Y», «это не просто X — это Y»
- Слова: невероятно, потрясающий, революционный, инновационный, ключевой, уникальный
- Вводные: «важно отметить», «стоит подчеркнуть», «интересно, что», «следует отметить»
- Завершение: «будущее выглядит светло», «это открывает новые горизонты», «впереди нас ждёт»
- Безликие атрибуции: «эксперты говорят», «исследования показывают»
- Причастные обороты в хвосте для «глубины»: «подчёркивая важность», «отражая реальность»"""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    return humanize_post(text, config)


def regenerate_post(posts: list, config: dict, feedback: str = "", theme: str = "") -> str:
    if not posts:
        raise ValueError("Нет постов для анализа")

    channel_desc = config["curator"]["channel_description"]
    voice_block = build_voice_context()
    context = build_context(posts)
    model = config["anthropic"].get("model", "claude-opus-4-6")

    voice_section = f"\n{voice_block}\n" if voice_block else ""
    theme_block = f"Тема поста (не меняй её): {theme}\n" if theme else ""
    feedback_block = f"Пожелания по правкам: {feedback}\n" if feedback else ""

    prompt = f"""Ты — редактор Telegram-канала. Вот описание канала:

{channel_desc}
{voice_section}
Материалы для вдохновения:
{context}

{theme_block}{feedback_block}
Напиши новый вариант поста на ту же тему — другой по структуре и подаче, но такой же полезный.
Пиши только готовый текст поста без пояснений."""

    client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
    message = client.messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()
