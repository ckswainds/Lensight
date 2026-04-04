"""
dashboard/pipeline_runner.py
-----------------------------
Runs the full Lensight analysis pipeline in a background thread
so the Dash UI stays responsive during processing.

The pipeline runner maintains a global PipelineStatus object that
callbacks poll every 500ms to update the loading screen.
"""

import base64
import json
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

from constants import ANALYSIS_READY_FLAG


def _analysis_ready_path(processed_dir: Path) -> Path:
    """Same relative flag as ANALYSIS_READY_FLAG but under the active processed dir."""
    return processed_dir / ANALYSIS_READY_FLAG.name


def _write_analysis_ready_marker(processed_dir: Path) -> None:
    """Signal that analysis.json is complete (for polling across workers)."""
    path = _analysis_ready_path(processed_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    logger.info("Wrote analysis-ready marker: %s", path)


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
    DONE        = "done"
    ERROR       = "error"

class RAGStatus(str, Enum):
    IDLE       = "idle"         # No PDF uploaded
    LOADING    = "loading"      # Reading/parsing PDF
    CHUNKING   = "chunking"     # Splitting into chunks
    EMBEDDING  = "embedding"    # Embedding in progress
    STORING    = "storing"      # Storing vectors
    READY      = "ready"        # Indexing complete
    ERROR      = "error"        # Indexing failed
    
    # Backwards compatibility
    INDEXING   = "embedding"    # Old name maps to embedding


# Human-readable label + progress % per stage
_STAGE_META: dict[Stage, tuple[str, int]] = {
    Stage.IDLE:         ("Waiting for upload",             0),
    Stage.FLUSHING:     ("Clearing previous data...",     10),
    Stage.PARSING:      ("Parsing Excel file...",          25),
    Stage.PROCESSING:   ("Cleaning & normalising...",      42),
    Stage.RATIOS:       ("Computing financial ratios...",  58),
    Stage.TRENDS:       ("Analysing trends...",            74),
    Stage.FORMATTING:   ("Building analysis output...",    84),
    Stage.DONE:         ("Analysis complete!",            100),
    Stage.ERROR:        ("Pipeline failed",                 0),
}


@dataclass
class PipelineStatus:
    """Thread-safe pipeline status container."""
    stage:       Stage  = Stage.IDLE
    rag_status:  RAGStatus = RAGStatus.IDLE
    progress:    int    = 0
    label:       str    = "Waiting for upload"
    error:       str    = ""
    company:     str    = ""
    started_at:  str    = ""
    done_at:     str    = ""
    # RAG progress tracking
    rag_progress: int   = 0      # 0-100%
    rag_label:    str   = ""     # e.g., "Embedding: 45/120 chunks"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, stage: Stage, error: str = "") -> None:
        label, progress = _STAGE_META[stage]
        with self._lock:
            self.stage    = stage
            self.progress = progress
            self.label    = label
            self.error    = error

    def update_rag(self, status: RAGStatus, progress: int = 0, label: str = "") -> None:
        with self._lock:
            self.rag_status = status
            self.rag_progress = max(0, min(100, progress))  # Clamp 0-100
            self.rag_label = label

    def set_company(self, name: str) -> None:
        with self._lock:
            self.company = name

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stage":       self.stage.value,
                "rag_status":  self.rag_status.value,
                "rag_progress": self.rag_progress,
                "rag_label":   self.rag_label,
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

        # Disk marker first so any worker/instance reading the same filesystem
        # can redirect even if this process's in-memory _status is not polled.
        _write_analysis_ready_marker(processed_dir)

        # ── SIGNAL CORE DONE ─────────────────────────────────────
        # Mark core analysis as DONE so the UI redirects to the dashboard.
        _status.update(Stage.DONE)
        with _status._lock:
            _status.done_at = datetime.now().isoformat(timespec="seconds")
        logger.info("Core analysis complete. RAG indexing starting in background...")

        # ── Stage: RAG_INDEXING ──────────────────────────────────
        # First, check if PDF exists — only proceed if one was uploaded
        global _rag_store
        _rag_store = None
        pdf_files = list(uploads_dir.glob("*.pdf"))
        
        if not pdf_files:
            # No PDF uploaded — skip RAG entirely
            _status.update_rag(RAGStatus.IDLE, 0, "No annual report uploaded")
            logger.info("No PDF found for RAG — staying in IDLE state.")
        else:
            # PDF exists — proceed with indexing
            pdf_path = pdf_files[0]
            logger.info("PDF found for RAG: %s", pdf_path.name)
            
            try:
                # ── LOADING: Read PDF
                _status.update_rag(RAGStatus.LOADING, 5, "Reading annual report...")
                from ingestion.unstructured_loader import UnstructuredLoader
                chunks = UnstructuredLoader().load_pdf(str(pdf_path))
                logger.info(f"PDF loaded with {len(chunks)} chunks")
                
                # ── CHUNKING: Already done by loader
                _status.update_rag(RAGStatus.CHUNKING, 15, f"Processing {len(chunks)} document chunks...")
                logger.info(f"[RAG] {len(chunks)} chunks ready for embedding")
                
                # ── EMBEDDING: Build vector store with progress tracking
                def progress_callback(current: int, total: int, label: str):
                    """Update progress during embedding."""
                    if total > 0:
                        progress_pct = 30 + int((current / total) * 50)  # 30-80% range
                        _status.update_rag(RAGStatus.EMBEDDING, progress_pct, f"Embedding: {current}/{total} chunks")
                        logger.debug(f"[RAG] Embedding progress: {current}/{total} ({progress_pct}%)")
                
                from rag.vector_store import LensightVectorStore
                vs = LensightVectorStore(batch_size=10, num_workers=4)
                vs.build_from_documents(chunks, progress_callback=progress_callback)
                
                # ── STORING: Complete
                _status.update_rag(RAGStatus.STORING, 85, "Finalizing index...")
                _rag_store = vs
                _status.update_rag(RAGStatus.READY, 100, "Annual report ready")
                logger.info("RAG indexing finished successfully.")
                
            except Exception as rag_exc:
                logger.warning("RAG indexing failed in background: %s", rag_exc)
                _status.update_rag(RAGStatus.ERROR, 0, f"Error: {str(rag_exc)[:50]}")

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
    """
    if not _running.acquire(blocking=False):
        logger.warning("Pipeline already running.")
        return False

    _status.update(Stage.FLUSHING)
    _status.rag_status = RAGStatus.IDLE

    def _worker():
        try:
            run_pipeline(
                file_content_b64, filename,
                uploads_dir, raw_dir, processed_dir,
            )
        except Exception:
            logger.exception("Pipeline worker exited with uncaught exception")
        finally:
            _running.release()

    thread = threading.Thread(target=_worker, daemon=True, name="lensight-pipeline")
    thread.start()
    logger.info("Pipeline thread started for file: %s", filename)
    return True