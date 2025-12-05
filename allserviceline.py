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

ack = st.checkbox("I understand these are assumptions/estimates and not guarantees.", value=True)

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
                                           value=float(svc.get("referrals", {}).get("revenue_per_referral", 0.0)), step=50.0)

st.subheader("👩‍⚕️ Locum Staffing")
loc_cfg = svc.get("locum", {})
use_locums = st.checkbox("Use Locums for this shift?", value=bool(loc_cfg.get("enabled", False)))

loc_col1, loc_col2, loc_col3 = st.columns(3)
with loc_col1:
    locum_count_ui = st.number_input("Locums per Shift", min_value=0, value=int(loc_cfg.get("default_count", 1)))
    hourly_rate_ui = st.number_input("Hourly Rate ($)", min_value=0.0, value=float(loc_cfg.get("hourly_rate", 0.0)), step=5.0)
with loc_col2:
    hours_per_shift_ui = st.number_input("Hours per Shift", min_value=1, max_value=24, value=int(loc_cfg.get("hours_per_shift", 10)))
    travel_per_day_ui = st.number_input("Travel/Housing per Day ($)", min_value=0.0, value=float(loc_cfg.get("travel_per_day", 0.0)), step=10.0)
with loc_col3:
    locum_util_pct_ui = st.slider("Locum Utilization %", 0, 100, int(loc_cfg.get("utilization_pct", 0)))

# ---- Exact Total Spend (Overall/Period) override ----
exact_total_spend_override: Optional[float] = None
use_exact_total_toggle: bool = False
if use_locums:
    st.markdown("**Exact Total Spend (optional)**: Enter your total locum spend for the entire analysis period (e.g., YTD or 365 days). This replaces the calculated per-shift spend × days.")
    use_exact_total_toggle = st.toggle(
        "Use exact total locum spend for the period?",
        value=False,
        help="If enabled, the exact amount below will be used for the period instead of (rate × hours + travel) × locum count × days.")
    if use_exact_total_toggle:
        exact_total_spend_override = float(st.number_input(
            "Exact Total Locum Spend for Analysis Period ($)",
            min_value=0.0,
            value=0.0,
            step=500.0,
            help="Enter what you actually paid to locums over the period.",
        ))

st.subheader("🔗 Revenue (Downstream)")
ref_cfg = svc.get("referrals", {})
ref_types: List[Dict[str, Any]] = ref_cfg.get("types", [])

cols = st.columns(max(1, len(ref_types)))
percent_values: List[int] = []
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


def scenario(
    staffed_pct: float,
    locum_count: int,
    hourly_rate: float,
    hours_per_shift: int,
    travel_per_day: float,
) -> Dict[str, float]:
    staffed_pct = max(0, min(100, staffed_pct))
    units_covered = int(round(total_units * staffed_pct / 100.0))
    gross_rev = units_covered * float(unit_rev)
    operating_cost = units_covered * float(unit_cost)
    ref_rev = referral_revenue_for(staffed_pct)
    locum_cost_per = (hourly_rate * hours_per_shift + travel_per_day) * locum_count
    net_before = gross_rev + ref_rev - operating_cost
    net_after = net_before - locum_cost_per
    return {
        "staffed_pct": staffed_pct,
        "units_covered": units_covered,
        "gross_rev": gross_rev,
        "operating_cost": operating_cost,
        "referral_rev": ref_rev,
        "locum_total": locum_cost_per,
        "net_before": net_before,
        "net_after": net_after,
    }

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

active = with_locums if use_locums else without_locums

# Analysis period (days)
annual_days = st.number_input("Analysis Period Days", min_value=1, max_value=366, value=365)

# Period totals: if an exact TOTAL spend is provided and toggle is on, use it.
if use_locums and use_exact_total_toggle and (exact_total_spend_override is not None) and (exact_total_spend_override > 0):
    period_locum_cost = exact_total_spend_override
else:
    period_locum_cost = active["locum_total"] * annual_days

period_net = active["net_before"] * annual_days - period_locum_cost

missed_units = max(0, total_units - active["units_covered"])
period_missed = missed_units * (float(unit_rev) + referrals_per_unit * float(revenue_per_referral) - float(unit_cost)) * annual_days

st.header("📊 Shift Financial Summary")
met1, met2, met3 = st.columns(3)
with met1:
    st.metric(f"{cap_label} Staffed This Shift", active["units_covered"])
    st.metric(f"Unstaffed {cap_label}", total_units - active["units_covered"])
with met2:
    st.metric("Gross Revenue from Staffed Units", f"${active['gross_rev']:,.0f}")
    st.metric("Operating Cost for Staffed Units", f"${active['operating_cost']:,.0f}")
with met3:
    st.metric("Downstream Revenue Generated", f"${active['referral_rev']:,.0f}")
    st.metric("Net Margin Before Locum Cost", f"${active['net_before']:,.0f}")

st.metric("🔥 Net Financial Impact (After Locum)", f"${active['net_after']:,.0f}")

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
    st.code(",".join(str(v) for v in row.values()))
    st.success("Scenario copied below as a CSV row.")

# -------------------------------
# Export to PDF (text-only snapshot; no charts)
# -------------------------------
from io import BytesIO

def build_pdf_bytes():
    try:
        # Lazy imports so the app runs even if libs are missing until export is clicked
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdfcanvas
        from reportlab.lib.units import inch
    except Exception:
        st.error("ReportLab is required to export a PDF. Add 'reportlab' to your requirements.txt and rerun.")
        return None

    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, height = letter

    y = height - 0.75 * inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, y, "All-Service Line ROI Snapshot")

    c.setFont("Helvetica", 9)
    y -= 0.25 * inch
    c.drawString(0.75 * inch, y, f"Service Line: {service_name}")
    y -= 0.18 * inch
    c.drawString(0.75 * inch, y, f"Analysis Period (days): {annual_days}")

    # Inputs grid
    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Inputs")
    c.setFont("Helvetica", 9)
    y -= 0.18 * inch
    inputs = [
        (f"Total {cap_label}", total_units),
        ("Staffed % (base)", f"{occupancy_pct}%"),
        ("Locum Utilization %", f"{locum_util_pct_ui}%" if use_locums else "0%"),
        (f"Revenue per {cap_label[:-1] if cap_label.endswith('s') else cap_label}", f"${unit_rev:,.0f}"),
        (f"Cost per {cap_label[:-1] if cap_label.endswith('s') else cap_label}", f"${unit_cost:,.0f}"),
        ("Referrals per Unit", referrals_per_unit),
        ("Revenue per Referral (baseline)", f"${revenue_per_referral:,.0f}"),
    ]
    for k, v in inputs:
        c.drawString(0.8 * inch, y, f"• {k}: {v}")
        y -= 0.16 * inch

    # Referral mix
    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Referral Mix")
    c.setFont("Helvetica", 9)
    y -= 0.18 * inch
    for pct, rt in zip(percent_values, ref_types):
        line = f"{rt.get('name','Type')}: {pct}% @ ${float(rt.get('unit_rev', revenue_per_referral)):,.0f}"
        c.drawString(0.8 * inch, y, f"• {line}")
        y -= 0.16 * inch

    # Metrics grid
    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Shift Financial Summary")
    y -= 0.18 * inch
    c.setFont("Helvetica", 9)
    metrics = [
        (f"{cap_label} Staffed", f"{active['units_covered']:,}"),
        (f"Unstaffed {cap_label}", f"{(total_units - active['units_covered']):,}"),
        ("Gross Revenue", f"${active['gross_rev']:,.0f}"),
        ("Operating Cost", f"${active['operating_cost']:,.0f}"),
        ("Downstream Revenue", f"${active['referral_rev']:,.0f}"),
        ("Net Before Locum", f"${active['net_before']:,.0f}"),
        ("Locum Cost (shift)", f"${active['locum_total']:,.0f}"),
        ("Net After Locum", f"${active['net_after']:,.0f}"),
    ]
    for k, v in metrics:
        c.drawString(0.8 * inch, y, f"• {k}: {v}")
        y -= 0.16 * inch

    # Period impact
    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y, "Analysis Period Impact")
    y -= 0.18 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.8 * inch, y, f"Locum Spend (Period): ${period_locum_cost:,.0f}")
    y -= 0.16 * inch
    c.drawString(0.8 * inch, y, f"Net ROI (Period): ${period_net:,.0f}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()

st.subheader("📄 Export")
if st.button("Generate PDF Snapshot"):
    pdf_bytes = build_pdf_bytes()
    if pdf_bytes:
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{service_name.replace(' ', '_').lower()}_roi_snapshot.pdf",
            mime="application/pdf",
        )
    else:
        st.stop()

