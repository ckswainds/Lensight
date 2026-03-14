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

# File handler: logs to file
log_file = LOGS_DIR / "preprocessor.log"
file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

# Console handler: logs to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers
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
    except:
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
        
    Raises
    ------
    ValueError
        If input DataFrame is empty.
    
    Notes
    -----
    - Wide format: metrics as rows, dates as columns
    - Long format: one row per metric-date combination
    - Logs detailed processing steps to logs/preprocessor.log
    """
    logger.debug(f"Starting preprocessing for table: {table_name}")

    df = df.replace("", np.nan)

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "metric"})

    df.columns = [_normalize_colname(c) for c in df.columns]
    logger.debug(f"Normalized {len(df.columns)} column names")

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

    logger.debug(f"Identified {len(date_cols)} date columns and {len(non_date_cols)} non-date columns")

    date_map = {}

    for col in date_cols:

        parsed = _parse_date_col(col)

        if parsed is not None:
            date_map[col] = parsed.strftime("%Y-%m-%d")
        else:
            date_map[col] = col

    cleaned_rows = []

    for _, row in df.iterrows():

        metric = row["metric"]
        metric_orig = row["metric_orig"]

        numeric_values = {}

        for col in date_cols:
            numeric_values[col] = _to_numeric_val(row.get(col))

        for col in non_date_cols:

            if col in ("metric", "metric_orig"):
                continue

            numeric_values[col] = _to_numeric_val(row.get(col), preserve_on_fail=True)

        record = {
            "metric": metric,
            "metric_orig": metric_orig,
        }

        record.update(numeric_values)

        cleaned_rows.append(record)

    wide = pd.DataFrame(cleaned_rows)
    logger.debug(f"Converted {len(wide)} rows to wide format")

    wide = wide.drop_duplicates(subset="metric", keep="first")
    logger.debug(f"Removed duplicates, {len(wide)} unique metrics remaining")

    wide = wide.set_index("metric")

    wide = wide.rename(columns=date_map)

    unit_map = {}

    def should_exclude(metric):

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

            if should_exclude(metric):

                unit_map[metric] = ""
                continue

            values = wide.loc[metric].drop(["metric_orig"]).values

            values = values[~pd.isna(values)]

            if len(values) == 0:
                unit_map[metric] = ""
                continue

            # Filter to only numeric values (skip strings)
            numeric_values = []
            for v in values:
                try:
                    numeric_values.append(float(v))
                except (ValueError, TypeError):
                    pass
            
            if len(numeric_values) == 0:
                unit_map[metric] = ""
                continue

            median = np.median(np.abs(numeric_values))

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
    logger.debug(f"Filled {fillna_value} for NaN values in {len(numeric_cols)} numeric columns")

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
                date = col
                label = col.strftime("%Y-%m-%d")
            else:
                date = _parse_date_col(col)
                label = str(col)

            rows.append(
                {
                    "metric": metric,
                    "metric_display": row["metric_display"],
                    "date": date,
                    "period_label": label,
                    "value": float(value),
                    "unit": unit_map.get(metric, ""),
                    "source_table": table_name,
                }
            )

    long_df = pd.DataFrame(rows)
    logger.debug(f"Created long format DataFrame with {len(long_df)} rows")
    logger.info(f"Preprocessing complete for table '{table_name}': {len(wide)} metrics × {len(date_cols)} periods")

    return {"wide": wide, "long": long_df}


def preprocess_all(
    tables: Dict[str, pd.DataFrame],
    scale_to: str = "auto",
    exclude_from_scaling: Optional[List[str]] = None,
    fillna_value: float = 0.0,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Preprocess multiple financial tables at once.
    
    Applies preprocess_table to each table and returns results dictionary.
    
    Parameters
    ----------
    tables : Dict[str, pd.DataFrame]
        Dictionary mapping table names to DataFrames (e.g., 
        {"pnl": pnl_df, "balance_sheet": bs_df}).
    scale_to : str, default 'auto'
        Scaling mode: 'auto' (detect crores), 'crore', or 'none'.
    exclude_from_scaling : List[str], optional
        Metric names to exclude from scaling.
    fillna_value : float, default 0.0
        Value to fill NaN entries.
    
    Returns
    -------
    Dict[str, Dict[str, pd.DataFrame]]
        Nested dict: {table_name: {'wide': wide_df, 'long': long_df}}
    
    Notes
    -----
    Logs each table's processing status and final summary.
    """
    logger.info(f"Starting batch processing of {len(tables)} tables")

    results = {}

    for name, df in tables.items():
        logger.debug(f"Processing table: {name}")
        results[name] = preprocess_table(
            df=df,
            table_name=name,
            scale_to=scale_to,
            exclude_from_scaling=exclude_from_scaling,
            fillna_value=fillna_value,
        )

    logger.info(f"Batch processing complete: {len(results)} tables processed")
    return results


# ─────────────────────────────────────────────────────────────────
# Automatic CSV Discovery and Processing
# ─────────────────────────────────────────────────────────────────

def _discover_csv_files() -> Dict[str, Path]:
    """
    Discover all CSV files in the data/raw/ directory.
    
    Returns
    -------
    Dict[str, Path]
        Dictionary mapping table names (without .csv) to file paths.
        
    Raises
    ------
    FileNotFoundError
        If data/raw/ directory does not exist.
    
    Notes
    -----
    Logs the number of CSV files discovered.
    """
    logger.debug(f"Discovering CSV files in {DATA_RAW_DIR}")
    
    if not DATA_RAW_DIR.exists():
        logger.error(f"Raw data directory does not exist: {DATA_RAW_DIR}")
        raise FileNotFoundError(f"Directory not found: {DATA_RAW_DIR}")
    
    csv_files = {}
    for csv_path in DATA_RAW_DIR.glob("*.csv"):
        table_name = csv_path.stem
        csv_files[table_name] = csv_path
        logger.debug(f"Found CSV: {table_name} → {csv_path}")
    
    if not csv_files:
        logger.warning(f"No CSV files found in {DATA_RAW_DIR}")
    else:
        logger.info(f"Discovered {len(csv_files)} CSV file(s): {', '.join(csv_files.keys())}")
    
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
    
    Notes
    -----
    Logs loading status and data shape for each file.
    Raises FileNotFoundError if any file cannot be read.
    """
    logger.info(f"Loading {len(csv_files)} CSV file(s)")
    
    tables = {}
    for table_name, csv_path in csv_files.items():
        try:
            df = pd.read_csv(csv_path)
            tables[table_name] = df
            logger.info(f"Loaded {table_name}: shape {df.shape}")
        except Exception as e:
            logger.error(f"Failed to load {table_name} from {csv_path}: {e}")
            raise
    
    logger.info(f"Successfully loaded {len(tables)} table(s)")
    return tables


def _save_processed_data(
    processed_results: Dict[str, Dict[str, pd.DataFrame]],
) -> Dict[str, Dict[str, Path]]:
    """
    Save processed DataFrames (wide and long formats) to data/processed/ folder.
    
    Special case: meta.csv is copied as-is without processing.
    
    Parameters
    ----------
    processed_results : Dict[str, Dict[str, pd.DataFrame]]
        Output from preprocess_all(): {table_name: {'wide': df, 'long': df}}
    
    Returns
    -------
    Dict[str, Dict[str, Path]]
        Dictionary mapping table names to saved file paths:
        {table_name: {'wide': path, 'long': path}} or {table_name: {'copy': path}} for meta
    
    Notes
    -----
    Creates data/processed/ directory if it doesn't exist.
    Logs save status for each file.
    meta.csv is copied from raw without processing.
    """
    logger.debug(f"Preparing to save processed data to {DATA_PROCESSED_DIR}")
    
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Ensured {DATA_PROCESSED_DIR} exists")
    
    saved_paths = {}
    
    for table_name, formats in processed_results.items():
        logger.debug(f"Saving processed data for table: {table_name}")
        
        # Special case: copy meta.csv as-is
        if table_name == "meta":
            from shutil import copy2
            src = DATA_RAW_DIR / "meta.csv"
            dst = DATA_PROCESSED_DIR / "meta.csv"
            copy2(src, dst)
            logger.info(f"Copied (not processed): meta → {dst}")
            saved_paths[table_name] = {"copy": dst}
            continue
        
        # Save wide format
        wide_path = DATA_PROCESSED_DIR / f"{table_name}_wide.csv"
        formats["wide"].to_csv(wide_path)
        logger.info(f"Saved wide format: {table_name} → {wide_path}")
        
        # Save long format
        long_path = DATA_PROCESSED_DIR / f"{table_name}_long.csv"
        formats["long"].to_csv(long_path, index=False)
        logger.info(f"Saved long format: {table_name} → {long_path}")
        
        saved_paths[table_name] = {
            "wide": wide_path,
            "long": long_path,
        }
    
    logger.info(f"Saved {len(saved_paths)} table(s) to {DATA_PROCESSED_DIR}")
    return saved_paths


def process_raw_data_pipeline(
    scale_to: str = "auto",
    exclude_from_scaling: Optional[List[str]] = None,
    fillna_value: float = 0.0,
) -> Dict[str, Dict[str, Path]]:
    """
    Main automation pipeline: discover CSVs from data/raw/, process, save to data/processed/.
    
    Orchestrates the entire pipeline:
    1. Discover CSV files in data/raw/
    2. Load CSVs into DataFrames
    3. Process using preprocess_all()
    4. Save wide and long formats to data/processed/
    
    Parameters
    ----------
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
        If data/raw/ doesn't exist or has no CSV files.
    
    Notes
    -----
    Logs all major steps and summary at the end.
    All logs are saved to logs/preprocessor.log.
    """
    logger.info("="*70)
    logger.info("STARTING RAW DATA PROCESSING PIPELINE")
    logger.info("="*70)
    
    try:
        # Step 1: Discover CSV files
        csv_files = _discover_csv_files()
        
        if not csv_files:
            logger.warning("No CSV files found to process")
            return {}
        
        # Step 2: Load CSV files
        tables = _load_csv_files(csv_files)
        
        # Step 3: Process tables
        logger.info(f"Starting preprocessing with scale_to='{scale_to}'")
        processed_results = preprocess_all(
            tables=tables,
            scale_to=scale_to,
            exclude_from_scaling=exclude_from_scaling,
            fillna_value=fillna_value,
        )
        
        # Step 4: Save processed data
        saved_paths = _save_processed_data(processed_results)
        
        logger.info("="*70)
        logger.info("RAW DATA PROCESSING PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("="*70)
        logger.info(f"Processed {len(saved_paths)} table(s)")
        logger.info(f"Output saved to: {DATA_PROCESSED_DIR}")
        
        return saved_paths
    
    except Exception as e:
        logger.error("="*70)
        logger.error("RAW DATA PROCESSING PIPELINE FAILED", exc_info=True)
        logger.error("="*70)
        raise


if __name__ == "__main__":
    """
    Entry point: run the pipeline when module is executed directly.
    Example: python -m ingestion.preprocessor
    """
    logger.info("Running preprocessor pipeline from command line")
    try:
        saved = process_raw_data_pipeline(
            scale_to="auto",
            exclude_from_scaling=["no_of_equity_shares", "face_value"]
        )
        logger.info(f"Pipeline completed. Saved {len(saved)} tables.")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        exit(1)