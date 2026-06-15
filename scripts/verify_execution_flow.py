"""Verify execution confirmation flow with all components integrated."""

from __future__ import annotations

from pathlib import Path
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine
from src.trading.data_resampler import generate_all_missing


def verify_flow(symbol: str = "XAUUSDm") -> None:
    """Verify the complete execution confirmation flow."""
    from src.core.config import Settings

    settings = Settings()

    print(f"\n=== VERIFICATION FOR {symbol} ===\n")

    print("1. Checking market data files...")
    input_dir = settings.paths.data_dir / "backtests" / "input"
    m5_file = input_dir / f"{symbol}_M5.csv"
    m15_file = input_dir / f"{symbol}_M15.csv"
    h1_file = input_dir / f"{symbol}_H1.csv"

    print(f"   M5: {m5_file.exists()} ({m5_file.stat().st_size if m5_file.exists() else 0} bytes)")
    print(f"   M15: {m15_file.exists()} ({m15_file.stat().st_size if m15_file.exists() else 0} bytes)")
    print(f"   H1: {h1_file.exists()} ({h1_file.stat().st_size if h1_file.exists() else 0} bytes)")

    if not m15_file.exists() or not h1_file.exists():
        print("\n   [REGENERATING MISSING DATA]")
        generate_all_missing(input_dir)

    print("\n2. Testing definitive confirmation engine...")
    engine = DefinitiveExecutionConfirmationEngine()

    test_intelligence = {
        "overview": {
            "market_state": {
                "preferred_side": "BUY",
                "market_regime": "EXPANSION",
                "pulse_score": 85,
                "clarity_score": 75,
                "harmony_score": 0.72,
                "setup_maturity": 78,
                "impulse_score": 68,
                "atr_ratio": 1.15,
                "range_ratio": 1.25,
                "ob_rejection_families": {
                    "aggressive": {
                        "active": True,
                        "checks": {
                            "strong_bullish_rejection": True,
                            "partial_bull_displacement": True,
                            "continuation_momentum_buy": True,
                        },
                    },
                    "institutional": {"active": False},
                },
                "timeframe_alignment": {
                    "dominant_side": "BUY",
                    "alignment_score": 0.65,
                },
            },
            "knowledge_alignment": {
                "harmony": {
                    "harmony_score": 0.72,
                    "operating_posture": "offensive",
                },
            },
            "signal": {
                "direction": "BUY",
                "stop_price": 1900.0,
                "target_price": 1920.0,
                "entry_price": 1910.0,
                "selected_rr": 2.0,
                "setup_type": "AGG",
                "displacement_score": 60,
                "micro_bos": True,
            },
            "decision": {"action": "EXECUTE"},
        },
        "execution_readiness": {
            "action": "EXECUTE",
            "setup_maturity": 78,
            "confidence": 0.75,
        },
        "event_risk": {"action": "allow"},
    }

    result = engine.evaluate(symbol=symbol, signal=test_intelligence["overview"]["signal"],
                             intelligence=test_intelligence, snapshot={})

    print(f"\n3. Confirmation Result:")
    print(f"   Decision: {result['decision']}")
    print(f"   Score: {result['final_confirmation_score']}")
    print(f"   Can Execute: {result['can_execute']}")
    print(f"   Should Arm Retest: {result['should_arm_retest']}")

    print(f"\n4. Confirmation Checklist:")
    for key, value in result["confirmation_checklist"].items():
        status = "PASS" if value else "FAIL"
        print(f"   [{status}] {key}: {value}")

    print(f"\n5. Volume/Momentum Analysis:")
    print(f"   Volume Score: {result['volume_confirmation_score']}")
    print(f"   Movement Quality: {result['volume_movement_quality']}")
    print(f"   Liquidity Readiness: {result['liquidity_readiness_score']}")

    print(f"\n6. Risk Geometry:")
    for key, value in result["risk_geometry"].items():
        print(f"   {key}: {value}")

    print(f"\n7. Direction Consistency:")
    print(f"   Aligned: {result['direction_consistency']['aligned']}")
    print(f"   Dominant Side: {result['direction_consistency']['dominant_side']}")

    print("\n=== VERIFICATION COMPLETE ===\n")


if __name__ == "__main__":
    verify_flow()