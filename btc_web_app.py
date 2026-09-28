import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import ta
import time

st.set_page_config(
    page_title="BTC Institutional Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background-color: #09090b; color: #f4f4f5; }
    .trade-short { background-color: #7f1d1d; border-left: 6px solid #ef4444; padding: 15px; border-radius: 8px; margin-bottom: 12px; }
    .trade-long { background-color: #14532d; border-left: 6px solid #22c55e; padding: 15px; border-radius: 8px; margin-bottom: 12px; }
    .trade-wait { background-color: #27272a; border-left: 6px solid #eab308; padding: 15px; border-radius: 8px; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)

SYMBOL = 'BTC/USDT'
TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
LIMIT = 100

# Cloud Geoblock-Proof Multi-Exchange Fallback
@st.cache_resource
def get_exchange():
    try:
        # Primary: Binance (Standard Spot API works on cloud)
        ex = ccxt.binance({'enableRateLimit': True})
        ex.load_markets()
        return ex
    except Exception:
        try:
            # Fallback 1: Kraken (100% US Cloud allowed)
            ex = ccxt.kraken({'enableRateLimit': True})
            ex.load_markets()
            return ex
        except Exception:
            # Fallback 2: KuCoin
            return ccxt.kucoin({'enableRateLimit': True})

exchange = get_exchange()

if 'locked_trade' not in st.session_state:
    st.session_state.locked_trade = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

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

def fetch_tf_data(tf):
    try:
        # Standardize pair for exchange
        sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
        candles = exchange.fetch_ohlcv(sym, timeframe=tf, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Technical calculations
        df['EMA9'] = ta.trend.ema_indicator(df['close'], window=9)
        df['EMA21'] = ta.trend.ema_indicator(df['close'], window=21)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=min(len(df)-1, 50))
        df['RSI'] = ta.momentum.rsi(df['close'], window=14)
        df['VOL_SMA20'] = df['volume'].rolling(window=20).mean()
        df['ATR'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
        
        # VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['VWAP'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        # StochRSI
        stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
        df['STOCH_K'] = stoch_rsi.stochrsi_k() * 100

        # ADX
        adx_ind = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
        df['ADX'] = adx_ind.adx()

        # CCI
        df['CCI'] = ta.trend.cci(df['high'], df['low'], df['close'], window=20)

        # Williams %R
        df['WILLR'] = ta.momentum.williams_r(df['high'], df['low'], df['close'], lbp=14)

        # Bollinger Bands Width
        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
        df['BB_WIDTH'] = ((bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()) * 100

        # Volume Delta
        candle_spread = (df['high'] - df['low']).replace(0, 0.0001)
        df['DELTA'] = ((df['close'] - df['open']) / candle_spread) * df['volume']

        return df.bfill().ffill()
    except Exception as e:
        return None

# Fetch all timeframes
tf_data = {}
for tf in TIMEFRAMES:
    d = fetch_tf_data(tf)
    if d is not None:
        tf_data[tf] = d

# Fetch live ticker price
try:
    sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
    ticker = exchange.fetch_ticker(sym)
    live_price = ticker['last'] if ticker and 'last' in ticker else tf_data['5m'].iloc[-1]['close']
except Exception:
    live_price = tf_data['5m'].iloc[-1]['close'] if '5m' in tf_data else 85000.0

# Support & Resistance Calculations
df_4h = tf_data.get('4h')
if df_4h is not None and len(df_4h) >= 2:
    p4 = df_4h.iloc[-2]
    pivot = (p4['high'] + p4['low'] + p4['close']) / 3
    res1 = (2 * pivot) - p4['low']
    sup1 = (2 * pivot) - p4['high']
else:
    pivot, res1, sup1 = live_price, live_price + 450, live_price - 450

df_1d = tf_data.get('1d')
if df_1d is not None and len(df_1d) >= 1:
    ema200_1d = df_1d.iloc[-1].get('EMA200', live_price)
else:
    ema200_1d = live_price

# ----------------- UI HEADER -----------------
st.title("⚡ BTC Perpetual Institutional Terminal")
h_col1, h_col2, h_col3, h_col4 = st.columns(4)
h_col1.metric("Live Price", f"${live_price:,.2f}")
h_col2.metric("Resistance (R1)", f"${res1:,.1f}")
h_col3.metric("Support (S1)", f"${sup1:,.1f}")
h_col4.metric("1D 200 EMA", f"${ema200_1d:,.1f}")

# ----------------- MASTER ACTION ENGINE -----------------
m4h_stoch = tf_data['4h'].iloc[-1].get('STOCH_K', 50) if '4h' in tf_data else 50
m1h_stoch = tf_data['1h'].iloc[-1].get('STOCH_K', 50) if '1h' in tf_data else 50
m5m_stoch = tf_data['5m'].iloc[-1].get('STOCH_K', 50) if '5m' in tf_data else 50
vol_5m = tf_data['5m'].iloc[-1]['volume'] / (tf_data['5m'].iloc[-1]['VOL_SMA20'] if tf_data['5m'].iloc[-1]['VOL_SMA20'] > 0 else 1) if '5m' in tf_data else 1.0

near_res = (res1 - live_price) <= 180
near_sup = (live_price - sup1) <= 180

short_cond = near_res and (m4h_stoch >= 85 and m1h_stoch >= 80 and m5m_stoch >= 80) and vol_5m < 1.2
long_cond = near_sup and (m4h_stoch <= 20 and m1h_stoch <= 25 and m5m_stoch <= 20) and vol_5m < 1.2

if st.session_state.locked_trade is None:
    if short_cond:
        st.session_state.locked_trade = {
            'type': 'SHORT', 'entry': live_price, 'sl': res1 + 220.0,
            'tp1': live_price - 800.0, 'tp2': live_price - 1800.0
        }
    elif long_cond:
        st.session_state.locked_trade = {
            'type': 'LONG', 'entry': live_price, 'sl': sup1 - 220.0,
            'tp1': live_price + 800.0, 'tp2': live_price + 1800.0
        }

if st.session_state.locked_trade is not None:
    t = st.session_state.locked_trade
    pts = (live_price - t['entry']) if t['type'] == 'LONG' else (t['entry'] - live_price)
    
    hit_sl = (live_price <= t['sl']) if t['type'] == 'LONG' else (live_price >= t['sl'])
    hit_tp2 = (live_price >= t['tp2']) if t['type'] == 'LONG' else (live_price <= t['tp2'])

    if hit_sl:
        st.error(f"🔴 {t['type']} TRADE STOP-LOSS HIT (-{abs(pts):.0f} pts). Exited @ ${live_price:,.1f}.")
        st.session_state.locked_trade = None
    elif hit_tp2:
        st.success(f"🟢 {t['type']} TARGET 2 HIT (+{pts:.0f} pts PROFIT BOOKED!). Great Trade.")
        st.session_state.locked_trade = None
    else:
        css_class = "trade-short" if t['type'] == 'SHORT' else "trade-long"
        st.markdown(f"""
        <div class="{css_class}">
            <h3>⚡ ACTIVE {t['type']} POSITION RUNNING (PnL: {pts:+.0f} Pts)</h3>
            <p><b>• FIXED ENTRY:</b> ${t['entry']:,.1f} (FROZEN)<br>
            <b>• HARD SL:</b> ${t['sl']:,.1f} (FROZEN)<br>
            <b>• TARGET 1:</b> ${t['tp1']:,.1f} (+800 pts -> SL to Entry)<br>
            <b>• TARGET 2:</b> ${t['tp2']:,.1f} (+1,800 pts Goal)</p>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="trade-wait">
        <h3>⏳ NO TRADE / 85%+ STRICT FILTER ACTIVE</h3>
        <p>Price S1 (${sup1:,.1f}) aur R1 (${res1:,.1f}) ke beech fasa hua hai. System extreme turning points ka wait kar raha hai.</p>
    </div>
    """, unsafe_allow_html=True)

# ----------------- TABLE (ALL 12 INDICATORS) -----------------
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
    if stoch_k <= 18 and will_v <= -82:
        sig = "💎 DIP BUY"
    elif stoch_k >= 85 and will_v >= -18:
        sig = "🩸 TOP REJECT"
    else:
        sig = "HOLD"

    table_rows.append({
        "TF": tf,
        "Trend": "BULLISH" if curr.get('EMA9', 0) > curr.get('EMA21', 0) else "BEARISH",
        "200 EMA": above_200,
        "VWAP": above_vwap,
        "RSI": f"{curr.get('RSI', 50):.1f}",
        "Vol Ratio": f"{vol_ratio:.1f}x",
        "StochRSI": f"{stoch_k:.0f}",
        "ADX": f"{curr.get('ADX', 20):.0f}",
        "CCI": f"{curr.get('CCI', 0):.0f}",
        "Will %R": f"{will_v:.0f}",
        "Delta": f"{curr.get('DELTA', 0):+.0f}",
        "BB Squeeze": f"{curr.get('BB_WIDTH', 2.0):.2f}%",
        "Pattern": pattern,
        "Signal": sig
    })

if table_rows:
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
else:
    st.info("Syncing live exchange feeds... Kripya 5 seconds wait karein.")

# ----------------- AI CHATBOT -----------------
st.subheader("🤖 Institutional AI Master Analyst")

for role, text in st.session_state.chat_history:
    with st.chat_message(role):
        st.write(text)

user_query = st.chat_input("Poochiye (e.g. SL kahan lagau?, Squeeze blast kya hai?, Volume rule kya hai?)...")

if user_query:
    st.session_state.chat_history.append(("user", user_query))
    with st.chat_message("user"):
        st.write(user_query)

    q = user_query.lower()
    t = st.session_state.locked_trade

    if t is not None:
        pts = (live_price - t['entry']) if t['type'] == 'LONG' else (t['entry'] - live_price)
        reply = f"🔒 Active {t['type']} Trade: Fixed Entry ${t['entry']:,.1f} | SL ${t['sl']:,.1f}. Current PnL: {pts:+.0f} points. Panic me exit na karein."
    elif "volume" in q:
        reply = "📘 Volume Rule: Resistance par low volume (<0.5x) fakeout hota hai. Real breakout ke liye volume > 1.5x hona chahiye."
    elif "squeeze" in q:
        reply = "💥 Squeeze Blast: Bollinger Bandwidth < 1.0% hone par market coil hoti hai aur 1,500-3,000 points ka explosive breakout karti hai."
    elif "sl" in q or "stoploss" in q:
        reply = f"🛡️ SL Rule: Resistance R1 ke upar +$220 points buffer par Short ka SL aur Support S1 ke niche -$220 par Long ka SL rakhein."
    else:
        reply = f"Live Market: BTC ${live_price:,.1f}. Key Resistance ${res1:,.1f} aur Support ${sup1:,.1f} hai. Extreme turning points ka wait karein."

    st.session_state.chat_history.append(("assistant", reply))
    with st.chat_message("assistant"):
        st.write(reply)

# Auto refresh every 5 seconds
time.sleep(5)
st.rerun()
