from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .models import Appointment, Resident

# ----------------------------------------------------------------------
# Shared with engine.py's WITHHELD_REASON_PRIORITY.
#
# This MUST stay a single source of truth. If a new policy rule is
# added (e.g. the Chapter 13 identity guard already anticipated here),
# it has to be added in exactly one place, or the engine's own
# withheld-reason recording and this module's coverage-gap attribution
# will silently disagree — precisely the trap Chapter 4 warns about.
# ----------------------------------------------------------------------
WITHHELD_REASON_PRIORITY: tuple[str, ...] = (
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


@dataclass(frozen=True)
class ReachMetrics:
    """Primary success metric."""

    appointments_in_scope: int
    confirmed_reached: int
    confirmed_reach_rate: float


@dataclass(frozen=True)
class CoverageMetrics:
    """Appointments that received no outbound contact at all."""

    appointments_without_contact: int
    by_reason: dict[str, int]


@dataclass(frozen=True)
class HarmMetrics:
    """Maximum contact volume within any rolling seven-day window."""

    max_contacts_per_resident: int
    max_contacts_per_identity: int


@dataclass(frozen=True)
class ComplianceResult:
    """Proof of rolling-limit compliance."""

    breaches: int
    checked_attempts: int
    breach_details: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MetricsReport:
    """
    Complete Chapter 10 report.

    The first three fields are deliberately the three headline
    success measures:

        1. confirmed reach
        2. coverage gap
        3. harm ceiling
    """

    reach: ReachMetrics
    coverage: CoverageMetrics
    harm: HarmMetrics

    silent_failure_exposure: dict[str, int]
    language_fallbacks: dict[str, int]
    attempts_by_channel: dict[str, int]
    withheld_by_reason: dict[str, int]

    any_delivery_rate: float
    compliance: ComplianceResult


# ------------------------------------------------------------------
# Ledger access
#
# These are the ONLY functions in this module that know anything
# about how records are shaped. Everything else works through them.
#
# `history.Ledger` exposes:
#   - a `.records` property: every record, attempts and withheld
#     mixed, each tagged record["kind"] in {"attempt", "withheld"}
#   - purpose-built query methods: attempts_for_appointment(),
#     attempts_for_resident(), reached(), contacts_in_window(), etc.
#
# It does NOT expose `.attempts` or `.withheld` attributes. A ledger
# stand-in used only for testing may offer either shape; the
# functions below accept both so the module works against the real
# Ledger and against any conforming test double.
# ------------------------------------------------------------------


def _value(record: Any, key: str, default: Any = None) -> Any:
    """Read a field from a dict or object record."""

    if isinstance(record, dict):
        return record.get(key, default)

    return getattr(record, key, default)


def _as_datetime(value: Any) -> datetime | None:
    """Coerce a ledger timestamp (str or datetime) to datetime."""

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        return datetime.fromisoformat(value)

    return None


def _all_records(ledger: Any, kind: str) -> list[Any]:
    """
    Return every ledger record of one kind ("attempt" or "withheld").

    Prefers the real Ledger's `.records` property (filtering by
    `kind`). Falls back to a bare `.attempts` / `.withheld` attribute
    only if `.records` is not present, so a minimal test double still
    works without silently returning nothing.
    """

    records = getattr(ledger, "records", None)

    if records is not None:
        if callable(records):
            records = records()

        return [
            record
            for record in records
            if _value(record, "kind") == kind
        ]

    # Fallback for ledger doubles that expose the raw lists directly.
    attribute = "attempts" if kind == "attempt" else "withheld"
    value = getattr(ledger, attribute, None)

    if value is None:
        raise AttributeError(
            f"ledger exposes neither '.records' nor '.{attribute}'; "
            "metrics cannot read its history"
        )

    if callable(value):
        value = value()

    return list(value)


def _attempts(ledger: Any) -> list[Any]:
    """Return every recorded outbound attempt."""

    return _all_records(ledger, "attempt")


def _withheld(ledger: Any) -> list[Any]:
    """Return every withheld record."""

    return _all_records(ledger, "withheld")


def _appointment_attempts(ledger: Any, appointment_id: str) -> list[Any]:
    """Return attempts for one appointment."""

    method = getattr(ledger, "attempts_for_appointment", None)

    if method is not None:
        return list(method(appointment_id))

    return [
        record
        for record in _attempts(ledger)
        if _value(record, "appointment_id") == appointment_id
    ]


def _reached(ledger: Any, appointment_id: str) -> bool:
    """
    Use the ledger's authoritative reached query when available.

    Reach is deliberately never inferred from 'delivered'.
    """

    method = getattr(ledger, "reached", None)

    if method is not None:
        return bool(method(appointment_id))

    return any(
        str(_value(record, "reach", "")).lower() == "reached"
        for record in _appointment_attempts(ledger, appointment_id)
    )


# ------------------------------------------------------------------
# Scope
# ------------------------------------------------------------------


def _scope_appointments(
    appointments: list[Appointment],
    now: datetime,
    until: datetime,
) -> list[Appointment]:
    """
    Return appointments in the reporting scope.

    Scope is bounded by CALENDAR DATE, not exact timestamp. The
    report covers "appointments scheduled during this reporting
    period" — it is not an artifact of the exact instant the last
    simulated tick happened to land on. Bounding by exact timestamp
    would silently drop appointments scheduled later on the same day
    as `until` (e.g. an appointment at 14:00 when `until` is 09:00 on
    the same date), even though the reminder engine — which looks
    ahead up to `reminder_horizon_hours` — would ordinarily have
    already attempted contact for it well before that boundary.
    """

    return [
        appointment
        for appointment in appointments
        if now.date() <= appointment.scheduled_at.date() <= until.date()
    ]


# ------------------------------------------------------------------
# 1. Confirmed reach (primary headline)
# ------------------------------------------------------------------


def confirmed_reach(
    appointments: list[Appointment],
    ledger: Any,
    now: datetime,
    until: datetime,
) -> ReachMetrics:
    """
    Calculate the primary success metric.

    Confirmed reach means an appointment has at least one REACHED
    event. DELIVERED is deliberately not treated as success.
    """

    scoped = _scope_appointments(appointments, now, until)

    reached_count = sum(
        _reached(ledger, appointment.appointment_id)
        for appointment in scoped
    )

    total = len(scoped)

    rate = reached_count / total if total else 0.0

    return ReachMetrics(
        appointments_in_scope=total,
        confirmed_reached=reached_count,
        confirmed_reach_rate=rate,
    )


# ------------------------------------------------------------------
# 2. Coverage gap
# ------------------------------------------------------------------


def coverage_gap(
    appointments: list[Appointment],
    ledger: Any,
    now: datetime,
    until: datetime,
) -> CoverageMetrics:
    """
    Find appointments with no contact attempt at all.

    Each appointment gets exactly one cause: the highest-priority
    withheld reason recorded for it, using the same priority order
    the engine itself uses to pick a primary reason
    (WITHHELD_REASON_PRIORITY, above).
    """

    scoped = _scope_appointments(appointments, now, until)

    priority_index = {
        reason: index
        for index, reason in enumerate(WITHHELD_REASON_PRIORITY)
    }

    withheld_by_appointment: defaultdict[str, list[Any]] = defaultdict(list)

    for row in _withheld(ledger):
        appointment_id = _value(row, "appointment_id")

        if appointment_id:
            withheld_by_appointment[appointment_id].append(row)

    gap_reasons: Counter[str] = Counter()
    without_contact = 0

    for appointment in scoped:
        attempts = _appointment_attempts(ledger, appointment.appointment_id)

        if attempts:
            continue

        without_contact += 1

        rows = withheld_by_appointment.get(appointment.appointment_id, [])

        if rows:
            reasons = [_value(row, "reason", "unknown") for row in rows]
            reason = min(
                reasons,
                key=lambda value: priority_index.get(value, len(priority_index)),
            )
        else:
            reason = "no_contact_recorded"

        gap_reasons[reason] += 1

    return CoverageMetrics(
        appointments_without_contact=without_contact,
        by_reason=dict(sorted(gap_reasons.items())),
    )


# ------------------------------------------------------------------
# 3. Harm ceiling
# ------------------------------------------------------------------


def _max_rolling_count(
    timestamps: list[datetime],
    window_days: int,
    now: datetime,
    until: datetime,
) -> int:
    """
    Given one entity's own attempt timestamps — its FULL history, not
    pre-restricted to the reporting window — return the largest
    number of attempts in any rolling window that ENDS at a moment
    within [now, until].

    Window: start < ts <= at (half-open, same as history.Ledger).

    Two things matter here:

    - Only an entity's own timestamps are ever candidate window ends:
      the rolling count can only change at a moment it received a
      contact, so a sorted two-pointer sweep over just those is
      enough — no need to rescan every attempt in the system for
      every entity.

    - The window's CONTENTS may reach back before `now`. A contact
      made two days before the reporting period started still counts
      toward a window that ends five days into it — the resident's
      actual rolling burden does not reset just because a report
      happens to start counting at `now`. Only which moments are
      evaluated as window ends is restricted to [now, until]; what
      counts inside a given window is not.
    """

    if not timestamps:
        return 0

    ordered = sorted(timestamps)
    window = timedelta(days=window_days)

    best = 0
    left = 0

    for right, at in enumerate(ordered):
        start = at - window

        while ordered[left] <= start:
            left += 1

        if now <= at <= until:
            best = max(best, right - left + 1)

    return best


def harm_ceiling(
    residents: list[Resident],
    ledger: Any,
    now: datetime,
    until: datetime,
    window_days: int = 7,
) -> HarmMetrics:
    """
    Calculate the largest number of contacts received by:

        - one resident
        - one suspected person (identity cluster)

    at any moment within the reporting period, counting every
    outbound attempt (including failures), and allowing a window to
    reach back to attempts made before the reporting period started.
    """

    resident_ids = {resident.resident_id for resident in residents}
    identity_keys = {
        resident.identity_key
        for resident in residents
        if getattr(resident, "identity_key", None)
    }

    by_resident: defaultdict[str, list[datetime]] = defaultdict(list)
    by_identity: defaultdict[str, list[datetime]] = defaultdict(list)

    for attempt in _attempts(ledger):
        at = _as_datetime(_value(attempt, "at"))

        if at is None:
            continue

        resident_id = _value(attempt, "resident_id")
        if resident_id in resident_ids:
            by_resident[resident_id].append(at)

        identity_key = _value(attempt, "identity_key")
        if identity_key in identity_keys:
            by_identity[identity_key].append(at)

    max_resident = max(
        (
            _max_rolling_count(timestamps, window_days, now, until)
            for timestamps in by_resident.values()
        ),
        default=0,
    )

    max_identity = max(
        (
            _max_rolling_count(timestamps, window_days, now, until)
            for timestamps in by_identity.values()
        ),
        default=0,
    )

    return HarmMetrics(
        max_contacts_per_resident=max_resident,
        max_contacts_per_identity=max_identity,
    )


# ------------------------------------------------------------------
# Secondary metrics
# ------------------------------------------------------------------


def silent_failure_exposure(ledger: Any) -> dict[str, int]:
    """
    Count outcomes that technically report success but have evidence
    the message may not have reached a usable recipient.
    """

    counts: Counter[str] = Counter()

    for attempt in _attempts(ledger):
        if str(_value(attempt, "reach", "")).lower() != "unverifiable":
            continue

        channel = str(_value(attempt, "channel", "unknown"))
        detail = str(_value(attempt, "detail", "unknown"))

        counts[f"{channel}:{detail}"] += 1

    return dict(sorted(counts.items()))


def language_fallbacks(ledger: Any) -> dict[str, int]:
    """
    Count language fallbacks by the language actually used.

    Note: the ledger's attempt schema records `language` (the
    template that was actually used after any fallback) but not the
    resident's originally requested language — that value exists on
    the Message object at send time but is never persisted. This
    reports fallbacks keyed on the used language; recovering a true
    "requested vs. actual" breakdown would require adding a
    `requested_language` field to the ledger schema in history.py.
    """

    counts: Counter[str] = Counter()

    for attempt in _attempts(ledger):
        if not _value(attempt, "language_fallback", False):
            continue

        language = str(_value(attempt, "language", "unknown"))
        counts[language] += 1

    return dict(sorted(counts.items()))


def attempts_by_channel(ledger: Any) -> dict[str, int]:
    """Count outbound attempts by channel."""

    counts: Counter[str] = Counter()

    for attempt in _attempts(ledger):
        counts[str(_value(attempt, "channel", "unknown"))] += 1

    return dict(sorted(counts.items()))


def withheld_by_reason(ledger: Any) -> dict[str, int]:
    """Count withheld appointments by primary reason."""

    counts: Counter[str] = Counter()

    for row in _withheld(ledger):
        counts[str(_value(row, "reason", "unknown"))] += 1

    return dict(sorted(counts.items()))


def any_delivery_rate(
    appointments: list[Appointment],
    ledger: Any,
    now: datetime,
    until: datetime,
) -> float:
    """
    Secondary metric. Counts an appointment if it has any attempt
    whose reach was DELIVERED or REACHED. This is NOT the primary
    success definition.
    """

    scoped = _scope_appointments(appointments, now, until)

    if not scoped:
        return 0.0

    delivered = 0

    for appointment in scoped:
        attempts = _appointment_attempts(ledger, appointment.appointment_id)

        if any(
            str(_value(attempt, "reach", "")).lower() in {"delivered", "reached"}
            for attempt in attempts
        ):
            delivered += 1

    return delivered / len(scoped)


# ------------------------------------------------------------------
# Compliance proof
# ------------------------------------------------------------------


def compliance(
    residents: list[Resident],
    ledger: Any,
    cfg: Config,
) -> ComplianceResult:
    """
    Independently prove the rolling seven-day contact limit.

    This intentionally does NOT call policy._rule_rolling_limit().
    For every attempt belonging to a known resident, the preceding-
    seven-day count is recomputed from scratch at that moment. That
    makes this an independent compliance proof rather than an
    assertion that policy behaved correctly.

    Grouped by resident first (rather than scanning the full attempt
    list per attempt), and two attempts sharing an identical
    timestamp for the same resident — which happens whenever more
    than one of a resident's appointments is processed in the same
    simulated tick — are both counted, matching the half-open window
    `start < ts <= at` used everywhere else in this system.
    """

    resident_ids = {resident.resident_id for resident in residents}

    by_resident: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for attempt in _attempts(ledger):
        resident_id = _value(attempt, "resident_id")

        if resident_id not in resident_ids:
            continue

        at = _as_datetime(_value(attempt, "at"))

        if at is None:
            continue

        by_resident[resident_id].append(
            {
                "resident_id": resident_id,
                "appointment_id": _value(attempt, "appointment_id"),
                "at": at,
            }
        )

    checked = 0
    breaches: list[dict[str, Any]] = []
    window = timedelta(days=cfg.rolling_window_days)

    for resident_id, records in by_resident.items():
        ordered = sorted(records, key=lambda record: record["at"])

        for index, record in enumerate(ordered):
            checked += 1

            at = record["at"]
            start = at - window

            # Every attempt with start < ts <= at is "in the window",
            # including other attempts that share this exact
            # timestamp — this record itself is one of them.
            count_including_current = sum(
                1
                for other in ordered
                if start < other["at"] <= at
            )

            count_before = count_including_current - 1

            # Deliberately independent of cfg.enforce_rolling_limit: this
            # function's entire purpose is to report what the actual
            # attempt history shows against the configured threshold,
            # including in the "Direction off" baseline where policy
            # was never enforcing that threshold in the first place.
            if count_including_current > cfg.max_contacts_per_window:
                breaches.append(
                    {
                        "resident_id": resident_id,
                        "appointment_id": record["appointment_id"],
                        "at": at.isoformat(),
                        "count_before": count_before,
                        "count_including_current": count_including_current,
                        "limit": cfg.max_contacts_per_window,
                        "window_days": cfg.rolling_window_days,
                    }
                )

    return ComplianceResult(
        breaches=len(breaches),
        checked_attempts=checked,
        breach_details=tuple(breaches),
    )


# ------------------------------------------------------------------
# Report assembly and rendering
# ------------------------------------------------------------------


def report(
    residents: list[Resident],
    appointments: list[Appointment],
    ledger: Any,
    cfg: Config,
    *,
    now: datetime | None = None,
    until: datetime | None = None,
) -> MetricsReport:
    """Build the complete Chapter 10 report."""

    start = now or cfg.now
    end = until or cfg.until

    reach = confirmed_reach(appointments, ledger, start, end)
    coverage = coverage_gap(appointments, ledger, start, end)
    harm = harm_ceiling(residents, ledger, start, end, cfg.rolling_window_days)
    compliance_result = compliance(residents, ledger, cfg)

    return MetricsReport(
        reach=reach,
        coverage=coverage,
        harm=harm,
        silent_failure_exposure=silent_failure_exposure(ledger),
        language_fallbacks=language_fallbacks(ledger),
        attempts_by_channel=attempts_by_channel(ledger),
        withheld_by_reason=withheld_by_reason(ledger),
        any_delivery_rate=any_delivery_rate(appointments, ledger, start, end),
        compliance=compliance_result,
    )


def _percent(value: float) -> str:
    """Format a rate as a percentage."""

    return f"{value * 100:.1f}%"


def render(metrics: MetricsReport) -> str:
    """
    Render the Chapter 10 report.

    The three headline blocks appear first:

        1. Confirmed reach rate
        2. Coverage gap
        3. Harm ceiling

    Messages sent is deliberately not a headline.
    """

    lines: list[str] = []

    lines.extend(
        [
            "=" * 64,
            "1. CONFIRMED REACH RATE",
            "=" * 64,
            (
                f"Confirmed reach: {metrics.reach.confirmed_reached}/"
                f"{metrics.reach.appointments_in_scope} appointments "
                f"({_percent(metrics.reach.confirmed_reach_rate)})"
            ),
            "Definition: appointment has at least one REACHED event.",
            "",
        ]
    )

    lines.extend(
        [
            "=" * 64,
            "2. COVERAGE GAP",
            "=" * 64,
            (
                "Appointments with no contact at all: "
                f"{metrics.coverage.appointments_without_contact}"
            ),
            "By cause:",
        ]
    )

    if metrics.coverage.by_reason:
        for reason, count in metrics.coverage.by_reason.items():
            lines.append(f"  - {reason}: {count}")
    else:
        lines.append("  - none")

    lines.append("")

    lines.extend(
        [
            "=" * 64,
            "3. HARM CEILING",
            "=" * 64,
            f"Max contacts / resident / 7 days: {metrics.harm.max_contacts_per_resident}",
            (
                "Max contacts / suspected person / 7 days: "
                f"{metrics.harm.max_contacts_per_identity}"
            ),
            "Definition: largest observed rolling seven-day contact count.",
            "",
        ]
    )

    lines.extend(
        [
            "=" * 64,
            "SECONDARY METRICS",
            "=" * 64,
            f"Any-delivery rate: {_percent(metrics.any_delivery_rate)}",
            "",
            "Silent-failure exposure:",
        ]
    )

    if metrics.silent_failure_exposure:
        for key, count in metrics.silent_failure_exposure.items():
            lines.append(f"  - {key}: {count}")
    else:
        lines.append("  - none")

    lines.extend(["", "Language fallbacks:"])

    if metrics.language_fallbacks:
        for language, count in metrics.language_fallbacks.items():
            lines.append(f"  - {language}: {count}")
    else:
        lines.append("  - none")

    lines.extend(["", "Attempts by channel:"])

    if metrics.attempts_by_channel:
        for channel, count in metrics.attempts_by_channel.items():
            lines.append(f"  - {channel}: {count}")
    else:
        lines.append("  - none")

    lines.extend(["", "Withheld by reason:"])

    if metrics.withheld_by_reason:
        for reason, count in metrics.withheld_by_reason.items():
            lines.append(f"  - {reason}: {count}")
    else:
        lines.append("  - none")

    lines.extend(
        [
            "",
            "=" * 64,
            "COMPLIANCE PROOF",
            "=" * 64,
            f"Attempts checked: {metrics.compliance.checked_attempts}",
            f"Compliance breaches: {metrics.compliance.breaches}",
        ]
    )

    if metrics.compliance.breach_details:
        lines.append("")
        lines.append("Breaches:")

        for breach in metrics.compliance.breach_details:
            lines.append(
                f"  - {breach['resident_id']} {breach['appointment_id']} "
                f"at {breach['at']}: "
                f"{breach['count_including_current']}/{breach['limit']}"
            )
    else:
        lines.append("Status: COMPLIANT")

    lines.append("=" * 64)

    return "\n".join(lines)