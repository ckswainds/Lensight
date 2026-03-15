"""
dashboard/layout.py  — v4
Adds three screens:
  build_upload_screen()   — file drop zone
  build_loading_screen()  — animated progress during pipeline
  build_layout()          — full analysis dashboard (unchanged)
  build_error_layout()    — error fallback
"""

import logging
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from charts import (
    profitability_chart, margins_chart, valuation_chart,
    eps_chart, growth_chart, efficiency_chart, leverage_chart,
    score_radar_chart, trend_badge_table, get_kpi_data,
)

logger = logging.getLogger(__name__)

# ── Design tokens ─────────────────────────────────────────────────────────────
_FONT     = "Georgia, 'Times New Roman', serif"
_ACCENT   = "#0d9488"
_NAVY     = "#0f172a"
_CARD_BG  = "#ffffff"
_PAGE_BG  = "#f1f5f9"
_BORDER   = "#e2e8f0"
_TEXT_PRI = "#0f172a"
_TEXT_MUT = "#64748b"

_TREND_COLORS = {
    "strong_uptrend": "#059669", "improving": "#10b981",
    "stable": "#6366f1", "volatile": "#f59e0b",
    "declining": "#f97316", "strong_decline": "#ef4444",
}
_TREND_ICONS = {
    "strong_uptrend": "↑↑", "improving": "↑",
    "stable": "→", "volatile": "↕",
    "declining": "↓", "strong_decline": "↓↓",
}
_LABEL_COLORS = {
    "excellent": "#059669", "strong": "#10b981", "good": "#34d399",
    "average": "#6366f1", "adequate": "#6366f1", "moderate": "#f59e0b",
    "weak": "#f97316", "poor": "#ef4444", "negative": "#dc2626",
    "fair": "#6366f1", "undervalued": "#059669", "cheap": "#059669",
    "low": "#059669", "safe": "#10b981", "expensive": "#f97316",
    "very_expensive": "#ef4444", "risky": "#f97316",
    "very_risky": "#ef4444", "very_high": "#ef4444", "high": "#f97316",
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _card(children, padding="16px 20px", mb="14px", extra_class=""):
    return dbc.Card(
        dbc.CardBody(children, style={"padding": padding}),
        className=f"lensight-card {extra_class}".strip(),
        style={
            "background":   _CARD_BG,
            "border":       f"1px solid {_BORDER}",
            "borderRadius": "10px",
            "boxShadow":    "0 1px 6px rgba(0,0,0,0.08)",
            "marginBottom": mb,
        },
    )


def _chart_card(fig):
    return _card(
        dcc.Graph(
            figure=fig,
            config={
                "displayModeBar":         True,
                "modeBarButtonsToRemove": [
                    "select2d", "lasso2d", "autoScale2d",
                    "hoverCompareCartesian", "hoverClosestCartesian",
                ],
                "displaylogo": False,
                "responsive":  True,
            },
            style={"width": "100%"},
        ),
        padding="10px 14px",
    )


def _kpi_card(kpi: dict[str, Any]) -> dbc.Col:
    value     = kpi.get("value")
    unit      = kpi.get("unit", "")
    label     = kpi.get("label", "")
    trend     = kpi.get("trend", "stable")
    icon      = _TREND_ICONS.get(trend, "→")
    t_color   = _TREND_COLORS.get(trend, _TEXT_MUT)
    is_ttm    = kpi.get("is_ttm", False)
    ttm_label = kpi.get("ttm_label", "")
    is_na     = (value is None)

    # Label color — N/A gets muted color, valid labels get semantic color
    if is_na or label in ("N/A", "—"):
        lbl_color = _TEXT_MUT
    else:
        lbl_color = _LABEL_COLORS.get(label.lower().replace(" ", "_"), _TEXT_MUT)

    value_str = (
        f"{value:.2f}" if isinstance(value, float) else
        str(value)     if value is not None          else "—"
    )

    # Value color: muted gray when N/A, normal otherwise
    value_color = "#94a3b8" if is_na else _TEXT_PRI

    return dbc.Col(
        _card([
            # Title row — with TTM badge if applicable
            html.Div([
                html.P(kpi.get("title", ""), style={
                    "fontSize": "11px", "fontWeight": "700",
                    "letterSpacing": "0.09em", "textTransform": "uppercase",
                    "color": _TEXT_MUT, "margin": "0",
                    "fontFamily": "'DM Sans', system-ui, sans-serif",
                }),
                # TTM badge — shown when value is from TTM quarter
                html.Span(
                    ttm_label,
                    style={
                        "fontSize": "9px", "fontWeight": "800",
                        "color": _ACCENT, "background": _ACCENT + "18",
                        "padding": "1px 6px", "borderRadius": "8px",
                        "letterSpacing": "0.04em",
                        "marginLeft": "6px",
                        "fontFamily": "'DM Sans', sans-serif",
                        "display": "inline" if (is_ttm and ttm_label) else "none",
                    },
                ),
            ], style={
                "display": "flex", "alignItems": "center",
                "marginBottom": "8px",
            }),

            # Value + unit
            html.Div([
                html.Span(value_str, className="kpi-value", style={
                    "fontSize": "34px", "fontWeight": "900",
                    "color": value_color, "fontFamily": _FONT,
                    "lineHeight": "1", "letterSpacing": "-0.02em",
                }),
                html.Span(
                    unit if not is_na else "",
                    style={
                        "fontSize": "15px", "fontWeight": "700",
                        "color": _TEXT_MUT, "marginLeft": "3px",
                        "fontFamily": "'DM Sans', sans-serif",
                    },
                ),
            ], style={"marginBottom": "10px"}),

            # Label pill + trend
            html.Div([
                html.Span(label, style={
                    "fontSize": "10px", "fontWeight": "700",
                    "color": lbl_color,
                    "background": lbl_color + "1a",
                    "padding": "3px 9px", "borderRadius": "20px",
                    "marginRight": "8px", "letterSpacing": "0.05em",
                    "textTransform": "uppercase",
                    "fontFamily": "'DM Sans', sans-serif",
                }),
                html.Span(
                    "" if is_na else f"{icon} {trend.replace('_', ' ').title()}",
                    style={
                        "fontSize": "12px", "fontWeight": "600",
                        "color": t_color,
                        "fontFamily": "'DM Sans', sans-serif",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center"}),
        ], padding="16px 18px"),
        xs=12, sm=6, md=4, lg=2,
    )


def _section(text: str) -> html.Div:
    return html.Div(text, className="section-label", style={
        "fontSize": "11px", "fontWeight": "800",
        "letterSpacing": "0.13em", "textTransform": "uppercase",
        "color": _ACCENT, "borderLeft": f"3px solid {_ACCENT}",
        "paddingLeft": "10px", "marginBottom": "10px", "marginTop": "4px",
        "fontFamily": "'DM Sans', system-ui, sans-serif",
    })


def _score_pill(label: str, score: float) -> html.Span:
    color = "#059669" if score >= 4.0 else "#6366f1" if score >= 3.0 else "#f97316"
    return html.Span(
        f"{label}  {score}/5",
        className="score-pill",
        style={
            "fontSize": "11px", "fontWeight": "700",
            "color": color, "background": color + "1f",
            "padding": "4px 11px", "borderRadius": "20px",
            "marginRight": "6px", "display": "inline-block",
            "marginBottom": "4px", "letterSpacing": "0.02em",
            "fontFamily": "'DM Sans', sans-serif",
        },
    )


def _header_logo() -> html.Div:
    """Shared header logo component."""
    return html.Div([
        html.Span("L", style={
            "fontSize": "22px", "fontWeight": "900",
            "color": _ACCENT, "fontFamily": _FONT, "marginRight": "2px",
        }),
        html.Span("ENSIGHT", style={
            "fontSize": "14px", "fontWeight": "800",
            "letterSpacing": "0.22em", "color": "#94a3b8",
            "fontFamily": "'DM Sans', sans-serif",
            "verticalAlign": "middle",
        }),
    ], style={
        "display": "flex", "alignItems": "baseline",
        "borderLeft": f"3px solid {_ACCENT}", "paddingLeft": "10px",
    })


# ── Screen 1: Upload ──────────────────────────────────────────────────────────

def build_upload_screen(error: str = "") -> html.Div:
    """
    Upload screen — large branding, animated background,
    submit button waits for user action (not auto-triggered on file select).
    """
    return html.Div(
        style={
            "minHeight":      "100vh",
            "background":     _NAVY,
            "display":        "flex",
            "flexDirection":  "column",
            "alignItems":     "center",
            "justifyContent": "center",
            "fontFamily":     "'DM Sans', system-ui, sans-serif",
            "padding":        "40px 20px",
            "position":       "relative",
            "overflow":       "hidden",
        },
        children=[

            # ── Animated background orbs ─────────────────────────────────
            html.Div(className="bg-orb bg-orb-1"),
            html.Div(className="bg-orb bg-orb-2"),
            html.Div(className="bg-orb bg-orb-3"),

            # ── Brand block ──────────────────────────────────────────────
            html.Div(
                style={
                    "textAlign":      "center",
                    "marginBottom":   "48px",
                    "position":       "relative",
                    "zIndex":         "1",
                    "animation":      "fadeSlideUp 0.6s ease both",
                },
                children=[
                    # Large L mark
                    html.Div([
                        html.Span("L", style={
                            "fontSize":   "72px",
                            "fontWeight": "900",
                            "color":      _ACCENT,
                            "fontFamily": _FONT,
                            "lineHeight": "1",
                            "letterSpacing": "-0.04em",
                        }),
                        html.Span("ENSIGHT", style={
                            "fontSize":      "36px",
                            "fontWeight":    "800",
                            "letterSpacing": "0.18em",
                            "color":         "#e2e8f0",
                            "fontFamily":    "'DM Sans', sans-serif",
                            "marginLeft":    "6px",
                            "verticalAlign": "middle",
                        }),
                    ], style={
                        "display":       "flex",
                        "alignItems":    "baseline",
                        "justifyContent":"center",
                        "borderBottom":  f"2px solid {_ACCENT}",
                        "paddingBottom": "12px",
                        "marginBottom":  "14px",
                    }),

                    html.P(
                        "Fundamental Analysis Platform",
                        style={
                            "color":         "#94a3b8",
                            "fontSize":      "16px",
                            "fontWeight":    "500",
                            "letterSpacing": "0.1em",
                            "textTransform": "uppercase",
                            "margin":        "0",
                        },
                    ),

                    # Tagline
                    html.P(
                        "Upload. Analyse. Decide.",
                        style={
                            "color":      _ACCENT,
                            "fontSize":   "13px",
                            "fontWeight": "600",
                            "marginTop":  "8px",
                            "marginBottom": "0",
                            "letterSpacing": "0.06em",
                        },
                    ),
                ],
            ),

            # ── Upload card ──────────────────────────────────────────────
            dbc.Card(
                dbc.CardBody([
                    html.Div(style={"textAlign": "center"}, children=[

                        html.H4("Upload Company Files", style={
                            "fontFamily":   _FONT,
                            "fontWeight":   "900",
                            "color":        _TEXT_PRI,
                            "fontSize":     "20px",
                            "marginBottom": "4px",
                        }),
                        html.P(
                            "Add your Screener.in export to begin. Annual report is optional.",
                            style={
                                "color":        _TEXT_MUT,
                                "fontSize":     "13px",
                                "fontWeight":   "500",
                                "marginBottom": "24px",
                            },
                        ),

                        # ── Zone 1: Excel ─────────────────────────────────
                        html.Div(style={"marginBottom": "16px"}, children=[
                            html.Div([
                                html.Span("01", style={
                                    "fontSize":      "10px",
                                    "fontWeight":    "800",
                                    "color":         _ACCENT,
                                    "letterSpacing": "0.1em",
                                    "background":    _ACCENT + "1a",
                                    "padding":       "2px 8px",
                                    "borderRadius":  "10px",
                                    "marginRight":   "8px",
                                }),
                                html.Span("Screener.in Excel", style={
                                    "fontSize":  "12px",
                                    "fontWeight":"700",
                                    "color":     _TEXT_PRI,
                                }),
                                html.Span(" — required", style={
                                    "fontSize": "11px",
                                    "color":    "#ef4444",
                                    "fontWeight": "600",
                                }),
                            ], style={"marginBottom": "6px", "textAlign": "left"}),

                            dcc.Upload(
                                id="upload-xlsx",
                                children=html.Div([
                                    html.Div("📊", style={
                                        "fontSize":    "22px",
                                        "marginBottom":"6px",
                                    }),
                                    html.Div([
                                        html.Span("Drop .xlsx  ", style={
                                            "fontWeight": "700",
                                            "color":      _ACCENT,
                                            "fontSize":   "13px",
                                        }),
                                        html.Span("or ", style={
                                            "color":    _TEXT_MUT,
                                            "fontSize": "13px",
                                        }),
                                        html.Span("browse", style={
                                            "fontWeight":    "700",
                                            "color":         _ACCENT,
                                            "fontSize":      "13px",
                                            "textDecoration":"underline",
                                        }),
                                    ]),
                                    html.Div(
                                        id="xlsx-filename",
                                        style={
                                            "fontSize":    "12px",
                                            "color":       "#059669",
                                            "fontWeight":  "700",
                                            "marginTop":   "6px",
                                            "minHeight":   "18px",
                                        },
                                    ),
                                ]),
                                className="upload-zone upload-zone-xlsx",
                                style={
                                    "width":          "100%",
                                    "minHeight":      "88px",
                                    "border":         f"2px dashed {_ACCENT}",
                                    "borderRadius":   "10px",
                                    "display":        "flex",
                                    "alignItems":     "center",
                                    "justifyContent": "center",
                                    "cursor":         "pointer",
                                    "background":     "#f0fdfa",
                                    "padding":        "14px 20px",
                                },
                                multiple=False,
                                accept=".xlsx,.xls",
                            ),
                        ]),

                        # ── Zone 2: PDF ───────────────────────────────────
                        html.Div(style={"marginBottom": "24px"}, children=[
                            html.Div([
                                html.Span("02", style={
                                    "fontSize":      "10px",
                                    "fontWeight":    "800",
                                    "color":         "#6366f1",
                                    "letterSpacing": "0.1em",
                                    "background":    "#6366f11a",
                                    "padding":       "2px 8px",
                                    "borderRadius":  "10px",
                                    "marginRight":   "8px",
                                }),
                                html.Span("Annual Report PDF", style={
                                    "fontSize":  "12px",
                                    "fontWeight":"700",
                                    "color":     _TEXT_PRI,
                                }),
                                html.Span(" — optional, for RAG pipeline", style={
                                    "fontSize": "11px",
                                    "color":    _TEXT_MUT,
                                }),
                            ], style={"marginBottom": "6px", "textAlign": "left"}),

                            dcc.Upload(
                                id="upload-pdf",
                                children=html.Div([
                                    html.Div("📄", style={
                                        "fontSize":    "22px",
                                        "marginBottom":"6px",
                                    }),
                                    html.Div([
                                        html.Span("Drop .pdf  ", style={
                                            "fontWeight": "700",
                                            "color":      "#6366f1",
                                            "fontSize":   "13px",
                                        }),
                                        html.Span("or ", style={
                                            "color":    _TEXT_MUT,
                                            "fontSize": "13px",
                                        }),
                                        html.Span("browse", style={
                                            "fontWeight":    "700",
                                            "color":         "#6366f1",
                                            "fontSize":      "13px",
                                            "textDecoration":"underline",
                                        }),
                                    ]),
                                    html.Div(
                                        id="pdf-filename",
                                        style={
                                            "fontSize":   "12px",
                                            "color":      "#059669",
                                            "fontWeight": "700",
                                            "marginTop":  "6px",
                                            "minHeight":  "18px",
                                        },
                                    ),
                                ]),
                                className="upload-zone upload-zone-pdf",
                                style={
                                    "width":          "100%",
                                    "minHeight":      "88px",
                                    "border":         "2px dashed #6366f1",
                                    "borderRadius":   "10px",
                                    "display":        "flex",
                                    "alignItems":     "center",
                                    "justifyContent": "center",
                                    "cursor":         "pointer",
                                    "background":     "#eef2ff",
                                    "padding":        "14px 20px",
                                },
                                multiple=False,
                                accept=".pdf",
                            ),
                        ]),

                        # ── Submit button ─────────────────────────────────
                        html.Button(
                            "Run Analysis →",
                            id="btn-run-analysis",
                            n_clicks=0,
                            style={
                                "width":         "100%",
                                "padding":       "14px",
                                "fontSize":      "15px",
                                "fontWeight":    "800",
                                "fontFamily":    "'DM Sans', sans-serif",
                                "color":         "#ffffff",
                                "background":    f"linear-gradient(135deg, {_ACCENT}, #10b981)",
                                "border":        "none",
                                "borderRadius":  "10px",
                                "cursor":        "pointer",
                                "letterSpacing": "0.04em",
                                "transition":    "all 0.2s ease",
                                "marginBottom":  "12px",
                            },
                            className="btn-run",
                        ),

                        # Error message
                        html.Div(
                            error,
                            id="upload-error-msg",
                            style={
                                "color":      "#ef4444",
                                "fontSize":   "13px",
                                "fontWeight": "600",
                                "textAlign":  "center",
                                "minHeight":  "20px",
                                "display":    "block" if error else "none",
                            },
                        ),

                        html.P(
                            "Excel is required to start  •  PDF stored for RAG  ",
                            style={
                                "color":     "#94a3b8",
                                "fontSize":  "11px",
                                "textAlign": "center",
                                "margin":    "0",
                            },
                        ),
                    ]),
                ]),
                style={
                    "maxWidth":     "520px",
                    "width":        "100%",
                    "border":       f"1px solid rgba(255,255,255,0.08)",
                    "borderRadius": "16px",
                    "boxShadow":    "0 24px 64px rgba(0,0,0,0.3)",
                    "position":     "relative",
                    "zIndex":       "1",
                    "animation":    "fadeSlideUp 0.7s ease 0.1s both",
                },
            ),

            # Bottom tagline
            html.P(
                "Powered by Screener.in data • Built with Lensight",
                style={
                    "color":       "#334155",
                    "fontSize":    "11px",
                    "marginTop":   "32px",
                    "position":    "relative",
                    "zIndex":      "1",
                },
            ),
        ],
    )



# ── Screen 2: Loading ─────────────────────────────────────────────────────────

def build_loading_screen() -> html.Div:
    """
    Animated loading screen shown while the pipeline runs.
    Progress bar and stage label updated via callbacks.
    """
    steps = [
        ("Clearing data",        "flushing"),
        ("Parsing Excel",        "parsing"),
        ("Preprocessing",        "processing"),
        ("Computing Ratios",     "ratios"),
        ("Analysing Trends",     "trends"),
        ("Building Output",      "formatting"),
    ]

    return html.Div(
        style={
            "minHeight": "100vh", "background": _NAVY,
            "display": "flex", "flexDirection": "column",
            "alignItems": "center", "justifyContent": "center",
            "fontFamily": "'DM Sans', system-ui, sans-serif",
            "padding": "40px 20px",
        },
        children=[

            # Logo
            html.Div([
                html.Span("L", style={
                    "fontSize": "28px", "fontWeight": "900",
                    "color": _ACCENT, "fontFamily": _FONT,
                }),
                html.Span("ENSIGHT", style={
                    "fontSize": "17px", "fontWeight": "800",
                    "letterSpacing": "0.25em", "color": "#94a3b8",
                    "fontFamily": "'DM Sans', sans-serif",
                    "marginLeft": "4px",
                }),
            ], style={
                "display": "flex", "alignItems": "baseline",
                "borderLeft": f"4px solid {_ACCENT}",
                "paddingLeft": "12px", "marginBottom": "48px",
            }),

            # Spinner ring
            html.Div(style={
                "width":  "72px", "height": "72px",
                "border": f"4px solid rgba(13,148,136,0.2)",
                "borderTop": f"4px solid {_ACCENT}",
                "borderRadius": "50%",
                "animation": "spin 0.9s linear infinite",
                "marginBottom": "32px",
            }),

            # Company name — id lives in shell, callback targets shell element
            # We render a visual placeholder; the shell's loading-company is
            # positioned via CSS to overlay this space
            html.Div(
                id="loading-company-display",
                style={
                    "color": _ACCENT, "fontSize": "16px",
                    "fontWeight": "700", "marginBottom": "8px",
                    "letterSpacing": "0.02em", "minHeight": "24px",
                },
            ),

            # Stage label placeholder
            html.Div(
                id="loading-stage-display",
                children="Analysing your data...",
                style={
                    "color": "#94a3b8", "fontSize": "14px",
                    "fontWeight": "500", "marginBottom": "24px",
                    "minHeight": "22px",
                },
            ),

            # Progress bar — id lives in shell so callback can update value
            html.Div(
                style={"width": "360px", "maxWidth": "90vw", "marginBottom": "36px"},
                children=[
                    dbc.Progress(
                        id="loading-progress-display",
                        value=5,
                        max=100,
                        className="lensight-progress",
                        style={
                            "height": "6px",
                            "borderRadius": "3px",
                            "backgroundColor": "rgba(255,255,255,0.08)",
                        },
                    ),
                ],
            ),

            # Step indicators
            html.Div(
                style={
                    "display": "flex", "gap": "24px",
                    "flexWrap": "wrap", "justifyContent": "center",
                    "maxWidth": "480px",
                },
                children=[
                    html.Div([
                        html.Div(style={
                            "width": "8px", "height": "8px",
                            "borderRadius": "50%",
                            "background": _ACCENT,
                            "animation": "pulse 1.4s ease infinite",
                            "animationDelay": f"{i * 0.22}s",
                            "display": "inline-block",
                            "marginRight": "6px",
                        }),
                        html.Span(label, style={
                            "color": "#64748b", "fontSize": "12px",
                            "fontWeight": "500",
                        }),
                    ], style={"display": "flex", "alignItems": "center"})
                    for i, (label, _) in enumerate(steps)
                ],
            ),
        ],
    )


# ── Screen 3: Dashboard ───────────────────────────────────────────────────────

def build_layout(data: dict[str, Any]) -> html.Div:
    """Full analysis dashboard — unchanged from previous version."""
    company      = data.get("company", "UNKNOWN")
    periods      = data.get("periods", [])
    generated_at = data.get("generated_at", "")
    scores       = data.get("summary_scores", {})
    # Detect TTM: if latest period is not a March year-end, it's a TTM quarter
    def _fy_label(period: str) -> str:
        """Convert YYYY-MM-DD to FY label. March year-ends = FY, others = TTM."""
        year  = period[:4]
        month = period[5:7]
        if month == "03":
            return f"FY{year}"
        # Quarter end — label as TTM with quarter
        qmap = {"06": "Q1", "09": "Q2", "12": "Q3", "03": "Q4"}
        q = qmap.get(month, "Q?")
        fy = str(int(year) + 1) if month != "03" else year
        return f"TTM {q}FY{fy}"

    latest_label = _fy_label(periods[-1]) if periods else ""
    period_range = (
        f"FY{periods[0][:4]} – {latest_label}"
        if len(periods) >= 2 else ""
    )

    kpis = get_kpi_data(data)

    logger.info("Building dashboard figures for '%s'...", company)
    figs = {
        "prof":  profitability_chart(data),
        "mar":   margins_chart(data),
        "val":   valuation_chart(data),
        "eps":   eps_chart(data),
        "grow":  growth_chart(data),
        "radar": score_radar_chart(data),
        "eff":   efficiency_chart(data),
        "lev":   leverage_chart(data),
        "table": trend_badge_table(data),
    }
    logger.info("Figures ready.")

    return html.Div(
        style={"background": _PAGE_BG, "minHeight": "100vh",
               "fontFamily": "'DM Sans', system-ui, sans-serif"},
        children=[

            # CSS loaded from dashboard/assets/style.css automatically

            # ── Header ────────────────────────────────────────────
            html.Div(
                style={
                    "background": _NAVY, "padding": "24px 48px 20px",
                    "borderBottom": f"4px solid {_ACCENT}",
                },
                children=[dbc.Container(fluid=True, children=[
                    dbc.Row([
                        dbc.Col([
                            _header_logo(),
                            html.Div(style={"height": "8px"}),
                            html.H1(company, style={
                                "fontFamily": _FONT,
                                "fontSize": "clamp(22px, 3vw, 36px)",
                                "fontWeight": "900", "color": "#f8fafc",
                                "margin": "0 0 8px 0",
                                "letterSpacing": "-0.01em", "lineHeight": "1.1",
                            }),
                            html.Div([
                                html.Span("Fundamental Analysis", style={
                                    "fontSize": "13px", "fontWeight": "500",
                                    "color": _ACCENT, "marginRight": "14px",
                                }),
                                html.Span(period_range, style={
                                    "fontSize": "13px", "fontWeight": "500",
                                    "color": "#94a3b8", "marginRight": "14px",
                                }),
                                html.Span(f"Generated {generated_at[:10]}", style={
                                    "fontSize": "12px", "color": "#64748b",
                                }),
                            ]),
                        ], md=7),

                        dbc.Col([
                            html.Div(style={"textAlign": "right", "paddingTop": "4px"}, children=[
                                html.Div("OVERALL SCORE", style={
                                    "fontSize": "10px", "fontWeight": "800",
                                    "letterSpacing": "0.2em", "color": "#64748b",
                                    "marginBottom": "4px",
                                }),
                                html.Div([
                                    html.Span(
                                        f"{scores.get('overall_score', 0):.1f}",
                                        style={
                                            "fontFamily": _FONT,
                                            "fontSize": "52px", "fontWeight": "900",
                                            "color": _ACCENT, "lineHeight": "1",
                                            "letterSpacing": "-0.03em",
                                        },
                                    ),
                                    html.Span("/5", style={
                                        "fontSize": "20px", "fontWeight": "700",
                                        "color": "#475569",
                                    }),
                                ], style={"marginBottom": "10px"}),
                                html.Div([
                                    _score_pill(
                                        cat.replace("_score", "").title(), val
                                    )
                                    for cat, val in scores.items()
                                    if cat != "overall_score"
                                ]),

                                # New analysis button
                                html.Button(
                                    "↑  New Analysis",
                                    id="btn-new-analysis",
                                    n_clicks=0,
                                    style={
                                        "marginTop": "12px",
                                        "background": "transparent",
                                        "border": f"1px solid {_ACCENT}",
                                        "color": _ACCENT,
                                        "borderRadius": "20px",
                                        "padding": "6px 16px",
                                        "fontSize": "12px",
                                        "fontWeight": "700",
                                        "cursor": "pointer",
                                        "fontFamily": "'DM Sans', sans-serif",
                                        "transition": "all 0.18s ease",
                                        "letterSpacing": "0.04em",
                                    },
                                ),
                            ]),
                        ], md=5),
                    ]),
                ])],
            ),

            # ── Body ──────────────────────────────────────────────
            dbc.Container(fluid=True, style={"padding": "20px 28px"}, children=[

                _section("Key Metrics"),
                dbc.Row([_kpi_card(k) for k in kpis], className="g-3",
                        style={"marginBottom": "4px"}),

                _section("Profitability & Margins"),
                dbc.Row([
                    dbc.Col(_chart_card(figs["prof"]), md=6),
                    dbc.Col(_chart_card(figs["mar"]),  md=6),
                ], className="g-3"),

                _section("Valuation & Per Share"),
                dbc.Row([
                    dbc.Col(_chart_card(figs["val"]), md=6),
                    dbc.Col(_chart_card(figs["eps"]), md=6),
                ], className="g-3"),

                _section("Growth & Score"),
                dbc.Row([
                    dbc.Col(_chart_card(figs["grow"]),  md=6),
                    dbc.Col(_chart_card(figs["radar"]), md=6),
                ], className="g-3"),

                _section("Efficiency & Leverage"),
                dbc.Row([
                    dbc.Col(_chart_card(figs["eff"]), md=6),
                    dbc.Col(_chart_card(figs["lev"]), md=6),
                ], className="g-3"),

                _section("Ratio Summary — Trend & Classification"),
                dbc.Row([
                    dbc.Col(_chart_card(figs["table"]), md=12),
                ], className="g-3"),

                html.Div([
                    html.Span("Lensight  •  Fundamental Analysis Platform", style={
                        "fontSize": "12px", "fontWeight": "500", "color": _TEXT_MUT,
                    }),
                    html.Span("  •  Data sourced from Screener.in", style={
                        "fontSize": "12px", "color": "#94a3b8",
                    }),
                ], style={
                    "textAlign": "center", "padding": "20px 0 28px",
                    "borderTop": f"1px solid {_BORDER}", "marginTop": "4px",
                }),
            ]),
        ],
    )


# ── Error layout ──────────────────────────────────────────────────────────────

def build_error_layout(message: str) -> html.Div:
    return html.Div(
        style={
            "minHeight": "100vh", "background": _PAGE_BG,
            "display": "flex", "alignItems": "center",
            "justifyContent": "center",
            "fontFamily": "'DM Sans', sans-serif",
        },
        children=[dbc.Card(
            dbc.CardBody([
                html.Div("⚠", style={
                    "fontSize": "48px", "textAlign": "center", "marginBottom": "16px",
                }),
                html.H4("Dashboard unavailable", style={
                    "fontFamily": _FONT, "fontWeight": "900",
                    "textAlign": "center", "color": _TEXT_PRI, "marginBottom": "12px",
                }),
                html.P(message, style={
                    "color": _TEXT_MUT, "textAlign": "center",
                    "fontSize": "14px", "fontWeight": "500",
                }),
            ]),
            style={
                "maxWidth": "520px", "width": "100%",
                "border": f"1px solid {_BORDER}", "borderRadius": "16px",
                "boxShadow": "0 4px 24px rgba(0,0,0,0.08)",
            },
        )],
    )