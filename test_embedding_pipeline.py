"""
test_embedding_pipeline.py
==========================
End-to-end test for the PDF → Chunk → Embed → VectorStore → Retrieve pipeline.

Tests:
  1. PDF loading & chunking via UnstructuredLoader
  2. Embedding creation via HuggingFace (sentence-transformers/all-MiniLM-L6-v2)
  3. Vector store (Chroma) build from document chunks
  4. Semantic retrieval with sample queries

Run from the project root:
    python test_embedding_pipeline.py
"""

import sys
import os
import logging
import time
from pathlib import Path

# Force UTF-8 output on Windows to avoid UnicodeEncodeError in cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Make sure project root is on the path ─────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before importing config
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("embedding_test")

# ── Colour helpers (works on Windows 10+ / ANSI terminals) ────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}[PASS]{RESET}  {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET}  {msg}")
def info(msg): print(f"  {CYAN}[INFO]{RESET}  {msg}")
def section(title):
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}{YELLOW}  {title}{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def find_pdf() -> Path:
    """Locate the PDF file in data/uploads/."""
    uploads_dir = PROJECT_ROOT / "data" / "uploads"
    pdfs = list(uploads_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF found in {uploads_dir}")
    # pick the first one
    return pdfs[0]


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — PDF Discovery
# ══════════════════════════════════════════════════════════════════════════════

def test_pdf_discovery():
    section("TEST 1: PDF Discovery in uploads/")
    try:
        pdf_path = find_pdf()
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        ok(f"PDF found: {pdf_path.name}  ({size_mb:.2f} MB)")
        return pdf_path
    except FileNotFoundError as e:
        fail(str(e))
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — PDF Loading & Chunking
# ══════════════════════════════════════════════════════════════════════════════

def test_pdf_chunking(pdf_path: Path):
    section("TEST 2: PDF Loading & Chunking (UnstructuredLoader)")
    from ingestion.unstructured_loader import UnstructuredLoader

    loader = UnstructuredLoader(chunk_size=1500, chunk_overlap=150)
    info(f"Loading: {pdf_path}")

    t0 = time.time()
    chunks = loader.load_pdf(str(pdf_path))
    elapsed = time.time() - t0

    if not chunks:
        fail("No chunks produced — loader returned empty list")
        sys.exit(1)

    ok(f"Loaded {len(chunks)} chunks in {elapsed:.1f}s")
    info(f"Sample chunk preview (first 200 chars):")
    print(f"    {repr(chunks[0].page_content[:200])}")

    # Validate chunk metadata
    sample = chunks[0]
    assert hasattr(sample, "page_content"), "Chunk missing page_content"
    assert hasattr(sample, "metadata"),     "Chunk missing metadata"
    ok("Chunk structure validated (page_content + metadata present)")

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Embedding Model Initialization
# ══════════════════════════════════════════════════════════════════════════════

def test_embedding_model():
    section("TEST 3: Embedding Model Initialization (HuggingFace)")
    from config import config

    embedding_model_name = config.EMBEDDING_MODEL
    info(f"EMBEDDING_MODEL from config: {embedding_model_name}")

    # Decide which embedding backend to use
    if "text-embedding" in embedding_model_name or "gemini" in embedding_model_name.lower():
        # Google embedding model
        info("Detected Google embedding model -> using GoogleGenerativeAIEmbeddings")
        if not config.GEMINI_API_KEY:
            fail("GEMINI_API_KEY not set in .env")
            sys.exit(1)
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(
            model=embedding_model_name,
            google_api_key=config.GEMINI_API_KEY,
        )
        backend = "google"
    else:
        # HuggingFace / sentence-transformers model
        info("Detected HuggingFace model -> using HuggingFaceEmbeddings (local)")
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
        except ImportError:
            info("langchain_huggingface not found - falling back to langchain_community")
            from langchain_community.embeddings import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
        backend = "huggingface"

    ok(f"Embedding model ready  [backend={backend}]  model={embedding_model_name}")

    # Quick smoke test — embed two sentences
    info("Running smoke test: embedding 2 sentences …")
    t0 = time.time()
    test_sentences = [
        "What is the revenue of the company?",
        "Profit and loss account for the fiscal year.",
    ]
    vecs = embeddings.embed_documents(test_sentences)
    elapsed = time.time() - t0

    assert len(vecs) == 2,      f"Expected 2 embeddings, got {len(vecs)}"
    assert len(vecs[0]) > 0,   "Embedding vector is empty"
    ok(f"Smoke test passed — dim={len(vecs[0])}, time={elapsed:.2f}s")

    return embeddings


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Vector Store Build
# ══════════════════════════════════════════════════════════════════════════════

def test_vector_store_build(chunks: list, embeddings):
    section("TEST 4: Building ChromaDB Vector Store")
    from langchain_community.vectorstores import Chroma

    info(f"Indexing {len(chunks)} chunks into Chroma …")

    # Use a subset for speed if the PDF is very large
    MAX_CHUNKS_FOR_TEST = 200
    if len(chunks) > MAX_CHUNKS_FOR_TEST:
        info(f"Large PDF detected — using first {MAX_CHUNKS_FOR_TEST} chunks for speed")
        index_chunks = chunks[:MAX_CHUNKS_FOR_TEST]
    else:
        index_chunks = chunks

    t0 = time.time()
    vector_store = Chroma.from_documents(
        documents=index_chunks,
        embedding=embeddings,
    )
    elapsed = time.time() - t0

    ok(f"Vector store built with {len(index_chunks)} chunks in {elapsed:.1f}s")
    return vector_store


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — Semantic Retrieval
# ══════════════════════════════════════════════════════════════════════════════

def test_retrieval(vector_store, top_k: int = 3):
    section("TEST 5: Semantic Retrieval")
    from config import config

    k = config.RETRIEVAL_TOP_K if config.RETRIEVAL_TOP_K <= top_k else top_k

    # Generic financial queries likely to match content in the PDF
    queries = [
        "What is the total revenue of the company?",
        "Net profit after tax",
        "Balance sheet total assets",
        "Cash flow from operations",
        "Key business highlights and risks",
    ]

    all_passed = True
    for i, query in enumerate(queries, 1):
        info(f"Query {i}: {query!r}")
        try:
            results = vector_store.similarity_search(query, k=k)
            if results:
                ok(f"Retrieved {len(results)} doc(s) — top chunk ({len(results[0].page_content)} chars)")
                print(f"    {repr(results[0].page_content[:180])}")
            else:
                fail(f"No results returned for query: {query}")
                all_passed = False
        except Exception as e:
            fail(f"Retrieval error: {e}")
            all_passed = False

    return all_passed


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — Similarity Score Sanity Check
# ══════════════════════════════════════════════════════════════════════════════

def test_similarity_scores(vector_store):
    section("TEST 6: Similarity Scores Sanity Check")
    query = "annual report financial statements"
    info(f"Query: {query!r}")

    try:
        results_with_scores = vector_store.similarity_search_with_score(query, k=3)
        for doc, score in results_with_scores:
            # Chroma returns L2 distance (lower = more similar)
            ok(f"Score={score:.4f}  |  chunk preview: {repr(doc.page_content[:100])}")
        return True
    except Exception as e:
        fail(f"Similarity score test error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{'#'*60}{RESET}")
    print(f"{BOLD}  Lensight — Embedding Pipeline End-to-End Test{RESET}")
    print(f"{BOLD}{'#'*60}{RESET}")
    info(f"Project root : {PROJECT_ROOT}")
    info(f"Python       : {sys.version.split()[0]}")

    results = {}

    # 1. PDF discovery
    pdf_path = test_pdf_discovery()
    results["pdf_discovery"] = True

    # 2. PDF loading & chunking
    chunks = test_pdf_chunking(pdf_path)
    results["pdf_chunking"] = len(chunks) > 0

    # 3. Embedding model init
    embeddings = test_embedding_model()
    results["embedding_model"] = embeddings is not None

    # 4. Vector store build
    vector_store = test_vector_store_build(chunks, embeddings)
    results["vector_store_build"] = vector_store is not None

    # 5. Retrieval
    retrieval_ok = test_retrieval(vector_store)
    results["retrieval"] = retrieval_ok

    # 6. Similarity scores
    scores_ok = test_similarity_scores(vector_store)
    results["similarity_scores"] = scores_ok

    # ── Summary ───────────────────────────────────────────────────────────────
    section("SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, status in results.items():
        label = f"{GREEN}PASS{RESET}" if status else f"{RED}FAIL{RESET}"
        print(f"  [{label}]  {name}")

    print()
    if passed == total:
        print(f"{BOLD}{GREEN}All {total}/{total} tests passed! Embedding pipeline is working correctly.{RESET}\n")
    else:
        print(f"{BOLD}{RED}{passed}/{total} tests passed. See failures above.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
