import random
from datetime import datetime, timedelta

import pytest

from src.config import Config
from src.history import Ledger
from src.metrics import (
    _max_rolling_count,
    compliance,
    coverage_gap,
    confirmed_reach,
    harm_ceiling,
    render,
    report,
)
from src.models import Appointment, Resident


NOW = datetime(2026, 3, 1, 9, 0)
UNTIL = datetime(2026, 3, 31, 9, 0)


# ----------------------------------------------------------------------
# Fixtures
#
# Deliberately uses the REAL history.Ledger, writing through its real
# append_attempt / append_withheld methods to a temp JSONL file. This
# is the whole point: a hand-rolled fake ledger can drift from the
# real interface (as the first draft of this module did) without any
# test ever noticing. Using the production class removes that failure
# mode by construction.
# ----------------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "history.jsonl")


def make_resident(resident_id="RS-1", identity_key=None, **overrides):
    defaults = dict(
        resident_id=resident_id,
        name="Test Resident",
        mobile="555-401-2288",
        language="en",
        identity_key=identity_key,
    )
    defaults.update(overrides)
    return Resident(**defaults)


def make_appointment(
    appointment_id="AP-1",
    resident_id="RS-1",
    scheduled_at=datetime(2026, 3, 10, 10, 0),
):
    return Appointment(
        appointment_id=appointment_id,
        resident_id=resident_id,
        scheduled_at=scheduled_at,
        location="District Office",
        service_type="Benefits",
    )


def record_attempt(
    ledger,
    appointment_id,
    resident_id="RS-1",
    identity_key=None,
    at=NOW,
    reach="failed",
    channel="sms",
    language="en",
    language_fallback=False,
):
    ledger.append_attempt(
        at=at,
        resident_id=resident_id,
        identity_key=identity_key,
        appointment_id=appointment_id,
        channel=channel,
        to="555-401-2288",
        attempt=1,
        language=language,
        language_fallback=language_fallback,
        body_hash="hash",
        status=reach,
        detail="",
        reach=reach,
        point_health="ok",
    )


def record_withheld(
    ledger,
    appointment_id,
    resident_id="RS-1",
    identity_key=None,
    at=NOW,
    reason="opt_out",
):
    ledger.append_withheld(
        at=at,
        resident_id=resident_id,
        identity_key=identity_key,
        appointment_id=appointment_id,
        channel="sms",
        reason=reason,
        detail={},
    )


# ----------------------------------------------------------------------
# 1. Confirmed reach
# ----------------------------------------------------------------------


def test_confirmed_reach_only_counts_reached(ledger):
    appointments = [make_appointment("AP-1"), make_appointment("AP-2")]

    record_attempt(ledger, "AP-1", reach="reached")
    record_attempt(ledger, "AP-2", reach="delivered")

    result = confirmed_reach(appointments, ledger, NOW, UNTIL)

    assert result.appointments_in_scope == 2
    assert result.confirmed_reached == 1
    assert result.confirmed_reach_rate == 0.5


def test_confirmed_reach_scope_includes_full_calendar_day_of_until(ledger):
    """
    Regression test: appointments scheduled later on the same calendar
    day as `until` must still count as in scope, even though their
    exact timestamp is after `until`'s time-of-day. The reporting
    window is calendar-date bounded, not instant bounded — an earlier
    version of this module dropped these appointments (940 -> 910 on
    the real data pack) even though the chapter's own worked numbers
    assume all of them are counted.
    """

    late_on_last_day = make_appointment(
        "AP-LATE",
        scheduled_at=datetime(2026, 3, 31, 16, 0),
    )

    until = datetime(2026, 3, 31, 9, 0)

    result = confirmed_reach([late_on_last_day], ledger, NOW, until)

    assert result.appointments_in_scope == 1


# ----------------------------------------------------------------------
# 2. Coverage gap
# ----------------------------------------------------------------------


def test_coverage_gap_counts_only_appointments_with_no_attempt(ledger):
    appointments = [
        make_appointment("AP-1"),
        make_appointment("AP-2"),
        make_appointment("AP-3"),
    ]

    record_attempt(ledger, "AP-1")
    record_withheld(ledger, "AP-2", reason="rolling_contact_limit")
    record_withheld(ledger, "AP-3", reason="opt_out")

    result = coverage_gap(appointments, ledger, NOW, UNTIL)

    assert result.appointments_without_contact == 2
    assert result.by_reason == {
        "opt_out": 1,
        "rolling_contact_limit": 1,
    }


def test_coverage_gap_uses_one_highest_priority_reason(ledger):
    appointment = make_appointment("AP-1")

    record_withheld(ledger, "AP-1", reason="opt_out")
    record_withheld(ledger, "AP-1", reason="rolling_contact_limit")

    result = coverage_gap([appointment], ledger, NOW, UNTIL)

    assert result.appointments_without_contact == 1
    assert result.by_reason == {"rolling_contact_limit": 1}


def test_coverage_gap_falls_back_when_nothing_was_ever_withheld(ledger):
    """
    An appointment with zero attempts and zero withheld rows (e.g. an
    orphan appointment the engine never even considered) still counts
    toward the gap, under a distinct catch-all reason.
    """

    appointment = make_appointment("AP-ORPHAN")

    result = coverage_gap([appointment], ledger, NOW, UNTIL)

    assert result.appointments_without_contact == 1
    assert result.by_reason == {"no_contact_recorded": 1}


# ----------------------------------------------------------------------
# 3. Harm ceiling
# ----------------------------------------------------------------------


def test_harm_ceiling_counts_failed_attempts(ledger):
    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", at=datetime(2026, 3, 10, 9, 0))
    record_attempt(ledger, "AP-2", at=datetime(2026, 3, 11, 9, 0))
    record_attempt(ledger, "AP-3", at=datetime(2026, 3, 12, 9, 0))

    result = harm_ceiling(
        residents, ledger, datetime(2026, 3, 1), datetime(2026, 3, 31)
    )

    assert result.max_contacts_per_resident == 3


def test_harm_ceiling_uses_rolling_seven_days(ledger):
    residents = [make_resident("RS-1")]

    record_attempt(ledger, "OLD", at=datetime(2026, 3, 1, 9, 0))
    record_attempt(ledger, "NEW", at=datetime(2026, 3, 10, 9, 0))

    result = harm_ceiling(
        residents, ledger, datetime(2026, 3, 1), datetime(2026, 3, 31)
    )

    assert result.max_contacts_per_resident == 1


def test_harm_ceiling_excludes_attempt_exactly_at_window_start(ledger):
    """
    Window is start < ts <= at, with start = at - 7 days. An attempt
    landing exactly on `start` (exactly 7 days before `at`) sits ON
    the excluded boundary and must NOT count alongside `at`.
    """

    residents = [make_resident("RS-1")]

    at = datetime(2026, 3, 17, 9, 0)
    exactly_on_boundary = at - timedelta(days=7)

    record_attempt(ledger, "AP-1", at=exactly_on_boundary)
    record_attempt(ledger, "AP-2", at=at)

    result = harm_ceiling(
        residents, ledger, datetime(2026, 3, 1), datetime(2026, 3, 31)
    )

    assert result.max_contacts_per_resident == 1


def test_harm_ceiling_includes_attempt_just_inside_window(ledger):
    """
    An attempt one minute inside the boundary (start < ts) must count
    alongside `at`, unlike the exactly-on-boundary case above.
    """

    residents = [make_resident("RS-1")]

    at = datetime(2026, 3, 17, 9, 0)
    just_inside = at - timedelta(days=7) + timedelta(minutes=1)

    record_attempt(ledger, "AP-1", at=just_inside)
    record_attempt(ledger, "AP-2", at=at)

    result = harm_ceiling(
        residents, ledger, datetime(2026, 3, 1), datetime(2026, 3, 31)
    )

    assert result.max_contacts_per_resident == 2


def test_harm_ceiling_counts_suspected_person(ledger):
    shared_identity = "person@example.net|test resident"

    residents = [
        make_resident("RS-1", identity_key=shared_identity),
        make_resident("RS-2", identity_key=shared_identity),
    ]

    record_attempt(
        ledger, "AP-1", resident_id="RS-1", identity_key=shared_identity
    )
    record_attempt(
        ledger, "AP-2", resident_id="RS-2", identity_key=shared_identity
    )

    result = harm_ceiling(residents, ledger, NOW, UNTIL)

    assert result.max_contacts_per_resident == 1
    assert result.max_contacts_per_identity == 2


def test_harm_ceiling_matches_brute_force_reference():
    """
    Cross-check the O(n log n) sliding-window implementation against
    a naive O(n^2) reference on randomized data, for one resident's
    timestamps, with `now`/`until` spanning the whole sample so every
    timestamp is a valid observation point.
    """

    rng = random.Random(1234)

    reference_max = 0
    timestamps = []

    base = datetime(2026, 3, 1)

    for _ in range(60):
        timestamps.append(base + timedelta(hours=rng.randint(0, 24 * 30)))

    for at in timestamps:
        start = at - timedelta(days=7)
        count = sum(1 for ts in timestamps if start < ts <= at)
        reference_max = max(reference_max, count)

    scope_start = base - timedelta(days=1)
    scope_end = base + timedelta(days=31)

    assert (
        _max_rolling_count(timestamps, 7, scope_start, scope_end)
        == reference_max
    )


def test_harm_ceiling_looks_back_before_the_reporting_window(ledger):
    """
    Regression test: a resident's rolling count must be able to reach
    back to an attempt made BEFORE `now`. An earlier version of this
    function pre-filtered attempts to [now, until] before computing
    windows at all, which silently dropped a look-back contact and
    undercounted harm for reports run on stored history that predates
    the requested window (e.g. re-reporting on just the back half of
    a month that already has history from the front half).
    """

    residents = [make_resident("RS-1")]

    now = datetime(2026, 3, 1)
    until = datetime(2026, 3, 31)

    record_attempt(ledger, "AP-OLD", at=datetime(2026, 2, 27, 9, 0))  # before `now`
    record_attempt(ledger, "AP-NEW", at=datetime(2026, 3, 2, 9, 0))   # in scope

    result = harm_ceiling(residents, ledger, now, until)

    # Feb 27 is 3 days before March 2 — well within the 7-day window
    # ending at the March 2 attempt, even though Feb 27 itself is
    # before the reporting period starts.
    assert result.max_contacts_per_resident == 2


def test_harm_ceiling_ignores_attempts_entirely_outside_reporting_window():
    """
    An attempt long before `now`, with nothing else nearby, must not
    itself surface as an observation point outside [now, until].
    """

    timestamps = [datetime(2026, 1, 1, 9, 0)]

    result = _max_rolling_count(
        timestamps, 7, datetime(2026, 3, 1), datetime(2026, 3, 31)
    )

    assert result == 0


# ----------------------------------------------------------------------
# Compliance proof
# ----------------------------------------------------------------------


def test_compliance_recomputes_rolling_count(ledger):
    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", at=datetime(2026, 3, 1, 9, 0))
    record_attempt(ledger, "AP-2", at=datetime(2026, 3, 3, 9, 0))
    record_attempt(ledger, "AP-3", at=datetime(2026, 3, 4, 9, 0))

    cfg = Config(
        enforce_rolling_limit=True,
        rolling_window_days=7,
        max_contacts_per_window=2,
    )

    result = compliance(residents, ledger, cfg)

    assert result.checked_attempts == 3
    assert result.breaches == 1

    breach = result.breach_details[0]
    assert breach["appointment_id"] == "AP-3"
    assert breach["count_before"] == 2
    assert breach["count_including_current"] == 3


def test_compliance_allows_contact_outside_rolling_window(ledger):
    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", at=datetime(2026, 3, 1, 9, 0))
    record_attempt(ledger, "AP-2", at=datetime(2026, 3, 9, 9, 0))
    record_attempt(ledger, "AP-3", at=datetime(2026, 3, 10, 9, 0))

    cfg = Config(
        enforce_rolling_limit=True,
        rolling_window_days=7,
        max_contacts_per_window=2,
    )

    result = compliance(residents, ledger, cfg)

    assert result.breaches == 0


def test_compliance_counts_same_tick_duplicate_timestamps(ledger):
    """
    Regression test: two of a resident's appointments processed in
    the same simulated tick produce two attempts with an IDENTICAL
    timestamp. An earlier version of compliance() used a strict '<'
    comparison that treated same-timestamp attempts as simultaneous
    rather than in each other's window, silently undercounting and
    missing real breaches.
    """

    residents = [make_resident("RS-1")]

    same_tick = datetime(2026, 3, 5, 9, 0)

    record_attempt(ledger, "AP-1", at=same_tick)
    record_attempt(ledger, "AP-2", at=same_tick)
    record_attempt(ledger, "AP-3", at=same_tick)

    cfg = Config(
        enforce_rolling_limit=True,
        rolling_window_days=7,
        max_contacts_per_window=2,
    )

    result = compliance(residents, ledger, cfg)

    # All three attempts land in each other's window: the ledger
    # allows more than one attempt per tick in principle even though
    # policy would ordinarily prevent it — compliance() must not rely
    # on policy to keep it honest.
    assert result.checked_attempts == 3
    assert result.breaches >= 1


def test_compliance_reports_breaches_even_when_direction_is_off(ledger):
    """
    Regression test: compliance() must report what the attempt
    history actually shows against max_contacts_per_window regardless
    of cfg.enforce_rolling_limit. That flag controls whether POLICY
    blocks sends; compliance() is the independent check of what
    happened. Gating the breach check on the same flag would make it
    impossible to ever see a breach in exactly the "Direction off"
    baseline scenario the chapter uses this proof to characterize
    (490 breaches, per the worked example, with the Direction off).
    """

    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", at=datetime(2026, 3, 1, 9, 0))
    record_attempt(ledger, "AP-2", at=datetime(2026, 3, 3, 9, 0))
    record_attempt(ledger, "AP-3", at=datetime(2026, 3, 4, 9, 0))

    cfg = Config(
        enforce_rolling_limit=False,
        rolling_window_days=7,
        max_contacts_per_window=2,
    )

    result = compliance(residents, ledger, cfg)

    assert result.breaches == 1


def test_compliance_ignores_attempts_for_unknown_residents(ledger):
    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", resident_id="RS-1")
    record_attempt(ledger, "AP-2", resident_id="RS-GHOST")

    cfg = Config(enforce_rolling_limit=True, max_contacts_per_window=2)

    result = compliance(residents, ledger, cfg)

    assert result.checked_attempts == 1


def test_compliance_is_not_trivially_compliant_when_disabled(ledger):
    """
    Regression test: an earlier version of this module silently read
    zero attempts from the real ledger (wrong attribute names), so
    checked_attempts was always 0 and breaches was always 0 — which
    looks identical to a genuinely compliant system. Any run with
    real attempts in the ledger must show a nonzero checked count.
    """

    residents = [make_resident("RS-1")]

    record_attempt(ledger, "AP-1", at=datetime(2026, 3, 1, 9, 0))
    record_attempt(ledger, "AP-2", at=datetime(2026, 3, 2, 9, 0))

    cfg = Config(enforce_rolling_limit=True, max_contacts_per_window=2)

    result = compliance(residents, ledger, cfg)

    assert result.checked_attempts > 0


# ----------------------------------------------------------------------
# Secondary metrics + rendering
# ----------------------------------------------------------------------


def test_render_contains_all_three_headlines(ledger):
    residents = [make_resident("RS-1")]
    appointments = [make_appointment("AP-1")]

    record_attempt(ledger, "AP-1", reach="reached")

    metrics = report(residents, appointments, ledger, Config(), now=NOW, until=UNTIL)
    output = render(metrics)

    assert "1. CONFIRMED REACH RATE" in output
    assert "2. COVERAGE GAP" in output
    assert "3. HARM CEILING" in output
    assert "Confirmed reach:" in output
    assert "Appointments with no contact at all:" in output
    assert "Max contacts / resident / 7 days:" in output
    assert "Max contacts / suspected person / 7 days:" in output


def test_report_reads_secondary_metrics_from_the_real_ledger(ledger):
    """
    Regression test: silent_failure_exposure, language_fallbacks,
    attempts_by_channel and withheld_by_reason must reflect what's
    actually in the ledger, not silently come back empty.
    """

    residents = [make_resident("RS-1")]
    appointments = [make_appointment("AP-1"), make_appointment("AP-2")]

    record_attempt(
        ledger, "AP-1", reach="unverifiable", channel="sms",
    )
    record_attempt(
        ledger, "AP-2", reach="delivered", channel="voice",
        language="en", language_fallback=True,
    )
    record_withheld(ledger, "AP-2", reason="quiet_hours")

    metrics = report(residents, appointments, ledger, Config(), now=NOW, until=UNTIL)

    assert metrics.silent_failure_exposure == {"sms:": 1}
    assert metrics.language_fallbacks == {"en": 1}
    assert metrics.attempts_by_channel == {"sms": 1, "voice": 1}
    assert metrics.withheld_by_reason == {"quiet_hours": 1}


def test_render_does_not_headline_a_send_count(ledger):
    """
    The three headline blocks must appear, in order, ahead of any
    raw send/attempt count. This checks structure rather than a
    single hardcoded phrase, so it can't pass vacuously.
    """

    residents = [make_resident("RS-1")]
    appointments = [make_appointment("AP-1")]

    metrics = report(residents, appointments, ledger, Config(), now=NOW, until=UNTIL)
    output = render(metrics)

    reach_pos = output.index("1. CONFIRMED REACH RATE")
    coverage_pos = output.index("2. COVERAGE GAP")
    harm_pos = output.index("3. HARM CEILING")
    secondary_pos = output.index("SECONDARY METRICS")

    assert reach_pos < coverage_pos < harm_pos < secondary_pos


# ----------------------------------------------------------------------
# Ledger persistence
# ----------------------------------------------------------------------


def test_metrics_work_after_reloading_ledger_from_disk(tmp_path):
    """
    metrics.py must work identically whether the Ledger was just
    written to in-process or reloaded from its JSONL file — this is
    how a real `report` CLI invocation would use it (separate process
    from the `run` that generated the history).
    """

    path = tmp_path / "history.jsonl"

    writer = Ledger(path)
    record_attempt(writer, "AP-1", reach="reached", at=NOW)
    record_withheld(writer, "AP-2", reason="opt_out", at=NOW)

    reloaded = Ledger(path)

    appointments = [make_appointment("AP-1"), make_appointment("AP-2")]

    reach = confirmed_reach(appointments, reloaded, NOW, UNTIL)
    coverage = coverage_gap(appointments, reloaded, NOW, UNTIL)

    assert reach.confirmed_reached == 1
    assert coverage.appointments_without_contact == 1
    assert coverage.by_reason == {"opt_out": 1}