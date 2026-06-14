# AI Copy Trading Replication Guide

## Architecture
```
Your MT5 (Master) → AI Engine → API Platform → Client MT5 Terminals
```

## Setup

### 1. Master Account (Tu servidor)
```bash
# Your MT5 connects to the backend
# AI generates signals → Platform stores signals → Clients fetch signals
```

### 2. Client Setup (Clientes)

#### Install Requirements
```bash
pip install -r requirements.txt
```

#### Configure Client
Crear `client_config.json`:
```json
{
  "api_url": "https://tu-dominio.com",
  "token": "TOKEN_DEL_CLIENTE",
  "symbols": ["XAUUSDm", "EURUSDm"],
  "volume_multiplier": 1.0,
  "check_interval_seconds": 30
}
```

#### Run Client Agent
```bash
python -m src.cli.main client-replicate --config client_config.json
```

## API Endpoints

### Get Live Signal (Público)
```bash
GET /api/platform/ai/live-signal?symbol=XAUUSDm
```

Response:
```json
{
  "symbol": "XAUUSDm",
  "direction": "BUY",
  "setup_type": "OB_REJECTION",
  "entry_zone": {
    "entry_price": 2650.5,
    "stop_price": 2649.0,
    "target_price": 2655.0
  },
  "thresholds": {"min_score": 72.0, "armed_retest": 71.0},
  "replication_ready": true
}
```

### Evaluate Signal
```bash
POST /api/platform/ai/evaluate-replication
{
  "symbol": "XAUUSDm",
  "signal": {"direction": "BUY", "stop_price": 2649.0, "target_price": 2655.0},
  "intelligence": {"pulse_score": 85, "clarity_score": 75}
}
```

Response:
```json
{
  "decision": "EXECUTE",
  "score": 72.39,
  "can_execute": true,
  "staged_exit_plan": {
    "staged_levels": [
      {"level": "0.5R", "price": 2653.0, "close_fraction": 0.3},
      {"level": "0.7R", "price": 2652.8, "close_fraction": 0.4},
      {"level": "1.0R", "price": 2655.0, "close_fraction": 0.3}
    ]
  }
}
```

## Staged Exits for Clients

Los clientes pueden replicar los staged exits:

```python
# Ejemplo de replicación
if signal_confirmed:
    # Place main order
    order = mt5_order(volume=0.01, price=entry)
    
    # Set partial closes
    schedule_partial_close(at=0.5R, fraction=0.3)
    schedule_partial_close(at=0.7R, fraction=0.4)
    # Trail rest to target
```

## Security
- Tokens únicos por cliente
- Rate limiting en API
- Validación de spreads y horarios
- Stop override para protección