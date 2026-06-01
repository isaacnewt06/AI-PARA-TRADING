from __future__ import annotations

from pathlib import Path

from src.core.config import reload_settings
from src.trading.spread_session_audit import SpreadSessionAudit, SpreadSessionAuditPaths


class _FakeBridge:
    def __init__(self, environments: list[dict]) -> None:
        self.environments = environments
        self.index = 0

    def read_execution_environment(self, *, symbol: str) -> dict:
        item = self.environments[min(self.index, len(self.environments) - 1)]
        self.index += 1
        return item


class _FakeIntelligence:
    def __init__(self, *, hour_ny: int = 9, atr_ratio: float = 1.2, macro_action: str = "allow") -> None:
        self.hour_ny = hour_ny
        self.atr_ratio = atr_ratio
        self.macro_action = macro_action

    def run_detailed(self, *, symbol: str) -> dict:
        return {
            "overview": {
                "market_state": {
                    "hour_ny": self.hour_ny,
                    "atr_ratio": self.atr_ratio,
                    "market_regime": "EXPANSION",
                }
            },
            "event_risk": {
                "action": self.macro_action,
                "highest_active_impact": "none",
                "highest_upcoming_impact": "none",
            },
            "volatility_intelligence": {"state": "expanding_with_force"},
        }


def _settings(tmp_path: Path):
    return reload_settings({"DATA_DIR": str(tmp_path / "data")})


def _sample(*, spread: float, session: str = "ny_am", hour_ny: int = 9) -> dict:
    return {
        "spread": spread,
        "latency": 0.05,
        "slippage_estimated": spread,
        "execution_environment": "SAFE" if spread <= 0.15 else "UNSAFE",
        "session": session,
        "hour_ny": hour_ny,
        "atr_regime": "HIGH",
        "macro_status": "allow",
    }


def test_collect_sample_records_spread_session_atr_and_macro(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(
        _settings(tmp_path),
        bridge=_FakeBridge(
            [
                {
                    "live_spread": 0.12,
                    "live_latency": 0.04,
                    "slippage_estimated": 0.12,
                    "execution_viability": "SAFE",
                }
            ]
        ),
        intelligence_engine=_FakeIntelligence(hour_ny=9, atr_ratio=1.25, macro_action="allow"),
        output_dir=tmp_path / "audit",
    )

    sample = audit.collect_sample(symbol="XAUUSDm")

    assert sample["spread"] == 0.12
    assert sample["latency"] == 0.04
    assert sample["slippage_estimated"] == 0.12
    assert sample["hour_ny"] in range(24)
    assert sample["market_hour_ny"] == 9
    assert sample["atr_regime"] == "HIGH"
    assert sample["macro_status"] == "allow"


def test_summarize_calculates_threshold_percentages_and_windows(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(_settings(tmp_path), output_dir=tmp_path / "audit")
    samples = [
        _sample(spread=0.10, session="ny_am", hour_ny=9),
        _sample(spread=0.14, session="ny_am", hour_ny=9),
        _sample(spread=0.18, session="ny_pm", hour_ny=15),
        _sample(spread=0.30, session="london", hour_ny=4),
    ]

    summary = audit.summarize(samples)

    assert summary["spread_min"] == 0.1
    assert summary["spread_max"] == 0.3
    assert summary["spread_avg"] == 0.18
    assert summary["pct_time_spread_lte_0_15"] == 50.0
    assert summary["pct_time_spread_lte_0_20"] == 75.0
    assert summary["by_session"]["ny_am"]["pct_spread_lte_0_15"] == 100.0
    assert summary["best_execution_windows"][0]["window"] == "9"


def test_conclusion_marks_symbol_apt_with_sustained_tight_spread(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(_settings(tmp_path), output_dir=tmp_path / "audit")
    samples = [_sample(spread=0.12, session="ny_am", hour_ny=9) for _ in range(30)]

    summary = audit.summarize(samples)

    assert summary["conclusion"] == "XAUUSDm APTO"


def test_conclusion_marks_specific_windows_when_only_some_sessions_work(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(_settings(tmp_path), output_dir=tmp_path / "audit")
    samples = [
        *[_sample(spread=0.12, session="ny_am", hour_ny=9) for _ in range(6)],
        *[_sample(spread=0.28, session="london", hour_ny=4) for _ in range(6)],
    ]

    summary = audit.summarize(samples)

    assert summary["conclusion"] == "XAUUSDm APTO SOLO EN VENTANAS ESPECÍFICAS"


def test_conclusion_marks_symbol_not_fit_for_micro_scalping(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(_settings(tmp_path), output_dir=tmp_path / "audit")
    samples = [_sample(spread=0.31, session="new_york_unvalidated", hour_ny=10) for _ in range(10)]

    summary = audit.summarize(samples)

    assert summary["conclusion"] == "XAUUSDm NO APTO PARA SCALPING MICRO EN ESTA CUENTA"


def test_write_report_handles_jsonl_and_invalid_lines(tmp_path: Path) -> None:
    audit = SpreadSessionAudit(_settings(tmp_path), output_dir=tmp_path / "audit")
    paths = SpreadSessionAuditPaths(
        jsonl=tmp_path / "audit" / "run.jsonl",
        csv=tmp_path / "audit" / "run.csv",
        report_md=tmp_path / "audit" / "run.md",
        latest_json=tmp_path / "audit" / "latest.json",
    )
    paths.jsonl.parent.mkdir(parents=True, exist_ok=True)
    audit.append_sample(paths=paths, sample=_sample(spread=0.12))
    with paths.jsonl.open("a", encoding="utf-8") as handle:
        handle.write("{bad-json\n")

    summary = audit.write_report(paths=paths, samples=audit.read_samples(paths.jsonl))

    assert summary["samples"] == 1
    assert paths.report_md.exists()
    assert paths.latest_json.exists()
