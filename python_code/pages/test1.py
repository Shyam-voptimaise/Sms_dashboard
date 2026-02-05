import streamlit as st
import struct
import math
import pandas as pd
import time
from datetime import datetime
from pathlib import Path

# Modbus and MQTT Imports
from pymodbus.client import ModbusSerialClient
from streamlit_autorefresh import st_autorefresh

# MQTT Fallback (For Camera/Gyro)
try:
    from mqtt_client import start_mqtt, latest_data, lock
except ImportError:
    latest_data = {"frame": None}
    lock = None
    def start_mqtt(): pass

# =====================================================
# CONFIGURATION & CONSTANTS
# =====================================================
st.set_page_config(page_title="Ladle Pouring Dashboard", layout="wide")

METAL_DENSITY = 6.8  # t/m3
LOG_INTERVAL = 5     # Seconds between CSV logs during pouring
SLAVE_ID = 1

LADLE_PROFILES = {
    "LADLE_3.4M_TEST": {
        "height_m": 3.4,
        "top_diameter_m": 3.2,
        "bottom_diameter_m": 3.0,
        "capacity_tons": 160, 
    },
    "LADLE_150T": {
        "height_m": 3.2,
        "top_diameter_m": 3.72,
        "bottom_diameter_m": 2.20,
        "capacity_tons": 150,
    },
}

# Modbus Register Map
REG_SPACE_F = 4096
REG_TEMP_F  = 4110
REG_CURR_F  = 4102

# =====================================================
# STYLED UI (CSS)
# =====================================================
st.markdown("""
<style>
    .block-container { padding-top: 1rem; max-width: 1400px; }
    .metric-card { background: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; margin-bottom: 10px; }
    .status-active { color: #28a745; font-weight: bold; animation: blinker 2s linear infinite; }
    @keyframes blinker { 50% { opacity: 0.5; } }
</style>
""", unsafe_allow_html=True)

# =====================================================
# MODBUS COMMUNICATION ENGINE (SOLVES OFFLINE ISSUE)
# =====================================================
def get_radar_data(port_name):
    """
    Handles robust connection to the radar. 
    Opens and closes the port quickly to prevent Streamlit locking.
    """
    client = ModbusSerialClient(
        port=port_name, 
        baudrate=9600, 
        timeout=2, 
        retries=3, 
        bytesize=8, 
        parity="N", 
        stopbits=1
    )
    
    data = {"dist": None, "temp": None, "curr": None, "status": "Offline"}
    
    try:
        if client.connect():
            # Read Space Distance (4096)
            res = client.read_holding_registers(address=REG_SPACE_F, count=2, slave=SLAVE_ID)
            if not res.isError():
                raw = struct.pack(">HH", res.registers[0], res.registers[1])
                data["dist"] = struct.unpack(">f", raw)[0]
                data["status"] = "Online"
            
            # Read Temperature (4110)
            res_t = client.read_holding_registers(address=REG_TEMP_F, count=2, slave=SLAVE_ID)
            if not res_t.isError():
                raw_t = struct.pack(">HH", res_t.registers[0], res_t.registers[1])
                data["temp"] = struct.unpack(">f", raw_t)[0]
                
            client.close()
    except Exception as e:
        data["status"] = f"Error: {str(e)}"
    
    return data

# =====================================================
# GEOMETRY LOGIC
# =====================================================
def calculate_metrics(dist, base_dist, profile):
    """
    Uses Conical Frustum Formula: 
    V = (pi * h / 3) * (R^2 + r^2 + R*r)
    """
    h = max(0.0, base_dist - dist)
    H_total = profile["height_m"]
    rb = profile["bottom_diameter_m"] / 2.0
    rt = profile["top_diameter_m"] / 2.0
    
    # Linear interpolation of radius at height h
    rh = rb + (rt - rb) * (h / H_total if H_total > 0 else 0)
    
    volume = (math.pi * h / 3.0) * (rb**2 + rh**2 + rb*rh)
    weight = volume * METAL_DENSITY
    return h, weight

# =====================================================
# SESSION STATE & REFRESH
# =====================================================
if "pouring" not in st.session_state:
    st.session_state.update({
        "pouring": False,
        "level0": 0.0,
        "last_log": 0,
        "history": []
    })

ss = st.session_state
st_autorefresh(interval=1000, key="data_update")
start_mqtt()

# =====================================================
# SIDEBAR CONTROLS
# =====================================================
with st.sidebar:
    st.header("⚙️ System Control")
    com_port = st.text_input("Radar Port", "COM14")
    ladle_key = st.selectbox("Ladle Profile", list(LADLE_PROFILES.keys()))
    sel_profile = LADLE_PROFILES[ladle_key]
    
    st.divider()
    
    if not ss.pouring:
        if st.button("▶ START POURING", use_container_width=True, type="primary"):
            init_data = get_radar_data(com_port)
            if init_data["dist"]:
                ss.level0 = init_data["dist"]
                ss.pouring = True
                ss.history = []
                st.toast("Pouring Started!")
            else:
                st.error("Cannot start: Radar Offline")
    else:
        if st.button("⏹ STOP POURING", use_container_width=True, type="secondary"):
            if ss.history:
                df = pd.DataFrame(ss.history)
                log_name = f"pour_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(log_name, index=False)
                st.success(f"Saved: {log_name}")
            ss.pouring = False

# =====================================================
# DATA ACQUISITION & PROCESSING
# =====================================================
radar = get_radar_data(com_port)
calc_h, calc_w = 0.0, 0.0

if radar["dist"] is not None and ss.pouring:
    calc_h, calc_w = calculate_metrics(radar["dist"], ss.level0, sel_profile)
    
    # Background Logging (Every 5 seconds)
    if time.time() - ss.last_log >= LOG_INTERVAL:
        ss.history.append({
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Level_m": round(calc_h, 3),
            "Weight_T": round(calc_w, 2),
            "Temp_C": radar["temp"]
        })
        ss.last_log = time.time()

# =====================================================
# MAIN DASHBOARD UI
# =====================================================
m1, m2, m3, m4 = st.columns(4)

with m1:
    st.metric("Radar Status", radar["status"], 
              delta="Connected" if radar["status"] == "Online" else "Disconnected",
              delta_color="normal" if radar["status"] == "Online" else "inverse")
with m2:
    st.metric("Metal Height", f"{calc_h:.3f} m")
with m3:
    st.metric("Net Weight", f"{calc_w:.2f} Tons")
with m4:
    status_text = "🟢 POURING" if ss.pouring else "🟡 STANDBY"
    st.markdown(f"### {status_text}")

st.divider()

col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("📷 Live Camera Stream")
    if lock:
        with lock:
            frame = latest_data.get("frame")
            if frame is not None:
                st.image(frame, use_container_width=True)
            else:
                st.info("Searching for Camera Stream...")

with col_right:
    st.subheader("📊 Session Data")
    if ss.pouring:
        if ss.history:
            st.dataframe(pd.DataFrame(ss.history).iloc[::-1], use_container_width=True)
        else:
            st.write("Initializing logs...")
    else:
        st.write("Ready for next ladle.")
        st.info(f"Geometry: {sel_profile['height_m']}m Height | {sel_profile['capacity_tons']}T Cap")

# Diagnostics Footer
with st.expander("🛠 Technical Diagnostics"):
    d1, d2, d3 = st.columns(3)
    d1.write(f"Raw Distance: {radar['dist']} m")
    d2.write(f"Internal Temp: {radar['temp']} °C")
    d3.write(f"Empty Reference: {ss.level0} m")