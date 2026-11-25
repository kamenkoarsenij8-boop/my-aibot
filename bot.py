import os
import io
import requests
import threading
import telebot
from http.server import HTTPServer, BaseHTTPRequestHandler
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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
    "3. Отвечай как хороший знакомый, который реально хочет помочь."
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

def ask_ai(chat_id, user_text, image_url=None, extra_system=None):
    msgs = get_history(chat_id)
    if extra_system:
        msgs = msgs + [{"role": "system", "content": extra_system}]

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
        max_tokens=2000,
    )
    answer = response.choices[0].message.content
    msgs.append({"role": "assistant", "content": answer})
    return answer

# ================== ДЛИННЫЕ СООБЩЕНИЯ ==================

def split_message(text, limit=3500):
    """Режет длинный текст на части до 3500 символов (лимит Telegram 4096)."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1 or cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts

def smart_send(chat_id, text, reply_to=None):
    """Шлёт длинный текст по частям; при сломанном Markdown — без разметки."""
    for part in split_message(text):
        try:
            tg.send_message(chat_id, part, reply_to_message_id=reply_to)
            reply_to = None  # отвечаем только на первое сообщение
        except Exception:
            tg.send_message(chat_id, part.replace("**", ""), parse_mode=None)

# ================== ГЕНЕРАЦИЯ PDF ==================

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

def register_cyrillic_font():
    for path in FONT_PATHS:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont("Main", path))
            return "Main"
    return "Helvetica"  # запасной вариант (кириллица может не отобразиться)

def make_pdf(text, filepath):
    font = register_cyrillic_font()
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin
    max_w = width - 2 * margin

    # Простой перенос строк по ширине страницы
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            if pdfmetrics.stringWidth(test, font, 11) <= max_w:
                line = test
            else:
                if line:
                    c.setFont(font, 11)
                    c.drawString(margin, y, line)
                    y -= 16
                line = word
        if line:
            c.setFont(font, 11)
            c.drawString(margin, y, line)
            y -= 16
        y -= 6  # отбивка между абзацами

        if y < margin:
            c.showPage()
            y = height - margin

    c.save()

def send_pdf(chat_id, topic):
    tg.send_message(chat_id, f"Пишу текст по теме «{topic}» и собираю PDF... ⏳")
    extra = (
        "Напиши подробный структурированный текст по теме запроса пользователя: "
        "с заголовками, разделами и выводом. Без таблиц, без символов |, "
        "без markdown-звёздочек — простой чистый текст для документа PDF."
    )
    content = ask_ai(chat_id, topic, extra_system=extra)
    # Убираем markdown, чтобы в PDF не было звёздочек
    content = content.replace("**", "").replace("__", "")
    filepath = f"doc_{chat_id}.pdf"
    make_pdf(content, filepath)
    with open(filepath, "rb") as f:
        tg.send_document(chat_id, f, caption=f"📄 {topic}")
    os.remove(filepath)

# ================== ЧТЕНИЕ ФАЙЛОВ ОТ ПОЛЬЗОВАТЕЛЯ ==================

def read_user_file(file_info):
    """Скачивает файл и возвращает текст (.txt, .md, .pdf)."""
    downloaded = tg.download_file(file_info.file_path)
    name = (file_info.file_path or "").lower()

    if name.endswith(".pdf"):
        import fitz  # PyMuPDF
        doc = fitz.open(stream=downloaded, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    else:
        return downloaded.decode("utf-8", errors="ignore")

# ================== ОБРАБОТЧИКИ ==================

@tg.message_handler(commands=["start"])
def handle_start(message):
    history.pop(message.chat.id, None)
    smart_send(
        message.chat.id,
        "Привет! 👋 Я — твой всесторонний помощник. Вот что я умею:\n\n"
        "💬 Отвечаю на вопросы и объясняю подробно\n"
        "📸 Читаю фото с задачами и решаю пошагово\n"
        "📄 **Делаю PDF-документы** — напиши «сделай мне проект в виде файла pdf по теме ...» или команду /pdf\n"
        "📥 **Принимаю файлы** — пришли .txt, .md или PDF, и я прочитаю содержимое\n"
        "✂️ Длинные ответы сам разбиваю на несколько сообщений\n\n"
        "Что бы ты хотел сделать прямо сейчас? 🚀"
    )

@tg.message_handler(commands=["pdf"])
def handle_pdf_command(message):
    topic = message.text.replace("/pdf", "").strip()
    if not topic:
        tg.reply_to(message, "Напиши тему: /pdf вред электронных сигарет")
        return
    try:
        send_pdf(message.chat.id, topic)
    except Exception as e:
        tg.reply_to(message, f"💥 Ошибка создания PDF: {type(e).__name__}: {str(e)}", parse_mode=None)

@tg.message_handler(content_types=["text"])
def handle_text(message):
    try:
        # Если пользователь просит PDF — делаем PDF
        if "pdf" in message.text.lower() and ("файл" in message.text.lower() or "сделай" in message.text.lower()):
            send_pdf(message.chat.id, message.text)
            return
        answer = ask_ai(message.chat.id, message.text)
        smart_send(message.chat.id, answer, reply_to=message.message_id)
    except Exception as e:
        tg.reply_to(message, f"💥 Критическая ошибка: {type(e).__name__}: {str(e)}", parse_mode=None)
        print("TEXT ERROR:", e)

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
        tg.reply_to(message, f"💥 Ошибка с фото: {type(e).__name__}: {str(e)}", parse_mode=None)
        print("PHOTO ERROR:", e)

@tg.message_handler(content_types=["document"])
def handle_document(message):
    try:
        doc = message.document
        file_info = tg.get_file(doc.file_id)
        name = file_info.file_path or "file"

        if not (name.endswith(".txt") or name.endswith(".md") or name.endswith(".pdf")):
            tg.reply_to(message, "Пока читаю только .txt, .md и PDF 📄")
            return

        tg.reply_to(message, "Читаю файл... 📖")
        text = read_user_file(file_info)

        if not text.strip():
            tg.reply_to(message, "Файл пустой или не содержит текста 🤷")
            return

        # Обрезаем, если файл огромный (лимит нейросети)
        if len(text) > 15000:
            text = text[:15000] + "\n\n(текст обрезан — файл слишком большой)"

        question = message.caption or "Проанализируй содержимое файла и кратко перескажи главное."
        answer = ask_ai(message.chat.id, f"{question}\n\nСодержимое файла:\n{text}")
        smart_send(message.chat.id, answer, reply_to=message.message_id)
    except Exception as e:
        tg.reply_to(message, f"💥 Ошибка с файлом: {type(e).__name__}: {str(e)}", parse_mode=None)
        print("DOC ERROR:", e)

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
