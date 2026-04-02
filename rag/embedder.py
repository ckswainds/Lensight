"""Embedder: text → vector conversion via HuggingFace InferenceClient."""

from langchain_core.embeddings import Embeddings
from huggingface_hub import InferenceClient
from config import config


class HFInferenceEmbeddings(Embeddings):
    """Langchain-compatible embedder using the official huggingface_hub InferenceClient."""

    def __init__(self):
        self.client = InferenceClient(
            provider="hf-inference",
            api_key=config.HUGGINGFACEHUB_API_TOKEN
        )
        self.model = config.EMBEDDING_MODEL

    def _embed(self, texts: list) -> list:
        vectors = []
        for text in texts:
            result = self.client.feature_extraction(text, model=self.model)
            # result is a numpy array; convert to plain Python list
            vectors.append(result.tolist())
        return vectors

    def embed_documents(self, texts: list) -> list:
        return self._embed(texts)

    def embed_query(self, text: str) -> list:
        return self._embed([text])[0]


class Embedder:
    def __init__(self):
        self.embeddings = HFInferenceEmbeddings()

    def get_embeddings_model(self):
        return self.embeddings
