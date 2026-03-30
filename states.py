from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_master = State()
    choosing_time = State()
    confirming_booking = State()
    entering_name = State()
    entering_phone = State()
    waiting_for_consult = State()
    viewing_about = State()


class CancelConfirm(StatesGroup):
    waiting_confirmation = State()


class CancelBooking(StatesGroup):
    viewing_bookings = State()
    confirm_cancel = State()


class ReviewStates(StatesGroup):
    waiting_text = State()


class RescheduleStates(StatesGroup):
    choosing_date = State()
    choosing_time = State()


class MasterStates(StatesGroup):
    waiting_block_date = State()
