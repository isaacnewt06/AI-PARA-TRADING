import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

symbol = "XAUUSDm"

timeframes = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "H1": mt5.TIMEFRAME_H1
}

mt5.initialize()

for name, tf in timeframes.items():
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 5000)
    
    if rates is None:
        print(f"Error descargando {symbol} {name}")
        continue
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    df = df[['time','open','high','low','close','tick_volume']]
    df.columns = ['time','open','high','low','close','volume']
    
    file_path = f"data/backtests/input/{symbol}_{name}.csv"
    df.to_csv(file_path, index=False)
    
    print(f"Exportado: {file_path}")

mt5.shutdown()
