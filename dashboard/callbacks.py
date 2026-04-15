"""
dashboard/callbacks.py
-----------------------
Dash callbacks for the Lensight dashboard.

Callbacks
---------
  cb_upload
    Triggered when user uploads a .xlsx file.
    Validates the file, starts the background pipeline,
    and switches the app to the PROCESSING state.

  cb_poll_pipeline
    Fires every 500ms while processing is active.
    Reads PipelineStatus and updates the loading screen.
    When pipeline is DONE, switches to DASHBOARD state.
    Stops the interval when done or on error.

  cb_reset
    Lets user upload a new file from the dashboard view.
    Resets app state back to UPLOAD screen.

App state flow
--------------
  "upload"     → initial screen (or after reset)
  "processing" → loading screen with progress bar
  "dashboard"  → full analysis result

State is stored in dcc.Store(id="app-state") as a dict:
  { "screen": "upload" | "processing" | "dashboard" }
"""

import base64
import json
import logging
import sys
import os
import threading
import time
import uuid
from pathlib import Path

from dash import Input, Output, State, callback_context, no_update, Patch
from dash.exceptions import PreventUpdate

from llm.query_analyzer import get_analyzer
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_data_uri(content: str) -> str:
    """
    dcc.Upload returns 'data:...;base64,<data>'.
    Strip the prefix and return only the base64 payload.
    """
    if "," in content:
        return content.split(",", 1)[1]
    return content


def _is_xlsx(filename: str) -> bool:
    return filename.lower().endswith((".xlsx", ".xls"))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_callbacks(app) -> None:
    """
    Register all Dash callbacks on the app instance.

    Parameters
    ----------
    app : dash.Dash
        The Dash application instance.
    """
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from constants import (
        DATA_UPLOADS_DIR,
        DATA_RAW_DIR,
        DATA_PROCESSED_DIR,
        ANALYSIS_READY_FLAG,
        STREAM_FIRST_TOKEN_TIMEOUT_SEC,
        STREAM_DATA_DIR,
    )

    from dashboard.pipeline_runner import start_pipeline, get_status, Stage, RAGStatus
    from dashboard.layout import (
        build_upload_screen,
        build_loading_screen,
        build_layout,
        build_error_layout,
        build_chat_screen,
    )

    logger.info("Registering callbacks...")

    # ── 1. Upload handler ─────────────────────────────────────────────────────
    @app.callback(
        Output("page-content",    "children"),
        Output("app-state",       "data"),
        Output("poll-interval",   "disabled"),
        Output("upload-error-msg","children"),
        Output("upload-error-msg","style"),
        Input("btn-run-analysis", "n_clicks"),
        State("upload-xlsx",      "contents"),
        State("upload-xlsx",      "filename"),
        State("upload-pdf",       "contents"),
        State("upload-pdf",       "filename"),
        State("app-state",        "data"),
        prevent_initial_call=True,
    )
    def cb_upload(n_clicks, xlsx_contents, xlsx_filename, pdf_contents, pdf_filename, state):
        """
        Triggered by the Run Analysis button — not by file selection.
        This ensures the user can upload both files before processing starts.
        - xlsx is required — triggers the analysis pipeline
        - pdf is optional — saved to uploads/ for later RAG use
        - CLEARS old uploads before processing new files
        """
        if not n_clicks:
            raise PreventUpdate

        _err_style_show = {
            "color": "#ef4444", "fontSize": "13px", "fontWeight": "600",
            "textAlign": "center", "minHeight": "20px", "display": "block",
        }
        _err_style_hide = {
            "color": "#ef4444", "fontSize": "13px", "fontWeight": "600",
            "textAlign": "center", "minHeight": "20px", "display": "none",
        }

        if xlsx_contents is None:
            return no_update, no_update, True, "Please upload a Screener.in Excel file first.", _err_style_show

        if not _is_xlsx(xlsx_filename or ""):
            logger.warning("Rejected upload: '%s' is not an xlsx file.", xlsx_filename)
            return (
                no_update,
                {"screen": "upload"},
                True,
                f"'{xlsx_filename}' is not a valid Excel file. Please upload a .xlsx file.",
                _err_style_show,
            )

        logger.info("Received Excel upload: %s", xlsx_filename)

        # 🧹 Clear old uploads from previous session before processing new files
        import shutil
        if DATA_UPLOADS_DIR.exists():
            try:
                for old_file in DATA_UPLOADS_DIR.glob("*"):
                    if old_file.is_file():
                        old_file.unlink()
                        logger.info(f"🧹 Cleared old upload: {old_file.name}")
                    elif old_file.is_dir():
                        shutil.rmtree(old_file)
                        logger.info(f"🧹 Cleared old upload directory: {old_file.name}")
            except Exception as exc:
                logger.warning(f"Could not clear uploads folder: {exc}")
        
        # Save PDF to uploads folder if provided (for RAG pipeline later)
        if pdf_contents and pdf_filename:
            try:
                pdf_bytes = base64.b64decode(_strip_data_uri(pdf_contents))
                pdf_path  = DATA_UPLOADS_DIR / pdf_filename
                DATA_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(pdf_bytes)
                logger.info(
                    "Annual report saved: %s (%d bytes)",
                    pdf_filename, len(pdf_bytes),
                )
            except Exception as exc:
                logger.warning("Could not save PDF '%s': %s", pdf_filename, exc)

        xlsx_b64 = _strip_data_uri(xlsx_contents)

        started = start_pipeline(
            file_content_b64=xlsx_b64,
            filename=xlsx_filename,
            uploads_dir=DATA_UPLOADS_DIR,
            raw_dir=DATA_RAW_DIR,
            processed_dir=DATA_PROCESSED_DIR,
        )

        if not started:
            return (
                no_update,
                {"screen": "upload"},
                True,
                "A pipeline is already running. Please wait and try again.",
                _err_style_show,
            )

        return (
            build_loading_screen(),
            {"screen": "processing"},
            False,
            "",
            _err_style_hide,
        )

    # ── 1b. Show filenames when files are selected ────────────────────────────
    @app.callback(
        Output("xlsx-filename", "children"),
        Input("upload-xlsx",    "filename"),
        prevent_initial_call=True,
    )
    def cb_show_xlsx_name(filename):
        if filename:
            return f"✓  {filename}"
        return ""

    @app.callback(
        Output("pdf-filename", "children"),
        Input("upload-pdf",    "filename"),
        prevent_initial_call=True,
    )
    def cb_show_pdf_name(filename):
        if filename:
            return f"✓  {filename}"
        return ""

    # ── 2. Pipeline polling ───────────────────────────────────────────────────
    @app.callback(
        Output("page-content",              "children",  allow_duplicate=True),
        Output("app-state",               "data",      allow_duplicate=True),
        Output("poll-interval",           "disabled",  allow_duplicate=True),
        Output("loading-progress-display","value",     allow_duplicate=True),
        Output("loading-stage-display",   "children",  allow_duplicate=True),
        Output("loading-company-display", "children",  allow_duplicate=True),
        Input("poll-interval",            "n_intervals"),
        State("app-state",            "data"),
        prevent_initial_call=True,
    )
    def cb_poll_pipeline(n_intervals, state):
        """
        Poll pipeline status every 500ms.
        Updates progress bar and labels.
        Switches to dashboard on completion.
        """
        if state is None or state.get("screen") != "processing":
            raise PreventUpdate

        status = get_status()
        stage    = status.get("stage", "idle")
        progress = status.get("progress", 0)
        label    = status.get("label", "Processing...")
        company  = status.get("company", "")
        error    = status.get("error", "")

        company_text = f"Analysing: {company}" if company else "Preparing analysis..."

        analysis_file = DATA_PROCESSED_DIR / "analysis.json"

        # Load-balanced hosting: pipeline runs on replica A while Dash polls hit B —
        # filesystem is shared (or we're on the same box), the ready marker +
        # analysis.json prove completion.
        if stage not in (Stage.DONE.value, Stage.ERROR.value):
            if analysis_file.exists() and ANALYSIS_READY_FLAG.exists():
                try:
                    marker = json.loads(ANALYSIS_READY_FLAG.read_text(encoding="utf-8"))
                    if marker.get("ok"):
                        with analysis_file.open(encoding="utf-8") as fh:
                            data = json.load(fh)
                        logger.info(
                            "Pipeline completion via on-disk marker — dashboard for '%s'",
                            data.get("company", ""),
                        )
                        return (
                            build_layout(data),
                            {"screen": "dashboard"},
                            True,
                            100,
                            "Analysis complete!",
                            company_text,
                        )
                except Exception as exc:
                    logger.warning(
                        "On-disk completion check failed (will keep polling): %s", exc
                    )

        if stage == Stage.DONE.value:
            # Pipeline finished — load analysis and switch to dashboard
            try:
                with analysis_file.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                logger.info("Pipeline done — rendering dashboard for '%s'", company)
                return (
                    build_layout(data),
                    {"screen": "dashboard"},
                    True,    # disable polling
                    100,
                    "Analysis complete!",
                    company_text,
                )
            except Exception as exc:
                logger.error("Failed to load analysis.json after pipeline: %s", exc)
                return (
                    build_error_layout(f"Pipeline completed but failed to load results: {exc}"),
                    {"screen": "upload"},
                    True,
                    0, "Error", "",
                )

        if stage == Stage.ERROR.value:
            logger.error("Pipeline error: %s", error)
            return (
                build_upload_screen(
                    error=f"Pipeline failed: {error}. Please try again."
                ),
                {"screen": "upload"},
                True,    # disable polling
                0, "Failed", "",
            )

        # Still running — update progress only
        return (
            no_update,
            no_update,
            False,   # keep polling
            progress,
            label,
            company_text,
        )

    # ── 3. Reset — go back to upload screen ──────────────────────────────────
    @app.callback(
        Output("page-content",  "children",  allow_duplicate=True),
        Output("app-state",     "data",      allow_duplicate=True),
        Output("poll-interval", "disabled",  allow_duplicate=True),
        Input("btn-new-analysis", "n_clicks"),
        prevent_initial_call=True,
    )
    def cb_reset(n_clicks):
        """Return to upload screen for a new analysis."""
        if not n_clicks:
            raise PreventUpdate
        logger.info("User reset to upload screen.")
        return build_upload_screen(), {"screen": "upload"}, True

    # ── 4. Navigate to Chat screen ────────────────────────────────────────────
    @app.callback(
        Output("page-content",  "children",  allow_duplicate=True),
        Output("app-state",     "data",      allow_duplicate=True),
        Input("btn-open-chat",  "n_clicks"),
        State("chat-history",   "data"),
        prevent_initial_call=True,
    )
    def cb_open_chat(n_clicks, chat_history):
        if not n_clicks:
            raise PreventUpdate
        analysis_file = DATA_PROCESSED_DIR / "analysis.json"
        if not analysis_file.exists():
            raise PreventUpdate
        with analysis_file.open(encoding="utf-8") as fh:
            data = json.load(fh)
        from dashboard.pipeline_runner import get_rag_store, get_status
        status = get_status()
        rag_status = status.get("rag_status", "idle")
        logger.info("Opening chat screen. rag_status=%s, existing messages=%d", rag_status, len(chat_history or []))
        return (
            build_chat_screen(data, messages=chat_history or []),
            {"screen": "chat"},
        )

    # ── 5. Update RAG Badge ──────────────────────────────────────────────────
    @app.callback(
        Output("rag-status-badge", "children"),
        Output("rag-status-badge", "style"),
        Output("rag-status-interval", "disabled"),
        Input("rag-status-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def cb_update_rag_status(n_intervals):
        from dashboard.pipeline_runner import get_status, RAGStatus
        status = get_status()
        rag_status = status.get("rag_status", RAGStatus.IDLE.value)
        rag_progress = status.get("rag_progress", 0)
        rag_label = status.get("rag_label", "")

        # Base style
        base_style = {
            "fontSize": "11px", "fontWeight": "600",
            "padding": "6px 12px", "borderRadius": "20px",
            "marginBottom": "16px", "textAlign": "center",
            "transition": "all 0.3s ease",
        }

        if rag_status == RAGStatus.READY.value:
            return "📄 Analysis Ready", {**base_style, "color": "#10b981", "background": "#10b98120"}, True
        
        elif rag_status == RAGStatus.LOADING.value:
            return f"📥 Reading Report... {rag_progress}%", {**base_style, "color": "#12aada", "background": "#12aada20"}, False
        
        elif rag_status == RAGStatus.CHUNKING.value:
            return f"✂️ Processing Chunks... {rag_progress}%", {**base_style, "color": "#12aada", "background": "#12aada20"}, False
        
        elif rag_status == RAGStatus.EMBEDDING.value:
            progress_bar = "▓" * (rag_progress // 10) + "░" * (10 - rag_progress // 10)
            return f"⚡ Embedding {progress_bar} {rag_progress}%", {**base_style, "color": "#12aada", "background": "#12aada20", "fontFamily": "monospace", "fontSize": "10px"}, False
        
        elif rag_status == RAGStatus.STORING.value:
            return f"💾 Finalizing... {rag_progress}%", {**base_style, "color": "#8b5cf6", "background": "#8b5cf620"}, False
        
        elif rag_status == RAGStatus.ERROR.value:
            return f"⚠ {rag_label or 'Indexing Failed'}", {**base_style, "color": "#ef4444", "background": "#ef444420"}, True
        
        else:  # IDLE or unknown
            return "📊 Financials Only", {**base_style, "color": "#64748b", "background": "#f1f5f9"}, True

    # ── 5b. Update chat header RAG message dynamically ───────────────────────
    @app.callback(
        Output("chat-rag-status-message", "children"),
        Output("chat-rag-status-message", "style"),
        Input("rag-status-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def cb_update_chat_rag_message(n_intervals):
        """Update chat header message based on current RAG status."""
        from dashboard.pipeline_runner import get_status, RAGStatus
        
        status = get_status()
        rag_status = status.get("rag_status", RAGStatus.IDLE.value)
        
        base_style = {
            "marginLeft": "auto", "fontSize": "11px",
            "padding": "4px 12px", "borderRadius": "12px",
            "fontWeight": "700",
            "display": "block",
        }
        
        if rag_status == RAGStatus.READY.value:
            # Report is indexed - hide the message
            return "", {**base_style, "display": "none"}
        
        elif rag_status == RAGStatus.IDLE.value:
            # No report uploaded
            return "📊 Answering from ratios only", {**base_style, "background": "#f59e0b20", "color": "#f59e0b", "display": "block"}
        
        elif rag_status in (RAGStatus.LOADING.value, RAGStatus.CHUNKING.value, RAGStatus.EMBEDDING.value, RAGStatus.STORING.value):
            # Report is being indexed
            return "📄 Processing report...", {**base_style, "background": "#12aada20", "color": "#12aada", "display": "block"}
        
        elif rag_status == RAGStatus.ERROR.value:
            # Indexing failed
            return "⚠️ Report error", {**base_style, "background": "#ef444420", "color": "#ef4444", "display": "block"}
        
        else:
            return "", {**base_style, "display": "none"}

    # ── 6a. Send chat message (optimistic UI update) ───────────────────────
    @app.callback(
        Output("chat-messages",        "children",  allow_duplicate=True),
        Output("chat-input",           "value",     allow_duplicate=True),
        Output("pending-chat-request", "data",      allow_duplicate=True),
        Input("btn-send-chat",         "n_clicks"),
        State("chat-input",            "value"),
        State("chat-history",          "data"),
        State("conv-summary",          "data"),
        prevent_initial_call=True,
    )
    def cb_send_message_optimistic(n_clicks, question, chat_history, conv_summary):
        """Show user message + loading bubble, queue the LLM request."""
        if not n_clicks or not question or not question.strip():
            raise PreventUpdate

        question = question.strip()
        chat_history = chat_history or []
        logger.info(f"[SEND] User message: {question[:60]}")

        from dashboard.layout import _chat_bubble, _loading_bubble
        bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history]
        bubbles.append(_chat_bubble("user", question))
        bubbles.append(_loading_bubble())

        request_data = {
            "question": question,
            "chat_history": chat_history,
            "conv_summary": conv_summary,
            "stream_id": str(uuid.uuid4()),
        }
        return bubbles, "", request_data

    # ── 6b. Kick off background LLM call ──────────────────────────────────
    @app.callback(
        Output("stream-interval",      "disabled", allow_duplicate=True),
        Output("streaming-response",   "data",     allow_duplicate=True),
        Output("pending-chat-request", "data",     allow_duplicate=True),
        Input("pending-chat-request",  "data"),
        prevent_initial_call=True,
    )
    def cb_start_streaming(request_data):
        """Spin up a daemon thread to call the LLM; enable the poll interval."""
        if not request_data:
            raise PreventUpdate

        stream_id = request_data["stream_id"]
        logger.info(f"[START_STREAM] stream_id={stream_id}")

        def _worker():
            STREAM_DATA_DIR.mkdir(parents=True, exist_ok=True)
            stream_file = STREAM_DATA_DIR / f"{stream_id}.txt"
            done_file = STREAM_DATA_DIR / f"{stream_id}.done"
            err_file = STREAM_DATA_DIR / f"{stream_id}.error"

            try:
                question     = request_data["question"]
                chat_history = request_data.get("chat_history", [])
                conv_summary = request_data.get("conv_summary", "")

                # ── Load analysis ──────────────────────────────────────────
                analysis_file = DATA_PROCESSED_DIR / "analysis.json"
                if not analysis_file.exists():
                    err_file.write_text("Analysis results not found. Please re-run analysis.", encoding="utf-8")
                    return

                with analysis_file.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                company = data.get("company", "Unknown Company")

                # ── Query analyzer ────────────────────────────────────────
                try:
                    analyzer = get_analyzer()
                    financial_summary, _ = analyzer.process_query(question, data)
                except Exception as exc:
                    logger.warning(f"[WORKER] Analyzer failed, using fallback: {exc}")
                    financial_summary = str(data.get("summary_scores", {}))[:3000]

                # ── RAG context ───────────────────────────────────────────
                rag_context   = ""
                rag_status_raw = "idle"
                try:
                    from dashboard.pipeline_runner import get_status, RAGStatus
                    st = get_status()
                    rag_status_raw = st.get("rag_status", RAGStatus.IDLE.value)
                    if rag_status_raw == RAGStatus.READY.value:
                        from rag.retriever import RAGRetriever
                        rag_context = RAGRetriever().retrieve_context(question)
                except Exception as exc:
                    logger.warning(f"[WORKER] RAG retrieval failed: {exc}")

                # ── Call LLM (collect full response) ──────────────────────
                from llm.orchestrator import LLMOrchestrator
                orchestrator = LLMOrchestrator()
                chunks = []
                last_sync = time.time()
                
                for token in orchestrator.chat_grounded_stream(
                    question=question,
                    company=company,
                    financial_summary=financial_summary,
                    rag_context=rag_context,
                    conversation_summary=conv_summary,
                    rag_status=rag_status_raw,
                ):
                    if token:
                        chunks.append(token)
                        # Throttle disk writes to ~3Hz to avoid IO bottlenecks
                        if time.time() - last_sync > 0.3:
                            stream_file.write_text("".join(chunks), encoding="utf-8")
                            last_sync = time.time()

                assistant_text = "".join(chunks)
                stream_file.write_text(assistant_text, encoding="utf-8")
                
                logger.info(f"[WORKER] Done. {len(chunks)} chunks, {len(assistant_text)} chars")

                done_file.write_text(json.dumps({
                    "assistant_text": assistant_text,
                    "chat_history": chat_history,
                    "conv_summary": conv_summary,
                }), encoding="utf-8")

            except Exception as exc:
                logger.error(f"[WORKER] Fatal error: {exc}", exc_info=True)
                err_file.write_text(f"Something went wrong: {exc}", encoding="utf-8")

        threading.Thread(target=_worker, daemon=True).start()

        streaming_state = {
            "status": "streaming",
            "stream_id": stream_id,
            "request_data": request_data,
            "start_time": time.time(),
            "poll_count": 0,
        }
        return False, streaming_state, None

    # ── 6c. Poll in-memory result and update UI ────────────────────────────
    @app.callback(
        Output("chat-messages",       "children",  allow_duplicate=True),
        Output("stream-interval",     "disabled",  allow_duplicate=True),
        Output("chat-history",        "data",      allow_duplicate=True),
        Output("conv-summary",        "data",      allow_duplicate=True),
        Output("streaming-response",  "data",      allow_duplicate=True),
        Input("stream-interval",      "n_intervals"),
        State("chat-history",         "data"),
        State("streaming-response",   "data"),
        prevent_initial_call=True,
    )
    def cb_poll_stream(n_intervals, chat_history, streaming_data):
        """Check in-memory result store and update chat UI."""
        if not streaming_data or streaming_data.get("status") != "streaming":
            raise PreventUpdate

        from dashboard.layout import _chat_bubble, _loading_bubble

        stream_id    = streaming_data.get("stream_id", "")
        request_data = streaming_data.get("request_data", {})
        question     = request_data.get("question", "")
        chat_history = chat_history or []

        streaming_data["poll_count"] = streaming_data.get("poll_count", 0) + 1
        poll_num = streaming_data["poll_count"]

        # ── Timeout guard ─────────────────────────────────────────────────
        elapsed = time.time() - streaming_data.get("start_time", time.time())
        if elapsed > STREAM_FIRST_TOKEN_TIMEOUT_SEC:
            logger.error(f"[POLL] Timeout after {elapsed:.0f}s for stream_id={stream_id}")
            error_msg = f"⏱️ Response timed out after {int(elapsed)}s. Please try again."
            final_history = chat_history + [
                {"role": "user",      "content": question},
                {"role": "assistant", "content": error_msg},
            ]
            patched_messages = Patch()
            patched_messages[-1] = _chat_bubble("assistant", error_msg)
            
            # Clean up
            for ext in ["txt", "done", "error"]:
                f = STREAM_DATA_DIR / f"{stream_id}.{ext}"
                if f.exists(): f.unlink()

            return (
                patched_messages,
                True, final_history, no_update, None,
            )

        # ── Check result files ────────────────────────────────────────────
        stream_file = STREAM_DATA_DIR / f"{stream_id}.txt"
        done_file = STREAM_DATA_DIR / f"{stream_id}.done"
        err_file = STREAM_DATA_DIR / f"{stream_id}.error"

        if err_file.exists():
            err_text = err_file.read_text(encoding="utf-8")
            logger.error(f"[POLL] Worker reported error: {err_text}")
            final_history = chat_history + [
                {"role": "user",      "content": question},
                {"role": "assistant", "content": f"❌ {err_text}"},
            ]
            patched_messages = Patch()
            patched_messages[-1] = _chat_bubble("assistant", f"❌ {err_text}")
            
            # Clean up
            for f in [stream_file, done_file, err_file]:
                if f.exists(): f.unlink()

            return (
                patched_messages,
                True, final_history, no_update, None,
            )

        if done_file.exists():
            try:
                done_data = json.loads(done_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"[POLL] Error parsing done file: {e}")
                done_data = {"assistant_text": stream_file.read_text(encoding="utf-8") if stream_file.exists() else "Error reading final response"}
                
            assistant_text   = done_data.get("assistant_text", "")
            saved_history    = done_data.get("chat_history", chat_history)
            new_conv_summary = done_data.get("conv_summary", "")
            final_history    = saved_history + [
                {"role": "user",      "content": question},
                {"role": "assistant", "content": assistant_text},
            ]
            logger.info(f"[POLL] Done — displaying {len(assistant_text)} chars")
            patched_messages = Patch()
            patched_messages[-1] = _chat_bubble("assistant", assistant_text)
            
            # Clean up
            for f in [stream_file, done_file, err_file]:
                if f.exists(): f.unlink()

            return (
                patched_messages,
                True, final_history, new_conv_summary, None,
            )

        # ── Still running: show partial text if available ─────────────────
        partial = ""
        if stream_file.exists():
            try:
                partial = stream_file.read_text(encoding="utf-8")
            except Exception as e:
                # File might be mid-write, ignore and wait for next poll
                pass

        if poll_num % 10 == 0:
            logger.info(f"[POLL] #{poll_num} @ {elapsed:.1f}s | partial={len(partial)} chars")

        patched_messages = Patch()
        if partial:
            patched_messages[-1] = _chat_bubble("assistant", partial)
        else:
            patched_messages[-1] = _loading_bubble()

        return patched_messages, no_update, no_update, no_update, streaming_data


    # ── 7. Back to Dashboard ──────────────────────────────────────────────────
    @app.callback(
        Output("page-content",        "children",  allow_duplicate=True),
        Output("app-state",           "data",      allow_duplicate=True),
        Input("btn-back-to-dashboard","n_clicks"),
        prevent_initial_call=True,
    )
    def cb_back_to_dashboard(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        
        analysis_file = DATA_PROCESSED_DIR / "analysis.json"
        if not analysis_file.exists():
            raise PreventUpdate
        with analysis_file.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return build_layout(data), {"screen": "dashboard"}

    # ── 8. Refresh warning ────────────────────────────────────────────────────
    app.clientside_callback(
        """
        function(app_state) {
            const screen = (app_state && app_state.screen) ? app_state.screen : 'upload';
            window.onbeforeunload = function(e) {
                if (screen === 'dashboard' || screen === 'processing' || screen === 'chat') {
                    const warningMessage = 'Refreshing will clear your analysis. Are you sure?';
                    e.preventDefault();
                    e.returnValue = warningMessage;
                    return warningMessage;
                }
            };
            return screen;
        }
        """,
        Output("screen-state-tracker", "children"),
        Input("app-state", "data"),
    )

    logger.info("All callbacks registered.")