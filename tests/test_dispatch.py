from src.dispatch import interpret
from src.models import Channel, PointHealth, Reach


def test_sms_delivered_is_delivered_not_reached():
    outcome = interpret(
        Channel.SMS,
        "delivered",
        "",
    )

    assert outcome.reach is Reach.DELIVERED
    assert outcome.point_health is PointHealth.OK


def test_sms_accepted_by_carrier_is_unverifiable():
    outcome = interpret(
        Channel.SMS,
        "delivered",
        "accepted_by_carrier",
    )

    assert outcome.reach is Reach.UNVERIFIABLE
    assert outcome.point_health is PointHealth.WRONG_CHANNEL


def test_sms_unroutable_landline_is_failed():
    outcome = interpret(
        Channel.SMS,
        "failed",
        "unroutable_landline",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.WRONG_CHANNEL


def test_sms_carrier_rejected_is_soft_failure():
    outcome = interpret(
        Channel.SMS,
        "failed",
        "carrier_rejected",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.SOFT


def test_sms_unknown_subscriber_is_dead():
    outcome = interpret(
        Channel.SMS,
        "failed",
        "unknown_subscriber",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.DEAD


def test_voice_human_is_reached():
    outcome = interpret(
        Channel.VOICE,
        "answered",
        "human",
    )

    assert outcome.reach is Reach.REACHED
    assert outcome.point_health is PointHealth.OK


def test_voice_voicemail_is_delivered_not_reached():
    outcome = interpret(
        Channel.VOICE,
        "answered",
        "voicemail_left",
    )

    assert outcome.reach is Reach.DELIVERED
    assert outcome.point_health is PointHealth.OK


def test_voice_busy_is_soft_failure():
    outcome = interpret(
        Channel.VOICE,
        "no_answer",
        "busy",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.SOFT


def test_voice_unobtainable_number_is_dead():
    outcome = interpret(
        Channel.VOICE,
        "failed",
        "number_unobtainable",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.DEAD


def test_email_delivered_is_delivered_not_reached():
    outcome = interpret(
        Channel.EMAIL,
        "delivered",
        "",
    )

    assert outcome.reach is Reach.DELIVERED
    assert outcome.point_health is PointHealth.OK


def test_email_spam_is_unverifiable():
    outcome = interpret(
        Channel.EMAIL,
        "delivered",
        "placed_in_spam",
    )

    assert outcome.reach is Reach.UNVERIFIABLE
    assert outcome.point_health is PointHealth.SOFT


def test_email_soft_bounce_is_soft_failure():
    outcome = interpret(
        Channel.EMAIL,
        "failed",
        "soft_bounce",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.SOFT


def test_email_hard_bounce_is_dead():
    outcome = interpret(
        Channel.EMAIL,
        "failed",
        "hard_bounce",
    )

    assert outcome.reach is Reach.FAILED
    assert outcome.point_health is PointHealth.DEAD


def test_unknown_outcome_is_never_optimistic():
    outcome = interpret(
        Channel.SMS,
        "new_status_from_future_carrier",
        "something_unrecognised",
    )

    assert outcome.reach is Reach.UNVERIFIABLE
    assert outcome.point_health is PointHealth.SOFT