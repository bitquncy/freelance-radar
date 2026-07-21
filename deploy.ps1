# PowerShell скрипт для деплоя FreelanceRadar на Railway
# Использование: .\deploy.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  FreelanceRadar - Railway Deploy Tool" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Проверка Git
Write-Host "🔍 Проверка Git..." -ForegroundColor Yellow
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Git не установлен! Установите Git и попробуйте снова." -ForegroundColor Red
    exit 1
}
Write-Host "✅ Git найден" -ForegroundColor Green

# Проверка Python
Write-Host "🔍 Проверка Python..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python не установлен!" -ForegroundColor Red
    exit 1
}
$pythonVersion = python --version
Write-Host "✅ $pythonVersion" -ForegroundColor Green

# Проверка тестов
Write-Host ""
Write-Host "🧪 Запуск тестов..." -ForegroundColor Yellow
$testResult = python -m pytest tests/ -q --tb=short 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Некоторые тесты не прошли. Продолжить? (y/n)" -ForegroundColor Yellow
    $continue = Read-Host
    if ($continue -ne "y") {
        Write-Host "❌ Деплой отменён" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "✅ Все тесты прошли успешно!" -ForegroundColor Green
}

# Проверка .gitignore
Write-Host ""
Write-Host "🔍 Проверка .gitignore..." -ForegroundColor Yellow
if (Test-Path ".env") {
    $gitignoreContent = Get-Content ".gitignore" -Raw
    if ($gitignoreContent -match "\.env") {
        Write-Host "✅ .env в .gitignore" -ForegroundColor Green
    } else {
        Write-Host "⚠️  .env НЕ в .gitignore! Добавьте его!" -ForegroundColor Red
        exit 1
    }
}

# Проверка Railway файлов
Write-Host ""
Write-Host "🔍 Проверка Railway конфигурации..." -ForegroundColor Yellow
$requiredFiles = @("nixpacks.toml", ".railwayignore", "runtime.txt", "Procfile", "requirements.txt")
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "  ✅ $file" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  $file отсутствует" -ForegroundColor Yellow
    }
}

# Git статус
Write-Host ""
Write-Host "📦 Git статус:" -ForegroundColor Yellow
git status --short

# Инициализация git (если нужно)
if (-not (Test-Path ".git")) {
    Write-Host ""
    Write-Host "📦 Инициализация Git репозитория..." -ForegroundColor Yellow
    git init
    Write-Host "✅ Git инициализирован" -ForegroundColor Green
}

# Добавление файлов
Write-Host ""
Write-Host "📦 Добавление файлов в Git..." -ForegroundColor Yellow
git add .
Write-Host "✅ Файлы добавлены" -ForegroundColor Green

# Коммит
Write-Host ""
Write-Host "💾 Создание коммита..." -ForegroundColor Yellow
$commitMessage = Read-Host "Введите сообщение коммита (или Enter для 'Deploy to Railway')"
if ([string]::IsNullOrWhiteSpace($commitMessage)) {
    $commitMessage = "Deploy to Railway - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}
git commit -m $commitMessage
Write-Host "✅ Коммит создан: $commitMessage" -ForegroundColor Green

# Проверка remote
Write-Host ""
Write-Host "🔗 Проверка GitHub remote..." -ForegroundColor Yellow
$remotes = git remote -v
if ([string]::IsNullOrWhiteSpace($remotes)) {
    Write-Host "⚠️  Remote не настроен!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Настройте GitHub remote:" -ForegroundColor Cyan
    Write-Host "1. Создайте репозиторий на GitHub: https://github.com/new" -ForegroundColor White
    Write-Host "2. Выполните команду:" -ForegroundColor White
    Write-Host "   git remote add origin https://github.com/YOUR_USERNAME/freelance-radar.git" -ForegroundColor Yellow
    Write-Host "3. Запустите скрипт снова" -ForegroundColor White
    exit 1
} else {
    Write-Host "✅ Remote настроен:" -ForegroundColor Green
    Write-Host $remotes
}

# Push на GitHub
Write-Host ""
Write-Host "🚀 Отправка кода на GitHub..." -ForegroundColor Yellow
$pushConfirm = Read-Host "Отправить код на GitHub? (y/n)"
if ($pushConfirm -eq "y") {
    git push origin main
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Код отправлен на GitHub!" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Ошибка при push. Попробуйте вручную:" -ForegroundColor Yellow
        Write-Host "   git push -u origin main" -ForegroundColor White
    }
} else {
    Write-Host "⏭️  Push пропущен" -ForegroundColor Yellow
}

# Railway инструкции
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  🚂 Следующие шаги на Railway" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1️⃣  Откройте: https://railway.app/" -ForegroundColor White
Write-Host "2️⃣  Нажмите: New Project → Deploy from GitHub repo" -ForegroundColor White
Write-Host "3️⃣  Выберите репозиторий: freelance-radar" -ForegroundColor White
Write-Host ""
Write-Host "4️⃣  Создайте Volume:" -ForegroundColor White
Write-Host "    Settings → Volumes → + Add Volume" -ForegroundColor Gray
Write-Host "    Mount Path: /app/data" -ForegroundColor Gray
Write-Host "    Size: 1 GB" -ForegroundColor Gray
Write-Host ""
Write-Host "5️⃣  Добавьте Variables:" -ForegroundColor White
Write-Host "    BOT_TOKEN=ваш_токен" -ForegroundColor Gray
Write-Host "    OWNER_CHAT_ID=ваш_id" -ForegroundColor Gray
Write-Host "    OPENAI_API_KEY=ваш_ключ" -ForegroundColor Gray
Write-Host "    DB_PATH=/app/data/freelance_radar.db" -ForegroundColor Gray
Write-Host ""
Write-Host "6️⃣  Railway автоматически задеплоит проект!" -ForegroundColor White
Write-Host ""
Write-Host "📚 Полная инструкция: RAILWAY_DEPLOY.md" -ForegroundColor Cyan
Write-Host "⚡ Быстрый старт: QUICK_START_RAILWAY.md" -ForegroundColor Cyan
Write-Host "✅ Чеклист: DEPLOYMENT_CHECKLIST.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "🎉 Подготовка к деплою завершена!" -ForegroundColor Green
Write-Host ""
