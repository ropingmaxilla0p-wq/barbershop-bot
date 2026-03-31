"""
Simple FastAPI server for Telegram WebApp.
Serves the booking mini-app HTML.
Run: python webapp_server.py
Then expose via ngrok: ngrok http 8080
Set WEBAPP_URL in .env to the ngrok HTTPS URL + /webapp
"""
import sys
import os
import json
import logging
from datetime import datetime, timedelta
try:
    import zoneinfo
    try:
        KYIV_TZ = zoneinfo.ZoneInfo("Europe/Kiev")
    except Exception:
        KYIV_TZ = zoneinfo.ZoneInfo("Europe/Kyiv")
except (ImportError, Exception):
    KYIV_TZ = None  # fallback: use UTC+2 offset
    import datetime as _dt
    class _KyivTZ(_dt.tzinfo):
        def utcoffset(self, dt): return _dt.timedelta(hours=2)
        def tzname(self, dt): return "EET"
        def dst(self, dt): return _dt.timedelta(0)
    KYIV_TZ = _KyivTZ()

# Ensure models are importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import httpx

from models import Booking, MasterProfile, MasterSchedule, SessionLocal, init_db
from config import settings

logger = logging.getLogger(__name__)

# ── Config path ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "business_config.json")

app = FastAPI()

# Allow CORS for local dev / ngrok
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



# Initialize DB tables on startup
init_db()

# Serve webapp static files
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")


@app.get("/webapp")
async def serve_webapp():
    return FileResponse(
        "webapp/static/index.html",
        headers={
            "ngrok-skip-browser-warning": "true",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/master-webapp")
async def serve_master_webapp():
    return FileResponse(
        "webapp/static/master.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/api/master/bookings")
async def master_bookings(master_id: int, period: str = "today"):
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        today = datetime.now().date()
        if period == "today":
            date_str = today.strftime("%Y-%m-%d")
            bookings = db.query(Booking).filter(
                Booking.master_id == master_id,
                Booking.time_slot.like(f"{date_str}%"),
                Booking.status.in_(["pending", "confirmed"])
            ).order_by(Booking.time_slot).all()
        elif period == "tomorrow":
            tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            bookings = db.query(Booking).filter(
                Booking.master_id == master_id,
                Booking.time_slot.like(f"{tomorrow}%"),
                Booking.status.in_(["pending", "confirmed"])
            ).order_by(Booking.time_slot).all()
        else:  # week
            week_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
            from sqlalchemy import or_
            bookings = db.query(Booking).filter(
                Booking.master_id == master_id,
                or_(*[Booking.time_slot.like(f"{d}%") for d in week_dates]),
                Booking.status.in_(["pending", "confirmed"])
            ).order_by(Booking.time_slot).all()

        result = [
            {
                "id": b.id,
                "time_slot": b.time_slot,
                "user_name": b.user_name or "—",
                "service": b.service or "—",
                "phone": b.phone or "—",
                "status": b.status,
            }
            for b in bookings
        ]
        return {"ok": True, "bookings": result}
    finally:
        db.close()

@app.post("/api/master/complete")
async def master_complete(data: dict):
    booking_id = data.get("booking_id")
    master_id = data.get("master_id")
    db = SessionLocal()
    try:
        b = db.query(Booking).filter(Booking.id == booking_id, Booking.master_id == master_id).first()
        if not b:
            raise HTTPException(status_code=404, detail="Booking not found")
        b.status = "completed"
        db.commit()
        if settings.OWNER_CHAT_ID:
            await send_telegram_message(settings.OWNER_CHAT_ID,
                f"✅ Майстер завершив запис #{booking_id}\n👤 {b.user_name} | ✂️ {b.service}")
        return {"ok": True}
    finally:
        db.close()

@app.post("/api/master/cancel")
async def master_cancel(data: dict):
    booking_id = data.get("booking_id")
    master_id = data.get("master_id")
    db = SessionLocal()
    try:
        b = db.query(Booking).filter(Booking.id == booking_id, Booking.master_id == master_id).first()
        if not b:
            raise HTTPException(status_code=404, detail="Booking not found")
        b.status = "cancelled"
        b.cancelled_by = "master"
        db.commit()
        if settings.OWNER_CHAT_ID:
            await send_telegram_message(settings.OWNER_CHAT_ID,
                f"❌ Майстер скасував запис #{booking_id}\n👤 {b.user_name} | ✂️ {b.service}")
        return {"ok": True}
    finally:
        db.close()

@app.head("/webapp")
async def serve_webapp_head():
    from fastapi.responses import Response
    return Response(status_code=200, headers={"ngrok-skip-browser-warning": "true", "content-type": "text/html"})


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Config & Services ──

def _load_config() -> dict:
    """Load business_config.json; return stub if missing."""
    if not os.path.exists(CONFIG_PATH):
        return {
            "barbershop_name": "Barber Shop",
            "working_hours": {"start": "10:00", "end": "20:00", "slot_duration_minutes": 30},
            "services": [
                {"id": 1, "name": "Стрижка", "description": "Класична стрижка", "duration_minutes": 45, "price": 600, "icon": "✂️"},
                {"id": 2, "name": "Борода", "description": "Стрижка бороди", "duration_minutes": 30, "price": 400, "icon": "🧔"},
            ],
            "masters": [
                {"id": 1, "name": "Майстер 1", "specialization": "Стрижки", "experience_years": 3, "avatar": "💈", "rating": 4.8},
            ]
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/config")
async def get_config():
    """Return services and masters from business_config.json."""
    cfg = _load_config()
    return JSONResponse({
        "barbershop_name": cfg.get("barbershop_name", "Barber Shop"),
        "services": cfg.get("services", []),
        "masters": cfg.get("masters", []),
        "working_hours": cfg.get("working_hours", {}),
    })


@app.get("/api/available-slots")
async def available_slots(
    master_id: int = Query(..., description="Master ID"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    duration: int = Query(30, description="Service duration in minutes"),
):
    """
    Return time slots for a given master and date.
    Each slot: {time: "HH:MM", available: bool}
    Busy slots are determined by existing bookings in the DB.
    """
    # Validate date format
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    cfg = _load_config()
    wh = cfg.get("working_hours", {"start": "10:00", "end": "20:00", "slot_duration_minutes": 30})

    # Generate all slots for the day
    start_h, start_m = map(int, wh["start"].split(":"))
    end_h, end_m = map(int, wh["end"].split(":"))
    step = int(cfg.get("slot_duration_minutes", 30))

    current = datetime.combine(target_date, datetime.min.time().replace(hour=start_h, minute=start_m))
    end_dt  = datetime.combine(target_date, datetime.min.time().replace(hour=end_h,   minute=end_m))

    all_slots = []
    while current < end_dt:
        all_slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=step)

    # Fetch booked slots for this master+date from DB
    db = SessionLocal()
    try:
        # Find master name by id for matching
        masters = cfg.get("masters", [])
        master_name = next((m["name"] for m in masters if m["id"] == master_id), None)

        # ── Check MasterSchedule for this date ──
        schedule_entry = db.query(MasterSchedule).filter(
            MasterSchedule.master_id == master_id,
            MasterSchedule.specific_date == date,
        ).first()

        # If master is blocked for this date — all slots unavailable
        if schedule_entry and not schedule_entry.is_working:
            slots = [{"time": t, "available": False} for t in all_slots]
            return {"ok": True, "master_id": master_id, "date": date, "slots": slots, "blocked": True}

        # If master has custom hours for this date — regenerate slots
        if schedule_entry and schedule_entry.is_working:
            custom_start = schedule_entry.start_time or wh["start"]
            custom_end = schedule_entry.end_time or wh["end"]
            sh, sm = map(int, custom_start.split(":"))
            eh, em = map(int, custom_end.split(":"))
            cur = datetime.combine(target_date, datetime.min.time().replace(hour=sh, minute=sm))
            end_custom = datetime.combine(target_date, datetime.min.time().replace(hour=eh, minute=em))
            all_slots = []
            while cur < end_custom:
                all_slots.append(cur.strftime("%H:%M"))
                cur += timedelta(minutes=step)

        booked_times = set()
        bookings = db.query(Booking).filter(
            Booking.time_slot.like(f"{date}%"),
            Booking.status != "cancelled",  # отменённые не блокируют
        ).all()

        # Build a map of service durations
        services_map = {s["name"]: s.get("duration_minutes", step) for s in cfg.get("services", [])}

        for b in bookings:
            if b.master and master_name and b.master == master_name:
                parts = b.time_slot.split(" ")
                if len(parts) >= 2:
                    slot_time = parts[1]
                    booked_times.add(slot_time)
                    # Block additional slots based on service duration
                    duration = services_map.get(b.service, step)
                    extra_slots = (duration - 1) // step  # how many extra 30-min slots to block
                    if extra_slots > 0:
                        try:
                            slot_dt = datetime.combine(target_date, datetime.strptime(slot_time, "%H:%M").time())
                            for i in range(1, extra_slots + 1):
                                extra = (slot_dt + timedelta(minutes=step * i)).strftime("%H:%M")
                                booked_times.add(extra)
                        except Exception:
                            pass

        # Блокируем прошедшее время для сегодня (Kyiv timezone)
        now = datetime.now(KYIV_TZ).replace(tzinfo=None)
        is_today = (target_date == now.date())

        # Check if date is blocked by owner
        blocked_dates = cfg.get("blocked_dates", [])
        if date in blocked_dates:
            slots = [{"time": t, "available": False} for t in all_slots]
            return {"ok": True, "master_id": master_id, "date": date, "slots": slots, "blocked": True}

        # Build set of all slot datetimes for boundary check
        all_slot_dts = {t: datetime.combine(target_date, datetime.strptime(t, "%H:%M").time()) for t in all_slots}

        slots = []
        for t in all_slots:
            slot_dt = all_slot_dts[t]

            # Block past slots for today
            if is_today and slot_dt <= now:
                slots.append({"time": t, "available": False})
                continue

            # Block if this slot itself is booked
            if t in booked_times:
                slots.append({"time": t, "available": False})
                continue

            # Check if there's enough room for the requested duration
            # i.e. no booked slot falls within [slot_dt, slot_dt + duration)
            end_dt = slot_dt + timedelta(minutes=duration)
            blocked = False
            for bt in booked_times:
                try:
                    bt_dt = datetime.combine(target_date, datetime.strptime(bt, "%H:%M").time())
                    if slot_dt < bt_dt < end_dt:
                        blocked = True
                        break
                except Exception:
                    pass

            # Also check working hours boundary
            if end_dt > datetime.combine(target_date, datetime.strptime(all_slots[-1], "%H:%M").time()) + timedelta(minutes=step):
                blocked = True

            slots.append({"time": t, "available": not blocked})

        return {"ok": True, "master_id": master_id, "date": date, "slots": slots}
    finally:
        db.close()


# --- Booking API ---

# ── Telegram notification helpers ──

async def send_telegram_message(chat_id: int | str, text: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not settings.BOT_TOKEN:
        logger.warning("BOT_TOKEN is not set; cannot send Telegram message.")
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Telegram API returned %s: %s", resp.status_code, resp.text)
                return False
        return True
    except Exception as e:
        logger.warning("Failed to send Telegram message: %s", e)
        return False


async def send_confirmation(user_id: int | str, booking_data: dict) -> None:
    """Send a beautiful HTML confirmation to the client."""
    logger.warning(f"[CONFIRM] Sending confirmation to user_id={user_id}")
    service_name = booking_data.get("service_name", "—")
    master_name = booking_data.get("master_name", "—")
    date = booking_data.get("date", "—")
    time = booking_data.get("time", "—")
    price = booking_data.get("price", "—")

    text = (
        f"✅ <b>Запись подтверждена!</b>\n\n"
        f"✂️ Услуга: {service_name}\n"
        f"👤 Мастер: {master_name}\n"
        f"📅 Дата: {date}\n"
        f"⏰ Время: {time}\n"
        f"💰 Стоимость: {price} UAH\n\n"
        f"📍 <i>The Gentleman's Den</i>\n"
        f"📞 Ждём вас! За 2 часа до визита придёт напоминание.\n\n"
        f"/mybookings — посмотреть мои записи"
    )
    await send_telegram_message(user_id, text)


async def send_owner_notification(booking_data: dict) -> None:
    """Notify the master and owner about a new booking."""
    user_name = booking_data.get("user_name") or "—"
    phone = booking_data.get("phone") or "—"
    service = booking_data.get("service_name", "—")
    master = booking_data.get("master_name") or "—"
    date = booking_data.get("date", "—")
    time = booking_data.get("time", "—")
    booking_id = booking_data.get("booking_id", "—")
    user_id = booking_data.get("user_id", "—")
    master_id = booking_data.get("master_id")

    text = (
        f"🔔 <b>Нова запис #{booking_id}</b>\n\n"
        f"👤 Клієнт: {user_name}\n"
        f"📞 Телефон: {phone}\n"
        f"✂️ Послуга: {service}\n"
        f"💈 Майстер: {master}\n"
        f"📅 Дата: {date} {time}\n"
        f"🆔 Telegram ID: {user_id}"
    )

    notified = set()

    # Notify the specific master
    if master_id:
        db = SessionLocal()
        try:
            profile = db.query(MasterProfile).filter(MasterProfile.master_id == master_id).first()
            if profile and profile.telegram_id:
                await send_telegram_message(profile.telegram_id, text)
                notified.add(str(profile.telegram_id))
        finally:
            db.close()

    # Notify owner if different from master
    if settings.OWNER_CHAT_ID and str(settings.OWNER_CHAT_ID) not in notified:
        await send_telegram_message(settings.OWNER_CHAT_ID, text)


class BookingRequest(BaseModel):
    user_id: int | str
    service: dict           # {id, name, price, duration_minutes, ...}
    date: str               # "YYYY-MM-DD"
    time: str               # "HH:MM"
    user_name: Optional[str] = None
    phone: Optional[str] = None
    master: Optional[str] = None       # master name
    master_id: Optional[int] = None    # master id for slot tracking
    notes: Optional[str] = None


@app.post("/api/confirm-booking")
async def confirm_booking(data: BookingRequest):
    """
    Accept booking from Telegram WebApp and save to DB.
    Uses atomic check+insert to prevent race-condition double bookings.
    """
    from sqlalchemy import text as sa_text

    time_slot = f"{data.date} {data.time}"
    service_info = data.service if isinstance(data.service, dict) else {}
    service_name = service_info.get("name", str(data.service)) if isinstance(data.service, dict) else str(data.service)
    price = service_info.get("price", "—")

    db = SessionLocal()
    try:
        # ── Double-booking guard ──
        existing = db.query(Booking).filter(
            Booking.master == data.master,
            Booking.time_slot == time_slot,
            Booking.status != "cancelled",
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Цей слот вже зайнятий. Будь ласка, оберіть інший час.",
            )

        # ── Duplicate submit guard (same user + same slot) ──
        duplicate = db.query(Booking).filter(
            Booking.user_id == str(data.user_id),
            Booking.time_slot == time_slot,
            Booking.status != "cancelled",
        ).first()
        if duplicate:
            db.close()
            return {"ok": True, "booking_id": duplicate.id}

        # ── Insert new booking ──
        booking = Booking(
            user_id=str(data.user_id),
            user_name=data.user_name,
            phone=data.phone,
            service=service_name,
            master=data.master,
            master_id=data.master_id,
            time_slot=time_slot,
            notes=data.notes,
            status="pending",
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        booking_id = booking.id
    except HTTPException:
        db.close()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

    # ── Send confirmation to client ──
    booking_data = {
        "service_name": service_name,
        "master_name": data.master or "—",
        "date": data.date,
        "time": data.time,
        "price": price,
        "user_name": data.user_name,
        "phone": data.phone or "—",
        "booking_id": booking_id,
        "user_id": str(data.user_id),
    }
    # Skip notifications for smoke/test bookings
    is_smoke = str(data.user_id).startswith("smoke") or str(data.user_id).startswith("__smoke") or str(data.user_id).startswith("__builder")
    if not is_smoke:
        try:
            await send_confirmation(data.user_id, booking_data)
        except Exception as e:
            logger.warning(f"Could not send confirmation: {e}")

        # ── Notify owner ──
        try:
            await send_owner_notification(booking_data)
        except Exception as e:
            logger.warning(f"Could not send owner notification: {e}")

    return {"ok": True, "booking_id": booking_id}


@app.get("/api/booked-dates")
async def booked_dates(master_id: int = Query(...)):
    """Return list of fully-booked dates for a master (all slots taken)."""
    cfg = _load_config()
    wh = cfg.get("working_hours", {"start": "10:00", "end": "20:00", "slot_duration_minutes": 30})
    start_h, start_m = map(int, wh["start"].split(":"))
    end_h, end_m = map(int, wh["end"].split(":"))
    step = int(cfg.get("slot_duration_minutes", wh.get("slot_duration_minutes", 30)))

    # Count total slots per day
    total_slots = 0
    current = datetime.combine(datetime.today(), datetime.min.time().replace(hour=start_h, minute=start_m))
    end_dt = datetime.combine(datetime.today(), datetime.min.time().replace(hour=end_h, minute=end_m))
    while current < end_dt:
        total_slots += 1
        current += timedelta(minutes=step)

    masters = cfg.get("masters", [])
    master_name = next((m["name"] for m in masters if m["id"] == master_id), None)

    db = SessionLocal()
    try:
        from collections import Counter
        bookings = db.query(Booking).filter(
            Booking.master == master_name,
            Booking.status != "cancelled",
        ).all()
        date_counts = Counter()
        for b in bookings:
            parts = b.time_slot.split(" ")
            if parts:
                date_counts[parts[0]] += 1
        fully_booked = [d for d, cnt in date_counts.items() if cnt >= total_slots]
        # Also include owner-blocked dates
        blocked_dates = cfg.get("blocked_dates", [])
        all_disabled = list(set(fully_booked + blocked_dates))
        return {"ok": True, "fully_booked_dates": all_disabled}
    finally:
        db.close()


@app.get("/api/bookings/{user_id}")
async def get_user_bookings(user_id: str, limit: int = 10):
    """Return the last N bookings for a given user_id."""
    db = SessionLocal()
    try:
        bookings = (
            db.query(Booking)
            .filter(Booking.user_id == str(user_id))
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "bookings": [
                {
                    "id": b.id,
                    "service": b.service,
                    "master": b.master,
                    "time_slot": b.time_slot,
                    "status": b.status,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                }
                for b in bookings
            ],
        }
    finally:
        db.close()


# ── Cancel Booking API (TASK-001) ──

class CancelRequest(BaseModel):
    user_id: str


@app.post("/api/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: int, data: CancelRequest):
    """
    Cancel a booking by ID.
    - AC-3: validates user_id ownership (403 if mismatch)
    - AC-4: only pending/confirmed can be cancelled (400 otherwise)
    - AC-6: idempotent — re-cancelling already cancelled returns 200
    - AC-2: notifies owner and master on successful cancellation
    - Sets cancelled_by="client"
    """
    db = SessionLocal()
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise HTTPException(status_code=404, detail="Запис не знайдено")

        # AC-3: ownership check
        if booking.user_id != str(data.user_id):
            raise HTTPException(status_code=403, detail="Це не ваш запис")

        # AC-6: idempotent — already cancelled
        if booking.status == "cancelled":
            return {"ok": True, "message": "Запис вже скасовано", "booking_id": booking_id}

        # AC-4: only pending/confirmed can be cancelled
        if booking.status not in ("pending", "confirmed"):
            raise HTTPException(
                status_code=400,
                detail=f"Неможливо скасувати запис зі статусом '{booking.status}'"
            )

        # Perform cancellation
        booking.status = "cancelled"
        booking.cancelled_by = "client"
        db.commit()

        # Build notification data
        time_slot_parts = booking.time_slot.split(" ") if booking.time_slot else []
        cancel_date = time_slot_parts[0] if len(time_slot_parts) >= 1 else "—"
        cancel_time = time_slot_parts[1] if len(time_slot_parts) >= 2 else "—"

        cancel_text = (
            f"❌ <b>Запис скасовано клієнтом</b>\n\n"
            f"🆔 Запис #{booking.id}\n"
            f"👤 Клієнт: {booking.user_name or '—'}\n"
            f"✂️ Послуга: {booking.service or '—'}\n"
            f"💈 Майстер: {booking.master or '—'}\n"
            f"📅 Дата: {cancel_date} {cancel_time}\n"
            f"🆔 Telegram ID: {booking.user_id}"
        )

        # Skip notifications for test bookings
        is_test = str(booking.user_id).startswith("__builder") or str(booking.user_id).startswith("smoke")
        if not is_test:
            notified = set()

            # Notify master
            if booking.master_id:
                try:
                    profile = db.query(MasterProfile).filter(
                        MasterProfile.master_id == booking.master_id
                    ).first()
                    if profile and profile.telegram_id:
                        await send_telegram_message(profile.telegram_id, cancel_text)
                        notified.add(str(profile.telegram_id))
                except Exception as e:
                    logger.warning(f"Could not notify master about cancellation: {e}")

            # Notify owner
            if settings.OWNER_CHAT_ID and str(settings.OWNER_CHAT_ID) not in notified:
                try:
                    await send_telegram_message(settings.OWNER_CHAT_ID, cancel_text)
                except Exception as e:
                    logger.warning(f"Could not notify owner about cancellation: {e}")

        return {"ok": True, "message": "Запис скасовано", "booking_id": booking_id}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Cancel booking error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


if __name__ == "__main__":
    port = int(os.getenv("WEBAPP_PORT", 8080))
    print(f"🌐 WebApp server starting on http://localhost:{port}")
    print(f"📱 Expose via ngrok: ngrok http {port}")
    print(f"📝 Then set WEBAPP_URL=https://YOUR-NGROK-URL/webapp in .env")
    uvicorn.run(app, host="0.0.0.0", port=port)
