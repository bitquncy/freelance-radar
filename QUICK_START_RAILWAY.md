# ⚡ Быстрый старт: Деплой на Railway за 5 минут

## Шаг 1: Подготовка (2 минуты)

### 1.1 Получите необходимые токены

**Telegram Bot Token:**
```
1. Откройте @BotFather в Telegram
2. Отправьте: /newbot
3. Следуйте инструкциям
4. Скопируйте токен (например: 1234567890:ABCdef...)
```

**Ваш Telegram ID:**
```
1. Откройте @userinfobot в Telegram
2. Он сразу пришлёт ваш ID (например: 123456789)
```

**OpenAI API Key:**
```
Вариант 1 - OpenAI (прямой API):
1. Откройте: https://platform.openai.com/api-keys
2. Создайте новый ключ
3. Скопируйте ключ (показывается только один раз!)
4. Используйте: BOT_TOKEN=sk-proj-xxxxxxxx

Вариант 2 - OpenRouter (дешевле, больше моделей):
1. Откройте: https://openrouter.ai/
2. Sign In → Keys: https://openrouter.ai/keys
3. Create Key → Скопируйте
4. Используйте: 
   OPENAI_API_KEY=sk-or-v1-xxxxxxxx
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_MODEL=openai/gpt-4o-mini

Подробнее об OpenRouter: см. OPENROUTER_SETUP.md
```

---

## Шаг 2: GitHub (1 минута)

```bash
# В терминале выполните:
cd C:\Users\Пользователь\Desktop\freelance-radar

# Инициализируйте git (если не сделано)
git init

# Добавьте все файлы
git add .

# Сделайте коммит
git commit -m "Initial commit: Ready for Railway deployment"

# Создайте репозиторий на GitHub (замените YOUR_USERNAME):
# https://github.com/new

# Подключите remote
git remote add origin https://github.com/YOUR_USERNAME/freelance-radar.git

# Отправьте код
git branch -M main
git push -u origin main
```

---

## Шаг 3: Railway (2 минуты)

### 3.1 Создайте проект

1. Откройте: https://railway.app/
2. Нажмите **Login with GitHub**
3. Нажмите **New Project** → **Deploy from GitHub repo**
4. Выберите репозиторий `freelance-radar`

### 3.2 Создайте Volume

1. В проекте откройте **Settings**
2. Найдите раздел **Volumes**
3. Нажмите **+ Add Volume**
4. Укажите:
   - Mount Path: `/app/data`
   - Size: `1 GB`

### 3.3 Добавьте переменные окружения

1. Откройте вкладку **Variables**
2. Нажмите **+ New Variable** и добавьте:

```bash
BOT_TOKEN=ваш_токен_от_botfather
OWNER_CHAT_ID=ваш_telegram_id
OPENAI_API_KEY=ваш_openai_или_openrouter_ключ
DB_PATH=/app/data/freelance_radar.db

# Для OpenRouter (опционально, дешевле):
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4o-mini
```

### 3.4 Задеплойте

Railway автоматически начнёт деплой! Дождитесь завершения (2-3 минуты).

---

## Шаг 4: Проверка (30 секунд)

1. Откройте вашего бота в Telegram
2. Отправьте: `/start`
3. Вы должны увидеть главное меню! 🎉

---

## 🎊 Готово!

Ваш бот работает на Railway 24/7!

### Что дальше?

1. **Настройте профиль:** Нажмите "👤 Профиль" в боте
2. **Добавьте источники:** Нажмите "📡 Источники"
3. **Настройте фильтры:** Нажмите "⚙️ Настройки"

### Полезные команды:

- `/health` - статус системы
- `/stats` - статистика вакансий
- `/check` - ручная проверка источников

---

## 🔄 Обновление бота

После изменений в коде:

```bash
git add .
git commit -m "Update: описание изменений"
git push origin main
```

Railway автоматически задеплоит новую версию!

---

## 📊 Мониторинг

- **Логи:** Railway Dashboard → Deployments → View Logs
- **Метрики:** Railway Dashboard → Metrics
- **Статус:** `/health` в боте

---

## ⚠️ Если что-то не работает

1. **Проверьте логи в Railway**
2. **Проверьте Variables (все ли заполнены?)**
3. **Проверьте Volume (создан ли?)**
4. **Отправьте `/health` в бота**

---

## 💰 Стоимость

Railway предоставляет **$5 бесплатных кредитов** в месяц.

Этот бот потребляет примерно:
- **RAM:** 128-256 MB
- **CPU:** минимально
- **Стоимость:** ~$3-4/месяц

**Хватит на бесплатном тарифе!** 🎉

---

## 🆘 Нужна помощь?

Смотрите полную инструкцию в файле `RAILWAY_DEPLOY.md`

**Успешного деплоя! 🚀**
