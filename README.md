# Lensight — Fundamental Analysis Platform

> AI-powered fundamental analysis for Indian equities.

## Pipeline
```
uploads/*.xlsx
  └─► excel_parser    → data/raw/          (pnl, balance_sheet, cash_flow, quarters, meta)
        └─► preprocessor  → data/processed/   (cleaned, typed, normalized)
              └─► ratio_engine   → financial ratios
              └─► trend_engine   → YoY, CAGR, trend direction
                    └─► llm/orchestrator → narrative generation
                          └─► dashboard   → Plotly/Dash UI
```

## Quickstart
```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```
