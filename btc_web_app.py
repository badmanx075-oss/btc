import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time

# Page Configuration for Mobile & Desktop
st.set_page_config(
    page_title="BTC Institutional Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Dark Trading CSS
st.markdown("""
<style>
    .stApp {
        background-color: #09090b;
        color: #f4f4f5;
    }
    .metric-card {
        background-color: #18181b;
        border: 1px solid #27272a;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .trade-short {
        background-color: #7f1d1d;
        border-left: 6px solid #ef4444;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
    .trade-long {
        background-color: #14532d;
        border-left: 6px solid #22c55e;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
    .trade-wait {
        background-color: #27272a;
        border-left: 6px solid #eab308;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

SYMBOL = 'BTC/USDT'
TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
LIMIT = 100

@st.cache_resource
def get_exchange():
    return ccxt.binance({
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })

exchange = get_exchange()

# Persistent state across auto-refreshes
if 'locked_trade' not in st.session_state:
    st.session_state.locked_trade = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

def detect_candlestick_pattern(row, prev_row, tf):
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
        candles = exchange.fetch_ohlcv(SYMBOL, timeframe=tf, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA9'] = ta.ema(df['close'], length=9)
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['EMA200'] = ta.ema(df['close'], length=min(len(df)-1, 200))
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['VOL_SMA20'] = ta.sma(df['volume'], length=20)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['VWAP'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        st_ind = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
        df['SUPERTREND_DIR'] = st_ind.iloc[:, 1] if st_ind is not None and not st_ind.empty else 0

        stoch = ta.stochrsi(df['close'], length=14, rsi_length=14, k=3, d=3)
        df['STOCH_K'] = stoch.iloc[:, 0] if stoch is not None and not stoch.empty else 50.0

        adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
        df['ADX'] = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else 20.0

        cci_df = ta.cci(df['high'], df['low'], df['close'], length=20)
        df['CCI'] = cci_df if cci_df is not None and not cci_df.empty else 0.0

        will_df = ta.willr(df['high'], df['low'], df['close'], length=14)
        df['WILLR'] = will_df if will_df is not None and not will_df.empty else -50.0

        bb = ta.bbands(df['close'], length=20, std=2)
        df['BB_WIDTH'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1] * 100 if bb is not None else 2.0

        candle_spread = df['high'] - df['low']
        candle_spread = candle_spread.replace(0, 0.0001)
        df['DELTA'] = ((df['close'] - df['open']) / candle_spread) * df['volume']

        return df
    except Exception:
        return None

# Fetch Data Across All 7 Timeframes
tf_data = {}
for tf in TIMEFRAMES:
    d = fetch_tf_data(tf)
    if d is not None:
        tf_data[tf] = d

try:
    ticker = exchange.fetch_ticker(SYMBOL)
    live_price = ticker['last']
except Exception:
    live_price = tf_data['5m'].iloc[-1]['close'] if '5m' in tf_data else 85000.0

# Support / Resistance from 4H
df_4h = tf_data.get('4h')
if df_4h is not None and len(df_4h) >= 2:
    p4 = df_4h.iloc[-2]
    pivot = (p4['high'] + p4['low'] + p4['close']) / 3
    res1 = (2 * pivot) - p4['low']
    sup1 = (2 * pivot) - p4['high']
else:
    pivot, res1, sup1 = live_price, live_price + 400, live_price - 400

# 1D Macro Indicators
df_1d = tf_data.get('1d')
if df_1d is not None and len(df_1d) >= 1:
    ema200_1d = df_1d.iloc[-1].get('EMA200', live_price)
    vwap_1d = df_1d.iloc[-1].get('VWAP', live_price)
else:
    ema200_1d, vwap_1d = live_price, live_price

# ----------------- HEADER BAR -----------------
st.title("⚡ BTC Perpetual Institutional Terminal")
h_col1, h_col2, h_col3, h_col4 = st.columns(4)
h_col1.metric("Live Price", f"${live_price:,.2f}")
h_col2.metric("Resistance (R1)", f"${res1:,.1f}")
h_col3.metric("Support (S1)", f"${sup1:,.1f}")
h_col4.metric("1D Macro 200 EMA", f"${ema200_1d:,.1f}")

# ----------------- ACTION CARD LOGIC -----------------
m4h_stoch = tf_data['4h'].iloc[-1].get('STOCH_K', 50) if '4h' in tf_data else 50
m1h_stoch = tf_data['1h'].iloc[-1].get('STOCH_K', 50) if '1h' in tf_data else 50
m5m_stoch = tf_data['5m'].iloc[-1].get('STOCH_K', 50) if '5m' in tf_data else 50
vol_5m = tf_data['5m'].iloc[-1]['volume'] / (tf_data['5m'].iloc[-1]['VOL_SMA20'] if tf_data['5m'].iloc[-1]['VOL_SMA20'] > 0 else 1) if '5m' in tf_data else 1.0

near_res = (res1 - live_price) <= 150
near_sup = (live_price - sup1) <= 150

short_cond = near_res and (m4h_stoch >= 85 and m1h_stoch >= 80 and m5m_stoch >= 80) and vol_5m < 1.2
long_cond = near_sup and (m4h_stoch <= 20 and m1h_stoch <= 25 and m5m_stoch <= 20) and vol_5m < 1.2

# Lock trade if triggered
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

# Render Action Card
if st.session_state.locked_trade is not None:
    t = st.session_state.locked_trade
    pts = (live_price - t['entry']) if t['type'] == 'LONG' else (t['entry'] - live_price)
    
    # Check TP / SL Exits
    hit_sl = (live_price <= t['sl']) if t['type'] == 'LONG' else (live_price >= t['sl'])
    hit_tp2 = (live_price >= t['tp2']) if t['type'] == 'LONG' else (live_price <= t['tp2'])

    if hit_sl:
        st.error(f"🔴 {t['type']} TRADE STOP-LOSS HIT (-{abs(pts):.0f} pts). Position exited @ ${live_price:,.1f}.")
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
        <p>Price S1 (${sup1:,.1f}) aur R1 (${res1:,.1f}) ke beech fasa hua hai. System boundaries par verified turning point ka wait kar raha hai.</p>
    </div>
    """, unsafe_allow_html=True)

# ----------------- MULTI-TIMEFRAME TABLE -----------------
st.subheader("📊 Multi-Timeframe Matrix (All 12 Indicators)")

table_rows = []
for tf in TIMEFRAMES:
    if tf not in tf_data:
        continue
    df = tf_data[tf]
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    vol_sma = curr['VOL_SMA20'] if curr['VOL_SMA20'] > 0 else 1
    vol_ratio = curr['volume'] / vol_sma
    above_200 = "Above" if curr['close'] >= curr['EMA200'] else "Below"
    above_vwap = "Above" if curr['close'] >= curr['VWAP'] else "Below"
    pattern = detect_candlestick_pattern(curr, prev, tf)

    stoch_k = curr['STOCH_K']
    will_v = curr['WILLR']
    if stoch_k <= 18 and will_v <= -82:
        sig = "💎 DIP BUY"
    elif stoch_k >= 85 and will_v >= -18:
        sig = "🩸 TOP REJECT"
    else:
        sig = "HOLD"

    table_rows.append({
        "TF": tf,
        "Trend": "BULLISH" if curr['EMA9'] > curr['EMA21'] else "BEARISH",
        "200 EMA": above_200,
        "VWAP": above_vwap,
        "RSI": f"{curr['RSI']:.1f}",
        "Vol Ratio": f"{vol_ratio:.1f}x",
        "StochRSI": f"{stoch_k:.0f}",
        "ADX": f"{curr['ADX']:.0f}",
        "CCI": f"{curr['CCI']:.0f}",
        "Will %R": f"{will_v:.0f}",
        "Delta": f"{curr['DELTA']:+.0f}",
        "BB Squeeze": f"{curr['BB_WIDTH']:.2f}%",
        "Pattern": pattern,
        "Signal": sig
    })

st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# ----------------- AI ANALYST & CHATBOT -----------------
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
        reply = f"🔒 Active {t['type']} Trade: Fixed Entry ${t['entry']:,.1f} | SL ${t['sl']:,.1f}. Current PnL: {pts:+.0f} points. Bina SL hit hue panic me na niklein."
    elif "volume" in q:
        reply = "📘 Volume Rule: Breakout ke waqt volume > 1.5x hona chahiye. Agar Resistance par volume dry (0.1x-0.4x) hai, toh wo 90% fakeout trap hota hai."
    elif "squeeze" in q:
        reply = "💥 Squeeze Blast: Bollinger Bandwidth < 1.0% hone par market spring ki tarah coil hoti hai. Volume aate hi 1,500-3,000 points ka blast trigger hota hai."
    elif "sl" in q or "stoploss" in q:
        reply = f"🛡️ SL Level: Active short ke liye ${res1 + 220:,.1f}, active long ke liye ${sup1 - 220:,.1f}."
    else:
        reply = f"Live Market: BTC ${live_price:,.1f}. Support ${sup1:,.1f} aur Resistance ${res1:,.1f} hai. System extreme turning points ka wait kar raha hai."

    st.session_state.chat_history.append(("assistant", reply))
    with st.chat_message("assistant"):
        st.write(reply)

# Auto refresh every 5 seconds
time.sleep(5)
st.rerun()