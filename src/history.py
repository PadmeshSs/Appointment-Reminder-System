from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class Ledger:
    """Append-only JSONL contact history with indexed queries.

    Contact-window queries are intentionally keyed by resident_id only.
    A shared contact point or channel does not change which resident's
    contact count is being evaluated.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

        self._records: list[dict[str, Any]] = []
        self._by_resident: defaultdict[
            str, list[dict[str, Any]]
        ] = defaultdict(list)
        self._by_appointment: defaultdict[
            str, list[dict[str, Any]]
        ] = defaultdict(list)
        self._by_point: defaultdict[
            str, list[dict[str, Any]]
        ] = defaultdict(list)
        self._by_identity: defaultdict[
            str, list[dict[str, Any]]
        ] = defaultdict(list)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------

    def _load(self) -> None:
        """Load existing JSONL records and rebuild indexes."""
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in {self.path} "
                        f"at line {line_number}"
                    ) from exc

                self._validate_record(record)

                self._records.append(record)
                self._index(record)

    def _append(self, record: dict[str, Any]) -> None:
        """Persist one record, then add it to the in-memory indexes."""
        self._validate_record(record)

        with self.path.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    record,
                    sort_keys=True,
                )
                + "\n"
            )

        self._records.append(record)
        self._index(record)

    def _index(self, record: dict[str, Any]) -> None:
        """Add a record to every index needed by later queries."""

        # Critical Chapter 5 decision:
        #
        # Contact-window queries are keyed by resident_id.
        #
        # The contact point, channel, and appointment do NOT become
        # part of the resident-level rolling-window key.
        self._by_resident[
            record["resident_id"]
        ].append(record)

        appointment_id = record.get("appointment_id")

        if appointment_id:
            self._by_appointment[
                appointment_id
            ].append(record)

        identity_key = record.get("identity_key")

        if identity_key:
            self._by_identity[
                identity_key
            ].append(record)

        # Only attempts have an actual destination point.
        if record["kind"] == "attempt":
            point = record.get("to")

            if point:
                self._by_point[
                    point
                ].append(record)

    @staticmethod
    def _validate_record(
        record: dict[str, Any],
    ) -> None:
        """Validate the minimum structure required by the ledger."""

        kind = record.get("kind")

        if kind not in {
            "attempt",
            "withheld",
        }:
            raise ValueError(
                f"Unknown ledger record kind: {kind!r}"
            )

        required = {
            "attempt": {
                "kind",
                "at",
                "resident_id",
                "identity_key",
                "appointment_id",
                "channel",
                "to",
                "attempt",
                "language",
                "language_fallback",
                "body_hash",
                "status",
                "detail",
                "reach",
                "point_health",
            },
            "withheld": {
                "kind",
                "at",
                "resident_id",
                "identity_key",
                "appointment_id",
                "channel",
                "reason",
                "detail",
            },
        }[kind]

        missing = required - record.keys()

        if missing:
            raise ValueError(
                f"{kind} record missing fields: "
                f"{sorted(missing)}"
            )

        try:
            datetime.fromisoformat(record["at"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid ledger timestamp: "
                f"{record['at']!r}"
            ) from exc

    # ---------------------------------------------------------
    # Append API
    # ---------------------------------------------------------

    def append_attempt(
        self,
        *,
        at: datetime,
        resident_id: str,
        identity_key: str | None,
        appointment_id: str,
        channel: str,
        to: str,
        attempt: int,
        language: str,
        language_fallback: bool,
        body_hash: str,
        status: str,
        detail: str,
        reach: str,
        point_health: str,
    ) -> None:
        """Append one outbound contact attempt."""

        self._append(
            {
                "kind": "attempt",
                "at": at.isoformat(),
                "resident_id": resident_id,
                "identity_key": identity_key,
                "appointment_id": appointment_id,
                "channel": channel,
                "to": to,
                "attempt": attempt,
                "language": language,
                "language_fallback": language_fallback,
                "body_hash": body_hash,
                "status": status,
                "detail": detail,
                "reach": reach,
                "point_health": point_health,
            }
        )

    def append_withheld(
        self,
        *,
        at: datetime,
        resident_id: str,
        identity_key: str | None,
        appointment_id: str,
        channel: str,
        reason: str,
        detail: dict[str, Any],
    ) -> None:
        """Append one withheld-contact decision."""

        self._append(
            {
                "kind": "withheld",
                "at": at.isoformat(),
                "resident_id": resident_id,
                "identity_key": identity_key,
                "appointment_id": appointment_id,
                "channel": channel,
                "reason": reason,
                "detail": detail,
            }
        )

    # ---------------------------------------------------------
    # Basic queries
    # ---------------------------------------------------------

    def attempts_for_resident(
        self,
        resident_id: str,
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in self._by_resident.get(
                resident_id,
                [],
            )
            if record["kind"] == "attempt"
        ]

    def attempts_for_appointment(
        self,
        appointment_id: str,
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in self._by_appointment.get(
                appointment_id,
                [],
            )
            if record["kind"] == "attempt"
        ]

    def attempts_to_point(
        self,
        point: str,
    ) -> list[dict[str, Any]]:
        return list(
            self._by_point.get(
                point,
                [],
            )
        )

    # ---------------------------------------------------------
    # Rolling-window queries
    # ---------------------------------------------------------

    @staticmethod
    def _in_window(
        record: dict[str, Any],
        at: datetime,
        days: int,
    ) -> bool:
        """Check the half-open rolling-window boundary.

        Required definition:

            start < timestamp <= at
        """

        start = at - timedelta(days=days)

        timestamp = datetime.fromisoformat(
            record["at"]
        )

        return start < timestamp <= at

    def contacts_in_window(
        self,
        resident_id: str,
        at: datetime,
        days: int,
    ) -> list[dict[str, Any]]:
        """Return contacts for one resident in a rolling window.

        Critical design decision:

        - keyed by resident_id only
        - shared contact points do not transfer counts
        - channels do not split the count
        - appointments do not split the count
        - failed attempts still count
        - withheld records do not count because no attempt occurred
        """

        return [
            record
            for record in self._by_resident.get(
                resident_id,
                [],
            )
            if (
                record["kind"] == "attempt"
                and self._in_window(
                    record,
                    at,
                    days,
                )
            )
        ]

    def cluster_contacts_in_window(
        self,
        identity_key: str,
        at: datetime,
        days: int,
    ) -> list[dict[str, Any]]:
        """Return contacts belonging to an identity cluster."""

        return [
            record
            for record in self._by_identity.get(
                identity_key,
                [],
            )
            if (
                record["kind"] == "attempt"
                and self._in_window(
                    record,
                    at,
                    days,
                )
            )
        ]

    def contacts_on_day(
        self,
        resident_id: str,
        at: datetime,
    ) -> list[dict[str, Any]]:
        """Return attempts made by a resident on the calendar day."""

        day = at.date()

        return [
            record
            for record in self._by_resident.get(
                resident_id,
                [],
            )
            if (
                record["kind"] == "attempt"
                and datetime.fromisoformat(
                    record["at"]
                ).date() == day
            )
        ]

    def messages_to_point_on_day(
        self,
        point: str,
        at: datetime,
    ) -> list[dict[str, Any]]:
        """Return messages sent to a contact point on the day."""

        day = at.date()

        return [
            record
            for record in self._by_point.get(
                point,
                [],
            )
            if datetime.fromisoformat(
                record["at"]
            ).date() == day
        ]

    # ---------------------------------------------------------
    # Outcome / stopping queries
    # ---------------------------------------------------------

    def point_is_dead(
        self,
        point: str,
        channel: str,
    ) -> bool:
        """Return whether a point has been marked dead."""

        return any(
            record.get("channel") == channel
            and record.get("point_health") == "dead"
            for record in self._by_point.get(
                point,
                [],
            )
        )

    def soft_failures(self, point: str, channel: str) -> int:
        return sum(
            record.get("channel") == channel
            and record.get("point_health") == "soft"
            for record in self._by_point.get(point, [])
        )

    def reached(
        self,
        appointment_id: str,
    ) -> bool:
        """Return whether an appointment reached a human."""

        return any(
            record["reach"] == "reached"
            for record in self._by_appointment.get(
                appointment_id,
                [],
            )
            if record["kind"] == "attempt"
        )

    # ---------------------------------------------------------
    # Retrospective history
    # ---------------------------------------------------------

    def import_prior(
        self,
        path: str | Path,
    ) -> int:
        """Import prior JSONL contact history."""

        source = Path(path)

        if not source.exists():
            raise FileNotFoundError(source)

        imported = 0

        with source.open(
            "r",
            encoding="utf-8",
        ) as file:
            for line_number, line in enumerate(
                file,
                start=1,
            ):
                line = line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in {source} "
                        f"at line {line_number}"
                    ) from exc

                self._append(record)
                imported += 1

        return imported

    @property
    def records(
        self,
    ) -> list[dict[str, Any]]:
        """Return all records in append order."""

        return list(self._records)