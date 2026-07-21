# ⚡ OpenRouter Quick Start - 3 минуты

## 🎯 Быстрая настройка OpenRouter для FreelanceRadar

### Шаг 1: Получите ключ (1 минута)

1. Откройте: **https://openrouter.ai/**
2. **Sign In** → через Google/GitHub
3. **Keys**: https://openrouter.ai/keys
4. **Create Key** → скопируйте (`sk-or-v1-xxxxx`)

Опционально: добавьте кредиты ($5) в https://openrouter.ai/credits

---

### Шаг 2: Настройте бота (30 секунд)

#### Локально (.env файл):
```bash
OPENAI_API_KEY=sk-or-v1-ваш_ключ_сюда
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4o-mini
```

#### Railway (Variables):
```
OPENAI_API_KEY = sk-or-v1-ваш_ключ_сюда
OPENAI_BASE_URL = https://openrouter.ai/api/v1
OPENAI_MODEL = openai/gpt-4o-mini
```

---

### Шаг 3: Перезапустите (30 секунд)

```bash
# Локально
python main.py

# Railway
# Автоматически перезапустится после изменения Variables
```

---

### Шаг 4: Проверьте (30 секунд)

В логах должно быть:
```
[info] ai.provider_initialized provider=OpenRouter model=openai/gpt-4o-mini
```

В Telegram отправьте `/check` - бот проанализирует вакансии через OpenRouter!

---

## 🎉 Готово!

**Теперь вы используете OpenRouter и экономите до 50% на AI запросах!**

### 💰 Рекомендуемые модели:

| Модель | Стоимость | Качество |
|--------|-----------|----------|
| `openai/gpt-4o-mini` | $1/мес | ⭐⭐⭐⭐ (рекомендуется) |
| `anthropic/claude-3.5-sonnet` | $15/мес | ⭐⭐⭐⭐⭐ (премиум) |
| `google/gemini-flash-1.5` | БЕСПЛАТНО | ⭐⭐⭐ (для тестов) |

### 📊 Мониторинг:
- Dashboard: https://openrouter.ai/activity
- Команда в боте: `/health`

### 📚 Подробнее:
- **OPENROUTER_SETUP.md** - полное руководство
- **OPENROUTER_MIGRATION.md** - что изменилось

---

## 🔄 Вернуться к OpenAI?

Просто удалите `OPENAI_BASE_URL`:
```bash
OPENAI_API_KEY=sk-proj-ваш_openai_ключ
OPENAI_MODEL=gpt-4o-mini
# Удалите или закомментируйте OPENAI_BASE_URL
```

**Успехов! 🚀**
