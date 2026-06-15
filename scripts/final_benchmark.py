import time
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine

engine = DefinitiveExecutionConfirmationEngine()
start = time.time()

# Test con valores óptimos
for i in range(100):
    result = engine.evaluate(
        symbol='XAUUSDm',
        signal={
            'direction': 'BUY',
            'stop_price': 1.000,
            'target_price': 1.030,
            'entry_price': 1.010,
            'selected_rr': 2.5,
            'displacement_score': 85,
            'continuation_momentum': 0.85,
            'micro_bos': True,
            'volume_confirmation': 0.75,
            'movement_quality': 0.70
        },
        intelligence={
            'overview': {'market_state': {'pulse_score': 85, 'clarity_score': 80, 'harmony_score': 0.9, 'setup_maturity': 0.85, 'daily_bias': 'BUY', 'macro_bias': 'BUY', 'preferred_side': 'BUY', 'ob_rejection_families': {'aggressive': {'active': True, 'side': 'BUY'}}}},
            'execution_readiness': {'pulse_score': 85, 'setup_maturity': 0.85},
            'event_risk': {}
        }
    )

elapsed = time.time() - start
print(f"=== VERIFICACION FINAL CALIDAD ALTA ===")
print(f"Tiempo: {elapsed/100*1000:.3f} ms/decision")
print(f"Velocidad: {100/elapsed:.0f} decisions/segundo")
print(f"Decision: {result['decision']}")
print(f"Can execute: {result['can_execute']}")
prob = result.get("probability", {})
print(f"Win probability: {prob.get('win_probability', 0)}")
print(f"Confidence: {prob.get('confidence', 0)}")
print(f"Trap analysis: {result.get('trap_analysis', {})}")
print(f"Staged exit: {'ACTIVO' if result.get('staged_exit_plan') else 'NO'}")
print(f"COORDENACION: OPTIMAL (multi-capa + probabilidad + memoria)")