#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Мини-программа «Анализатор экрана».

Как это работает:
  1. Программа ждёт нажатие горячей клавиши Alt+X.
  2. Делает снимок всего экрана.
  3. Распознаёт текст на снимке (OCR через Tesseract).
  4. Отправляет распознанный текст в LLM (OpenAI или любой совместимый API)
     вместе с системным промптом, который просит определить,
     что это за страница и какой город на ней указан.
  5. Показывает ответ во всплывающем окне (Tkinter) и дублирует в консоль.

Требования:
  pip install keyboard pillow pytesseract openai
  + системная зависимость Tesseract OCR:
      Ubuntu/Debian : sudo apt install tesseract-ocr tesseract-ocr-rus
      macOS         : brew install tesseract tesseract-lang
      Windows       : https://github.com/UB-Mannheim/tesseract/wiki
                      (не забудьте указать путь в TESSERACT_CMD ниже)

Запуск:
  python screen_analyzer.py
  (в Linux для работы модуля keyboard могут потребоваться права root:
   sudo python3 screen_analyzer.py)

Настройки API-ключа берутся из переменных окружения OPENAI_API_KEY / OPENAI_BASE_URL
или из файла .env рядом со скриптом.
"""

import os
import sys
import threading
import queue

# ---------------------------------------------------------------------------
# Настройки — можно поменять под себя
# ---------------------------------------------------------------------------

# Системный промпт для модели: именно здесь задаётся вопрос
SYSTEM_PROMPT = (
    "Ты — помощник, который анализирует текст, распознанный со скриншота экрана. "
    "По предоставленному тексту определи: "
    "1) что это за страница (тип сайта/раздела, например: карточка товара, "
    "главная страница, объявление о недвижимости, меню ресторана и т.п.); "
    "2) какой город упоминается или подразумевается на этой странице. "
    "Ответ дай кратко, на русском языке, в формате:\n"
    "Страница: <что это>\n"
    "Город: <город>\n"
    "Если определить не удалось — честно напиши об этом."
)

# Язык OCR через запятую (rus+eng — русский и английский)
OCR_LANGS = "rus+eng"

# Путь к tesseract.exe (актуально для Windows). На Linux/macOS обычно не нужен.
TESSERACT_CMD_WINDOWS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

HOTKEY = "alt+x"          # комбинация клавиш для запуска анализа
MODEL_NAME = "gpt-4o-mini"  # модель OpenAI (или совместимого API)

# ---------------------------------------------------------------------------
# Импорт зависимостей с понятными ошибками
# ---------------------------------------------------------------------------

def _missing(pkg: str, pip_name: str = None):
    print(f"[ОШИБКА] Не установлен пакет '{pip_name or pkg}'. "
          f"Установите его командой: pip install {pip_name or pkg}")
    sys.exit(1)

try:
    import keyboard
except ImportError:
    _missing("keyboard")

try:
    from PIL import ImageGrab
except ImportError:
    _missing("Pillow", "pillow")

try:
    import pytesseract
except ImportError:
    _missing("pytesseract")

try:
    from openai import OpenAI
except ImportError:
    _missing("openai")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def setup_tesseract():
    """Настраиваем путь к tesseract под Windows, если он там существует."""
    if sys.platform.startswith("win") and os.path.exists(TESSERACT_CMD_WINDOWS):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_WINDOWS


def load_env_file(path=".env"):
    """Мини-загрузчик .env (без внешних зависимостей)."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def take_screenshot():
    """Делает снимок всего экрана и возвращает объект PIL.Image."""
    print("[...]: делаю снимок экрана...")
    return ImageGrab.grab(all_screens=True)


def ocr_image(image) -> str:
    """Распознаёт текст на изображении."""
    print("[...]: распознаю текст (OCR)...")
    try:
        text = pytesseract.image_to_string(image, lang=OCR_LANGS)
    except pytesseract.TesseractNotFoundError:
        print("[ОШИБКА] Tesseract OCR не найден в системе. Установите его "
              "или укажите правильный путь в TESSERACT_CMD_WINDOWS.")
        sys.exit(1)
    return text.strip()


def ask_llm(recognized_text: str) -> str:
    """Отправляет распознанный текст в LLM с системным промптом."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ("Не задан API-ключ. Положите его в файл .env "
                "(OPENAI_API_KEY=sk-...) или экспортируйте переменную "
                "окружения OPENAI_API_KEY.")

    kwargs = {"api_key": api_key}
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:  # для локальных/сторонних эндпоинтов (Ollama, OpenRouter и т.п.)
        kwargs["base_url"] = base_url

    client = OpenAI(**kwargs)

    print("[...]: отправляю текст в модель...")
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Текст со скриншота:\n" + recognized_text},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def show_result_window(answer: str, raw_text: str):
    """Показывает ответ в маленьком окне Tkinter поверх всех окон."""
    import tkinter as tk

    root = tk.Tk()
    root.title("Результат анализа экрана")
    root.attributes("-topmost", True)
    root.geometry("560x420")

    frame = tk.Frame(root, padx=12, pady=12)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Ответ модели:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    txt = tk.Text(frame, wrap="word", height=8, font=("Segoe UI", 11))
    txt.pack(fill="x", pady=(2, 10))
    txt.insert("1.0", answer)
    txt.config(state="disabled")

    tk.Label(frame, text="Распознанный текст (OCR):",
             font=("Segoe UI", 10, "bold")).pack(anchor="w")
    raw = tk.Text(frame, wrap="word", height=10, font=("Segoe UI", 9))
    raw.pack(fill="both", expand=True, pady=(2, 10))
    raw.insert("1.0", raw_text[:3000])
    raw.config(state="disabled")

    tk.Button(frame, text="Закрыть", command=root.destroy, width=12).pack()

    root.mainloop()


# ---------------------------------------------------------------------------
# Основная логика: хоткей -> скриншот -> OCR -> LLM -> окно с ответом
# ---------------------------------------------------------------------------

result_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def on_hotkey():
    """Вызывается по нажатию Alt+X в отдельном потоке."""
    try:
        image = take_screenshot()
        text = ocr_image(image)
        if not text:
            answer = "Не удалось распознать никакой текст на экране."
        else:
            answer = ask_llm(text)
        result_queue.put((answer, text))
    except Exception as e:  # чтобы программа не падала от ошибок в потоке
        result_queue.put((f"Произошла ошибка: {e}", ""))


def gui_loop():
    """Главный поток: крутит Tkinter и ждёт результатов из очереди."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # скрытое «корневое» окно, нужное для работы after()

    def poll():
        try:
            while True:
                answer, raw = result_queue.get_nowait()
                show_result_window(answer, raw)
        except queue.Empty:
            pass
        root.after(300, poll)  # проверяем очередь каждые 300 мс

    root.after(300, poll)
    root.mainloop()


def main():
    setup_tesseract()
    load_env_file()

    print("=" * 60)
    print(" Анализатор экрана запущен.")
    print(f" Нажмите {HOTKEY.upper()} — будет сделан снимок экрана,")
    print(" распознан текст и отправлен в модель с вопросом:")
    print('   "Какая это страница и какой город?"')
    print(" Ctrl+C — выход.")
    print("=" * 60)

    keyboard.add_hotkey(HOTKEY, on_hotkey)

    try:
        gui_loop()  # блокирующий цикл Tkinter в главном потоке
    except KeyboardInterrupt:
        print("\nВыход.")
        keyboard.unhook_all_hotkeys()


if __name__ == "__main__":
    main()
