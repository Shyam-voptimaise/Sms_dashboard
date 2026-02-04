import streamlit as st
import struct
import os
import pandas as pd
from datetime import datetime

from pymodbus.client import ModbusSerialClient
from streamlit_autorefresh import st_autorefresh

# MQTT (CAMERA)
from mqtt_client import start_mqtt, latest_data, lock

# =====================================================
# STREAMLIT UI STYLE
# =====================================================
st.markdown("""
<style>
.block-container { padding-top: 2rem; max-width: 1400px; }
.alarm {
    background: #ffe6e6;
    color: #a10000;
    padding: 0.4rem 0.8rem;
    border-radius: 6px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# =====================================================
# AUTO REFRESH
# =====================================================
st_autorefresh(interval=1000, key="refresh")

# =====================================================
# BASIC CONFIG (FROM DOCUMENT)
# =====================================================
DEFAULT_PORT = "COM14"
BAUDRATE = 9600
SLAVE_ID = 1   # device default (configured in radar)

TONS_PER_METER = 45.0
MAX_SAFE_TONS = 170.0

# =====================================================
# MODBUS REGISTERS (DOCUMENT VERIFIED)
# =====================================================
REG_SPACE_HEIGHT_F = 4096   # 0x1000
REG_MATERIAL_PCT_F = 4100   # 0x1004
REG_CURRENT_F = 4102        # 0x1006
REG_TEMPERATURE_F = 4110    # 0x100E

# =====================================================
# DATA STORAGE
# =====================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(DATA_DIR, "pour_history.csv")
PROFILE_FILE = os.path.join(DATA_DIR, "ladle_profiles.csv")

if not os.path.exists(HISTORY_FILE):
    pd.DataFrame(columns=[
        "ladle_id",
        "operator_id",
        "track_no",
        "pour_no",
        "shift",
        "start_time",
        "end_time",
        "start_height_m",
        "end_height_m",
        "start_tons",
        "end_tons",
        "bottom_line_m"
    ]).to_csv(HISTORY_FILE, index=False)

if not os.path.exists(PROFILE_FILE):
    pd.DataFrame(columns=[
        "ladle_id",
        "bottom_line_m",
        "updated_at"
    ]).to_csv(PROFILE_FILE, index=False)

# =====================================================
# MODBUS HELPERS (DOCUMENT STYLE)
# =====================================================
def mb_client(port: str) -> ModbusSerialClient:
    return ModbusSerialClient(
        port=port,
        baudrate=BAUDRATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1,
    )

def read_f32(port: str, reg: int):
    client = mb_client(port)
    if not client.connect():
        return None

    # ✔ EXACTLY as per document examples
    rr = client.read_holding_registers(reg, count=2)

    client.close()

    if rr is None or rr.isError():
        return None

    r0, r1 = rr.registers
    raw = bytes([
        (r0 >> 8) & 0xFF, r0 & 0xFF,
        (r1 >> 8) & 0xFF, r1 & 0xFF
    ])
    return struct.unpack(">f", raw)[0]

# =====================================================
# SESSION STATE
# =====================================================
ss = st.session_state
ss.setdefault("pouring", False)
ss.setdefault("start_time", None)
ss.setdefault("start_height", None)
ss.setdefault("start_tons", None)
ss.setdefault("bottom_line", None)

# =====================================================
# SIDEBAR – OPERATOR / LADLE
# =====================================================
st.sidebar.header("👷 Operator Details")
operator_id = st.sidebar.text_input("Operator ID")
shift = st.sidebar.selectbox("Shift", ["A", "B", "C", "Night"])
port = st.sidebar.text_input("COM Port", DEFAULT_PORT)

st.sidebar.markdown("---")
ladle_id = st.sidebar.text_input("Ladle ID")
track_no = st.sidebar.selectbox("Track / Line", ["Track-1", "Track-2"])
pour_no = st.sidebar.selectbox("Pour Count", [1, 2])

# =====================================================
# LOAD LADLE PROFILE (BOTTOM LINE)
# =====================================================
if ladle_id:
    try:
        dfp = pd.read_csv(PROFILE_FILE)
        row = dfp[dfp["ladle_id"] == ladle_id]
        if not row.empty:
            ss.bottom_line = float(row.iloc[0]["bottom_line_m"])
    except Exception:
        pass

# =====================================================
# POUR CONTROL
# =====================================================
st.sidebar.markdown("---")
if not ss.pouring:
    if st.sidebar.button("▶ Start Pouring"):
        ss.pouring = True
        ss.start_time = datetime.now()
        ss.start_height = None
        ss.start_tons = None
else:
    if st.sidebar.button("⏹ Stop Pouring"):
        ss.pouring = False

# =====================================================
# CALIBRATION – BOTTOM LINE (DOCUMENT LOGIC)
# =====================================================
st.sidebar.markdown("---")
st.sidebar.subheader("🧭 Ladle Bottom Line")

distance_m = read_f32(port, REG_SPACE_HEIGHT_F)

if ss.bottom_line is not None:
    st.sidebar.caption(f"Saved Bottom Line: {ss.bottom_line:.3f} m")

if st.sidebar.button("Set Current Distance as Bottom Line"):
    if ladle_id and distance_m is not None:
        ss.bottom_line = distance_m
        dfp = pd.read_csv(PROFILE_FILE)
        dfp = dfp[dfp["ladle_id"] != ladle_id]
        dfp.loc[len(dfp)] = [ladle_id, distance_m, datetime.now().isoformat()]
        dfp.to_csv(PROFILE_FILE, index=False)
        st.sidebar.success("Bottom line saved")

# =====================================================
# READ RADAR VALUES
# =====================================================
material_pct = read_f32(port, REG_MATERIAL_PCT_F)
current_ma = read_f32(port, REG_CURRENT_F)
temperature_c = read_f32(port, REG_TEMPERATURE_F)

# =====================================================
# LIVE WEIGHT CALCULATION
# =====================================================
metal_height = None
ladle_tons = None
overfill = False

if distance_m is not None and ss.bottom_line is not None:
    metal_height = max(0.0, ss.bottom_line - distance_m)
    ladle_tons = metal_height * TONS_PER_METER
    if ladle_tons >= MAX_SAFE_TONS:
        overfill = True

# =====================================================
# SAVE HISTORY
# =====================================================
if ss.pouring and ss.start_height is None and metal_height is not None:
    ss.start_height = metal_height
    ss.start_tons = ladle_tons

if not ss.pouring and ss.start_time and ss.start_height is not None:
    dfh = pd.read_csv(HISTORY_FILE)
    dfh.loc[len(dfh)] = [
        ladle_id,
        operator_id,
        track_no,
        pour_no,
        shift,
        ss.start_time,
        datetime.now(),
        ss.start_height,
        metal_height,
        ss.start_tons,
        ladle_tons,
        ss.bottom_line
    ]
    dfh.to_csv(HISTORY_FILE, index=False)

    ss.start_time = None
    ss.start_height = None
    ss.start_tons = None

# =====================================================
# DASHBOARD
# =====================================================
if overfill:
    st.markdown('<div class="alarm">🚨 OVERFILL WARNING</div>', unsafe_allow_html=True)

st.markdown("## 📡 Radar & Live Weight")

c1, c2, c3 = st.columns(3)

with c1:
    st.metric("Radar Distance (m)", f"{distance_m:.3f}" if distance_m is not None else "—")
    st.metric("Metal Height from Bottom (m)", f"{metal_height:.3f}" if metal_height is not None else "—")

with c2:
    st.metric("Calculated Tons (LIVE)", f"{ladle_tons:.2f}" if ladle_tons is not None else "—")
    st.metric("Radar Fill %", f"{material_pct:.1f}%" if material_pct is not None else "—")

with c3:
    st.metric("Current (mA)", f"{current_ma:.2f}" if current_ma is not None else "—")
    st.metric("Temperature (°C)", f"{temperature_c:.1f}" if temperature_c is not None else "—")

# =====================================================
# CAMERA
# =====================================================
start_mqtt()
with lock:
    frame = latest_data.get("frame")

st.markdown("---")
st.markdown("## 📷 Camera")
if frame is not None:
    st.image(frame, width=450)
else:
    st.info("Waiting for camera stream")

# =====================================================
# TABLES
# =====================================================
st.markdown("---")
st.markdown("## 📜 Pour History")
st.dataframe(pd.read_csv(HISTORY_FILE), use_container_width=True)

st.markdown("## 🧠 Ladle Profiles (Bottom Line)")
st.dataframe(pd.read_csv(PROFILE_FILE), use_container_width=True)
