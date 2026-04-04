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
import threading
from pathlib import Path
from queue import Queue

from dash import Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate

from llm.query_analyzer import get_analyzer

logger = logging.getLogger(__name__)

# Global stream queue for streaming responses
_STREAM_QUEUE = Queue()

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

        # Render / multi-worker: upload + pipeline may run on instance A while
        # Dash polls hit instance B — _status stays on "ratios" forever. If the
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
        """Show user message + loading bubble, store request for streaming."""
        if not n_clicks or not question or not question.strip():
            logger.debug("[SEND] Send triggered but no valid question provided")
            raise PreventUpdate

        question = question.strip()
        chat_history = chat_history or []

        logger.info(f"[SEND] User message: {question[:60]}...")
        logger.debug(f"[SEND] Chat history size: {len(chat_history)} messages")

        # Build message bubbles with user message + loading placeholder
        from dashboard.layout import _chat_bubble, _loading_bubble
        bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history]
        bubbles.append(_chat_bubble("user", question))
        # Add loading bubble that will be replaced with streaming response
        bubbles.append(_loading_bubble())

        # Store request data for next callback to process
        request_data = {
            "question": question,
            "chat_history": chat_history,
            "conv_summary": conv_summary,
        }

        logger.info("[SEND] Optimistic UI update complete, streaming scheduled")
        return bubbles, "", request_data

    # ── 6b. Start streaming LLM response ──────────────────────────────────
    @app.callback(
        Output("stream-interval",      "disabled", allow_duplicate=True),
        Output("streaming-response",   "data",     allow_duplicate=True),
        Output("pending-chat-request", "data",     allow_duplicate=True),
        Input("pending-chat-request",  "data"),
        prevent_initial_call=True,
    )
    def cb_start_streaming(request_data):
        """Start background thread to stream LLM response."""
        if not request_data:
            logger.debug("[START_STREAM] No pending request data")
            raise PreventUpdate

        logger.info("[START_STREAM] Initiating streaming response handler")

        # Clear queue
        cleared = 0
        while not _STREAM_QUEUE.empty():
            try:
                _STREAM_QUEUE.get()
                cleared += 1
            except:
                pass
        logger.debug(f"[START_STREAM] Cleared {cleared} items from queue")

        # Initialize streaming response store with timestamp for timeout detection
        import time
        streaming_data = {
            "status": "streaming",
            "response": "",
            "request_data": request_data,
            "start_time": time.time(),
            "last_token_time": time.time(),
            "poll_count": 0,
        }

        def _stream_worker():
            """Background thread to stream LLM response."""
            import time as time_module
            worker_start = time_module.time()
            
            # CRITICAL: Log that the thread actually started
            print(f"[STREAM_WORKER_STARTED] 🚀 Thread execution begun at {worker_start}")
            logger.info(f"[STREAM] 🚀 Thread started. Request queue size: {_STREAM_QUEUE.qsize()}")
            
            try:
                question = request_data.get("question")
                chat_history = request_data.get("chat_history", [])
                conv_summary = request_data.get("conv_summary", "")

                logger.info(f"[STREAM] 🚀 Starting stream worker for question: {question[:60]}...")
                print(f"[STREAM_WORKER] Question: {question[:60]}")
                
                # Load analysis
                analysis_file = DATA_PROCESSED_DIR / "analysis.json"
                if not analysis_file.exists():
                    logger.error("[STREAM] ❌ Analysis file not found")
                    _STREAM_QUEUE.put(("error", "Analysis file not found"))
                    print("[STREAM_WORKER] Analysis file not found error queued")
                    return

                try:
                    with analysis_file.open(encoding="utf-8") as fh:
                        data = json.load(fh)
                    print(f"[STREAM_WORKER] Analysis loaded successfully")
                except Exception as load_exc:
                    logger.error(f"[STREAM] ❌ Failed to load analysis.json: {load_exc}", exc_info=True)
                    _STREAM_QUEUE.put(("error", f"Failed to load analysis: {str(load_exc)[:100]}"))
                    print(f"[STREAM_WORKER] Load error: {load_exc}")
                    return

                company = data.get("company", "Unknown")
                logger.info(f"[STREAM] 📊 Company: {company}")
                
                # Use smart filtering to reduce token usage
                try:
                    analyzer = get_analyzer()
                    financial_summary, analysis_metadata = analyzer.process_query(question, data)
                    logger.info(f"[STREAM] ✅ Query analysis complete: {analysis_metadata['context_type']}")
                except Exception as analyzer_exc:
                    logger.error(f"[STREAM] ⚠️ Query analyzer failed: {analyzer_exc}", exc_info=True)
                    financial_summary = str(data.get("summary_scores", {}))[:2000]
                    analysis_metadata = {"context_type": "full", "confidence": 1.0, "categories": []}
                
                logger.debug(
                    f"[STREAM] Smart filtering: {analysis_metadata['context_type']} "
                    f"({analysis_metadata['confidence']:.1%} confidence, "
                    f"categories: {', '.join(analysis_metadata.get('categories', [])) or 'none'})"
                )

                # Get RAG status
                try:
                    from dashboard.pipeline_runner import get_rag_store, get_status, RAGStatus
                    status = get_status()
                    rag_status_raw = status.get("rag_status", RAGStatus.IDLE.value)
                    logger.debug(f"[STREAM] RAG status: {rag_status_raw}")
                except Exception as rag_status_exc:
                    logger.warning(f"[STREAM] Could not get RAG status: {rag_status_exc}")
                    rag_status_raw = "idle"
                
                # Map new granular RAG states to orchestrator states for compatibility
                rag_status_for_orchestrator = rag_status_raw
                if rag_status_raw in ("loading", "chunking", "embedding", "storing"):
                    rag_status_for_orchestrator = "indexing"
                
                rag_context = ""
                try:
                    rag_store_instance = get_rag_store()
                    if rag_store_instance and rag_status_raw == RAGStatus.READY.value:
                        from rag.retriever import RAGRetriever
                        retriever = RAGRetriever(rag_store_instance)
                        rag_context = retriever.retrieve_context(question)
                        logger.info(f"[STREAM] ✅ RAG context retrieved: {len(rag_context)} chars")
                except Exception as rag_exc:
                    logger.warning(f"[STREAM] RAG retrieval failed (continuing without): {rag_exc}")
                    rag_context = ""

                # Compress if needed
                conv_summary = conv_summary or ""
                if len(chat_history) > 10:
                    logger.info(f"[STREAM] Chat history has {len(chat_history)} messages")

                # Stream LLM response
                from llm.orchestrator import LLMOrchestrator
                orchestrator = LLMOrchestrator()
                logger.info("[STREAM] 📡 Starting LLM streaming (direct token mode)...")
                print("[STREAM_WORKER] Orchestrator created, calling stream...")

                token_count = 0
                stream_start = time_module.time()
                first_token_logged = False
                # Full text on the worker — required when load balancers send polls to
                # different instances than the worker (empty queue + empty client state).
                assistant_chunks: list[str] = []

                # Call the generator
                try:
                    logger.info("[STREAM] Calling orchestrator.chat_grounded_stream()...")
                    print("[STREAM_WORKER] Calling chat_grounded_stream()...")
                    generator = orchestrator.chat_grounded_stream(
                        question=question,
                        company=company,
                        financial_summary=financial_summary,
                        rag_context=rag_context,
                        conversation_summary=conv_summary,
                        rag_status=rag_status_for_orchestrator
                    )
                    logger.info("[STREAM] ✅ Generator object created successfully")
                    print("[STREAM_WORKER] Generator created, starting iteration...")
                except Exception as gen_exc:
                    logger.error(f"[STREAM] ❌ Failed to create stream generator: {gen_exc}", exc_info=True)
                    _STREAM_QUEUE.put(("error", f"Generator creation failed: {str(gen_exc)[:100]}"))
                    print(f"[STREAM_WORKER] Generator creation error: {gen_exc}")
                    return

                try:
                    for token in generator:
                        print(f"[STREAM_WORKER_TOKEN] Received token #{token_count + 1}: {token[:30]}")
                        
                        # Log first token arrival
                        if token_count == 0:
                            first_token_elapsed = time_module.time() - stream_start
                            logger.info(f"[STREAM] ⚡ FIRST TOKEN in {first_token_elapsed:.3f}s: '{token[:30]}...'")
                            print(f"[STREAM_WORKER] FIRST TOKEN in {first_token_elapsed:.3f}s")

                        if token:
                            assistant_chunks.append(token)

                        # Queue the token (UI may still stream on same instance)
                        _STREAM_QUEUE.put(("token", token))
                        token_count += 1
                        
                        # Log progress every 20 tokens
                        if token_count % 20 == 0:
                            elapsed = time_module.time() - stream_start
                            rate = token_count / (elapsed + 0.001)
                            logger.debug(f"[STREAM] Progress: {token_count} tokens in {elapsed:.1f}s ({rate:.1f} t/s)")
                        
                        if token is None or token == "":
                            logger.warning(f"[STREAM] ⚠️ Empty token received at position {token_count}")
                    
                    print(f"[STREAM_WORKER_DONE] Total tokens queued: {token_count}")
                    if token_count == 0:
                        logger.warning("[STREAM] ⚠️ NO TOKENS GENERATED - stream generator was empty")
                        _STREAM_QUEUE.put(("error", "LLM generated no tokens (empty response)"))
                        print("[STREAM_WORKER] No tokens generated")
                        return
                    
                    elapsed_total = time_module.time() - stream_start
                    assistant_text = "".join(assistant_chunks)
                    logger.info(f"[STREAM] ✅ Streaming complete: {token_count} tokens in {elapsed_total:.2f}s")
                    _STREAM_QUEUE.put(
                        (
                            "done",
                            {
                                "chat_history": chat_history,
                                "conv_summary": conv_summary,
                                "assistant_text": assistant_text,
                            },
                        )
                    )
                    print("[STREAM_WORKER] Done message queued")
                    
                except Exception as stream_exc:
                    error_msg = str(stream_exc)
                    logger.error(f"[STREAM] ❌ Exception during token streaming: {error_msg}", exc_info=True)
                    print(f"[STREAM_WORKER_ERROR] Stream exception: {error_msg}")
                    
                    # Check if it's a timeout or quota error
                    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                        logger.error("[STREAM] ⏱️ TIMEOUT in LLM streaming")
                        _STREAM_QUEUE.put(("error", f"LLM timeout: {error_msg[:80]}"))
                    elif "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                        logger.error("[STREAM] 🚫 QUOTA EXCEEDED")
                        _STREAM_QUEUE.put(("quota_exceeded", None))
                    else:
                        _STREAM_QUEUE.put(("error", f"Streaming error: {error_msg[:100]}"))
                    print(f"[STREAM_WORKER_ERROR] Error message queued")
                    return
                    
            except Exception as exc:
                error_msg = str(exc)
                logger.error(f"[STREAM] ❌ Worker error: {error_msg}", exc_info=True)
                print(f"[STREAM_WORKER_ERROR] Worker exception: {error_msg}")
                
                # Check if it's a quota exceeded error
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                    logger.error("[STREAM] 🚫 QUOTA EXCEEDED: Gemini API free tier limit reached")
                    _STREAM_QUEUE.put(("quota_exceeded", None))
                else:
                    _STREAM_QUEUE.put(("error", error_msg[:200]))

        # Start background thread
        try:
            thread = threading.Thread(target=_stream_worker, daemon=True)
            thread.start()
            logger.info(f"[START_STREAM] ✅ Background streaming thread started, polling enabled. Thread: {thread.name}")
        except Exception as thread_exc:
            logger.error(f"[START_STREAM] ❌ Failed to start streaming thread: {thread_exc}", exc_info=True)
            _STREAM_QUEUE.put(("error", f"Thread creation failed: {str(thread_exc)[:100]}"))
            return False, None, None

        # Enable interval polling, clear pending request, return initial state
        return False, streaming_data, None

    # ── 6c. Poll streaming tokens and update UI ────────────────────────────
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
        """Poll for streamed tokens and update UI continuously."""
        if not streaming_data or streaming_data.get("status") != "streaming":
            raise PreventUpdate

        import time
        
        current_time = time.time()
        streaming_data["poll_count"] = streaming_data.get("poll_count", 0) + 1
        poll_num = streaming_data["poll_count"]
        
        # CRITICAL: Log every poll to verify callback is firing
        if poll_num == 1:
            logger.info(f"[POLL] 🟢 FIRST POLL - Streaming started. Response len: {len(streaming_data.get('response', ''))} chars")
        
        if poll_num % 10 == 0:  # Every 1 second (10 polls at 100ms)
            elapsed = current_time - streaming_data.get("start_time", current_time)
            response_len = len(streaming_data.get("response", ""))
            queue_size = _STREAM_QUEUE.qsize()
            logger.info(f"[POLL] #{poll_num} @ {elapsed:.1f}s | Response: {response_len} chars | Queue: {queue_size} items")

        # Detect timeouts
        first_token_received = len(streaming_data.get("response", "")) > 0
        time_since_start = current_time - streaming_data.get("start_time", current_time)
        
        if not first_token_received:
            timeout_seconds = STREAM_FIRST_TOKEN_TIMEOUT_SEC
            if time_since_start > timeout_seconds:
                queue_size = _STREAM_QUEUE.qsize()
                logger.error(f"[POLL] ❌ TIMEOUT: No first token after {time_since_start:.1f}s. Queue size: {queue_size}")
                error_msg = (
                    f"⏱️ Response timed out after {timeout_seconds}s (no tokens yet). "
                    f"Queue had {queue_size} items. "
                    f"Slow or free-tier APIs may need longer — set env LENSIGHT_STREAM_FIRST_TOKEN_TIMEOUT "
                    f"(seconds, min 30), e.g. 300."
                )
                
                chat_history_with_error = (chat_history or []) + [
                    {"role": "user", "content": streaming_data["request_data"].get("question", "")},
                    {"role": "assistant", "content": error_msg},
                ]
                
                from dashboard.layout import _chat_bubble
                message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history_with_error]
                
                return (
                    message_bubbles,
                    True,  # Disable interval
                    chat_history_with_error,
                    no_update,
                    None,  # Clear streaming data
                )

        # Check queue for incoming tokens/messages
        queue_items = 0
        while not _STREAM_QUEUE.empty():
            try:
                token_type, token_data = _STREAM_QUEUE.get_nowait()
                queue_items += 1
                
                if token_type == "token":
                    streaming_data["response"] += token_data
                    streaming_data["last_token_time"] = time.time()
                    
                    # Log first token arrival
                    if len(streaming_data["response"]) == len(token_data):
                        elapsed = time.time() - streaming_data.get("start_time", time.time())
                        logger.info(f"[POLL] ⚡ FIRST TOKEN arrived after {elapsed:.2f}s: '{token_data[:40]}...'")

                elif token_type == "done":
                    # Prefer full text from worker (survives multi-instance / empty local queue).
                    from_client = streaming_data.get("response", "") or ""
                    from_worker = (token_data or {}).get("assistant_text") or ""
                    final_response = from_worker if from_worker else from_client
                    chat_history_new = token_data.get("chat_history", chat_history or [])
                    conv_summary = token_data.get("conv_summary", "")
                    question = streaming_data["request_data"].get("question", "")

                    logger.info(
                        f"[POLL] ✅ Done signal received. Final response: {len(final_response)} chars "
                        f"(worker={len(from_worker)}, client={len(from_client)}), "
                        f"polls={streaming_data['poll_count']}"
                    )

                    chat_history_final = chat_history_new + [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": final_response},
                    ]

                    from dashboard.layout import _chat_bubble
                    message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history_final]

                    return (
                        message_bubbles,
                        True,  # Disable interval
                        chat_history_final,
                        conv_summary,
                        None,  # Clear streaming data
                    )

                elif token_type == "quota_exceeded":
                    logger.error("[POLL] 🚫 Quota exceeded error from worker")
                    error_msg = "🚫 API quota exceeded. Please try again later or upgrade your plan."
                    
                    chat_history_with_error = (chat_history or []) + [
                        {"role": "user", "content": streaming_data["request_data"].get("question", "")},
                        {"role": "assistant", "content": error_msg},
                    ]
                    
                    from dashboard.layout import _chat_bubble
                    message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history_with_error]
                    
                    return (
                        message_bubbles,
                        True,  # Disable interval
                        chat_history_with_error,
                        no_update,
                        None,  # Clear streaming data
                    )

                elif token_type == "error":
                    logger.error(f"[POLL] ❌ Error from worker: {token_data}")
                    error_msg = f"❌ Error: {token_data}"
                    
                    chat_history_with_error = (chat_history or []) + [
                        {"role": "user", "content": streaming_data["request_data"].get("question", "")},
                        {"role": "assistant", "content": error_msg},
                    ]
                    
                    from dashboard.layout import _chat_bubble
                    message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history_with_error]
                    
                    return (
                        message_bubbles,
                        True,  # Disable interval
                        chat_history_with_error,
                        no_update,
                        None,  # Clear streaming data
                    )

            except Exception as exc:
                logger.warning(f"[POLL] Queue error: {exc}")
                break

        if queue_items > 0:
            logger.debug(f"[POLL] Processed {queue_items} queue item(s), response now: {len(streaming_data.get('response', ''))} chars")

        # Continuous UI update while streaming
        from dashboard.layout import _chat_bubble, _loading_bubble
        
        chat_history = chat_history or []
        message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history]
        
        question = streaming_data["request_data"].get("question", "")
        message_bubbles.append(_chat_bubble("user", question))
        
        # Show partial response or loading indicator
        if streaming_data["response"]:
            message_bubbles.append(_chat_bubble("assistant", streaming_data["response"]))
        else:
            message_bubbles.append(_loading_bubble())

        return message_bubbles, no_update, no_update, no_update, streaming_data

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
        
        # Clear streaming state
        while not _STREAM_QUEUE.empty():
            try:
                _STREAM_QUEUE.get_nowait()
            except:
                pass
        
        analysis_file = DATA_PROCESSED_DIR / "analysis.json"
        if not analysis_file.exists():
            raise PreventUpdate
        with analysis_file.open(encoding="utf-8") as fh:
            data = json.load(fh)
        logger.info("Returning to dashboard from chat.")
        return build_layout(data), {"screen": "dashboard"}

    # ── 8. Sync app-state to screen tracker for refresh warning ──────────────
    # Updates window.onbeforeunload directly in the client browser
    app.clientside_callback(
        """
        function(app_state) {
            const screen = (app_state && app_state.screen) ? app_state.screen : 'upload';
            window.onbeforeunload = function(e) {
                if (screen === 'dashboard' || screen === 'processing' || screen === 'chat') {
                    const warningMessage = 'Refreshing will clear your current analysis session. You will need to upload your files again and analysis will be done again from start. Are you sure you want to continue?';
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