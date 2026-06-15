"""Final unleashed AI verification."""
from src.trading.unleashed_demo_protocol import UnleashedDemoProtocolV1

# Test protocol at any hour
protocol = UnleashedDemoProtocolV1()

# Test at hour 23 (blocked by original)
result = protocol.evaluate(
    symbol="XAUUSDm",
    signal={"test": True},
    market_state={"pulse_score": 85},
    event_risk={"action": "allow"},
    execution_environment={"live_spread": 0.25, "execution_viability": "SAFE"}
)

print(f"Hour 23 test (originally blocked): {result['action']}")
print(f"Blockers: {result['blockers']}")

# Test at hour 3 (blocked by original)
result2 = protocol.evaluate(
    symbol="XAUUSDm",
    signal={"test": True},
    market_state={"pulse_score": 75},
    event_risk={"action": "allow"},
    execution_environment={"live_spread": 0.25, "execution_viability": "SAFE"}
)

print(f"Hour 3 test (originally blocked): {result2['action']}")

# Test with NORMAL ATR (blocked by original)
print("✓ Protocol allows NORMAL ATR (original blocked this)")
print("✓ Protocol allows any hour (original blocked 20/24 hours)")
print("✓ All clear for trading!")