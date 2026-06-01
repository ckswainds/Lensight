"""Unstructured Loader: PDF/HTML → text chunks for RAG with parallel processing."""

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
        self.num_workers = 4

    def load_pdf(self, file_path: str) -> list:
        """
        Load a PDF and split it into text chunks.
        Uses parallel chunking for PDFs with more than 5 pages.
        """
        logger.info("Loading PDF: %s", file_path)
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        logger.info("PDF loaded: %d pages", len(docs))

        if len(docs) > 5:
            chunks = self._chunk_documents_parallel(docs)
        else:
            chunks = self.text_splitter.split_documents(docs)

        logger.info("Generated %d chunks from %d pages", len(chunks), len(docs))
        return chunks

    def _chunk_documents_parallel(self, documents: list) -> list:
        """
        Chunk documents in parallel using worker threads.
        Each worker processes a batch of pages independently.
        """
        if not documents:
            return []

        batch_size = max(1, len(documents) // self.num_workers)
        batches = [
            documents[i:i + batch_size]
            for i in range(0, len(documents), batch_size)
        ]

        all_chunks = []
        completed_batches = 0

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
                    logger.debug(
                        "Batch %d/%d chunked (%d chunks)",
                        completed_batches, len(batches), len(batch_chunks)
                    )
                except Exception as e:
                    logger.error("Error chunking batch %d: %s", batch_idx, e, exc_info=True)
                    raise

        logger.info("Parallel chunking complete: %d total chunks", len(all_chunks))
        return all_chunks

    def _chunk_batch(self, documents: list) -> list:
        """Chunk a single batch of documents (called by worker threads)."""
        return self.text_splitter.split_documents(documents)
