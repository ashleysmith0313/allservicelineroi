import math
from typing import Dict, Any, List, Optional
import streamlit as st

try:
    import yaml
except Exception:
    yaml = None

st.set_page_config(page_title="All-Service Line ROI Calculator", layout="centered")
st.title("🏥 All-Service Line ROI Calculator")
st.caption("All Revenue and Cost Values are assumptive and can be modified with actual values • Powered by VISTA")
# --- Disclaimer (visible, styled) ---
DISCLAIMER_HTML = """
<div style="
  border-left: 6px solid #f59e0b;
  background: #FFF7ED;
  padding: 14px 16px;
  border-radius: 12px;
  margin: 8px 0 20px 0;
  font-size: 0.95rem; line-height: 1.35;">
  <strong>Disclaimer:</strong> This tool produces <em>illustrative estimates</em>, not guarantees.
  All outputs are based on <em>assumptions, user-entered values, and generalized averages</em> derived from
  <em>publicly available benchmarks</em> (e.g., CMS datasets) and industry/commercial analyses
  (e.g., Definitive Healthcare) and may not reflect your organization’s actual performance.
  Results do not constitute financial, legal, or reimbursement advice. Actual results vary by
  payer mix, contracts, coding/DRG, case mix, and operations. Validate these figures with your
  internal finance data before making decisions. Do not use for rate setting, price quotes, or
  regulatory filings.
</div>
"""
st.markdown(DISCLAIMER_HTML, unsafe_allow_html=True)

# (Optional) tiny acknowledgment checkbox
ack = st.checkbox("I understand these are assumptions/estimates and not guarantees.", value=True)
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
    referrals_per_unit = st.number_input("Avg Patient Downstream per Unit", min_value=0.0,
                                         value=float(svc["default"].get("referrals_per_unit", 0.0)), step=0.1)
    revenue_per_referral = st.number_input("Baseline Downstream Revenue per Patient ($)", min_value=0.0,
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

# ---- UPDATED: Exact Locum Spend (Overall/Period) override ----
exact_total_spend_override: Optional[float] = None
use_exact_total_toggle: bool = False
if use_locums:
    st.markdown(
        f"""
        ### 🧮 Analysis Period Impact ({annual_days} Days)
        <div style='background-color:#d4f4dd;padding:1rem;border-radius:8px;'>
        <strong>Net ROI (Period): ${period_net:,.0f}</strong><br>
        <em>Locum Spend (Period): ${period_locum_cost:,.0f}{' • using exact total override' if (use_exact_total_toggle and (exact_total_spend_override or 0) > 0) else ''}</em>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        ### 🧮 Estimated Missed Opportunity (Period: {annual_days} Days)
        <div style='background-color:#990000;padding:1rem;border-radius:8px;color:white;'>
        <strong>Net Loss (Period): (${period_missed:,.0f})</strong>
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
        "staffed_pct": active["staffed_pct"],
        "units_covered": active["units_covered"],
        "unit_rev": unit_rev,
        "unit_cost": unit_cost,
        "referrals_per_unit": referrals_per_unit,
        "referral_revenue": round(active["referral_rev"], 2),
        "gross_rev": round(active["gross_rev"], 2),
        "operating_cost": round(active["operating_cost"], 2),
        "net_before_locum_per_shift": round(active["net_before"], 2),
        "locum_total_per_shift": round(active["locum_total"], 2),
        "net_after_locum_per_shift": round(active["net_after"], 2),
        "period_days": annual_days,
        "locum_total_period": round(period_locum_cost, 2),
        "net_after_locum_period": round(period_net, 2),
    }
    st.code(",".join(str(v) for v in row.values()))(",".join(str(v) for v in row.values()))
    st.success("Scenario copied below as a CSV row.")
