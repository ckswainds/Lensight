"""Retriever: semantic search over the vector store."""

from rag.vector_store import LensightVectorStore
from config import config

class RAGRetriever:
    def __init__(self, vector_store_instance: LensightVectorStore):
        self.vector_store = vector_store_instance.get_store()

    def retrieve_context(self, query: str) -> str:
        """
        Retrieves the top k most relevant text chunks from the annual reports given a query.
        Returns a single concatenated string of context.
        """
        if not self.vector_store:
            return ""

        # Perform similarity search
        retrieved_docs = self.vector_store.similarity_search(
            query, 
            k=config.RETRIEVAL_TOP_K
        )
        
        # Merge the document chunks into a contextual string
        context_string = "\n\n".join([doc.page_content for doc in retrieved_docs])
        return context_string
