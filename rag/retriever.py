"""Retriever: semantic search over the vector store."""

import logging
from rag.vector_store import LensightVectorStore
from config import config

logger = logging.getLogger(__name__)

class RAGRetriever:
    def __init__(self, vector_store_instance: LensightVectorStore):
        logger.info("[RAG] Initializing RAGRetriever")
        self.vector_store = vector_store_instance.get_store()
        logger.info("[RAG] RAGRetriever initialized with LangSmith tracing enabled")

    def retrieve_context(self, query: str) -> str:
        """
        Retrieves the top k most relevant text chunks from the annual reports given a query.
        Returns a single concatenated string of context.
        Traced automatically by LangSmith for observability.
        """
        if not self.vector_store:
            logger.warning("[RAG] Vector store is not initialized, returning empty context")
            return ""

        logger.info(f"[RAG] Retrieving top {config.RETRIEVAL_TOP_K} documents for query")
        # Perform similarity search
        retrieved_docs = self.vector_store.similarity_search(
            query, 
            k=config.RETRIEVAL_TOP_K
        )
        
        logger.debug(f"[RAG] Retrieved {len(retrieved_docs)} documents")
        
        # Merge the document chunks into a contextual string
        context_string = "\n\n".join([doc.page_content for doc in retrieved_docs])
        logger.debug(f"[RAG] Context string generated, length: {len(context_string)} chars")
        return context_string
