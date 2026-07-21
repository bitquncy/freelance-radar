#!/bin/bash
# Bash скрипт для деплоя FreelanceRadar на Railway
# Использование: ./deploy.sh

set -e

echo "========================================"
echo "  FreelanceRadar - Railway Deploy Tool"
echo "========================================"
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Проверка Git
echo -e "${YELLOW}🔍 Проверка Git...${NC}"
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Git не установлен!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Git найден${NC}"

# Проверка Python
echo -e "${YELLOW}🔍 Проверка Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python не установлен!${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✅ $PYTHON_VERSION${NC}"

# Проверка тестов
echo ""
echo -e "${YELLOW}🧪 Запуск тестов...${NC}"
if python3 -m pytest tests/ -q --tb=short; then
    echo -e "${GREEN}✅ Все тесты прошли успешно!${NC}"
else
    echo -e "${YELLOW}⚠️  Некоторые тесты не прошли. Продолжить? (y/n)${NC}"
    read -r continue
    if [ "$continue" != "y" ]; then
        echo -e "${RED}❌ Деплой отменён${NC}"
        exit 1
    fi
fi

# Проверка .gitignore
echo ""
echo -e "${YELLOW}🔍 Проверка .gitignore...${NC}"
if [ -f ".env" ]; then
    if grep -q "\.env" .gitignore; then
        echo -e "${GREEN}✅ .env в .gitignore${NC}"
    else
        echo -e "${RED}⚠️  .env НЕ в .gitignore! Добавьте его!${NC}"
        exit 1
    fi
fi

# Проверка Railway файлов
echo ""
echo -e "${YELLOW}🔍 Проверка Railway конфигурации...${NC}"
for file in nixpacks.toml .railwayignore runtime.txt Procfile requirements.txt; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}  ✅ $file${NC}"
    else
        echo -e "${YELLOW}  ⚠️  $file отсутствует${NC}"
    fi
done

# Git статус
echo ""
echo -e "${YELLOW}📦 Git статус:${NC}"
git status --short

# Инициализация git (если нужно)
if [ ! -d ".git" ]; then
    echo ""
    echo -e "${YELLOW}📦 Инициализация Git репозитория...${NC}"
    git init
    echo -e "${GREEN}✅ Git инициализирован${NC}"
fi

# Добавление файлов
echo ""
echo -e "${YELLOW}📦 Добавление файлов в Git...${NC}"
git add .
echo -e "${GREEN}✅ Файлы добавлены${NC}"

# Коммит
echo ""
echo -e "${YELLOW}💾 Создание коммита...${NC}"
echo -n "Введите сообщение коммита (или Enter для 'Deploy to Railway'): "
read -r COMMIT_MESSAGE
if [ -z "$COMMIT_MESSAGE" ]; then
    COMMIT_MESSAGE="Deploy to Railway - $(date '+%Y-%m-%d %H:%M')"
fi
git commit -m "$COMMIT_MESSAGE"
echo -e "${GREEN}✅ Коммит создан: $COMMIT_MESSAGE${NC}"

# Проверка remote
echo ""
echo -e "${YELLOW}🔗 Проверка GitHub remote...${NC}"
if ! git remote -v | grep -q origin; then
    echo -e "${YELLOW}⚠️  Remote не настроен!${NC}"
    echo ""
    echo -e "${CYAN}Настройте GitHub remote:${NC}"
    echo "1. Создайте репозиторий на GitHub: https://github.com/new"
    echo "2. Выполните команду:"
    echo -e "${YELLOW}   git remote add origin https://github.com/YOUR_USERNAME/freelance-radar.git${NC}"
    echo "3. Запустите скрипт снова"
    exit 1
else
    echo -e "${GREEN}✅ Remote настроен:${NC}"
    git remote -v
fi

# Push на GitHub
echo ""
echo -e "${YELLOW}🚀 Отправка кода на GitHub...${NC}"
echo -n "Отправить код на GitHub? (y/n): "
read -r PUSH_CONFIRM
if [ "$PUSH_CONFIRM" = "y" ]; then
    if git push origin main; then
        echo -e "${GREEN}✅ Код отправлен на GitHub!${NC}"
    else
        echo -e "${YELLOW}⚠️  Ошибка при push. Попробуйте вручную:${NC}"
        echo "   git push -u origin main"
    fi
else
    echo -e "${YELLOW}⏭️  Push пропущен${NC}"
fi

# Railway инструкции
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  🚂 Следующие шаги на Railway${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo "1️⃣  Откройте: https://railway.app/"
echo "2️⃣  Нажмите: New Project → Deploy from GitHub repo"
echo "3️⃣  Выберите репозиторий: freelance-radar"
echo ""
echo "4️⃣  Создайте Volume:"
echo "    Settings → Volumes → + Add Volume"
echo "    Mount Path: /app/data"
echo "    Size: 1 GB"
echo ""
echo "5️⃣  Добавьте Variables:"
echo "    BOT_TOKEN=ваш_токен"
echo "    OWNER_CHAT_ID=ваш_id"
echo "    OPENAI_API_KEY=ваш_ключ"
echo "    DB_PATH=/app/data/freelance_radar.db"
echo ""
echo "6️⃣  Railway автоматически задеплоит проект!"
echo ""
echo -e "${CYAN}📚 Полная инструкция: RAILWAY_DEPLOY.md${NC}"
echo -e "${CYAN}⚡ Быстрый старт: QUICK_START_RAILWAY.md${NC}"
echo -e "${CYAN}✅ Чеклист: DEPLOYMENT_CHECKLIST.md${NC}"
echo ""
echo -e "${GREEN}🎉 Подготовка к деплою завершена!${NC}"
echo ""
