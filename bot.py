import os
import requests
import threading
import telebot
from http.server import HTTPServer, BaseHTTPRequestHandler
from openai import OpenAI

# ================== НАСТРОЙКИ ==================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

tg = telebot.TeleBot(BOT_TOKEN)

# Принудительно удаляем вебхук, чтобы не было конфликта 409
requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")

# Pollinations: бесплатный API без ключей
ai = OpenAI(
    api_key="not-needed",
    base_url="https://text.pollinations.ai/openai"
)
MODEL = "openai"

SYSTEM_PROMPT = (
    "Ты — дружелюбный и живой помощник. Отвечай на том языке, "
    "на котором пишет пользователь.\n"
    "Если тебе прислали фото с задачей — внимательно прочитай текст "
    "на изображении и реши её пошагово."
)

# ================== ПАМЯТЬ ДИАЛОГОВ ==================

history = {}

def get_history(chat_id):
    if chat_id not in history:
        history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return history[chat_id]

def trim_history(chat_id, limit=20):
    msgs = history[chat_id]
    if len(msgs) > limit + 1:
        history[chat_id] = [msgs[0]] + msgs[-limit:]

# ================== ЗАПРОС К НЕЙРОСЕТИ ==================

def ask_ai(chat_id, user_text, image_url=None):
    msgs = get_history(chat_id)

    if image_url:
        msgs.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        })
    else:
        msgs.append({"role": "user", "content": user_text})

    trim_history(chat_id)

    response = ai.chat.completions.create(
        model=MODEL,
        messages=msgs,
        max_tokens=1000,
    )
    answer = response.choices[0].message.content
    msgs.append({"role": "assistant", "content": answer})
    return answer

# ================== ОБРАБОТЧИКИ ==================

@tg.message_handler(commands=["start"])
def handle_start(message):
    history.pop(message.chat.id, None)
    tg.reply_to(
        message,
        "Привет! 👋 Я бот с памятью — помню контекст диалога.\n"
        "Напиши вопрос или пришли фото с подписью 📸\n"
        "Объясняю подробно и понятно 🙂"
    )

@tg.message_handler(content_types=["text"])
def handle_text(message):
    try:
        answer = ask_ai(message.chat.id, message.text)
        tg.reply_to(message, answer)
    except Exception as e:
        tg.reply_to(message, f"Ошибка: {e}")
        print("TEXT ERROR:", e)

@tg.message_handler(content_types=["photo"])
def handle_photo(message):
    try:
        file_info = tg.get_file(message.photo[-1].file_id)
        # Прямая ссылка на файл Telegram — её понимают vision-модели
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        caption = message.caption or "Что на этом изображении? Реши, если это задача."
        tg.reply_to(message, "Думаю над фото... 🤔")
        answer = ask_ai(message.chat.id, caption, image_url=image_url)
        tg.reply_to(message, answer)
    except Exception as e:
        tg.reply_to(message, f"Не смог разобрать фото. Причина: {e}")
        print("PHOTO ERROR:", e)

# ================== HTTP-СЕРВЕР ДЛЯ RENDER ==================

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    handler = BaseHTTPRequestHandler
    handler.do_GET = lambda self: (self.send_response(200),
                                   self.end_headers(),
                                   self.wfile.write(b"bot is alive"))
    HTTPServer(("0.0.0.0", port), handler).serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ================== ЗАПУСК ==================

print("Bot is running...")
tg.polling(none_stop=True)
