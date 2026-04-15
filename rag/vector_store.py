"""Vector Store: interface for ChromaDB with progress tracking."""

import logging
import shutil
from langchain_community.vectorstores import Chroma
from rag.embedder import Embedder
from constants import DATA_VECTOR_STORE_DIR

logger = logging.getLogger(__name__)

class LensightVectorStore:
    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        logger.info("[VECTOR_STORE] Initializing LensightVectorStore")
        self.embedder = Embedder(batch_size=batch_size, num_workers=num_workers)
        self.vector_store = None
        
        # Ensure fresh directory for new uploads
        if DATA_VECTOR_STORE_DIR.exists():
            shutil.rmtree(DATA_VECTOR_STORE_DIR)
        DATA_VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info("[VECTOR_STORE] LensightVectorStore initialized")

    def build_from_documents(self, documents: list, progress_callback=None):
        """
        Takes chunked Langchain documents and builds the Chroma index on disk.
        """
        logger.info(f"[VECTOR_STORE] Building vector store from {len(documents)} document(s)")
        
        if progress_callback:
            progress_callback(0, len(documents), "Initializing vector store...")
        
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embedder.get_embeddings_model(),
            persist_directory=str(DATA_VECTOR_STORE_DIR)
        )
        
        if progress_callback:
            progress_callback(len(documents), len(documents), "Vector store ready!")
        
        logger.info(f"[VECTOR_STORE] persistent Vector store built successfully")
        return self.vector_store
        
    def get_store(self):
        """Returns the built Chroma vector store."""
        if self.vector_store is None:
            logger.warning("[VECTOR_STORE] Vector store not yet built")
        return self.vector_store
