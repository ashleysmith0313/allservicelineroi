import math
from typing import Dict, Any, List

import streamlit as st

try:
    import yaml
except Exception:
    yaml = None

st.set_page_config(page_title="All-Service Line ROI Calculator", layout="centered")
st.title("🏥 All-Service Line ROI Calculator")
st.caption("Modeled on your Hospitalist ROI app • Powered by VISTA")

# -------------------------------
# Config loading
# -------------------------------
@st.cache_data
def load_config() -> Dict[str, Any]:
    """Load YAML config from ./config/service_lines.yaml if present, else fall back to sample."""
    sample = {
        "service_lines": [
            {
                "key": "hospitalist_med_surg",
                "display_name": "Daytime Hospitalist (Med-Surg only)",
                "capacity_label": "Beds",
                "default": {
                    "total_units": 18,
                    "occupancy_pct": 75,
                    "unit_rev": 2750,
                    "unit_cost": 1850,
                    "referrals_per_unit": 1.2,
                },
                "referrals": {
                    "revenue_per_referral": 900,
                    "types": [
                        {"name": "Cardiology", "pct": 30, "unit_rev": 500},
                        {"name": "GI", "pct": 25, "unit_rev": 1200},
                        {"name": "Surgery", "pct": 25, "unit_rev": 3000},
                        {"name": "Imaging/Diagnostics", "pct": 20, "unit_rev": 800},
                    ],
                },
                "locum": {
                    "enabled": True,
                    "default_count": 1,
                    "utilization_pct": 80,
                    "hourly_rate": 265,
                    "hours_per_shift": 10,
                    "travel_per_day": 390,
                },
            }
        ]
    }

    if yaml is None:
        return sample

    import os
    cfg_path = os.path.join("config", "service_lines.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            # basic validation
            if isinstance(data, dict) and data.get("service_lines"):
                return data
    return sample

CFG = load_config()
SERVICE_MAP = {sl["display_name"]: sl for sl in CFG.get("service_lines", [])}

# -------------------------------
# UI: service line selection & defaults
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
        min_value=0.0,
        value=float(svc["default"].get("unit_rev", 0.0)),
        step=100.0,
    )
    unit_cost = st.number_input(
        f"Average Cost per {cap_label[:-1] if cap_label.endswith('s') else cap_label} ($)",
        min_value=0.0,
        value=float(svc["default"].get("unit_cost", 0.0)),
        step=100.0,
    )

with right:
    referrals_per_unit = st.number_input(
        "Avg Referrals per Unit", min_value=0.0, value=float(svc["default"].get("referrals_per_unit", 0.0)), step=0.1
    )
    revenue_per_referral = st.number_input(
        "Baseline Revenue per Referral ($)",
        min_value=0.0,
        value=float(svc.get("referrals", {}).get("revenue_per_referral", 0.0)),
        step=50.0,
    )

# -------------------------------
# Locum inputs (optional)
# -------------------------------
st.subheader("👩‍⚕️ Locum Staffing Cost")
locum_enabled_default = bool(svc.get("locum", {}).get("enabled", False))
use_locums = st.checkbox("Use Locums?", value=locum_enabled_default)
if use_locums:
    loc_col1, loc_col2, loc_col3 = st.columns(3)
    with loc_col1:
        locum_count = st.number_input("Locums per Shift", min_value=0, value=int(svc.get("locum", {}).get("default_count", 1)))
        hourly_rate = st.number_input("Hourly Rate ($)", min_value=0.0, value=float(svc.get("locum", {}).get("hourly_rate", 0.0)), step=5.0)
    with loc_col2:
        hours_per_shift = st.number_input("Hours per Shift", min_value=1, max_value=24, value=int(svc.get("locum", {}).get("hours_per_shift", 10)))
        travel_per_day = st.number_input("Travel/Housing per Day ($)", min_value=0.0, value=float(svc.get("locum", {}).get("travel_per_day", 0.0)), step=10.0)
    with loc_col3:
        locum_utilization_pct = st.slider("Locum Utilization %", 0, 100, int(svc.get("locum", {}).get("utilization_pct", 0)))
else:
    locum_count = 0
    hourly_rate = 0.0
    hours_per_shift = 10
    travel_per_day = 0.0
    locum_utilization_pct = 0

locum_cost_per = hourly_rate * hours_per_shift + travel_per_day
locum_total = locum_cost_per * locum_count if use_locums else 0.0

# -------------------------------
# Referral mix
# -------------------------------
st.subheader("🔗 Referral Revenue (Downstream)")
ref_cfg = svc.get("referrals", {})
ref_types: List[Dict[str, Any]] = ref_cfg.get("types", [])

staffed_pct = occupancy_pct + (locum_utilization_pct if use_locums else 0)
staffed_pct = max(0, min(100, staffed_pct))  # cap 0–100
units_covered = int(round(total_units * (staffed_pct / 100.0)))

ref_total = total_units * referrals_per_unit * (staffed_pct / 100.0)
st.write(f"📄 Estimated Total Referrals This Shift: **{ref_total:.1f}**")

# sliders for referral type %
cols = st.columns(max(1, len(ref_types)))
percent_values = []
for i, rt in enumerate(ref_types):
    with cols[i % len(cols)]:
        pct = st.slider(f"{rt.get('name', f'Type {i+1}')} (%)", 0, 100, int(rt.get("pct", 0)))
        percent_values.append(pct)

pct_sum = sum(percent_values)
normalize = st.toggle("Auto-normalize referral % to 100% when off by a little", value=True)

if pct_sum != 100:
    if normalize and pct_sum > 0:
        # scale all to sum 100
        scale = 100.0 / pct_sum
        percent_values = [round(p * scale) for p in percent_values]
        # fix rounding drift
        drift = 100 - sum(percent_values)
        if percent_values:
            percent_values[0] += drift
        pct_sum = sum(percent_values)
    else:
        st.warning("Referral type percentages must total 100%. Adjust sliders or enable auto-normalize.")

# compute referral revenue by type
referral_revenue = 0.0
for pct, rt in zip(percent_values, ref_types):
    rt_referrals = ref_total * (pct / 100.0)
    rt_unit_rev = float(rt.get("unit_rev", revenue_per_referral))
    referral_revenue += rt_referrals * rt_unit_rev

# -------------------------------
# Core financial math
# -------------------------------
gross_rev = units_covered * float(unit_rev)
operating_cost = units_covered * float(unit_cost)
net_before_locum = gross_rev + referral_revenue - operating_cost
net_after_locum = net_before_locum - locum_total

annual_days = st.number_input("Annualization Days", min_value=1, max_value=366, value=365)
annualized_net = net_after_locum * annual_days
annualized_locum_cost = locum_total * annual_days
missed_units = max(0, total_units - units_covered)
annualized_missed = missed_units * (float(unit_rev) + referrals_per_unit * float(revenue_per_referral) - float(unit_cost)) * annual_days

# -------------------------------
# Output summary
# -------------------------------
st.header("📊 Shift Financial Summary")
met1, met2, met3 = st.columns(3)
with met1:
    st.metric(f"{cap_label} Staffed This Shift", units_covered)
    st.metric(f"Unstaffed {cap_label}", missed_units)
with met2:
    st.metric("Gross Revenue from Staffed Units", f"${gross_rev:,.0f}")
    st.metric("Operating Cost for Staffed Units", f"${operating_cost:,.0f}")
with met3:
    st.metric("Referral Revenue Generated", f"${referral_revenue:,.0f}")
    st.metric("Net Margin Before Locum Cost", f"${net_before_locum:,.0f}")

st.metric("🔥 Net Financial Impact (After Locum)", f"${net_after_locum:,.0f}")

if use_locums:
    st.markdown(
        f"""
        ### 🧮 Estimated Annual Impact ({annual_days} Days)
        <div style='background-color:#d4f4dd;padding:1rem;border-radius:8px;'>
        <strong>Annualized Net ROI (With Locum): ${annualized_net:,.0f}</strong><br>
        <em>Annualized Locum Cost: ${annualized_locum_cost:,.0f}</em>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        ### 🧮 Estimated Annual Missed Opportunity ({annual_days} Days)
        <div style='background-color:#990000;padding:1rem;border-radius:8px;color:white;'>
        <strong>Annualized Net Loss: (${annualized_missed:,.0f})</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -------------------------------
# Scenario export (CSV-style line)
# -------------------------------
if st.button("Copy Scenario Row"):
    row = {
        "service_line": service_name,
        "total_units": total_units,
        "staffed_pct": staffed_pct,
        "units_covered": units_covered,
        "unit_rev": unit_rev,
        "unit_cost": unit_cost,
        "referrals_per_unit": referrals_per_unit,
        "referral_revenue": round(referral_revenue, 2),
        "gross_rev": round(gross_rev, 2),
        "operating_cost": round(operating_cost, 2),
        "net_before_locum": round(net_before_locum, 2),
        "locum_total": round(locum_total, 2),
        "net_after_locum": round(net_after_locum, 2),
        "annualized_net": round(annualized_net, 2),
    }
    st.code(",".join(str(v) for v in row.values()))
    st.success("Scenario copied below as a CSV row.")