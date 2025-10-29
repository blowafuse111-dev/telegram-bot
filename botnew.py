import sqlite3
import asyncio
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ----------------- НАСТРОЙКИ -----------------
TOKEN = "7512515821:AAGKP4iysC3YfmZ9zje7NS2VstyazOm0dD0"
ADMIN_IDS = [7817856373, 7822572763]
CHANNEL_ID = "-1003157439297"
BANK_CARD = "2204 1201 3108 2352"
BANK_NAME = "ЮMoney bank"
BOT_NAME = "Убежище Х"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ----------------- БАЗА ДАННЫХ -----------------
def init_db():
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        anon INTEGER,
        status TEXT,
        media_type TEXT,
        media_ids TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount_coins INTEGER,
        price INTEGER,
        status TEXT,
        screenshot TEXT,
        created_at TEXT
    )
    """)

    # Новые таблицы для заявок на удаление и для "Совета администрации"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS delete_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        screenshot TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_council (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        joined_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def register_user(user_id: int, username: str | None):
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user_id, username))
    # обновим username, если изменился
    cur.execute("UPDATE users SET username = ? WHERE id = ? AND (username IS NULL OR username != ?)", (username, user_id, username))
    conn.commit()
    conn.close()

def get_balance(user_id: int) -> int:
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE id=?", (user_id,))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else 0

def update_balance(user_id: int, amount: int):
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user_id, None))
    cur.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_username_from_db(user_id: int) -> str | None:
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id=?", (user_id,))
    res = cur.fetchone()
    conn.close()
    return res[0] if res and res[0] else None

def has_joined_council(user_id: int) -> bool:
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admin_council WHERE user_id=?", (user_id,))
    res = cur.fetchone()
    conn.close()
    return bool(res)

# ----------------- FSM -----------------
class PostState(StatesGroup):
    waiting_for_post = State()

class QuestionState(StatesGroup):
    waiting_for_question = State()
    waiting_for_answer = State()

class BuyCoinsState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_screenshot = State()

class DeletePostState(StatesGroup):
    waiting_for_info = State()

# ----------------- КНОПКИ -----------------
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Предложить пост", callback_data="menu_post")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
    ])

def help_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Правила", callback_data="help_rules")],
        [InlineKeyboardButton(text="👻 Что такое анонимный пост?", callback_data="help_anon")],
        [InlineKeyboardButton(text="💬 Задать вопрос", callback_data="help_question")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

def post_choice_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 От своего имени", callback_data="post_self")],
        [InlineKeyboardButton(text="👻 Анонимно", callback_data="post_anon")],
        [InlineKeyboardButton(text="🗑 Удалить пост (5 Coins)", callback_data="post_delete")],
        [InlineKeyboardButton(text="🏛 Совет администрации", callback_data="admin_council")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

def payment_admin_markup(payment_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"payment_approve_{payment_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"payment_reject_{payment_id}")
        ]
    ])

def moderation_markup(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"moderate_approve_{post_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"moderate_reject_{post_id}")
        ]
    ])

def delete_request_admin_markup(request_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"del_approve_{request_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"del_reject_{request_id}")
        ]
    ])

def balance_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить Coins", callback_data="balance_buy")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

# ----------------- СТАРТ -----------------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    register_user(message.from_user.id, message.from_user.username)
    text = (
        f"👋 <b>Добро пожаловать в {BOT_NAME}!</b>\n\n"
        "Это бот для отправки постов и управления внутренней валютой — <b>Coins</b>.\n"
        "1 Coin = 50 ₽.\n\n"
        "Выберите действие 👇"
    )
    await message.answer(text, reply_markup=main_menu())

# ----------------- МЕНЮ НАЗАД / ПОСТ -----------------
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    await cb.message.edit_text(
        "👋 Главное меню. Выберите действие 👇",
        reply_markup=main_menu()
    )
    await cb.answer()

@dp.callback_query(F.data == "menu_post")
async def menu_post(cb: CallbackQuery):
    await cb.message.edit_text("📝 Как вы хотите опубликовать пост?", reply_markup=post_choice_menu())
    await cb.answer()

# ----------------- СОЗДАНИЕ ПОСТА -----------------
@dp.callback_query(F.data.in_(["post_self", "post_anon"]))
async def post_create(cb: CallbackQuery, state: FSMContext):
    anon = 1 if cb.data == "post_anon" else 0

    # Обновим/зарегистрируем username на всякий случай
    register_user(cb.from_user.id, cb.from_user.username)

    await state.update_data(anon=anon)
    await state.set_state(PostState.waiting_for_post)
    await cb.message.edit_text("✍️ Отправьте текст и/или медиа для поста. (Можно одно фото/видео и подпись)",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                   [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_post")]
                               ]))
    await cb.answer()

@dp.message(PostState.waiting_for_post, F.content_type.in_([ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO]))
async def handle_post(message: Message, state: FSMContext):
    data = await state.get_data()
    anon = data.get("anon", 0)
    created = datetime.now(timezone.utc).isoformat()

    text = message.caption or message.text or ""
    media_type = None
    media_id = None

    if message.photo:
        media_type = "photo"
        media_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        media_id = message.video.file_id

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO posts (user_id, text, anon, status, media_type, media_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message.from_user.id, text, anon, "pending", media_type, media_id, created)
    )
    post_id = cur.lastrowid
    conn.commit()
    conn.close()

    await message.answer("✅ Ваш пост отправлен на модерацию. После одобрения он появится в канале.")
    await state.clear()

    # Уведомление админу: используем username из message (на момент отправки мы его знаем)
    username = message.from_user.username
    pretty_user = f"@{username}" if username else str(message.from_user.id)
    caption_header = f"📢 Новый пост (ID {post_id})\nОт: {pretty_user}\nАноним: {'Да' if anon else 'Нет'}"
    for admin in ADMIN_IDS:
        try:
            if media_type == "photo":
                await bot.send_photo(admin, media_id, caption=f"{caption_header}\n\n{text}", reply_markup=moderation_markup(post_id))
            elif media_type == "video":
                await bot.send_video(admin, media_id, caption=f"{caption_header}\n\n{text}", reply_markup=moderation_markup(post_id))
            else:
                await bot.send_message(admin, f"{caption_header}\n\n{text}", reply_markup=moderation_markup(post_id))
        except Exception:
            # на случай ошибок с отправкой медиа/сообщения одному из админов
            pass

# ----------------- МОДЕРАЦИЯ ПОСТОВ -----------------
@dp.callback_query(F.data.startswith("moderate_approve_"))
async def moderate_approve(cb: CallbackQuery):
    post_id = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, text, anon, media_type, media_ids, status FROM posts WHERE id=?", (post_id,))
    post = cur.fetchone()
    if not post:
        await cb.answer("Пост не найден.", show_alert=True)
        conn.close()
        return

    user_id, text, anon, media_type, media_id, status = post
    if status != "pending":
        await cb.answer("Этот пост уже обработан.", show_alert=True)
        conn.close()
        return

    # Получим username из users (если есть)
    username = get_username_from_db(user_id)
    if username:
        author_text = f"👤 @{username}\n\n"
    else:
        # если username нет — упомянем по ID
        author_text = f"👤 <a href='tg://user?id={user_id}'>пользователь</a>\n\n"

    # Публикуем в канал с учётом анонимности
    if anon:
        channel_text = text or ""
    else:
        channel_text = author_text + (text or "")

    try:
        if media_type == "photo":
            await bot.send_photo(CHANNEL_ID, media_id, caption=channel_text)
        elif media_type == "video":
            await bot.send_video(CHANNEL_ID, media_id, caption=channel_text)
        else:
            await bot.send_message(CHANNEL_ID, channel_text)
    except Exception:
        # если публикация не удалась — информируем админа
        await cb.answer("Ошибка при публикации в канал.", show_alert=True)
        conn.close()
        return

    # Обновляем статус и блокируем кнопки
    cur.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, "✅ Ваш пост одобрен и опубликован в канале!")
    except:
        pass

    # удаляем inline-кнопки у сообщения админа
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Пост опубликован ✅")

@dp.callback_query(F.data.startswith("moderate_reject_"))
async def moderate_reject(cb: CallbackQuery):
    post_id = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, status FROM posts WHERE id=?", (post_id,))
    post = cur.fetchone()
    if not post:
        await cb.answer("Пост не найден.", show_alert=True)
        conn.close()
        return

    user_id, status = post
    if status != "pending":
        await cb.answer("Этот пост уже обработан.", show_alert=True)
        conn.close()
        return

    cur.execute("UPDATE posts SET status='rejected' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, "❌ Ваш пост отклонён модератором.")
    except:
        pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Пост отклонён ❌")

# ----------------- УДАЛЕНИЕ ПОСТА (ЗА 5 COINS) -----------------
@dp.callback_query(F.data == "post_delete")
async def post_delete_start(cb: CallbackQuery, state: FSMContext):
    register_user(cb.from_user.id, cb.from_user.username)
    bal = get_balance(cb.from_user.id)
    cost = 5
    if bal < cost:
        await cb.message.edit_text(
            f"⚠️ У вас недостаточно средств для подачи заявки на удаление.\n\nБаланс: {bal} Coins\nНе хватает: {cost - bal} Coins",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_post")]])
        )
        await cb.answer()
        return

    await state.set_state(DeletePostState.waiting_for_info)
    await cb.message.edit_text(
        "🗑 Отправьте ссылку на пост или скриншот поста, который хотите удалить.\n\n"
        "После отправки заявка пойдёт администраторам. Оплата (5 Coins) будет списана только после подтверждения админом.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_post")]
        ])
    )
    await cb.answer()

@dp.message(DeletePostState.waiting_for_info, F.content_type.in_([ContentType.TEXT, ContentType.PHOTO]))
async def handle_delete_request(message: Message, state: FSMContext):
    # Требуем, чтобы пользователь был зарегистрирован
    register_user(message.from_user.id, message.from_user.username)
    text = message.text or ""
    screenshot = message.photo[-1].file_id if message.photo else None
    created = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO delete_requests (user_id, message, screenshot, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (message.from_user.id, text, screenshot, "pending", created))
    rid = cur.lastrowid
    conn.commit()
    conn.close()

    await message.answer("✅ Ваша заявка на удаление отправлена администраторам. Ожидайте проверки.")
    await state.clear()

    # Уведомление админу
    username = message.from_user.username
    pretty_user = f"@{username}" if username else str(message.from_user.id)
    caption = (
        f"🗑 <b>Заявка на удаление поста</b>\n\n"
        f"👤 Пользователь: {pretty_user}\n"
        f"🆔 ID заявки: {rid}\n\n"
        f"{text}\n\n"
        "Пожалуйста, вручную удалите пост в канале, затем нажмите ✅ чтобы подтвердить удаление и списать 5 Coins, "
        "или ❌ чтобы отклонить заявку."
    )
    for admin in ADMIN_IDS:
        try:
            if screenshot:
                await bot.send_photo(admin, screenshot, caption=caption, reply_markup=delete_request_admin_markup(rid))
            else:
                await bot.send_message(admin, caption, reply_markup=delete_request_admin_markup(rid))
        except:
            pass

# Обработка решения админа по заявке на удаление
@dp.callback_query(F.data.startswith("del_approve_"))
async def approve_delete(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("У вас нет прав.", show_alert=True)
        return

    rid = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, status FROM delete_requests WHERE id=?", (rid,))
    row = cur.fetchone()
    if not row:
        await cb.answer("Заявка не найдена.", show_alert=True)
        conn.close()
        return
    user_id, status = row
    if status != "pending":
        await cb.answer("Заявка уже обработана.", show_alert=True)
        conn.close()
        return

    # списываем 5 Coins (если вдруг баланс изменился — проверяем)
    bal = get_balance(user_id)
    cost = 5
    if bal < cost:
        # обновим статус как rejected из-за недостатка средств
        cur.execute("UPDATE delete_requests SET status='rejected' WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        try:
            await bot.send_message(user_id, f"❌ Не удалось удалить пост — у вас недостаточно средств (нужно {cost} Coins).")
        except:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        await cb.answer("Пользователь не имеет достаточного баланса — заявка отклонена.")
        return

    update_balance(user_id, -cost)
    cur.execute("UPDATE delete_requests SET status='approved' WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, "✅ Ваша заявка на удаление поста одобрена. С вас списано 5 Coins.")
    except:
        pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Заявка на удаление одобрена ✅")

@dp.callback_query(F.data.startswith("del_reject_"))
async def reject_delete(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("У вас нет прав.", show_alert=True)
        return

    rid = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, status FROM delete_requests WHERE id=?", (rid,))
    row = cur.fetchone()
    if not row:
        await cb.answer("Заявка не найдена.", show_alert=True)
        conn.close()
        return
    user_id, status = row
    if status != "pending":
        await cb.answer("Заявка уже обработана.", show_alert=True)
        conn.close()
        return

    cur.execute("UPDATE delete_requests SET status='rejected' WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, "❌ Ваша заявка на удаление поста отклонена.")
    except:
        pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Заявка отклонена ❌")

# ----------------- СОВЕТ АДМИНИСТРАЦИИ (ВСТУПЛЕНИЕ ЗА 20 COINS) -----------------
@dp.callback_query(F.data == "admin_council")
async def admin_council_info(cb: CallbackQuery):
    text = (
        "🏛 <b>Совет администрации Убежища</b>\n\n"
        "Совет администрации убежища — это то место, где ты сможешь вершить дела! "
        "Тебе открываются «секретно-новые» эксклюзивные возможности, в том числе взаимодействие с постами, "
        "создавать интриги, влиять на общество и многое другое.. Такое, что никому не стоит знать об этом.\n\n"
        "💰 Стоимость прохода: 20 Coins"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Вступить (20 Coins)", callback_data="join_council")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_post")]
    ])
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()

@dp.callback_query(F.data == "join_council")
async def join_council(cb: CallbackQuery):
    user_id = cb.from_user.id
    # Проверим, не вступал ли уже
    if has_joined_council(user_id):
        await cb.message.edit_text(
            "Вы уже являетесь участником Совета администрации.\n\n"
            "🔗 Ссылка: https://t.me/sovet_ubezhishe_bot\n"
            "🧩 Код доступа: <code>7351808</code>",
            reply_markup=post_choice_menu()
        )
        await cb.answer("Вы уже в Совете.")
        return

    bal = get_balance(user_id)
    cost = 20
    if bal < cost:
        await cb.message.edit_text(
            f"⚠️ У вас недостаточно средств для вступления.\nБаланс: {bal} Coins\nНе хватает: {cost - bal} Coins",
            reply_markup=post_choice_menu()
        )
        await cb.answer()
        return

    # Списываем и записываем факт вступления
    update_balance(user_id, -cost)
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admin_council (user_id, joined_at) VALUES (?, ?)",
                (user_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

    await cb.message.edit_text(
        "🎉 Добро пожаловать в Совет администрации!\n\n"
        "Твоя анонимность защищена — вы регистрируетесь под вымышленным ником в системе.\n\n"
        "🔗 Ссылка: https://t.me/sovet_ubezhishe_bot\n"
        "🧩 Код доступа: <code>7351808</code>",
        reply_markup=post_choice_menu()
    )
    await cb.answer("Вступление успешно ✅")

# ----------------- ПОМОЩЬ -----------------
@dp.callback_query(F.data == "menu_help")
async def menu_help(cb: CallbackQuery):
    help_text = "📖 Раздел помощи. Выберите пункт ниже:"
    await cb.message.edit_text(help_text, reply_markup=help_menu())
    await cb.answer()

@dp.callback_query(F.data == "help_rules")
async def help_rules(cb: CallbackQuery):
    rules_text = (
        "📋 <b>Правила Убежища</b>\n\n"
        "— Будь добрым и уважай других.\n\n"
        "🚫 <b>Запрещено:</b>\n"
        "• Экстремизм, призывы к насилию, дискриминация.\n"
        "• Порнография, реклама наркотиков, азарт.\n"
        "• Публикация личных данных без согласия."
    )
    await cb.message.edit_text(rules_text, reply_markup=help_menu())
    await cb.answer()

@dp.callback_query(F.data == "help_anon")
async def help_anon(cb: CallbackQuery):
    await cb.message.edit_text(
        "👻 <b>Анонимный пост</b>\nПолностью анонимная публикация. Никто никогда не узнает автора поста.",
        reply_markup=help_menu()
    )
    await cb.answer()

@dp.callback_query(F.data == "help_question")
async def help_question(cb: CallbackQuery, state: FSMContext):
    await state.set_state(QuestionState.waiting_for_question)
    await cb.message.edit_text("💬 Введите ваш вопрос — админ ответит вам лично.")
    await cb.answer()

# ----------------- ВОПРОСЫ -----------------
@dp.message(QuestionState.waiting_for_question)
async def send_question(message: Message, state: FSMContext):
    register_user(message.from_user.id, message.from_user.username)
    text = f"📩 Вопрос от @{message.from_user.username or message.from_user.id}:\n\n{message.text}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Ответить пользователю", callback_data=f"answer_question_{message.from_user.id}")]
            ]))
        except:
            pass
    await message.answer("✅ Ваш вопрос отправлен администратору.")
    await state.clear()

@dp.callback_query(F.data.startswith("answer_question_"))
async def answer_question(cb: CallbackQuery, state: FSMContext):
    # админ нажал "Ответить пользователю"
    user_id = int(cb.data.split("_")[-1])
    await cb.message.answer(f"💬 Введите ответ пользователю (ID {user_id}):")
    # сохраним в FSM данные по админу, чтобы его ответ точно отправился нужному пользователю
    await state.update_data(reply_to_user=user_id)
    await state.set_state(QuestionState.waiting_for_answer)
    await cb.answer()

@dp.message(QuestionState.waiting_for_answer)
async def send_answer_to_user(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_to_user")
    if not user_id:
        await message.answer("❌ Не удалось определить пользователя.")
        await state.clear()
        return

    try:
        await bot.send_message(user_id, f"💬 Ответ от администратора:\n\n{message.text}")
        await message.answer("✅ Ответ отправлен пользователю.")
    except:
        await message.answer("❌ Не удалось отправить сообщение пользователю.")
    await state.clear()

# ----------------- БАЛАНС / ПОКУПКА COINS -----------------
@dp.callback_query(F.data == "menu_balance")
async def menu_balance(cb: CallbackQuery, state: FSMContext):
    register_user(cb.from_user.id, cb.from_user.username)
    bal = get_balance(cb.from_user.id)
    text = f"💎 Ваш баланс: <b>{bal} Coins</b>"
    await cb.message.edit_text(text, reply_markup=balance_menu())
    await cb.answer()

@dp.callback_query(F.data == "balance_buy")
async def balance_buy(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите количество Coins для покупки (1 Coin = 50 ₽, максимум 100):")
    await state.set_state(BuyCoinsState.waiting_for_amount)
    await cb.answer()

@dp.message(BuyCoinsState.waiting_for_amount)
async def handle_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except:
        return await message.answer("Введите число от 1 до 100.")

    if amount < 1 or amount > 100:
        return await message.answer("⚠️ Можно купить от 1 до 100 Coins.")

    price = amount * 50
    await state.update_data(amount_coins=amount, price=price)
    await state.set_state(BuyCoinsState.waiting_for_screenshot)

    await message.answer(
        f"💳 <b>Оплата</b>\n\n"
        f"Сумма: <b>{price} ₽</b>\n"
        f"Количество: <b>{amount} Coins</b>\n\n"
        f"Переведите деньги на карту:\n<code>{BANK_CARD}</code> — {BANK_NAME}\n"
        "В комментарии укажите свой @username или ID.\n\n"
        "📸 После перевода отправьте скриншот сюда."
    )

@dp.message(BuyCoinsState.waiting_for_screenshot, F.photo)
async def handle_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount_coins", 0)
    price = data.get("price", 0)
    screenshot_id = message.photo[-1].file_id
    created = datetime.now(timezone.utc).isoformat()

    # Сохраняем платёж в базе
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO payments (user_id, amount_coins, price, status, screenshot, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (message.from_user.id, amount, price, "pending", screenshot_id, created)
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    # Сообщение пользователю
    await message.answer("✅ Ваш запрос принят на проверку. Ожидайте подтверждения администратора.")
    await state.clear()

    # Уведомление админу (красивое)
    markup = payment_admin_markup(pid)
    username = message.from_user.username
    pretty_user = f"@{username}" if username else str(message.from_user.id)
    caption = (
        f"💰 <b>Новый платёж</b>\n\n"
        f"👤 Пользователь: {pretty_user}\n"
        f"💎 Coins: {amount}\n"
        f"💳 Сумма: {price} ₽\n"
        f"🆔 ID платежа: {pid}\n\n"
        f"Нажмите ✅ чтобы подтвердить и зачислить Coins, или ❌ чтобы отклонить."
    )
    for admin in ADMIN_IDS:
        try:
            await bot.send_photo(admin, screenshot_id, caption=caption, reply_markup=markup)
        except:
            # если отправка фото не удалась — отправим текст+ссылку
            try:
                await bot.send_message(admin, caption, reply_markup=markup)
            except:
                pass

# ----------------- АДМИН: ПОДТВЕРЖДЕНИЕ/ОТКЛОНЕНИЕ ПЛАТЕЖА -----------------
@dp.callback_query(F.data.startswith("payment_approve_"))
async def payment_approve(cb: CallbackQuery):
    pid = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, amount_coins, status FROM payments WHERE id=?", (pid,))
    payment = cur.fetchone()
    if not payment:
        await cb.answer("Платёж не найден.", show_alert=True)
        conn.close()
        return

    user_id, amount, status = payment
    if status != "pending":
        await cb.answer("Этот платёж уже обработан.", show_alert=True)
        conn.close()
        return

    # Начисляем Coins и обновляем статус
    update_balance(user_id, amount)
    cur.execute("UPDATE payments SET status='approved' WHERE id=?", (pid,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, f"✅ Ваш платёж подтвержден! Вам зачислено {amount} Coins.")
    except:
        pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Платёж подтверждён ✅")

@dp.callback_query(F.data.startswith("payment_reject_"))
async def payment_reject(cb: CallbackQuery):
    pid = int(cb.data.split("_")[-1])
    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, status FROM payments WHERE id=?", (pid,))
    payment = cur.fetchone()
    if not payment:
        await cb.answer("Платёж не найден.", show_alert=True)
        conn.close()
        return

    user_id, status = payment
    if status != "pending":
        await cb.answer("Этот платёж уже обработан.", show_alert=True)
        conn.close()
        return

    cur.execute("UPDATE payments SET status='rejected' WHERE id=?", (pid,))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(user_id, "❌ Ваш запрос отклонен.")
    except:
        pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    await cb.answer("Платёж отклонён ❌")

# ----------------- АДМИН: /addcoin -----------------
@dp.message(Command("addcoin"))
async def add_coin_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ У вас нет прав на выполнение этой команды.")
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        amount = int(parts[2])
    except (IndexError, ValueError):
        return await message.answer("Использование: /addcoin <user_id> <amount>")

    update_balance(user_id, amount)
    await message.answer(f"✅ Пользователю {user_id} добавлено {amount} Coins.")
    try:
        await bot.send_message(user_id, f"💎 Вам начислено {amount} Coins администратором.")
    except:
        pass

# ----------------- ЗАПУСК -----------------
async def main():
    init_db()
    print("🤖 Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
