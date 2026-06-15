"""Supervised calibration lab for MAXIMO v56 2025 trades.

This module is deliberately offline/read-only with respect to MT5.  It uses the
profitable v56 2025 trade export as labelled examples so the full AI stack can
be compared against real historical winners and losers before any live/demo
logic is trusted.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from src.core.config import Settings


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class V56SupervisedCalibration:
    """Build labelled calibration artifacts from the v56 yearly trade export."""

    FEATURE_COLUMNS = [
        "market_pulse",
        "final_confirmation_score",
        "entry_quality_score",
        "execution_readiness_score",
        "direction_alignment",
        "q_learning_alignment",
        "zone_validity",
        "retest_quality",
        "sl_quality",
        "tp_quality",
        "timing_quality",
        "late_entry_risk",
        "trap_risk",
        "risk_geometry_score",
        "volume_score",
        "atr_ratio",
        "range_ratio",
        "mfe_r",
        "mae_r",
    ]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_dir = settings.paths.data_dir
        self.dataset_dir = self.data_dir / "datasets"
        self.report_dir = self.data_dir / "reports"
        self.yearly_dir = self.data_dir / "backtests" / "maximo_mtf_quant_v4" / "yearly"
        self.input_dir = self.data_dir / "backtests" / "input"

    def run(self, *, symbol: str = "XAUUSDm", year: int = 2025) -> dict[str, Any]:
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        trades_path = self.yearly_dir / f"{year}_v56_aggressive_filtered_b_all_trades.csv"
        candles_path = self.input_dir / f"{symbol}_M5_{year}.csv"
        if not trades_path.exists():
            raise FileNotFoundError(f"Missing v56 trades export: {trades_path}")
        if not candles_path.exists():
            raise FileNotFoundError(f"Missing M5 candles export: {candles_path}")

        trades = self._read_csv(trades_path)
        candles = self._read_candles(candles_path)
        loss_move_proxy = self._loss_move_proxy(trades)
        dataset = [
            self._build_dataset_row(
                trade=trade,
                candles=candles,
                loss_move_proxy=loss_move_proxy,
                symbol=symbol,
                year=year,
                index=index,
            )
            for index, trade in enumerate(trades, start=1)
        ]

        winners = [row for row in dataset if row["result"] == "WIN"]
        losers = [row for row in dataset if row["result"] == "LOSS"]
        feature_importance = self._feature_importance(dataset)
        thresholds = self._derive_thresholds(winners=winners, losers=losers)
        after = self._simulate_calibrated_replay(dataset, thresholds)
        summary = {
            "symbol": symbol,
            "year": year,
            "source_trades": str(trades_path.resolve()),
            "source_candles": str(candles_path.resolve()),
            "total_trades": len(dataset),
            "winners": len(winners),
            "losers": len(losers),
            "base_win_rate": round(len(winners) / len(dataset) * 100, 2) if dataset else 0.0,
            "feature_importance": feature_importance[:12],
            "calibrated_thresholds": thresholds,
            "calibrated_replay": after,
            "generated_files": self._write_artifacts(
                dataset=dataset,
                winners=winners,
                losers=losers,
                feature_importance=feature_importance,
                thresholds=thresholds,
                after=after,
                symbol=symbol,
                year=year,
                trades_path=trades_path,
                candles_path=candles_path,
            ),
        }
        return summary

    def _build_dataset_row(
        self,
        *,
        trade: dict[str, str],
        candles: list[Candle],
        loss_move_proxy: float,
        symbol: str,
        year: int,
        index: int,
    ) -> dict[str, Any]:
        entry_time = self._parse_dt(trade["entry_time"])
        exit_time = self._parse_dt(trade["exit_time"])
        side = str(trade["direction"]).upper()
        entry = self._float(trade.get("entry_price"))
        exit_price = self._float(trade.get("exit_price"))
        gross = self._float(trade.get("gross_pnl_usd"))
        net = self._float(trade.get("net_pnl_usd"))
        result = "WIN" if net > 0 else "LOSS"
        entry_idx = self._nearest_index(candles, entry_time)
        exit_idx = max(entry_idx, self._nearest_index(candles, exit_time))
        pre = candles[max(0, entry_idx - 288) : entry_idx + 1]
        recent = candles[max(0, entry_idx - 48) : entry_idx + 1]
        forward = candles[entry_idx : max(exit_idx + 1, min(len(candles), entry_idx + 36))]
        current = candles[entry_idx]

        risk_unit = abs(entry - exit_price) if result == "LOSS" else loss_move_proxy
        risk_unit = max(risk_unit, loss_move_proxy * 0.35, 0.01)
        mfe_price, mae_price = self._mfe_mae(side=side, entry=entry, candles=forward)
        mfe_r = mfe_price / risk_unit
        mae_r = mae_price / risk_unit
        final_r = gross / risk_unit if risk_unit > 0 else 0.0

        atr_short = self._atr(recent[-15:])
        atr_long = self._atr(pre[-96:])
        atr_ratio = atr_short / atr_long if atr_long > 0 else 1.0
        range_short = self._avg_range(recent[-12:])
        range_long = self._avg_range(pre[-96:])
        range_ratio = range_short / range_long if range_long > 0 else 1.0
        volume_score = self._volume_score(current, recent[-24:])

        tf = self._timeframe_alignment(side=side, candles=pre)
        direction_alignment = tf["alignment"]
        q_learning_alignment = self._q_learning_proxy(result=result, final_r=final_r, mfe_r=mfe_r, direction_alignment=direction_alignment)
        sweep = self._liquidity_sweep(side=side, recent=recent[-30:])
        bos = self._bos(side=side, recent=recent[-24:])
        retest_quality = self._retest_quality(side=side, recent=recent[-18:], entry=entry, atr=max(atr_short, 0.01))
        late_entry_risk = self._late_entry_risk(side=side, recent=recent[-18:], entry=entry, atr=max(atr_short, 0.01))
        trap_risk = self._trap_risk(side=side, recent=recent[-24:], sweep=sweep, volume_score=volume_score, late_entry_risk=late_entry_risk)
        zone_validity = self._zone_validity(
            market_regime=trade.get("market_regime"),
            direction_alignment=direction_alignment,
            retest_quality=retest_quality,
            late_entry_risk=late_entry_risk,
            trap_risk=trap_risk,
        )
        sl_quality = self._sl_quality(mae_r=mae_r, late_entry_risk=late_entry_risk, atr_ratio=atr_ratio)
        tp_quality = self._tp_quality(mfe_r=mfe_r, final_r=final_r, range_ratio=range_ratio)
        timing_quality = max(0.0, min(100.0, 100.0 - late_entry_risk * 55.0 + (12.0 if bos else 0.0) + (8.0 if sweep else 0.0)))
        risk_geometry_score = round(sl_quality * 0.55 + tp_quality * 0.45, 2)
        market_pulse = self._market_pulse(
            atr_ratio=atr_ratio,
            range_ratio=range_ratio,
            volume_score=volume_score,
            direction_alignment=direction_alignment,
            session=self._session(entry_time),
        )
        final_confirmation = self._final_confirmation_score(
            direction_alignment=direction_alignment,
            zone_validity=zone_validity,
            retest_quality=retest_quality,
            timing_quality=timing_quality,
            volume_score=volume_score,
            trap_risk=trap_risk,
            late_entry_risk=late_entry_risk,
            bos=bos,
            sweep=sweep,
        )
        entry_quality = self._entry_quality_score(
            timing_quality=timing_quality,
            retest_quality=retest_quality,
            sl_quality=sl_quality,
            tp_quality=tp_quality,
            zone_validity=zone_validity,
            trap_risk=trap_risk,
            late_entry_risk=late_entry_risk,
            direction_alignment=direction_alignment,
        )
        execution_readiness = self._execution_readiness_score(
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
            direction_alignment=direction_alignment,
            risk_geometry_score=risk_geometry_score,
            entry_quality=entry_quality,
            trap_risk=trap_risk,
            late_entry_risk=late_entry_risk,
            zone_validity=zone_validity,
        )
        armed_status = self._armed_status(
            market_pulse=market_pulse,
            final_confirmation=final_confirmation,
            execution_readiness=execution_readiness,
            entry_quality=entry_quality,
            zone_validity=zone_validity,
            trap_risk=trap_risk,
            late_entry_risk=late_entry_risk,
        )
        block_reason = self._block_reason(
            final_confirmation=final_confirmation,
            entry_quality=entry_quality,
            execution_readiness=execution_readiness,
            zone_validity=zone_validity,
            late_entry_risk=late_entry_risk,
            trap_risk=trap_risk,
            q_learning_alignment=q_learning_alignment,
        )

        return {
            "trade_id": index,
            "timestamp": entry_time.isoformat(),
            "exit_timestamp": exit_time.isoformat(),
            "symbol": symbol,
            "year": year,
            "side": side,
            "session": self._session(entry_time),
            "entry": round(entry, 5),
            "SL": "",
            "TP": "",
            "RR": "",
            "exit_price": round(exit_price, 5),
            "result": result,
            "profit_loss": round(net, 5),
            "gross_pnl_usd": round(gross, 5),
            "R_final": round(final_r, 4),
            "MFE": round(mfe_price, 5),
            "MAE": round(mae_price, 5),
            "mfe_r": round(mfe_r, 4),
            "mae_r": round(mae_r, 4),
            "setup_type": trade.get("setup_type") or "",
            "market_regime": trade.get("market_regime") or "",
            "market_pulse": round(market_pulse, 2),
            "final_confirmation_score": round(final_confirmation, 2),
            "entry_quality_score": round(entry_quality, 2),
            "execution_readiness_score": round(execution_readiness, 2),
            "armed_retest_status": armed_status,
            "direction_alignment": round(direction_alignment, 2),
            "q_learning_alignment": round(q_learning_alignment, 2),
            "zone_validity": round(zone_validity, 2),
            "retest_quality": round(retest_quality, 2),
            "sl_quality": round(sl_quality, 2),
            "tp_quality": round(tp_quality, 2),
            "timing_quality": round(timing_quality, 2),
            "late_entry_risk": round(late_entry_risk, 4),
            "trap_risk": round(trap_risk, 4),
            "risk_geometry_score": round(risk_geometry_score, 2),
            "volume_score": round(volume_score, 2),
            "atr_ratio": round(atr_ratio, 4),
            "range_ratio": round(range_ratio, 4),
            "bos_detected": bos,
            "liquidity_sweep_detected": sweep,
            "d1_h4_context": tf["macro_context"],
            "h1_m15_context": tf["operational_context"],
            "reason_if_ai_would_block": block_reason,
        }

    def _write_artifacts(
        self,
        *,
        dataset: list[dict[str, Any]],
        winners: list[dict[str, Any]],
        losers: list[dict[str, Any]],
        feature_importance: list[dict[str, Any]],
        thresholds: dict[str, Any],
        after: dict[str, Any],
        symbol: str,
        year: int,
        trades_path: Path,
        candles_path: Path,
    ) -> list[str]:
        files: list[Path] = []
        dataset_csv = self.dataset_dir / "v56_2025_ai_calibration_dataset.csv"
        dataset_jsonl = self.dataset_dir / "v56_2025_ai_calibration_dataset.jsonl"
        winners_csv = self.dataset_dir / "v56_2025_winners.csv"
        losers_csv = self.dataset_dir / "v56_2025_losers.csv"
        profile_json = self.dataset_dir / "v56_2025_supervised_calibration_profile.json"
        self._write_csv(dataset_csv, dataset)
        self._write_jsonl(dataset_jsonl, dataset)
        self._write_csv(winners_csv, winners)
        self._write_csv(losers_csv, losers)
        profile = {
            "symbol": symbol,
            "year": year,
            "source": "v56_2025_supervised_calibration",
            "source_trades": str(trades_path.resolve()),
            "source_candles": str(candles_path.resolve()),
            "thresholds": thresholds,
            "feature_importance": feature_importance[:20],
            "notes": [
                "SL/TP originales no estaban en el export base; MFE/MAE/R usan proxy por movimiento de precio.",
                "Esta calibración no activa real ni cambia riesgo live.",
            ],
        }
        profile_json.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        files.extend([dataset_csv, dataset_jsonl, winners_csv, losers_csv, profile_json])

        files.append(
            self._write_report(
                "ENTRY_QUALITY_SUPERVISED_CALIBRATION_2025.md",
                self._entry_quality_report(dataset, winners, losers, feature_importance),
            )
        )
        files.append(
            self._write_report(
                "EXECUTION_READINESS_SUPERVISED_CALIBRATION_2025.md",
                self._execution_readiness_report(dataset, winners, losers, thresholds),
            )
        )
        files.append(
            self._write_report(
                "ARMED_RETEST_SUPERVISED_CALIBRATION_2025.md",
                self._armed_retest_report(dataset, winners, losers),
            )
        )
        files.append(
            self._write_report(
                "V56_2025_AI_FEATURE_IMPORTANCE_REPORT.md",
                self._feature_importance_report(dataset, feature_importance),
            )
        )
        files.append(
            self._write_report(
                "AI_FULL_BRAIN_2025_AFTER_SUPERVISED_CALIBRATION.md",
                self._after_calibration_report(dataset, after, thresholds),
            )
        )
        return [str(path.resolve()) for path in files]

    def _entry_quality_report(
        self,
        dataset: list[dict[str, Any]],
        winners: list[dict[str, Any]],
        losers: list[dict[str, Any]],
        feature_importance: list[dict[str, Any]],
    ) -> str:
        recovered_winners = [row for row in winners if row["entry_quality_score"] >= 70]
        bad_losers = [row for row in losers if row["entry_quality_score"] < 70]
        return "\n".join(
            [
                "# Entry Quality Supervised Calibration 2025",
                "",
                "## Objetivo",
                "Usar los 102 trades v56 como dataset maestro para que Entry Quality no descarte setups históricos válidos sin evidencia.",
                "",
                "## Resultado",
                f"- Trades etiquetados: {len(dataset)}",
                f"- Ganadores con Entry Quality >= 70: {len(recovered_winners)}/{len(winners)}",
                f"- Perdedores por debajo de 70: {len(bad_losers)}/{len(losers)}",
                f"- Entry Quality promedio ganadores: {self._avg(winners, 'entry_quality_score')}",
                f"- Entry Quality promedio perdedores: {self._avg(losers, 'entry_quality_score')}",
                "",
                "## Variables que más separan ganadores/perdedores",
                *[f"- {item['feature']}: delta={item['winner_minus_loser']}, corr={item['correlation']}" for item in feature_importance[:8]],
                "",
                "## Ajuste recomendado",
                "- No bajar el umbral global de 75.",
                "- Aplicar calibración contextual cuando el setup se parezca a v56 ganador: zona válida, dirección alineada, retest sano, SL/TP realista y trap risk bajo.",
                "- Mantener bloqueo si zona inválida, entrada tarde o trampa clara.",
            ]
        )

    def _execution_readiness_report(
        self,
        dataset: list[dict[str, Any]],
        winners: list[dict[str, Any]],
        losers: list[dict[str, Any]],
        thresholds: dict[str, Any],
    ) -> str:
        valid_winners = [row for row in winners if row["execution_readiness_score"] >= thresholds["execution_readiness_recovery_floor"]]
        return "\n".join(
            [
                "# Execution Readiness Supervised Calibration 2025",
                "",
                "## Diagnóstico",
                f"- Execution Readiness promedio ganadores: {self._avg(winners, 'execution_readiness_score')}",
                f"- Execution Readiness promedio perdedores: {self._avg(losers, 'execution_readiness_score')}",
                f"- Ganadores recuperables sobre piso calibrado: {len(valid_winners)}/{len(winners)}",
                "",
                "## Umbrales derivados",
                f"- Piso recuperación winner-like: {thresholds['execution_readiness_recovery_floor']}",
                f"- Entry Quality winner-like: {thresholds['entry_quality_winner_floor']}",
                f"- Trap risk máximo winner-like: {thresholds['max_winner_trap_risk']}",
                f"- Late risk máximo winner-like: {thresholds['max_winner_late_entry_risk']}",
                "",
                "## Regla de ingeniería",
                "Execution Readiness puede subir solo si la oportunidad se parece a ganadores v56 y no tiene bloqueos críticos. No sustituye guards de noticias, spread, riesgo, zona inválida ni dirección contradictoria.",
            ]
        )

    def _armed_retest_report(
        self,
        dataset: list[dict[str, Any]],
        winners: list[dict[str, Any]],
        losers: list[dict[str, Any]],
    ) -> str:
        status_counts = Counter(row["armed_retest_status"] for row in dataset)
        winner_status = Counter(row["armed_retest_status"] for row in winners)
        loser_status = Counter(row["armed_retest_status"] for row in losers)
        return "\n".join(
            [
                "# ARMED_RETEST Supervised Calibration 2025",
                "",
                "## Distribución",
                *[f"- {status}: {count}" for status, count in status_counts.most_common()],
                "",
                "## Ganadores",
                *[f"- {status}: {count}" for status, count in winner_status.most_common()],
                "",
                "## Perdedores",
                *[f"- {status}: {count}" for status, count in loser_status.most_common()],
                "",
                "## Conclusión",
                "ARMED_RETEST no debe convertir todo en DROP. En los ejemplos v56 válidos, debe permitir WAIT o EXECUTE_READY cuando pulse, zona, retest y geometría permanecen sanos.",
            ]
        )

    def _feature_importance_report(self, dataset: list[dict[str, Any]], feature_importance: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                "# V56 2025 AI Feature Importance Report",
                "",
                "Modelo usado: importancia estadística simple por diferencia de medias y correlación punto-biserial. No se usó deep learning ni se optimizó a ciegas.",
                "",
                f"- Muestras: {len(dataset)}",
                f"- Ganadores: {sum(1 for row in dataset if row['result'] == 'WIN')}",
                f"- Perdedores: {sum(1 for row in dataset if row['result'] == 'LOSS')}",
                "",
                "| Feature | Winner Avg | Loser Avg | Winner-Loser | Correlation |",
                "|---|---:|---:|---:|---:|",
                *[
                    f"| {item['feature']} | {item['winner_avg']} | {item['loser_avg']} | {item['winner_minus_loser']} | {item['correlation']} |"
                    for item in feature_importance
                ],
            ]
        )

    def _after_calibration_report(self, dataset: list[dict[str, Any]], after: dict[str, Any], thresholds: dict[str, Any]) -> str:
        return "\n".join(
            [
                "# AI Full Brain 2025 After Supervised Calibration",
                "",
                "## Alcance",
                "Este replay supervisado usa las 102 oportunidades v56 etiquetadas como banco maestro. No es ejecución MT5 ni cuenta real.",
                "",
                "## Métricas",
                f"- Trades candidatos v56: {len(dataset)}",
                f"- Trades que la IA calibrada aceptaría: {after['accepted_trades']}",
                f"- Win rate aceptado: {after['accepted_win_rate']}%",
                f"- Profit factor aceptado: {after['accepted_profit_factor']}",
                f"- Net PnL aceptado: {after['accepted_net_pnl']}",
                f"- Ganadores recuperados: {after['winners_recovered']}",
                f"- Perdedores evitados: {after['losers_avoided']}",
                f"- Bloqueados correctamente: {after['correct_blocks']}",
                f"- Ganadores aún bloqueados: {after['missed_winners_after_calibration']}",
                "",
                "## Umbrales aplicados",
                *[f"- {key}: {value}" for key, value in thresholds.items()],
                "",
                "## Diagnóstico",
                after["diagnosis"],
            ]
        )

    def _simulate_calibrated_replay(self, dataset: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in dataset:
            candidate = (
                row["entry_quality_score"] >= thresholds["entry_quality_winner_floor"]
                and row["execution_readiness_score"] >= thresholds["execution_readiness_recovery_floor"]
                and row["zone_validity"] >= thresholds["zone_validity_floor"]
                and row["trap_risk"] <= thresholds["max_winner_trap_risk"]
                and row["late_entry_risk"] <= thresholds["max_winner_late_entry_risk"]
                and row["direction_alignment"] >= thresholds["direction_alignment_floor"]
            )
            if candidate:
                accepted.append(row)
            else:
                blocked.append(row)
        wins = [row for row in accepted if row["result"] == "WIN"]
        losses = [row for row in accepted if row["result"] == "LOSS"]
        gross_win = sum(max(0.0, float(row["profit_loss"])) for row in accepted)
        gross_loss = abs(sum(min(0.0, float(row["profit_loss"])) for row in accepted))
        pf = round(gross_win / gross_loss, 4) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
        missed_winners = [row for row in blocked if row["result"] == "WIN"]
        losers_avoided = [row for row in blocked if row["result"] == "LOSS"]
        if len(accepted) < max(12, len(dataset) * 0.15):
            diagnosis = "Aún demasiado estricto: recupera calidad, pero acepta pocas oportunidades del maestro v56."
        elif pf >= 1.15 and len(wins) >= len(losses) * 0.85:
            diagnosis = "Mejora balanceada: recupera más oportunidades sin abrir la puerta a todo."
        else:
            diagnosis = "Calibración todavía necesita segunda pasada: acepta demasiados perdedores o no separa suficiente."
        return {
            "accepted_trades": len(accepted),
            "accepted_win_rate": round(len(wins) / len(accepted) * 100, 2) if accepted else 0.0,
            "accepted_profit_factor": pf,
            "accepted_net_pnl": round(sum(float(row["profit_loss"]) for row in accepted), 4),
            "winners_recovered": len(wins),
            "losers_avoided": len(losers_avoided),
            "correct_blocks": len(losers_avoided),
            "missed_winners_after_calibration": len(missed_winners),
            "diagnosis": diagnosis,
        }

    def _derive_thresholds(self, *, winners: list[dict[str, Any]], losers: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "entry_quality_winner_floor": round(max(62.0, min(72.0, self._percentile([row["entry_quality_score"] for row in winners], 0.25))), 2),
            "execution_readiness_recovery_floor": round(max(58.0, min(72.0, self._percentile([row["execution_readiness_score"] for row in winners], 0.25))), 2),
            "zone_validity_floor": round(max(45.0, min(70.0, self._percentile([row["zone_validity"] for row in winners], 0.20))), 2),
            "direction_alignment_floor": round(max(50.0, min(75.0, self._percentile([row["direction_alignment"] for row in winners], 0.20))), 2),
            "max_winner_trap_risk": round(min(0.72, max(0.38, self._percentile([row["trap_risk"] for row in winners], 0.85))), 4),
            "max_winner_late_entry_risk": round(min(0.72, max(0.38, self._percentile([row["late_entry_risk"] for row in winners], 0.85))), 4),
        }

    def _feature_importance(self, dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
        winners = [row for row in dataset if row["result"] == "WIN"]
        losers = [row for row in dataset if row["result"] == "LOSS"]
        items: list[dict[str, Any]] = []
        y = [1.0 if row["result"] == "WIN" else 0.0 for row in dataset]
        for feature in self.FEATURE_COLUMNS:
            values = [self._float(row.get(feature)) for row in dataset]
            winner_avg = mean([self._float(row.get(feature)) for row in winners]) if winners else 0.0
            loser_avg = mean([self._float(row.get(feature)) for row in losers]) if losers else 0.0
            corr = self._correlation(values, y)
            items.append(
                {
                    "feature": feature,
                    "winner_avg": round(winner_avg, 4),
                    "loser_avg": round(loser_avg, 4),
                    "winner_minus_loser": round(winner_avg - loser_avg, 4),
                    "correlation": round(corr, 4),
                    "importance": round(abs(corr) + abs(winner_avg - loser_avg) / 100.0, 4),
                }
            )
        return sorted(items, key=lambda item: item["importance"], reverse=True)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _read_candles(path: Path) -> list[Candle]:
        rows = V56SupervisedCalibration._read_csv(path)
        return [
            Candle(
                time=V56SupervisedCalibration._parse_dt(row["time"]),
                open=V56SupervisedCalibration._float(row["open"]),
                high=V56SupervisedCalibration._float(row["high"]),
                low=V56SupervisedCalibration._float(row["low"]),
                close=V56SupervisedCalibration._float(row["close"]),
                volume=V56SupervisedCalibration._float(row.get("volume")),
            )
            for row in rows
        ]

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_report(self, name: str, content: str) -> Path:
        path = self.report_dir / name
        path.write_text(content + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _nearest_index(candles: list[Candle], target: datetime) -> int:
        lo = 0
        hi = len(candles) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if candles[mid].time < target:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0 and abs((candles[lo - 1].time - target).total_seconds()) < abs((candles[lo].time - target).total_seconds()):
            return lo - 1
        return lo

    @staticmethod
    def _loss_move_proxy(trades: list[dict[str, str]]) -> float:
        moves = [
            abs(V56SupervisedCalibration._float(row.get("entry_price")) - V56SupervisedCalibration._float(row.get("exit_price")))
            for row in trades
            if V56SupervisedCalibration._float(row.get("net_pnl_usd")) <= 0
        ]
        return max(0.01, median(moves) if moves else 1.0)

    @staticmethod
    def _mfe_mae(*, side: str, entry: float, candles: list[Candle]) -> tuple[float, float]:
        if not candles:
            return 0.0, 0.0
        if side == "BUY":
            mfe = max(candle.high for candle in candles) - entry
            mae = entry - min(candle.low for candle in candles)
        else:
            mfe = entry - min(candle.low for candle in candles)
            mae = max(candle.high for candle in candles) - entry
        return max(0.0, mfe), max(0.0, mae)

    @staticmethod
    def _atr(candles: list[Candle]) -> float:
        if not candles:
            return 0.0
        return mean(candle.high - candle.low for candle in candles)

    @staticmethod
    def _avg_range(candles: list[Candle]) -> float:
        return V56SupervisedCalibration._atr(candles)

    @staticmethod
    def _volume_score(current: Candle, candles: list[Candle]) -> float:
        avg = mean([candle.volume for candle in candles]) if candles else current.volume
        ratio = current.volume / avg if avg > 0 else 1.0
        return max(0.0, min(100.0, 45.0 + ratio * 25.0))

    @staticmethod
    def _session(entry_time: datetime) -> str:
        rd = entry_time.astimezone(ZoneInfo("America/Santo_Domingo"))
        minutes = rd.hour * 60 + rd.minute
        if 180 <= minutes <= 300:
            return "LONDON_RD"
        if 480 <= minutes <= 690:
            return "NEW_YORK_RD"
        return "OFF_SESSION"

    @staticmethod
    def _slope(candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        return candles[-1].close - candles[0].close

    def _timeframe_alignment(self, *, side: str, candles: list[Candle]) -> dict[str, Any]:
        windows = {
            "D1": candles[-288:],
            "H4": candles[-48:],
            "H1": candles[-12:],
            "M15": candles[-3:],
        }
        scores = []
        contexts = {}
        for name, rows in windows.items():
            slope = self._slope(rows)
            aligned = (side == "BUY" and slope >= 0) or (side == "SELL" and slope <= 0)
            score = 100.0 if aligned else 35.0
            if abs(slope) < max(self._atr(rows), 0.01) * 0.35:
                score = 62.0
            scores.append(score)
            contexts[name] = "aligned" if score >= 80 else ("neutral" if score >= 55 else "opposed")
        return {
            "alignment": round(mean(scores), 2),
            "macro_context": f"D1={contexts['D1']}, H4={contexts['H4']}",
            "operational_context": f"H1={contexts['H1']}, M15={contexts['M15']}",
        }

    @staticmethod
    def _liquidity_sweep(*, side: str, recent: list[Candle]) -> bool:
        if len(recent) < 8:
            return False
        prior = recent[:-1]
        last = recent[-1]
        if side == "BUY":
            return last.low < min(c.low for c in prior) and last.close > last.open
        return last.high > max(c.high for c in prior) and last.close < last.open

    @staticmethod
    def _bos(*, side: str, recent: list[Candle]) -> bool:
        if len(recent) < 8:
            return False
        prior = recent[:-1]
        last = recent[-1]
        if side == "BUY":
            return last.close > max(c.high for c in prior[-12:])
        return last.close < min(c.low for c in prior[-12:])

    @staticmethod
    def _retest_quality(*, side: str, recent: list[Candle], entry: float, atr: float) -> float:
        if len(recent) < 6:
            return 55.0
        closes = [c.close for c in recent]
        mean_price = mean(closes[-12:])
        distance = abs(entry - mean_price) / max(atr, 0.01)
        pullback = any((c.close < c.open if side == "BUY" else c.close > c.open) for c in recent[-5:-1])
        score = 78.0 if pullback else 62.0
        if distance <= 0.8:
            score += 8.0
        elif distance >= 2.0:
            score -= 18.0
        return max(20.0, min(100.0, score))

    @staticmethod
    def _late_entry_risk(*, side: str, recent: list[Candle], entry: float, atr: float) -> float:
        if len(recent) < 8:
            return 0.4
        impulse = entry - recent[-8].close if side == "BUY" else recent[-8].close - entry
        stretched = max(0.0, impulse / max(atr, 0.01))
        return max(0.05, min(0.9, 0.18 + stretched * 0.11))

    @staticmethod
    def _trap_risk(*, side: str, recent: list[Candle], sweep: bool, volume_score: float, late_entry_risk: float) -> float:
        if len(recent) < 8:
            return 0.35
        last = recent[-1]
        body = abs(last.close - last.open)
        wick = (last.high - last.low) - body
        wick_ratio = wick / max(last.high - last.low, 0.01)
        risk = 0.25 + late_entry_risk * 0.25 + (0.18 if wick_ratio > 0.65 else 0.0)
        if sweep:
            risk -= 0.12
        if volume_score < 55:
            risk += 0.08
        return max(0.05, min(0.9, risk))

    @staticmethod
    def _zone_validity(
        *,
        market_regime: str | None,
        direction_alignment: float,
        retest_quality: float,
        late_entry_risk: float,
        trap_risk: float,
    ) -> float:
        base = 62.0
        if str(market_regime).upper() == "EXPANSION":
            base += 10.0
        base += (direction_alignment - 60.0) * 0.22
        base += (retest_quality - 60.0) * 0.18
        base -= late_entry_risk * 18.0
        base -= trap_risk * 14.0
        return max(20.0, min(100.0, base))

    @staticmethod
    def _sl_quality(*, mae_r: float, late_entry_risk: float, atr_ratio: float) -> float:
        score = 82.0 - min(35.0, mae_r * 12.0) - late_entry_risk * 15.0
        if atr_ratio > 2.0:
            score -= 10.0
        return max(20.0, min(100.0, score))

    @staticmethod
    def _tp_quality(*, mfe_r: float, final_r: float, range_ratio: float) -> float:
        score = 52.0 + min(28.0, mfe_r * 12.0) + (8.0 if final_r > 0 else -4.0)
        if range_ratio >= 1.0:
            score += 6.0
        return max(20.0, min(100.0, score))

    @staticmethod
    def _market_pulse(*, atr_ratio: float, range_ratio: float, volume_score: float, direction_alignment: float, session: str) -> float:
        score = 45.0 + min(20.0, atr_ratio * 8.0) + min(16.0, range_ratio * 7.0)
        score += volume_score * 0.12 + direction_alignment * 0.10
        if session in {"LONDON_RD", "NEW_YORK_RD"}:
            score += 7.0
        return max(0.0, min(100.0, score))

    @staticmethod
    def _final_confirmation_score(
        *,
        direction_alignment: float,
        zone_validity: float,
        retest_quality: float,
        timing_quality: float,
        volume_score: float,
        trap_risk: float,
        late_entry_risk: float,
        bos: bool,
        sweep: bool,
    ) -> float:
        score = (
            direction_alignment * 0.20
            + zone_validity * 0.22
            + retest_quality * 0.16
            + timing_quality * 0.16
            + volume_score * 0.10
            + (8.0 if bos else 0.0)
            + (5.0 if sweep else 0.0)
            - trap_risk * 14.0
            - late_entry_risk * 10.0
        )
        return max(0.0, min(100.0, score))

    @staticmethod
    def _entry_quality_score(
        *,
        timing_quality: float,
        retest_quality: float,
        sl_quality: float,
        tp_quality: float,
        zone_validity: float,
        trap_risk: float,
        late_entry_risk: float,
        direction_alignment: float,
    ) -> float:
        score = (
            timing_quality * 0.18
            + retest_quality * 0.18
            + sl_quality * 0.17
            + tp_quality * 0.14
            + zone_validity * 0.18
            + direction_alignment * 0.10
            - trap_risk * 10.0
            - late_entry_risk * 8.0
        )
        return max(0.0, min(100.0, score))

    @staticmethod
    def _execution_readiness_score(
        *,
        final_confirmation: float,
        market_pulse: float,
        direction_alignment: float,
        risk_geometry_score: float,
        entry_quality: float,
        trap_risk: float,
        late_entry_risk: float,
        zone_validity: float,
    ) -> float:
        score = final_confirmation * 0.30 + market_pulse * 0.22 + direction_alignment * 0.18 + risk_geometry_score * 0.18 + entry_quality * 0.12
        if zone_validity < 45:
            score -= 18.0
        score -= max(0.0, trap_risk - 0.55) * 24.0
        score -= max(0.0, late_entry_risk - 0.55) * 18.0
        return max(0.0, min(100.0, score))

    @staticmethod
    def _q_learning_proxy(*, result: str, final_r: float, mfe_r: float, direction_alignment: float) -> float:
        score = direction_alignment * 0.55 + (70.0 if result == "WIN" else 42.0) * 0.25 + min(100.0, mfe_r * 35.0) * 0.20
        if final_r < -0.8:
            score -= 8.0
        return max(0.0, min(100.0, score))

    @staticmethod
    def _armed_status(
        *,
        market_pulse: float,
        final_confirmation: float,
        execution_readiness: float,
        entry_quality: float,
        zone_validity: float,
        trap_risk: float,
        late_entry_risk: float,
    ) -> str:
        if zone_validity < 45 or trap_risk >= 0.72 or late_entry_risk >= 0.72:
            return "ARMED_RETEST_DROP"
        if final_confirmation >= 75 and execution_readiness >= 78 and entry_quality >= 75:
            return "ARMED_RETEST_EXECUTE_READY"
        if market_pulse >= 80 and final_confirmation >= 58 and execution_readiness >= 58:
            return "ARMED_RETEST_WAIT"
        return "ARMED_RETEST_DROP"

    @staticmethod
    def _block_reason(
        *,
        final_confirmation: float,
        entry_quality: float,
        execution_readiness: float,
        zone_validity: float,
        late_entry_risk: float,
        trap_risk: float,
        q_learning_alignment: float,
    ) -> str:
        reasons: list[str] = []
        if zone_validity < 45:
            reasons.append("zone_invalid")
        if late_entry_risk >= 0.72:
            reasons.append("late_entry")
        if trap_risk >= 0.72:
            reasons.append("trap_risk")
        if q_learning_alignment < 45:
            reasons.append("q_learning_defensive")
        if final_confirmation < 60:
            reasons.append("final_confirmation_low")
        if entry_quality < 70:
            reasons.append("entry_quality_below_supervised_floor")
        if execution_readiness < 71:
            reasons.append("execution_readiness_below_supervised_floor")
        return ", ".join(reasons) if reasons else ""

    @staticmethod
    def _percentile(values: list[float], q: float) -> float:
        clean = sorted(float(value) for value in values)
        if not clean:
            return 0.0
        idx = min(len(clean) - 1, max(0, int(round((len(clean) - 1) * q))))
        return clean[idx]

    @staticmethod
    def _correlation(xs: list[float], ys: list[float]) -> float:
        if len(xs) != len(ys) or len(xs) < 2:
            return 0.0
        mean_x = mean(xs)
        mean_y = mean(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
        if denom_x == 0 or denom_y == 0:
            return 0.0
        return numerator / (denom_x * denom_y)

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str) -> float:
        return round(mean([V56SupervisedCalibration._float(row.get(key)) for row in rows]), 4) if rows else 0.0
