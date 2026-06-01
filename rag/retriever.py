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
        from backend.pipeline_runner import get_rag_store
        vs_instance = get_rag_store()
        self.vector_store = vs_instance.get_store() if vs_instance is not None else None
        if self.vector_store is None:
            logger.warning("No vector store available — RAG context will be empty.")

    def retrieve_context(self, query: str) -> str:
        """
        Retrieve the top-k most relevant text chunks for a query.
        Returns a single concatenated string of context.
        """
        if not self.vector_store:
            return ""

        logger.info("Retrieving top %d documents for query", config.RETRIEVAL_TOP_K)
        retrieved_docs = self.vector_store.similarity_search(
            query,
            k=config.RETRIEVAL_TOP_K
        )

        return "\n\n".join([doc.page_content for doc in retrieved_docs])
