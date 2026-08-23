from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .models import Appointment, Channel, Decision, Resident


_MINT = object()


@dataclass(frozen=True)
class Authorization:
    resident_id: str
    appointment_id: str
    channel: Channel
    to: str
    at: datetime
    attempt: int
    _mint: object

    def __post_init__(self) -> None:
        if self._mint is not _MINT:
            raise PermissionError(
                "Authorization was not issued by policy.authorize()"
            )


def verify(auth: Authorization, *, channel: Channel, to: str, at: datetime) -> None:
    if not isinstance(auth, Authorization) or auth._mint is not _MINT:
        raise PermissionError("forged authorization")
    if auth.channel is not channel:
        raise PermissionError("authorization does not match the send channel")
    if auth.to != to:
        raise PermissionError("authorization does not match the send recipient")
    if auth.at != at:
        raise PermissionError("authorization does not match the send time")


@dataclass(frozen=True)
class _Ctx:
    cfg: Config
    ledger: object
    resident: Resident
    appointment: Appointment
    channel: Channel
    now: datetime
    point: str | None
    body_hash: str | None


def _value(record: object, key: str, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _attempts_for_appointment(ctx: _Ctx) -> list:
    return list(ctx.ledger.attempts_for_appointment(ctx.appointment.appointment_id))


def _attempts_to_point(ctx: _Ctx) -> list:
    if ctx.point is None:
        return []
    return list(ctx.ledger.attempts_to_point(ctx.point))


def _rule_appointment_relevant(ctx: _Ctx) -> Decision | None:
    delta_hours = (ctx.appointment.scheduled_at - ctx.now).total_seconds() / 3600

    if delta_hours < 0:
        return Decision.block("appointment_relevant", "appointment has already passed")
    if delta_hours < ctx.cfg.min_lead_hours:
        return Decision.block(
            "appointment_relevant",
            f"appointment is less than {ctx.cfg.min_lead_hours} hours away",
        )
    if delta_hours > ctx.cfg.reminder_horizon_hours:
        return Decision.block(
            "appointment_relevant",
            f"appointment is more than {ctx.cfg.reminder_horizon_hours} hours away",
        )
    return None


def _rule_already_reached(ctx: _Ctx) -> Decision | None:
    if ctx.ledger.reached(ctx.appointment.appointment_id):
        return Decision.block("already_reached", "a human already answered about this appointment")
    return None


def _rule_opt_out(ctx: _Ctx) -> Decision | None:
    if ctx.resident.opted_out_of(ctx.channel):
        return Decision.block("opt_out", f"resident opted out of {ctx.channel.value}")
    return None


def _rule_contact_point_exists(ctx: _Ctx) -> Decision | None:
    if not ctx.point:
        return Decision.block("contact_point_exists", f"no usable contact point for {ctx.channel.value}")
    return None


def _rule_point_known_bad(ctx: _Ctx) -> Decision | None:
    assert ctx.point is not None

    if ctx.ledger.point_is_dead(ctx.point, ctx.channel):
        return Decision.block("point_known_bad", "contact point is marked dead")

    soft_failures = ctx.ledger.soft_failures(ctx.point, ctx.channel)

    if soft_failures >= ctx.cfg.max_soft_failures_per_point:
        return Decision.block(
            "point_known_bad",
            f"soft-failure limit reached: {soft_failures}/{ctx.cfg.max_soft_failures_per_point}",
        )
    return None


def _rule_quiet_hours(ctx: _Ctx) -> Decision | None:
    current_time = ctx.now.time()
    quiet_start = ctx.cfg.quiet_start
    quiet_end = ctx.cfg.quiet_end

    if quiet_start > quiet_end:
        in_quiet_hours = current_time >= quiet_start or current_time < quiet_end
    else:
        in_quiet_hours = quiet_start <= current_time < quiet_end

    if in_quiet_hours:
        return Decision.block(
            "quiet_hours",
            f"contacting is blocked between {quiet_start.strftime('%H:%M')} and {quiet_end.strftime('%H:%M')}",
        )
    return None


def _rule_attempt_cap(ctx: _Ctx) -> Decision | None:
    attempts = _attempts_for_appointment(ctx)

    if len(attempts) >= ctx.cfg.max_attempts_per_appointment:
        return Decision.block(
            "attempt_cap",
            f"{len(attempts)} attempts already made; maximum is {ctx.cfg.max_attempts_per_appointment}",
        )

    if attempts:
        last_at = max(_value(attempt, "at") for attempt in attempts)
        if isinstance(last_at, str):
            last_at = datetime.fromisoformat(last_at)

        elapsed_hours = (ctx.now - last_at).total_seconds() / 3600
        if elapsed_hours < ctx.cfg.min_hours_between_attempts:
            return Decision.block(
                "attempt_cap", f"only {elapsed_hours:.1f} hours since the previous attempt",
            )
    return None


def _rule_duplicate_message(ctx: _Ctx) -> Decision | None:
    if ctx.point is None:
        return None

    attempts = _attempts_to_point(ctx)

    messages_today = len(ctx.ledger.messages_to_point_on_day(ctx.point, ctx.now))

    if messages_today >= ctx.cfg.max_messages_per_point_per_day:
        return Decision.block(
            "duplicate_message",
            f"contact point already received {messages_today} message(s) today",
        )

    if ctx.body_hash is None:
        return None

    for previous in attempts:
        previous_hash = _value(previous, "body_hash")
        if previous_hash != ctx.body_hash:
            continue

        previous_appointment = _value(previous, "appointment_id")
        previous_reach = str(_value(previous, "reach", "")).lower()

        retry_allowed = (
            previous_appointment == ctx.appointment.appointment_id
            and previous_reach == "failed"
        )

        if not retry_allowed:
            return Decision.block(
                "duplicate_message", "identical message body already sent to this contact point",
            )
    return None


def _rule_resident_daily_cap(ctx: _Ctx) -> Decision | None:
    contacts_today = len(ctx.ledger.contacts_on_day(ctx.resident.resident_id, ctx.now))

    if contacts_today >= ctx.cfg.max_contacts_per_resident_per_day:
        return Decision.block(
            "resident_daily_cap", f"resident already received {contacts_today} contact(s) today",
        )
    return None


def _rule_rolling_limit(ctx: _Ctx) -> Decision | None:
    """Direction CR-2026/11 s.1 — Chapter 13."""
    if not ctx.cfg.enforce_rolling_limit:
        return None

    contacts = ctx.ledger.contacts_in_window(
        ctx.resident.resident_id, ctx.now, ctx.cfg.rolling_window_days,
    )

    if len(contacts) >= ctx.cfg.max_contacts_per_window:
        return Decision.block(
            "rolling_contact_limit",
            f"{len(contacts)} contact(s) in the preceding {ctx.cfg.rolling_window_days} days; "
            f"limit is {ctx.cfg.max_contacts_per_window}",
        )
    return None


# Identity guard (Chapter 13.4) still not implemented — next chapter.
RULES = (
    _rule_appointment_relevant,
    _rule_already_reached,
    _rule_opt_out,
    _rule_contact_point_exists,
    _rule_point_known_bad,
    _rule_quiet_hours,
    _rule_attempt_cap,
    _rule_duplicate_message,
    _rule_resident_daily_cap,
    _rule_rolling_limit,
)


def evaluate(
    cfg: Config,
    ledger,
    resident: Resident,
    appointment: Appointment,
    channel: Channel,
    now: datetime,
    body_hash: str | None = None,
) -> Decision:
    point = resident.point_for(channel)

    ctx = _Ctx(
        cfg=cfg, ledger=ledger, resident=resident, appointment=appointment,
        channel=channel, now=now, point=point, body_hash=body_hash,
    )

    for rule in RULES:
        verdict = rule(ctx)
        if verdict is not None:
            return verdict

    return Decision.allow()


def authorize(
    cfg: Config,
    ledger,
    resident: Resident,
    appointment: Appointment,
    channel: Channel,
    now: datetime,
    attempt: int,
    body_hash: str | None = None,
) -> Authorization:
    decision = evaluate(
        cfg=cfg, ledger=ledger, resident=resident, appointment=appointment,
        channel=channel, now=now, body_hash=body_hash,
    )

    if not decision.allowed:
        raise PermissionError(
            f"contact blocked: {decision.reason}"
            + (f" — {decision.detail}" if decision.detail else "")
        )

    point = resident.point_for(channel)
    if point is None:
        raise PermissionError("cannot authorize a send without a contact point")

    return Authorization(
        resident_id=resident.resident_id,
        appointment_id=appointment.appointment_id,
        channel=channel,
        to=point,
        at=now,
        attempt=attempt,
        _mint=_MINT,
    )