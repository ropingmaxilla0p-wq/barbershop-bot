import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from handlers import router
from reminders import reminder_loop


async def main():
    import uvicorn
    from webapp_server import app as webapp_app

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("🚀 Barber Bot v2 запущено і готове до роботи!")
    print(f"   WEBAPP_URL: {settings.WEBAPP_URL or '(не задано — використовується inline FSM)'}")
    print(f"   ADMIN_IDS: {settings.ADMIN_IDS or '(не задано)'}")

    # Запускаем фоновую задачу напоминаний
    reminder_task = asyncio.create_task(reminder_loop(bot))
    print("🔔 Система напоминань запущена (перевірка кожні 30 хвилин)")

    # Запускаем webapp в том же процессе — одна БД, нет WAL-конфликтов
    config = uvicorn.Config(webapp_app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)
    webapp_task = asyncio.create_task(server.serve())
    print("🌐 WebApp запущено на порту 8080 (в одному процесі з ботом)")

    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        webapp_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        try:
            await webapp_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот зупинено.")
