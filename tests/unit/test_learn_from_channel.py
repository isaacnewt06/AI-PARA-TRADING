from src.application.learn_from_channel import LearnFromChannelApplicationService, LearnFromChannelOptions


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_learn_from_channel_continues_after_phase_failure(monkeypatch) -> None:
    session = _FakeSession()
    service = LearnFromChannelApplicationService(session, settings=None, ingestion_service=None)  # type: ignore[arg-type]

    def ok_phase() -> dict:
        return {"ok": True}

    def fail_phase() -> dict:
        raise RuntimeError("phase exploded")

    monkeypatch.setattr(
        service,
        "_build_phases",
        lambda options: [
            ("phase-a", ok_phase),
            ("phase-b", fail_phase),
            ("phase-c", ok_phase),
        ],
    )
    monkeypatch.setattr(service, "_summary", lambda: {"messages": 1, "files": 2, "chunks": 3, "rules": 4, "strategies": 5})

    result = service.run(LearnFromChannelOptions(channel="https://t.me/tradingcursosgratiss"))

    assert [phase["status"] for phase in result["phases"]] == ["completed", "failed", "completed"]
    assert result["summary"]["strategies"] == 5
    assert session.commits == 2
    assert session.rollbacks == 1
