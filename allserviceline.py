# allserviceline_v2_toggle_additive.py
# Additive upgrade of your original app:
# - Keeps existing service lines & Analyst flow intact
# - Adds an Executive (Simple) toggle for Interventional Cardiology only
# - Safer math (staffed% clamp) + symmetric missed-opportunity using referral mix
# - Executive PDF reporting with charts (pie charts for case mix and economics)

import math
from typing import Dict, Any, List, Optional, Tuple
import streamlit as st

try:
    import yaml
except Exception:
    yaml = None

import io
from io import BytesIO

import matplotlib.pyplot as plt

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
    # Same sample shape as your original app
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
        },
        # --- You can add an IC entry to enable the Simple view ---
        {
            "key": "ic_interventional",
            "display_name": "Interventional Cardiology",
            "capacity_label": "Units",
            "category": "interventional_cardiology",
            "default": {"total_units": 8, "occupancy_pct": 80, "unit_rev": 9000, "unit_cost": 4500, "referrals_per_unit": 1.0},
            "referrals": {"revenue_per_referral": 350, "types": [
                {"name": "Echo", "pct": 35, "unit_rev": 350},
                {"name": "Cardiac Rehab", "pct": 20, "unit_rev": 1800},
                {"name": "Clinic Follow-up", "pct": 40, "unit_rev": 220},
                {"name": "Other", "pct": 5, "unit_rev": 200},
            ]},
            "locum": {"enabled": True, "default_count": 1, "utilization_pct": 15, "hourly_rate": 425, "hours_per_shift": 24, "travel_per_day": 0},
            # Simple-mode defaults live under `ic_simple` so they don't interfere with advanced inputs
            "ic_simple": {
                "capture_map": {"None": 0.25, "Business Hours Only": 0.55, "24/7/365": 0.85},
                "diagnostic_per_cp": 0.35,
                "pci_per_cp": 0.12,
                "rev_diag": 8500.0, "cost_diag": 4000.0,
                "rev_pci": 22000.0, "cost_pci": 11000.0,
                "providers_needed_247": 4,
                "locum_util_factor": 0.15,
            }
        }]
    }
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
SERVICE_MAP = {sl.get("display_name", sl.get("key", f"svc_{i}")): sl for i, sl in enumerate(CFG.get("service_lines", []))}

service_name = st.selectbox("Select Service Line", list(SERVICE_MAP.keys()))
svc = SERVICE_MAP[service_name]
cap_label = svc.get("capacity_label", "Units")

# --- Helper: detect if this service is Interventional Cardiology for Simple mode ---
def is_ic_service(svc: Dict[str, Any]) -> bool:
    name = (svc.get("display_name") or svc.get("key") or "").lower()
    cat = (svc.get("category") or "").lower()
    return ("cardio" in name) or (cat == "interventional_cardiology") or (svc.get("ic_simple") is not None)

is_ic = is_ic_service(svc)

# Toggle only enabled for IC; others remain Analyst-only
simple_mode = st.toggle("Executive (Simple) Mode", value=is_ic, disabled=not is_ic, help="Quick 3–4 input view for Interventional Cardiology only. Analyst view remains available for all lines.")

# ---------------- Analyst (Advanced) Inputs (kept from your original app) ----------------
left, right = st.columns(2)
with left:
    total_units = st.number_input(f"Total {cap_label}", min_value=1, value=int(svc.get("default", {}).get("total_units", 1)))
    occupancy_pct = st.slider("Current Staffed % (without Locums)", 0, 100, int(svc.get("default", {}).get("occupancy_pct", 0)))
    unit_rev = st.number_input(
        f"Average Revenue per {cap_label[:-1] if cap_label.endswith('s') else cap_label} ($)",
        min_value=0.0, value=float(svc.get("default", {}).get("unit_rev", 0.0)), step=100.0)
    unit_cost = st.number_input(
        f"Average Cost per {cap_label[:-1] if cap_label.endswith('s') else cap_label} ($)",
        min_value=0.0, value=float(svc.get("default", {}).get("unit_cost", 0.0)), step=100.0)
with right:
    referrals_per_unit = st.number_input("Avg Patient Downstream per Unit", min_value=0.0,
                                         value=float(svc.get("default", {}).get("referrals_per_unit", 0.0)), step=0.1)
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

# ---------------- Referral inputs (kept) ----------------
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

# ---------- Core functions (kept, with small safety tweaks) ----------

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
    staffed_pct = max(0, min(100, staffed_pct))  # clamp early
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
    staffed_pct=occupancy_pct + (locum_util_pct_ui if use_locums else 0),
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

# ---------- Executive (Simple) view for IC ----------
exec_metrics: Optional[Dict[str, float]] = None
if simple_mode and is_ic:
    st.header("🫀 Interventional Cardiology — Executive View")
    ic_s = svc.get("ic_simple", {})
    cap_map = ic_s.get("capture_map", {"None": 0.25, "Business Hours Only": 0.55, "24/7/365": 0.85})

    c1, c2, c3 = st.columns(3)
    with c1:
        ed_visits = st.number_input("Annual ED Visits", min_value=0, value=25000, step=500)
        coverage = st.selectbox("Current Interventional Coverage", list(cap_map.keys()), index=1)
    with c2:
        chest_pain_pct = st.slider("Chest Pain / Cardiac Flag % of ED", 0, 100, 8)
        providers = st.number_input("Interventional Cardiologists on Staff", min_value=0, value=1)
    with c3:
        loc_rate = st.number_input("Locums Hourly Rate ($)", min_value=0.0, value=float(svc.get("locum", {}).get("hourly_rate", 425.0)), step=25.0)
        st.text("")

    diag_per_cp = float(ic_s.get("diagnostic_per_cp", 0.35))
    pci_per_cp = float(ic_s.get("pci_per_cp", 0.12))
    rev_diag, cost_diag = float(ic_s.get("rev_diag", 8500.0)), float(ic_s.get("cost_diag", 4000.0))
    rev_pci, cost_pci = float(ic_s.get("rev_pci", 22000.0)), float(ic_s.get("cost_pci", 11000.0))
    providers_needed = int(ic_s.get("providers_needed_247", 4))
    util_factor = float(ic_s.get("locum_util_factor", 0.15))

    chest_pain_patients = ed_visits * (chest_pain_pct / 100.0)
    capture = float(cap_map.get(coverage, 0.55))

    diag_cases = chest_pain_patients * diag_per_cp * capture
    pci_cases = chest_pain_patients * pci_per_cp * capture

    gross = diag_cases * rev_diag + pci_cases * rev_pci
    cost = diag_cases * cost_diag + pci_cases * cost_pci
    margin = gross - cost

    gap = max(0, providers_needed - int(providers))
    annual_hours = 8760
    locums_spend = gap * annual_hours * util_factor * float(loc_rate)

    # Display metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Est. Annual Caths (Diagnostic)", f"{diag_cases:,.0f}")
    m2.metric("Est. Annual PCIs", f"{pci_cases:,.0f}")
    m3.metric("Net Margin (cases only)", f"${margin:,.0f}")

    m4, m5, m6 = st.columns(3)
    m4.metric("Gross Revenue", f"${gross:,.0f}")
    m5.metric("Direct Cost", f"${cost:,.0f}")
    m6.metric("Capture Rate", f"{capture:.0%}")

    st.markdown("---")
    g1, g2, g3 = st.columns(3)
    g1.metric("Providers Needed (24/7)", f"{providers_needed}")
    g2.metric("Provider Gap", f"{gap}")
    g3.metric("Rough Locums Spend for Gap", f"${locums_spend:,.0f}")

    # Build pie charts
    st.subheader("📈 Visuals (Executive)")

    fig1, ax1 = plt.subplots()
    ax1.pie([diag_cases, pci_cases], labels=["Diagnostics", "PCIs"], autopct='%1.0f%%')
    ax1.set_title("Case Mix")
    st.pyplot(fig1, use_container_width=True)

    # Economics composition: cost vs margin (positive only) to avoid negative slices
    pos_margin = max(0.0, margin)
    econ_values = [cost, pos_margin]
    econ_labels = ["Direct Cost", "Net Margin"]
    fig2, ax2 = plt.subplots()
    ax2.pie(econ_values, labels=econ_labels, autopct='%1.0f%%')
    ax2.set_title("Economics Composition")
    st.pyplot(fig2, use_container_width=True)

    # Keep for export
    exec_metrics = {
        "ed_visits": ed_visits,
        "chest_pain_pct": chest_pain_pct,
        "coverage": coverage,
        "providers": providers,
        "loc_rate": loc_rate,
        "diag_cases": diag_cases,
        "pci_cases": pci_cases,
        "gross": gross,
        "cost": cost,
        "margin": margin,
        "providers_needed": providers_needed,
        "gap": gap,
        "locums_spend": locums_spend,
    }

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

# ---- Analyst visuals (pie charts) ----
# Revenue composition: unit revenue vs referral revenue
fig_rev, ax_rev = plt.subplots()
rev_unit = max(0.0, active['gross_rev'])
rev_ref = max(0.0, active['referral_rev'])
if (rev_unit + rev_ref) > 0:
    ax_rev.pie([rev_unit, rev_ref], labels=["Unit Revenue", "Referral Revenue"], autopct='%1.0f%%')
else:
    ax_rev.pie([1], labels=["No Revenue"], autopct='%1.0f%%')
ax_rev.set_title("Revenue Composition")
st.pyplot(fig_rev, use_container_width=True)

# Cost composition: operating vs locum cost
fig_cost, ax_cost = plt.subplots()
cost_oper = max(0.0, active['operating_cost'])
cost_loc = max(0.0, active['locum_total'])
if (cost_oper + cost_loc) > 0:
    ax_cost.pie([cost_oper, cost_loc], labels=["Operating Cost", "Locum Cost"], autopct='%1.0f%%')
else:
    ax_cost.pie([1], labels=["No Cost"], autopct='%1.0f%%')
ax_cost.set_title("Cost Composition")
st.pyplot(fig_cost, use_container_width=True)

# Export helpers for Analyst report
from io import BytesIO as _BIO

def _fig_to_png_bytes(fig):
    b = _BIO(); fig.savefig(b, format='png', bbox_inches='tight', dpi=180); plt.close(fig); b.seek(0); return b.getvalue()

analyst_revenue_png = _fig_to_png_bytes(fig_rev)
analyst_cost_png = _fig_to_png_bytes(fig_cost)


# Analysis period (days)
annual_days = st.number_input("Analysis Period Days", min_value=1, max_value=366, value=365)

# Symmetric missed revenue uses the same referral mix
missed_units = max(0, total_units - active["units_covered"])
missed_referral_rev = referral_revenue_for(100) - referral_revenue_for(active["staffed_pct"])  # same mix

# Period totals: if an exact TOTAL spend is provided and toggle is on, use it.
if use_locums and use_exact_total_toggle and (exact_total_spend_override or 0) > 0:
    period_locum_cost = float(exact_total_spend_override)
else:
    period_locum_cost = active["locum_total"] * annual_days

period_net = active["net_before"] * annual_days - period_locum_cost
period_missed = (missed_units * (float(unit_rev) - float(unit_cost)) + missed_referral_rev) * annual_days

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
        "missed_referral_rev_period": round(missed_referral_rev * annual_days, 2),
        "missed_units_period": missed_units * annual_days,
    }
    st.code(",".join(str(v) for v in row.values()))
    st.success("Scenario copied below as a CSV row.")

# -------------------------------
# Export to PDF (supports Executive visuals when enabled)
# -------------------------------

def _save_fig_as_png_bytes(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def build_pdf_bytes(exec_block=None, case_mix_png=None, econ_png=None, analyst_block=None, analyst_revenue_png=None, analyst_cost_png=None):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdfcanvas
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
    except Exception:
        st.error("ReportLab is required to export a PDF. Add 'reportlab' to requirements.txt and rerun.")
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

    # Executive block (if provided)
    if exec_block is not None:
        y -= 0.35 * inch
        c.setFont("Helvetica-Bold", 11)
        c.drawString(0.75 * inch, y, "Executive (Interventional Cardiology)")
        c.setFont("Helvetica", 9)
        y -= 0.16 * inch
        lines = [
            f"ED Visits: {int(exec_block['ed_visits']):,}",
            f"Chest Pain %: {exec_block['chest_pain_pct']}%",
            f"Coverage: {exec_block['coverage']}",
            f"IC on Staff: {int(exec_block['providers'])}",
            f"Locums $/hr: ${exec_block['loc_rate']:,.0f}",
            f"Est. Diagnostics: {exec_block['diag_cases']:,.0f}",
            f"Est. PCIs: {exec_block['pci_cases']:,.0f}",
            f"Gross: ${exec_block['gross']:,.0f}  Cost: ${exec_block['cost']:,.0f}  Net: ${exec_block['margin']:,.0f}",
            f"Providers Needed 24/7: {int(exec_block['providers_needed'])}  Gap: {int(exec_block['gap'])}",
            f"Rough Locums Spend (Gap): ${exec_block['locums_spend']:,.0f}",
        ]
        for L in lines:
            c.drawString(0.8 * inch, y, f"• {L}")
            y -= 0.16 * inch

        # Insert charts if available
        if case_mix_png is not None:
            img = ImageReader(BytesIO(case_mix_png))
            c.drawImage(img, 0.75 * inch, y - 2.6 * inch, width=3.7 * inch, height=2.6 * inch, preserveAspectRatio=True, mask='auto')
        if econ_png is not None:
            img2 = ImageReader(BytesIO(econ_png))
            c.drawImage(img2, 4.5 * inch, y - 2.6 * inch, width=3.7 * inch, height=2.6 * inch, preserveAspectRatio=True, mask='auto')
        y -= 2.8 * inch

    # Analyst visuals block (if provided)
    if analyst_block is not None:
        y -= 0.25 * inch
        c.setFont("Helvetica-Bold", 11)
        c.drawString(0.75 * inch, y, "Analyst View — Composition Charts")
        c.setFont("Helvetica", 9)
        y -= 0.16 * inch
        lines = [
            f"Units Covered: {analyst_block['units_covered']:,} / {analyst_block['total_units']:,}",
            f"Revenue — Unit: ${analyst_block['gross_rev']:,.0f}  Referral: ${analyst_block['referral_rev']:,.0f}",
            f"Costs — Operating: ${analyst_block['operating_cost']:,.0f}  Locum: ${analyst_block['locum_total']:,.0f}",
            f"Net After Locum: ${analyst_block['net_after']:,.0f}",
        ]
        for L in lines:
            c.drawString(0.8 * inch, y, f"• {L}")
            y -= 0.16 * inch
        if analyst_revenue_png is not None:
            ar = ImageReader(BytesIO(analyst_revenue_png))
            c.drawImage(ar, 0.75 * inch, y - 2.6 * inch, width=3.7 * inch, height=2.6 * inch, preserveAspectRatio=True, mask='auto')
        if analyst_cost_png is not None:
            ac = ImageReader(BytesIO(analyst_cost_png))
            c.drawImage(ac, 4.5 * inch, y - 2.6 * inch, width=3.7 * inch, height=2.6 * inch, preserveAspectRatio=True, mask='auto')
        y -= 2.8 * inch

    # Shift metrics
    y -= 0.2 * inch
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

# When in Executive IC mode, include a dedicated Executive Report button with charts
case_mix_png = econ_png = None
if exec_metrics is not None:
    # Rebuild charts silently for export
    fig1, ax1 = plt.subplots()
    ax1.pie([exec_metrics["diag_cases"], exec_metrics["pci_cases"]], labels=["Diagnostics", "PCIs"], autopct='%1.0f%%')
    ax1.set_title("Case Mix")
    case_mix_png = _save_fig_as_png_bytes(fig1)

    fig2, ax2 = plt.subplots()
    pos_margin = max(0.0, exec_metrics["margin"])
    ax2.pie([exec_metrics["cost"], pos_margin], labels=["Direct Cost", "Net Margin"], autopct='%1.0f%%')
    ax2.set_title("Economics Composition")
    econ_png = _save_fig_as_png_bytes(fig2)

    if st.button("Download Executive Report (PDF)"):
        pdf_bytes = build_pdf_bytes(exec_block=exec_metrics, case_mix_png=case_mix_png, econ_png=econ_png,
                                    analyst_block=None)
        if pdf_bytes:
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name="interventional_cardiology_executive_report.pdf",
                mime="application/pdf",
            )

# Analyst report always available; includes pies even if Executive is visible
analyst_block = {
    "units_covered": active["units_covered"],
    "total_units": total_units,
    "gross_rev": active["gross_rev"],
    "referral_rev": active["referral_rev"],
    "operating_cost": active["operating_cost"],
    "locum_total": active["locum_total"],
    "net_after": active["net_after"],
}
if st.button("Download Analyst Report (PDF)"):
    pdf_bytes = build_pdf_bytes(analyst_block=analyst_block, analyst_revenue_png=analyst_revenue_png, analyst_cost_png=analyst_cost_png)
    if pdf_bytes:
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{service_name.replace(' ', '_').lower()}_analyst_report.pdf",
            mime="application/pdf",
        )
