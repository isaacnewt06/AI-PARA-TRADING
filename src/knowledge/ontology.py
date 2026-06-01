"""Operational trading ontology used by phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StrategyFamily(StrEnum):
    """High-level strategy families."""

    ICT = "ICT"
    SMC = "SMC"
    TREND_PULLBACK = "Trend Pullback"
    BREAKOUT_RETEST = "Breakout Retest"
    LIQUIDITY_REVERSAL = "Liquidity Reversal"
    OB_REJECTION = "OB Rejection"
    FVG_CONTINUATION = "FVG Continuation"
    SESSION_EXPANSION = "Session Expansion"
    GENERAL = "General"


class TradingSession(StrEnum):
    """Known trading sessions."""

    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_OPEN = "london_open"
    NY_OPEN = "ny_open"
    KILLZONE = "killzone"


class Timeframe(StrEnum):
    """Canonical timeframes."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"


class TechnicalConcept(StrEnum):
    """Canonical technical concepts."""

    BOS = "bos"
    CHOCH = "choch"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    FVG = "fvg"
    ORDER_BLOCK = "order_block"
    MARKET_STRUCTURE = "market_structure"
    DISPLACEMENT = "displacement"
    PREMIUM_DISCOUNT = "premium_discount"
    BREAKOUT = "breakout"
    RETEST = "retest"
    TREND = "trend"
    SUPPORT_RESISTANCE = "support_resistance"


class ConfirmationType(StrEnum):
    """Entry confirmation patterns."""

    ENGULFING = "engulfing"
    PINBAR = "pinbar"
    DISPLACEMENT_CANDLE = "displacement_candle"
    CLOSE_ABOVE_BELOW = "close_above_below"
    RETEST_REJECTION = "retest_rejection"


class EntryType(StrEnum):
    """Entry model types."""

    FVG_ENTRY = "fvg_entry"
    ORDER_BLOCK_REJECTION = "order_block_rejection"
    BREAKOUT_RETEST = "breakout_retest"
    LIQUIDITY_REVERSAL = "liquidity_reversal"
    MARKET_ORDER_SIGNAL = "market_order_signal"
    LIMIT_AT_ZONE = "limit_at_zone"


class StopModel(StrEnum):
    """Stop loss models."""

    RECENT_SWING_LOW = "recent_swing_low"
    RECENT_SWING_HIGH = "recent_swing_high"
    ORDER_BLOCK_INVALIDATION = "order_block_invalidation"
    FVG_INVALIDATION = "fvg_invalidation"
    FIXED_PIPS = "fixed_pips"
    ATR_MULTIPLE = "atr_multiple"
    UNKNOWN = "unknown"


class TakeProfitModel(StrEnum):
    """Take profit models."""

    FIXED_RR = "fixed_rr"
    OPPOSING_LIQUIDITY = "opposing_liquidity"
    PREVIOUS_HIGH_LOW = "previous_high_low"
    PARTIALS = "partials"
    SESSION_RANGE_EXTENSION = "session_range_extension"
    UNKNOWN = "unknown"


class RiskModel(StrEnum):
    """Risk model types."""

    FIXED_PERCENT = "fixed_percent"
    FIXED_LOT = "fixed_lot"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    CONFIGURABLE = "configurable"


class ContextFilter(StrEnum):
    """Context filter types."""

    HTF_BIAS = "htf_bias"
    EMA_SLOPE = "ema_slope"
    STRUCTURE_HH_HL = "structure_hh_hl"
    STRUCTURE_LL_LH = "structure_ll_lh"
    PREMIUM_DISCOUNT = "premium_discount"
    NEWS_AVOIDANCE = "news_avoidance"


@dataclass(frozen=True, slots=True)
class ConditionTemplate:
    """Quantifiable template for a trading concept."""

    condition_key: str
    concept: TechnicalConcept | ConfirmationType | EntryType | StopModel | TakeProfitModel | ContextFilter
    condition_type: str
    signal_function: str
    default_parameters: dict
    notes: str


class TradingOntology:
    """Reusable catalog and synonym resolver for trading concepts."""

    SYMBOL_ALIASES: dict[str, str] = {
        "gold": "XAUUSD",
        "xau": "XAUUSD",
        "xauusd": "XAUUSD",
        "xauusdm": "XAUUSDm",
        "xagusdm": "XAGUSDm",
        "bitcoin": "BTCUSD",
        "btc": "BTCUSD",
        "btcusd": "BTCUSD",
        "btcusdm": "BTCUSDm",
        "nasdaq": "NAS100",
        "nas100": "NAS100",
        "us30": "US30",
        "eurusd": "EURUSD",
        "eurusdm": "EURUSDm",
        "gbpusd": "GBPUSD",
        "gbpusdm": "GBPUSDm",
    }
    TIMEFRAME_ALIASES: dict[str, Timeframe] = {
        "1m": Timeframe.M1,
        "m1": Timeframe.M1,
        "5m": Timeframe.M5,
        "m5": Timeframe.M5,
        "15m": Timeframe.M15,
        "m15": Timeframe.M15,
        "30m": Timeframe.M30,
        "m30": Timeframe.M30,
        "1h": Timeframe.H1,
        "h1": Timeframe.H1,
        "4h": Timeframe.H4,
        "h4": Timeframe.H4,
        "daily": Timeframe.D1,
        "d1": Timeframe.D1,
    }
    SESSION_ALIASES: dict[str, TradingSession] = {
        "london": TradingSession.LONDON,
        "london session": TradingSession.LONDON,
        "london open": TradingSession.LONDON_OPEN,
        "ny": TradingSession.NEW_YORK,
        "new york": TradingSession.NEW_YORK,
        "new york session": TradingSession.NEW_YORK,
        "ny open": TradingSession.NY_OPEN,
        "asia": TradingSession.ASIA,
        "asian": TradingSession.ASIA,
        "tokyo": TradingSession.ASIA,
        "killzone": TradingSession.KILLZONE,
    }
    CONCEPT_ALIASES: dict[str, TechnicalConcept] = {
        "bos": TechnicalConcept.BOS,
        "break of structure": TechnicalConcept.BOS,
        "choch": TechnicalConcept.CHOCH,
        "change of character": TechnicalConcept.CHOCH,
        "liquidity sweep": TechnicalConcept.LIQUIDITY_SWEEP,
        "liquidity grab": TechnicalConcept.LIQUIDITY_SWEEP,
        "sweep": TechnicalConcept.LIQUIDITY_SWEEP,
        "fvg": TechnicalConcept.FVG,
        "fair value gap": TechnicalConcept.FVG,
        "imbalance": TechnicalConcept.FVG,
        "ob": TechnicalConcept.ORDER_BLOCK,
        "order block": TechnicalConcept.ORDER_BLOCK,
        "market structure": TechnicalConcept.MARKET_STRUCTURE,
        "displacement": TechnicalConcept.DISPLACEMENT,
        "premium": TechnicalConcept.PREMIUM_DISCOUNT,
        "discount": TechnicalConcept.PREMIUM_DISCOUNT,
        "breakout": TechnicalConcept.BREAKOUT,
        "retest": TechnicalConcept.RETEST,
        "trend": TechnicalConcept.TREND,
    }
    CONFIRMATION_ALIASES: dict[str, ConfirmationType] = {
        "engulfing": ConfirmationType.ENGULFING,
        "vela envolvente": ConfirmationType.ENGULFING,
        "pinbar": ConfirmationType.PINBAR,
        "pin bar": ConfirmationType.PINBAR,
        "displacement candle": ConfirmationType.DISPLACEMENT_CANDLE,
        "close above": ConfirmationType.CLOSE_ABOVE_BELOW,
        "close below": ConfirmationType.CLOSE_ABOVE_BELOW,
        "rejection": ConfirmationType.RETEST_REJECTION,
    }

    CONDITION_TEMPLATES: dict[str, ConditionTemplate] = {
        "market_structure_break": ConditionTemplate(
            condition_key="market_structure_break",
            concept=TechnicalConcept.BOS,
            condition_type="context",
            signal_function="detect_break_of_structure",
            default_parameters={"swing_lookback": 5, "close_required": True},
            notes="Close beyond recent structural swing.",
        ),
        "change_of_character": ConditionTemplate(
            condition_key="change_of_character",
            concept=TechnicalConcept.CHOCH,
            condition_type="context",
            signal_function="detect_change_of_character",
            default_parameters={"swing_lookback": 5},
            notes="First structural break against prior trend.",
        ),
        "liquidity_sweep": ConditionTemplate(
            condition_key="liquidity_sweep",
            concept=TechnicalConcept.LIQUIDITY_SWEEP,
            condition_type="entry",
            signal_function="detect_wick_sweep",
            default_parameters={"swing_lookback": 10, "close_back_inside": True},
            notes="Wick sweep above/below prior swing with close back inside.",
        ),
        "fair_value_gap": ConditionTemplate(
            condition_key="fair_value_gap",
            concept=TechnicalConcept.FVG,
            condition_type="entry_zone",
            signal_function="detect_fair_value_gap",
            default_parameters={"min_gap_atr": 0.1, "mitigation_allowed": True},
            notes="Three-candle inefficiency zone.",
        ),
        "order_block": ConditionTemplate(
            condition_key="order_block",
            concept=TechnicalConcept.ORDER_BLOCK,
            condition_type="entry_zone",
            signal_function="detect_order_block",
            default_parameters={"displacement_required": True},
            notes="Last opposing candle before displacement.",
        ),
        "engulfing_confirmation": ConditionTemplate(
            condition_key="engulfing_confirmation",
            concept=ConfirmationType.ENGULFING,
            condition_type="confirmation",
            signal_function="detect_engulfing_candle",
            default_parameters={"body_ratio_min": 1.0},
            notes="Engulfing candle in trade direction.",
        ),
        "session_filter": ConditionTemplate(
            condition_key="session_filter",
            concept=ContextFilter.HTF_BIAS,
            condition_type="filter",
            signal_function="is_within_allowed_session",
            default_parameters={"timezone": "exchange"},
            notes="Restrict entries to configured sessions.",
        ),
        "premium_discount": ConditionTemplate(
            condition_key="premium_discount",
            concept=TechnicalConcept.PREMIUM_DISCOUNT,
            condition_type="context",
            signal_function="range_position_filter",
            default_parameters={"range_lookback": 50, "discount_below": 0.5, "premium_above": 0.5},
            notes="Relative position inside dealing range.",
        ),
    }

    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip().lower()
        return cls.SYMBOL_ALIASES.get(normalized, value.strip().upper())

    @classmethod
    def normalize_timeframes(cls, values: list[str | None]) -> list[str]:
        result: list[str] = []
        for value in values:
            if not value:
                continue
            for token in str(value).replace("/", " ").replace(",", " ").split():
                timeframe = cls.TIMEFRAME_ALIASES.get(token.strip().lower())
                if timeframe and timeframe.value not in result:
                    result.append(timeframe.value)
        return result

    @classmethod
    def normalize_sessions(cls, text: str | None) -> list[str]:
        if not text:
            return []
        lowered = text.lower()
        result: list[str] = []
        for alias, session in cls.SESSION_ALIASES.items():
            if alias in lowered and session.value not in result:
                result.append(session.value)
        return result

    @classmethod
    def normalize_concepts(cls, values: list[str] | str | None) -> list[str]:
        if not values:
            return []
        text = " ".join(values) if isinstance(values, list) else values
        lowered = text.lower().replace("_", " ")
        result: list[str] = []
        for alias, concept in cls.CONCEPT_ALIASES.items():
            if alias in lowered and concept.value not in result:
                result.append(concept.value)
        return result

    @classmethod
    def normalize_confirmations(cls, text: str | None) -> list[str]:
        if not text:
            return []
        lowered = text.lower()
        result: list[str] = []
        for alias, confirmation in cls.CONFIRMATION_ALIASES.items():
            if alias in lowered and confirmation.value not in result:
                result.append(confirmation.value)
        return result

    @classmethod
    def infer_strategy_family(cls, concepts: list[str], sessions: list[str], entry_text: str | None) -> StrategyFamily:
        concept_set = set(concepts)
        entry_lower = (entry_text or "").lower()
        if TechnicalConcept.FVG.value in concept_set:
            return StrategyFamily.FVG_CONTINUATION
        if TechnicalConcept.ORDER_BLOCK.value in concept_set:
            return StrategyFamily.OB_REJECTION
        if TechnicalConcept.LIQUIDITY_SWEEP.value in concept_set:
            return StrategyFamily.LIQUIDITY_REVERSAL
        if TechnicalConcept.BREAKOUT.value in concept_set or TechnicalConcept.RETEST.value in concept_set:
            return StrategyFamily.BREAKOUT_RETEST
        if sessions:
            return StrategyFamily.SESSION_EXPANSION
        if "pullback" in entry_lower or TechnicalConcept.TREND.value in concept_set:
            return StrategyFamily.TREND_PULLBACK
        if concept_set.intersection({TechnicalConcept.BOS.value, TechnicalConcept.CHOCH.value, TechnicalConcept.FVG.value}):
            return StrategyFamily.ICT
        return StrategyFamily.GENERAL

    @classmethod
    def infer_stop_model(cls, text: str | None, direction: str | None) -> StopModel:
        lowered = (text or "").lower()
        if "swing low" in lowered or "minimum" in lowered or "mínimo" in lowered:
            return StopModel.RECENT_SWING_LOW
        if "swing high" in lowered or "maximum" in lowered or "máximo" in lowered:
            return StopModel.RECENT_SWING_HIGH
        if "order block" in lowered or "ob" in lowered:
            return StopModel.ORDER_BLOCK_INVALIDATION
        if "fvg" in lowered or "gap" in lowered:
            return StopModel.FVG_INVALIDATION
        if "atr" in lowered:
            return StopModel.ATR_MULTIPLE
        if "pip" in lowered:
            return StopModel.FIXED_PIPS
        if direction and direction.lower() in {"buy", "long"}:
            return StopModel.RECENT_SWING_LOW
        if direction and direction.lower() in {"sell", "short"}:
            return StopModel.RECENT_SWING_HIGH
        return StopModel.UNKNOWN

    @classmethod
    def infer_take_profit_model(cls, text: str | None) -> TakeProfitModel:
        lowered = (text or "").lower()
        if "rr" in lowered or "risk reward" in lowered or "1:" in lowered:
            return TakeProfitModel.FIXED_RR
        if "liquidity" in lowered:
            return TakeProfitModel.OPPOSING_LIQUIDITY
        if "high" in lowered or "low" in lowered:
            return TakeProfitModel.PREVIOUS_HIGH_LOW
        if "partial" in lowered or "tp1" in lowered:
            return TakeProfitModel.PARTIALS
        if "session" in lowered or "range" in lowered:
            return TakeProfitModel.SESSION_RANGE_EXTENSION
        return TakeProfitModel.UNKNOWN
