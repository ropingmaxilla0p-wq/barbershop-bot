from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import settings

LEXICON = {
    "ua": {
        "book": "✨ Записатися онлайн",
        "about": "📍 Про нас",
        "consult": "💬 AI Стиліст",
        "lookbook": "📚 Lookbook",
        "lang": "🌐 Мова / Язык",
        "my_bookings": "📋 Мої записи",
        "confirm": "✅ Підтвердити запис",
        "edit": "✏️ Змінити",
        "cancel": "❌ Скасувати",
        "back": "◀️ Назад",
        "yes": "✅ Так, скасувати",
        "no": "❌ Ні, залишити",
        "welcome": "Вітаємо у Premium Барбершопі! 💈",
        "choose_service": "Яку послугу виберемо сьогодні?",
        "choose_master": "Оберіть майстра:",
        "choose_time": "Оберіть зручний час:",
        "enter_name": "Як до вас звертатися?",
        "enter_phone": "Вкажіть ваш номер телефону:",
        "booking_confirmed": "Запис підтверджено!",
        "booking_cancelled": "Запис скасовано.",
        "cancel_confirm": "Ви впевнені, що хочете скасувати запис?",
        "consult_greeting": (
            "🤖 *AI Стиліст Олександр*: Вітаю! Я ваш персональний стиліст.\n\n"
            "Розкажіть про ваш стиль, бажаний образ або задайте питання — "
            "я допоможу підібрати ідеальну послугу. ✂️"
        ),
    },
    "ru": {
        "book": "✨ Записаться онлайн",
        "about": "📍 О нас",
        "consult": "💬 AI Стилист",
        "lookbook": "📚 Lookbook",
        "lang": "🌐 Мова / Язык",
        "my_bookings": "📋 Мои записи",
        "confirm": "✅ Подтвердить запись",
        "edit": "✏️ Изменить",
        "cancel": "❌ Отменить",
        "back": "◀️ Назад",
        "yes": "✅ Да, отменить",
        "no": "❌ Нет, оставить",
        "welcome": "Добро пожаловать в Premium Барбершоп! 💈",
        "choose_service": "Какую услугу выберем сегодня?",
        "choose_master": "Выберите мастера:",
        "choose_time": "Выберите удобное время:",
        "enter_name": "Как к вам обращаться?",
        "enter_phone": "Укажите ваш номер телефона:",
        "booking_confirmed": "Запись подтверждена!",
        "booking_cancelled": "Запись отменена.",
        "cancel_confirm": "Вы уверены, что хотите отменить запись?",
        "consult_greeting": (
            "🤖 *AI Стилист Александр*: Приветствую! Я ваш персональный стилист.\n\n"
            "Расскажите о своём стиле, желаемом образе или задайте вопрос — "
            "я помогу подобрать идеальную услугу. ✂️"
        ),
    },
}


def get_main_menu(lang: str = "ua") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if settings.WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(
                text=LEXICON[lang]["book"],
                web_app=WebAppInfo(url=settings.WEBAPP_URL + "?v=3&ngrok-skip-browser-warning=true"),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=LEXICON[lang]["book"],
                callback_data="start_booking",
            )
        )
    builder.row(
        InlineKeyboardButton(text=LEXICON[lang]["lookbook"], callback_data="lookbook"),
        InlineKeyboardButton(text=LEXICON[lang]["consult"], callback_data="ai_consult"),
    )
    builder.row(
        InlineKeyboardButton(text=LEXICON[lang]["my_bookings"], callback_data="my_bookings"),
    )
    builder.row(
        InlineKeyboardButton(text=LEXICON[lang]["about"], callback_data="about_us"),
        InlineKeyboardButton(text=LEXICON[lang]["lang"], callback_data="change_lang"),
    )
    return builder.as_markup()


def get_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_ua"))
    builder.add(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"))
    return builder.as_markup()


def get_services_keyboard(services: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        builder.add(
            InlineKeyboardButton(text=service, callback_data=f"service_{service}")
        )
    builder.adjust(2)
    return builder.as_markup()


def get_masters_keyboard(masters: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for master in masters:
        builder.add(
            InlineKeyboardButton(text=master, callback_data=f"master_{master}")
        )
    builder.adjust(1)
    return builder.as_markup()


def get_time_keyboard(slots: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.add(InlineKeyboardButton(text=slot, callback_data=f"time_{slot}"))
    builder.adjust(3)
    return builder.as_markup()


def get_confirmation_keyboard(lang: str = "ua") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text=LEXICON[lang]["confirm"], callback_data="confirm_booking"
        )
    )
    builder.add(
        InlineKeyboardButton(
            text=LEXICON[lang]["edit"], callback_data="start_booking"
        )
    )
    builder.adjust(1)
    return builder.as_markup()


def get_review_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """5 star-rating buttons for post-visit review."""
    builder = InlineKeyboardBuilder()
    stars = ["⭐", "⭐⭐", "⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐⭐"]
    for i, label in enumerate(stars, start=1):
        builder.add(
            InlineKeyboardButton(
                text=label,
                callback_data=f"review_rating_{booking_id}_{i}",
            )
        )
    builder.adjust(5)
    return builder.as_markup()


def get_cancel_confirm_keyboard(lang: str = "ua") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text=LEXICON[lang]["yes"], callback_data="cancel_yes"
        )
    )
    builder.add(
        InlineKeyboardButton(
            text=LEXICON[lang]["no"], callback_data="cancel_no"
        )
    )
    builder.adjust(2)
    return builder.as_markup()


def get_date_keyboard(dates: list, lang: str = "ua") -> InlineKeyboardMarkup:
    """Keyboard with date buttons for reschedule."""
    from datetime import datetime
    builder = InlineKeyboardBuilder()
    day_names_ua = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    day_names_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_names = day_names_ua if lang == "ua" else day_names_ru
    for d in dates:
        label = f"{day_names[d.weekday()]} {d.strftime('%d.%m')}"
        builder.button(text=label, callback_data=f"reschedule_date_{d.strftime('%Y-%m-%d')}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text=LEXICON[lang]["back"], callback_data="my_bookings"))
    return builder.as_markup()


def get_my_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """One button per active booking: '✂️ {service} — {date} {time}'"""
    builder = InlineKeyboardBuilder()
    for b in bookings:
        # Format readable label from time_slot (may contain date or be time-only)
        slot = b.time_slot or "—"
        # Try to parse date part for a friendlier display
        label = f"✂️ {b.service} — {slot}"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"my_booking_{b.id}",
            )
        )
    return builder.as_markup()


def get_cancel_booking_keyboard(booking_id: int, lang: str = "ua") -> InlineKeyboardMarkup:
    """Detail view keyboard: reschedule, cancel, back."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔄 Перенести" if lang == "ua" else "🔄 Перенести",
            callback_data=f"reschedule_booking_{booking_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Скасувати" if lang == "ua" else "❌ Отменить",
            callback_data=f"do_cancel_booking_{booking_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=LEXICON[lang]["back"],
            callback_data="my_bookings",
        )
    )
    return builder.as_markup()
