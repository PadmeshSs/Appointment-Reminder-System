from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .models import Appointment, Channel, Decision, Resident


# ---------------------------------------------------------------------------
# Authorization mint
# ---------------------------------------------------------------------------

_MINT = object()


@dataclass(frozen=True)
class Authorization:
    """
    Permission issued by policy.authorize() for one exact send.

    The private mint prevents callers from manufacturing a valid
    authorization themselves.
    """

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


def verify(
    auth: Authorization,
    *,
    channel: Channel,
    to: str,
    at: datetime,
) -> None:
    """
    Verify that an authorization exactly matches the send being attempted.

    This is deliberately called by dispatch immediately before touching
    a channel.
    """

    if not isinstance(auth, Authorization) or auth._mint is not _MINT:
        raise PermissionError("forged authorization")

    if auth.channel is not channel:
        raise PermissionError(
            "authorization does not match the send channel"
        )

    if auth.to != to:
        raise PermissionError(
            "authorization does not match the send recipient"
        )

    if auth.at != at:
        raise PermissionError(
            "authorization does not match the send time"
        )


# ---------------------------------------------------------------------------
# Policy context
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _value(record: object, key: str, default=None):
    """Read either a dictionary record or an object attribute."""

    if isinstance(record, dict):
        return record.get(key, default)

    return getattr(record, key, default)


def _attempts_for_appointment(ctx: _Ctx) -> list:
    return list(
        ctx.ledger.attempts_for_appointment(
            ctx.appointment.appointment_id
        )
    )


def _attempts_to_point(ctx: _Ctx) -> list:
    if ctx.point is None:
        return []

    return list(
        ctx.ledger.attempts_to_point(ctx.point)
    )


# ---------------------------------------------------------------------------
# Rule 1 — appointment relevance
# ---------------------------------------------------------------------------

def _rule_appointment_relevant(ctx: _Ctx) -> Decision | None:
    """
    Block appointments that have already happened, are too close,
    or are outside the reminder horizon.
    """

    delta_hours = (
        ctx.appointment.scheduled_at - ctx.now
    ).total_seconds() / 3600

    if delta_hours < 0:
        return Decision.block(
            "appointment_relevant",
            "appointment has already passed",
        )

    if delta_hours < ctx.cfg.min_lead_hours:
        return Decision.block(
            "appointment_relevant",
            f"appointment is less than "
            f"{ctx.cfg.min_lead_hours} hours away",
        )

    if delta_hours > ctx.cfg.reminder_horizon_hours:
        return Decision.block(
            "appointment_relevant",
            f"appointment is more than "
            f"{ctx.cfg.reminder_horizon_hours} hours away",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 2 — already reached
# ---------------------------------------------------------------------------

def _rule_already_reached(ctx: _Ctx) -> Decision | None:
    if ctx.ledger.reached(ctx.appointment.appointment_id):
        return Decision.block(
            "already_reached",
            "a human already answered about this appointment",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 3 — opt-out
# ---------------------------------------------------------------------------

def _rule_opt_out(ctx: _Ctx) -> Decision | None:
    if ctx.resident.opted_out_of(ctx.channel):
        return Decision.block(
            "opt_out",
            f"resident opted out of {ctx.channel.value}",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 4 — contact point exists
# ---------------------------------------------------------------------------

def _rule_contact_point_exists(ctx: _Ctx) -> Decision | None:
    if not ctx.point:
        return Decision.block(
            "contact_point_exists",
            f"no usable contact point for {ctx.channel.value}",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 5 — known bad contact point
# ---------------------------------------------------------------------------

def _rule_point_known_bad(ctx: _Ctx) -> Decision | None:
    assert ctx.point is not None

    if ctx.ledger.point_is_dead(
        ctx.point,
        ctx.channel,
    ):
        return Decision.block(
            "point_known_bad",
            "contact point is marked dead",
        )

    soft_failures = ctx.ledger.soft_failures(
        ctx.point,
        ctx.channel,
    )

    if soft_failures >= ctx.cfg.max_soft_failures_per_point:
        return Decision.block(
            "point_known_bad",
            f"soft-failure limit reached: "
            f"{soft_failures}/"
            f"{ctx.cfg.max_soft_failures_per_point}",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 6 — quiet hours
# ---------------------------------------------------------------------------

def _rule_quiet_hours(ctx: _Ctx) -> Decision | None:
    current_time = ctx.now.time()

    quiet_start = ctx.cfg.quiet_start
    quiet_end = ctx.cfg.quiet_end

    if quiet_start > quiet_end:
        in_quiet_hours = (
            current_time >= quiet_start
            or current_time < quiet_end
        )
    else:
        in_quiet_hours = (
            quiet_start <= current_time < quiet_end
        )

    if in_quiet_hours:
        return Decision.block(
            "quiet_hours",
            f"contacting is blocked between "
            f"{quiet_start.strftime('%H:%M')} and "
            f"{quiet_end.strftime('%H:%M')}",
        )

    return None


# ---------------------------------------------------------------------------
# Rule 7 — attempt cap
# ---------------------------------------------------------------------------

def _rule_attempt_cap(ctx: _Ctx) -> Decision | None:
    attempts = _attempts_for_appointment(ctx)

    if len(attempts) >= ctx.cfg.max_attempts_per_appointment:
        return Decision.block(
            "attempt_cap",
            f"{len(attempts)} attempts already made; "
            f"maximum is {ctx.cfg.max_attempts_per_appointment}",
        )

    if attempts:
        last_at = max(
            _value(attempt, "at")
            for attempt in attempts
        )

        if isinstance(last_at, str):
            last_at = datetime.fromisoformat(last_at)

        elapsed_hours = (
            ctx.now - last_at
        ).total_seconds() / 3600

        if elapsed_hours < ctx.cfg.min_hours_between_attempts:
            return Decision.block(
                "attempt_cap",
                f"only {elapsed_hours:.1f} hours since "
                f"the previous attempt",
            )

    return None


# ---------------------------------------------------------------------------
# Rule 8 — duplicate message / shared point cap
# ---------------------------------------------------------------------------

def _rule_duplicate_message(ctx: _Ctx) -> Decision | None:
    """
    Protect the person holding a shared contact point.

    There are two independent protections:

    1. The same body cannot be sent twice down the same line.
       A failed retry for the same appointment is allowed.
    2. A contact point receives at most one message per day,
       even when it belongs to different residents.
    """

    if ctx.point is None:
        return None

    attempts = _attempts_to_point(ctx)

    # One message per contact point per day.
    messages_today = len(ctx.ledger.messages_to_point_on_day(
        ctx.point,
        ctx.now,
    ))

    if messages_today >= ctx.cfg.max_messages_per_point_per_day:
        return Decision.block(
            "duplicate_message",
            f"contact point already received "
            f"{messages_today} message(s) today",
        )

    # Same body twice to the same point is blocked unless this is
    # a retry of the same appointment after a failed delivery.
    if ctx.body_hash is None:
        return None

    for previous in attempts:
        previous_hash = _value(
            previous,
            "body_hash",
        )

        if previous_hash != ctx.body_hash:
            continue

        previous_appointment = _value(
            previous,
            "appointment_id",
        )

        previous_reach = str(
            _value(previous, "reach", "")
        ).lower()

        retry_allowed = (
            previous_appointment
            == ctx.appointment.appointment_id
            and previous_reach == "failed"
        )

        if not retry_allowed:
            return Decision.block(
                "duplicate_message",
                "identical message body already sent "
                "to this contact point",
            )

    return None


# ---------------------------------------------------------------------------
# Rule 9 — resident daily cap
# ---------------------------------------------------------------------------

def _rule_resident_daily_cap(ctx: _Ctx) -> Decision | None:
    contacts_today = len(ctx.ledger.contacts_on_day(
        ctx.resident.resident_id,
        ctx.now,
    ))

    if contacts_today >= ctx.cfg.max_contacts_per_resident_per_day:
        return Decision.block(
            "resident_daily_cap",
            f"resident already received "
            f"{contacts_today} contact(s) today",
        )

    return None


# ---------------------------------------------------------------------------
# Day-two rules are intentionally not implemented here yet.
#
# Chapter 13 adds:
#
#   _rule_rolling_limit
#   _rule_identity_guard
#
# The important architectural point is that they will be added to this
# same RULES tuple rather than scattered into engine/dispatch/call sites.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Single source of truth
# ---------------------------------------------------------------------------

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
    """
    Evaluate every contact rule in order.

    The first objection wins.

    Returning the first decision is deliberate: the ordering puts cheap,
    absolute reasons before increasingly expensive historical checks.
    """

    point = resident.point_for(channel)

    ctx = _Ctx(
        cfg=cfg,
        ledger=ledger,
        resident=resident,
        appointment=appointment,
        channel=channel,
        now=now,
        point=point,
        body_hash=body_hash,
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
    """
    Evaluate policy and issue an authorization only when every rule passes.
    """

    decision = evaluate(
        cfg=cfg,
        ledger=ledger,
        resident=resident,
        appointment=appointment,
        channel=channel,
        now=now,
        body_hash=body_hash,
    )

    if not decision.allowed:
        raise PermissionError(
            f"contact blocked: {decision.reason}"
            + (
                f" — {decision.detail}"
                if decision.detail
                else ""
            )
        )

    point = resident.point_for(channel)

    if point is None:
        # This should already have been caught by policy, but keeping
        # the invariant here makes the Authorization contract explicit.
        raise PermissionError(
            "cannot authorize a send without a contact point"
        )

    return Authorization(
        resident_id=resident.resident_id,
        appointment_id=appointment.appointment_id,
        channel=channel,
        to=point,
        at=now,
        attempt=attempt,
        _mint=_MINT,
    )