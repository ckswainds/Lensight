"""Vector Store: ChromaDB interface with progress tracking."""

import logging
from langchain_community.vectorstores import Chroma
from rag.embedder import Embedder

logger = logging.getLogger(__name__)


class LensightVectorStore:
    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        self.embedder = Embedder(batch_size=batch_size, num_workers=num_workers)
        self.vector_store = None

    def build_from_documents(self, documents: list, progress_callback=None):
        """
        Build an in-memory Chroma index from chunked LangChain documents.

        Parameters
        ----------
        documents : list
            List of LangChain Document objects with page_content.
        progress_callback : callable, optional
            Called with (current, total, label) to report indexing progress.
        """
        logger.info("Building vector store from %d document(s)", len(documents))

        if progress_callback:
            progress_callback(0, len(documents), "Initializing vector store...")

        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embedder.get_embeddings_model()
        )

        if progress_callback:
            progress_callback(len(documents), len(documents), "Vector store ready!")

        logger.info("Vector store built with %d document(s)", len(documents))
        return self.vector_store

    def get_store(self):
        """Return the built Chroma vector store, or None if not yet built."""
        if self.vector_store is None:
            logger.warning("Vector store not yet built")
        return self.vector_store
