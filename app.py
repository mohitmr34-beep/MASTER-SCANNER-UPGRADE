import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from urllib.parse import unquote
import time

# -------------------------------
# CONFIG
# -------------------------------
st.set_page_config(page_title="SMT PRO AI Scanner", layout="wide")
st.title("SMT PRO AI Trading Terminal")

# -------------------------------
# AUTO REFRESH
# -------------------------------
if st.checkbox("Auto Refresh (5 min)"):
    time.sleep(300)
    st.rerun()

# -------------------------------
# SOURCE
# -------------------------------
source = st.radio("Stock Source", ["Manual CSV", "Chartink LIVE"])

df_symbols = pd.DataFrame()

# -------------------------------
# CSV MODE
# -------------------------------
if source == "Manual CSV":
    file = st.file_uploader("Upload CSV", type=["csv"])

    if file:
        df_symbols = pd.read_csv(file)
        df_symbols.columns = df_symbols.columns.str.lower().str.strip()

        if "volume" in df_symbols.columns:
            df_symbols["volume"] = (
                df_symbols["volume"].astype(str)
                .str.replace(",", "")
            )
            df_symbols["volume"] = pd.to_numeric(df_symbols["volume"], errors="coerce")

        if "close" in df_symbols.columns:
            df_symbols["close"] = pd.to_numeric(df_symbols["close"], errors="coerce")

        symbols = [s.upper() + ".NS" for s in df_symbols["symbol"]]

    else:
        symbols = ["RELIANCE.NS","HDFCBANK.NS"]

# -------------------------------
# CHARTINK MODE
# -------------------------------
else:
    cookie = st.text_input("Chartink Cookie", type="password")

    def get_symbols(cookie):
        session = requests.Session()

        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                session.cookies.set(k, v, domain="chartink.com")

        session.get("https://chartink.com")
        xsrf = unquote(session.cookies.get("XSRF-TOKEN", ""))

        headers = {
            "X-XSRF-TOKEN": xsrf,
            "Content-Type": "application/json"
        }

        payload = {"scan_clause": "your logic"}

        r = session.post("https://chartink.com/screener/process", headers=headers, json=payload)
        data = r.json().get("data", [])

        return [d["nsecode"] + ".NS" for d in data]

    if st.button("Get Stocks"):
        try:
            symbols = get_symbols(cookie)
            st.session_state["symbols"] = symbols
        except:
            st.error("Chartink error")

    symbols = st.session_state.get("symbols", [])

# -------------------------------
# DATA
# -------------------------------
def get_data(sym):
    try:
        df = yf.download(sym, period="3mo", interval="5m", progress=False)
        return df.dropna()
    except:
        return None

# -------------------------------
# ATR
# -------------------------------
def atr(df):
    tr = (df["High"] - df["Low"]).rolling(14).mean()
    return tr.iloc[-1]

# -------------------------------
# LOGIC
# -------------------------------
def analyze(df):
    if df is None or len(df) < 50:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    try:
        high = last["High"]
        low = last["Low"]
        close = last["Close"]
        open_ = last["Open"]
        prev_close = prev["Close"]
    except:
        return None

    a = atr(df)

    if close > open_:
        return "BUY", high, high - a, high + 2*a
    else:
        return "SELL", low, low + a, low - 2*a

# -------------------------------
# RUN
# -------------------------------
if st.button("Run Scanner"):

    results = []

    for sym in symbols:
        df = get_data(sym)
        out = analyze(df)

        if not out:
            continue

        signal, entry, sl, target = out

        results.append({
            "Stock": sym,
            "Signal": signal,
            "Entry": round(entry,2),
            "SL": round(sl,2),
            "Target": round(target,2)
        })

    # -------------------------------
    # FALLBACK
    # -------------------------------
    if len(results) == 0:

        st.warning("No strict trades → fallback mode")

        for sym in symbols:
            df = get_data(sym)
            if df is None:
                continue

            last = df.iloc[-1]

            results.append({
                "Stock": sym,
                "Signal": "INFO",
                "Entry": last["Close"],
                "SL": "-",
                "Target": "-"
            })

    # -------------------------------
    # OUTPUT
    # -------------------------------
    df_results = pd.DataFrame(results)

    st.subheader("Results")
    st.dataframe(df_results)

    st.subheader("Top 2 Trades")

    top2 = df_results.head(2)

    for _, r in top2.iterrows():
        st.write(f"{r['Stock']} → {r['Signal']} | Entry: {r['Entry']}")
