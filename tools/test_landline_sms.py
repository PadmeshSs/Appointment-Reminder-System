from datetime import datetime
import sys
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------
# Configuration

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from channels.channels import send_sms

TEST_NUMBER = "555-214-9004"

MESSAGE = "Your appointment reminder."

START_TIME = datetime(2026, 3, 2, 10, 0)


# ---------------------------------------------------------
# Experiment

print("=" * 70)
print("LANDLINE SMS EXPERIMENT")
print("=" * 70)

print(f"Number : {TEST_NUMBER}")
print(f"Message: {MESSAGE}")
print(f"Time   : {START_TIME}")
print()


results = []

for attempt in range(1, 6):

    result = send_sms(
        TEST_NUMBER,
        MESSAGE,
        at=START_TIME,
        attempt=attempt,
    )

    results.append(result)

    print(f"Attempt {attempt}")
    print(f"  status : {result['status']}")
    print(f"  detail : {result.get('detail', '')}")
    print()


# ---------------------------------------------------------
# Analyse the results

print("=" * 70)
print("RESULT ANALYSIS")
print("=" * 70)

delivered = sum(
    1
    for result in results
    if result["status"] == "delivered"
)

accepted_by_carrier = sum(
    1
    for result in results
    if result.get("detail") == "accepted_by_carrier"
)

failed = sum(
    1
    for result in results
    if result["status"] == "failed"
)

print(f"Delivered responses        : {delivered}")
print(f"Accepted by carrier        : {accepted_by_carrier}")
print(f"Failed responses           : {failed}")
print()


# ---------------------------------------------------------
# Interpretation

print("=" * 70)
print("INTERPRETATION")
print("=" * 70)

if accepted_by_carrier > 0:
    print(
        "WARNING: The mock reported accepted_by_carrier."
    )

    print(
        "This means the SMS was accepted by the carrier "
        "but the destination is a landline."
    )

    print(
        "Therefore 'delivered' cannot be treated as proof "
        "that the resident received the message."
    )

if delivered > 0:
    print()
    print(
        "IMPORTANT: At least one landline SMS was reported "
        "as 'delivered'."
    )

    print(
        "This demonstrates that the channel's 'delivered' "
        "status is not sufficient evidence of reach."
    )

print()
print(
    "Conclusion: A landline must not be treated as a "
    "successful SMS destination merely because the mock "
    "reports 'delivered'."
)