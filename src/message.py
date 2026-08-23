from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import Appointment, Resident


TEMPLATE_KEYS = (
    "sms",
    "voice",
    "email_subject",
    "email",
)


@dataclass(frozen=True)
class Message:
    """
    A fully rendered reminder message.

    `requested_language` is the resident's recorded preference.

    `language` is the language of the template that was actually used.

    `fallback` records whether English had to be used because the
    requested language template was unavailable.
    """

    body: str
    language: str
    requested_language: str
    fallback: bool

    @property
    def body_hash(self) -> str:
        """
        Return a stable SHA-256 hash of the final message body.

        The hash is used by policy to detect duplicate messages
        sent to the same contact point.
        """

        return hashlib.sha256(
            self.body.encode("utf-8")
        ).hexdigest()


class MessageBuilder:
    """
    Loads available templates and renders messages for residents.

    Templates are selected per resident. Missing languages fall back
    to the configured default language.
    """

    def __init__(
        self,
        templates_dir: str | Path,
        default_language: str = "en",
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.default_language = default_language

        self._templates = self._load_templates()

        if self.default_language not in self._templates:
            raise ValueError(
                f"Default language template is missing: "
                f"{self.default_language}"
            )

    def _load_templates(self) -> dict[str, dict[str, str]]:
        """
        Load every JSON template file in the templates directory.

        Only files that exist are loaded. This is intentional:
        missing language files are what activate the fallback path.
        """

        templates: dict[str, dict[str, str]] = {}

        if not self.templates_dir.exists():
            raise FileNotFoundError(
                f"Template directory does not exist: "
                f"{self.templates_dir}"
            )

        for path in sorted(
            self.templates_dir.glob("*.json")
        ):
            language = path.stem.lower()

            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

            self._validate_template(
                language,
                data,
            )

            templates[language] = data

        return templates

    @staticmethod
    def _validate_template(
        language: str,
        template: object,
    ) -> None:
        """
        Validate the shape of a template file.

        Every language must provide exactly the message keys required
        by Chapter 7.
        """

        if not isinstance(template, dict):
            raise ValueError(
                f"Template for {language} must be a JSON object"
            )

        missing = [
            key
            for key in TEMPLATE_KEYS
            if key not in template
        ]

        if missing:
            raise ValueError(
                f"Template for {language} is missing: "
                + ", ".join(missing)
            )

        for key in TEMPLATE_KEYS:
            if not isinstance(template[key], str):
                raise ValueError(
                    f"Template value {language}.{key} "
                    "must be a string"
                )

    def available_languages(self) -> tuple[str, ...]:
        """Return the languages for which templates actually exist."""

        return tuple(
            sorted(self._templates)
        )

    def _select_language(
        self,
        requested_language: str,
    ) -> tuple[str, bool]:
        """
        Select the actual template language.

        Returns:
            (language_used, fallback)
        """

        requested = (
            requested_language.strip().lower()
            if requested_language
            else self.default_language
        )

        if requested in self._templates:
            return requested, False

        return self.default_language, True

    def _context(
        self,
        resident: Resident,
        appointment: Appointment,
    ) -> dict[str, str]:
        """Build the placeholder values for one appointment."""

        return {
            "name": resident.name,
            "service_type": appointment.service_type,
            "date": appointment.scheduled_at.strftime(
                "%Y-%m-%d"
            ),
            "time": appointment.scheduled_at.strftime(
                "%H:%M"
            ),
            "location": appointment.location,
        }

    def render(
        self,
        resident: Resident,
        appointment: Appointment,
        kind: str,
    ) -> Message:
        """
        Render one message for one resident and appointment.

        `kind` must be one of:
            sms
            voice
            email_subject
            email
        """

        if kind not in TEMPLATE_KEYS:
            raise ValueError(
                f"Unsupported message kind: {kind}"
            )

        language, fallback = self._select_language(
            resident.language
        )

        template = self._templates[language][kind]

        body = template.format(
            **self._context(
                resident,
                appointment,
            )
        )

        return Message(
            body=body,
            language=language,
            requested_language=resident.language,
            fallback=fallback,
        )

    def sms(
        self,
        resident: Resident,
        appointment: Appointment,
    ) -> Message:
        """Build an SMS message."""

        return self.render(
            resident,
            appointment,
            "sms",
        )

    def voice(
        self,
        resident: Resident,
        appointment: Appointment,
    ) -> Message:
        """Build a voice message."""

        return self.render(
            resident,
            appointment,
            "voice",
        )

    def email(
        self,
        resident: Resident,
        appointment: Appointment,
    ) -> tuple[Message, Message]:
        """
        Build an email subject and body.

        Returns:
            (subject, body)
        """

        subject = self.render(
            resident,
            appointment,
            "email_subject",
        )

        body = self.render(
            resident,
            appointment,
            "email",
        )

        return subject, body