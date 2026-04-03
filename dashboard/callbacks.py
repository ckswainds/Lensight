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

    from constants import DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR
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

        if stage == Stage.DONE.value:
            # Pipeline finished — load analysis and switch to dashboard
            analysis_file = DATA_PROCESSED_DIR / "analysis.json"
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

        # Initialize streaming response store
        streaming_data = {
            "status": "streaming",
            "response": "",
            "request_data": request_data,
        }

        def _stream_worker():
            """Background thread to stream LLM response."""
            try:
                question = request_data.get("question")
                chat_history = request_data.get("chat_history", [])
                conv_summary = request_data.get("conv_summary", "")

                logger.info(f"[STREAM] Starting stream worker for question: {question[:60]}...")

                # Load analysis
                analysis_file = DATA_PROCESSED_DIR / "analysis.json"
                if not analysis_file.exists():
                    logger.error("[STREAM] Analysis file not found")
                    _STREAM_QUEUE.put(("error", "Analysis file not found"))
                    return

                with analysis_file.open(encoding="utf-8") as fh:
                    data = json.load(fh)

                company = data.get("company", "Unknown")
                
                # Use smart filtering to reduce token usage
                analyzer = get_analyzer()
                financial_summary, analysis_metadata = analyzer.process_query(question, data)
                
                logger.debug(
                    f"[STREAM] Smart filtering applied: {analysis_metadata['context_type']} "
                    f"({analysis_metadata['confidence']:.1%} confidence, "
                    f"categories: {', '.join(analysis_metadata['categories']) or 'none'})"
                )
                logger.debug(f"[STREAM] Loaded analysis for {company}")

                # Get RAG status
                from dashboard.pipeline_runner import get_rag_store, get_status, RAGStatus
                status = get_status()
                rag_status_raw = status.get("rag_status", RAGStatus.IDLE.value)
                
                # Map new granular RAG states to orchestrator states for compatibility
                rag_status_for_orchestrator = rag_status_raw
                if rag_status_raw in ("loading", "chunking", "embedding", "storing"):
                    rag_status_for_orchestrator = "indexing"  # Group intermediate states as "indexing"
                
                rag_context = ""
                rag_store_instance = get_rag_store()
                if rag_store_instance and rag_status_raw == RAGStatus.READY.value:
                    try:
                        from rag.retriever import RAGRetriever
                        retriever = RAGRetriever(rag_store_instance)
                        rag_context = retriever.retrieve_context(question)
                        logger.debug("[STREAM] RAG context retrieved successfully")
                    except Exception as exc:
                        logger.warning(f"[STREAM] RAG retrieval failed: {exc}")

                # Compress if needed
                conv_summary = conv_summary or ""
                if len(chat_history) > 10:
                    logger.info(f"[STREAM] Chat history has {len(chat_history)} messages, skipping compression to save quota")

                # Stream LLM response
                from llm.orchestrator import LLMOrchestrator
                orchestrator = LLMOrchestrator()
                logger.info("[STREAM] Starting LLM streaming...")

                token_count = 0
                for token in orchestrator.chat_grounded_stream(
                    question=question,
                    company=company,
                    financial_summary=financial_summary,
                    rag_context=rag_context,
                    conversation_summary=conv_summary,
                    rag_status=rag_status_for_orchestrator
                ):
                    _STREAM_QUEUE.put(("token", token))
                    token_count += 1

                logger.info(f"[STREAM] LLM streaming complete. Total tokens: {token_count}")
                _STREAM_QUEUE.put(("done", {"chat_history": chat_history, "conv_summary": conv_summary}))

            except Exception as exc:
                error_msg = str(exc)
                logger.error(f"[STREAM] Streaming error occurred: {error_msg}", exc_info=True)
                
                # Check if it's a quota exceeded error (429)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                    logger.error("[STREAM] QUOTA EXCEEDED: Gemini API free tier limit reached (20 requests/day)")
                    _STREAM_QUEUE.put(("quota_exceeded", None))
                else:
                    _STREAM_QUEUE.put(("error", error_msg))

        # Start background thread
        thread = threading.Thread(target=_stream_worker, daemon=True)
        thread.start()
        logger.info("[START_STREAM] Background streaming thread started, polling enabled")

        # Enable interval polling and return initial state
        return False, streaming_data

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

        # Collect ALL tokens from queue
        while not _STREAM_QUEUE.empty():
            try:
                token_type, token_data = _STREAM_QUEUE.get_nowait()

                if token_type == "token":
                    streaming_data["response"] += token_data
                    logger.debug(f"[POLL] Received token, response length: {len(streaming_data['response'])}")

                elif token_type == "done":
                    # Streaming complete - finalize
                    final_response = streaming_data["response"]
                    chat_history_new = token_data.get("chat_history", chat_history or [])
                    conv_summary = token_data.get("conv_summary", "")
                    question = streaming_data["request_data"].get("question", "")

                    logger.info(f"[POLL] Streaming complete. Final response length: {len(final_response)}")

                    # Save to history
                    chat_history_final = chat_history_new + [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": final_response},
                    ]

                    # Rebuild all messages
                    from dashboard.layout import _chat_bubble
                    message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history_final]

                    logger.info(f"[POLL] Chat history saved with {len(chat_history_final)} messages")
                    return (
                        message_bubbles,
                        True,  # Disable interval
                        chat_history_final,
                        conv_summary,
                        None,  # Clear streaming data
                    )

                elif token_type == "quota_exceeded":
                    # API quota limit exceeded
                    logger.error("[POLL] API quota exceeded - user needs to wait for reset or upgrade")
                    error_msg = "API quota exceeded. Please try again later."
                    
                    # Build messages with error
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
                    # Generic error occurred
                    logger.error(f"[POLL] Stream error: {token_data}")
                    error_msg = "An error occurred. Please try again."
                    
                    # Build messages with error
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
                logger.warning(f"[POLL] Queue get error: {exc}", exc_info=True)
                break

        # ALWAYS update UI while streaming - show partial response as tokens arrive
        from dashboard.layout import _chat_bubble, _loading_bubble
        
        # Rebuild messages with current partial response
        chat_history = chat_history or []
        message_bubbles = [_chat_bubble(m["role"], m["content"]) for m in chat_history]
        
        # Add user message from pending request
        question = streaming_data["request_data"].get("question", "")
        message_bubbles.append(_chat_bubble("user", question))
        
        # Add response - show loading if empty, otherwise show partial response
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

    logger.info("All callbacks registered.")