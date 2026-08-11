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

df_symbols = pd.DataFrame()

# ===============================
# CSV MODE (FIXED)
# ===============================
if source == "Manual CSV":

    uploaded_file = st.file_uploader("Upload Stock CSV", type=["csv"])

    if uploaded_file:
        df_symbols = pd.read_csv(uploaded_file)

        # CLEAN COLUMNS
        df_symbols.columns = df_symbols.columns.str.strip().str.lower()

        # FIX volume (remove commas)
        if "volume" in df_symbols.columns:
            df_symbols["volume"] = df_symbols["volume"].astype(str).str.replace(",", "")
            df_symbols["volume"] = pd.to_numeric(df_symbols["volume"], errors="coerce")

        # FIX close
        if "close" in df_symbols.columns:
            df_symbols["close"] = pd.to_numeric(df_symbols["close"], errors="coerce")

        if "symbol" not in df_symbols.columns:
            st.error("CSV must contain 'symbol' column")
            st.stop()

        symbols = [s.strip().upper() + ".NS" for s in df_symbols["symbol"].dropna()]

    else:
        symbols = ["RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS"]

# ===============================
# CHARTINK MODE
# ===============================
else:
    st.subheader("Chartink LIVE Scanner")
    chartink_cookie = st.text_input("Enter Chartink Cookie", type="password")

    @st.cache_data(ttl=60)
    def get_chartink_symbols(cookie):
        if not cookie:
            raise Exception("Cookie required")

        session = requests.Session()

        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                session.cookies.set(k, v, domain="chartink.com")

        session.get("https://chartink.com")
        xsrf = unquote(session.cookies.get("XSRF-TOKEN", ""))

        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": xsrf,
            "Content-Type": "application/json",
            "Referer": "https://chartink.com/"
        }

        payload = {
            "scan_clause": "( {cash} ( ( {cash} ( ( {cash} ( daily close >= daily max(252, daily high)*0.98 and daily volume > daily sma(daily volume,20)*1.5 and daily close > daily open ) ) or ( {cash} ( daily high >= daily max(252, daily high) and daily close < daily open and daily volume > daily sma(daily volume,20)*1.5 ) ) or ( {cash} ( daily open > 1 day ago close*1.02 and daily volume > daily sma(daily volume,20)*2 and daily close > daily open ) ) ) ) ) )"
        }

        res = session.post("https://chartink.com/screener/process", headers=headers, json=payload)

        data = res.json().get("data", [])
        return [row["nsecode"].upper() + ".NS" for row in data if row.get("nsecode")]

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
        st.stop()

# -------------------------------
# TIMEFRAME
# -------------------------------
timeframe = st.selectbox("Timeframe", ["5m","15m","1d"])

# -------------------------------
# DATA FETCH
# -------------------------------
@st.cache_data
def get_data(symbol, timeframe):
    try:
        df = yf.download(symbol, period="3mo", interval=timeframe, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna()
    except:
        return None

# -------------------------------
# ATR
# -------------------------------
def calculate_atr(df, period=14):
    df = df.copy()
    df["H-L"] = df["High"] - df["Low"]
    df["H-PC"] = abs(df["High"] - df["Close"].shift(1))
    df["L-PC"] = abs(df["Low"] - df["Close"].shift(1))
    tr = df[["H-L","H-PC","L-PC"]].max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

# -------------------------------
# ANALYSIS
# -------------------------------
def analyze_stock(df):

    if df is None or len(df) < 50:
        return "WAIT", None, None, None, None

    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(latest["Close"])
        open_ = float(latest["Open"])
        high = float(latest["High"])
        low = float(latest["Low"])
        prev_close = float(prev["Close"])

        atr = calculate_atr(df)

    except:
        return "WAIT", None, None, None, None

    high_52 = float(df["High"].rolling(252).max().iloc[-1])

    if close >= 0.95 * high_52 and close > open_:
        return "BUY", high, high - atr, high + 2*atr, atr

    elif high >= high_52 and close < open_:
        return "SELL", low, low + atr, low - 2*atr, atr

    elif open_ > prev_close * 1.02:
        if close > open_:
            return "BUY", high, high - atr, high + 2*atr, atr
        else:
            return "SELL", low, low + atr, low - 2*atr, atr

    return "WAIT", None, None, None, None

# -------------------------------
# RUN
# -------------------------------
if st.button("Run AI Scanner"):

    results = []

    for sym in symbols:
        df = get_data(sym, timeframe)
        if df is None:
            continue

        signal, entry, sl, target, atr = analyze_stock(df)

        # GET CSV DATA IF AVAILABLE
        if not df_symbols.empty:
            row = df_symbols[df_symbols["symbol"].str.upper() == sym.replace(".NS","")]
            if not row.empty:
                volume = row["volume"].values[0]
                close_price = row["close"].values[0]
            else:
                volume = df["Volume"].iloc[-1]
                close_price = df["Close"].iloc[-1]
        else:
            volume = df["Volume"].iloc[-1]
            close_price = df["Close"].iloc[-1]

        # RELAXED FILTER (₹50K FRIENDLY)
        if volume < 50000 or close_price < 50:
            continue

        if signal in ["BUY","SELL"] and entry and sl and target:
            rr = abs(target-entry)/abs(entry-sl)

            results.append({
                "Stock": sym,
                "Signal": signal,
                "Entry": round(entry,2),
                "SL": round(sl,2),
                "Target": round(target,2),
                "RR": round(rr,2),
                "Volume": int(volume)
            })

    if len(results) == 0:
    st.warning("No strict trades → showing fallback trades")

    # fallback = ignore filters
    fallback_results = []

    for sym in symbols:
        df = get_data(sym, timeframe)
        if df is None:
            continue

        signal, entry, sl, target, atr = analyze_stock(df)

        if signal in ["BUY","SELL"] and entry and sl and target:
            rr = abs(target-entry)/abs(entry-sl)

            fallback_results.append({
                "Stock": sym,
                "Signal": signal,
                "Entry": round(entry,2),
                "SL": round(sl,2),
                "Target": round(target,2),
                "RR": round(rr,2),
                "Volume": 0
            })

    if len(fallback_results) == 0:
        st.error("No trades at all today")
        st.stop()

    df_results = pd.DataFrame(fallback_results)

    df_results = pd.DataFrame(results)

    # RANKING
    df_results["Score"] = (
        df_results["RR"]*0.6 +
        (df_results["Volume"]/df_results["Volume"].max())*0.4
    )

    df_results = df_results.sort_values(by="Score", ascending=False)

    st.subheader("📊 Filtered Results")
    st.dataframe(df_results, use_container_width=True)

    # SMART TOP 2
    buy_df = df_results[df_results["Signal"]=="BUY"]
    sell_df = df_results[df_results["Signal"]=="SELL"]

    if len(buy_df)>0 and len(sell_df)>0:
        best = pd.concat([buy_df.head(1), sell_df.head(1)])
    else:
        best = df_results.head(2)

    st.subheader("🔥 Top 2 Trades")

    for _, row in best.iterrows():
        color = "green" if row["Signal"]=="BUY" else "red"

        st.markdown(f"""
        <div style='padding:15px;border-radius:10px;background:{color};color:white;margin-bottom:10px'>
        <b>{row['Stock']}</b> - {row['Signal']}<br>
        Entry: {row['Entry']} | SL: {row['SL']} | Target: {row['Target']}<br>
        RR: {row['RR']}
        </div>
        """, unsafe_allow_html=True)

# -------------------------------
# FOOTER
# -------------------------------
st.caption("Final stable version • ATR + CSV fix + Smart filtering")
