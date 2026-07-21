# 🚂 Деплой FreelanceRadar на Railway через GitHub

## 📋 Содержание
1. [Подготовка проекта](#подготовка-проекта)
2. [Настройка GitHub](#настройка-github)
3. [Настройка Railway](#настройка-railway)
4. [Проверка и мониторинг](#проверка-и-мониторинг)
5. [Troubleshooting](#troubleshooting)

---

## 1️⃣ Подготовка проекта

### Шаг 1: Проверьте Git репозиторий

```bash
# Перейдите в директорию проекта
cd C:\Users\Пользователь\Desktop\freelance-radar

# Проверьте статус git
git status

# Если git еще не инициализирован:
git init
git add .
git commit -m "Initial commit: FreelanceRadar bot ready for deployment"
```

### Шаг 2: Создайте файл railway.json (опционально)

Railway автоматически определит Python проект, но можно настроить явно:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python main.py",
    "healthcheckPath": "/",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### Шаг 3: Создайте .railwayignore (опционально)

```
# Railway ignore file
venv/
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.so
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.db
*.db-journal
*.db-shm
*.db-wal
*.session
*.session-journal
.env
logs/
data/
debug/
test_*.py
tests/
docs/
*.md
!README.md
.git/
.github/
```

### Шаг 4: Убедитесь, что runtime.txt настроен (опционально)

Railway автоматически определит версию Python из requirements.txt, но можно указать явно:

```
python-3.11.9
```

---

## 2️⃣ Настройка GitHub

### Шаг 1: Создайте репозиторий на GitHub

1. Откройте https://github.com/new
2. Заполните:
   - **Repository name:** `freelance-radar` (или любое другое имя)
   - **Description:** `Telegram bot for freelance job monitoring with AI analysis`
   - **Visibility:** Private (рекомендуется для проектов с токенами)
3. **НЕ** выбирайте "Initialize with README" (у вас уже есть код)
4. Нажмите **Create repository**

### Шаг 2: Подключите локальный репозиторий к GitHub

```bash
# Добавьте remote origin (замените YOUR_USERNAME на ваш GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/freelance-radar.git

# Проверьте, что remote добавлен
git remote -v

# Переименуйте ветку в main (если нужно)
git branch -M main

# Отправьте код на GitHub
git push -u origin main
```

### Шаг 3: Проверьте, что код загружен

Откройте `https://github.com/YOUR_USERNAME/freelance-radar` в браузере и убедитесь, что все файлы на месте.

---

## 3️⃣ Настройка Railway

### Шаг 1: Создайте аккаунт на Railway

1. Откройте https://railway.app/
2. Нажмите **Login** → **Login with GitHub**
3. Авторизуйтесь через GitHub
4. Предоставьте Railway доступ к вашим репозиториям

### Шаг 2: Создайте новый проект

1. На главной странице Railway нажмите **New Project**
2. Выберите **Deploy from GitHub repo**
3. Найдите и выберите репозиторий `freelance-radar`
4. Railway автоматически обнаружит Python проект

### Шаг 3: Настройте переменные окружения

После создания проекта:

1. Откройте ваш проект в Railway
2. Перейдите на вкладку **Variables**
3. Добавьте следующие переменные:

```bash
# Обязательные переменные
BOT_TOKEN=your_bot_token_from_botfather
OWNER_CHAT_ID=your_telegram_user_id
OPENAI_API_KEY=your_openai_api_key

# Опциональные (если используете Telethon)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# База данных
DB_PATH=/app/data/freelance_radar.db

# Настройки парсера
KWORK_PROJECTS_URL=https://kwork.ru/projects
KWORK_REQUEST_DELAY_MIN=2.0
KWORK_REQUEST_DELAY_MAX=5.0
KWORK_MAX_PAGES=1
KWORK_MAX_DETAIL_PAGES=5

# Мониторинг
MONITOR_INTERVAL_MINUTES=15

# Другие настройки
DEFAULT_COOLDOWN_SEC=3600
```

**Как получить значения:**

- **BOT_TOKEN:** 
  1. Напишите @BotFather в Telegram
  2. Отправьте `/newbot` или `/token`
  3. Скопируйте токен

- **OWNER_CHAT_ID:**
  1. Напишите @userinfobot в Telegram
  2. Он отправит ваш ID

- **OPENAI_API_KEY:**
  1. Откройте https://platform.openai.com/api-keys
  2. Создайте новый ключ
  3. Скопируйте его (покажется только один раз!)

- **TELEGRAM_API_ID и TELEGRAM_API_HASH (опционально):**
  1. Откройте https://my.telegram.org/apps
  2. Создайте приложение
  3. Скопируйте API ID и API Hash

### Шаг 4: Настройте Volume для данных (важно!)

Railway эфемерная - файлы удаляются при каждом деплое. Нужно создать Volume:

1. В проекте перейдите на вкладку **Settings**
2. Найдите раздел **Volumes**
3. Нажмите **+ Add Volume**
4. Укажите:
   - **Mount Path:** `/app/data`
   - **Size:** 1 GB (достаточно для SQLite + логов)
5. Сохраните

### Шаг 5: Настройте Playwright

Railway должен автоматически установить системные зависимости для Playwright из Dockerfile. Если возникнут проблемы, создайте файл `nixpacks.toml`:

```toml
[phases.setup]
nixPkgs = ["python311", "playwright", "chromium"]

[phases.install]
cmds = [
  "pip install --upgrade pip",
  "pip install -r requirements.txt",
  "playwright install chromium",
  "playwright install-deps chromium"
]

[start]
cmd = "python main.py"
```

### Шаг 6: Настройте Start Command (если нужно)

Railway автоматически найдёт `main.py`, но можно указать явно:

1. Перейдите на вкладку **Settings**
2. Найдите **Start Command**
3. Укажите: `python main.py`

### Шаг 7: Задеплойте проект

1. Нажмите **Deploy** (или Railway сделает это автоматически)
2. Следите за логами в реальном времени
3. Дождитесь сообщения о успешном деплое

---

## 4️⃣ Проверка и мониторинг

### Шаг 1: Проверьте логи

1. В Railway откройте вкладку **Deployments**
2. Выберите последний деплой
3. Проверьте логи на наличие ошибок

Должны увидеть:
```
[info] bot.started interval_minutes=15
[info] Database initialized successfully
```

### Шаг 2: Проверьте бота в Telegram

1. Откройте вашего бота в Telegram
2. Отправьте `/start`
3. Должно появиться главное меню
4. Отправьте `/health` - проверьте статус

### Шаг 3: Проверьте автоматический мониторинг

1. Подождите интервал мониторинга (по умолчанию 15 минут)
2. Или отправьте `/check` для ручной проверки
3. Бот должен начать парсить вакансии

### Шаг 4: Настройте мониторинг Railway

Railway предоставляет метрики:
1. Перейдите на вкладку **Metrics**
2. Следите за:
   - CPU usage
   - Memory usage
   - Network
   - Build/Deploy time

---

## 5️⃣ Автоматические деплои

Railway автоматически деплоит при каждом push в GitHub:

```bash
# Внесите изменения в код
git add .
git commit -m "Update: улучшения фильтров"
git push origin main

# Railway автоматически:
# 1. Обнаружит новый коммит
# 2. Соберёт новый образ
# 3. Задеплоит его
# 4. Перезапустит бота
```

---

## 🔧 Troubleshooting

### Проблема: Playwright не работает

**Решение 1:** Создайте `nixpacks.toml` (см. выше)

**Решение 2:** Добавьте в переменные окружения:
```
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0
PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
```

### Проблема: База данных теряется при деплое

**Решение:** Обязательно настройте Volume (см. Шаг 4 настройки Railway)

### Проблема: Телефонный код для Telethon

Если используете Telethon для парсинга Telegram, при первом запуске потребуется ввести код:

**Решение:** 
1. Используйте HTTP парсер (по умолчанию)
2. Или создайте сессию локально и загрузите в Volume:
   ```bash
   # Локально запустите бота один раз
   python main.py
   # Введите код
   
   # Загрузите сессию на Railway через Volume
   ```

### Проблема: Out of Memory

**Решение:** Увеличьте лимиты в Railway или оптимизируйте настройки:
```bash
# Уменьшите параметры парсинга
KWORK_MAX_PAGES=1
KWORK_MAX_DETAIL_PAGES=3
MONITOR_INTERVAL_MINUTES=30
```

### Проблема: Бот не отвечает

**Проверки:**
1. Логи Railway - есть ли ошибки?
2. `/health` в Telegram - работает ли бот?
3. Переменные окружения - правильно ли указаны?
4. BOT_TOKEN - не истёк ли?

---

## 💰 Тарифы Railway

**Hobby Plan (Free):**
- $5 в месяц в виде кредитов
- ~500 часов работы
- 512 MB RAM
- 1 GB Volume
- **Достаточно для этого бота!**

**Developer Plan ($20/месяц):**
- $20 в месяц в виде кредитов
- Больше ресурсов
- Приоритетная поддержка

---

## 📊 Рекомендуемые настройки для Railway

```bash
# Оптимизация для Railway
MONITOR_INTERVAL_MINUTES=15
KWORK_MAX_PAGES=1
KWORK_MAX_DETAIL_PAGES=5
DEFAULT_COOLDOWN_SEC=3600
```

---

## 🔐 Безопасность

1. ✅ Используйте Private репозиторий на GitHub
2. ✅ Храните токены только в Railway Variables (не в коде!)
3. ✅ Не коммитьте `.env` файл в git
4. ✅ Регулярно ротируйте API ключи
5. ✅ Включите 2FA на GitHub и Railway

---

## 🎉 Готово!

После выполнения всех шагов ваш бот будет:
- ✅ Автоматически деплоиться при push в GitHub
- ✅ Работать 24/7 на Railway
- ✅ Сохранять данные в Volume
- ✅ Логировать всё в Railway
- ✅ Автоматически перезапускаться при ошибках

**Наслаждайтесь автоматическим мониторингом вакансий! 🚀**

---

## 📞 Полезные ссылки

- Railway Dashboard: https://railway.app/dashboard
- Railway Docs: https://docs.railway.app/
- GitHub Repo: https://github.com/YOUR_USERNAME/freelance-radar
- Telegram Bot API: https://core.telegram.org/bots/api
- OpenAI API: https://platform.openai.com/docs/api-reference

---

## 🆘 Поддержка

При возникновении проблем:
1. Проверьте логи в Railway
2. Проверьте `/health` в боте
3. Проверьте Variables в Railway
4. Проверьте GitHub Actions (если настроены)
5. Проверьте документацию Railway

**Удачного деплоя! 🎊**
