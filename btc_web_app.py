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
    .calc-box { background-color: #18181b; border: 1px solid #3f3f46; border-radius: 10px; padding: 16px; margin-top: 15px; }
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
            <p><b>• FIXED ENTRY:</b> ${t['entry']:,.1f} (FROZEN - Caught at the Turning Point)<br>
            <b>• HARD SL:</b> ${t['sl']:,.1f} (FROZEN - Risk Defined)<br>
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

# ----------------- INTERACTIVE FUTURES PnL & RISK CALCULATOR -----------------
st.subheader("🧮 Interactive Futures PnL, Leverage & Risk Calculator")

with st.expander("👉 Click to Open / Calculate Profit, Loss & Leverage", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        calc_direction = st.selectbox("Trade Direction", ["SHORT", "LONG"], index=0 if (st.session_state.locked_trade and st.session_state.locked_trade['type'] == 'SHORT') else 1)
        calc_margin = st.number_input("Margin Amount ($) [Aapka Paisa]", value=100.0, step=10.0, min_value=1.0)
    with c2:
        calc_leverage = st.slider("Leverage (x)", min_value=1, max_value=50, value=10, step=1)
        default_entry = float(st.session_state.locked_trade['entry']) if st.session_state.locked_trade else float(live_price)
        calc_entry = st.number_input("Entry Price ($)", value=round(default_entry, 1), step=10.0)
    with c3:
        default_target = float(st.session_state.locked_trade['tp1']) if st.session_state.locked_trade else (calc_entry - 600.0 if calc_direction == 'SHORT' else calc_entry + 600.0)
        calc_exit = st.number_input("Exit / Target / SL Price ($)", value=round(default_target, 1), step=10.0)
        
    # Math Calculations
    position_size_usd = calc_margin * calc_leverage
    btc_qty = position_size_usd / calc_entry if calc_entry > 0 else 0

    if calc_direction == "LONG":
        point_diff = calc_exit - calc_entry
        est_liq = calc_entry * (1 - (1 / calc_leverage) + 0.005)
    else:
        point_diff = calc_entry - calc_exit
        est_liq = calc_entry * (1 + (1 / calc_leverage) - 0.005)

    net_pnl_usd = (point_diff / calc_entry) * position_size_usd if calc_entry > 0 else 0
    roe_percentage = (net_pnl_usd / calc_margin) * 100 if calc_margin > 0 else 0

    st.markdown("---")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total Position Size", f"${position_size_usd:,.0f}", f"{btc_qty:.4f} BTC")
    
    pnl_label = "Net Profit" if net_pnl_usd >= 0 else "Net Loss"
    r2.metric(f"Estimated {pnl_label} ($)", f"${net_pnl_usd:+,.2f}", f"{point_diff:+.1f} Points")
    
    roe_color = "normal" if roe_percentage >= 0 else "inverse"
    r3.metric("ROE (Profit/Loss % on Margin)", f"{roe_percentage:+.2f}%")
    r4.metric("Estimated Liq. Price", f"${est_liq:,.1f}", "Be Cautious")

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
        reply = (
            f"🔒 Active {t['type']} Position Status @ ${live_price:,.1f}:\n"
            f"• Entry: ${t['entry']:,.1f} | Hard SL: ${t['sl']:,.1f} | Current PnL: {pts:+.0f} points.\n"
            f"• Note: Jab tak price SL (${t['sl']:,.1f}) ke upar close na ho, position valid hai. 15m/30m/1h indicators abhi bhi overbought exhaustion dikha rahe hain."
        )
    elif "calculator" in q or "pnl" in q:
        reply = "🧮 Calculator widget upar live hai! Wahan aap margin amount, leverage slider aur target price daal kar exact Dollar aur % profit/loss calculate kar sakte hain."
    else:
        reply = f"Live Market: BTC ${live_price:,.1f}. Key levels monitor ho rahe hain. Extreme turning points par system early triggers de raha hai."

    st.session_state.chat_history.append(("assistant", reply))
    with st.chat_message("assistant"):
        st.write(reply)

# Auto refresh every 5s
time.sleep(5)
st.rerun()
