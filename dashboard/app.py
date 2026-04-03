"""
dashboard/app.py  — v4
Upload-first flow with background pipeline + polling.

Run
---
  python dashboard/app.py
  uvicorn dashboard.app:fastapi_app --host 0.0.0.0 --port 8050 --reload
"""

import json
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from constants import (
    DATA_PROCESSED_DIR, LOGS_DIR,
    DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_DEBUG,
)
from dashboard.layout import build_upload_screen, build_layout, build_error_layout
from dashboard.callbacks import register_callbacks

# ── Logging ───────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(LOGS_DIR / "dashboard.log", mode="a", encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_fmt = logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_fh.setFormatter(_fmt)
_ch.setFormatter(_fmt)
if not logger.handlers:
    logger.addHandler(_fh)
    logger.addHandler(_ch)

_ANALYSIS_FILE = DATA_PROCESSED_DIR / "analysis.json"


# ── Determine initial screen ───────────────────────────────────────────────────

def _initial_content():
    """
    Always start with the upload screen.
    The user must upload a file every session — this ensures stale
    analysis.json from a previous company never silently pre-loads.
    The dashboard is shown only after a successful pipeline run via callbacks.
    """
    logger.info("Starting on upload screen.")
    return build_upload_screen(), "upload"


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> tuple[dash.Dash, FastAPI]:
    logger.info("Initialising Lensight dashboard (FastAPI + upload flow)...")

    initial_content, initial_screen = _initial_content()

    dash_app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        title="Lensight — Fundamental Analysis",
        suppress_callback_exceptions=True,
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        ],
        requests_pathname_prefix="/",
    )

    # ── Root layout ───────────────────────────────────────────────────────────
    # All component IDs referenced by callbacks must exist in the root layout.
    # Components only used on certain screens are hidden with display:none.
    # page-content holds the active screen and is swapped by callbacks.
    dash_app.layout = html.Div([

        # App-level state store
        dcc.Store(id="app-state", data={"screen": initial_screen}),

        # Chat memory stores — persisted across dashboard ↔ chat navigation
        dcc.Store(id="chat-history", data=[]),
        dcc.Store(id="conv-summary", data=""),
        dcc.Store(id="pending-chat-request", data=None),  # Stores pending LLM request data
        dcc.Store(id="streaming-response", data=None),  # Stores streaming response data

        # Streaming interval — polls for new tokens
        dcc.Interval(
            id="stream-interval",
            interval=100,  # Poll every 100ms - CRITICAL for responsive streaming
            n_intervals=0,
            disabled=True,
        ),

        # Polling interval — disabled by default, enabled during processing
        dcc.Interval(
            id="poll-interval",
            interval=500,
            n_intervals=0,
            disabled=True,
        ),

        # All callback-target IDs (loading-progress-display, loading-stage-display,
        # loading-company-display, btn-new-analysis) live inside page-content
        # and are rendered by build_loading_screen() / build_layout().
        # suppress_callback_exceptions=True handles the case where they are
        # temporarily absent during screen transitions.

        # ── Main content ──────────────────────────────────────────────────────
        # Swapped between upload / loading / dashboard screens by callbacks
        html.Div(id="page-content", children=initial_content),

    ])

    register_callbacks(dash_app)

    # ── FastAPI wrapper ────────────────────────────────────────────────────────
    fastapi_app = FastAPI(
        title="Lensight",
        description="Fundamental Analysis Dashboard — FastAPI + Dash",
        version="2.0.0",
    )

    @fastapi_app.get("/health")
    async def health():
        return {"status": "ok", "service": "lensight-dashboard"}

    @fastapi_app.get("/api/analysis")
    async def get_analysis():
        if _ANALYSIS_FILE.exists():
            with _ANALYSIS_FILE.open(encoding="utf-8") as fh:
                return json.load(fh)
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No analysis available yet.")

    @fastapi_app.get("/api/pipeline-status")
    async def pipeline_status():
        from dashboard.pipeline_runner import get_status
        return get_status()

    fastapi_app.mount("/", WSGIMiddleware(dash_app.server))

    logger.info("App ready.")
    return dash_app, fastapi_app


# ── Module-level instances for uvicorn ────────────────────────────────────────

dash_app, fastapi_app = create_app()

if __name__ == "__main__":
    logger.info(
        "Starting Lensight — http://%s:%s", DASHBOARD_HOST, DASHBOARD_PORT
    )
    uvicorn.run(
        "dashboard.app:fastapi_app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=DASHBOARD_DEBUG,
        log_level="info",
    )