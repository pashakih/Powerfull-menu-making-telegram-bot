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
DB_NAME = "multichef.db"
SECRET_WORD = "chef"
CHEF_PASSWORD = "bsqkl" 

# --- 2. СОСТОЯНИЯ ДИАЛОГОВ ---
REG_CHECK_PHRASE, REG_CHECK_PASSWORD = range(2)
ADD_DISH_NAME = range(2, 3)

# Обновленная цепочка заказа: Повар -> Блюдо -> Количество -> Адрес
CHOOSE_CHEF, CHOOSE_DISH, TYPE_QUANTITY, TYPE_ADDRESS = range(3, 7)

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
            dish_name TEXT,
            FOREIGN KEY(chef_id) REFERENCES CHEFS(user_id)
        )
    """)
    
    # ДОБАВЛЕНО ПОЛЕ address
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

def db_add_dish(chef_id, dish_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO MENU (chef_id, dish_name) VALUES (?, ?)", (chef_id, dish_name))
    conn.commit()
    conn.close()

def db_get_all_chefs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM CHEFS")
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_get_chef_menu(chef_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT dish_name FROM MENU WHERE chef_id = ?", (chef_id,))
    rows = cursor.fetchall() 
    conn.close()
    return [r[0] for r in rows]

# Обновленное сохранение заказа с адресом
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
    """Получает активные заказы клиента."""
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
    """Нужно для уведомлений: узнать, кто клиент и кто повар."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, chef_id, dish_name, status FROM ORDERS WHERE id = ?", (order_id,))
    res = cursor.fetchone()
    conn.close()
    return res # (client_id, chef_id, dish_name, status)

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

# --- 5. РЕГИСТРАЦИЯ ПОВАРА (Без изменений) ---

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

# --- 6. ФУНКЦИОНАЛ ПОВАРА ---

async def menu_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_is_chef(update.effective_user.id):
        await update.message.reply_text("Вы не повар.")
        return
    
    keyboard = [["➕ Добавить блюдо"], ["📋 Мои заказы"], ["📂 Моё меню (список)"]]
    await update.message.reply_text(
        "👨‍🍳 <b>Кабинет Повара</b>", 
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )

# Добавление блюда
async def add_dish_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название нового блюда:", reply_markup=ReplyKeyboardRemove())
    return ADD_DISH_NAME

async def add_dish_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dish_name = update.message.text
    chef_id = update.effective_user.id
    db_add_dish(chef_id, dish_name)
    await update.message.reply_text(f"✅ Блюдо <b>{dish_name}</b> добавлено!", parse_mode=ParseMode.HTML)
    await menu_chef(update, context)
    return ConversationHandler.END

async def show_my_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    items = db_get_chef_menu(chef_id)
    if not items:
        await update.message.reply_text("Меню пусто.")
    else:
        text = "\n".join([f"- {item}" for item in items])
        await update.message.reply_text(f"<b>Ваше меню:</b>\n{text}", parse_mode=ParseMode.HTML)

async def chef_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_id = update.effective_user.id
    orders = db_get_chef_orders(chef_id)
    
    if not orders:
        await update.message.reply_text("Активных заказов нет.")
        return

    msg = "📋 <b>Активные заказы:</b>\n\n"
    for o in orders:
        # o = (id, dish_name, quantity, address, status, created_at)
        msg += f"🆔 <b>{o[0]}</b> | {o[1]} (x{o[2]})\n📍 Адрес: {o[3]}\nСтатус: {o[4]}\nКоманды: /cook_{o[0]} | /finish_{o[0]}\n------------------\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

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
                chat_id=data[0], # client_id
                text=f"🔔 Статус заказа (<b>{data[2]}</b>) обновлен: <b>{status_rus}</b>",
                parse_mode=ParseMode.HTML
            )
        except: pass

# --- 7. ФУНКЦИОНАЛ КЛИЕНТА ---

async def menu_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🍕 Сделать заказ"], ["📜 Мои заказы"]]
    await update.message.reply_text("Меню клиента:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# Просмотр заказов клиента + ОТМЕНА
async def client_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_id = update.effective_user.id
    orders = db_get_client_orders(client_id)
    
    if not orders:
        await update.message.reply_text("Список заказов пуст.")
        return

    msg = "📜 <b>Ваши последние заказы:</b>\n\n"
    for o in orders:
        # o = (id, dish_name, quantity, status, address)
        status = o[3]
        msg += f"🆔 <b>{o[0]}</b> | {o[1]} (x{o[2]})\n📍 {o[4]}\nСтатус: <b>{status}</b>\n"
        
        # Кнопку отмены показываем только если заказ "New"
        if status == 'New':
            msg += f"❌ Отменить: /cancel_order_{o[0]}\n"
        
        msg += "----------------------\n"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# Обработчик отмены заказа клиентом
async def client_cancel_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text # /cancel_order_123
    order_id = int(cmd.split('_')[-1])
    
    # 1. Проверяем заказ
    details = db_get_order_details(order_id) # (client_id, chef_id, dish_name, status)
    
    if not details:
        await update.message.reply_text("Заказ не найден.")
        return

    # 2. Проверяем права (чтобы чужой не отменил)
    if details[0] != update.effective_user.id:
        await update.message.reply_text("Это не ваш заказ!")
        return

    # 3. Проверяем статус
    if details[3] == "Completed":
        await update.message.reply_text("Нельзя отменить заказ, который выполнен.")
        return

    # 4. Отменяем
    db_update_status(order_id, "Cancelled")
    await update.message.reply_text(f"✅ Заказ №{order_id} успешно отменен.")

    # 5. Уведомляем повара
    try:
        await context.bot.send_message(
            chat_id=details[1], # chef_id
            text=f"⚠️ <b>ВНИМАНИЕ:</b> Клиент отменил заказ №{order_id} ({details[2]})!",
            parse_mode=ParseMode.HTML
        )
    except: pass

# --- 8. ЦЕПОЧКА ЗАКАЗА (С АДРЕСОМ) ---

# Шаг 1: Выбор повара
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chefs = db_get_all_chefs()
    if not chefs:
        await update.message.reply_text("Поваров нет.")
        return ConversationHandler.END
    
    context.user_data['chefs_map'] = {c[1]: c[0] for c in chefs}
    keyboard = [[c[1]] for c in chefs]
    
    await update.message.reply_text(
        "Выберите повара:", 
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return CHOOSE_CHEF

# Шаг 2: Выбор блюда
async def order_choose_chef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chef_name = update.message.text
    chefs_map = context.user_data.get('chefs_map', {})
    
    if chef_name not in chefs_map:
        await update.message.reply_text("Выберите повара кнопкой.")
        return CHOOSE_CHEF
    
    chef_id = chefs_map[chef_name]
    context.user_data['selected_chef_id'] = chef_id
    
    menu = db_get_chef_menu(chef_id)
    if not menu:
        await update.message.reply_text("У повара нет меню.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
        
    keyboard = [[item] for item in menu]
    await update.message.reply_text(
        f"Меню повара <b>{chef_name}</b>:", 
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_DISH

# Шаг 3: Количество
async def order_choose_dish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dish_name = update.message.text
    context.user_data['selected_dish'] = dish_name
    
    await update.message.reply_text(
        f"Блюдо: <b>{dish_name}</b>. Введите количество (число):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    return TYPE_QUANTITY

# Шаг 4: Ввод адреса (НОВЫЙ ШАГ)
async def order_ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число больше 0.")
        return TYPE_QUANTITY
    
    context.user_data['selected_qty'] = qty
    
    await update.message.reply_text(
        "📍 Теперь напишите <b>место доставки</b>:",
        parse_mode=ParseMode.HTML
    )
    return TYPE_ADDRESS

# Шаг 5: Финиш
async def order_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text # Получаем адрес
    client_id = update.effective_user.id
    
    chef_id = context.user_data['selected_chef_id']
    dish_name = context.user_data['selected_dish']
    qty = context.user_data['selected_qty']
    
    # Сохраняем в БД с адресом
    order_id = db_save_order(client_id, chef_id, dish_name, qty, address)
    
    await update.message.reply_text(
        f"✅ Заказ №{order_id} оформлен!", 
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Уведомляем повара (с адресом)
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
    
    # Хендлеры регистрации
    conv_reg = ConversationHandler(
        entry_points=[CommandHandler("register_chef", reg_start)],
        states={
            REG_CHECK_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_phrase)],
            REG_CHECK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_check_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Хендлеры добавления блюда
    conv_add_dish = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^➕ Добавить блюдо$"), add_dish_start)],
        states={ADD_DISH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_save)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Хендлеры заказа (ОБНОВЛЕННЫЕ)
    conv_order = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🍕 Сделать заказ$"), order_start)],
        states={
            CHOOSE_CHEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_chef)],
            CHOOSE_DISH: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_dish)],
            TYPE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_ask_address)], # Идет в адрес
            TYPE_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_finish)], # Идет в финиш
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(conv_reg)
    app.add_handler(conv_add_dish)
    app.add_handler(conv_order)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu_client", menu_client))
    app.add_handler(CommandHandler("menu_chef", menu_chef))
    
    # Просмотр заказов
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Мои заказы$"), chef_view_orders))
    app.add_handler(MessageHandler(filters.Regex(r"^📂 Моё меню \(список\)$"), show_my_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^📜 Мои заказы$"), client_view_orders))
    
    # Динамические команды
    app.add_handler(MessageHandler(filters.Regex(r"^/(cook|finish)_\d+$"), order_status_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/cancel_order_\d+$"), client_cancel_order_handler))
    
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
