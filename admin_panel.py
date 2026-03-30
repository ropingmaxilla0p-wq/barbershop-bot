"""
Streamlit Admin Panel — The Gentleman's Den Barbershop
Run: streamlit run admin_panel.py
"""
import json
import os
import sys
import asyncio
from datetime import datetime, date, time

import pandas as pd
import plotly.express as px
import streamlit as st
import requests
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Ensure project directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Base, Booking, MasterProfile, init_db

# ── DB setup ──
DATABASE_URL = "sqlite:///./barbershop.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 10})


@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    """Enable WAL mode for better concurrent access."""
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA busy_timeout=5000")


def wal_checkpoint():
    """Force WAL checkpoint so Docker bot sees latest changes immediately."""
    try:
        import sqlite3 as _sqlite3
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "barbershop.db")
        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.close()
    except Exception:
        pass


Session = sessionmaker(bind=engine)
init_db()

# ── Config path ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "business_config.json")

# ── Auth ──
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("PASSWORD", "admin123"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {"services": [], "masters": [], "working_hours": {}, "blocked_dates": [], "tariffs": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def send_telegram_message(chat_id: str, text: str):
    """Send a message to a Telegram user via Bot API (sync, for Streamlit)."""
    if not BOT_TOKEN:
        st.warning("BOT_TOKEN не налаштовано — повідомлення не надіслано.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        st.warning(f"Помилка відправки повідомлення: {e}")
        return False


# ── Auth check ──
def check_auth():
    """Returns True if authenticated, False otherwise. Shows login form if not authenticated."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.sidebar.title("🔐 Вхід в адмін-панель")
    password = st.sidebar.text_input("Пароль", type="password", key="login_password")
    if st.sidebar.button("Увійти"):
        if password == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.sidebar.error("❌ Невірний пароль")

    st.title("🔐 Авторизація")
    st.info("Введіть пароль у бічній панелі для доступу до адмін-панелі.")
    return False


# ── Helpers ──
def get_service_by_id(services: list, service_id: int) -> dict | None:
    """Find a service by its id."""
    for s in services:
        if s["id"] == service_id:
            return s
    return None


def calc_services_total(services: list, service_ids: list[int]) -> int:
    """Calculate total price of selected services."""
    total = 0
    for sid in service_ids:
        svc = get_service_by_id(services, sid)
        if svc:
            total += svc.get("price", 0)
    return total


def calc_services_duration(services: list, service_ids: list[int]) -> int:
    """Calculate total duration of selected services."""
    total = 0
    for sid in service_ids:
        svc = get_service_by_id(services, sid)
        if svc:
            total += svc.get("duration_minutes", 0)
    return total


def get_tariffs_using_service(tariffs: list, service_id: int) -> list:
    """Return tariffs that include a given service_id."""
    result = []
    for t in tariffs:
        if service_id in t.get("services", []) or service_id in t.get("service_ids", []):
            result.append(t)
    return result


# ── Page: Bookings ──
def page_bookings():
    st.title("📋 Записи")
    db = Session()
    try:
        bookings = db.query(Booking).order_by(Booking.id.desc()).all()
        if not bookings:
            st.info("Записів ще немає.")
            return

        STATUS_LABELS = {
            "pending": "Очікує",
            "confirmed": "Підтверджено",
            "completed": "Завершено",
            "cancelled": "Скасовано",
        }

        data = [
            {
                "ID": b.id,
                "Клієнт": b.user_name or "—",
                "Телефон": b.phone or "—",
                "Послуга": b.service or "—",
                "Майстер": b.master or "—",
                "Час": b.time_slot or "—",
                "Статус": STATUS_LABELS.get(b.status, b.status or "—"),
                "Дата запису": b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "—",
                "user_id": b.user_id or "",
            }
            for b in bookings
        ]
        df = pd.DataFrame(data)

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            masters = ["Всі"] + sorted(df["Майстер"].unique().tolist())
            selected_master = st.selectbox("Майстер", masters)
        with col2:
            statuses = ["Всі"] + sorted(df["Статус"].unique().tolist())
            selected_status = st.selectbox("Статус", statuses)
        with col3:
            date_filter = st.date_input("Фільтр по даті", value=None, key="date_filter")

        filtered = df.copy()
        if selected_master != "Всі":
            filtered = filtered[filtered["Майстер"] == selected_master]
        if selected_status != "Всі":
            filtered = filtered[filtered["Статус"] == selected_status]
        if date_filter:
            date_str = date_filter.strftime("%Y-%m-%d")
            filtered = filtered[
                filtered["Час"].str.contains(date_str, na=False) |
                filtered["Дата запису"].str.contains(date_filter.strftime("%d.%m.%Y"), na=False)
            ]

        display_df = filtered.drop(columns=["user_id"], errors="ignore")
        st.dataframe(display_df, use_container_width=True)

        # ── Actions: Cancel / Complete ──
        st.subheader("Дії із записами")

        col_action1, col_action2 = st.columns(2)

        with col_action1:
            st.markdown("**❌ Скасувати запис**")
            cancel_id = st.number_input("ID запису для скасування", min_value=1, step=1, key="cancel_id")
            if st.button("❌ Скасувати запис"):
                booking = db.query(Booking).filter(Booking.id == cancel_id).first()
                if booking:
                    if booking.status == "cancelled":
                        st.warning(f"Запис #{cancel_id} вже скасовано.")
                    else:
                        client_user_id = booking.user_id
                        b_service = booking.service
                        b_master = booking.master
                        b_time = booking.time_slot

                        booking.status = "cancelled"
                        booking.cancelled_by = "admin"
                        db.commit()
                        wal_checkpoint()

                        if client_user_id:
                            msg_text = (
                                f"❌ <b>Ваш запис скасовано адміністратором.</b>\n\n"
                                f"✂️ Послуга: {b_service}\n"
                                f"👤 Майстер: {b_master}\n"
                                f"⏰ Час: {b_time}\n\n"
                                f"Будь ласка, запишіться на інший час. 💈"
                            )
                            if send_telegram_message(client_user_id, msg_text):
                                st.success(f"✅ Запис #{cancel_id} скасовано. Клієнта повідомлено.")
                            else:
                                st.success(f"✅ Запис #{cancel_id} скасовано. ⚠️ Не вдалося повідомити клієнта.")
                        else:
                            st.success(f"✅ Запис #{cancel_id} скасовано.")
                        st.rerun()
                else:
                    st.error(f"Запис #{cancel_id} не знайдено.")

        with col_action2:
            st.markdown("**✅ Завершити запис**")
            complete_id = st.number_input("ID запису для завершення", min_value=1, step=1, key="complete_id")
            if st.button("✅ Завершити запис"):
                booking = db.query(Booking).filter(Booking.id == complete_id).first()
                if booking:
                    if booking.status == "completed":
                        st.warning(f"Запис #{complete_id} вже завершено.")
                    elif booking.status == "cancelled":
                        st.warning(f"Запис #{complete_id} скасовано — не можна завершити.")
                    else:
                        booking.status = "completed"
                        if hasattr(booking, "completed_at"):
                            booking.completed_at = datetime.utcnow()
                        db.commit()
                        wal_checkpoint()

                        # Send review request to client
                        if booking.user_id:
                            # Build inline keyboard directly (no aiogram dependency)
                            buttons = [
                                [
                                    {"text": "⭐ 1", "callback_data": f"review_{booking.id}_1"},
                                    {"text": "⭐ 2", "callback_data": f"review_{booking.id}_2"},
                                    {"text": "⭐ 3", "callback_data": f"review_{booking.id}_3"},
                                    {"text": "⭐ 4", "callback_data": f"review_{booking.id}_4"},
                                    {"text": "⭐ 5", "callback_data": f"review_{booking.id}_5"},
                                ]
                            ]
                            review_text = (
                                f"💈 <b>Як пройшов візит?</b>\n\n"
                                f"✂️ {booking.service} у {booking.master}\n\n"
                                f"Будь ласка, оцініть нашу роботу від 1 до 5 ⭐"
                            )
                            payload = {
                                "chat_id": booking.user_id,
                                "text": review_text,
                                "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": buttons},
                            }
                            try:
                                resp = requests.post(
                                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                    json=payload,
                                    timeout=10,
                                )
                                if resp.status_code == 200:
                                    booking.review_sent = True
                                    db.commit()
                            except Exception as e:
                                st.warning(f"⚠️ Не вдалося надіслати запит відгуку: {e}")

                        st.success(f"✅ Запис #{complete_id} позначено як завершений.")
                        st.rerun()
                else:
                    st.error(f"Запис #{complete_id} не знайдено.")

        # ── Change master for booking ──
        st.divider()
        st.subheader("🔄 Змінити майстра")
        cfg_masters = load_config().get("masters", [])
        change_booking_id = st.number_input("ID запису", min_value=1, step=1, key="change_master_booking_id")
        booking_to_change = db.query(Booking).filter(Booking.id == change_booking_id).first()

        if booking_to_change and booking_to_change.status in ("pending", "confirmed"):
            current_master = booking_to_change.master or "—"
            st.info(f"Поточний майстер: **{current_master}**")

            other_masters = [m for m in cfg_masters if m["name"] != current_master.lstrip("💈 ").strip()]
            if other_masters:
                master_options = {m["name"]: m["id"] for m in other_masters}
                new_master_name = st.selectbox(
                    "Новий майстер",
                    options=list(master_options.keys()),
                    key="new_master_select",
                )
                if st.button("🔄 Змінити майстра", key="btn_change_master"):
                    new_master_id = master_options[new_master_name]
                    old_master_name = booking_to_change.master
                    booking_to_change.master = new_master_name
                    booking_to_change.master_id = new_master_id
                    db.commit()
                    wal_checkpoint()

                    # Notify client
                    if booking_to_change.user_id:
                        send_telegram_message(
                            booking_to_change.user_id,
                            f"ℹ️ <b>Зміна майстра</b>\n\n"
                            f"Ваш майстер змінений на <b>{new_master_name}</b>.\n"
                            f"✂️ Послуга: {booking_to_change.service}\n"
                            f"⏰ Час: {booking_to_change.time_slot}",
                        )

                    # Notify new master
                    new_profile = db.query(MasterProfile).filter(
                        MasterProfile.master_id == new_master_id
                    ).first()
                    if new_profile and new_profile.telegram_id:
                        send_telegram_message(
                            new_profile.telegram_id,
                            f"📋 <b>До вас додано запис</b>\n\n"
                            f"👤 Клієнт: {booking_to_change.user_name}\n"
                            f"✂️ Послуга: {booking_to_change.service}\n"
                            f"⏰ Час: {booking_to_change.time_slot}",
                        )

                    st.success(f"✅ Майстра для запису #{change_booking_id} змінено на {new_master_name}.")
                    st.rerun()
            else:
                st.warning("Немає інших доступних майстрів.")
        elif booking_to_change:
            st.warning(f"Запис #{change_booking_id} має статус '{booking_to_change.status}' — зміна майстра неможлива.")

    finally:
        db.close()


# ── Page: Tariffs ──
def page_tariffs():
    st.title("🏷️ Тарифи (пакети послуг)")
    cfg = load_config()
    services = cfg.get("services", [])
    tariffs = cfg.get("tariffs", [])

    if not services:
        st.warning("Спочатку додайте послуги у розділі Налаштування → Послуги.")
        return

    # ── Display existing tariffs ──
    if tariffs:
        st.subheader("📋 Поточні тарифи")
        for idx, tariff in enumerate(tariffs):
            t_services = tariff.get("services", tariff.get("service_ids", []))
            svc_names = []
            for sid in t_services:
                svc = get_service_by_id(services, sid)
                svc_names.append(svc["name"] if svc else f"[ID {sid} — видалено]")

            full_price = calc_services_total(services, t_services)
            package_price = tariff.get("price", tariff.get("final_price", 0))
            discount_uah = full_price - package_price
            discount_pct = (discount_uah / full_price * 100) if full_price > 0 else 0
            active = tariff.get("active", True)
            status_icon = "✅" if active else "⏸️"

            with st.expander(f"{status_icon} {tariff['name']} — {package_price} UAH (знижка {discount_uah} UAH / {discount_pct:.1f}%)"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Послуги:** {', '.join(svc_names)}")
                    st.write(f"**Повна ціна:** {full_price} UAH")
                    st.write(f"**Ціна пакету:** {package_price} UAH")
                    st.write(f"**Тривалість:** {tariff.get('duration_minutes', '—')} хв")
                with col2:
                    st.write(f"**Знижка:** {tariff.get('discount_percent', discount_pct):.1f}%")
                    st.write(f"**Статус:** {'Активний' if active else 'Неактивний'}")

                # Toggle active
                col_act, col_del = st.columns(2)
                with col_act:
                    new_active = st.checkbox(
                        "Активний",
                        value=active,
                        key=f"tariff_active_{tariff['id']}",
                    )
                    if new_active != active:
                        tariffs[idx]["active"] = new_active
                        cfg["tariffs"] = tariffs
                        save_config(cfg)
                        st.success(f"Тариф '{tariff['name']}' {'активовано' if new_active else 'деактивовано'}.")
                        st.rerun()

                with col_del:
                    if st.button(f"🗑️ Видалити", key=f"del_tariff_{tariff['id']}"):
                        st.session_state[f"confirm_del_tariff_{tariff['id']}"] = True

                    if st.session_state.get(f"confirm_del_tariff_{tariff['id']}", False):
                        st.warning(f"Справді видалити тариф **{tariff['name']}**?")
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("✅ Так, видалити", key=f"confirm_yes_tariff_{tariff['id']}"):
                                tariffs.pop(idx)
                                cfg["tariffs"] = tariffs
                                save_config(cfg)
                                st.session_state.pop(f"confirm_del_tariff_{tariff['id']}", None)
                                st.success(f"Тариф видалено.")
                                st.rerun()
                        with c2:
                            if st.button("❌ Скасувати", key=f"confirm_no_tariff_{tariff['id']}"):
                                st.session_state.pop(f"confirm_del_tariff_{tariff['id']}", None)
                                st.rerun()

                # ── Edit tariff inline ──
                st.markdown("---")
                st.markdown("**Редагувати:**")
                svc_options = {s["name"]: s["id"] for s in services}
                current_svc_names = [s["name"] for s in services if s["id"] in t_services]

                edit_name = st.text_input("Назва", value=tariff["name"], key=f"edit_tname_{tariff['id']}")
                edit_svcs = st.multiselect(
                    "Послуги",
                    options=list(svc_options.keys()),
                    default=current_svc_names,
                    key=f"edit_tsvcs_{tariff['id']}",
                )
                edit_svc_ids = [svc_options[n] for n in edit_svcs]
                edit_full = calc_services_total(services, edit_svc_ids)
                edit_dur = calc_services_duration(services, edit_svc_ids)

                edit_discount = st.number_input(
                    "Знижка %",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(tariff.get("discount_percent", discount_pct)),
                    step=1.0,
                    key=f"edit_tdisc_{tariff['id']}",
                )
                edit_price = round(edit_full * (1 - edit_discount / 100))
                st.info(f"Повна ціна: {edit_full} UAH → Ціна пакету: **{edit_price} UAH** | Тривалість: {edit_dur} хв")

                if edit_price > edit_full and edit_full > 0:
                    st.warning("⚠️ Ціна пакету більша за суму послуг — знижка від'ємна!")

                if st.button("💾 Зберегти зміни", key=f"save_tariff_{tariff['id']}"):
                    if len(edit_svc_ids) < 2:
                        st.error("Пакет повинен містити мінімум 2 послуги.")
                    elif not edit_name.strip():
                        st.error("Введіть назву тарифу.")
                    else:
                        tariffs[idx]["name"] = edit_name.strip()
                        tariffs[idx]["services"] = edit_svc_ids
                        tariffs[idx]["price"] = edit_price
                        tariffs[idx]["discount_percent"] = round(edit_discount, 1)
                        tariffs[idx]["duration_minutes"] = edit_dur
                        cfg["tariffs"] = tariffs
                        save_config(cfg)
                        st.success(f"✅ Тариф '{edit_name}' оновлено!")
                        st.rerun()
    else:
        st.info("Тарифів ще немає. Створіть перший пакет нижче.")

    # ── Add new tariff ──
    st.divider()
    st.subheader("➕ Додати новий тариф")

    svc_options_new = {s["name"]: s["id"] for s in services}

    new_name = st.text_input("Назва тарифу", key="new_tariff_name", placeholder="Наприклад: Комплекс VIP")
    new_svcs = st.multiselect(
        "Оберіть послуги (мін. 2)",
        options=list(svc_options_new.keys()),
        key="new_tariff_svcs",
    )
    new_svc_ids = [svc_options_new[n] for n in new_svcs]
    new_full = calc_services_total(services, new_svc_ids)
    new_dur = calc_services_duration(services, new_svc_ids)

    new_discount = st.number_input(
        "Знижка %", min_value=0.0, max_value=100.0, value=10.0, step=1.0, key="new_tariff_disc"
    )
    new_price = round(new_full * (1 - new_discount / 100)) if new_full > 0 else 0

    if new_svc_ids:
        st.info(f"Повна ціна: {new_full} UAH → Ціна пакету: **{new_price} UAH** | Тривалість: {new_dur} хв")

    if st.button("➕ Додати тариф"):
        if not new_name.strip():
            st.error("Введіть назву тарифу.")
        elif len(new_svc_ids) < 2:
            st.error("Пакет повинен містити мінімум 2 послуги.")
        else:
            new_id = max((t["id"] for t in tariffs), default=0) + 1
            new_tariff = {
                "id": new_id,
                "name": new_name.strip(),
                "services": new_svc_ids,
                "price": new_price,
                "discount_percent": round(new_discount, 1),
                "duration_minutes": new_dur,
                "active": True,
                "created_at": date.today().isoformat(),
            }
            tariffs.append(new_tariff)
            cfg["tariffs"] = tariffs
            save_config(cfg)
            st.success(f"✅ Тариф '{new_name}' додано!")
            st.rerun()


# ── Page: Settings (Налаштування) ──
def page_settings():
    st.title("⚙️ Налаштування")
    cfg = load_config()

    tab_shop, tab_masters, tab_services = st.tabs(["🏪 Барбершоп", "👨‍💈 Майстри", "✂️ Послуги"])

    # ── Tab: Barbershop settings ──
    with tab_shop:
        st.subheader("🏪 Загальні налаштування")

        shop_name = st.text_input(
            "Назва барбершопу",
            value=cfg.get("barbershop_name", ""),
            key="setting_shop_name",
        )

        wh = cfg.get("working_hours", {})
        col1, col2 = st.columns(2)
        with col1:
            start_parts = wh.get("start", "09:00").split(":")
            start_time = st.time_input(
                "Робочі години: початок",
                value=time(int(start_parts[0]), int(start_parts[1])),
                key="setting_wh_start",
            )
        with col2:
            end_parts = wh.get("end", "20:00").split(":")
            end_time = st.time_input(
                "Робочі години: кінець",
                value=time(int(end_parts[0]), int(end_parts[1])),
                key="setting_wh_end",
            )

        slot_options = [15, 20, 30, 45, 60]
        current_slot = cfg.get("slot_duration_minutes", 30)
        slot_idx = slot_options.index(current_slot) if current_slot in slot_options else 2
        slot_duration = st.selectbox(
            "Тривалість слота (хвилин)",
            options=slot_options,
            index=slot_idx,
            key="setting_slot",
        )

        if st.button("💾 Зберегти налаштування", key="save_shop_settings"):
            cfg["barbershop_name"] = shop_name.strip()
            cfg["working_hours"] = {
                "start": start_time.strftime("%H:%M"),
                "end": end_time.strftime("%H:%M"),
            }
            cfg["slot_duration_minutes"] = slot_duration
            save_config(cfg)
            st.success("✅ Налаштування барбершопу збережено!")

    # ── Tab: Masters ──
    with tab_masters:
        st.subheader("👨‍💈 Управління майстрами")
        masters = cfg.get("masters", [])
        db = Session()
        try:
            if masters:
                for idx, master in enumerate(masters):
                    with st.expander(f"💈 {master['name']} (ID: {master['id']})"):
                        col1, col2 = st.columns(2)
                        with col1:
                            m_name = st.text_input("Ім'я", value=master.get("name", ""), key=f"m_name_{master['id']}")
                            m_spec = st.text_input("Спеціалізація", value=master.get("specialization", ""), key=f"m_spec_{master['id']}")
                            m_exp = st.number_input("Досвід (роки)", value=int(master.get("experience_years", 0)), min_value=0, step=1, key=f"m_exp_{master['id']}")
                        with col2:
                            m_rating = st.number_input("Рейтинг", value=float(master.get("rating", 5.0)), min_value=0.0, max_value=5.0, step=0.1, key=f"m_rating_{master['id']}")
                            m_active = st.checkbox("Активний", value=master.get("active", True), key=f"m_active_{master['id']}")

                            # Telegram ID from DB
                            profile = db.query(MasterProfile).filter(
                                MasterProfile.master_id == master["id"]
                            ).first()
                            current_tg = profile.telegram_id if profile else ""
                            m_tg = st.text_input(
                                "Telegram ID",
                                value=current_tg or "",
                                key=f"m_tg_{master['id']}",
                                placeholder="Числовий Telegram ID",
                            )

                        col_save, col_del = st.columns(2)
                        with col_save:
                            if st.button(f"💾 Зберегти", key=f"save_master_{master['id']}"):
                                masters[idx]["name"] = m_name.strip()
                                masters[idx]["specialization"] = m_spec.strip()
                                masters[idx]["experience_years"] = m_exp
                                masters[idx]["rating"] = round(m_rating, 1)
                                masters[idx]["active"] = m_active
                                cfg["masters"] = masters
                                save_config(cfg)

                                # Save Telegram ID to DB
                                if profile:
                                    profile.telegram_id = m_tg.strip() if m_tg.strip() else None
                                else:
                                    profile = MasterProfile(
                                        master_id=master["id"],
                                        telegram_id=m_tg.strip() if m_tg.strip() else None,
                                    )
                                    db.add(profile)
                                db.commit()
                                st.success(f"✅ Майстер '{m_name}' оновлено.")
                                st.rerun()

                        with col_del:
                            if st.button(f"🗑️ Видалити", key=f"del_master_{master['id']}"):
                                st.session_state[f"confirm_del_master_{master['id']}"] = True

                            if st.session_state.get(f"confirm_del_master_{master['id']}", False):
                                # Перевірка активних записів
                                active_bookings = db.query(Booking).filter(
                                    Booking.master == master['name'],
                                    Booking.status.in_(["pending", "confirmed"])
                                ).count()
                                if active_bookings > 0:
                                    st.error(f"❌ Неможливо видалити — у майстра **{master['name']}** є {active_bookings} активних записів. Спочатку скасуйте або завершіть їх.")
                                    st.session_state.pop(f"confirm_del_master_{master['id']}", None)
                                else:
                                    st.warning(f"Справді видалити майстра **{master['name']}**?")
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        if st.button("✅ Так", key=f"confirm_yes_master_{master['id']}"):
                                            masters.pop(idx)
                                            cfg["masters"] = masters
                                            save_config(cfg)
                                            # Remove profile from DB
                                            if profile:
                                                db.delete(profile)
                                                db.commit()
                                            st.session_state.pop(f"confirm_del_master_{master['id']}", None)
                                            st.success("Майстра видалено.")
                                            st.rerun()
                                with c2:
                                    if st.button("❌ Ні", key=f"confirm_no_master_{master['id']}"):
                                        st.session_state.pop(f"confirm_del_master_{master['id']}", None)
                                        st.rerun()
            else:
                st.info("Майстрів ще немає.")

            # ── Add master ──
            st.divider()
            st.subheader("➕ Додати майстра")
            col1, col2 = st.columns(2)
            with col1:
                new_m_name = st.text_input("Ім'я", key="new_master_name")
                new_m_spec = st.text_input("Спеціалізація", key="new_master_spec")
            with col2:
                new_m_exp = st.number_input("Досвід (роки)", value=1, min_value=0, step=1, key="new_master_exp")
                new_m_rating = st.number_input("Рейтинг", value=5.0, min_value=0.0, max_value=5.0, step=0.1, key="new_master_rating")
            new_m_tg = st.text_input("Telegram ID", key="new_master_tg", placeholder="Опціонально")

            if st.button("➕ Додати майстра"):
                if not new_m_name.strip():
                    st.error("Введіть ім'я майстра.")
                else:
                    new_id = max((m["id"] for m in masters), default=0) + 1
                    new_master = {
                        "id": new_id,
                        "name": new_m_name.strip(),
                        "specialization": new_m_spec.strip(),
                        "experience_years": new_m_exp,
                        "rating": round(new_m_rating, 1),
                        "active": True,
                    }
                    masters.append(new_master)
                    cfg["masters"] = masters
                    save_config(cfg)

                    # Save TG ID to DB if provided
                    if new_m_tg.strip():
                        new_profile = MasterProfile(
                            master_id=new_id,
                            telegram_id=new_m_tg.strip(),
                        )
                        db.add(new_profile)
                        db.commit()

                    st.success(f"✅ Майстра '{new_m_name}' додано!")
                    st.rerun()
        finally:
            db.close()

    # ── Tab: Services ──
    with tab_services:
        st.subheader("✂️ Управління послугами")
        services = cfg.get("services", [])
        tariffs = cfg.get("tariffs", [])

        if not services:
            st.info("Послуг ще немає.")
        else:
            updated_services = []
            for svc in services:
                with st.expander(f"#{svc['id']} {svc['name']} — {svc.get('price', 0)} UAH"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        name = st.text_input("Назва", value=svc.get("name", ""), key=f"svc_name_{svc['id']}")
                    with col2:
                        price = st.number_input(
                            "Ціна (UAH)", value=int(svc.get("price", 0)), step=50, key=f"svc_price_{svc['id']}"
                        )
                    with col3:
                        duration = st.number_input(
                            "Тривалість (хв)",
                            value=int(svc.get("duration_minutes", 30)),
                            step=15,
                            key=f"svc_dur_{svc['id']}",
                        )

                    # Warn if price changed and tariffs use this service
                    if price != svc.get("price", 0):
                        affected = get_tariffs_using_service(tariffs, svc["id"])
                        if affected:
                            names = ", ".join(t["name"] for t in affected)
                            st.warning(f"⚠️ Зміна ціни вплине на тарифи: **{names}**. Перевірте ціни пакетів після збереження.")

                    updated_svc = dict(svc)
                    updated_svc["name"] = name
                    updated_svc["price"] = price
                    updated_svc["duration_minutes"] = duration

                    col_save, col_del = st.columns(2)
                    with col_del:
                        if st.button(f"🗑️ Видалити", key=f"del_svc_{svc['id']}"):
                            affected = get_tariffs_using_service(tariffs, svc["id"])
                            if affected:
                                names = ", ".join(t["name"] for t in affected)
                                st.error(f"❌ Неможливо видалити — послуга використовується в тарифах: **{names}**. Спочатку видаліть або оновіть тарифи.")
                            else:
                                st.session_state[f"confirm_del_svc_{svc['id']}"] = True

                        if st.session_state.get(f"confirm_del_svc_{svc['id']}", False):
                            st.warning(f"Справді видалити послугу **{svc['name']}**?")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.button("✅ Так", key=f"confirm_yes_svc_{svc['id']}"):
                                    # Don't add to updated list = deleted
                                    st.session_state[f"_delete_svc_{svc['id']}"] = True
                                    st.session_state.pop(f"confirm_del_svc_{svc['id']}", None)
                            with c2:
                                if st.button("❌ Ні", key=f"confirm_no_svc_{svc['id']}"):
                                    st.session_state.pop(f"confirm_del_svc_{svc['id']}", None)
                                    st.rerun()

                    if not st.session_state.get(f"_delete_svc_{svc['id']}", False):
                        updated_services.append(updated_svc)

            if st.button("💾 Зберегти всі зміни", key="save_all_services"):
                cfg["services"] = updated_services
                save_config(cfg)
                # Clean up deletion flags
                for svc in services:
                    st.session_state.pop(f"_delete_svc_{svc['id']}", None)
                st.success("✅ Послуги оновлено!")
                st.rerun()

        # ── Add new service ──
        st.divider()
        st.subheader("➕ Додати нову послугу")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_name = st.text_input("Назва", key="new_svc_name_settings")
        with col2:
            new_price = st.number_input("Ціна (UAH)", value=300, step=50, key="new_svc_price_settings")
        with col3:
            new_duration = st.number_input("Тривалість (хв)", value=30, step=15, key="new_svc_dur_settings")

        if st.button("➕ Додати послугу", key="add_svc_settings"):
            if new_name.strip():
                new_id = max((s["id"] for s in cfg.get("services", [])), default=0) + 1
                cfg.setdefault("services", []).append(
                    {"id": new_id, "name": new_name.strip(), "price": new_price, "duration_minutes": new_duration}
                )
                save_config(cfg)
                st.success(f"✅ Послугу '{new_name}' додано!")
                st.rerun()
            else:
                st.error("Введіть назву послуги.")


# ── Page: Statistics ──
def page_stats():
    st.title("📊 Статистика")
    db = Session()
    try:
        bookings = db.query(Booking).filter(Booking.status != "cancelled").all()
        if not bookings:
            st.info("Даних для статистики ще немає.")
            return

        cfg = load_config()
        service_prices = {s["name"]: s["price"] for s in cfg.get("services", [])}

        data = []
        for b in bookings:
            date_part = b.time_slot[:10] if b.time_slot and len(b.time_slot) >= 10 else None
            price = service_prices.get(b.service, 0)
            data.append(
                {
                    "date": date_part,
                    "service": b.service or "—",
                    "master": b.master or "—",
                    "status": b.status,
                    "price": price,
                }
            )

        df = pd.DataFrame(data)
        df = df[df["date"].notna()]

        # ── KPIs ──
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Всього записів", len(df))
        with col2:
            completed_rev = df[df["status"] == "completed"]["price"].sum()
            st.metric("Виручка (завершені)", f"{completed_rev:,.0f} UAH")
        with col3:
            expected_rev = df[df["status"].isin(["confirmed", "pending"])]["price"].sum()
            st.metric("Очікувана виручка", f"{expected_rev:,.0f} UAH")
        with col4:
            total_rev = df["price"].sum()
            st.metric("Загальна виручка", f"{total_rev:,.0f} UAH")

        st.divider()

        # ── Bookings per day chart ──
        st.subheader("📈 Записи по днях")
        daily = df.groupby("date").size().reset_index(name="count")
        daily = daily.sort_values("date")
        fig_daily = px.bar(
            daily,
            x="date",
            y="count",
            labels={"date": "Дата", "count": "Кількість записів"},
            title="Кількість записів по днях",
            color_discrete_sequence=["#1f77b4"],
        )
        st.plotly_chart(fig_daily, use_container_width=True)

        # ── Revenue per day ──
        st.subheader("💰 Виручка по днях")
        revenue_daily = df.groupby("date")["price"].sum().reset_index(name="revenue")
        revenue_daily = revenue_daily.sort_values("date")
        fig_rev = px.line(
            revenue_daily,
            x="date",
            y="revenue",
            labels={"date": "Дата", "revenue": "Виручка (UAH)"},
            title="Виручка по днях",
            markers=True,
        )
        st.plotly_chart(fig_rev, use_container_width=True)

        # ── Top services ──
        st.subheader("🏆 Топ послуги")
        top_services = df.groupby("service").size().reset_index(name="count").sort_values("count", ascending=False)
        fig_svc = px.pie(
            top_services,
            names="service",
            values="count",
            title="Розподіл по послугах",
        )
        st.plotly_chart(fig_svc, use_container_width=True)
        st.dataframe(top_services, use_container_width=True)

        # ── Masters workload ──
        st.subheader("👨‍💈 Навантаження по майстрах")
        master_load = df.groupby("master").size().reset_index(name="count").sort_values("count", ascending=False)
        fig_master = px.bar(
            master_load,
            x="master",
            y="count",
            labels={"master": "Майстер", "count": "Кількість записів"},
            title="Записи по майстрах",
            color="master",
        )
        st.plotly_chart(fig_master, use_container_width=True)
    finally:
        db.close()


# ── Main app ──
st.set_page_config(
    page_title="Barbershop Admin",
    page_icon="💈",
    layout="wide",
)

# Auth gate
if not check_auth():
    st.stop()

st.sidebar.title("💈 Адмін-панель")
st.sidebar.markdown(f"_Увійшли як адміністратор_")
if st.sidebar.button("🚪 Вийти"):
    st.session_state.authenticated = False
    st.rerun()

page = st.sidebar.radio(
    "Навігація",
    ["📋 Записи", "🏷️ Тарифи", "📊 Статистика", "⚙️ Налаштування"],
)

if page == "📋 Записи":
    page_bookings()
elif page == "🏷️ Тарифи":
    page_tariffs()
elif page == "📊 Статистика":
    page_stats()
elif page == "⚙️ Налаштування":
    page_settings()
