from __future__ import annotations

import importlib
import os
from pathlib import Path

from .config import Config
from .models import Channel, Outcome, PointHealth, Reach
from .policy import Authorization, verify


def _load_channels(cfg: Config):
    """
    Load the supplied channel mock with an explicit outbox location.

    The environment variable must be set before importing the module.
    """

    outbox_path = Path(cfg.runtime_dir) / "outbox.jsonl"
    outbox_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.environ["OUTBOX_PATH"] = str(outbox_path)

    import channels.channels as channels_module

    return importlib.reload(channels_module)


def interpret(
    channel: Channel,
    status: str,
    detail: str,
) -> Outcome:
    """
    Interpret the raw channel result conservatively.

    `delivered` is not `reached`.
    Only voice + answered + human provides positive evidence
    of human engagement.
    """

    # ---------------------------------------------------------
    # SMS
    # ---------------------------------------------------------

    if channel is Channel.SMS:
        if status == "delivered" and detail == "":
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.DELIVERED,
                point_health=PointHealth.OK,
            )

        if (
            status == "delivered"
            and detail == "accepted_by_carrier"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.UNVERIFIABLE,
                point_health=PointHealth.WRONG_CHANNEL,
            )

        if (
            status == "failed"
            and detail == "unroutable_landline"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.WRONG_CHANNEL,
            )

        if (
            status == "failed"
            and detail == "carrier_rejected"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.SOFT,
            )

        if (
            status == "failed"
            and detail == "unknown_subscriber"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.DEAD,
            )

    # ---------------------------------------------------------
    # Voice
    # ---------------------------------------------------------

    if channel is Channel.VOICE:
        if (
            status == "answered"
            and detail == "human"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.REACHED,
                point_health=PointHealth.OK,
            )

        if (
            status == "answered"
            and detail == "voicemail_left"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.DELIVERED,
                point_health=PointHealth.OK,
            )

        if (
            status == "no_answer"
            and detail in {"", "busy"}
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.SOFT,
            )

        if (
            status == "failed"
            and detail == "number_unobtainable"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.DEAD,
            )

    # ---------------------------------------------------------
    # Email
    # ---------------------------------------------------------

    if channel is Channel.EMAIL:
        if (
            status == "delivered"
            and detail == ""
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.DELIVERED,
                point_health=PointHealth.OK,
            )

        if (
            status == "delivered"
            and detail == "placed_in_spam"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.UNVERIFIABLE,
                point_health=PointHealth.SOFT,
            )

        if (
            status == "failed"
            and detail == "soft_bounce"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.SOFT,
            )

        if (
            status == "failed"
            and detail == "hard_bounce"
        ):
            return Outcome(
                channel=channel,
                status=status,
                detail=detail,
                reach=Reach.FAILED,
                point_health=PointHealth.DEAD,
            )

    # ---------------------------------------------------------
    # Unknown outcome
    # ---------------------------------------------------------

    return Outcome(
        channel=channel,
        status=status,
        detail=detail,
        reach=Reach.UNVERIFIABLE,
        point_health=PointHealth.SOFT,
    )


def send(
    cfg: Config,
    auth: Authorization,
    body: str,
) -> Outcome:
    """
    Send exactly the message authorized by policy.

    This function verifies authorization BEFORE importing/touching
    the supplied channel.
    """

    verify(
        auth,
        channel=auth.channel,
        to=auth.to,
        at=auth.at,
    )

    channels = _load_channels(cfg)

    if auth.channel is Channel.SMS:
        raw = channels.send_sms(
            auth.to,
            body,
            at=auth.at,
            attempt=auth.attempt,
        )

    elif auth.channel is Channel.VOICE:
        raw = channels.send_voice(
            auth.to,
            body,
            at=auth.at,
            attempt=auth.attempt,
        )

    elif auth.channel is Channel.EMAIL:
        raw = channels.send_email(
            auth.to,
            body,
            at=auth.at,
            attempt=auth.attempt,
        )

    else:
        raise ValueError(
            f"Unsupported channel: {auth.channel}"
        )

    return interpret(
        channel=auth.channel,
        status=raw.get("status", ""),
        detail=raw.get("detail", ""),
    )