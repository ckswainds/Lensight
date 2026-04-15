from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import logging
import asyncio
from pydantic import BaseModel
from typing import Optional, List

from constants import (
    DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR,
    PROJECT_ROOT
)
from backend.pipeline_runner import start_pipeline, get_status, is_idle, flush_all_data

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error Classification Helper
# ---------------------------------------------------------------------------

def _classify_llm_error(e: Exception) -> str:
    """
    Convert raw LLM/API exceptions into professional, user-facing markdown messages.
    Inspects the error string for known patterns (quota, timeout, auth, etc.).
    """
    s = str(e)
    sl = s.lower()

    if '429' in s or 'resource_exhausted' in sl or 'quota' in sl or 'rate limit' in sl or 'rate_limit' in sl:
        return (
            "### ⚠️ API Limit Exceeded\n\n"
            "The AI service has reached its request limit for now. "
            "Please try again in a few moments — this usually resets very quickly.\n\n"
            "---\n\n"
            "💡 **Notice:** We use high-capacity models that may occasionally hit rate caps during peak periods. Thank you for your patience."
        )
    if '503' in s or 'service unavailable' in sl:
        return (
            "**AI Service Temporarily Unavailable**\n\n"
            "The AI service is experiencing a brief disruption. "
            "Please try again in a few seconds."
        )
    if 'timeout' in sl or 'timed out' in sl or 'deadline' in sl:
        return (
            "**Request Timed Out**\n\n"
            "The AI service took too long to respond. "
            "Please try again — this is usually temporary."
        )
    if 'connection' in sl or 'network' in sl or 'unreachable' in sl:
        return (
            "**Connection Error**\n\n"
            "Unable to reach the AI service. "
            "Please check your internet connection and try again."
        )
    if 'api_key' in sl or 'authentication' in sl or 'unauthorized' in sl or '401' in s or '403' in s:
        return (
            "**Authentication Error**\n\n"
            "There is a configuration issue with the AI service credentials. "
            "Please contact support."
        )
    return (
        "**Something Went Wrong**\n\n"
        "An unexpected error occurred while processing your request. "
        "Please try again in a moment."
    )

app = FastAPI(title="Lensight AI Backend")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str
    conversation_summary: str = ""
    chat_history: List[dict] = []

# -----------------------------------------------------------------------------
# Helper: Build financial summary string for LLM context
# -----------------------------------------------------------------------------
def _build_financial_summary(data: dict) -> str:
    """
    Converts analysis.json into a compact textual summary for the LLM chat prompt.
    Extracts latest values + trends for key ratios across all categories.
    """
    lines = []
    company = data.get("company", "Unknown")
    latest = data.get("latest_period", "")
    periods = data.get("periods", [])
    
    lines.append(f"Company: {company}")
    lines.append(f"Analysis Period: {periods[0] if periods else 'N/A'} to {latest}")
    lines.append(f"Overall Score: {data.get('summary_scores', {}).get('overall_score', 'N/A')}/5")
    lines.append("")

    # Category labels for display
    categories = {
        "profitability": "Profitability",
        "valuation": "Valuation",
        "leverage": "Leverage",
        "liquidity": "Liquidity",
        "efficiency": "Efficiency",
        "per_share": "Per Share",
    }

    for cat_key, cat_label in categories.items():
        cat_data = data.get(cat_key, {})
        if not cat_data:
            continue
        lines.append(f"## {cat_label}")
        for ratio_name, ratio_data in cat_data.items():
            if not isinstance(ratio_data, dict):
                continue
            latest_val = ratio_data.get("latest_value")
            latest_lbl = ratio_data.get("latest_label", "")
            trend = ratio_data.get("trend", "")
            display_name = ratio_name.replace("_", " ").title()
            val_str = f"{latest_val:.2f}" if latest_val is not None else "N/A"
            lines.append(f"  - {display_name}: {val_str} ({latest_lbl}) | Trend: {trend}")
        lines.append("")

    # Growth CAGRs
    growth = data.get("growth", {})
    if growth:
        lines.append("## Growth (CAGR)")
        for key, g in growth.items():
            if isinstance(g, dict):
                val = g.get("value")
                lbl = g.get("label", "")
                display = key.replace("_", " ").title()
                val_str = f"{val:.1f}%" if val is not None else "N/A"
                lines.append(f"  - {display}: {val_str} ({lbl})")
        lines.append("")

    # Include llm_financial_summary if it exists (could be pre-generated)
    llm_summary = data.get("llm_financial_summary", "")
    if llm_summary:
        lines.append("## AI Narrative Summary")
        lines.append(llm_summary)

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_files(
    excel_file: UploadFile = File(...),
    pdf_file: Optional[UploadFile] = File(None)
):
    """
    Accepts Excel + Optional PDF.
    Saves to /data/uploads/ and triggers the background pipeline.
    """
    if not is_idle():
        raise HTTPException(status_code=400, detail="Pipeline is currently running.")
    
    # 1. Flush old uploads manually first
    flush_all_data(DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR)
    
    # 2. Save Excel
    excel_path = DATA_UPLOADS_DIR / excel_file.filename
    with open(excel_path, "wb") as f:
        f.write(await excel_file.read())
        
    # 3. Save PDF if attached
    if pdf_file and pdf_file.filename:
        pdf_path = DATA_UPLOADS_DIR / pdf_file.filename
        with open(pdf_path, "wb") as f:
            f.write(await pdf_file.read())
            
    # 4. Start Pipeline
    success = start_pipeline(
        excel_filename=excel_file.filename,
        uploads_dir=DATA_UPLOADS_DIR,
        raw_dir=DATA_RAW_DIR,
        processed_dir=DATA_PROCESSED_DIR,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start pipeline.")
        
    return {"status": "started", "message": "Pipeline started successfully"}

@app.get("/api/status")
async def pipeline_status():
    """Returns the current pipeline status."""
    return get_status()

@app.get("/api/analysis")
async def get_analysis():
    """Returns the generated analysis.json if ready."""
    analysis_file = DATA_PROCESSED_DIR / "analysis.json"
    if not analysis_file.exists():
        raise HTTPException(status_code=404, detail="Analysis results not found.")
        
    with open(analysis_file, "r") as f:
        data = json.load(f)
    return data

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """
    Streams a response from the LLM based on RAG context and financial data.
    """
    st = get_status()
    rag_status_raw = st.get("rag_status", "idle")
    company_name = st.get("company", "Unknown Company")
    
    # 1. Load Financial Summary (build a rich text representation for the LLM)
    analysis_file = DATA_PROCESSED_DIR / "analysis.json"
    financial_summary = ""
    if analysis_file.exists():
        with open(analysis_file, "r") as f:
            data = json.load(f)
            financial_summary = _build_financial_summary(data)
            # Fallback company name from analysis if pipeline status doesn't have it
            if company_name == "Unknown Company":
                company_name = data.get("company", "Unknown Company")

    # 2. Retrieve RAG text (lazy import to avoid loading models globally)
    rag_context = ""
    try:
        if rag_status_raw == "ready":
            from rag.retriever import RAGRetriever
            rag_context = RAGRetriever().retrieve_context(req.question)
    except Exception as exc:
        logger.warning(f"RAG retrieval failed: {exc}")

    # 3. Stream Generator
    async def event_generator():
        from llm.orchestrator import LLMOrchestrator
        orchestrator = LLMOrchestrator()
        
        try:
            for chunk in orchestrator.chat_grounded_stream(
                question=req.question,
                company=company_name,
                financial_summary=financial_summary,
                rag_context=rag_context,
                conversation_summary=req.conversation_summary,
                rag_status=rag_status_raw,
            ):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"Chat streaming error: {e}", exc_info=True)
            friendly_msg = _classify_llm_error(e)
            yield f"data: {json.dumps({'error': friendly_msg})}\n\n"
            
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount Static Files (Frontend UI)
app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "static"), html=True), name="static")
