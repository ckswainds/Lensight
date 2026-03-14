"""Lensight — Project Constants
Centralized path definitions for the entire project.
Import these paths in any module to avoid hardcoding.
"""

from pathlib import Path

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
