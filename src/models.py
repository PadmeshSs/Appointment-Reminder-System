from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Channel(Enum):
    """Communication channels supported by the reminder system."""

    SMS = "sms"
    VOICE = "voice"
    EMAIL = "email"


class Reach(Enum):
    """
    Evidence level for whether a reminder actually reached a person.

    REACHED:
        Positive evidence that a person engaged.

    DELIVERED:
        The network accepted/took the message, but human engagement
        is unknown.

    UNVERIFIABLE:
        The channel reported success, but there is reason to doubt
        that the message actually reached a usable recipient.

    FAILED:
        The message did not arrive.
    """

    REACHED = "reached"
    DELIVERED = "delivered"
    UNVERIFIABLE = "unverifiable"
    FAILED = "failed"


class PointHealth(Enum):
    """Current health classification of a contact point."""

    OK = "ok"
    SOFT = "soft"
    DEAD = "dead"
    WRONG_CHANNEL = "wrong_channel"


@dataclass(frozen=True)
class Resident:
    """A resident and the contact details recorded for them."""

    resident_id: str
    name: str

    mobile: Optional[str] = None
    landline: Optional[str] = None
    email: Optional[str] = None

    language: str = "en"

    sms_optout: bool = False
    voice_optout: bool = False
    email_optout: bool = False

    number_last_verified: Optional[datetime] = None
    
    suspected_landline_mobile: bool = False
    identity_key: Optional[str] = None

    def opted_out_of(self, channel: Channel) -> bool:
        """Return whether the resident opted out of the given channel."""

        if channel is Channel.SMS:
            return self.sms_optout

        if channel is Channel.VOICE:
            return self.voice_optout

        if channel is Channel.EMAIL:
            return self.email_optout

        raise ValueError(f"Unsupported channel: {channel}")

    def point_for(self, channel: Channel) -> Optional[str]:
        """
        Return the contact point appropriate for a channel.

        SMS:
            Mobile only. Never falls back to landline.

        Voice:
            Mobile first, then landline.

        Email:
            Email only.
        """

        if channel is Channel.SMS:
            return self.mobile

        if channel is Channel.VOICE:
            return self.mobile or self.landline

        if channel is Channel.EMAIL:
            return self.email

        raise ValueError(f"Unsupported channel: {channel}")


@dataclass(frozen=True)
class Appointment:
    """A scheduled appointment belonging to a resident."""

    appointment_id: str
    resident_id: str
    scheduled_at: datetime
    location: str
    service_type: str
    status: str = "Booked"


@dataclass(frozen=True)
class Decision:
    """
    Result of a policy evaluation.

    An allowed decision has no blocking reason.
    A blocked decision records the reason responsible for withholding contact.
    """

    allowed: bool
    reason: Optional[str] = None
    detail: Optional[str] = None

    @classmethod
    def allow(cls) -> "Decision":
        """Create an allowed decision."""

        return cls(allowed=True)

    @classmethod
    def block(
        cls,
        reason: str,
        detail: Optional[str] = None,
    ) -> "Decision":
        """Create a blocked decision."""

        return cls(
            allowed=False,
            reason=reason,
            detail=detail,
        )


@dataclass(frozen=True)
class Outcome:
    """Interpretation of a channel's raw response."""

    channel: Channel
    status: str
    detail: str
    reach: Reach
    point_health: PointHealth