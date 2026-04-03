"""Unstructured Loader: PDF/HTML  →  text chunks for RAG with parallel processing."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

class UnstructuredLoader:
    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 150):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )
        self.num_workers = 4  # Parallel workers for chunking

    def load_pdf(self, file_path: str) -> list:
        """
        Loads a PDF file and splits it into manageable text chunks.
        Uses parallel processing for faster chunking on multi-page PDFs.
        """
        logger.info(f"[LOADER] Loading PDF: {file_path}")
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        logger.info(f"[LOADER] PDF loaded with {len(docs)} pages")
        
        # Use parallel chunking for larger PDFs
        if len(docs) > 5:
            logger.info(f"[LOADER] Using parallel chunking for {len(docs)} pages ({self.num_workers} workers)")
            chunks = self._chunk_documents_parallel(docs)
        else:
            logger.info(f"[LOADER] Using sequential chunking for {len(docs)} pages")
            chunks = self.text_splitter.split_documents(docs)
        
        logger.info(f"[LOADER] Generated {len(chunks)} chunks from {len(docs)} pages")
        return chunks

    def _chunk_documents_parallel(self, documents: list) -> list:
        """
        Chunk documents in parallel using worker threads.
        Each worker processes a batch of pages and chunks them independently.
        """
        if not documents:
            return []
        
        logger.debug(f"[LOADER] Starting parallel chunking with {self.num_workers} workers")
        
        # Distribute pages to workers
        batch_size = max(1, len(documents) // self.num_workers)
        batches = [
            documents[i:i + batch_size] 
            for i in range(0, len(documents), batch_size)
        ]
        logger.debug(f"[LOADER] Split into {len(batches)} batches, ~{batch_size} pages per batch")
        
        all_chunks = []
        completed_batches = 0
        
        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {
                executor.submit(self._chunk_batch, batch): i 
                for i, batch in enumerate(batches)
            }
            
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    batch_chunks = future.result()
                    all_chunks.extend(batch_chunks)
                    completed_batches += 1
                    pct = (completed_batches * 100) // len(batches)
                    logger.debug(
                        f"[LOADER] Batch {completed_batches}/{len(batches)} chunked "
                        f"({pct}%, {len(batch_chunks)} chunks)"
                    )
                except Exception as e:
                    logger.error(
                        f"[LOADER] Error chunking batch {batch_idx}: {e}", 
                        exc_info=True
                    )
                    raise
        
        logger.info(f"[LOADER] Parallel chunking complete: {len(all_chunks)} total chunks")
        return all_chunks

    def _chunk_batch(self, documents: list) -> list:
        """Chunk a batch of documents (called by worker threads)."""
        logger.debug(f"[LOADER_WORKER] Chunking batch of {len(documents)} pages")
        chunks = self.text_splitter.split_documents(documents)
        logger.debug(f"[LOADER_WORKER] Batch produced {len(chunks)} chunks")
        return chunks
