"""
analysis/json_formatter.py
---------------------------
Combines ratio_engine output (ratios.json) and trend_engine output
(TrendResult) into one finalized analysis.json consumed by both the
dashboard and the LLM prompt builder.

Input
-----
  data/processed/ratios.json   — ratio engine output
  TrendResult dataclass        — trend engine output (passed in-memory)

Output
------
  data/processed/analysis.json — single source of truth for downstream

Structure of analysis.json
---------------------------
{
  "company":       "BHARAT ELECTRONICS LTD",
  "generated_at":  "2025-03-14T10:30:00",
  "period_count":  10,
  "periods":       ["2016-03-31", ..., "2025-03-31"],
  "latest_period": "2025-03-31",

  "profitability": {
    "roe": {
      "values":        {"2016-03-31": 14.85, ...},
      "yoy_change":    {"2017-03-31": 3.2, ...},
      "yoy_pct":       {"2017-03-31": 21.5, ...},
      "labels":        {"2016-03-31": "average", ...},
      "latest_value":  26.64,
      "latest_label":  "excellent",
      "trend":         "strong_uptrend",
      "trend_score":   5
    }, ...
  },

  "valuation":  { ... same structure ... },
  "leverage":   { ... },
  "liquidity":  { ... },
  "efficiency": { ... },

  "growth": {
    "sales_cagr_3y":      {"value": 15.65, "label": "strong"},
    "net_profit_cagr_3y": {"value": 30.42, "label": "excellent"},
    ...
  },

  "per_share": {
    "eps": {
      "values":       {"2016-03-31": 1.69, ...},
      "yoy_change":   {...},
      "yoy_pct":      {...},
      "labels":       {...},
      "latest_value": 7.28,
      "latest_label": "strong",
      "trend":        "strong_uptrend",
      "trend_score":  5
    }, ...
  },

  "summary_scores": {
    "profitability_score": 4.8,
    "valuation_score":     2.1,
    "leverage_score":      5.0,
    "liquidity_score":     3.5,
    "efficiency_score":    3.2,
    "growth_score":        4.5,
    "per_share_score":     4.8,
    "overall_score":       3.9
  },

  "data_quality": { ... from ratios.json ... }
}

Summary Score Computation
--------------------------
For each ratio category:
  - Collect trend_score (1-5) for every ratio in the category
  - Average them → category_score (rounded to 1 dp)
  - overall_score = average of all category scores

These scores give the LLM an immediate quantitative signal
about company quality without reading every individual ratio.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from trend_engine import TrendResult, RatioTrend, GrowthTrend
from constants import DATA_PROCESSED_DIR, LOGS_DIR


# ─────────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────────

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file = LOGS_DIR / "json_formatter.log"
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
# Custom exception
# ---------------------------------------------------------------------------

class JsonFormatterError(Exception):
    """Raised when formatting or file I/O fails."""


# ---------------------------------------------------------------------------
# Main formatter
# ---------------------------------------------------------------------------

class JsonFormatter:
    """
    Merges ratio engine and trend engine outputs into analysis.json.

    Parameters
    ----------
    processed_dir : path-like, optional
        Directory containing ratios.json and where analysis.json is written.
        Defaults to DATA_PROCESSED_DIR from constants.

    Example
    -------
    >>> from trend_engine import TrendEngine
    >>> from json_formatter import JsonFormatter
    >>>
    >>> trend_result = TrendEngine("data/processed").compute_all()
    >>> formatter    = JsonFormatter("data/processed")
    >>> formatter.build(trend_result)
    """

    _RATIOS_FILE   = "ratios.json"
    _ANALYSIS_FILE = "analysis.json"

    def __init__(self, processed_dir: str | Path | None = None) -> None:
        self._dir    = Path(processed_dir) if processed_dir else DATA_PROCESSED_DIR
        self._ratios: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build(self, trend_result: TrendResult) -> dict[str, Any]:
        """
        Build and write analysis.json from trend + ratio data.

        Parameters
        ----------
        trend_result : TrendResult
            Output of TrendEngine.compute_all().

        Returns
        -------
        dict[str, Any]
            The complete analysis dict (also written to analysis.json).

        Raises
        ------
        JsonFormatterError
            If ratios.json is missing or file writing fails.
        """
        logger.info("Building analysis.json — dir: '%s'", self._dir)

        self._load_ratios()

        periods      = self._ratios.get("periods", [])
        latest_period = periods[-1] if periods else None

        analysis: dict[str, Any] = {
            "company":       self._ratios.get("company", "UNKNOWN"),
            "generated_at":  datetime.now().isoformat(timespec="seconds"),
            "period_count":  len(periods),
            "periods":       periods,
            "latest_period": latest_period,
            "profitability": self._format_category(trend_result.profitability),
            "valuation":     self._format_category(trend_result.valuation),
            "leverage":      self._format_category(trend_result.leverage),
            "liquidity":     self._format_category(trend_result.liquidity),
            "efficiency":    self._format_category(trend_result.efficiency),
            "growth":        self._format_growth(trend_result.growth),
            "per_share":     self._format_category(trend_result.per_share),
        }

        analysis["summary_scores"] = self._compute_summary_scores(analysis)
        analysis["data_quality"]   = self._ratios.get("data_quality", {})

        self._write_json(analysis)

        logger.info(
            "analysis.json built — company: %s | periods: %d | "
            "overall_score: %.1f",
            analysis["company"],
            len(periods),
            analysis["summary_scores"].get("overall_score", 0),
        )
        return analysis

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_ratios(self) -> None:
        """Load ratios.json into self._ratios."""
        path = self._dir / self._RATIOS_FILE
        if not path.exists():
            raise JsonFormatterError(
                f"ratios.json not found at '{path}'. "
                "Run ratio_engine.compute_all() first."
            )
        try:
            with path.open(encoding="utf-8") as fh:
                self._ratios = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise JsonFormatterError(
                f"Cannot read ratios.json: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _format_category(
        self,
        category: dict[str, RatioTrend],
    ) -> dict[str, dict[str, Any]]:
        """
        Convert a dict of RatioTrend objects to a plain JSON-serialisable dict.

        Each ratio becomes:
        {
          "values":       {...},
          "yoy_change":   {...},
          "yoy_pct":      {...},
          "labels":       {...},
          "latest_value": ...,
          "latest_label": ...,
          "trend":        ...,
          "trend_score":  ...
        }
        """
        return {
            ratio_name: trend.to_dict()
            for ratio_name, trend in category.items()
        }

    def _format_growth(
        self,
        growth: dict[str, GrowthTrend],
    ) -> dict[str, dict[str, Any]]:
        """
        Convert GrowthTrend objects to plain dicts.

        Each CAGR key becomes:
        {
          "value": 15.65,
          "label": "strong"
        }
        """
        return {
            key: gt.to_dict()
            for key, gt in growth.items()
        }

    # ------------------------------------------------------------------
    # Summary scores
    # ------------------------------------------------------------------

    def _compute_summary_scores(
        self,
        analysis: dict[str, Any],
    ) -> dict[str, float]:
        """
        Compute per-category and overall trend scores.

        For each ratio category:
          - Collect trend_score from every ratio in that category
          - Category score = mean of trend scores (rounded to 1 dp)

        For growth:
          - No trend_score available (scalar CAGRs) — skip from overall

        overall_score = mean of all category scores that have data.

        Returns
        -------
        dict[str, float]
            Keys: <category>_score for each category + overall_score.
        """
        categories = [
            "profitability", "valuation", "leverage",
            "liquidity", "efficiency", "per_share",
        ]

        scores: dict[str, float] = {}
        category_score_values: list[float] = []

        for cat in categories:
            cat_data = analysis.get(cat, {})
            trend_scores = [
                v["trend_score"]
                for v in cat_data.values()
                if isinstance(v, dict) and v.get("trend_score") is not None
            ]
            if trend_scores:
                cat_score = round(sum(trend_scores) / len(trend_scores), 1)
                scores[f"{cat}_score"] = cat_score
                category_score_values.append(cat_score)
                logger.debug(
                    "Category '%s' score: %.1f (from %d ratios)",
                    cat, cat_score, len(trend_scores),
                )
            else:
                logger.debug("Category '%s' has no trend scores — skipped.", cat)

        # Growth score from CAGR labels — convert label to a 1-5 scale
        growth_data = analysis.get("growth", {})
        growth_numeric = self._growth_label_to_score(growth_data)
        if growth_numeric:
            growth_score = round(sum(growth_numeric) / len(growth_numeric), 1)
            scores["growth_score"] = growth_score
            category_score_values.append(growth_score)
            logger.debug(
                "Growth score: %.1f (from %d CAGR values)", growth_score, len(growth_numeric)
            )

        if category_score_values:
            scores["overall_score"] = round(
                sum(category_score_values) / len(category_score_values), 1
            )
        else:
            scores["overall_score"] = 0.0

        logger.info(
            "Summary scores — overall: %.1f | %s",
            scores["overall_score"],
            " | ".join(f"{k}: {v}" for k, v in scores.items() if k != "overall_score"),
        )
        return scores

    @staticmethod
    def _growth_label_to_score(
        growth_data: dict[str, dict[str, Any]],
    ) -> list[float]:
        """
        Convert CAGR classification labels to numeric scores (1–5).

        Label → Score mapping:
          negative  → 1
          slow      → 2
          moderate  → 3
          strong    → 4
          excellent → 5
          None      → excluded
        """
        label_scores: dict[str, float] = {
            "negative":  1.0,
            "slow":      2.0,
            "moderate":  3.0,
            "strong":    4.0,
            "excellent": 5.0,
        }
        result: list[float] = []
        for entry in growth_data.values():
            label = entry.get("label")
            if label and label in label_scores:
                result.append(label_scores[label])
        return result

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _write_json(self, analysis: dict[str, Any]) -> None:
        """Write analysis dict to analysis.json with indent=2."""
        out_path = self._dir / self._ANALYSIS_FILE
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(analysis, fh, indent=2, ensure_ascii=False)
            logger.info(
                "analysis.json written -> %s (%d bytes)",
                out_path, out_path.stat().st_size,
            )
        except OSError as exc:
            raise JsonFormatterError(
                f"Failed to write '{out_path}': {exc}"
            ) from exc