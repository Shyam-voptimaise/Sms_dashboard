import streamlit as st
import struct, math, time, os
import pandas as pd
from datetime import datetime
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException

# =====================================================
# BASIC CONFIG
# =====================================================
DEFAULT_PORT = "COM14"
BAUDRATE = 9600
SLAVE_ID = 1
ENGINEER_PASSWORD = "0000"

# =====================================================
# RADAR REGISTERS (CONFIRMED SAFE)
# =====================================================
REG_DISTANCE     = 4096
REG_CURRENT      = 4102
REG_TEMPERATURE  = 4110

# ---- Diagnostic (OPTIONAL – radar may reject)
REG_POWER        = 4120
REG_SNR          = 4122

# ---- Engineering (safe subset)
REG_BLIND        = 4210
REG_RANGE        = 4212
REG_DAMPING      = 4220

# =====================================================
# PROCESS CONSTANTS
# =====================================================
NO_LADLE_DISTANCE   = 16.5
FULL_LADLE_DISTANCE = 11.5
STABLE_TIME_SEC     = 3
FLOW_START_KG_S     = 50
FLOW_STOP_KG_S      = 10

LADLE_DIAMETER_M = 3.0
METAL_DENSITY = 7000

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
        "empty_distance_m","end_distance_m",
        "total_weight_kg","avg_flow_kg_s"
    ]).to_csv(HISTORY_FILE, index=False)

# =====================================================
# MODBUS HELPERS (pymodbus 3.x SAFE)
# =====================================================
def mb_client(port):
    c = ModbusSerialClient(
        port=port,
        baudrate=BAUDRATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1
    )
    c.unit_id = SLAVE_ID
    return c

def read_float(port, reg):
    c = mb_client(port)
    if not c.connect():
        return None

    rr = c.read_holding_registers(reg, count=2)
    c.close()

    if rr is None or rr.isError():
        return None

    r0, r1 = rr.registers
    raw = bytes([
        (r0 >> 8) & 0xFF, r0 & 0xFF,
        (r1 >> 8) & 0xFF, r1 & 0xFF
    ])
    return struct.unpack(">f", raw)[0]

# ---- Optional diagnostic read (NO CRASH)
def read_optional_float(port, reg):
    try:
        return read_float(port, reg)
    except Exception:
        return None

def write_float(port, reg, value):
    try:
        c = mb_client(port)
        if not c.connect():
            return False, "Connection failed"

        raw = struct.pack(">f", float(value))
        rq = c.write_registers(
            reg,
            [(raw[0]<<8)|raw[1], (raw[2]<<8)|raw[3]]
        )
        c.close()

        if rq and not rq.isError():
            return True, "Written"
        return False, "Rejected"

    except ModbusIOException:
        return False, "Protected register"

# =====================================================
# STREAMLIT UI
# =====================================================
st.set_page_config("Radar Ladle Pouring", layout="wide")
st.title("🔥 Radar-Based Ladle Pouring Dashboard")

# =====================================================
# SIDEBAR – OPERATOR
# =====================================================
st.sidebar.header("👷 Operator Details")
operator = st.sidebar.text_input("Operator Name")
employee_id = st.sidebar.text_input("Employee ID")
shift = st.sidebar.selectbox("Shift", ["A","B","C","Night"])
port = st.sidebar.text_input("COM Port", DEFAULT_PORT)

# =====================================================
# ENGINEER MODE
# =====================================================
st.sidebar.markdown("---")
engineer_mode = st.sidebar.checkbox("Engineer Mode")
if engineer_mode:
    pwd = st.sidebar.text_input("Password", type="password")
    engineer_mode = (pwd == ENGINEER_PASSWORD)
    if not engineer_mode:
        st.sidebar.error("Invalid password")

# =====================================================
# SESSION STATE
# =====================================================
ss = st.session_state
ss.setdefault("empty_distance", None)
ss.setdefault("stable_since", None)
ss.setdefault("samples", [])
ss.setdefault("pouring", False)
ss.setdefault("pour_start", None)

# =====================================================
# READ RADAR
# =====================================================
now = datetime.now()
distance = read_float(port, REG_DISTANCE)
current = read_float(port, REG_CURRENT)
temperature = read_float(port, REG_TEMPERATURE)

# ---- OPTIONAL diagnostics
power = read_optional_float(port, REG_POWER)
snr   = read_optional_float(port, REG_SNR)

# =====================================================
# EMPTY LADLE AUTO-LEARN
# =====================================================
if distance is not None and distance > NO_LADLE_DISTANCE:
    ss.stable_since = ss.stable_since or now
    if ss.empty_distance is None and (now - ss.stable_since).total_seconds() >= STABLE_TIME_SEC:
        ss.empty_distance = distance
else:
    ss.stable_since = None

# =====================================================
# MATERIAL HEIGHT & WEIGHT
# =====================================================
area = math.pi * (LADLE_DIAMETER_M / 2) ** 2
material_height = None
weight = None

if ss.empty_distance and distance:
    material_height = max(ss.empty_distance - distance, 0)
    weight = material_height * area * METAL_DENSITY

# =====================================================
# FLOW RATE
# =====================================================
flow = None
if weight is not None:
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
        ss.empty_distance, distance,
        weight, flow
    ]
    df.to_csv(HISTORY_FILE, index=False)
    ss.samples.clear()

# =====================================================
# ETA
# =====================================================
eta = None
if ss.pouring and flow and distance:
    remaining_dist = max(distance - FULL_LADLE_DISTANCE, 0)
    eta = remaining_dist / (flow / METAL_DENSITY) if flow > 0 else None

# =====================================================
# DASHBOARD – OPERATOR VIEW
# =====================================================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("Actual Distance (m)", f"{distance:.3f}" if distance else "—")
    st.metric("Material Height (m)", f"{material_height:.3f}" if material_height else "—")
    st.metric(
        "Fill (%)",
        f"{(material_height / (ss.empty_distance - FULL_LADLE_DISTANCE)) * 100:.1f}"
        if material_height and ss.empty_distance else "—"
    )

with c2:
    st.metric("Flow Rate (kg/s)", f"{flow:.1f}" if flow else "—")
    st.metric("ETA (s)", f"{eta:.0f}" if eta else "—")
    st.metric("Temperature (°C)", f"{temperature:.1f}" if temperature else "—")

with c3:
    st.metric("Power (dB)", f"{power:.0f}" if power is not None else "—")
    st.metric("SNR (dB)", f"{snr:.0f}" if snr is not None else "—")
    st.markdown(f"## {'🟢 POURING' if ss.pouring else '🟡 READY'}")

# =====================================================
# ENGINEER SETTINGS (SAFE)
# =====================================================
if engineer_mode:
    st.markdown("---")
    st.subheader("⚙ Engineering Settings")

    blind = st.number_input("Blind Zone (m)", 0.25)
    rng = st.number_input("Range (m)", 18.0)
    damp = st.number_input("Damping (s)", 1.0)

    if st.button("Write Parameters"):
        r1 = write_float(port, REG_BLIND, blind)
        r2 = write_float(port, REG_RANGE, rng)
        r3 = write_float(port, REG_DAMPING, damp)
        st.info(f"{r1[1]} | {r2[1]} | {r3[1]}")

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
