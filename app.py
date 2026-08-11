import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from urllib.parse import unquote
import time

# -------------------------------
# APP CONFIG
# -------------------------------
st.set_page_config(page_title="SMT PRO AI Scanner", layout="wide")
st.markdown("<h2 style='text-align:center;'>SMT PRO AI Trading Terminal</h2><hr>", unsafe_allow_html=True)

# -------------------------------
# AUTO REFRESH
# -------------------------------
auto_refresh = st.checkbox("Auto Refresh (5 min)", value=False)
if auto_refresh:
    time.sleep(300)
    st.rerun()

# -------------------------------
# STOCK SOURCE
# -------------------------------
source = st.radio("Stock Source", ["Manual CSV", "Chartink LIVE"], horizontal=True)

# ===============================
# CSV MODE
# ===============================
if source == "Manual CSV":

    uploaded_file = st.file_uploader("Upload Stock CSV", type=["csv"])

    if uploaded_file:
        df_symbols = pd.read_csv(uploaded_file)

        if "Symbol" in df_symbols.columns:
            symbols = [s.strip().upper() + ".NS" for s in df_symbols["Symbol"].dropna()]
        else:
            st.error("CSV must contain 'Symbol'")
            st.stop()
    else:
        symbols = ["RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS"]

# ===============================
# CHARTINK LIVE MODE
# ===============================
else:

    st.subheader("Chartink LIVE Scanner")
    chartink_cookie = st.text_input("Enter Chartink Cookie", type="password")

    @st.cache_data(ttl=60)
    def get_chartink_symbols(cookie):

        if not cookie:
            raise Exception("Cookie required")

        session = requests.Session()

        # Load cookie
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                session.cookies.set(k, v, domain="chartink.com")

        session.get("https://chartink.com")
        xsrf = unquote(session.cookies.get("XSRF-TOKEN", ""))

        if not xsrf:
            raise Exception("Invalid Cookie")

        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": xsrf,
            "Content-Type": "application/json",
            "Referer": "https://chartink.com/"
        }

        # YOUR REAL SCANNER CLAUSE
        payload = {
            "scan_clause": "( {cash} ( ( {cash} ( ( {cash} ( daily close >= daily max(252, daily high)*0.98 and daily volume > daily sma(daily volume,20)*1.5 and daily close > daily open ) ) or ( {cash} ( daily high >= daily max(252, daily high) and daily close < daily open and daily volume > daily sma(daily volume,20)*1.5 ) ) or ( {cash} ( daily open > 1 day ago close*1.02 and daily volume > daily sma(daily volume,20)*2 and daily close > daily open ) ) ) ) ) )"
        }

        res = session.post("https://chartink.com/screener/process", headers=headers, json=payload)

        if res.status_code != 200:
            raise Exception("Chartink fetch failed")

        data = res.json().get("data", [])

        symbols = [row["nsecode"].upper() + ".NS" for row in data if row.get("nsecode")]

        if not symbols:
            raise Exception("No stocks returned")

        return symbols

    if st.button("Get LIVE Stocks"):
        try:
            symbols = get_chartink_symbols(chartink_cookie)
            st.session_state["symbols"] = symbols
            st.success(f"{len(symbols)} stocks loaded")
        except Exception as e:
            st.error(str(e))
            st.stop()

    elif "symbols" in st.session_state:
        symbols = st.session_state["symbols"]
    else:
        st.info("Enter cookie and click button")
        st.stop()

    st.dataframe(pd.DataFrame({"Stocks": symbols}), use_container_width=True)

# -------------------------------
# TIMEFRAME
# -------------------------------
timeframe = st.selectbox("Select Timeframe", ["5m", "15m", "1d"])

# -------------------------------
# DATA FETCH (SAFE)
# -------------------------------
@st.cache_data
def get_data(symbol, timeframe):
    try:
        df = yf.download(symbol, period="5d", interval=timeframe, progress=False)

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()

        if not all(col in df.columns for col in ["Open","High","Low","Close"]):
            return None

        return df

    except:
        return None

# -------------------------------
# AI LOGIC
# -------------------------------
def analyze_stock(df):

    if df is None or len(df) < 50:
        return "WAIT", None, None, None

    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(latest["Close"])
        open_ = float(latest["Open"])
        high = float(latest["High"])
        low = float(latest["Low"])
        prev_close = float(prev["Close"])
    except:
        return "WAIT", None, None, None

    high_52 = float(df["High"].rolling(252).max().iloc[-1])

    if close >= 0.98 * high_52 and close > open_:
        return "BUY", high, low, high + (high - low) * 2

    elif high >= high_52 and close < open_:
        return "SELL", low, high, low - (high - low) * 2

    elif open_ > prev_close * 1.02:
        if close > open_:
            return "BUY", high, low, high + (high - low) * 2
        else:
            return "SELL", low, high, low - (high - low) * 2

    return "WAIT", None, None, None

# -------------------------------
# RISK SETTINGS
# -------------------------------
st.sidebar.header("💼 Risk Settings")

capital = st.sidebar.number_input("Capital (₹)", value=50000)
risk_percent = st.sidebar.slider("Risk % per trade", 0.5, 2.0, 1.0)

risk_amount = capital * (risk_percent / 100)

# -------------------------------
# PURE RISK CALCULATOR
# -------------------------------
def calculate_qty(entry, sl, risk_amount):

    if entry is None or sl is None:
        return 0, 0, 0, "NO DATA"

    sl_distance = abs(entry - sl)

    if sl_distance == 0:
        return 0, 0, 0, "INVALID SL"

    qty = int(risk_amount / sl_distance)

    position_value = qty * entry
    risk_used = qty * sl_distance

    if qty <= 0:
        return 0, 0, 0, "LOW RISK"

    return qty, position_value, risk_used, "OK"

# -------------------------------
# RUN SCANNER
# -------------------------------
if st.button("Run AI Scanner"):

    results = []

    for sym in symbols:

        df = get_data(sym, timeframe)
        signal, entry, sl, target = analyze_stock(df)

        qty, value, risk_used, status = calculate_qty(entry, sl, risk_amount)

        results.append({
            "Stock": sym,
            "Signal": signal,
            "Entry": round(entry, 2) if entry else None,
            "SL": round(sl, 2) if sl else None,
            "Target": round(target, 2) if target else None,
            "Qty": qty,
            "Capital Used": round(value, 0),
            "Risk Used": round(risk_used, 0),
            "Status": status
        })

    df_results = pd.DataFrame(results)

    st.subheader("📊 All Results (No Filter)")
    st.dataframe(df_results, use_container_width=True)

    st.subheader("🔥 Top 2 Signals")

    best = df_results[df_results["Signal"].isin(["BUY","SELL"])].head(2)

    for _, row in best.iterrows():
        color = "green" if row["Signal"] == "BUY" else "red"

        st.markdown(f"""
        <div style='padding:15px;border-radius:10px;background:{color};color:white;margin-bottom:10px'>
        <b>{row['Stock']}</b> - {row['Signal']}<br>
        Entry: {row['Entry']} | SL: {row['SL']} | Target: {row['Target']}<br>
        Qty: {row['Qty']} | Capital: ₹{row['Capital Used']} | Risk: ₹{row['Risk Used']}
        </div>
        """, unsafe_allow_html=True)

    if best.empty:
        st.warning("No signals found")

# -------------------------------
# FOOTER
# -------------------------------
st.caption("Educational use only. Pure risk-based sizing (no capital restriction).")
