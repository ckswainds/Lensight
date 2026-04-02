"""Vector Store: interface for FAISS."""

from langchain_community.vectorstores import FAISS
from rag.embedder import Embedder

class LensightVectorStore:
    def __init__(self):
        self.embedder = Embedder()
        self.vector_store = None

    def build_from_documents(self, documents: list):
        """
        Takes chunked Langchain documents and builds the FAISS index in-memory.
        """
        self.vector_store = FAISS.from_documents(
            documents=documents,
            embedding=self.embedder.get_embeddings_model()
        )
        return self.vector_store
        
    def get_store(self):
        """Returns the built FAISS vector store."""
        return self.vector_store
