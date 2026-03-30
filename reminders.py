"""
Система напоминаний о записях.
Запускается как фоновая задача вместе с ботом.
Проверяет каждые 30 минут есть ли записи через 24ч или 2ч.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from models import SessionLocal, Booking
from keyboards import get_review_keyboard
from config import settings

logger = logging.getLogger(__name__)


async def check_and_send_reminders(bot: Bot):
    """Отправляет напоминания за 24ч и за 2ч до записи."""
    now = datetime.now()

    db = SessionLocal()
    try:
        # Получаем все активные записи (pending/confirmed), которым ещё не отправлены оба напоминания
        bookings = (
            db.query(Booking)
            .filter(Booking.status.in_(["pending", "confirmed"]))
            .all()
        )

        for booking in bookings:
            if not booking.time_slot:
                continue

            # Парсим время записи (формат "YYYY-MM-DD HH:MM")
            try:
                appointment_dt = datetime.strptime(booking.time_slot, "%Y-%m-%d %H:%M")
            except ValueError:
                logger.warning(
                    "Booking #%s has unexpected time_slot format: %s",
                    booking.id,
                    booking.time_slot,
                )
                continue

            # Запись в прошлом больше чем на 2 часа — авто-завершение
            if appointment_dt <= now - timedelta(hours=2):
                booking.status = "completed"
                booking.cancelled_by = "auto"
                db.commit()
                logger.info("Auto-completed past booking #%s (%s)", booking.id, booking.time_slot)
                continue

            # Запись в прошлом (менее 2ч) — пропускаем
            if appointment_dt <= now:
                continue

            delta = appointment_dt - now
            delta_minutes = delta.total_seconds() / 60

            # ── Напоминание за 24 часа (окно: 23ч–25ч = 1380–1500 мин) ──
            if not booking.reminder_24h_sent and 1380 <= delta_minutes <= 1500:
                sent = await _send_reminder(bot, booking, hours=24)
                if sent:
                    booking.reminder_24h_sent = True
                    db.commit()
                    logger.info(
                        "24h reminder sent for booking #%s (user %s)", booking.id, booking.user_id
                    )

            # ── Напоминание за 2 часа (окно: 1.5ч–2.5ч = 90–150 мин) ──
            if not booking.reminder_2h_sent and 90 <= delta_minutes <= 150:
                sent = await _send_reminder(bot, booking, hours=2)
                if sent:
                    booking.reminder_2h_sent = True
                    db.commit()
                    logger.info(
                        "2h reminder sent for booking #%s (user %s)", booking.id, booking.user_id
                    )

    except Exception as e:
        db.rollback()
        logger.error("Error during reminder check: %s", e)
        raise
    finally:
        db.close()


async def _send_reminder(bot: Bot, booking: Booking, hours: int) -> bool:
    """
    Формирует и отправляет напоминание клиенту.
    Возвращает True, если сообщение успешно отправлено.
    """
    # Parse date and time from time_slot
    if booking.time_slot and " " in booking.time_slot:
        date_part, time_part = booking.time_slot.split(" ", 1)
    else:
        date_part = "—"
        time_part = booking.time_slot or "—"

    master_name = booking.master or "—"

    if hours == 2:
        text = (
            f"⏰ <b>Нагадування! Через 2 години ваш запис:</b>\n\n"
            f"✂️ {booking.service} у {master_name}\n"
            f"📅 {date_part} о {time_part}\n\n"
            f"Чекаємо!"
        )
    else:
        # 24h reminder
        text = (
            f"🗓 <b>Нагадування! Завтра ваш запис:</b>\n\n"
            f"✂️ {booking.service} у {master_name}\n"
            f"📅 {date_part} о {time_part}\n\n"
            f"Чекаємо вас! 💈\n"
            f"/mybookings — переглянути або скасувати запис"
        )

    try:
        await bot.send_message(chat_id=booking.user_id, text=text, parse_mode="HTML")
        return True
    except TelegramForbiddenError:
        logger.warning(
            "User %s blocked the bot — skipping reminder for booking #%s",
            booking.user_id,
            booking.id,
        )
        return False
    except TelegramBadRequest as e:
        logger.warning(
            "Bad request sending reminder to user %s (booking #%s): %s",
            booking.user_id,
            booking.id,
            e,
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error sending reminder to user %s (booking #%s): %s",
            booking.user_id,
            booking.id,
            e,
        )
        return False


async def check_and_send_reviews(bot: Bot):
    """Отправляет запрос отзыва клиентам, чья запись завершилась 2-3 часа назад."""
    now = datetime.now()
    window_start = now - timedelta(hours=3)   # запись прошла > 3ч назад
    window_end   = now - timedelta(hours=2)   # запись прошла < 2ч назад

    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.status == "confirmed",
                Booking.review_sent == False,  # noqa: E712
            )
            .all()
        )

        for booking in bookings:
            if not booking.time_slot:
                continue

            try:
                appointment_dt = datetime.strptime(booking.time_slot, "%Y-%m-%d %H:%M")
            except ValueError:
                logger.warning(
                    "Booking #%s has unexpected time_slot format: %s",
                    booking.id,
                    booking.time_slot,
                )
                continue

            # Проверяем, что запись прошла 2–3 часа назад
            if not (window_start <= appointment_dt <= window_end):
                continue

            try:
                await bot.send_message(
                    chat_id=booking.user_id,
                    text=(
                        "💈 <b>Як пройшов візит?</b>\n\n"
                        "Будь ласка, оцініть нашу роботу від 1 до 5 ⭐"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_review_keyboard(booking.id),
                )
                booking.review_sent = True
                db.commit()
                logger.info(
                    "Review request sent for booking #%s (user %s)",
                    booking.id,
                    booking.user_id,
                )
            except TelegramForbiddenError:
                logger.warning(
                    "User %s blocked the bot — skipping review for booking #%s",
                    booking.user_id,
                    booking.id,
                )
                booking.review_sent = True   # помечаем, чтобы не повторять
                db.commit()
            except Exception as e:
                logger.error(
                    "Error sending review request to user %s (booking #%s): %s",
                    booking.user_id,
                    booking.id,
                    e,
                )

    except Exception as e:
        db.rollback()
        logger.error("Error during review check: %s", e)
        raise
    finally:
        db.close()


async def reminder_loop(bot: Bot):
    """Бесконечный цикл проверки каждые 30 минут."""
    logger.info("Reminder loop started.")
    while True:
        try:
            await check_and_send_reminders(bot)
        except Exception as e:
            logger.error("Reminder error: %s", e)
        try:
            await check_and_send_reviews(bot)
        except Exception as e:
            logger.error("Review check error: %s", e)
        await asyncio.sleep(1800)  # 30 минут
