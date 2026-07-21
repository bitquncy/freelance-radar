# 🌐 Настройка OpenRouter для FreelanceRadar

## Что такое OpenRouter?

**OpenRouter** — это унифицированный API для доступа к множеству AI моделей (OpenAI, Anthropic, Google, Meta и др.) через единый интерфейс.

### Преимущества OpenRouter:

✅ **Дешевле**: цены ниже, чем напрямую у OpenAI  
✅ **Больше моделей**: доступ к 100+ моделям  
✅ **Единый API**: совместим с OpenAI SDK  
✅ **Бесплатные модели**: есть бесплатные варианты для тестирования  
✅ **Гибкость**: легко переключаться между моделями

---

## 📝 Получение API ключа OpenRouter

### Шаг 1: Регистрация

1. Откройте: https://openrouter.ai/
2. Нажмите **Sign In** (можно через Google/GitHub)
3. Перейдите в раздел **Keys**: https://openrouter.ai/keys

### Шаг 2: Создание ключа

1. Нажмите **Create Key**
2. Дайте ключу имя (например: `freelance-radar`)
3. Установите лимит (например: $5/месяц)
4. Нажмите **Create**
5. **Скопируйте ключ** (показывается только один раз!)

Ключ выглядит так: `sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### Шаг 3: Пополнение баланса (опционально)

1. Перейдите в **Credits**: https://openrouter.ai/credits
2. Добавьте кредиты (от $5)
3. Некоторые модели бесплатные!

---

## ⚙️ Конфигурация FreelanceRadar

### Вариант 1: Локальная настройка (.env файл)

Отредактируйте файл `.env`:

```bash
# AI Configuration - OpenRouter
OPENAI_API_KEY=sk-or-v1-ваш_ключ_openrouter
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=anthropic/claude-3.5-sonnet
```

### Вариант 2: Railway

В Railway → Variables добавьте:

```bash
OPENAI_API_KEY=sk-or-v1-ваш_ключ_openrouter
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=anthropic/claude-3.5-sonnet
```

### Вариант 3: Docker

В `docker-compose.yml` добавьте в `environment`:

```yaml
environment:
  - OPENAI_API_KEY=sk-or-v1-ваш_ключ_openrouter
  - OPENAI_BASE_URL=https://openrouter.ai/api/v1
  - OPENAI_MODEL=anthropic/claude-3.5-sonnet
```

---

## 🎯 Рекомендуемые модели

### Для FreelanceRadar (анализ + генерация откликов):

#### 1. **Бюджетный вариант** (~$0.15-0.30/1000 сообщений)
```bash
OPENAI_MODEL=openai/gpt-4o-mini
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```
- Быстрая модель OpenAI
- Дешевле прямого API OpenAI
- Отлично подходит для вакансий

#### 2. **Оптимальный вариант** (~$3-5/1000 сообщений)
```bash
OPENAI_MODEL=anthropic/claude-3.5-sonnet
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```
- Высокое качество анализа
- Отличное понимание контекста
- Лучше генерирует отклики

#### 3. **Премиум вариант** (~$15-30/1000 сообщений)
```bash
OPENAI_MODEL=openai/gpt-4o
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```
- Максимальное качество
- Самая умная модель
- Для критичных задач

#### 4. **Бесплатные модели** (для тестирования)
```bash
# Google Gemini Flash (бесплатно)
OPENAI_MODEL=google/gemini-flash-1.5
OPENAI_BASE_URL=https://openrouter.ai/api/v1

# Meta Llama (бесплатно)
OPENAI_MODEL=meta-llama/llama-3.2-3b-instruct:free
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

---

## 💰 Сравнение стоимости

### Типичное использование FreelanceRadar:
- ~50 вакансий в день
- ~2 анализа + 1 отклик = 3 запроса/вакансия
- ~150 запросов/день = 4500 запросов/месяц

### Стоимость по моделям:

| Модель | Стоимость/месяц | Качество |
|--------|----------------|----------|
| **openai/gpt-4o-mini** | $0.70-1.50 | ⭐⭐⭐⭐ |
| **anthropic/claude-3.5-sonnet** | $13-22 | ⭐⭐⭐⭐⭐ |
| **openai/gpt-4o** | $70-135 | ⭐⭐⭐⭐⭐ |
| **google/gemini-flash-1.5** | БЕСПЛАТНО | ⭐⭐⭐ |

**Рекомендация**: Начните с `openai/gpt-4o-mini` — оптимальный баланс цены и качества!

---

## 🔄 Переключение обратно на OpenAI

Если хотите вернуться к прямому API OpenAI:

```bash
# В .env файле или Railway Variables
OPENAI_API_KEY=sk-proj-ваш_ключ_openai
# Удалите или закомментируйте:
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=gpt-4o-mini
```

Или просто не указывайте `OPENAI_BASE_URL` — бот автоматически использует OpenAI.

---

## 📊 Мониторинг использования

### OpenRouter Dashboard:
1. Откройте: https://openrouter.ai/activity
2. Смотрите:
   - Количество запросов
   - Потраченные кредиты
   - Использованные модели
   - Статистика по дням

### В боте:
- Логи показывают провайдера: `ai.provider_initialized provider=OpenRouter`
- Команда `/health` показывает статус AI

---

## 🔍 Полный список моделей

Все доступные модели: https://openrouter.ai/models

### Популярные для задач FreelanceRadar:

```bash
# OpenAI
openai/gpt-4o
openai/gpt-4o-mini
openai/gpt-4-turbo

# Anthropic Claude
anthropic/claude-3.5-sonnet
anthropic/claude-3-opus
anthropic/claude-3-haiku

# Google
google/gemini-pro-1.5
google/gemini-flash-1.5

# Meta
meta-llama/llama-3.1-70b-instruct
meta-llama/llama-3.2-3b-instruct:free

# Mistral
mistralai/mistral-large
mistralai/mixtral-8x7b-instruct
```

---

## ⚠️ Важные замечания

### 1. Формат ключей
- **OpenRouter**: `sk-or-v1-xxxxx`
- **OpenAI**: `sk-proj-xxxxx` или `sk-xxxxx`

### 2. Base URL
- **Обязательно** указывайте для OpenRouter: `https://openrouter.ai/api/v1`
- Для OpenAI НЕ указывайте или удалите переменную

### 3. Названия моделей
- OpenRouter использует формат: `provider/model-name`
- Примеры: `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`

### 4. Rate Limits
- OpenRouter имеет свои лимиты (зависят от модели)
- Обычно выше, чем у прямого API
- Бот автоматически управляет rate limiting

---

## 🧪 Тестирование

После настройки проверьте работу:

```bash
# 1. Запустите бота
python main.py

# 2. В логах должно быть:
# ai.provider_initialized provider=OpenRouter model=anthropic/claude-3.5-sonnet

# 3. В Telegram отправьте:
/check

# 4. Бот должен проанализировать вакансии через OpenRouter
```

---

## 🆘 Troubleshooting

### Ошибка: "Invalid API key"
- Проверьте формат ключа: `sk-or-v1-xxxxx`
- Убедитесь, что ключ скопирован полностью
- Проверьте, что ключ активен: https://openrouter.ai/keys

### Ошибка: "Model not found"
- Проверьте название модели: https://openrouter.ai/models
- Формат должен быть: `provider/model-name`
- Пример: `openai/gpt-4o-mini`

### Ошибка: "Insufficient credits"
- Пополните баланс: https://openrouter.ai/credits
- Или используйте бесплатную модель (с `:free` в конце)

### Бот не использует OpenRouter
- Проверьте `OPENAI_BASE_URL=https://openrouter.ai/api/v1`
- Перезапустите бота после изменения переменных
- Проверьте логи: должно быть `provider=OpenRouter`

---

## 📚 Дополнительные ресурсы

- **OpenRouter Docs**: https://openrouter.ai/docs
- **Модели**: https://openrouter.ai/models
- **API Reference**: https://openrouter.ai/docs/api-reference
- **Pricing**: https://openrouter.ai/docs/pricing

---

## ✅ Чеклист настройки

- [ ] Зарегистрирован на OpenRouter
- [ ] Создан API ключ
- [ ] Добавлены кредиты (если нужно)
- [ ] Выбрана модель
- [ ] Обновлены переменные окружения:
  - [ ] `OPENAI_API_KEY=sk-or-v1-xxxxx`
  - [ ] `OPENAI_BASE_URL=https://openrouter.ai/api/v1`
  - [ ] `OPENAI_MODEL=выбранная_модель`
- [ ] Перезапущен бот
- [ ] Проверены логи (provider=OpenRouter)
- [ ] Протестирована команда `/check`

**Готово! Теперь FreelanceRadar использует OpenRouter! 🎉**

---

## 💡 Рекомендации

1. **Начните с `openai/gpt-4o-mini`** — лучший баланс цена/качество
2. **Мониторьте расходы** через Dashboard OpenRouter
3. **Экспериментируйте** с разными моделями для своих задач
4. **Используйте бесплатные модели** для тестирования
5. **Установите лимиты** на ключ, чтобы избежать перерасхода

**Удачи! 🚀**
