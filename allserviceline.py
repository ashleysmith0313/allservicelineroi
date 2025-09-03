import math
from typing import Dict, Any, List
import streamlit as st

try:
    import yaml
except Exception:
    yaml = None

st.set_page_config(page_title="All-Service Line ROI Calculator", layout="centered")
st.title("🏥 All-Service Line ROI Calculator")
st.caption("All Revenue and Cost Values are assumptive and can be modified with actual values • Powered by VISTA")

# -------------------------------
# Config loading (supports config/service_lines.yaml)
# -------------------------------
@st.cache_data
def load_config() -> Dict[str, Any]:
    sample = {
        "service_lines": [{
            "key": "hospitalist_med_surg",
            "display_name": "Daytime Hospitalist (Med-Surg only)",
            "capacity_label": "Beds",
            "default": {"total_units": 18, "occupancy_pct": 75, "unit_rev": 2750, "unit_cost": 1850, "referrals_per_unit": 1.2},
            "referrals": {"revenue_per_referral": 900, "types": [
                {"name": "Cardiology", "pct": 30, "unit_rev": 500},
                {"name": "GI", "pct": 25, "unit_rev": 1200},
                {"name": "Surgery", "pct": 25, "unit_rev": 3000},
                {"name": "Imaging/Diagnostics", "pct": 20, "unit_rev": 800},
            ]},
            "locum": {"enabled": True, "default_count": 1, "utilization_pct": 80, "hourly_rate": 265, "hours_per_shift": 10, "travel_per_day": 390},
        }]}
    if yaml is None:
        return sample
    import os
    for p in [os.path.join("config", "service_lines.yaml"), "service_lines.yaml", "serviceline.yaml"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict) and data.get("service_lines"):
                return data
    return sample

CFG = load_config()
SERVICE_MAP = {sl["display_name"]: sl for sl in CFG.get("service_lines", [])}

# -------------------------------
# UI: service line & defaults
# -------------------------------
service_name = st.selectbox("Select Service Line", list(SERVICE_MAP.keys()))
svc = SERVICE_MAP[service_name]
cap_label = svc.get("capacity_label", "Units")

st.header("🛠️ Shift Details")
left, right = st.columns(2)

with left:
    total_units = st.number_input(f"Total {cap_label}", min_value=1, value=int(svc["default"].get("total_units", 1)))
    occupancy_pct = st.slider("Current Staffed % (without Locums)", 0, 100, int(svc["default"].get("occupancy_pct", 0)))
    unit_rev = st.number_input(
        f"Average Revenue per {cap_label[:-1] if cap_label.endswith('s') else cap_label} ($)",
        min_value=0.0, value=float(svc["default"].get("unit_rev", 0.0)), step=100.0)
    unit_cost = st.number_input(
        f"Average Cost per {cap_label[:-1] if cap_label.endswith('s') else cap_label} ($)",
        min_value=0.0, value=float(svc["default"].get("unit_cost", 0.0)), step=100.0)

with right:
    referrals_per_unit = st.number_input("Avg Referrals per Unit", min_value=0.0,
                                         value=float(svc["default"].get("referrals_per_unit", 0.0)), step=0.1)
    revenue_per_referral = st.number_input("Baseline Revenue per Referral ($)", min_value=0.0,
                                           value=float(svc.get("referrals", {}).get("revenue_per_referral", 0.0)),
                                           step=50.0)

# -------------------------------
# Locum settings + toggle
# -------------------------------
st.subheader("👩‍⚕️ Locum Staffing")
loc_cfg = svc.get("locum", {})
use_locums = st.checkbox("Use Locums for this shift?", value=bool(loc_cfg.get("enabled", False)))

# We always keep a set of locum settings (used for the WITH-locum scenario),
# even when the toggle is off (so we can show the impact if locums were used).
loc_col1, loc_col2, loc_col3 = st.columns(3)
with loc_col1:
    locum_count_ui = st.number_input("Locums per Shift", min_value=0, value=int(loc_cfg.get("default_count", 1)))
    hourly_rate_ui = st.number_input("Hourly Rate ($)", min_value=0.0, value=float(loc_cfg.get("hourly_rate", 0.0)), step=5.0)
with loc_col2:
    hours_per_shift_ui = st.number_input("Hours per Shift", min_value=1, max_value=24, value=int(loc_cfg.get("hours_per_shift", 10)))
    travel_per_day_ui = st.number_input("Travel/Housing per Day ($)", min_value=0.0, value=float(loc_cfg.get("travel_per_day", 0.0)), step=10.0)
with loc_col3:
    locum_util_pct_ui = st.slider("Locum Utilization %", 0, 100, int(loc_cfg.get("utilization_pct", 0)))

# -------------------------------
# Referral mix
# -------------------------------
st.subheader("🔗 Referral Revenue (Downstream)")
ref_cfg = svc.get("referrals", {})
ref_types: List[Dict[str, Any]] = ref_cfg.get("types", [])

cols = st.columns(max(1, len(ref_types)))
percent_values = []
for i, rt in enumerate(ref_types):
    with cols[i % len(cols)]:
        pct = st.slider(f"{rt.get('name', f'Type {i+1}')} (%)", 0, 100, int(rt.get("pct", 0)))
        percent_values.append(pct)

pct_sum = sum(percent_values)
normalize = st.toggle("Auto-normalize referral % to 100%", value=True)
if pct_sum != 100:
    if normalize and pct_sum > 0:
        scale = 100.0 / pct_sum
        percent_values = [round(p * scale) for p in percent_values]
        drift = 100 - sum(percent_values)
        if percent_values:
            percent_values[0] += drift

def referral_revenue_for(staffed_pct: float) -> float:
    ref_total = total_units * referrals_per_unit * (max(0, min(100, staffed_pct)) / 100.0)
    total = 0.0
    for pct, rt in zip(percent_values, ref_types):
        rt_referrals = ref_total * (pct / 100.0)
        rt_unit_rev = float(rt.get("unit_rev", revenue_per_referral))
        total += rt_referrals * rt_unit_rev
    return total

# -------------------------------
# Scenario math helpers
# -------------------------------
def scenario(staffed_pct: float, locum_count: int, hourly_rate: float, hours_per_shift: int, travel_per_day: float):
    staffed_pct = max(0, min(100, staffed_pct))
    units_covered = int(round(total_units * staffed_pct / 100.0))
    gross_rev = units_covered * float(unit_rev)
    operating_cost = units_covered * float(unit_cost)
    ref_rev = referral_revenue_for(staffed_pct)
    locum_cost_per = hourly_rate * hours_per_shift + travel_per_day
    locum_total = locum_cost_per * locum_count
    net_before = gross_rev + ref_rev - operating_cost
    net_after = net_before - locum_total
    return {
        "staffed_pct": staffed_pct,
        "units_covered": units_covered,
        "gross_rev": gross_rev,
        "operating_cost": operating_cost,
        "referral_rev": ref_rev,
        "locum_total": locum_total,
        "net_before": net_before,
        "net_after": net_after,
    }

# Build both scenarios so we can show the impact either way
with_locums = scenario(
    staffed_pct=occupancy_pct + locum_util_pct_ui,
    locum_count=locum_count_ui,
    hourly_rate=hourly_rate_ui,
    hours_per_shift=hours_per_shift_ui,
    travel_per_day=travel_per_day_ui,
)
without_locums = scenario(
    staffed_pct=occupancy_pct,
    locum_count=0,
    hourly_rate=0.0,
    hours_per_shift=hours_per_shift_ui,
    travel_per_day=0.0,
)

# Choose which scenario is "active" based on the toggle
active = with_locums if use_locums else without_locums

# Annualization
annual_days = st.number_input("Annualization Days", min_value=1, max_value=366, value=365)
annualized_net = active["net_after"] * annual_days
annualized_locum_cost = active["locum_total"] * annual_days
missed_units = max(0, total_units - active["units_covered"])
annualized_missed = missed_units * (float(unit_rev) + referrals_per_unit * float(revenue_per_referral) - float(unit_cost)) * annual_days

# -------------------------------
# Output summary (active scenario)
# -------------------------------
st.header("📊 Shift Financial Summary")
met1, met2, met3 = st.columns(3)
with met1:
    st.metric(f"{cap_label} Staffed This Shift", active["units_covered"])
    st.metric(f"Unstaffed {cap_label}", total_units - active["units_covered"])
with met2:
    st.metric("Gross Revenue from Staffed Units", f"${active['gross_rev']:,.0f}")
    st.metric("Operating Cost for Staffed Units", f"${active['operating_cost']:,.0f}")
with met3:
    st.metric("Referral Revenue Generated", f"${active['referral_rev']:,.0f}")
    st.metric("Net Margin Before Locum Cost", f"${active['net_before']:,.0f}")

st.metric("🔥 Net Financial Impact (After Locum)", f"${active['net_after']:,.0f}")

if use_locums:
    st.markdown(
        f"""
        ### 🧮 Estimated Annual Impact ({annual_days} Days)
        <div style='background-color:#d4f4dd;padding:1rem;border-radius:8px;'>
        <strong>Annualized Net ROI (With Locum): ${annualized_net:,.0f}</strong><br>
        <em>Annualized Locum Cost: ${annualized_locum_cost:,.0f}</em>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown(
        f"""
        ### 🧮 Estimated Annual Missed Opportunity ({annual_days} Days)
        <div style='background-color:#990000;padding:1rem;border-radius:8px;color:white;'>
        <strong>Annualized Net Loss: (${annualized_missed:,.0f})</strong>
        </div>
        """, unsafe_allow_html=True)

# -------------------------------
# Impact vs the other scenario
# -------------------------------
st.subheader("📉 Impact of Turning Locums Off/On")
if use_locums:
    # Show improvement vs WITHOUT locums
    delta_units = with_locums["units_covered"] - without_locums["units_covered"]
    delta_gross = with_locums["gross_rev"] - without_locums["gross_rev"]
    delta_ref = with_locums["referral_rev"] - without_locums["referral_rev"]
    delta_net = with_locums["net_after"] - without_locums["net_after"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Extra Units Covered", delta_units)
    c2.metric("Top-line ↑ (Gross)", f"${delta_gross:,.0f}")
    c3.metric("Referral Revenue ↑", f"${delta_ref:,.0f}")
    c4.metric("Net Impact ↑ (After Locum)", f"${delta_net:,.0f}")
else:
    # Show losses vs WITH locums
    delta_units = without_locums["units_covered"] - with_locums["units_covered"]
    delta_gross = without_locums["gross_rev"] - with_locums["gross_rev"]
    delta_ref = without_locums["referral_rev"] - with_locums["referral_rev"]
    delta_net = without_locums["net_after"] - with_locums["net_after"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Units Lost", delta_units)
    c2.metric("Top-line Lost", f"${-delta_gross:,.0f}")  # negative shown as positive loss
    c3.metric("Referral Revenue Lost", f"${-delta_ref:,.0f}")
    c4.metric("Net Impact Lost", f"${-delta_net:,.0f}")

# -------------------------------
# Scenario export (CSV-style line)
# -------------------------------
if st.button("Copy Scenario Row"):
    row = {
        "service_line": service_name,
        "total_units": total_units,
        "staffed_pct": active["staffed_pct"],
        "units_covered": active["units_covered"],
        "unit_rev": unit_rev,
        "unit_cost": unit_cost,
        "referrals_per_unit": referrals_per_unit,
        "referral_revenue": round(active["referral_rev"], 2),
        "gross_rev": round(active["gross_rev"], 2),
        "operating_cost": round(active["operating_cost"], 2),
        "net_before_locum": round(active["net_before"], 2),
        "locum_total": round(active["locum_total"], 2),
        "net_after_locum": round(active["net_after"], 2),
    }
    st.code(",".join(str(v) for v in row.values()))
    st.success("Scenario copied below as a CSV row.")
