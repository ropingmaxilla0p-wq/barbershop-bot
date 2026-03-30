from sqlalchemy import Column, Integer, String, DateTime, Boolean, create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    language = Column(String, default="ua")
    created_at = Column(DateTime, default=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    user_name = Column(String)
    phone = Column(String)
    service = Column(String)
    master = Column(String)
    master_id = Column(Integer, nullable=True)
    time_slot = Column(String)
    notes = Column(String)  # For AI Stylist advice storage
    status = Column(String, default="pending")  # pending / confirmed / cancelled / completed
    cancelled_by = Column(String, nullable=True)  # "client" / "master" / "admin"
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reminder_24h_sent = Column(Boolean, default=False)
    reminder_2h_sent = Column(Boolean, default=False)
    review_sent = Column(Boolean, default=False)
    review_rating = Column(Integer, nullable=True)
    review_text = Column(String, nullable=True)


class MasterSchedule(Base):
    """Master working schedule — can define day-of-week defaults or specific date overrides."""
    __tablename__ = "master_schedules"

    id = Column(Integer, primary_key=True, index=True)
    master_id = Column(Integer, nullable=False)
    day_of_week = Column(Integer, nullable=True)   # 0=Monday … 6=Sunday; None if specific_date set
    specific_date = Column(String, nullable=True)   # "YYYY-MM-DD"; None if day_of_week set
    is_working = Column(Boolean, default=True)
    start_time = Column(String, default="09:00")   # "HH:MM"
    end_time = Column(String, default="20:00")     # "HH:MM"


class MasterProfile(Base):
    """Links a barbershop master (by numeric id) to a Telegram account."""
    __tablename__ = "master_profiles"

    master_id = Column(Integer, primary_key=True)
    telegram_id = Column(String, nullable=True)    # Telegram user_id as string
    photo_url = Column(String, nullable=True)


# Database Setup
DATABASE_URL = "sqlite:///./barbershop.db"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 10},
)


@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    """Enable WAL mode for better concurrent access."""
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA busy_timeout=5000")
    dbapi_connection.execute("PRAGMA read_uncommitted=1")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=True, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_db()


def _migrate_db():
    """Add any missing columns to existing tables (SQLite ALTER TABLE)."""
    from sqlalchemy import text, inspect as sa_inspect
    inspector = sa_inspect(engine)

    # New columns to add to bookings table
    booking_migrations = [
        ("master_id", "INTEGER"),
        ("cancelled_by", "VARCHAR"),
        ("confirmed_at", "DATETIME"),
        ("completed_at", "DATETIME"),
    ]

    existing_cols = {c["name"] for c in inspector.get_columns("bookings")}
    with engine.connect() as conn:
        for col_name, col_type in booking_migrations:
            if col_name not in existing_cols:
                conn.execute(
                    text(f"ALTER TABLE bookings ADD COLUMN {col_name} {col_type}")
                )
        conn.commit()


def get_booked_slots(date: str, master: str) -> list:
    """Return list of occupied time_slot strings for a given master and date.

    `date` should be a string prefix that the stored time_slot starts with,
    e.g. "2024-12-25" or simply a time prefix like "10:" when date is embedded
    in the slot string.  For the current FSM flow time_slot stores time only
    (e.g. "10:00"), so we match by master only when no date is recorded.
    When time_slot contains a date part (e.g. "2024-12-25 10:00") we filter
    by both date and master.
    """
    db = SessionLocal()
    try:
        query = db.query(Booking).filter(
            Booking.master == master,
            Booking.status != "cancelled",
        )
        results = query.all()
        booked = []
        for b in results:
            if b.time_slot:
                # If slot contains date info, filter by date prefix
                if " " in b.time_slot:
                    slot_date = b.time_slot.split(" ")[0]
                    if slot_date == date:
                        booked.append(b.time_slot.split(" ")[1])
                else:
                    # No date in slot — return all slots for this master
                    # (caller should filter by date externally if needed)
                    booked.append(b.time_slot)
        return booked
    finally:
        db.close()
