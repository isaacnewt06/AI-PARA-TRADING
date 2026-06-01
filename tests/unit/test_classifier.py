from src.processing.classifier import HeuristicContentClassifier


def test_signal_message_is_classified() -> None:
    classifier = HeuristicContentClassifier()
    result = classifier.classify("BUY XAUUSD entry 2320 sl 2310 tp 2340")
    assert result.label == "signal"
