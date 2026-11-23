import os
import base64
import telebot
from openai import OpenAI

# ================== НАСТРОЙКИ ==================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")   # токен бота — только в переменных окружения Render

# Pollinations: бесплатный API без ключей.
# OpenAI-клиенту нужен какой-то api_key, поэтому ставим заглушку.
ai = OpenAI(
    api_key="not-needed",
    base_url="https://text.pollinations.ai/openai"
)
MODEL = "openai"   # у Pollinations модель так и называется; vision (картинки) поддерживается

tg = telebot.TeleBot(BOT_TOKEN)

SYSTEM_PROMPT = (
    "Ты — дружелюбный и живой помощник. Отвечай на том языке, "
    "на котором пишет пользователь.\n"
    "Правила твоих ответов:\n"
    "1. Объясняй подробно и понятно: без слов, которые надо гуглить, "
    "и без пропусков логики. Если тема сложная — разбивай её на шаги.\n"
    "2. Используй примеры и аналогии из обычной жизни, чтобы было ясно.\n"
    "3. Добавляй эмодзи, чтобы текст был живым и легко читался — "
    "но по делу, без спама смайликами в каждом слове.\n"
    "4. Не будь сухим и канцелярским: отвечай как хороший знакомый, "
    "который реально хочет, чтобы ты понял.\n"
    "5. В конце можно задать короткий уточняющий вопрос или предложить "
    "разобрать тему глубже, если это уместно."
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

def ask_ai(chat_id, user_text, image_b64=None):
    msgs = get_history(chat_id)

    if image_b64:
        msgs.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }},
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
        downloaded = tg.download_file(file_info.file_path)

        with open("temp.jpg", "wb") as f:
            f.write(downloaded)
        with open("temp.jpg", "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        caption = message.caption or "Что на этом изображении?"
        answer = ask_ai(message.chat.id, caption, image_b64=img_b64)
        tg.reply_to(message, answer)
    except Exception as e:
        tg.reply_to(message, "Не смог разобрать фото 😔")
        print("PHOTO ERROR:", e)

# ================== ЗАПУСК ==================

print("Bot is running...")
tg.polling(none_stop=True)
