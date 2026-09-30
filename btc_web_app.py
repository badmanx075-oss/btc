import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import ta
import time
import requests
import threading
from datetime import datetime, timezone, timedelta

st.set_page_config(
    page_title="BTC Institutional Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #09090b; color: #f4f4f5; }
    .trade-short { background-color: #7f1d1d; border-left: 6px solid #ef4444; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
    .trade-long { background-color: #14532d; border-left: 6px solid #22c55e; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
    .trade-wait { background-color: #27272a; border-left: 6px solid #eab308; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)

# IST Indian Standard Timezone
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_time():
    return datetime.now(IST).strftime("%I:%M:%S %p")

# ================= TELEGRAM SECURE CONFIG =================
raw_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
raw_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "5984456777")

TELEGRAM_BOT_TOKEN = str(raw_token).strip() if raw_token else ""
TELEGRAM_CHAT_ID = str(raw_chat_id).strip()

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 10:
        return False, "Bot Token missing in Secrets"
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload, timeout=4)
        resp = res.json()
        if res.status_code == 200 and resp.get("ok"):
            return True, "Delivered"
        else:
            return False, resp.get("description", "Error")
    except Exception as e:
        return False, str(e)

# ================= ULTRA-FAST 1-SEC PRICE API =================
def get_live_crypto_price():
    # 1. Bybit Perpetual Linear Fast API
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT", timeout=1.2)
        if r.status_code == 200:
            d = r.json()
            list_res = d.get("result", {}).get("list", [])
            if list_res and "lastPrice" in list_res[0]:
                return float(list_res[0]["lastPrice"])
    except Exception:
        pass

    # 2. Coinbase Pro Live Price
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=1.2)
        if r.status_code == 200:
            d = r.json()
            return float(d["data"]["amount"])
    except Exception:
        pass

    # 3. Binance Futures Fast Mirror
    try:
        r = requests.get("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", timeout=1.2)
        if r.status_code == 200:
            d = r.json()
            if "price" in d:
                return float(d["price"])
    except Exception:
        pass

    return None

# ================= PERSISTENT SHARED STATE =================
@st.cache_resource
def get_shared_system():
    init_p = get_live_crypto_price() or 84000.0
    return {
        'trade': None,
        'tp1_hit': False,
        'trade_history': [],
        'thread_running': False,
        'last_price': init_p,
        'matrix_cache': {},
        'matrix_lock': threading.Lock(),
        'last_fetch': 0
    }

shared = get_shared_system()
TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']

@st.cache_resource
def get_exchange():
    for name in ['kraken', 'kucoin', 'bybit']:
        try:
            ex = getattr(ccxt, name)({'enableRateLimit': True, 'timeout': 4000})
            ex.load_markets()
            return ex
        except Exception:
            continue
    return ccxt.kraken({'enableRateLimit': True})

exchange = get_exchange()

def detect_candlestick_pattern(row, prev_row):
    o, h, l, c = row['open'], row['high'], row['low'], row['close']
    po, pc = prev_row['open'], prev_row['close']
    body = abs(c - o)
    candle_range = h - l if (h - l) > 0 else 0.0001
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if lower_wick >= (2 * body) and upper_wick <= (0.2 * body) and c > o:
        return "Hammer"
    elif upper_wick >= (2 * body) and lower_wick <= (0.2 * body) and c < o:
        return "Shooting Star"
    elif c > o and pc < po and c >= po and o <= pc and body > abs(pc - po):
        return "Bullish Engulf"
    elif c < o and pc > po and o >= pc and c <= po and body > abs(pc - po):
        return "Bearish Engulf"
    elif body <= (0.1 * candle_range):
        return "Doji"
    return "Normal"

def fetch_tf_series(ex, tf):
    try:
        bybit_tf_map = {'5m': '5', '15m': '15', '30m': '30', '1h': '60', '2h': '120', '4h': '240', '1d': 'D'}
        interval = bybit_tf_map.get(tf, '5')
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval={interval}&limit=40"
        r = requests.get(url, timeout=2.5)
        if r.status_code == 200:
            raw = r.json().get("result", {}).get("list", [])
            if raw:
                raw.reverse()
                formatted = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in raw]
                df = pd.DataFrame(formatted, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            else:
                return None
        else:
            sym = 'BTC/USDT' if 'BTC/USDT' in ex.markets else 'BTC/USD'
            candles = ex.fetch_ohlcv(sym, timeframe=tf, limit=40)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        if df.empty:
            return None

        df['EMA9'] = ta.trend.ema_indicator(df['close'], window=9)
        df['EMA21'] = ta.trend.ema_indicator(df['close'], window=21)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=min(len(df)-1, 40))
        df['RSI'] = ta.momentum.rsi(df['close'], window=14)
        df['VOL_SMA20'] = df['volume'].rolling(window=20).mean()
        df['ATR'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['VWAP'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
        df['STOCH_K'] = stoch_rsi.stochrsi_k() * 100

        adx_ind = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
        df['ADX'] = adx_ind.adx()

        df['CCI'] = ta.trend.cci(df['high'], df['low'], df['close'], window=20)
        df['WILLR'] = ta.momentum.williams_r(df['high'], df['low'], df['close'], lbp=14)

        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
        df['BB_HIGH'] = bb.bollinger_hband()
        df['BB_LOW'] = bb.bollinger_lband()
        df['BB_WIDTH'] = ((df['BB_HIGH'] - df['BB_LOW']) / bb.bollinger_mavg()) * 100

        candle_spread = (df['high'] - df['low']).replace(0, 0.0001)
        df['DELTA'] = ((df['close'] - df['open']) / candle_spread) * df['volume']

        return df.bfill().ffill()
    except Exception:
        return None

# ================= 24/7 BACKGROUND DAEMON THREAD =================
def cloud_daemon():
    bg_ex = get_exchange()
    while True:
        try:
            live_p = get_live_crypto_price()
            if live_p is not None:
                shared['last_price'] = live_p
            else:
                live_p = float(shared['last_price'])

            # Active Trade Check
            t = shared['trade']
            if t is not None:
                is_long = "LONG" in t['type']
                pts = (live_p - t['entry']) if is_long else (t['entry'] - live_p)

                hit_sl = (live_p <= t['sl']) if is_long else (live_p >= t['sl'])
                hit_tp1 = (live_p >= t['tp1']) if is_long else (live_p <= t['tp1'])
                hit_tp2 = (live_p >= t['tp2']) if is_long else (live_p <= t['tp2'])

                if hit_tp1 and not shared['tp1_hit']:
                    shared['tp1_hit'] = True
                    send_telegram(
                        f"🎯 *TARGET 1 REACHED!*\n\n"
                        f"• Trade: {t['type']}\n"
                        f"• Rate: `${live_p:,.1f}`\n"
                        f"• Action: Stop-Loss ko entry (`${t['entry']:,.1f}`) par move karein."
                    )

                if hit_sl:
                    send_telegram(
                        f"❌ *STOP-LOSS HIT IN THIS TRADE*\n\n"
                        f"• Trade: {t['type']}\n"
                        f"• Entry: `${t['entry']:,.1f}`\n"
                        f"• Exit: `${live_p:,.1f}`\n"
                        f"• Net PnL: -{abs(pts):.0f} Points\n"
                        f"• Rating: ⭐ 1/5 (Risk Preserved at SL)"
                    )
                    shared['trade_history'].insert(0, {
                        "Time": t.get('time', '--'),
                        "Type": t['type'],
                        "Entry": f"${t['entry']:,.1f}",
                        "Exit": f"${live_p:,.1f}",
                        "PnL": f"-{abs(pts):.0f} pts",
                        "Result": "❌ LOSS (SL HIT)",
                        "Rating": "⭐ 1/5"
                    })
                    shared['trade'] = None
                    shared['tp1_hit'] = False

                elif hit_tp2:
                    send_telegram(
                        f"💰 *PROFIT TARGET 2 HIT IN THIS TRADE!*\n\n"
                        f"• Trade: {t['type']}\n"
                        f"• Entry: `${t['entry']:,.1f}`\n"
                        f"• Exit: `${live_p:,.1f}`\n"
                        f"• Net Profit: +{pts:.0f} Points captured\n"
                        f"• Rating: ⭐⭐⭐⭐⭐ 5/5 (Master Setup Victory!)"
                    )
                    shared['trade_history'].insert(0, {
                        "Time": t.get('time', '--'),
                        "Type": t['type'],
                        "Entry": f"${t['entry']:,.1f}",
                        "Exit": f"${live_p:,.1f}",
                        "PnL": f"+{pts:.0f} pts",
                        "Result": "🟢 PROFIT (TP2 HIT)",
                        "Rating": "⭐⭐⭐⭐⭐ 5/5"
                    })
                    shared['trade'] = None
                    shared['tp1_hit'] = False

            # Update indicators every 10 seconds in background
            now = time.time()
            if now - shared['last_fetch'] > 10:
                temp_map = {}
                for tf in TIMEFRAMES:
                    df_item = fetch_tf_series(bg_ex, tf)
                    if df_item is not None:
                        temp_map[tf] = df_item
                with shared['matrix_lock']:
                    shared['matrix_cache'] = temp_map
                    shared['last_fetch'] = now

                # Real automatic entry scanner
                if shared['trade'] is None and '5m' in temp_map and '15m' in temp_map:
                    s5 = temp_map['5m'].iloc[-1].get('STOCH_K', 50)
                    s15 = temp_map['15m'].iloc[-1].get('STOCH_K', 50)
                    c5 = temp_map['5m'].iloc[-1].get('CCI', 0)
                    c15 = temp_map['15m'].iloc[-1].get('CCI', 0)
                    w5 = temp_map['5m'].iloc[-1].get('WILLR', -50)

                    if (s5 >= 88 or s15 >= 90) and (c5 > 130 or c15 > 130) and (w5 >= -15):
                        shared['trade'] = {
                            'type': 'SHORT', 'entry': live_p, 'sl': live_p + 280.0,
                            'tp1': live_p - 600.0, 'tp2': live_p - 1500.0, 'tp3': live_p - 2500.0,
                            'time': get_ist_time()
                        }
                        shared['tp1_hit'] = False
                        send_telegram(f"🚨 *NEW BTC SHORT TRIGGERED*\n• Entry: `${live_p:,.1f}`\n• SL: `${live_p+280:,.1f}`\n• TP1: `${live_p-600:,.1f}`")

                    elif (s5 <= 15 or s15 <= 18) and (c5 < -130 or c15 < -130) and (w5 <= -85):
                        shared['trade'] = {
                            'type': 'LONG', 'entry': live_p, 'sl': live_p - 280.0,
                            'tp1': live_p + 600.0, 'tp2': live_p + 1500.0, 'tp3': live_p + 2500.0,
                            'time': get_ist_time()
                        }
                        shared['tp1_hit'] = False
                        send_telegram(f"🚀 *NEW BTC LONG TRIGGERED*\n• Entry: `${live_p:,.1f}`\n• SL: `${live_p-280:,.1f}`\n• TP1: `${live_p+600:,.1f}`")

        except Exception:
            pass

        time.sleep(1)

if not shared['thread_running']:
    t_daemon = threading.Thread(target=cloud_daemon, daemon=True)
    t_daemon.start()
    shared['thread_running'] = True

# ================= 1-SEC INSTANT PRICE FETCH =================
fresh_p = get_live_crypto_price()
if fresh_p is not None:
    live_price = fresh_p
    shared['last_price'] = fresh_p
else:
    live_price = float(shared['last_price'])

with shared['matrix_lock']:
    tf_data = dict(shared['matrix_cache'])

df_5m = tf_data.get('5m')
df_15m = tf_data.get('15m')
recent_high = max(df_5m['high'].iloc[-20:].max() if df_5m is not None else live_price + 300, live_price + 150)
recent_low = min(df_5m['low'].iloc[-20:].min() if df_5m is not None else live_price - 300, live_price - 150)

df_1d = tf_data.get('1d')
ema200_1d = df_1d.iloc[-1].get('EMA200', live_price) if df_1d is not None and len(df_1d) >= 1 else live_price

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.header("⚙️ 24/7 Cloud Daemon")
    st.success("🟢 Perpetual Loop: ACTIVE (1s Tick)")
    st.caption(f"Telegram Target ID: `{TELEGRAM_CHAT_ID}`")
    st.info(f"⏱️ Live IST: **{get_ist_time()}**")

    if st.button("🔔 Send Force Test Alert"):
        ok, reason = send_telegram("✅ *Terminal Test Message*\nAapka Telegram alert pipeline bilkul active hai!")
        if ok:
            st.success("Test alert send ho gaya!")
        else:
            st.error(f"Failed: {reason}")
            
    st.divider()
    st.subheader("🧪 Live Auto-Trigger Tester")
    st.caption("Yeh dummy trade lock karega aur agle 8-15 points ke movement par TP1/TP2 ya SL ka notification auto bhejega.")
    
    if st.button("🚀 Trigger Instant Dummy Trade"):
        shared['trade'] = {
            'type': 'LONG (TEST)',
            'entry': live_price,
            'sl': live_price - 6.0,
            'tp1': live_price + 6.0,
            'tp2': live_price + 12.0,
            'time': get_ist_time()
        }
        shared['tp1_hit'] = False
        send_telegram(
            f"🧪 *[TEST TRADE TRIGGERED!]*\n\n"
            f"• *Type:* LONG (SIMULATION)\n"
            f"• *Entry:* `${live_price:,.1f}`\n"
            f"• *Test SL:* `${live_price - 6.0:,.1f}`\n"
            f"• *Test TP1:* `${live_price + 6.0:,.1f}`\n\n"
            f"⚡ Testing Auto Alert Pipeline..."
        )
        st.success("Dummy trade lock ho gayi!")

    if st.button("⏹️ Reset/Cancel Active Trade"):
        shared['trade'] = None
        shared['tp1_hit'] = False
        st.info("Active trade reset kar di gayi hai.")

# ----------------- UI HEADER -----------------
st.title("⚡ BTC Perpetual Institutional Terminal (24/7 Cloud Guard)")
h_col1, h_col2, h_col3, h_col4 = st.columns(4)
h_col1.metric("Live Price (Perpetual)", f"${live_price:,.2f}")
h_col2.metric("Local High (Resistance)", f"${recent_high:,.1f}")
h_col3.metric("Local Low (Support)", f"${recent_low:,.1f}")
h_col4.metric("1D 200 EMA", f"${ema200_1d:,.1f}")

# ----------------- ACTIVE POSITION CARD -----------------
active_t = shared['trade']
if active_t is not None:
    is_long = "LONG" in active_t['type']
    pts = (live_price - active_t['entry']) if is_long else (active_t['entry'] - live_price)
    css_class = "trade-long" if is_long else "trade-short"
    tp1_status = "✅ HIT (SL at Entry)" if shared['tp1_hit'] else "[+600 pts -> Shift SL]"
    
    st.markdown(f"""
    <div class="{css_class}">
        <h3>⚡ ACTIVE {active_t['type']} POSITION RUNNING (PnL: {pts:+.0f} Pts)</h3>
        <p><b>• FIXED ENTRY:</b> ${active_t['entry']:,.1f} (FROZEN)<br>
        <b>• HARD SL:</b> ${active_t['sl']:,.1f} (FROZEN)<br>
        <b>• TARGET 1 (TP1):</b> ${active_t['tp1']:,.1f} {tp1_status}<br>
        <b>• TARGET 2 (TP2):</b> ${active_t['tp2']:,.1f} [+1,500 pts Main Goal]<br>
        <b>• RUNNER TARGET (TP3):</b> ${active_t.get('tp3', active_t['tp2']):,.1f} [+2,500 pts Mega Runway]</p>
    </div>
    """, unsafe_allow_html=True)
else:
    stoch_5m = df_5m.iloc[-1].get('STOCH_K', 50) if df_5m is not None else 50
    stoch_15m = df_15m.iloc[-1].get('STOCH_K', 50) if df_15m is not None else 50
    cci_5m = df_5m.iloc[-1].get('CCI', 0) if df_5m is not None else 0
    st.markdown(f"""
    <div class="trade-wait">
        <h3>⏳ SCANNING EARLY TURNING POINT (5m/15m Extreme Hunter)</h3>
        <p>Current 5m StochRSI: {stoch_5m:.0f} | 15m StochRSI: {stoch_15m:.0f} | CCI: {cci_5m:.0f}.<br>
        Extreme saturation aate hi Telegram alert aur screen par entry 24/7 background engine lock karega.</p>
    </div>
    """, unsafe_allow_html=True)

# ----------------- TABLE (12 INDICATORS LIVE) -----------------
st.subheader("📊 Multi-Timeframe Matrix (All 12 Indicators Live)")

table_rows = []
for tf in TIMEFRAMES:
    if tf not in tf_data or tf_data[tf] is None or tf_data[tf].empty:
        continue
    df = tf_data[tf]
    curr = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else curr

    vol_sma = curr.get('VOL_SMA20', 1)
    vol_sma = vol_sma if vol_sma > 0 else 1
    vol_ratio = curr['volume'] / vol_sma
    above_200 = "Above" if curr['close'] >= curr.get('EMA200', curr['close']) else "Below"
    above_vwap = "Above" if curr['close'] >= curr.get('VWAP', curr['close']) else "Below"
    pattern = detect_candlestick_pattern(curr, prev)

    stoch_k = curr.get('STOCH_K', 50.0)
    will_v = curr.get('WILLR', -50.0)
    cci_val = curr.get('CCI', 0.0)

    if (stoch_k <= 18 or will_v <= -85) and cci_val < -100:
        sig = "💎 EARLY BUY DIP"
    elif (stoch_k >= 85 or will_v >= -15) and cci_val > 100:
        sig = "🩸 EARLY TOP REJECT"
    else:
        sig = "HOLD/WAIT"

    table_rows.append({
        "TF": tf,
        "Trend": "BULLISH" if curr.get('EMA9', 0) > curr.get('EMA21', 0) else "BEARISH",
        "200 EMA": above_200,
        "VWAP": above_vwap,
        "RSI": f"{curr.get('RSI', 50):.1f}",
        "Vol Ratio": f"{vol_ratio:.1f}x",
        "StochRSI": f"{stoch_k:.0f}",
        "ADX": f"{curr.get('ADX', 20):.0f}",
        "CCI": f"{cci_val:.0f}",
        "Will %R": f"{will_v:.0f}",
        "Delta": f"{curr.get('DELTA', 0):+.0f}",
        "BB Squeeze": f"{curr.get('BB_WIDTH', 2.0):.2f}%",
        "Pattern": pattern,
        "Signal": sig
    })

if table_rows:
    st.dataframe(pd.DataFrame(table_rows), hide_index=True)
else:
    st.info("Syncing 12-indicator multi-timeframe matrix in background...")

# ----------------- CLOSED TRADES JOURNAL -----------------
st.subheader("📜 Closed Trades Performance Journal")
if shared['trade_history']:
    st.dataframe(pd.DataFrame(shared['trade_history']), hide_index=True)
else:
    st.info("Pehli trade close hone par uski Entry, Exit, PnL aur Star Rating yahan automatically record ho jayegi.")

# ----------------- AI CHATBOT -----------------
st.subheader("🤖 Institutional AI Master Analyst")

if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

for role, text in st.session_state.chat_history:
    with st.chat_message(role):
        st.write(text)

user_query = st.chat_input("Poochiye (e.g. Abhi trade lu ya wait karu?, SL kahan lagau?)...")

if user_query:
    st.session_state.chat_history.append(("user", user_query))
    with st.chat_message("user"):
        st.write(user_query)

    q = user_query.lower()
    t = shared['trade']

    if t is not None:
        pts = (live_price - t['entry']) if "LONG" in t['type'] else (t['entry'] - live_price)
        reply = "Active " + str(t['type']) + " Sniper Position: Entry $" + f"{t['entry']:,.1f}" + " \vert{} SL $" + f"{t['sl']:,.1f}" + ". Current PnL: " + f"{pts:+.0f}" + " pts."
    else:
        s5 = df_5m.iloc[-1].get('STOCH_K', 50) if df_5m is not None else 50
        c5 = df_5m.iloc[-1].get('CCI', 0) if df_5m is not None else 0
        if s5 >= 85 and c5 > 120:
            reply = f"Market Overheated: 5M StochRSI {s5:.0f} aur CCI {c5:.0f} par hai. Top rejection short entry zone active hai."
        elif s5 <= 18 and c5 < -120:
            reply = f"Dip Buying Opportunity: 5M StochRSI {s5:.0f} oversold hai. Bounce ke liye Long entry favoured hai."
        else:
            reply = f"Live Market: BTC Perpetual ${live_price:,.1f}. Momentum scanning chal raha hai. Turning point aate hi 24/7 Cloud engine Telegram par notification push karega."

    st.session_state.chat_history.append(("assistant", reply))
    with st.chat_message("assistant"):
        st.write(reply)

# EXACT 1-SECOND TICK REFRESH
time.sleep(1)
st.rerun()
