# -----------------------------------------------
# Export (Executive + Analyst) — PDF-only charts
# -----------------------------------------------
st.subheader("📄 Export")

# Always build a safe base filename without braces to avoid f-string issues
safe_base = service_name.replace(" ", "_").replace("/", "_").lower()

# Executive IC report (if in Executive mode and metrics exist)
case_mix_png = econ_png = None
if exec_metrics is not None:
    # build charts ONLY for export (no UI rendering)
    fig1, ax1 = plt.subplots()
    ax1.pie([exec_metrics["diag_cases"], exec_metrics["pci_cases"]],
            labels=["Diagnostics", "PCIs"], autopct="%1.0f%%")
    ax1.set_title("Case Mix")
    case_mix_png = _save_fig_as_png_bytes(fig1)

    fig2, ax2 = plt.subplots()
    pos_margin = max(0.0, exec_metrics["margin"])
    ax2.pie([exec_metrics["cost"], pos_margin],
            labels=["Direct Cost", "Net Margin"], autopct="%1.0f%%")
    ax2.set_title("Economics Composition")
    econ_png = _save_fig_as_png_bytes(fig2)

    if st.button("Download Executive Report (PDF)"):
        pdf_bytes = build_pdf_bytes(
            exec_block=exec_metrics,
            case_mix_png=case_mix_png,
            econ_png=econ_png,
            analyst_block=None
        )
        if pdf_bytes:
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name=safe_base + "_executive_report.pdf",
                mime="application/pdf",
            )

# Analyst report (always available) — build pies for export only
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
    # Build pies for PDF only (no UI pyplot)
    fig_rev, ax_rev = plt.subplots()
    rev_unit = max(0.0, analyst_block["gross_rev"])
    rev_ref = max(0.0, analyst_block["referral_rev"])
    if (rev_unit + rev_ref) > 0:
        ax_rev.pie([rev_unit, rev_ref], labels=["Unit Revenue", "Referral Revenue"], autopct="%1.0f%%")
    else:
        ax_rev.pie([1], labels=["No Revenue"], autopct="%1.0f%%")
    ax_rev.set_title("Revenue Composition")
    analyst_revenue_png = _save_fig_as_png_bytes(fig_rev)

    fig_cost, ax_cost = plt.subplots()
    cost_oper = max(0.0, analyst_block["operating_cost"])
    cost_loc = max(0.0, analyst_block["locum_total"])
    if (cost_oper + cost_loc) > 0:
        ax_cost.pie([cost_oper, cost_loc], labels=["Operating Cost", "Locum Cost"], autopct="%1.0f%%")
    else:
        ax_cost.pie([1], labels=["No Cost"], autopct="%1.0f%%")
    ax_cost.set_title("Cost Composition")
    analyst_cost_png = _save_fig_as_png_bytes(fig_cost)

    pdf_bytes = build_pdf_bytes(
        analyst_block=analyst_block,
        analyst_revenue_png=analyst_revenue_png,
        analyst_cost_png=analyst_cost_png
    )
    if pdf_bytes:
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=safe_base + "_analyst_report.pdf",
            mime="application/pdf",
        )
