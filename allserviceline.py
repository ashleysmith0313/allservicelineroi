# streamlit_app.py — All Service Line Calculator (Toggle Version, additive only)
# Author: RadiusOS - SaaS Developer
# Description: Adds an Executive (Simple) view for Interventional Cardiology via a toggle.
#              Keeps ALL existing service lines and Analyst logic intact.
# Launch: `streamlit run streamlit_app.py`
# Optional config file: `config/service_lines.yaml`

import os
import io
import json
import math
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Any, List

import pandas as pd
import streamlit as st

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

# ---------------------------------------------
# Utility & Config
# ---------------------------------------------
CONFIG_PATH = os.path.join("config", "service_lines.yaml")

# Minimal defaults used ONLY to backfill missing keys (user config always wins)
DEFAULT_CONFIG = {
    "service_lines": {
        "Interventional Cardiology": {
            "simple": {
                "capture_map": {"None": 0.25, "Business Hours Only": 0.55, "24/7/365": 0.85},
                "diagnostic_per_cp": 0.35,
                "pci_per_cp": 0.12,
                "rev_diag": 8500.0, "cost_diag": 4000.0,
                "rev_pci": 22000.0, "cost_pci": 11000.0,
                "providers_needed_247": 4,
                "locum_util_factor": 0.15,
            },
            # Analyst defaults are only used if your YAML lacks these keys
            "advanced": {
                "units_per_day": 8.0,
                "days_per_period": 365,
                "revenue_per_unit": 9000.0,
                "variable_cost_per_unit": 4500.0,
                "fixed_costs_per_period": 0.0,
                "occupancy_pct": 80.0,
                "use_locums": True,
                "locum_util_pct": 10.0,
                "referrals": {
                    "Cardiac Rehab": {"referrals_per_unit": 0.20, "revenue_per_referral": 1800.0},
                    "Echo": {"referrals_per_unit": 0.35, "revenue_per_referral": 350.0},
                    "Clinic Follow-up": {"referrals_per_unit": 0.40, "revenue_per_referral": 220.0},
                },
            },
        },
    }
}


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict[str, Any]:
    if yaml is None:
        return DEFAULT_CONFIG
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            # User config overlays defaults (user wins)
            return _deep_merge(DEFAULT_CONFIG, user_cfg)
    except Exception:
        pass
    return DEFAULT_CONFIG


# ---------------------------------------------
# Math Helpers
# ---------------------------------------------

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def pct_to_01(p: float) -> float:
    return clamp01((p or 0.0) / 100.0)


def format_money(x: float) -> str:
    try:
        return f"${x:,.0f}"
    except Exception:
        return f"${x}"


# ---------------------------------------------
# Executive (Simple) — Interventional Cardiology
# ---------------------------------------------
@dataclass
class ICSimpleInputs:
    ed_visits: int = 25000
    chest_pain_pct: float = 8.0  # percent of ED
    coverage_level: str = "Business Hours Only"  # None | Business Hours Only | 24/7/365
    providers_on_staff: int = 1
    locums_hourly_rate: float = 425.0
    payer_mix_sensitivity_pct: float = 0.0  # ±% applied to revenue only


@dataclass
class ICSimpleConfig:
    capture_map: Dict[str, float] = field(default_factory=lambda: {
        "None": 0.25,
        "Business Hours Only": 0.55,
        "24/7/365": 0.85,
    })
    diagnostic_per_cp: float = 0.35
    pci_per_cp: float = 0.12
    rev_diag: float = 8500.0
    cost_diag: float = 4000.0
    rev_pci: float = 22000.0
    cost_pci: float = 11000.0
    providers_needed_247: int = 4
    locum_util_factor: float = 0.15  # fraction of 8760 hours considered in calc


@dataclass
class ICSimpleResult:
    chest_pain_patients: float
    capture_rate: float
    diag_cases: float
    pci_cases: float
    gross_revenue: float
    direct_cost: float
    net_margin: float
    providers_needed_247: int
    provider_gap: int
    locums_spend_for_gap: float


def ic_simple_calculate(inp: ICSimpleInputs, cfg: ICSimpleConfig) -> ICSimpleResult:
    cp_patients = inp.ed_visits * (inp.chest_pain_pct / 100.0)
    capture = cfg.capture_map.get(inp.coverage_level, 0.55)

    diag = cp_patients * cfg.diagnostic_per_cp * capture
    pci = cp_patients * cfg.pci_per_cp * capture

    # Apply payer-mix sensitivity to revenue (not costs)
    rev_multiplier = 1.0 + (inp.payer_mix_sensitivity_pct / 100.0)

    gross = (diag * cfg.rev_diag + pci * cfg.rev_pci) * rev_multiplier
    cost = diag * cfg.cost_diag + pci * cfg.cost_pci
    margin = gross - cost

    needed = int(cfg.providers_needed_247)
    gap = max(0, needed - int(inp.providers_on_staff))

    # Very rough locums spend estimate for gap coverage:
    annual_hours = 8760  # 24*365
    locums_spend = gap * annual_hours * cfg.locum_util_factor * float(inp.locums_hourly_rate)

    return ICSimpleResult(
        chest_pain_patients=cp_patients,
        capture_rate=capture,
        diag_cases=diag,
        pci_cases=pci,
        gross_revenue=gross,
        direct_cost=cost,
        net_margin=margin,
        providers_needed_247=needed,
        provider_gap=gap,
        locums_spend_for_gap=locums_spend,
    )


# ---------------------------------------------
# Analyst (Advanced) — Generic Unit + Referral Engine
# ---------------------------------------------
@dataclass
class AdvancedInputs:
    units_per_day: float
    days_per_period: int
    revenue_per_unit: float
    variable_cost_per_unit: float
    fixed_costs_per_period: float
    occupancy_pct: float
    use_locums: bool
    locum_util_pct: float
    referrals: Dict[str, Dict[str, float]]  # {name: {referrals_per_unit, revenue_per_referral}}
    payer_mix_sensitivity_pct: float = 0.0


@dataclass
class AdvancedResult:
    staffed_pct: float
    units_period: float
    gross_revenue_units: float
    variable_cost_units: float
    referral_revenue: float
    missed_revenue_units: float
    missed_referral_revenue: float
    net_margin: float


def compute_referral_revenue(units_period: float, referrals: Dict[str, Dict[str, float]], rev_multiplier: float) -> float:
    total = 0.0
    for name, d in (referrals or {}).items():
        rpu = float(d.get("referrals_per_unit", 0.0))
        rpr = float(d.get("revenue_per_referral", 0.0))
        total += units_period * rpu * rpr * rev_multiplier
    return total


def advanced_calculate(inp: AdvancedInputs) -> AdvancedResult:
    # Effective staffed pct = occupancy + locum_util (if on), clamped to 0-100 **before** any downstream calc
    staffed_pct = max(0.0, min(100.0, inp.occupancy_pct + (inp.locum_util_pct if inp.use_locums else 0.0)))

    units_period_full = float(inp.units_per_day) * float(inp.days_per_period)
    units_period = units_period_full * (staffed_pct / 100.0)

    rev_multiplier = 1.0 + (inp.payer_mix_sensitivity_pct / 100.0)

    gross_units = units_period * float(inp.revenue_per_unit) * rev_multiplier
    var_cost_units = units_period * float(inp.variable_cost_per_unit)

    # Referral revenue at achieved volume (weighted mix)
    referral_rev = compute_referral_revenue(units_period, inp.referrals, rev_multiplier)

    # Missed opportunity computed with the same mix (symmetry with achieved)
    missed_units = units_period_full - units_period
    missed_rev_units = missed_units * float(inp.revenue_per_unit) * rev_multiplier
    missed_referral_rev = compute_referral_revenue(missed_units, inp.referrals, rev_multiplier)

    net = (gross_units + referral_rev) - (var_cost_units + float(inp.fixed_costs_per_period))

    return AdvancedResult(
        staffed_pct=staffed_pct,
        units_period=units_period,
        gross_revenue_units=gross_units,
        variable_cost_units=var_cost_units,
        referral_revenue=referral_rev,
        missed_revenue_units=missed_rev_units,
        missed_referral_revenue=missed_referral_rev,
        net_margin=net,
    )


# ---------------------------------------------
# Streamlit UI
# ---------------------------------------------
st.set_page_config(page_title="All Service Line Calculator", layout="wide")

st.title("All Service Line Calculator")
st.caption("Executive-simple vs Analyst-advanced with a toggle. Defaults are illustrative; adjust or provide a YAML config.")

cfg = load_config()

# Normalize service lines without removing user entries
_raw_services = cfg.get("service_lines", {})
if isinstance(_raw_services, list):
    tmp = {}
    for item in _raw_services:
        if isinstance(item, str):
            tmp[item] = {}
        elif isinstance(item, dict):
            tmp.update(item)
    _raw_services = tmp
elif not isinstance(_raw_services, dict):
    _raw_services = {}

services = sorted(list(_raw_services.keys()))
if not services:
    st.error("No service lines found in configuration. Ensure `service_lines` is a mapping and not a list.")
    st.stop()

# Service line picker & mode toggle (toggle only enabled for Interventional Cardiology)
col_hdr1, col_hdr2 = st.columns([2, 1])
with col_hdr1:
    default_index = services.index("Interventional Cardiology") if "Interventional Cardiology" in services else 0
    service_line = st.selectbox("Service Line", services, index=default_index)
with col_hdr2:
    is_ic = (service_line == "Interventional Cardiology")
    simple_default = True if is_ic else False
    try:
        simple_mode = st.toggle("Executive (Simple) Mode", value=simple_default, disabled=not is_ic)
    except Exception:
        simple_mode = st.checkbox("Executive (Simple) Mode", value=simple_default, disabled=not is_ic)

# Global sensitivity (applies to both modes) — ±% revenue impact for payer mix / reimbursement
sensitivity = st.slider("Payer-Mix / Reimbursement Sensitivity (±% applied to revenue)", -20, 20, 0, help="Applies multiplicatively to revenue in both modes.")

st.divider()

session_rows: List[Dict[str, Any]] = st.session_state.get("_session_rows", [])

# -----------------------
# Executive (Simple) UI — Interventional Cardiology only
# -----------------------
if simple_mode and is_ic:
    st.subheader("Interventional Cardiology — Executive View")

    scfg = _raw_services.get("Interventional Cardiology", {}).get("simple", {})
    ic_conf = ICSimpleConfig(
        capture_map=scfg.get("capture_map", ICSimpleConfig().capture_map),
        diagnostic_per_cp=float(scfg.get("diagnostic_per_cp", 0.35)),
        pci_per_cp=float(scfg.get("pci_per_cp", 0.12)),
        rev_diag=float(scfg.get("rev_diag", 8500.0)),
        cost_diag=float(scfg.get("cost_diag", 4000.0)),
        rev_pci=float(scfg.get("rev_pci", 22000.0)),
        cost_pci=float(scfg.get("cost_pci", 11000.0)),
        providers_needed_247=int(scfg.get("providers_needed_247", 4)),
        locum_util_factor=float(scfg.get("locum_util_factor", 0.15)),
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        ed_visits = st.number_input("Annual ED Visits", min_value=0, value=25000, step=500)
        coverage = st.selectbox("Current Interventional Coverage", list(ic_conf.capture_map.keys()), index=1)
    with c2:
        chest_pain_pct = st.slider("Chest Pain / Cardiac Flag % of ED", 0, 100, 8)
        providers = st.number_input("Interventional Cardiologists on Staff", min_value=0, value=1)
    with c3:
        loc_rate = st.number_input("Locums Hourly Rate ($)", min_value=0.0, value=425.0, step=25.0)
        st.text("")

    inputs = ICSimpleInputs(
        ed_visits=ed_visits,
        chest_pain_pct=float(chest_pain_pct),
        coverage_level=str(coverage),
        providers_on_staff=int(providers),
        locums_hourly_rate=float(loc_rate),
        payer_mix_sensitivity_pct=float(sensitivity),
    )

    res = ic_simple_calculate(inputs, ic_conf)

    m1, m2, m3 = st.columns(3)
    m1.metric("Est. Annual Caths (Diagnostic)", f"{res.diag_cases:,.0f}")
    m2.metric("Est. Annual PCIs", f"{res.pci_cases:,.0f}")
    m3.metric("Net Margin (Cases Only)", format_money(res.net_margin))

    m4, m5, m6 = st.columns(3)
    m4.metric("Gross Revenue", format_money(res.gross_revenue))
    m5.metric("Direct Cost", format_money(res.direct_cost))
    m6.metric("Capture Rate", f"{res.capture_rate:.0%}")

    st.markdown("---")
    cgap1, cgap2, cgap3 = st.columns(3)
    cgap1.metric("Providers Needed (24/7)", f"{res.providers_needed_247}")
    cgap2.metric("Provider Gap", f"{res.provider_gap}")
    cgap3.metric("Rough Locums Spend for Gap", format_money(res.locums_spend_for_gap))

    # Log to session table
    session_rows.append({
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "Executive",
        "service_line": service_line,
        "ED_visits": inputs.ed_visits,
        "chest_pain_pct": inputs.chest_pain_pct,
        "coverage": inputs.coverage_level,
        "providers_on_staff": inputs.providers_on_staff,
        "locums_rate": inputs.locums_hourly_rate,
        "est_diag_cases": round(res.diag_cases, 0),
        "est_pci_cases": round(res.pci_cases, 0),
        "gross_revenue": round(res.gross_revenue, 0),
        "direct_cost": round(res.direct_cost, 0),
        "net_margin": round(res.net_margin, 0),
    })

# -----------------------
# Analyst (Advanced) UI — ALL service lines (unchanged behavior)
# -----------------------
else:
    st.subheader(f"{service_line} — Analyst View")

    adv_defaults = _raw_services.get(service_line, {}).get("advanced", {})

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        units_per_day = st.number_input("Units per Day", min_value=0.0, value=float(adv_defaults.get("units_per_day", 8.0)), step=0.5)
        revenue_per_unit = st.number_input("Revenue per Unit ($)", min_value=0.0, value=float(adv_defaults.get("revenue_per_unit", 9000.0)), step=100.0)
    with a2:
        days_per_period = st.number_input("Days per Period", min_value=1, value=int(adv_defaults.get("days_per_period", 365)))
        variable_cost_per_unit = st.number_input("Variable Cost per Unit ($)", min_value=0.0, value=float(adv_defaults.get("variable_cost_per_unit", 4500.0)), step=100.0)
    with a3:
        occupancy_pct = st.slider("Staffed % (Employed)", 0, 100, int(adv_defaults.get("occupancy_pct", 80)))
        use_locums = st.checkbox("Use Locums to Cover Gap", value=bool(adv_defaults.get("use_locums", True)))
    with a4:
        fixed_costs = st.number_input("Fixed Costs per Period ($)", min_value=0.0, value=float(adv_defaults.get("fixed_costs_per_period", 0.0)), step=1000.0)
        locum_util_pct = st.slider("Locums Utilization %", 0, 100, int(adv_defaults.get("locum_util_pct", 10)))

    st.markdown("**Referral Mix (per Unit)** — add rows or edit values:")
    ref_defaults = adv_defaults.get("referrals", {})

    # Editable referral table
    ref_df = pd.DataFrame([
        {"Referral": k, "Referrals per Unit": v.get("referrals_per_unit", 0.0), "Revenue per Referral": v.get("revenue_per_referral", 0.0)}
        for k, v in ref_defaults.items()
    ])
    if ref_df.empty:
        ref_df = pd.DataFrame([{"Referral": "Example", "Referrals per Unit": 0.10, "Revenue per Referral": 250.0}])

    edited = st.data_editor(ref_df, num_rows="dynamic", use_container_width=True, key="ref_table")

    # Build dict back from editor
    referrals: Dict[str, Dict[str, float]] = {}
    for _, row in edited.iterrows():
        name = str(row.get("Referral", "")).strip()
        if not name:
            continue
        referrals[name] = {
            "referrals_per_unit": float(row.get("Referrals per Unit", 0.0)),
            "revenue_per_referral": float(row.get("Revenue per Referral", 0.0)),
        }

    adv_inputs = AdvancedInputs(
        units_per_day=float(units_per_day),
        days_per_period=int(days_per_period),
        revenue_per_unit=float(revenue_per_unit),
        variable_cost_per_unit=float(variable_cost_per_unit),
        fixed_costs_per_period=float(fixed_costs),
        occupancy_pct=float(occupancy_pct),
        use_locums=bool(use_locums),
        locum_util_pct=float(locum_util_pct),
        referrals=referrals,
        payer_mix_sensitivity_pct=float(sensitivity),
    )

    adv_res = advanced_calculate(adv_inputs)

    ctop1, ctop2, ctop3 = st.columns(3)
    ctop1.metric("Effective Staffed %", f"{adv_res.staffed_pct:.0f}%")
    ctop2.metric("Units this Period", f"{adv_res.units_period:,.0f}")
    ctop3.metric("Net Margin", format_money(adv_res.net_margin))

    cmid1, cmid2, cmid3 = st.columns(3)
    cmid1.metric("Gross Revenue (Units)", format_money(adv_res.gross_revenue_units))
    cmid2.metric("Referral Revenue", format_money(adv_res.referral_revenue))
    cmid3.metric("Variable Cost (Units)", format_money(adv_res.variable_cost_units))

    st.markdown("---")
    cbtm1, cbtm2 = st.columns(2)
    cbtm1.metric("Missed Revenue (Units)", format_money(adv_res.missed_revenue_units))
    cbtm2.metric("Missed Referral Revenue", format_money(adv_res.missed_referral_revenue))

    # Log to session table
    session_rows.append({
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "Analyst",
        "service_line": service_line,
        "units_per_day": adv_inputs.units_per_day,
        "days_per_period": adv_inputs.days_per_period,
        "revenue_per_unit": adv_inputs.revenue_per_unit,
        "variable_cost_per_unit": adv_inputs.variable_cost_per_unit,
        "fixed_costs": adv_inputs.fixed_costs_per_period,
        "occupancy_pct": adv_inputs.occupancy_pct,
        "use_locums": adv_inputs.use_locums,
        "locum_util_pct": adv_inputs.locum_util_pct,
        "referrals_rows": len(referrals),
        "net_margin": round(adv_res.net_margin, 0),
    })

# Persist session rows
st.session_state["_session_rows"] = session_rows

st.markdown("---")
st.subheader("Scenario Runs")
if session_rows:
    sess_df = pd.DataFrame(session_rows)
    st.dataframe(sess_df, use_container_width=True)

    csv_bytes = sess_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Scenarios (CSV)", data=csv_bytes, file_name="scenarios.csv", mime="text/csv")

# ---------------------------------------------
# Glossary & Notes
# ---------------------------------------------
with st.expander("Glossary & Assumptions"):
    st.markdown(
        """
        **ED visits**: Annual emergency department encounters at your facility.  
        **Chest Pain %**: Share of ED visits with chest-pain/cardiac flags.  
        **Coverage level**: Availability of interventional cardiology (none, business-hours, 24/7). Drives capture rate.  
        **Capture rate**: Portion of cardiac patients kept in-house rather than transferred/outmigrated.  
        **Diagnostic cath / PCI**: Illustrative conversion ratios from chest-pain population to procedures.  
        **Units** (Advanced): Your primary throughput notion (cases, shifts, studies, encounters).  
        **Referral mix**: Downstream services that occur per unit (e.g., echo, clinic), with revenue per referral.  
        **Missed revenue**: Same revenue logic applied to the unstaffed share (symmetry with achieved).  
        **Sensitivity**: ±% on revenue to quickly simulate payer mix / rate changes.  
        \- All defaults are placeholders. Load real medians via `config/service_lines.yaml`.
        """
    )

st.markdown(
    "_Disclaimer: This tool provides directional estimates only and is not a substitute for a full pro forma. Defaults are illustrative and should be validated against your organization’s data sources._"
)
