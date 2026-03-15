"""
analysis/ratio_engine.py
-------------------------
Computes fundamental financial ratios from processed wide-format CSVs
and persists the results as data/processed/ratios.json.

Robustness guarantees
---------------------
- Period columns are detected by parsing column headers as dates, not
  by exclusion of a hardcoded set. Any date-parseable column is treated
  as a period; anything else is metadata. This means adding or removing
  years in the source data requires zero code changes.

- CAGR windows are not hardcoded. The engine computes CAGR for every
  window in CAGR_WINDOWS (configurable) and silently skips any window
  that exceeds the number of available periods — no crash, no None spam.

- Meta key resolution for adj_shares and hist_price uses a fuzzy lookup
  that scans all meta index keys matching the period date, rather than
  constructing a key string and hoping it matches exactly. Survives
  preprocessor naming convention changes.

- All arithmetic goes through _div() / _pct() which handle None, zero,
  NaN and Inf defensively. No computation path can raise ZeroDivisionError
  or propagate a NaN into the output.

- Missing metrics (e.g. a company without Dividend data) are handled
  gracefully — _series() returns a dict of all-None for absent metrics
  and logs a debug warning rather than raising.

- The engine reports a data quality summary at the end — which metrics
  were fully populated, partially populated, or fully missing — so
  downstream consumers know what to trust.

Input files (data/processed/)
------------------------------
  pnl_wide.csv            annual P&L  (metric x period)
  balance_sheet_wide.csv  annual BS   (metric x period)
  cash_flow_wide.csv      annual CF   (metric x period)
  quarters_wide.csv       quarterly   (metric x period)
  meta.csv                scalar meta (field, value) — two-column format

  meta.csv format:
    field,value
    company_name,BHARAT ELECTRONICS LTD
    face_value,1.0
    current_price_inr,453.55
    market_cap_cr,331571.53
    hist_price_Mar-2016,37.1
    adj_equity_shares_cr_Mar-2016,792.0
    ...

Output (data/processed/ratios.json)
-------------------------------------
{
  "company":       "BHARAT ELECTRONICS LTD",
  "generated_at":  "2025-03-14T10:30:00",
  "period_count":  10,
  "periods":       ["2016-03-31", ..., "2025-03-31"],
  "profitability": { "net_profit_margin": {"2016-03-31": 18.2, ...}, ... },
  "valuation":     { ... },
  "leverage":      { ... },
  "liquidity":     { ... },
  "efficiency":    { ... },
  "growth":        { "sales_cagr_3y": 15.6, ... },
  "per_share":     { ... },
  "data_quality":  { "fully_populated": [...], "partial": [...], "missing": [...] }
}
"""

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from constants import DATA_PROCESSED_DIR, LOGS_DIR


# ─────────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file = LOGS_DIR / "ratio_engine.log"
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CAGR_WINDOWS: list[int] = [3, 5, 7, 10]
ROUND_DP: int = 2
_PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class RatioEngineError(Exception):
    """Raised when ratio computation cannot proceed due to bad input."""


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class RatioResult:
    """
    Complete ratio output for one company.

    Attributes
    ----------
    company : str
        Company name from meta.csv, or 'UNKNOWN' if unavailable.
    generated_at : str
        ISO-8601 timestamp of computation.
    period_count : int
        Number of annual periods found in the source data.
    periods : list[str]
        Sorted list of annual period date strings (YYYY-MM-DD).
    profitability / valuation / leverage / liquidity / efficiency : dict
        {ratio_name: {period: value | None}}
    growth : dict
        {cagr_label: value | None}  scalar, not period-keyed.
    per_share : dict
        {metric_name: {period: value | None}}
    data_quality : dict
        Summary of which ratio outputs are fully populated,
        partially populated, or fully missing.
    """
    company:       str
    generated_at:  str
    period_count:  int
    periods:       list[str]
    profitability: dict[str, dict[str, float | None]] = field(default_factory=dict)
    valuation:     dict[str, dict[str, float | None]] = field(default_factory=dict)
    leverage:      dict[str, dict[str, float | None]] = field(default_factory=dict)
    liquidity:     dict[str, dict[str, float | None]] = field(default_factory=dict)
    efficiency:    dict[str, dict[str, float | None]] = field(default_factory=dict)
    growth:        dict[str, float | None]             = field(default_factory=dict)
    per_share:     dict[str, dict[str, float | None]] = field(default_factory=dict)
    data_quality:  dict[str, list[str]]                = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company":       self.company,
            "generated_at":  self.generated_at,
            "period_count":  self.period_count,
            "periods":       self.periods,
            "profitability": self.profitability,
            "valuation":     self.valuation,
            "leverage":      self.leverage,
            "liquidity":     self.liquidity,
            "efficiency":    self.efficiency,
            "growth":        self.growth,
            "per_share":     self.per_share,
            "data_quality":  self.data_quality,
        }


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class RatioEngine:
    """
    Loads processed wide CSVs, computes all financial ratios,
    and writes ratios.json.

    Parameters
    ----------
    processed_dir : path-like, optional
        Directory containing wide CSVs and where ratios.json is written.
        Defaults to DATA_PROCESSED_DIR from constants.
    cagr_windows : list[int], optional
        CAGR year windows to compute. Defaults to module-level CAGR_WINDOWS.
        Any window larger than available periods is silently skipped.

    Example
    -------
    >>> engine = RatioEngine("data/processed")
    >>> result = engine.compute_all()
    >>> print(result.profitability["roe"])
    {'2016-03-31': 14.85, '2017-03-31': 18.32, ...}
    """

    _PNL_FILE  = "pnl_wide.csv"
    _BS_FILE   = "balance_sheet_wide.csv"
    _CF_FILE   = "cash_flow_wide.csv"
    _QT_FILE   = "quarters_wide.csv"
    _META_FILE = "meta.csv"           # two-column format: field, value
    _OUT_FILE  = "ratios.json"

    def __init__(
        self,
        processed_dir: str | Path | None = None,
        cagr_windows: list[int] | None = None,
    ) -> None:
        self._dir          = Path(processed_dir) if processed_dir else DATA_PROCESSED_DIR
        self._cagr_windows = sorted(cagr_windows or CAGR_WINDOWS)
        self._pnl:  pd.DataFrame = pd.DataFrame()
        self._bs:   pd.DataFrame = pd.DataFrame()
        self._cf:   pd.DataFrame = pd.DataFrame()
        self._qt:   pd.DataFrame = pd.DataFrame()
        self._meta: pd.DataFrame = pd.DataFrame()
        self._periods:    list[str]      = []
        self._meta_index: dict[str, str] = {}  # normalised_key → raw_key

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute_all(self) -> RatioResult:
        """
        Run the full ratio pipeline.

        Returns
        -------
        RatioResult
            Populated dataclass. Also written to ratios.json.

        Raises
        ------
        RatioEngineError
            If required files are missing or cannot be parsed.
        """
        logger.info("Starting ratio computation — dir: '%s'", self._dir)

        self._load_data()

        if not self._periods:
            raise RatioEngineError(
                "No financial periods found in PNL wide CSV. "
                "Ensure the preprocessor has produced valid output."
            )

        company = self._resolve_company_name()
        logger.info(
            "Company: %s | Periods: %d (%s to %s) | CAGR windows: %s",
            company,
            len(self._periods),
            self._periods[0],
            self._periods[-1],
            self._cagr_windows,
        )

        # Compute TTM from quarterly data
        self._ttm_period, self._ttm_pnl = self._compute_ttm()

        # Only use TTM if it goes beyond the latest annual period
        if self._ttm_period and self._ttm_period > self._periods[-1]:
            display_periods = self._periods + [self._ttm_period]
            logger.info(
                "TTM period '%s' extends beyond latest annual '%s' — appended.",
                self._ttm_period, self._periods[-1],
            )
        else:
            self._ttm_period = None
            display_periods  = self._periods

        result = RatioResult(
            company=company,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            period_count=len(display_periods),
            periods=display_periods,
        )

        result.profitability = self._profitability()
        result.valuation     = self._valuation()
        result.leverage      = self._leverage()
        result.liquidity     = self._liquidity()
        result.efficiency    = self._efficiency()
        result.growth        = self._growth()
        result.per_share     = self._per_share()
        result.data_quality  = self._data_quality(result)

        self._write_json(result)

        logger.info(
            "Ratio computation complete — %d periods | %d fully populated | "
            "%d partial | %d missing",
            len(self._periods),
            len(result.data_quality.get("fully_populated", [])),
            len(result.data_quality.get("partial", [])),
            len(result.data_quality.get("missing", [])),
        )
        return result

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        """Load and normalise all five CSVs."""
        self._pnl  = self._read_wide(self._PNL_FILE)
        self._bs   = self._read_wide(self._BS_FILE)
        self._cf   = self._read_wide(self._CF_FILE)
        self._qt   = self._read_wide(self._QT_FILE)
        self._meta = self._read_meta(self._META_FILE)

        self._periods    = self._detect_periods(self._pnl)
        self._meta_index = self._build_meta_index()

        # Detect sector and fix unit mismatches before any ratio computation
        self._is_bank = self._is_financial_company()
        if self._is_bank:
            self._fix_bank_unit_mismatch()

        logger.debug(
            "Detected %d annual periods: %s | is_bank: %s",
            len(self._periods), self._periods, self._is_bank,
        )

    def _fix_bank_unit_mismatch(self) -> None:
        """
        Selectively correct BS rows that were over-scaled by the preprocessor.

        Problem:
          Screener.in exports all values in crores.
          The preprocessor auto-scales any metric whose median > 1e6 by /1e7.
          For large banks: certain BS line items (borrowings, total, etc.) have
          values like 1,400,000 crores → median = 1,400,000 > 1e6 → ÷1e7 → 0.14.
          P&L values (net_profit ~18,000 Cr) have median < 1e6 → unchanged.
          Result: ROA = 18,000 / 0.14 * 100 = 12,857,142% (nonsense).

          But NOT all BS rows are mis-scaled: equity_share_capital (5,807 Cr),
          reserves (82,000 Cr) are fine — only the very large rows were affected.

        Fix:
          For each BS row, check if median of period values < 5.0.
          Values representing crores should always be > 5 (at least 5 crores).
          If median < 5.0 the row was over-divided — multiply back by 1e7.
          Exclude: no_of_equity_shares, face_value, new_bonus_shares (counts).
        """
        try:
            periods = self._detect_periods(self._bs)
            if not periods:
                return

            # Metrics that are counts/ratios — don't apply unit correction
            skip_metrics = {
                "no_of_equity_shares", "new_bonus_shares",
                "face_value", "dividend_payout",
            }

            corrected = []
            for metric in self._bs.index:
                if metric in skip_metrics:
                    continue
                vals = [
                    self._get(self._bs, metric, p)
                    for p in periods
                ]
                non_null = [v for v in vals if v is not None]
                if not non_null:
                    continue

                import statistics
                try:
                    med = statistics.median(non_null)
                except Exception:
                    continue

                # If median is suspiciously small (< 5 Cr) for a financial metric,
                # it was over-scaled by the preprocessor
                if 0 < abs(med) < 5.0:
                    self._bs.loc[metric, periods] = (
                        self._bs.loc[metric, periods] * 1e7
                    )
                    corrected.append(metric)

            if corrected:
                logger.warning(
                    "Bank BS unit correction applied to %d metric(s): %s",
                    len(corrected), corrected,
                )
            else:
                logger.debug("No BS unit correction needed.")

        except Exception as exc:
            logger.warning("Could not apply BS unit correction: %s", exc)

    def _read_wide(self, filename: str) -> pd.DataFrame:
        """
        Load a wide CSV indexed on 'metric'.

        Period column headers are normalised to "YYYY-MM-DD" regardless of
        whether they arrive as "2025-03-31", "2025-03-31 00:00:00", or
        "2025-03-31T00:00:00". Non-date columns are left unchanged.
        """
        path = self._dir / filename
        if not path.exists():
            raise RatioEngineError(
                f"Required file not found: '{path}'. "
                "Run the preprocessor before the ratio engine."
            )
        try:
            df = pd.read_csv(path, index_col="metric")
        except Exception as exc:
            raise RatioEngineError(f"Cannot read '{filename}': {exc}") from exc

        df.columns = [
            col[:10] if _PERIOD_PATTERN.match(str(col)) else col
            for col in df.columns
        ]
        return df

    def _read_meta(self, filename: str) -> pd.DataFrame:
        """
        Load meta.csv and index it on the correct identifier column.

        Supports two formats produced by the preprocessor:

        Format A — new (field, value):
            field,value
            company_name,BHARAT ELECTRONICS LTD
            hist_price_Mar-2016,37.1
            adj_equity_shares_cr_Mar-2016,792.0

        Format B — legacy (metric, metric_orig, value, metric_display):
            metric,metric_orig,value,metric_display
            company_name,company_name,BHARAT ELECTRONICS LTD,...

        The engine auto-detects the format by checking which identifier
        column is present: 'field' takes priority, then 'metric'.
        This means the engine works with both old and new preprocessor
        output without any manual config change.
        """
        path = self._dir / filename
        if not path.exists():
            raise RatioEngineError(f"Meta file not found: '{path}'.")
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            raise RatioEngineError(f"Cannot read '{filename}': {exc}") from exc

        # Auto-detect index column: 'field' (new format) or 'metric' (legacy)
        if "field" in raw.columns:
            index_col = "field"
        elif "metric" in raw.columns:
            index_col = "metric"
        else:
            raise RatioEngineError(
                f"meta.csv must have a 'field' or 'metric' column. "
                f"Found: {list(raw.columns)}"
            )

        logger.debug("meta.csv — index column: '%s'", index_col)
        return raw.set_index(index_col)

    @staticmethod
    def _detect_periods(df: pd.DataFrame) -> list[str]:
        """
        Return sorted list of column headers that parse as dates.
        Robust to any number of years — discovers periods at runtime.
        """
        periods = []
        for col in df.columns:
            col_str = str(col)
            if _PERIOD_PATTERN.match(col_str):
                try:
                    datetime.strptime(col_str[:10], "%Y-%m-%d")
                    periods.append(col_str[:10])
                except ValueError:
                    pass
        return sorted(periods)

    def _build_meta_index(self) -> dict[str, str]:
        """
        Build a normalised_key -> raw_key mapping for all meta index entries.

        Normalisation: lowercase + replace non-alphanumeric with underscore.
        Examples:
          "hist_price_Mar-2016"           -> "hist_price_mar_2016"
          "adj_equity_shares_cr_Mar-2016" -> "adj_equity_shares_cr_mar_2016"
          "company_name"                  -> "company_name"  (unchanged)

        This decouples the engine from exact meta key casing or separators.
        """
        index: dict[str, str] = {}
        for raw_key in self._meta.index:
            normalised = re.sub(r"[^a-z0-9]", "_", str(raw_key).lower())
            index[normalised] = raw_key
        return index

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    def _get(self, df: pd.DataFrame, metric: str, period: str) -> float | None:
        """
        Safely retrieve one cell from a wide DataFrame.
        Returns None for missing metric, missing period, NaN, or non-numeric.
        """
        try:
            val = df.loc[metric, period]
            if pd.isna(val):
                return None
            return float(val)
        except (KeyError, TypeError, ValueError):
            return None

    def _series(self, df: pd.DataFrame, metric: str) -> dict[str, float | None]:
        """
        Return {period: value} for all detected periods for one metric.
        Logs a debug warning if the metric row is absent from the DataFrame.
        """
        if metric not in df.index:
            logger.debug(
                "Metric '%s' not found in DataFrame — all-None series returned.",
                metric,
            )
        return {p: self._get(df, metric, p) for p in self._periods}

    def _resolve_meta_key(self, field_name: str) -> str | None:
        """
        Resolve a logical field name to its raw meta index key.

        Strategy:
          1. Exact match against meta index (fastest path)
          2. Normalised match via _meta_index dict

        Returns None if neither match — never raises.
        """
        if field_name in self._meta.index:
            return field_name
        normalised = re.sub(r"[^a-z0-9]", "_", field_name.lower())
        return self._meta_index.get(normalised)

    def _meta_scalar(self, field_name: str) -> str | None:
        """Return a string value from meta by exact or normalised key."""
        raw_key = self._resolve_meta_key(field_name)
        if raw_key is None:
            return None
        try:
            val = self._meta.loc[raw_key, "value"]
            return str(val) if not pd.isna(val) else None
        except (KeyError, TypeError):
            return None

    def _meta_float(self, field_name: str) -> float | None:
        """Return a float value from meta by exact or normalised key."""
        raw_key = self._resolve_meta_key(field_name)
        if raw_key is None:
            return None
        try:
            val = self._meta.loc[raw_key, "value"]
            return float(val) if not pd.isna(val) else None
        except (KeyError, TypeError, ValueError):
            return None

    def _adj_shares(self, period: str) -> float | None:
        """
        Return adjusted equity shares (in crores) for a given period.

        Constructs a normalised candidate key from the period date then
        resolves it against the meta index — resilient to casing and
        separator changes in the preprocessor output.

        Example: "2025-03-31"
          candidate key  -> "adj_equity_shares_cr_mar_2025"
          resolves to    -> "adj_equity_shares_cr_Mar-2025"  (raw meta key)
        """
        try:
            dt  = datetime.strptime(period[:10], "%Y-%m-%d")
            key = f"adj_equity_shares_cr_{dt.strftime('%b_%Y').lower()}"
            val = self._meta_float(key)
            if val is None:
                logger.debug(
                    "adj_shares not found for period %s (candidate: '%s')", period, key
                )
            return val
        except (ValueError, TypeError):
            return None

    def _hist_price(self, period: str) -> float | None:
        """
        Return historical share price for a given period.

        Example: "2025-03-31"
          candidate key  -> "hist_price_mar_2025"
          resolves to    -> "hist_price_Mar-2025"  (raw meta key)
        """
        try:
            dt  = datetime.strptime(period[:10], "%Y-%m-%d")
            key = f"hist_price_{dt.strftime('%b_%Y').lower()}"
            val = self._meta_float(key)
            if val is None:
                logger.debug(
                    "hist_price not found for period %s (candidate: '%s')", period, key
                )
            return val
        except (ValueError, TypeError):
            return None

    def _resolve_company_name(self) -> str:
        """
        Extract company name from meta with fallback to 'UNKNOWN'.
        Guards against numeric coercion artifacts (e.g. value '0.0').
        """
        name = self._meta_scalar("company_name")
        if not name or name.replace(".", "").replace("0", "").strip() == "":
            logger.warning(
                "Company name absent or corrupted in meta — defaulting to UNKNOWN."
            )
            return "UNKNOWN"
        return name.strip()

    # ------------------------------------------------------------------
    # Safe arithmetic
    # ------------------------------------------------------------------

    @staticmethod
    def _div(n: float | None, d: float | None) -> float | None:
        """Safe division — returns None on None input or zero/inf denominator."""
        if n is None or d is None:
            return None
        if abs(d) < 1e-9:
            return None
        result = n / d
        return None if (math.isnan(result) or math.isinf(result)) else result

    @staticmethod
    def _pct(n: float | None, d: float | None) -> float | None:
        """Safe percentage = (n / d) x 100."""
        r = RatioEngine._div(n, d)
        return None if r is None else r * 100

    @staticmethod
    def _add(
        a: float | None,
        b: float | None,
        require_both: bool = False,
    ) -> float | None:
        """
        Safe addition.
        require_both=True  -> returns None unless both operands are non-None.
        require_both=False -> treats None as 0 when the other operand exists.
        """
        if require_both:
            return None if (a is None or b is None) else a + b
        if a is None and b is None:
            return None
        return (a or 0.0) + (b or 0.0)

    @staticmethod
    def _sub(a: float | None, b: float | None) -> float | None:
        """Safe subtraction. Returns None if a is None."""
        if a is None:
            return None
        return a - (b or 0.0)

    @staticmethod
    def _r(value: float | None) -> float | None:
        """Round to ROUND_DP decimal places. Returns None for non-finite."""
        if value is None or not math.isfinite(value):
            return None
        return round(value, ROUND_DP)

    def _period_ratio(
        self,
        numerators:   dict[str, float | None],
        denominators: dict[str, float | None],
        pct: bool = False,
    ) -> dict[str, float | None]:
        """Compute a ratio across all periods from two period-keyed dicts."""
        out = {}
        for p in self._periods:
            n, d = numerators.get(p), denominators.get(p)
            out[p] = self._r(self._pct(n, d) if pct else self._div(n, d))
        return out

    # ------------------------------------------------------------------
    # Derived intermediate series
    # ------------------------------------------------------------------

    def _equity(self) -> dict[str, float | None]:
        """Equity = Share Capital + Reserves."""
        cap = self._series(self._bs, "equity_share_capital")
        res = self._series(self._bs, "reserves")
        return {p: self._r(self._add(cap[p], res[p])) for p in self._periods}

    def _ebit(self) -> dict[str, float | None]:
        """EBIT = Profit Before Tax + Interest."""
        pbt  = self._series(self._pnl, "profit_before_tax")
        intr = self._series(self._pnl, "interest")
        return {p: self._r(self._add(pbt[p], intr[p])) for p in self._periods}

    def _ebitda(self) -> dict[str, float | None]:
        """EBITDA = EBIT + Depreciation."""
        ebit = self._ebit()
        dep  = self._series(self._pnl, "depreciation")
        return {p: self._r(self._add(ebit[p], dep[p])) for p in self._periods}

    def _is_financial_company(self) -> bool:
        """
        Detect if this is a bank / NBFC / financial company.

        Heuristic: average (other_liabilities / total_assets) > 0.65

        Why NOT D/E ratio:
          On Screener.in, banks report "Borrowings" as interbank/bond
          borrowings only. Customer deposits sit in "Other Liabilities".
          So Bank of Baroda shows D/E ~1.9x — below any reasonable
          threshold — while BEL shows D/E ~0.004x.
          The real signal is that Other Liabilities dominate total assets.

        Calibration:
          BEL  : other_liab/total ≈ 0.51  → not a bank ✓
          BOB  : other_liab/total ≈ 0.82  → bank ✓
          HDFC : other_liab/total ≈ 0.88  → bank ✓
          NBFC : other_liab/total ≈ 0.70  → financial ✓
        """
        other_liab = self._series(self._bs, "other_liabilities")
        total      = self._series(self._bs, "total")

        ratios = []
        for p in self._periods:
            ol = other_liab.get(p)
            t  = total.get(p)
            if ol is not None and t and t > 0:
                ratios.append(ol / t)

        if not ratios:
            return False

        avg    = sum(ratios) / len(ratios)
        is_fin = avg > 0.65

        if is_fin:
            logger.info(
                "Financial company detected "
                "(avg other_liabilities/total = %.2f > 0.65) "
                "— ROCE set to None.",
                avg,
            )
        else:
            logger.debug(
                "Not a financial company "
                "(avg other_liabilities/total = %.2f <= 0.65).",
                avg,
            )
        return is_fin

    def _capital_employed(self) -> dict[str, float | None]:
        """
        Capital Employed = Total Assets - Other Liabilities.
        Returns all-None for financial companies (banks/NBFCs).
        """
        if getattr(self, "_is_bank", False):
            return {p: None for p in self._periods}
        total = self._series(self._bs, "total")
        curr  = self._series(self._bs, "other_liabilities")
        return {p: self._r(self._sub(total[p], curr[p])) for p in self._periods}

    # ------------------------------------------------------------------
    # TTM (Trailing Twelve Months) helpers
    # ------------------------------------------------------------------

    def _compute_ttm(self) -> tuple[str | None, dict[str, float | None]]:
        """
        Sum the last 4 quarters of P&L to produce a TTM (Trailing Twelve
        Months) snapshot.

        Returns
        -------
        (ttm_period, ttm_values)
            ttm_period : YYYY-MM-DD string of the last quarter end, or None
            ttm_values : {metric: summed_value} for P&L flow metrics
        """
        if self._qt.empty:
            logger.debug("No quarterly data available — TTM skipped.")
            return None, {}

        qt_periods = self._detect_periods(self._qt)
        if len(qt_periods) < 4:
            logger.debug(
                "Only %d quarter(s) available — need 4 for TTM.", len(qt_periods)
            )
            return None, {}

        last_4     = qt_periods[-4:]
        ttm_period = last_4[-1]

        flow_metrics = [
            "sales", "expenses", "operating_profit", "other_income",
            "depreciation", "interest", "profit_before_tax",
            "tax", "net_profit",
        ]
        ttm_values: dict[str, float | None] = {}
        for metric in flow_metrics:
            # Use _get() directly with quarterly period keys — NOT _series()
            # because _series() iterates self._periods (annual dates only)
            vals = [self._get(self._qt, metric, p) for p in last_4]
            ttm_values[metric] = (
                round(sum(float(v) for v in vals), 2)
                if all(v is not None for v in vals)
                else None
            )

        logger.info(
            "TTM: quarters %s → %s | Sales=%.0f | Net Profit=%.0f",
            last_4[0], last_4[-1],
            ttm_values.get("sales") or 0,
            ttm_values.get("net_profit") or 0,
        )
        return ttm_period, ttm_values

    def _ttm_val(self, metric: str) -> float | None:
        """Return the TTM value for a P&L flow metric."""
        if not getattr(self, "_ttm_pnl", None):
            return None
        return self._ttm_pnl.get(metric)

    # ------------------------------------------------------------------
    # Ratio categories
    # ------------------------------------------------------------------

    def _profitability(self) -> dict[str, dict[str, float | None]]:
        """
        net_profit_margin  : Net Profit / Sales x 100
        op_profit_margin   : EBIT / Sales x 100
        ebitda_margin      : EBITDA / Sales x 100
        roe                : Net Profit / Equity x 100
        roce               : EBIT / Capital Employed x 100
        roa                : Net Profit / Total Assets x 100
        """
        logger.debug("Computing profitability ratios...")
        sales    = self._series(self._pnl, "sales")
        net_prof = self._series(self._pnl, "net_profit")
        total    = self._series(self._bs,  "total")
        ebit     = self._ebit()
        ebitda   = self._ebitda()
        equity   = self._equity()
        cap_emp  = self._capital_employed()

        out = {
            "net_profit_margin": self._period_ratio(net_prof, sales,   pct=True),
            "op_profit_margin":  self._period_ratio(ebit,     sales,   pct=True),
            "ebitda_margin":     self._period_ratio(ebitda,   sales,   pct=True),
            "roe":               self._period_ratio(net_prof, equity,  pct=True),
            "roce":              self._period_ratio(ebit,     cap_emp, pct=True),
            "roa":               self._period_ratio(net_prof, total,   pct=True),
        }

        # ── TTM period ────────────────────────────────────────────────
        if self._ttm_period:
            tp          = self._ttm_period
            latest      = self._periods[-1]
            ttm_np      = self._ttm_val("net_profit")
            ttm_sales   = self._ttm_val("sales")
            ttm_op      = self._ttm_val("operating_profit")  # ≈ EBIT for TTM
            ttm_dep     = self._ttm_val("depreciation")
            ttm_ebitda  = self._r(self._add(ttm_op, ttm_dep))
            # Stock metrics: use latest annual BS (no quarterly BS available)
            ttm_equity  = equity.get(latest)
            ttm_total   = total.get(latest)
            ttm_cap     = cap_emp.get(latest)

            out["net_profit_margin"][tp] = self._r(self._pct(ttm_np,     ttm_sales))
            out["op_profit_margin"][tp]  = self._r(self._pct(ttm_op,     ttm_sales))
            out["ebitda_margin"][tp]     = self._r(self._pct(ttm_ebitda, ttm_sales))
            out["roe"][tp]               = self._r(self._pct(ttm_np,     ttm_equity))
            out["roce"][tp]              = (
                self._r(self._pct(ttm_op, ttm_cap)) if ttm_cap else None
            )
            out["roa"][tp]               = self._r(self._pct(ttm_np,     ttm_total))

        return out

    def _valuation(self) -> dict[str, dict[str, float | None]]:
        """
        pe_ratio        : Hist Price / EPS
        pb_ratio        : Hist Price / Book Value per Share
        ev_ebitda       : (MktCap + Borrowings - Cash) / EBITDA
        mktcap_to_sales : Derived MktCap / Sales
        """
        logger.debug("Computing valuation ratios...")

        sales  = self._series(self._pnl, "sales")
        ebitda = self._ebitda()
        equity = self._equity()
        borr   = self._series(self._bs, "borrowings")
        cash   = self._series(self._bs, "cash_bank")
        np_    = self._series(self._pnl, "net_profit")

        out: dict[str, dict[str, float | None]] = {
            k: {} for k in ("pe_ratio", "pb_ratio", "ev_ebitda", "mktcap_to_sales")
        }

        for p in self._periods:
            price  = self._hist_price(p)
            shares = self._adj_shares(p)

            eps    = self._div(np_.get(p), shares)
            bvps   = self._div(equity.get(p), shares)
            mktcap = (price * shares) if (price and shares) else None
            ev     = self._sub(self._add(mktcap, borr.get(p)), cash.get(p))

            out["pe_ratio"][p]        = self._r(self._div(price, eps))
            out["pb_ratio"][p]        = self._r(self._div(price, bvps))
            # EV/EBITDA not meaningful for banks (no EBITDA concept)
            out["ev_ebitda"][p]       = (
                None if getattr(self, "_is_bank", False)
                else self._r(self._div(ev, ebitda.get(p)))
            )
            out["mktcap_to_sales"][p] = self._r(self._div(mktcap, sales.get(p)))

        # ── TTM valuation using current_price_inr ─────────────────────
        # Screener only exports annual hist_price (March year-ends).
        # For the TTM quarter we use current_price_inr from meta.
        # BS values (equity, borrowings, cash) use latest annual since
        # Screener does not export quarterly balance sheet data.
        if self._ttm_period:
            tp         = self._ttm_period
            latest     = self._periods[-1]
            cur_price  = self._meta_float("current_price_inr")
            shares_ttm = self._adj_shares(latest)

            if cur_price and shares_ttm:
                ttm_np    = self._ttm_val("net_profit")
                ttm_sales = self._ttm_val("sales")
                ttm_op    = self._ttm_val("operating_profit")
                ttm_dep   = self._ttm_val("depreciation")
                ttm_ebitda_val = self._r(self._add(ttm_op, ttm_dep))
                ttm_borr  = borr.get(latest)
                ttm_cash  = cash.get(latest)

                ttm_eps   = self._div(ttm_np,           shares_ttm)
                ttm_bvps  = self._div(equity.get(latest), shares_ttm)
                mktcap    = cur_price * shares_ttm
                ev        = self._sub(self._add(mktcap, ttm_borr), ttm_cash)

                out["pe_ratio"][tp]  = self._r(self._div(cur_price, ttm_eps))
                out["pb_ratio"][tp]  = self._r(self._div(cur_price, ttm_bvps))
                out["ev_ebitda"][tp] = (
                    None if getattr(self, "_is_bank", False)
                    else self._r(self._div(ev, ttm_ebitda_val))
                )
                out["mktcap_to_sales"][tp] = self._r(self._div(mktcap, ttm_sales))

                logger.info(
                    "TTM valuation: current_price=%.2f | TTM P/E=%.2f | TTM P/B=%.2f",
                    cur_price,
                    out["pe_ratio"].get(tp) or 0,
                    out["pb_ratio"].get(tp) or 0,
                )
            else:
                out["pe_ratio"][tp]        = None
                out["pb_ratio"][tp]        = None
                out["ev_ebitda"][tp]       = None
                out["mktcap_to_sales"][tp] = None

        return out

    def _leverage(self) -> dict[str, dict[str, float | None]]:
        """
        debt_to_equity    : Borrowings / Equity
        interest_coverage : EBIT / Interest  (None for banks — interest is core revenue cost)
        debt_to_assets    : Borrowings / Total Assets

        For banks:
          - debt_to_equity is misleading (deposits not in borrowings)
          - interest_coverage is meaningless (interest IS the operating cost)
          Both are set to None for financial companies.
        """
        logger.debug("Computing leverage ratios...")

        _none = {p: None for p in self._periods}

        if getattr(self, "_is_bank", False):
            # For banks only debt_to_assets is retained (borrowings/total)
            # as a proxy for leverage — but interest coverage and D/E are removed
            return {
                "debt_to_equity":    _none,
                "interest_coverage": _none,
                "debt_to_assets":    self._period_ratio(
                    self._series(self._bs, "borrowings"),
                    self._series(self._bs, "total"),
                ),
            }

        borr  = self._series(self._bs, "borrowings")
        total = self._series(self._bs, "total")
        eqt   = self._equity()
        ebit  = self._ebit()
        intr  = self._series(self._pnl, "interest")

        out = {
            "debt_to_equity":    self._period_ratio(borr,  eqt),
            "interest_coverage": self._period_ratio(ebit,  intr),
            "debt_to_assets":    self._period_ratio(borr,  total),
        }

        # TTM: BS uses latest annual (no quarterly BS); Interest uses TTM sum
        if self._ttm_period:
            tp     = self._ttm_period
            latest = self._periods[-1]
            ttm_b  = borr.get(latest)
            ttm_e  = eqt.get(latest)
            ttm_t  = total.get(latest)
            ttm_int = self._ttm_val("interest")
            # EBIT TTM = Operating Profit (quarterly)
            ttm_op  = self._ttm_val("operating_profit")

            out["debt_to_equity"][tp]    = self._r(self._div(ttm_b, ttm_e))
            out["interest_coverage"][tp] = self._r(self._div(ttm_op, ttm_int))
            out["debt_to_assets"][tp]    = self._r(self._div(ttm_b, ttm_t))

        return out

    def _liquidity(self) -> dict[str, dict[str, float | None]]:
        """
        cash_ratio : Cash & Bank / Other Liabilities
        TTM: uses latest annual BS (Screener does not export quarterly BS).
        """
        logger.debug("Computing liquidity ratios...")
        cash = self._series(self._bs, "cash_bank")
        curr = self._series(self._bs, "other_liabilities")
        out  = {"cash_ratio": self._period_ratio(cash, curr)}

        # TTM: repeat latest annual BS values (no quarterly BS data available)
        if self._ttm_period:
            tp = self._ttm_period
            latest = self._periods[-1]
            out["cash_ratio"][tp] = out["cash_ratio"].get(latest)

        return out

    def _efficiency(self) -> dict[str, dict[str, float | None]]:
        """
        asset_turnover          : Sales / Total Assets
        inventory_turnover_days : (Inventory / Sales) x 365
        receivables_days        : (Receivables / Sales) x 365

        All set to None for financial companies — banks have no inventory
        or trade receivables, and asset turnover is meaningless for them
        (revenue = interest income, assets = loans/securities).
        """
        logger.debug("Computing efficiency ratios...")

        _none = {p: None for p in self._periods}

        if getattr(self, "_is_bank", False):
            logger.debug("Financial company — efficiency ratios set to None.")
            return {
                "asset_turnover":          _none,
                "inventory_turnover_days": _none,
                "receivables_days":        _none,
            }

        sales = self._series(self._pnl, "sales")
        total = self._series(self._bs,  "total")
        inv   = self._series(self._bs,  "inventory")
        rec   = self._series(self._bs,  "receivables")

        inv_days: dict[str, float | None] = {}
        rec_days: dict[str, float | None] = {}
        for p in self._periods:
            s = sales.get(p)
            inv_days[p] = self._r(
                self._div(inv.get(p), s) * 365
                if (inv.get(p) is not None and s is not None) else None
            )
            rec_days[p] = self._r(
                self._div(rec.get(p), s) * 365
                if (rec.get(p) is not None and s is not None) else None
            )

        out = {
            "asset_turnover":          self._period_ratio(sales, total),
            "inventory_turnover_days": inv_days,
            "receivables_days":        rec_days,
        }

        # TTM: use TTM sales with latest annual BS for asset/inventory/receivables
        if self._ttm_period:
            tp         = self._ttm_period
            latest     = self._periods[-1]
            ttm_sales  = self._ttm_val("sales")
            ttm_total  = total.get(latest)
            ttm_inv    = inv.get(latest)
            ttm_rec    = rec.get(latest)

            out["asset_turnover"][tp] = self._r(self._div(ttm_sales, ttm_total))
            out["inventory_turnover_days"][tp] = self._r(
                self._div(ttm_inv, ttm_sales) * 365
                if (ttm_inv is not None and ttm_sales) else None
            )
            out["receivables_days"][tp] = self._r(
                self._div(ttm_rec, ttm_sales) * 365
                if (ttm_rec is not None and ttm_sales) else None
            )

        return out

    def _growth(self) -> dict[str, float | None]:
        """
        CAGR for Sales and Net Profit across all configured windows.

        Windows that exceed the number of available periods are silently
        skipped — no None entry is emitted, output only contains computable windows.

        Formula: CAGR = (end / start) ^ (1 / years) - 1
        """
        logger.debug(
            "Computing growth CAGRs — windows: %s, periods available: %d",
            self._cagr_windows, len(self._periods),
        )

        n      = len(self._periods)
        sales  = self._series(self._pnl, "sales")
        profit = self._series(self._pnl, "net_profit")
        result: dict[str, float | None] = {}

        for years in self._cagr_windows:
            if years >= n:
                logger.debug(
                    "CAGR window %dy skipped — only %d periods available.", years, n
                )
                continue

            end_p   = self._periods[-1]
            start_p = self._periods[-(years + 1)]

            def _cagr(series: dict[str, float | None]) -> float | None:
                end_v   = series.get(end_p)
                start_v = series.get(start_p)
                if end_v is None or start_v is None or start_v <= 0:
                    return None
                try:
                    return self._r(((end_v / start_v) ** (1.0 / years) - 1) * 100)
                except (ValueError, ZeroDivisionError):
                    return None

            label = f"{years}y"
            result[f"sales_cagr_{label}"]      = _cagr(sales)
            result[f"net_profit_cagr_{label}"] = _cagr(profit)

        return result

    def _per_share(self) -> dict[str, dict[str, float | None]]:
        """
        eps                  : Net Profit (Cr) / Adj Shares (Cr)
        book_value_per_share : Equity (Cr) / Adj Shares (Cr)
        dividend_per_share   : Dividend (Cr) / Adj Shares (Cr)
        """
        logger.debug("Computing per-share metrics...")
        net_prof = self._series(self._pnl, "net_profit")
        dividend = self._series(self._pnl, "dividend_amount")
        equity   = self._equity()

        eps:  dict[str, float | None] = {}
        bvps: dict[str, float | None] = {}
        dps:  dict[str, float | None] = {}

        for p in self._periods:
            shares  = self._adj_shares(p)
            eps[p]  = self._r(self._div(net_prof.get(p), shares))
            bvps[p] = self._r(self._div(equity.get(p),   shares))
            dps[p]  = self._r(self._div(dividend.get(p), shares))

        # ── TTM EPS ───────────────────────────────────────────────────
        if self._ttm_period:
            tp         = self._ttm_period
            latest     = self._periods[-1]
            ttm_np     = self._ttm_val("net_profit")
            ttm_shares = self._adj_shares(latest)
            eps[tp]    = self._r(self._div(ttm_np, ttm_shares)) if ttm_shares else None
            # Book value unchanged (annual BS only); dividends declared annually
            bvps[tp]   = bvps.get(latest)
            dps[tp]    = None

        return {
            "eps":                  eps,
            "book_value_per_share": bvps,
            "dividend_per_share":   dps,
        }

    # ------------------------------------------------------------------
    # Data quality report
    # ------------------------------------------------------------------

    def _data_quality(self, result: RatioResult) -> dict[str, list[str]]:
        """
        Classify every ratio series as fully_populated, partial, or missing.
        Growth scalars are treated as present or missing.
        """
        fully:   list[str] = []
        partial: list[str] = []
        missing: list[str] = []

        all_period_series: dict[str, dict[str, float | None]] = {}
        for category_dict in (
            result.profitability, result.valuation,
            result.leverage, result.liquidity,
            result.efficiency, result.per_share,
        ):
            all_period_series.update(category_dict)

        n = len(self._periods)
        for name, series in all_period_series.items():
            non_null = sum(1 for v in series.values() if v is not None)
            if non_null == 0:
                missing.append(name)
            elif non_null == n:
                fully.append(name)
            else:
                partial.append(f"{name} ({non_null}/{n} periods)")

        for name, val in result.growth.items():
            (fully if val is not None else missing).append(f"growth.{name}")

        logger.info(
            "Data quality — fully: %d, partial: %d, missing: %d",
            len(fully), len(partial), len(missing),
        )
        if missing:
            logger.warning("Missing ratio outputs: %s", missing)

        return {
            "fully_populated": sorted(fully),
            "partial":         sorted(partial),
            "missing":         sorted(missing),
        }

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------

    def _write_json(self, result: RatioResult) -> None:
        """Write RatioResult to ratios.json with indent=2."""
        out_path = self._dir / self._OUT_FILE
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(result.to_dict(), fh, indent=2, ensure_ascii=False)
            logger.info(
                "ratios.json written -> %s (%d bytes)",
                out_path, out_path.stat().st_size,
            )
        except OSError as exc:
            raise RatioEngineError(
                f"Failed to write '{out_path}': {exc}"
            ) from exc


if __name__ == "__main__":
    import sys
    logger.info("Running ratio engine from command line")
    try:
        engine = RatioEngine()
        result = engine.compute_all()
        logger.info("Ratio engine completed. Company: %s", result.company)
    except Exception as e:
        logger.error("Ratio engine failed: %s", e, exc_info=True)
        sys.exit(1)