"""
Preprocessor module for financial tables (balance_sheet, pnl, cashflow, quarterly)

Automatically discovers CSV files from data/raw/, processes them, and saves
results to data/processed/ with comprehensive logging for debugging.

Features
--------
• Automatically load CSVs from data/raw folder
• Normalize metric names
• Detect date columns dynamically
• Convert string values → numeric
• Handle empty Excel cells
• Remove duplicate metrics
• Optional scaling to crores
• Output both wide + long data format
• Comprehensive logging to logs folder
• Save processed data to data/processed folder
• Accepts optional raw_dir / processed_dir arguments — no monkey-patching needed
"""

import logging
import logging.handlers
from typing import Dict, List, Optional
from pathlib import Path
import re
import pandas as pd
import numpy as np
from pandas.tseries.offsets import MonthEnd

from constants import DATA_RAW_DIR, DATA_PROCESSED_DIR, LOGS_DIR


# ─────────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file = LOGS_DIR / "preprocessor.log"
file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


_MONTH_PAT = re.compile(r"^[A-Za-z]{3}-\d{4}$")


def _normalize_colname(name: str) -> str:
    """
    Normalize column names to a consistent format.

    Converts date columns (e.g. "Mar-2016") as-is, otherwise converts
    to lowercase snake_case and removes special characters.

    Parameters
    ----------
    name : str
        Original column name from CSV.

    Returns
    -------
    str
        Normalized column name.
    """
    if pd.isna(name):
        return name

    name = str(name).strip()

    if _MONTH_PAT.match(name):
        return name

    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", "_", name)

    return name.strip("_")


def _parse_date_col(col) -> Optional[pd.Timestamp]:
    """
    Parse a column name into a date if it matches the Mon-YYYY format.

    Parameters
    ----------
    col
        Column name to parse.

    Returns
    -------
    Optional[pd.Timestamp]
        Parsed date or None if parsing fails.
    """
    try:
        if _MONTH_PAT.match(str(col)):
            dt = pd.to_datetime(col, format="%b-%Y", errors="coerce")
            if pd.notna(dt):
                return (dt + MonthEnd(0)).normalize()
    except Exception:
        pass

    return None


def _to_numeric_val(val, preserve_on_fail: bool = False) -> float:
    """
    Convert a value to numeric, handling various formats and edge cases.

    Handles:
    - None and empty strings → np.nan
    - Parenthesized numbers → negative values
    - Comma-separated numbers
    - Scientific notation

    Parameters
    ----------
    val
        Value to convert.
    preserve_on_fail : bool, default False
        If True, return original value if conversion fails.
        If False, return np.nan on conversion failure.

    Returns
    -------
    float or original value
        Numeric value, np.nan, or original value (if preserve_on_fail=True).
    """
    if val is None:
        return np.nan

    if isinstance(val, (int, float, np.number)):
        return float(val)

    s = str(val).strip()

    if s == "":
        return np.nan

    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]

    s = s.replace(",", "")
    s = re.sub(r"[^\d.\-eE]", "", s)

    if s == "":
        return val if preserve_on_fail else np.nan

    try:
        num = float(s)
        return -num if neg else num
    except Exception:
        return val if preserve_on_fail else np.nan


def preprocess_table(
    df: pd.DataFrame,
    table_name: Optional[str] = None,
    scale_to: str = "auto",
    exclude_from_scaling: Optional[List[str]] = None,
    fillna_value: float = 0.0,
) -> Dict[str, pd.DataFrame]:
    """
    Preprocess a single financial table (balance_sheet, pnl, cashflow, etc).

    Cleans, normalizes, converts to numeric, and optionally scales values.
    Returns both wide and long format DataFrames.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame (typically loaded from CSV).
    table_name : str, optional
        Name of the table (e.g., "pnl", "balance_sheet") for logging.
    scale_to : str, default 'auto'
        Scaling mode: 'auto' (detect crores), 'crore', or 'none'.
    exclude_from_scaling : List[str], optional
        Metric names to exclude from scaling (e.g., share counts).
    fillna_value : float, default 0.0
        Value to fill NaN entries in numeric columns.

    Returns
    -------
    Dict[str, pd.DataFrame]
        Dictionary with 'wide' and 'long' format DataFrames.
    """
    if exclude_from_scaling is None:
        exclude_from_scaling = []

    logger.debug("Starting preprocessing for table: %s", table_name)

    df = df.replace("", np.nan)

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "metric"})
    df.columns = [_normalize_colname(c) for c in df.columns]
    logger.debug("Normalized %d column names", len(df.columns))

    df["metric_orig"] = df["metric"].astype(str)
    df["metric"] = df["metric"].apply(_normalize_colname)

    other_cols = [c for c in df.columns if c not in ("metric", "metric_orig")]

    date_cols = []
    non_date_cols = []

    for col in other_cols:
        if _parse_date_col(col) is not None:
            date_cols.append(col)
        else:
            non_date_cols.append(col)

    if not date_cols:
        for col in other_cols:
            if re.search(r"\d{4}", str(col)):
                date_cols.append(col)
            else:
                non_date_cols.append(col)

    logger.debug(
        "Identified %d date columns and %d non-date columns",
        len(date_cols), len(non_date_cols),
    )

    date_map = {}
    for col in date_cols:
        parsed = _parse_date_col(col)
        date_map[col] = parsed.strftime("%Y-%m-%d") if parsed is not None else col

    cleaned_rows = []
    for _, row in df.iterrows():
        metric      = row["metric"]
        metric_orig = row["metric_orig"]

        numeric_values = {}
        for col in date_cols:
            numeric_values[col] = _to_numeric_val(row.get(col))

        for col in non_date_cols:
            if col in ("metric", "metric_orig"):
                continue
            numeric_values[col] = _to_numeric_val(row.get(col), preserve_on_fail=True)

        record = {"metric": metric, "metric_orig": metric_orig}
        record.update(numeric_values)
        cleaned_rows.append(record)

    wide = pd.DataFrame(cleaned_rows)
    logger.debug("Converted %d rows to wide format", len(wide))

    wide = wide.drop_duplicates(subset="metric", keep="first")
    logger.debug("Removed duplicates, %d unique metrics remaining", len(wide))

    wide = wide.set_index("metric")
    wide = wide.rename(columns=date_map)

    unit_map = {}

    def _should_exclude(metric: str) -> bool:
        for ex in exclude_from_scaling:
            if ex.lower() in metric:
                return True
        for kw in ["shares", "number", "qty", "quantity", "face_value"]:
            if kw in metric:
                return True
        return False

    if scale_to == "none":
        for metric in wide.index:
            unit_map[metric] = ""
    else:
        for metric in wide.index:
            if _should_exclude(metric):
                unit_map[metric] = ""
                continue

            values = wide.loc[metric].drop(["metric_orig"]).values
            values = values[~pd.isna(values)]

            if len(values) == 0:
                unit_map[metric] = ""
                continue

            numeric_values_list = []
            for v in values:
                try:
                    numeric_values_list.append(float(v))
                except (ValueError, TypeError):
                    pass

            if len(numeric_values_list) == 0:
                unit_map[metric] = ""
                continue

            median = np.median(np.abs(numeric_values_list))

            if scale_to == "crore" or (scale_to == "auto" and median >= 1e6):
                unit_map[metric] = "in crores"
                for col in wide.columns:
                    if col == "metric_orig":
                        continue
                    val = wide.loc[metric, col]
                    if isinstance(val, pd.Series):
                        val = val.iloc[0]
                    if pd.notna(val):
                        wide.loc[metric, col] = float(val) / 1e7
            else:
                unit_map[metric] = ""

    numeric_cols = [c for c in wide.columns if c != "metric_orig"]
    wide[numeric_cols] = wide[numeric_cols].apply(pd.to_numeric, errors="coerce")
    wide[numeric_cols] = wide[numeric_cols].fillna(fillna_value)
    logger.debug(
        "Filled %s for NaN values in %d numeric columns",
        fillna_value, len(numeric_cols),
    )

    wide["metric_display"] = wide.apply(
        lambda r: (
            f"{r['metric_orig']} ({unit_map.get(r.name)})"
            if unit_map.get(r.name)
            else r["metric_orig"]
        ),
        axis=1,
    )

    rows = []
    for metric, row in wide.iterrows():
        for col in numeric_cols:
            value = row[col]
            if isinstance(col, pd.Timestamp):
                date  = col
                label = col.strftime("%Y-%m-%d")
            else:
                date  = _parse_date_col(col)
                label = str(col)

            rows.append({
                "metric":         metric,
                "metric_display": row["metric_display"],
                "date":           date,
                "period_label":   label,
                "value":          float(value),
                "unit":           unit_map.get(metric, ""),
                "source_table":   table_name,
            })

    long_df = pd.DataFrame(rows)
    logger.debug("Created long format DataFrame with %d rows", len(long_df))
    logger.info(
        "Preprocessing complete for table '%s': %d metrics × %d periods",
        table_name, len(wide), len(date_cols),
    )

    return {"wide": wide, "long": long_df}


def preprocess_all(
    tables: Dict[str, pd.DataFrame],
    scale_to: str = "auto",
    exclude_from_scaling: Optional[List[str]] = None,
    fillna_value: float = 0.0,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Preprocess multiple financial tables at once.

    Parameters
    ----------
    tables : Dict[str, pd.DataFrame]
        Dictionary mapping table names to DataFrames.
    scale_to : str, default 'auto'
        Scaling mode: 'auto', 'crore', or 'none'.
    exclude_from_scaling : List[str], optional
        Metric names to exclude from scaling.
    fillna_value : float, default 0.0
        Value to fill NaN entries.

    Returns
    -------
    Dict[str, Dict[str, pd.DataFrame]]
        Nested dict: {table_name: {'wide': wide_df, 'long': long_df}}
    """
    logger.info("Starting batch processing of %d tables", len(tables))
    results = {}

    for name, df in tables.items():
        logger.debug("Processing table: %s", name)
        results[name] = preprocess_table(
            df=df,
            table_name=name,
            scale_to=scale_to,
            exclude_from_scaling=exclude_from_scaling,
            fillna_value=fillna_value,
        )

    logger.info("Batch processing complete: %d tables processed", len(results))
    return results


# ─────────────────────────────────────────────────────────────────
# Path-aware helpers — accept explicit dirs, fall back to constants
# ─────────────────────────────────────────────────────────────────

def _resolve_raw_dir(raw_dir: Optional[Path]) -> Path:
    """Return raw_dir if provided, else the constant default."""
    return Path(raw_dir) if raw_dir is not None else DATA_RAW_DIR


def _resolve_processed_dir(processed_dir: Optional[Path]) -> Path:
    """Return processed_dir if provided, else the constant default."""
    return Path(processed_dir) if processed_dir is not None else DATA_PROCESSED_DIR


def _discover_csv_files(raw_dir: Optional[Path] = None) -> Dict[str, Path]:
    """
    Discover all CSV files in the raw data directory.

    Parameters
    ----------
    raw_dir : Path, optional
        Override for the raw data directory.
        Falls back to DATA_RAW_DIR from constants when omitted.

    Returns
    -------
    Dict[str, Path]
        Dictionary mapping table names (without .csv) to file paths.

    Raises
    ------
    FileNotFoundError
        If the raw directory does not exist.
    """
    raw_path = _resolve_raw_dir(raw_dir)
    logger.debug("Discovering CSV files in %s", raw_path)

    if not raw_path.exists():
        logger.error("Raw data directory does not exist: %s", raw_path)
        raise FileNotFoundError(f"Directory not found: {raw_path}")

    csv_files = {}
    for csv_path in raw_path.glob("*.csv"):
        table_name = csv_path.stem
        csv_files[table_name] = csv_path
        logger.debug("Found CSV: %s → %s", table_name, csv_path)

    if not csv_files:
        logger.warning("No CSV files found in %s", raw_path)
    else:
        logger.info(
            "Discovered %d CSV file(s): %s",
            len(csv_files), ", ".join(csv_files.keys()),
        )

    return csv_files


def _load_csv_files(csv_files: Dict[str, Path]) -> Dict[str, pd.DataFrame]:
    """
    Load all discovered CSV files into DataFrames.

    Parameters
    ----------
    csv_files : Dict[str, Path]
        Mapping of table names to file paths.

    Returns
    -------
    Dict[str, pd.DataFrame]
        Dictionary mapping table names to loaded DataFrames.
    """
    logger.info("Loading %d CSV file(s)", len(csv_files))
    tables = {}

    for table_name, csv_path in csv_files.items():
        try:
            df = pd.read_csv(csv_path)
            tables[table_name] = df
            logger.info("Loaded %s: shape %s", table_name, df.shape)
        except Exception as exc:
            logger.error("Failed to load %s from %s: %s", table_name, csv_path, exc)
            raise

    logger.info("Successfully loaded %d table(s)", len(tables))
    return tables


def _save_processed_data(
    processed_results: Dict[str, Dict[str, pd.DataFrame]],
    raw_dir: Optional[Path] = None,
    processed_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Path]]:
    """
    Save processed DataFrames (wide and long formats) to the processed directory.

    meta.csv is copied as-is without transformation.

    Parameters
    ----------
    processed_results : Dict[str, Dict[str, pd.DataFrame]]
        Output from preprocess_all().
    raw_dir : Path, optional
        Source directory for meta.csv copy.
        Falls back to DATA_RAW_DIR from constants when omitted.
    processed_dir : Path, optional
        Destination directory for saved files.
        Falls back to DATA_PROCESSED_DIR from constants when omitted.

    Returns
    -------
    Dict[str, Dict[str, Path]]
        Mapping of table names to saved file paths.
    """
    raw_path  = _resolve_raw_dir(raw_dir)
    proc_path = _resolve_processed_dir(processed_dir)

    logger.debug("Saving processed data to %s", proc_path)
    proc_path.mkdir(parents=True, exist_ok=True)

    saved_paths: Dict[str, Dict[str, Path]] = {}

    for table_name, formats in processed_results.items():
        logger.debug("Saving processed data for table: %s", table_name)

        # meta.csv — copy as-is, no transformation
        if table_name == "meta":
            from shutil import copy2
            src = raw_path / "meta.csv"
            dst = proc_path / "meta.csv"
            copy2(src, dst)
            logger.info("Copied (not processed): meta → %s", dst)
            saved_paths[table_name] = {"copy": dst}
            continue

        wide_path = proc_path / f"{table_name}_wide.csv"
        formats["wide"].to_csv(wide_path)
        logger.info("Saved wide format: %s → %s", table_name, wide_path)

        long_path = proc_path / f"{table_name}_long.csv"
        formats["long"].to_csv(long_path, index=False)
        logger.info("Saved long format: %s → %s", table_name, long_path)

        saved_paths[table_name] = {"wide": wide_path, "long": long_path}

    logger.info("Saved %d table(s) to %s", len(saved_paths), proc_path)
    return saved_paths


# ─────────────────────────────────────────────────────────────────
# Main pipeline entry point
# ─────────────────────────────────────────────────────────────────

def process_raw_data_pipeline(
    raw_dir: Optional[Path] = None,
    processed_dir: Optional[Path] = None,
    scale_to: str = "auto",
    exclude_from_scaling: Optional[List[str]] = None,
    fillna_value: float = 0.0,
) -> Dict[str, Dict[str, Path]]:
    """
    Main automation pipeline: discover CSVs, process, save results.

    Accepts optional path overrides so the pipeline runner can pass
    explicit directories without monkey-patching module globals.
    Falls back to DATA_RAW_DIR / DATA_PROCESSED_DIR from constants
    when paths are omitted — fully backwards compatible.

    Parameters
    ----------
    raw_dir : Path, optional
        Override for the raw CSV source directory.
        Default: DATA_RAW_DIR from constants.
    processed_dir : Path, optional
        Override for the processed output directory.
        Default: DATA_PROCESSED_DIR from constants.
    scale_to : str, default 'auto'
        Scaling mode: 'auto', 'crore', or 'none'.
    exclude_from_scaling : List[str], optional
        Metrics to exclude from scaling.
    fillna_value : float, default 0.0
        NaN fill value.

    Returns
    -------
    Dict[str, Dict[str, Path]]
        Mapping of table names to saved file paths.

    Raises
    ------
    FileNotFoundError
        If raw_dir doesn't exist or has no CSV files.
    """
    raw_path  = _resolve_raw_dir(raw_dir)
    proc_path = _resolve_processed_dir(processed_dir)

    logger.info("=" * 70)
    logger.info("STARTING RAW DATA PROCESSING PIPELINE")
    logger.info("  raw_dir       : %s", raw_path)
    logger.info("  processed_dir : %s", proc_path)
    logger.info("=" * 70)

    try:
        csv_files = _discover_csv_files(raw_path)

        if not csv_files:
            logger.warning("No CSV files found to process")
            return {}

        tables = _load_csv_files(csv_files)

        logger.info("Starting preprocessing with scale_to='%s'", scale_to)
        processed_results = preprocess_all(
            tables=tables,
            scale_to=scale_to,
            exclude_from_scaling=exclude_from_scaling,
            fillna_value=fillna_value,
        )

        saved_paths = _save_processed_data(
            processed_results,
            raw_dir=raw_path,
            processed_dir=proc_path,
        )

        logger.info("=" * 70)
        logger.info("RAW DATA PROCESSING PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("  Processed %d table(s)", len(saved_paths))
        logger.info("  Output : %s", proc_path)
        logger.info("=" * 70)

        return saved_paths

    except Exception:
        logger.error("=" * 70)
        logger.error("RAW DATA PROCESSING PIPELINE FAILED", exc_info=True)
        logger.error("=" * 70)
        raise


if __name__ == "__main__":
    logger.info("Running preprocessor pipeline from command line")
    try:
        saved = process_raw_data_pipeline(
            scale_to="auto",
            exclude_from_scaling=["no_of_equity_shares", "face_value"],
        )
        logger.info("Pipeline completed. Saved %d tables.", len(saved))
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc)
        raise SystemExit(1)