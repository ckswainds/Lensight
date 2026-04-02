"""Embedder: text → vector conversion via embedding model."""

from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from config import config

class Embedder:
    def __init__(self):
        # We load the cloud API embedding model (free cloud processing)
        self.embeddings = HuggingFaceInferenceAPIEmbeddings(
            api_key=config.HUGGINGFACEHUB_API_TOKEN,
            model_name=config.EMBEDDING_MODEL
        )
        
    def get_embeddings_model(self):
        return self.embeddings
