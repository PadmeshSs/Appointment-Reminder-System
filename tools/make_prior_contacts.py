from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.loading import load_residents
from src.models import Channel


CONTACTS_PATH = ROOT / "data" / "contacts.csv"

SEED = 20260313
TARGET_CONTACTS = 310

START = datetime(2026, 2, 20, 9, 0)
END = datetime(2026, 2, 28, 18, 0)


def eligible_residents():
    residents = load_residents(CONTACTS_PATH)

    return [
        resident
        for resident in residents
        if resident.resident_id[-1:] in {"0", "1", "2"}
        and resident.point_for(Channel.SMS)
    ]


def build_records():
    random.seed(SEED)

    residents = eligible_residents()

    if not residents:
        raise RuntimeError(
            "No eligible residents found."
        )

    records = []

    span_seconds = int(
        (END - START).total_seconds()
    )

    for index in range(TARGET_CONTACTS):
        resident = residents[index % len(residents)]

        offset = random.randint(
            0,
            span_seconds,
        )

        at = START + timedelta(
            seconds=offset,
        )

        records.append(
            {
                "kind": "attempt",
                "at": at.isoformat(),
                "resident_id": resident.resident_id,
                "identity_key": resident.identity_key,
                "appointment_id": f"PRIOR-{index + 1:04d}",
                "channel": "sms",
                "to": resident.mobile,
                "attempt": 1,
                "language": resident.language or "en",
                "language_fallback": False,
                "body_hash": f"prior-contact-{index + 1:04d}",
                "status": "failed",
                "detail": "prior_system_contact",
                "reach": "failed",
                "point_health": "ok",
            }
        )

    records.sort(
        key=lambda record: record["at"]
    )

    if len(records) != TARGET_CONTACTS:
        raise RuntimeError(
            f"Expected {TARGET_CONTACTS} records, "
            f"generated {len(records)}"
        )

    return records


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        type=Path,
        help="Output UTF-8 JSONL file.",
    )

    args = parser.parse_args()

    records = build_records()

    text = "".join(
        json.dumps(
            record,
            sort_keys=True,
        ) + "\n"
        for record in records
    )

    if args.output:
        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        args.output.write_text(
            text,
            encoding="utf-8",
            newline="",
        )
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()