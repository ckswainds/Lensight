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
from pathlib import Path

from dash import Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate

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

    from constants import DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR
    from dashboard.pipeline_runner import start_pipeline, get_status, Stage
    from dashboard.layout import (
        build_upload_screen,
        build_loading_screen,
        build_layout,
        build_error_layout,
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

    logger.info("All callbacks registered.")