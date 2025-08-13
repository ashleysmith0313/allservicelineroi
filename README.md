# All Service-Line ROI Calculator (v0.9.3)

Locum vs No Coverage ROI with CFO-friendly UI. Scenario A/B tabs, payer mix auto-normalize, presets, 
breakeven mini-chart, sensitivity buttons, and realistic annualization (coverage days + utilization).

## Quickstart
```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows
# or
source .venv/bin/activate # macOS/Linux

pip install -r requirements.txt
streamlit run streamlit_app/app.py
```
App opens at http://localhost:8501

## Configs
Edit defaults in `configs/service_lines/*.json`. App is config-driven; math lives in the UI file for now.
