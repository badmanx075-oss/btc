import ccxt
import pandas as pd
import numpy as np
import ta
import time
import requests
import os
from datetime import datetime

# Environment Variables se Token aur Chat ID uthayega (100% Safe)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5984456777").strip()

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("Bot Token missing!")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        print("Telegram push error:", e)

SYMBOL = 'BTC/USDT'
TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
LIMIT = 100

def get_exchange():
    try:
        ex = ccxt.binance({'enableRateLimit': True})
        ex.load_markets()
        return ex
    except Exception:
        try:
            ex = ccxt.kraken({'enableRateLimit': True})
            ex.load_markets()
            return ex
        except Exception:
            return ccxt.kucoin({'enableRateLimit': True})

exchange = get_exchange()

# Global state for tracking positions
locked_trade = None
tp1_hit = False

def fetch_tf_data(tf):
    try:
        sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
        candles = exchange.fetch_ohlcv(sym, timeframe=tf, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
        df['STOCH_K'] = stoch_rsi.stochrsi_k() * 100

        df['CCI'] = ta.trend.cci(df['high'], df['low'], df['close'], window=20)
        df['WILLR'] = ta.momentum.williams_r(df['high'], df['low'], df['close'], lbp=14)
        return df.bfill().ffill()
    except Exception:
        return None

print("24/7 Institutional Alert Background Engine Started...")
send_telegram("🚀 *24/7 CLOUD BOT ACTIVATED!*\nAapka automated bot ab cloud server par live hai. Mobile switch off ya screen lock hone par bhi Telegram alerts aate rahenge.")

while True:
    try:
        # Fetch 5m & 15m live feeds
        df_5m = fetch_tf_data('5m')
        df_15m = fetch_tf_data('15m')

        if df_5m is None or df_15m is None:
            time.sleep(10)
            continue

        sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
        ticker = exchange.fetch_ticker(sym)
        live_price = ticker['last'] if ticker and 'last' in ticker else df_5m.iloc[-1]['close']

        stoch_5m = df_5m.iloc[-1].get('STOCH_K', 50)
        stoch_15m = df_15m.iloc[-1].get('STOCH_K', 50)
        cci_5m = df_5m.iloc[-1].get('CCI', 0)
        cci_15m = df_15m.iloc[-1].get('CCI', 0)
        will_5m = df_5m.iloc[-1].get('WILLR', -50)

        early_short_cond = (stoch_5m >= 88 or stoch_15m >= 90) and (cci_5m > 130 or cci_15m > 130) and (will_5m >= -15)
        early_long_cond = (stoch_5m <= 15 or stoch_15m <= 18) and (cci_5m < -130 or cci_15m < -130) and (will_5m <= -85)

        # 1. New Trade Trigger
        if locked_trade is None:
            if early_short_cond:
                locked_trade = {
                    'type': 'SHORT', 'entry': live_price, 'sl': live_price + 280.0,
                    'tp1': live_price - 600.0, 'tp2': live_price - 1500.0, 'tp3': live_price - 2500.0,
                    'time': datetime.now().strftime("%H:%M:%S")
                }
                tp1_hit = False
                send_telegram(
                    f"🚨 *NEW BTC TRADE TRIGGERED!*\n\n"
                    f"⚡ *Type:* SHORT POSITION\n"
                    f"• *Entry:* `${live_price:,.1f}`\n"
                    f"• *Hard SL:* `${live_price + 280.0:,.1f}` (+280 pts risk)\n"
                    f"• *Target 1:* `${live_price - 600.0:,.1f}` (+600 pts)\n"
                    f"• *Target 2:* `${live_price - 1500.0:,.1f}` (+1,500 pts)\n"
                    f"• *Target 3:* `${live_price - 2500.0:,.1f}` (+2,500 pts)\n\n"
                    f"📊 *Confluence:* 15m StochRSI {stoch_15m:.0f} Peak Exhaustion."
                )
            elif early_long_cond:
                locked_trade = {
                    'type': 'LONG', 'entry': live_price, 'sl': live_price - 280.0,
                    'tp1': live_price + 600.0, 'tp2': live_price + 1500.0, 'tp3': live_price + 2500.0,
                    'time': datetime.now().strftime("%H:%M:%S")
                }
                tp1_hit = False
                send_telegram(
                    f"🚀 *NEW BTC TRADE TRIGGERED!*\n\n"
                    f"⚡ *Type:* LONG POSITION\n"
                    f"• *Entry:* `${live_price:,.1f}`\n"
                    f"• *Hard SL:* `${live_price - 280.0:,.1f}` (-280 pts risk)\n"
                    f"• *Target 1:* `${live_price + 600.0:,.1f}` (+600 pts)\n"
                    f"• *Target 2:* `${live_price + 1500.0:,.1f}` (+1,500 pts)\n"
                    f"• *Target 3:* `${live_price + 2500.0:,.1f}` (+2,500 pts)\n\n"
                    f"📊 *Confluence:* 15m StochRSI {stoch_15m:.0f} Oversold Bounce."
                )

        # 2. Tracking Active Trade Exits
        else:
            t = locked_trade
            is_long = t['type'] == 'LONG'
            pts = (live_price - t['entry']) if is_long else (t['entry'] - live_price)

            hit_sl = (live_price <= t['sl']) if is_long else (live_price >= t['sl'])
            hit_tp1 = (live_price >= t['tp1']) if is_long else (live_price <= t['tp1'])
            hit_tp2 = (live_price >= t['tp2']) if is_long else (live_price <= t['tp2'])

            if hit_tp1 and not tp1_hit:
                tp1_hit = True
                send_telegram(
                    f"🎯 *TARGET 1 REACHED (+600 PTS)*\n\n"
                    f"• *Trade:* {t['type']}\n"
                    f"• *Current Rate:* `${live_price:,.1f}`\n"
                    f"• *Profit:* +600 points\n"
                    f"• *Action:* Stop-Loss ko entry (`${t['entry']:,.1f}`) par move karein (Risk-Free)."
                )

            if hit_sl:
                send_telegram(
                    f"❌ *STOP-LOSS HIT IN THIS TRADE*\n\n"
                    f"• *Trade:* {t['type']}\n"
                    f"• *Entry:* `${t['entry']:,.1f}`\n"
                    f"• *Exit:* `${live_price:,.1f}`\n"
                    f"• *PnL:* -{abs(pts):.0f} Points\n"
                    f"• *Trade Rating:* ⭐ 1/5 (Risk Preserved at SL)\n"
                    f"• *Status:* Position closed. Scanning next opportunity."
                )
                locked_trade = None
                tp1_hit = False

            elif hit_tp2:
                send_telegram(
                    f"💰 *PROFIT TARGET 2 HIT IN THIS TRADE!*\n\n"
                    f"• *Trade:* {t['type']}\n"
                    f"• *Entry:* `${t['entry']:,.1f}`\n"
                    f"• *Exit:* `${live_price:,.1f}`\n"
                    f"• *Net Profit:* +{pts:.0f} Points captured\n"
                    f"• *Trade Rating:* ⭐⭐⭐⭐⭐ 5/5 (Master Setup Victory!)\n"
                    f"• *Status:* Profit locked. Ready for next cycle."
                )
                locked_trade = None
                tp1_hit = False

    except Exception as e:
        print("Loop error:", e)

    # 10 second delay between checks
    time.sleep(10)
