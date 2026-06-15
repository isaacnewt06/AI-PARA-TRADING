"""Check Q-learning memory status."""

from pathlib import Path
import json

q_path = Path("data/demo_trading/maximo_quant_v4/q_learning_table.json")
if q_path.exists():
    with open(q_path) as f:
        data = json.load(f)
    meta = data.get("_meta", {})
    print(f"Experience count: {meta.get('experience_count', 0)}")
    print(f"Replay count: {meta.get('replay_count', 0)}")
    print(f"Historical seed: {meta.get('historical_seed', {})}")
    states = [k for k in data.keys() if k != "_meta"]
    print(f"States tracked: {len(states)}")
    if states:
        print(f"Sample state: {states[0]} -> {data[states[0]]}")
else:
    print("Q-learning table NOT FOUND - needs seeding from backtest data")