from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

from .models import Channel


@dataclass(frozen=True)
class Config:
    """
    Immutable configuration for the reminder system.

    All thresholds and runtime settings belong here so that policy,
    engine, and other modules do not hardcode their own values.
    """

    # Simulation window
    now: datetime = datetime(2026, 3, 1, 9, 0)
    until: datetime = datetime(2026, 3, 31, 9, 0)
    tick_hours: int = 4

    # Paths
    data_dir: Path = Path("data")
    runtime_dir: Path = Path("runtime")
    templates_dir: Path = Path("templates")
    contacts_path: Path = Path("data/contacts.csv")
    appointments_path: Path = Path("data/appointments.csv")
    history_path: Path = Path("runtime/contact_history.jsonl")

    # Appointment timing
    reminder_horizon_hours: int = 72
    min_lead_hours: int = 2

    # Quiet hours
    quiet_start: time = time(21, 0)
    quiet_end: time = time(8, 0)

    # Per-appointment stopping rules
    max_attempts_per_appointment: int = 3
    min_hours_between_attempts: int = 18

    # Contact-point health
    max_soft_failures_per_point: int = 2

    # Shared contact-point protection
    max_messages_per_point_per_day: int = 1

    # Resident-level protection
    max_contacts_per_resident_per_day: int = 1

    # Day-two rolling contact limit
    enforce_rolling_limit: bool = True
    rolling_window_days: int = 7
    max_contacts_per_window: int = 2

    # Suspected duplicate-person protection
    identity_guard: str = "enforce"

    # Channel fallback
    fallback_order: tuple[Channel, ...] = (
        Channel.SMS,
        Channel.VOICE,
        Channel.EMAIL,
    )

    # Language fallback
    default_language: str = "en"