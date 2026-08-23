#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import signal
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from src.config import Config
from src.engine import Engine
from src.history import Ledger
from src.loading import audit, load_appointments, load_residents
from src.message import MessageBuilder


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / "runtime"
TEMPLATES_DIR = ROOT / "templates"

CONTACTS_PATH = DATA_DIR / "contacts.csv"
APPOINTMENTS_PATH = DATA_DIR / "appointments.csv"
HISTORY_PATH = RUNTIME_DIR / "contact_history.jsonl"
OUTBOX_PATH = RUNTIME_DIR / "outbox.jsonl"


def parse_datetime(value: str) -> datetime:
    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d %H:%M",
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid datetime: {value!r}; "
            "expected YYYY-MM-DD HH:MM"
        ) from exc


def parse_tick_hours(value: str) -> list[int]:
    try:
        hours = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "tick hours must be comma-separated integers"
        ) from exc

    if not hours:
        raise argparse.ArgumentTypeError(
            "at least one tick hour is required"
        )

    if any(hour < 0 or hour > 23 for hour in hours):
        raise argparse.ArgumentTypeError(
            "tick hours must be between 0 and 23"
        )

    if len(set(hours)) != len(hours):
        raise argparse.ArgumentTypeError(
            "tick hours must not contain duplicates"
        )

    return sorted(hours)


def load_data() -> tuple[list, list]:
    residents = load_residents(CONTACTS_PATH)
    appointments = load_appointments(APPOINTMENTS_PATH)

    return residents, appointments


def fresh_runtime() -> None:
    RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    HISTORY_PATH.unlink(
        missing_ok=True,
    )

    OUTBOX_PATH.unlink(
        missing_ok=True,
    )


# ----------------------------------------------------------------------
# Ledger helpers
#
# history.Ledger exposes attempts_for_resident / attempts_for_appointment
# and a mixed `.records` property (each tagged record["kind"]), but does
# NOT expose withheld_for_resident / withheld_for_appointment directly.
# Filter `.records` here rather than guessing at a method name the real
# class doesn't have — that exact mistake is what crashed the first
# version of this file on both `explain` and `trace`.
# ----------------------------------------------------------------------


def withheld_for_resident(
    ledger: Ledger,
    resident_id: str,
) -> list[dict]:
    """Every withheld record for one resident, in append order."""

    return [
        record
        for record in ledger.records
        if record["kind"] == "withheld"
        and record["resident_id"] == resident_id
    ]


def withheld_for_appointment(
    ledger: Ledger,
    appointment_id: str,
) -> list[dict]:
    """Every withheld record for one appointment, in append order."""

    return [
        record
        for record in ledger.records
        if record["kind"] == "withheld"
        and record["appointment_id"] == appointment_id
    ]


def build_config(args) -> Config:
    """
    Build the Config for a `run` invocation.

    Note: `--tick-hours` (args.tick_hours) is a LIST of specific
    clock hours the batch fires at (e.g. [4, 9]) — a fundamentally
    different thing from Config.tick_hours, which is a single-int
    "every N hours" step used by Engine.simulate(). This CLI uses
    run_ticks() below instead of simulate(), specifically so it can
    fire at exact hours (the whole point of s.11 is to be able to
    show quiet-hours blocking at a chosen hour) — so Config.tick_hours
    is simply left at its default here rather than being force-fit
    with the wrong type.
    """

    cfg = Config(
        now=args.now,
        until=args.until,
        data_dir=DATA_DIR,
        runtime_dir=RUNTIME_DIR,
        templates_dir=TEMPLATES_DIR,
        contacts_path=CONTACTS_PATH,
        appointments_path=APPOINTMENTS_PATH,
        history_path=HISTORY_PATH,
    )

    if args.no_limit:
        cfg = replace(
            cfg,
            enforce_rolling_limit=False,
        )

    if args.identity_guard is not None:
        cfg = replace(
            cfg,
            identity_guard=args.identity_guard,
        )

    return cfg


def command_audit(args) -> None:
    residents, appointments = load_data()

    result = audit(
        residents,
        appointments,
    )

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )


def command_run(args) -> None:
    if args.fresh:
        fresh_runtime()
    else:
        RUNTIME_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    residents, appointments = load_data()

    cfg = build_config(args)

    ledger = Ledger(
        HISTORY_PATH,
    )

    if args.seed_history:
        ledger.import_prior(
            args.seed_history,
        )

    messages = MessageBuilder(
        TEMPLATES_DIR,
        default_language=cfg.default_language,
    )

    engine = Engine(
        cfg=cfg,
        residents=residents,
        appointments=appointments,
        ledger=ledger,
        messages=messages,
    )

    results = run_ticks(
        engine,
        args.now,
        args.until,
        args.tick_hours,
    )

    print(
        json.dumps(
            {
                "start": args.now.isoformat(
                    sep=" "
                ),
                "until": args.until.isoformat(
                    sep=" "
                ),
                "ticks": len(results),
                "attempted": sum(
                    result.attempted
                    for result in results
                ),
                "withheld": sum(
                    result.withheld
                    for result in results
                ),
                "rolling_limit":
                    cfg.enforce_rolling_limit,
                "identity_guard":
                    cfg.identity_guard,
            },
            indent=2,
        )
    )


def run_ticks(
    engine: Engine,
    start: datetime,
    until: datetime,
    tick_hours: list[int],
):
    """
    Run one tick per configured hour, per calendar day, from start
    through until inclusive.

    This deliberately does NOT use Engine.simulate() (which steps by
    a fixed hourly interval): --tick-hours names specific hours of
    the day the batch fires at (e.g. 4 and 9), which is what actually
    lets a run demonstrate quiet-hours blocking at a chosen hour.
    """

    results = []

    current_date = start.date()

    while current_date <= until.date():
        for hour in tick_hours:
            tick = datetime.combine(
                current_date,
                datetime.min.time(),
            ).replace(
                hour=hour,
            )

            if tick < start or tick > until:
                continue

            results.append(
                engine.tick(tick)
            )

        current_date += timedelta(
            days=1,
        )

    return results


def command_report(args) -> None:
    # Wired to the Chapter 10 metrics API.
    #
    # Read-only: inspects stored history, never executes the engine.
    from src.metrics import report, render

    residents, appointments = load_data()

    ledger = Ledger(
        HISTORY_PATH,
    )

    defaults = Config()

    cfg = Config(
        now=args.now or defaults.now,
        until=args.until or defaults.until,
    )

    result = report(
        residents,
        appointments,
        ledger,
        cfg,
    )

    print(
        render(result)
    )


def command_explain(args) -> None:
    residents, appointments = load_data()

    ledger = Ledger(
        HISTORY_PATH,
    )

    cfg = Config()

    resident = next(
        (
            resident
            for resident in residents
            if resident.resident_id == args.resident
        ),
        None,
    )

    if resident is None:
        raise SystemExit(
            f"unknown resident: {args.resident}"
        )

    contacts = ledger.contacts_in_window(
        resident.resident_id,
        args.date,
        cfg.rolling_window_days,
    )

    withheld = [
        record
        for record in withheld_for_resident(
            ledger,
            resident.resident_id,
        )
        if datetime.fromisoformat(record["at"]) <= args.date
    ]

    print(
        json.dumps(
            {
                "resident": resident.resident_id,
                "date": args.date.isoformat(
                    sep=" "
                ),
                "window_days": cfg.rolling_window_days,
                "counted_contacts": len(
                    contacts
                ),
                "contacts": contacts,
                "withheld": withheld,
            },
            indent=2,
            default=str,
        )
    )


def command_trace(args) -> None:
    ledger = Ledger(
        HISTORY_PATH,
    )

    attempts = ledger.attempts_for_appointment(
        args.appointment,
    )

    withheld = withheld_for_appointment(
        ledger,
        args.appointment,
    )

    print(
        json.dumps(
            {
                "appointment": args.appointment,
                "attempts": attempts,
                "withheld": withheld,
            },
            indent=2,
            default=str,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calder County appointment reminder system"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ----------------------------------------------------------
    # audit
    # ----------------------------------------------------------

    audit_parser = subparsers.add_parser(
        "audit",
        help="report what is actually in the data",
    )

    audit_parser.set_defaults(
        handler=command_audit,
    )

    # ----------------------------------------------------------
    # run
    # ----------------------------------------------------------

    run_parser = subparsers.add_parser(
        "run",
        help="run the reminder program",
    )

    run_parser.add_argument(
        "--now",
        required=True,
        type=parse_datetime,
    )

    run_parser.add_argument(
        "--until",
        required=True,
        type=parse_datetime,
    )

    run_parser.add_argument(
        "--fresh",
        action="store_true",
        help="delete previous history before running",
    )

    run_parser.add_argument(
        "--seed-history",
        type=Path,
        help="import contact history made before this system",
    )

    run_parser.add_argument(
        "--tick-hours",
        required=True,
        type=parse_tick_hours,
        help="daily batch hours, e.g. 4,9",
    )

    run_parser.add_argument(
        "--no-limit",
        action="store_true",
        help="disable the Direction rolling contact limit",
    )

    run_parser.add_argument(
        "--identity-guard",
        choices=("off", "flag", "enforce"),
    )

    run_parser.set_defaults(
        handler=command_run,
    )

    # ----------------------------------------------------------
    # report
    # ----------------------------------------------------------

    report_parser = subparsers.add_parser(
        "report",
        help="re-report on stored history",
    )

    report_parser.add_argument(
        "--now",
        type=parse_datetime,
        default=None,
        help=(
            "optional: override the reporting window start "
            "(defaults to the full data-pack month)"
        ),
    )

    report_parser.add_argument(
        "--until",
        type=parse_datetime,
        default=None,
        help="optional: override the reporting window end",
    )

    report_parser.set_defaults(
        handler=command_report,
    )

    # ----------------------------------------------------------
    # explain
    # ----------------------------------------------------------

    explain_parser = subparsers.add_parser(
        "explain",
        help="show seven-day contact evidence",
    )

    explain_parser.add_argument(
        "--resident",
        required=True,
    )

    explain_parser.add_argument(
        "--date",
        required=True,
        type=parse_datetime,
    )

    explain_parser.set_defaults(
        handler=command_explain,
    )

    # ----------------------------------------------------------
    # trace
    # ----------------------------------------------------------

    trace_parser = subparsers.add_parser(
        "trace",
        help="show everything recorded for an appointment",
    )

    trace_parser.add_argument(
        "--appointment",
        required=True,
    )

    trace_parser.set_defaults(
        handler=command_trace,
    )

    return parser


def main() -> None:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(
            signal.SIGPIPE,
            signal.SIG_DFL,
        )

    parser = build_parser()
    args = parser.parse_args()

    args.handler(args)


if __name__ == "__main__":
    main()