import streamlit as st
import pandas as pd
import requests
from urllib.parse import unquote
import time

# -------------------------------
# APP CONFIG
# -------------------------------
st.set_page_config(page_title="Risk Calculator", layout="wide")
st.markdown("<h2 style='text-align:center;'>📊 Risk & Position Size Calculator</h2><hr>", unsafe_allow_html=True)

# -------------------------------
# RISK SETTINGS
# -------------------------------
st.sidebar.header("💼 Risk Settings")

capital = st.sidebar.number_input("Capital (₹)", value=50000)
risk_percent = st.sidebar.slider("Risk % per trade", 0.5, 2.0, 1.0)

risk_amount = capital * (risk_percent / 100)

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
# CSV MODE (REQUIRES Entry & SL)
# ===============================
if source == "Manual CSV":

    uploaded_file = st.file_uploader("Upload CSV (Symbol, Entry, SL)", type=["csv"])

    if uploaded_file:
        df = pd.read_csv(uploaded_file)

        required = ["Symbol", "Entry", "SL"]
        if not all(col in df.columns for col in required):
            st.error("CSV must contain: Symbol, Entry, SL")
            st.stop()

    else:
        st.info("Upload CSV with Symbol, Entry, SL")
        st.stop()

# ===============================
# CHARTINK MODE (USER INPUT ENTRY/SL)
# ===============================
else:

    st.subheader("Chartink LIVE Scanner")

    chartink_cookie = st.text_input("Enter Chartink Cookie", type="password")

    @st.cache_data(ttl=30)
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

        payload = {"scan_clause": "( {cash} ( daily close > daily open ) )"}

        res = session.post("https://chartink.com/screener/process", headers=headers, json=payload)
        data = res.json().get("data", [])

        return [row["nsecode"] for row in data if row.get("nsecode")]

    if st.button("Get Stocks"):
        symbols = get_symbols(chartink_cookie)

        df = pd.DataFrame({
            "Symbol": symbols,
            "Entry": [0]*len(symbols),
            "SL": [0]*len(symbols)
        })

        st.warning("Enter Entry & SL manually below")

        df = st.data_editor(df, use_container_width=True)

    else:
        st.stop()

# -------------------------------
# POSITION SIZE FUNCTION
# -------------------------------
def calculate(entry, sl, capital, risk_amount):

    if entry <= 0 or sl <= 0:
        return 0, 0, 0, "INVALID"

    sl_dist = abs(entry - sl)

    if sl_dist == 0:
        return 0, 0, 0, "SL ZERO"

    ideal_qty = int(risk_amount / sl_dist)
    max_qty = int(capital / entry)

    qty = min(ideal_qty, max_qty)

    capital_used = qty * entry
    risk_used = qty * sl_dist

    status = "OK" if qty == ideal_qty else "CAP LIMITED"

    return qty, capital_used, risk_used, status

# -------------------------------
# CALCULATE BUTTON
# -------------------------------
if st.button("Calculate Position Size"):

    results = []

    for _, row in df.iterrows():

        symbol = row["Symbol"]
        entry = float(row["Entry"])
        sl = float(row["SL"])

        qty, cap_used, risk_used, status = calculate(entry, sl, capital, risk_amount)

        results.append({
            "Stock": symbol,
            "Entry": entry,
            "SL": sl,
            "Qty": qty,
            "Capital Used": round(cap_used, 0),
            "Risk Used": round(risk_used, 0),
            "Status": status
        })

    result_df = pd.DataFrame(results)

    st.subheader("📊 Position Size Output")
    st.dataframe(result_df, use_container_width=True)

# -------------------------------
# FOOTER
# -------------------------------
st.caption("Only risk calculation. No trading signals included.")
