from datetime import datetime, timedelta

import pytest

from src.config import Config
from src.models import Appointment, Channel, Resident
from src.policy import Authorization, authorize, evaluate, verify


NOW = datetime(2026, 3, 10, 10, 0)


class FakeLedger:
    """Small ledger double containing only what Chapter 6 needs."""

    def __init__(
        self,
        *,
        appointment_attempts=None,
        point_attempts=None,
        reached=False,
        contacts_today=0,
        point_messages_today=0,
        dead=False,
        soft_failures=0,
    ):
        self._appointment_attempts = (
            appointment_attempts or []
        )
        self._point_attempts = (
            point_attempts or []
        )
        self._reached = reached
        self._contacts_today = contacts_today
        self._point_messages_today = point_messages_today
        self._dead = dead
        self._soft_failures = soft_failures

    def attempts_for_appointment(self, appointment_id):
        return self._appointment_attempts

    def attempts_to_point(self, point):
        return self._point_attempts

    def reached(self, appointment_id):
        return self._reached

    def contacts_on_day(self, resident_id, at):
        return [{}] * self._contacts_today
    
    def messages_to_point_on_day(self, point, at):
        return [{}] * self._point_messages_today

    def point_is_dead(self, point, channel):
        return self._dead

    def soft_failures(self, point, channel):
        return self._soft_failures


def make_resident(
    *,
    mobile="555-401-2288",
    email="person@example.net",
    sms_optout=False,
    voice_optout=False,
    email_optout=False,
):
    return Resident(
        resident_id="RS-TEST",
        name="Test Resident",
        mobile=mobile,
        email=email,
        language="en",
        sms_optout=sms_optout,
        voice_optout=voice_optout,
        email_optout=email_optout,
    )


def make_appointment(
    *,
    scheduled_at=NOW + timedelta(hours=24),
):
    return Appointment(
        appointment_id="AP-TEST",
        resident_id="RS-TEST",
        scheduled_at=scheduled_at,
        location="District Office",
        service_type="Benefits",
    )


def make_cfg(**changes):
    cfg = Config()

    values = {
        field: getattr(cfg, field)
        for field in cfg.__dataclass_fields__
    }

    values.update(changes)

    return Config(**values)


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------

def test_sms_opt_out_blocks_sms_only():
    resident = make_resident(
        sms_optout=True,
    )
    appointment = make_appointment()
    ledger = FakeLedger()

    sms = evaluate(
        Config(),
        ledger,
        resident,
        appointment,
        Channel.SMS,
        NOW,
    )

    voice = evaluate(
        Config(),
        ledger,
        resident,
        appointment,
        Channel.VOICE,
        NOW,
    )

    assert sms.allowed is False
    assert sms.reason == "opt_out"

    assert voice.allowed is True


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def test_quiet_hours_block_at_four_am():
    resident = make_resident()
    appointment = make_appointment()

    now = datetime(2026, 3, 10, 4, 0)

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        now,
    )

    assert decision.allowed is False
    assert decision.reason == "quiet_hours"


def test_quiet_hours_release_at_nine_am():
    resident = make_resident()
    appointment = make_appointment()

    now = datetime(2026, 3, 10, 9, 0)

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        now,
    )

    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Appointment relevance
# ---------------------------------------------------------------------------

def test_passed_appointment_is_blocked():
    resident = make_resident()

    appointment = make_appointment(
        scheduled_at=NOW - timedelta(minutes=1),
    )

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "appointment_relevant"


def test_appointment_less_than_two_hours_away_is_blocked():
    resident = make_resident()

    appointment = make_appointment(
        scheduled_at=NOW + timedelta(hours=1),
    )

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "appointment_relevant"


def test_appointment_more_than_seventy_two_hours_away_is_blocked():
    resident = make_resident()

    appointment = make_appointment(
        scheduled_at=NOW + timedelta(hours=73),
    )

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "appointment_relevant"


# ---------------------------------------------------------------------------
# Contact point
# ---------------------------------------------------------------------------

def test_missing_contact_point_is_blocked():
    resident = make_resident(
        mobile=None,
    )
    appointment = make_appointment()

    decision = evaluate(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "contact_point_exists"


# ---------------------------------------------------------------------------
# Attempt stopping
# ---------------------------------------------------------------------------

def test_three_attempts_are_blocked():
    attempts = [
        {"at": NOW - timedelta(days=2)},
        {"at": NOW - timedelta(days=1)},
        {"at": NOW - timedelta(hours=20)},
    ]

    decision = evaluate(
        Config(),
        FakeLedger(
            appointment_attempts=attempts,
        ),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "attempt_cap"


def test_attempt_within_eighteen_hours_is_blocked():
    attempts = [
        {
            "at": NOW - timedelta(hours=10),
        }
    ]

    decision = evaluate(
        Config(),
        FakeLedger(
            appointment_attempts=attempts,
        ),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "attempt_cap"


# ---------------------------------------------------------------------------
# Point health
# ---------------------------------------------------------------------------

def test_dead_point_is_never_retried():
    decision = evaluate(
        Config(),
        FakeLedger(dead=True),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "point_known_bad"


def test_soft_failure_limit_blocks_point():
    cfg = make_cfg(
        max_soft_failures_per_point=2,
    )

    decision = evaluate(
        cfg,
        FakeLedger(soft_failures=2),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "point_known_bad"


# ---------------------------------------------------------------------------
# Human answer
# ---------------------------------------------------------------------------

def test_human_answer_stops_future_contact():
    decision = evaluate(
        Config(),
        FakeLedger(reached=True),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "already_reached"


# ---------------------------------------------------------------------------
# Shared point daily cap
# ---------------------------------------------------------------------------

def test_shared_point_daily_cap_blocks_second_message():
    cfg = make_cfg(
        max_messages_per_point_per_day=1,
    )

    decision = evaluate(
        cfg,
        FakeLedger(point_messages_today=1),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
    )

    assert decision.allowed is False
    assert decision.reason == "duplicate_message"


# ---------------------------------------------------------------------------
# Duplicate body
# ---------------------------------------------------------------------------

def test_identical_body_is_blocked_on_same_point():
    previous = {
        "appointment_id": "OTHER-APPOINTMENT",
        "body_hash": "same-hash",
        "reach": "delivered",
    }

    decision = evaluate(
        Config(),
        FakeLedger(
            point_attempts=[previous],
        ),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
        body_hash="same-hash",
    )

    assert decision.allowed is False
    assert decision.reason == "duplicate_message"


def test_failed_retry_of_same_appointment_is_allowed():
    previous = {
        "appointment_id": "AP-TEST",
        "body_hash": "same-hash",
        "reach": "failed",
    }

    decision = evaluate(
        Config(),
        FakeLedger(
            point_attempts=[previous],
        ),
        make_resident(),
        make_appointment(),
        Channel.SMS,
        NOW,
        body_hash="same-hash",
    )

    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def test_authorize_returns_authorization_for_allowed_send():
    resident = make_resident()
    appointment = make_appointment()

    auth = authorize(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
        attempt=1,
        body_hash="body-hash",
    )

    assert isinstance(auth, Authorization)
    assert auth.resident_id == resident.resident_id
    assert auth.appointment_id == appointment.appointment_id
    assert auth.channel is Channel.SMS
    assert auth.to == resident.mobile
    assert auth.at == NOW
    assert auth.attempt == 1


def test_authorize_rejects_blocked_send():
    resident = make_resident(
        sms_optout=True,
    )

    with pytest.raises(PermissionError):
        authorize(
            Config(),
            FakeLedger(),
            resident,
            make_appointment(),
            Channel.SMS,
            NOW,
            attempt=1,
        )


def test_authorization_cannot_be_forged():
    with pytest.raises(PermissionError):
        Authorization(
            resident_id="RS-TEST",
            appointment_id="AP-TEST",
            channel=Channel.SMS,
            to="555-401-2288",
            at=NOW,
            attempt=1,
            _mint=object(),
        )


def test_authorization_cannot_be_reused_for_another_number():
    resident = make_resident()
    appointment = make_appointment()

    auth = authorize(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
        attempt=1,
    )

    with pytest.raises(PermissionError):
        verify(
            auth,
            channel=Channel.SMS,
            to="555-999-9999",
            at=NOW,
        )


def test_authorization_cannot_be_reused_for_another_channel():
    resident = make_resident()
    appointment = make_appointment()

    auth = authorize(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
        attempt=1,
    )

    with pytest.raises(PermissionError):
        verify(
            auth,
            channel=Channel.VOICE,
            to=resident.mobile,
            at=NOW,
        )


def test_authorization_cannot_be_reused_at_another_time():
    resident = make_resident()
    appointment = make_appointment()

    auth = authorize(
        Config(),
        FakeLedger(),
        resident,
        appointment,
        Channel.SMS,
        NOW,
        attempt=1,
    )

    with pytest.raises(PermissionError):
        verify(
            auth,
            channel=Channel.SMS,
            to=resident.mobile,
            at=NOW + timedelta(hours=1),
        )