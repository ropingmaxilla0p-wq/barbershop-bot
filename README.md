# 💈 Barber Bot — Telegram Booking System

Полнофункциональный Telegram-бот для онлайн-записи в барбершоп (и другие beauty-бизнесы) с мини-приложением WebApp, AI-консультантом и системой уведомлений.

---

## Быстрый старт (5 минут)

### 1. Создай бота через @BotFather
Открой Telegram → @BotFather → `/newbot` → следуй инструкциям → получи **BOT_TOKEN**

### 2. Настрой окружение
```bash
cp .env.example .env
```
Открой `.env` и вставь токен:
```env
BOT_TOKEN=1234567890:AAExampleTokenHere
OWNER_CHAT_ID=твой_telegram_id   # Получи у @userinfobot
```

### 3. Настрой бизнес-конфиг
Открой `business_config.json` и измени:
- Название заведения (`business_name`)
- Список услуг (`services`) — название, цена, длительность
- Список мастеров (`masters`) — имя и эмодзи
- Рабочие часы (`working_hours`)

### 4. Запусти через Docker
```bash
docker-compose up -d
```
Бот запустится автоматически. Проверь логи:
```bash
docker-compose logs -f bot
```

### 5. Настрой WebApp (опционально)
Для мини-приложения (выбор даты через календарь) нужен HTTPS-адрес:

**Вариант A — ngrok (для тестирования):**
```bash
ngrok http 8080
# Скопируй HTTPS-URL, например: https://abc123.ngrok.io
```
Добавь в `.env`:
```env
WEBAPP_URL=https://abc123.ngrok.io/webapp
```

**Вариант B — VPS/домен (для production):**
Настрой nginx как reverse proxy на порт 8080, добавь SSL через Let's Encrypt.

---

## Адаптация под бизнес

### Как менять услуги и цены
Открой `business_config.json`, раздел `services`:
```json
{
  "services": [
    {"id": 1, "name": "Стрижка", "price": 350, "duration_min": 45},
    {"id": 2, "name": "Борода", "price": 250, "duration_min": 30}
  ]
}
```
- `name` — название услуги (отображается в боте)
- `price` — цена в выбранной валюте (`currency`)
- `duration_min` — длительность в минутах

После изменений перезапусти бота:
```bash
docker-compose restart bot
```

### Как добавить мастеров
Раздел `masters` в `business_config.json`:
```json
{
  "masters": [
    {"id": 1, "name": "Александр", "emoji": "✂️"},
    {"id": 2, "name": "Дмитрий",   "emoji": "💈"},
    {"id": 3, "name": "Новый Мастер", "emoji": "🪒"}
  ]
}
```
Каждому мастеру нужен уникальный `id`.

### Как настроить рабочие часы
```json
{
  "working_hours": {
    "start": "09:00",
    "end": "20:00"
  },
  "slot_duration_min": 30
}
```
- `start` / `end` — начало и конец рабочего дня
- `slot_duration_min` — длина слота записи (30 = каждые полчаса)

### Как настроить язык
В `business_config.json`:
```json
{
  "languages": ["ua", "ru"]
}
```
Поддерживаются: `ua` (украинский), `ru` (русский).

---

## Структура файлов

| Файл | Описание |
|------|----------|
| `main.py` | Точка входа. Запускает бота (aiogram polling) и фоновый цикл напоминаний |
| `handlers.py` | Все обработчики сообщений и callback-кнопок. FSM-поток: услуга → мастер → время → подтверждение → имя → телефон |
| `webapp_server.py` | FastAPI-сервер для Telegram Mini App. Эндпоинты: `/api/config`, `/api/available-slots`, `/api/confirm-booking`, `/api/bookings/{user_id}` |
| `config.py` | Настройки через pydantic-settings (BOT_TOKEN, WEBAPP_URL, ADMIN_IDS, OWNER_CHAT_ID) |
| `models.py` | SQLAlchemy-модели: `Booking`, `User`. Инициализация SQLite-базы |
| `keyboards.py` | Все Inline и Reply-клавиатуры. Словарь `LEXICON` для двуязычности |
| `states.py` | FSM-состояния (BookingStates, CancelConfirm) |
| `reminders.py` | Фоновая задача — рассылка напоминаний клиентам за день до записи |
| `business_config.json` | Конфигурация бизнеса: услуги, мастера, часы, валюта. **Главный файл адаптации** |
| `.env.example` | Пример файла переменных окружения |
| `barbershop.db` | SQLite база данных (создаётся автоматически) |
| `webapp/` | Статические файлы Telegram Mini App (HTML/JS/CSS) |
| `Dockerfile` | Docker-образ на базе python:3.11-slim |
| `docker-compose.yml` | Оркестрация: сервис `bot` + сервис `webapp` |

---

## Поддерживаемые типы бизнеса

Бот легко адаптируется под любой beauty/wellness бизнес через `business_config.json`:

| `business_type` | Описание |
|-----------------|----------|
| `barbershop` | Барбершоп — стрижки, бороды, укладки |
| `beauty_salon` | Салон красоты — маникюр, педикюр, уход за волосами |
| `nail_studio` | Nail-студия — гель-лак, наращивание, дизайн |
| `tattoo` | Тату-салон — тату, пирсинг, коррекция |
| `massage` | Массажный кабинет — виды массажа по длительности |
| `dental` | Стоматология — консультации, чистки, лечение |

Для смены типа измени поле `business_type` в `business_config.json` и обнови услуги/мастеров соответственно.

---

## Переменные окружения

| Переменная | Обязательная | Описание |
|------------|:---:|---------|
| `BOT_TOKEN` | ✅ | Токен Telegram-бота от @BotFather |
| `WEBAPP_URL` | — | HTTPS-URL мини-приложения (`https://domain.com/webapp`) |
| `ADMIN_IDS` | — | Telegram ID администраторов через запятую `[123,456]` |
| `OWNER_CHAT_ID` | — | ID чата для уведомлений о новых записях |
| `WEBAPP_PORT` | — | Порт WebApp-сервера (по умолчанию: 8080) |

---

## Управление

```bash
# Запуск
docker-compose up -d

# Остановка
docker-compose down

# Логи бота
docker-compose logs -f bot

# Логи webapp
docker-compose logs -f webapp

# Перезапуск после изменения конфига
docker-compose restart

# Пересборка после изменения кода
docker-compose up -d --build
```

---

## Требования

- Docker + Docker Compose
- (Опционально) ngrok или домен с SSL для WebApp

---

*White label продукт. Адаптируй `business_config.json` и `.env` — бот готов к работе за 5 минут.*
