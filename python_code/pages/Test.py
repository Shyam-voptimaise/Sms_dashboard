import streamlit as st
import math, time, os
import pandas as pd
from datetime import datetime

from mqtt_client import start_mqtt, latest_data, lock

# =====================================================
# STREAMLIT CONFIG
# =====================================================
st.set_page_config(page_title="Radar Ladle Pouring", layout="wide")

# =====================================================
# START MQTT ONCE
# =====================================================
if "mqtt_started" not in st.session_state:
    start_mqtt()
    st.session_state.mqtt_started = True

# =====================================================
# CONSTANTS
# =====================================================
FLOW_START_KG_S = 50
FLOW_STOP_KG_S  = 10

LADLE_DIAMETER_M = 3.0
METAL_DENSITY   = 7000

MIN_HEIGHT_ALARM = 0.5
MAX_HEIGHT_ALARM = 14.0

# =====================================================
# DATA STORAGE
# =====================================================
DATA_DIR = "data"
HISTORY_FILE = os.path.join(DATA_DIR, "pour_history.csv")
os.makedirs(DATA_DIR, exist_ok=True)

if not os.path.exists(HISTORY_FILE):
    pd.DataFrame(columns=[
        "pour_id","operator","employee_id","shift",
        "pour_start","pour_end","duration_s",
        "material_height_m","fill_pct",
        "total_weight_kg","avg_flow_kg_s"
    ]).to_csv(HISTORY_FILE, index=False)

# =====================================================
# RADAR PARSER (MATCHES YOUR PAYLOAD)
# =====================================================
def parse_radar(rs):
    if not isinstance(rs, dict):
        return None, None, None, None

    rs = {k.lower(): v for k, v in rs.items()}

    try:
        material_height = float(rs.get("material_height_m"))
    except:
        material_height = None

    try:
        fill_pct = float(rs.get("material_pct"))
    except:
        fill_pct = None

    try:
        current = float(rs.get("current_ma"))
    except:
        current = None

    try:
        temperature = float(rs.get("temp_c"))
    except:
        temperature = None

    return material_height, fill_pct, current, temperature

# =====================================================
# UI HEADER
# =====================================================
st.title("🔥 Radar-Based Ladle Pouring Dashboard (MQTT)")

# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.header("👷 Operator Details")
operator     = st.sidebar.text_input("Operator Name")
employee_id  = st.sidebar.text_input("Employee ID")
shift        = st.sidebar.selectbox("Shift", ["A","B","C","Night"])

# =====================================================
# SESSION STATE
# =====================================================
ss = st.session_state
ss.setdefault("samples", [])
ss.setdefault("pouring", False)
ss.setdefault("pour_start", None)
ss.setdefault("trend", [])

# =====================================================
# FETCH MQTT DATA
# =====================================================
with lock:
    frame = latest_data["frame"]
    gyro  = latest_data["gyro"]
    rs    = latest_data["rs485"]

material_height, fill_pct, current, temperature = parse_radar(rs)
now = datetime.now()

# =====================================================
# WEIGHT & FLOW
# =====================================================
area = math.pi * (LADLE_DIAMETER_M / 2) ** 2
weight = None
flow = None

if material_height is not None:
    weight = material_height * area * METAL_DENSITY
    ss.samples.append({"t": now, "w": weight})
    ss.samples = ss.samples[-20:]

    if len(ss.samples) >= 2:
        dw = ss.samples[-1]["w"] - ss.samples[-2]["w"]
        dt = (ss.samples[-1]["t"] - ss.samples[-2]["t"]).total_seconds()
        if dt > 0 and dw > 0:
            flow = dw / dt

# =====================================================
# POUR START / END
# =====================================================
if not ss.pouring and flow and flow > FLOW_START_KG_S:
    ss.pouring = True
    ss.pour_start = now

if ss.pouring and flow and flow < FLOW_STOP_KG_S:
    ss.pouring = False
    duration = (now - ss.pour_start).total_seconds()

    df = pd.read_csv(HISTORY_FILE)
    df.loc[len(df)] = [
        now.strftime("%Y%m%d_%H%M%S"),
        operator, employee_id, shift,
        ss.pour_start, now, duration,
        material_height, fill_pct,
        weight, flow
    ]
    df.to_csv(HISTORY_FILE, index=False)
    ss.samples.clear()

# =====================================================
# STORE TRENDS (FIXED)
# =====================================================
if material_height is not None:
    ss.trend.append({
        "time": now,
        "material_height": material_height,
        "fill_pct": fill_pct,
        "flow": flow
    })

# ✅ FIXED SLICE (NO INDEX ERROR)
ss.trend = ss.trend[-300:]

trend_df = pd.DataFrame(ss.trend)

# =====================================================
# VIDEO
# =====================================================
st.subheader("📷 Live Camera Feed")
if frame is not None:
    st.image(frame)
else:
    st.info("Waiting for video stream...")

# =====================================================
# GYRO
# =====================================================
st.subheader("🧭 Gyroscope")
if gyro:
    cols = st.columns(len(gyro))
    for col, (k, v) in zip(cols, gyro.items()):
        col.metric(k, f"{v:.2f}")

# =====================================================
# RADAR METRICS
# =====================================================
st.subheader("📡 Radar Readings")

r1, r2, r3, r4 = st.columns(4)

r1.metric("Material Height (m)", f"{material_height:.2f}" if material_height else "—")
r2.metric("Fill (%)", f"{fill_pct:.1f}%" if fill_pct else "—")
r3.metric("Flow (kg/s)", f"{flow:.1f}" if flow else "—")
r4.metric("Temperature (°C)", f"{temperature:.1f}" if temperature else "—")

# =====================================================
# ALARMS
# =====================================================
if material_height is not None:
    if material_height < MIN_HEIGHT_ALARM:
        st.error("🔴 LOW LEVEL ALARM")
    elif material_height > MAX_HEIGHT_ALARM:
        st.error("🔴 HIGH LEVEL ALARM")
    else:
        st.success("🟢 Level Normal")

# =====================================================
# REAL-TIME CHARTS
# =====================================================
st.markdown("---")
st.subheader("📈 Real-Time Trends")

if not trend_df.empty:
    st.line_chart(trend_df.set_index("time")[["material_height"]], height=250)
    st.line_chart(trend_df.set_index("time")[["fill_pct"]], height=250)

    if trend_df["flow"].notna().any():
        st.line_chart(trend_df.set_index("time")[["flow"]], height=250)
else:
    st.info("Waiting for radar data...")

# =====================================================
# HISTORY
# =====================================================
st.markdown("---")
st.subheader("📜 Pour History")
st.dataframe(pd.read_csv(HISTORY_FILE), use_container_width=True)

# =====================================================
# AUTO REFRESH
# =====================================================
time.sleep(0.3)
st.rerun()
