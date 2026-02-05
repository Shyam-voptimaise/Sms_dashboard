import streamlit as st
import struct
import math
import os
import pandas as pd
import time
from datetime import datetime
from pathlib import Path
from pymodbus.client import ModbusSerialClient
from streamlit_autorefresh import st_autorefresh

# MQTT Fallback
try:
    from mqtt_client import start_mqtt, latest_data, lock
except ImportError:
    latest_data = {"frame": None}
    lock = None
    def start_mqtt(): pass

# =====================================================
# 1. ROBUST SESSION INITIALIZATION
# =====================================================
def initialize_state():
    if "pouring" not in st.session_state:
        st.session_state.pouring = False
    if "empty_distance" not in st.session_state:
        st.session_state.empty_distance = 14.51 # Default
    if "history" not in st.session_state:
        st.session_state.history = []
    if "engineer_mode" not in st.session_state:
        st.session_state.engineer_mode = False
    if "last_loaded_ladle" not in st.session_state:
        st.session_state.last_loaded_ladle = None
    if "calibration_source" not in st.session_state:
        st.session_state.calibration_source = "none"
    if "mqtt_started" not in st.session_state:
        try:
            start_mqtt()
            st.session_state.mqtt_started = True
        except:
            st.session_state.mqtt_started = False

initialize_state()
ss = st.session_state
STRETCH = "stretch" # 2026 Syntax

# =====================================================
# 2. CONFIG & GEOMETRY
# =====================================================
st.set_page_config(page_title="Ladle Pro 2026", layout="wide")

DEFAULT_PORT = "COM14"
BAUDRATE = 9600
SLAVE_ID = 1
ENGINEER_PASSWORD = "0000"
STEEL_DENSITY = 6.8  
R_BOTTOM = 1.55 
WALL_ANGLE_DEG = 0.9
TAN_THETA = math.tan(math.radians(WALL_ANGLE_DEG))

# Modbus Registers
REG_SPACE_HEIGHT_F = 4096
REG_MATERIAL_HEIGHT_F = 4098
REG_MATERIAL_PCT_F = 4100
REG_CURRENT_F = 4102
REG_TEMPERATURE_F = 4110

# CSV Setup
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(DATA_DIR, "pour_history.csv")
PROFILE_FILE = os.path.join(DATA_DIR, "ladle_profiles.csv")

# =====================================================
# 3. MODBUS HEARTBEAT (Fixes Access Denied)
# =====================================================
def get_all_radar_data(port_name):
    """Opens port, reads all registers in one burst, and closes immediately."""
    client = ModbusSerialClient(port=port_name, baudrate=BAUDRATE, timeout=0.8, retries=1)
    results = {"dist": None, "mat_h": None, "pct": None, "curr": None, "temp": None, "err": None}
    
    try:
        if client.connect():
            # Read 16 registers starting from 4096 to get all values in one go
            res = client.read_holding_registers(address=REG_SPACE_HEIGHT_F, count=16, slave=SLAVE_ID)
            if not res.isError():
                def parse_f32(idx):
                    r0, r1 = res.registers[idx], res.registers[idx+1]
                    return struct.unpack(">f", struct.pack(">HH", r0, r1))[0]
                
                results["dist"] = parse_f32(0)  # 4096
                results["mat_h"] = parse_f32(2) # 4098
                results["pct"] = parse_f32(4)   # 4100
                results["curr"] = parse_f32(6)  # 4102
                results["temp"] = parse_f32(14) # 4110
        else:
            results["err"] = "Port Busy"
    except Exception as e:
        results["err"] = str(e)
    finally:
        client.close()
    return results

# =====================================================
# 4. CUSTOM CSS STYLING
# =====================================================
st.markdown("""
<style>
    .block-container { padding-top: 1rem; max-width: 1400px; }
    .metric-row { margin-bottom: 0.8rem; background: #f1f3f5; padding: 10px; border-radius: 5px; }
    .metric-label { font-size: 0.8rem; color: #666; }
    .metric-value { font-size: 1.2rem; font-weight: bold; color: #000; }
    .status-box { font-size: 1.8rem; font-weight: 800; padding: 10px; border-radius: 8px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# =====================================================
# 5. SIDEBAR & CONTROLS
# =====================================================
st_autorefresh(interval=1500, key="global_refresh")

with st.sidebar:
    st.header("👷 Operator")
    op_name = st.text_input("Name")
    shift = st.selectbox("Shift", ["A", "B", "C"])
    port = st.text_input("Port", DEFAULT_PORT)
    
    st.divider()
    ladle_id = st.text_input("Ladle ID")
    
    # Auto-load profile logic
    if ladle_id and ss.last_loaded_ladle != ladle_id:
        if os.path.exists(PROFILE_FILE):
            pdf = pd.read_csv(PROFILE_FILE)
            match = pdf[pdf['ladle_id'] == ladle_id]
            if not match.empty:
                ss.empty_distance = float(match.iloc[0]['empty_distance_m'])
                ss.calibration_source = "saved_profile"
        ss.last_loaded_ladle = ladle_id

    if not ss.pouring:
        if st.button("▶ START POUR", width=STRETCH, type="primary"):
            ss.pouring = True
            st.rerun()
    else:
        if st.button("⏹ STOP & SAVE", width=STRETCH, type="secondary"):
            ss.pouring = False
            st.rerun()

    # Calibration
    if st.button("Set Current as EMPTY", disabled=ss.pouring):
        radar_check = get_all_radar_data(port)
        if radar_check["dist"]:
            ss.empty_distance = radar_check["dist"]
            # Save to CSV
            new_row = pd.DataFrame([{"ladle_id": ladle_id, "empty_distance_m": ss.empty_distance}])
            new_row.to_csv(PROFILE_FILE, mode='a', header=not os.path.exists(PROFILE_FILE), index=False)
            st.success("Calibrated!")

# =====================================================
# 6. MAIN DASHBOARD (4-QUADRANT)
# =====================================================
radar = get_all_radar_data(port)

# Calculations
height_fill = 0.0
ladle_tons = 0.0
if radar["dist"] is not None:
    height_fill = max(ss.empty_distance - radar["dist"], 0.0)
    R_fill = R_BOTTOM + (height_fill * TAN_THETA)
    volume = (math.pi * height_fill / 3.0) * (R_fill**2 + R_fill * R_BOTTOM + R_BOTTOM**2)
    ladle_tons = volume * STEEL_DENSITY

# --- ROW 1 ---
q1, q2, q_stat = st.columns([4, 4, 2])

with q1:
    st.subheader("📡 Radar Data")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="metric-row"><div class="metric-label">Distance</div><div class="metric-value">{radar["dist"] or "—"} m</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-row"><div class="metric-label">Filled Height</div><div class="metric-value">{height_fill:.3f} m</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-row"><div class="metric-label">Device %</div><div class="metric-value">{radar["pct"] or "—"} %</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-row"><div class="metric-label">Calc. Tons</div><div class="metric-value">{ladle_tons:.2f} T</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-row"><div class="metric-label">Current</div><div class="metric-value">{radar["curr"] or "—"} mA</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-row"><div class="metric-label">Temp</div><div class="metric-value">{radar["temp"] or "—"} °C</div></div>', unsafe_allow_html=True)

with q2:
    st.subheader("🧭 Gyro Scope")
    with lock:
        g = latest_data.get("gyro", {})
    gc1, gc2 = st.columns(2)
    gc1.metric("X-Axis", g.get("gyro_x", "—"))
    gc2.metric("Y-Axis", g.get("gyro_y", "—"))

with q_stat:
    color = "#28a745" if ss.pouring else "#ffc107"
    label = "POURING" if ss.pouring else "READY"
    st.markdown(f'<div class="status-box" style="background:{color}; color:white; margin-top:2rem;">{label}</div>', unsafe_allow_html=True)

st.divider()

# --- ROW 2 ---
q3, q4 = st.columns(2)

with q3:
    st.subheader("🪣 Bucket Schematic")
    fill_pct = int(round(radar["pct"] / 5) * 5) if radar["pct"] else 0
    img_path = Path(f"LadleImages/Ladle_Image_{max(0, min(100, fill_pct))}.png")
    if img_path.exists():
        st.image(str(img_path), width=300)
    else:
        st.info(f"Schematic: {fill_pct}% fill level")

with q4:
    st.subheader("📷 Live Stream")
    with lock:
        frame = latest_data.get("frame")
    if frame is not None:
        st.image(frame, width=STRETCH)
    else:
        st.warning("Camera Offline")

# --- DATA TABLES ---
st.divider()
tabs = st.tabs(["📜 Pour History", "🧠 Ladle Memory"])
with tabs[0]:
    if os.path.exists(HISTORY_FILE):
        st.dataframe(pd.read_csv(HISTORY_FILE), width=STRETCH)
with tabs[1]:
    if os.path.exists(PROFILE_FILE):
        st.dataframe(pd.read_csv(PROFILE_FILE), width=STRETCH)