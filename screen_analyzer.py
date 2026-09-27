#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║   🌍  GEO SCREEN ANALYZER  —  анализатор экрана              ║
║                                                              ║
║   Горячая клавиша:  Alt + X                                  ║
║                                                              ║
║   1. Делает снимок всего экрана                              ║
║   2. Распознаёт текст (Tesseract OCR, rus+eng)               ║
║   3. Отправляет текст в LLM через агрегатор Polza AI         ║
║      (OpenAI-совместимый API)                                ║
║   4. Модель отвечает:  СТРАНА  и  ГОРОД этой страницы        ║
║   5. Красивое всплывающее окно с результатом                 ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys
import queue
import textwrap

# ══════════════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════════════════════════

HOTKEY          = "alt+x"
OCR_LANGS       = "rus+eng"
TESS_CMD_WIN    = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

API_BASE_URL    = os.environ.get("API_BASE_URL", "https://api.polza.ai/v1")
MODEL_NAME      = os.environ.get("POLZA_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "Ты — геолокационный аналитик. Тебе передаётся текст, распознанный "
    "со скриншота веб-страницы или приложения. Твоя задача — определить:\n"
    "1) СТРАНУ, к которой относится содержимое страницы;\n"
    "2) ГОРОД, который указан или подразумевается на странице.\n\n"
    "Используй подсказки: домены (.ru, .kz, .by...), языки, валюты, "
    "телефонные коды, адреса, названия улиц и организаций.\n\n"
    "Формат ответа (строго):\n"
    "Страна: <название страны>\n"
    "Город: <название города>\n"
    "Обоснование: <1–2 предложения, почему так решили>\n\n"
    "Если страну или город определить невозможно, напиши «не определено»."
)

# ── цвета интерфейса (Catppuccin Mocha) ───────────────────────
C_BG        = "#1e1e2e"   # фон окна
C_CARD      = "#2a2a40"   # карточки
C_ACCENT    = "#89b4fa"   # акцент (синий)
C_GREEN     = "#a6e3a1"   # успех
C_YELLOW    = "#f9e2af"   # внимание
C_TEXT      = "#cdd6f4"   # основной текст
C_SUBTEXT   = "#7f849c"   # второстепенный текст
C_BORDER    = "#45475a"


# ══════════════════════════════════════════════════════════════
#  ЗАВИСИМОСТИ
# ══════════════════════════════════════════════════════════════

def _die(pkg: str):
    print(f"❌ Не установлен пакет '{pkg}'. Установите: pip install {pkg}")
    sys.exit(1)

try:
    import keyboard
except ImportError:
    _die("keyboard")

try:
    from PIL import ImageGrab
except ImportError:
    _die("pillow")

try:
    import pytesseract
except ImportError:
    _die("pytesseract")

try:
    import requests
except ImportError:
    _die("requests")


# ══════════════════════════════════════════════════════════════
#  ЛОГИКА
# ══════════════════════════════════════════════════════════════

def setup_tesseract():
    """Подбирает путь к tesseract под Windows."""
    if sys.platform.startswith("win") and os.path.exists(TESS_CMD_WIN):
        pytesseract.pytesseract.tesseract_cmd = TESS_CMD_WIN


def load_env(path=".env"):
    """Мини-загрузчик .env без внешних зависимостей."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def take_screenshot():
    log("📸  Делаю снимок экрана...")
    return ImageGrab.grab(all_screens=True)


def ocr_image(image) -> str:
    log("🔍  Распознаю текст (OCR)...")
    try:
        return pytesseract.image_to_string(image, lang=OCR_LANGS).strip()
    except pytesseract.TesseractNotFoundError:
        return "__NO_TESSERACT__"


def ask_llm(text: str) -> str:
    api_key = os.environ.get("POLZA_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ("⚠️  Не задан ключ Polza AI.\n"
                "Скопируйте .env.example → .env и заполните POLZA_API_KEY.")

    url = API_BASE_URL.rstrip("/") + "/chat/completions"
    log(f"🤖  Запрос в модель «{MODEL_NAME}» (Polza AI)...")

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        f"Текст со скриншота:\n\"\"\"\n{text[:6000]}\n\"\"\""},
                ],
                "temperature": 0.2,
            },
            timeout=120,
        )
    except requests.RequestException as e:
        return f"🌐 Сетевая ошибка: {e}"

    if resp.status_code != 200:
        return (f"⚠️ Polza AI вернул HTTP {resp.status_code}:\n"
                f"{textwrap.shorten(resp.text, 400)}\n"
                "Проверьте ключ и название модели.")

    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError):
        return "⚠️ Не удалось разобрать ответ модели."


def parse_answer(answer: str) -> tuple[str, str, str]:
    """Вытаскивает из ответа модели Страна / Город / Обоснование.

    Устойчив к Markdown-разметке вида «**Страна:** Россия».
    """
    def clean(s: str) -> str:
        return s.replace("**", "").replace("__", "").strip(" \t#:*>-")

    country = city = reason = ""
    for line in answer.splitlines():
        low = clean(line).lower()
        if ":" not in line:
            continue
        value = clean(line.split(":", 1)[1])
        if low.startswith(("страна", "country")) and not country:
            country = value
        elif low.startswith(("город", "city")) and not city:
            city = value
        elif low.startswith(("обоснование", "почему", "reason")) and not reason:
            reason = value
    return country or "—", city or "—", reason


# ══════════════════════════════════════════════════════════════
#  КОНСОЛЬ
# ══════════════════════════════════════════════════════════════

def log(msg: str):
    print(f"  {msg}")


BANNER = r"""
   ██████╗ ███████╗ ██████╗  █████╗
  ██╔════╝ ██╔════╝██╔═══██╗██╔══██╗
  ██║  ███╗█████╗  ██║   ██║███████║
  ██║   ██║██╔══╝  ██║   ██║██╔══██║
  ╚██████╔╝███████╗╚██████╔╝██║  ██║
   ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝   S C R E E N  A N A L Y Z E R
"""


# ══════════════════════════════════════════════════════════════
#  GUI — красивое тёмное окно результата
# ══════════════════════════════════════════════════════════════

result_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
busy_flag = False


def show_result_window(answer: str, raw_text: str):
    import tkinter as tk

    country, city, reason = parse_answer(answer)

    root = tk.Tk()
    root.title("🌍 Geo Screen Analyzer")
    root.configure(bg=C_BG)
    root.attributes("-topmost", True)
    root.geometry("620x540")
    root.resizable(False, False)

    def card(parent, y, title, value, color):
        frm = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER,
                       highlightthickness=1)
        frm.place(x=20, y=y, width=580, height=64)
        tk.Label(frm, text=title, bg=C_CARD, fg=C_SUBTEXT,
                 font=("Segoe UI", 9)).place(x=14, y=8)
        tk.Label(frm, text=value, bg=C_CARD, fg=color, wraplength=550,
                 justify="left", anchor="w",
                 font=("Segoe UI", 14, "bold")).place(x=14, y=28,
                                                      relwidth=0.95)

    # заголовок
    head = tk.Frame(root, bg=C_BG)
    head.place(x=0, y=0, width=620, height=72)
    tk.Label(head, text="🌍 РЕЗУЛЬТАТ АНАЛИЗА ЭКРАНА", bg=C_BG, fg=C_TEXT,
             font=("Segoe UI", 15, "bold")).pack(pady=(18, 2))
    tk.Label(head, text=f"модель: {MODEL_NAME} · Polza AI", bg=C_BG,
             fg=C_SUBTEXT, font=("Segoe UI", 9)).pack()

    # карточки Страна / Город
    card(root, 82,  "🏳️  СТРАНА", country, C_GREEN)
    card(root, 154, "🏙️  ГОРОД",  city,    C_ACCENT)

    y_raw = 236
    if reason:
        frm = tk.Frame(root, bg=C_CARD, highlightbackground=C_BORDER,
                       highlightthickness=1)
        frm.place(x=20, y=226, width=580, height=58)
        tk.Label(frm, text="💡 ОБОСНОВАНИЕ", bg=C_CARD, fg=C_SUBTEXT,
                 font=("Segoe UI", 9)).place(x=14, y=6)
        tk.Label(frm, text=textwrap.shorten(reason, 150, placeholder=" …"),
                 bg=C_CARD, fg=C_YELLOW, wraplength=550, justify="left",
                 anchor="w", font=("Segoe UI", 10)).place(x=14, y=24,
                                                          relwidth=0.95)
        y_raw = 296

    # OCR-текст
    tk.Label(root, text="Распознанный текст (OCR):", bg=C_BG, fg=C_SUBTEXT,
             font=("Segoe UI", 9, "bold")).place(x=20, y=y_raw)

    txt = tk.Text(root, wrap="word", bg=C_CARD, fg=C_TEXT,
                  insertbackground=C_TEXT, relief="flat",
                  highlightbackground=C_BORDER, highlightthickness=1,
                  font=("Consolas", 9))
    txt.place(x=20, y=y_raw + 22, width=580, height=140)
    txt.insert("1.0", raw_text[:2500] or "(текст не распознан)")
    txt.config(state="disabled")

    # кнопка закрытия
    tk.Button(root, text="✖  Закрыть", command=root.destroy,
              bg=C_ACCENT, fg=C_BG, activebackground="#74a8fc",
              relief="flat", font=("Segoe UI", 10, "bold"),
              cursor="hand2", bd=0).place(x=250, y=488, width=120, height=36)

    root.mainloop()


# ══════════════════════════════════════════════════════════════
#  ОСНОВНОЙ ЦИКЛ
# ══════════════════════════════════════════════════════════════

def on_hotkey():
    global busy_flag
    if busy_flag:
        log("⏳  Анализ уже выполняется, подождите...")
        return
    busy_flag = True
    try:
        image = take_screenshot()
        text = ocr_image(image)
        if text == "__NO_TESSERACT__":
            answer = ("⚠️ Tesseract OCR не найден.\n"
                      "Установите его и/или укажите путь в TESS_CMD_WIN.")
            raw = ""
        elif not text:
            answer = ("Страна: не определено\nГород: не определено\n"
                      "На экране не удалось распознать текст.")
            raw = ""
        else:
            answer = ask_llm(text)
            raw = text
        print("\n" + "─" * 50 + f"\n{answer}\n" + "─" * 50)
        result_queue.put((answer, raw))
    except Exception as e:
        result_queue.put((f"❌ Ошибка: {e}", ""))
    finally:
        busy_flag = False


def gui_loop():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    def poll():
        try:
            while True:
                ans, raw = result_queue.get_nowait()
                show_result_window(ans, raw)
        except queue.Empty:
            pass
        root.after(300, poll)

    root.after(300, poll)
    root.mainloop()


def main():
    setup_tesseract()
    load_env()

    print(BANNER)
    print("  ┌───────────────────────────────────────────────┐")
    print("  │  Нажмите  Alt + X  — определение СТРАНЫ       │")
    print("  │  и ГОРОДА со скриншота текущего экрана        │")
    print("  │                                               │")
    print("  │  API:     Polza AI                            │")
    print(f"  │  Модель:  {MODEL_NAME:<31}│")
    print("  │  Выход:   Ctrl + C                            │")
    print("  └───────────────────────────────────────────────┘\n")

    keyboard.add_hotkey(HOTKEY, on_hotkey)
    try:
        gui_loop()
    except KeyboardInterrupt:
        print("\n👋  Пока!")
        keyboard.unhook_all_hotkeys()


if __name__ == "__main__":
    main()
