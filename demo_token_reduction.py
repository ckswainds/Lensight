"""
============================================================
  DEMO: How Lensight Reduces LLM Tokens by 80-98%
============================================================

Run this script to see EXACTLY what changes between:
  - BEFORE: Full analysis.json dumped into LLM prompt
  - AFTER:  QueryAnalyzer + compact format

Usage:
  python demo_token_reduction.py
  python demo_token_reduction.py --show-context   # print full LLM context too
"""

import json
import sys
import os

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set UTF-8 output so colors work on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANALYSIS_FILE = "data/processed/analysis.json"

# ANSI color helpers
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

SHOW_CONTEXT = "--show-context" in sys.argv


# -----------------------------------------------------------------------------
# Helper: rough token estimator (GPT/Gemini: ~1 token per 0.75 words)
# -----------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return int(words / 0.75)


def separator(char="=", width=65):
    print(BOLD + char * width + RESET)


def section(title: str):
    separator()
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    separator()


# -----------------------------------------------------------------------------
# APPROACH 1 - "Before":  Full JSON dump (what the old code did)
# -----------------------------------------------------------------------------
def approach_before(data: dict):
    """
    Old approach: convert the entire analysis.json to text and inject it.
    PromptBuilder.build_financial_summary_text() walks every category,
    every ratio, and every historical year value.
    """
    from llm.prompt_builder import PromptBuilder
    full_text = PromptBuilder.build_financial_summary_text(data)
    return full_text, estimate_tokens(full_text)


# -----------------------------------------------------------------------------
# APPROACH 2 - "After":  QueryAnalyzer smart filtering
# -----------------------------------------------------------------------------
def approach_after(query: str, data: dict):
    """
    New approach: classify query intent -> prune data -> compact format.
    """
    from llm.query_analyzer import get_analyzer
    analyzer = get_analyzer()
    context, metadata = analyzer.process_query(query, data)
    return context, estimate_tokens(context), metadata


# -----------------------------------------------------------------------------
# MAIN DEMO
# -----------------------------------------------------------------------------
def main():
    # Load data
    if not os.path.exists(ANALYSIS_FILE):
        print(f"{RED}ERROR: {ANALYSIS_FILE} not found.{RESET}")
        print("  -> Run the pipeline first by uploading an Excel file.")
        sys.exit(1)

    with open(ANALYSIS_FILE, "r") as f:
        data = json.load(f)

    company = data.get("company", "Unknown Company")
    periods = data.get("periods", [])

    print()
    separator()
    print(f"{BOLD}  LENSIGHT TOKEN REDUCTION DEMO{RESET}")
    print(f"  Company : {company}")
    print(f"  Periods : {', '.join(periods) if periods else 'N/A'}")
    separator()

    # -------------------------------------------------------------------------
    # STEP 1 - BASELINE: full JSON
    # -------------------------------------------------------------------------
    section("STEP 1 -- BEFORE: Full analysis.json dumped into LLM prompt")
    full_text, full_tokens = approach_before(data)

    print(f"\n  Raw JSON characters  : {len(json.dumps(data)):,}")
    print(f"  Formatted text chars : {len(full_text):,}")
    print(f"  {RED}{BOLD}Estimated tokens     : {full_tokens:,}{RESET}")
    print(f"\n  [!] Every chat message costs ~{full_tokens:,} tokens")
    print(f"  [!] Gemini Flash free tier = 15 RPM / 1M TPM")
    print(f"  [!] ~{1_000_000 // full_tokens} queries/day before hitting quota")

    if SHOW_CONTEXT:
        print(f"\n{YELLOW}--- FULL CONTEXT SENT TO LLM (first 1500 chars) ---{RESET}")
        print(full_text[:1500])
        print(f"{YELLOW}... (truncated){RESET}\n")

    # -------------------------------------------------------------------------
    # STEP 2 - Show filtered output for each query
    # -------------------------------------------------------------------------
    section("STEP 2 -- AFTER: QueryAnalyzer filters context per query")

    test_queries = [
        ("What is the net profit margin trend?",  "Specific -> PROFITABILITY only"),
        ("How is the P/E ratio?",                 "Specific -> VALUATION only"),
        ("Tell me about liquidity and cash flow", "Specific -> LIQUIDITY only"),
        ("What is the ROE and debt situation?",   "Multi-cat -> PROFITABILITY + LEVERAGE"),
        ("How is the company doing overall?",     "Ambiguous -> fallback summary"),
    ]

    results = []
    for query, label in test_queries:
        context, tokens, meta = approach_after(query, data)
        reduction = (1 - tokens / full_tokens) * 100
        results.append((query, label, context, tokens, reduction, meta))

    # Print table
    print()
    col_q = 44
    col_t = 10
    col_r = 10
    header = (
        f"  {'Query':<{col_q}} {'Tokens':>{col_t}} {'Reduction':>{col_r}}  Categories"
    )
    print(BOLD + header + RESET)
    print("  " + "-" * (col_q + col_t + col_r + 20))

    for query, label, context, tokens, reduction, meta in results:
        cats = ", ".join(meta["categories"]) if meta["categories"] else "fallback"
        ambig = "  [AMBIGUOUS]" if meta["is_ambiguous"] else ""
        colour = GREEN if reduction > 90 else YELLOW if reduction > 70 else RED
        q_short = (query[:col_q - 2] + "..") if len(query) > col_q else query
        print(
            f"  {q_short:<{col_q}} "
            f"{colour}{tokens:>{col_t},}{RESET} "
            f"{colour}{reduction:>{col_r - 1}.1f}%{RESET}  "
            f"{cats}{ambig}"
        )

    print()

    # -------------------------------------------------------------------------
    # STEP 3 - Deep dive on one query
    # -------------------------------------------------------------------------
    section("STEP 3 -- Deep dive: what changes for one query")

    demo_query = "What is the net profit margin trend?"
    context, tokens, meta = approach_after(demo_query, data)
    reduction = (1 - tokens / full_tokens) * 100

    print(f"\n  Query    : \"{demo_query}\"")
    print(f"  Intent   : {meta['categories']}  (confidence: {meta['confidence']:.0%})")
    print(f"  Strategy : {meta['context_type']}")
    print()
    print(f"  {RED}BEFORE{RESET}: {full_tokens:,} tokens  <-- entire analysis.json")
    print(f"  {GREEN}AFTER {RESET}: {tokens:,} tokens  <-- only profitability metrics")
    print()

    bar_width = 50
    before_bar = "#" * bar_width
    after_len  = max(1, int(bar_width * tokens / full_tokens))
    after_bar  = "#" * after_len + "." * (bar_width - after_len)

    print(f"  {RED}Before{RESET}: [{before_bar}] {full_tokens:,} tokens")
    print(f"  {GREEN}After {RESET}: [{after_bar}] {tokens:,} tokens  ({reduction:.1f}% saved)")
    print()

    print(f"{YELLOW}--- CONTEXT ACTUALLY SENT TO LLM ---{RESET}")
    print(context)
    print(f"{YELLOW}{'-' * 65}{RESET}")

    # -------------------------------------------------------------------------
    # STEP 4 - Code walkthrough
    # -------------------------------------------------------------------------
    section("STEP 4 -- How the code does it (3 functions)")

    print(f"""
  {BOLD}Function 1:{RESET}  QueryAnalyzer.analyze_query(question)
  {CYAN}-----------------------------------------------------{RESET}
  -> Regex keyword scan across 7 category dictionaries
  -> "profit" / "margin" / "roe" => MetricCategory.PROFITABILITY
  -> Returns: (categories, confidence, is_ambiguous)
  -> Latency: < 1ms  (no LLM call, pure Python regex)

  {BOLD}Function 2:{RESET}  QueryAnalyzer.get_relevant_metrics(categories, full_data)
  {CYAN}-----------------------------------------------------{RESET}
  -> Extracts ONLY the matching section from analysis.json
  -> full_data has 7 sections => keeps 1 (or 2 for multi-category)
  -> Discards 85-90% of data before it ever reaches formatting

  {BOLD}Function 3:{RESET}  QueryAnalyzer.build_compact_context(filtered_data)
  {CYAN}-----------------------------------------------------{RESET}
  -> Converts remaining data to compact bullet text (NOT raw JSON)
  -> "Net Profit Margin: 15.85% (+0.34 YoY)"    <- ~7 tokens
  -> vs "15.85 (2023), 15.51 (2022), 14.20 (2021)..." <- 20+ tokens
  -> Only latest value + YoY change, not the full time series
""")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    section("SUMMARY")

    min_tokens = min(r[3] for r in results)
    max_tokens = max(r[3] for r in results)
    avg_tokens = int(sum(r[3] for r in results) / len(results))
    avg_reduction = sum(r[4] for r in results) / len(results)

    print(f"""
  Full context (baseline)  : {RED}{full_tokens:>8,} tokens{RESET}
  Specific query (best)    : {GREEN}{min_tokens:>8,} tokens{RESET}  ({(1-min_tokens/full_tokens)*100:.1f}% reduction)
  Ambiguous query (worst)  : {YELLOW}{max_tokens:>8,} tokens{RESET}  ({(1-max_tokens/full_tokens)*100:.1f}% reduction)
  Average across queries   : {GREEN}{avg_tokens:>8,} tokens{RESET}  ({avg_reduction:.1f}% avg reduction)

  Cost impact (Gemini Flash @ $0.075/1M tokens):
    Before : ${full_tokens * 0.075 / 1_000_000:.5f} per query
    After  : ${avg_tokens * 0.075 / 1_000_000:.5f} per query

  Free-tier headroom:
    Before : ~{1_000_000 // full_tokens:,} queries before quota hit
    After  : ~{1_000_000 // max(avg_tokens, 1):,}+ queries before quota hit

  Tip: run with --show-context to see the full before-context printed
""")


if __name__ == "__main__":
    main()
