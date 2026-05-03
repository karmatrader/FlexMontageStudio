"""
curator/bot.py — Telegram-бот для одобрения и публикации постов
"""
import logging
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ConversationHandler,
)
from modules.curator import parser, generator
from modules.db import get_posts

logger = logging.getLogger(__name__)

WAITING_EDIT_TEXT = 1
DRAFTS_COUNT = 3

# Хранилище сессии в памяти
current_session = {
    "posts": [], "drafts": [], "draft": "", "theme": "", "message_id": None,
}


def get_approval_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Опубликовать", callback_data="cur_approve"),
         InlineKeyboardButton("❌ Пропустить", callback_data="cur_reject")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="cur_edit"),
         InlineKeyboardButton("🔄 Перегенерировать", callback_data="cur_regenerate")],
    ])


def get_generate_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Из базы", callback_data="cur_gen_history")],
        [InlineKeyboardButton("🔄 Обновить базу и генерировать", callback_data="cur_gen_fresh")],
    ])


def get_drafts_keyboard(drafts: list):
    keyboard = [
        [InlineKeyboardButton(f"📄 {d['theme']}", callback_data=f"cur_pick_{i}")]
        for i, d in enumerate(drafts)
    ]
    keyboard.append([InlineKeyboardButton("🔄 Другие темы", callback_data="cur_more_themes")])
    return InlineKeyboardMarkup(keyboard)


async def send_draft(bot, draft: str, owner_id: int):
    text = f"📝 *Черновик поста*\n\n{draft}\n\n─────────────────\nСимволов: {len(draft)}"
    msg = await bot.send_message(
        chat_id=owner_id, text=text, parse_mode="Markdown", reply_markup=get_approval_keyboard()
    )
    current_session["message_id"] = msg.message_id
    return msg


async def generate_and_show_drafts(bot, posts: list, source_label: str, config: dict):
    owner_id = config["bot"]["owner_id"]
    current_session["posts"] = posts
    current_session["drafts"] = []
    current_session["draft"] = ""

    await bot.send_message(chat_id=owner_id, text=f"⏳ Генерирую {DRAFTS_COUNT} поста на разные темы ({source_label})...")
    drafts = generator.generate_multiple_posts(posts, config, count=DRAFTS_COUNT)
    current_session["drafts"] = drafts

    for i, d in enumerate(drafts):
        preview = d["text"][:300] + "..." if len(d["text"]) > 300 else d["text"]
        await bot.send_message(
            chat_id=owner_id, text=f"*Тема {i+1}: {d['theme']}*\n\n{preview}", parse_mode="Markdown"
        )

    await bot.send_message(chat_id=owner_id, text="Выбери тему для публикации:", reply_markup=get_drafts_keyboard(drafts))


def build_curator_app(config: dict) -> Application:
    owner_id = int(config["bot"]["owner_id"])

    async def post_init(app: Application):
        await app.bot.set_my_commands([
            BotCommand("parse", "Обновить базу постов из каналов"),
            BotCommand("generate", "Сгенерировать черновики из базы"),
            BotCommand("db", "Статистика базы постов"),
            BotCommand("status", "Статус текущей сессии"),
        ])
        history_count = len(get_posts())
        source_count = len(config["curator"]["source_channels"])
        await app.bot.send_message(
            chat_id=owner_id,
            text=f"🤖 *Curator запущен!*\n\nКаналов для мониторинга: {source_count}\nПостов в базе: {history_count}\n\n"
                 f"/parse — обновить базу\n/generate — сгенерировать черновики\n/db — статистика",
            parse_mode="Markdown",
        )

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return
        await update.message.reply_text(
            "👋 Привет! Я бот-куратор контента.\n\n"
            "/parse — собрать посты из каналов\n"
            "/generate — сгенерировать черновики через Claude\n"
            "/db — статистика базы\n"
            "/status — статус сессии"
        )

    async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return
        history = get_posts()
        if not history:
            await update.message.reply_text("🗄 База пуста. Сначала выполни /parse")
            return
        await update.message.reply_text(
            f"🗄 В базе {len(history)} постов.\n\n⚡ *Из базы* — использовать накопленное\n🔄 *Обновить базу* — спарсить новые и генерировать",
            parse_mode="Markdown", reply_markup=get_generate_keyboard(),
        )

    async def cmd_parse(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return
        await update.message.reply_text("⏳ Собираю посты из каналов...")
        try:
            posts = await parser.fetch_all_posts(config)
            total = len(get_posts())
            await update.message.reply_text(f"✅ Собрано {len(posts)} постов. Всего в базе: {total}")
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")

    async def cmd_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return
        posts = get_posts()
        if not posts:
            await update.message.reply_text("🗄 База постов пуста.")
            return
        by_channel = Counter(p["channel"] for p in posts)
        top_lines = "\n".join(f"  • {ch}: {cnt}" for ch, cnt in by_channel.most_common())
        await update.message.reply_text(
            f"🗄 База постов\n\nВсего: {len(posts)}\n\nКаналы:\n{top_lines}"
        )

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return
        await update.message.reply_text(
            f"📊 *Статус Curator*\n\n"
            f"Постов в сессии: {len(current_session['posts'])}\n"
            f"Вариантов на выборе: {len(current_session['drafts'])}\n"
            f"Черновик выбран: {'да' if current_session['draft'] else 'нет'}\n"
            f"Постов в базе: {len(get_posts())}",
            parse_mode="Markdown",
        )

    async def cb_gen_fresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("⏳ Собираю посты из каналов...")
        try:
            posts = await parser.fetch_all_posts(config)
            if not posts:
                await query.edit_message_text("😕 Новых постов не нашёл. Попробуй позже.")
                return
            await query.edit_message_text(f"✅ Собрал {len(posts)} постов.")
            await generate_and_show_drafts(context.bot, posts, "свежий парсинг", config)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await context.bot.send_message(chat_id=owner_id, text=f"❌ Ошибка: {e}")

    async def cb_gen_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        posts = get_posts()
        if not posts:
            await query.edit_message_text("😕 База пуста. Сначала сделай свежий парсинг.")
            return
        await query.edit_message_text(f"✅ Загружено {len(posts)} постов из базы.")
        try:
            await generate_and_show_drafts(context.bot, posts, "история", config)
        except Exception as e:
            await context.bot.send_message(chat_id=owner_id, text=f"❌ Ошибка: {e}")

    async def cb_more_themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        posts = current_session.get("posts")
        if not posts:
            await query.edit_message_text("❌ Нет данных. Запусти /generate заново.")
            return
        await query.edit_message_text("⏳ Генерирую новые темы...")
        try:
            await generate_and_show_drafts(context.bot, posts, "новая подборка", config)
        except Exception as e:
            await context.bot.send_message(chat_id=owner_id, text=f"❌ Ошибка: {e}")

    async def cb_pick_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        idx = int(query.data.split("_")[-1])
        drafts = current_session.get("drafts", [])
        if idx >= len(drafts):
            await query.edit_message_text("❌ Вариант не найден.")
            return
        chosen = drafts[idx]
        current_session["draft"] = chosen["text"]
        current_session["theme"] = chosen.get("theme", "")
        current_session["drafts"] = []
        await query.edit_message_text(f"✅ Выбрана тема: *{chosen['theme']}*", parse_mode="Markdown")
        await send_draft(context.bot, chosen["text"], owner_id)

    async def cb_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        draft = current_session.get("draft")
        if not draft:
            await query.edit_message_text("❌ Черновик не найден.")
            return
        try:
            await query.edit_message_text("⏳ Обрабатываю...")
            humanized = generator.humanize_post(draft, config)
            interval = config["curator"].get("queue", {}).get("interval_hours", 4)
            from modules.db import get_next_scheduled_at, enqueue_post
            import pytz
            slot_iso = get_next_scheduled_at(interval)
            enqueue_post(humanized, slot_iso)
            # Показать время в МСК
            from datetime import datetime, timezone
            msk = pytz.timezone("Europe/Moscow")
            slot_dt = datetime.fromisoformat(slot_iso).replace(tzinfo=timezone.utc).astimezone(msk)
            slot_str = slot_dt.strftime("%d.%m %H:%M МСК")
            await query.edit_message_text(
                f"✅ *Поставлен в очередь*\n\nПубликация: {slot_str}\n\n{humanized}",
                parse_mode="Markdown"
            )
            current_session["draft"] = ""
            current_session["posts"] = []
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")

    async def cb_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("❌ Черновик отклонён.")
        current_session["draft"] = ""
        current_session["posts"] = []

    async def cb_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("🔄 Генерирую...")
        posts = current_session.get("posts")
        if not posts:
            await query.edit_message_text("❌ Нет данных. Запусти /generate.")
            return
        try:
            await query.edit_message_text("⏳ Перегенерирую черновик...")
            draft = generator.regenerate_post(posts, config, theme=current_session.get("theme", ""))
            current_session["draft"] = draft
            await send_draft(context.bot, draft, owner_id)
        except Exception as e:
            await context.bot.send_message(chat_id=owner_id, text=f"❌ Ошибка: {e}")

    async def cb_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        draft = current_session.get("draft", "")
        await query.edit_message_text(
            f"✏️ Отправь исправленный текст поста.\n\nТекущий черновик:\n\n{draft}\n\n"
            "_(или напиши пожелания, начав с «правки:»)_",
            parse_mode="Markdown",
        )
        return WAITING_EDIT_TEXT

    async def receive_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != owner_id:
            return ConversationHandler.END
        text = update.message.text.strip()
        if text.lower().startswith("правки:"):
            feedback = text[7:].strip()
            posts = current_session.get("posts", [])
            await update.message.reply_text("⏳ Генерирую с учётом правок...")
            try:
                draft = generator.regenerate_post(posts, config, feedback=feedback)
                current_session["draft"] = draft
                await send_draft(context.bot, draft, owner_id)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
        else:
            current_session["draft"] = text
            await update.message.reply_text("✅ Текст обновлён. Вот новый черновик:")
            await send_draft(context.bot, text, owner_id)
        return ConversationHandler.END

    app = Application.builder().token(config["bot"]["token"]).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit, pattern="^cur_edit$")],
        states={WAITING_EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit)]},
        fallbacks=[], per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("parse", cmd_parse))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("db", cmd_db))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cb_approve, pattern="^cur_approve$"))
    app.add_handler(CallbackQueryHandler(cb_reject, pattern="^cur_reject$"))
    app.add_handler(CallbackQueryHandler(cb_regenerate, pattern="^cur_regenerate$"))
    app.add_handler(CallbackQueryHandler(cb_gen_fresh, pattern="^cur_gen_fresh$"))
    app.add_handler(CallbackQueryHandler(cb_gen_history, pattern="^cur_gen_history$"))
    app.add_handler(CallbackQueryHandler(cb_more_themes, pattern="^cur_more_themes$"))
    app.add_handler(CallbackQueryHandler(cb_pick_draft, pattern="^cur_pick_\\d+$"))

    return app


async def notify_owner(bot, config: dict, text: str, event: str = None, user_id: int = 1):
    """Отправляет уведомление владельцу бота.
    event: если указан, проверяет настройки уведомлений пользователя — при disabled пропускает.
    """
    if event:
        try:
            from modules.db import should_notify
            if not should_notify(user_id, event):
                logger.debug(f"notify_owner: событие '{event}' отключено для u{user_id}, пропускаю")
                return
        except Exception:
            pass
    try:
        owner_id = int(config["bot"]["owner_id"])
        await bot.send_message(chat_id=owner_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"notify_owner: не удалось отправить уведомление: {e}")


async def trigger_auto_generation(bot, config: dict, user_id: int = 1):
    owner_id = int(config["bot"]["owner_id"])
    logger.info(f"[AUTO/u{user_id}] Запускаю автоматическую генерацию...")

    # Проверяем наличие Anthropic API key
    api_key = config.get("anthropic", {}).get("api_key", "")
    if not api_key or not api_key.strip():
        logger.warning(f"[AUTO/u{user_id}] Anthropic API key не задан — пропускаю автогенерацию")
        return

    # Проверяем настройки уведомлений для авто-генерации
    try:
        from modules.db import should_notify
        notify_auto = should_notify(user_id, "auto_generation")
    except Exception:
        notify_auto = True

    try:
        new_posts = await parser.fetch_all_posts(config)
        all_posts = get_posts()
        if not all_posts:
            if notify_auto:
                await bot.send_message(chat_id=owner_id, text="⏰ Автозапуск: база пуста и новых постов не найдено.")
            return
        if notify_auto:
            await bot.send_message(
                chat_id=owner_id,
                text=f"⏰ *Автозапуск* — добавлено {len(new_posts)} новых постов, в базе {len(all_posts)}",
                parse_mode="Markdown",
            )
        await generate_and_show_drafts(bot, all_posts, "автозапуск", config)
    except Exception as e:
        logger.error(f"[AUTO/u{user_id}] Ошибка: {e}")
        if notify_auto:
            await bot.send_message(chat_id=owner_id, text=f"❌ Ошибка автогенерации: {e}")
