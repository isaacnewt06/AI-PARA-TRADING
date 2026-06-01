from src.application.unlock_archives_and_learn import (
    UnlockArchivesAndLearnApplicationService,
    UnlockArchivesAndLearnOptions,
)


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_unlock_archives_and_learn_continues_after_phase_failure(monkeypatch) -> None:
    session = _FakeSession()
    service = UnlockArchivesAndLearnApplicationService(session, settings=None)  # type: ignore[arg-type]

    def ok_phase():
        return {"ok": True}

    def fail_phase():
        raise RuntimeError("boom")

    monkeypatch.setattr(
        service,
        "_summary",
        lambda: {"messages": 1, "files": 2, "chunks": 3, "rules": 4, "strategies": 5},
    )
    monkeypatch.setattr(
        service,
        "run",
        lambda options: {
            "phases": [
                service._run_phase("doctor-archives", ok_phase),
                service._run_phase("inspect-archives", fail_phase),
                service._run_phase("rank-archives", ok_phase),
            ],
            "summary": service._summary(),
        },
    )

    result = service.run(UnlockArchivesAndLearnOptions(channel="https://t.me/tradingcursosgratiss"))

    assert [phase["status"] for phase in result["phases"]] == ["completed", "failed", "completed"]
    assert result["summary"]["rules"] == 4
    assert session.commits == 2
    assert session.rollbacks == 1


def test_unlock_archives_and_learn_includes_download_phase(monkeypatch) -> None:
    session = _FakeSession()
    service = UnlockArchivesAndLearnApplicationService(session, settings=None)  # type: ignore[arg-type]
    observed: list[str] = []

    monkeypatch.setattr(
        service,
        "_run_phase",
        lambda phase_name, runner: observed.append(phase_name) or {"phase": phase_name, "status": "completed"},
    )
    monkeypatch.setattr(
        service,
        "_summary",
        lambda: {"messages": 0, "files": 0, "chunks": 0, "rules": 0, "strategies": 0},
    )

    service.run(UnlockArchivesAndLearnOptions(channel="https://t.me/tradingcursosgratiss"))

    assert observed[:4] == ["doctor-archives", "download-archives", "inspect-archives", "rank-archives"]
