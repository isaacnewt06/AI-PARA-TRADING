"""Prepare a structured dataset for future backtesting engines."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.knowledge import ExtractedRule
from src.db.repositories.knowledge import BacktestDatasetRepository, RuleRepository

logger = get_logger(__name__)


class BacktestDatasetBuilder:
    """Transform structured rules into a flat dataset."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.rule_repository = RuleRepository(session)
        self.dataset_repository = BacktestDatasetRepository(session)

    def build(self, strategy_key: str | None = None, output_path: str | None = None) -> dict:
        rules = self.rule_repository.list_rules()
        if strategy_key:
            rules = [rule for rule in rules if rule.strategy_key == strategy_key]

        payloads = [self._payload(rule) for rule in rules]
        rows_written = self.dataset_repository.replace_rows(payloads)

        file_path = None
        if output_path:
            file_path = self._write_csv(payloads, Path(output_path))
        return {"rows": rows_written, "output_path": file_path}

    def _payload(self, rule: ExtractedRule) -> dict:
        return {
            "extracted_rule_id": rule.id,
            "source_chunk_id": rule.source_chunk_id,
            "strategy_key": rule.strategy_key,
            "cluster_key": rule.cluster_key,
            "author_name": rule.author_name,
            "channel_name": rule.channel_name,
            "asset": rule.asset,
            "timeframe": rule.timeframe,
            "direction": rule.direction,
            "context": rule.context,
            "entry_condition": rule.entry_condition,
            "confirmation": rule.confirmation,
            "stop_loss": rule.stop_loss,
            "take_profit": rule.take_profit,
            "risk_management": rule.risk_management,
            "session_filter": rule.session_filter,
            "observations": rule.observations,
            "concepts_json": rule.concepts_json,
            "dataset_version": "v1",
            "ready_for_backtest": bool(rule.entry_condition and (rule.stop_loss or rule.risk_management)),
        }

    def _write_csv(self, payloads: list[dict], output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not payloads:
            output_path.write_text("", encoding="utf-8")
            return str(output_path.resolve())

        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(payloads[0].keys()))
            writer.writeheader()
            writer.writerows(payloads)
        logger.info("Exported backtest dataset to %s", output_path)
        return str(output_path.resolve())
