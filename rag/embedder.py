"""Embedder: text -> vector conversion.

Auto-detects the correct backend from EMBEDDING_MODEL in .env:
  - Google models  : any name starting with 'models/' or containing 'text-embedding'
                     e.g. 'models/text-embedding-004'  -> GoogleGenerativeAIEmbeddings
  - HuggingFace    : everything else
                     e.g. 'sentence-transformers/all-MiniLM-L6-v2' -> HuggingFaceEmbeddings

Override via .env:  EMBEDDING_MODEL=models/text-embedding-004   (Google)
                    EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2  (HuggingFace)
"""

import logging
from config import config

logger = logging.getLogger(__name__)


def _is_google_model(model_name: str) -> bool:
    """Return True if the model name refers to a Google Generative AI embedding model."""
    name = model_name.lower()
    return name.startswith("models/") or "text-embedding" in name or "gemini" in name


class Embedder:
    """Provides the embedding model configured in .env.

    Automatically routes to Google Generative AI or HuggingFace depending on
    the value of EMBEDDING_MODEL.
    """

    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        model_name = config.EMBEDDING_MODEL
        logger.info("[EMBEDDER] Initializing embedder")
        logger.info("[EMBEDDER] EMBEDDING_MODEL = %s", model_name)

        if _is_google_model(model_name):
            self._init_google(model_name)
        else:
            self._init_huggingface(model_name)

    def _init_google(self, model_name: str) -> None:
        logger.info("[EMBEDDER] Backend: Google Generative AI")
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=model_name,
                google_api_key=config.GEMINI_API_KEY,
            )
            logger.info("[EMBEDDER] Google embedder ready")
        except Exception as e:
            logger.error("[EMBEDDER] Failed to initialize Google embeddings: %s", e)
            raise

    def _init_huggingface(self, model_name: str) -> None:
        logger.info("[EMBEDDER] Backend: HuggingFace (local)")
        try:
            try:
                from langchain_huggingface import HuggingFaceEmbeddings
            except ImportError:
                logger.debug("[EMBEDDER] langchain_huggingface not installed, falling back to langchain_community")
                from langchain_community.embeddings import HuggingFaceEmbeddings

            self.embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                # Prevent network calls if model is already cached locally
                model_kwargs={"local_files_only": False},   # try cache first, download if missing
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("[EMBEDDER] HuggingFace embedder ready")
        except Exception as e:
            logger.error("[EMBEDDER] Failed to initialize HuggingFace embeddings: %s", e)
            raise

    def get_embeddings_model(self):
        return self.embeddings
