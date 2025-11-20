import logging
import sqlite3
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

# --- 1. НАСТРОЙКИ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

TOKEN = "8556744063:AAGX0H1SkCxFa3Sl6mIZp1J9BuVCXOJ8PbQ" 
DB_NAME = "multichef.db" # Используйте новое имя для новой структуры
SECRET_WORD = "chef"
CHEF_PASSWORD = "bsqkl" 

# --- 2. СОСТОЯНИЯ ДИАЛОГОВ ---
REG_CHECK_PHRASE, REG_CHECK_PASSWORD = range(2)

# Добавление блюда: Категория -> Название
ADD_DISH_CATEGORY, ADD_DISH_NAME = range(2, 4)

# Заказ: Повар -> Категория -> Блюдо -> Количество -> Адрес
CHOOSE_CHEF, CHOOSE_CATEGORY, CHOOSE_DISH, TYPE_QUANTITY, TYPE_ADDRESS = range(4, 9)

# Удаление:
DELETE_ITEM_ID = 9 

# --- 3. БАЗА ДАННЫХ ---

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS CHEFS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT,
            username TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS MENU (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chef_id INTEGER,
            category TEXT,
            dish_name TEXT,
            FOREIGN KEY(chef_id) REFERENCES CHEFS(user_id)
        )
    """)
    
    cursor.execute("""
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
    """)
    conn.commit()
    conn.close()

# --- Helpers БД ---

def db_register_chef(user_id, name, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO CHEFS (user_id, name, username) VALUES (?, ?, ?)", (user_id, name, username))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def db_is_chef(user_id):
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM CHEFS")
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_get_chef_categories(chef_id):
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
    """Для просмотра всего меню поваром с ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category, dish_name FROM MENU WHERE chef_id = ? ORDER BY category, id", (chef_id,))
    rows = cursor.fetchall() 
    conn.close()
    return rows

def db_delete_menu_item(item_id, chef_id):
    """Удаляет блюдо по ID, проверяя, что оно принадлежит повару."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM MENU WHERE id = ? AND chef_id = ?", (item_id, chef_id))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def db_save_order(client_id, chef_id, dish_name, quantity, address):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    dt = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("""
        INSERT INTO ORDERS (client_id, chef_id, dish_name, quantity, address, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (client_id, chef_id, dish_name, quantity, address, 'New', dt))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def db_get_chef_orders(chef_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, dish_name, quantity, address, status, created_at 
        FROM ORDERS 
        WHERE chef_id = ? AND status IN ('New', 'In Progress')
        ORDER BY id DESC
    """, (chef_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_get_client_orders(client_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, dish_name, quantity, status, address 
        FROM ORDERS 
        WHERE client_id = ? ORDER BY id DESC LIMIT 10
    """, (client_id,))
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
    cursor.execute("""
        DELETE FROM ORDERS 
        WHERE chef_id = ? AND status IN ('Completed', 'Cancelled')
    """, (chef_id,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

# --- 4. ОБЩИЕ ФУНКЦИИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if db_is_chef(user.id):
        await update.message.reply_text(f"Привет, Кых <b>{user.first_name}</b>! 👨‍🍳\nИди в /menu_chef.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"Привет, <b>{user.first_name}</b>! 🍕\nЖми /menu_client.", parse_mode=ParseMode.HTML)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- 5. РЕГИСТРАЦИЯ ПОВАРА ---

async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db_is_chef(update.effective_user.id):
        await update.message.reply_text("Вы уже повар!")
        return ConversationHandler.END
    await update.message.reply_text("Введите секретное слово:", reply_markup=ReplyKeyboardRemove())
    return REG_CHECK_PHRASE

async def reg_check_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == SECRET_WORD:
        await update.message.reply_text("Верно. Введите пароль:")
        return REG_CHECK_PASSWORD
    else:
        await update.message.reply_text("Неверно. /cancel")
        return REG_CHECK_PHRASE

async def reg_check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == CHEF_PASSWORD:
        user = update.effective_user
        db_register_chef(user.id, user.first_name, user.username)
        await update.message.reply_text("✅ Вы зарегистрированы как Повар! /menu_chef")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Неверный пароль.")
        return REG_CHECK_PASSWORD

# --- 6. ФУНКЦИОНАЛ ПОВАРА (Менеджмент) ---

async def menu_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_is_chef(update.effective_user.id):
        await update.message.reply_text("Вы не повар.")
        return
    
    keyboard = [
        ["➕ Добавить блюдо", "🗑 Удалить блюдо"], 
        ["📋 Мои заказы"], 
        ["📂 Моё меню (список)", "🗑 Удалить архив (выполненные)"]
    ]
    await update.message.reply_text(
        "👨‍🍳 <b>Кабинет Повара</b>", 
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )

# Добавление блюда
async def add_dish_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Шаг 1. Введите <b>Категорию</b> блюда.", 
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    return ADD_DISH_CATEGORY

async def add_dish_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text
    context.user_data['new_category'] = category
    
    await update.message.reply_text(
        f"Категория: <b>{category}</b>.\nШаг 2. Введите <b>Название</b> блюда:",
        parse_mode=ParseMode.HTML
    )
    return ADD_DISH_NAME

async def add_dish_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dish_name = update.message.text
    category = context.user_data['new_category']
    chef_id = update.effective_user.id
    
    db_add_dish(chef_id, category, dish_name)
    
    await update.message.reply_text(f"✅ Добавлено:\nКатегория: <b>{category}</b>\nБлюдо: <b>{dish_name}</b>", parse_mode=ParseMode.HTML)
    await menu_chef(update, context)
    return ConversationHandler.END

# Удаление блюда
async def delete_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    menu_items = db_get_full_menu_with_ids(chef_id)

    if not menu_items:
        await update.message.reply_text("Ваше меню пусто.")
        return ConversationHandler.END

    msg = "📂 <b>Ваше меню (для удаления):</b>\n\n"
    current_cat = ""
    for item_id, cat, dish in menu_items:
        if cat != current_cat:
            msg += f"\n📁 <b>{cat}</b>\n"
            current_cat = cat
        msg += f" (ID: <code>{item_id}</code>) {dish}\n"

    msg += "\nВведите <b>ID</b> блюда, которое хотите удалить:"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
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
        await update.message.reply_text(f"✅ Блюдо с ID <code>{item_id}</code> успешно удалено.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ Блюдо с ID <code>{item_id}</code> не найдено в вашем меню или не принадлежит вам.", parse_mode=ParseMode.HTML)

    return ConversationHandler.END

# Просмотр своего меню
async def show_my_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    rows = db_get_full_menu_with_ids(chef_id)
    if not rows:
        await update.message.reply_text("Меню пусто.")
    else:
        msg = "<b>Ваше меню:</b>\n\n"
        current_cat = ""
        for item_id, cat, dish in rows:
            if cat != current_cat:
                msg += f"📂 <b>{cat}</b>\n"
                current_cat = cat
            msg += f" (ID: <code>{item_id}</code>) {dish}\n"
            
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# Просмотр заказов
async def chef_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    orders = db_get_chef_orders(chef_id)
    
    if not orders:
        await update.message.reply_text("Активных заказов нет.")
        return

    msg = "📋 <b>Активные заказы:</b>\n\n"
    for o in orders:
        msg += f"🆔 <b>{o[0]}</b> | {o[1]} (x{o[2]})\n📍 Место: {o[3]}\nСтатус: {o[4]}\nКоманды: /cook_{o[0]} | /finish_{o[0]}\n------------------\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# Удаление архива
async def chef_delete_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    if not db_is_chef(chef_id): return
    
    count = db_delete_completed_orders(chef_id)
    
    if count > 0:
        await update.message.reply_text(f"✅ Удалено <b>{count}</b> старых заказов (Выполненных и Отмененных).", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("Нет заказов для удаления (архив пуст).")

# Смена статуса
async def order_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_is_chef(update.effective_user.id): return
    
    cmd = update.message.text
    action, order_id_str = cmd.split('_') 
    order_id = int(order_id_str)
    
    new_status = "In Progress" if "cook" in action else "Completed"
    status_rus = "Готовится 🍳" if "cook" in action else "Доставлен/Готов ✅"
    
    db_update_status(order_id, new_status)
    await update.message.reply_text(f"Заказ {order_id}: {status_rus}")
    
    data = db_get_order_details(order_id)
    if data:
        try:
            await context.bot.send_message(
                chat_id=data[0],
                text=f"🔔 Статус заказа (<b>{data[2]}</b>) обновлен: <b>{status_rus}</b>",
                parse_mode=ParseMode.HTML
            )
        except: pass

# --- 7. ФУНКЦИОНАЛ КЛИЕНТА ---

async def menu_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🍕 Сделать заказ"], ["📜 Мои заказы"]]
    await update.message.reply_text("Меню клиента:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def client_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_id = update.effective_user.id
    orders = db_get_client_orders(client_id)
    
    if not orders:
        await update.message.reply_text("Список заказов пуст.")
        return

    msg = "📜 <b>Ваши последние заказы:</b>\n\n"
    for o in orders:
        status = o[3]
        msg += f"🆔 <b>{o[0]}</b> | {o[1]} (x{o[2]})\n📍 {o[4]}\nСтатус: <b>{status}</b>\n"
        if status == 'New':
            msg += f"❌ Отменить: /cancel_order_{o[0]}\n"
        msg += "----------------------\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def client_cancel_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text 
    order_id = int(cmd.split('_')[-1])
    
    details = db_get_order_details(order_id)
    
    if not details or details[0] != update.effective_user.id:
        await update.message.reply_text("Ошибка доступа.")
        return
    if details[3] != 'New':
        await update.message.reply_text("Поздно отменять.")
        return

    db_update_status(order_id, "Cancelled")
    await update.message.reply_text(f"✅ Заказ №{order_id} отменен.")
    try:
        await context.bot.send_message(chat_id=details[1], text=f"⚠️ <b>ВНИМАНИЕ:</b> Клиент отменил заказ №{order_id} ({details[2]})!", parse_mode=ParseMode.HTML)
    except: pass

# --- 8. ЦЕПОЧКА ЗАКАЗА (С КАТЕГОРИЯМИ И АДРЕСОМ) ---

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chefs = db_get_all_chefs()
    if not chefs:
        await update.message.reply_text("Поваров нет.")
        return ConversationHandler.END
    
    context.user_data['chefs_map'] = {c[1]: c[0] for c in chefs}
    keyboard = [[c[1]] for c in chefs]
    
    await update.message.reply_text("Выберите повара:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return CHOOSE_CHEF

async def order_choose_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_name = update.message.text
    chefs_map = context.user_data.get('chefs_map', {})
    
    if chef_name not in chefs_map:
        await update.message.reply_text("Выберите повара кнопкой.")
        return CHOOSE_CHEF
    
    chef_id = chefs_map[chef_name]
    context.user_data['selected_chef_id'] = chef_id
    
    categories = db_get_chef_categories(chef_id)
    if not categories:
        await update.message.reply_text("У повара пустое меню.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
        
    keyboard = [[c] for c in categories]
    await update.message.reply_text(
        f"Меню <b>{chef_name}</b>. Выберите категорию:", 
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_CATEGORY

async def order_choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text
    chef_id = context.user_data['selected_chef_id']
    
    dishes = db_get_dishes_by_category(chef_id, category)
    if not dishes:
        await update.message.reply_text("В этой категории пусто. Выберите другую или /cancel.")
        return CHOOSE_CATEGORY
        
    context.user_data['selected_category'] = category # Сохраняем категорию (опционально)
    keyboard = [[d] for d in dishes]
    await update.message.reply_text(
        f"Категория <b>{category}</b>. Выберите блюдо:\nЕсли нет нужного, напишите что вам нужно", 
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_DISH

async def order_choose_dish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dish_name = update.message.text
    context.user_data['selected_dish'] = dish_name
    
    await update.message.reply_text("Введите количество (число):", reply_markup=ReplyKeyboardRemove())
    return TYPE_QUANTITY

async def order_ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число больше 0.")
        return TYPE_QUANTITY
    
    context.user_data['selected_qty'] = qty
    
    await update.message.reply_text("📍 Напишите <b>место доставки</b>:", parse_mode=ParseMode.HTML)
    return TYPE_ADDRESS

async def order_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text
    client_id = update.effective_user.id
    
    chef_id = context.user_data['selected_chef_id']
    dish_name = context.user_data['selected_dish']
    qty = context.user_data['selected_qty']
    
    order_id = db_save_order(client_id, chef_id, dish_name, qty, address)
    
    await update.message.reply_text(f"✅ Заказ №{order_id} оформлен!\nМесто: {address}", reply_markup=ReplyKeyboardRemove())
    
    try:
        await context.bot.send_message(
            chat_id=chef_id,
            text=f"🔔 <b>НОВЫЙ ЗАКАЗ №{order_id}</b>\nЗаказщик: {client_id}\nБлюдо: {dish_name} (x{qty})\n📍 Место: {address}",
            parse_mode=ParseMode.HTML
        )
    except: pass
        
    context.user_data.clear()
    return ConversationHandler.END

# --- 9. MAIN ---

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    # Регистрация
    conv_reg = ConversationHandler(
        entry_points=[CommandHandler("register_chef", reg_start)],
        states={
            REG_CHECK_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_phrase)],
            REG_CHECK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Добавление блюда
    conv_add_dish = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^➕ Добавить блюдо$"), add_dish_start)],
        states={
            ADD_DISH_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_category_handler)],
            ADD_DISH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_name_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Удаление блюда
    conv_delete_dish = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🗑 Удалить блюдо$"), delete_item_start)],
        states={DELETE_ITEM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_item_finish)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Оформление заказа
    conv_order = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🍕 Сделать заказ$"), order_start)],
        states={
            CHOOSE_CHEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_chef)],
            CHOOSE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_category)],
            CHOOSE_DISH: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_dish)],
            TYPE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_ask_address)],
            TYPE_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_finish)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(conv_reg)
    app.add_handler(conv_add_dish)
    app.add_handler(conv_delete_dish) # Новый обработчик
    app.add_handler(conv_order)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu_client", menu_client))
    app.add_handler(CommandHandler("menu_chef", menu_chef))
    
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Мои заказы$"), chef_view_orders))
    app.add_handler(MessageHandler(filters.Regex(r"^📂 Моё меню \(список\)$"), show_my_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^📜 Мои заказы$"), client_view_orders))
    app.add_handler(MessageHandler(filters.Regex(r"^🗑 Удалить архив \(выполненные\)$"), chef_delete_archive))
    
    # Динамические команды
    app.add_handler(MessageHandler(filters.Regex(r"^/(cook|finish)_\d+$"), order_status_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/cancel_order_\d+$"), client_cancel_order_handler))
    
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
