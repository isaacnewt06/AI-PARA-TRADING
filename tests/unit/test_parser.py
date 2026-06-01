from types import SimpleNamespace

from src.telegram.parsers import TelegramMessageParser


def test_supported_document_filename_detection() -> None:
    assert TelegramMessageParser.is_supported_document_filename("plan.pdf") is True
    assert TelegramMessageParser.is_supported_document_filename("notes.docx") is True
    assert TelegramMessageParser.is_supported_document_filename("archive.zip") is False


def test_detect_message_content_type_classifies_document_video_by_mime_and_extension() -> None:
    message = SimpleNamespace(
        video=False,
        audio=False,
        voice=False,
        photo=False,
        document=True,
        file=SimpleNamespace(mime_type="video/mp4", ext=".mp4"),
    )

    assert TelegramMessageParser.detect_message_content_type(message) == "video"


def test_detect_message_content_type_classifies_document_text_payloads_as_document() -> None:
    message = SimpleNamespace(
        video=False,
        audio=False,
        voice=False,
        photo=False,
        document=True,
        file=SimpleNamespace(mime_type="text/plain", ext=".txt"),
    )

    assert TelegramMessageParser.detect_message_content_type(message) == "document"
