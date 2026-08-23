#!/usr/bin/env python3

import json
import sys
from pathlib import Path

from src.loading import audit, load_appointments, load_residents


ROOT = Path(__file__).resolve().parent

DATA_DIR = ROOT / "data"

CONTACTS_PATH = DATA_DIR / "contacts.csv"
APPOINTMENTS_PATH = DATA_DIR / "appointments.csv"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "audit":
        print("Usage: python3 main.py audit")
        raise SystemExit(1)

    residents = load_residents(CONTACTS_PATH)
    appointments = load_appointments(APPOINTMENTS_PATH)

    report = audit(
        residents,
        appointments,
    )

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()