"""
dashboard/pipeline_runner.py
-----------------------------
Runs the full Lensight analysis pipeline in a background thread
so the Dash UI stays responsive during processing.

The pipeline runner maintains a global PipelineStatus object that
callbacks poll every 500ms to update the loading screen.

Flow
----
  1. Flush data/raw/, data/processed/, data/uploads/
  2. Save uploaded .xlsx to data/uploads/
  3. Run ExcelParser      → data/raw/
  4. Run Preprocessor     → data/processed/
  5. Run RatioEngine      → data/processed/ratios.json
  6. Run TrendEngine      (in memory)
  7. Run JsonFormatter    → data/processed/analysis.json
  8. Mark status DONE or ERROR

Thread safety
-------------
PipelineStatus uses a threading.Lock for all reads/writes.
Only one pipeline run is allowed at a time (guarded by _running flag).
"""

import base64
import logging
import shutil
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status types
# ---------------------------------------------------------------------------

class Stage(str, Enum):
    IDLE        = "idle"
    FLUSHING    = "flushing"
    PARSING     = "parsing"
    PROCESSING  = "processing"
    RATIOS      = "ratios"
    TRENDS      = "trends"
    FORMATTING  = "formatting"
    RAG_INDEXING = "rag_indexing"
    DONE        = "done"
    ERROR       = "error"


# Human-readable label + progress % per stage
_STAGE_META: dict[Stage, tuple[str, int]] = {
    Stage.IDLE:         ("Waiting for upload",             0),
    Stage.FLUSHING:     ("Clearing previous data...",     10),
    Stage.PARSING:      ("Parsing Excel file...",          25),
    Stage.PROCESSING:   ("Cleaning & normalising...",      42),
    Stage.RATIOS:       ("Computing financial ratios...",  58),
    Stage.TRENDS:       ("Analysing trends...",            74),
    Stage.FORMATTING:   ("Building analysis output...",    84),
    Stage.RAG_INDEXING: ("Indexing annual report PDF...",  93),
    Stage.DONE:         ("Analysis complete!",            100),
    Stage.ERROR:        ("Pipeline failed",                 0),
}


@dataclass
class PipelineStatus:
    """Thread-safe pipeline status container."""
    stage:      Stage  = Stage.IDLE
    progress:   int    = 0
    label:      str    = "Waiting for upload"
    error:      str    = ""
    company:    str    = ""
    started_at: str    = ""
    done_at:    str    = ""
    _lock:      threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, stage: Stage, error: str = "") -> None:
        label, progress = _STAGE_META[stage]
        with self._lock:
            self.stage    = stage
            self.progress = progress
            self.label    = label
            self.error    = error

    def set_company(self, name: str) -> None:
        with self._lock:
            self.company = name

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stage":      self.stage.value,
                "progress":   self.progress,
                "label":      self.label,
                "error":      self.error,
                "company":    self.company,
                "started_at": self.started_at,
                "done_at":    self.done_at,
            }


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_status  = PipelineStatus()
_running = threading.Lock()   # prevents concurrent runs
_rag_store = None             # holds the built ChromaDB vector store


def get_status() -> dict[str, Any]:
    """Return current pipeline status as a plain dict (safe to store in dcc.Store)."""
    return _status.to_dict()


def get_rag_store():
    """Return the built RAG vector store (or None if no PDF was indexed)."""
    return _rag_store


def is_idle() -> bool:
    return _status.stage in (Stage.IDLE, Stage.DONE, Stage.ERROR)


# ---------------------------------------------------------------------------
# Flush helpers
# ---------------------------------------------------------------------------

def _flush_dir(path: Path) -> None:
    """Delete all contents of a directory, keep the directory itself."""
    if path.exists():
        for item in path.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    else:
        path.mkdir(parents=True, exist_ok=True)
    logger.debug("Flushed: %s", path)


def flush_all_data(uploads_dir: Path, raw_dir: Path, processed_dir: Path) -> None:
    """
    Wipe all previous pipeline data before a new run.
    Ensures no stale files from a prior company interfere.

    PDFs in uploads/ are preserved — they are used by the RAG pipeline
    and are not regenerated by the analysis pipeline.
    Only .xlsx files and all raw/processed data are cleared.
    """
    logger.info("Flushing previous pipeline data...")

    # Flush raw and processed entirely
    _flush_dir(raw_dir)
    _flush_dir(processed_dir)

    # Flush uploads — remove xlsx only, keep PDFs for RAG
    if uploads_dir.exists():
        for item in uploads_dir.iterdir():
            if item.is_file() and item.suffix.lower() in (".xlsx", ".xls"):
                item.unlink()
                logger.debug("Removed upload: %s", item.name)
            elif item.is_dir():
                shutil.rmtree(item)
    else:
        uploads_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Flush complete — PDFs preserved in uploads/.")


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(
    file_content_b64: str,
    filename: str,
    uploads_dir: Path,
    raw_dir:      Path,
    processed_dir: Path,
) -> None:
    """
    Run the full analysis pipeline synchronously.
    Always called from a background thread via start_pipeline().

    Parameters
    ----------
    file_content_b64 : str
        Base64-encoded file content from dcc.Upload (strip data URI prefix first).
    filename : str
        Original filename of the uploaded file.
    uploads_dir / raw_dir / processed_dir : Path
        Data directories from constants.py.
    """
    import sys
    root = Path(__file__).parent.parent.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        # ── Stage: FLUSHING ──────────────────────────────────────
        _status.update(Stage.FLUSHING)
        with _status._lock:
            _status.started_at = datetime.now().isoformat(timespec="seconds")

        flush_all_data(uploads_dir, raw_dir, processed_dir)

        # ── Decode and save uploaded file ────────────────────────
        xlsx_path = uploads_dir / filename
        file_bytes = base64.b64decode(file_content_b64)
        xlsx_path.write_bytes(file_bytes)
        logger.info("Saved upload: %s (%d bytes)", filename, len(file_bytes))

        # ── Stage: PARSING ───────────────────────────────────────
        _status.update(Stage.PARSING)
        from ingestion.excel_parser import ExcelParser
        parser = ExcelParser(xlsx_path, raw_dir)
        parse_result = parser.parse_all()
        _status.set_company(parse_result.company_name)
        logger.info("Parsed: %s", parse_result.company_name)

        # ── Stage: PROCESSING ────────────────────────────────────
        _status.update(Stage.PROCESSING)
        from ingestion.preprocessor import process_raw_data_pipeline
        process_raw_data_pipeline(
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            scale_to="auto",
            exclude_from_scaling=["no_of_equity_shares", "face_value"],
            fillna_value=0.0,
        )
        logger.info("Preprocessing complete.")

        # ── Stage: RATIOS ────────────────────────────────────────
        _status.update(Stage.RATIOS)
        from analysis.ratio_engine import RatioEngine
        ratio_result = RatioEngine(processed_dir).compute_all()
        logger.info("Ratios computed: %d periods.", len(ratio_result.periods))

        # ── Stage: TRENDS ────────────────────────────────────────
        _status.update(Stage.TRENDS)
        from analysis.trend_engine import TrendEngine
        trend_result = TrendEngine(processed_dir).compute_all()
        logger.info("Trends computed.")

        # ── Stage: FORMATTING ────────────────────────────────────
        _status.update(Stage.FORMATTING)
        from analysis.json_formatter import JsonFormatter
        JsonFormatter(processed_dir).build(trend_result)
        logger.info("analysis.json written.")

        # ── Stage: RAG_INDEXING ──────────────────────────────────
        _status.update(Stage.RAG_INDEXING)
        global _rag_store
        _rag_store = None   # reset from prior session
        try:
            pdf_files = list(uploads_dir.glob("*.pdf"))
            if pdf_files:
                pdf_path = pdf_files[0]
                logger.info("Indexing PDF for RAG: %s", pdf_path.name)
                from ingestion.unstructured_loader import UnstructuredLoader
                from rag.vector_store import LensightVectorStore
                chunks = UnstructuredLoader().load_pdf(str(pdf_path))
                vs = LensightVectorStore()
                vs.build_from_documents(chunks)
                _rag_store = vs
                logger.info("RAG index built: %d chunks.", len(chunks))
            else:
                logger.info("No PDF found — skipping RAG indexing.")
        except Exception as rag_exc:
            # RAG failure is non-fatal — log and continue
            logger.warning("RAG indexing failed (non-fatal): %s", rag_exc)

        # ── DONE ─────────────────────────────────────────────────
        _status.update(Stage.DONE)
        with _status._lock:
            _status.done_at = datetime.now().isoformat(timespec="seconds")
        logger.info("Pipeline complete for '%s'.", parse_result.company_name)

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)
        _status.update(Stage.ERROR, error=str(exc))


def start_pipeline(
    file_content_b64: str,
    filename: str,
    uploads_dir: Path,
    raw_dir: Path,
    processed_dir: Path,
) -> bool:
    """
    Launch the pipeline in a daemon background thread.

    Returns True if started, False if a pipeline is already running.
    """
    if not _running.acquire(blocking=False):
        logger.warning("Pipeline already running — ignoring new request.")
        return False

    _status.update(Stage.FLUSHING)

    def _worker():
        try:
            run_pipeline(
                file_content_b64, filename,
                uploads_dir, raw_dir, processed_dir,
            )
        finally:
            _running.release()

    thread = threading.Thread(target=_worker, daemon=True, name="lensight-pipeline")
    thread.start()
    logger.info("Pipeline thread started for file: %s", filename)
    return True