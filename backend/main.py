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
    
    # 1. Load Financial Summary
    analysis_file = DATA_PROCESSED_DIR / "analysis.json"
    financial_summary = ""
    if analysis_file.exists():
        with open(analysis_file, "r") as f:
            data = json.load(f)
            financial_summary = data.get("llm_financial_summary", "")

    # 2. Retrieve RAG text (Wait to import slowly to avoid loading LLMs globally)
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
            # chat_grounded_stream is synchronous generator, we can iter over it,
            # but ideally it should be async. However, since we are doing SSE,
            # we can use Server-Sent Events structure: `data: chunk\n\n`.
            for chunk in orchestrator.chat_grounded_stream(
                question=req.question,
                company=company_name,
                financial_summary=financial_summary,
                rag_context=rag_context,
                conversation_summary=req.conversation_summary,
                rag_status=rag_status_raw,
            ):
                # Yield in SSE format
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                await asyncio.sleep(0) # Yield control back to event loop
        except Exception as e:
            logger.error(f"Chat streaming error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount Static Files (Frontend UI)
app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "static"), html=True), name="static")
