"""Retriever: semantic search over the vector store."""

import logging
from langchain_community.vectorstores import Chroma
from rag.embedder import Embedder
from config import config
from constants import DATA_VECTOR_STORE_DIR

logger = logging.getLogger(__name__)

class RAGRetriever:
    def __init__(self, vector_store_instance=None):
        logger.info("[RAG] Initializing RAGRetriever")
        try:
            self.vector_store = Chroma(
                persist_directory=str(DATA_VECTOR_STORE_DIR),
                embedding_function=Embedder(batch_size=1, num_workers=1).get_embeddings_model()
            )
            logger.info("[RAG] RAGRetriever initialized with thread-safe disk DB")
        except Exception as e:
            logger.error(f"[RAG] Failed to connect to disk DB: {e}")
            self.vector_store = None

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
