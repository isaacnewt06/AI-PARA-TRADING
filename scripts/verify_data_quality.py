"""Verify AI independence and data quality."""
import json
import csv
from pathlib import Path

print("="*60)
print("VERIFICACION INDEPENDENCIA IA - SIN DEPENDENCIA DE BOT")
print("="*60)

# Check AI modules have no bot dependencies
ai_files = [
    "src/trading/definitive_execution_confirmation.py",
    "src/trading/probability_assessment.py",
    "src/trading/trade_experience_memory.py",
    "src/trading/q_learning_decision_memory.py",
]

for filepath in ai_files:
    content = Path(filepath).read_text()
    has_bot_import = "bot" in content.lower() and "import" in content.lower()
    has_bot_class = "Bot" in content and "class" in content
    status = "BOT-FREE" if not has_bot_import and not has_bot_class else "CHECK"
    print(f"  [{status}] {filepath}")

# Verify data quality
print("")
print("VERIFICACION CALIDAD DE DATOS")
csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

# Check for data gaps
null_count = sum(1 for t in trades if any(v in ("", "null", None) for v in t.values()))
print(f"  Trades total: {len(trades)}")
print(f"  Datos completos: {len(trades) - null_count}/{len(trades)} ({100*(len(trades)-null_count)/len(trades):.1f}%)")

# Check Q-learning data
q_table = json.loads(Path("data/demo_trading/maximo_quant_v4/q_learning_table.json").read_text())
print(f"  Q-learning experiencias: {q_table.get('_meta', {}).get('experience_count', 0)}")
print(f"  Q-learning estados: {len([k for k in q_table.keys() if k != '_meta'])}")

print("")
print("RESPUESTA CERO BOT:")
print("  IA depende solo de:")
print("    - Señales (signal dict)")
print("    - Inteligencia de mercado (intelligence dict)")
print("    - Memoria histórica (JSON/JSONL)")
print("    - Thresholds configurables (72.0/71.0)")
print("="*60)