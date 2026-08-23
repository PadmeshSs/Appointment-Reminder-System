from datetime import datetime
from pathlib import Path

from src.message import MessageBuilder
from src.models import Appointment, Resident


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def make_resident(language: str) -> Resident:
    return Resident(
        resident_id="RS-TEST",
        name="Test Resident",
        mobile="555-401-2288",
        email="test@example.net",
        language=language,
    )


def make_appointment() -> Appointment:
    return Appointment(
        appointment_id="AP-TEST",
        resident_id="RS-TEST",
        scheduled_at=datetime(
            2026,
            3,
            10,
            10,
            0,
        ),
        location="District Office",
        service_type="Benefits",
    )


def test_english_resident_uses_english_template():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("en"),
        make_appointment(),
    )

    assert message.requested_language == "en"
    assert message.language == "en"
    assert message.fallback is False
    assert "Test Resident" in message.body


def test_spanish_resident_uses_spanish_template():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("es"),
        make_appointment(),
    )

    assert message.requested_language == "es"
    assert message.language == "es"
    assert message.fallback is False
    assert "[PLACEHOLDER - NOT PROFESSIONALLY TRANSLATED]" in (
        message.body
    )


def test_vietnamese_resident_uses_vietnamese_template():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("vi"),
        make_appointment(),
    )

    assert message.requested_language == "vi"
    assert message.language == "vi"
    assert message.fallback is False


def test_somali_resident_falls_back_to_english():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("so"),
        make_appointment(),
    )

    assert message.requested_language == "so"
    assert message.language == "en"
    assert message.fallback is True


def test_russian_resident_falls_back_to_english():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("ru"),
        make_appointment(),
    )

    assert message.requested_language == "ru"
    assert message.language == "en"
    assert message.fallback is True


def test_chinese_resident_falls_back_to_english():
    builder = MessageBuilder(TEMPLATES)

    message = builder.sms(
        make_resident("zh"),
        make_appointment(),
    )

    assert message.requested_language == "zh"
    assert message.language == "en"
    assert message.fallback is True


def test_all_required_placeholders_are_rendered():
    builder = MessageBuilder(TEMPLATES)

    appointment = make_appointment()

    message = builder.sms(
        make_resident("en"),
        appointment,
    )

    assert "Test Resident" in message.body
    assert "Benefits" in message.body
    assert "2026-03-10" in message.body
    assert "10:00" in message.body
    assert "District Office" in message.body

    assert "{name}" not in message.body
    assert "{service_type}" not in message.body
    assert "{date}" not in message.body
    assert "{time}" not in message.body
    assert "{location}" not in message.body


def test_body_hash_is_stable():
    builder = MessageBuilder(TEMPLATES)

    message_one = builder.sms(
        make_resident("en"),
        make_appointment(),
    )

    message_two = builder.sms(
        make_resident("en"),
        make_appointment(),
    )

    assert message_one.body_hash == message_two.body_hash


def test_different_residents_produce_different_body_hashes():
    builder = MessageBuilder(TEMPLATES)

    appointment = make_appointment()

    first = builder.sms(
        make_resident("en"),
        appointment,
    )

    second = builder.sms(
        Resident(
            resident_id="RS-OTHER",
            name="Other Resident",
            mobile="555-401-2288",
            email="other@example.net",
            language="en",
        ),
        appointment,
    )

    assert first.body != second.body
    assert first.body_hash != second.body_hash


def test_available_languages_are_only_shipped_templates():
    builder = MessageBuilder(TEMPLATES)

    assert builder.available_languages() == (
        "en",
        "es",
        "vi",
    )