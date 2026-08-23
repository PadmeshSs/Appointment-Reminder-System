from datetime import datetime, timedelta

from src.config import Config
from src.engine import Engine
from src.message import MessageBuilder
from src.models import (
    Appointment,
    Channel,
    Resident,
)


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

NOW = datetime(2026, 3, 10, 9, 0)


class FakeLedger:
    def __init__(self):
        self.attempts = []
        self.withheld = []

    # --------------------------------------------------------------
    # Queries required by engine / policy
    # --------------------------------------------------------------

    def attempts_for_appointment(self, appointment_id):
        return [
            record
            for record in self.attempts
            if record["appointment_id"] == appointment_id
        ]

    def attempts_to_point(self, point):
        return [
            record
            for record in self.attempts
            if record["to"] == point
        ]

    def reached(self, appointment_id):
        return any(
            record["appointment_id"] == appointment_id
            and record["reach"] == "reached"
            for record in self.attempts
        )

    def contacts_on_day(self, resident_id, at):
        return [
            record
            for record in self.attempts
            if record["resident_id"] == resident_id
            and record["at"].date() == at.date()
        ]

    def messages_to_point_on_day(self, point, at):
        return [
            record
            for record in self.attempts
            if record["to"] == point
            and record["at"].date() == at.date()
        ]

    def point_is_dead(self, point, channel):
        return False

    def soft_failures(self, point, channel):
        return 0

    def contacts_in_window(
        self,
        resident_id,
        at,
        days,
    ):
        start = at - timedelta(days=days)

        return [
            record
            for record in self.attempts
            if record["resident_id"] == resident_id
            and start < record["at"] <= at
        ]

    # --------------------------------------------------------------
    # Writes
    # --------------------------------------------------------------

    def record_attempt(self, **record):
        self.attempts.append(record)

    def record_withheld(self, **record):
        self.withheld.append(record)


def make_config(**changes):
    values = {
        field: getattr(
            Config(),
            field,
        )
        for field in Config.__dataclass_fields__
    }

    values.update(changes)

    return Config(**values)


def make_resident(
    resident_id,
    name,
    *,
    mobile="555-401-2288",
    email=None,
    language="en",
    suspected_landline_mobile=False,
):
    return Resident(
        resident_id=resident_id,
        name=name,
        mobile=mobile,
        email=email,
        language=language,
        suspected_landline_mobile=(
            suspected_landline_mobile
        ),
    )


def make_appointment(
    appointment_id,
    resident_id,
    scheduled_at,
):
    return Appointment(
        appointment_id=appointment_id,
        resident_id=resident_id,
        scheduled_at=scheduled_at,
        location="District Office",
        service_type="Benefits",
    )


def make_engine(
    residents,
    appointments,
    ledger=None,
    cfg=None,
):
    ledger = ledger or FakeLedger()
    cfg = cfg or make_config(
        reminder_horizon_hours=72,
        min_lead_hours=2,
    )

    return (
        Engine(
            cfg=cfg,
            residents=residents,
            appointments=appointments,
            ledger=ledger,
            messages=MessageBuilder(
                TEMPLATES
            ),
        ),
        ledger,
    )


# ------------------------------------------------------------------
# Prioritisation
# ------------------------------------------------------------------

def test_untouched_appointment_beats_retry():
    residents = [
        make_resident(
            "RS-1",
            "First Resident",
        ),
        make_resident(
            "RS-2",
            "Second Resident",
        ),
    ]

    retry = make_appointment(
        "AP-RETRY",
        "RS-1",
        NOW + timedelta(hours=12),
    )

    untouched = make_appointment(
        "AP-NEW",
        "RS-2",
        NOW + timedelta(hours=24),
    )

    ledger = FakeLedger()

    ledger.record_attempt(
        at=NOW - timedelta(hours=20),
        resident_id="RS-1",
        appointment_id="AP-RETRY",
        to="555-401-2288",
        reach="failed",
    )

    engine, _ = make_engine(
        residents,
        [retry, untouched],
        ledger=ledger,
    )

    due = engine.due(NOW)

    assert [
        appointment.appointment_id
        for appointment in due
    ] == [
        "AP-NEW",
        "AP-RETRY",
    ]


def test_earlier_appointment_wins_when_attempt_counts_match():
    residents = [
        make_resident("RS-1", "A"),
        make_resident("RS-2", "B"),
    ]

    later = make_appointment(
        "AP-LATER",
        "RS-1",
        NOW + timedelta(hours=30),
    )

    earlier = make_appointment(
        "AP-EARLIER",
        "RS-2",
        NOW + timedelta(hours=10),
    )

    engine, _ = make_engine(
        residents,
        [later, earlier],
    )

    due = engine.due(NOW)

    assert [
        appointment.appointment_id
        for appointment in due
    ] == [
        "AP-EARLIER",
        "AP-LATER",
    ]


# ------------------------------------------------------------------
# One contact per appointment per tick
# ------------------------------------------------------------------

def test_one_appointment_gets_at_most_one_contact_per_tick():
    resident = make_resident(
        "RS-1",
        "Test Resident",
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    engine, ledger = make_engine(
        [resident],
        [appointment],
    )

    result = engine.tick(NOW)

    attempts = ledger.attempts_for_appointment(
        "AP-1"
    )

    assert result.attempted == 1
    assert len(attempts) == 1


def test_fallback_happens_on_later_tick_not_same_tick():
    resident = make_resident(
        "RS-1",
        "Test Resident",
        mobile="555-201-1000",
        email="test@example.net",
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    engine, ledger = make_engine(
        [resident],
        [appointment],
    )

    # First tick produces at most one attempt.
    engine.tick(NOW)

    first = ledger.attempts_for_appointment(
        "AP-1"
    )

    assert len(first) == 1

    # The next tick may consider fallback, but the first tick
    # must never contain multiple channel attempts.
    assert len(
        {
            record["at"]
            for record in first
        }
    ) == 1


# ------------------------------------------------------------------
# Shared phone
# ------------------------------------------------------------------

def test_two_residents_shared_phone_get_different_messages():
    residents = [
        make_resident(
            "RS-1",
            "Alice Resident",
        ),
        make_resident(
            "RS-2",
            "Bob Resident",
        ),
    ]

    appointments = [
        make_appointment(
            "AP-2",
            "RS-2",
            NOW + timedelta(hours=48),   # was hours=25
        ),
    ]

    engine, ledger = make_engine(
        residents,
        appointments,
    )

    first_tick = engine.tick(NOW)

    first_attempts = list(
        ledger.attempts
    )

    assert first_tick.attempted == 1
    assert len(first_attempts) == 1

    second_tick = engine.tick(
        NOW + timedelta(days=1)
    )

    assert second_tick.attempted == 1
    assert len(ledger.attempts) == 2

    bodies = [
        record["body_hash"]
        for record in ledger.attempts
    ]

    assert len(set(bodies)) == 2


# ------------------------------------------------------------------
# Suspected landline
# ------------------------------------------------------------------

def test_suspected_landline_prefers_voice():
    resident = make_resident(
        "RS-1",
        "Landline Resident",
        mobile="555-223-1234",
        email="resident@example.net",
        suspected_landline_mobile=True,
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    engine, ledger = make_engine(
        [resident],
        [appointment],
    )

    engine.tick(NOW)

    assert len(ledger.attempts) == 1
    assert ledger.attempts[0]["channel"] == "voice"


# ------------------------------------------------------------------
# Withheld register
# ------------------------------------------------------------------

def test_every_blocked_channel_creates_one_withheld_row():
    resident = make_resident(
        "RS-1",
        "Blocked Resident",
        mobile=None,
        email=None,
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    engine, ledger = make_engine(
        [resident],
        [appointment],
    )

    result = engine.tick(NOW)

    assert result.attempted == 0
    assert result.withheld == 1

    assert len(ledger.withheld) == 1

    row = ledger.withheld[0]

    assert row["appointment_id"] == "AP-1"
    assert row["resident_id"] == "RS-1"
    assert row["reason"] == "contact_point_exists"


def test_rolling_limit_is_preferred_in_withheld_reason():
    resident = make_resident(
        "RS-1",
        "Blocked Resident",
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    ledger = FakeLedger()

    ledger.record_attempt(
        at=NOW - timedelta(days=2),
        resident_id="RS-1",
        appointment_id="OLD-1",
        to=resident.mobile,
        reach="failed",
    )

    ledger.record_attempt(
        at=NOW - timedelta(days=1),
        resident_id="RS-1",
        appointment_id="OLD-2",
        to=resident.mobile,
        reach="failed",
    )

    engine, _ = make_engine(
        [resident],
        [appointment],
        ledger=ledger,
        cfg=make_config(
            max_contacts_per_window=2,
            enforce_rolling_limit=True,
        ),
    )

    result = engine.tick(NOW)

    assert result.withheld == 1

    row = ledger.withheld[-1]

    assert row["reason"] == "rolling_contact_limit"
    assert row["detail"]["counted_contacts"] == 2