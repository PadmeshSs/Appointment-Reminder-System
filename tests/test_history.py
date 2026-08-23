from datetime import datetime
import json

from src.history import Ledger


def append_attempt(
    ledger: Ledger,
    *,
    resident_id: str = "RS-001",
    identity_key: str | None = None,
    appointment_id: str = "A-001",
    channel: str = "sms",
    to: str = "555-111-1111",
    at: datetime = datetime(
        2026,
        3,
        5,
        10,
        0,
    ),
    attempt: int = 1,
    reach: str = "delivered",
    point_health: str = "ok",
) -> None:
    ledger.append_attempt(
        at=at,
        resident_id=resident_id,
        identity_key=identity_key,
        appointment_id=appointment_id,
        channel=channel,
        to=to,
        attempt=attempt,
        language="en",
        language_fallback=False,
        body_hash=f"hash-{appointment_id}-{attempt}",
        status="delivered",
        detail="",
        reach=reach,
        point_health=point_health,
    )


def test_contacts_in_window_is_keyed_only_by_resident_id(
    tmp_path,
):
    """A shared point must not transfer one resident's count."""

    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-001",
        to="555-999-9999",
    )

    at = datetime(
        2026,
        3,
        6,
        10,
        0,
    )

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            at,
            7,
        )
    ) == 1

    assert len(
        ledger.contacts_in_window(
            "RS-002",
            at,
            7,
        )
    ) == 0


def test_contacts_in_window_counts_across_channels(
    tmp_path,
):
    """The resident count is not split by channel."""

    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-SMS",
        channel="sms",
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-VOICE",
        channel="voice",
        at=datetime(
            2026,
            3,
            6,
            10,
            0,
        ),
    )

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            datetime(
                2026,
                3,
                7,
                10,
                0,
            ),
            7,
        )
    ) == 2


def test_shared_point_does_not_count_for_both_residents(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    shared_point = "555-999-9999"

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-001",
        to=shared_point,
    )

    at = datetime(
        2026,
        3,
        6,
        10,
        0,
    )

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            at,
            7,
        )
    ) == 1

    assert len(
        ledger.contacts_in_window(
            "RS-002",
            at,
            7,
        )
    ) == 0


def test_failed_attempt_counts_as_contact(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    append_attempt(
        ledger,
        reach="failed",
        point_health="soft",
    )

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            datetime(
                2026,
                3,
                6,
                10,
                0,
            ),
            7,
        )
    ) == 1


def test_withheld_does_not_count_as_contact(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    ledger.append_withheld(
        at=datetime(
            2026,
            3,
            5,
            10,
            0,
        ),
        resident_id="RS-001",
        identity_key=None,
        appointment_id="A-001",
        channel="sms",
        reason="rolling_contact_limit",
        detail={"counted": 2},
    )

    assert ledger.contacts_in_window(
        "RS-001",
        datetime(
            2026,
            3,
            6,
            10,
            0,
        ),
        7,
    ) == []


def test_window_start_is_exclusive_and_end_is_inclusive(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    at = datetime(
        2026,
        3,
        10,
        10,
        0,
    )

    append_attempt(
        ledger,
        appointment_id="A-START",
        at=datetime(
            2026,
            3,
            3,
            10,
            0,
        ),
    )

    append_attempt(
        ledger,
        appointment_id="A-AFTER",
        at=datetime(
            2026,
            3,
            3,
            10,
            0,
            1,
        ),
    )

    append_attempt(
        ledger,
        appointment_id="A-END",
        at=at,
    )

    contacts = ledger.contacts_in_window(
        "RS-001",
        at,
        7,
    )

    assert [
        record["appointment_id"]
        for record in contacts
    ] == [
        "A-AFTER",
        "A-END",
    ]


def test_append_reload_preserves_resident_window_count(
    tmp_path,
):
    path = tmp_path / "history.jsonl"

    ledger = Ledger(path)

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-001",
        at=datetime(
            2026,
            3,
            5,
            10,
            0,
        ),
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-002",
        channel="voice",
        at=datetime(
            2026,
            3,
            7,
            10,
            0,
        ),
    )

    ledger = Ledger(path)

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            datetime(
                2026,
                3,
                8,
                10,
                0,
            ),
            7,
        )
    ) == 2


def test_identity_cluster_query_is_separate_from_resident_query(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    identity_key = (
        "person@example.net|same person"
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        identity_key=identity_key,
        appointment_id="A-001",
    )

    append_attempt(
        ledger,
        resident_id="RS-002",
        identity_key=identity_key,
        appointment_id="A-002",
        at=datetime(
            2026,
            3,
            6,
            10,
            0,
        ),
    )

    at = datetime(
        2026,
        3,
        7,
        10,
        0,
    )

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            at,
            7,
        )
    ) == 1

    assert len(
        ledger.contacts_in_window(
            "RS-002",
            at,
            7,
        )
    ) == 1

    assert len(
        ledger.cluster_contacts_in_window(
            identity_key,
            at,
            7,
        )
    ) == 2


def test_import_prior_updates_resident_index(
    tmp_path,
):
    target = tmp_path / "history.jsonl"
    prior = tmp_path / "prior.jsonl"

    record = {
        "kind": "attempt",
        "at": "2026-03-01T10:00:00",
        "resident_id": "RS-001",
        "identity_key": None,
        "appointment_id": "A-PRIOR",
        "channel": "sms",
        "to": "555-111-1111",
        "attempt": 1,
        "language": "en",
        "language_fallback": False,
        "body_hash": "prior",
        "status": "failed",
        "detail": "carrier_rejected",
        "reach": "failed",
        "point_health": "soft",
    }

    prior.write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )

    ledger = Ledger(target)

    assert ledger.import_prior(prior) == 1

    assert len(
        ledger.contacts_in_window(
            "RS-001",
            datetime(
                2026,
                3,
                2,
                10,
                0,
            ),
            7,
        )
    ) == 1


def test_basic_indexes_are_populated_on_write(
    tmp_path,
):
    ledger = Ledger(
        tmp_path / "history.jsonl"
    )

    append_attempt(
        ledger,
        resident_id="RS-001",
        appointment_id="A-001",
        to="555-999-9999",
    )

    assert len(
        ledger.attempts_for_resident(
            "RS-001"
        )
    ) == 1

    assert len(
        ledger.attempts_for_appointment(
            "A-001"
        )
    ) == 1

    assert len(
        ledger.attempts_to_point(
            "555-999-9999"
        )
    ) == 1