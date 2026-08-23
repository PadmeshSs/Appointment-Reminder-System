import re
import csv
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path


# Initial setup
ROOT = Path(__file__).resolve().parent.parent
CONTACTS_FILE = ROOT / "data" / "contacts.csv"
APPOINTMENTS_FILE = ROOT / "data" / "appointments.csv"


# ---------------------------------------------------------
# helpers

def load_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean(value):
    if value is None:
        return ""
    return value.strip()

def normalise_email(email):
    return clean(email).lower()


def normalise_name(name):
    return " ".join(clean(name).lower().split())


def parse_datetime(value):
    return datetime.strptime(clean(value), "%Y-%m-%d %H:%M")

def parse_date(value):
    return datetime.strptime(clean(value), "%Y-%m-%d")


def is_non_empty(value):
    return bool(clean(value))


def print_section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------
# Load Data

contacts = load_csv(CONTACTS_FILE)

appointments = load_csv(APPOINTMENTS_FILE)

print_section("Data Loaded")

print(f"Contacts: {len(contacts)}")

print(f"Appointments: {len(appointments)}")


# ---------------------------------------------------------
# resident appointment lookup

appointments_by_resident = defaultdict(list)

for entry in appointments:
    resident_id = clean(entry["resident_id"])
    appointments_by_resident[resident_id].append(entry)


# ---------------------------------------------------------
# 1. Resident with no contacts

print_section("1. Residents with No Contacts")

no_contact = []

for resident in contacts:
    mobile = clean(resident["mobile"])
    email = normalise_email(resident["email"])
    landline = clean(resident["landline"])
    if not mobile and not email and not landline:
        no_contact.append(resident)

no_contact_with_appointments = [
    r for r in no_contact
    if clean(r["resident_id"]) in appointments_by_resident
]

print(f"Residents with no contact details : {len(no_contact)}")
print(f"Of those, with appointments       : {len(no_contact_with_appointments)}")


# ---------------------------------------------------------
# 2. Resident opted out of every contact

print_section("2. OPTED OUT OF EVERY CHANNEL")

OPT_OUT_COLUMNS = [
    "sms_optout",
    "voice_optout",
    "email_optout",
]

TRUE_VALUE = 'y'

def is_opted_out(value):
    return clean(value).lower()  == TRUE_VALUE

all_opted_out = []

for resident in contacts:
    if all(
        is_opted_out(resident.get(column, ""))
        for column in OPT_OUT_COLUMNS
    ):
        all_opted_out.append(resident)


all_opted_out_with_appointments = [
    r for r in all_opted_out
    if clean(r["resident_id"]) in appointments_by_resident
]

print(f"Opted out of all channels : {len(all_opted_out)}")
print(
    f"Of those, with appointments : "
    f"{len(all_opted_out_with_appointments)}"
)


# ---------------------------------------------------------
# 3. Missing individual contact types

print_section("3. MISSING CONTACT TYPES")

missing_mobile = [
    r for r in contacts
    if not is_non_empty(r.get("mobile"))
]

missing_landline = [
    r for r in contacts
    if not is_non_empty(r.get("landline"))
]

missing_email = [
    r for r in contacts
    if not is_non_empty(r.get("email"))
]

print(f"No mobile   : {len(missing_mobile)}")
print(f"No landline : {len(missing_landline)}")
print(f"No email    : {len(missing_email)}")


# ---------------------------------------------------------
# 4. Shared mobile numbers

print_section("4. SHARED CONTACT POINTS")

mobile_to_residents = defaultdict(list)
email_to_residents = defaultdict(list)
landline_to_residents = defaultdict(list)

for resident in contacts:
    resident_id = clean(resident["resident_id"])
    name = clean(resident.get("name"))

    mobile = clean(resident.get("mobile"))
    email = normalise_email(resident.get("email"))
    landline = clean(resident.get("landline"))

    if mobile:
        mobile_to_residents[mobile].append((resident_id, name))

    if email:
        email_to_residents[email].append((resident_id, name))

    if landline:
        landline_to_residents[landline].append((resident_id, name))


shared_mobiles = {
    number: people
    for number, people in mobile_to_residents.items()
    if len(people) > 1
}

shared_emails = {
    email: people
    for email, people in email_to_residents.items()
    if len(people) > 1
}


print(f"Shared mobile numbers : {len(shared_mobiles)}")
print(
    "Residents using those mobiles : "
    f"{sum(len(x) for x in shared_mobiles.values())}"
)

different_name_mobile_clusters = 0

for number, people in shared_mobiles.items():
    names = {
        normalise_name(name)
        for _, name in people
    }

    if len(names) > 1:
        different_name_mobile_clusters += 1

print(
    "Shared mobile clusters with differing names : "
    f"{different_name_mobile_clusters}"
)


print()
print(f"Shared email addresses : {len(shared_emails)}")
print(
    "Residents using those emails : "
    f"{sum(len(x) for x in shared_emails.values())}"
)

identical_name_email_clusters = 0

for email, people in shared_emails.items():
    names = {
        normalise_name(name)
        for _, name in people
    }

    if len(names) == 1:
        identical_name_email_clusters += 1

print(
    "Shared email clusters with identical names : "
    f"{identical_name_email_clusters}"
)


# ---------------------------------------------------------
# 5. Language disagreements in duplicate-name clusters

print_section("5. DUPLICATE-NAME CLUSTERS")

name_groups = defaultdict(list)

for resident in contacts:
    email = normalise_email(resident.get("email"))
    name = normalise_name(resident.get("name"))
    if email and name:
        name_groups[(email, name)].append(resident)


duplicate_name_clusters = {
    name: people
    for name, people in name_groups.items()
    if len(people) > 1
}

language_disagreement_clusters = []

for name, people in duplicate_name_clusters.items():
    languages = {
        clean(person.get("language")).lower()
        for person in people
        if clean(person.get("language"))
    }

    if len(languages) > 1:
        language_disagreement_clusters.append(
            (name, people, languages)
        )

print(
    "Duplicate-name clusters disagreeing on language : "
    f"{len(language_disagreement_clusters)}"
)


# ---------------------------------------------------------
# 6. Duplicate-name clusters disagreeing on opt-outs

opt_out_disagreement_clusters = []

for name, people in duplicate_name_clusters.items():
    opt_out_profiles = set()
    for person in people:
        profile = tuple(
            is_opted_out(person.get(column, ""))
            for column in OPT_OUT_COLUMNS
        )
        opt_out_profiles.add(profile)

    if len(opt_out_profiles) > 1:
        opt_out_disagreement_clusters.append(
            (name, people, opt_out_profiles)
        )

print(
    "Duplicate-name clusters disagreeing on opt-outs : "
    f"{len(opt_out_disagreement_clusters)}"
)


# ---------------------------------------------------------
# 7. Landline-looking numbers in mobile column

print_section("6. MOBILE NUMBERS THAT LOOK LIKE LANDLINES")

# We DO NOT know the mock's hidden landline rule.
# Instead, infer prefixes from numbers that explicitly occur
# in the landline column.

def extract_exchange(number):
    """
    Extract the 3-digit exchange from a US-style phone number.

    Examples:
        (555) 234-1234 -> 234
        555-234-1234   -> 234
    """

    digits = re.sub(r"\D", "", number)

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        return None

    return int(digits[3:6])

landline_prefixes = set()

for resident in contacts:
    landline = clean(resident.get("landline"))

    if landline:
        exchange = extract_exchange(landline)

        if exchange is not None:
            landline_prefixes.add(exchange)


suspected_landline_mobiles = []

for resident in contacts:
    mobile = clean(resident.get("mobile"))

    if not mobile:
        continue

    exchange = extract_exchange(mobile)

    if exchange in landline_prefixes:
        suspected_landline_mobiles.append(
            (resident, exchange)
        )


print(
    "Distinct exchange prefixes observed in landline column : "
    f"{len(landline_prefixes)}"
)

print(
    "Mobile-column numbers matching those prefixes : "
    f"{len(suspected_landline_mobiles)}"
)

no_other_contact = []

for resident, exchange in suspected_landline_mobiles:
    mobile = clean(resident.get("mobile"))
    landline = clean(resident.get("landline"))
    email = clean(resident.get("email"))

    if not landline and not email:
        no_other_contact.append(resident)


print(
    "Suspected landline mobiles with no other contact point : "
    f"{len(no_other_contact)}"
)


# ---------------------------------------------------------
# 8. Verification-date staleness

print_section("7. VERIFICATION DATE STALENESS")

# Use the latest appointment date as the observation/reference
# date rather than today's date. This keeps the analysis tied
# to the dataset.

appointment_dates = [
    parse_datetime(a["scheduled_at"])
    for a in appointments
    if clean(a.get("scheduled_at"))
]

latest_appointment = min(appointment_dates)

print(
    "Latest appointment date used as reference : "
    f"{latest_appointment:%Y-%m-%d}"
)

verification_dates = []

for resident in contacts:
    value = clean(resident.get("number_last_verified"))

    if not value:
        continue

    try:
        verification_dates.append(
            parse_date(value)
        )
    except ValueError:
        print(
            f"WARNING: could not parse verified_at "
            f"for {resident['resident_id']}: {value}"
        )


over_one_year = 0
over_two_years = 0

for verified in verification_dates:
    age_days = (latest_appointment - verified).days

    if age_days > 365:
        over_one_year += 1

    if age_days > 730:
        over_two_years += 1


print(f"Verification dates available : {len(verification_dates)}")
print(f"Not verified in over 1 year  : {over_one_year}")
print(f"Not verified in over 2 years : {over_two_years}")

print()
print(
    "Interpretation: an old verification date indicates "
    "staleness/uncertainty; it does NOT prove that the "
    "contact point is invalid."
)


# ---------------------------------------------------------
# 9. Appointment date range

print_section("8. APPOINTMENT DATE RANGE")

earliest = min(appointment_dates)
latest = max(appointment_dates)

print(f"Earliest appointment : {earliest:%Y-%m-%d}")
print(f"Latest appointment   : {latest:%Y-%m-%d}")


# ---------------------------------------------------------
# 10. Appointments per resident

print_section("9. APPOINTMENTS PER RESIDENT")

appointment_counts = Counter(
    len(value)
    for value in appointments_by_resident.values()
)

for count in sorted(appointment_counts):
    print(
        f"Residents with {count} appointment(s): "
        f"{appointment_counts[count]}"
    )


# ---------------------------------------------------------
# 11. Language distribution

print_section("10. LANGUAGE DISTRIBUTION")

language_counts = Counter(
    clean(r.get("language")).lower()
    for r in contacts
    if clean(r.get("language"))
)

for language, count in sorted(language_counts.items()):
    print(f"{language}: {count}")


non_english_ids = {
    clean(r["resident_id"])
    for r in contacts
    if clean(r.get("language")).lower() not in {"", "en"}
}

non_english_appointments = [
    a for a in appointments
    if clean(a["resident_id"]) in non_english_ids
]

print()
print(
    "Appointments belonging to non-English residents : "
    f"{len(non_english_appointments)}"
)


# ---------------------------------------------------------
# 12. Data integrity checks-

print_section("11. DATA INTEGRITY")

resident_ids = [
    clean(r["resident_id"])
    for r in contacts
]

appointment_resident_ids = {
    clean(a["resident_id"])
    for a in appointments
}

duplicate_resident_ids = [
    resident_id
    for resident_id, count in Counter(resident_ids).items()
    if count > 1
]

orphan_appointments = [
    a
    for a in appointments
    if clean(a["resident_id"]) not in set(resident_ids)
]


def valid_phone(phone):
    digits = re.sub(r"\D", "", clean(phone))

    if not digits:
        return True

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return len(digits) == 10


def valid_email(email):
    email = clean(email)

    if not email:
        return True

    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email
        )
    )


malformed_phones = []

for resident in contacts:
    for column in ("mobile", "landline"):
        value = resident.get(column)

        if value and not valid_phone(value):
            malformed_phones.append(
                (resident["resident_id"], column, value)
            )


malformed_emails = []

for resident in contacts:
    email = resident.get("email")

    if email and not valid_email(email):
        malformed_emails.append(
            (resident["resident_id"], email)
        )


print(f"Duplicate resident IDs : {len(duplicate_resident_ids)}")
print(f"Orphan appointments     : {len(orphan_appointments)}")
print(f"Malformed phones        : {len(malformed_phones)}")
print(f"Malformed emails        : {len(malformed_emails)}")


# ---------------------------------------------------------
# 13. Final summary


print_section("SUMMARY")

print(f"Residents                         : {len(contacts)}")
print(f"Appointments                      : {len(appointments)}")
print(f"No contact details                : {len(no_contact)}")
print(f"Opted out of everything           : {len(all_opted_out)}")
print(f"Missing mobile                    : {len(missing_mobile)}")
print(f"Missing landline                  : {len(missing_landline)}")
print(f"Missing email                     : {len(missing_email)}")
print(f"Shared mobile numbers             : {len(shared_mobiles)}")
print(f"Shared email addresses            : {len(shared_emails)}")
print(f"Suspected landline mobiles        : {len(suspected_landline_mobiles)}")
print(f"Stale >1 year                     : {over_one_year}")
print(f"Stale >2 years                    : {over_two_years}")
print(
    f"Appointment range                 : "
    f"{earliest:%Y-%m-%d} -> {latest:%Y-%m-%d}"
)
print(f"Non-English appointments          : {len(non_english_appointments)}")
print(f"Duplicate resident IDs            : {len(duplicate_resident_ids)}")
print(f"Orphan appointments               : {len(orphan_appointments)}")
print(f"Malformed phones                  : {len(malformed_phones)}")
print(f"Malformed emails                  : {len(malformed_emails)}")
