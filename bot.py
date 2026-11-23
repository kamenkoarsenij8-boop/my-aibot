import os
import time
import urllib.parse

import telebot
import requests
from flask import Flask, request

# ================== НАСТРОЙКИ ==================

# Сначала пробуем взять токен из переменной окружения (для Render),
# если её нет — берём запасной токен в кавычках (для запуска на компе)
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9228329417:AAHRBGMySQ8sc0V8V2bIYbr3Z2DHRqadnKQ")

CREATOR_NAME = "XELD_i"

# Адрес, который Render выдаст сервису (на компе этой переменной нет — и это нормально)
WEBHOOK_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_PORT = 8000
WEBHOOK_URL_BASE = f"https://{WEBHOOK_HOST}" if WEBHOOK_HOST else "http://localhost"
WEBHOOK_URL_PATH = f"/webhook/{TG_TOKEN}/"

SYSTEM_PROMPT = (
    "Ты полезный ассистент. Отвечай на русском языке, кратко и по делу. "
    "Оформляй ответы красиво: выделяй главное жирным (**текст**), "
    "используй курсив для нюансов, списки (пунктиром) для перечислений. "
    "Не используй заголовки уровня H1 (#). "
    "Ты помнишь всю предыдущую переписку с пользователем и учитываешь её в ответах."
)

POLLINATIONS_URL = "https://text.pollinations.ai/"
MAX_HISTORY = 12
MAX_CHARS_IN_PROMPT = 6000

bot = telebot.TeleBot(TG_TOKEN, parse_mode=None)

# ================== ПАМЯТЬ ДИАЛОГОВ ==================
# Живёт в оперативке: при перезапуске бота память сбрасывается.
# {chat_id: [(кто_сказал, текст), ...]}
memory = dict()


def remember(chat_id: int, who: str, text: str):
    if chat_id not in memory:
        memory[chat_id] = list()
    history = memory[chat_id]
    history.append((who, text))
    while len(history) > MAX_HISTORY:
        history.pop(0)


def build_prompt(chat_id: int) -> str:
    history = memory.get(chat_id, list())
    lines = list()
    total = 0
    for who, text in reversed(history):
        prefix = "Пользователь" if who == "user" else "Ты"
        line = f"{prefix}: {text}"
        total += len(line)
        if total > MAX_CHARS_IN_PROMPT:
            break
        lines.append(line)
    lines.reverse()
    return "\n".join(lines)


def clear_memory(chat_id: int):
    memory.pop(chat_id, None)


# ================== ЗАПРОС К ИИ ==================

def ask_ai(prompt: str) -> str:
    encoded = urllib.parse.quote(prompt)
    params = {
        "system": SYSTEM_PROMPT,
        "referrer": "telegram-bot",
    }

    for attempt in range(3):
        try:
            resp = requests.get(POLLINATIONS_URL + encoded, params=params, timeout=60)

            if resp.status_code == 429:
                wait = 8 + attempt * 5
                print(f"[429] Подожду {wait} сек и попробую снова...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.text.strip()

        except requests.exceptions.RequestException as e:
            print(f"[Ошибка запроса, попытка {attempt + 1}/3]: {e}")
            time.sleep(2)

    return "Не удалось получить ответ от ИИ. Попробуй позже."


# ================== ОТПРАВКА ОТВЕТА ==================

def send_reply(message, text: str):
    try:
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, text)


# ================== ОБРАБОТЧИКИ ==================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    clear_memory(message.chat.id)
    text = (
        "Привет! Я бот-ассистент на Python 🤖\n\n"
        "Я помню нашу переписку в рамках диалога — можешь задавать "
        "уточняющие вопросы и ссылаться на то, что уже обсуждали.\n\n"
        f"Создатель бота: {CREATOR_NAME}\n\n"
        "Команды:\n"
        "/clear — очистить память и начать заново\n"
        "/creator — показать создателя бота"
    )
    send_reply(message, text)


@bot.message_handler(commands=["creator"])
def cmd_creator(message):
    send_reply(message, f"Создатель этого бота: {CREATOR_NAME}")


@bot.message_handler(commands=["clear"])
def cmd_clear(message):
    clear_memory(message.chat.id)
    send_reply(message, "Память очищена. Начинаем с чистого листа 🙂")


@bot.message_handler(content_types=["photo", "sticker", "voice", "video", "document"])
def handle_media(message):
    send_reply(message, "Пока я понимаю только текст — фото и голос прилетят позже 🙂")


@bot.message_handler(func=lambda m: True)
def handle_text(message):
    chat_id = message.chat.id
    user_text = message.text
    print(f"[{message.from_user.first_name}]: {user_text}")

    remember(chat_id, "user", user_text)
    prompt = build_prompt(chat_id)

    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass

    answer = ask_ai(prompt)
    remember(chat_id, "bot", answer)

    print(f"[Бот]: {answer[:100]}...")
    send_reply(message, answer)


# ================== FLASK (ДЛЯ RENDER) ==================

app = Flask(__name__)


@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "", 200


@app.route("/")
def index():
    return "Бот работает!"


# ================== ЗАПУСК ==================

if __name__ == "__main__":
    if WEBHOOK_HOST:
        # Режим Render: вебхук
        print(f"Запуск на Render. Хост: {WEBHOOK_HOST}")

        bot.remove_webhook()
        webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_URL_PATH}"
        print(f"Установка вебхука: {webhook_url}")
        bot.set_webhook(url=webhook_url)

        app.run(host="0.0.0.0", port=WEBHOOK_PORT)
    else:
        # Локальный режим: обычный polling
        print("Запуск локально (Polling)...")
        print("Бот запущен. Жду сообщений...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
