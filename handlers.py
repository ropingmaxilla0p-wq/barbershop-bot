"""
handlers.py — Barbershop Bot v2
Full FSM flow: service → master → time → confirm → name → phone → save
/cancel support at any step
/admin command for admins
AI consultant — built-in, no external dependencies
"""

import json
import logging
import os
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from states import BookingStates, CancelConfirm, CancelBooking, ReviewStates, RescheduleStates, MasterStates
import keyboards as kb
from keyboards import LEXICON
from models import SessionLocal, Booking, User, MasterProfile, MasterSchedule, init_db, get_booked_slots
from config import settings

logger = logging.getLogger(__name__)
router = Router()

# Initialize DB on import
init_db()

# ──────────────────────────────────────────────
# Business data — loaded from business_config.json
# ──────────────────────────────────────────────

def _load_business_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "business_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _generate_time_slots(working_hours: dict, slot_duration_min: int) -> list:
    """Generate time slot strings from working_hours start/end and slot_duration_min."""
    start_h, start_m = map(int, working_hours["start"].split(":"))
    end_h, end_m = map(int, working_hours["end"].split(":"))
    start = timedelta(hours=start_h, minutes=start_m)
    end = timedelta(hours=end_h, minutes=end_m)
    step = timedelta(minutes=slot_duration_min)
    slots = []
    current = start
    while current < end:
        total_minutes = int(current.total_seconds() // 60)
        h, m = divmod(total_minutes, 60)
        slots.append(f"{h:02d}:{m:02d}")
        current += step
    return slots


_BUSINESS_CONFIG = _load_business_config()

SERVICES = [s["name"] for s in _BUSINESS_CONFIG["services"]]
MASTERS = [f"{m.get('emoji', '💈')} {m['name']}" for m in _BUSINESS_CONFIG["masters"]]
TIME_SLOTS = _generate_time_slots(
    _BUSINESS_CONFIG["working_hours"],
    _BUSINESS_CONFIG.get("slot_duration_minutes", _BUSINESS_CONFIG.get("slot_duration_min", 30)),
)

# Simple AI stylist knowledge base (no external deps)
AI_TIPS = {
    "стрижк": (
        "✂️ Для класичної чоловічої стрижки рекомендую звернути увагу на послугу "
        "**Чоловіча стрижка** або **Комплекс** (стрижка + борода). "
        "Наш майстер Олександр спеціалізується на fade & taper."
    ),
    "борода": (
        "🧔 Догляд за бородою — наша спеціалізація! Послуга **Стрижка бороди** включає "
        "оформлення, корекцію контурів і гарячий рушник. "
        "Майстер Дмитро — ваш вибір для ідеальної бороди."
    ),
    "колір": (
        "🎨 Для тонування та роботи з кольором рекомендуємо послугу **Тонування**. "
        "Ігор — наш колорист з 5-річним досвідом."
    ),
    "ціна": (
        "💰 Орієнтовний прайс:\n"
        "• Чоловіча стрижка — від 350 грн\n"
        "• Стрижка бороди — від 200 грн\n"
        "• Комплекс — від 500 грн\n"
        "• Тонування — від 600 грн\n"
        "Точну вартість уточнюйте при записі."
    ),
    "час": (
        "⏰ Ми працюємо щодня з 10:00 до 19:00. "
        "Запис доступний онлайн через кнопку меню."
    ),
    "default": (
        "💈 Дякую за ваше питання! Я — AI Стиліст Барбершопу.\n\n"
        "Можу допомогти з:\n"
        "• Вибором послуги та майстра\n"
        "• Інформацією про ціни\n"
        "• Порадами зі стилю\n\n"
        "Просто задайте питання або скористайтесь меню для запису! ✂️"
    ),
}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def get_lang(user_id: str) -> str:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        return user.language if user else "ua"
    finally:
        db.close()


def ai_response(text: str) -> str:
    """Simple keyword-based AI consultant without external dependencies."""
    text_lower = text.lower()
    for keyword, reply in AI_TIPS.items():
        if keyword != "default" and keyword in text_lower:
            return reply
    return AI_TIPS["default"]


def format_booking_summary(data: dict, lang: str) -> str:
    service = data.get("service", "—")
    master = data.get("master", "—")
    time_slot = data.get("time_slot", "—")
    name = data.get("name", "—")
    phone = data.get("phone", "—")

    if lang == "ua":
        return (
            f"📋 *Підсумок запису:*\n\n"
            f"✂️ Послуга: {service}\n"
            f"👤 Майстер: {master}\n"
            f"⏰ Час: {time_slot}\n"
            f"📛 Ім'я: {name}\n"
            f"📞 Телефон: {phone}"
        )
    return (
        f"📋 *Итог записи:*\n\n"
        f"✂️ Услуга: {service}\n"
        f"👤 Мастер: {master}\n"
        f"⏰ Время: {time_slot}\n"
        f"📛 Имя: {name}\n"
        f"📞 Телефон: {phone}"
    )


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == str(message.from_user.id)).first()
        if not user:
            user = User(user_id=str(message.from_user.id), language="ua")
            db.add(user)
            db.commit()
        lang = user.language
    finally:
        db.close()

    await message.answer(
        f"👋 {LEXICON[lang]['welcome']}\n\n"
        "Оберіть дію з меню нижче:" if lang == "ua" else
        f"👋 {LEXICON[lang]['welcome']}\n\n"
        "Выберите действие из меню:",
        reply_markup=kb.get_main_menu(lang),
    )


# ──────────────────────────────────────────────
# /cancel — cancels any active FSM state
# ──────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    lang = get_lang(str(message.from_user.id))
    current_state = await state.get_state()
    if current_state is None:
        msg = (
            "Немає активного запису для скасування. Натисніть /start для початку."
            if lang == "ua"
            else "Нет активной записи для отмены. Нажмите /start для начала."
        )
        await message.answer(msg)
        return

    await state.clear()
    msg = (
        "❌ Дію скасовано. Повертаємось до головного меню."
        if lang == "ua"
        else "❌ Действие отменено. Возвращаемся в главное меню."
    )
    await message.answer(msg, reply_markup=kb.get_main_menu(lang))


# ──────────────────────────────────────────────
# /admin — show last 10 bookings (admin only)
# ──────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        await message.answer("⛔ Доступ заборонено.")
        return

    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .order_by(Booking.id.desc())
            .limit(10)
            .all()
        )
    finally:
        db.close()

    if not bookings:
        await message.answer("📭 Записів ще немає.")
        return

    lines = ["📊 *Останні 10 записів:*\n"]
    for b in bookings:
        status_emoji = {"pending": "🟡", "confirmed": "✅", "cancelled": "❌"}.get(
            b.status, "🔵"
        )
        lines.append(
            f"{status_emoji} #{b.id} | {b.service} | {b.master}\n"
            f"   👤 {b.user_name} | 📞 {b.phone}\n"
            f"   ⏰ {b.time_slot} | {b.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
# Language
# ──────────────────────────────────────────────

@router.callback_query(F.data == "change_lang")
async def change_lang(callback: CallbackQuery):
    await callback.message.edit_text(
        "Оберіть мову / Выберите язык:",
        reply_markup=kb.get_language_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang(callback: CallbackQuery):
    lang = callback.data.split("_")[2]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == str(callback.from_user.id)).first()
        if user:
            user.language = lang
            db.commit()
    finally:
        db.close()

    await callback.message.edit_text(
        f"✅ Мову змінено!\n\n{LEXICON[lang]['welcome']}"
        if lang == "ua"
        else f"✅ Язык изменён!\n\n{LEXICON[lang]['welcome']}",
        reply_markup=kb.get_main_menu(lang),
    )
    await callback.answer()


# ──────────────────────────────────────────────
# About us
# ──────────────────────────────────────────────

@router.callback_query(F.data == "about_us")
async def about_us(callback: CallbackQuery):
    lang = get_lang(str(callback.from_user.id))
    descriptions = {
        "ua": (
            "💈 *The Gentleman's Den*\n\n"
            "Це не просто барбершоп — це простір стилю та комфорту.\n\n"
            "🏆 Понад 5 років досвіду\n"
            "✂️ Майстри з міжнародними сертифікатами\n"
            "🎯 Індивідуальний підхід до кожного клієнта\n\n"
            "📍 Адреса: вул. Хрещатик, 1, Київ\n"
            "📞 +380 (44) 123-45-67\n"
            "⏰ Пн-Нд: 10:00–19:00"
        ),
        "ru": (
            "💈 *The Gentleman's Den*\n\n"
            "Это не просто барбершоп — это пространство стиля и комфорта.\n\n"
            "🏆 Более 5 лет опыта\n"
            "✂️ Мастера с международными сертификатами\n"
            "🎯 Индивидуальный подход к каждому клиенту\n\n"
            "📍 Адрес: ул. Крещатик, 1, Киев\n"
            "📞 +380 (44) 123-45-67\n"
            "⏰ Пн-Вс: 10:00–19:00"
        ),
    }
    await callback.message.answer(
        descriptions[lang],
        parse_mode="Markdown",
        reply_markup=kb.get_main_menu(lang),
    )
    await callback.answer()


# ──────────────────────────────────────────────
# Lookbook
# ──────────────────────────────────────────────

@router.callback_query(F.data == "lookbook")
async def lookbook_gallery(callback: CallbackQuery):
    lang = get_lang(str(callback.from_user.id))
    msg = (
        "📚 *Lookbook — наші роботи:*\n\n"
        "🔹 Premium Fade — чистий сучасний фейд\n"
        "🔹 Classic Pompadour — класика, яка не виходить з моди\n"
        "🔹 Beard Grooming — ідеальна форма бороди\n\n"
        "_Фото доступні у нашому Instagram @gentlemansdeen_"
        if lang == "ua"
        else
        "📚 *Lookbook — наши работы:*\n\n"
        "🔹 Premium Fade — чистый современный фейд\n"
        "🔹 Classic Pompadour — классика, которая не выходит из моды\n"
        "🔹 Beard Grooming — идеальная форма бороды\n\n"
        "_Фото доступны в нашем Instagram @gentlemansdeen_"
    )
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb.get_main_menu(lang))
    await callback.answer()


# ──────────────────────────────────────────────
# AI Consultant
# ──────────────────────────────────────────────

@router.callback_query(F.data == "ai_consult")
async def ai_consult(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    await state.set_state(BookingStates.waiting_for_consult)
    await callback.message.answer(
        LEXICON[lang]["consult_greeting"],
        parse_mode="Markdown",
    )
    hint = (
        "\n💡 Напишіть ваше питання або введіть /cancel для повернення до меню."
        if lang == "ua"
        else "\n💡 Напишите ваш вопрос или введите /cancel для возврата в меню."
    )
    await callback.message.answer(hint)
    await callback.answer()


@router.message(BookingStates.waiting_for_consult)
async def process_consult(message: Message, state: FSMContext):
    lang = get_lang(str(message.from_user.id))
    reply = ai_response(message.text)
    await message.answer(reply, parse_mode="Markdown")

    follow_up = (
        "Бажаєте записатися? Оберіть дію нижче:"
        if lang == "ua"
        else "Хотите записаться? Выберите действие ниже:"
    )
    await message.answer(follow_up, reply_markup=kb.get_main_menu(lang))
    await state.clear()


# ──────────────────────────────────────────────
# Booking FSM: service → master → time → confirm → name → phone → save
# ──────────────────────────────────────────────

@router.callback_query(F.data == "start_booking")
async def start_booking(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    await state.clear()
    await state.set_state(BookingStates.choosing_service)
    await callback.message.answer(
        LEXICON[lang]["choose_service"],
        reply_markup=kb.get_services_keyboard(SERVICES),
    )
    await callback.answer()


# Step 1: service selected → go to master
@router.callback_query(BookingStates.choosing_service, F.data.startswith("service_"))
async def service_selected(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    service = callback.data[len("service_"):]
    await state.update_data(service=service)
    await state.set_state(BookingStates.choosing_master)

    msg = (
        f"Ви обрали: *{service}*\n\n{LEXICON[lang]['choose_master']}"
        if lang == "ua"
        else f"Вы выбрали: *{service}*\n\n{LEXICON[lang]['choose_master']}"
    )
    await callback.message.edit_text(
        msg,
        parse_mode="Markdown",
        reply_markup=kb.get_masters_keyboard(MASTERS),
    )
    await callback.answer()


# Step 2: master selected → go to time
@router.callback_query(BookingStates.choosing_master, F.data.startswith("master_"))
async def master_selected(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    master = callback.data[len("master_"):]
    await state.update_data(master=master)
    await state.set_state(BookingStates.choosing_time)

    # Get booked slots for this master today (date-aware bookings use today's date)
    today = datetime.now().strftime("%Y-%m-%d")
    booked = get_booked_slots(today, master)

    # Build available slots — exclude booked ones
    available_slots = [s for s in TIME_SLOTS if s not in booked]

    msg = (
        f"Майстер: *{master}*\n\n{LEXICON[lang]['choose_time']}"
        if lang == "ua"
        else f"Мастер: *{master}*\n\n{LEXICON[lang]['choose_time']}"
    )
    if not available_slots:
        no_slots_msg = (
            "😔 На жаль, для цього майстра немає вільних слотів на сьогодні. Оберіть іншого майстра."
            if lang == "ua"
            else "😔 К сожалению, у этого мастера нет свободных слотов на сегодня. Выберите другого мастера."
        )
        await callback.message.edit_text(no_slots_msg, reply_markup=kb.get_masters_keyboard(MASTERS))
    else:
        await callback.message.edit_text(
            msg,
            parse_mode="Markdown",
            reply_markup=kb.get_time_keyboard(available_slots),
        )
    await callback.answer()


# Step 3: time selected → show confirmation summary (called from unified handler)
async def time_selected(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    time_slot = callback.data[len("time_"):]
    await state.update_data(time_slot=time_slot)
    await state.set_state(BookingStates.confirming_booking)

    data = await state.get_data()
    summary = format_booking_summary(data, lang)
    prompt = (
        "\n\nПідтвердіть або змініть запис:"
        if lang == "ua"
        else "\n\nПодтвердите или измените запись:"
    )
    await callback.message.edit_text(
        summary + prompt,
        parse_mode="Markdown",
        reply_markup=kb.get_confirmation_keyboard(lang),
    )
    await callback.answer()


# Step 4: confirmed → ask for name
@router.callback_query(BookingStates.confirming_booking, F.data == "confirm_booking")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    await state.set_state(BookingStates.entering_name)
    await callback.message.answer(
        f"📛 {LEXICON[lang]['enter_name']}\n\n"
        + ("(або /cancel для скасування)" if lang == "ua" else "(или /cancel для отмены)")
    )
    await callback.answer()


# Step 5: name entered → ask for phone
@router.message(BookingStates.entering_name)
async def name_entered(message: Message, state: FSMContext):
    lang = get_lang(str(message.from_user.id))
    name = message.text.strip()
    if len(name) < 2:
        err = "Будь ласка, введіть ваше ім'я (мін. 2 символи)." if lang == "ua" else "Пожалуйста, введите ваше имя (мин. 2 символа)."
        await message.answer(err)
        return

    await state.update_data(name=name)
    await state.set_state(BookingStates.entering_phone)

    msg = (
        f"Приємно познайомитись, *{name}*! 🤝\n\n📞 {LEXICON[lang]['enter_phone']}"
        if lang == "ua"
        else f"Приятно познакомиться, *{name}*! 🤝\n\n📞 {LEXICON[lang]['enter_phone']}"
    )
    await message.answer(msg, parse_mode="Markdown")


# Step 6: phone entered → save to DB
@router.message(BookingStates.entering_phone)
async def phone_entered(message: Message, state: FSMContext, bot: Bot):
    lang = get_lang(str(message.from_user.id))
    phone = message.text.strip()

    # Basic phone validation
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 7:
        err = (
            "Будь ласка, введіть коректний номер телефону."
            if lang == "ua"
            else "Пожалуйста, введите корректный номер телефона."
        )
        await message.answer(err)
        return

    data = await state.get_data()

    db = SessionLocal()
    slot_taken = False
    try:
        chosen_time_slot_raw = data.get("time_slot", "")
        # Ensure time_slot always includes a date (YYYY-MM-DD HH:MM) for reminders
        if chosen_time_slot_raw and " " not in chosen_time_slot_raw:
            today_date = datetime.now().strftime("%Y-%m-%d")
            chosen_time_slot = f"{today_date} {chosen_time_slot_raw}"
        else:
            chosen_time_slot = chosen_time_slot_raw
        chosen_master = data.get("master", "")

        # ── Double-booking guard ──
        existing = db.query(Booking).filter(
            Booking.master == chosen_master,
            Booking.time_slot == chosen_time_slot,
            Booking.status != "cancelled",
        ).first()
        if existing:
            slot_taken = True
        else:
            # Resolve master_id from business config by master name
            master_name_clean = chosen_master.lstrip("💈 ").strip()
            _master_id = next(
                (m["id"] for m in _BUSINESS_CONFIG["masters"] if m["name"] == master_name_clean),
                None,
            )
            new_booking = Booking(
                user_id=str(message.from_user.id),
                user_name=data.get("name", ""),
                phone=phone,
                service=data.get("service", ""),
                master=chosen_master,
                master_id=_master_id,
                time_slot=chosen_time_slot,
                status="pending",
            )
            db.add(new_booking)
            db.commit()
            db.refresh(new_booking)
            booking_id = new_booking.id
    except Exception as e:
        logger.error(f"DB error saving booking: {e}")
        err = (
            "⚠️ Помилка при збереженні запису. Спробуйте ще раз."
            if lang == "ua"
            else "⚠️ Ошибка при сохранении записи. Попробуйте ещё раз."
        )
        await message.answer(err)
        return
    finally:
        db.close()

    if slot_taken:
        await state.clear()
        err = (
            "😔 На жаль, цей слот щойно зайняли. Будь ласка, почніть бронювання знову та оберіть інший час."
            if lang == "ua"
            else "😔 К сожалению, этот слот только что заняли. Пожалуйста, начните бронирование заново и выберите другое время."
        )
        await message.answer(err, reply_markup=kb.get_main_menu(lang))
        return

    await state.clear()

    data["phone"] = phone

    # ── Notify owner/master about new booking ──
    if settings.OWNER_CHAT_ID:
        try:
            owner_text = (
                f"🔔 <b>Нова запис #{booking_id}</b>\n\n"
                f"👤 Клієнт: {data.get('name', '—')}\n"
                f"📞 Телефон: {phone}\n"
                f"✂️ Послуга: {data.get('service', '—')}\n"
                f"💈 Майстер: {data.get('master', '—')}\n"
                f"⏰ Час: {data.get('time_slot', '—')}\n"
                f"🆔 Telegram ID: {message.from_user.id}"
            )
            await bot.send_message(settings.OWNER_CHAT_ID, owner_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to notify owner (OWNER_CHAT_ID={settings.OWNER_CHAT_ID}): {e}")

    # ── Beautiful HTML confirmation to client ──
    time_slot_val = data.get("time_slot", "—")
    # Try to split time_slot into date + time parts if it contains a space
    time_slot_parts = time_slot_val.split(" ", 1) if " " in time_slot_val else [time_slot_val, ""]
    date_part = time_slot_parts[0] if time_slot_parts[0] else "—"
    time_part = time_slot_parts[1] if len(time_slot_parts) > 1 and time_slot_parts[1] else time_slot_val

    # Look up price from business config
    service_name = data.get("service", "—")
    price_val = "—"
    for svc in _BUSINESS_CONFIG.get("services", []):
        if svc.get("name") == service_name:
            price_val = svc.get("price", "—")
            break

    success = (
        f"✅ <b>Запис підтверджено!</b>\n\n"
        f"✂️ Послуга: {service_name}\n"
        f"👤 Майстер: {data.get('master', '—')}\n"
        f"📅 Дата: {date_part}\n"
        f"⏰ Час: {time_part}\n"
        f"💰 Вартість: {price_val} UAH\n\n"
        f"📍 <i>The Gentleman's Den</i>\n"
        f"📞 Чекаємо на вас! За 2 години до візиту прийде нагадування.\n\n"
        f"/mybookings — переглянути мої записи"
        if lang == "ua"
        else
        f"✅ <b>Запись подтверждена!</b>\n\n"
        f"✂️ Услуга: {service_name}\n"
        f"👤 Мастер: {data.get('master', '—')}\n"
        f"📅 Дата: {date_part}\n"
        f"⏰ Время: {time_part}\n"
        f"💰 Стоимость: {price_val} UAH\n\n"
        f"📍 <i>The Gentleman's Den</i>\n"
        f"📞 Ждём вас! За 2 часа до визита придёт напоминание.\n\n"
        f"/mybookings — посмотреть мои записи"
    )
    await message.answer(success, parse_mode="HTML", reply_markup=kb.get_main_menu(lang))


# ──────────────────────────────────────────────
# WebApp data handler (if WEBAPP_URL is set)
# ──────────────────────────────────────────────

@router.message(F.content_type == "web_app_data")
async def web_app_data_handler(message: Message, state: FSMContext):
    lang = get_lang(str(message.from_user.id))
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        await message.answer("⚠️ Помилка обробки даних WebApp.")
        return

    service = data.get("service", {})
    service_name = service.get("name") if isinstance(service, dict) else str(service)
    date_str = data.get("date", "")
    time_str = data.get("time", "")
    time_slot = f"{date_str} {time_str}".strip()

    # Clear any leftover FSM state before setting new data
    await state.clear()
    await state.update_data(service=service_name, time_slot=time_slot, master=data.get("master", "—"))
    await state.set_state(BookingStates.confirming_booking)

    summary = (
        f"📝 *Ваш вибір:*\n\n"
        f"✂️ Послуга: {service_name}\n"
        f"⏰ Час: {time_slot}\n\n"
        "Підтвердіть або змініть запис:"
        if lang == "ua"
        else
        f"📝 *Ваш выбор:*\n\n"
        f"✂️ Услуга: {service_name}\n"
        f"⏰ Время: {time_slot}\n\n"
        "Подтвердите или измените запись:"
    )
    await message.answer(summary, parse_mode="Markdown", reply_markup=kb.get_confirmation_keyboard(lang))


# ──────────────────────────────────────────────
# Cancel confirmation flow
# ──────────────────────────────────────────────

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_ask(callback: CallbackQuery, state: FSMContext, lang_override: str = None):
    lang = get_lang(str(callback.from_user.id))
    await state.set_state(CancelConfirm.waiting_confirmation)
    await callback.message.answer(
        LEXICON[lang]["cancel_confirm"],
        reply_markup=kb.get_cancel_confirm_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(CancelConfirm.waiting_confirmation, F.data == "cancel_yes")
async def cancel_confirmed(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    await state.clear()
    await callback.message.edit_text(
        f"❌ {LEXICON[lang]['booking_cancelled']}",
        reply_markup=kb.get_main_menu(lang),
    )
    await callback.answer()


# ──────────────────────────────────────────────
# Review handlers
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("review_rating_"))
async def review_rating_handler(callback: CallbackQuery, state: FSMContext):
    """User tapped a star rating button."""
    # callback_data format: review_rating_{booking_id}_{rating}
    parts = callback.data.split("_")
    try:
        booking_id = int(parts[2])
        rating = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Помилка даних.")
        return

    # Save rating and booking_id in FSM state, ask for text
    await state.update_data(review_booking_id=booking_id, review_rating=rating)
    await state.set_state(ReviewStates.waiting_text)

    stars_display = "⭐" * rating
    await callback.message.edit_text(
        f"Дякуємо за оцінку: {stars_display}\n\n"
        "✍️ Напишіть короткий відгук про ваш візит (або надішліть <b>-</b> щоб пропустити):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ReviewStates.waiting_text)
async def review_text_handler(message: Message, state: FSMContext, bot: Bot):
    """User sent review text (or '-' to skip)."""
    data = await state.get_data()
    booking_id = data.get("review_booking_id")
    rating = data.get("review_rating", 0)
    review_text = message.text.strip()

    if review_text == "-":
        review_text = None

    # Save to DB
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if booking:
            booking.review_rating = rating
            booking.review_text = review_text
            db.commit()

        # Notify owner if rating >= 4
        if rating >= 4 and settings.OWNER_CHAT_ID:
            try:
                stars_display = "⭐" * rating
                owner_text = (
                    f"🌟 <b>Новий відгук (booking #{booking_id})</b>\n\n"
                    f"Оцінка: {stars_display} ({rating}/5)\n"
                )
                if booking:
                    owner_text += (
                        f"👤 Клієнт: {booking.user_name}\n"
                        f"✂️ Послуга: {booking.service}\n"
                        f"👨‍🔧 Майстер: {booking.master}\n"
                        f"⏰ Час: {booking.time_slot}\n"
                    )
                if review_text:
                    owner_text += f"\n💬 Відгук: {review_text}"
                await bot.send_message(settings.OWNER_CHAT_ID, owner_text, parse_mode="HTML")
            except Exception as e:
                logger.warning("Failed to notify owner about review: %s", e)
    except Exception as e:
        logger.error("DB error saving review: %s", e)
        db.rollback()
    finally:
        db.close()

    await state.clear()

    lang = get_lang(str(message.from_user.id))
    thanks = (
        "🙏 Дякуємо за ваш відгук! До зустрічі у барбершопі 💈"
        if lang == "ua"
        else "🙏 Спасибо за ваш отзыв! До встречи в барбершопе 💈"
    )
    await message.answer(thanks, reply_markup=kb.get_main_menu(lang))


@router.callback_query(CancelConfirm.waiting_confirmation, F.data == "cancel_no")
async def cancel_declined(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(str(callback.from_user.id))
    await state.clear()
    msg = "Добре, запис залишено. Повертаємось до меню." if lang == "ua" else "Хорошо, запись сохранена. Возвращаемся в меню."
    await callback.message.edit_text(msg, reply_markup=kb.get_main_menu(lang))
    await callback.answer()


# ──────────────────────────────────────────────
# My Bookings flow: list → details → cancel
# ──────────────────────────────────────────────

async def _show_my_bookings(user_id: str, lang: str, message_or_callback):
    """Fetch active bookings and display them (used by command and callback)."""
    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.user_id == user_id,
                Booking.status.in_(["pending", "confirmed"]),
            )
            .order_by(Booking.id.desc())
            .all()
        )
        # Detach from session so we can use after close
        booking_list = list(bookings)
    finally:
        db.close()

    if not booking_list:
        no_bookings = (
            "📭 У вас немає активних записів."
            if lang == "ua"
            else "📭 У вас нет активных записей."
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(
                no_bookings, reply_markup=kb.get_main_menu(lang)
            )
        else:
            await message_or_callback.answer(no_bookings, reply_markup=kb.get_main_menu(lang))
        return

    header = (
        "📋 *Ваші активні записи:*\nОберіть запис для перегляду деталей або скасування."
        if lang == "ua"
        else "📋 *Ваши активные записи:*\nВыберите запись для просмотра деталей или отмены."
    )
    markup = kb.get_my_bookings_keyboard(booking_list)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(
            header, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await message_or_callback.answer(header, parse_mode="Markdown", reply_markup=markup)


@router.message(Command("mybookings"))
async def cmd_my_bookings(message: Message):
    lang = get_lang(str(message.from_user.id))
    await _show_my_bookings(str(message.from_user.id), lang, message)


@router.callback_query(F.data == "my_bookings")
async def cb_my_bookings(callback: CallbackQuery):
    lang = get_lang(str(callback.from_user.id))
    await _show_my_bookings(str(callback.from_user.id), lang, callback)
    await callback.answer()


@router.callback_query(F.data.startswith("my_booking_"))
async def cb_booking_detail(callback: CallbackQuery):
    lang = get_lang(str(callback.from_user.id))
    booking_id = int(callback.data.split("my_booking_")[1])

    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            await callback.answer("⚠️ Запис не знайдено.", show_alert=True)
            return
        # Snapshot fields before closing session
        b_service = booking.service
        b_master = booking.master
        b_time = booking.time_slot
        b_name = booking.user_name
        b_phone = booking.phone
        b_status = booking.status
        b_created = booking.created_at.strftime("%d.%m.%Y %H:%M") if booking.created_at else "—"
    finally:
        db.close()

    status_label = {"pending": "🟡 Очікує", "confirmed": "✅ Підтверджено"}.get(b_status, b_status)
    if lang == "ru":
        status_label = {"pending": "🟡 Ожидает", "confirmed": "✅ Подтверждено"}.get(b_status, b_status)

    if lang == "ua":
        detail_text = (
            f"📋 *Деталі запису #{booking_id}*\n\n"
            f"✂️ Послуга: {b_service}\n"
            f"👤 Майстер: {b_master}\n"
            f"⏰ Час: {b_time}\n"
            f"📛 Ім'я: {b_name}\n"
            f"📞 Телефон: {b_phone}\n"
            f"📅 Створено: {b_created}\n"
            f"🔖 Статус: {status_label}"
        )
    else:
        detail_text = (
            f"📋 *Детали записи #{booking_id}*\n\n"
            f"✂️ Услуга: {b_service}\n"
            f"👤 Мастер: {b_master}\n"
            f"⏰ Время: {b_time}\n"
            f"📛 Имя: {b_name}\n"
            f"📞 Телефон: {b_phone}\n"
            f"📅 Создано: {b_created}\n"
            f"🔖 Статус: {status_label}"
        )

    await callback.message.edit_text(
        detail_text,
        parse_mode="Markdown",
        reply_markup=kb.get_cancel_booking_keyboard(booking_id, lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reschedule_booking_"))
async def cb_reschedule(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Cancel current booking and start a fresh booking flow (reschedule)."""
    lang = get_lang(str(callback.from_user.id))
    booking_id = int(callback.data.split("reschedule_booking_")[1])

    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.user_id == str(callback.from_user.id),
        ).first()
        if not booking or booking.status == "cancelled":
            await callback.answer("⚠️ Запис не знайдено або вже скасовано.", show_alert=True)
            return

        # Snapshot before cancellation
        b_user_name = booking.user_name or "Клієнт"
        b_time = booking.time_slot or "—"
        b_master = booking.master or "—"
        b_master_id = booking.master_id

        # Cancel the old booking
        booking.status = "cancelled"
        booking.cancelled_by = "client_reschedule"
        db.commit()

        # Notify master about reschedule
        if b_master_id:
            profile = db.query(MasterProfile).filter(
                MasterProfile.master_id == b_master_id
            ).first()
            if profile and profile.telegram_id:
                try:
                    master_notice = (
                        f"🔄 <b>Перенос запису</b>\n\n"
                        f"Клієнт <b>{b_user_name}</b> переніс запис з <b>{b_time}</b>.\n"
                        f"Очікуйте нову запис."
                    )
                    await bot.send_message(profile.telegram_id, master_notice, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Failed to notify master about reschedule: {e}")

        # Notify owner
        if settings.OWNER_CHAT_ID:
            try:
                owner_notice = (
                    f"🔄 <b>Клієнт переніс запис #{booking_id}</b>\n\n"
                    f"👤 {b_user_name}\n"
                    f"⏰ Було: {b_time}\n"
                    f"💈 Майстер: {b_master}\n"
                    f"Очікуйте нову запис."
                )
                await bot.send_message(settings.OWNER_CHAT_ID, owner_notice, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Failed to notify owner about reschedule: {e}")
    finally:
        db.close()

    # Clear state and start new booking flow
    await state.clear()
    await state.set_state(BookingStates.choosing_service)

    await callback.message.edit_text(
        "🔄 Запис скасовано. Оберіть новий зручний час 👇"
        if lang == "ua"
        else "🔄 Запись отменена. Выберите новое удобное время 👇",
    )
    await callback.message.answer(
        LEXICON[lang]["choose_service"],
        reply_markup=kb.get_services_keyboard(SERVICES),
    )
    await callback.answer()


@router.callback_query(BookingStates.choosing_time, F.data.startswith("time_"))
async def time_selected_unified(callback: CallbackQuery, state: FSMContext):
    """Regular booking time selection."""
    await time_selected(callback, state)


@router.callback_query(F.data.startswith("do_cancel_booking_"))
async def cb_do_cancel_booking(callback: CallbackQuery, bot: Bot):
    lang = get_lang(str(callback.from_user.id))
    booking_id = int(callback.data.split("do_cancel_booking_")[1])

    db = SessionLocal()
    try:
        booking = (
            db.query(Booking)
            .filter(
                Booking.id == booking_id,
                Booking.user_id == str(callback.from_user.id),
            )
            .first()
        )
        if not booking:
            await callback.answer("⚠️ Запис не знайдено або вже скасовано.", show_alert=True)
            return
        if booking.status == "cancelled":
            await callback.answer("ℹ️ Запис вже скасовано.", show_alert=True)
            return

        # Snapshot for owner notification
        b_service = booking.service
        b_master = booking.master
        b_time = booking.time_slot
        b_name = booking.user_name
        b_phone = booking.phone

        booking.status = "cancelled"
        db.commit()
    finally:
        db.close()

    # Notify owner
    if settings.OWNER_CHAT_ID:
        try:
            cancel_notice = (
                f"❌ <b>Клієнт скасував запис #{booking_id}</b>\n\n"
                f"👤 Клієнт: {b_name}\n"
                f"📞 Телефон: {b_phone}\n"
                f"✂️ Послуга: {b_service}\n"
                f"💈 Майстер: {b_master}\n"
                f"⏰ Час: {b_time}\n"
                f"🆔 Telegram ID: {callback.from_user.id}"
            )
            await bot.send_message(settings.OWNER_CHAT_ID, cancel_notice, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to notify owner about cancellation: {e}")

    success_msg = (
        f"✅ Запис #{booking_id} успішно скасовано."
        if lang == "ua"
        else f"✅ Запись #{booking_id} успешно отменена."
    )
    await callback.message.edit_text(success_msg, reply_markup=kb.get_main_menu(lang))
    await callback.answer()


# ──────────────────────────────────────────────
# /master — Master panel
# ──────────────────────────────────────────────

def _get_master_profile(telegram_id: str):
    """Return MasterProfile row for a given Telegram user ID, or None."""
    db = SessionLocal()
    try:
        profile = db.query(MasterProfile).filter(
            MasterProfile.telegram_id == telegram_id
        ).first()
        if profile:
            # snapshot
            master_id = profile.master_id
            db.expunge(profile)
            return profile
        return None
    finally:
        db.close()


def _get_master_name_by_id(master_id: int) -> str:
    """Return master name from business_config.json by id."""
    for m in _BUSINESS_CONFIG.get("masters", []):
        if m["id"] == master_id:
            return m["name"]
    return f"Майстер #{master_id}"


def _get_master_panel_keyboard() -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📅 Мої записи сьогодні", callback_data="master_today"))
    builder.row(InlineKeyboardButton(text="📆 Записи на тиждень", callback_data="master_week"))
    builder.row(InlineKeyboardButton(text="🚫 Заблокувати день", callback_data="master_block_day"))
    builder.row(InlineKeyboardButton(text="🗓 Заблоковані дні", callback_data="master_blocked_list"))
    builder.row(InlineKeyboardButton(text="✅ Підтвердити запис", callback_data="master_pending_list"))
    return builder.as_markup()


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@router.message(Command("master"))
async def cmd_master(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await message.answer("⛔ Доступ заборонено. Ви не зареєстровані як майстер.")
        return

    master_name = _get_master_name_by_id(profile.master_id)
    await state.clear()
    await message.answer(
        f"💈 <b>Панель майстра — {master_name}</b>\n\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=_get_master_panel_keyboard(),
    )


@router.callback_query(F.data == "master_today")
async def cb_master_today(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    master_name = _get_master_name_by_id(profile.master_id)
    today = datetime.now().strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.master_id == profile.master_id,
                Booking.time_slot.like(f"{today}%"),
                Booking.status != "cancelled",
            )
            .order_by(Booking.time_slot)
            .all()
        )

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()

        lines = [f"📅 <b>Записи на сьогодні ({today}) — {master_name}:</b>\n"]
        if not bookings:
            lines.append("Записів немає.")
        for b in bookings:
            status_emoji = {"pending": "🟡", "confirmed": "✅", "completed": "🏁"}.get(b.status, "🔵")
            time_part = b.time_slot.split(" ")[1] if " " in b.time_slot else b.time_slot
            lines.append(
                f"{status_emoji} {time_part} | {b.service}\n"
                f"   👤 {b.user_name} | 📞 {b.phone}"
            )
            # Add "Complete" button for non-completed active bookings
            if b.status in ("pending", "confirmed"):
                builder.row(
                    InlineKeyboardButton(
                        text=f"🏁 Завершити #{b.id}",
                        callback_data=f"master_complete:{b.id}",
                    )
                )
        # Add back button
        builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="master_back"))
    finally:
        db.close()

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "master_week")
async def cb_master_week(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    master_name = _get_master_name_by_id(profile.master_id)
    today = datetime.now()
    week_end = today + timedelta(days=7)
    today_str = today.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.master_id == profile.master_id,
                Booking.status != "cancelled",
            )
            .order_by(Booking.time_slot)
            .all()
        )
        # Filter by date range manually (sqlite LIKE approach)
        week_bookings = [
            b for b in bookings
            if b.time_slot and today_str <= b.time_slot[:10] <= week_end_str
        ]

        lines = [f"📆 <b>Записи на 7 днів — {master_name}:</b>\n"]
        if not week_bookings:
            lines.append("Записів немає.")
        current_date = None
        for b in week_bookings:
            date_part = b.time_slot[:10] if " " in b.time_slot else "—"
            time_part = b.time_slot.split(" ")[1] if " " in b.time_slot else b.time_slot
            if date_part != current_date:
                current_date = date_part
                lines.append(f"\n📅 <b>{date_part}</b>")
            status_emoji = {"pending": "🟡", "confirmed": "✅", "completed": "🏁"}.get(b.status, "🔵")
            lines.append(
                f"  {status_emoji} {time_part} | {b.service} — {b.user_name}"
            )
    finally:
        db.close()

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_get_master_panel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "master_block_day")
async def cb_master_block_day(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    await state.set_data({"master_id_for_block": profile.master_id})
    await state.set_state(MasterStates.waiting_block_date)
    await callback.message.answer(
        "🚫 Введіть дату для блокування у форматі <b>РРРР-ММ-ДД</b> (наприклад: 2026-04-01):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MasterStates.waiting_block_date)
async def process_block_date(message: Message, state: FSMContext, bot: Bot):
    date_str = message.text.strip()
    data = await state.get_data()
    master_id = data.get("master_id_for_block")

    # Validate date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("⚠️ Невірний формат дати. Введіть у форматі РРРР-ММ-ДД (наприклад: 2026-04-01).")
        return

    master_name = _get_master_name_by_id(master_id)

    db = SessionLocal()
    try:
        # Check if already exists
        existing = db.query(MasterSchedule).filter(
            MasterSchedule.master_id == master_id,
            MasterSchedule.specific_date == date_str,
        ).first()
        if existing:
            existing.is_working = False
        else:
            schedule = MasterSchedule(
                master_id=master_id,
                specific_date=date_str,
                is_working=False,
                start_time="09:00",
                end_time="20:00",
            )
            db.add(schedule)
        db.commit()

        # Find and notify clients with bookings on this day
        affected_bookings = (
            db.query(Booking)
            .filter(
                Booking.master_id == master_id,
                Booking.time_slot.like(f"{date_str}%"),
                Booking.status.in_(["pending", "confirmed"]),
            )
            .all()
        )

        notified_count = 0
        for b in affected_bookings:
            # Cancel the booking
            b.status = "cancelled"
            b.cancelled_by = "master"
            db.commit()

            if b.user_id:
                try:
                    rebook_markup = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🔄 Записатися знову", callback_data="start_booking"),
                    ]])
                    await bot.send_message(
                        chat_id=b.user_id,
                        text=(
                            f"⚠️ <b>Зміна у розкладі</b>\n\n"
                            f"Вибачте, майстер <b>{master_name}</b> недоступний <b>{date_str}</b>.\n"
                            f"Ваш запис на {b.service} ({b.time_slot}) скасовано.\n\n"
                            f"Будь ласка, запишіться на інший день. 💈"
                        ),
                        parse_mode="HTML",
                        reply_markup=rebook_markup,
                    )
                    notified_count += 1
                except Exception as e:
                    logger.warning(f"Failed to notify client {b.user_id} about day block: {e}")
    finally:
        db.close()

    await state.clear()
    result_text = f"✅ День <b>{date_str}</b> заблоковано для майстра <b>{master_name}</b>."
    if affected_bookings:
        result_text += f"\n\n📢 Повідомлено клієнтів: {notified_count}/{len(affected_bookings)}"
    await message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=_get_master_panel_keyboard(),
    )


@router.callback_query(F.data == "master_blocked_list")
async def cb_master_blocked_list(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    master_name = _get_master_name_by_id(profile.master_id)
    db = SessionLocal()
    try:
        blocked = (
            db.query(MasterSchedule)
            .filter(
                MasterSchedule.master_id == profile.master_id,
                MasterSchedule.is_working == False,
            )
            .order_by(MasterSchedule.specific_date)
            .all()
        )

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()

        if not blocked:
            text = f"🗓 <b>Заблоковані дні — {master_name}</b>\n\nНемає заблокованих днів."
        else:
            lines = [f"🗓 <b>Заблоковані дні — {master_name}:</b>\n"]
            for s in blocked:
                lines.append(f"🚫 {s.specific_date}")
                builder.row(
                    InlineKeyboardButton(
                        text=f"🔓 Розблокувати {s.specific_date}",
                        callback_data=f"master_unblock:{s.specific_date}",
                    )
                )
            text = "\n".join(lines)

        builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="master_back"))
    finally:
        db.close()

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("master_unblock:"))
async def cb_master_unblock(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    date_str = callback.data.split(":")[1]
    db = SessionLocal()
    try:
        schedule = db.query(MasterSchedule).filter(
            MasterSchedule.master_id == profile.master_id,
            MasterSchedule.specific_date == date_str,
        ).first()
        if schedule:
            db.delete(schedule)
            db.commit()
    finally:
        db.close()

    await callback.answer(f"🔓 День {date_str} розблоковано.", show_alert=True)
    # Refresh the blocked list
    await cb_master_blocked_list(callback)


@router.callback_query(F.data == "master_pending_list")
async def cb_master_pending_list(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.master_id == profile.master_id,
                Booking.status == "pending",
            )
            .order_by(Booking.time_slot)
            .all()
        )
        if not bookings:
            await callback.message.edit_text(
                "✅ Немає записів, що очікують підтвердження.",
                reply_markup=_get_master_panel_keyboard(),
            )
            await callback.answer()
            return

        # Build inline keyboard with confirm/cancel buttons per booking
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        lines = ["📋 <b>Записи, що очікують підтвердження:</b>\n"]
        for b in bookings:
            time_part = b.time_slot.split(" ")[1] if " " in b.time_slot else b.time_slot
            date_part = b.time_slot[:10] if len(b.time_slot) >= 10 else b.time_slot
            lines.append(f"#{b.id} | {date_part} {time_part} | {b.service} — {b.user_name}")
            builder.row(
                InlineKeyboardButton(
                    text=f"✅ Підтвердити #{b.id}",
                    callback_data=f"master_confirm:{b.id}",
                ),
                InlineKeyboardButton(
                    text=f"❌ Скасувати #{b.id}",
                    callback_data=f"master_cancel:{b.id}",
                ),
            )
        builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="master_back"))
    finally:
        db.close()

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "master_back")
async def cb_master_back(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return
    master_name = _get_master_name_by_id(profile.master_id)
    await callback.message.edit_text(
        f"💈 <b>Панель майстра — {master_name}</b>\n\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=_get_master_panel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("master_confirm:"))
async def cb_master_confirm(callback: CallbackQuery, bot: Bot):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    booking_id = int(callback.data.split(":")[1])
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.master_id == profile.master_id,
        ).first()
        if not booking:
            await callback.answer("⚠️ Запис не знайдено.", show_alert=True)
            return
        booking.status = "confirmed"
        booking.confirmed_at = datetime.utcnow()
        client_user_id = booking.user_id
        b_service = booking.service
        b_time = booking.time_slot
        db.commit()
    finally:
        db.close()

    # Notify client
    try:
        await bot.send_message(
            chat_id=client_user_id,
            text=(
                f"✅ <b>Ваш запис підтверджено майстром!</b>\n\n"
                f"✂️ Послуга: {b_service}\n"
                f"⏰ Час: {b_time}\n\n"
                f"Чекаємо вас! 💈"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Failed to notify client about confirmation: {e}")

    await callback.answer(f"✅ Запис #{booking_id} підтверджено.", show_alert=True)
    # Refresh pending list
    await cb_master_pending_list(callback)


@router.callback_query(F.data.startswith("master_cancel:"))
async def cb_master_cancel(callback: CallbackQuery, bot: Bot):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    booking_id = int(callback.data.split(":")[1])
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.master_id == profile.master_id,
        ).first()
        if not booking:
            await callback.answer("⚠️ Запис не знайдено.", show_alert=True)
            return
        booking.status = "cancelled"
        booking.cancelled_by = "master"
        client_user_id = booking.user_id
        b_service = booking.service
        b_time = booking.time_slot
        db.commit()
    finally:
        db.close()

    # Notify client
    try:
        await bot.send_message(
            chat_id=client_user_id,
            text=(
                f"❌ <b>Ваш запис скасовано майстром.</b>\n\n"
                f"✂️ Послуга: {b_service}\n"
                f"⏰ Час: {b_time}\n\n"
                f"Будь ласка, запишіться на інший час. 💈"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Failed to notify client about master cancellation: {e}")

    await callback.answer(f"❌ Запис #{booking_id} скасовано.", show_alert=True)
    # Refresh pending list
    await cb_master_pending_list(callback)


@router.callback_query(F.data.startswith("master_complete:"))
async def cb_master_complete(callback: CallbackQuery, bot: Bot):
    telegram_id = str(callback.from_user.id)
    profile = _get_master_profile(telegram_id)
    if not profile:
        await callback.answer("⛔ Доступ заборонено.", show_alert=True)
        return

    booking_id = int(callback.data.split(":")[1])
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.master_id == profile.master_id,
        ).first()
        if not booking:
            await callback.answer("⚠️ Запис не знайдено.", show_alert=True)
            return
        if booking.status == "cancelled":
            await callback.answer("⚠️ Запис вже скасовано — не можна завершити.", show_alert=True)
            return
        booking.status = "completed"
        booking.completed_at = datetime.utcnow()
        client_user_id = booking.user_id
        b_service = booking.service
        b_master = booking.master
        db.commit()
    finally:
        db.close()

    # Send review request to client
    try:
        await bot.send_message(
            chat_id=client_user_id,
            text=(
                f"💈 <b>Як пройшов візит?</b>\n\n"
                f"✂️ {b_service} у {b_master}\n\n"
                f"Будь ласка, оцініть нашу роботу від 1 до 5 ⭐"
            ),
            parse_mode="HTML",
            reply_markup=kb.get_review_keyboard(booking_id),
        )
        # Mark review as sent
        db2 = SessionLocal()
        try:
            b = db2.query(Booking).filter(Booking.id == booking_id).first()
            if b:
                b.review_sent = True
                db2.commit()
        finally:
            db2.close()
    except Exception as e:
        logger.warning(f"Failed to send review request for booking #{booking_id}: {e}")

    await callback.answer(f"🏁 Запис #{booking_id} завершено.", show_alert=True)
    await callback.message.edit_text(
        f"🏁 Запис #{booking_id} позначено як завершений.",
        reply_markup=_get_master_panel_keyboard(),
    )
