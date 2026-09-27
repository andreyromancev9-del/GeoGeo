# Анализатор экрана (Alt+X → скриншот → OCR → Polza AI)

Мини-программа: по нажатию **Alt+X** делает снимок экрана, распознаёт текст
(Tesseract OCR) и отправляет его в LLM через агрегатор **Polza AI** с системным
промптом «какая это страница и какой город?». Ответ показывается в окне.

---

## 1. Установка Python-зависимостей

Желательно создать виртуальное окружение:

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

Пакеты: `keyboard`, `pillow`, `pytesseract`, `requests`.

## 2. Установка Tesseract OCR (системная программа)

### Windows
1. Скачайте установщик: https://github.com/UB-Mannheim/tesseract/wiki
2. При установке отметьте язык **Russian** (Additional language data → rus).
3. По умолчанию путь `C:\Program Files\Tesseract-OCR\tesseract.exe` — скрипт
   подхватывает его сам. Если ставили в другое место — поменяйте
   `TESSERACT_CMD_WINDOWS` в начале `screen_analyzer.py`.

### Ubuntu / Debian
```bash
sudo apt install tesseract-ocr tesseract-ocr-rus
```

### macOS
```bash
brew install tesseract tesseract-lang
```

Проверка: `tesseract --version` и `tesseract --list-langs` (должен быть `rus`).

## 3. Ключ Polza AI

1. Зарегистрируйтесь на https://polza.ai и получите API-ключ в личном кабинете.
2. Скопируйте файл `.env.example` в `.env` и впишите ключ:

```bash
# Windows:
copy .env.example .env
# Linux/macOS:
cp .env.example .env
```

```
POLZA_API_KEY=sk-...ваш_ключ...
```

3. Модель задаётся в начале `screen_analyzer.py` (`MODEL_NAME = "gpt-4o-mini"`).
   Если Polza AI отдаёт список моделей, можно проверить так:

```bash
curl -H "Authorization: Bearer ВАШ_КЛЮЧ" https://api.polza.ai/v1/models
```

(точным эндпоинтом сверьтесь в документации Polza AI — при необходимости
поправьте `API_BASE_URL` в скрипте или в `.env`)

## 4. Запуск

```bash
# Windows (из активированного venv):
python screen_analyzer.py

# Linux (модулю keyboard нужны права на /dev/input):
sudo python3 screen_analyzer.py
# либо без sudo, добавив пользователя в группу input:
sudo usermod -aG input $USER   # затем перезайти в систему
```

В консоли появится сообщение «Анализатор экрана запущен». Откройте нужную
страницу/окно и нажмите **Alt+X** → через несколько секунд появится окно
с ответом («Страница: …», «Город: …») и распознанным текстом.

Выход — **Ctrl+C** в консоли.

## 5. Частые проблемы

| Симптом | Решение |
|---|---|
| `Не установлен пакет 'keyboard'` | `pip install keyboard` (проверьте, что venv активирован) |
| `Tesseract OCR не найден` | Установите Tesseract (шаг 2) или поправьте путь в скрипте |
| OCR не читает русский | Установите языковой пакет `rus` (`tesseract --list-langs`) |
| Ошибка 401/403 от Polza AI | Проверьте `POLZA_API_KEY` в `.env` |
| Ошибка 404 / «model not found» | Проверьте `MODEL_NAME` и `API_BASE_URL` (эндпоинты смотрите в докам Polza AI) |
| Alt+X не реагирует (Linux) | Запустите через sudo или добавьте в группу `input`; на Wayland может не работать — используйте X11 |
| Экран не захватывается (Windows, удалённый рабочий стол/UAC) | Запускайте от обычного пользователя, не от админа, либо запускайте в той же сессии |

## 6. Настройки в `screen_analyzer.py`

- `SYSTEM_PROMPT` — вопрос модели («какая страница и какой город»), меняйте под себя;
- `HOTKEY` — комбинация (по умолчанию `alt+x`);
- `OCR_LANGS` — языки OCR (`rus+eng`);
- `MODEL_NAME`, `API_BASE_URL` — модель и эндпоинт Polza AI.
