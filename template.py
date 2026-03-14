"""
╔══════════════════════════════════════════════════════════════════╗
║              LENSIGHT — Project Scaffold Generator               ║
║         Fundamental Analysis Platform  |  template.py            ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python template.py

Creates the full Lensight project directory structure with all
folders, __init__.py stubs, and placeholder module files.
Run once before starting development.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────────────────────────
#  Logging Setup
# ─────────────────────────────────────────────────────────────────

LOG_FORMAT  = "%(asctime)s | %(levelname)-8s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("lensight.scaffold")


# ─────────────────────────────────────────────────────────────────
#  Project Root
# ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path("lensight")


# ─────────────────────────────────────────────────────────────────
#  Directory Structure
# ─────────────────────────────────────────────────────────────────

DIRECTORIES: list[str] = [
    "data/uploads",
    "data/raw",
    "data/processed",
    "data/vector_store",
    "ingestion",
    "analysis",
    "rag",
    "llm",
    "dashboard/assets",
    "tests",
    "logs",
]


# ─────────────────────────────────────────────────────────────────
#  Files to Create  (relative path → stub content)
# ─────────────────────────────────────────────────────────────────

FILES: dict[str, str] = {

    # ── Root ─────────────────────────────────────────────────────

    "main.py": '"""Lensight — Application Entry Point.\nOrchestrates the full pipeline end to end.\n"""\n',

    "config.py": '"""Lensight — Global Configuration.\nCentralizes env vars, file paths, model settings, and constants.\n"""\n',

    "requirements.txt": (
        "# Lensight Dependencies\n"
        "pandas>=2.2.0\n"
        "openpyxl>=3.1.2\n"
        "numpy>=1.26.0\n"
        "python-dotenv>=1.0.0\n"
        "openai>=1.30.0\n"
        "anthropic>=0.28.0\n"
        "chromadb>=0.5.0\n"
        "faiss-cpu>=1.8.0\n"
        "sentence-transformers>=3.0.0\n"
        "pdfplumber>=0.11.0\n"
        "beautifulsoup4>=4.12.0\n"
        "lxml>=5.2.0\n"
        "dash>=2.17.0\n"
        "plotly>=5.22.0\n"
        "dash-bootstrap-components>=1.6.0\n"
        "pytest>=8.2.0\n"
        "pytest-cov>=5.0.0\n"
        "pydantic>=2.7.0\n"
        "tenacity>=8.3.0\n"
        "tqdm>=4.66.0\n"
    ),

    ".env.example": (
        "# Copy to .env and fill in values. Never commit .env.\n\n"
        "LLM_PROVIDER=openai\n"
        "LLM_MODEL=gpt-4o\n"
        "LLM_TEMPERATURE=0.3\n"
        "LLM_MAX_TOKENS=2048\n"
        "OPENAI_API_KEY=sk-...\n"
        "ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "EMBEDDING_MODEL=text-embedding-3-small\n"
        "VECTOR_STORE_TYPE=chroma\n"
        "RETRIEVAL_TOP_K=5\n\n"
        "DASHBOARD_HOST=0.0.0.0\n"
        "DASHBOARD_PORT=8050\n"
        "DASHBOARD_DEBUG=false\n\n"
        "LOG_LEVEL=INFO\n"
    ),

    ".gitignore": (
        ".env\n__pycache__/\n*.py[cod]\n*.egg-info/\ndist/\nbuild/\n"
        "data/uploads/\ndata/raw/\ndata/processed/\ndata/vector_store/\n"
        "logs/\n.vscode/\n.idea/\n.pytest_cache/\n.coverage\nhtmlcov/\n"
    ),

    "README.md": (
        "# Lensight — Fundamental Analysis Platform\n\n"
        "> AI-powered fundamental analysis for Indian equities.\n\n"
        "## Pipeline\n"
        "```\n"
        "uploads/*.xlsx\n"
        "  └─► excel_parser    → data/raw/          (pnl, balance_sheet, cash_flow, quarters, meta)\n"
        "        └─► preprocessor  → data/processed/   (cleaned, typed, normalized)\n"
        "              └─► ratio_engine   → financial ratios\n"
        "              └─► trend_engine   → YoY, CAGR, trend direction\n"
        "                    └─► llm/orchestrator → narrative generation\n"
        "                          └─► dashboard   → Plotly/Dash UI\n"
        "```\n\n"
        "## Quickstart\n"
        "```bash\npip install -r requirements.txt\ncp .env.example .env\npython main.py\n```\n"
    ),

    # ── Data placeholders ─────────────────────────────────────────

    "data/uploads/.gitkeep":      "",
    "data/raw/.gitkeep":          "",
    "data/processed/.gitkeep":    "",
    "data/vector_store/.gitkeep": "",

    # ── Ingestion ─────────────────────────────────────────────────

    "ingestion/__init__.py":            '"""Lensight — Ingestion Package."""\n',
    "ingestion/excel_parser.py":        '"""Excel Parser: uploads/*.xlsx  →  data/raw/ CSVs."""\n',
    "ingestion/preprocessor.py":        '"""Preprocessor: data/raw/  →  data/processed/ (clean, typed)."""\n',
    "ingestion/unstructured_loader.py": '"""Unstructured Loader: PDF/HTML  →  text chunks for RAG."""\n',
    "ingestion/data_cleaner.py":        '"""Shared data cleaning utility functions."""\n',

    # ── Analysis ──────────────────────────────────────────────────

    "analysis/__init__.py":             '"""Lensight — Analysis Package."""\n',
    "analysis/ratio_engine.py":         '"""Ratio Engine: reads processed/ CSVs → computes financial ratios."""\n',
    "analysis/trend_engine.py":         '"""Trend Engine: YoY growth, CAGR, trend direction."""\n',
    "analysis/classification_rules.py": '"""Classification Rules: labels ratios as Strong/Weak/Improving etc."""\n',
    "analysis/json_formatter.py":       '"""JSON Formatter: structured output builder for LLM consumption."""\n',

    # ── RAG ───────────────────────────────────────────────────────

    "rag/__init__.py":     '"""Lensight — RAG Package."""\n',
    "rag/embedder.py":     '"""Embedder: text → vector conversion via embedding model."""\n',
    "rag/vector_store.py": '"""Vector Store: interface for ChromaDB / FAISS."""\n',
    "rag/retriever.py":    '"""Retriever: semantic search over the vector store."""\n',

    # ── LLM ───────────────────────────────────────────────────────

    "llm/__init__.py":            '"""Lensight — LLM Package."""\n',
    "llm/prompt_builder.py":      '"""Prompt Builder: constructs dynamic prompts from ratio + RAG context."""\n',
    "llm/orchestrator.py":        '"""Orchestrator: manages LLM call flow and chaining."""\n',
    "llm/narrative_generator.py": '"""Narrative Generator: produces final fundamental analysis text."""\n',

    # ── Dashboard ─────────────────────────────────────────────────

    "dashboard/__init__.py":   '"""Lensight — Dashboard Package."""\n',
    "dashboard/app.py":        '"""Dash App: entry point for the Plotly/Dash web application."""\n',
    "dashboard/layout.py":     '"""Layout: page structure and component definitions."""\n',
    "dashboard/callbacks.py":  '"""Callbacks: Dash event listeners and interactivity logic."""\n',
    "dashboard/charts.py":     '"""Charts: reusable Plotly chart builder functions."""\n',
    "dashboard/assets/style.css": "/* Lensight — Global Styles */\n",

    # ── Tests ─────────────────────────────────────────────────────

    "tests/__init__.py":          '"""Lensight — Test Suite."""\n',
    "tests/test_excel_parser.py":  '"""Tests for ingestion/excel_parser.py"""\n',
    "tests/test_preprocessor.py":  '"""Tests for ingestion/preprocessor.py"""\n',
    "tests/test_ratio_engine.py":  '"""Tests for analysis/ratio_engine.py"""\n',
    "tests/test_retriever.py":     '"""Tests for rag/retriever.py"""\n',
    "tests/test_orchestrator.py":  '"""Tests for llm/orchestrator.py"""\n',
}


# ─────────────────────────────────────────────────────────────────
#  Scaffold Functions
# ─────────────────────────────────────────────────────────────────

def create_directories() -> None:
    """Create all project directories under PROJECT_ROOT."""
    logger.info("Creating directories under '%s/'...", PROJECT_ROOT)
    created = 0
    for rel_dir in DIRECTORIES:
        full_path = PROJECT_ROOT / rel_dir
        try:
            full_path.mkdir(parents=True, exist_ok=True)
            logger.debug("  [DIR]  %s", full_path)
            created += 1
        except OSError as exc:
            logger.error("Failed to create directory '%s': %s", full_path, exc)
            raise
    logger.info("Directories ready: %d", created)


def create_files() -> None:
    """Write all stub files under PROJECT_ROOT."""
    logger.info("Creating stub files...")
    created = 0
    skipped = 0
    for rel_path, content in FILES.items():
        full_path = PROJECT_ROOT / rel_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                logger.warning("  [SKIP] Already exists — %s", full_path)
                skipped += 1
                continue
            full_path.write_text(content, encoding="utf-8")
            logger.debug("  [FILE] %s", full_path)
            created += 1
        except OSError as exc:
            logger.error("Failed to write file '%s': %s", full_path, exc)
            raise
    logger.info("Files created: %d  |  Skipped (already exist): %d", created, skipped)


def print_tree(root: Path, prefix: str = "") -> None:
    """Recursively print a visual directory tree."""
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError as exc:
        logger.warning("Cannot read directory '%s': %s", root, exc)
        return
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        print(prefix + connector + entry.name)
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            print_tree(entry, prefix + extension)


# ─────────────────────────────────────────────────────────────────
#  Main Scaffold Entry Point
# ─────────────────────────────────────────────────────────────────

def scaffold() -> None:
    """Create the full Lensight project structure."""
    start = datetime.now()

    logger.info("=" * 60)
    logger.info("  LENSIGHT — Project Scaffold")
    logger.info("  Target : %s", PROJECT_ROOT.resolve())
    logger.info("=" * 60)

    if PROJECT_ROOT.exists():
        logger.warning(
            "Project root '%s' already exists. "
            "Existing files will be skipped; new ones added.",
            PROJECT_ROOT,
        )
    else:
        try:
            PROJECT_ROOT.mkdir(parents=True)
            logger.info("Created project root: %s/", PROJECT_ROOT)
        except OSError as exc:
            logger.critical("Cannot create project root '%s': %s", PROJECT_ROOT, exc)
            sys.exit(1)

    try:
        create_directories()
        create_files()
    except OSError:
        logger.critical(
            "Scaffold aborted due to filesystem error. "
            "Check permissions and retry.",
            exc_info=True,
        )
        sys.exit(1)
    except Exception as exc:                          # noqa: BLE001
        logger.critical("Unexpected scaffold failure: %s", exc, exc_info=True)
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds()

    logger.info("-" * 60)
    logger.info("Scaffold complete in %.2fs", elapsed)
    logger.info("-" * 60)

    # Print visual tree
    print(f"\n{PROJECT_ROOT}/")
    print_tree(PROJECT_ROOT)

    print(
        f"\n✅  Lensight scaffolded at '{PROJECT_ROOT.resolve()}'\n"
        "\n"
        "    Next steps:\n"
        f"    1.  cd {PROJECT_ROOT}\n"
        "    2.  cp .env.example .env       # fill in your API keys\n"
        "    3.  pip install -r requirements.txt\n"
        "    4.  Start coding → ingestion/excel_parser.py\n"
    )


# ─────────────────────────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scaffold()