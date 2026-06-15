import time
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine

engine = DefinitiveExecutionConfirmationEngine()
start = time.time()

for i in range(100):
    result = engine.evaluate(
        symbol='XAUUSDm',
        signal={
            'direction': 'BUY',
            'stop_price': 1.000,
            'target_price': 1.020,
            'entry_price': 1.005,
            'selected_rr': 2.0,
            'displacement_score': 65,
            'continuation_momentum': 0.7,
            'micro_bos': True
        },
        intelligence={
            'overview': {'market_state': {'pulse_score': 85, 'clarity_score': 75, 'harmony_score': 0.85, 'setup_maturity': 0.7, 'daily_bias': 'BUY', 'macro_bias': 'BUY'}},
            'execution_readiness': {'pulse_score': 85, 'setup_maturity': 0.7},
            'event_risk': {}
        }
    )

elapsed = time.time() - start
print(f'Tiempo: {elapsed/100*1000:.3f} ms/eval')
print(f'Decision: {result["decision"]}')
print(f'Can execute: {result["can_execute"]}')
prob = result.get("probability", {})
print(f'Win probability: {prob.get("win_probability", "N/A")}')
print(f'Should execute: {prob.get("should_execute", "N/A")}')
print('INTEGRACION: EXITOSA')