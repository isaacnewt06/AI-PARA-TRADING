"""Typed strategy schemas for phase 3."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StrategySetupDefinition(BaseModel):
    """Backtest-ready setup definition with full traceability."""

    setup_id: str
    setup_name: str
    strategy_family: str
    symbols: list[str] = Field(default_factory=list)
    context_tf: list[str] = Field(default_factory=list)
    entry_tf: list[str] = Field(default_factory=list)
    allowed_sessions: list[str] = Field(default_factory=list)
    required_conditions: list[dict] = Field(default_factory=list)
    optional_conditions: list[dict] = Field(default_factory=list)
    invalidation_conditions: list[dict] = Field(default_factory=list)
    confirmation_logic: list[dict] = Field(default_factory=list)
    sl_logic: dict = Field(default_factory=dict)
    tp_logic: dict = Field(default_factory=dict)
    rr_constraints: dict = Field(default_factory=dict)
    risk_constraints: dict = Field(default_factory=dict)
    execution_notes: str | None = None
    source_traceability: dict = Field(default_factory=dict)


class StrategyExportBundle(BaseModel):
    """Serializable bundle for backtesting adapters."""

    schema_version: str = "phase3.v1"
    strategies: list[StrategySetupDefinition] = Field(default_factory=list)


class DetectedStrategySummary(BaseModel):
    """Summarized materialized strategy pattern detected across channel knowledge."""

    strategy_key: str
    name: str
    strategy_family: str | None = None
    concepts: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    entry_types: list[str] = Field(default_factory=list)
    supporting_setup_names: list[str] = Field(default_factory=list)
    source_count: int = 0
    author_count: int = 0
    channel_count: int = 0
    rule_count: int = 0
    candidate_count: int = 0
    completeness_score: float = 0.0
    frequency_score: float = 0.0
    source_diversity_score: float = 0.0
    execution_definition_score: float = 0.0
    relevance_score: float = 0.0
    summary: str | None = None
    evidence: dict = Field(default_factory=dict)


class ExecutableStrategyBlueprint(BaseModel):
    """Actionable strategy blueprint derived from detected strategies."""

    blueprint_id: str
    strategy_key: str
    blueprint_name: str
    strategy_family: str
    priority: int = 0
    execution_profile: str
    status: str = "executable"
    context: dict = Field(default_factory=dict)
    valid_zone: dict = Field(default_factory=dict)
    confirmation: dict = Field(default_factory=dict)
    entry: dict = Field(default_factory=dict)
    stop_loss: dict = Field(default_factory=dict)
    take_profit: dict = Field(default_factory=dict)
    risk_management: dict = Field(default_factory=dict)
    operational_checklist: list[str] = Field(default_factory=list)
    quantifiable_conditions: list[dict] = Field(default_factory=list)
    invalidation_rules: list[str] = Field(default_factory=list)
    simulation_overrides: dict = Field(default_factory=dict)
    source_traceability: dict = Field(default_factory=dict)


class ExcludedStrategyBlueprint(BaseModel):
    """Detected strategy intentionally excluded from executable export."""

    strategy_key: str
    name: str
    strategy_family: str | None = None
    reason: str
    evidence: dict = Field(default_factory=dict)


class ExecutableBlueprintBundle(BaseModel):
    """Exportable bundle of executable and excluded strategies."""

    schema_version: str = "phase3.blueprints.v1"
    generated_at: str
    blueprints: list[ExecutableStrategyBlueprint] = Field(default_factory=list)
    excluded_strategies: list[ExcludedStrategyBlueprint] = Field(default_factory=list)


class BacktestBlueprintSpec(BaseModel):
    """Formal backtest spec generated from an executable blueprint."""

    strategy_name: str
    family: str
    symbols_suggested: list[str] = Field(default_factory=list)
    context_timeframe: list[str] = Field(default_factory=list)
    entry_timeframe: list[str] = Field(default_factory=list)
    session_filter: list[str] = Field(default_factory=list)
    required_conditions: list[dict] = Field(default_factory=list)
    confirmation_conditions: list[dict] = Field(default_factory=list)
    entry_logic: dict = Field(default_factory=dict)
    sl_logic: dict = Field(default_factory=dict)
    tp_logic: dict = Field(default_factory=dict)
    rr_min: float | None = None
    risk_per_trade: float | None = None
    invalidation_conditions: list[str] = Field(default_factory=list)
    quantifiable_condition_map: list[dict] = Field(default_factory=list)
    simulation_overrides: dict = Field(default_factory=dict)
    source_traceability: dict = Field(default_factory=dict)
