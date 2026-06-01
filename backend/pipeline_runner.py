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
    return processed_dir / ANALYSIS_READY_FLAG.name


def _write_analysis_ready_marker(processed_dir: Path) -> None:
    path = _analysis_ready_path(processed_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    logger.info("Wrote analysis-ready marker: %s", path)


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
    IDLE       = "idle"
    LOADING    = "loading"
    CHUNKING   = "chunking"
    EMBEDDING  = "embedding"
    STORING    = "storing"
    READY      = "ready"
    ERROR      = "error"
    INDEXING   = "embedding"


class SummaryStatus(str, Enum):
    IDLE       = "idle"
    GENERATING = "generating"
    READY      = "ready"
    ERROR      = "error"


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
    stage:          Stage         = Stage.IDLE
    rag_status:     RAGStatus     = RAGStatus.IDLE
    summary_status: SummaryStatus = SummaryStatus.IDLE
    summary_error:  str           = ""
    progress:       int           = 0
    label:          str           = "Waiting for upload"
    error:          str           = ""
    company:        str           = ""
    started_at:     str           = ""
    done_at:        str           = ""
    rag_progress:   int           = 0
    rag_label:      str           = ""
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
            self.rag_status   = status
            self.rag_progress = max(0, min(100, progress))
            self.rag_label    = label

    def update_summary(self, status: SummaryStatus, error: str = "") -> None:
        with self._lock:
            self.summary_status = status
            self.summary_error  = error

    def set_company(self, name: str) -> None:
        with self._lock:
            self.company = name

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stage":          self.stage.value,
                "rag_status":     self.rag_status.value,
                "summary_status": self.summary_status.value,
                "summary_error":  self.summary_error,
                "rag_progress":   self.rag_progress,
                "rag_label":      self.rag_label,
                "progress":       self.progress,
                "label":          self.label,
                "error":          self.error,
                "company":        self.company,
                "started_at":     self.started_at,
                "done_at":        self.done_at,
            }


_status    = PipelineStatus()
_running   = threading.Lock()
_rag_store = None


def get_status() -> dict[str, Any]:
    return _status.to_dict()


def reset_status() -> None:
    _status.update(Stage.IDLE)
    _status.update_rag(RAGStatus.IDLE)
    _status.update_summary(SummaryStatus.IDLE, error="")
    global _rag_store
    _rag_store = None
    with _status._lock:
        _status.company      = ""
        _status.progress     = 0
        _status.rag_progress = 0
        _status.error        = ""


def get_rag_store():
    return _rag_store


def is_idle() -> bool:
    return _status.stage in (Stage.IDLE, Stage.DONE, Stage.ERROR)


def _flush_dir(path: Path) -> None:
    """Delete all contents of a directory, keeping the directory itself."""
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
    """Wipe all previous pipeline data before a new run."""
    logger.info("Flushing previous pipeline data...")
    _flush_dir(raw_dir)
    _flush_dir(processed_dir)
    _flush_dir(uploads_dir)
    logger.info("Flush complete.")


def run_pipeline(
    excel_filename: str,
    pdf_filename: str | None,
    uploads_dir: Path,
    raw_dir:      Path,
    processed_dir: Path,
) -> None:
    """Run the full analysis pipeline synchronously."""
    import sys
    root = Path(__file__).parent.parent.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        _status.update(Stage.FLUSHING)
        with _status._lock:
            _status.started_at = datetime.now().isoformat(timespec="seconds")

        _flush_dir(raw_dir)
        _flush_dir(processed_dir)

        xlsx_path = uploads_dir / excel_filename
        logger.info("Using Excel file: %s", xlsx_path)

        _status.update(Stage.PARSING)
        from ingestion.excel_parser import ExcelParser
        parser = ExcelParser(xlsx_path, raw_dir)
        parse_result = parser.parse_all()
        _status.set_company(parse_result.company_name)
        logger.info("Parsed: %s", parse_result.company_name)

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

        _status.update(Stage.RATIOS)
        from analysis.ratio_engine import RatioEngine
        ratio_result = RatioEngine(processed_dir).compute_all()
        logger.info("Ratios computed: %d periods.", len(ratio_result.periods))

        _status.update(Stage.TRENDS)
        from analysis.trend_engine import TrendEngine
        trend_result = TrendEngine(processed_dir).compute_all()
        logger.info("Trends computed.")

        _status.update(Stage.FORMATTING)
        from analysis.json_formatter import JsonFormatter
        analysis_data = JsonFormatter(processed_dir).build(trend_result)
        logger.info("analysis.json written.")

        _write_analysis_ready_marker(processed_dir)
        _status.update(Stage.DONE)
        with _status._lock:
            _status.done_at = datetime.now().isoformat(timespec="seconds")
        logger.info("Core analysis complete. Starting background AI generation...")

        def _generate_summary_task():
            try:
                _status.update_summary(SummaryStatus.GENERATING)

                from config import config as _cfg
                missing_keys = []
                if not _cfg.GEMINI_API_KEY:
                    missing_keys.append("GEMINI_API_KEY")
                if not _cfg.HUGGINGFACEHUB_API_TOKEN:
                    missing_keys.append("HUGGINGFACEHUB_API_TOKEN")

                if missing_keys:
                    logger.error("Missing required API keys: %s", ", ".join(missing_keys))
                    _status.update_summary(SummaryStatus.ERROR, error="config_missing")
                    return

                import json as _json
                from llm.narrative_generator import NarrativeGenerator

                logger.info("Starting LLM financial narrative synthesis...")
                gen = NarrativeGenerator()

                logger.info("Invoking LLM router (timeout: %ds)...", _cfg.LLM_TIMEOUT)
                narrative = gen.generate_narrative(financial_data=analysis_data)

                if not narrative:
                    raise ValueError("LLM returned empty narrative")

                analysis_path = processed_dir / "analysis.json"
                with open(analysis_path, "r", encoding="utf-8") as _f:
                    _doc = _json.load(_f)
                _doc["llm_financial_summary"] = narrative
                with open(analysis_path, "w", encoding="utf-8") as _f:
                    _json.dump(_doc, _f, indent=2, ensure_ascii=False)

                logger.info("Narrative synthesis complete (%d chars)", len(narrative))
                _status.update_summary(SummaryStatus.READY)
            except Exception as _narr_exc:
                logger.error("Narrative generation failed: %s: %s", type(_narr_exc).__name__, _narr_exc)
                err_str = str(_narr_exc).lower()
                if any(x in err_str for x in ['429', 'quota', 'exhausted', 'rate']):
                    _status.update_summary(SummaryStatus.ERROR, error="quota")
                elif any(x in err_str for x in ['timeout', 'deadline', 'timed out']):
                    _status.update_summary(SummaryStatus.ERROR, error="timeout")
                else:
                    _status.update_summary(SummaryStatus.ERROR, error="generic")

        summary_thread = threading.Thread(
            target=_generate_summary_task, daemon=True, name="lensight-summary"
        )
        summary_thread.start()

        def _rag_indexing_task():
            global _rag_store
            _rag_store = None

            if not pdf_filename:
                _status.update_rag(RAGStatus.IDLE, 0, "No annual report uploaded")
                logger.info("No PDF provided — skipping RAG indexing.")
                return

            pdf_path = uploads_dir / pdf_filename
            if not pdf_path.exists():
                logger.warning("PDF not found: %s", pdf_path)
                _status.update_rag(RAGStatus.ERROR, 0, "Error: PDF file missing")
                return

            try:
                _status.update_rag(RAGStatus.LOADING, 5, "Reading annual report...")
                from ingestion.unstructured_loader import UnstructuredLoader
                chunks = UnstructuredLoader().load_pdf(str(pdf_path))

                _status.update_rag(RAGStatus.CHUNKING, 15, f"Processing {len(chunks)} document chunks...")

                def progress_callback(current: int, total: int, label: str):
                    if total > 0:
                        pct = 30 + int((current / total) * 50)
                        _status.update_rag(RAGStatus.EMBEDDING, pct, f"Embedding: {current}/{total} chunks")

                from rag.vector_store import LensightVectorStore
                vs = LensightVectorStore(batch_size=10, num_workers=4)
                vs.build_from_documents(chunks, progress_callback=progress_callback)

                _status.update_rag(RAGStatus.STORING, 85, "Finalizing index...")
                _rag_store = vs
                _status.update_rag(RAGStatus.READY, 100, "Annual report ready")
                logger.info("RAG indexing complete.")
            except Exception as rag_exc:
                logger.warning("RAG indexing failed: %s", rag_exc)
                _status.update_rag(RAGStatus.ERROR, 0, f"Error: {str(rag_exc)[:50]}")

        rag_thread = threading.Thread(
            target=_rag_indexing_task, daemon=True, name="lensight-rag"
        )
        rag_thread.start()

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)
        _status.update(Stage.ERROR, error=str(exc))


def start_pipeline(
    excel_filename: str,
    pdf_filename: str | None,
    uploads_dir: Path,
    raw_dir: Path,
    processed_dir: Path,
) -> bool:
    """Launch the pipeline in a daemon background thread."""
    if not _running.acquire(blocking=False):
        logger.warning("Pipeline already running.")
        return False

    _status.update(Stage.FLUSHING)
    _status.rag_status = RAGStatus.IDLE

    def _worker():
        try:
            run_pipeline(
                excel_filename,
                pdf_filename,
                uploads_dir, raw_dir, processed_dir,
            )
        except Exception:
            logger.exception("Pipeline worker exited with uncaught exception")
        finally:
            _running.release()

    thread = threading.Thread(target=_worker, daemon=True, name="lensight-pipeline")
    thread.start()
    logger.info("Pipeline thread started for file: %s", excel_filename)
    return True