"""Lensight — Project Constants
Centralized path definitions for the entire project.
Import these paths in any module to avoid hardcoding.
"""

from pathlib import Path
import os
# ─────────────────────────────────────────────────────────────────
# Project Root
# ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.resolve()


# ─────────────────────────────────────────────────────────────────
# Data Directories
# ─────────────────────────────────────────────────────────────────

DATA_DIR = PROJECT_ROOT / "data"
DATA_UPLOADS_DIR = DATA_DIR / "uploads"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_VECTOR_STORE_DIR = DATA_DIR / "vector_store"

# Written when core analysis finishes (after analysis.json). Used by the
# dashboard poll callback to detect completion when in-memory PipelineStatus
# is stale (e.g. multiple replicas / workers on Railway, Render, etc.).
ANALYSIS_READY_FLAG = DATA_PROCESSED_DIR / ".lensight_analysis_ready"


# ─────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────

LOGS_DIR = PROJECT_ROOT / "logs"


# ─────────────────────────────────────────────────────────────────
# CSV File Paths (Raw Data)
# ─────────────────────────────────────────────────────────────────

CSV_PNL = DATA_RAW_DIR / "pnl.csv"
CSV_BALANCE_SHEET = DATA_RAW_DIR / "balance_sheet.csv"
CSV_CASH_FLOW = DATA_RAW_DIR / "cash_flow.csv"
CSV_QUARTERS = DATA_RAW_DIR / "quarters.csv"
CSV_META = DATA_RAW_DIR / "meta.csv"

DASHBOARD_HOST  = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT  = int(os.getenv("DASHBOARD_PORT", "8050"))
DASHBOARD_DEBUG = os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"

# Chat streaming: max wait for first LLM token (slow / free-tier APIs).
# Hosted: set LENSIGHT_STREAM_FIRST_TOKEN_TIMEOUT (seconds, minimum 30).
STREAM_FIRST_TOKEN_TIMEOUT_SEC = max(
    30,
    int(os.getenv("LENSIGHT_STREAM_FIRST_TOKEN_TIMEOUT", "300")),
)