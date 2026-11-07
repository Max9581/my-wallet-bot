import os
import threading
from flask import Flask
import telebot
from telebot import types
import sqlite3
import re
import ssl
import time
import csv
from datetime import datetime

ssl._create_default_https_context = ssl._create_unverified_context

TOKEN = '8529906637:AAHXyh53d4qm8fMcuaW5JY7W6VxZJYepF4g'
bot = telebot.TeleBot(TOKEN)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            amount INTEGER,
            date TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_premium INTEGER DEFAULT 0,
            month_limit INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def add_expense(user_id, category, amount):
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    date_now = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("INSERT INTO expenses (user_id, category, amount, date) VALUES (?, ?, ?, ?)",
                   (user_id, category, amount, date_now))
    conn.commit()
    conn.close()

def get_stats(user_id, period='today'):
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    if period == 'today':
        date_filter = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id = ? AND date = ? GROUP BY category", (user_id, date_filter))
    else:
        month_filter = datetime.now().strftime('%Y-%m')
        cursor.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id = ? AND date LIKE ? GROUP BY category", (user_id, f"{month_filter}%"))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_month_total(user_id):
    rows = get_stats(user_id, 'month')
    return sum(row[1] for row in rows)

def get_user(user_id):
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, month_limit FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = (0, 0)
    conn.close()
    return row

def set_premium(user_id):
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_limit(user_id, limit):
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET month_limit = ? WHERE user_id = ?", (limit, user_id))
    conn.commit()
    conn.close()

# --- МЕНЮ ---
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('📊 За сегодня'), types.KeyboardButton('🗓 За месяц'))
    markup.add(types.KeyboardButton('👑 Premium'), types.KeyboardButton('❓ Помощь'))
    return markup

def premium_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('📥 Экспорт в Excel'), types.KeyboardButton('🎯 Установить лимит'))
    markup.add(types.KeyboardButton('⬅️ Назад в меню'))
    return markup

# --- КОМАНДЫ ---
@bot.message_handler(commands=['start', 'menu'])
def start(message):
    get_user(message.from_user.id)
    text = (
        "👋 Привет! Я твой личный бухгалтер «Моя Копилка».\n\n"
        "Просто пиши мне траты в формате:\n"
        "👉 **Категория Сумма**\n"
        "Например: `Кофе 300` или `Такси 450`\n\n"
        "Пользуйся кнопками ниже 👇"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == '📊 За сегодня' or m.text == '/today')
def today(message):
    rows = get_stats(message.from_user.id, 'today')
    if not rows:
        bot.send_message(message.chat.id, "За сегодня трат нет. Отличный день! 🤑", reply_markup=main_menu())
        return
    total = sum(row[1] for row in rows)
    text = "📅 **Траты за сегодня:**\n\n"
    for row in rows:
        text += f"▪ {row[0]}: {row[1]} ₽\n"
    text += f"\n💰 **Итого: {total} ₽**"
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == '🗓 За месяц' or m.text == '/month')
def month(message):
    rows = get_stats(message.from_user.id, 'month')
    if not rows:
        bot.send_message(message.chat.id, "В этом месяце пока нет записей.", reply_markup=main_menu())
        return
    total = sum(row[1] for row in rows)
    is_premium, limit = get_user(message.from_user.id)
    limit_text = ""
    if is_premium and limit > 0:
        if total > limit:
            limit_text = f"\n⚠️ **ВНИМАНИЕ! Вы превысили лимит на {total - limit} ₽!**"
        else:
            limit_text = f"\n🎯 Остаток до лимита: {limit - total} ₽"

    text = "🗓 **Траты за этот месяц:**\n\n"
    for row in rows:
        text += f"▪ {row[0]}: {row[1]} ₽\n"
    text += f"\n💰 **Итого: {total} ₽**" + limit_text
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == '❓ Помощь')
def help_cmd(message):
    text = (
        "📖 **Как мной пользоваться:**\n"
        "Напиши: `Еда 500`\n\n"
        "👑 **Premium дает:**\n"
        "• Экспорт всех трат в Excel\n"
        "• Установку лимитов (бот предупредит, если потратишь больше)"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == '👑 Premium' or m.text == '/premium')
def premium(message):
    is_premium, _ = get_user(message.from_user.id)
    if is_premium:
        bot.send_message(message.chat.id, "У тебя уже есть Premium! 👑", reply_markup=premium_menu())
        return

    text = (
        "👑 **Premium-подписка**\n\n"
        "✅ Экспорт трат в Excel (CSV)\n"
        "✅ Установка месячного лимита\n"
        "✅ Приоритетная поддержка\n\n"
        "Стоимость: **100 звезд** (навсегда)"
    )
    markup = types.InlineKeyboardMarkup()
    btn_pay = types.InlineKeyboardButton("⭐ Оплатить 100 звезд", callback_data="pay_premium")
    markup.add(btn_pay)
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'pay_premium')
def send_invoice(call):
    prices = [types.LabeledPrice(label="Premium доступ", amount=100)]
    bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Premium доступ",
        description="Экспорт в Excel и лимиты навсегда",
        invoice_payload="premium_payload",
        provider_token="",
        currency="XTR",
        prices=prices
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    set_premium(message.from_user.id)
    bot.send_message(message.chat.id, "🎉 Спасибо за оплату! Теперь тебе доступен Premium.\n", reply_markup=premium_menu())

@bot.message_handler(func=lambda m: m.text == '📥 Экспорт в Excel')
def export_csv(message):
    is_premium, _ = get_user(message.from_user.id)
    if not is_premium:
        bot.send_message(message.chat.id, "❌ Функция доступна только в Premium.", reply_markup=main_menu())
        return

    bot.send_message(message.chat.id, "⏳ Собираю данные и формирую файл...")
    conn = sqlite3.connect('wallet.db')
    cursor = conn.cursor()
    cursor.execute("SELECT date, category, amount FROM expenses WHERE user_id = ? ORDER BY date DESC", (message.from_user.id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(message.chat.id, "У тебя пока нет записей.", reply_markup=premium_menu())
        return

    filename = f"expenses_{message.from_user.id}.csv"
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["Дата", "Категория", "Сумма"])
        for row in rows:
            writer.writerow(row)

    with open(filename, 'rb') as f:
        bot.send_document(message.chat.id, f, caption="Твои траты в Excel")
    
    os.remove(filename)
    bot.send_message(message.chat.id, "Файл готов!", reply_markup=premium_menu())

@bot.message_handler(func=lambda m: m.text == '🎯 Установить лимит')
def set_limit_prompt(message):
    is_premium, _ = get_user(message.from_user.id)
    if not is_premium:
        bot.send_message(message.chat.id, "❌ Функция доступна только в Premium.", reply_markup=main_menu())
        return
    msg = bot.send_message(message.chat.id, "Введи сумму лимита на месяц (например, 50000). Чтобы отключить, введи 0:")
    bot.register_next_step_handler(msg, save_limit)

def save_limit(message):
    if not message.text.isdigit():
        bot.send_message(message.chat.id, "❌ Введи только цифры.", reply_markup=premium_menu())
        return
    limit = int(message.text)
    set_limit(message.from_user.id, limit)
    if limit == 0:
        bot.send_message(message.chat.id, "Лимит отключен.", reply_markup=premium_menu())
    else:
        bot.send_message(message.chat.id, f"✅ Лимит установлен: {limit} ₽ в месяц.", reply_markup=premium_menu())

@bot.message_handler(func=lambda m: m.text == '⬅️ Назад в меню')
def back_to_main(message):
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())

@bot.message_handler(content_types=['text'])
def handle_expense(message):
    if message.text in ['📊 За сегодня', '🗓 За месяц', '👑 Premium', '❓ Помощь', '📥 Экспорт в Excel', '🎯 Установить лимит', '⬅️ Назад в меню']:
        return
    text = message.text.strip()
    match = re.search(r'\s(\d+)$', text)
    if match:
        amount = int(match.group(1))
        if amount > 10000000:
            bot.reply_to(message, "🤨 Слишком большая сумма. Проверь ввод.", reply_markup=main_menu())
            return
        category = text[:match.start()].strip().capitalize()
        if not category:
            category = "Разное"
        add_expense(message.from_user.id, category, amount)
        is_premium, limit = get_user(message.from_user.id)
        warning = ""
        if is_premium and limit > 0:
            total_month = get_month_total(message.from_user.id)
            if total_month > limit:
                warning = f"\n\n⚠️ **Внимание! Ты превысил лимит на {total_month - limit} ₽!**"
        bot.reply_to(message, f"✅ Записал: **{category}** — {amount} ₽{warning}", parse_mode='Markdown', reply_markup=main_menu())
    else:
        bot.reply_to(message, "🤔 Я не понял сумму. Напиши в формате: `Еда 500`", parse_mode='Markdown', reply_markup=main_menu())

# --- ЗАПУСК ДЛЯ RENDER ---
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
