"""Vector Store: interface for ChromaDB with progress tracking."""

import logging
from langchain_community.vectorstores import Chroma
from rag.embedder import Embedder

logger = logging.getLogger(__name__)

class LensightVectorStore:
    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        logger.info("[VECTOR_STORE] Initializing LensightVectorStore")
        self.embedder = Embedder(batch_size=batch_size, num_workers=num_workers)
        self.vector_store = None
        logger.info("[VECTOR_STORE] LensightVectorStore initialized")

    def build_from_documents(self, documents: list, progress_callback=None):
        """
        Takes chunked Langchain documents and builds the Chroma index in-memory.
        
        Parameters
        ----------
        documents : list
            List of langchain Document objects with page_content
        progress_callback : callable, optional
            Function called with (current, total) to track progress
        """
        logger.info(f"[VECTOR_STORE] Building vector store from {len(documents)} document(s)")
        
        if progress_callback:
            progress_callback(0, len(documents), "Initializing vector store...")
        
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embedder.get_embeddings_model()
        )
        
        if progress_callback:
            progress_callback(len(documents), len(documents), "Vector store ready!")
        
        logger.info(f"[VECTOR_STORE] Vector store built successfully with {len(documents)} document(s)")
        return self.vector_store
        
    def get_store(self):
        """Returns the built Chroma vector store."""
        if self.vector_store is None:
            logger.warning("[VECTOR_STORE] Vector store not yet built")
        return self.vector_store
