# streamlit_app/app.py
import json
from dataclasses import dataclass, asdict
from typing import Dict, Any
import math

import streamlit as st

# ----------------------------
# Styling (compact KPI "pills")
# ----------------------------
PILL_CSS = """
<style>
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 8px 0 18px 0; }
.kpi-pill { border-radius: 10px; padding: 12px 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.kpi-pill h4 { margin: 0 0 6px 0; font-weight: 600; font-size: 0.85rem; color: rgba(0,0,0,0.66); }
.kpi-pill .val { font-size: 1.65rem; font-weight: 700; letter-spacing: -0.3px; }
.kpi-good { background: #16a34a; color: #fff; }
.kpi-bad  { background: #991b1b; color: #fff; }
.kpi-neutral { background: #f7f7f9; color: #111; }
.section { border-top: 1px solid rgba(0,0,0,0.07); margin-top: 16px; padding-top: 12px; }
.hero { padding: 10px 14px; border-radius: 12px; background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%); color: white; margin-bottom: 14px; }
.hero .title { font-size: 1.2rem; font-weight: 700; margin: 0 0 3px 0; }
.hero .subtitle { opacity: 0.95; }
.small-note { font-size: 0.84rem; color: rgba(0,0,0,0.58); }
.pill-controls { display: flex; gap: 8px; flex-wrap: wrap; }
.pill-button { padding: 6px 10px; border-radius: 999px; background: #eef2ff; color: #3730a3; cursor: pointer; border: 1px solid #e0e7ff; font-size: 0.85rem; }
.pill-button:hover { background: #e0e7ff; }
.delta { font-size: 0.9rem; opacity: 0.9; }
.divider { height: 10px; }
</style>
"""
st.set_page_config(page_title="All Service-Line ROI", page_icon="✅", layout="wide")
st.markdown(PILL_CSS, unsafe_allow_html=True)

# ----------------------------
# Seed configs (base Medicare-ish)
# ----------------------------
SERVICE_LINES = {
    "Hospitalist": dict(unit_type="shift", units_label="Encounters/shift", units=18,
                        direct_per_unit=180.0, # per encounter
                        referral_rate=0.05, referral_rev=300.0,
                        variable_cost_pct=0.20, safe_capacity=22, locum_cost=2500.0),
    "Radiology (DX/CT blend)": dict(unit_type="study", units_label="Studies/shift", units=40,
                        direct_per_unit=150.0, referral_rate=0.12, referral_rev=600.0,
                        variable_cost_pct=0.20, safe_capacity=50, locum_cost=2400.0),
    "Anesthesia": dict(unit_type="procedure", units_label="Procedures/day", units=10,
                        direct_per_unit=500.0, referral_rate=0.10, referral_rev=800.0,
                        variable_cost_pct=0.20, safe_capacity=12, locum_cost=3500.0),
    "Surgery (Gen)": dict(unit_type="case", units_label="Cases/day", units=6,
                        direct_per_unit=3500.0, referral_rate=0.25, referral_rev=2000.0,
                        variable_cost_pct=0.20, safe_capacity=7, locum_cost=4000.0),
    "Emergency Dept": dict(unit_type="visit", units_label="Visits/shift", units=30,
                        direct_per_unit=220.0, referral_rate=0.12, referral_rev=600.0,
                        variable_cost_pct=0.20, safe_capacity=40, locum_cost=2800.0),
}

PRESETS = {
    "Conservative": 0.90,
    "Base": 1.00,
    "Stretch": 1.10,
}

@dataclass
class Inputs:
    service_line: str
    preset: str
    units: float
    direct_per_unit: float
    referral_rate: float
    referral_rev: float
    variable_cost_pct: float
    safe_capacity: float

    locums_per_shift: int
    locum_cost_per_shift: float
    travel_per_locum: float
    amortize_travel: bool
    amortization_shifts: int

    show_payer_mix: bool
    payer_medicare_pct: float
    payer_commercial_pct: float
    payer_medicaid_pct: float
    # payer factors multiply base Medicare-ish direct rate
    medicare_factor: float
    commercial_factor: float
    medicaid_factor: float

    show_finance_settings: bool
    overhead_base: str  # 'direct' or 'total'
    overhead_pct: float

    show_costs_plus: bool
    add_call_stipend: float
    add_overtime_premium: float
    add_holiday_premium: float

    coverage_days_per_year: int
    utilization_pct: float

def format_money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"

def normalized_payer_mix(i: Inputs):
    total = i.payer_medicare_pct + i.payer_commercial_pct + i.payer_medicaid_pct
    if total == 0:
        return 0.33, 0.34, 0.33, True
    m = i.payer_medicare_pct / total
    c = i.payer_commercial_pct / total
    md = i.payer_medicaid_pct / total
    changed = abs(total - 1.0) > 1e-6
    return m, c, md, changed

def blended_direct_rate(i: Inputs) -> float:
    # Base direct_per_unit is roughly Medicare; apply payer factors
    m, c, md, changed = normalized_payer_mix(i)
    rate = i.direct_per_unit * (m * i.medicare_factor + c * i.commercial_factor + md * i.medicaid_factor)
    if changed and i.show_payer_mix:
        st.info("Payer mix auto‑normalized to 100%.")
    return rate

def _travel_cost_total(i: Inputs) -> float:
    if not i.amortize_travel or i.amortization_shifts <= 0:
        return i.travel_per_locum * i.locums_per_shift
    # amortize per-locum travel over N shifts
    return (i.travel_per_locum / i.amortization_shifts) * i.locums_per_shift

def calculate_shift(i: Inputs, with_locum: bool) -> Dict[str, float]:
    units = i.units if with_locum else 0.0
    direct_rate = blended_direct_rate(i)
    direct_revenue = units * direct_rate
    variable_costs = units * direct_rate * i.variable_cost_pct
    downstream = units * i.referral_rate * i.referral_rev

    coverage_cost = 0.0
    if with_locum:
        coverage_cost = i.locums_per_shift * i.locum_cost_per_shift + _travel_cost_total(i)
        coverage_cost += i.add_call_stipend + i.add_overtime_premium + i.add_holiday_premium

    if i.overhead_base == "direct":
        overhead = (direct_revenue) * i.overhead_pct
    else:
        overhead = (direct_revenue + downstream) * i.overhead_pct

    total_costs = variable_costs + coverage_cost + overhead
    net = (direct_revenue + downstream) - total_costs

    return dict(
        units=units,
        direct_revenue=direct_revenue,
        downstream=downstream,
        variable_costs=variable_costs,
        coverage_cost=coverage_cost,
        overhead=overhead,
        total_costs=total_costs,
        net=net,
        roi=(net / coverage_cost) if with_locum and coverage_cost else float("nan"),
    )

def calculate_annual(i: Inputs, shift_result: Dict[str, float]) -> Dict[str, float]:
    days = i.coverage_days_per_year
    util = i.utilization_pct
    factor = days * util
    return {k: (v * factor if isinstance(v, (int, float)) and math.isfinite(v) else v)
            for k, v in shift_result.items()}

def breakeven_locum_cost(i: Inputs) -> float:
    # Solve for coverage_cost where net = 0
    tmp = calculate_shift(i, with_locum=True)
    # Replace coverage_cost with variable; net = (dir+down - var - overhead - cov) = 0
    dir_plus_down = tmp["direct_revenue"] + tmp["downstream"]
    var_plus_oh = tmp["variable_costs"] + (tmp["overhead"])
    cov_other = tmp["coverage_cost"]  # current; we will compute what BE should be ignoring current
    # Current coverage cost components we control explicitly:
    fixed_adders = i.add_call_stipend + i.add_overtime_premium + i.add_holiday_premium
    travel_now = _travel_cost_total(i)
    per_locum_cost = i.locum_cost_per_shift
    # breakeven coverage cost total:
    be_total_coverage = max(0.0, dir_plus_down - var_plus_oh)
    # if we want the BE locum cost portion (subtract travel + adders):
    be_locum_component = max(0.0, be_total_coverage - (travel_now + fixed_adders))
    return be_locum_component

def kpi_pill(label: str, value: str, good: bool=None):
    cls = "kpi-neutral"
    if good is True:
        cls = "kpi-good"
    elif good is False:
        cls = "kpi-bad"
    st.markdown(f"""
    <div class="kpi-pill {cls}">
      <h4>{label}</h4>
      <div class="val">{value}</div>
    </div>
    """, unsafe_allow_html=True)

# ----------------------------
# UI
# ----------------------------
with st.container():
    st.markdown(
        '<div class="hero"><div class="title">All Service‑Line ROI</div>'
        '<div class="subtitle">Quick compare: Locum coverage vs No coverage — compact, CFO‑friendly</div></div>',
        unsafe_allow_html=True
    )

c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1.8])
with c1:
    service_line = st.selectbox("Service line", list(SERVICE_LINES.keys()))
with c2:
    preset = st.selectbox("Preset", list(PRESETS.keys()), index=1)
with c3:
    locums_per_shift = st.number_input("Locums per shift", 1, 10, 1)
with c4:
    st.markdown('<div class="small-note">Use presets for quick ballparks. Adjust details below.</div>', unsafe_allow_html=True)

cfg = SERVICE_LINES[service_line]
preset_mult = PRESETS[preset]

colA, colB, colC, colD = st.columns(4)
with colA:
    units = st.number_input(cfg["units_label"], min_value=0.0, value=round(cfg["units"] * preset_mult, 2))
with colB:
    direct_per_unit = st.number_input("Direct revenue / unit (base)", min_value=0.0, value=cfg["direct_per_unit"])
with colC:
    referral_rate = st.slider("Referral %", 0.0, 0.9, float(cfg["referral_rate"]), step=0.01)
with colD:
    referral_rev = st.number_input("Referral revenue / case", min_value=0.0, value=cfg["referral_rev"])

colE, colF, colG, colH = st.columns(4)
with colE:
    variable_cost_pct = st.slider("General operating cost (% of direct)", 0.0, 0.9, float(cfg["variable_cost_pct"]), step=0.01)
with colF:
    safe_capacity = st.number_input("Safe capacity (units/shift)", min_value=1.0, value=float(cfg["safe_capacity"]))
with colG:
    locum_cost_per_shift = st.number_input("Locum cost per shift", min_value=0.0, value=float(cfg["locum_cost"]))
with colH:
    travel_per_locum = st.number_input("Travel & lodging per locum", min_value=0.0, value=600.0)

colI, colJ = st.columns(2)
with colI:
    amortize_travel = st.checkbox("Amortize travel over multiple shifts", value=True)
with colJ:
    amortization_shifts = st.number_input("Amortization shifts", min_value=1, value=10)

# Toggles
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
t1, t2, t3 = st.columns([1,1,1])
with t1:
    show_payer_mix = st.toggle("Show Payer Mix", value=False)
with t2:
    show_finance_settings = st.toggle("Finance Settings", value=False)
with t3:
    show_costs_plus = st.toggle("Costs+", value=False)

# Payer mix panel
payer_vals = dict(
    payer_medicare_pct=0.5, payer_commercial_pct=0.35, payer_medicaid_pct=0.15,
    medicare_factor=1.00, commercial_factor=1.30, medicaid_factor=0.80
)
if show_payer_mix:
    st.markdown('<div class="section"></div>', unsafe_allow_html=True)
    pm1, pm2, pm3, pm4, pm5, pm6 = st.columns(6)
    with pm1:
        payer_vals["payer_medicare_pct"] = st.number_input("Medicare %", 0.0, 1.0, 0.5, step=0.01)
    with pm2:
        payer_vals["payer_commercial_pct"] = st.number_input("Commercial %", 0.0, 1.0, 0.35, step=0.01)
    with pm3:
        payer_vals["payer_medicaid_pct"] = st.number_input("Medicaid %", 0.0, 1.0, 0.15, step=0.01)
    with pm4:
        payer_vals["medicare_factor"] = st.number_input("Medicare factor", 0.0, 5.0, 1.00, step=0.05)
    with pm5:
        payer_vals["commercial_factor"] = st.number_input("Commercial factor", 0.0, 5.0, 1.30, step=0.05)
    with pm6:
        payer_vals["medicaid_factor"] = st.number_input("Medicaid factor", 0.0, 5.0, 0.80, step=0.05)

# Finance settings
overhead_base = "direct"
overhead_pct = 0.10
if show_finance_settings:
    st.markdown('<div class="section"></div>', unsafe_allow_html=True)
    fs1, fs2 = st.columns(2)
    with fs1:
        overhead_base = st.radio("Apply overhead on:", ["direct", "total"], horizontal=True, index=0)
    with fs2:
        overhead_pct = st.slider("Overhead %", 0.0, 0.5, 0.10, step=0.01)

# Costs+
add_call_stipend = 0.0
add_overtime_premium = 0.0
add_holiday_premium = 0.0
st.markdown('<div class="section"></div>', unsafe_allow_html=True)
cdy, util = st.columns(2)
with cdy:
    coverage_days_per_year = st.number_input("Coverage days / year", min_value=1, value=260)
with util:
    utilization_pct = st.slider("Utilization %", 0.1, 1.0, 0.90, step=0.05)

if show_costs_plus:
    st.markdown('<div class="section"></div>', unsafe_allow_html=True)
    cp1, cp2, cp3 = st.columns(3)
    with cp1:
        add_call_stipend = st.number_input("Call stipend (per shift)", min_value=0.0, value=0.0)
    with cp2:
        add_overtime_premium = st.number_input("Overtime premium (per shift)", min_value=0.0, value=0.0)
    with cp3:
        add_holiday_premium = st.number_input("Holiday premium (per shift)", min_value=0.0, value=0.0)

# Assemble inputs
i = Inputs(
    service_line=service_line,
    preset=preset,
    units=units,
    direct_per_unit=direct_per_unit,
    referral_rate=referral_rate,
    referral_rev=referral_rev,
    variable_cost_pct=variable_cost_pct,
    safe_capacity=safe_capacity,
    locums_per_shift=locums_per_shift,
    locum_cost_per_shift=locum_cost_per_shift,
    travel_per_locum=travel_per_locum,
    amortize_travel=amortize_travel,
    amortization_shifts=amortization_shifts,
    show_payer_mix=show_payer_mix,
    payer_medicare_pct=payer_vals["payer_medicare_pct"] if show_payer_mix else 0.5,
    payer_commercial_pct=payer_vals["payer_commercial_pct"] if show_payer_mix else 0.35,
    payer_medicaid_pct=payer_vals["payer_medicaid_pct"] if show_payer_mix else 0.15,
    medicare_factor=payer_vals["medicare_factor"] if show_payer_mix else 1.00,
    commercial_factor=payer_vals["commercial_factor"] if show_payer_mix else 1.30,
    medicaid_factor=payer_vals["medicaid_factor"] if show_payer_mix else 0.80,
    show_finance_settings=show_finance_settings,
    overhead_base=overhead_base,
    overhead_pct=overhead_pct,
    show_costs_plus=show_costs_plus,
    add_call_stipend=add_call_stipend,
    add_overtime_premium=add_overtime_premium,
    add_holiday_premium=add_holiday_premium,
    coverage_days_per_year=coverage_days_per_year,
    utilization_pct=utilization_pct
)

# Guardrails
if i.units > i.safe_capacity:
    st.warning(f"Entered volume ({i.units:.1f}) exceeds safe capacity ({i.safe_capacity:.1f}). Results may be unrealistic.")

# Quick sensitivity buttons
st.markdown('<div class="pill-controls">', unsafe_allow_html=True)
csa, csb, csc = st.columns(3)
with csa:
    if st.button("Sensitivity: +10% volume"):
        i.units = round(i.units * 1.10, 2)
with csb:
    if st.button("Sensitivity: +10% locum rate"):
        i.locum_cost_per_shift = round(i.locum_cost_per_shift * 1.10, 0)
with csc:
    if st.button("Sensitivity: +10% commercial factor"):
        i.commercial_factor = round(i.commercial_factor * 1.10, 2)
st.markdown('</div>', unsafe_allow_html=True)

# Scenario A/B tabs
tabA, tabB = st.tabs(["Locum coverage (A)", "No coverage (B)"])

with tabA:
    a = calculate_shift(i, with_locum=True)
    a_ann = calculate_annual(i, a)
    # KPIs
    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    kpi_pill("Net Impact (per shift)", format_money(a["net"]), good=(a["net"] >= 0))
    roi_display = "—" if not math.isfinite(a["roi"]) else f"{a['roi']*100:,.1f}%"
    kpi_pill("ROI % (per shift)", roi_display, good=(math.isfinite(a["roi"]) and a["roi"] >= 0))
    kpi_pill("Total Revenue (per shift)", format_money(a["direct_revenue"] + a["downstream"]), good=None)
    kpi_pill("Total Costs (per shift)", format_money(a["total_costs"]), good=None)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    kpi_pill("Net Impact (annualized adj.)", format_money(a_ann["net"]), good=(a_ann["net"] >= 0))
    kpi_pill("Coverage days × Utilization", f"{i.coverage_days_per_year} × {int(i.utilization_pct*100)}%", good=None)
    kpi_pill("Breakeven locum portion (per shift)", format_money(breakeven_locum_cost(i)), good=None)
    st.markdown('</div>', unsafe_allow_html=True)

with tabB:
    b = calculate_shift(i, with_locum=False)
    b_ann = calculate_annual(i, b)

    diverted = i.units  # all units missed if no coverage
    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    kpi_pill("# Patients/Studies diverted (per shift)", f"{diverted:,.0f}", good=False)
    kpi_pill("Lost Revenue (per shift)", format_money(b["direct_revenue"] + b["downstream"]), good=False)
    kpi_pill("Net Impact (per shift)", format_money(b["net"]), good=False)  # b["net"] is negative costs only (overhead/var are zero here)
    st.markdown('</div>', unsafe_allow_html=True)

# Delta row
delta_net_shift = (a["net"] - b["net"])
delta_ann = (a_ann["net"] - b_ann["net"])
st.markdown('<div class="section"></div>', unsafe_allow_html=True)
st.subheader("Difference: A (Locum) vs B (No coverage)")
st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
kpi_pill("Δ Net Impact (per shift)", format_money(delta_net_shift), good=(delta_net_shift >= 0))
kpi_pill("Δ Net Impact (annualized adj.)", format_money(delta_ann), good=(delta_ann >= 0))
st.markdown('</div>', unsafe_allow_html=True)

# Save / Load (kept simple, behind expander)
with st.expander("Save / Load scenario"):
    colx, coly = st.columns(2)
    with colx:
        if st.button("Download current inputs.json"):
            st.download_button("Click to download", data=json.dumps(asdict(i), indent=2),
                               file_name="inputs.json", mime="application/json")
    with coly:
        uploaded = st.file_uploader("Upload inputs.json", type=["json"])
        if uploaded is not None:
            try:
                data = json.load(uploaded)
                st.success("Inputs loaded. Please re‑select preset if needed.")
                # naive update: user can refresh page to reflect; or we could set session_state
                st.json(data)
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

# Footer small notes
st.markdown('<div class="section"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="small-note">Overhead base: apply on '
    '<b>direct</b> revenue only or on <b>total</b> (direct + downstream). '
    'Payer mix auto‑normalizes if not 100%. Travel can amortize across shifts. '
    'Breakeven locum portion excludes travel and fixed adders.</div>', unsafe_allow_html=True
)
