"""
analysis/classification_rules.py
----------------------------------
Single source of truth for all ratio classification thresholds
and trend level definitions.

Responsibilities
----------------
- Hold RATIO_CLASSIFICATION_LEVELS as the authoritative threshold dict
- Expose classify() to label any ratio value given its name and category
- Expose get_trend_label() to map a numeric trend score to a level name
- Expose get_trend_score() to map a trend label to its numeric score
- All functions are pure — no I/O, no pandas, no side effects

Design
------
Each ratio maps to an ordered list of (label, lower, upper) buckets.
Ranges are inclusive on the lower bound, exclusive on the upper bound:
    lower <= value < upper
except the final bucket which is inclusive on both ends to catch
exact boundary values (e.g. value == 0 in a (0, 0.3) range).

The classify() function iterates buckets in definition order so the
dict ordering must go from lowest to highest range per ratio.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification thresholds — edit thresholds here, nowhere else
# ---------------------------------------------------------------------------

RATIO_CLASSIFICATION_LEVELS: dict[str, Any] = {

    "trend_levels": {
        "strong_uptrend": {
            "description": "Consistently increasing values over time",
            "score": 5,
        },
        "improving": {
            "description": "Overall upward direction with some fluctuations",
            "score": 4,
        },
        "stable": {
            "description": "Mostly flat with small variation",
            "score": 3,
        },
        "volatile": {
            "description": "Large fluctuations without clear direction",
            "score": 3,       # raised from 2 — volatile != declining
        },
        "declining": {
            "description": "Gradual downward movement",
            "score": 2,
        },
        "strong_decline": {
            "description": "Consistently decreasing values",
            "score": 1,
        },
    },

    "profitability": {

        "roe": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 12),
            "average":   (12, 18),
            "strong":    (18, 25),
            "excellent": (25, float("inf")),
        },
        "roce": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 12),
            "average":   (12, 18),
            "strong":    (18, 25),
            "excellent": (25, float("inf")),
        },
        "roa": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 3),
            "average":   (3, 6),
            "strong":    (6, 10),
            "excellent": (10, float("inf")),
        },
        "net_profit_margin": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 10),
            "average":   (10, 15),
            "strong":    (15, 20),
            "excellent": (20, float("inf")),
        },
        "op_profit_margin": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 10),
            "average":   (10, 18),
            "strong":    (18, 25),
            "excellent": (25, float("inf")),
        },
        "ebitda_margin": {
            "negative":  (-float("inf"), 0),
            "weak":      (0, 12),
            "average":   (12, 18),
            "strong":    (18, 25),
            "excellent": (25, float("inf")),
        },
    },

    "valuation": {

        "pe_ratio": {
            "negative":       (-float("inf"), 0),
            "undervalued":    (0, 15),
            "fair":           (15, 25),
            "expensive":      (25, 40),
            "very_expensive": (40, float("inf")),
        },
        "pb_ratio": {
            "negative":       (-float("inf"), 0),
            "undervalued":    (0, 2),
            "fair":           (2, 4),
            "expensive":      (4, 8),
            "very_expensive": (8, float("inf")),
        },
        "ev_ebitda": {
            "negative":       (-float("inf"), 0),
            "cheap":          (0, 8),
            "fair":           (8, 15),
            "expensive":      (15, 25),
            "very_expensive": (25, float("inf")),
        },
        "mktcap_to_sales": {
            "cheap":          (0, 2),
            "fair":           (2, 5),
            "expensive":      (5, 10),
            "very_expensive": (10, float("inf")),
        },
    },

    "leverage": {

        "debt_to_equity": {
            "excellent":  (0, 0.3),
            "safe":       (0.3, 1.0),
            "risky":      (1.0, 2.0),
            "very_risky": (2.0, float("inf")),
        },
        "interest_coverage": {
            "weak":      (0, 2),
            "moderate":  (2, 5),
            "strong":    (5, 10),
            "excellent": (10, float("inf")),
        },
        "debt_to_assets": {
            "low":       (0, 0.3),
            "moderate":  (0.3, 0.6),
            "high":      (0.6, 1.0),
            "very_high": (1.0, float("inf")),
        },
    },

    "liquidity": {

        "cash_ratio": {
            "weak":     (0, 0.2),
            "adequate": (0.2, 0.5),
            "strong":   (0.5, float("inf")),
        },
    },

    "efficiency": {

        "asset_turnover": {
            "weak":      (0, 0.3),
            "average":   (0.3, 0.6),
            "good":      (0.6, 1.0),
            "excellent": (1.0, float("inf")),
        },
        "inventory_turnover_days": {
            "excellent": (0, 60),
            "good":      (60, 120),
            "average":   (120, 180),
            "poor":      (180, float("inf")),
        },
        "receivables_days": {
            "excellent": (0, 60),
            "good":      (60, 120),
            "average":   (120, 180),
            "poor":      (180, float("inf")),
        },
    },

    "growth": {

        # Applied to sales_cagr_3y, sales_cagr_5y, sales_cagr_7y
        "sales_cagr": {
            "negative":  (-float("inf"), 0),
            "slow":      (0, 6),
            "moderate":  (6, 12),
            "strong":    (12, 20),
            "excellent": (20, float("inf")),
        },

        # Applied to net_profit_cagr_3y, net_profit_cagr_5y, net_profit_cagr_7y
        "profit_cagr": {
            "negative":  (-float("inf"), 0),
            "slow":      (0, 8),
            "moderate":  (8, 15),
            "strong":    (15, 25),
            "excellent": (25, float("inf")),
        },

        # Applied to EPS YoY growth
        "eps_growth": {
            "negative":  (-float("inf"), 0),
            "slow":      (0, 8),
            "moderate":  (8, 15),
            "strong":    (15, 25),
            "excellent": (25, float("inf")),
        },
    },

    "per_share": {

        "eps_growth": {
            "negative":  (-float("inf"), 0),
            "slow":      (0, 8),
            "moderate":  (8, 15),
            "strong":    (15, 25),
            "excellent": (25, float("inf")),
        },
    },
}


# ---------------------------------------------------------------------------
# Ratio → category mapping
# Used by classify() to locate the right threshold dict without the caller
# having to know which category a ratio belongs to.
# ---------------------------------------------------------------------------

_RATIO_TO_CATEGORY: dict[str, str] = {}

def _build_ratio_index() -> None:
    """
    Populate _RATIO_TO_CATEGORY by scanning RATIO_CLASSIFICATION_LEVELS.
    Called once at module import. Skips the 'trend_levels' top-level key.
    """
    for category, ratios in RATIO_CLASSIFICATION_LEVELS.items():
        if category == "trend_levels":
            continue
        if isinstance(ratios, dict):
            for ratio_name in ratios:
                _RATIO_TO_CATEGORY[ratio_name] = category

_build_ratio_index()


# ---------------------------------------------------------------------------
# Growth key normalisation
# Maps engine output keys like "sales_cagr_3y" to the threshold key
# "sales_cagr" and "net_profit_cagr_5y" to "profit_cagr".
# ---------------------------------------------------------------------------

def _normalise_growth_key(ratio_name: str) -> str | None:
    """
    Map a specific CAGR key from the ratio engine to a generic growth
    threshold key defined in RATIO_CLASSIFICATION_LEVELS["growth"].

    Examples
    --------
    "sales_cagr_3y"       → "sales_cagr"
    "sales_cagr_5y"       → "sales_cagr"
    "net_profit_cagr_3y"  → "profit_cagr"
    "net_profit_cagr_7y"  → "profit_cagr"
    "eps_growth"          → "eps_growth"

    Returns None if no mapping found.
    """
    if ratio_name.startswith("sales_cagr"):
        return "sales_cagr"
    if ratio_name.startswith("net_profit_cagr"):
        return "profit_cagr"
    if ratio_name == "eps_growth":
        return "eps_growth"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    ratio_name: str,
    value: float | None,
    category: str | None = None,
) -> str | None:
    """
    Classify a ratio value and return its label.

    Parameters
    ----------
    ratio_name : str
        The ratio key as produced by ratio_engine.py, e.g. "roe",
        "pe_ratio", "sales_cagr_3y", "net_profit_cagr_5y".
    value : float | None
        The numeric value to classify. Returns None if value is None.
    category : str | None, optional
        The category the ratio belongs to (e.g. "profitability").
        If omitted the function auto-detects it via _RATIO_TO_CATEGORY.
        Pass explicitly when calling for growth ratios to force the
        correct threshold lookup.

    Returns
    -------
    str | None
        The label string (e.g. "excellent", "fair", "very_expensive"),
        or None if value is None or no matching threshold is found.

    Examples
    --------
    >>> classify("roe", 26.64)
    'excellent'
    >>> classify("pe_ratio", 41.39)
    'very_expensive'
    >>> classify("sales_cagr_3y", 15.65)
    'strong'
    >>> classify("roe", None)
    None
    """
    if value is None:
        return None

    # Resolve threshold dict
    thresholds = _resolve_thresholds(ratio_name, category)
    if thresholds is None:
        logger.debug(
            "No classification thresholds found for ratio '%s' — returning None.",
            ratio_name,
        )
        return None

    # Iterate buckets in order; return first matching label
    for label, (lower, upper) in thresholds.items():
        if lower <= value < upper:
            return label

    # Catch exact match on the upper boundary of the last bucket
    # (handles value == float("inf") edge case)
    last_label = list(thresholds.keys())[-1]
    last_lower, last_upper = list(thresholds.values())[-1]
    if value >= last_lower:
        return last_label

    logger.warning(
        "Value %.4f for ratio '%s' fell outside all defined buckets.",
        value, ratio_name,
    )
    return None


def classify_all_periods(
    ratio_name: str,
    values: dict[str, float | None],
    category: str | None = None,
) -> dict[str, str | None]:
    """
    Classify a ratio across all periods at once.

    Parameters
    ----------
    ratio_name : str
        Ratio key (same as classify()).
    values : dict[str, float | None]
        Period-keyed dict of values, e.g. {"2016-03-31": 14.85, ...}
    category : str | None
        Optional category hint (same as classify()).

    Returns
    -------
    dict[str, str | None]
        Period-keyed dict of labels, e.g. {"2016-03-31": "average", ...}
    """
    return {
        period: classify(ratio_name, value, category)
        for period, value in values.items()
    }


def get_trend_score(trend_label: str) -> int | None:
    """
    Return the numeric score (1–5) for a trend label.

    Parameters
    ----------
    trend_label : str
        One of the keys in RATIO_CLASSIFICATION_LEVELS["trend_levels"].

    Returns
    -------
    int | None
        Score, or None if the label is not recognised.

    Examples
    --------
    >>> get_trend_score("strong_uptrend")
    5
    >>> get_trend_score("declining")
    2
    """
    entry = RATIO_CLASSIFICATION_LEVELS["trend_levels"].get(trend_label)
    if entry is None:
        logger.warning("Unknown trend label '%s' — returning None.", trend_label)
        return None
    return entry["score"]


def get_trend_label(score: int) -> str | None:
    """
    Return the canonical trend label for a numeric score.
    When multiple labels share the same score, the first match is returned.

    Parameters
    ----------
    score : int
        Numeric trend score (1–5).

    Returns
    -------
    str | None
        Trend label, or None if no label has that score.

    Examples
    --------
    >>> get_trend_label(5)
    'strong_uptrend'
    >>> get_trend_label(1)
    'strong_decline'
    """
    for label, entry in RATIO_CLASSIFICATION_LEVELS["trend_levels"].items():
        if entry["score"] == score:
            return label
    logger.warning("No trend label found for score %d — returning None.", score)
    return None


def list_ratios_for_category(category: str) -> list[str]:
    """
    Return all ratio names defined under a given category.

    Parameters
    ----------
    category : str
        e.g. "profitability", "valuation", "leverage"

    Returns
    -------
    list[str]
        Ratio names, or empty list if category not found.
    """
    cat = RATIO_CLASSIFICATION_LEVELS.get(category, {})
    if category == "trend_levels":
        return []
    return list(cat.keys())


def get_all_categories() -> list[str]:
    """Return all ratio categories (excludes 'trend_levels')."""
    return [
        k for k in RATIO_CLASSIFICATION_LEVELS
        if k != "trend_levels"
    ]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_thresholds(
    ratio_name: str,
    category: str | None,
) -> dict[str, tuple[float, float]] | None:
    """
    Locate the threshold dict for a given ratio.

    Resolution order:
      1. Use provided category if given
      2. Check _RATIO_TO_CATEGORY index (exact ratio name match)
      3. Check growth normalisation for CAGR keys
      4. Return None if nothing found
    """
    levels = RATIO_CLASSIFICATION_LEVELS

    # 1. Explicit category provided
    if category is not None:
        cat_dict = levels.get(category, {})
        if ratio_name in cat_dict:
            return cat_dict[ratio_name]
        # Try growth normalisation within the given category
        growth_key = _normalise_growth_key(ratio_name)
        if growth_key and growth_key in cat_dict:
            return cat_dict[growth_key]
        return None

    # 2. Exact match via pre-built index
    auto_category = _RATIO_TO_CATEGORY.get(ratio_name)
    if auto_category is not None:
        return levels[auto_category].get(ratio_name)

    # 3. Growth key normalisation (handles "sales_cagr_3y" etc.)
    growth_key = _normalise_growth_key(ratio_name)
    if growth_key is not None:
        return levels.get("growth", {}).get(growth_key)

    return None