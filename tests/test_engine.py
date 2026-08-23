from datetime import datetime, timedelta
from pathlib import Path

from src.config import Config
from src.engine import Engine
from src.history import Ledger
from src.message import MessageBuilder
from src.models import (
    Appointment,
    Channel,
    Resident,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

NOW = datetime(2026, 3, 10, 9, 0)


def seed_attempt(
    ledger: Ledger,
    *,
    appointment_id: str,
    at: datetime,
    resident_id: str = "RS-1",
    identity_key: str | None = None,
    to: str = "555-401-2288",
    channel: str = "sms",
    attempt: int = 1,
    reach: str = "failed",
    point_health: str = "ok",
) -> None:
    """
    Write one attempt directly into the real Ledger, for tests that
    need contact history to already exist BEFORE the engine runs
    (e.g. testing prioritisation or the rolling limit). Fills in
    every field append_attempt requires, with sensible defaults for
    whatever the specific test doesn't care about.
    """

    ledger.append_attempt(
        at=at,
        resident_id=resident_id,
        identity_key=identity_key,
        appointment_id=appointment_id,
        channel=channel,
        to=to,
        attempt=attempt,
        language="en",
        language_fallback=False,
        body_hash=f"seed-{appointment_id}-{attempt}",
        status=reach,
        detail="",
        reach=reach,
        point_health=point_health,
    )


def withheld_records(ledger: Ledger) -> list[dict]:
    """
    Every withheld row currently in the ledger. The real Ledger
    exposes a single `.records` property mixing both record kinds
    (each tagged `record["kind"]`) rather than separate `.attempts` /
    `.withheld` lists, so tests filter by kind here instead of
    poking at an attribute the production class doesn't have.
    """

    return [record for record in ledger.records if record["kind"] == "withheld"]


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
    tmp_path,
    ledger=None,
    cfg=None,
):
    ledger = ledger or Ledger(tmp_path / "history.jsonl")
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

def test_untouched_appointment_beats_retry(tmp_path):
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

    ledger = Ledger(tmp_path / "history.jsonl")

    seed_attempt(
        ledger,
        appointment_id="AP-RETRY",
        resident_id="RS-1",
        at=NOW - timedelta(hours=20),
        reach="failed",
    )

    engine, _ = make_engine(
        residents,
        [retry, untouched],
        tmp_path,
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


def test_earlier_appointment_wins_when_attempt_counts_match(tmp_path):
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
        tmp_path,
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

def test_one_appointment_gets_at_most_one_contact_per_tick(tmp_path):
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
        tmp_path,
    )

    result = engine.tick(NOW)

    attempts = ledger.attempts_for_appointment(
        "AP-1"
    )

    assert result.attempted == 1
    assert len(attempts) == 1


def test_fallback_happens_on_later_tick_not_same_tick(tmp_path):
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
        tmp_path,
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
# Shared phone / channel fallback across ticks
# ------------------------------------------------------------------

def test_two_residents_shared_phone_get_different_messages(tmp_path):
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
        tmp_path,
    )

    first_tick = engine.tick(NOW)

    first_attempts = ledger.attempts_for_appointment("AP-2")

    assert first_tick.attempted == 1
    assert len(first_attempts) == 1

    second_tick = engine.tick(
        NOW + timedelta(days=1)
    )

    assert second_tick.attempted == 1

    all_attempts = ledger.attempts_for_appointment("AP-2")

    assert len(all_attempts) == 2

    bodies = [
        record["body_hash"]
        for record in all_attempts
    ]

    assert len(set(bodies)) == 2


# ------------------------------------------------------------------
# Suspected landline
# ------------------------------------------------------------------

def test_suspected_landline_prefers_voice(tmp_path):
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
        tmp_path,
    )

    engine.tick(NOW)

    attempts = ledger.attempts_for_appointment("AP-1")

    assert len(attempts) == 1
    assert attempts[0]["channel"] == "voice"


# ------------------------------------------------------------------
# Withheld register
# ------------------------------------------------------------------

def test_every_blocked_channel_creates_one_withheld_row(tmp_path):
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
        tmp_path,
    )

    result = engine.tick(NOW)

    assert result.attempted == 0
    assert result.withheld == 1

    rows = withheld_records(ledger)

    assert len(rows) == 1

    row = rows[0]

    assert row["appointment_id"] == "AP-1"
    assert row["resident_id"] == "RS-1"
    assert row["reason"] == "contact_point_exists"


def test_rolling_limit_is_preferred_in_withheld_reason(tmp_path):
    resident = make_resident(
        "RS-1",
        "Blocked Resident",
    )

    appointment = make_appointment(
        "AP-1",
        "RS-1",
        NOW + timedelta(hours=24),
    )

    ledger = Ledger(tmp_path / "history.jsonl")

    seed_attempt(
        ledger,
        appointment_id="OLD-1",
        resident_id="RS-1",
        at=NOW - timedelta(days=2),
        to=resident.mobile,
        reach="failed",
    )

    seed_attempt(
        ledger,
        appointment_id="OLD-2",
        resident_id="RS-1",
        at=NOW - timedelta(days=1),
        to=resident.mobile,
        reach="failed",
    )

    engine, _ = make_engine(
        [resident],
        [appointment],
        tmp_path,
        ledger=ledger,
        cfg=make_config(
            max_contacts_per_window=2,
            enforce_rolling_limit=True,
        ),
    )

    result = engine.tick(NOW)

    assert result.withheld == 1

    rows = withheld_records(ledger)

    row = rows[-1]

    assert row["reason"] == "rolling_contact_limit"
    assert row["detail"]["counted_contacts"] == 2