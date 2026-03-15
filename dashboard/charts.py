"""
dashboard/charts.py  — v3
Fixed: legend overlap, square-ish aspect ratio, Georgia serif font, no italic
"""

import logging
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)

# ── Design tokens ────────────────────────────────────────────────────────────
_FONT   = "Georgia, 'Times New Roman', serif"
_BG     = "rgba(0,0,0,0)"
_GRID   = "rgba(0,0,0,0.07)"
_TEXT   = "#0f172a"
_MUTED  = "#475569"
_H      = 360          # chart height — more square, less stretched

_TREND_COLORS = {
    "strong_uptrend": "#059669",
    "improving":      "#10b981",
    "stable":         "#6366f1",
    "volatile":       "#f59e0b",
    "declining":      "#f97316",
    "strong_decline": "#ef4444",
}
_LABEL_COLORS = {
    "excellent":      "#059669",
    "strong":         "#10b981",
    "good":           "#34d399",
    "average":        "#6366f1",
    "adequate":       "#6366f1",
    "moderate":       "#f59e0b",
    "weak":           "#f97316",
    "poor":           "#ef4444",
    "negative":       "#dc2626",
    "fair":           "#6366f1",
    "undervalued":    "#059669",
    "cheap":          "#059669",
    "low":            "#059669",
    "safe":           "#10b981",
    "expensive":      "#f97316",
    "very_expensive": "#ef4444",
    "risky":          "#f97316",
    "very_risky":     "#ef4444",
    "very_high":      "#ef4444",
    "high":           "#f97316",
}
_PALETTE = ["#6366f1","#059669","#f59e0b","#3b82f6","#ec4899","#14b8a6"]
_TREND_ICONS = {
    "strong_uptrend": "↑↑",
    "improving":      "↑",
    "stable":         "→",
    "volatile":       "↕",
    "declining":      "↓",
    "strong_decline": "↓↓",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _year_labels(periods):
    """
    FY labels for chart x-axis.
    2025-03-31 → FY2025
    2025-12-31 → TTM Q3FY26
    2025-06-30 → TTM Q1FY26
    2025-09-30 → TTM Q2FY26
    """
    _qmap = {"06": "Q1", "09": "Q2", "12": "Q3"}
    out = []
    for p in periods:
        try:
            month = p[5:7]
            year  = p[:4]
            if month == "03":
                out.append(f"FY{year}")
            else:
                q  = _qmap.get(month, "Q?")
                fy = str(int(year) + 1)
                out.append(f"TTM {q}FY{fy}")
        except Exception:
            out.append(p)
    return out

def _hex_to_rgba(hex_color, alpha=1.0):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

def _ti(trend):
    return _TREND_ICONS.get(trend, "→")

def _base(title, height=None):
    """
    Shared layout:
    - Georgia serif font throughout
    - Legend BELOW the chart (not overlapping title)
    - Title top-left, no bold tag (cleaner)
    - Square-ish height
    """
    h = height or _H
    return dict(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=14, color=_TEXT, family=_FONT),
            x=0.5,
            xanchor="center",
            pad=dict(b=4),
        ),
        height=h,
        # Top margin large enough for title; bottom large enough for legend
        margin=dict(l=54, r=20, t=52, b=72),
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(family=_FONT, size=12, color=_MUTED),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,          # below chart, not above
            xanchor="left",
            x=0,
            font=dict(size=11, color=_TEXT, family=_FONT),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
        ),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=11, color=_TEXT, family=_FONT),
            linecolor=_GRID,
            tickangle=0,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=_GRID,
            tickfont=dict(size=11, color=_TEXT, family=_FONT),
            zeroline=False,
        ),
        hovermode="x unified",
        hoverlabel=dict(font=dict(size=12, family=_FONT)),
    )

# ── Charts ────────────────────────────────────────────────────────────────────

def profitability_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    prof    = data.get("profitability", {})
    series  = [("roe","ROE %"),("roce","ROCE %"),("roa","ROA %")]

    fig = go.Figure()
    for i, (key, name) in enumerate(series):
        rd = prof.get(key, {})
        y  = [rd.get("values", {}).get(p) for p in periods]
        tr = _ti(rd.get("trend","stable"))
        fig.add_trace(go.Scatter(
            x=x, y=y, name=f"{name} {tr}",
            mode="lines+markers",
            line=dict(color=_PALETTE[i], width=2.5),
            marker=dict(size=6), connectgaps=True,
            hovertemplate=f"<b>{name}</b>: %{{y:.1f}}%<extra></extra>",
        ))
    layout = _base("Profitability Analysis")
    layout["yaxis"]["ticksuffix"] = "%"
    fig.update_layout(**layout)
    return fig


def margins_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    prof    = data.get("profitability", {})
    series  = [
        ("net_profit_margin","Net Margin"),
        ("op_profit_margin","Op Margin"),
        ("ebitda_margin","EBITDA Margin"),
    ]
    fig = go.Figure()
    for i, (key, name) in enumerate(series):
        rd = prof.get(key, {})
        y  = [rd.get("values", {}).get(p) for p in periods]
        tr = _ti(rd.get("trend","stable"))
        fig.add_trace(go.Scatter(
            x=x, y=y, name=f"{name} {tr}",
            mode="lines+markers",
            line=dict(color=_PALETTE[i], width=2.5),
            marker=dict(size=6), connectgaps=True,
            hovertemplate=f"<b>{name}</b>: %{{y:.1f}}%<extra></extra>",
        ))
    layout = _base("Margins Analysis")
    layout["yaxis"]["ticksuffix"] = "%"
    fig.update_layout(**layout)
    return fig


def valuation_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    val     = data.get("valuation", {})
    pe      = val.get("pe_ratio", {})
    pb      = val.get("pb_ratio", {})

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=x, y=[pe.get("values",{}).get(p) for p in periods],
        name=f"P/E {_ti(pe.get('trend','stable'))}",
        mode="lines+markers",
        line=dict(color=_PALETTE[0], width=2.5),
        marker=dict(size=6), connectgaps=True,
        hovertemplate="<b>P/E</b>: %{y:.1f}x<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=x, y=[pb.get("values",{}).get(p) for p in periods],
        name=f"P/B {_ti(pb.get('trend','stable'))}",
        mode="lines+markers",
        line=dict(color=_PALETTE[1], width=2.5, dash="dash"),
        marker=dict(size=6), connectgaps=True,
        hovertemplate="<b>P/B</b>: %{y:.1f}x<extra></extra>",
    ), secondary_y=True)

    layout = _base("Market Valuation")
    fig.update_layout(**layout)
    fig.update_yaxes(
        title_text="P/E (x)", showgrid=True, gridcolor=_GRID,
        tickfont=dict(size=11, family=_FONT, color=_TEXT), secondary_y=False,
    )
    fig.update_yaxes(
        title_text="P/B (x)", showgrid=False,
        tickfont=dict(size=11, family=_FONT, color=_TEXT), secondary_y=True,
    )
    return fig


def eps_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    ps      = data.get("per_share", {})
    eps     = ps.get("eps", {})
    dps     = ps.get("dividend_per_share", {})

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=[eps.get("values",{}).get(p) for p in periods],
        name=f"EPS (Rs.) {_ti(eps.get('trend','stable'))}",
        marker_color=_PALETTE[0], opacity=0.85,
        hovertemplate="<b>EPS</b>: Rs.%{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=x, y=[dps.get("values",{}).get(p) for p in periods],
        name=f"DPS (Rs.) {_ti(dps.get('trend','stable'))}",
        marker_color=_PALETTE[1], opacity=0.85,
        hovertemplate="<b>DPS</b>: Rs.%{y:.2f}<extra></extra>",
    ))
    layout = _base("EPS & Dividend per Share")
    layout["barmode"] = "group"
    fig.update_layout(**layout)
    return fig


def growth_chart(data):
    growth = data.get("growth", {})
    windows, sales, profit = [], [], []
    for w in ["3y","5y","7y","10y"]:
        sk = f"sales_cagr_{w}"
        pk = f"net_profit_cagr_{w}"
        if sk in growth:
            windows.append(w.upper())
            sales.append(growth[sk].get("value"))
            profit.append(growth.get(pk, {}).get("value"))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=windows, x=sales, name="Sales CAGR",
        orientation="h", marker_color=_PALETTE[0], opacity=0.85,
        hovertemplate="<b>Sales CAGR</b>: %{x:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=windows, x=profit, name="Profit CAGR",
        orientation="h", marker_color=_PALETTE[1], opacity=0.85,
        hovertemplate="<b>Profit CAGR</b>: %{x:.1f}%<extra></extra>",
    ))
    layout = _base("Growth Analysis (CAGR)", height=340)
    layout["barmode"]              = "group"
    layout["bargap"]               = 0.35
    layout["bargroupgap"]          = 0.08
    layout["xaxis"]["ticksuffix"]  = "%"
    layout["xaxis"]["showgrid"]    = True
    layout["xaxis"]["gridcolor"]   = _GRID
    layout["yaxis"]["showgrid"]    = False
    layout["yaxis"]["autorange"]   = "reversed"   # 3Y top, 7Y bottom — natural read order
    layout["margin"]               = dict(l=60, r=20, t=52, b=90)
    fig.update_layout(**layout)
    return fig


def efficiency_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    eff     = data.get("efficiency", {})
    series  = [
        ("inventory_turnover_days","Inventory Days"),
        ("receivables_days","Receivables Days"),
    ]
    fig = go.Figure()
    for i, (key, name) in enumerate(series):
        rd = eff.get(key, {})
        y  = [rd.get("values",{}).get(p) for p in periods]
        tr = _ti(rd.get("trend","stable"))
        fig.add_trace(go.Scatter(
            x=x, y=y, name=f"{name} {tr}",
            mode="lines+markers",
            line=dict(color=_PALETTE[i], width=2.5),
            marker=dict(size=6), connectgaps=True,
            hovertemplate=f"<b>{name}</b>: %{{y:.0f}}d<extra></extra>",
        ))
    layout = _base("Efficiency Analysis (lower = better)")
    layout["yaxis"]["ticksuffix"] = "d"
    fig.update_layout(**layout)
    return fig


def leverage_chart(data):
    periods = data.get("periods", [])
    x       = _year_labels(periods)
    lev     = data.get("leverage", {})
    de      = lev.get("debt_to_equity", {})
    ic      = lev.get("interest_coverage", {})

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=x, y=[de.get("values",{}).get(p) for p in periods],
        name=f"Debt/Equity {_ti(de.get('trend','stable'))}",
        mode="lines+markers",
        line=dict(color=_PALETTE[3], width=2.5),
        marker=dict(size=6), connectgaps=True,
        hovertemplate="<b>D/E</b>: %{y:.2f}x<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=x, y=[ic.get("values",{}).get(p) for p in periods],
        name=f"Int. Coverage {_ti(ic.get('trend','stable'))}",
        mode="lines+markers",
        line=dict(color=_PALETTE[2], width=2.5, dash="dash"),
        marker=dict(size=6), connectgaps=True,
        hovertemplate="<b>Coverage</b>: %{y:.0f}x<extra></extra>",
    ), secondary_y=True)

    layout = _base("Leverage & Coverage")
    fig.update_layout(**layout)
    fig.update_yaxes(
        title_text="Debt/Equity", showgrid=True, gridcolor=_GRID,
        tickfont=dict(size=11, family=_FONT, color=_TEXT), secondary_y=False,
    )
    fig.update_yaxes(
        title_text="Coverage (x)", showgrid=False,
        tickfont=dict(size=11, family=_FONT, color=_TEXT), secondary_y=True,
    )
    return fig


def score_radar_chart(data):
    scores = data.get("summary_scores", {})
    cats   = [
        ("profitability_score","Profitability"),
        ("valuation_score","Valuation"),
        ("leverage_score","Leverage"),
        ("liquidity_score","Liquidity"),
        ("efficiency_score","Efficiency"),
        ("growth_score","Growth"),
        ("per_share_score","Per Share"),
    ]
    labels = [l for _,l in cats] + [cats[0][1]]
    values = [scores.get(k,0) for k,_ in cats] + [scores.get(cats[0][0],0)]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values, theta=labels, fill="toself",
        fillcolor=_hex_to_rgba(_PALETTE[0], 0.15),
        line=dict(color=_PALETTE[0], width=2.5),
        marker=dict(size=7, color=_PALETTE[0]),
        name="Score",
        hovertemplate="<b>%{theta}</b>: %{r:.1f}/5<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0,5],
                tickvals=[1,2,3,4,5],
                tickfont=dict(size=10, family=_FONT, color=_TEXT),
                gridcolor=_GRID, linecolor=_GRID,
            ),
            angularaxis=dict(
                tickfont=dict(size=12, color=_TEXT, family=_FONT),
                linecolor=_GRID,
            ),
            bgcolor=_BG,
        ),
        showlegend=False,
        paper_bgcolor=_BG,
        height=_H,
        margin=dict(l=48, r=48, t=52, b=32),
        font=dict(family=_FONT),
        title=dict(
            text="<b>Overall Score Radar</b>",
            font=dict(size=14, color=_TEXT, family=_FONT),
            x=0.5,
            xanchor="center",
        ),
    )
    return fig


def trend_badge_table(data):
    categories = ["profitability","valuation","leverage","liquidity","efficiency","per_share"]
    display_names = {
        "net_profit_margin":"Net Profit Margin","op_profit_margin":"Op Profit Margin",
        "ebitda_margin":"EBITDA Margin","roe":"ROE","roce":"ROCE","roa":"ROA",
        "pe_ratio":"P/E Ratio","pb_ratio":"P/B Ratio","ev_ebitda":"EV/EBITDA",
        "mktcap_to_sales":"Mktcap/Sales","debt_to_equity":"Debt/Equity",
        "interest_coverage":"Interest Coverage","debt_to_assets":"Debt/Assets",
        "cash_ratio":"Cash Ratio","asset_turnover":"Asset Turnover",
        "inventory_turnover_days":"Inventory Days","receivables_days":"Receivables Days",
        "eps":"EPS","book_value_per_share":"Book Value/Share","dividend_per_share":"Dividend/Share",
    }

    rows = []
    for cat in categories:
        for ratio, rd in data.get(cat, {}).items():
            trend  = rd.get("trend","stable")
            score  = rd.get("trend_score",3)
            latest = rd.get("latest_value")
            label  = rd.get("latest_label","—") or "—"
            rows.append({
                "name":   display_names.get(ratio, ratio),
                "latest": f"{latest:.2f}" if latest is not None else "—",
                "label":  label.replace("_"," ").title(),
                "trend":  trend.replace("_"," ").title(),
                "score":  f"{score}/5",
                "_trend": trend,
                "_label": label,
            })

    trend_bg   = [_hex_to_rgba(_TREND_COLORS.get(r["_trend"],"#6366f1"),0.12) for r in rows]
    label_bg   = [_hex_to_rgba(_LABEL_COLORS.get(r["_label"],"#64748b"),0.12) for r in rows]
    trend_font = [_TREND_COLORS.get(r["_trend"],"#64748b") for r in rows]
    label_font = [_LABEL_COLORS.get(r["_label"],"#64748b") for r in rows]
    white      = ["#ffffff"]*len(rows)
    dark       = [_TEXT]*len(rows)

    fig = go.Figure(data=[go.Table(
        columnwidth=[200,90,140,160,70],
        header=dict(
            values=["<b>Ratio</b>","<b>Latest</b>","<b>Label</b>","<b>Trend</b>","<b>Score</b>"],
            fill_color="#f1f5f9",
            font=dict(color=_TEXT, size=13, family=_FONT),
            align=["left","center","center","center","center"],
            line_color="#e2e8f0", height=36,
        ),
        cells=dict(
            values=[
                [r["name"]   for r in rows],
                [r["latest"] for r in rows],
                [r["label"]  for r in rows],
                [r["trend"]  for r in rows],
                [r["score"]  for r in rows],
            ],
            fill_color=[white, white, label_bg, trend_bg, white],
            font=dict(
                color=[dark, dark, label_font, trend_font, dark],
                size=12, family=_FONT,
            ),
            align=["left","center","center","center","center"],
            line_color="#e2e8f0", height=32,
        ),
    )])

    fig.update_layout(
        title=dict(
            text="<b>Ratio Summary — Trend & Classification</b>",
            font=dict(size=16, color=_TEXT, family=_FONT),
            x=0.5,
            xanchor="center",
        ),
        margin=dict(l=0, r=0, t=52, b=0),
        paper_bgcolor=_BG,
        height=max(440, len(rows)*34+100),
    )
    return fig


def get_kpi_data(data):
    prof          = data.get("profitability", {})
    lev           = data.get("leverage", {})
    ps            = data.get("per_share", {})
    latest_period = data.get("latest_period", "")

    # Detect if showing TTM quarter (not a March year-end)
    is_ttm = bool(latest_period) and latest_period[5:7] != "03"
    _qmap  = {"06": "Q1", "09": "Q2", "12": "Q3"}
    if is_ttm:
        q  = _qmap.get(latest_period[5:7], "Q?")
        fy = str(int(latest_period[:4]) + 1)
        ttm_label = f"TTM {q}FY{fy}"
    else:
        ttm_label = ""

    def _k(cat_data, ratio, title, unit):
        rd    = cat_data.get(ratio, {})
        val   = rd.get("latest_value")
        trend = rd.get("trend", "stable")

        # If value is None (e.g. ROCE/Interest Coverage for banks), 
        # show "N/A" label not the raw label which may be wrong
        if val is None:
            label = "N/A"
        else:
            label = (rd.get("latest_label") or "—").replace("_", " ").title()
            # Don't show "Negative" for EPS — it means the label lookup failed
            # EPS is classified by YoY growth not by value, so latest_label may be None
            if ratio == "eps" and label in ("Negative", "—"):
                label = "—"

        return {
            "title":       title,
            "value":       val,
            "unit":        unit,
            "label":       label,
            "trend":       trend,
            "trend_color": _TREND_COLORS.get(trend, "#64748b"),
            "trend_icon":  _TREND_ICONS.get(trend, "→"),
            "is_ttm":      is_ttm,
            "ttm_label":   ttm_label,
        }

    kpis = [
        _k(prof, "roe",               "ROE",               "%"),
        _k(prof, "net_profit_margin",  "Net Margin",        "%"),
        _k(prof, "roce",               "ROCE",              "%"),
        _k(lev,  "interest_coverage",  "Interest Coverage", "x"),
        _k(ps,   "eps",                "EPS",               "Rs."),
    ]
    overall = data.get("summary_scores", {}).get("overall_score", 0)
    kpis.append({
        "title":       "Overall Score",
        "value":       overall,
        "unit":        "/5",
        "label":       "Composite",
        "trend":       "stable",
        "trend_color": _PALETTE[0],
        "trend_icon":  "★",
        "is_ttm":      is_ttm,
        "ttm_label":   ttm_label,
    })
    return kpis