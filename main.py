mport os
import re
import threading
import time
import requests
import telebot
from telebot import types
from openai import OpenAI
from flask import Flask
import database as db

# --- CONFIG ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='HTML')
client = OpenAI(api_key=OPENAI_API_KEY)
db.init_db()

# --- WEB SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "🤖 Bot is Active 24/7", 200
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()

# --- UI ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("⚡ Перевести видео", "⭐ Купить Stars")
    markup.row("👤 Профиль", "⚙️ Настройки", "📚 Инфо")
    return markup

def get_voice_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎙️ Onyx (Мужской)", callback_data="set_voice_onyx"))
    markup.add(types.InlineKeyboardButton("🎙️ Nova (Женский)", callback_data="set_voice_nova"))
    markup.add(types.InlineKeyboardButton("🎙️ Alloy (Нейтральный)", callback_data="set_voice_alloy"))
    return markup

@bot.message_handler(commands=['start'])
def start(m):
    db.get_user(m.from_user.id, m.from_user.username)
    bot.send_message(m.chat.id, "👑 <b>AI TRANSLATOR PREMIUM</b>\n\nОтправьте ссылку на YouTube-видео для перевода!", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "⚡ Перевести видео")
def prompt_link(m): bot.reply_to(m, "📥 Отправьте ссылку на YouTube-видео в чат:")

@bot.message_handler(func=lambda m: m.text == "📚 Инфо")
def show_info(m): bot.send_message(m.chat.id, "📚 Сервис переводит YouTube-видео с помощью ИИ (GPT-4o + Whisper). Стоимость: 10 Stars.")

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def settings_menu(m):
    user = db.get_user(m.from_user.id)
    bot.send_message(m.chat.id, f"⚙️ Выберите голос:", reply_markup=get_voice_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_voice_"))
def update_voice_pref(call):
    new_voice = call.data.split("_")[2]
    db.update_voice(call.from_user.id, new_voice)
    bot.answer_callback_query(call.id, f"✅ Голос: {new_voice}")
    bot.edit_message_text(f"✅ <b>Голос изменен на {new_voice.upper()}</b>", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(m):
    u = db.get_user(m.from_user.id)
    bot.send_message(m.chat.id, f"👤 Баланс: {u[1]} Stars | Голос: {u[3].upper()}")

@bot.message_handler(func=lambda m: m.text in ["⭐ Купить Stars", "💎 Тарифы и VIP"])
def shop(m):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⭐ 50 Stars - 50 XTR", callback_data="buy_50"))
    bot.send_message(m.chat.id, "💳 Выберите пакет пополнения:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def payment_invoice(call):
    amt = int(call.data.split("_")[1])
    bot.send_invoice(call.message.chat.id, "Пополнение баланса", f"{amt} Stars", f"payload_{amt}", "", "XTR", [types.LabeledPrice("Stars", amt)])

@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q): bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pay_ok(m):
    db.add_stars(m.from_user.id, m.successful_payment.total_amount)
    bot.send_message(m.chat.id, "🎉 Оплата прошла успешно!")

@bot.message_handler(commands=['admin', 'give'])
def admin_tools(m):
    if m.from_user.id != ADMIN_ID: return
    if m.text.startswith('/give'):
        try:
            _, uid, amt = m.text.split()
            db.add_stars(int(uid), int(amt))
            bot.reply_to(m, "✅ Выдано!")
        except: bot.reply_to(m, "Ошибка формата")
    else:
        u, s = db.get_stats()
        bot.send_message(m.chat.id, f"📊 Админка: Юзеров: {u}, Оборот: {s}")

# --- ПАРСЕР ID ---
def extract_video_id(url):
    m = re.search(r'(?:v=|\/|be\/|shorts\/|embed\/)([0-9A-Za-z_-]{11})', url)
    return m.group(1) if m else None

# --- МОДУЛЬ ЗАГРУЗКИ ЧЕРЕЗ COBALT API ---
def download_via_cobalt(url, user_id):
    filename = f"in_{user_id}.mp3"
    cobalt_nodes = [
        "https://api.cobalt.tools/",
        "https://co.wuk.sh/",
        "https://cobalt.stream/"
    ]
    for node in cobalt_nodes:
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://cobalt.tools",
                "Referer": "https://cobalt.tools/"
            }
            payload = {
                "url": url,
                "downloadMode": "audio",
                "audioFormat": "mp3",
                "audioBitrate": "128"
            }
            res = requests.post(node, json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                download_url = data.get("url")
                if download_url:
                    audio_data = requests.get(download_url, timeout=90, stream=True)
                    if audio_data.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in audio_data.iter_content(chunk_size=32768):
                                f.write(chunk)
                        if os.path.exists(filename) and os.path.getsize(filename) > 3000:
                            print(f"✅ Успешно скачано через Cobalt ({node})")
                            return filename
        except Exception as e:
            print(f"Cobalt node {node} err: {e}")
    return None

# --- ОБРАБОТЧИК ---
@bot.message_handler(func=lambda msg: "youtube.com" in msg.text or "youtu.be" in msg.text or "shorts" in msg.text)
def handle_video(message):
    user = db.get_user(message.from_user.id)
    if user[1] < 10:
        bot.reply_to(message, "❌ Недостаточно Stars.")
        return

    url = message.text.strip()
    status = bot.reply_to(message, "⚡ <b>[■□□□□] 20%</b> Скачиваю аудио через шлюз...")
    vid = extract_video_id(url)
    
    if not vid:
        bot.edit_message_text("❌ Некорректная ссылка.", message.chat.id, status.message_id)
        return

    f_in = download_via_cobalt(url, message.from_user.id)

    if not f_in:
        bot.edit_message_text("❌ <b>Не удалось прочитать видео.</b> Попробуйте другую ссылку.", message.chat.id, status.message_id)
        return

    try:
        bot.edit_message_text("⏳ <b>[■■□□□] 40%</b> Whisper расшифровывает аудио...", message.chat.id, status.message_id)
        with open(f_in, "rb") as f:
            original_text = client.audio.transcriptions.create(model="whisper-1", file=f).text

        bot.edit_message_text("🌐 <b>[■■■□□] 60%</b> Перевод на русский...", message.chat.id, status.message_id)
        translation = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Переведи на красивый русский язык. Только перевод."}, {"role": "user", "content": original_text}]
        ).choices[0].message.content

        bot.edit_message_text("🎙️ <b>[■■■■□] 80%</b> Синтез озвучки...", message.chat.id, status.message_id)
        f_out = f"out_{message.from_user.id}.mp3"
        voice = user[3]
        
        chunks = [translation[i:i+3500] for i in range(0, len(translation), 3500)]
        chunk_files = []
        for idx, part in enumerate(chunks):
            cf = f"chunk_{message.from_user.id}_{idx}.mp3"
            chunk_files.append(cf)
            speech = client.audio.speech.create(model="tts-1", voice=voice, input=part)
            speech.write_to_file(cf)

        with open(f_out, 'wb') as final_f:
            for cf in chunk_files:
                with open(cf, 'rb') as c_file: final_f.write(c_file.read())
                os.remove(cf)

        db.deduct_stars(message.from_user.id, 10)
        bot.delete_message(message.chat.id, status.message_id)

        bot.send_message(message.chat.id, f"📝 <b>ПЕРЕВОД:</b>\n\n{translation[:3800]}")
        with open(f_out, "rb") as a:
            bot.send_audio(message.chat.id, a, caption="🎧 <b>ГОТОВЫЙ ДУБЛЯЖ</b>")

        if os.path.exists(f_in): os.remove(f_in)
        if os.path.exists(f_out): os.remove(f_out)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
        if os.path.exists(f_in): os.remove(f_in)

while True:
    try:
        print("🚀 Бот запущен!")
        bot.polling(none_stop=True, interval=2, timeout=20)
    except: time.sleep(3)
