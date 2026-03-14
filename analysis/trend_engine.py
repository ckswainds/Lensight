"""
analysis/trend_engine.py
-------------------------
Computes trend direction, YoY changes, and period-level classifications
for every ratio series in ratios.json.

Reads
-----
  data/processed/ratios.json   — produced by ratio_engine.py

Outputs
-------
  A TrendResult dataclass consumed by json_formatter.py.
  Nothing is written to disk here — json_formatter combines
  ratio + trend output into the final analysis.json.

Trend Detection Logic
---------------------
For each ratio series (period-keyed values):

  1. YoY absolute change    : value[t] - value[t-1]
  2. YoY % change           : (value[t] - value[t-1]) / |value[t-1]| * 100
  3. Direction per step     : +1 (up), -1 (down), 0 (flat)
  4. Trend label assignment :

     - strong_uptrend  : all N recent steps are +1
     - strong_decline  : all N recent steps are -1
     - improving       : majority of steps are +1, not all
     - declining       : majority of steps are -1, not all
     - stable          : all absolute % changes < STABLE_THRESHOLD
     - volatile        : std dev of % changes > VOLATILE_THRESHOLD
     - stable          : fallback

  N (lookback window) defaults to 4 periods, configurable.

Per-share EPS growth is computed here as YoY % change in EPS
and classified using the "eps_growth" threshold.
"""

import logging
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from analysis.classification_rules import (
    classify,
    classify_all_periods,
    get_trend_score,
    RATIO_CLASSIFICATION_LEVELS,
)
from constants import DATA_PROCESSED_DIR, LOGS_DIR


# ─────────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file = LOGS_DIR / "trend_engine.log"
file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Number of most-recent periods to use for trend detection
TREND_LOOKBACK: int = 4

# A series is "stable" if ALL period-over-period % changes are below this
STABLE_THRESHOLD: float = 5.0

# A series is "volatile" if std dev of % changes exceeds this
VOLATILE_THRESHOLD: float = 20.0


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class TrendEngineError(Exception):
    """Raised when trend computation cannot proceed."""


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class RatioTrend:
    """
    Trend analysis output for a single ratio series.

    Attributes
    ----------
    values : dict[str, float | None]
        Original period-keyed ratio values.
    yoy_change : dict[str, float | None]
        Absolute year-over-year change per period.
    yoy_pct : dict[str, float | None]
        Percentage year-over-year change per period.
    labels : dict[str, str | None]
        Classification label per period (e.g. "excellent").
    latest_value : float | None
        Most recent period value.
    latest_label : str | None
        Classification label for the most recent value.
    trend : str
        Trend direction label (e.g. "strong_uptrend", "declining").
    trend_score : int
        Numeric trend score (1–5).
    """
    values:       dict[str, float | None]
    yoy_change:   dict[str, float | None]
    yoy_pct:      dict[str, float | None]
    labels:       dict[str, str | None]
    latest_value: float | None
    latest_label: str | None
    trend:        str
    trend_score:  int

    def to_dict(self) -> dict[str, Any]:
        return {
            "values":       self.values,
            "yoy_change":   self.yoy_change,
            "yoy_pct":      self.yoy_pct,
            "labels":       self.labels,
            "latest_value": self.latest_value,
            "latest_label": self.latest_label,
            "trend":        self.trend,
            "trend_score":  self.trend_score,
        }


@dataclass
class GrowthTrend:
    """
    Trend for a scalar growth metric (CAGR).

    Attributes
    ----------
    value : float | None
        The CAGR value.
    label : str | None
        Classification label.
    """
    value: float | None
    label: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label}


@dataclass
class TrendResult:
    """
    Complete trend analysis output for one company.

    Contains the same category structure as RatioResult but each ratio
    is a RatioTrend instead of a raw value dict.
    """
    company:       str
    periods:       list[str]
    profitability: dict[str, RatioTrend] = field(default_factory=dict)
    valuation:     dict[str, RatioTrend] = field(default_factory=dict)
    leverage:      dict[str, RatioTrend] = field(default_factory=dict)
    liquidity:     dict[str, RatioTrend] = field(default_factory=dict)
    efficiency:    dict[str, RatioTrend] = field(default_factory=dict)
    growth:        dict[str, GrowthTrend] = field(default_factory=dict)
    per_share:     dict[str, RatioTrend] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def _category(d: dict) -> dict:
            return {k: v.to_dict() for k, v in d.items()}

        return {
            "company":       self.company,
            "periods":       self.periods,
            "profitability": _category(self.profitability),
            "valuation":     _category(self.valuation),
            "leverage":      _category(self.leverage),
            "liquidity":     _category(self.liquidity),
            "efficiency":    _category(self.efficiency),
            "growth":        _category(self.growth),
            "per_share":     _category(self.per_share),
        }


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class TrendEngine:
    """
    Computes trend direction, YoY changes, and classification labels
    for every ratio series in ratios.json.

    Parameters
    ----------
    processed_dir : path-like, optional
        Directory containing ratios.json. Defaults to DATA_PROCESSED_DIR.
    lookback : int, optional
        Number of most-recent periods to use for trend detection.
        Defaults to TREND_LOOKBACK (4).

    Example
    -------
    >>> engine = TrendEngine("data/processed")
    >>> result = engine.compute_all()
    >>> print(result.profitability["roe"].trend)
    'strong_uptrend'
    """

    _RATIOS_FILE = "ratios.json"

    def __init__(
        self,
        processed_dir: str | Path | None = None,
        lookback: int = TREND_LOOKBACK,
    ) -> None:
        self._dir      = Path(processed_dir) if processed_dir else DATA_PROCESSED_DIR
        self._lookback = max(2, lookback)   # minimum 2 for meaningful trend
        self._ratios:  dict[str, Any] = {}
        self._periods: list[str]      = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute_all(self) -> TrendResult:
        """
        Load ratios.json and compute trends for all ratio categories.

        Returns
        -------
        TrendResult
            Fully populated trend result.

        Raises
        ------
        TrendEngineError
            If ratios.json is missing or malformed.
        """
        logger.info("Starting trend computation — dir: '%s'", self._dir)

        self._load_ratios()

        company = self._ratios.get("company", "UNKNOWN")
        self._periods = self._ratios.get("periods", [])

        if not self._periods:
            raise TrendEngineError(
                "No periods found in ratios.json. "
                "Run ratio_engine.py first."
            )

        logger.info(
            "Company: %s | Periods: %d | Lookback: %d",
            company, len(self._periods), self._lookback,
        )

        result = TrendResult(company=company, periods=self._periods)

        result.profitability = self._process_category("profitability")
        result.valuation     = self._process_category("valuation")
        result.leverage      = self._process_category("leverage")
        result.liquidity     = self._process_category("liquidity")
        result.efficiency    = self._process_category("efficiency")
        result.growth        = self._process_growth()
        result.per_share     = self._process_per_share()

        logger.info(
            "Trend computation complete — %d categories processed.",
            6,  # fixed number of ratio categories
        )
        return result

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_ratios(self) -> None:
        """Load and validate ratios.json."""
        path = self._dir / self._RATIOS_FILE
        if not path.exists():
            raise TrendEngineError(
                f"ratios.json not found at '{path}'. "
                "Run ratio_engine.compute_all() first."
            )
        try:
            with path.open(encoding="utf-8") as fh:
                self._ratios = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise TrendEngineError(
                f"Cannot read ratios.json: {exc}"
            ) from exc

        if "periods" not in self._ratios:
            raise TrendEngineError(
                "ratios.json is missing the 'periods' key. "
                "File may be from an older version of ratio_engine."
            )

    # ------------------------------------------------------------------
    # Category processors
    # ------------------------------------------------------------------

    def _process_category(self, category: str) -> dict[str, RatioTrend]:
        """
        Process all ratios in a given category from ratios.json.

        Returns
        -------
        dict[str, RatioTrend]
            Ratio name → RatioTrend for every ratio in the category.
        """
        raw: dict[str, dict[str, float | None]] = self._ratios.get(category, {})
        if not raw:
            logger.debug("Category '%s' is empty in ratios.json.", category)
            return {}

        result: dict[str, RatioTrend] = {}
        for ratio_name, values in raw.items():
            try:
                result[ratio_name] = self._analyse_series(
                    ratio_name=ratio_name,
                    values=values,
                    category=category,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to analyse ratio '%s' in category '%s': %s — skipping.",
                    ratio_name, category, exc,
                )
        return result

    def _process_growth(self) -> dict[str, GrowthTrend]:
        """
        Process scalar growth metrics (CAGR values) from ratios.json.
        Each CAGR key is classified using classification_rules.
        """
        raw: dict[str, float | None] = self._ratios.get("growth", {})
        result: dict[str, GrowthTrend] = {}

        for key, value in raw.items():
            label = classify(key, value, category="growth")
            result[key] = GrowthTrend(value=value, label=label)
            logger.debug(
                "Growth '%s': value=%.2f  label=%s",
                key, value if value is not None else float("nan"), label,
            )

        return result

    def _process_per_share(self) -> dict[str, RatioTrend]:
        """
        Process per-share metrics (eps, book_value_per_share, dividend_per_share).
        EPS gets an additional eps_growth YoY classification.
        """
        raw: dict[str, dict[str, float | None]] = self._ratios.get("per_share", {})
        result: dict[str, RatioTrend] = {}

        for ratio_name, values in raw.items():
            try:
                # For EPS, use eps_growth thresholds on YoY % change
                # For others, no classification thresholds exist — trend only
                use_category = "per_share" if ratio_name == "eps" else None
                result[ratio_name] = self._analyse_series(
                    ratio_name=ratio_name,
                    values=values,
                    category=use_category,
                    classify_yoy_pct=(ratio_name == "eps"),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to analyse per_share metric '%s': %s — skipping.",
                    ratio_name, exc,
                )

        return result

    # ------------------------------------------------------------------
    # Core series analysis
    # ------------------------------------------------------------------

    def _analyse_series(
        self,
        ratio_name: str,
        values: dict[str, float | None],
        category: str | None = None,
        classify_yoy_pct: bool = False,
    ) -> RatioTrend:
        """
        Full analysis of one ratio series.

        Parameters
        ----------
        ratio_name : str
            Ratio key (e.g. "roe", "pe_ratio").
        values : dict[str, float | None]
            Period-keyed ratio values in chronological order.
        category : str | None
            Category hint for classify().
        classify_yoy_pct : bool
            If True, classify the YoY % change series instead of the
            raw value series. Used for EPS growth.

        Returns
        -------
        RatioTrend
        """
        # Ensure periods are sorted chronologically
        sorted_periods = sorted(values.keys())
        ordered_values: list[float | None] = [values[p] for p in sorted_periods]

        yoy_change = self._compute_yoy_change(sorted_periods, ordered_values)
        yoy_pct    = self._compute_yoy_pct(sorted_periods, ordered_values)

        # Classify raw values or YoY % change depending on ratio type
        if classify_yoy_pct:
            labels = classify_all_periods("eps_growth", yoy_pct, category="per_share")
        else:
            labels = classify_all_periods(ratio_name, values, category=category)

        latest_period = sorted_periods[-1] if sorted_periods else None
        latest_value  = values.get(latest_period) if latest_period else None
        latest_label  = labels.get(latest_period) if latest_period else None

        trend, trend_score = self._detect_trend(
            sorted_periods, ordered_values, yoy_pct
        )

        logger.debug(
            "%-30s latest=%-8s label=%-14s trend=%s (score=%d)",
            ratio_name,
            f"{latest_value:.2f}" if latest_value is not None else "None",
            str(latest_label),
            trend,
            trend_score,
        )

        return RatioTrend(
            values=values,
            yoy_change=yoy_change,
            yoy_pct=yoy_pct,
            labels=labels,
            latest_value=latest_value,
            latest_label=latest_label,
            trend=trend,
            trend_score=trend_score,
        )

    # ------------------------------------------------------------------
    # YoY computation
    # ------------------------------------------------------------------

    def _compute_yoy_change(
        self,
        periods: list[str],
        values: list[float | None],
    ) -> dict[str, float | None]:
        """
        Compute absolute year-over-year change for each period.
        The first period has no prior, so its change is None.
        """
        result: dict[str, float | None] = {periods[0]: None}
        for i in range(1, len(periods)):
            curr = values[i]
            prev = values[i - 1]
            if curr is None or prev is None:
                result[periods[i]] = None
            else:
                result[periods[i]] = round(curr - prev, 2)
        return result

    def _compute_yoy_pct(
        self,
        periods: list[str],
        values: list[float | None],
    ) -> dict[str, float | None]:
        """
        Compute percentage year-over-year change for each period.

        Uses absolute value of the previous period as denominator to
        handle sign changes correctly (e.g. negative → positive profit).
        First period is always None.
        """
        result: dict[str, float | None] = {periods[0]: None}
        for i in range(1, len(periods)):
            curr = values[i]
            prev = values[i - 1]
            if curr is None or prev is None:
                result[periods[i]] = None
            elif abs(prev) < 1e-9:
                # Previous value was zero — % change is undefined
                result[periods[i]] = None
            else:
                pct = ((curr - prev) / abs(prev)) * 100
                if math.isfinite(pct):
                    result[periods[i]] = round(pct, 2)
                else:
                    result[periods[i]] = None
        return result

    # ------------------------------------------------------------------
    # Trend detection
    # ------------------------------------------------------------------

    def _detect_trend(
        self,
        periods: list[str],
        values:  list[float | None],
        yoy_pct: dict[str, float | None],
    ) -> tuple[str, int]:
        """
        Detect trend direction from the most recent TREND_LOOKBACK periods.

        Returns
        -------
        tuple[str, int]
            (trend_label, trend_score)
        """
        n = len(periods)
        if n < 2:
            return "stable", get_trend_score("stable")

        # Use the most recent `lookback` periods, or all if fewer available
        lookback = min(self._lookback, n - 1)
        recent_periods  = periods[-(lookback + 1):]
        recent_values   = values[-(lookback + 1):]

        # Filter to periods where both current and prior value are non-None
        valid_pairs: list[tuple[float, float]] = []
        for i in range(1, len(recent_values)):
            curr = recent_values[i]
            prev = recent_values[i - 1]
            if curr is not None and prev is not None:
                valid_pairs.append((prev, curr))

        if not valid_pairs:
            logger.debug(
                "No valid value pairs for trend detection — defaulting to stable."
            )
            return "stable", get_trend_score("stable")

        # Direction per step: +1 up, -1 down, 0 flat
        directions = [
            1 if curr > prev else (-1 if curr < prev else 0)
            for prev, curr in valid_pairs
        ]

        # Collect valid YoY % changes for volatility check
        pct_changes = [
            yoy_pct.get(p)
            for p in recent_periods[1:]
            if yoy_pct.get(p) is not None
        ]

        trend_label = self._assign_trend_label(directions, pct_changes)
        trend_score = get_trend_score(trend_label) or 3

        return trend_label, trend_score

    def _assign_trend_label(
        self,
        directions:  list[int],
        pct_changes: list[float],
    ) -> str:
        """
        Map step directions and % changes to a trend label.

        Rules (evaluated in priority order):
          1. All steps up   → strong_uptrend
          2. All steps down → strong_decline
          3. Std dev of % changes > VOLATILE_THRESHOLD → volatile
          4. All % changes < STABLE_THRESHOLD → stable
          5. Majority up    → improving
          6. Majority down  → declining
          7. fallback       → stable
        """
        if not directions:
            return "stable"

        total   = len(directions)
        up      = sum(1 for d in directions if d == 1)
        down    = sum(1 for d in directions if d == -1)

        # 1 & 2: unanimous direction
        if up == total:
            return "strong_uptrend"
        if down == total:
            return "strong_decline"

        # 3: volatility check
        if len(pct_changes) >= 2:
            try:
                std = statistics.stdev(pct_changes)
                if std > VOLATILE_THRESHOLD:
                    return "volatile"
            except statistics.StatisticsError:
                pass

        # 4: stable — all changes are small
        if pct_changes and all(
            abs(p) < STABLE_THRESHOLD for p in pct_changes
        ):
            return "stable"

        # 5 & 6: majority direction
        if up > down:
            return "improving"
        if down > up:
            return "declining"

        # 7: fallback
        return "stable"