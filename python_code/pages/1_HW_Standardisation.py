
import streamlit as st
import struct
import math
import time
import pandas as pd
from datetime import datetime
from pymodbus.client import ModbusSerialClient

# =====================================================
# MODBUS CONFIG (VENDOR VERIFIED)
# =====================================================
DEFAULT_PORT = "COM14"
BAUDRATE = 9600
SLAVE_ID = 1

REG_SPACE_HEIGHT = 4096
REG_MATERIAL_HEIGHT = 4098
REG_MATERIAL_PERCENT = 4100
REG_CURRENT = 4102
REG_TEMPERATURE = 4110

# =====================================================
# MODBUS HELPERS (MATCHES YOUR pymodbus SIGNATURE)
# =====================================================

def read_float(client, address):
    rr = client.read_holding_registers(address, count=2)

    if rr is None or rr.isError():
        return None

    r0, r1 = rr.registers
    raw = bytes([
        (r0 >> 8) & 0xFF, r0 & 0xFF,
        (r1 >> 8) & 0xFF, r1 & 0xFF
    ])
    return struct.unpack(">f", raw)[0]


def read_radar(port):
    client = ModbusSerialClient(
        port=port,
        baudrate=BAUDRATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1
    )

    # ✅ SET SLAVE ID ON CLIENT (NOT IN FUNCTION CALL)
    client.unit_id = SLAVE_ID

    if not client.connect():
        return None

    data = {
        "space_height": read_float(client, REG_SPACE_HEIGHT),
        "material_height": read_float(client, REG_MATERIAL_HEIGHT),
        "material_percent": read_float(client, REG_MATERIAL_PERCENT),
        "current": read_float(client, REG_CURRENT),
        "temperature": read_float(client, REG_TEMPERATURE),
    }

    client.close()
    return data

# =====================================================
# STREAMLIT UI
# =====================================================

st.set_page_config(page_title="Radar SMS-2 Dashboard", layout="wide")
st.title("🔥 Radar-Based Molten Metal Pouring Dashboard")

# ---------------- SIDEBAR ----------------
st.sidebar.header("⚙️ Configuration")

port = st.sidebar.text_input("COM Port", DEFAULT_PORT)

st.sidebar.subheader("🏗️ Ladle Geometry")
diameter = st.sidebar.number_input("Ladle Diameter (m)", 0.5, 10.0, 3.0, 0.1)
ladle_height = st.sidebar.number_input("Ladle Height (m)", 0.5, 20.0, 4.0, 0.1)
density = st.sidebar.number_input("Metal Density (kg/m³)", 6000, 9000, 7000, 100)

area = math.pi * (diameter / 2) ** 2

target_weight = st.sidebar.number_input(
    "Target Weight (kg)", 1000.0, 300000.0, 150000.0, 1000.0
)

# ---------------- LIVE READ ----------------
radar = read_radar(port)

col1, col2, col3 = st.columns(3)

if radar and radar["material_height"] is not None:
    level = radar["material_height"]
    volume = level * area
    weight = volume * density
    remaining = max(target_weight - weight, 0)

    with col1:
        st.subheader("📡 Radar")
        st.metric("Actual Distance (m)", f"{radar['space_height']:.3f}")
        st.metric("Material Height (m)", f"{level:.3f}")
        st.metric("Fill (%)", f"{radar['material_percent']:.2f}")

    with col2:
        st.subheader("🔧 Sensor")
        st.metric("Current (mA)", f"{radar['current']:.2f}")
        st.metric("Temperature (°C)", f"{radar['temperature']:.1f}")
        st.metric("Time", datetime.now().strftime("%H:%M:%S"))

    with col3:
        st.subheader("⚖️ Pour Status")
        st.metric("Weight (kg)", f"{weight:,.0f}")
        st.metric("Remaining (kg)", f"{remaining:,.0f}")
        st.progress(min(weight / target_weight, 1.0))

        if weight >= target_weight:
            st.error("🛑 STOP POURING")
        elif weight >= 0.9 * target_weight:
            st.warning("⚠️ SLOW POURING")
        else:
            st.success("✅ CONTINUE POURING")

else:
    st.error("❌ No radar data. Check COM14 and RS-485 wiring.")

# ---------------- TREND ----------------
if "history" not in st.session_state:
    st.session_state.history = []

if radar and radar["material_height"] is not None:
    st.session_state.history.append({
        "time": datetime.now(),
        "level": radar["material_height"],
        "percent": radar["material_percent"]
    })

if len(st.session_state.history) > 300:
    st.session_state.history = st.session_state.history[-300:]

if st.session_state.history:
    df = pd.DataFrame(st.session_state.history).set_index("time")
    st.line_chart(df)

# ---------------- AUTO REFRESH ----------------
time.sleep(0.3)
st.rerun()