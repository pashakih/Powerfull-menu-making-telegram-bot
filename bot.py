import logging
import sqlite3
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode

# Поддержка загрузки переменных окружения из .env (опционально)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Настройка логирования
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Конфигурация: замените TOKEN на реальный токен перед запуском или поставьте в .env
TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
DB_NAME = "multichef.db"

# Простая проверка доступа для регистрации повара
SECRET_WORD = "chef"
CHEF_PASSWORD = "bsqkl"

# Состояния для ConversationHandler'ов (каждое состояние — целое число)
REG_CHECK_PHRASE, REG_CHECK_PASSWORD = range(2)
ADD_DISH_CATEGORY, ADD_DISH_NAME = range(2, 4)
CHOOSE_CHEF, CHOOSE_CATEGORY, CHOOSE_DISH, TYPE_QUANTITY, TYPE_ADDRESS = range(4, 9)
DELETE_ITEM_ID = 9


def init_db():
    """
    Инициализация SQLite базы: создаёт таблицы, если их нет.
    Таблицы: CHEFS (повара), MENU (блюда), ORDERS (заказы).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS CHEFS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT,
            username TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS MENU (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chef_id INTEGER,
            category TEXT,
            dish_name TEXT,
            FOREIGN KEY(chef_id) REFERENCES CHEFS(user_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ORDERS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            chef_id INTEGER,
            dish_name TEXT,
            quantity INTEGER,
            address TEXT,
            status TEXT,
            created_at TEXT,
            FOREIGN KEY(chef_id) REFERENCES CHEFS(user_id)
        )
        """
    )

    conn.commit()
    conn.close()


# -------------------- ФУНКЦИИ РАБОТЫ С БД --------------------
def db_register_chef(user_id, name, username):
    """Добавить повара в таблицу CHEFS. Возвращает True при успехе."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO CHEFS (user_id, name, username) VALUES (?, ?, ?)", (user_id, name, username))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Уже зарегистрирован
        return False
    finally:
        conn.close()


def db_is_chef(user_id):
    """Проверяет, зарегистрирован ли пользователь как повар."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM CHEFS WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None


def db_add_dish(chef_id, category, dish_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO MENU (chef_id, category, dish_name) VALUES (?, ?, ?)", (chef_id, category, dish_name))
    conn.commit()
    conn.close()


def db_get_all_chefs():
    """Возвращает список зарегистрированных поваров как (user_id, name)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM CHEFS")
    rows = cursor.fetchall()
    conn.close()
    return rows


def db_get_chef_categories(chef_id):
    """Список уникальных категорий меню для повара."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM MENU WHERE chef_id = ?", (chef_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_get_dishes_by_category(chef_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT dish_name FROM MENU WHERE chef_id = ? AND category = ?", (chef_id, category))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_get_full_menu_with_ids(chef_id):
    """Возвращает меню повара с id записей: [(id, category, dish_name), ...]"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category, dish_name FROM MENU WHERE chef_id = ? ORDER BY category, id", (chef_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def db_delete_menu_item(item_id, chef_id):
    """Удаляет запись меню по id и проверяет принадлежность повару."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM MENU WHERE id = ? AND chef_id = ?", (item_id, chef_id))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def db_save_order(client_id, chef_id, dish_name, quantity, address):
    """Сохраняет новый заказ и возвращает его id."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    dt = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        """
        INSERT INTO ORDERS (client_id, chef_id, dish_name, quantity, address, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (client_id, chef_id, dish_name, quantity, address, 'New', dt),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id


def db_get_chef_orders(chef_id):
    """Активные заказы повара (New, In Progress)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, dish_name, quantity, address, status, created_at
        FROM ORDERS
        WHERE chef_id = ? AND status IN ('New', 'In Progress')
        ORDER BY id DESC
        """,
        (chef_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def db_get_client_orders(client_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, dish_name, quantity, status, address
        FROM ORDERS
        WHERE client_id = ? ORDER BY id DESC LIMIT 10
        """,
        (client_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def db_update_status(order_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE ORDERS SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()


def db_get_order_details(order_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, chef_id, dish_name, status FROM ORDERS WHERE id = ?", (order_id,))
    res = cursor.fetchone()
    conn.close()
    return res


def db_delete_completed_orders(chef_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM ORDERS
        WHERE chef_id = ? AND status IN ('Completed', 'Cancelled')
        """,
        (chef_id,),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


# -------------------- HANDLERS (логика бота) --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Стартовое сообщение: различаем клиента и повара."""
    user = update.effective_user
    if db_is_chef(user.id):
        await update.message.reply_text(
            f"Привет, <b>{user.first_name}</b>! Вы — повар. Используйте /menu_chef.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"Привет, <b>{user.first_name}</b>! Вы — клиент. Используйте /menu_client.", parse_mode=ParseMode.HTML
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего ConversationHandler'а и очистка временных данных пользователя."""
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# Регистрация повара: две проверки — секретная фраза и пароль
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db_is_chef(update.effective_user.id):
        await update.message.reply_text("Вы уже зарегистрированы как повар.")
        return ConversationHandler.END
    await update.message.reply_text("Введите секретное слово:", reply_markup=ReplyKeyboardRemove())
    return REG_CHECK_PHRASE


async def reg_check_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == SECRET_WORD:
        await update.message.reply_text("Верно. Введите пароль:")
        return REG_CHECK_PASSWORD
    await update.message.reply_text("Неверное секретное слово. Попробуйте снова или /cancel")
    return REG_CHECK_PHRASE


async def reg_check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == CHEF_PASSWORD:
        user = update.effective_user
        db_register_chef(user.id, user.first_name, user.username)
        await update.message.reply_text("✅ Вы зарегистрированы как повар. Используйте /menu_chef")
        return ConversationHandler.END
    await update.message.reply_text("Неверный пароль. Попробуйте ещё раз или /cancel")
    return REG_CHECK_PASSWORD


# -------------------- Меню повара (управление меню и заказами) --------------------
async def menu_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_is_chef(update.effective_user.id):
        await update.message.reply_text("Доступно только для поваров.")
        return

    keyboard = [
        ["➕ Добавить блюдо", "🗑 Удалить блюдо"],
        ["📋 Мои заказы"],
        ["📂 Моё меню (список)", "🗑 Удалить архив (выполненные)"]
    ]
    await update.message.reply_text(
        "👨‍🍳 Кабинет повара:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode=ParseMode.HTML
    )


async def add_dish_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Шаг 1: введите категорию блюда.", reply_markup=ReplyKeyboardRemove())
    return ADD_DISH_CATEGORY


async def add_dish_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text
    context.user_data['new_category'] = category
    await update.message.reply_text(f"Категория: <b>{category}</b>. Теперь введите название блюда:", parse_mode=ParseMode.HTML)
    return ADD_DISH_NAME


async def add_dish_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dish_name = update.message.text
    category = context.user_data['new_category']
    chef_id = update.effective_user.id
    db_add_dish(chef_id, category, dish_name)
    await update.message.reply_text(f"✅ Добавлено: {category} / {dish_name}", parse_mode=ParseMode.HTML)
    await menu_chef(update, context)
    return ConversationHandler.END


async def delete_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список меню повара с ID для удаления записи."""
    chef_id = update.effective_user.id
    menu_items = db_get_full_menu_with_ids(chef_id)
    if not menu_items:
        await update.message.reply_text("Ваше меню пусто.")
        return ConversationHandler.END

    msg = "Ваше меню (ID для удаления):\n\n"
    current_cat = None
    for item_id, cat, dish in menu_items:
        if cat != current_cat:
            msg += f"\n{cat}\n"
            current_cat = cat
        msg += f" (ID: {item_id}) {dish}\n"

    msg += "\nВведите ID блюда для удаления:"
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return DELETE_ITEM_ID


async def delete_item_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    try:
        item_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите числовой ID.")
        return DELETE_ITEM_ID

    count = db_delete_menu_item(item_id, chef_id)
    if count > 0:
        await update.message.reply_text(f"✅ Блюдо с ID {item_id} удалено.")
    else:
        await update.message.reply_text("Блюдо не найдено или не принадлежит вам.")
    return ConversationHandler.END


async def show_my_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_get_full_menu_with_ids(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Меню пусто.")
        return

    msg = "Ваше меню:\n\n"
    current_cat = None
    for item_id, cat, dish in rows:
        if cat != current_cat:
            msg += f"{cat}\n"
            current_cat = cat
        msg += f" (ID: {item_id}) {dish}\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def chef_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders = db_get_chef_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("Активных заказов нет.")
        return

    msg = "Активные заказы:\n\n"
    for o in orders:
        msg += f"ID {o[0]} | {o[1]} x{o[2]}\nАдрес: {o[3]}\nСтатус: {o[4]}\nКоманды: /cook_{o[0]} | /finish_{o[0]}\n---\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def chef_delete_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет старые заказы со статусами Completed/Cancelled для данного повара."""
    chef_id = update.effective_user.id
    if not db_is_chef(chef_id):
        return
    count = db_delete_completed_orders(chef_id)
    if count > 0:
        await update.message.reply_text(f"Удалено {count} записей архива.")
    else:
        await update.message.reply_text("Архив пуст.")


async def order_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команд смены статуса заказа: /cook_<id> или /finish_<id>"""
    if not db_is_chef(update.effective_user.id):
        return
    cmd = update.message.text
    action, order_id_str = cmd.split('_')
    order_id = int(order_id_str)
    new_status = "In Progress" if "cook" in action else "Completed"
    status_rus = "Готовится" if "cook" in action else "Выполнен"
    db_update_status(order_id, new_status)
    await update.message.reply_text(f"Заказ {order_id}: {status_rus}")

    details = db_get_order_details(order_id)
    if details:
        try:
            await context.bot.send_message(chat_id=details[0], text=f"Статус заказа {details[2]}: {status_rus}")
        except Exception:
            pass


# -------------------- Клиентская часть --------------------
async def menu_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🍕 Сделать заказ"], ["📜 Мои заказы"]]
    await update.message.reply_text("Меню клиента:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))


async def client_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders = db_get_client_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("У вас пока нет заказов.")
        return

    msg = "Ваши последние заказы:\n\n"
    for o in orders:
        status = o[3]
        msg += f"ID {o[0]} | {o[1]} x{o[2]}\nАдрес: {o[4]}\nСтатус: {status}\n"
        if status == 'New':
            msg += f"Отменить: /cancel_order_{o[0]}\n"
        msg += "---\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def client_cancel_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text
    order_id = int(cmd.split('_')[-1])
    details = db_get_order_details(order_id)
    if not details or details[0] != update.effective_user.id:
        await update.message.reply_text("Ошибка доступа к заказу.")
        return
    if details[3] != 'New':
        await update.message.reply_text("Заказ уже в обработке; отмена невозможна.")
        return

    db_update_status(order_id, "Cancelled")
    await update.message.reply_text(f"Заказ {order_id} отменён.")
    try:
        await context.bot.send_message(chat_id=details[1], text=f"Клиент отменил заказ {order_id}: {details[2]}")
    except Exception:
        pass


# -------------------- Процесс оформления заказа --------------------
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chefs = db_get_all_chefs()
    if not chefs:
        await update.message.reply_text("Поваров пока нет.")
        return ConversationHandler.END

    # Запоминаем отображение имя->id для пользователя
    context.user_data['chefs_map'] = {c[1]: c[0] for c in chefs}
    keyboard = [[c[1]] for c in chefs]
    await update.message.reply_text("Выберите повара:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return CHOOSE_CHEF


async def order_choose_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_name = update.message.text
    chefs_map = context.user_data.get('chefs_map', {})
    if chef_name not in chefs_map:
        await update.message.reply_text("Выберите повара через кнопку.")
        return CHOOSE_CHEF

    chef_id = chefs_map[chef_name]
    context.user_data['selected_chef_id'] = chef_id
    categories = db_get_chef_categories(chef_id)
    if not categories:
        await update.message.reply_text("У выбранного повара пустое меню.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    keyboard = [[c] for c in categories]
    await update.message.reply_text("Выберите категорию:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return CHOOSE_CATEGORY


async def order_choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text
    chef_id = context.user_data['selected_chef_id']
    dishes = db_get_dishes_by_category(chef_id, category)
    if not dishes:
        await update.message.reply_text("В этой категории нет блюд. Выберите другую.")
        return CHOOSE_CATEGORY

    context.user_data['selected_category'] = category
    keyboard = [[d] for d in dishes]
    await update.message.reply_text("Выберите блюдо:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return CHOOSE_DISH


async def order_choose_dish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['selected_dish'] = update.message.text
    await update.message.reply_text("Введите количество (числом):", reply_markup=ReplyKeyboardRemove())
    return TYPE_QUANTITY


async def order_ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите корректное положительное число.")
        return TYPE_QUANTITY

    context.user_data['selected_qty'] = qty
    await update.message.reply_text("Напишите адрес/место доставки:")
    return TYPE_ADDRESS


async def order_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text
    client_id = update.effective_user.id
    chef_id = context.user_data['selected_chef_id']
    dish_name = context.user_data['selected_dish']
    qty = context.user_data['selected_qty']

    order_id = db_save_order(client_id, chef_id, dish_name, qty, address)
    await update.message.reply_text(f"✅ Заказ #{order_id} оформлен. Адрес: {address}", reply_markup=ReplyKeyboardRemove())

    # Уведомление повара
    try:
        await context.bot.send_message(chat_id=chef_id, text=f"Новый заказ #{order_id}: {dish_name} x{qty}. Адрес: {address}")
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Conversation для регистрации повара
    conv_reg = ConversationHandler(
        entry_points=[CommandHandler("register_chef", reg_start)],
        states={
            REG_CHECK_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_phrase)],
            REG_CHECK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation для добавления блюда
    conv_add_dish = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^➕ Добавить блюдо$"), add_dish_start)],
        states={
            ADD_DISH_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_category_handler)],
            ADD_DISH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_name_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation для удаления блюда
    conv_delete_dish = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🗑 Удалить блюдо$"), delete_item_start)],
        states={DELETE_ITEM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_item_finish)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation для оформления заказа клиентом
    conv_order = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🍕 Сделать заказ$"), order_start)],
        states={
            CHOOSE_CHEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_chef)],
            CHOOSE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_category)],
            CHOOSE_DISH: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_dish)],
            TYPE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_ask_address)],
            TYPE_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_finish)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Регистрируем обработчики
    app.add_handler(conv_reg)
    app.add_handler(conv_add_dish)
    app.add_handler(conv_delete_dish)
    app.add_handler(conv_order)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu_client", menu_client))
    app.add_handler(CommandHandler("menu_chef", menu_chef))

    app.add_handler(MessageHandler(filters.Regex(r"^📋 Мои заказы$"), chef_view_orders))
    app.add_handler(MessageHandler(filters.Regex(r"^📂 Моё меню \(список\)$"), show_my_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^📜 Мои заказы$"), client_view_orders))
    app.add_handler(MessageHandler(filters.Regex(r"^🗑 Удалить архив \(выполненные\)$"), chef_delete_archive))

    # Динамические команды для смены статуса и отмены заказа
    app.add_handler(MessageHandler(filters.Regex(r"^/(cook|finish)_\d+$"), order_status_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/cancel_order_\d+$"), client_cancel_order_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
