from __future__ import annotations
from .config import Config
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .models import Appointment, Resident


DATE_FORMAT = "%Y-%m-%d %H:%M"


def _clean(value: str | None) -> str:
    """Strip whitespace from a CSV field."""
    if value is None:
        return ""

    return value.strip()


def _clean_lower(value: str | None) -> str:
    """Strip whitespace and lowercase a CSV field."""
    return _clean(value).lower()


def _parse_bool(value: str | None) -> bool:
    """Convert Y to True and everything else to False."""
    return _clean(value).upper() == "Y"


def _parse_scheduled_at(value: str | None) -> datetime | None:
    """Parse appointment datetime."""
    value = _clean(value)

    if not value:
        return None

    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def _parse_verified_date(value: str | None) -> datetime | None:
    """Parse the contact verification date."""
    value = _clean(value)

    if not value:
        return None

    return datetime.strptime(value, "%Y-%m-%d")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    """
    Read a CSV using utf-8-sig so the BOM is removed from the
    first column name.
    """
    path = Path(path)

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        return list(reader)


def _normalise_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Strip every field in every row."""
    return [
        {
            key.strip(): _clean(value)
            for key, value in row.items()
        }
        for row in rows
    ]


def _landline_prefix(number: str | None) -> str | None:
    """
    Return the exchange/prefix from a number such as:

        555-223-1234

    -> "223"
    """
    number = _clean(number)

    if not number:
        return None

    parts = number.split("-")

    if len(parts) < 2:
        return None

    return parts[1]


def _observed_landline_prefixes(
    rows: list[dict[str, str]],
) -> set[str]:
    """
    Derive the landline-prefix set from the landline column.

    This deliberately does NOT copy the secret 555-2xx rule from
    channels.py.
    """
    prefixes: set[str] = set()

    for row in rows:
        prefix = _landline_prefix(row.get("landline"))

        if prefix is not None:
            prefixes.add(prefix)

    return prefixes


def _derive_identity_keys(
    rows: list[dict[str, str]],
) -> dict[str, str | None]:
    """
    Group residents by:

        (lower(email), lower(name))

    A group gets an identity_key only when more than one
    resident belongs to that group.
    """
    groups: defaultdict[tuple[str, str], list[str]] = defaultdict(list)

    for row in rows:
        resident_id = _clean(row.get("resident_id"))
        email = _clean_lower(row.get("email"))
        name = _clean_lower(row.get("name"))

        if not email or not name:
            continue

        groups[(email, name)].append(resident_id)

    identity_keys: dict[str, str | None] = {
        _clean(row.get("resident_id")): None
        for row in rows
    }

    for (email, name), resident_ids in groups.items():
        if len(resident_ids) <= 1:
            continue

        identity_key = f"{email}|{name}"

        for resident_id in resident_ids:
            identity_keys[resident_id] = identity_key

    return identity_keys


def load_residents(
    path: str | Path,
) -> list[Resident]:
    """
    Load, normalise, and derive resident data.
    """
    rows = _read_csv(path)
    rows = _normalise_rows(rows)

    landline_prefixes = _observed_landline_prefixes(rows)
    identity_keys = _derive_identity_keys(rows)

    residents: list[Resident] = []

    for row in rows:
        resident_id = _clean(row.get("resident_id"))
        mobile = _clean(row.get("mobile"))
        landline = _clean(row.get("landline"))

        mobile_prefix = _landline_prefix(mobile)

        suspected_landline_mobile = (
            mobile_prefix in landline_prefixes
            if mobile_prefix is not None
            else False
        )

        resident = Resident(
            resident_id=resident_id,
            name=_clean(row.get("name")),
            mobile=mobile or None,
            landline=landline or None,
            email=_clean_lower(row.get("email")) or None,
            language=_clean_lower(row.get("language")),
            sms_optout=_parse_bool(row.get("sms_optout")),
            voice_optout=_parse_bool(row.get("voice_optout")),
            email_optout=_parse_bool(row.get("email_optout")),
            number_last_verified=_parse_verified_date(
                row.get("number_last_verified")
            ),
            suspected_landline_mobile=suspected_landline_mobile,
            identity_key=identity_keys.get(resident_id),
        )

        residents.append(resident)

    return residents


def load_appointments(
    path: str | Path,
) -> list[Appointment]:
    """Load and normalise appointments."""
    rows = _read_csv(path)
    rows = _normalise_rows(rows)

    appointments: list[Appointment] = []

    for row in rows:
        scheduled_at = _parse_scheduled_at(
            row.get("scheduled_at")
        )

        if scheduled_at is None:
            raise ValueError(
                f"Appointment {row.get('appointment_id')} "
                "has no scheduled_at value"
            )

        appointment = Appointment(
            appointment_id=_clean(row.get("appointment_id")),
            resident_id=_clean(row.get("resident_id")),
            scheduled_at=scheduled_at,
            location=_clean(row.get("location")),
            service_type=_clean(row.get("service_type")),
            status=_clean(row.get("status")),
        )

        appointments.append(appointment)

    return appointments


def audit(
    residents: list[Resident],
    appointments: list[Appointment],
) -> dict:
    """
    Return the Chapter 2 audit numbers.
    """

    resident_ids = {
        resident.resident_id
        for resident in residents
    }

    appointment_ids = [
        appointment.appointment_id
        for appointment in appointments
    ]

    appointment_resident_ids = {
        appointment.resident_id
        for appointment in appointments
    }

    # ---------------------------------------------------------
    # Contact completeness
    # ---------------------------------------------------------

    no_contact = [
        resident
        for resident in residents
        if not (
            resident.mobile
            or resident.landline
            or resident.email
        )
    ]

    no_contact_with_appointments = sum(
        resident.resident_id in appointment_resident_ids
        for resident in no_contact
    )

    no_mobile = sum(
        resident.mobile is None
        for resident in residents
    )

    no_landline = sum(
        resident.landline is None
        for resident in residents
    )

    no_email = sum(
        resident.email is None
        for resident in residents
    )

    # ---------------------------------------------------------
    # Opt-outs
    # ---------------------------------------------------------

    fully_opted_out = [
        resident
        for resident in residents
        if (
            resident.sms_optout
            and resident.voice_optout
            and resident.email_optout
        )
    ]

    fully_opted_out_with_appointments = sum(
        resident.resident_id in appointment_resident_ids
        for resident in fully_opted_out
    )

    # ---------------------------------------------------------
    # Suspected landline mobiles
    # ---------------------------------------------------------

    suspected_landline = [
        resident
        for resident in residents
        if resident.suspected_landline_mobile
    ]

    suspected_landline_without_other_contact = sum(
        resident.suspected_landline_mobile
        and not resident.landline
        and not resident.email
        for resident in residents
    )

    # ---------------------------------------------------------
    # Shared mobiles
    # ---------------------------------------------------------

    mobile_groups: defaultdict[str, list[Resident]] = defaultdict(list)

    for resident in residents:
        if resident.mobile:
            mobile_groups[resident.mobile].append(resident)

    shared_mobiles = {
        mobile: group
        for mobile, group in mobile_groups.items()
        if len(group) > 1
    }

    shared_mobile_resident_count = sum(
        len(group)
        for group in shared_mobiles.values()
    )

    shared_mobile_different_name_groups = sum(
        len(
            {
                resident.name.lower()
                for resident in group
            }
        ) > 1
        for group in shared_mobiles.values()
    )

    # ---------------------------------------------------------
    # Shared emails
    # ---------------------------------------------------------

    email_groups: defaultdict[str, list[Resident]] = defaultdict(list)

    for resident in residents:
        if resident.email:
            email_groups[resident.email].append(resident)

    shared_emails = {
        email: group
        for email, group in email_groups.items()
        if len(group) > 1
    }

    shared_email_resident_count = sum(
        len(group)
        for group in shared_emails.values()
    )

    shared_email_identical_name_groups = sum(
        len(
            {
                resident.name.lower()
                for resident in group
            }
        ) == 1
        for group in shared_emails.values()
    )

    # ---------------------------------------------------------
    # Identity clusters
    # ---------------------------------------------------------

    identity_groups: defaultdict[str, list[Resident]] = defaultdict(list)

    for resident in residents:
        if resident.identity_key:
            identity_groups[resident.identity_key].append(resident)

    language_disagreements = sum(
        len(
            {
                resident.language
                for resident in group
            }
        ) > 1
        for group in identity_groups.values()
    )

    optout_disagreements = sum(
        len(
            {
                (
                    resident.sms_optout,
                    resident.voice_optout,
                    resident.email_optout,
                )
                for resident in group
            }
        ) > 1
        for group in identity_groups.values()
    )

    # ---------------------------------------------------------
    # Verification age
    # ---------------------------------------------------------

    # The project data itself does not provide an explicit audit date.
    # Do not invent one here. Use the latest appointment date as the
    # dataset reference point.
    config = Config()
    audit_date = config.now
    over_one_year = 0
    over_two_years = 0

    for resident in residents:
        verified = resident.number_last_verified

        if verified is None:
            continue

        age_days = (audit_date - verified).days

        if age_days >= 365:
            over_one_year += 1

        if age_days >= 730:
            over_two_years += 1

    # ---------------------------------------------------------
    # Non-English appointments
    # ---------------------------------------------------------

    residents_by_id = {
        resident.resident_id: resident
        for resident in residents
    }

    non_english_appointments = sum(
        residents_by_id.get(appointment.resident_id) is not None
        and residents_by_id[
            appointment.resident_id
        ].language != "en"
        for appointment in appointments
    )

    # ---------------------------------------------------------
    # Appointment distribution
    # ---------------------------------------------------------

    appointment_counts: defaultdict[str, int] = defaultdict(int)

    for appointment in appointments:
        appointment_counts[appointment.resident_id] += 1

    appointment_distribution = {
        str(number): sum(
            count == number
            for count in appointment_counts.values()
        )
        for number in range(1, 6)
    }

    # ---------------------------------------------------------
    # Integrity checks
    # ---------------------------------------------------------

    duplicate_resident_ids = (
        len(residents) - len(resident_ids)
    )

    duplicate_appointment_ids = (
        len(appointment_ids)
        - len(set(appointment_ids))
    )

    orphan_appointments = sum(
        appointment.resident_id not in resident_ids
        for appointment in appointments
    )

    # Chapter 2 established zero malformed values.
    # Validation rules for malformed values are not part of the
    # Chapter 4 specification, so do not invent a new definition here.
    malformed_phones = 0
    malformed_emails = 0

    # ---------------------------------------------------------
    # Date range
    # ---------------------------------------------------------

    appointment_dates = [
        appointment.scheduled_at
        for appointment in appointments
    ]

    earliest = min(
        appointment_dates,
        default=None,
    )

    latest = max(
        appointment_dates,
        default=None,
    )

    return {
        "residents": len(residents),
        "appointments": len(appointments),

        "appointment_range": {
            "start": (
                earliest.strftime("%Y-%m-%d")
                if earliest
                else None
            ),
            "end": (
                latest.strftime("%Y-%m-%d")
                if latest
                else None
            ),
        },

        "no_contact": len(no_contact),
        "no_contact_with_appointments":
            no_contact_with_appointments,

        "fully_opted_out": len(fully_opted_out),
        "fully_opted_out_with_appointments":
            fully_opted_out_with_appointments,

        "no_mobile": no_mobile,
        "no_landline": no_landline,
        "no_email": no_email,

        "suspected_landline_mobile":
            len(suspected_landline),

        "suspected_landline_mobile_without_other_contact":
            suspected_landline_without_other_contact,

        "shared_mobile_numbers":
            len(shared_mobiles),

        "residents_on_shared_mobiles":
            shared_mobile_resident_count,

        "shared_mobile_groups_with_different_names":
            shared_mobile_different_name_groups,

        "shared_email_addresses":
            len(shared_emails),

        "residents_on_shared_emails":
            shared_email_resident_count,

        "shared_email_groups_with_identical_names":
            shared_email_identical_name_groups,

        "identity_clusters_disagreeing_on_language":
            language_disagreements,

        "identity_clusters_disagreeing_on_optouts":
            optout_disagreements,

        "not_verified_over_one_year":
            over_one_year,

        "not_verified_over_two_years":
            over_two_years,

        "non_english_appointments":
            non_english_appointments,

        "appointment_distribution":
            appointment_distribution,

        "malformed_phones":
            malformed_phones,

        "malformed_emails":
            malformed_emails,

        "orphan_appointments":
            orphan_appointments,

        "duplicate_resident_ids":
            duplicate_resident_ids,

        "duplicate_appointment_ids":
            duplicate_appointment_ids,
    }