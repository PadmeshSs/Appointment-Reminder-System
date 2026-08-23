from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .dispatch import send
from .message import MessageBuilder
from .models import Appointment, Channel, Resident
from .policy import authorize, evaluate


@dataclass(frozen=True)
class TickResult:
    """
    Summary of one engine tick.

    The engine only reports what happened. It does not decide
    whether contact was permitted.
    """

    at: datetime
    attempted: int
    withheld: int


class Engine:
    """
    Orchestration layer for the reminder system.

    The engine is responsible for:

    - selecting appointments that are currently relevant
    - prioritising appointments
    - determining channel order
    - asking policy for permission
    - dispatching an authorised message
    - recording attempts
    - recording fully-withheld appointments
    - running deterministic simulations

    The engine is NOT responsible for permission rules.

    Policy remains the single authority for:
    - opt-outs
    - quiet hours
    - contact limits
    - duplicate protection
    - appointment relevance
    - point health
    - any future regulatory rules
    """

    # When all channels are blocked, this determines which blocking
    # reason is recorded as the primary reason in the withheld register.
    #
    # The rolling contact limit is intentionally first because
    # Direction CR-2026/11 specifically requires the appointment
    # concerned to be recorded when that limit prevents contact.
    WITHHELD_REASON_PRIORITY = (
        "rolling_contact_limit",
        "identity_guard",
        "already_reached",
        "opt_out",
        "contact_point_exists",
        "point_known_bad",
        "quiet_hours",
        "attempt_cap",
        "duplicate_message",
        "resident_daily_cap",
        "appointment_relevant",
    )

    def __init__(
        self,
        cfg: Config,
        residents: list[Resident],
        appointments: list[Appointment],
        ledger: Any,
        messages: MessageBuilder,
    ) -> None:
        self.cfg = cfg

        self.residents = {
            resident.resident_id: resident
            for resident in residents
        }

        self.appointments = list(appointments)
        self.ledger = ledger
        self.messages = messages

    # ------------------------------------------------------------------
    # Appointment prioritisation
    # ------------------------------------------------------------------

    def _attempt_count(
        self,
        appointment: Appointment,
    ) -> int:
        """
        Return the number of previous attempts for an appointment.

        Failed attempts count because the ledger records every outbound
        attempt, regardless of delivery outcome.
        """

        return len(
            self.ledger.attempts_for_appointment(
                appointment.appointment_id
            )
        )

    def _priority_key(
        self,
        appointment: Appointment,
    ) -> tuple[int, datetime, str]:
        """
        Return the deterministic Chapter 9 priority key.

        Level 1:
            appointments with zero previous attempts first.

        Level 2:
            earlier appointments first.

        Final tie-break:
            appointment ID.

        No resident characteristic is used.
        """

        return (
            self._attempt_count(appointment),
            appointment.scheduled_at,
            appointment.appointment_id,
        )

    def due(
        self,
        now: datetime,
    ) -> list[Appointment]:
        """
        Return appointments currently eligible for consideration.

        This is NOT a permission check.

        The engine only establishes the broad reminder window.
        Policy is still called for every channel before a send.

        This distinction matters because a future policy rule must
        not be bypassable by changing the engine's selection logic.
        """

        candidates = [
            appointment
            for appointment in self.appointments
            if appointment.status == "Booked"
            and appointment.scheduled_at > now
            and appointment.scheduled_at
            <= now + timedelta(
                hours=self.cfg.reminder_horizon_hours
            )
        ]

        return sorted(
            candidates,
            key=self._priority_key,
        )

    # ------------------------------------------------------------------
    # Channel ordering
    # ------------------------------------------------------------------

    @staticmethod
    def _has_point(
        resident: Resident,
        channel: Channel,
    ) -> bool:
        """Return whether the resident has a usable point."""

        return resident.point_for(channel) is not None

    def _channel_order(
        self,
        resident: Resident,
    ) -> list[Channel]:
        """
        Determine the order in which channels are considered.

        Default:
            SMS -> VOICE -> EMAIL

        Suspected landline:
            VOICE -> SMS -> EMAIL

        Channels without a contact point are removed.

        This is channel ordering, not permission. Policy is still
        asked before every actual send.
        """

        order = list(self.cfg.fallback_order)

        if getattr(
            resident,
            "suspected_landline_mobile",
            False,
        ):
            order.sort(
                key=lambda channel: (
                    0
                    if channel is Channel.VOICE
                    else 1
                    if channel is Channel.SMS
                    else 2
                )
            )

        return [
            channel
            for channel in order
            if self._has_point(
                resident,
                channel,
            )
        ]

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def _message_for(
        self,
        resident: Resident,
        appointment: Appointment,
        channel: Channel,
    ):
        """
        Build the message for one channel.

        MessageBuilder owns language selection and fallback.
        The engine does not make language decisions.
        """

        if channel is Channel.SMS:
            return self.messages.sms(
                resident,
                appointment,
            )

        if channel is Channel.VOICE:
            return self.messages.voice(
                resident,
                appointment,
            )

        if channel is Channel.EMAIL:
            _, body = self.messages.email(
                resident,
                appointment,
            )
            return body

        raise ValueError(
            f"Unsupported channel: {channel}"
        )

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_value(
        record: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read a field from either a dict-like ledger record or an object.

        This keeps the engine tolerant of the ledger's internal record
        representation without moving ledger logic into the engine.
        """

        if isinstance(record, dict):
            return record.get(
                key,
                default,
            )

        return getattr(
            record,
            key,
            default,
        )

    def _record_attempt(
        self,
        *,
        now: datetime,
        resident: Resident,
        appointment: Appointment,
        channel: Channel,
        attempt: int,
        message: Any,
        outcome: Any,
    ) -> None:
        """
        Append the outbound attempt to the ledger.

        This happens after dispatch returns its graded outcome.

        The ledger therefore contains the evidence needed by later
        policy decisions, including failed attempts.
        """

        self.ledger.record_attempt(
            at=now,
            resident_id=resident.resident_id,
            identity_key=getattr(
                resident,
                "identity_key",
                None,
            ),
            appointment_id=appointment.appointment_id,
            channel=channel.value,
            to=resident.point_for(channel),
            attempt=attempt,
            language=message.language,
            language_fallback=message.fallback,
            body_hash=message.body_hash,
            status=outcome.status,
            detail=outcome.detail,
            reach=outcome.reach.value,
            point_health=outcome.point_health.value,
        )

    # ------------------------------------------------------------------
    # Withheld register
    # ------------------------------------------------------------------

    def _reason_priority(
        self,
        reason: str | None,
    ) -> int:
        """
        Return the priority of a policy blocking reason.

        Unknown reasons are deliberately lowest priority. The engine
        records them rather than inventing a new interpretation.
        """

        try:
            return self.WITHHELD_REASON_PRIORITY.index(
                reason
            )
        except ValueError:
            return len(
                self.WITHHELD_REASON_PRIORITY
            )

    def _counted_contacts(
        self,
        resident: Resident,
        now: datetime,
    ) -> int:
        method = getattr(self.ledger, "contacts_in_window", None)

        if method is None:
            return 0

        return len(
            method(
                resident.resident_id,
                now,
                self.cfg.rolling_window_days,
            )
        )

    def _record_withheld(
        self,
        *,
        now: datetime,
        resident: Resident,
        appointment: Appointment,
        decisions: list[tuple[Channel, Any]],
    ) -> None:
        """
        Record exactly one withheld row for an appointment.

        The row records:

        - resident
        - appointment
        - primary blocking channel
        - primary reason
        - counted contacts
        - all channel-level blocking reasons

        This satisfies Direction CR-2026/11 s.4.1 and makes the
        decision explainable.
        """

        blocked = [
            (channel, decision)
            for channel, decision in decisions
            if not decision.allowed
        ]

        if not blocked:
            return

        primary_channel, primary_decision = min(
            blocked,
            key=lambda item: (
                self._reason_priority(
                    item[1].reason
                ),
                item[0].value,
            ),
        )

        counted_contacts = self._counted_contacts(
            resident,
            now,
        )

        detail = {
            "primary_reason": primary_decision.reason,
            "primary_detail": primary_decision.detail,
            "counted_contacts": counted_contacts,
            "channels_considered": [
                {
                    "channel": channel.value,
                    "reason": decision.reason,
                    "detail": decision.detail,
                }
                for channel, decision in blocked
            ],
        }

        self.ledger.record_withheld(
            at=now,
            resident_id=resident.resident_id,
            identity_key=getattr(
                resident,
                "identity_key",
                None,
            ),
            appointment_id=appointment.appointment_id,
            channel=primary_channel.value,
            reason=primary_decision.reason,
            detail=detail,
        )

    # ------------------------------------------------------------------
    # One appointment
    # ------------------------------------------------------------------

    def _process_appointment(
        self,
        appointment: Appointment,
        now: datetime,
    ) -> tuple[bool, bool]:
        """
        Process one appointment during one tick.

        Returns:
            (attempted, withheld)

        Critical Chapter 9 rule:

            At most ONE outbound contact can happen here.

        If SMS fails, the engine does NOT immediately call voice.
        Fallback can only happen during a later tick.

        This is the core anti-harassment orchestration rule.
        """

        resident = self.residents.get(
            appointment.resident_id
        )

        if resident is None:
            # An orphan appointment should not produce a send.
            # Loading/audit is responsible for reporting the data issue.
            return False, False

        # A human already answering ends the reminder process for
        # this appointment.
        if self.ledger.reached(
            appointment.appointment_id
        ):
            return False, False

        decisions: list[tuple[Channel, Any]] = []

        channels = self._channel_order(
            resident
        )

        # If there are no usable contact points, there is no channel
        # for policy to evaluate. Record one withheld appointment.
        if not channels:
            from .models import Decision

            self._record_withheld(
                now=now,
                resident=resident,
                appointment=appointment,
                decisions=[
                    (
                        Channel.SMS,
                        Decision.block(
                            "contact_point_exists",
                            "resident has no usable contact point",
                        ),
                    )
                ],
            )

            return False, True

        for channel in channels:
            # ----------------------------------------------------------
            # Build the message.
            #
            # Language fallback is owned by MessageBuilder.
            # ----------------------------------------------------------

            message = self._message_for(
                resident,
                appointment,
                channel,
            )

            # ----------------------------------------------------------
            # Ask policy.
            #
            # The engine does not inspect opt-outs, quiet hours,
            # rolling limits, identity guards, etc.
            # ----------------------------------------------------------

            decision = evaluate(
                cfg=self.cfg,
                ledger=self.ledger,
                resident=resident,
                appointment=appointment,
                channel=channel,
                now=now,
                body_hash=message.body_hash,
            )

            if not decision.allowed:
                decisions.append(
                    (
                        channel,
                        decision,
                    )
                )
                continue

            # The attempt number is derived from the appointment's
            # existing history. Failed attempts are still contacts.
            attempt_number = (
                len(
                    self.ledger.attempts_for_appointment(
                        appointment.appointment_id
                    )
                )
                + 1
            )

            # ----------------------------------------------------------
            # Policy must issue the actual Authorization immediately
            # before dispatch.
            # ----------------------------------------------------------

            authorization = authorize(
                cfg=self.cfg,
                ledger=self.ledger,
                resident=resident,
                appointment=appointment,
                channel=channel,
                now=now,
                attempt=attempt_number,
                body_hash=message.body_hash,
            )

            # ----------------------------------------------------------
            # Exactly ONE outbound send for this appointment/tick.
            # ----------------------------------------------------------

            outcome = send(
                self.cfg,
                authorization,
                message.body,
            )

            self._record_attempt(
                now=now,
                resident=resident,
                appointment=appointment,
                channel=channel,
                attempt=attempt_number,
                message=message,
                outcome=outcome,
            )

            # Stop immediately after the first outbound attempt.
            #
            # Even if the carrier reports failure, fallback is deferred
            # to a later tick.
            return True, False

        # Every usable channel was considered and policy blocked all of
        # them. Record exactly one withheld row.
        self._record_withheld(
            now=now,
            resident=resident,
            appointment=appointment,
            decisions=decisions,
        )

        return False, True

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(
        self,
        now: datetime,
    ) -> TickResult:
        """
        Execute one deterministic batch at one moment.

        Appointments are processed according to the Chapter 9 priority:

            1. fewer previous attempts
            2. sooner appointment
            3. appointment ID

        Each appointment gets at most one contact attempt.
        """

        attempted = 0
        withheld = 0

        for appointment in self.due(now):
            did_attempt, did_withhold = (
                self._process_appointment(
                    appointment,
                    now,
                )
            )

            if did_attempt:
                attempted += 1

            if did_withhold:
                withheld += 1

        return TickResult(
            at=now,
            attempted=attempted,
            withheld=withheld,
        )

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def simulate(
        self,
        start: datetime,
        until: datetime,
        tick_hours: int | None = None,
    ) -> list[TickResult]:
        """
        Run deterministic ticks from start through until.

        No system clock is used.

        The same:
            start
            until
            tick_hours
            input data
            ledger state

        produces the same sequence of ticks.
        """

        if tick_hours is None:
            tick_hours = self.cfg.tick_hours

        if tick_hours <= 0:
            raise ValueError(
                "tick_hours must be greater than zero"
            )

        if until < start:
            raise ValueError(
                "until must not be earlier than start"
            )

        results: list[TickResult] = []

        current = start
        step = timedelta(
            hours=tick_hours
        )

        while current <= until:
            results.append(
                self.tick(current)
            )
            current += step

        return results