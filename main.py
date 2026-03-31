import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from handlers import router
from reminders import reminder_loop


def init_master_profiles():
    """Ініціалізує профілі майстрів з business_config.json при першому запуску."""
    import json, os
    from models import SessionLocal, MasterProfile
    try:
        config_path = "business_config.json"
        if not os.path.exists(config_path):
            return
        with open(config_path) as f:
            cfg = json.load(f)
        masters = cfg.get("masters", [])
        db = SessionLocal()
        try:
            for m in masters:
                if not m.get("telegram_id"):
                    continue
                exists = db.query(MasterProfile).filter(
                    MasterProfile.master_id == m["id"]
                ).first()
                if not exists:
                    db.add(MasterProfile(master_id=m["id"], telegram_id=str(m["telegram_id"])))
            db.commit()
            print(f"✅ Майстри ініціалізовані: {[m['name'] for m in masters if m.get('telegram_id')]}")
        finally:
            db.close()
    except Exception as e:
        print(f"⚠️ Помилка ініціалізації майстрів: {e}")


async def main():
    import uvicorn
    from webapp_server import app as webapp_app

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    init_master_profiles()
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
