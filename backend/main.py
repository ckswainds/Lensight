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
from backend.pipeline_runner import start_pipeline, get_status, is_idle, flush_all_data, reset_status
from llm.prompt_builder import PromptBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _classify_llm_error(e: Exception) -> str:
    """Convert raw LLM exceptions into user-facing markdown messages."""
    s = str(e)
    sl = s.lower()

    if '429' in s or 'resource_exhausted' in sl or 'quota' in sl or 'rate limit' in sl or 'rate_limit' in sl:
        return (
            "<div class='err-header'>API Limit Exceeded</div>"
            "<p>The AI service has reached its request limit. Please try again in a few moments — this usually resets very quickly.</p>"
            "<hr/>"
            "<div class='err-footer'><b>Notice:</b> High-capacity models may hit rate caps during peak periods. Thank you for your patience.</div>"
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    conversation_summary: str = ""
    chat_history: List[dict] = []


@app.post("/api/upload")
async def upload_files(
    excel_file: UploadFile = File(...),
    pdf_file: Optional[UploadFile] = File(None)
):
    """Accept Excel + optional PDF, save to uploads/, and trigger the background pipeline."""
    if not is_idle():
        raise HTTPException(status_code=400, detail="Pipeline is currently running.")

    flush_all_data(DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR)

    excel_path = DATA_UPLOADS_DIR / excel_file.filename
    with open(excel_path, "wb") as f:
        f.write(await excel_file.read())

    if pdf_file and pdf_file.filename:
        pdf_path = DATA_UPLOADS_DIR / pdf_file.filename
        with open(pdf_path, "wb") as f:
            f.write(await pdf_file.read())

    success = start_pipeline(
        excel_filename=excel_file.filename,
        pdf_filename=pdf_file.filename if pdf_file and pdf_file.filename else None,
        uploads_dir=DATA_UPLOADS_DIR,
        raw_dir=DATA_RAW_DIR,
        processed_dir=DATA_PROCESSED_DIR,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to start pipeline.")

    return {"status": "started", "message": "Pipeline started successfully"}


@app.post("/api/reset")
async def reset_analysis():
    """Reset pipeline state and flush all data."""
    reset_status()
    flush_all_data(DATA_UPLOADS_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR)
    return {"status": "reset"}


@app.get("/api/status")
async def pipeline_status():
    """Return the current pipeline status."""
    return get_status()


@app.get("/api/analysis")
async def get_analysis():
    """Return analysis.json if ready."""
    analysis_file = DATA_PROCESSED_DIR / "analysis.json"
    if not analysis_file.exists():
        raise HTTPException(status_code=404, detail="Analysis results not found.")

    with open(analysis_file, "r") as f:
        data = json.load(f)
    return data


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Stream a grounded LLM response based on financial data and RAG context."""
    st = get_status()
    rag_status_raw = st.get("rag_status", "idle")
    company_name = st.get("company", "Unknown Company")

    analysis_file = DATA_PROCESSED_DIR / "analysis.json"
    financial_summary = ""
    if analysis_file.exists():
        with open(analysis_file, "r") as f:
            data = json.load(f)
            financial_summary = PromptBuilder.build_financial_summary_text(data)
            llm_summary = data.get("llm_financial_summary", "")
            if llm_summary:
                financial_summary += f"\n## AI Narrative Summary\n{llm_summary}\n"
            if company_name == "Unknown Company":
                company_name = data.get("company", "Unknown Company")

    rag_context = ""
    try:
        if rag_status_raw == "ready":
            from rag.retriever import RAGRetriever
            rag_context = RAGRetriever().retrieve_context(req.question)
    except Exception as exc:
        logger.warning("RAG retrieval failed: %s", exc)

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
            logger.error("Chat streaming error: %s", e, exc_info=True)
            friendly_msg = _classify_llm_error(e)
            yield f"data: {json.dumps({'error': friendly_msg})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "static"), html=True), name="static")
