"""Retriever: semantic search over the vector store."""

import logging
from config import config

logger = logging.getLogger(__name__)


class RAGRetriever:
    """
    Retrieves context chunks from the in-memory vector store built by the pipeline.
    Uses the global _rag_store from pipeline_runner — no constructor argument needed.
    """

    def __init__(self):
        logger.info("[RAG] Initializing RAGRetriever")
        from backend.pipeline_runner import get_rag_store
        vs_instance = get_rag_store()
        self.vector_store = vs_instance.get_store() if vs_instance is not None else None
        if self.vector_store is None:
            logger.warning("[RAG] No vector store available — RAG context will be empty.")
        else:
            logger.info("[RAG] RAGRetriever initialized successfully.")

    def retrieve_context(self, query: str) -> str:
        """
        Retrieves the top-k most relevant text chunks for a query.
        Returns a single concatenated string of context.
        """
        if not self.vector_store:
            logger.warning("[RAG] Vector store is not initialized, returning empty context")
            return ""

        logger.info(f"[RAG] Retrieving top {config.RETRIEVAL_TOP_K} documents for query")
        retrieved_docs = self.vector_store.similarity_search(
            query,
            k=config.RETRIEVAL_TOP_K
        )

        logger.debug(f"[RAG] Retrieved {len(retrieved_docs)} documents")
        context_string = "\n\n".join([doc.page_content for doc in retrieved_docs])
        logger.debug(f"[RAG] Context string generated, length: {len(context_string)} chars")
        return context_string
