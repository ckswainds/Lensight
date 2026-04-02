"""Embedder: text → vector conversion via embedding model."""

from langchain_community.embeddings import HuggingFaceEmbeddings
from config import config

class Embedder:
    def __init__(self):
        # We load a local embedding model via sentence-transformers (free and fast)
        self.embeddings = HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
    def get_embeddings_model(self):
        return self.embeddings
