import os
import requests
import threading
import telebot
from telebot import types
from http.server import HTTPServer, BaseHTTPRequestHandler
from openai import OpenAI

# ================== НАСТРОЙКИ ==================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

tg = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# Принудительно удаляем вебхук, чтобы не было конфликта 409
requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")

# Pollinations: бесплатный API без ключей
ai = OpenAI(
    api_key="not-needed",
    base_url="https://text.pollinations.ai/openai"
)
MODEL = "openai"

SYSTEM_PROMPT = (
    "Ты — дружелюбный и живой помощник в Telegram. Отвечай на том языке, "
    "на котором пишет пользователь.\n\n"
    "ПРАВИЛА ОФОРМЛЕНИЯ (строго):\n"
    "1. НИКОГДА не используй таблицы и символ вертикальной палки | — "
    "Telegram их не поддерживает. Вместо таблиц используй список строк.\n"
    "2. Для жирного шрифта используй **текст** (двойные звёздочки).\n"
    "3. Для списков используй обычные дефисы или нумерацию 1. 2. 3.\n"
    "4. Разделяй логические блоки пустой строкой.\n"
    "5. Добавляй эмодзи для живости, но умеренно.\n\n"
    "ПРАВИЛА ОТВЕТОВ:\n"
    "1. Объясняй подробно и понятно, без пропусков логики.\n"
    "2. Используй примеры и аналогии из обычной жизни.\n"
    "3. Отвечай как хороший знакомый, который реально хочет помочь.\n"
    "4. В конце можно задать короткий уточняющий вопрос, если это уместно."
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

# ================== ОТПРАВКА СООБЩЕНИЙ ==================

def smart_send(chat_id, text, reply_to=None):
    """Пробует отправить с Markdown-разметкой, при ошибке — как обычный текст."""
    try:
        tg.send_message(chat_id, text, reply_to_message_id=reply_to)
    except Exception:
        # Если модель вставила «сломанный» markdown — шлём без разметки
        tg.send_message(chat_id, text.replace("**", ""), parse_mode=None)

# ================== ОБРАБОТЧИКИ ==================

@tg.message_handler(commands=["start"])
def handle_start(message):
    history.pop(message.chat.id, None)
    smart_send(
        message.chat.id,
        "Привет! 👋 Я — твой всесторонний помощник, и вот что я умею:\n\n"
        "❓ **Отвечать на вопросы** — от простых фактов до сложных разъяснений.\n"
        "🎓 **Объяснять и обучать** — разберу сложные идеи на простые шаги, добавлю примеры.\n"
        "🧮 **Помогать в учёбе** — решение задач, подготовка к экзаменам, объяснение формул.\n"
        "💻 **Кодинг** — пишу и разбираю код, помогаю отладить.\n"
        "📝 **Списки и планы** — организую задачи, создам чек-листы.\n"
        "🌍 **Переводы** — быстрый перевод текста с/на разные языки.\n"
        "✍️ **Креатив** — стихи, рассказы, заметки, объявления.\n"
        "🔍 **Грамматика** — проверю и поправлю текст.\n"
        "💪 **Мотивация** — цитаты, короткие истории, заряд бодрости.\n"
        "📸 **Фото** — пришли фото с задачей, прочитаю и решу пошагово.\n\n"
        "✌️ **Как обращаться?**\n"
        "Пиши любую тему, добавляй детали — например, «сколько это будет в литрах?» "
        "или «напиши алгоритм на Python». Постараюсь ответить чётко и дружелюбно 🙂\n\n"
        "Что бы ты хотел сделать прямо сейчас? 🚀",
        reply_to=message.message_id
    )

@tg.message_handler(content_types=["text"])
def handle_text(message):
    try:
        answer = ask_ai(message.chat.id, message.text)
        smart_send(message.chat.id, answer, reply_to=message.message_id)
    except Exception as e:
        error_msg = f"💥 Критическая ошибка: {type(e).__name__}: {str(e)}"
        tg.reply_to(message, error_msg, parse_mode=None)
        print(error_msg)

@tg.message_handler(content_types=["photo"])
def handle_photo(message):
    try:
        file_info = tg.get_file(message.photo[-1].file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        caption = message.caption or "Что на этом изображении? Реши, если это задача."
        tg.reply_to(message, "Думаю над фото... 🤔", parse_mode=None)
        answer = ask_ai(message.chat.id, caption, image_url=image_url)
        smart_send(message.chat.id, answer, reply_to=message.message_id)
    except Exception as e:
        error_msg = f"💥 Ошибка с фото: {type(e).__name__}: {str(e)}"
        tg.reply_to(message, error_msg, parse_mode=None)
        print(error_msg)

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
