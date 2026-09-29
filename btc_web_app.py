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
    .trade-short { background-color: #7f1d1d; border-left: 6px solid #ef4444; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
    .trade-long { background-color: #14532d; border-left: 6px solid #22c55e; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
    .trade-wait { background-color: #27272a; border-left: 6px solid #eab308; padding: 16px; border-radius: 8px; margin-bottom: 12px; }
    .calc-card { background-color: #18181b; border: 1px solid #3f3f46; border-radius: 10px; padding: 16px; margin-bottom: 15px; }
    .metric-value-green { color: #22c55e; font-weight: bold; }
    .metric-value-red { color: #ef4444; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

SYMBOL = 'BTC/USDT'
TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
LIMIT = 100

@st.cache_resource
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
        sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
        candles = exchange.fetch_ohlcv(sym, timeframe=tf, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA9'] = ta.trend.ema_indicator(df['close'], window=9)
        df['EMA21'] = ta.trend.ema_indicator(df['close'], window=21)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=min(len(df)-1, 50))
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

tf_data = {}
for tf in TIMEFRAMES:
    d = fetch_tf_data(tf)
    if d is not None:
        tf_data[tf] = d

try:
    sym = 'BTC/USDT' if 'BTC/USDT' in exchange.markets else 'BTC/USD'
    ticker = exchange.fetch_ticker(sym)
    live_price = ticker['last'] if ticker and 'last' in ticker else tf_data['5m'].iloc[-1]['close']
except Exception:
    live_price = tf_data['5m'].iloc[-1]['close'] if '5m' in tf_data else 84000.0

df_5m = tf_data.get('5m')
df_15m = tf_data.get('15m')
recent_high = max(df_5m['high'].iloc[-20:].max() if df_5m is not None else live_price + 300, live_price + 150)
recent_low = min(df_5m['low'].iloc[-20:].min() if df_5m is not None else live_price - 300, live_price - 150)

df_1d = tf_data.get('1d')
ema200_1d = df_1d.iloc[-1].get('EMA200', live_price) if df_1d is not None and len(df_1d) >= 1 else live_price

# ----------------- UI HEADER -----------------
st.title("⚡ BTC Perpetual Institutional Terminal")
h_col1, h_col2, h_col3, h_col4 = st.columns(4)
h_col1.metric("Live Price", f"${live_price:,.2f}")
h_col2.metric("Local High (Resistance)", f"${recent_high:,.1f}")
h_col3.metric("Local Low (Support)", f"${recent_low:,.1f}")
h_col4.metric("1D 200 EMA", f"${ema200_1d:,.1f}")

# ----------------- SNIPER ENGINE -----------------
stoch_5m = df_5m.iloc[-1].get('STOCH_K', 50) if df_5m is not None else 50
stoch_15m = df_15m.iloc[-1].get('STOCH_K', 50) if df_15m is not None else 50
cci_5m = df_5m.iloc[-1].get('CCI', 0) if df_5m is not None else 0
cci_15m = df_15m.iloc[-1].get('CCI', 0) if df_15m is not None else 0
will_5m = df_5m.iloc[-1].get('WILLR', -50) if df_5m is not None else -50

early_short_cond = (stoch_5m >= 88 or stoch_15m >= 90) and (cci_5m > 130 or cci_15m > 130) and (will_5m >= -15)
early_long_cond = (stoch_5m <= 15 or stoch_15m <= 18) and (cci_5m < -130 or cci_15m < -130) and (will_5m <= -85)

if st.session_state.locked_trade is None:
    if early_short_cond:
        st.session_state.locked_trade = {
            'type': 'SHORT', 'entry': live_price, 'sl': live_price + 280.0,
            'tp1': live_price - 600.0, 'tp2': live_price - 1500.0, 'tp3': live_price - 2500.0
        }
    elif early_long_cond:
        st.session_state.locked_trade = {
            'type': 'LONG', 'entry': live_price, 'sl': live_price - 280.0,
            'tp1': live_price + 600.0, 'tp2': live_price + 1500.0, 'tp3': live_price + 2500.0
        }

# Render Master Action Card
if st.session_state.locked_trade is not None:
    t = st.session_state.locked_trade
    pts = (live_price - t['entry']) if t['type'] == 'LONG' else (t['entry'] - live_price)
    
    hit_sl = (live_price <= t['sl']) if t['type'] == 'LONG' else (live_price >= t['sl'])
    hit_tp2 = (live_price >= t['tp2']) if t['type'] == 'LONG' else (live_price <= t['tp2'])

    if hit_sl:
        st.error(f"🔴 {t['type']} TRADE STOP-LOSS HIT (-{abs(pts):.0f} pts). Position exited @ ${live_price:,.1f}.")
        st.session_state.locked_trade = None
    elif hit_tp2:
        st.success(f"🟢 {t['type']} TARGET 2 HIT (+{pts:.0f} pts PROFIT BOOKED!).")
        st.session_state.locked_trade = None
    else:
        css_class = "trade-short" if t['type'] == 'SHORT' else "trade-long"
        st.markdown(f"""
        <div class="{css_class}">
            <h3>⚡ ACTIVE {t['type']} SNIPER POSITION RUNNING (PnL: {pts:+.0f} Pts)</h3>
            <p><b>• FIXED ENTRY:</b> ${t['entry']:,.1f} (FROZEN)<br>
            <b>• HARD SL:</b> ${t['sl']:,.1f} (FROZEN)<br>
            <b>• TARGET 1 (TP1):</b> ${t['tp1']:,.1f} [+600 pts -> Shift SL to Entry]<br>
            <b>• TARGET 2 (TP2):</b> ${t['tp2']:,.1f} [+1,500 pts Big Target]<br>
            <b>• RUNNER TARGET (TP3):</b> ${t.get('tp3', t['tp2']):,.1f} [+2,500 pts Mega Runway]</p>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="trade-wait">
        <h3>⏳ SCANNING EARLY TURNING POINT (5m/15m Extreme Hunter)</h3>
        <p>5m StochRSI: {stoch_5m:.0f} | 15m StochRSI: {stoch_15m:.0f} | CCI: {cci_5m:.0f}.<br>
        System extreme turning points par <b>pehli candle par entry lock karega</b>.</p>
    </div>
    """, unsafe_allow_html=True)

# ----------------- INTERACTIVE ADVANCED PnL, LOT & RISK CALCULATOR -----------------
st.subheader("🧮 Futures Position Size, Risk & Profit Calculator")

with st.container():
    st.markdown('<div class="calc-card">', unsafe_allow_html=True)
    
    active_type = st.session_state.locked_trade['type'] if st.session_state.locked_trade else "SHORT"
    active_entry = float(st.session_state.locked_trade['entry']) if st.session_state.locked_trade else float(live_price)
    
    if active_type == "SHORT":
        sys_sug_sl = active_entry + 280.0
        sys_sug_tp1 = active_entry - 600.0
        sys_sug_tp2 = active_entry - 1500.0
    else:
        sys_sug_sl = active_entry - 280.0
        sys_sug_tp1 = active_entry + 600.0
        sys_sug_tp2 = active_entry + 1500.0

    col_dir, col_entry, col_qty, col_lev = st.columns([1.5, 2, 2, 2.5])
    with col_dir:
        direction = st.selectbox("Direction", ["SHORT", "LONG"], index=0 if active_type == "SHORT" else 1)
    with col_entry:
        entry_val = st.number_input("Entry Price ($)", value=round(active_entry, 1), step=10.0)
    with col_qty:
        qty_btc = st.number_input("Qty / Lot Size (BTC)", value=0.05, step=0.01, min_value=0.001, format="%.3f")
    with col_lev:
        leverage = st.slider("Leverage (x)", min_value=1, max_value=50, value=10, step=1)

    total_position_usd = qty_btc * entry_val
    margin_paid_usd = total_position_usd / leverage if leverage > 0 else total_position_usd

    st.info(f"💵 **Amount You Pay (Margin Required):** `${margin_paid_usd:,.2f}` | **Total Position Value:** `${total_position_usd:,.2f}` ({qty_btc:.3f} BTC)")

    col_sl_in, col_tp_in = st.columns(2)
    
    with col_sl_in:
        st.markdown(f"**🛡️ Stop-Loss Setup** *(System Suggests: `${sys_sug_sl:,.1f}`)*")
        sl_val = st.number_input("Enter Your Stop-Loss ($)", value=round(sys_sug_sl, 1), step=10.0)
        
        if direction == "LONG":
            sl_points = entry_val - sl_val
            sl_loss_usd = (sl_points / entry_val) * total_position_usd if entry_val > 0 else 0
        else:
            sl_points = sl_val - entry_val
            sl_loss_usd = (sl_points / entry_val) * total_position_usd if entry_val > 0 else 0
            
        sl_roe = (sl_loss_usd / margin_paid_usd) * 100 if margin_paid_usd > 0 else 0
        st.markdown(f"""
        * **Loss in Points:** `{sl_points:+.1f} Pts`
        * **Loss in Dollars:** <span class="metric-value-red">`-${abs(sl_loss_usd):,.2f}`</span>
        * **Loss Percentage (ROE):** <span class="metric-value-red">`-{abs(sl_roe):.2f}%`</span>
        """, unsafe_allow_html=True)

    with col_tp_in:
        st.markdown(f"**🎯 Take-Profit / Target Setup** *(TP1: `${sys_sug_tp1:,.1f}` | TP2: `${sys_sug_tp2:,.1f}`)*")
        tp_val = st.number_input("Enter Your Profit Target ($)", value=round(sys_sug_tp1, 1), step=10.0)
        
        if direction == "LONG":
            tp_points = tp_val - entry_val
            tp_profit_usd = (tp_points / entry_val) * total_position_usd if entry_val > 0 else 0
        else:
            tp_points = entry_val - tp_val
            tp_profit_usd = (tp_points / entry_val) * total_position_usd if entry_val > 0 else 0
            
        tp_roe = (tp_profit_usd / margin_paid_usd) * 100 if margin_paid_usd > 0 else 0
        rr_ratio = abs(tp_points / sl_points) if sl_points > 0 else 0
        
        st.markdown(f"""
        * **Gain in Points:** `{tp_points:+.1f} Pts`
        * **Profit in Dollars:** <span class="metric-value-green">`+${tp_profit_usd:,.2f}`</span>
        * **Profit Percentage (ROE):** <span class="metric-value-green">`+{tp_roe:.2f}%`</span>
        * **Risk-to-Reward Ratio (R:R):** `1 : {rr_ratio:.2f}`
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ----------------- TABLE (ALL 12 INDICATORS LIVE) -----------------
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
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# ----------------- AI CHATBOT -----------------
st.subheader("🤖 Institutional AI Master Analyst")

for role, text in st.session_state.chat_history:
    with st.chat_message(role):
        st.write(text)

user_query = st.chat_input("Poochiye (e.g. SL kahan rakhu?, kya trade safe hai?, loss kitna hoga?)...")

if user_query:
    st.session_state.chat_history.append(("user", user_query))
    with st.chat_message("user"):
        st.write(user_query)

    q = user_query.lower()
    t = st.session_state.locked_trade

    if t is not None:
        pts = (live_price - t['entry']) if t['type'] == 'LONG' else (t['entry'] - live_price)
        reply = f"Active {t['type']} Position @ ${live_price:,.1f}: Entry: ${t['entry']:,.1f} | Hard SL: ${t['sl']:,.1f} | PnL: {pts:+.0f} pts. Position is valid."
    elif "calculator" in q or "pnl" in q:
reply = (
    f"Active {t['type']} Position @ ${live_price:,.1f}: "
    f"Entry: ${t['entry']:,.1f} | Hard SL: ${t['sl']:,.1f} | PnL: {pts:+.0f} pts. "
    f"Jab tak price SL ke upar close na ho, position valid hai."
)
        )
    elif "calculator" in q or "pnl" in q:
        reply = "Calculator box live hai: Entry, Qty (Lot) aur Leverage se required margin ($), loss aur profit percentage auto-calculate ho jayega."
    else:
        reply = f"Live Market: BTC ${live_price:,.1f}. Extreme turning points monitor ho rahe hain."

    st.session_state.chat_history.append(("assistant", reply))
    with st.chat_message("assistant"):
        st.write(reply)

# Auto refresh every 5s
time.sleep(5)
st.rerun()
